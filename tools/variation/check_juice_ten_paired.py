"""Eleven-row A4/A5 task validation on Linux; never modifies production tasks."""
import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import traceback

import gymnasium as gym
import numpy as np
from PIL import Image, ImageDraw
import sapien
import torch

sys.path.insert(0,str(Path.cwd()))
import tasks
from tasks.robots.franka_joint_impedance_controller import FrankaJointImpedanceController


def plain(x):
    if torch.is_tensor(x):return x.detach().cpu().tolist()
    if isinstance(x,np.ndarray):return x.tolist()
    if isinstance(x,np.generic):return x.item()
    if isinstance(x,sapien.Pose):return {"p":x.p.tolist(),"q":x.q.tolist()}
    if isinstance(x,dict):return {str(k):plain(v) for k,v in x.items()}
    if isinstance(x,(tuple,list)):return [plain(v) for v in x]
    if isinstance(x,(str,int,float,bool,type(None))):return x
    return str(x)


def dump(p,x):p.write_text(json.dumps(plain(x),indent=2)+"\n")


def diffs(a,b,path=""):
    if isinstance(a,dict):
        assert a.keys()==b.keys(),(path,a.keys()^b.keys())
        return [v for k in a for v in diffs(a[k],b[k],path+"/"+k)]
    if isinstance(a,list):
        assert len(a)==len(b),(path,len(a),len(b))
        return [v for i,(x,y) in enumerate(zip(a,b)) for v in diffs(x,y,path+f"/{i}")]
    if a==b:return []
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
        return [{"path":path,"delta":abs(float(a)-float(b))}]
    return [{"path":path,"before":a,"after":b,"delta":None}]


def numeric_equal(a,b,label):
    d=diffs(plain(a),plain(b));assert all(x["delta"] is not None and x["delta"]<=1e-6 for x in d),(label,d[:10]);return d


def attrs(obj,names):return {n:plain(getattr(obj,n)) for n in names if hasattr(obj,n)}


def fingerprint(x):
    x=np.asarray(x);return {"shape":list(x.shape),"dtype":str(x.dtype),"sha256":hashlib.sha256(x.tobytes()).hexdigest()}


def shape_geometry(s):
    d={"type":type(s).__name__,**attrs(s,("local_pose","half_size","radius","half_length","scale","density","contact_offset","rest_offset"))}
    for n in ("vertices","triangles"):
        if hasattr(s,n):d[n]=fingerprint(getattr(s,n))
    if hasattr(s,"parts"):
        d["parts"]=[{"vertices":fingerprint(p.vertices),"triangles":fingerprint(p.triangles),"uv":fingerprint(p.get_vertex_uv()),"normals":fingerprint(p.get_vertex_normal())} for p in s.parts]
    return d


def physical(t,idx):
    rows=[]
    for entity in sorted(t.scene.sub_scenes[idx].entities,key=lambda x:x.name):
        bodies=[]
        for c in entity.components:
            if isinstance(c,sapien.physx.PhysxRigidBaseComponent):
                row={"type":type(c).__name__,**attrs(c,("mass","inertia","cmass_local_pose","linear_damping","angular_damping","kinematic","disable_gravity")),"collisions":[]}
                for s in c.collision_shapes:
                    row["collisions"].append({**shape_geometry(s),"groups":plain(s.get_collision_groups()),"contact":attrs(s.physical_material,("static_friction","dynamic_friction","restitution"))})
                if isinstance(c,sapien.physx.PhysxArticulationLinkComponent):
                    j=c.joint;row["joint"]=attrs(j,("type","dof","pose_in_parent","pose_in_child"))
                    if j.dof:row["joint"].update(attrs(j,("limits","friction","stiffness","damping","force_limit","drive_mode")))
                bodies.append(row)
        if bodies:rows.append({"name":entity.name,"bodies":bodies})
    assert rows;return rows


SCALARS=("base_color","emission","specular","roughness","metallic","transmission","ior","transmission_roughness")
TEX=("base_color_texture","emission_texture","metallic_texture","normal_texture","roughness_texture","transmission_texture")


