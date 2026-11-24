"""Four-step appearance regression with a fresh process for every instance.

PhysX/SAPIEN process history is excluded from the native/candidate oracle.
Each worker still simulates two environments. No success-rate claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

TASKS={s:f"JuicePreparation{s}-Sharpa-v1" for s in ("OpenFridge","AppleToBlender","CloseFridge","PlaceLid","PressButton","Long")}
CATALOG=Path("tasks/assets/variation/juice_preparation/v1/catalog.json")


def worker(args):
    import gymnasium as gym
    import torch
    import check_juice_ten_paired as check
    check.FAMILY="juice";check.KEY="juice_appearance"
    config=None if args.native else {"scheme_id":args.schemes[0]}
    env=gym.make(TASKS[args.stage],num_envs=2,sim_backend="physx_cuda",obs_mode="state",render_mode=None,reconfiguration_freq=0,robot_init_qpos_noise=0,juice_appearance=config)
    try:
        env.reset(seed=7,options={} if args.native else {"juice_appearance":config})
        t=env.unwrapped
        result={"initial":{"state":[check.row_state(t,k) for k in range(2)],"drive_targets":check.plain(t.agent.robot.get_drive_targets()),"drive_velocities":check.plain(t.agent.robot.get_drive_velocities()),"controller":check.plain(t.agent.controller.get_state())},"trace":[]}
        for i in range(4):
            action=.01*torch.sin(torch.arange(env.action_space.shape[-1],device=t.device,dtype=torch.float32)+i)
            action=action.expand(env.action_space.shape).clone()
            _,reward,terminated,truncated,info=env.step(action)
            result["trace"].append({"state":[check.row_state(t,k) for k in range(2)],"reward":check.plain(reward),"terminated":check.plain(terminated),"truncated":check.plain(truncated),"info":check.plain(info)})
        check.dump(args.output,result)
    finally:env.close()


def equal(a,b,path=""):
    if isinstance(a,dict):
        assert a.keys()==b.keys(),path
        for k in a:equal(a[k],b[k],path+"/"+str(k))
    elif isinstance(a,list):
        assert len(a)==len(b),path
        for i,(x,y) in enumerate(zip(a,b)):equal(x,y,path+"/"+str(i))
    elif a!=b:
        assert isinstance(a,(int,float)) and isinstance(b,(int,float)) and abs(a-b)<=1e-6,(path,a,b)


def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);p.add_argument("--stage",choices=list(TASKS));p.add_argument("--schemes",nargs="+");p.add_argument("--worker",action="store_true");p.add_argument("--native",action="store_true");args=p.parse_args()
    if args.worker:
        assert args.stage and len(args.schemes)==1
        worker(args);return
    args.output.mkdir(parents=True,exist_ok=False)
    ids=list(json.loads(CATALOG.read_text())["schemes"])
    if args.schemes:
        assert all(s in ids for s in args.schemes)
        ids=args.schemes
    report={"job":os.getenv("SLURM_JOB_ID"),"gpu":os.getenv("SLURM_JOB_GPUS"),"num_envs":2,"seed":7,"steps":4,"action":"absolute joint targets .01*sin(arange(action dimensions)+step); deliberately not described as an initial-pose perturbation","history_pairing":"fresh Python process per native AND candidate instance; two envs inside each worker","catalog_sha256":hashlib.sha256(CATALOG.read_bytes()).hexdigest(),"checker_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"stages":{}}
    def save(): (args.output/"trace.json").write_text(json.dumps(report,indent=2)+"\n")
    failed=False
    for stage,task in TASKS.items():
        if args.stage and stage!=args.stage:continue
        row={"task":task,"status":"running","schemes":[]};report["stages"][stage]=row
        for scheme in ids:
            try:
                values=[]
                for native in (True,False):
                    name=f"{stage}_{scheme}_{'native' if native else 'candidate'}"
                    target=args.output/(name+".json")
                    cmd=[sys.executable,"-B",str(Path(__file__).resolve()),"--worker","--stage",stage,"--schemes",scheme,"--output",str(target.resolve())]
                    if native:cmd.append("--native")
                    with (args.output/(name+".log")).open("w") as log:
                        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
                    values.append(json.loads(target.read_text()))
                baseline,actual=values
                equal(baseline["initial"],actual["initial"],stage+"/"+scheme+"/initial")
                equal(baseline["trace"],actual["trace"],stage+"/"+scheme+"/trace")
                row["schemes"].append({"scheme":scheme,"native_initial":baseline["initial"],"initial":actual["initial"],"native_trace":baseline["trace"],"trace":actual["trace"],"differences":[]})
                print("TRACE PASS",stage,scheme,flush=True)
            except Exception as e:
                row["first_failure"]=repr(e);row["failed_scheme"]=scheme;failed=True;break
            finally:save()
        row["status"]="failed" if "first_failure" in row else "passed";save()
    if failed:raise SystemExit(1)

if __name__=="__main__":main()
