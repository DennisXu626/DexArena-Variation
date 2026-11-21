"""Render and verify all Meal schemes in a named Slurm GPU job."""
import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

import gymnasium as gym
import numpy as np
from PIL import Image, ImageDraw
import sapien
import torch

sys.path.insert(0, str(Path.cwd()))
import tasks
from tasks.meal_preparation.appearance import CATALOG, linear_rgba
from tasks.meal_preparation.appearance_textures import bake_texture
from mani_skill.utils.sapien_utils import look_at
from check_meal_parallel import TASKS, changed, sample_tree, materials
from check_meal_restore_original import snapshot, equal_materials

CAT = json.loads(CATALOG.read_text())
IDS = list(CAT["schemes"])


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def frame(env):
    a = env.render().detach().cpu().numpy()
    return a if a.ndim == 4 else a[None]


def image_delta(a, b):
    d = np.abs(a.astype(np.int16)-b.astype(np.int16))
    return {"changed_channels": int(np.count_nonzero(d)), "max_delta": int(d.max())}


def make(stage, config, backend, count):
    return gym.make(TASKS[stage], num_envs=count, sim_backend=backend,
                    obs_mode="state", render_mode="rgb_array", reconfiguration_freq=0,
                    robot_init_qpos_noise=0, meal_appearance=config,
                    box_asset_source="procedural")


def semantic(adapter, idx, scheme):
    checked = []
    for actor, roles in adapter.bindings[idx].items():
        for role, targets in roles.items():
            cfg = CAT["schemes"][scheme][actor][role]
            for mat, baseline, root in targets:
                assert np.isclose(mat.roughness, cfg["roughness"], atol=1e-6)
                assert np.isclose(mat.metallic, cfg["metallic"], atol=1e-6)
                if "pixels" in baseline:
                    original = baseline["pixels"]
                    if "texture" in cfg:
                        baked = Image.fromarray(bake_texture(root, cfg["texture"]))
                        expected = np.asarray(baked.resize((original.shape[1], original.shape[0]), Image.Resampling.LANCZOS))
                    else:
                        expected = np.empty_like(original)
                        expected[:] = [int(cfg["color"][i:i+2],16) for i in (1,3,5)]+[255]
                    actual = mat.base_color_texture.download()
                    assert np.array_equal(actual, expected), (actor,role,"pixels")
                    assert np.allclose(mat.base_color, [1,1,1,1], atol=1e-6)
                    checked.append({"role": actor+"/"+role, "pixels_sha256": hashlib.sha256(actual.tobytes()).hexdigest()})
                else:
                    assert np.allclose(mat.base_color, linear_rgba(cfg["color"]), atol=1e-6)
                    checked.append({"role": actor+"/"+role, "color":cfg["color"]})
    assert checked
    return checked


def state_equal(a,b):
    delta = changed(a,b)
    assert all(x["max_abs_delta"] is not None and x["max_abs_delta"]<=1e-6 for x in delta), delta
    return delta


def verify(stage, out):
    native=make(stage,None,"physx_cuda",2)
    try:
        native.reset(seed=7)
        native_slots=[snapshot(native.unwrapped,i) for i in range(2)]
    finally:
        native.close()
    env=make(stage,{"enabled":True},"physx_cuda",2)
    t=env.unwrapped
    results=[]
    try:
        for scheme in IDS[1:]:
            env.reset(seed=7,options={"meal_appearance":{"scheme_id":scheme}})
            initial=frame(env)
            assert np.ptp(initial)>0
            Image.fromarray(initial[0,...,:3]).save(out/f"{stage}_{scheme}_scene.png")
            checks=[semantic(t.meal_appearance,i,scheme) for i in range(2)]
            for selected in (1,0):
                # Reset both rows to the candidate without advancing physics.
                env.reset(seed=7,options={"meal_appearance":{"scheme_id":scheme}})
                other=1-selected
                before=frame(env)
                state=sample_tree(t.get_state_dict(),other)
                slots=snapshot(t,other)
                record=copy.deepcopy(t.meal_appearance.records[other])
                rng=copy.deepcopy(t.meal_appearance.rng[other].bit_generator.state)
                task_rng=copy.deepcopy(t._batched_episode_rng[other].get_state())
                env.reset(options={"env_idx":torch.tensor([selected],device=t.device),
                                   "meal_appearance":{"scheme_id":"original"}})
                after=frame(env)
                rows=equal_materials(native_slots[selected],snapshot(t,selected),"native restore")
                assert all(x["match"] for x in rows), rows
                assert all(x["match"] for x in equal_materials(slots,snapshot(t,other),"unselected"))
                delta=state_equal(state,sample_tree(t.get_state_dict(),other))
                assert record==t.meal_appearance.records[other]
                assert rng==t.meal_appearance.rng[other].bit_generator.state
                assert all(np.array_equal(a,b) for a,b in zip(task_rng,t._batched_episode_rng[other].get_state()))
                rgb=image_delta(before[other],after[other])
                assert rgb["max_delta"]<=1 and rgb["changed_channels"]<=8, rgb
                assert t.meal_appearance.records[selected]["scheme_id"]=="original"
                results.append({"scheme":scheme,"selected":selected,"restored_slots":len(rows),
                                "other_state_delta":delta,"other_rgb":rgb,"semantic":checks[selected],
                                "other_record_and_rng_unchanged":True})
            save_json(out/f"{stage}_results.json",results)
            print("PASS",stage,scheme,flush=True)
        # Limited dynamics smoke check, not a robot success trajectory.
        action=torch.zeros(env.action_space.shape,device=t.device)
        for _ in range(4):
            env.step(action)
        save_json(out/f"{stage}_summary.json",{"job":os.environ.get("SLURM_JOB_ID"),
            "gpu":os.environ.get("SLURM_JOB_GPUS"),"task":TASKS[stage],"cases":len(results),
            "schemes":IDS,"seed":7,"num_envs":2,"zero_action_steps":4,
            "scope":"material semantics, native material restore, near-initial partial reset isolation; no complete robot trajectory"})
    finally:
        env.close()


