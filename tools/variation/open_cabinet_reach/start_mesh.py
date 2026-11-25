"""Closed-start diagnostic. Compare actual URDF triangles to archived convex cabinet pieces."""
import hashlib
import itertools
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull
from numba import njit
import trimesh
import model as m

OUT = m.ROOT / "docs/variation/evidence/open_cabinet_clearance"
DATA = m.ROOT / "tasks/cabinet_pouring/open_cabinet_clearance.npz"
OLD = json.loads((m.EVIDENCE/"CPU_RESULTS.json").read_bytes())["presets"]
POSES = {k: v["root_xy_m"] for k, v in OLD.items()}
POSES["native_nominal"] = [.14,.12]


@lru_cache()
def hand():
    parts = {}
    for link in m.tree.findall("link"):
        name = link.get("name")
        if not (name.startswith("left_") or name in ("angle_bracket","panda_link7")):
            continue
        for i,coll in enumerate(link.findall("collision")):
            geo = coll.find("geometry/mesh")
            mesh = trimesh.load(m.URDF.parent / geo.get("filename"), process=False)
            scale = np.fromstring(geo.get("scale","1 1 1"),sep=" ")
            transform = np.linalg.inv(m.rest_pose("panda_link7")) @ m.rest_pose(name) @ m.origin(coll.find("origin"))
            tri = (mesh.triangles*scale) @ transform[:3,:3].T + transform[:3,3]
            local = np.array(list(itertools.product(*zip(mesh.bounds[0]*scale,mesh.bounds[1]*scale))))
            corners = local @ transform[:3,:3].T + transform[:3,3]
            parts[name+":"+str(i)] = (tri,corners)
    return parts


def cabinet(export):
    b=export.read_bytes()
    expected=json.loads((m.EVIDENCE/"collision_bounds.json").read_bytes())
    assert hashlib.sha256(b).hexdigest()==expected["source_sha256"]
    d=json.loads(b)["tasks"]["PickBottle"]
    parts={}
    for link,group in d["cabinet"].items():
        pose=np.array(group["pose_matrix"])
        for i,part in enumerate(group["pieces"]):
            v=np.array(part["vertices_local"]) @ pose[:3,:3].T+pose[:3,3]
            v[:,:2]=(v[:,:2]-d["cabinet_root_pose"][0][:2]) @ m.rz(15)[:2,:2]
            if link=="link_0":
                v[:,:2]=(v[:,:2]-m.HINGE) @ m.rz(np.rad2deg(d["cabinet_qpos"][0][0]))[:2,:2].T +m.HINGE
            h=ConvexHull(v)
            group_name="body" if link=="link_1" else ("door" if i<10 else "handle")
            parts[f"{group_name}:{i}"]=(v[h.simplices],h.equations)
    return parts


@njit
def segment(a,b,c,d):
    u,v,w=b-a,d-c,a-c
    A,B,C,D,E=u@u,u@v,v@v,u@w,v@w
    denom=A*C-B*B
    s=max(0.,min(1.,(B*E-C*D)/denom)) if denom>1e-20 else 0.
    t=(B*s+E)/C if C>1e-20 else 0.
    if t<0. or t>1.:
        t=max(0.,min(1.,t))
        s=max(0.,min(1.,(t*B-D)/A)) if A>1e-20 else 0.
    return a+s*u,c+t*v


@njit
def interior_projection(p,t):
    a,b,c=t
    u,v=b-a,c-a
    n=np.cross(u,v)
    nn=n@n
    if nn<1e-24: return False,a
    x=p-n*((p-a)@n)/nn
    k=x-a
    return np.cross(k,v)@n>=0 and np.cross(u,k)@n>=0 and np.cross(b-x,c-x)@n>=0,x


@njit
def narrow(a,b):
    best=1e9
    wa=np.zeros(3);wb=wa.copy()
    for t in a:
        for s in b:
            gap=0.
            for k in range(3):
                v=max(0.,t[:,k].min()-s[:,k].max(),s[:,k].min()-t[:,k].max())
                gap+=v*v
            if gap>=best: continue
            for i in range(3):
                ok,y=interior_projection(t[i],s)
                if ok and (t[i]-y)@(t[i]-y)<best:
                    wa,wb=t[i].copy(),y;best=(wa-wb)@(wa-wb)
                ok,x=interior_projection(s[i],t)
                if ok and (s[i]-x)@(s[i]-x)<best:
                    wa,wb=x,s[i].copy();best=(wa-wb)@(wa-wb)
                for j in range(3):
                    x,y=segment(t[i],t[(i+1)%3],s[j],s[(j+1)%3])
                    gap=(x-y)@(x-y)
                    if gap<best:wa,wb,best=x,y,gap
    return np.sqrt(best),wa,wb


