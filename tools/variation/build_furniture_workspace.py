"""Generate Furniture workspace cells using native robot frames, held-object paths and bounded IK."""
import argparse
from itertools import product
import json
from pathlib import Path

import gymnasium as gym
import numpy as np
from scipy.spatial.transform import Rotation

import tasks
from tasks.furniture_assembly import furniture_assembly_lay_flat_panel as panel
from tasks.furniture_assembly import furniture_assembly_insert_rail as rail
from tasks.furniture_assembly import furniture_assembly_fasten_screw as screw
from tasks.furniture_assembly.workspace import TABLE, ROLES, world_layout
from tools.variation.check_cabinet_positions import setup_motion
from tools.variation.check_furniture_positions import table_geometry
from tools.variation.furniture_position_samples import extent_clearance

IK_LIMIT = .015
MAX_STEP = 1.45  # radians between consecutive modelled poses, after pre-approach
Z = np.array([0., 0., 1.])
OUT = Path("docs/variation/evidence/furniture_workspace")


def vector(angle):
    return np.array([np.cos(np.deg2rad(angle)), np.sin(np.deg2rad(angle)), 0.])


def xyz(xy, z):
    return np.column_stack((xy, np.broadcast_to(z, len(xy))))


def paths(kind, angles, coords, tilt):
    """Each node is a world-space pinch midpoint and a directed pinch line."""
    root = coords[:, :2]
    yaw = angles[0]
    x, y = vector(yaw), vector(yaw + 90)
    places = np.broadcast_to(panel.PLACE_CENTER, root.shape)
    if kind == "LayFlatPanel":
        grasp = xyz(root, panel.PANEL_IN_SLOT_Z + panel.GRASP_LOCAL_POS[1])
        # Move the held panel clear of the walls before translating above the landing zone.
        raised_z = panel.RACK_TOP_Z + panel.PANEL_HALF[1] + panel.GRASP_LOCAL_POS[1] + .014
        lifted = xyz(root, raised_z)
        target = xyz(places, raised_z)
        nodes = [(grasp + .05*Z, y), (grasp, y), (lifted, y), (target, y)]
        # Roll the vertical board flat above its destination. Model a release from above.
        for angle in (60, 30, 0):
            r = np.deg2rad(angle)
            g = panel.GRASP_LOCAL_POS[1]
            center = target - g*Z + g*(np.cos(r)*vector(90) + np.sin(r)*Z)
            # Upright local +Z points towards -Y; face-up maps it to +Z.
            normal = np.sin(r)*y - np.cos(r)*Z
            nodes.append((center, normal))
        nodes.append((xyz(places, panel.PANEL_HALF[2]+.045) + panel.GRASP_LOCAL_POS[1]*vector(90), -Z))
    elif kind == "InsertRail":
        ryaw = angles[1]
        relative = coords[:, 2:3]*x[:2] + coords[:, 3:4]*y[:2]
        start = xyz(root + relative, rail.RAIL_REST_Z + rail.RAIL_GRASP_LOCAL[2] + .008)
        pick_axis = vector(ryaw + 90)
        target = xyz(root, panel.PANEL_HALF[2] + rail.RAIL_SEATED_Z_LOCAL + rail.RAIL_GRASP_LOCAL[2] + .008)
        target += rail.RAIL_SEATED_X_LOCAL*x
        # Stage at the groove mouth with the aligned rail raised, lower and push along +X.
        mouth = target - (rail.RAIL_SEATED_X_LOCAL + panel.PANEL_HALF[0] - rail.RAIL_HALF[0])*x
        nodes = [(start+.055*Z, pick_axis), (start, pick_axis), (start+.075*Z, pick_axis),
                 (mouth+.075*Z, y), (mouth, y), (target, y), (target+.05*Z, y)]
    else:
        offset = np.asarray(rail.RAIL_SCREW_LOCAL_POSITIONS[0])
        center = xyz(root, panel.PANEL_HALF[2] + rail.RAIL_SEATED_Z_LOCAL + offset[2]
                     + screw.WING_SCREW_STEM_HEIGHT + screw.WING_HALF[2])
        center += (rail.RAIL_SEATED_X_LOCAL + offset[0])*x + offset[1]*y
        nodes = [(center+.055*Z, x)]
        nodes += [(center, vector(yaw-angle)) for angle in range(0, 91, 15)]
        nodes += [(center+.05*Z, vector(yaw-90))]
    dense = []
    for index, (midpoint, axis) in enumerate(nodes):
        if index:
            previous, before = nodes[index-1]
            splits = max(1, int(np.ceil(np.linalg.norm(midpoint-previous, axis=1).max()/.055)))
            for t in np.arange(1, splits)/splits:
                dense.append(((1-t)*previous+t*midpoint, (1-t)*before+t*axis))
        dense.append((midpoint, axis))
    # Tilting the same pinch line allows different approach postures. For horizontal
    # surfaces switch to a tangent component so the line remains well-defined.
    result = []
    for center, axis in dense:
        tangent = Z if abs(np.dot(axis, Z)) < .8 else vector(90)
        oriented = axis*np.cos(tilt) + tangent*np.sin(tilt)
        result.append((center, oriented / np.linalg.norm(oriented)))
    return result


