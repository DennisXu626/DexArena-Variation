"""Audit the actual sampler, the fixed examples and the yaw-specific cell maps on CPU."""
import hashlib
import importlib.util
import json
from types import SimpleNamespace
import numpy as np
from scipy.optimize import minimize
from scipy.spatial.transform import Rotation
import model as m
from measure import target_frames, scene_boxes, collision

path=m.ROOT/"tasks/cabinet_pouring/open_cabinet_workspace.py"
spec=importlib.util.spec_from_file_location("open_cabinet_workspace",path)
sampler=importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampler)


def streams():
    return SimpleNamespace(_batched_episode_rng=[np.random.RandomState(7),np.random.RandomState(23)])


def pose(row):
    xy=row[:2]
    yaw=int(row[2])
    return dict(root_xy_m=np.asarray(xy,dtype=float).tolist(),yaw_deg=yaw,
                closed_handle_xyz_m=np.r_[xy+m.handle_offset(yaw,0),m.Z].tolist())


def path_check(xy,yaw):
    offsets,rots,angles=target_frames(yaw)
    q=m.HOME.copy()
    groups,corners,allowed=m.collision_boxes()
    rows=[]
    for i,angle in enumerate(angles):
        goal=np.r_[xy+offsets[i],m.Z]
        ok,nxt=m.solve(goal,rots[i],q)
        p,rot,origins,links=m.fk(nxt)
        err_deg=np.rad2deg((Rotation.from_matrix(rot).inv()*Rotation.from_matrix(rots[i])).magnitude())
        jump=float(np.max(abs(nxt-q)))
        hinge=xy+m.HINGE@m.rz(yaw)[:2,:2].T
        hit=collision(origins,links,groups,corners,allowed,scene_boxes(),
                      np.array([np.eye(3),m.rz(yaw),m.rz(yaw-angle)]),
                      np.array([[0,0,0],np.r_[xy,0],np.r_[hinge,0]]))
        rows.append(dict(stage="pregrasp" if i==0 else f"{angle}deg",xyz_m=p.tolist(),
                         q_rad=nxt.tolist(),error_mm=float(np.linalg.norm(goal-p)*1000),
                         error_deg=float(err_deg),joint_delta_max_rad=jump,
                         blocked_box=bool(hit),accepted=bool(ok and not hit and (i==0 or jump<=.60))))
        if not rows[-1]["accepted"]:
            break
        q=nxt
    return rows


def free_orientation_radius():
    """Largest horizontal reach found at the measured grip height, ignoring obstacles."""
    def tip_and_jac(q):
        p,_,o,r=m.fk(q)
        return p,np.cross(r[:,:,2],p-o).T
    def objective(q):
        p,j=tip_and_jac(q)
        radial=p[:2]-m.MOUNT[:2]
        return -radial@radial, -2*radial@j[:2]
    height={"type":"eq","fun":lambda q:tip_and_jac(q)[0][2]-m.Z,
            "jac":lambda q:tip_and_jac(q)[1][2]}
    rng=np.random.RandomState(718)
    starts=[m.HOME,m.REFERENCE,*rng.uniform(m.limits[:,0],m.limits[:,1],(16,7))]
    solutions=[]
    for q in starts:
        opt=minimize(objective,q,jac=True,bounds=m.limits,constraints=[height],
                     method="SLSQP",options={"ftol":1e-11,"maxiter":160})
        if opt.success and abs(height["fun"](opt.x))<1e-6:
            solutions.append((float(np.sqrt(-opt.fun)),opt.x.tolist()))
    radius,angles=max(solutions)
    return dict(radius_m=radius,q_rad=angles,starts=len(starts),converged=len(solutions),
                top_agree_10um=sum(radius-r<.00001 for r,_ in solutions))


