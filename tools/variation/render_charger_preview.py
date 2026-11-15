"""Render the Charger A3 catalog in the original InsertPlug scene."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys

import gymnasium as gym
import numpy as np
import sapien
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def charger_materials(env):
    """Identify material bindings by the original box half sizes."""
    base = env.unwrapped
    entity, = base.charger._objs
    body = entity.find_component_by_type(sapien.render.RenderBodyComponent)
    groups = {"body": [], "prongs": []}
    for shape in body.render_shapes:
        if np.allclose(shape.half_size, base.charger_half):
            group = "body"
        elif np.allclose(shape.half_size, base.charger_prong_half):
            group = "prongs"
        else:
            raise ValueError(f"Unexpected Charger box size: {shape.half_size}")
        groups[group].append(shape)
    if [len(groups["body"]), len(groups["prongs"])] != [1, 2]:
        raise ValueError("Expected one Charger body and two prongs")
    return groups


def save_comparison(frames, path):
    width, height = frames[0][1].size
    title_height = 36
    comparison = Image.new("RGB", (width * 2, (height + title_height) * 2))
    draw = ImageDraw.Draw(comparison)
    for index, (name, image) in enumerate(frames):
        x = (index % 2) * width
        y = (index // 2) * (height + title_height)
        draw.text((x + 12, y + 10), name, fill="white")
        comparison.paste(image, (x, y + title_height))
    comparison.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog_path = ROOT / "tasks/assets/variation/drawer_plug/v1/catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)

    import tasks  # Register environments.

    task_id = "DrawerPlugInsertPlug-Sharpa-v1"
    seed = 7
    env = gym.make(task_id, num_envs=1, obs_mode="state", render_mode="rgb_array")
    try:
        env.reset(seed=seed)
        groups = charger_materials(env)
        # Add a fixed close-up to complement the original task render camera.
        base = env.unwrapped
        center = base.charger.pose.p[0].cpu().numpy()
        camera = base.scene.human_render_cameras["render_camera"].camera._render_cameras[0]
        task_pose = camera.entity.pose
        from mani_skill.utils import sapien_utils

        view_pose = sapien_utils.look_at(center + [0.19, -0.17, 0.16], center)
        closeup_pose = sapien.Pose(view_pose.p[0].tolist(), view_pose.q[0].tolist())
        frames = {"task": [], "closeup": []}
        for scheme_id, scheme in catalog["schemes"].items():
            for group, shapes in groups.items():
                params = scheme["body"] if group == "body" else catalog["prongs"]
                for shape in shapes:
                    for part in shape.parts:
                        material = part.material
                        if scheme_id == "original":
                            np.testing.assert_allclose(material.base_color, params["base_color"])
                            np.testing.assert_allclose(material.roughness, params["roughness"])
                            np.testing.assert_allclose(material.metallic, params["metallic"])
                        else:
                            material.base_color = params["base_color"]
                            material.roughness = params["roughness"]
                            material.metallic = params["metallic"]

            for view, pose in (("task", task_pose), ("closeup", closeup_pose)):
                camera.entity.set_pose(pose)
                pixels = env.render().cpu().numpy()[..., :3]
                if pixels.ndim == 4:
                    pixels = pixels[0]
                if np.ptp(pixels) == 0:
                    raise RuntimeError(f"Blank {view} frame for {scheme_id}")
                image = Image.fromarray(pixels)
                image.save(args.output / f"{scheme_id}_{view}.png")
                frames[view].append((scheme_id, image))

        for view, images in frames.items():
            save_comparison(images, args.output / f"comparison_{view}.png")

        manifest = {
            "task_id": task_id,
            "seed": seed,
            "task_camera_pose": {"p": task_pose.p.tolist(), "q": task_pose.q.tolist()},
            "charger_pose": base.charger.pose.raw_pose.cpu().tolist(),
            "closeup_pose": {"p": closeup_pose.p.tolist(), "q": closeup_pose.q.tolist()},
            "versions": {
                name: importlib.metadata.version(name)
                for name in ("torch", "sapien", "mani_skill", "gymnasium")
            },
            "catalog": catalog,
        }
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        env.close()


if __name__ == "__main__":
    main()