def texture(x):
    if x is None:return None
    a=x.download()
    if a.shape[-1]==3:a=np.concatenate([a,np.full((*a.shape[:2],1),255,dtype=a.dtype)],-1)
    return {"srgb":x.is_srgb,**fingerprint(a)}


def object_entities(t,idx):
    names=("box","plate","spoon","bread","ball_food") if FAMILY=="meal" else ("fridge","apple","blender","lid")
    for name in names:
        actor=getattr(t,name,None)
        if actor is None:continue
        raw=actor._objs[idx]
        yield name,([l.entity for l in raw.get_links()] if hasattr(raw,"get_links") else [raw])


def materials(t,idx):
    out={}
    for name,entities in object_entities(t,idx):
        for k,entity in enumerate(entities):
            rb=entity.find_component_by_type(sapien.render.RenderBodyComponent)
            if rb is None:continue
            for i,s in enumerate(rb.render_shapes):
                mats=[s.material] if isinstance(s,sapien.render.RenderShapePrimitive) else [p.material for p in s.parts]
                for j,m in enumerate(mats):out[f"{name}/{k}/{i}/{j}"]={"shape":shape_geometry(s),"values":attrs(m,SCALARS),"textures":{n:texture(getattr(m,n)) for n in TEX}}
    assert out;return out


def row_state(t,idx):
    def visit(x):
        if isinstance(x,dict):return {k:visit(v) for k,v in x.items() if not ((FAMILY=="juice" and k.endswith(f"_{1-idx}")) or (k.startswith(("procedural_box_","partnet_box_","package_")) and k.rsplit("_",1)[-1].isdigit() and k.rsplit("_",1)[-1]!=str(idx)))}
        if torch.is_tensor(x):return plain(x[idx] if x.ndim and x.shape[0]==2 else x)
        return plain(x)
    return visit(t.get_state_dict())


def control_targets(t):
    """Read live targets, independently of optional controller serialization."""
    def snapshot(value, label):
        assert torch.is_tensor(value), (label, "expected batched tensor")
        assert value.ndim == 2 and value.shape[0] == 2 and value.shape[1] > 0, (label, value.shape)
        assert torch.isfinite(value).all().item(), (label, "non-finite target")
        # tolist creates an independent snapshot even for CPU-backed buffers.
        return value.detach().cpu().tolist()

    arms = {}
    def visit(controller, path):
        if isinstance(controller, FrankaJointImpedanceController):
            arms[path] = snapshot(getattr(controller, "_target_qpos", None), path)
        for name, child in getattr(controller, "controllers", {}).items():
            visit(child, path + "/" + str(name))
    visit(t.agent.controller, "controller")
    assert arms, "Juice A5 requires live arm impedance targets"
    positions = snapshot(t.agent.robot.get_drive_targets(), "drive_targets")
    velocities = snapshot(t.agent.robot.get_drive_velocities(), "drive_velocities")
    assert len(positions[0]) == len(velocities[0]), "drive target dimensions differ"
    return [{"arm_impedance_qpos": {name: value[i] for name, value in arms.items()},
             "drive_targets": positions[i], "drive_velocities": velocities[i]} for i in range(2)]


def prime_juice_control_targets(env):
    """Issue distinct legal commands without stepping or moving the scene."""
    t = env.unwrapped
    controller = t.agent.controller
    actions = {}
    arms = []
    for name, child in controller.controllers.items():
        assert not child.config.normalize_action and not getattr(child.config, "use_delta", False), name
        action = child.qpos.clone()
        low = torch.as_tensor(child.single_action_space.low, device=t.device, dtype=action.dtype)
        high = torch.as_tensor(child.single_action_space.high, device=t.device, dtype=action.dtype)
        action[:, 0] += torch.tensor([.125, -.125], device=t.device)
        action = torch.maximum(low, torch.minimum(high, action))
        assert torch.all(action >= low) and torch.all(action <= high), name
        if isinstance(child, FrankaJointImpedanceController):
            assert torch.all((action[:, 0] - child.qpos[:, 0]).abs() > .01), name
            assert abs(float(action[0, 0] - action[1, 0])) > .01, name
            arms.append(child)
        actions[name] = action
    assert arms, "Juice A5 needs arm impedance controllers"
    command = controller.from_action_dict(actions)
    t.agent.set_action(command)
    for arm in arms:
        assert torch.all((arm._target_qpos[:, 0] - arm.qpos[:, 0]).abs() > .01)
        assert abs(float(arm._target_qpos[0, 0] - arm._target_qpos[1, 0])) > .01
    return plain(command)


