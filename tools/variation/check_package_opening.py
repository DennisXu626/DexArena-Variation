"""Check native versus variant Package Opening tasks and a two-env partial reset."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
from time import perf_counter

import gymnasium as gym
import numpy as np
from PIL import Image
import sapien
import torch

sys.path.insert(0, str(Path.cwd()))
from tasks.package_opening import package_opening_long as package

TASKS = {"open": "PackageOpeningOpenPackage-Sharpa-v1",
         "extract": "PackageOpeningExtractApple-Sharpa-v1",
         "long": "PackageOpeningLong-Sharpa-v1"}
CONFIG = {"per_env": {"0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "variant_2"}}}
SCALARS = ("base_color", "emission", "specular", "roughness", "metallic",
           "transmission", "ior", "transmission_roughness")
TEXTURES = ("base_color_texture", "emission_texture", "metallic_texture",
            "normal_texture", "roughness_texture", "transmission_texture")
PREDICATES = ("success", "stage", "box_opened", "apple_lifted", "apple_grasped",
              "apple_extracted", "apple_picked_now", "apple_pick_completed",
              "apple_height_correct", "apple_stable", "apple_rest_steps",
              "apple_released", "apple_in_plate", "apple_task_completed")


def fingerprint(data):
    data = np.asarray(data)
    return [list(data.shape), str(data.dtype), hashlib.sha256(data.tobytes()).hexdigest()]


def attributes(object_, fields):
    result = {}
    for field in fields:
        if not hasattr(object_, field):
            continue
        value = getattr(object_, field)
        if isinstance(value, sapien.Pose):
            value = [*value.p.tolist(), *value.q.tolist()]
        elif isinstance(value, np.ndarray):
            value = value.tolist()
        result[field] = value
    return result


def texture_signature(texture):
    if texture is None:
        return None
    pixels = texture.download()
    if pixels.ndim == 3 and pixels.shape[2] == 3:
        pixels = np.concatenate((pixels, np.full((*pixels.shape[:2], 1), 255, dtype=pixels.dtype)), axis=2)
    return [texture.is_srgb, fingerprint(pixels)]


def snapshot(task, idx):
    geometry, materials = {}, {}
    for name in ("box", "apple", "plate"):
        actor = getattr(task, name, None)
        if actor is None:
            continue
        raw = actor._objs[idx]
        bodies = ([link.entity for link in raw.get_links()] if name == "box" else [raw])
        if name == "box":
            geometry["hinges"] = [
                attributes(joint, ("type", "limits", "pose_in_parent", "pose_in_child",
                                   "stiffness", "damping", "force_limit", "friction", "drive_target"))
                for joint in raw.get_active_joints()
            ]
        for body_index, body in enumerate(bodies):
            rb = body.find_component_by_type(sapien.render.RenderBodyComponent)
            phys = body.find_component_by_type(
                sapien.physx.PhysxArticulationLinkComponent if name == "box"
                else sapien.physx.PhysxRigidDynamicComponent
            )
            key = f"{name}/{body_index}"
            geometry[key] = {"body": attributes(phys, ("mass", "inertia", "cmass_local_pose", "kinematic",
                                                       "linear_damping", "angular_damping", "disable_gravity")),
                             "collisions": [], "visuals": []}
            for shape in phys.get_collision_shapes():
                contact = shape.physical_material
                mesh = {f: fingerprint(getattr(shape, f)) for f in ("vertices", "triangles") if hasattr(shape, f)}
                geometry[key]["collisions"].append({
                    "type": type(shape).__name__, "mesh": mesh,
                    "shape": attributes(shape, ("local_pose", "half_size", "scale", "radius",
                                                "density", "contact_offset", "rest_offset")),
                    "groups": np.asarray(shape.get_collision_groups()).tolist(),
                    "contact": attributes(contact, ("static_friction", "dynamic_friction", "restitution")),
                })
            for i, shape in enumerate(rb.render_shapes if rb else ()):
                primitive = isinstance(shape, sapien.render.RenderShapePrimitive)
                geometry[key]["visuals"].append({
                    "type": type(shape).__name__,
                    "shape": attributes(shape, ("local_pose", "half_size", "scale")),
                    "meshes": [] if primitive else [
                        {f: fingerprint(getattr(part, f)) for f in ("vertices", "triangles", "vertex_uv")
                         if hasattr(part, f)} | {"uv": fingerprint(part.get_vertex_uv()),
                                               "normals": fingerprint(part.get_vertex_normal())}
                         for part in shape.parts],
                })
                for j, mat in enumerate([shape.material] if primitive else [part.material for part in shape.parts]):
                    materials[f"{key}/{i}/{j}"] = {
                        "scalars": attributes(mat, SCALARS),
                        "textures": {f: texture_signature(getattr(mat, f)) for f in TEXTURES},
                    }
    assert materials and geometry
    return geometry, materials


def tree_row(tree, index):
    if isinstance(tree, dict):
        return {key: tree_row(value, index) for key, value in tree.items()
                if not key.endswith(f"_{1 - index}")}
    if isinstance(tree, torch.Tensor):
        return tree[index if tree.shape[0] == 2 else 0].detach().cpu().numpy().copy()
    raise TypeError(type(tree))


def state_delta(a, b, prefix=""):
    if isinstance(a, dict):
        assert a.keys() == b.keys(), prefix
        return {path: delta for key in a for path, delta in
                state_delta(a[key], b[key], f"{prefix}/{key}").items()}
    assert a.shape == b.shape, prefix
    delta = float(np.max(np.abs(a.astype(np.float64) - b.astype(np.float64)), initial=0))
    return {prefix: delta} if delta else {}


def rgb(env):
    return env.render()[..., :3].detach().cpu().numpy().copy()


def rgb_delta(a, b):
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return {"changed_channels": int(np.count_nonzero(d)), "max_abs_channel_delta": int(d.max())}


def predicates(env, stage):
    """Drive controlled state inputs through the real task evaluator."""
    task = env.unwrapped
    cfg = task.scene_config
    trace = {}
    def read(label):
        data = task.evaluate()
        trace[label] = {k: data[k].tolist() for k in PREDICATES if k in data}
        return trace[label]
    def qpos(a, b):
        delta = torch.tensor([a, b], device=task.device)
        closed = torch.tensor(cfg.closed_box, device=task.device)
        q = task.box.get_qpos().clone()
        q[:, :2] = closed + torch.deg2rad(delta)
        task.box.set_qpos(q)
    def apple_position(p):
        task.apple.set_pose(package.Pose.create_from_pq(p=p, q=task.apple.pose.q))
    def tick():
        task._elapsed_steps += 1
    if stage != "extract":
        qpos(0., 0.)
        assert read("both_closed")["box_opened"] == [False, False]
        qpos(110., 89.)
        assert read("one_flap_open")["box_opened"] == [False, False]
        qpos(110., 91.)
        opened = read("both_flaps_open")
        assert opened["box_opened"] == [True, True]
        assert opened["success"] == [stage == "open"] * 2
    if stage == "open":
        return trace

    landing = task.plate.pose.p.clone()
    landing[:, 2] = cfg.plate_top_z + cfg.apple_half_height
    apple_position(landing)
    settle = task.task_evaluator.PLACE_SETTLE_STEPS
    for _ in range(settle + 2):
        tick()
        no_pick = read("settled_without_pickup")
    assert no_pick["apple_in_plate"] == [True, True], no_pick
    assert no_pick["success"] == [False, False]

    agent = task.agent
    tips = getattr(agent, "right_tip_links", None) or getattr(agent, "tip_links", None)
    palm = getattr(agent, "right_palm_link", None) or getattr(agent, "palm_link", None)
    tcp = (0.7 * torch.stack([link.pose.p for link in tips]).mean(0) + 0.3 * palm.pose.p
           if tips and palm is not None else agent.tcp.pose.p).clone()
    tcp[:, 2].clamp_(min=max(cfg.seam_z + cfg.apple_half_height + .012, cfg.apple_pos[2] + .040))
    apple_position(tcp)
    tick()
    picked = read("lifted_near_tcp_and_clear_of_rim")
    assert picked["apple_picked_now"] == [True, True], picked

    misplaced = landing.clone()
    misplaced[:, 1] += .12
    apple_position(misplaced)
    tick()
    assert read("outside_plate")["success"] == [False, False]
    apple_position(landing)
    tick()
    assert read("just_moved_to_plate")["apple_stable"] == [False, False]
    for _ in range(settle - 1):
        tick()
        waiting = read("before_settle_threshold")
    assert waiting["apple_rest_steps"] == [settle - 1] * 2, waiting
    assert waiting["success"] == [False, False]
    tick()
    complete = read("released_at_settle_threshold")
    assert complete["success"] == [True, True], complete
    assert complete["stage"] == [2, 2]
    return trace


def timed(call):
    torch.cuda.synchronize()
    start = perf_counter()
    output = call()
    torch.cuda.synchronize()
    return output, (perf_counter() - start) * 1000


def trial(stage, enabled, output):
    env, build_ms = timed(lambda: gym.make(
        TASKS[stage], num_envs=2, sim_backend="physx_cuda", render_backend="gpu",
        obs_mode="state", render_mode="rgb_array",
        reconfiguration_freq=0, robot_init_qpos_noise=0,
        **({"package_appearance": CONFIG} if enabled else {}),
    ))
    task = env.unwrapped
    try:
        env.reset(seed=7)
        adapter = task.package_appearance
        if enabled:
            assert [r["scheme_id"] for r in adapter.records] == ["variant_1", "variant_2"]
        records_before = [dict(r) for r in adapter.records] if enabled else None
        before = rgb(env)
        geometry, before1 = snapshot(task, 1)
        _, before0 = snapshot(task, 0)
        other_state = tree_row(task.get_state_dict(), 0)
        opts = {"env_idx": torch.tensor([1], device=task.device)}
        if enabled:
            opts["package_appearance"] = {"scheme_id": "original"}
        env.reset(options=opts)
        after = rgb(env)
        post_geometry, after1 = snapshot(task, 1)
        _, after0 = snapshot(task, 0)
        assert geometry == post_geometry
        assert before0 == after0
        other_state_delta = state_delta(other_state, tree_row(task.get_state_dict(), 0))
        print("RESET ENV0 STATE", stage, enabled, other_state_delta, flush=True)
        other_rgb = rgb_delta(before[0], after[0])
        print("RESET ENV0 RGB", stage, enabled, other_rgb, flush=True)
        state = tree_row(task.get_state_dict(), 1)
        if enabled:
            assert adapter.records[0] == records_before[0]
            assert adapter.records[1]["scheme_id"] == "original"
            assert adapter.records[1]["episode_index"] == records_before[1]["episode_index"] + 1
            for index, label in enumerate(("variant_1", "variant_2")):
                Image.fromarray(before[index]).save(output / f"{stage}_{label}.png")
        Image.fromarray(after[1]).save(output / f"{stage}_{'restored' if enabled else 'native'}.png")
        traces = {}
        for scheme in (("variant_1", "variant_2") if enabled else ("native",)):
            override = {"package_appearance": {"mode": "explicit", "scheme_id": scheme,
                        "per_env": {str(i): {"scheme_id": scheme} for i in range(2)}}} if enabled else {}
            env.reset(seed=7, options=override)
            traces[scheme] = predicates(env, stage)

        def reset():
            return env.reset(seed=7)
        reset()
        action = torch.zeros(env.action_space.shape, device=task.device)
        task.step(action)
        benchmark = {"build_ms": build_ms}
        for label, call in (("reset", reset), ("step", lambda: task.step(action)), ("rgb", lambda: rgb(env))):
            timings = [timed(call)[1] for _ in range(8)]
            benchmark[f"{label}_median_ms"] = float(np.median(timings))
        return {"geometry": geometry, "before_materials": before1, "materials": after1,
                "image": after[1], "state": state, "trace": traces, "timings": benchmark,
                "other_rgb": other_rgb, "other_state_delta": other_state_delta,
                "records": [dict(r) for r in adapter.records] if enabled else None}
    finally:
        env.close()


def check(stage, output):
    native = trial(stage, False, output)
    variant = trial(stage, True, output)
    geometry_equal = native["geometry"] == variant["geometry"]
    material_faults = [slot for slot, sig in native["materials"].items()
                       if sig != variant["materials"].get(slot)]
    assert native["materials"].keys() == variant["materials"].keys()
    changed_slots = [slot for slot, sig in variant["before_materials"].items()
                     if sig != variant["materials"][slot]]
    frame_diff = rgb_delta(native["image"], variant["image"])
    restored_delta = state_delta(native["state"], variant["state"])
    result = {
        "physics_and_geometry_match": geometry_equal,
        "materials_match_native": not material_faults, "material_faults": material_faults,
        "material_slots": len(native["materials"]), "changed_slots": changed_slots,
        "restored_state_matches_native": max(restored_delta.values(), default=0) <= 1e-6,
        "restored_state_deltas": restored_delta,
        "restored_rgb": frame_diff, "untouched_rgb": variant["other_rgb"],
        "untouched_state_and_materials_match": max(variant["other_state_delta"].values(), default=0) <= 1e-6,
        "untouched_state_deltas": {"native": native["other_state_delta"], "variant": variant["other_state_delta"]},
        "task_predicates_match": all(v == native["trace"]["native"] for v in variant["trace"].values()),
        "task_predicates": native["trace"]["native"],
        "timings": {"native": native["timings"], "variant": variant["timings"]},
        "native_material_signatures": native["materials"],
        "restored_material_signatures": variant["materials"],
        "native_geometry": native["geometry"], "variant_geometry": variant["geometry"],
    }
    (output / f"{stage}.json").write_text(json.dumps(result, indent=2) + "\n")
    assert geometry_equal, f"{stage}: geometry differs"
    assert not material_faults, (stage, material_faults)
    assert changed_slots and result["restored_state_matches_native"] and result["task_predicates_match"], stage
    assert result["untouched_state_and_materials_match"], (stage, result["untouched_state_deltas"])
    assert variant["other_rgb"]["max_abs_channel_delta"] <= 1 and variant["other_rgb"]["changed_channels"] <= 8, (stage, variant["other_rgb"])
    assert frame_diff["max_abs_channel_delta"] <= 1 and frame_diff["changed_channels"] <= 8, (stage, frame_diff)
    return {k: v for k, v in result.items() if k not in (
        "native_material_signatures", "restored_material_signatures", "native_geometry", "variant_geometry")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--stages", choices=TASKS, nargs="+", default=list(TASKS))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    package.PACKAGE_URDF_PATH = args.assets / "package/mobility.urdf"
    package.ROBOCASA_OBJECT_DIR = args.assets / "robocasa/objects/objaverse"
    source_files = ("tasks/package_opening/appearance.py", "tasks/package_opening/package_opening_long.py",
                    "tasks/assets/variation/package_opening/v1/catalog.json",
                    "tools/variation/check_package_opening.py")
    summary = {"job": os.environ.get("SLURM_JOB_ID"), "base": args.base,
               "gpu": os.environ.get("SLURM_JOB_GPUS"), "num_envs": 2,
               "sim_backend": "physx_cuda", "render_backend": "gpu",
               "versions": {name: importlib.metadata.version(name) for name in ("sapien", "mani_skill", "torch")},
               "source_sha256": {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in source_files},
               "stages": {}}
    for stage in args.stages:
        try:
            summary["stages"][stage] = check(stage, args.output)
        except AssertionError as error:
            import traceback
            traceback.print_exc()
            summary["stages"][stage] = {"error": str(error)}

        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        if "error" not in summary["stages"][stage]:
            print("PASS", stage, flush=True)
    if any("error" in stage for stage in summary["stages"].values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
