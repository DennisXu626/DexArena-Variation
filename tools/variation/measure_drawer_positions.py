"""Derive centimetre-scale plan geometry from the frozen drawer asset and source."""
import argparse
import ast
import csv
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation
from shapely.affinity import rotate
from shapely.geometry import MultiPoint, box
from shapely.ops import nearest_points, unary_union

from plot_cabinet_positions import ring, rotation, square


def xy(vertices):
    return MultiPoint(np.asarray(vertices)[:, :2]).convex_hull


def rings(geometry):
    polys = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms
    return [{"out": list(p.exterior.coords), "holes": [list(h.coords) for h in p.interiors]}
            for p in polys if p.geom_type == "Polygon" and p.area > 1e-8]


def corners(half, center=(0, 0, 0)):
    return np.asarray(list(product(*[(-h, h) for h in half]))) + center


def vector(element, name):
    return list(map(float, element.get(name, "0 0 0").split())) if element is not None else [0, 0, 0]


def drawer_meshes(directory, manifest, scale):
    urdf = directory / "mobility.urdf"
    files = {}
    def checked(path):
        key = path.relative_to(directory).as_posix()
        data = path.read_bytes()
        digest = sha256(data).hexdigest()
        assert digest == manifest[key]["sha256"], key
        files[key] = digest
        return data
    robot = ET.fromstring(checked(urdf))
    joints = {j.find("child").get("link"): j for j in robot.findall("joint")}
    transforms = {"base": (np.eye(3), np.zeros(3))}
    def pose(link):
        if link not in transforms:
            joint = joints[link]
            parent_r, parent_p = pose(joint.find("parent").get("link"))
            origin = joint.find("origin")
            r = Rotation.from_euler("xyz", vector(origin,"rpy")).as_matrix()
            transforms[link] = parent_r @ r, parent_p + parent_r @ vector(origin,"xyz")
        return transforms[link]
    parts = {}
    for el in robot.findall("link"):
        name = el.get("name")
        r, p = pose(name)
        visual_names = {v.find("geometry/mesh").get("filename"): v.get("name") for v in el.findall("visual")}
        parts[name] = {}
        for collision in el.findall("collision"):
            mesh = collision.find("geometry/mesh")
            if mesh is not None:
                filename = mesh.get("filename")
                vertices = np.array([[float(x) for x in line.split()[1:4]]
                                     for line in checked(directory / filename).decode().splitlines()
                                     if line.startswith("v ")])
                key = visual_names[filename].split("-")[0] + "/" + Path(filename).stem
            else:
                vertices = corners(np.array(vector(collision.find("geometry/box"), "size")) / 2)
                key = collision.get("name")
            origin = collision.find("origin")
            local_r = Rotation.from_euler("xyz", vector(origin,"rpy")).as_matrix()
            local = vertices @ local_r.T + vector(origin,"xyz")
            parts[name][key] = (local @ r.T + p) * (scale * 100)
    axis = pose("link_2")[0] @ vector(joints["link_2"].find("axis"),"xyz")
    assert np.allclose(axis, [-1,0,0], atol=1e-9)
    return parts, files


def minimum_pair(charger_xy, socket_xy, parts, socket_half, charger_r, socket_r, yaw=90):
    shell = box(*(socket_xy - socket_half), *(socket_xy + socket_half))
    shell = rotate(shell, yaw, origin=socket_xy.tolist())
    pieces = [xy(vertices + charger_xy) for vertices in parts]
    a, b = min((nearest_points(piece, shell) for piece in pieces),
               key=lambda pair: pair[0].distance(pair[1]))
    a, b = np.array(a.coords[0]), np.array(b.coords[0])
    distance = np.linalg.norm(b-a)
    assert distance > charger_r + socket_r
    toward = (b-a)/distance
    return {"charger_xy": charger_xy + charger_r*toward, "socket_xy": socket_xy - socket_r*toward,
            "witness": [a + charger_r*toward, b - socket_r*toward],
            "gap_cm": distance - charger_r - socket_r, "socket_yaw_deg": yaw}