def compare_control_targets(before, after, idx, label):
    return numeric_equal(before["control_targets"][idx], after["control_targets"][idx], label)


def counters(t,idx):
    out={}
    for label,obj in (("task",t),("evaluator",getattr(t,"task_evaluator",None))):
        if obj is None:continue
        for n,v in vars(obj).items():
            if torch.is_tensor(v) and v.ndim and v.shape[0]==2 and any(s in n for s in ("stage","success","count","last","lock","hold","stable","elapsed")):
                out[label+"/"+n]=plain(v[idx])
    return out


def rng(t,idx):
    x=t._batched_episode_rng[idx]
    a=getattr(t,KEY)
    return {"task":plain(x.get_state() if hasattr(x,"get_state") else x.bit_generator.state),"appearance":None if a is None else None}


def images(env,info):
    obs=env.unwrapped.get_obs(info=info)
    rgb={k:v["rgb"].detach().cpu().numpy().copy()[...,:3] for k,v in obs["sensor_data"].items()}
    seg={k:v["segmentation"].detach().cpu().numpy().copy()[...,0] for k,v in obs["sensor_data"].items()}
    rgb["human"]=env.render().detach().cpu().numpy().copy()[...,:3]
    human=next(iter(env.unwrapped.scene.human_render_cameras.values()))
    seg["human"]=human.get_obs(rgb=False,depth=False,position=False,segmentation=True)["segmentation"].detach().cpu().numpy().copy()[...,0]
    for name,a in rgb.items():assert a.ndim==4 and a.shape[0]==2 and np.ptp(a)>0,(name,a.shape)
    assert len(rgb)>1 and seg
    return rgb,seg


def capture(env,info):
    t=env.unwrapped;rgb,seg=images(env,info);a=getattr(t,KEY)
    return {"images":rgb,"seg":seg,"state":[row_state(t,i) for i in range(2)],
        "control_targets":control_targets(t) if FAMILY=="juice" else None,
        "info":plain(info),"counters":[counters(t,i) for i in range(2)],
        "materials":[materials(t,i) for i in range(2)],"physics":[physical(t,i) for i in range(2)],
        "rng":[rng(t,i) for i in range(2)],"object_ids":[{n:[e.per_scene_id for e in es] for n,es in object_entities(t,i)} for i in range(2)],"records":None if a is None else copy.deepcopy(a.records)}


def image_diff(a,b,idx,strict=True,unselected=False):
    out={}
    for k,x in a.items():
        d=np.abs(x[idx].astype(np.int16)-b[k][idx].astype(np.int16));out[k]={"max":int(d.max()),"channels":int(np.count_nonzero(d)),"pixels":int(np.count_nonzero(np.any(d>0,axis=-1)))}
    if strict:
        for camera,x in out.items():
            special=unselected and FAMILY=="meal" and STAGE=="tomato" and camera=="wrist_camera"
            assert x["max"]<=(3 if special else 1) and x["channels"]<=8 and (not special or x["pixels"]<=5),(camera,x)
    return out


def restored_target_rgb(base,trial,idx):
    result={}
    for camera in trial["seg"]:
        result[camera]={}
        for name,ids in trial["object_ids"][idx].items():
            mask=np.isin(trial["seg"][camera][idx],ids)|np.isin(base["seg"][camera][idx],base["object_ids"][idx][name])
            d=np.abs(base["images"][camera][idx].astype(np.int16)-trial["images"][camera][idx].astype(np.int16))
            values=d[mask]
            row={"pixels":int(mask.sum()),"max":int(values.max(initial=0)),"channels":int(np.count_nonzero(values))}
            result[camera][name]=row
            assert row["max"]<=1 and row["channels"]<=8,(camera,name,row)
    return result


