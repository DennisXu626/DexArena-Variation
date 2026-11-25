"""Capture the geometry and native arm frames used by the Office offline screen."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.variation import check_office_positions as checks
import gymnasium as gym
import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation


def box(points):
    return [points.min(axis=0).tolist(), points.max(axis=0).tolist()]


def capture(env, task, index):
    e = env.unwrapped
    robot = e.agent.robot
    device = getattr(e, e._position_device_name)
    table, _, colliders = checks.read_geometry(e, device, index)
    parts = checks.body_points(device, colliders, index)
    controls = checks.read_controls(e, task, index)
    ids = e.agent.controller.controllers["arm"].active_joint_indices
    joints = [robot.joints_map[name] for name in e.agent.arm_joint_names]
    frames = np.stack([checks.read(j.global_pose.raw_pose[index]) for j in joints])
    origin = checks.read(device.pose.p[index])
    protected = {}
    for suffix in (
        "panda_link4",
        "panda_link5",
        "panda_link6",
        "angle_bracket",
        "hand_wrist",
        "hand_C_MC",
    ):
        link = next(l for l in robot.links if l.name.endswith(suffix))
        meshes = checks.get_component_meshes(link._objs[index])
        if meshes:
            # Fixed-size enclosures grouped along the longest link dimension.
            raw = checks.vertices(meshes)
            axis = np.argmax(np.ptp(raw, axis=0))
            cuts = np.linspace(raw[:, axis].min(), raw[:, axis].max(), 5)
            # Clip the actual convex hull to each slab, including edge/plane intersections.
            hull = ConvexHull(raw)
            edges = np.unique(
                np.sort(
                    np.vstack(
                        [hull.simplices[:, [0, 1]], hull.simplices[:, [0, 2]], hull.simplices[:, [1, 2]]]
                    ),
                    axis=1,
                ),
                axis=0,
            )
            groups = []
            for a, b in zip(cuts, cuts[1:]):
                points = [raw[(raw[:, axis] >= a) & (raw[:, axis] <= b)]]
                for face in (a, b):
                    first, second = raw[edges[:, 0]], raw[edges[:, 1]]
                    cross = (first[:, axis] - face) * (second[:, axis] - face) < 0
                    first, second = first[cross], second[cross]
                    ratio = (face - first[:, axis]) / (second[:, axis] - first[:, axis])
                    points.append(first + ratio[:, None] * (second - first))
                low, high = box(np.vstack(points))
                corners = np.array(list(itertools.product(*zip(low, high))))
                groups.append(checks.transform(corners, checks.read(link.pose.raw_pose[index])).tolist())
            protected[suffix] = groups
    lid = controls.get("lid")
    shell = np.concatenate([v for k, v in parts.items() if lid is None or k != lid["link"]])
    result = dict(
        device=e._position_device_name,
        origin=origin.tolist(),
        table=box(table),
        footprint=checks.outline(np.concatenate(list(parts.values()))),
        shell=box(shell),
        controls=controls,
        joints_xyz=frames[:, :3].tolist(),
        protected=protected,
        axes=Rotation.from_quat(frames[:, [4, 5, 6, 3]]).as_matrix()[:, :, 0].tolist(),
        home=checks.read(robot.qpos[index, ids]).tolist(),
        limits=checks.read(robot.get_qlimits()[index, ids]).tolist(),
        tip=checks.read(checks.finger(e, task).pose.p[index]).tolist(),
        robot=e.robot_uids,
        finger_id=e.target_finger_id,
    )
    if lid:
        surface = parts[lid["link"]]
        result["screen_hull"] = surface[ConvexHull(surface).vertices].tolist()
        result["open_sign"] = float(np.sign(float(e.qpos_open[index] - e.qpos_closed[index])))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for kind, seed in checks.SEEDS.items():
        checks.assets.require_model_asset_root(kind)
        e = gym.make(
            f"OfficeDesk{kind}-Sharpa-v1",
            num_envs=1,
            obs_mode="state",
            sim_backend="physx_cpu",
            reconfiguration_freq=0,
            control_mode="pd_joint_pos",
        )
        try:
            e.reset(seed=seed, options={"position_layout": {"0": {}}})
            row = capture(e, kind, 0)
            row["seed"] = seed
            row["asset_sha256"] = {
                k: v
                for k, v in checks.assets.asset_hashes().items()
                if k.startswith(checks.MODELS[kind] + "/")
            }
            row["robot_assets"] = checks.assets.asset_closure(e.unwrapped)
            row["capture_script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            (args.output / (kind + ".json")).write_text(
                json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8"
            )
        finally:
            e.close()


if __name__ == "__main__":
    main()
