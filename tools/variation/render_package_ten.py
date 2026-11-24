"""Render original and ten complete runtime Package appearance schemes."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

import gymnasium as gym
import numpy as np
from PIL import Image, ImageDraw
import sapien

sys.path.insert(0,str(Path.cwd()))
import tasks
from tasks.package_opening import package_opening_long as package
from tasks.package_opening.appearance import CATALOG
from mani_skill.utils.sapien_utils import look_at
from render_package_opening_preview import VIEWS


def main():
    p=argparse.ArgumentParser();p.add_argument("--assets",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    package.PACKAGE_URDF_PATH=a.assets/"package/mobility.urdf"
    package.ROBOCASA_OBJECT_DIR=a.assets/"robocasa/objects/objaverse"
    catalog=json.loads(CATALOG.read_text());ids=list(catalog["schemes"])
    assert set(ids)=={"original",*[f"variant_{i}" for i in range(1,11)]}
    manifest={"job":os.environ.get("SLURM_JOB_ID"),"gpu":os.environ.get("SLURM_JOB_GPUS"),
        "backend":"CPU physics + GPU rendering","seed":7,"schemes":ids,
        "catalog_version":catalog["version"],"catalog_sha256":hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        "versions":{k:importlib.metadata.version(k) for k in ("sapien","mani_skill","torch")},"views":{}}
    for view,(part,task_id,offset,aim,fovy) in VIEWS.items():
        env=gym.make(task_id,num_envs=1,sim_backend="cpu",obs_mode="state",render_mode="rgb_array",
            robot_init_qpos_noise=0,reconfiguration_freq=0,
            package_appearance={"enabled":True,"scheme_id":"original"},
            human_render_camera_configs={"width":900,"height":900})
        images=[];reference=None;records={}
        try:
            t=env.unwrapped
            assert t.package_appearance is not None
            for scheme in ids:
                env.reset(seed=7,options={"package_appearance":{"scheme_id":scheme}})
                assert t.package_appearance.records[0]["scheme_id"]==scheme
                actor=getattr(t,part);center=actor.pose.p[0].cpu().numpy()
                pose=look_at(center+np.asarray(offset),center+np.asarray(aim),up=(0,1,0))
                camera=t.scene.human_render_cameras["render_camera"].camera._render_cameras[0]
                camera.entity.set_pose(sapien.Pose());camera.local_pose=sapien.Pose(pose.p[0].tolist(),pose.q[0].tolist())
                camera.set_fovy(fovy,compute_x=True)
                state={"task":task_id,"poses":{n:getattr(t,n).pose.raw_pose.cpu().tolist() for n in ("box","apple","plate") if getattr(t,n,None) is not None},
                    "qpos":t.box.qpos.cpu().tolist(),"camera_p":pose.p[0].tolist(),"camera_q":pose.q[0].tolist(),"fovy":fovy}
                if reference is None:reference=state
                assert state==reference,(view,scheme,"scene drift")
                image=env.render().detach().cpu().numpy()[...,:3]
                if image.ndim==4:image=image[0]
                assert np.ptp(image)>0,(view,scheme,"blank")
                im=Image.fromarray(image);im.save(a.output/f"{view}_{scheme}.png");images.append(im)
                records[scheme]=dict(t.package_appearance.records[0])
            assert len({hashlib.sha256(im.tobytes()).hexdigest() for im in images})==len(ids),(view,"duplicate images")
            w,h=400,400;sheet=Image.new("RGB",(w*4,(h+30)*3),(25,29,34));draw=ImageDraw.Draw(sheet)
            for i,(scheme,im) in enumerate(zip(ids,images)):
                x=(i%4)*w;y=(i//4)*(h+30);draw.text((x+12,y+8),scheme,fill="white");sheet.paste(im.resize((w,h)),(x,y+30))
            sheet.save(a.output/f"{view}_comparison.jpg",quality=95)
            manifest["views"][view]={"reference":reference,"records":records}
            (a.output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
            print("PASS PREVIEW",view,flush=True)
        finally:env.close()


if __name__=="__main__":main()
