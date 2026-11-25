"""Exercise Furniture workspace placement using registered CPU or two-scene CUDA tasks."""
import argparse
from collections import Counter
import copy
import csv
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

import gymnasium as gym
import numpy as np
import sapien
import torch

from tasks.furniture_assembly.workspace import ROLES, TABLE, draw, fixed_layout, workspace, world_layout
from tools.variation.build_furniture_workspace import hand_enclosures, paths, screen, setup_motion
from tools.variation.check_furniture_positions import (
    WING_HALF, WING_SCREW_STEM_HEIGHT, env_digest, measure, pose, reach, release_probe,
    robot_pose, rotation, short_attempt, state, table_geometry,
)
from tools.variation.furniture_position_samples import CENTERS, cases
from tasks.furniture_assembly.position_layout import XY_OFFSETS_M, YAW_DEGREES


def digest(e, i):
    return dict(scene=env_digest(state(e), i), stream=e._workspace_stream.get(i),
                record=e.workspace_records.get(i), controller=env_digest(e.agent.controller.get_state(),i))


def operating_point(e, kind, i):
    if kind == "LayFlatPanel":
        return e.grasp_position[i].cpu().numpy()
    if kind == "InsertRail":
        return e.rail_grasp_position[i].cpu().numpy()
    wing=pose(e.screw_head,i)
    return wing[:3]+rotation(wing).apply([0.,0.,WING_SCREW_STEM_HEIGHT+WING_HALF[2]])


