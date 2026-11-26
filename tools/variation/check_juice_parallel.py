"""GPU regression: two fixed schemes, local reset, native restore and cost.

Run inside a Slurm job: python -B verify.py PlaceLid (or another Juice suffix).
No robot policy or long-task completion claim is made by this check.
"""
import copy
import hashlib
import json
import os
import resource
import time
from pathlib import Path

import gymnasium as gym
import numpy as np
import sapien
import torch
from PIL import Image
import tasks.juice_preparation

ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ["TMPDIR"]).parent / ("verification-" + os.environ["SLURM_JOB_ID"])
OUT.mkdir(exist_ok=True)
CONFIG = {"per_env": {"0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "variant_2"}}}
ROLES = {"OpenFridge": {"fridge"}, "CloseFridge": {"fridge"},
         "AppleToBlender": {"fridge", "apple", "blender"},
         "PlaceLid": {"blender", "lid"}, "PressButton": {"blender", "lid"},
         "Long": {"fridge", "apple", "blender", "lid"}}

def value(v):
    if isinstance(v, torch.Tensor):
        return v.detach().cpu().numpy().copy()
    return np.asarray(v).copy()

def sample(tree, index=None):
    if isinstance(tree, dict):
        return {k: sample(v, index) for k, v in tree.items()}
    v = value(tree)
    return v if index is None else v[index].copy()

def difference(a, b):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        return max((difference(a[k], b[k]) for k in a), default=0.)
    return float(np.max(np.abs(a.astype(float) - b.astype(float)), initial=0))

def digest(v):
    return hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()

def material(m):
    result = {k: value(getattr(m, k)).tolist() for k in
              ("base_color", "roughness", "metallic", "specular", "emission", "transmission", "ior", "transmission_roughness")}
    for key in ("base_color_texture", "normal_texture", "roughness_texture", "metallic_texture", "emission_texture", "transmission_texture"):
        tex = getattr(m, key)
        if tex is None:
            result[key] = None
        else:
            pixels = tex.download()
            if key == "base_color_texture" and pixels.shape[2] == 3:
                pixels = np.asarray(Image.fromarray(pixels).convert("RGBA"))
            result[key] = {"srgb": tex.is_srgb, "shape": list(pixels.shape), "sha256": digest(pixels)}
    return result

def materials(task, index):
    result = {}
    for name in ("fridge", "apple", "blender", "lid"):
        actor = getattr(task, name, None)
        if actor is None:
            continue
        raw = actor._objs[index]
        entities = [x.entity for x in raw.get_links()] if hasattr(raw, "get_links") else [raw]
        for n, entity in enumerate(entities):
            render = entity.find_component_by_type(sapien.render.RenderBodyComponent)
            if render is None:
                continue
            for i, shape in enumerate(render.render_shapes):
                for j, part in enumerate(shape.parts):
                    result[f"{name}/{n}/{i}/{j}"] = material(part.material)
    return result

def physical(task):
    result = {}
    for name in ("fridge", "apple", "blender", "lid"):
        actor = getattr(task, name, None)
        if actor is None:
            continue
        for index, raw in enumerate(actor._objs):
            bodies = raw.get_links() if hasattr(raw, "get_links") else [raw.find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)]
            for n, body in enumerate(bodies):
                data = {k: value(getattr(body, k)).tolist() for k in ("mass", "inertia")}
                data["cmass_pose"] = [value(body.cmass_local_pose.p).tolist(), value(body.cmass_local_pose.q).tolist()]
                shapes = []
                for shape in body.get_collision_shapes():
                    m = shape.physical_material
                    s = {"type": type(shape).__name__, "pose": [value(shape.local_pose.p).tolist(), value(shape.local_pose.q).tolist()],
                         "contact_offset": shape.contact_offset, "rest_offset": shape.rest_offset,
                         "friction_restitution": [m.static_friction, m.dynamic_friction, m.restitution]}
                    for k in ("vertices", "triangles", "scale", "half_size", "radius", "half_length"):
                        if hasattr(shape, k):
                            a = value(getattr(shape, k))
                            s[k] = {"shape": list(a.shape), "sha256": digest(a)}
                    shapes.append(s)
                data["collision_shapes"] = shapes
                result[f"{name}/{index}/{n}"] = data
            if hasattr(raw, "get_active_joints"):
                result[f"{name}/{index}/joints"] = [
                    {k: value(getattr(j, k)).tolist() for k in ("limits", "friction", "stiffness", "damping", "force_limit") if hasattr(j, k)}
                    for j in raw.get_active_joints()]
    return result

def frame(env):
    return env.render()[..., :3].cpu().numpy().copy()

def rgbdiff(a, b):
    d = np.abs(a.astype(int) - b.astype(int))
    return {"max": int(d.max()), "changed_channels": int(np.count_nonzero(d))}

def timed(fn):
    torch.cuda.synchronize()
    start = time.perf_counter()
    result = fn()
    torch.cuda.synchronize()
    return result, time.perf_counter() - start

def trial(task_name, enabled):
    start = time.perf_counter()
    env = gym.make(f"JuicePreparation{task_name}-Sharpa-v1", num_envs=2, sim_backend="physx_cuda", obs_mode="state",
                   render_mode="rgb_array", reconfiguration_freq=0, robot_init_qpos_noise=0,
                   **({"juice_appearance": CONFIG} if enabled else {}))
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - start
    try:
        _, reset_seconds = timed(lambda: env.reset(seed=7))
        task = env.unwrapped
        initial = sample(task.get_state_dict())
        signature = physical(task)
        m0, m1 = materials(task, 0), materials(task, 1)
        before = frame(env)
        record = copy.deepcopy(task.juice_appearance.records[0]) if enabled else None
        rng_before = repr(task._batched_episode_rng[0].get_state())
        options = {"env_idx": torch.tensor([1], device=task.device)}
        if enabled:
            options["juice_appearance"] = {"scheme_id": "original"}
            assert [r["scheme_id"] for r in task.juice_appearance.records] == ["variant_1", "variant_2"]
            assert all(set(b) == ROLES[task_name] for b in task.juice_appearance.bindings)
        _, local_reset_seconds = timed(lambda: env.reset(options=options))
        after = frame(env)
        result = {"load_seconds": load_seconds, "reset_seconds": reset_seconds, "local_reset_seconds": local_reset_seconds,
                  "env0_state_max_delta": difference(sample(initial, 0), sample(task.get_state_dict(), 0)),
                  "env0_materials_unchanged": m0 == materials(task, 0), "env0_rgb": rgbdiff(before[0], after[0]),
                  "env0_rng_unchanged": rng_before == repr(task._batched_episode_rng[0].get_state()),
                  "physics_unchanged_after_local_reset": signature == physical(task),
                  "before_materials": [m0, m1], "restored_materials": materials(task, 1),
                  "physics": signature}
        if enabled:
            result["env0_record_unchanged"] = record == task.juice_appearance.records[0]
            result["records"] = copy.deepcopy(task.juice_appearance.records)
            assert result["records"][1]["scheme_id"] == "original"
        for suffix, image in zip(("env0-before", "env1-before", "env0-after", "env1-restored"), (*before, *after)):
            Image.fromarray(image).save(OUT / f"{task_name}-{'variation' if enabled else 'native'}-{suffix}.png")
        states, infos, step_times, render_times = [], [], [], []
        action = torch.zeros(env.action_space.shape, device=task.device)
        for _ in range(16):
            step, seconds = timed(lambda: env.step(action))
            step_times.append(seconds)
            states.append(sample(task.get_state_dict()))
            infos.append(sample({k: v for k, v in step[-1].items() if isinstance(v, torch.Tensor)}))
        for _ in range(3):
            _, seconds = timed(lambda: frame(env))
            render_times.append(seconds)
        result["step_median_seconds"] = float(np.median(step_times[1:]))
        result["render_median_seconds"] = float(np.median(render_times))
        result["torch_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
        result["host_process_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return result, after[1], before, initial, states, infos
    finally:
        env.close()

def run(task_name):
    native, ni, nb, ns, nt, nf = trial(task_name, False)
    variant, vi, vb, vs, vt, vf = trial(task_name, True)
    checks = {
        "initial_state_matches_disabled": difference(ns, vs) <= 1e-6,
        "physics_matches_disabled": native["physics"] == variant["physics"],
        "env0_state_unchanged": variant["env0_state_max_delta"] <= 1e-6,
        "env0_materials_unchanged": variant["env0_materials_unchanged"],
        "env0_image_unchanged": variant["env0_rgb"]["max"] <= 1 and variant["env0_rgb"]["changed_channels"] <= 12,
        "env0_rng_unchanged": variant["env0_rng_unchanged"],
        "env0_record_unchanged": variant["env0_record_unchanged"],
        "physics_unchanged_after_local_reset": variant["physics_unchanged_after_local_reset"],
        "all_original_material_slots_restored": native["restored_materials"] == variant["restored_materials"],
        "original_image_restored": rgbdiff(ni, vi)["max"] <= 1 and rgbdiff(ni, vi)["changed_channels"] <= 12,
        "both_schemes_change_materials": all(native["before_materials"][i] != variant["before_materials"][i] for i in (0, 1)),
        "both_schemes_change_pixels": all(rgbdiff(nb[i], vb[i])["changed_channels"] > 100 for i in (0, 1)),
        "schemes_distinct": variant["before_materials"][0] != variant["before_materials"][1],
        "16_step_states_match_disabled": max(difference(a, b) for a, b in zip(nt, vt)) <= 1e-6,
        "16_step_info_matches_disabled": max(difference(a, b) for a, b in zip(nf, vf)) <= 1e-6,
    }
    result = {"task": task_name, "job_id": os.environ["SLURM_JOB_ID"], "gpu_index": os.environ["SLURM_JOB_GPUS"],
              "checks": checks, "native": native, "variation": variant, "restored_rgb": rgbdiff(ni, vi),
              "state_trajectory_max_delta": max(difference(a, b) for a, b in zip(nt, vt)),
              "scope": "Sharpa; 2 envs; seed 7; fixed schemes; noise 0; 16 zero-action steps; no policy success claim",
              "status": "passed" if all(checks.values()) else "failed"}
    (OUT / f"{task_name}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(task_name, result["status"], json.dumps(checks), flush=True)
    assert all(checks.values()), checks

if __name__ == "__main__":
    import sys
    run(sys.argv[1])
