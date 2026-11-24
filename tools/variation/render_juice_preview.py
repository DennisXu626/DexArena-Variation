"""Render Juice Preparation appearance variants in the actual Sharpa tasks."""
import argparse
import colorsys
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

import gymnasium as gym
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import sapien

from mani_skill.utils.sapien_utils import look_at
from tasks.juice_preparation import juice_preparation_apple_to_blender as apple_task

VIEWS = {
    "fridge_closed": ("OpenFridge", "native closed-door reset"),
    "fridge_open": ("AppleToBlender", "native open-door reset with apple"),
    "apple_in_fridge": ("AppleToBlender", "native apple position"),
    "apple_in_pitcher": ("AppleToBlender", "controlled apple placement in pitcher"),
    "loose_lid": ("PlaceLid", "native loose-lid reset"),
    "seated_lid_button": ("PressButton", "native integrated-lid reset"),
}
LABELS = {"original": "Original", "variant_1": "Sage / Golden Apple",
          "variant_2": "Terracotta / Green Apple"}


def comparison_columns(schemes):
    """Bind each image and label to its stable ID, regardless of JSON order."""
    return [(scheme, f"{scheme} | {LABELS.get(scheme, scheme)}") for scheme in schemes]


def rgb_hex(color):
    return np.array([int(color[i:i+2], 16)/255 for i in (1, 3, 5)])


def linear_rgba(color):
    rgb = rgb_hex(color)
    return [*np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4), 1.]


def material_groups(actor):
    if actor is None:
        return []
    raw, = actor._objs
    links = [(x.name, x.entity) for x in raw.get_links()] if hasattr(raw, "get_links") else [(raw.name, raw)]
    groups = []
    for name,entity in links:
        component = entity.find_component_by_type(sapien.render.RenderBodyComponent)
        if component is None:
            continue
        for shape in component.render_shapes:
            mats = [shape.material] if isinstance(shape, sapien.render.RenderShapePrimitive) else [
                p.material for p in shape.parts]
            groups.extend((name, getattr(shape, "filename", ""), material) for material in mats)
    return groups


def texture_pixels(texture):
    pixels = texture.download()
    return np.asarray(Image.fromarray(pixels).convert("RGBA")).copy()


def recolor_apple(rgba, color):
    source = Image.fromarray(rgba).convert("RGB")
    hsv = np.asarray(source.convert("HSV"), dtype=np.float32) / 255
    hue,sat,value = np.moveaxis(hsv,-1,0)
    target_h,target_s,_ = colorsys.rgb_to_hsv(*rgb_hex(color))
    warm = (hue + .5) % 1 - .5
    weight = np.clip((warm+.13)/.095,0,1) * np.clip((.22-warm)/.06,0,1)
    weight *= np.clip((sat-.10)/.30,0,1) * np.clip((value-.20)/.27,0,1)
    mapped = np.stack(((target_h + .19*warm) % 1,
                       np.clip(sat * .36 + target_s*.42,0,1),
                       np.clip(value*.97+.015,0,1)),axis=-1)
    colors = np.asarray(Image.fromarray(np.rint(mapped*255).astype(np.uint8),"HSV").convert("RGB"))
    rgba[..., :3] = np.rint((1-weight[...,None])*np.asarray(source) + weight[...,None]*colors)
    return rgba


def recolor_shell(rgba, color):
    rgb = rgba[..., :3].astype(np.float32) / 255
    luminance = rgb @ np.array([.2126,.7152,.0722], dtype=np.float32)
    strength = np.clip((luminance-.05)/.25, .48, .88) * np.clip((.96-luminance)/.20, 0, 1)
    shade = np.clip((.37 + luminance)[...,None]*rgb_hex(color) + (luminance*.23)[...,None],0,1)
    rgba[..., :3] = np.rint(((1-strength[...,None])*rgb + strength[...,None]*shade)*255)
    return rgba


