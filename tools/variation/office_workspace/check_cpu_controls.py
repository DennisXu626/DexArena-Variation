"""Check native defaults, snapshot restoration, held-out robot poses and passive lid motion."""

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2])]

from capture import capture
from build import OfficeScreen
from verify import checks, options_for
import gymnasium as gym
import numpy as np
import torch


def main(output):
    previous_dir = checks.ROOT / "docs/variation/evidence/office_position_boundaries/cpu"
    workspace_dir = checks.ROOT / "docs/variation/evidence/office_workspace"
    results = {}
    for task, seed in checks.SEEDS.items():
        archive = json.loads((previous_dir / task / "results.json").read_text(encoding="utf-8"))
        task_id = f"OfficeDesk{task}-Sharpa-v1"
        env = gym.make(task_id, **archive["make_kwargs"])
        try:
            base = env.unwrapped
            art = getattr(base, base._position_device_name)
            env.reset(seed=seed)
            actual = dict(
                pose=checks.read(art.pose.raw_pose),
                qpos=checks.read(art.qpos),
                qvel=checks.read(art.qvel),
                robot_qpos=checks.read(base.agent.robot.qpos),
            )
            differences = {
                key: float(np.max(np.abs(value - archive["native_seed_reference"][key])))
                for key, value in actual.items()
            }
            assert max(differences.values()) < 2e-6
        finally:
            env.close()
        env = gym.make(task_id, position_workspace=True, **archive["make_kwargs"])
        try:
            base = env.unwrapped
            api = base.position_workspace
            env.reset(seed=seed, options={"workspace_placement": {"0": "near"}})
            saved, original = copy.deepcopy(base.get_state_dict()), base.get_state().clone()
            env.reset(options={"workspace_placement": {"0": "far"}})
            counts = api.counts.copy()
            env.reset(options={"reset_to_env_states": {"env_states": saved}})
            error = float(torch.max(torch.abs(base.get_state() - original)))
            assert error < 2e-6 and counts == api.counts
            result = dict(
                archived_input=archive["source_commit"],
                native_max_abs_difference=differences,
                saved_state_restore_max_abs_difference=error,
                layout_counters_preserved=True,
            )
            result["held_out_robot_poses"] = []
            for new_seed in (7111, 8111, 9111):
                env.reset(seed=new_seed)
                frame = capture(env, task, 0)
                screen = OfficeScreen(frame)
                pose = api.episodes[0]
                from tasks.office_desk.position_workspace import cell_at

                routes = cell_at(api.table, pose["xy_m"], pose["yaw_offset_deg"])[3]
                start = frame["controls"].get("lid", {}).get("angles_deg", [0])[0]
                measured = {}
                for route in routes:
                    code, index, tip_error, margin, jump, _ = screen.evaluate(
                        screen.origin[:2], 0, route, start
                    )
                    measured[route] = dict(
                        code=int(code),
                        waypoint=int(index),
                        tip_error_m=float(tip_error),
                        clearance_m=float(margin),
                        joint_step_rad=float(jump),
                    )
                result["held_out_robot_poses"].append(dict(seed=new_seed, layout=pose, routes=measured))
            if task == "OpenLaptop":
                trials = json.loads(
                    (workspace_dir / "cpu/OpenLaptop/report.json").read_text(encoding="utf-8")
                )
                result["passive_controls"] = []
                for active in trials["actions"]:
                    if "short_action" not in active:
                        continue
                    _, info = env.reset(
                        seed=active["seed"], options={"workspace_placement": {"0": active["preset"]}}
                    )
                    action = checks.hold_action(env)
                    angles = [float(info["opening_angle_deg"][0])]
                    for _ in range(active["short_action"]["control_steps"]):
                        *_, info = env.step(action)
                        angles.append(float(info["opening_angle_deg"][0]))
                    result["passive_controls"].append(
                        dict(
                            seed=active["seed"],
                            preset=active["preset"],
                            control_steps=len(angles) - 1,
                            initial_angle_deg=angles[0],
                            passive_peak_deg=max(angles),
                            final_angle_deg=angles[-1],
                            active_peak_deg=active["short_action"]["peak"],
                        )
                    )
            results[task] = result
        finally:
            env.close()
    kw = options_for("OpenLaptop", "physx_cpu")
    long_id = "OfficeDeskLong-Sharpa-v1"
    env = gym.make(long_id, **kw)
    try:
        initializations = []
        for _ in range(2):
            _, info = env.reset(seed=817)
            state = env.unwrapped.get_state()
            initializations.append(
                dict(
                    digest=hashlib.sha256(state.cpu().numpy().tobytes()).hexdigest(),
                    success=bool(info["success"][0]),
                    values=state.numel(),
                )
            )
        assert initializations[0] == initializations[1]
        results["long"] = dict(
            task=long_id, seed=817, make_kwargs=kw, initializations=initializations, passed=True
        )
    finally:
        env.close()
    results["source_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checks.ROOT, text=True
    ).strip()
    results["checker_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    checks.write_json(output, results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    main(parser.parse_args().output)