def save_images(cap,prefix):
    paths={}
    for camera,frames in cap["images"].items():
        for i in range(2):
            name=f"{prefix}_{camera}_env{i}.png";Image.fromarray(frames[i]).save(OUT/name);paths[f"{camera}/env{i}"]=name
    return paths


def store(x):
    text=json.dumps(plain(x),sort_keys=True,separators=(",",":"));h=hashlib.sha256(text.encode()).hexdigest();SIGNATURES[h]=plain(x);return h


def sig(cap):return {k:store(cap[k]) for k in ("state","control_targets","info","counters","materials","physics","rng","records")}


def target_rgb(t,base,trial,idx):
    report={}
    for name,entities in object_entities(t,idx):
        ids=[e.per_scene_id for e in entities];cams={}
        for camera,s in trial["seg"].items():
            mask=np.isin(s[idx],ids);d=np.abs(trial["images"][camera][idx].astype(np.int16)-base["images"][camera][idx].astype(np.int16))
            cams[camera]={"pixels":int(mask.sum()),"changed_pixels":int(np.count_nonzero(np.any(d>1,axis=-1)&mask)),"entity_ids":ids}
        report[name]=cams
    return report


def semantic(t,idx,scheme):
    a=getattr(t,KEY)
    if FAMILY=="meal":
        from check_meal_ten import semantic as check
        return check(a,idx,scheme)
    from tasks.juice_preparation.appearance_colors import linear_rgba, recolor_apple, recolor_shell
    recipe=CAT["schemes"][scheme];out=[]
    expected={"OpenFridge":{"fridge"},"CloseFridge":{"fridge"},"AppleToBlender":{"fridge","apple","blender"},"PlaceLid":{"blender","lid"},"PressButton":{"blender","lid"},"Long":{"fridge","apple","blender","lid"}}[STAGE]
    assert set(a.bindings[idx])==expected
    for role,slots in a.bindings[idx].items():
        for mat,source in slots:
            if role=="fridge":
                assert np.allclose(mat.base_color,linear_rgba(recipe[role]),atol=1e-6)
                assert abs(mat.roughness-recipe["fridge_roughness"])<1e-6
                out.append({"role":role,"color":recipe[role]})
            else:
                pixels=(recolor_apple if role=="apple" else recolor_shell)(source.copy(),recipe[role])
                assert np.array_equal(mat.base_color_texture.download(),pixels)
                out.append({"role":role,"texture":fingerprint(pixels)})
    return out


def make(config):
    kwargs={KEY:config}
    if FAMILY=="meal":kwargs['box_asset_source']='procedural'
    return gym.make(TASKS[STAGE],num_envs=2,sim_backend="physx_cuda",render_backend="gpu",obs_mode="rgb+segmentation",render_mode="rgb_array",reconfiguration_freq=0,robot_init_qpos_noise=0,**kwargs)


def full_reset(env,scheme=None):return env.reset(seed=7,options={} if scheme is None else {KEY:{"scheme_id":scheme}})


def compare_baseline(base,c,label):
    out={"state":numeric_equal(base["state"],c["state"],label+" state"),"info":numeric_equal(base["info"],c["info"],label+" info")}
    numeric_equal(base["physics"],c["physics"],label+" physics")
    return out


