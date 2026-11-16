"""Render object appearance candidates in the unmodified MealPreparation task scene."""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import os
import sys

import gymnasium as gym
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import sapien

sys.path.insert(0, str(Path.cwd()))
from mani_skill.utils.building._mjcf_loader import MJCFLoader
from mani_skill.utils.sapien_utils import look_at
from tasks.meal_preparation import meal_preparation_long as meal

OUT = Path(__file__).resolve().parent
ROOT = Path(os.environ["ROBOCASA_ASSET_DIR"]) / "objaverse"
CATALOG = json.loads((OUT / "catalog.json").read_text())
SEED = 7
ASSETS = {
    "plate": ROOT / "plate/plate_0",
    "spoon": ROOT / "spoon/spoon_16",
    "bagel": ROOT / "bagel/bagel_5",
    "tomato": ROOT / "tomato/tomato_2",
}
ACTOR = {"plate":"plate", "spoon":"spoon", "bagel":"bread", "tomato":"ball_food"}
TASKS = {key: "MealPreparationPlaceBread-Sharpa-v1" for key in ASSETS}
TASKS.update(spoon="MealPreparationScoopTomato-Sharpa-v1", tomato="MealPreparationScoopTomato-Sharpa-v1")
VIEWS = {
    "plate": ((0.0,-0.12,0.55),(0,0,0.012),0.83),
    "spoon": ((0.0,-0.025,0.48),(0,0,0.024),0.87),
    "bagel": ((0.0,-0.095,0.23),(0,0,0.012),0.77),
    "tomato": ((0.0,-0.085,0.23),(0,0,0.012),0.62),
}


def rgba(value):
    channels = [int(value[i:i+2], 16) / 255 for i in (1,3,5)]
    return [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels] + [1.]


