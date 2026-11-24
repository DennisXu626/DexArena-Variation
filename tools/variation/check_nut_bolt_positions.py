"""Measure Nut & Bolt reset layouts, contacts and fingertip reach."""

import argparse
import csv
import hashlib
from importlib.metadata import version
from itertools import product
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import gymnasium as gym
import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation
import torch

# The private SDK launcher executes this script through runpy.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_cabinet_positions import env_digest, setup_motion, solve_arm, value
from mani_skill.utils.structs.pose import Pose
import sapien
import tasks
from tasks.nut_bolt.nut_bolt_long import BOLT_HEX_HEAD_PATH, NutBoltLongEnv, TASK_PHASES
from tasks.nut_bolt.position_layout import (
    BOLT_SPAWN_AXIAL_SPIN_DEG,
    BOLT_SPAWN_RADIUS_M,
    BOLT_SPAWN_YAW_DEG,
    TABLE_NUT_HALF_RANGE_M,
    THREADED_NUT_RELATIVE_YAW_DEG,
    UPRIGHT_BOLT_RADIUS_M,
)


ROOT = Path(__file__).resolve().parents[2]
GPU_MEMORY = {
    "max_rigid_contact_count": 2**17,
    "max_rigid_patch_count": 2**16,
    "found_lost_pairs_capacity": 2**20,
}
IK_LIMIT_M = 0.015
IK_ATTEMPT_LIMIT_M = 0.07
SUPPORT_STEPS = 10
TASKS = ("PickBolt", "SeatNut", "TurnNut")


def shape_local_points(shape):
    if hasattr(shape, "half_size"):
        return np.array(list(product(*[[-x, x] for x in shape.half_size])))
    if hasattr(shape, "half_length"):
        angles = np.arange(256) * 2 * np.pi / 256
        ring = shape.radius * np.column_stack([np.cos(angles), np.sin(angles)])
        return np.concatenate([
            np.column_stack([np.full(len(ring), x), ring])
            for x in (-shape.half_length, shape.half_length)
        ])
    return np.asarray(shape.vertices) * np.asarray(shape.scale)


def orient(raw_pose):
    return Rotation.from_quat(np.roll(raw_pose[3:], -1))


def as_pose(pose):
    return np.r_[pose.p, pose.q].astype(float)


def shapes_world(shapes, raw_pose):
    outer = orient(raw_pose)
    for shape in shapes:
        local = as_pose(shape.local_pose)
        combined = outer * orient(local)
        center = outer.apply(local[:3]) + raw_pose[:3]
        corners = combined.apply(shape_local_points(shape)) + center
        if hasattr(shape, "half_length"):
            # Use analytic cylinder extrema when calculating support clearance.
            direction = combined.as_matrix()[:, 0]
            half_range = np.abs(direction) * shape.half_length
            half_range += shape.radius * np.sqrt(np.maximum(0, 1 - direction**2))
            lo, hi = center - half_range, center + half_range
        else:
            lo, hi = corners.min(0), corners.max(0)
        yield corners, lo, hi


def hull(points):
    points = np.unique(np.asarray(points)[:, :2], axis=0)
    return points[ConvexHull(points).vertices].tolist()