def run():
    report={"stage":STAGE,"task":TASKS[STAGE],"family":FAMILY,"rows":[],"A5":[],"random":None,"status":"running"}
    dump(OUT/"report.json",report)
    try:
        natives=[];locals_={}
        for repeat in range(2):
            env=make(None)
            try:
                _,info=full_reset(env);cap=capture(env,info);natives.append(cap)
                report[f"native_{repeat}"]={"signatures":sig(cap),"images":save_images(cap,f"native{repeat}")}
                if repeat==0:
                    for selected in (1,0):
                        _,info=full_reset(env);before=capture(env,info)
                        _,info=env.reset(options={"env_idx":torch.tensor([selected],device=env.unwrapped.device)})
                        after=capture(env,info);locals_[selected]=after
                        report[f"native_partial_{selected}"]={"after":sig(after),"unselected_rgb":image_diff(before["images"],after["images"],1-selected),"images":save_images(after,f"native_partial{selected}")}
            finally:env.close()
        report["native_noise"]={"numeric":compare_baseline(natives[0],natives[1],"native repeat"),"rgb":[image_diff(natives[0]["images"],natives[1]["images"],i) for i in range(2)]}
        base=natives[0];env=make({"enabled":True,"scheme_id":"original"});control=make(None)
        try:
            t=env.unwrapped;a=getattr(t,KEY)
            for scheme in IDS:
                _,ninfo=full_reset(control);paired=capture(control,ninfo)
                _,info=full_reset(env,scheme);cap=capture(env,info)
                assert [x["scheme_id"] for x in a.records]==[scheme]*2
                row={"request":scheme,"actual":copy.deepcopy(a.records),"signatures":sig(cap),"images":save_images(cap,scheme),"baseline":compare_baseline(base,cap,scheme),"expected":CAT["schemes"][scheme],"paired_native":sig(paired)}
                if scheme=="original":
                    numeric_equal(base["materials"],cap["materials"],"enabled original materials")
                    row["original_rgb"]=[image_diff(paired["images"],cap["images"],i) for i in range(2)]
                else:
                    row["semantic"]=[semantic(t,i,scheme) for i in range(2)]
                    row["target_rgb"]=target_rgb(t,paired,cap,0)
                    assert any(c["changed_pixels"]>0 for obj in row["target_rgb"].values() for c in obj.values()),(scheme,"no target RGB change")
                    _,ninfo=full_reset(control);paired_restore=capture(control,ninfo)
                    _,info=full_reset(env,"original");restored=capture(env,info)
                    numeric_equal(paired_restore["materials"],restored["materials"],"A4 restore slots")
                    compare_baseline(base,restored,"A4 restore")
                    row["restored"]={"signatures":sig(restored),"paired_native":sig(paired_restore),"rgb":[image_diff(paired_restore["images"],restored["images"],i) for i in range(2)],"images":save_images(restored,f"{scheme}_restored")}
                report["rows"].append(row);dump(OUT/"report.json",report);dump(OUT/"signatures.json",SIGNATURES)
                print("A4 PASS",STAGE,scheme,flush=True)
            for n,scheme in enumerate(IDS[1:]):
                peer=IDS[1+(n+1)%10]
                for selected in (1,0):
                    cfg={"per_env":{"0":{"scheme_id":scheme},"1":{"scheme_id":peer}}}
                    _,ninfo=control.reset(seed=7)
                    commands=prime_juice_control_targets(control) if FAMILY=="juice" else None
                    native_before=capture(control,ninfo)
                    _,info=env.reset(seed=7,options={KEY:cfg})
                    if FAMILY=="juice":
                        numeric_equal(commands,prime_juice_control_targets(env),"A5 matched commands")
                    before=capture(env,info);other=1-selected
                    _,ninfo=control.reset(options={"env_idx":torch.tensor([selected],device=t.device)});native_after=capture(control,ninfo)
                    _,info=env.reset(options={"env_idx":torch.tensor([selected],device=t.device),KEY:{"per_env":{str(selected):{"scheme_id":"original"}}}})
                    after=capture(env,info)
                    report["pending_case"]={"scheme":scheme,"selected":selected,"commands":commands,"before":sig(before),"after":sig(after),
                        "before_images":save_images(before,f"a5_{scheme}_selected{selected}_before"),"after_images":save_images(after,f"a5_{scheme}_selected{selected}_after")}
                    dump(OUT/"report.json",report);dump(OUT/"signatures.json",SIGNATURES)
                    if FAMILY=="juice":
                        compare_control_targets(before,after,other,"A5 other control targets")
                    numeric_equal(before["state"][other],after["state"][other],"A5 other state")
                    numeric_equal(before["counters"][other],after["counters"][other],"A5 other counters")
                    numeric_equal(before["materials"][other],after["materials"][other],"A5 other materials")
                    assert before["records"][other]==after["records"][other]
                    assert before["rng"][other]==after["rng"][other]
                    assert after["records"][selected]["scheme_id"]=="original"
                    native=native_after
                    if FAMILY=="juice":
                        compare_control_targets(native,after,selected,"A5 selected control targets vs native")
                    numeric_equal(native["materials"][selected],after["materials"][selected],"A5 selected slots")
                    numeric_equal(native["state"][selected],after["state"][selected],"A5 selected state")
                    case={"request_pair":[scheme,peer],"selected":selected,"commands":commands,"before":sig(before),"after":sig(after),
                        "unselected_rgb":image_diff(before["images"],after["images"],other,unselected=True),
                        "matched_native_before":sig(native_before),"matched_native_after":sig(native_after),
                        "matched_native_images":save_images(native_after,f"a5_{scheme}_selected{selected}_native"),
                        "selected_vs_native_rgb":image_diff(native["images"],after["images"],selected,False),
                        "selected_vs_native_target_rgb":restored_target_rgb(native,after,selected),
                        "selected_before_vs_after_rgb":image_diff(before["images"],after["images"],selected,False),
                        "before_images":save_images(before,f"a5_{scheme}_selected{selected}_before"),"after_images":save_images(after,f"a5_{scheme}_selected{selected}_after")}
                    assert any(x["channels"]>8 for x in case["selected_before_vs_after_rgb"].values()),"selected RGB did not change"
                    report["A5"].append(case)
                    report.pop("pending_case",None)
                dump(OUT/"report.json",report);dump(OUT/"signatures.json",SIGNATURES)
                print("A5 PASS",STAGE,scheme,flush=True)
        finally:
            env.close();control.close()
        report["random"]="not implemented: fixed schemes only";report["status"]="passed"
    except Exception:
        report["status"]="failed";report["first_failure"]=traceback.format_exc();raise
    finally:
        dump(OUT/"report.json",report);dump(OUT/"signatures.json",SIGNATURES)


