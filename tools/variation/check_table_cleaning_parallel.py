"""Verify two parallel Table Cleaning environments on the actual task entries."""
import hashlib
import json
import os
from pathlib import Path
import sys

import gymnasium as gym
import numpy as np
from PIL import Image
import sapien
import torch
from render_table_cleaning import use_verified_collision_cache, native, PICK, DUMP, LONG
from table_cleaning_contract import check_catalog, check_materials

CONFIG = {"per_env": {"0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "variant_2"}}}


def digest(array):
    array = np.asarray(array)
    return [list(array.shape), str(array.dtype), hashlib.sha256(array.tobytes()).hexdigest()]


def objects(task):
    return {"pan": task.pan, "bin": task.bin, **{f"debris_{i}": a for i, a in enumerate(task.debris)}}


def state(task, index):
    snap = {"robot": task.agent.robot.get_qpos()[index], "qvel": task.agent.robot.get_qvel()[index]}
    for k,a in objects(task).items():
        snap[k] = a.pose.raw_pose[index]
        if k != "bin":
            snap[k+".linear_velocity"] = a.linear_velocity[index]
            snap[k+".angular_velocity"] = a.angular_velocity[index]
    snap["task"] = task.get_state_dict()["table_clean_task_state"][index]
    return {k:v.detach().cpu().numpy().copy() for k,v in snap.items()}


def material_state(task, index):
    result = {}
    for key,actor in objects(task).items():
        entity = actor._objs[index]
        render = entity.find_component_by_type(sapien.render.RenderBodyComponent)
        for i,shape in enumerate(render.render_shapes):
            mats = [shape.material] if isinstance(shape, sapien.render.RenderShapePrimitive) else [
                part.material for part in shape.parts]
            for j,m in enumerate(mats):
                t = m.base_color_texture
                pixels = None if t is None else t.download()
                if pixels is not None and pixels.ndim == 3 and pixels.shape[-1] == 3:
                    pixels = np.asarray(Image.fromarray(pixels).convert("RGBA"))
                result[f"{key}/{i}/{j}"] = {
                    "color": list(m.base_color), "roughness": m.roughness, "metallic": m.metallic,
                    "base_color_texture": None if t is None else [t.is_srgb, digest(pixels)],
                }
    return result


def frame(env):
    return env.render()[..., :3].detach().cpu().numpy().copy()


def delta(a,b):
    d = np.abs(a.astype(np.float64) - b.astype(np.float64))
    return {"nonzero": int(np.count_nonzero(d)), "max": float(d.max(initial=0))}


def trial(task_id, enabled, out):
    env = gym.make(task_id, num_envs=2, sim_backend="physx_cuda",
                   obs_mode="state", render_mode="rgb_array", reconfiguration_freq=0,
                   robot_init_qpos_noise=0., **({"table_cleaning_appearance": CONFIG} if enabled else {}))
    try:
        task = env.unwrapped
        env.reset(seed=7, options={"reconfigure": True})
        before = frame(env)
        m_before = [material_state(task, i) for i in (0,1)]
        source_pixels = task.cleaning_appearance.pixels["original"].copy() if enabled else None
        s_before = state(task, 0)
        record_before = dict(task.cleaning_appearance.records[0]) if enabled else None
        options = {"env_idx": torch.tensor([1], device=task.device)}
        if enabled:
            assert [r["scheme_id"] for r in task.cleaning_appearance.records] == ["variant_1", "variant_2"]
            options["table_cleaning_appearance"] = {"scheme_id": "original"}
        env.reset(options=options)
        after = frame(env)
        m_after = [material_state(task, i) for i in (0,1)]
        s_after = state(task, 0)
        state_changes = {k:delta(v,s_after[k]) for k,v in s_before.items()}
        ident = task_id.removesuffix("-Sharpa-v1")
        for i, img in enumerate([before[0], before[1], after[0], after[1]]):
            if enabled or i == 3:
                Image.fromarray(img).save(out/f"{ident}_{'variation' if enabled else 'native'}_{i}.png")
        records = None
        if enabled:
            records = task.cleaning_appearance.records
            assert records[0] == record_before
            assert records[1]["scheme_id"] == "original"
        # Run one dynamics step after collecting exact post-reset snapshots.
        task.step(torch.zeros(env.action_space.shape, device=task.device))
        return {"before": m_before, "after": m_after, "env0_rgb": delta(before[0],after[0]),
                "env0_state": state_changes, "env1_state": state(task,1),
                "after_rgb": after, "before_rgb": before, "records": records,
                "source_pixels": source_pixels}
    finally:
        env.close()


def check(task_id,out):
    a,b = trial(task_id,False,out),trial(task_id,True,out)
    semantic = [check_materials(a["before"][i], b["before"][i], scheme, b["source_pixels"])
                for i, scheme in enumerate(("variant_1", "variant_2"))]
    changed = [[k for k,v in b["before"][i].items() if a["before"][i].get(k) != v] for i in (0,1)]
    restored = delta(a["after_rgb"][1], b["after_rgb"][1])
    images = [delta(a["before_rgb"][i],b["before_rgb"][i]) for i in (0,1)]
    states = {k:delta(v,b["env1_state"][k]) for k,v in a["env1_state"].items()}
    result = {"scheme_material_contract": semantic,
              "changed_slots": changed, "appearance_image_differences": images,
              "env0_state_differences": b["env0_state"], "native_env0_state_differences": a["env0_state"],
              "env0_rgb": b["env0_rgb"], "native_env0_rgb": a["env0_rgb"],
              "restored_rgb": restored, "env1_materials_match_original": a["after"][1] == b["after"][1],
              "env0_materials_unchanged": b["before"][0] == b["after"][0], "records": b["records"]}
    (out/f"{task_id}.json").write_text(json.dumps(result,indent=2)+"\n")
    assert all(len(slots) == 5 for slots in changed), changed
    assert all(d["nonzero"] > 0 for d in images), images
    assert result["env0_materials_unchanged"] and result["env1_materials_match_original"], result
    assert all(d["max"] <= 1e-6 for d in b["env0_state"].values()), result
    assert restored["max"] <= 1 and restored["nonzero"] <= 12, result
    assert b["env0_rgb"]["max"] <= 1 and b["env0_rgb"]["nonzero"] <= 12, result
    return result


def main():
    catalog = Path(__file__).resolve().parents[2] / "tasks/assets/variation/table_cleaning/v1/catalog.json"
    check_catalog(json.loads(catalog.read_text(encoding="utf-8")))
    assets,out = map(Path,sys.argv[1:])
    out.mkdir(parents=True,exist_ok=True)
    native.GLB_CACHE = assets/"glb_cache"
    native.ROBOCASA = assets/"robocasa/lightwheel"
    use_verified_collision_cache()
    report = {"job_id": os.environ.get("SLURM_JOB_ID"), "gpu": os.environ.get("SLURM_JOB_GPUS"),
              "num_envs": 2, "tasks": {}}
    for task_id in (PICK,DUMP,LONG):
        report["tasks"][task_id] = check(task_id,out)
        (out/"summary.json").write_text(json.dumps(report,indent=2)+"\n")
        print(task_id,"PASS",flush=True)


if __name__ == "__main__":
    main()