def exact(root,yaw,pose,cab):
    """Positive surface distance; a negative witness is depth of a real hand vertex inside a solid."""
    angle=m.rz(yaw)
    hand_local={n:(tri @ pose[:3,:3].T+pose[:3,3]-np.r_[root,0])@angle for n,(tri,_) in hand().items()}
    pairs=[]
    for n,t in hand_local.items():
        lo,hi=t.reshape(-1,3).min(0),t.reshape(-1,3).max(0)
        for part,(s,planes) in cab.items():
            pts=s.reshape(-1,3)
            gap=np.linalg.norm(np.maximum(0,np.maximum(lo-pts.max(0),pts.min(0)-hi)))
            pairs.append((gap,n,part))
    best=np.inf
    for gap,n,part in sorted(pairs):
        if gap>max(best,0):break
        t=hand_local[n];s,planes=cab[part]
        if gap==0:
            # Clip each actual triangle against the cabinet convex piece; an interior
            # polygon centroid proves intersection even if all original vertices are outside.
            vertices=np.unique(t.reshape(-1,3),axis=0)
            depth=(vertices@planes[:,:3].T+planes[:,3]).max(1)
            i=depth.argmin()
            if depth[i]<-1e-8:
                val=depth[i];x=vertices[i];k=(planes[:,:3]@x+planes[:,3]).argmax();y=x-val*planes[k,:3]
            else:
                val=np.inf
                signed=t@planes[:,:3].T+planes[:,3]
                for tri in t[~(signed.min(1)>0).any(1)]:
                    poly=tri
                    for plane in planes:
                        ds=poly@plane[:3]+plane[3]
                        if ds.min()>0:poly=np.empty((0,3));break
                        if ds.max()<=0:continue
                        edge=[]
                        for k in range(len(poly)):
                            j=(k+1)%len(poly)
                            if ds[k]<=0:edge.append(poly[k])
                            if (ds[k]<0<ds[j]) or (ds[j]<0<ds[k]):
                                edge.append(poly[k]+(poly[j]-poly[k])*ds[k]/(ds[k]-ds[j]))
                        poly=np.array(edge)
                        if not len(poly):break
                    if len(poly):
                        x0=poly.mean(0);ds=planes[:,:3]@x0+planes[:,3];k=ds.argmax()
                        if ds[k]<val:val,x,y=ds[k],x0,x0-ds[k]*planes[k,:3]
        else:val=np.inf
        if val==np.inf and best>=0:val,x,y=narrow(t,s)
        if val<best:
            best=val
            row=dict(hand=n,cabinet=part,mesh_gap_mm=max(0.,val*1000),inside_witness_mm=max(0.,-val*1000),
                     hand_xyz_m=(x@angle.T+np.r_[root,0]).tolist(),cabinet_xyz_m=(y@angle.T+np.r_[root,0]).tolist())
    row["overlapping_AABB_pairs"]=int(sum(g==0 for g,_,_ in pairs))
    return row


def arm_pose(q):
    _,_,orig,rot=m.fk(q)
    p=np.eye(4);p[:3,:3]=rot[-1];p[:3,3]=orig[-1]
    return p


def enclosures(c):
    """Rest-frame robot and cabinet boxes used to build the reset lookup."""
    hand_names=list(hand());cab_names=list(c)
    boxes=np.array([[s.reshape(-1,3).min(0),s.reshape(-1,3).max(0)] for s,_ in c.values()])
    return dict(names=hand_names,obstacles=cab_names,corners=[v[1] for v in hand().values()],
                boxes=boxes,frames=m.frames,grip=m.grip_local,limits=m.limits)


if __name__=="__main__":
    import sys
    export=Path(sys.argv[1]);c=cabinet(export);OUT.mkdir(exist_ok=True)
    results={n:exact(xy,15,arm_pose(m.HOME),c) for n,xy in POSES.items()}
    print(results,flush=True)
    (OUT/"old_starts.json").write_text(json.dumps(dict(q=m.HOME.tolist(),root_xy_m=POSES,placements=results),indent=2)+"\n",encoding="utf8",newline="\n")
