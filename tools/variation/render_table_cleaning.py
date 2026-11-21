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


def linear_hex(color):
    values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values] + [1.]


def render_materials(actor):
    entity, = actor._objs
    body = entity.find_component_by_type(sapien.render.RenderBodyComponent)
    mesh, primitives = [], []
    for shape in body.render_shapes:
        if isinstance(shape, sapien.render.RenderShapePrimitive):
            primitives.append(shape.material)
        else:
            mesh.extend(part.material for part in shape.parts)
    return mesh, primitives


def one(values, role):
    if len(values) != 1:
        raise RuntimeError(f"{role}: expected one material slot, got {len(values)}")
    return values[0]


def texture_info(texture):
    if texture is None:
        return None
    pixels = texture.download()
    return {"shape": list(pixels.shape), "sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
            "srgb": texture.is_srgb}


def apply_appearance(task, scheme, colors, sugar_original):
    pan, grip = render_materials(task.pan)
    body = one([m for m in pan if m.base_color[2] > .8 and m.base_color[0] < .1], "pan body")
    if len(pan) != 2:
        raise RuntimeError(f"Expected two imported dustpan parts, got {len(pan)}")
    sleeve = one(grip, "grip")
    bin_parts, _ = render_materials(task.bin)
    frame = one([m for m in bin_parts if m.base_color_texture is None], "bin frame")
    wall = one([m for m in bin_parts if m.base_color_texture is not None], "bin wall")
    wall_signature = texture_info(wall.base_color_texture)
    shared_texture = None
    if scheme != "original":
        body.base_color = linear_hex(colors["pan"])
        body.roughness = colors["pan_roughness"]
        frame.base_color = linear_hex(colors["bin_frame"])
        rgba = np.asarray(sugar_original.convert("RGBA")).copy()
        rgba[..., :3] = np.rint(
            rgba[..., :3].astype(np.float32) * np.asarray(colors["sugar_rgb_multipliers"])
        ).clip(0, 255).astype(np.uint8)
        shared_texture = sapien.render.RenderTexture2D(
            np.ascontiguousarray(rgba), "R8G8B8A8Unorm", srgb=True,
        )
    sugar_slots = []
    for actor in task.debris:
        mesh, _ = render_materials(actor)
        material = one(mesh, "sugar")
        if material.base_color_texture is None:
            raise RuntimeError("Original sugar texture was not bound")
        if shared_texture is not None:
            material.base_color_texture = shared_texture
        sugar_slots.append(texture_info(material.base_color_texture))
    assert wall_signature == texture_info(wall.base_color_texture)
    return {"pan_body_color": list(body.base_color), "pan_roughness": body.roughness,
            "bin_frame_color": list(frame.base_color), "bin_frame_roughness": frame.roughness,
            "bin_wall_color": list(wall.base_color), "bin_wall_texture": wall_signature,
            "grip_color": list(sleeve.base_color), "grip_roughness": sleeve.roughness,
            "sugar_textures": sugar_slots}


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
                   render_mode="rgb_array", robot_init_qpos_noise=0.,
                   human_render_camera_configs={"width": 900, "height": 720})
    try:
        env.reset(seed=7)
        task = env.unwrapped
        if focus == "bin":
            place_for_bin_preview(task)
        binding = apply_appearance(task, scheme, colors, sugar_original)
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
    w,h = images[0].size
    canvas = Image.new("RGB", (w*len(images), h+44), "#1B2027")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 23)
    for i, (img,label) in enumerate(zip(images, LABELS)):
        canvas.paste(img,(i*w,44))
        draw.text((i*w+15,8),label,font=font,fill="white")
    canvas.save(out / f"{view}_comparison.png")


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
        for scheme in ("variant_1", "variant_2"):
            assert all(checks[scheme][k] == v for k,v in reference.items() if k != "binding"), view
            old, new = reference["binding"], checks[scheme]["binding"]
            for part in ("bin_wall_color", "bin_wall_texture", "grip_color", "grip_roughness"):
                assert old[part] == new[part], part
            for part in ("pan_body_color", "bin_frame_color", "sugar_textures"):
                assert old[part] != new[part], part
        sheet(a.output, view, schemes)
        (a.output/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print("ALL COMPARISONS PASSED", flush=True)


if __name__ == "__main__":
    main()
