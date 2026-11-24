"""Fixed-action numeric regression for all Package appearance IDs; no success-rate claim."""
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
import torch
sys.path.insert(0,str(Path.cwd()))
import tasks
import check_ten_environment_paired as check
from check_package_opening import TASKS
from tasks.package_opening import package_opening_long as package
from tasks.package_opening.appearance import CATALOG


def main():
    p=argparse.ArgumentParser();p.add_argument("--assets",type=Path,required=True);p.add_argument("--output",type=Path,required=True);args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    package.PACKAGE_URDF_PATH=args.assets/"package/mobility.urdf";package.ROBOCASA_OBJECT_DIR=args.assets/"robocasa/objects/objaverse"
    check.FAMILY="package";check.KEY="package_appearance"
    cat=json.loads(CATALOG.read_text());ids=list(cat["schemes"])
    report={"job":os.environ.get("SLURM_JOB_ID"),"gpu":os.environ.get("SLURM_JOB_GPUS"),"seed":7,"num_envs":2,"steps":4,"action":"deterministic small joint-control inputs: .01*sin(arange(action dimensions)+step)","catalog_sha256":hashlib.sha256(CATALOG.read_bytes()).hexdigest(),"checker_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"stages":{},"full_robot_success_rate":"not measured","history_pairing":"serial fresh native then closed, fresh candidate per ID; identical reset and four actions; drive/controller precondition checked"}
    def make(task,config):return gym.make(task,num_envs=2,sim_backend="physx_cuda",obs_mode="state",render_mode=None,reconfiguration_freq=0,robot_init_qpos_noise=0,package_appearance=config)
    def trace(env):
        t=env.unwrapped;result=[]
        for i in range(4):
            action=.01*torch.sin(torch.arange(env.action_space.shape[-1],device=t.device,dtype=torch.float32)+i);action=action.expand(env.action_space.shape).clone()
            _,reward,terminated,truncated,info=env.step(action)
            result.append({"state":[check.row_state(t,k) for k in range(2)],"reward":check.plain(reward),"terminated":check.plain(terminated),"truncated":check.plain(truncated),"info":check.plain(info)})
        return result
    for stage,task in TASKS.items():
        row={"task":task,"status":"running","schemes":[]};report["stages"][stage]=row
        try:
            for scheme in ids:
                native=make(task,None);env=None
                try:
                    native.reset(seed=7)
                    def initial(e):
                        t=e.unwrapped
                        return {"state":[check.row_state(t,k) for k in range(2)],"drive_targets":check.plain(t.agent.robot.get_drive_targets()),"drive_velocities":check.plain(t.agent.robot.get_drive_velocities()),"controller":check.plain(t.agent.controller.get_state())}
                    native_initial=initial(native);baseline=trace(native)
                    native.close();native=None
                    env=make(task,{"enabled":True,"scheme_id":scheme})
                    env.reset(seed=7,options={"package_appearance":{"scheme_id":scheme}})
                    candidate_initial=initial(env)
                    check.numeric_equal(native_initial,candidate_initial,stage+"/"+scheme+" initial/control precondition")
                    actual=trace(env)
                    row["last_attempt"]={"scheme":scheme,"trace":actual,"native_trace":baseline,"native_initial":native_initial,"candidate_initial":candidate_initial}
                    differences=check.numeric_equal(baseline,actual,stage+"/"+scheme)
                    row["schemes"].append({"scheme":scheme,"trace":actual,"native_trace":baseline,"initial":candidate_initial,"native_initial":native_initial,"differences":differences})
                    row.pop("last_attempt",None);check.dump(args.output/"trace.json",report)
                    print("TRACE PASS",stage,scheme,flush=True)
                finally:
                    if native is not None:native.close()
                    if env is not None:env.close()
            row["status"]="passed"
        except Exception:row["status"]="failed";row["first_failure"]=traceback.format_exc();print(row["first_failure"],flush=True)
        check.dump(args.output/"trace.json",report)
    if any(x["status"]!="passed" for x in report["stages"].values()):raise SystemExit(1)


if __name__=="__main__":main()