def fk(q, chain):
    """Forward product of revolute joint transforms and its geometric Jacobian."""
    origins0, axes0, home, _, tips0 = chain
    n = len(q)
    rot = np.broadcast_to(np.eye(3), (n, 3, 3)).copy()
    trans = np.zeros((n, 3))
    joints, axes = [], []
    for j, (origin, axis) in enumerate(zip(origins0, axes0)):
        moved = rot @ origin + trans
        joints.append(moved)
        axes.append(rot @ axis)
        joint = Rotation.from_rotvec((q[:, j]-home[j])[:, None]*axis).as_matrix()
        rot = rot @ joint
        trans = moved - rot @ origin
    tips = (rot @ tips0.T).transpose(0, 2, 1) + trans[:, None]
    jac = np.cross(np.stack(axes, axis=1)[:, None], tips[:, :, None]-np.stack(joints, axis=1)[:, None])
    jac = jac.transpose(0, 1, 3, 2).reshape(n, 3*len(tips0), 7)
    return tips, jac, rot, trans


def hand_enclosures(e, index=0):
    """Enclose each native palm/wrist collision mesh separately at the seed pose."""
    boxes = []
    for link in e.agent.robot.links:
        if link.name != "panda_link7" and not link.name.endswith(("_hand_wrist", "_hand_C_MC")):
            continue
        link_pose = link.pose.raw_pose[index].cpu().numpy()
        orient = Rotation.from_quat(link_pose[[4,5,6,3]])
        for shape in link._bodies[0].collision_shapes:
            local = np.asarray(shape.vertices)*np.asarray(shape.scale)
            ends = list(zip(local.min(axis=0),local.max(axis=0)))
            corners = np.array(list(product(*ends)))
            p = shape.local_pose
            corners = Rotation.from_quat(p.q[[1,2,3,0]]).apply(corners)+p.p
            boxes.append(orient.apply(corners)+link_pose[:3])
    if not boxes:
        raise ValueError("no native wrist collision geometry")
    return np.array(boxes)


def hand_clearance(rot, trans, boxes, kind, xy, yaw):
    world = (rot @ boxes.reshape(-1,3).T).transpose(0,2,1) + trans[:,None]
    world = world.reshape(len(rot),len(boxes),8,3)
    lowest = world[:,:,:,2].min(axis=(1,2))
    if kind == "LayFlatPanel":
        half, top = panel.RACK_BASE_HALF, panel.RACK_TOP_Z
    else:
        half, top = panel.PANEL_HALF, panel.PANEL_HALF[2]*2
    # Conservative enclosure of the fixed rack or fixed flat panel.
    pos = world - xyz(xy,top/2)[:,None,None]
    axes = np.stack([vector(yaw), vector(yaw+90), Z])
    local = pos @ axes.T
    ext = np.array([half[0],half[1],top/2])
    separated = np.maximum(local.min(axis=2)-ext, -ext-local.max(axis=2)).max(axis=2)
    return np.minimum(lowest,separated.min(axis=1))