def snapshot(groups):
    result = []
    for link, fn, m in groups:
        tex = m.base_color_texture
        result.append({"link": link, "mesh": Path(fn).name if fn else "", "color": list(m.base_color),
                       "roughness": float(m.roughness), "metallic": float(m.metallic),
                       "texture_sha256": None if tex is None else hashlib.sha256(texture_pixels(tex).tobytes()).hexdigest()})
    return result


def appearance(task, recipe, stage):
    actors = {x:getattr(task,x,None) for x in ("fridge", "apple", "blender", "lid")}
    groups = {k:material_groups(v) for k,v in actors.items()}
    native = {k:snapshot(v) for k,v in groups.items()}
    touched = {k:[] for k in groups}
    keepalive = []
    for actor, slots in groups.items():
        for i,(link, fn, material) in enumerate(slots):
            mesh = Path(fn).stem.lower() if fn else ""
            role = None
            if actor == "fridge":
                c = np.asarray(material.base_color)
                if link.endswith(("fridge_body","fridge_door")) and np.allclose(
                    c, [.89411765,.90980392,.92156863,1],atol=.005):
                    role = "fridge"
            elif actor == "apple" and material.base_color_texture is not None:
                role = "apple"
            elif actor == "lid" or link.endswith("integrated_lid"):
                role = "lid"
            elif actor == "blender" and (mesh == "body001" or (
                not mesh and link.endswith(("object","root")))):
                role = "blender"
            if role is None:
                continue
            touched[actor].append((i,role))
            if recipe:
                if role == "fridge":
                    material.base_color = linear_rgba(recipe[role])
                    material.roughness = recipe["fridge_roughness"]
                else:
                    source = material.base_color_texture
                    if source is None:
                        raise RuntimeError(f"{role} has no base color texture: {link}/{mesh}")
                    transform = recolor_apple if role == "apple" else recolor_shell
                    pixels = transform(texture_pixels(source), recipe[role])
                    texture = sapien.render.RenderTexture2D(pixels, "R8G8B8A8Unorm", srgb=True)
                    material.base_color_texture = texture
                    keepalive.append(texture)
    wanted = {"fridge" if actors["fridge"] is not None else "",
              "apple" if actors["apple"] is not None else "",
              "blender" if actors["blender"] is not None else "",
              "lid" if actors["lid"] is not None or stage == "PressButton" else ""} - {""}
    roles = {role for values in touched.values() for _,role in values}
    if roles != wanted:
        raise RuntimeError(f"Unexpected bindings: wanted={wanted} found={touched} native={native}")
    after = {k:snapshot(v) for k,v in groups.items()}
    for k,slots in touched.items():
        indices = {i for i,_ in slots}
        assert all((m != after[k][i]) == (bool(recipe) and i in indices)
                   for i,m in enumerate(native[k])), (k,touched[k])
    return {"native": native, "actual": after, "bindings": touched}, keepalive


def xyz(actor):
    return actor.pose.p[0].detach().cpu().numpy().copy()


def framing(task, view):
    if view == "fridge_closed":
        target = xyz(task.fridge) + [-.035,.015,.25]
        return target, [-.87,.33,.25], .77
    if view == "fridge_open":
        target = xyz(task.fridge) + [-.04,.14,.25]
        return target, [-.94,-.32,.30], .80
    if view == "apple_in_fridge":
        return xyz(task.apple) + [0,0,.013], [-.40,.018,.12], .62
    if view == "apple_in_pitcher":
        return xyz(task.apple) + [0,0,.03], [.10,-.09,.59], .63
    center = xyz(task.blender)
    if view == "loose_lid":
        target = (center + xyz(task.lid))/2 + [0,0,.17]
        return target,[.48,-.48,.40],.78
    direction = xyz(task.button_link)[:2] - center[:2]
    direction /= np.linalg.norm(direction)
    tangent = np.array([-direction[1], direction[0]])
    offset = .62*direction + .14*tangent
    target = center + [.0,.0,.08]
    return target,[*offset,.22],.82


