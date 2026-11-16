"""Run Meal Appearance isolation and latency checks inside the task."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import gymnasium as gym
import numpy as np
from PIL import Image
import torch

sys.path.insert(0, str(Path.cwd()))
import tasks

TASKS = {
    "open": "MealPreparationOpenLunchBox-Sharpa-v1",
    "bread": "MealPreparationPlaceBread-Sharpa-v1",
    "tomato": "MealPreparationScoopTomato-Sharpa-v1",
    "long": "MealPreparationLong-Sharpa-v1",
}
CONFIG = {"per_env": {"0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "variant_2"}}}


def make(stage, config, obs_mode="rgb"):
    return gym.make(TASKS[stage], num_envs=2, sim_backend="physx_cuda",
                    obs_mode=obs_mode, render_mode="rgb_array",
                    reconfiguration_freq=0, meal_appearance=config)


def sample_tree(tree, idx):
    if isinstance(tree, dict):
        return {k: sample_tree(v, idx) for k, v in tree.items()
                if not (k.startswith(("procedural_box_", "partnet_box_"))
                        and k.rsplit("_", 1)[-1] != str(idx))}
    if torch.is_tensor(tree):
        if tree.ndim and tree.shape[0] == 2:
            return tree[idx].detach().cpu().clone()
        return tree.detach().cpu().clone()
    if isinstance(tree, np.ndarray):
        return tree[idx].copy() if tree.ndim and tree.shape[0] == 2 else tree.copy()
    return tree


def changed(a, b, prefix=""):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        return [k for name in a for k in changed(a[name], b[name], f"{prefix}/{name}")]
    if np.array_equal(a, b):
        return []
    a, b = np.asarray(a), np.asarray(b)
    if a.shape == b.shape and np.issubdtype(a.dtype, np.floating):
        return [{"field": prefix, "max_abs_delta": float(np.max(np.abs(a - b)))}]
    return [{"field": prefix, "max_abs_delta": None}]


def pixels(obs, human):
    return {**{name: s["rgb"].detach().cpu().numpy().copy()
               for name, s in obs["sensor_data"].items() if "rgb" in s},
            "human": human.detach().cpu().numpy().copy()}


def materials(adapter, idx):
    return {
        f"{actor}/{role}": [{
            "base_color": list(m.base_color),
            "roughness": m.roughness, "metallic": m.metallic,
            "texture": None if m.base_color_texture is None else hashlib.sha256(
                m.base_color_texture.download().tobytes()).hexdigest(),
        } for m, _, _ in targets]
        for actor, group in adapter.bindings[idx].items()
        for role, targets in group.items()
    }


def isolate(stage, output, enabled=True):
    env = make(stage, CONFIG if enabled else None)
    t = env.unwrapped
    try:
        obs, _ = env.reset(seed=7)
        adapter = t.meal_appearance
        if enabled:
            assert [x["scheme_id"] for x in adapter.records] == ["variant_1", "variant_2"]
            pre_mat = [materials(adapter, idx) for idx in range(2)]
            assert pre_mat[0] != pre_mat[1]
            records = [dict(row) for row in adapter.records]
        before = sample_tree(t.get_state_dict(), 0)
        scene_rng = t._batched_episode_rng[0]
        rng_before = scene_rng.get_state() if hasattr(scene_rng, "get_state") else scene_rng.bit_generator.state
        variation_rng = None if adapter is None else adapter.rng[0].bit_generator.state
        pre_images = pixels(obs, env.render())
        opts = {"env_idx": torch.tensor([1], device=t.device),
                "meal_appearance": {"per_env": {"1": {"scheme_id": "original"}}}}
        obs, _ = env.reset(options=opts)
        state_changes = changed(before, sample_tree(t.get_state_dict(), 0))
        scene_rng = t._batched_episode_rng[0]
        rng_after = scene_rng.get_state() if hasattr(scene_rng, "get_state") else scene_rng.bit_generator.state
        if isinstance(rng_before, tuple):
            assert all(np.array_equal(a, b) for a, b in zip(rng_before, rng_after)), stage
        else:
            assert rng_before == rng_after, stage
        if adapter is not None:
            assert adapter.rng[0].bit_generator.state == variation_rng, stage
        post_images = pixels(obs, env.render())
        deltas = {k: np.abs(pre_images[k][0].astype(np.int16) - post_images[k][0])
                  for k in pre_images}
        pixel_changes = {k: int(np.count_nonzero(v)) for k, v in deltas.items()}
        max_pixel_delta = {k: int(v.max()) for k, v in deltas.items()}
        selected_changes = {k: int(np.count_nonzero(pre_images[k][1] != post_images[k][1]))
                            for k in pre_images}
        assert all(x["max_abs_delta"] is not None and x["max_abs_delta"] <= 1e-6
                   for x in state_changes), (stage, state_changes)
        # GPU pose/transform round trips can quantize a few color channels by one.
        assert max(max_pixel_delta.values()) <= 1 and max(pixel_changes.values()) <= 8, (
            stage, pixel_changes, max_pixel_delta
        )
        result = {"unselected_rng_unchanged": True, "unselected_state_changes": state_changes, "unselected_pixels": pixel_changes,
                  "unselected_max_channel_delta": max_pixel_delta, "selected_pixels": selected_changes}
        if enabled:
            post_mat = [materials(adapter, idx) for idx in range(2)]
            assert adapter.records[0] == records[0]
            assert adapter.records[1]["scheme_id"] == "original"
            assert adapter.records[1]["episode_index"] == records[1]["episode_index"] + 1
            assert post_mat[1] != pre_mat[1]
            assert post_mat[0] == pre_mat[0]
            assert any(selected_changes.values())
            names = ("env0_before","env0_after","env1_before","env1_after")
            for name, image in zip(names, [pre_images["human"][0], post_images["human"][0],
                                          pre_images["human"][1], post_images["human"][1]]):
                Image.fromarray(image[..., :3]).save(output / f"{stage}_{name}.png")
            if stage == "long":
                # The stock 768px human camera sees the fixed plate in this ROI.
                # Read rendered pixels as well as RenderMaterial getters.
                old = pre_images["human"][1, 445:515, 465:585, :3].astype(np.int16)
                new = post_images["human"][1, 445:515, 465:585, :3].astype(np.int16)
                rim = (old[..., 1] > old[..., 0] + 15) & (old[..., 1] > old[..., 2] + 10)
                blue = pre_images["human"][0, 445:515, 465:585, :3].astype(np.int16)
                blue_pixels = int(np.count_nonzero((blue[..., 2] > blue[..., 0] + 15)
                                                       & (blue[..., 2] > blue[..., 1] + 10)))
                assert blue_pixels >= 100, ("cobalt glaze was not rendered", blue_pixels)
                matching = int(rim.sum())
                assert matching >= 100, matching
                moved = int(np.count_nonzero(np.max(np.abs(old - new), axis=-1)[rim] > 10))
                assert moved >= matching * .9, ("selected plate texture did not refresh", matching, moved)
                grip = pre_images["human"][1, 453:461, 423:438, :3].astype(np.int16)
                orange = int(np.count_nonzero((grip[..., 0] > grip[..., 1] + 35)
                                              & (grip[..., 1] > grip[..., 2] + 15)))
                assert orange >= 45, ("warm-orange grip was not rendered", orange, pre_mat[1]["spoon/grip"])
                result["selected_plate_rim_refresh"] = {
                    "warm_orange_grip_pixels": orange,
                    "cobalt_glaze_pixels": blue_pixels,
                    "former_green_rim_pixels": matching, "changed_by_over_10_rgb_levels": moved
                }
            result.update(records_before=records, records_after=adapter.records,
                          checked_material_roles=sorted(pre_mat[0]))
        return result
    finally:
        env.close()


def measured(callback, samples=1):
    values = []
    for _ in range(samples):
        torch.cuda.synchronize()
        start = time.perf_counter()
        callback()
        torch.cuda.synchronize()
        values.append((time.perf_counter()-start)*1000)
    return {"samples": samples, "median_ms": statistics.median(values),
            "min_ms": min(values), "max_ms": max(values)}


def process_gpu_mib():
    # Read only the current job process, excluding other users on the same GPU.
    try:
        result = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory",
                                 "--format=csv,noheader,nounits"], check=True,
                                capture_output=True, text=True)
        return sum(int(mib) for pid, mib in (r.split(",") for r in result.stdout.splitlines())
                   if pid.strip() == str(os.getpid())) or None
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def benchmark(enabled, stage="long"):
    env = None
    def construct():
        nonlocal env
        env = make(stage, CONFIG if enabled else None)

    torch.cuda.init()
    torch.cuda.reset_peak_memory_stats()
    try:
        construct_time = measured(construct)
        phase = {"construction": process_gpu_mib()}
        env.reset(seed=7)
        phase["reset"] = process_gpu_mib()
        t=env.unwrapped
        opts={"env_idx":torch.tensor([1],device=t.device)}
        def reset():
            current = None if t.meal_appearance is None else t.meal_appearance.applied[1]
            target = "variant_1" if current == "variant_2" else "variant_2"
            env.reset(options={**opts, "meal_appearance":{"per_env":{"1":{"scheme_id":target}}}})
        action = torch.zeros(env.action_space.shape, device=t.device)
        for _ in range(3):
            reset()
            env.step(action)
            env.render()
        phase["warm"] = process_gpu_mib()
        partial = measured(reset, 20)
        advance = measured(lambda: env.step(action), 30)
        draw = measured(env.render, 20)
        phase["end"] = process_gpu_mib()
        return {"task":TASKS[stage],"enabled":enabled,"num_envs":2,
                "construct_ms":construct_time,"partial_reset_rgb_ms":partial,
                "step_rgb_ms":advance,"human_render_ms":draw,
                "torch_cuda_peak_bytes":torch.cuda.max_memory_allocated(),
                "pid_gpu_mib_by_phase":phase}
    finally:
        if env is not None:
            env.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mode", choices=("isolation","baseline","enabled"), required=True)
    p.add_argument("--stages", nargs="+", choices=TASKS, default=list(TASKS))
    args=p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode=="isolation":
        result={}
        for stage in args.stages:
            control = isolate(stage,args.output,enabled=False)
            trial = isolate(stage,args.output)
            result[stage] = {"control": control, "variation": trial}
            print(stage, "pixels control", control["unselected_pixels"],
                  control["unselected_max_channel_delta"], "variation", trial["unselected_pixels"],
                  trial["unselected_max_channel_delta"], flush=True)
            (args.output/"isolation.json").write_text(json.dumps(result,indent=2)+"\n")
            print("PASS",stage,flush=True)
    else:
        result=benchmark(args.mode=="enabled", args.stages[-1])
        (args.output/f"{args.mode}.json").write_text(json.dumps(result,indent=2)+"\n")
        print(json.dumps(result),flush=True)


if __name__=="__main__":
    main()
