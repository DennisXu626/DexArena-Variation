"""Render Package Opening appearance candidates in the actual task environments."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

import gymnasium as gym
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import sapien

sys.path.insert(0, str(Path.cwd()))
from mani_skill.utils.sapien_utils import look_at
from tasks.package_opening import package_opening_long as package

from tasks.package_opening.appearance import CATALOG, linear_rgba, recolor_apple

CATALOG = Path(__file__).resolve().with_name("package_opening_catalog.json")
VIEWS = {
    "box_closed": ("box", "PackageOpeningOpenPackage-Sharpa-v1",
                   (0.0, -0.36, 0.34), (0.0, 0.0, -.015), .85),
    "box_open": ("box", "PackageOpeningExtractApple-Sharpa-v1",
                 (0.0, -0.40, 0.43), (0.0, 0.0, .05), .93),
    "apple": ("apple", "PackageOpeningExtractApple-Sharpa-v1",
              (0.0, -.025, .24), (0.0, 0.0, .004), .65),
    "apple_in_box": ("apple", "PackageOpeningExtractApple-Sharpa-v1",
                     (0.0, -.31, .59), (0.0, 0.0, .037), .76),
    "plate": ("plate", "PackageOpeningExtractApple-Sharpa-v1",
              (0.0, -.04, .36), (0.0, 0.0, .01), .80),
}


def apple_texture(source, target, output, include_yellow_skin=False):
    with Image.open(source) as image:
        pixels, coverage = recolor_apple(image, target, include_yellow_skin)
    Image.fromarray(pixels).save(output)
    return coverage


def body_render(entity):
    result = entity.find_component_by_type(sapien.render.RenderBodyComponent)
    if result is None:
        raise RuntimeError(f"No renderer for {entity.name}")
    return result


def change_material(material, scheme, color=None, texture=None):
    material.roughness = scheme["roughness"]
    material.metallic = scheme["metallic"]
    if color is not None:
        material.base_color_texture = None
        material.base_color = linear_rgba(color)
    if texture is not None:
        material.base_color_texture = sapien.render.RenderTexture2D(filename=str(texture), srgb=True)


def tint_box(task, scheme):
    handled = {"body": 0, "flap": 0, "floor": 0, "tab": 0, "accent": 0}
    art, = task.box._objs
    for link in art.get_links():
        name = link.name.rsplit("_", 2)
        if len(name) < 2 or name[-2] != "link" or name[-1] not in ("0", "1", "2"):
            continue
        is_flap = name[-1] in ("0", "1")
        for shape in body_render(link.entity).render_shapes:
            if isinstance(shape, sapien.render.RenderShapeBox):
                role = "tab" if is_flap else "floor"
                materials = [shape.material]
            else:
                role = "flap" if is_flap else "body"
                materials = [part.material for part in shape.parts]
            for material in materials:
                r, g, b, _ = material.base_color
                if role == "body" and r > .7 and g < .25 and b > .3:
                    handled["accent"] += 1
                    continue
                change_material(material, scheme, color=scheme["colors"][role])
                handled[role] += 1
    if (handled["flap"], handled["tab"], handled["floor"], handled["accent"]) != (2, 2, 1, 1):
        raise RuntimeError(f"Unexpected carton visual binding: {handled}")
    return handled


def tint_actor(actor, scheme, color=None, texture=None):
    entity, = actor._objs
    shapes = body_render(entity).render_shapes
    materials = [part.material for shape in shapes for part in shape.parts]
    if len(materials) != 1:
        raise RuntimeError(f"Expected one input visual slot, found {len(materials)}")
    change_material(materials[0], scheme, color, texture)


def capture(task_id, part, offset, aim, fovy, scheme_id, scheme, out, textures):
    env = gym.make(task_id, num_envs=1, sim_backend="cpu", obs_mode="state",
                   render_mode="rgb_array",
                   human_render_camera_configs={"width": 900, "height": 900})
    try:
        env.reset(seed=7)
        task = env.unwrapped
        actor = getattr(task, part)
        binding = None
        if scheme_id != "original":
            if part == "box":
                binding = tint_box(task, scheme)
            elif part == "apple":
                tint_actor(actor, scheme, texture=textures[scheme_id])
            else:
                tint_actor(actor, scheme, color=scheme["color"])
        camera = task.scene.human_render_cameras["render_camera"].camera._render_cameras[0]
        center = actor.pose.p[0].cpu().numpy()
        pose = look_at(center + np.asarray(offset), center + np.asarray(aim), up=(0, 1, 0))
        camera.entity.set_pose(sapien.Pose())
        camera.local_pose = sapien.Pose(pose.p[0].tolist(), pose.q[0].tolist())
        camera.set_fovy(fovy, compute_x=True)
        pixels = env.render().cpu().numpy()[..., :3]
        pixels = pixels[0] if pixels.ndim == 4 else pixels
        if np.ptp(pixels) == 0:
            raise RuntimeError("Blank preview")
        image = Image.fromarray(pixels).convert("RGB")
        states = {name: getattr(task, name).pose.raw_pose.cpu().tolist()
                  for name in ("box", "apple", "plate") if getattr(task, name, None) is not None}
        state = {"task": task_id, "states": states, "box_qpos": task.box.qpos.cpu().tolist(),
                 "camera_p": pose.p[0].tolist(), "camera_q": pose.q[0].tolist(), "fovy": fovy}
        return image, state, binding
    finally:
        env.close()


def contact_sheet(images, labels, destination):
    w, h = images[0].size
    sheet = Image.new("RGB", (w * len(images), h + 44), "#1B2027")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 25)
    except OSError:
        font = ImageFont.load_default()
    for i, (label, image) in enumerate(zip(labels, images)):
        sheet.paste(image, (i * w, 44))
        draw.text((i * w + 16, 8), label, fill="white", font=font)
    sheet.save(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--views", choices=VIEWS, nargs="+", default=list(VIEWS))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = args.assets.resolve()
    package.PACKAGE_URDF_PATH = root / "package/mobility.urdf"
    package.ROBOCASA_OBJECT_DIR = root / "robocasa/objects/objaverse"
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    apple_source = package.ROBOCASA_OBJECT_DIR / "apple/apple_0/visual/image0.png"
    textures, fractions = {}, {}
    for scheme_id, scheme in catalog["objects"]["apple"].items():
        if scheme_id != "original":
            textures[scheme_id] = args.output / f"apple_{scheme_id}_generated.png"
            fractions[scheme_id] = apple_texture(
                apple_source, scheme["color"], textures[scheme_id],
                include_yellow_skin=scheme.get("include_yellow_skin", False),
            )
    manifest = {"seed": 7, "catalog": catalog["version"], "views": {},
                "job": os.environ.get("SLURM_JOB_ID"), "apple_mask_fraction": fractions,
                "versions": {key: importlib.metadata.version(key)
                             for key in ("sapien", "mani_skill", "torch")}}
    for view in args.views:
        part, task_id, offset, aim, fovy = VIEWS[view]
        images, labels, bindings = [], [], {}
        reference = None
        for scheme_id, scheme in catalog["objects"][part].items():
            image, state, binding = capture(task_id, part, offset, aim, fovy,
                                            scheme_id, scheme, args.output, textures)
            if reference is None:
                reference = state
            elif reference != state:
                raise RuntimeError(f"Scene or camera changed in {view}/{scheme_id}")
            image.save(args.output / f"{view}_{scheme_id}.png")
            images.append(image)
            labels.append(scheme["label"])
            if binding:
                bindings[scheme_id] = binding
        if len({hashlib.sha256(image.tobytes()).digest() for image in images}) != len(images):
            raise RuntimeError(f"Duplicate variants in {view}")
        contact_sheet(images, labels, args.output / f"{view}_comparison.png")
        manifest["views"][view] = {"state": reference, "bindings": bindings}
        print("Completed", view, flush=True)
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                                   encoding="utf-8")


if __name__ == "__main__":
    main()
