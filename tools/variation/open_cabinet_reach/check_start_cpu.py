"""CPU reset harness. Execute the production qpos generator, reset hook and sampler on real geometry."""
import argparse
import ast
import copy
import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import torch
import model as m
from start_mesh import OUT, POSES, arm_pose, cabinet, exact, hand

pkg=m.ROOT/"tasks/cabinet_pouring"
package=types.ModuleType("cpu_cabinet")
package.__path__=[str(pkg)]
sys.modules[package.__name__]=package
sc=importlib.import_module("cpu_cabinet.start_clearance")
sampler=importlib.import_module("cpu_cabinet.open_cabinet_workspace")
layout=importlib.import_module("cpu_cabinet.position_layout")


def method(filename,name):
    path=pkg/filename
    tree=ast.parse(path.read_bytes())
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
    scope=dict(torch=torch,np=np,DEFAULT_ARM_INIT_QPOS=m.HOME,__package__="cpu_cabinet")
    exec(compile(ast.Module([node],[]),str(path),"exec"),scope)
    return scope[name]


class Reset:
    _initial_robot_qpos=method("cabinet_pouring_long.py","_initial_robot_qpos")
    _initialize_workspace=method("cabinet_pouring_long.py","_initialize_workspace")
    reset=method("cabinet_pouring_open_cabinet.py","_initialize_episode")
    device="cpu"
    _handle_workspace=True
    _robot_base_pose=m.BASE
    _family_appearance=_cabinet_appearance=None
    robot_init_qpos_noise=.02

    def __init__(self):
        self._batched_episode_rng=[np.random.RandomState(i) for i in (71,83)]
        self.table_scene=NS(initialize=lambda idx:None)
        self._set_work_table_pose=lambda:None
        self.roots=np.zeros((2,3))
        self.q=np.zeros((2,7))
        names=[m.joints[n].get("name") for n in m.arm_names]
        self.agent=NS(arm_joint_names=names,keyframes={"rest":NS(qpos=np.zeros(7))},
                      reset=self.apply_q,robot=NS(get_active_joints=lambda:[NS(name=n) for n in names],
                                                  set_root_pose=lambda p:None))

    def _reset_episode_buffers(self,idx):self.indices=idx.tolist()
    def apply_q(self,q):self.q[self.indices]=q.numpy()
    def _initialize_cabinet(self,idx,b,door_open,layout):
        assert not door_open
        self.roots[idx.tolist()]=layout[:,:3] if layout is not None else [.14,.12,15]

    def run(self,i,seed,item=None):
        torch.manual_seed(seed)
        options={} if item is None else {"handle_placement":{str(i):item}}
        self.reset(torch.tensor([i]),options)
        return self.roots[i].copy(),self.q[i].copy()


def details(pose,q):
    xy,yaw=pose[:2],pose[2]
    end=sc.pregrasp(sc.geometry(),xy,yaw)
    start,approach=sc.clearance(xy,yaw,q,end)
    def entry(pair):
        mm,(step,h,c)=pair
        return dict(mm=mm,interval=step,hand=str(sc.geometry()["names"][h]),cabinet=str(sc.geometry()["obstacles"][c]))
    return {"start":entry(start),"approach":entry(approach)}