def main():
    global FAMILY,KEY,TASKS,CAT,STAGE,OUT,IDS,SIGNATURES
    p=argparse.ArgumentParser();p.add_argument("stage");p.add_argument("--output",type=Path,required=True)
    args=p.parse_args();FAMILY="juice";STAGE=args.stage;OUT=args.output;OUT.mkdir(parents=True,exist_ok=False);SIGNATURES={}
    TASKS={s:f"JuicePreparation{s}-Sharpa-v1" for s in ("OpenFridge","AppleToBlender","CloseFridge","PlaceLid","PressButton","Long")}
    CATALOG=Path("tasks/assets/variation/juice_preparation/v1/catalog.json");KEY="juice_appearance"
    CAT=json.loads(CATALOG.read_text());IDS=list(CAT["schemes"]);assert IDS==["original",*[f"variant_{i}" for i in range(1,11)]]
    dump(OUT/"identity.json",{"job":os.environ.get("SLURM_JOB_ID"),"gpu":os.environ.get("SLURM_JOB_GPUS"),"family":FAMILY,"task":TASKS[STAGE],"backend":"physx_cuda / GPU render","num_envs":2,"seed":7,"robot_noise":0,"catalog_sha256":hashlib.sha256(CATALOG.read_bytes()).hexdigest(),"checker_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"versions":{k:importlib.metadata.version(k) for k in ("sapien","mani_skill","torch")},"history_pairing":"native and candidate execute identical reset/env_idx/render sequence; no physical steps in A4/A5","tolerances":{"numeric":1e-6,"rgb_max":1,"rgb_channels":8,"note":"No family-specific RGB tolerance exceptions"},"full_robot_success_rate":"not measured","short_action_trace":"not run: current production changes are appearance recipes only, no physics/reset code changes"})
    run()


if __name__=="__main__":main()