def geometry(e):
    table = e.table_scene.table
    shape, = table._bodies[0].collision_shapes
    _, lo, hi = next(shapes_world([shape], value(table.pose.raw_pose[0])))
    base_parts = []
    for link in e.agent.robot._objs[0].links:
        if "_mobile_base_link_" in link.name:
            parts = shapes_world(link.collision_shapes, as_pose(link.entity.pose))
            base_parts.extend(hull(corners) for corners, _, _ in parts)
    bolt_shapes = e.bolt._bodies[0].collision_shapes
    identity = np.array([0., 0., 0., 1., 0., 0., 0.])
    head, _, _ = next(shapes_world(bolt_shapes[-1:], identity))
    result = {
        "table_lo": lo.tolist(), "table_hi": hi.tolist(), "base_parts_xy_m": base_parts,
        "bolt_local_vertices_m": head.tolist(),
        "bolt_cylinders": [
            {"local_pose": as_pose(shape.local_pose).tolist(), "radius_m": shape.radius,
             "half_length_m": shape.half_length}
            for shape in bolt_shapes[:-1]
        ],
        "bolt_spawn_xy_m": e.bolt_spawn_xy, "bolt_spawn_radius_m": e.bolt_spawn_radius,
        "bolt_spawn_tilt_range_deg": np.rad2deg(e.bolt_spawn_tilt_range).tolist(),
        "handoff_xy_m": e.bolt_place_center_xy, "handoff_radius_m": e.bolt_place_radius,
        "bolt_head_circumradius_m": e.hex_head_circumradius,
        "table_nut_xy_m": e.nut_spawn_xy, "table_nut_native_half_range_m": e.object_init_xy_noise,
        "platform_radius_m": e.platform_radius, "platform_support_height_m": e.platform_start_z,
        "nut_half_height_m": e.nut_half_height,
        "candidate": {
            "bolt_spawn_radius_m": BOLT_SPAWN_RADIUS_M, "bolt_spawn_yaw_deg": BOLT_SPAWN_YAW_DEG,
            "bolt_spawn_axial_spin_deg": BOLT_SPAWN_AXIAL_SPIN_DEG,
            "upright_bolt_radius_m": UPRIGHT_BOLT_RADIUS_M,
            "table_nut_half_range_m": TABLE_NUT_HALF_RANGE_M,
            "threaded_nut_relative_yaw_deg": THREADED_NUT_RELATIVE_YAW_DEG,
        },
    }
    if e.has_nut:
        free = [corners.tolist() for corners, _, _ in
                shapes_world(e.nut._bodies[0].collision_shapes, identity)]
        result["nut_local_parts_m"] = free
        link = e.nut_revolute.links_map["threaded_nut"]
        result["threaded_nut_local_parts_m"] = [
            corners.tolist() for corners, _, _ in shapes_world(link._objs[0].collision_shapes, identity)
        ]
    return result