VIEWS={
 "plate":("bread",(0,-.12,.55),(0,0,.012),.83),
 "spoon":("tomato",(0,-.025,.48),(0,0,.024),.87),
 "bread":("bread",(0,-.095,.23),(0,0,.012),.77),
 "ball_food":("tomato",(0,-.085,.23),(0,0,.012),.62),
 "box":("open",(.32,-.40,.40),(0,0,.025),.78),
}


def preview(out):
    manifest={}
    for name,(stage,offset,aim,fovy) in VIEWS.items():
        env=make(stage,{"enabled":True},"cpu",1)
        images=[]; reference=None
        try:
            for scheme in IDS:
                env.reset(seed=7,options={"meal_appearance":{"scheme_id":scheme}})
                t=env.unwrapped
                actor=getattr(t,name)
                center=actor.pose.p[0].cpu().numpy()
                if name=="spoon":
                    from scipy.spatial.transform import Rotation
                    w,x,y,z=actor.pose.q[0].cpu().tolist()
                    axis=Rotation.from_quat([x,y,z,w]).apply([0,0,1])
                    up=np.array([axis[0],axis[1],0.]); up/=np.linalg.norm(up)
                    pose=look_at(center+np.array([0,0,.48])-.025*up,center+np.array(aim)-.025*up,up=tuple(up))
                else:
                    pose=look_at(center+np.array(offset),center+np.array(aim),up=(0,1,0))
                camera=t.scene.human_render_cameras["render_camera"].camera._render_cameras[0]
                camera.entity.set_pose(sapien.Pose())
                camera.local_pose=sapien.Pose(pose.p[0].tolist(),pose.q[0].tolist())
                camera.set_fovy(fovy,compute_x=True)
                identity={"pose":actor.pose.raw_pose.cpu().tolist(),"box_qpos":t.box.qpos.cpu().tolist(),
                          "camera_p":pose.p[0].tolist(),"camera_q":pose.q[0].tolist(),"fovy":fovy}
                if reference is None: reference=identity
                assert identity==reference,(name,scheme,"scene drift")
                a=frame(env)[0,...,:3]
                assert np.ptp(a)>0
                im=Image.fromarray(a); im.save(out/f"{name}_{scheme}.png")
                images.append(im)
            assert len({hashlib.sha256(im.tobytes()).hexdigest() for im in images})==len(IDS),(name,"identical frames")
            w,h=480,360
            board=Image.new("RGB",(w*4,(h+32)*3),(25,29,34)); draw=ImageDraw.Draw(board)
            for i,(scheme,im) in enumerate(zip(IDS,images)):
                x=(i%4)*w;y=(i//4)*(h+32)
                draw.text((x+12,y+8),scheme,fill="white")
                board.paste(im.resize((w,h)),(x,y+32))
            board.save(out/f"{name}_comparison.jpg",quality=94)
            manifest[name]={"task":TASKS[stage],"seed":7,"scene":reference,"schemes":IDS,
                            "backend":"CPU physics + GPU rendering; native reset state"}
            save_json(out/"preview_manifest.json",manifest)
            print("PREVIEW",name,flush=True)
        finally:
            env.close()


def main():
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["preview",*TASKS]);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    save_json(a.output/(a.mode+"_identity.json"),{"job":os.environ.get("SLURM_JOB_ID"),"gpu":os.environ.get("SLURM_JOB_GPUS"),
        "versions":{k:importlib.metadata.version(k) for k in ("sapien","mani_skill","torch")},
        "catalog_sha256":hashlib.sha256(CATALOG.read_bytes()).hexdigest()})
    if a.mode=="preview":preview(a.output)
    else:verify(a.mode,a.output)


if __name__=="__main__":main()
