"""Compare three appearance sets in the native meal preparation environments."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path

import torch
from render_meal_objects import (
    ACTOR, CATALOG, OUT, SEED, Image, ImageDraw, ImageFont, gym, look_at,
    meal, np, override_preview, recolor_bagel, rgba, ring_texture, sapien,
)

STAGES = {
    "open": "MealPreparationOpenLunchBox-Sharpa-v1",
    "bread": "MealPreparationPlaceBread-Sharpa-v1",
    "tomato": "MealPreparationScoopTomato-Sharpa-v1",
    "long": "MealPreparationLong-Sharpa-v1",
}
OBJECT_SCHEMES = [
    ["original"]*4,
    ["cobalt_glaze","silver_navy","light_toast","golden"],
    ["green_rim","graphite_orange","dark_toast","purple_red"],
]
BOX_SURFACES = {
    (.70,.50,.30,1.): "box_base", (.86,.72,.52,1.): "inner_floor",
    (.78,.57,.34,1.): "box_lid",
}
BOX_CATALOG=json.loads((OUT/"lunch_box_catalog.json").read_text())["schemes"]
BOX_SCHEMES=["original","mist_blue_matte","brick_red_satin"]
DATA=Path("/mnt/ceph2/DexArena/data/sharpa")


@contextmanager
def appearance(index, stage):
    scheme={"materials":{}}
    for obj,key in zip(CATALOG, OBJECT_SCHEMES[index]):
        if stage=="open" and obj!="spoon":
            continue
        spec=CATALOG[obj][key]
        scheme["materials"].update(spec.get("materials",{}))
        if "grip" in spec:
            scheme["grip"]=spec["grip"]
    expected=set(scheme["materials"])
    if "grip" in scheme:
        expected.add("grip")
    original=meal._build_procedural_lidded_box
    box=BOX_CATALOG[BOX_SCHEMES[index]]
    box_applied=set()

    def build(*args,**kwargs):
        make=meal._make_material
        def material(color):
            part=BOX_SURFACES.get(tuple(color))
            if part not in box:
                return make(color)
            box_applied.add(part)
            return sapien.render.RenderMaterial(base_color=rgba(box[part]),
                roughness=box["roughness"],metallic=box["metallic"],specular=.25)
        meal._make_material=material
        try:
            return original(*args,**kwargs)
        finally:
            meal._make_material=make

    with override_preview("spoon",scheme) as applied:
        meal._build_procedural_lidded_box=build
        try:
            yield
        finally:
            meal._build_procedural_lidded_box=original
    assert applied==expected, (stage,index,applied,expected)
    assert box_applied==set(BOX_SURFACES.values()).intersection(box)


def value(x):
    if isinstance(x,sapien.Pose):
        return {"p":value(x.p),"q":value(x.q)}
    if torch.is_tensor(x):
        return value(x.detach().cpu().numpy())
    if isinstance(x,np.ndarray):
        if np.issubdtype(x.dtype,np.number) and x.size>32:
            return {"shape":list(x.shape),"sha256":hashlib.sha256(x.tobytes()).hexdigest()}
        return x.tolist()
    if isinstance(x,np.generic):
        return x.item()
    if isinstance(x,(float,int,str,bool,type(None))):
        return x
    if isinstance(x,(list,tuple)):
        return [value(v) for v in x]
    if isinstance(x,dict):
        return {k:value(v) for k,v in x.items()}
    raise TypeError(type(x))


def properties(obj, keys):
    out={}
    for key in keys.split():
        prop=getattr(obj,key,None)
        if prop is not None:
            out[key]=value(prop)
    return out


def physics(task):
    signatures={}
    for attr in ("box",*ACTOR.values()):
        obj=getattr(task,attr)
        if obj is None:
            continue
        links=obj.get_links() if attr=="box" else [obj]
        built=[]
        for link in links:
            for raw in link._objs:
                component=raw
                if not hasattr(component,"get_collision_shapes"):
                    component=(raw.find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)
                               or raw.find_component_by_type(sapien.physx.PhysxRigidStaticComponent))
                assert component is not None
                shapes=[]
                for shape in component.get_collision_shapes():
                    entry=properties(shape,"local_pose half_size radius half_length vertices triangles indices scale density contact_offset rest_offset")
                    entry["type"]=type(shape).__name__
                    if hasattr(shape,"get_collision_groups"):
                        entry["collision_groups"]=value(shape.get_collision_groups())
                    mat=shape.physical_material
                    entry["physical_material"]=properties(mat,"static_friction dynamic_friction restitution")
                    shapes.append(entry)
                built.append({"mass_properties":properties(component,"mass inertia cmass_local_pose kinematic"),
                              "shapes":shapes})
        signatures[attr]=built
    signatures["lid_qlimits"]=value(task.box.get_qlimits())
    component=task.box.get_links()[-1]._objs[0]
    joint=getattr(component,"joint",None)
    if joint is not None:
        signatures["lid_joint"]=properties(joint,"type limits pose_in_parent pose_in_child stiffness damping force_limit friction drive_target drive_velocity_target")
    return signatures


def env_for(stage,index,seed,extra=None):
    with appearance(index,stage):
        env=gym.make(STAGES[stage],num_envs=1,obs_mode="state",render_mode="rgb_array",
                     sim_backend="cpu",box_asset_source="procedural",**(extra or {}))
        env.reset(seed=seed)
    task=env.unwrapped
    assert task.box is not None and task.spoon is not None
    if stage!="open":
        assert all(getattr(task,x) is not None for x in ACTOR.values())
    return env


def truth(info,name):
    return bool(torch.as_tensor(info[name]).reshape(-1)[0])


def test_predicates(task,stage):
    trace=[]
    def evaluate(label,steps=1):
        frames=[]
        for _ in range(steps):
            task._elapsed_steps += 1
            info=task.evaluate()
            keys=("success","success_condition","stage_box_open","stage_bread_done","stage_ball_done",
                  "ball_on_plate","bread_on_plate","open_process_ok","ball_process_ok","stage_id")
            frames.append({k:value(info[k]) for k in keys if k in info})
        trace.append({"case":label,"frames":frames})
        return info

    def place(attr,away=False):
        actor=getattr(task,attr)
        xyz=task.plate.pose.p.clone()
        xyz[:,2] += .035
        if attr=="ball_food":
            xyz[:,1] += .060
        if away:
            xyz[:,1] += .36
        actor.set_pose(meal.Pose.create_from_pq(xyz))
        actor.set_linear_velocity(torch.zeros_like(xyz))
        actor.set_angular_velocity(torch.zeros_like(xyz))

    def assert_then_hold(key,label):
        window=int(task.success_hold_steps)
        info=evaluate(label+"_one_short",window-1)
        assert not truth(info,key),(stage,label,key)
        info=evaluate(label+"_full_hold")
        assert truth(info,key),(stage,label,key)

    initial=evaluate("initial")
    assert not truth(initial,"success"),stage
    if stage in ("open","long"):
        ids=torch.tensor([0],device=task.device)
        task._set_box_lid_qpos(ids,task.open_threshold-.02)
        task.ever_left_hand_opened_box.fill_(True)
        info=evaluate("opening_below_threshold")
        assert not truth(info,"stage_box_open")
        if stage=="long":
            place("bread")
            info=evaluate("bread_before_open",task.success_hold_steps)
            assert not truth(info,"stage_bread_done")
            place("bread",away=True)
        task._set_box_lid_qpos(ids,task.open_threshold+.03)
        assert_then_hold("stage_box_open","open")
    if stage in ("bread","long"):
        place("bread",away=True)
        info=evaluate("bread_outside_plate")
        assert not truth(info,"stage_bread_done")
        place("bread")
        evaluate("interrupted_bread_hold",8)
        place("bread",away=True)
        info=evaluate("bread_hold_reset")
        assert not truth(info,"stage_bread_done")
        place("bread")
        assert_then_hold("stage_bread_done","bread")
    if stage in ("tomato","long"):
        flags=("initial_ball_in_box","ever_ball_left_box","ever_ball_scooped",
               "ever_ball_transport","ever_right_hand_used_spoon")
        place("ball_food")
        for flag in flags:
            getattr(task,flag).fill_(True)
        task.ever_right_hand_used_spoon.fill_(False)
        info=evaluate("tomato_on_plate_without_spoon_history",task.success_hold_steps)
        assert truth(info,"ball_on_plate") and not truth(info,"stage_ball_done")
        task.ever_right_hand_used_spoon.fill_(True)
        assert_then_hold("stage_ball_done","tomato")
    assert truth(task.evaluate(),"success"),stage
    return trace


def recorded_actions(stage,index):
    if stage=="long":
        return None
    episode=None
    for meta_file in sorted((DATA/STAGES[stage]/"replay").glob("source_*/meta.json")):
        m=json.loads(meta_file.read_text())
        if m.get("final_success") and (meta_file.parent/"episode.npz").is_file():
            episode=meta_file.parent
            break
    if episode is None:
        return None
    with np.load(episode/"episode.npz",allow_pickle=False) as series:
        actions=series["actions"].astype(np.float32)
        recorded=series["success"].reshape(-1).tolist()
    env=env_for(stage,index,int(m["episode_seed"]),{"control_mode":m["control_mode"]})
    try:
        trail=[]
        for action in actions:
            _,reward,terminated,truncated,info=env.step(action[None,:])
            trail.append({key:value(item) for key,item in info.items()
                         if key.startswith("stage_") or key in ("success","success_condition")})
        return {"episode":episode.name,"seed":m["episode_seed"],"steps":len(trail),
                "recorded_final":bool(recorded[-1]),"ever":any(v["success"][0] for v in trail),
                "final":trail[-1]["success"][0],"trace":trail}
    finally:
        env.close()


def frame(task,path,stage):
    camera=task.scene.human_render_cameras["render_camera"].camera._render_cameras[0]
    box=task.box.pose.p[0].cpu().numpy()
    if stage=="open":
        target=box+np.array([0.,-.09,.15])
        eye=target+np.array([0.,-.65,.57])
        fovy=.98
    else:
        plate=task.plate.pose.p[0].cpu().numpy()
        target=(box+plate)/2+np.array([0.,.02,.06])
        eye=target+np.array([-.55,-.10,.86])
        fovy=.96
    p=look_at(eye,target)
    camera.entity.set_pose(sapien.Pose())
    camera.local_pose=sapien.Pose(p.p[0].tolist(),p.q[0].tolist())
    camera.set_fovy(fovy,compute_x=True)
    pix=task.render().cpu().numpy()[...,:3]
    img=Image.fromarray(pix[0] if pix.ndim==4 else pix).convert("RGB")
    img.save(path)
    return img


def main():
    ring_texture(OUT/"plate_green_rim.png")
    for style in ("light","dark"):
        recolor_bagel(OUT/f"bagel_{style}_generated.png",style)
    summary={}
    for stage in STAGES:
        reference=None
        images={}
        for index in range(3):
            env=env_for(stage,index,SEED)
            t=env.unwrapped
            try:
                sig=physics(t)
                images.setdefault("entry",[]).append(frame(t,OUT/f"{stage}_{index}_entry.png",stage))
                trace=test_predicates(t,stage)
                images.setdefault("qualified",[]).append(frame(t,OUT/f"{stage}_{index}_qualified.png",stage))
            finally:
                env.close()
            replay=recorded_actions(stage,index)
            res={"physics":sig,"predicate_trace":trace,"recorded_action_trace":replay}
            if reference is None:
                reference=res
            else:
                for key in res:
                    assert res[key]==reference[key],(stage,index,key)
            print("PASS",stage,index,"replay",None if replay is None else (replay["steps"],replay["ever"],replay["final"]),flush=True)
        for moment,frames in images.items():
            w,h=frames[0].size
            sheet=Image.new("RGB",(3*w,h+38),"#1B2027")
            draw=ImageDraw.Draw(sheet)
            font=ImageFont.truetype("DejaVuSans.ttf",20)
            for i,img in enumerate(frames):
                sheet.paste(img,(i*w,38))
                draw.text((i*w+12,7),("Original","Variant 1","Variant 2")[i],font=font,fill="white")
            sheet.save(OUT/f"{stage}_{moment}.png")
        summary[stage]=reference
        (OUT/"report.json").write_text(json.dumps({"task_code_sha256":hashlib.sha256(Path(meal.__file__).read_bytes()).hexdigest(),
            "seed":SEED,"job_id":os.environ.get("SLURM_JOB_ID"),"completed":summary},indent=2)+"\n")
    print("ALL STAGES PASSED",flush=True)


if __name__=="__main__":
    main()