def ring_texture(path):
    """Project a continuous circular stripe onto the original plate UV triangles."""
    obj = ASSETS["plate"] / "visual/model_normalized_0.obj"
    verts, uv, faces = [], [], []
    for line in obj.read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "v":
            verts.append([float(v) for v in fields[1:3]])
        elif fields[0] == "vt":
            uv.append([float(fields[1]), 1-float(fields[2])])
        elif fields[0] == "f":
            faces.append([[int(v)-1 for v in item.split("/")[:2]] for item in fields[1:]])
    width, height = 2048, 1024
    coords = np.asarray(uv) * [width-1,height-1]
    verts = np.asarray(verts)
    pixels = np.zeros((height,width), dtype=np.float32)
    for face in faces:
        for i in range(1,len(face)-1):
            ids = np.asarray([face[0],face[i],face[i+1]])
            pts = coords[ids[:,1]]
            lo = np.maximum(np.floor(pts.min(0)).astype(int)-1, 0)
            hi = np.minimum(np.ceil(pts.max(0)).astype(int)+1,[width-1,height-1])
            if np.any(hi<lo):
                continue
            a,b,c = pts
            m = np.stack([b-a,c-a],axis=1)
            if abs(np.linalg.det(m)) < 1e-8:
                continue
            yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
            bc=(np.stack([xx,yy],axis=-1)-a)@np.linalg.inv(m).T
            bary=np.stack([1-bc.sum(-1),bc[...,0],bc[...,1]],axis=-1)
            inside=np.all(bary>=-.015,axis=-1)
            pos=bary@verts[ids[:,0]]
            radius=np.linalg.norm(pos,axis=-1)
            stripe=np.clip((radius-.429)/.005,0,1)*np.clip((.459-radius)/.005,0,1)
            tile=pixels[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
            np.maximum(tile,stripe*inside,out=tile)
    if np.count_nonzero(pixels) < 100:
        raise RuntimeError("Could not project a rim stripe onto the plate UVs")
    alpha=pixels[...,None]
    rgb=np.rint(np.array([243,234,214])*(1-alpha)+np.array([30,84,61])*alpha)
    Image.fromarray(rgb.astype(np.uint8),"RGB").save(path)


def recolor_bagel(path, style):
    src = np.asarray(Image.open(ASSETS["bagel"] / "visual/image0.png").convert("RGB"),
                     dtype=np.float32)/255
    if style=="light":
        out = np.power(src,0.63)*[1.06,1.08,.91]+[.045,.034,.012]
    else:
        out = np.power(src,1.32)*[.94,.66,.55]+[.025,.014,.01]
    Image.fromarray(np.uint8(np.clip(out,0,1)*255),"RGB").save(path)


def texture(path):
    return sapien.render.RenderTexture2D(filename=str(path), srgb=True)


@contextmanager
def override_preview(obj, scheme):
    parse = MJCFLoader._parse_material
    make = meal._make_material
    applied = set()

    def parse_material(loader, element):
        parse(loader, element)
        name = element.get("name")
        config = scheme.get("materials", {}).get(name)
        if config is None:
            return
        original = loader._materials[name]
        material = sapien.render.RenderMaterial(
            base_color=rgba(config["color"]) if "color" in config else original.base_color,
            roughness=config.get("roughness", original.roughness),
            metallic=config.get("metallic", original.metallic),
            specular=original.specular,
        )
        if "texture" in config:
            material.base_color_texture = texture(OUT / config["texture"])
        loader._materials[name] = material
        applied.add(name)

    def make_material(color):
        original = make(color)
        if obj=="spoon" and "grip" in scheme and np.allclose(color, [.12,.12,.14,1]):
            original.base_color = rgba(scheme["grip"])
            original.roughness = .78
            applied.add("grip")
        return original

    MJCFLoader._parse_material = parse_material
    meal._make_material = make_material
    try:
        yield applied
    finally:
        MJCFLoader._parse_material = parse
        meal._make_material = make


def render(obj, scheme_id, scheme, baseline):
    task_id=TASKS[obj]
    env=None
    try:
        with override_preview(obj,scheme) as applied:
            env=gym.make(task_id,num_envs=1,obs_mode="state",render_mode="rgb_array",
                         sim_backend="cpu",box_asset_source="procedural")
            env.reset(seed=SEED)
        expected=set(scheme.get("materials",{}))
        if "grip" in scheme:
            expected.add("grip")
        if applied!=expected:
            raise RuntimeError(f"Unexpected material bindings for {obj}/{scheme_id}: {applied} != {expected}")
        task=env.unwrapped
        if any(getattr(task,key) is None for key in ACTOR.values()):
            raise RuntimeError(f"Missing task objects in {task_id}")
        info=task.robocasa_asset_info[ACTOR[obj]]
        if Path(info["asset_dir"]).resolve()!=ASSETS[obj].resolve():
            raise RuntimeError(f"Unexpected asset: {info}")
        actor=getattr(task,ACTOR[obj])
        camera=task.scene.human_render_cameras["render_camera"].camera._render_cameras[0]
        root=actor.pose.p[0].cpu().numpy()
        offset,aim,fovy=VIEWS[obj]
        if obj=="spoon":
            # Align the overhead camera with the spoon's long local Z axis.
            from scipy.spatial.transform import Rotation
            w,x,y,z=actor.pose.q[0].cpu().tolist()
            axis=Rotation.from_quat([x,y,z,w]).apply([0,0,1])
            horizontal=np.array([axis[0],axis[1],0.])
            horizontal/=np.linalg.norm(horizontal)
            offset=np.array([0,0,offset[2]])-0.025*horizontal
            aim=np.array([0,0,aim[2]])-0.025*horizontal
            pose=look_at(root+offset,root+aim,up=tuple(horizontal))
        else:
            pose=look_at(root+np.array(offset),root+np.array(aim),up=(0,1,0))
        camera.entity.set_pose(sapien.Pose())
        camera.local_pose=sapien.Pose(pose.p[0].tolist(),pose.q[0].tolist())
        camera.set_fovy(fovy,compute_x=True)
        snap={"task":task_id,"actor_poses":{a:getattr(task,a).pose.raw_pose.cpu().tolist() for a in ACTOR.values()},
              "lid_qpos":task.box.qpos.cpu().tolist(),"camera_p":pose.p[0].tolist(),"camera_q":pose.q[0].tolist(),
              "fovy":fovy,"asset":ASSETS[obj].name}
        if baseline is not None and snap!=baseline:
            raise RuntimeError(f"Scene or camera drift: {obj}/{scheme_id}")
        pixels=env.render().cpu().numpy()[...,:3]
        if pixels.ndim==4:
            pixels=pixels[0]
        if np.ptp(pixels)==0:
            raise RuntimeError(f"Blank frame: {obj}/{scheme_id}")
        image=Image.fromarray(pixels).convert("RGB")
        image.save(OUT/f"{obj}_{scheme_id}.png")
        return image,snap
    finally:
        if env is not None:
            env.close()


def main():
    ring_texture(OUT/"plate_green_rim.png")
    for tone in ("light","dark"):
        recolor_bagel(OUT/f"bagel_{tone}_generated.png",tone)
    refs={}
    try:
        font=ImageFont.truetype("DejaVuSans.ttf",22)
    except OSError:
        font=ImageFont.load_default()
    for obj, schemes in CATALOG.items():
        images=[]
        for scheme_id, scheme in schemes.items():
            im,snap=render(obj,scheme_id,scheme,refs.get(obj))
            refs.setdefault(obj,snap)
            images.append(im)
        if len({hashlib.sha256(im.tobytes()).digest() for im in images})!=len(images):
            raise RuntimeError(f"Some {obj} variants look identical")
        w,h=images[0].size
        sheet=Image.new("RGB",(w*len(images),h+44),"#1B2027")
        draw=ImageDraw.Draw(sheet)
        for idx,(scheme,im) in enumerate(zip(schemes.values(), images)):
            sheet.paste(im,(idx*w,44))
            draw.text((idx*w+16,9),scheme["label"],font=font,fill="white")
        sheet.save(OUT/f"{obj}_comparison.png")
        print("Completed",obj,flush=True)
    payload={"seed":SEED,"views":refs,"job_id":os.environ.get("SLURM_JOB_ID"),
             "gpu_indices":os.environ.get("SLURM_JOB_GPUS"),
             "versions":{n:importlib.metadata.version(n) for n in ("sapien","mani_skill","torch")}}
    (OUT/"manifest.json").write_text(json.dumps(payload,indent=2)+"\n")


if __name__=="__main__":
    main()
