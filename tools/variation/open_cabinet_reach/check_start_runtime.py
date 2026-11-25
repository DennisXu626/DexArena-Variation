"""Proposed two-env capture, immediately after reset and before any controller step."""
import argparse
import copy
from contextlib import closing
import json
from pathlib import Path

import gymnasium as gym
import numpy as np
import sapien
import torch
import tasks
from tasks.cabinet_pouring import start_clearance as sc
from tasks.cabinet_pouring.open_cabinet_workspace import workspace
from check_runtime import TASK, snapshot
from scipy.spatial import ConvexHull


def matrix(link,i):
    p=link.pose
    return sapien.Pose(p=p.p[i].cpu().numpy(),q=p.q[i].cpu().numpy()).to_transformation_matrix()


def cloud(link,i,world,root_inverse):
    component=link._objs[i].entity.find_component_by_type(sapien.physx.PhysxArticulationLinkComponent)
    points_by_shape=[]
    for shape in component.get_collision_shapes():
        tf=root_inverse @ world @ shape.local_pose.to_transformation_matrix()
        points=(shape.vertices*shape.scale)@tf[:3,:3].T+tf[:3,3]
        points_by_shape.append(points)
    return points_by_shape


def capture(e,i):
    cabinet=e._cabinets[i]; root=matrix(cabinet,0); inverse=np.linalg.inv(root)
    data=sc.geometry()
    parts=sorted({str(n).split(":")[0] for n in data["names"]})
    arm=e.agent.robot
    evidence={}; hand=[];cab=[];hn=[];cn=[]
    for name in parts:
        link=arm.links_map[name]; tf=matrix(link,i)
        evidence[name]=tf.tolist()
        for index,box in enumerate(cloud(link,i,tf,inverse)):
            hand.append(box);hn.append(f"{name}:{index}")
    for name in ("link_0","link_1"):
        link=cabinet.links_map[name];tf=matrix(link,0);evidence[name]=tf.tolist()
        for index,box in enumerate(cloud(link,0,tf,inverse)):
            cab.append(box);cn.append(f"{name}:{index}")
    h=np.asarray([[v.min(0),v.max(0)] for v in hand])
    c=np.asarray([[v.min(0),v.max(0)] for v in cab])
    delta=np.maximum(0,np.maximum(h[:,None,0]-c[:,1],c[:,0]-h[:,None,1]))
    distance=np.linalg.norm(delta,axis=2)*1000
    k,j=np.unravel_index(distance.argmin(),distance.shape)
    witnesses=[]
    for a,b in np.argwhere(distance==0):
        equations=ConvexHull(cab[b]).equations
        signed=(hand[a]@equations[:,:3].T+equations[:,3]).max(axis=1)
        vertex=int(signed.argmin())
        if signed[vertex]<-1e-7:
            witnesses.append(dict(pair=[hn[a],cn[b]],inside_mm=float(-1000*signed[vertex]),
                                  vertex_in_cabinet_frame_m=hand[a][vertex].tolist()))
    active_names=[j.name for j in arm.get_active_joints()]
    ids=[active_names.index(n) for n in e.agent.arm_joint_names]
    return dict(env=i,root=root.tolist(),door_angle=float(cabinet.qpos[0,0]),world_links=evidence,
                full_robot_qpos=arm.qpos[i].cpu().tolist(),arm_qpos=arm.qpos[i,ids].cpu().tolist(),
                hand_parts=hn,cabinet_parts=cn,hand_boxes_root_m=h.tolist(),cabinet_boxes_root_m=c.tolist(),
                bounds_gap_mm=float(distance[k,j]),pair=[hn[k],cn[j]],inside_vertices=witnesses)


def run(out):
    logs=[]
    def record(tag,info):
        logs.append(dict(case=tag,**info))
        out.write_text(json.dumps(logs,indent=1)+"\n")
    opts=dict(num_envs=2,sim_backend="physx_cuda",obs_mode="state",reconfiguration_freq=0)
    old=workspace()[1]
    for name,root in {**old,"native_nominal":[14,12]}.items():
        with closing(gym.make(TASK, cabinet_xy=(np.array(root)/100).tolist(),cabinet_init_xy_noise=0.,**opts)) as env:
            env.reset(seed=7)
            record("old_"+name,capture(env.unwrapped,0))
    with closing(gym.make(TASK,handle_workspace=True,**opts)) as env:
        e=env.unwrapped
        env.reset(seed=7)
        for i,name in [(0,"near"),(1,"far"),(0,"left"),(1,"right"),(0,None),(1,None)]:
            other=1-i;prior=snapshot(e.get_state_dict(),other)
            stream=copy.deepcopy(e._batched_episode_rng[other].get_state())
            def passive():
                state=snapshot(e.get_state_dict(),other)
                current=e._batched_episode_rng[other].get_state()
                return dict(passive_unchanged=prior==state,
                            passive_rng_unchanged=all(np.array_equal(a,b) for a,b in zip(stream,current)))
            opts={"env_idx":torch.tensor([i],device=e.device)}
            if name:opts["handle_placement"]={str(i):name}
            try:env.reset(options=opts)
            except ValueError as exc:
                isolation=passive()
                record(name or "random",dict(env=i,rejection=str(exc),**isolation))
                assert all(isolation.values())
                if name and repr(name) in str(exc) and "rejected for env" in str(exc):continue
                raise
            actual=capture(e,i)
            root=np.array(actual["root"])
            xy=root[:2,3];yaw=round(np.rad2deg(np.arctan2(root[1,0],root[0,0])))
            ok,detail=sc.evaluate_start(xy,yaw,np.array(actual["arm_qpos"]))
            actual.update(**passive(),approach_screen=detail)
            record(name or "random",actual)
            assert actual["passive_unchanged"] and actual["passive_rng_unchanged"] and abs(actual["door_angle"])<1e-4
            assert ok and actual["bounds_gap_mm"]>=sc.MIN_START_CLEARANCE_MM
            if name:assert yaw==15 and np.allclose(xy,np.array(workspace(start_clearance=True)[1][name])/100,atol=1e-5)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True)
    run(p.parse_args().output)
