"""Proposed CUDA short check. Run only inside the approved launcher."""
import argparse
import copy
import json
from pathlib import Path

import gymnasium as gym
import numpy as np
import sapien
import torch
import tasks
from tasks.cabinet_pouring.cabinet_pouring_long import link_piece_bounds
from tasks.cabinet_pouring.open_cabinet_workspace import contains, workspace

TASK = "CabinetPouringOpenCabinet-Sharpa-v1"


def snapshot(state, i):
    if isinstance(state, dict):
        return {k:snapshot(v,i) for k,v in state.items()}
    a=state[i].detach().cpu().contiguous().numpy()
    return (a.dtype.str,a.shape,a.tobytes())


def physical(env,i):
    e=env.unwrapped
    art=e._cabinets[i]
    xy=art.pose.p[0,:2].cpu().numpy()
    q=art.pose.q[0].cpu().numpy()
    yaw=float(np.rad2deg(2*np.arctan2(q[3],q[0])))
    bounds=link_piece_bounds(art.links_map["link_0"],relative_to=sapien.Pose(
        p=art.pose.p[0].cpu().numpy(),q=q))
    handle=link_piece_bounds(art.links_map["link_0"])[np.argmin(bounds[:,0,0])].mean(axis=0)
    return dict(root_xy_m=xy.tolist(),yaw_deg=yaw,handle_xyz_m=handle.tolist(),
                door_rad=float(art.qpos[0,0]),success=bool(e._stage_door[i]))


def run(out):
    results=[]
    def save():
        out.write_text(json.dumps(results,indent=2)+"\n")
    regions,presets=workspace()
    with gym.make(TASK,num_envs=2,sim_backend="physx_cuda",obs_mode="state",
                  reconfiguration_freq=0) as native:
        native.reset(seed=7)
        default=[physical(native,i) for i in range(2)]
        assert all(abs(p["yaw_deg"]-15)<.001 and np.all(
            np.abs(np.array(p["root_xy_m"])-[.14,.12])<=.01001) for p in default)
        native.reset(options={"position_layout":{str(i):{"cabinet_xy_m":[.19,.17],"yaw_deg":20}
                                                 for i in range(2)}})
        explicit=[physical(native,i) for i in range(2)]
        assert all(np.allclose(p["root_xy_m"],[.19,.17],atol=1e-5) and
                   abs(p["yaw_deg"]-20)<.001 for p in explicit)
        results.append(dict(test="native and PR32 explicit entry",native=default,explicit=explicit))
        save()
    with gym.make(TASK,num_envs=2,sim_backend="physx_cuda",obs_mode="state",
                  reconfiguration_freq=0,handle_workspace=True) as env:
        e=env.unwrapped
        def episode(seed=None, options=None):
            env.reset(seed=seed,options=options)
            return [physical(env,i) for i in range(2)]
        try:
            first=episode(7)
            next_pair=episode()
            assert first!=next_pair
            assert first==episode(7) and next_pair==episode()
            results.append(dict(test="seeded sequence",poses=[first,next_pair]))
            save()
            for i in (0,1):
                other=1-i
                before=snapshot(e.get_state_dict(),other)
                stream=copy.deepcopy(e._batched_episode_rng[other].get_state())
                pose=episode(options={"env_idx":torch.tensor([i],device=e.device)})[i]
                angle=round(pose["yaw_deg"])
                assert abs(angle-pose["yaw_deg"])<.001 and contains(regions[angle],pose["root_xy_m"])
                assert snapshot(e.get_state_dict(),other)==before
                after=e._batched_episode_rng[other].get_state()
                assert all(np.array_equal(a,b) for a,b in zip(stream,after))
                assert abs(pose["door_rad"])<1e-4 and not pose["success"]
                results.append(dict(test="local reset",selected=i,isolated=other,pose=pose))
                save()
            cases=[(name,xy,15) for name,xy in presets.items()]
            for yaw,rows in regions.items():
                y,x,_=rows[0]
                cases.append((dict(cabinet_xy_m=[x/100,y/100],yaw_deg=yaw),[x,y],yaw))
            for request,xy,yaw in cases:
                pose=episode(options={"env_idx":torch.tensor([0],device=e.device),
                                      "handle_placement":{"0":request}})[0]
                assert np.allclose(pose["root_xy_m"],np.array(xy)/100,atol=1e-5,rtol=0)
                assert abs(pose["yaw_deg"]-yaw)<.001 and abs(pose["door_rad"])<1e-4
                results.append(dict(test="fixed / boundary",request=request,pose=pose))
                save()
            for yaw,rows in regions.items():
                outside=[(rows[:,1].min()-1)/100,rows[0,0]/100]
                try:
                    episode(options={"env_idx":torch.tensor([0],device=e.device),
                                     "handle_placement":{"0":{"cabinet_xy_m":outside,"yaw_deg":yaw}}})
                except ValueError as exc:
                    assert "Outside OpenCabinet handle workspace" in str(exc)
                    results.append(dict(test="outside rejected",xy=outside,yaw=yaw))
                    save()
                else:
                    raise AssertionError(f"outside request accepted: {yaw} {outside}")
        except Exception as exc:
            results.append(dict(failure=repr(exc)))
            save()
            raise


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    run(parser.parse_args().output)
