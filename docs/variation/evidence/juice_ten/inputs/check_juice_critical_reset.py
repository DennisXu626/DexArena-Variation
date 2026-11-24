"""Controlled near-success reset fixtures; no robot-success claim."""
import argparse
import copy
import os
from pathlib import Path
import gymnasium as gym
import torch
import check_juice_ten_paired as check


def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    check.FAMILY="juice";check.KEY="juice_appearance"
    report={"job":os.getenv("SLURM_JOB_ID"),"gpu":os.getenv("SLURM_JOB_GPUS"),"cases":[]}
    for stage in ("PressButton","Long","AppleToBlender"):
        env=gym.make(f"JuicePreparation{stage}-Sharpa-v1",num_envs=2,sim_backend="physx_cuda",obs_mode="state",robot_init_qpos_noise=0,juice_appearance={"scheme_id":"variant_10"})
        try:
            for selected in (0,1):
                env.reset(seed=7);t=env.unwrapped;other=1-selected
                check.prime_juice_control_targets(env)
                if stage in ("PressButton","Long"):
                    q=t.blender.get_qpos().clone();q[other,t.button_joint_index]=t.button_pressed_qpos;t.blender.set_qpos(q)
                    counter=t.button_hold_counter if stage=="PressButton" else t.stage_counter
                    counter[other]=3;t.success_latched[other]=False
                    if stage=="Long":t.stage[other]=4
                else:
                    t.stable_counter[other]=11;t.apple_left_fridge_latched[other]=True;t.apple_lifted_latched[other]=True
                    t.apple_motion["last_step"][other]=-17
                before=copy.deepcopy(check.row_state(t,other));control=check.control_targets(t)[other]
                records=copy.deepcopy(t.juice_appearance.records[other])
                env.reset(options={"env_idx":torch.tensor([selected],device=t.device),"juice_appearance":{"scheme_id":"original"}})
                after=check.row_state(t,other)
                check.numeric_equal(before,after,stage+" critical state")
                check.numeric_equal(control,check.control_targets(t)[other],stage+" critical controls")
                assert records==t.juice_appearance.records[other]
                assert not bool(t.success_latched[other])
                report["cases"].append({"stage":stage,"selected":selected,"before":before,"after":after,"controls":control,"status":"passed"})
                check.dump(args.output/"report.json",report)
                print("CRITICAL PASS",stage,selected,flush=True)
        finally:env.close()
    report["status"]="passed";check.dump(args.output/"report.json",report)

if __name__=="__main__":main()
