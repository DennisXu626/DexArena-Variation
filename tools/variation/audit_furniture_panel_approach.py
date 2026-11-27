"""Recheck the raised-panel interior path from the exact start in a saved checker row."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import gymnasium as gym
import numpy as np
import torch

from tools.variation.build_furniture_workspace import (
    IK_LIMIT, MAX_STEP, hand_enclosures, paths, screen, setup_motion,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--physx-gpu-dir")
    args = parser.parse_args()
    with args.points.open(encoding="utf-8", newline="") as handle:
        row = next(row for row in csv.DictReader(handle)
                   if row["task"] == "FurnitureAssemblyLayFlatPanel-Sharpa-v1" and row["id"] == "interior-(10,)")
    options = json.loads(row["options"])
    make = json.loads(row["make"])
    seed, index = int(row["seed"]), int(row["env_idx"])
    layout = json.loads(row["layout"])
    xy, yaw = np.array([layout["rack_xy_m"]]), layout["rack_yaw_deg"]
    readings = {}
    with gym.make(row["task"], **make) as env:
        robot = env.unwrapped
        env.reset(seed=seed)
        if "env_idx" in options:
            options["env_idx"] = torch.tensor(options["env_idx"], device=robot.device)
        env.reset(options=options)
        chain, boxes = setup_motion(robot, index), hand_enclosures(robot, index)
        for tilt in (0, 25, -25, -15, 15, -10, 10, -5, 5, -20, 20, -30, 30, -35, 35):
            result = screen(chain, paths("LayFlatPanel", (yaw,), xy, np.deg2rad(tilt)),
                            boxes, "LayFlatPanel", xy, yaw)
            readings[tilt] = [float(value[0]) for value in result]
        arm = robot.agent.robot.get_qpos()[index, :7].cpu().numpy().tolist()
        observed_point = robot.grasp_position[index].cpu().numpy().tolist()
    initial = [readings[t] for t in (0, 25, -25)]
    # The replay must reproduce the old solve and the physical grasp marker before
    # an additional approach can count as evidence for this particular start.
    original = json.loads(row["holdout_ik"])
    same = np.allclose(initial, original, atol=2e-4, rtol=0)
    same_point = np.allclose(observed_point, json.loads(row["operation_xyz_m"]), atol=2e-5, rtol=0)
    feasible = [angle for angle, (error, step, clearance) in readings.items()
                if error <= IK_LIMIT and step <= MAX_STEP and clearance > .001]
    output = dict(task=row["task"], id=row["id"], make=make, seed=seed, index=index, layout=layout,
                  source_points_sha256=hashlib.sha256(args.points.read_bytes()).hexdigest(),
                  source_approaches=original, initial_approaches_reproduced=bool(same),
                  grasp_marker_reproduced=bool(same_point), initial_arm_rad=arm,
                  grasp_marker_m=observed_point, attempts=readings, feasible_tilts_deg=feasible)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "panel_approach.json").write_text(json.dumps(output, indent=2)+"\n", encoding="utf-8")
    if not (same and same_point and feasible):
        raise RuntimeError("Panel start, measured marker, or approach feasibility check failed.")


if __name__ == "__main__":
    main()