def main():
    regions,named=sampler.workspace()
    env=streams()
    poses=np.concatenate([sampler.resolve_workspace(env,[0,1],None) for _ in range(4096)])
    replay=streams()
    assert np.array_equal(poses,np.concatenate([sampler.resolve_workspace(replay,[0,1],None) for _ in range(4096)]))
    checks={}
    for target in (0,1):
        a,b=streams(),streams()
        sampler.resolve_workspace(a,[target],None)
        assert np.array_equal(sampler.resolve_workspace(a,[1-target],None),sampler.resolve_workspace(b,[1-target],None))
        checks[f"local_stream_env{1-target}"]=True
    fixed={}
    for name in named:
        row=sampler.resolve_workspace(env,[1],{"1":name})[0]
        fixed[name]=pose(row)
        path=path_check(row[:2],15)
        assert len(path)==10 and all(r["accepted"] for r in path)
        fixed[name]["ik_path"]=path
    metrics={}
    for yaw,rows in regions.items():
        data=np.load(m.EVIDENCE/f"screen_{yaw}.npz")
        cells=data["cells"]
        jj,ii=np.where(cells)
        assert sum(rows[:,2]-rows[:,1])==len(ii)
        for y,x0,x1 in rows:
            for x,edge_y in ((x0,y),(x0,y+1),(x1,y),(x1,y+1)):
                xy=np.array([x,edge_y],dtype=np.float32)/100
                assert sampler.contains(rows,xy), (yaw,xy)
        for j in range(cells.shape[0]):
            rebuilt=np.zeros(cells.shape[1],dtype=bool)
            for y,x0,x1 in rows[rows[:,0]==round(data["ry"][j]*100)]:
                rebuilt |= (data["rx"][:-1]+.005>=x0/100)&(data["rx"][:-1]+.005<=x1/100)
            assert np.array_equal(cells[j],rebuilt)
        group=poses[poses[:,2]==yaw]
        assert all(sampler.contains(rows,xy) for xy in group[:,:2])
        bounds=[int(rows[:,1].min()),int(rows[:,2].max()),int(rows[:,0].min()),int(rows[:,0].max()+1)]
        y0,x0,_=rows[0]
        req=lambda xy: {"0":{"cabinet_xy_m":xy,"yaw_deg":yaw}}
        sampler.resolve_workspace(env,[0],req([x0/100,y0/100]))
        try:
            sampler.resolve_workspace(env,[0],req([(bounds[0]-1)/100,y0/100]))
        except ValueError as e:
            assert "Outside" in str(e)
        else:
            raise AssertionError("Exterior point accepted")
        # Adjacent rejected grid nodes at the four bounding extrema. Codes
        # 0..6 denote pass, IK, jump, collision, table, green margin, base.
        neighbours={}
        grid=data["reasons"]
        for side,sel,dj,di in (("near",ii==ii.min(),0,-1),("far",ii==ii.max(),0,2),
                                ("right",jj==jj.min(),-1,0),("left",jj==jj.max(),2,0)):
            codes=grid[jj[sel]+dj,ii[sel]+di]
            neighbours[side]={int(k):int(n) for k,n in zip(*np.unique(codes,return_counts=True))}
        metrics[yaw]=dict(bounds_cm=bounds,spans_cm=[bounds[1]-bounds[0],bounds[3]-bounds[2]],
                          cells=len(ii),random_count=len(group),neighbour_codes=neighbours,
                          nominal_path=path_check(np.array([.14,.12]),yaw))
    zero=m.fk(m.REFERENCE)[0]
    ref_error=np.linalg.norm(zero-m.NOMINAL["handle_xyz"])
    assert ref_error<1.e-5
    upper=sum(np.linalg.norm(m.offsets[i]) for i in range(1,7))+np.linalg.norm(m.grip_local)
    result=dict(cpu_only=True,urdf_sha256=hashlib.sha256(m.URDF.read_bytes()).hexdigest(),
                registered="panda_sharpa_hand_left_angled_mobile_base",mount_m=m.MOUNT.tolist(),
                shoulder_m=m.SHOULDER.tolist(),handle_height_m=m.Z,reach_upper_3d_m=upper,
                loose_radius_bound_m=float(np.sqrt(upper**2-(m.Z-m.SHOULDER[2])**2)),
                free_orientation=free_orientation_radius(),
                fk_reference_error_mm=ref_error*1000,local_stream_checks=checks,
                seeded_replay_draws=len(poses),seed7_single_stream=pose(poses[0]),
                next_single_stream=pose(poses[2]),yaws=metrics,presets=fixed)
    (m.EVIDENCE/"CPU_RESULTS.json").write_text(json.dumps(result,indent=2)+"\n", encoding="utf-8", newline="\n")
    print("PASS", len(poses),"draws; four fixed paths; three boundary pairs; both local RNG directions")


if __name__=="__main__":
    main()