def screen(chain, nodes, boxes, kind, xy, yaw, trajectory=None):
    _, _, home, limits, tips = chain
    q = np.tile(home, (len(nodes[0][0]), 1))
    span = np.linalg.norm(tips[1]-tips[0])
    sign = 1 if np.dot(nodes[0][1], tips[1]-tips[0]) >= 0 else -1
    # A third landmark fixes the previously unconstrained roll about the pinch line.
    # Project the physical wrist offset into components parallel and normal to that line.
    wrist = boxes.mean(axis=(0,1))
    baseline = (tips[1]-tips[0])/span
    offset = wrist-tips.mean(axis=0)
    along = np.dot(offset,baseline)
    perpendicular = np.linalg.norm(offset-along*baseline)
    chain = (*chain[:4], np.vstack([tips,wrist]))
    worst = np.zeros(len(q))
    jump = np.zeros(len(q))
    wrist_gap = np.full(len(q), np.inf)
    for index, (midpoint, axis) in enumerate(nodes):
        axis = sign*axis
        # Tilt the back of the hand up and toward the robot side of the table.
        towards = np.array([-.8,0.,1.])
        towards -= axis*np.dot(axis,towards)
        towards /= np.linalg.norm(towards)
        relative = np.vstack([np.outer([-.5,.5],axis*span), along*axis+perpendicular*towards])
        goal = midpoint[:,None] + relative
        start = q.copy()
        for _ in range(30):
            positions, jac, _, _ = fk(q, chain)
            delta = (goal-positions).reshape(len(q), 9, 1)
            if np.max(np.abs(delta)) < .0004:
                break
            jt = jac.swapaxes(1, 2)
            # Damped, bounded differential IK. Suppress increments into active joint limits.
            step = np.linalg.solve(jt @ jac + np.eye(7)*.00012, jt @ delta)[:, :, 0]
            active = ((q <= limits[:, 0]+.0001) & (step < 0)) | ((q >= limits[:, 1]-.0001) & (step > 0))
            if np.any(active):
                jac = np.where(active[:, None], 0., jac)
                jt = jac.swapaxes(1, 2)
                step = np.linalg.solve(jt @ jac + np.eye(7)*.00012, jt @ delta)[:, :, 0]
            scale = np.maximum(1, np.max(np.abs(step), axis=1)/.21)
            q = np.clip(q+step/scale[:, None], *limits.T)
        positions, _, rot, trans = fk(q, chain)
        if trajectory is not None:
            trajectory.append(q.copy())
        worst = np.maximum(worst, np.linalg.norm(positions-goal, axis=2).max(axis=1))
        if index:
            jump = np.maximum(jump, np.max(np.abs(q-start), axis=1))
        wrist_gap = np.minimum(wrist_gap, hand_clearance(rot,trans,boxes,kind,xy,yaw))
        # Include the home-to-approach segment. Subdivide sampled joint-space sweeps.
        for t in np.arange(1, max(1,int(np.ceil(np.max(np.abs(q-start))/.18)))) * .18 / max(np.max(np.abs(q-start)),.18):
            _, _, rot, trans = fk(start+t*(q-start), chain)
            wrist_gap = np.minimum(wrist_gap, hand_clearance(rot,trans,boxes,kind,xy,yaw))
    return worst, jump, wrist_gap


def lattice(kind):
    if kind == "LayFlatPanel":
        return [(-10,), (0,), (10,)], list(product(range(-194,-61,12), range(184,269,12))), [.006,.006]
    if kind == "FastenScrew":
        return [(-7,), (0,), (7,)], list(product(range(-154,-105,8), range(-84,-35,8))), [.004,.004]
    # Centimetre-scale panel translations and relative rail lanes; independent axes
    # share only one accepted four-dimensional cell, never products of marginal masks.
    angles = list(product((-7,0,7), (-10,0,10)))
    rows = list(product((-154,-142,-130,-118,-106), (-84,-72,-60,-48,-36),
                        (-81,-54,-27,0,27,54,81), (-294,-267,-240,-213,-186,-159,-132)))
    return angles, rows, [.002,.002,.003,.003]


def geometry(kind, angles, coords, half, table):
    """The axis-aligned support and Y separation margins are affine per footprint edge."""
    from tools.variation.furniture_position_samples import rect
    margin = np.full(len(coords), np.inf)
    for signs in product((-1, 1), repeat=len(half)):
        corner = coords + np.array(half)*signs
        anchors = [corner[:,:2]]
        if kind == "InsertRail":
            rot = Rotation.from_euler("z",angles[0],degrees=True).as_matrix()[:2,:2]
            anchors.append(anchors[0]+corner[:,2:] @ rot.T)
        extents = {}
        for role,center,yaw in zip(ROLES[kind],anchors,angles):
            size = {"panel":panel.PANEL_HALF, "rack":panel.RACK_BASE_HALF, "rail":rail.RAIL_HALF}[role]
            extents[role] = np.abs(rect((0,0),size,yaw)).max(axis=1)
            margin = np.minimum(margin, (table[1]-np.abs(center-table[0])-extents[role]).min(axis=1))
        if kind == "LayFlatPanel":
            gap=anchors[0][:,1]-extents["rack"][1]-panel.PLACE_CENTER[1]-panel.PLACE_REGION_HALF_SIZE[1]
        else:
            gap=(panel.PLACE_REGION_HALF_SIZE-np.abs(anchors[0]-panel.PLACE_CENTER)-extents["panel"]).min(axis=1)
            if kind=="InsertRail":
                gap=np.minimum(gap, anchors[0][:,1]-extents["panel"][1]-anchors[1][:,1]-extents["rail"][1])
        margin=np.minimum(margin,gap)
    return margin


