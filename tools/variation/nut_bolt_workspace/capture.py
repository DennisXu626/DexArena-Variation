"""Capture the native Sharpa chain, palm collision mesh and Nut & Bolt geometry."""

import hashlib
import json
from pathlib import Path
import sys

import gymnasium as gym
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parents[1])]
from check_nut_bolt_positions import as_pose, geometry, setup_motion, shapes_world
from tasks.nut_bolt.nut_bolt_long import BOLT_HEX_HEAD_PATH

DEST = ROOT / "docs/variation/evidence/nut_bolt_workspace/model.json"


def capture(task):
    env = gym.make(
        f"NutBolt{task}-Sharpa-v1",
        sim_backend="physx_cpu",
        obs_mode="state",
        control_mode="pd_joint_pos",
        reconfiguration_freq=0,
        render_mode=None,
    )
    try:
        env.reset(seed=707, options={"position_layout": {"0": {}}})
        e = env.unwrapped
        chain = setup_motion(e, 0)
        g = geometry(e)
        hand = []
        for link in e.agent.robot._objs[0].links:
            if link.name.endswith(("hand_wrist", "hand_C_MC", "angle_bracket")) and link.collision_shapes:
                for cloud, _, _ in shapes_world(link.collision_shapes, as_pose(link.entity.pose)):
                    for axis in range(3):
                        hand.extend((cloud[cloud[:, axis].argmin()], cloud[cloud[:, axis].argmax()]))
        if not hand:
            raise RuntimeError([link.name for link in e.agent.robot._objs[0].links])
        return dict(
            robot_uid=e.robot_uids,
            seed=707,
            chain=[a.tolist() for a in chain],
            palm_witnesses=np.unique(np.round(hand, 7), axis=0).tolist(),
            geometry=g,
            bolt_height=e.bolt_height,
            tip_height=e.bolt_tip_height,
            nut_radius=e.nut_circumradius,
        )
    finally:
        env.close()


if __name__ == "__main__":
    data = {t: capture(t) for t in ("PickBolt", "SeatNut", "TurnNut")}
    data["bolt_mesh_sha256"] = hashlib.sha256(BOLT_HEX_HEAD_PATH.read_bytes()).hexdigest()
    DEST.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