def candidates(kind):
    _, groups, presets = workspace(kind)
    for name, layout in presets.items():
        yield name, name, layout, False
    for angles, centers, half in groups:
        # Exact exterior faces (extrema in every task coordinate), a corner and a held-out interior.
        for j in range(len(half)):
            for sign in (-1,1):
                p = centers[(sign*centers[:,j]).argmax()].copy()
                p[j] += sign*half[j]
                key = f"yaw{'_'.join(map(str,angles))}-axis{j}-{sign:+}"
                layout = world_layout(kind,angles,p)
                yield key, layout, layout, False
                if j == 0:
                    p[j] += sign*.00025
                    bad = world_layout(kind,angles,p)
                    yield key+"-outside",bad,bad,True
        for name, fraction in (("corner",1),("interior",-.317)):
            p = centers[len(centers)//2]+fraction*half
            layout = world_layout(kind,angles,p)
            yield f"{name}-{angles}",layout,layout,False
    if kind == "InsertRail":
        angles, centers, half = groups[len(groups)//2]
        p = centers[0].copy()
        p[2] += 2.5*half[2]
        bad = world_layout(kind,angles,p)
        yield "interior-hole",bad,bad,True


def summary_native(e, kind):
    return dict(root={r:pose(getattr(e,r),0).tolist() for r in ROLES[kind]},
                robot=[v.tolist() for v in robot_pose(e,0)],operation=operating_point(e,kind,0).tolist())


def legacy_reference(kind,rng):
    result={}
    for role in ROLES[kind]:
        delta=[rng.uniform(lo,hi) for lo,hi in XY_OFFSETS_M[role]]
        result[role+"_xy_m"]=(np.asarray(CENTERS[role])+delta).tolist()
        result[role+"_yaw_deg"]=int(rng.choice(YAW_DEGREES[role]))
    return result


def test_task(kind,backend,n,rows):
    make = dict(num_envs=n,sim_backend=backend,obs_mode="state",control_mode="pd_joint_pos",reconfiguration_freq=0)
    task = f"FurnitureAssembly{kind}-Sharpa-v1"
    samples, samples_ms = {}, {}
    seeded_native = {}
    with gym.make(task,**make) as baseline:
        for i in range(8):
            t=time.perf_counter()
            baseline.reset(seed=501+i)
            samples_ms.setdefault("native",[]).append((time.perf_counter()-t)*1000)
            v=summary_native(baseline.unwrapped,kind)
            samples.setdefault("native",[]).append(v["operation"])
            seeded_native[i]=v["robot"]
    with gym.make(task,position_workspace=True,**make) as env:
        e=env.unwrapped
        for i in range(8):
            seed=501+i
            for mode in ("legacy","workspace"):
                request=legacy_reference(kind,np.random.default_rng(seed))
                opts=dict(position_layout={str(j):request for j in range(n)}) if mode=="legacy" else {}
                t=time.perf_counter()
                env.reset(seed=seed,options=opts)
                samples_ms.setdefault(mode,[]).append((time.perf_counter()-t)*1000)
                v=summary_native(e,kind)
                assert v["robot"]==seeded_native[i],(kind,mode,"robot seed sequence")
                samples.setdefault(mode,[]).append(v["operation"])
        # Each fixed request leaves the next random result unchanged.
        env.reset(seed=991)
        saved=copy.deepcopy(e.workspace_records)
        env.reset()
        next_draw=copy.deepcopy(e.workspace_records)
        env.reset(seed=991)
        assert e.workspace_records==saved
        env.reset(options={"workspace_placement":{str(i):"reference" for i in range(n)}})
        env.reset()
        assert e.workspace_records==next_draw
        # Old explicit nominal and replayable actual state.
        env.reset(seed=707,options={"position_layout":{str(i):{} for i in range(n)}})
        assert not e.workspace_records
        table=table_geometry(e)
        assert all(measure(e,kind,0,{},table)["checks"].values())
        snapshot=copy.deepcopy(e.get_state_dict())
        streams=copy.deepcopy(e._workspace_stream)
        env.reset(options={"reset_to_env_states":{"env_states":snapshot}})
        assert streams==e._workspace_stream
        if n==2:
            env.reset(options={"env_idx":torch.tensor([1,0],device=e.device),
                               "workspace_placement":{"0":"near","1":"far"}})
            for j,label in enumerate(("near","far")):
                assert all(measure(e,kind,j,fixed_layout(kind,label),table)["checks"].values())
            before=copy.deepcopy([digest(e,j) for j in range(n)])
            try:
                env.reset(options={"workspace_placement":{"0":"near","1":"bad"}})
            except ValueError:
                assert [digest(e,j) for j in range(n)]==before
            else:
                raise AssertionError("invalid second row accepted")
            for j in (0,1):
                other=copy.deepcopy(digest(e,1-j))
                env.reset(options={"env_idx":torch.tensor([j],device=e.device)})
                assert other==digest(e,1-j)
        for k,(name,request,layout,negative) in enumerate(candidates(kind)):
            i=k%n
            seed=1300+k
            env.reset(seed=seed)
            checkpoint=copy.deepcopy([digest(e,j) for j in range(n)])
            opts={"workspace_placement":{str(i):request}}
            if n==2:
                opts["env_idx"]=torch.tensor([i],device=e.device)
            serial_options=dict(opts,env_idx=[i]) if n==2 else opts
            row=dict(task=task,id=name,seed=seed,env_idx=i,make=dict(make,position_workspace=True),
                     options=serial_options,expected="reject" if negative else "accept")
            try:
                env.reset(options=opts)
            except ValueError as exc:
                if not negative:
                    raise
                assert checkpoint==[digest(e,j) for j in range(n)]
                row["reason"]=str(exc)
            else:
                assert not negative, (kind,name)
                data=measure(e,kind,i,layout,table)
                assert all(data["checks"].values()),(kind,name,data)
                row.update(data,operation_xyz_m=operating_point(e,kind,i).tolist(),
                           layout=e.workspace_records[i]["layout"])
                from tools.variation.build_furniture_workspace import panel, rail, screw, vector
                if kind == "LayFlatPanel":
                    expected_xyz = np.r_[layout["rack_xy_m"],panel.PANEL_IN_SLOT_Z + panel.GRASP_LOCAL_POS[1]]
                elif kind == "InsertRail":
                    expected_xyz = np.r_[layout["rail_xy_m"],rail.RAIL_REST_Z + rail.RAIL_GRASP_LOCAL[2]]
                else:
                    offset=rail.RAIL_SCREW_LOCAL_POSITIONS[0]
                    expected_xyz = np.r_[layout["panel_xy_m"],panel.PANEL_HALF[2]+rail.RAIL_SEATED_Z_LOCAL
                                         +offset[2]+screw.WING_SCREW_STEM_HEIGHT+screw.WING_HALF[2]]
                    expected_xyz += (rail.RAIL_SEATED_X_LOCAL+offset[0])*vector(layout["panel_yaw_deg"])
                row["operation_error_m"]=float(np.linalg.norm(expected_xyz-row["operation_xyz_m"]))
                assert row["operation_error_m"] <= 2e-5,(kind,name,row["operation_error_m"])
                if n==2:
                    assert checkpoint[1-i]==digest(e,1-i)
                    row["unselected_unchanged"]=True
                if name in ("reference","near","far"):
                    a=reach(e,kind,i)
                    row["reach"]=a
                    row["release"]=release_probe(env,e,kind,i)
                    assert row["release"].get("passed",True)
                    if name in ("reference","far"):
                        env.reset(seed=seed)
                        env.reset(options=opts)
                        row["short_action"]=short_attempt(env,e,kind,i,a)
                if name.startswith("interior"):
                    # Independent native reset and IK solve at a point excluded from map generation.
                    from tasks.furniture_assembly.workspace import rotate
                    angles=[layout[r+"_yaw_deg"] for r in ROLES[kind]]
                    xy=layout[ROLES[kind][0]+"_xy_m"]
                    if kind=="InsertRail":
                        xy=[*xy,*rotate(np.array(layout["rail_xy_m"])-xy,-angles[0])]
                    coords=np.array([xy])
                    chain=setup_motion(e,i)
                    # The per-env hand enclosures must be read in the same scene as the chain.
                    boxes=hand_enclosures(e,i)
                    scores=[]
                    for tilt in (0,25,-25):
                        err,jump,gap=screen(chain,paths(kind,angles,coords,np.deg2rad(tilt)),boxes,kind,coords[:,:2],angles[0])
                        scores.append([float(err[0]),float(jump[0]),float(gap[0])])
                    row["holdout_ik"] = scores
            rows.append(row)
        # Existing legal points outside our screened map retain their original interface.
        for name, _, req, negative in cases(kind):
            if not negative and name in ("C-edge","C-lane","C-far"):
                env.reset(seed=909,options={"position_layout":{str(j):req for j in range(n)}})
                assert all(measure(e,kind,0,req,table)["checks"].values())
    return dict(operation_xyz_m=samples,reset_ms=samples_ms)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend",choices=("physx_cpu","physx_cuda"),default="physx_cpu")
    parser.add_argument("--physx-gpu-dir")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    n=2 if args.backend=="physx_cuda" else 1
    rows=[]
    result=dict(backend=args.backend,num_envs=n,sapien=sapien.__version__,torch=torch.__version__,
                indexed_gpu_apply=getattr(sapien.physx,"indexed_gpu_apply_patch_version",lambda:None)(),
                platform=platform.platform(),commit=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
                table_sha256=hashlib.sha256(TABLE.read_bytes()).hexdigest(),tasks={})
    for kind in ROLES:
        print("checking",kind,flush=True)
        result["tasks"][kind]=test_task(kind,args.backend,n,rows)
        if n == 1:
            rng, replay = np.random.default_rng(3942), np.random.default_rng(3942)
            layers = Counter()
            for _ in range(8192):
                placed = draw(kind,rng)
                assert placed == draw(kind,replay)
                validated = fixed_layout(kind,placed)
                for role in ROLES[kind]:
                    assert np.allclose(validated[role+"_xy_m"],placed[role+"_xy_m"],atol=1e-12,rtol=0)
                layers[str([placed[r+"_yaw_deg"] for r in ROLES[kind]])] += 1
            result["tasks"][kind]["sample_yaw_counts"]=dict(layers)
    if n == 1:
        with gym.make("FurnitureAssemblyLong-Sharpa-v1",sim_backend="physx_cpu",obs_mode="state",
                      control_mode="pd_joint_pos",reconfiguration_freq=0) as env:
            env.reset(seed=7)
            baseline=env_digest(state(env.unwrapped),0)
            env.reset(seed=7,options={"position_layout":{"0":{}}})
            assert env_digest(state(env.unwrapped),0)==baseline
            result["long_native_compatibility"]=True
    result["counts"]=dict(Counter(r["expected"] for r in rows))
    result["short_action"]=[r["short_action"]["passed"] for r in rows if "short_action" in r]
    (args.output/"results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with (args.output/"POINTS.csv").open("w",newline="",encoding="utf-8") as fp:
        writer=csv.DictWriter(fp,fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,separators=(",",":")) if isinstance(v,(list,dict)) else v for k,v in row.items()})
    print(result["counts"],result["short_action"])


if __name__=="__main__":
    main()