def build(kind):
    angles, grid, half = lattice(kind)
    coords = np.array(grid)/1000
    groups, audit = [], []
    with gym.make(f"FurnitureAssembly{kind}-Sharpa-v1", sim_backend="physx_cpu", obs_mode="state",
                  control_mode="pd_joint_pos", reconfiguration_freq=0) as env:
        e = env.unwrapped
        env.reset(seed=7, options={"position_layout":{"0":{}}})
        chain = setup_motion(e, 0)
        boxes = hand_enclosures(e)
        table = table_geometry(e)
    # For a rigid translation of a certified node, the same joint solution witnesses
    # a tip error at most its centre error plus the worst corner displacement.
    bound = sum(np.linalg.norm(half[n:n+2]) for n in range(0,len(half),2))
    for yaw in angles:
        margins = geometry(kind, yaw, coords, half, table)
        valid = margins > .0005
        selected = coords[valid]
        if not len(selected):
            continue
        errors = np.full(len(selected), np.inf)
        routes = np.zeros(len(selected))
        gaps = np.zeros(len(selected))
        for deg in (0, 25, -25):
            nodes = paths(kind, yaw, selected, np.deg2rad(deg))
            err, jump, gap = screen(chain, nodes, boxes, kind,selected[:,:2],yaw[0])
            eligible = (jump <= MAX_STEP) & (gap > bound+.001) & (err < errors)
            errors[eligible], routes[eligible], gaps[eligible] = err[eligible], deg, gap[eligible]
        keep = errors + bound <= IK_LIMIT
        points = selected[keep].tolist()
        print(kind,yaw,len(points),"/",len(coords), "best", float(errors.min()),flush=True)
        if points:
            groups.append(dict(yaw_deg=list(yaw), half_m=half, centers_m=points))
        audit.append(dict(yaw_deg=list(yaw), proposed=len(coords), geometry=int(valid.sum()), accepted=len(points),
                          displacement_bound_m=bound, route_tilt_deg=routes[keep].astype(int).tolist(),
                          max_tip_error_m=errors[keep].round(6).tolist(),
                          min_wrist_clearance_m=gaps[keep].round(6).tolist(),
                          geometry_margin_m=margins[valid][keep].round(6).tolist()))
    if not groups:
        raise ValueError(f"no screened regions for {kind}")
    # Fixed comparisons use the same angles; choose the richest single layer.
    group = max(groups, key=lambda g: (len(g["centers_m"]),-sum(map(abs,g["yaw_deg"]))))
    rows = np.array(group["centers_m"])
    nominal = {"LayFlatPanel":[-.13,.2], "InsertRail":[-.13,-.06,0.,-.21],
               "FastenScrew":[-.13,-.06]}[kind]
    middle = rows[np.argmin(np.linalg.norm(rows-nominal, axis=1))]
    dim = 3 if kind == "InsertRail" else 0
    aligned = rows[np.all(np.isclose(np.delete(rows,dim,1),np.delete(middle,dim)),axis=1)]
    near, far = aligned[aligned[:,dim].argmin()], aligned[aligned[:,dim].argmax()]
    if kind == "InsertRail":
        near, far = far, near  # Shorter vs longer transport from the panel's -Y side.
    presets = {name: world_layout(kind,group["yaw_deg"],point)
               for name,point in [("reference",middle),("near",near),("far",far)]}
    if np.allclose(aligned[:,dim],aligned[0,dim]):
        raise ValueError(f"no controlled contrast for {kind}")
    return dict(groups=groups,presets=presets),audit


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=TABLE)
    p.add_argument("--audit", type=Path, default=OUT/"screen.json")
    args=p.parse_args()
    result,history={},{}
    for task in ROLES:
        result[task],history[task]=build(task)
    args.output.write_text(json.dumps(dict(version=1,tasks=result),separators=(",",":"))+"\n",encoding="utf-8")
    args.audit.parent.mkdir(parents=True,exist_ok=True)
    args.audit.write_text(json.dumps(history,separators=(",",":"))+"\n",encoding="utf-8")