def samples():
    def circle(center, radius):
        return [center] + [
            (np.asarray(center) + radius * np.array([np.cos(angle), np.sin(angle)])).tolist()
            for angle in np.arange(8) * np.pi / 4
        ]

    c = NutBoltLongEnv
    bolt = circle(c.bolt_spawn_xy, BOLT_SPAWN_RADIUS_M)
    upright = circle(c.bolt_place_center_xy, UPRIGHT_BOLT_RADIUS_M)
    nut = [
        (np.asarray(c.nut_spawn_xy) + np.asarray(TABLE_NUT_HALF_RANGE_M) * [x, y]).tolist()
        for x, y in [(0, 0), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    ]
    yield "PickBolt", [
        *[(f"P-XY{index}", {"bolt_spawn_xy_m": p}, False) for index, p in enumerate(bolt)],
        *[(f"P-Y{yaw:+d}", {"bolt_spawn_yaw_deg": yaw}, False) for yaw in BOLT_SPAWN_YAW_DEG if yaw],
        ("P-near-yaw", {"bolt_spawn_xy_m": bolt[6], "bolt_spawn_yaw_deg": -90}, False),
        ("P-far-yaw", {"bolt_spawn_xy_m": bolt[1], "bolt_spawn_yaw_deg": 90}, False),
        ("P-reject-xy", {"bolt_spawn_xy_m": [c.bolt_spawn_xy[0] - BOLT_SPAWN_RADIUS_M - .0001,
                                             c.bolt_spawn_xy[1]]}, True),
        ("P-reject-yaw", {"bolt_spawn_yaw_deg": 89.9}, True),
    ]
    yield "SeatNut", [
        *[(f"S-B{index}", {"upright_bolt_xy_m": p}, False) for index, p in enumerate(upright)],
        *[(f"S-N{index}", {"table_nut_xy_m": p}, False) for index, p in enumerate(nut) if index],
        ("S-near", {"upright_bolt_xy_m": upright[8], "table_nut_xy_m": nut[3]}, False),
        ("S-far", {"upright_bolt_xy_m": upright[1], "table_nut_xy_m": nut[8]}, False),
        ("S-reject-bolt", {"upright_bolt_xy_m": [c.bolt_place_center_xy[0] + UPRIGHT_BOLT_RADIUS_M + .0001,
                                                c.bolt_place_center_xy[1]]}, True),
        ("S-reject-nut", {"table_nut_xy_m": [c.nut_spawn_xy[0], c.nut_spawn_xy[1] - TABLE_NUT_HALF_RANGE_M[1]
                                                                               - .0001]}, True),
    ]
    yield "TurnNut", [
        *[(f"T-B{index}", {"upright_bolt_xy_m": p}, False) for index, p in enumerate(upright)],
        *[(f"T-Y{yaw:+d}", {"threaded_nut_relative_yaw_deg": yaw}, False)
          for yaw in THREADED_NUT_RELATIVE_YAW_DEG if yaw],
        ("T-far-yaw", {"upright_bolt_xy_m": upright[1], "threaded_nut_relative_yaw_deg": 20}, False),
        ("T-reject-bolt", {"upright_bolt_xy_m": [c.bolt_place_center_xy[0],
                                                c.bolt_place_center_xy[1] + UPRIGHT_BOLT_RADIUS_M + .0001]}, True),
        ("T-reject-yaw", {"threaded_nut_relative_yaw_deg": 20.1}, True),
    ]


def read_pose(actor, i):
    return value(actor.pose.raw_pose[i]).astype(float)


def actor_for(e, task):
    if task == "PickBolt":
        return e.bolt, e.bolt._bodies[0].collision_shapes
    if task == "SeatNut":
        return e.nut, e.nut._bodies[0].collision_shapes
    link = e.nut_revolute.links_map["threaded_nut"]
    return link, link._objs[0].collision_shapes


def readback(e, task, request, i, g):
    bolt = read_pose(e.bolt, i)
    target, shapes = actor_for(e, task)
    pose = read_pose(target, i)
    points, lo, hi = zip(*shapes_world(shapes, pose))
    lo, hi = np.min(lo, axis=0), np.max(hi, axis=0)
    table_clearance = float(np.min(np.r_[lo[:2] - g["table_lo"][:2], g["table_hi"][:2] - hi[:2]]))
    stage = int(e._task_phase[i])
    flags = {name: bool(getattr(e, "_" + name)[i]) for name in
             ("bolt_locked", "stage_bolt_placed", "stage_nut_placed", "nut_engaged", "stage_turned")}
    result = {
        "bolt_pose": bolt.tolist(), "target_pose": pose.tolist(), "task_phase": TASK_PHASES[stage],
        **flags, "robot_qpos": value(e.agent.robot.qpos[i]).tolist(),
        "target_table_edge_clearance_m": table_clearance,
        "target_lowest_z_m": float(lo[2]), "target_outline_xy_m": hull(np.concatenate(points)),
        "bolt_linear_velocity_m_s": value(e.bolt.linear_velocity[i]).tolist(),
        "bolt_angular_velocity_rad_s": value(e.bolt.angular_velocity[i]).tolist(),
    }
    expected_stage = dict(PickBolt="bolt_pick_place", SeatNut="nut_pick_place", TurnNut="turn")[task]
    assert result["task_phase"] == expected_stage
    assert flags == dict(bolt_locked=task != "PickBolt", stage_bolt_placed=task != "PickBolt",
                         stage_nut_placed=task == "TurnNut", nut_engaged=task == "TurnNut", stage_turned=False)
    assert table_clearance > 0
    assert np.linalg.norm(result["bolt_linear_velocity_m_s"]) < 1e-7
    assert np.linalg.norm(result["bolt_angular_velocity_rad_s"]) < 1e-7
    if task == "PickBolt":
        yaw = request.get("bolt_spawn_yaw_deg", 0)
        axis = orient(bolt).apply([0, 0, 1])
        expected_axis = [np.cos(np.deg2rad(yaw)), np.sin(np.deg2rad(yaw)), 0]
        result["bolt_axis_world"] = axis.tolist()
        result["bolt_spawn_world_yaw_deg"] = float(np.rad2deg(np.arctan2(axis[1], axis[0])))
        expected = (Rotation.from_euler("z", yaw, degrees=True)
                    * Rotation.from_euler("y", 90, degrees=True)
                    * Rotation.from_euler("z", BOLT_SPAWN_AXIAL_SPIN_DEG, degrees=True))
        assert np.allclose(bolt[:2], request.get("bolt_spawn_xy_m", e.bolt_spawn_xy), atol=1e-6, rtol=0)
        assert np.allclose(axis, expected_axis, atol=1e-6, rtol=0)
        assert np.allclose(orient(bolt).as_matrix(), expected.as_matrix(), atol=1e-6, rtol=0)
        assert abs(lo[2] - g["table_hi"][2] - .001) <= 1e-6
        return result
    assert np.allclose(bolt[:3], [*request.get("upright_bolt_xy_m", e.bolt_place_center_xy), e.bolt_height / 2],
                       atol=1e-6, rtol=0)
    assert np.allclose(orient(bolt).as_matrix(), np.eye(3), atol=1e-6, rtol=0)
    platform_pose = read_pose(e.platform, i)
    assert np.allclose(platform_pose[:3], [*bolt[:2], e.platform_start_z - e.platform_half_height],
                       atol=1e-6, rtol=0)
    bottom = np.asarray(g["bolt_local_vertices_m"])
    bottom = bottom[np.isclose(bottom[:, 2], bottom[:, 2].min())]
    head_margin = e.bolt_place_radius - np.linalg.norm(
        orient(bolt).apply(bottom)[:, :2] + bolt[:2] - np.asarray(e.bolt_place_center_xy), axis=1
    ).max()
    result.update(platform_pose=platform_pose.tolist(), bolt_head_disc_clearance_m=float(head_margin),
                  bolt_placement_candidate=bool(e._bolt_placement_state()[0][i]),
                  threaded_root_pose=read_pose(e.nut_revolute, i).tolist(), free_nut_pose=read_pose(e.nut, i).tolist())
    assert head_margin > 0 and result["bolt_placement_candidate"]
    if task == "SeatNut":
        assert np.allclose(pose[:2], request.get("table_nut_xy_m", e.nut_spawn_xy), atol=1e-6, rtol=0)
        assert np.allclose(orient(pose).as_matrix(), np.eye(3), atol=1e-6, rtol=0)
        assert abs(lo[2] - g["table_hi"][2] - .001) <= 1e-6
        assert result["threaded_root_pose"][2] >= 4.99
        nut_radius = float(np.linalg.norm(np.concatenate(points)[:, :2] - pose[:2], axis=1).max())
        clearance = float(np.linalg.norm(pose[:2] - bolt[:2]) -
                          nut_radius - max(e.platform_radius, e.hex_head_circumradius))
        result["nut_bolt_plan_clearance_lower_bound_m"] = clearance
        assert clearance > 0
    else:
        yaw = float(np.rad2deg(value(e.nut_revolute.get_qpos()[i, 0])))
        progress = float(e._cum_rotation[i])
        result.update(threaded_relative_yaw_deg=yaw, turn_progress_rad=progress,
                      threaded_axial_depth_m=float(e._threaded_depth[i]))
        expected_yaw = request.get("threaded_nut_relative_yaw_deg", 0)
        assert abs(yaw - expected_yaw) <= 1e-4 and abs(progress) < 1e-7
        assert np.allclose(pose[:2], bolt[:2], atol=1e-6, rtol=0)
        assert np.allclose(orient(pose).as_matrix(), Rotation.from_euler("z", expected_yaw, degrees=True).as_matrix(),
                           atol=1e-6, rtol=0)
        assert abs(lo[2] - e.platform_start_z) <= 1e-6
        assert result["free_nut_pose"][2] >= 4.99
    return result


def full_action(env, e):
    action = torch.empty((e.num_envs, env.action_space.shape[-1]), device=e.device)
    for key, (lo, hi) in e.agent.controller.action_mapping.items():
        indices = e.agent.controller.controllers[key].active_joint_indices
        action[:, lo:hi] = e.agent.robot.qpos[:, indices]
    return action


def support_probe(env, e, task, i, before, g):
    target, shapes = actor_for(e, task)
    support = e.platform if task == "TurnNut" else e.table_scene.table
    nominal_z = e.platform_start_z if task == "TurnNut" else g["table_hi"][2]
    action = full_action(env, e)
    forces = []
    for _ in range(SUPPORT_STEPS):
        env.step(action)
        forces.append(float(e.scene.get_pairwise_contact_forces(target, support)[i].norm()))
    pose = read_pose(target, i)
    lows = np.min([lower for _, lower, _ in shapes_world(shapes, pose)], axis=0)
    highs = np.max([upper for _, _, upper in shapes_world(shapes, pose)], axis=0)
    before = np.asarray(before)
    angle = np.rad2deg((orient(pose) * orient(before).inv()).magnitude())
    moved = float(np.linalg.norm(pose[:3] - before[:3]))
    edge = float(np.min(np.r_[lows[:2] - g["table_lo"][:2], g["table_hi"][:2] - highs[:2]]))
    stable = (moved <= .02 and abs(lows[2] - nominal_z) <= .003 and edge > 0 and
              angle <= 20 and (forces[-1] > .03 or task == "TurnNut"))
    return {
        "after_pose": pose.tolist(), "elapsed_control_steps": SUPPORT_STEPS,
        "elapsed_seconds": SUPPORT_STEPS / e.control_freq,
        "shift_m": moved, "angle_delta_deg": float(angle), "peak_support_force_N": max(forces),
        "final_support_force_N": forces[-1], "support_clearance_m": float(lows[2] - nominal_z),
        "table_edge_clearance_m": edge, "passed": bool(stable),
        "support": "fixed-root revolute; plate plane" if task == "TurnNut" else "physical table contact",
    }


def motion_targets(e, task, i, read):
    chain = setup_motion(e, i)
    tips = chain[-1]
    pose = np.asarray(read["target_pose"])
    p = pose[:3].copy()
    if task == "PickBolt":
        axis = orient(pose).apply([0, 0, 1])
        direction = np.r_[-axis[1], axis[0], 0.]
        p += .01 * axis
        p[2] += .011
    else:
        direction = orient(pose).apply([0, 1, 0])
        p[2] += .008 if task == "SeatNut" else .004
    if np.dot(tips[1] - tips[0], direction) < 0:
        direction = -direction
    spread = np.stack([-direction, direction]) * np.linalg.norm(tips[1] - tips[0]) / 2
    approached = p - np.array([.02, 0., -.055])
    targets = [approached, p]
    names = ["above and left of body", "opposed finger approach"]
    if task == "TurnNut":
        turn = Rotation.from_euler("z", 15, degrees=True)
        targets.append(p)
        names.append("15 degree counterclockwise finger path")
    else:
        targets.append(p + [0., 0., .055])
        names.append("55 mm lift")
        if task == "SeatNut":
            targets.append(np.r_[read["bolt_pose"][:2], e.bolt_height + .045])
            names.append("above upright bolt tip")
    spans = [spread for _ in targets]
    if task == "TurnNut":
        spans[-1] = turn.apply(spread)
    arm, errors = [], []
    prev = chain[2]
    for point, span in zip(targets, spans):
        prev, error = solve_arm(chain, point + span, prev)
        arm.append(prev.tolist())
        errors.append(error)
    return {"stages": names, "centres_xyz_m": np.asarray(targets).tolist(), "arm_qpos": arm,
            "fingertip_max_errors_m": errors, "limit_m": IK_LIMIT_M, "passed": max(errors) <= IK_LIMIT_M}


def short_attempt(env, e, task, i, ik):
    if max(ik["fingertip_max_errors_m"][:2]) > IK_ATTEMPT_LIMIT_M:
        return {"executed": False, "reason": "approach error exceeds short action start limit",
                "start_limit_m": IK_ATTEMPT_LIMIT_M}
    target, _ = actor_for(e, task)
    action = full_action(env, e)
    ctrl = e.agent.controller
    arm_lo, arm_hi = ctrl.action_mapping["arm"]
    hand_lo, hand_hi = ctrl.action_mapping["hand"]
    hand0 = action[i, hand_lo:hand_hi].clone()
    close = hand0.clone()
    limits = e.agent.robot.get_qlimits()[i, ctrl.controllers["hand"].active_joint_indices]
    for index, name in enumerate(e.agent.hand_joint_names):
        if name.endswith(("PIP", "DIP", "_IP", "MCP_FE")):
            close[index] = torch.clamp(hand0[index] + .45, min=limits[index, 0], max=limits[index, 1])
    start_z = read_pose(target, i)[2]
    trace = []
    for phase, arm in enumerate(ik["arm_qpos"][:3]):
        initial = action[i, arm_lo:arm_hi].clone()
        desired = torch.as_tensor(arm, device=e.device)
        for step in range(25):
            action[i, arm_lo:arm_hi] = torch.lerp(initial, desired, min(1., (step + 1) / 16))
            if phase >= 1:
                action[i, hand_lo:hand_hi] = torch.lerp(hand0, close, min(1., (step + 1) / 14)) if phase == 1 else close
            env.step(action)
            forces = [float(e.scene.get_pairwise_contact_forces(link, target)[i].norm())
                      for link in e.agent.tip_links[:2]]
            trace.append({
                "phase": phase, "step": step + 1, "finger_contact_N": forces,
                "lift_m": float(read_pose(target, i)[2] - start_z),
                "accumulated_turn_rad": float(e._cum_rotation[i]),
            })
    dual = [row for row in trace if min(row["finger_contact_N"]) > .05]
    metric = "accumulated_turn_rad" if task == "TurnNut" else "lift_m"
    threshold = float(np.deg2rad(8)) if task == "TurnNut" else .01
    return {"executed": True, "stages": ik["stages"][:3], "trace": trace,
            "contact_qualified_maximum": max((row[metric] for row in dual), default=0.),
            "overall_maximum": max(row[metric] for row in trace), "metric": metric,
            "threshold": threshold, "opposed_contact_frames": len(dual),
            "peak_tip_contact_N": max(max(row["finger_contact_N"]) for row in trace),
            "passed": any(row[metric] >= threshold for row in dual)}


def state(e, index):
    combined = {**e.get_state_dict(), "elapsed_steps": e.elapsed_steps}
    return env_digest(combined, index)


def compare(left, right, prefix=""):
    diffs = []
    for key, value_at_key in left.items():
        path = f"{prefix}/{key}" if prefix else key
        if isinstance(value_at_key, dict):
            diffs.extend(compare(value_at_key, right[key], path))
        elif value_at_key != right[key]:
            diffs.append(path)
    return diffs


def predicate_probes(env, e, seed):
    """Construct independent CPU states for the existing six-vertex rule."""
    env.reset(seed=seed)
    initial = e.get_state_dict()
    initial_hash = state(e, 0)
    probes = []
    radius = e.bolt_place_radius - e.hex_head_circumradius
    for label, shift in (("CENTER", 0.), ("EAST-IN", radius - 1e-6),
                         ("EAST-EXACT", radius), ("EAST-OUT", radius + 1e-6)):
        p = [e.bolt_place_center_xy[0] + shift, e.bolt_place_center_xy[1], e.bolt_height / 2]
        try:
            e.bolt.set_pose(Pose.create_from_pq(p=p, q=[1, 0, 0, 0]))
            answer = bool(e._bolt_placement_state()[0][0])
            probes.append({"kind": "manufactured_predicate", "label": label, "seed": seed,
                           "fixture_xyz_m": p, "six_vertex_predicate": answer})
        finally:
            e.set_state_dict(initial)
        assert state(e, 0) == initial_hash
    assert [row["six_vertex_predicate"] for row in probes if row["label"] != "EAST-EXACT"] == [True, True, False]
    return probes


def check_task(args, task, entries, out):
    num = 2 if args.sim_backend == "physx_cuda" else 1
    spec = f"NutBolt{task}-Sharpa-v1"
    build = dict(num_envs=num, sim_backend=args.sim_backend, obs_mode="state", control_mode="pd_joint_pos",
                 render_mode=None, reconfiguration_freq=0, enhanced_determinism=True)
    if num == 2:
        build["sim_config"] = {"gpu_memory_config": GPU_MEMORY}
    env = gym.make(spec, **build)
    e = env.unwrapped
    results, predicates = [], []
    try:
        g = geometry(e)
        env.reset(seed=700)
        native1 = state(e, 0)
        env.reset(seed=700, options={})
        assert state(e, 0) == native1
        native_robot = [value(e.agent.robot.qpos[i]).tolist() for i in range(num)]
        env.reset(seed=700, options={"position_layout": {str(i): {} for i in range(num)}})
        assert native_robot == [value(e.agent.robot.qpos[i]).tolist() for i in range(num)]
        for j, (label, request, rejected) in enumerate(entries):
            i = j % num
            seed = 710 + 50 * TASKS.index(task) + j
            env.reset(seed=seed)
            opts = {"env_idx": [i], "position_layout": {str(i): request}}
            states = [state(e, k) for k in range(num)]
            row = {"kind": "rejection" if rejected else "initialization", "task": spec, "label": label,
                   "seed": seed, "env_idx": i, "build": build, "options": opts}
            if rejected:
                try:
                    env.reset(options=opts)
                except ValueError as exc:
                    row["rejected_reason"] = str(exc)
                else:
                    raise AssertionError(f"{label}: out-of-domain request was accepted")
                row["rejection_state_diffs"] = [compare(snapshot, state(e, k)) for k, snapshot in enumerate(states)]
                assert not any(row["rejection_state_diffs"])
            else:
                env.reset(options=opts)
                row["unselected_state_diffs"] = compare(states[1-i], state(e, 1-i)) if num == 2 else None
                assert not row["unselected_state_diffs"], (label, row["unselected_state_diffs"])
                row["readback"] = readback(e, task, request, i, g)
                row["ik"] = motion_targets(e, task, i, row["readback"])
                row["support"] = support_probe(env, e, task, i, row["readback"]["target_pose"], g)
                if not row["support"]["passed"]:
                    print(f"SUPPORT FAILED {label}: {row['support']}", flush=True)
                if not args.no_attempt and label in {
                    "P-XY0", "P-far-yaw", "S-B0", "S-near", "T-B0", "T-far-yaw"
                }:
                    env.reset(seed=seed)
                    env.reset(options=opts)
                    assert row["readback"]["robot_qpos"] == value(e.agent.robot.qpos[i]).tolist()
                    row["short_attempt"] = short_attempt(env, e, task, i, row["ik"])
            results.append(row)
            print(f"{label}: {row['kind']}" +
                  (f" support={row['support']['passed']} IK={row['ik']['passed']}" if not rejected else ""),
                  flush=True)
            (out / f"{task}.json").write_text(json.dumps({"geometry": g, "rows": results}, indent=2) + "\n",
                                              encoding="utf-8")
        if task == "PickBolt" and num == 1:
            predicates = predicate_probes(env, e, seed=705)
        assert all(row.get("support", {}).get("passed", True) for row in results)
        return {"geometry": g, "rows": results, "predicates": predicates,
                "native_repeat_exact": True, "same_seed_robot_qpos_exact": True}
    finally:
        env.close()


def write_csv(path, results):
    fields = ["kind", "task", "label", "seed", "env_idx", "build", "options", "readback", "support",
              "ik_pass", "ik_tip_max_error_m", "short_attempt_executed", "short_attempt_pass",
              "unselected_state_diffs", "rejected_reason", "rejection_state_diffs", "predicate_fixture"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv_out = csv.DictWriter(stream, fields)
        csv_out.writeheader()
        for task, item in results.items():
            for row in item["rows"]:
                record = {k: row.get(k) for k in fields}
                record["ik_pass"] = row.get("ik", {}).get("passed")
                errors = row.get("ik", {}).get("fingertip_max_errors_m", [])
                record["ik_tip_max_error_m"] = max(errors) if errors else None
                record["short_attempt_executed"] = row.get("short_attempt", {}).get("executed")
                record["short_attempt_pass"] = row.get("short_attempt", {}).get("passed")
                csv_out.writerow({k: json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list)) else v
                                  for k, v in record.items()})
            for probe in item["predicates"]:
                csv_out.writerow({k: probe[k] for k in ("kind", "label", "seed")} |
                                 {"task": f"NutBolt{task}-Sharpa-v1", "env_idx": 0, "predicate_fixture": json.dumps(probe)})


