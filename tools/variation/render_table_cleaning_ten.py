"""Capture appearance comparisons in the unmodified Table Cleaning tasks."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
from pathlib import Path

import gymnasium as gym
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import sapien
import torch
from mani_skill.utils.sapien_utils import look_at
from tasks.table_cleaning import table_cleaning_long as native


import inspect
from mani_skill.utils.building import actor_builder


def use_verified_collision_cache():
    """Reuse the native collision cache after verifying the source and parameters."""
    original = actor_builder.do_coacd
    signature = inspect.signature(original)

    def cached(filename, **kwargs):
        args = signature.bind(filename, **kwargs)
        args.apply_defaults()
        path = Path(filename)
        if path.name != native.UID_DUSTPAN + ".glb":
            return original(filename, **kwargs)
        keys = ("threshold", "max_convex_hull", "preprocess_mode", "preprocess_resolution",
                "resolution", "mcts_nodes", "mcts_iterations", "mcts_max_depth", "pca", "merge", "seed")
        params = dict(args.arguments)
        params["threshold"] = f"{params['threshold']:.2f}"
        md5 = hashlib.md5(path.read_bytes()).hexdigest()
        expected = "comment " + ", ".join([f"md5={md5}"] + [f"{k}={params[k]}" for k in keys])
        cache = path.with_name(path.name + ".coacd.ply")
        with cache.open("rb") as stream:
            assert stream.readline() == b"ply\n"
            assert stream.readline() == b"format binary_little_endian 1.0\n"
            assert stream.readline().decode("ascii").rstrip("\n") == expected, cache
        return str(cache)

    actor_builder.do_coacd = cached


PICK = "TableCleaningPickDebris-Sharpa-v1"
DUMP = "TableCleaningDumpDustpan-Sharpa-v1"
LONG = "TableCleaningLong-Sharpa-v1"
VIEWS = {
    "pick_scene": (PICK, "scene", (.35, -.24, .83), .70),
    "pan_loaded": (DUMP, "pan", (.28, -.04, .48), .69),
    "bin_floor": (DUMP, "bin", (.20, -.06, .63), .63),
    "long_scene": (LONG, "scene", (.35, -.24, .83), .70),
}
LABELS = ["Original", "Teal / Warm Gray / Pink", "Brick / Blue Gray / Pale Blue"]


def place_for_bin_preview(task):
    # Controlled visualization state from the actual dump task. No control steps.
    center = task.bin.pose.p[0].detach().cpu().numpy()
    for actor, (x, y) in zip(task.debris, ((-.033, -.025), (.031, -.015), (0., .034))):
        p = [float(center[0]+x), float(center[1]+y), float(task.bin_floor_z+.010)]
        actor.set_pose(sapien.Pose(p=p, q=actor.pose.q[0].cpu().tolist()))
        actor.set_linear_velocity(torch.zeros((1, 3), device=task.device))
        actor.set_angular_velocity(torch.zeros((1, 3), device=task.device))


def capture(view, scheme, colors, sugar_original, out):
    task_id, focus, delta, fovy = VIEWS[view]
    source_glb = native.GLB_CACHE
    private_glb = out.parent / ("visual-cache-" + os.environ.get("SLURM_JOB_ID", "local")) / f"{view}_{scheme}"
    private_glb.mkdir(parents=True, exist_ok=True)
    for name in (native.UID_DUSTPAN + ".glb", native.UID_DUSTPAN + ".glb.coacd.ply", native.UID_BIN + ".glb"):
        shutil.copyfile(source_glb / name, private_glb / name)
    native.GLB_CACHE = private_glb
    env = gym.make(task_id, num_envs=1, sim_backend="cpu", obs_mode="state",
                   render_mode="rgb_array", robot_init_qpos_noise=0., table_cleaning_appearance={"scheme_id":scheme},
                   human_render_camera_configs={"width": 900, "height": 720})
    try:
        env.reset(seed=7)
        task = env.unwrapped
        if focus == "bin":
            place_for_bin_preview(task)
        from check_table_cleaning_parallel import material_state
        binding = material_state(task, 0)
        xyz = lambda actor: actor.pose.p[0].cpu().numpy()
        if focus == "pan":
            target = xyz(task.pan) + [0., 0., .015]
        elif focus == "bin":
            target = xyz(task.bin) + [0., 0., .15]
        else:
            target = (xyz(task.pan) + xyz(task.bin)) / 2 + [0., 0., .045]
        actual_cam = task.scene.human_render_cameras["render_camera"].camera._render_cameras[0]
        pose = look_at(target + np.asarray(delta), target, up=(0, 1, 0))
        actual_cam.entity.set_pose(sapien.Pose())
        actual_cam.local_pose = sapien.Pose(pose.p[0].tolist(), pose.q[0].tolist())
        actual_cam.set_fovy(fovy, compute_x=True)
        image = env.render().cpu().numpy()[..., :3]
        if image.ndim == 4:
            image = image[0]
        if np.ptp(image) == 0:
            raise RuntimeError(f"Blank render for {view}")
        Image.fromarray(image).save(out / f"{view}_{scheme}.png")
        return {"task": task_id, "controlled_bin_placement": focus == "bin",
                "positions_wxyz": {k: a.pose.raw_pose.cpu().tolist() for k,a in
                                   [("pan", task.pan), ("bin", task.bin)] +
                                   [(f"debris_{i}", a) for i,a in enumerate(task.debris)]},
                "robot_qpos": task.agent.robot.get_qpos().cpu().tolist(),
                "camera_pose": pose.raw_pose.cpu().tolist(), "fovy": fovy,
                "binding": binding}
    finally:
        env.close()
        native.GLB_CACHE = source_glb


def sheet(out, view, schemes):
    images = [Image.open(out / f"{view}_{s}.png").convert("RGB") for s in schemes]
    w,h=500,400
    canvas=Image.new("RGB",(w*3,(h+32)*4),"#1B2027")
    draw=ImageDraw.Draw(canvas)
    for i,(img,label) in enumerate(zip(images,schemes)):
        x,y=(i%3)*w,(i//3)*(h+32)
        canvas.paste(img.resize((w,h)),(x,y+32))
        draw.text((x+12,y+8),label,fill="white")
    canvas.save(out/f"{view}_comparison.png")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    use_verified_collision_cache()
    native.GLB_CACHE = a.assets / "glb_cache"
    native.ROBOCASA = a.assets / "robocasa/lightwheel"
    src = native.ROBOCASA / native.DEBRIS_REF / "visual/T_BC001.png"
    source = Image.open(src)
    catalog = json.loads(a.catalog.read_text())
    schemes = catalog["schemes"]
    manifest = {"job_id": os.environ.get("SLURM_JOB_ID"), "gpu_indices": os.environ.get("SLURM_JOB_GPUS"),
                "seed": 7, "num_envs": 1, "physics": "cpu", "render": "gpu (SAPIEN/Vulkan)",
                "versions": {x: importlib.metadata.version(x) for x in ("sapien", "mani_skill", "torch")},
                "source_hashes": {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                  for p in (src, native.__file__, a.catalog, __file__)},
                "views": {}}
    for view in VIEWS:
        checks = manifest["views"][view] = {}
        for scheme, colors in schemes.items():
            checks[scheme] = capture(view, scheme, colors, source, a.output)
            print(view, scheme, "OK", flush=True)
        reference = checks["original"]
        for scheme in list(schemes)[1:]:
            assert all(checks[scheme][k] == v for k,v in reference.items() if k != "binding"), view
            old, new = reference["binding"], checks[scheme]["binding"]
            assert old != new, (view,scheme,"unchanged materials")
        sheet(a.output, view, schemes)
        (a.output/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print("ALL COMPARISONS PASSED", flush=True)


if __name__ == "__main__":
    main()
