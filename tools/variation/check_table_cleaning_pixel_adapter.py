"""Exercise the existing pixel adapter after native multi-env support moved in."""
import argparse
from pathlib import Path
import gymnasium as gym
import torch
from utils.task_adapters import adapt
import check_table_cleaning_ten_paired as check


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    check.setup(args.assets)
    results = []
    for stage, task_id in check.TASKS.items():
        from tasks.table_cleaning.table_cleaning_pick_debris import TableCleaningPickDebrisEnv
        from tasks.table_cleaning.table_cleaning_dump_dustpan import TableCleaningDumpDustpanEnv
        from tasks.table_cleaning.table_cleaning_long import TableCleaningLongEnv
        native = {"PickDebris": TableCleaningPickDebrisEnv,
                  "DumpDustpan": TableCleaningDumpDustpanEnv,
                  "Long": TableCleaningLongEnv}[stage]
        cls = adapt(task_id, native)
        for enabled in (False, True):
            kwargs = {} if not enabled else {"table_cleaning_appearance": {"scheme_id": "variant_10"}}
            env = cls(num_envs=2, sim_backend="physx_cuda", obs_mode="rgb", robot_init_qpos_noise=0,
                      reconfiguration_freq=0, **kwargs)
            try:
                env.reset(seed=7)
                assert env.num_envs == 2
                if enabled:
                    assert len(env.cleaning_appearance.records) == 2
                before = env.agent.robot.get_qpos()[0].clone()
                env.reset(options={"env_idx": torch.tensor([1], device=env.device)})
                torch.testing.assert_close(before, env.agent.robot.get_qpos()[0], atol=1e-6, rtol=0)
                obs, _, _, _, _ = env.step(torch.zeros(env.action_space.shape, device=env.device))
                assert obs["sensor_data"]
                results.append({"stage": stage, "enabled": enabled, "num_envs": 2, "status": "passed"})
                check.dump(args.output / "report.json", {"cases": results})
                print("PIXEL PASS", stage, enabled, flush=True)
            finally:
                env.close()
    check.dump(args.output / "report.json", {"status": "passed", "cases": results})


if __name__ == "__main__":
    main()