def source_identity():
    paths = sorted((ROOT / "tasks/nut_bolt").glob("*.py")) + [
        Path(__file__).resolve(), Path(__file__).resolve().with_name("check_cabinet_positions.py"), BOLT_HEX_HEAD_PATH,
    ]
    return {file.relative_to(ROOT).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in paths}


def check_long():
    env = gym.make("NutBoltLong-Sharpa-v1", sim_backend="physx_cpu", render_mode=None,
                   obs_mode="state", reconfiguration_freq=0)
    e = env.unwrapped
    stages = {}
    try:
        for phase in TASK_PHASES:
            env.reset(seed=700, options={"task_phase": phase})
            stages[phase] = {
                "phase": TASK_PHASES[int(e._task_phase[0])],
                "bolt_locked": bool(e._bolt_locked[0]),
                "nut_engaged": bool(e._nut_engaged[0]),
            }
            assert stages[phase] == {"phase": phase, "bolt_locked": phase in ("nut_pick_place", "turn"),
                                     "nut_engaged": phase == "turn"}
        before = state(e, 0)
        try:
            env.reset(options={"position_layout": {"0": {}}})
        except ValueError as exc:
            assert state(e, 0) == before
            return {"stages": stages, "explicit_rejected_without_mutation": str(exc)}
        raise AssertionError("Long accepted a short-task position_layout")
    finally:
        env.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim-backend", choices=["physx_cpu", "physx_cuda"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--physx-gpu-dir", type=Path, help="accepted from the native-lock SDK launcher")
    parser.add_argument("--task", choices=TASKS)
    parser.add_argument("--no-attempt", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.sim_backend == "physx_cuda":
        if os.name == "nt" and not sapien.physx.is_gpu_enabled():
            if args.physx_gpu_dir is None:
                raise RuntimeError("Use the native-lock SDK launcher for Windows CUDA")
            sapien.physx._enable_gpu()
        assert sapien.physx.indexed_gpu_apply_patch_version() == 1
        assert sapien.physx.native_gpu_lock_sync_patch_version() == 1
    source = source_identity()
    started = time.perf_counter()
    settings = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "source_sha256": source, "platform": platform.platform(), "python": platform.python_version(),
                "sapien": sapien.__version__, "mani_skill": version("mani-skill"), "torch": torch.__version__,
                "backend": args.sim_backend, "pid": os.getpid()}
    results = {}
    for task, rows in samples():
        if args.task is None or task == args.task:
            results[task] = check_task(args, task, rows, args.output)
    long_check = check_long() if args.sim_backend == "physx_cpu" and args.task is None else None
    assert source_identity() == source
    (args.output / "results.json").write_text(json.dumps({
        "settings": settings, "elapsed_seconds": time.perf_counter() - started,
        "tasks": results, "long": long_check,
    }, indent=2) + "\n", encoding="utf-8")
    write_csv(args.output / "POINTS.csv", results)


if __name__ == "__main__":
    main()