def main(export):
    env=Reset()
    regions,presets=sampler.workspace(start_clearance=True)
    log=[];rejected=[];worst={};fixed={}
    def check(p,q,seed,case):
        gaps=details(p,q)
        for key,mn in [("start",sc.MIN_START_CLEARANCE_MM),("approach",sc.MIN_APPROACH_CLEARANCE_MM)]:
            gap=gaps[key]
            assert gap["mm"]>=mn
            if key not in worst or worst[key]["mm"]>gap["mm"]:
                worst[key]=dict(**gap,seed=seed,case=case,pose=p.tolist(),arm_q=q.tolist())
        return gaps
    for seed in range(128):
        for name in presets:
            try:p,q=env.run(0,seed,name)
            except ValueError as err:
                assert name in str(err) and "env 0" in str(err)
                rejected.append(dict(seed=seed,preset=name,error=str(err)))
                continue
            gaps=check(p,q,seed,name)
            entry=fixed.setdefault(name,dict(accepted=0,start=1e9,approach=1e9))
            entry["accepted"]+=1
            for k,g in gaps.items():
                if g["mm"]<entry[k]:
                    entry[k]=g["mm"];entry[k+"_seed"]=seed;entry[k+"_pair"]=[g["hand"],g["cabinet"]]
    seq=[]
    for repeat in range(2):
        env=Reset();sequence=[]
        for seed in range(192):
            i=seed%2;j=1-i
            before=(env.roots[j].copy(),env.q[j].copy(),copy.deepcopy(env._batched_episode_rng[j].get_state()))
            p,q=env.run(i,seed)
            assert sampler.contains(regions[int(p[2])],p[:2])
            assert np.array_equal(env.roots[j],before[0]) and np.array_equal(env.q[j],before[1])
            assert all(np.array_equal(a,b) for a,b in zip(env._batched_episode_rng[j].get_state(),before[2]))
            sequence.append(p.tolist())
            if repeat==0:check(p,q,seed,"random")
        seq.append(sequence)
    assert seq[0]==seq[1] and len(set(map(tuple,seq[0])))>180
    # A session gets seeded once. Let both the native arm and placement streams
    # advance naturally on subsequent local resets, then replay the full session.
    sessions = []
    for _ in range(2):
        env = Reset()
        torch.manual_seed(7)
        env._batched_episode_rng = [np.random.RandomState(s) for s in (7, 8)]
        session = []
        for i in [0, 1] * 16:
            env.reset(torch.tensor([i]), {})
            session.append((env.roots[i].tolist(), env.q[i].tolist()))
        sessions.append(session)
    assert sessions[0] == sessions[1]
    assert len({tuple(p) for p, q in sessions[0]}) == 32
    for yaw,rows in regions.items():
        y,x,_=rows[len(rows)//2]
        point=dict(cabinet_xy_m=[x/100,y/100],yaw_deg=yaw)
        for seed in (0,7,19,42):
            try:p,q=env.run(0,seed,point)
            except ValueError as err:
                log.append(dict(yaw=yaw,seed=seed,request=point,error=str(err)))
            else:
                log.append(dict(yaw=yaw,seed=seed,request=point,clearance=check(p,q,seed,"boundary")))
        assert any(r["yaw"]==yaw and "clearance" in r for r in log)
        try:env.run(0,7,dict(cabinet_xy_m=[-1.,-1.],yaw_deg=yaw))
        except ValueError as exc:assert "Outside" in str(exc)
        else:raise AssertionError("exterior accepted")
    # Exercise explicit failure for a real named pose under adverse noise.
    if not rejected:
        for seed in range(128,4096):
            try:env.run(0,seed,"near")
            except ValueError as exc:
                assert "'near'" in str(exc) and "env 0" in str(exc)
                rejected.append(dict(seed=seed,preset="near",error=str(exc),targeted=True));break
    assert rejected
    old=Reset();old._handle_workspace=False
    old.reset(torch.tensor([0]),{});native=old.roots[0].tolist()
    old.reset(torch.tensor([1]),{"position_layout":{"1":{"cabinet_xy_m":[.19,.17],"yaw_deg":20}}})
    assert np.allclose(old.roots[1],[.19,.17,20])
    c=cabinet(export)
    torch.manual_seed(7);q=old._initial_robot_qpos(1)[0].numpy().astype(float);pose=arm_pose(q)
    snapshots={}
    for name,xy in list(POSES.items())+[("new_"+k,np.array(v)/100) for k,v in presets.items()]:
        snapshots[name]=dict(root_xy_m=list(xy),yaw=15,door_angle=0,seed=7,mesh=exact(xy,15,pose,c))
    frames={name:(pose@np.linalg.inv(m.rest_pose("panda_link7"))@m.rest_pose(name)).tolist()
            for name in {n.split(":")[0] for n in hand()}}
    result=dict(method="CPU reconstruction at the first reset frame; no physics, action or glove input",
                sampled_arm_q=q.tolist(),link_world_frames=frames,seed7=snapshots,fixed=fixed,
                rejects=rejected,worst=worst,boundary=log,random_interiors=len(seq[0]),replay=True,
                local_directions=[0,1],native_control=native,consecutive_replayed_resets=len(sessions[0]),
                random_yaw_counts={str(yaw):sum(r[2]==yaw for r in seq[0]) for yaw in regions})
    (OUT/"cpu_audit.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf8",newline="\n")
    print(fixed,rejected[:3],worst,flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("export",type=Path)
    main(p.parse_args().export)
