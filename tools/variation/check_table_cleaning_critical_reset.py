"""Controlled GPU critical reset fixtures, not robot completion trajectories."""
import argparse
import copy
import os
from pathlib import Path
import gymnasium as gym
import torch
import check_table_cleaning_ten_paired as check


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    check.setup(args.assets)
    check.FAMILY = "table_cleaning"
    check.KEY = "table_cleaning_appearance"
    report = {"job": os.getenv("SLURM_JOB_ID"), "gpu": os.getenv("SLURM_JOB_GPUS"), "cases": []}
    for stage in check.TASKS:
        for loaded in ((True, False) if stage == "DumpDustpan" else (None,)):
            kwargs = {} if loaded is None else {"start_loaded": loaded}
            env = gym.make(check.TASKS[stage], num_envs=2, sim_backend="physx_cuda",
                           obs_mode="state", robot_init_qpos_noise=0,
                           table_cleaning_appearance={"scheme_id": "variant_10"}, **kwargs)
            try:
                for selected in (0, 1):
                    env.reset(seed=7)
                    t = env.unwrapped
                    other = 1 - selected
                    check.prime_control_targets(env)
                    t.hold[other] = 7 if stage == "PickDebris" else 9
                    t.f_picked[other] = True
                    t.f_grasp_pan[other] = stage != "PickDebris"
                    t.f_poured[other] = stage == "Long"
                    t.stage[other] = {"PickDebris": 1, "DumpDustpan": 1, "Long": 3}[stage]
                    t.success_latched[other] = False
                    # Flags above are assigned directly, so refresh the observed
                    # stage without calling evaluate (which would advance hold).
                    t._last_obs = t.get_obs(info={"n_in_pan": t._debris_in_pan(resting=stage == "PickDebris"),
                                    "n_in_bin": t._debris_in_bin()})
                    state = copy.deepcopy(check.row_state(t, other))
                    counters = copy.deepcopy(check.counters(t, other))
                    controls = check.control_targets(t)[other]
                    records = copy.deepcopy(t.cleaning_appearance.records[other])
                    env.reset(options={"env_idx": torch.tensor([selected], device=t.device),
                                       check.KEY: {"scheme_id": "original"}})
                    after = check.row_state(t, other)
                    check.numeric_equal(state, after, "critical neighbour state")
                    check.numeric_equal(counters, check.counters(t, other), "critical neighbour counters")
                    check.numeric_equal(controls, check.control_targets(t)[other], "critical controls")
                    assert records == t.cleaning_appearance.records[other]
                    assert not bool(t.success_latched[other])
                    # These are counter/flag fixtures; physical containment and
                    # restore invalidation are checked independently below/CPU.
                    report["cases"].append({"stage": stage, "start_loaded": loaded,
                                             "selected": selected, "before": state,
                                             "after": after, "counters": counters, "status": "passed"})
                    check.dump(args.output / "report.json", report)
                    print("CRITICAL PASS", stage, loaded, selected, flush=True)
            finally:
                env.close()
    report["status"] = "passed"
    check.dump(args.output / "report.json", report)


if __name__ == "__main__":
    main()