def capture(out, view, scheme, recipe):
    stage,description = VIEWS[view]
    task_id = "JuicePreparation" + stage + "-Sharpa-v1"
    env = gym.make(task_id, num_envs=1, sim_backend="cpu", obs_mode="state",
                   render_mode="rgb_array", robot_init_qpos_noise=0.,
                   human_render_camera_configs={"width": 960,"height": 800})
    try:
        env.reset(seed=7)
        task = env.unwrapped
        if view == "apple_in_pitcher":
            geom = task.blender_geometry
            nominal = np.array(geom.seat_position, dtype=float, copy=True)
            nominal[:2] += xyz(task.blender)[:2] - np.asarray(geom.blender_root)[:2]
            nominal[2] -= .085
            task.apple.set_pose(sapien.Pose(p=nominal.tolist(),q=task.apple.pose.q[0].cpu().tolist()))
        info, textures = appearance(task, recipe, stage)
        target,offset,fovy = framing(task,view)
        camera = task.scene.human_render_cameras["render_camera"].camera._render_cameras[0]
        pose = look_at(target + np.asarray(offset),target)
        camera.entity.set_pose(sapien.Pose())
        camera.local_pose = sapien.Pose(pose.p[0].tolist(),pose.q[0].tolist())
        camera.set_fovy(fovy,compute_x=True)
        image = env.render()[..., :3].detach().cpu().numpy()
        if image.ndim == 4:
            image = image[0]
        assert np.ptp(image) > 0
        Image.fromarray(image).save(out/f"{view}_{scheme}.png")
        state = {}
        for k in ("fridge","apple","blender","lid"):
            a = getattr(task,k,None)
            if a is not None:
                state[k] = a.pose.raw_pose.cpu().tolist()
                if hasattr(a,"get_qpos"):
                    state[k+"_qpos"] = a.get_qpos().cpu().tolist()
        state["robot_qpos"] = task.agent.robot.get_qpos().cpu().tolist()
        return {"task":task_id,"state_label":description,"state":state,
                "camera":pose.raw_pose.cpu().tolist(),"fovy":fovy,"appearance":info}
    finally:
        env.close()


def contact_sheet(out,view,schemes):
    columns = comparison_columns(schemes)
    if not columns:
        raise ValueError("No schemes to compare")
    panels = [Image.open(out/f"{view}_{scheme}.png").convert("RGB") for scheme, _ in columns]
    w,h = panels[0].size
    cols=3;rows=(len(panels)+cols-1)//cols
    sheet=Image.new("RGB",(cols*w,rows*(h+44)),"#1B2027")
    try:
        font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",23)
    except OSError:
        font=ImageFont.load_default()
    draw=ImageDraw.Draw(sheet)
    for i,((scheme,label),panel) in enumerate(zip(columns,panels)):
        x=(i%cols)*w;y=(i//cols)*(h+44)
        draw.text((x+15,y+8),label,fill="white",font=font)
        sheet.paste(panel,(x,y+44))
    sheet.save(out/f"{view}_comparison.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--views",nargs="+",choices=VIEWS,default=list(VIEWS))
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    schemes = json.loads(args.catalog.read_text())["schemes"]
    manifest = {"job_id":os.getenv("SLURM_JOB_ID"),"gpu":os.getenv("SLURM_JOB_GPUS"),
                "seed":7,"num_envs":1,"physics":"CPU","rendering":"GPU",
                "versions":{k:importlib.metadata.version(k) for k in ("sapien","mani_skill","torch")},
                "views":{}}
    for view in args.views:
        rows = manifest["views"][view] = {}
        for scheme,recipe in schemes.items():
            rows[scheme] = capture(args.output,view,scheme,recipe)
            print(view,scheme,"OK",flush=True)
        expected = rows["original"]
        for row in rows.values():
            assert all(row[k] == v for k,v in expected.items() if k != "appearance"),view
            assert row["appearance"]["native"] == expected["appearance"]["native"],view
        contact_sheet(args.output,view,schemes)
        (args.output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print("ALL VIEWS PASSED",flush=True)


if __name__ == "__main__":
    main()