def measure(args):
    tree = ast.parse(args.task.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="DrawerPlugLongEnv")
    fields = {n.targets[0].id:n.value for n in cls.body
              if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
    def attr(name):
        return ast.literal_eval(fields[name])
    cabinet, handoff, socket = [100*np.asarray(attr(key)) for key in
                                 ("drawer_xy","charger_place_center_xy","socket_center_xy")]
    assert np.allclose(cabinet,[18,18]) and np.allclose(handoff,[-29,-61]) and np.allclose(socket,[-12.5,-38])
    runtime = json.loads(args.manifest.read_bytes())
    assets = runtime["asset_identity"]["legacy_object_files"]
    parts, hashes = drawer_meshes(args.asset, assets, attr("drawer_scale"))
    door = parts["link_2"]
    frame = unary_union([xy(v) for v in parts["link_0"].values()])
    static = unary_union([xy(v) for link in ("link_0","link_1","link_3") for v in parts[link].values()])
    closed = unary_union([xy(v) for v in door.values()])
    floor = door["drawer_bottom_collision"]
    floor_xy = (floor.min(0) + floor.max(0))[:2]/2
    nominal = floor_xy + [100*attr("charger_outer_offset_x"),0]
    front = np.vstack(list(door.values()))[:,0].min()
    handle_parts = [v for k,v in door.items() if k.startswith("handle/")]
    handle = np.vstack(handle_parts)
    far_handle = np.vstack([v for v in handle_parts if v[:,0].min() < front + .1])
    handle_xy = (far_handle.min(0) + far_handle.max(0))[:2]/2
    z_lift = .1 - min(v[:,2].min() for v in parts["link_0"].values())
    travel = 100*attr("drawer_success_travel")+4
    shift = np.array([-travel,0])
    body_half = 100*np.asarray(attr("charger_half"))
    blade_half = 100*np.asarray(attr("charger_prong_half"))
    slot_offset = 100*attr("socket_slot_offset_x")
    prong_z = -body_half[2]-blade_half[2]
    boxes = [corners(body_half), *(corners(blade_half,(x,0,prong_z)) for x in (-slot_offset,slot_offset))]
    q = attr("charger_initial_quat")
    charger = [Rotation.from_quat(q[1:]+q[:1]).apply(p)[:, :2] for p in boxes]
    radius = 100*attr("charger_place_radius")
    sample_r = .75*radius
    table_geometry = json.loads(args.table.read_bytes())
    table_bounds = np.asarray(table_geometry["table_xy_cm"])
    table_shape = box(*table_bounds[0],*table_bounds[1])
    support_limit_x = table_bounds[0,0] - min(p[:,0].min() for p in charger)
    shell_half = 50*attr("socket_side")
    nearest_by_yaw = [minimum_pair(handoff, socket, charger, shell_half, sample_r, 2, yaw)
                      for yaw in (85, 90, 95)]
    nearest = next(case for case in nearest_by_yaw if case["socket_yaw_deg"] == 90)
    socket_nominal = minimum_pair(handoff, socket, charger, shell_half, sample_r, 0)
    open_geometry = unary_union([xy(v[:,:2]+cabinet+shift) for v in door.values()])
    c_and_drawer = min((nearest_points(xy(p+handoff), open_geometry) for p in charger),
                        key=lambda pair: pair[0].distance(pair[1]))
    a,b = (np.array(p.coords[0]) for p in c_and_drawer)
    vector_to_drawer = (b-a)/np.linalg.norm(b-a)
    wall = unary_union([xy(v) for k,v in door.items() if k.startswith(("drawer_side/","drawer_back/","drawer_front/"))])
    local_points = [nominal+[x,y] for x,y in product((-1,0,1),(-2,0,2))]
    def wall_gap(center):
        return min(xy(p+center).distance(wall) for p in charger)
    top = next(v for name,v in parts["link_0"].items() if name.startswith("top_panel/"))
    roof_front_drawer_x = top[:,0].min()+travel
    front_panel = unary_union([xy(v) for k,v in door.items() if k.startswith("drawer_front/")])
    # Test the starting body footprint on the floor, separately from the forward-reaching prongs.
    def floor_gap(center):
        footprint = xy(charger[0]+center)
        return footprint.distance(xy(floor).boundary) if xy(floor).covers(footprint) else -1
    right = max(local_points, key=lambda p:(p[0],p[1]))
    extreme = []
    full_fixture = unary_union([static,closed])
    all_part_vertices = np.vstack([v for link in parts.values() for v in link.values()])
    for x,y,yaw in product((-5,5),(-5,5),(-5,5)):
        center=cabinet+[x,y]
        vertices = all_part_vertices[:,:2] @ rotation(yaw).T + center
        margin = min(*(vertices.min(0)-table_bounds[0]),*(table_bounds[1]-vertices.max(0)))
        open_vertices = np.vstack(list(door.values()))[:,:2]+shift
        open_vertices = open_vertices@rotation(yaw).T+center
        open_left_edge = open_vertices[:,0].min()-table_bounds[0,0]
        handle_open = (handle_xy+shift)@rotation(yaw).T+center
        extreme.append({"root_xy":center,"yaw_deg":yaw,"table_containment_cm":float(margin),
                        "open_projection_left_margin_cm":open_left_edge,
                        "open_handle_xy":handle_open, "closed_handle_xy":handle_xy@rotation(yaw).T+center,
                        "open_handle_planar_distance_from_base_origin_cm":float(np.linalg.norm(handle_open-[-87,0]))})
    worst = min(extreme,key=lambda e:e["table_containment_cm"])
    # Robot base outline is shared across the two task families at the same root.
    # This archived footprint provides scene context at named nominal base pose.
    out = {"units":"cm", "source_task_sha256":sha256(args.task.read_bytes()).hexdigest(),
           "asset_hashes_matched_128860":hashes,
           "table_xy_cm":table_bounds, "robot_base":table_geometry["robot_base"],
           "cabinet_xy":cabinet,"handoff_xy":handoff,"socket_xy":socket,
           "frame":rings(frame),"cabinet":rings(full_fixture),
           "middle":rings(closed),"middle_parts":{k:rings(xy(v)) for k,v in door.items()},
           "handle_xy":handle_xy,"handle":rings(xy(handle)), "floor":rings(xy(floor)),
           "front_panel":rings(front_panel),"walls":rings(wall),
           "roof_front_drawer_x_cm":roof_front_drawer_x,
           "travel_cm":travel,"drawer_charger_xy":nominal,"charger_shapes":[rings(xy(p)) for p in charger],
           "upright_half_xy":body_half[:2], "blade_half_xy":blade_half[:2],
           "socket_half":shell_half,"slot_half_xy":100*np.asarray(attr("socket_slot_half")),
           "slot_offset":slot_offset,"slot_depth_cm":100*(attr("socket_thickness")-attr("socket_floor_thickness")),
           "nearest_socket_new":nearest,"nearest_socket_by_yaw":nearest_by_yaw,"nearest_socket_nominal":socket_nominal,
           "handoff_drawer_limit":{"charger_xy":handoff+radius*vector_to_drawer,
                 "gap_cm":np.linalg.norm(b-a)-radius,"witness":[a+radius*vector_to_drawer,b],
                 "open_mid_min_z_cm":min(v[:,2].min() for v in door.values())+z_lift,
                 "charger_max_z_cm":2*body_half[1]+.1},
           "handoff_x_table_support_min":support_limit_x,
           "handoff_west_gaps_cm":{"pick_limit":handoff[0]-radius-support_limit_x,
                                    "insert_sample":handoff[0]-sample_r-support_limit_x},
           "handoff_r":radius,"handoff_insert_r":sample_r,
           "in_drawer_min_wall_gap_cm":min(map(wall_gap,local_points)),
           "in_drawer_min_floor_edge_cm":min(map(floor_gap,local_points)),
           "deep_positive_y":{"charger_xy":right,"wall_gap_cm":wall_gap(right),
                               "front_gap_cm":min(xy(p+right).distance(front_panel) for p in charger),
                               "charger_to_roof_front_xy_cm":roof_front_drawer_x-(right[0]+max(p[:,0].max() for p in charger))},
           "drawer_corner_screen":extreme,"worst_drawer_table":worst}
    return out


def points(g):
    result=[]
    def add(task, figure, index, request, kind="candidate"):
        row=len(result)
        result.append(dict(task="DrawerPlug"+task+"-Sharpa-v1",figure=figure,id=f"{figure}-{index}",
                           kind=kind,seed=810+row,env_idx=row%2,
                           request=json.dumps(request,separators=(",",":")),
                           actual_xyz_m="",actual_wxyz="",actual_drawer_open_m="",
                           initialization="pending",ik="pending",contact_N="",
                           actual_motion="",failure_reason=""))
    def meters(p):
        return np.round(np.asarray(p)/100,10).tolist()
    cab, slot, handoff, inside = (np.asarray(g[k]) for k in
                                 ("cabinet_xy","socket_xy","handoff_xy","drawer_charger_xy"))
    for task in ("OpenDrawer","PickCharger"):
        offsets = [(0,0),*[(x,y) for x,y in product((-5,0,5),repeat=2) if (x,y)!=(0,0)]]
        for i,(x,y) in enumerate(offsets):
            add(task,"F1",i,{"drawer_xy_m":meters(cab+[x,y]),"drawer_yaw_deg":0})
        for i,yaw in enumerate((0,-5,5)):
            add(task,"F2",i,{"drawer_xy_m":meters(cab),"drawer_yaw_deg":yaw})
    for i,(x,y) in enumerate([(0,0),*[(x,y) for x,y in product((-1,0,1),(-2,0,2)) if (x,y)!=(0,0)]]):
        add("PickCharger","F3",i,{"charger_drawer_local_xy_m":meters(inside+[x,y])})
    for i,p in enumerate(ring(handoff,g["handoff_r"])):
        add("PickCharger","F4",i,{"diagnostic_place_center_xy_m":meters(p)},
            "native_predicate_boundary" if i else "native_predicate_center")
    for i,p in enumerate(ring(handoff,g["handoff_insert_r"])):
        add("InsertPlug","F4",i,{"charger_table_xy_m":meters(p)},"retained_domain")
    for i,p in enumerate(ring(slot,2)):
        add("InsertPlug","F5",i,{"socket_xy_m":meters(p),"socket_yaw_deg":90})
    for i,yaw in enumerate((90,85,95)):
        add("InsertPlug","F6",i,{"socket_xy_m":meters(slot),"socket_yaw_deg":yaw})
    # Reserve one seed per pairwise extreme and per near-boundary invalid input.
    worst=g["worst_drawer_table"]
    farthest=max(g["drawer_corner_screen"],key=lambda e:np.linalg.norm(e["closed_handle_xy"]-[-87,0]))
    for task,case in [("OpenDrawer",farthest),("PickCharger",worst)]:
        add(task,"C",f"far-{task}",{"drawer_xy_m":meters(case["root_xy"]),"drawer_yaw_deg":case["yaw_deg"]},"combination")
    for suffix,y in [("plus",2),("minus",-2)]:
        add("PickCharger","C",f"deep-{suffix}",{"charger_drawer_local_xy_m":meters(inside+[1,y])},"combination")
    near=g["nearest_socket_new"]
    add("InsertPlug","C","near",{"socket_xy_m":meters(near["socket_xy"]),
          "charger_table_xy_m":meters(near["charger_xy"]),"socket_yaw_deg":90},"combination")
    add("OpenDrawer","R","xy",{"drawer_xy_m":[.231,.18]},"expected_reject")
    add("OpenDrawer","R","yaw",{"drawer_yaw_deg":6},"expected_reject")
    add("PickCharger","R","deep",{"charger_drawer_local_xy_m":meters(inside+[1.1,0])},"expected_reject")
    add("InsertPlug","R","xy",{"socket_xy_m":[-.125,-.359]},"expected_reject")
    add("InsertPlug","R","yaw",{"socket_yaw_deg":96},"expected_reject")
    for candidate in g["nearest_socket_by_yaw"]:
        angle = candidate["socket_yaw_deg"]
        if angle != 90:
            add("InsertPlug","C",f"near-{angle}",{"socket_xy_m":meters(candidate["socket_xy"]),
                "charger_table_xy_m":meters(candidate["charger_xy"]),"socket_yaw_deg":angle},"combination")
    # Make the rotated in-drawer case explicit in addition to the two named deep points.
    add("PickCharger","C","rotated-deep",{"drawer_xy_m":[.23,.23],"drawer_yaw_deg":-5,
        "charger_drawer_local_xy_m":meters(inside+[1,2])},"combination")
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ("task","asset","manifest","table","out"):
        parser.add_argument(arg,type=Path)
    args=parser.parse_args()
    data=measure(args)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"GEOMETRY.json").write_text(json.dumps(data,indent=2,default=lambda obj:obj.tolist())+"\n",encoding="utf-8")
    rows=points(data)
    with (args.out/"SAMPLES.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0],lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} requests; {len(data['asset_hashes_matched_128860'])} URDF/OBJ hashes matched")
