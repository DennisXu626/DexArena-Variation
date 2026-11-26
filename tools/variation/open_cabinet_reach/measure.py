"""Generate the discrete CPU screen. No simulator or device initialization."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from numba import njit, prange, set_num_threads
from scipy.ndimage import distance_transform_edt, label, map_coordinates
from shapely.geometry import Polygon
from shapely.affinity import rotate, translate
from shapely.ops import unary_union
import model as m
from model import HOME

OUT = m.EVIDENCE
CATALOG = m.ROOT / "tasks/cabinet_pouring/open_cabinet_cells.json"


def extract(export):
    raw=json.loads(export.read_bytes())["tasks"]["PickBottle"]
    boxes=[]
    for link,group in raw["cabinet"].items():
        pose=np.array(group["pose_matrix"])
        for i,part in enumerate(group["pieces"]):
            vertices=np.array(part["vertices_local"])@pose[:3,:3].T+pose[:3,3]
            xy=(vertices[:,:2]-np.array(raw["cabinet_root_pose"][0][:2]))@m.rz(15)[:2,:2]
            if link=="link_0":
                xy=(xy-m.HINGE)@m.rz(np.rad2deg(raw["cabinet_qpos"][0][0]))[:2,:2].T+m.HINGE
            points=np.column_stack((xy,vertices[:,2]))
            boxes.append(dict(link=link,part=i,bounds=[points.min(axis=0).tolist(),points.max(axis=0).tolist()]))
    base_top=max((np.array(piece["vertices_local"])@np.array(group["pose_matrix"])[:3,:3].T+
                  np.array(group["pose_matrix"])[:3,3])[:,2].max()
                 for name,group in raw["robot"].items() if name.startswith("mobile_base_link")
                 for piece in group["pieces"])
    (OUT/"collision_bounds.json").write_text(json.dumps(dict(source_sha256=hashlib.sha256(export.read_bytes()).hexdigest(),boxes=boxes,base_top_m=base_top),indent=1)+"\n", encoding="utf-8", newline="\n")


def target_frames(yaw):
    # Preserve the measured thumb/index pinch line. A 4 degree roll about it
    # clears the conservative palm/handle box overlap at the nominal grasp.
    axis=(m.tips[1]-m.tips[0]) @ m.rest_pose(m.arm_names[-1])[:3,:3]
    roll=m.Rotation.from_rotvec(np.deg2rad(4)*axis/np.linalg.norm(axis)).as_matrix()
    grip=m.fk(m.REFERENCE)[1] @ roll
    angles=np.r_[0,0,np.arange(10,81,10)]
    offsets=np.array([m.handle_offset(yaw,a) for a in angles])
    offsets[0]-=.045*m.rz(yaw)[:2,0]
    rotations=np.stack([m.rz(yaw-15-a)@grip for a in angles])
    return offsets,rotations,angles


@njit(parallel=True)
def approach(xy,rot,normal):
    ok=np.zeros(len(xy),np.bool_)
    for k in prange(len(xy)):
        p=np.array([xy[k,0],xy[k,1],m.Z])
        a,q=m.solve(p-.045*normal,rot,m.HOME)
        if a:
            b,q2=m.solve(p,rot,q)
            ok[k]=b and np.max(np.abs(q2-q))<=.60
    return ok


@njit
def collision(origins,rots,groups,corners,allow_handle,boxes,axes,offset):
    for i in range(len(groups)):
        j=groups[i]
        world=corners[i]@rots[j].T + origins[j]
        # Broad phase in each obstacle's local axes: conservative OBB enclosure.
        for frame in range(3):
            pts=(world-offset[frame])@axes[frame]
            lo=np.array([pts[:,k].min() for k in range(3)])
            hi=np.array([pts[:,k].max() for k in range(3)])
            for b in range(len(boxes)):
                if int(boxes[b,0])!=frame or (boxes[b,1] and allow_handle[i]):
                    continue
                if np.all(hi>=boxes[b,2:5]) and np.all(lo<=boxes[b,5:8]):
                    return True
    return False


@njit(parallel=True)
def pull(roots,offsets,rotations,scene_axes,door_origin,boxes,groups,corners,allow_handle):
    reason=np.zeros(len(roots),np.int8)
    for k in prange(len(roots)):
        q=HOME.copy()
        root=np.array([roots[k,0],roots[k,1],0.])
        for s in range(len(offsets)):
            p=np.array([roots[k,0]+offsets[s,0],roots[k,1]+offsets[s,1],m.Z])
            ok,nxt=m.solve(p,rotations[s],q)
            if not ok:
                reason[k]=1
                break
            if s>0 and np.max(np.abs(nxt-q))>.60:
                reason[k]=2
                break
            q=nxt
            _,_,origins,rots=m.fk(q)
            trans=np.zeros((3,3))
            trans[1]=root
            trans[2]=root+door_origin[s]
            if collision(origins,rots,groups,corners,allow_handle,boxes,scene_axes[s],trans):
                reason[k]=3
                break
    return reason


def scene_boxes():
    parts=json.loads((OUT/"collision_bounds.json").read_bytes())["boxes"]
    boxes=[[0,0,*m.TABLE[0],-.06,*m.TABLE[1],0]]
    for part in parts:
        frame=1 if part["link"]=="link_1" else 2
        bounds=np.array(part["bounds"])
        if frame==2:
            bounds[:,:2]-=m.HINGE
        boxes.append([frame,int(frame==2 and part["part"]>=10),*bounds.ravel()])
    return np.array(boxes)


def grid(x,y):
    return np.stack(np.meshgrid(x,y),axis=-1)


def green_map(yaw):
    # Refine all coarse successes and a 3 cm band outside them. Outside the
    # front working half-plane is untested; the finite grid has a failed border.
    ticks_x=np.arange(-176,109)*m.STEP
    ticks_y=np.arange(-248,249)*m.STEP
    xy=grid(ticks_x,ticks_y)
    _,rots,_=target_frames(yaw)
    normal=m.rz(yaw)[:,0].copy()
    coarse=xy[::4,::4].copy()
    valid=approach(coarse.reshape(-1,2),rots[0],normal).reshape(coarse.shape[:2])
    iy,ix=np.indices(xy.shape[:2])/4
    mask=map_coordinates(valid.astype(float),[iy,ix],order=0,mode="nearest")>.5
    band=distance_transform_edt(~mask)<=6
    mask[band]=approach(xy[band],rots[0],normal)
    mask[[0,-1]]=False
    mask[:,[0,-1]]=False
    # Two half-diagonals cover the extent of both the accepted and failed
    # pixels: the complete accepted pixel clears the failed pixel by >=1 cm.
    inset=distance_transform_edt(mask)*m.STEP >= .01 + m.STEP*np.sqrt(2)
    return ticks_x,ticks_y,mask,inset


def measure(yaw):
    x,y,raw,green=green_map(yaw)
    print(yaw,"green",int(green.sum()),flush=True)
    offset,rots,angles=target_frames(yaw)
    body=np.vstack([m.BODY,m.DOOR,m.HARDWARE])@m.rz(yaw)[:2,:2].T
    rx=np.arange(-43,80)*.01
    ry=np.arange(-121,122)*.01
    roots=grid(rx,ry)
    inside=((roots+body.min(axis=0)>=m.TABLE[0])&(roots+body.max(axis=0)<=m.TABLE[1])).all(axis=2)
    ix=np.rint((roots[:,:,0]+offset[1,0]-x[0])/m.STEP).astype(int)
    iy=np.rint((roots[:,:,1]+offset[1,1]-y[0])/m.STEP).astype(int)
    mask=inside & (ix>=0)&(iy>=0)&(ix<len(x))&(iy<len(y))
    mask[mask]=green[iy[mask],ix[mask]]
    groups,corners,allowed=m.collision_boxes()
    frames=np.array([[np.eye(3),m.rz(yaw),m.rz(yaw-angle)] for angle in angles])
    hinge=np.r_[m.HINGE,0.]@m.rz(yaw).T
    reasons=pull(roots[mask],offset,rots,frames,np.tile(hinge,(len(angles),1)),scene_boxes(),groups,corners,allowed)
    eligible=mask.copy()
    eligible[mask]=reasons==0
    # The swept projection matters only if door and trolley heights can overlap.
    base=unary_union([Polygon(s["out"],s["holes"]) for s in m.PLAN["robot_base"]])
    sweep=rotate(unary_union([Polygon(s["out"],s["holes"]) for s in m.PLAN["sweep_local"]]),yaw,origin=(0,0))
    base_reject=0
    evidence=json.loads((OUT/"collision_bounds.json").read_bytes())
    door_low=min(b["bounds"][0][2] for b in evidence["boxes"] if b["link"]=="link_0")
    for j,i in zip(*np.where(eligible & (door_low<=evidence["base_top_m"]))):
        if base.intersects(translate(sweep,rx[i]*100,ry[j]*100)):
            eligible[j,i]=False
            base_reject+=1
    codes=np.full(mask.shape,4,np.int8)
    codes[inside]=5  # supported cabinet but closed-grasp reach margin missed
    codes[mask]=reasons
    codes[mask & ~eligible & (codes==0)]=6
    cells=eligible[1:,1:] & eligible[:-1,1:] & eligible[1:,:-1] & eligible[:-1,:-1]
    # A cell needs four passing vertices and a passing continuous-path check at its centre.
    jj,ii=np.where(cells)
    centres=roots[jj,ii]+.005
    indices=np.rint((centres+offset[1]-[x[0],y[0]])/m.STEP).astype(int)
    center_ok=green[indices[:,1],indices[:,0]] & (pull(centres,offset,rots,frames,np.tile(hinge,(len(angles),1)),scene_boxes(),groups,corners,allowed)==0)
    # Keep the entire translated cell in the buffered green raster. A 1 cm
    # square can intersect up to nine 5 mm pixels at this non-grid handle offset.
    for dx in (-.005,0.,.005):
        for dy in (-.005,0.,.005):
            index=np.rint((centres+offset[1]+[dx,dy]-[x[0],y[0]])/m.STEP).astype(int)
            center_ok &= green[index[:,1],index[:,0]]
    cells[jj,ii]=center_ok
    labels,count=label(cells)
    if not count:
        raise ValueError(f"No admissible cells at yaw {yaw}; {np.bincount(reasons)}")
    cells=labels==(1+np.argmax(np.bincount(labels.ravel())[1:]))
    rows=[]
    for j in np.flatnonzero(cells.any(axis=1)):
        spans=np.where(np.diff(np.r_[False,cells[j],False]))[0]
        for left,right in spans.reshape(-1,2):
            rows.append([round(ry[j]*100),round(rx[left]*100),round(rx[right]*100)])
    # Raw and buffered handle-space raster kept distinct from root-space cells.
    np.savez_compressed(OUT/f"screen_{yaw}.npz",x=x,y=y,raw=raw,green=green,rx=rx,ry=ry,eligible=eligible,cells=cells,reasons=codes)
    counts=dict(supported_nodes=int(inside.sum()),reach_nodes=len(reasons),ik_reject=int((reasons==1).sum()),
                jump_reject=int((reasons==2).sum()),collision_box_reject=int((reasons==3).sum()),
                base_sweep_reject=base_reject,cells=int(cells.sum()))
    print(yaw,counts,flush=True)
    return rows,counts


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--extract",type=Path,help="Archived Stage 2 runtime_geometry.json")
    args=p.parse_args()
    if args.extract:
        extract(args.extract)
    set_num_threads(4)
    rows,stats={},{}
    for angle in (10,15,20):
        rows[str(angle)],stats[str(angle)]=measure(angle)
    cells=np.load(OUT/"screen_15.npz")
    mask=cells["cells"]
    # Pick two axis-aligned comparisons through a common interior cell. Each
    # preset keeps a neighbouring cell on all four sides wherever practical.
    safe=distance_transform_edt(mask)>=2
    best=None
    for j,i in zip(*np.where(safe)):
        same_x=np.flatnonzero(safe[:,i])
        same_y=np.flatnonzero(safe[j])
        arms=[i-same_y.min(),same_y.max()-i,j-same_x.min(),same_x.max()-j]
        score=(min(arms),sum(arms),-abs(i-np.mean(same_y))-abs(j-np.mean(same_x)))
        if best is None or score>best[0]:
            best=(score,{"near":(j,same_y.min()),"far":(j,same_y.max()),
                         "left":(same_x.max(),i),"right":(same_x.min(),i)})
    presets={name:[round(cells["rx"][i]*100+.5,1),round(cells["ry"][j]*100+.5,1)]
             for name,(j,i) in best[1].items()}
    packed=json.dumps(dict(rows_cm=rows,presets_cm=presets),separators=(",",":"))
    CATALOG.write_text(packed+"\n", encoding="utf-8", newline="\n")
    (OUT/"screen_counts.json").write_text(json.dumps(stats,indent=2)+"\n", encoding="utf-8", newline="\n")
