"""Sample real Office Desk resets, support, fingertip IK and short motions."""

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import gymnasium as gym
import numpy as np
import sapien
import torch
from mani_skill.utils.geometry.trimesh_utils import get_component_meshes
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation

import tasks
from tasks.office_desk.office_desk_click_mouse import MOUSE_MODEL
from tasks.office_desk.office_desk_type_keys import (
    KEYBOARD_MODELS, TARGET_KEY_LABELS, _key_target_marker_pose, press_contact_link,
)
from tasks.office_desk.position_layout import XY_BOUNDS_M, YAW_OFFSETS_DEG
from tools.variation import check_furniture_appearance as state
from tools.variation import check_office_devices_runtime as assets


TOLERANCE_M = 2e-6
IK_THRESHOLD_M = .015
SUPPORT_STEPS = 8
SEEDS = {"OpenLaptop": 517, "TypeKeys": 617, "ClickMouse": 717}
MODELS = {"OpenLaptop": "10211", "TypeKeys": "13106", "ClickMouse": "101408"}


def read(tensor):
    return tensor.detach().cpu().numpy().astype(float)


def orient(pose):
    return Rotation.from_quat(pose[[4, 5, 6, 3]])


def vertices(meshes):
    return np.concatenate([mesh.vertices for mesh in meshes])


def outline(points):
    xy = np.unique(points[:, :2].round(8), axis=0)
    return xy[ConvexHull(xy).vertices].tolist()


def transform(points, pose):
    return orient(pose).apply(points) + pose[:3]


def read_geometry(base, art, index):
    table = base.table_scene.table
    table_vertices = transform(vertices(get_component_meshes(table._bodies[index])),
                               read(table.pose.raw_pose[index]))
    robot = {}
    for link in base.agent.robot.links:
        if not link.name.startswith("mobile_base_link_"):
            continue
        meshes = get_component_meshes(link._objs[index])
        if meshes:
            robot[link.name] = outline(transform(vertices(meshes), read(link.pose.raw_pose[index])))
    if not robot:
        for link in base.agent.robot.links[:3]:
            meshes = get_component_meshes(link._objs[index])
            if meshes:
                robot[link.name] = outline(transform(vertices(meshes), read(link.pose.raw_pose[index])))

    colliders = {}
    for link in art.links:
        meshes = get_component_meshes(link._objs[index])
        if meshes:
            colliders[link.name] = vertices(meshes)
    return table_vertices, robot, colliders


def body_points(art, colliders, index):
    return {name: transform(points, read(art.links_map[name].pose.raw_pose[index]))
            for name, points in colliders.items()}


def read_controls(base, kind, index):
    if kind == "OpenLaptop":
        screen = base._screen_links[index]
        joint = base.laptop.get_active_joints()[0]
        hinge = read(joint.global_pose.raw_pose[index])
        edge = read(base._screen_edge_position()[index])
        angle = float(base._opening_angle()[index])
        axis = orient(hinge).apply([1., 0., 0.])
        direction = math.copysign(1.0, float(base.qpos_open[index] - base.qpos_closed[index]))
        target_angle = float(base.target_angle[index])
        angles = np.linspace(angle, target_angle, 11)
        sweep = [Rotation.from_rotvec(axis * direction * (other - angle))
                 for other in angles]
        tracker = [(rot.apply(edge - hinge[:3]) + hinge[:3]).tolist() for rot in sweep]
        return {
            "targets_xyz_m": {"lid edge": edge.tolist()},
            "lid": {"link": screen.name, "hinge_xyz_m": hinge[:3].tolist(),
                    "axis_world": axis.tolist(), "edge_sweep_xyz_m": tracker,
                    "angles_deg": np.degrees(angles).tolist(),
                    "sweep_rotation_vectors": [rot.as_rotvec().tolist() for rot in sweep]},
        }
    if kind == "TypeKeys":
        targets = {}
        for slot, label in enumerate(TARGET_KEY_LABELS):
            link = base._target_links[index][slot]
            targets[label] = transform(read(base._target_local_top[index, slot]),
                                       read(link.pose.raw_pose[0])).tolist()
        frame = base._target_key_frame()
        marker = base.key_target_marker
        marker_evidence = None
        if marker is not None:
            key = base._target_links[index][0]
            expected = _key_target_marker_pose(key, pose=key.pose.sp)
            measured = read(marker.pose.raw_pose[index])
            marker_evidence = {"pose": measured.tolist(), "expected_xyz_m": expected.p.tolist(),
                               "error_m": float(np.linalg.norm(measured[:3] - expected.p))}
        return {"targets_xyz_m": targets, "press_direction_xyz": read(frame["press"][index]).tolist(),
                "key_links": {label: link.name for label, link in
                              zip(TARGET_KEY_LABELS, base._target_links[index])},
                "marker": marker_evidence}
    button = base._button_quantities()
    return {
        "targets_xyz_m": {"left button": read(button["released_top"][index]).tolist()},
        "press_direction_xyz": read(button["press_axis"][index]).tolist(),
        "button_links": {"left button": base._left_links[index].name,
                         "right button": base.mouse.get_active_joints()[int(base._right_indices[index])].child_link.name},
    }


def approach_waypoints(kind, controls):
    targets = controls["targets_xyz_m"]
    if kind == "OpenLaptop":
        edge = np.asarray(targets["lid edge"])
        sweep = np.asarray(controls["lid"]["edge_sweep_xyz_m"])
        direction = sweep[1] - edge
        direction /= np.linalg.norm(direction)
        return {"lid edge": np.stack((edge - .035 * direction, edge,
                                     sweep[2] + .004 * direction, sweep[4]))}
    press = np.asarray(controls["press_direction_xyz"])
    return {label: np.asarray(point) + np.outer((-.035, 0.0, .004, -.035), press)
            for label, point in targets.items()}


def finger(base, kind):
    tip = base.agent.tip_links[base.target_finger_id]
    return tip if kind == "OpenLaptop" else press_contact_link(base.agent, tip)


def solve_ik(base, kind, index, controls):
    robot = base.agent.robot
    arm = base.agent.controller.controllers["arm"]
    ids = arm.active_joint_indices
    home = read(robot.qpos[index, ids])
    bounds = read(robot.get_qlimits()[index, ids])
    joints = np.stack([read(robot.joints_map[name].global_pose.raw_pose[index])
                       for name in base.agent.arm_joint_names])
    axes = Rotation.from_quat(joints[:, [4, 5, 6, 3]]).as_matrix()[:, :, 0]
    origins = joints[:, :3]
    start = read(finger(base, kind).pose.p[index])

    def fk(q):
        point = start.copy()
        for origin, axis, delta in reversed(list(zip(origins, axes, q - home))):
            point = Rotation.from_rotvec(axis * delta).apply(point - origin) + origin
        return point

    results = {}
    for label, goals in approach_waypoints(kind, controls).items():
        q = home
        solutions, errors = [], []
        for goal in goals:
            q = least_squares(lambda qpos: fk(qpos) - goal, np.clip(q, *bounds.T),
                              bounds=bounds.T, max_nfev=55, ftol=1e-7, xtol=1e-7).x
            solutions.append(q.tolist())
            errors.append(float(np.linalg.norm(fk(q) - goal)))
        results[label] = {"targets_xyz_m": goals.tolist(), "joint_targets": solutions,
                          "errors_m": errors, "passed": max(errors) <= IK_THRESHOLD_M}
    return results


def hold_action(env):
    base = env.unwrapped
    controller = base.agent.controller
    result = torch.empty((base.num_envs, env.action_space.shape[-1]), device=base.device)
    for name, (lo, hi) in controller.action_mapping.items():
        result[:, lo:hi] = base.agent.robot.qpos[:, controller.controllers[name].active_joint_indices]
    return result


def table_probe(env, art, index, colliders, table):
    base = env.unwrapped
    action = hold_action(env)
    before = read(art.pose.raw_pose[index])
    points = body_points(art, colliders, index)
    lowest = min(points, key=lambda name: points[name][:, 2].min())
    gap_before = float(points[lowest][:, 2].min() - table[:, 2].max())
    loads = []
    for _ in range(SUPPORT_STEPS):
        env.step(action)
        forces = base.scene.get_pairwise_contact_forces(art.links_map[lowest], base.table_scene.table)
        loads.append(float(forces[index].norm()))
    after = read(art.pose.raw_pose[index])
    tilt = math.degrees(math.acos(np.clip(orient(after).apply([0, 0, 1])[2], -1, 1)))
    bottom_z = min(points[:, 2].min() for points in body_points(art, colliders, index).values())
    bottom_gap = float(bottom_z - table[:, 2].max())
    travel = float(np.linalg.norm(after[:3] - before[:3]))
    return {"control_steps": SUPPORT_STEPS, "settled_pose": after.tolist(), "support_link": lowest,
            "peak_table_contact_N": max(loads), "final_table_contact_N": loads[-1],
            "method": "native fixed-root drift and stand-off; collision loads recorded separately",
            "root_displacement_m": travel,
            "tilt_deg": tilt, "settled_bottom_gap_m": bottom_gap,
            "passed": (bottom_gap >= -.0001 and abs(bottom_gap - gap_before) < TOLERANCE_M
                       and tilt < .01 and travel < TOLERANCE_M)}


def short_attempt(env, art, kind, index, controls, ik, info):
    base = env.unwrapped
    label = next(iter(ik))
    label_key = {"OpenLaptop": "opening_angle_deg", "TypeKeys": "target_press_fraction",
                 "ClickMouse": "left_press_fraction"}[kind]
    initial = float(info[label_key][index])
    if kind == "OpenLaptop":
        device_link = controls["lid"]["link"]
    elif kind == "TypeKeys":
        device_link = controls["key_links"][label]
    else:
        device_link = controls["button_links"][label]
    tip = finger(base, kind)
    lo, hi = base.agent.controller.action_mapping["arm"]
    action = hold_action(env)
    history = []
    for stage, q in enumerate(ik[label]["joint_targets"]):
        start = action[index, lo:hi].clone()
        for step in range(24):
            alpha = min((step + 1) / 16, 1)
            action[index, lo:hi] = torch.lerp(start, start.new_tensor(q), alpha)
            _, _, _, _, info = env.step(action)
            loads = base.scene.get_pairwise_contact_forces(tip, art.links_map[device_link])
            row = {"stage": stage, "substep": step, "metric": float(info[label_key][index]),
                   "contact_N": float(loads[index].norm()), "success": bool(info["success"][index])}
            if kind == "TypeKeys":
                row["sequence_index"] = int(base.sequence_index[index])
            if kind == "ClickMouse":
                row["right_press_fraction"] = float(info["right_press_fraction"][index])
            history.append(row)
    peak = max(row["metric"] for row in history)
    if kind == "OpenLaptop":
        passed = peak - initial >= 5.0 and max(row["contact_N"] for row in history) > .01
        threshold = "screen contact > 0.01 N and hinge opening increases by at least 5 degrees"
    elif kind == "TypeKeys":
        passed = max(row["sequence_index"] for row in history) >= 1
        threshold = "native P cycle advances to A"
    else:
        passed = any(row["success"] for row in history)
        threshold = "native valid left-click success"
    return {"target": label, "metric": label_key, "initial": initial, "peak": peak,
            "threshold": threshold, "passed": passed, "control_steps": len(history), "trace": history}


def position_samples(base):
    device = base._position_device_name
    center = np.asarray(base._position_center)
    lower, upper = np.asarray(XY_BOUNDS_M[device])
    midpoint = (lower + upper) / 2
    span = (lower, midpoint, upper)
    signs = {-1: "-", 0: "0", 1: "+"}

    def request(xy, angle):
        return {f"{device}_xy_m": (center + xy).round(8).tolist(),
                f"{device}_yaw_offset_deg": angle}

    yield "N", "initialization", request([0, 0], 0)
    if np.any(midpoint):
        yield "M", "initialization", request(midpoint, 0)
    for x, y in product((-1, 0, 1), repeat=2):
        if (x, y) != (0, 0):
            yield f"XY{x:+d}{y:+d}", "initialization", request([span[x + 1][0], span[y + 1][1]], 0)
    for angle in YAW_OFFSETS_DEG:
        if angle:
            yield f"R{angle:+d}", "initialization", request([0, 0], angle)
    for x, y, angle in product((-1, 1), (-1, 1), (YAW_OFFSETS_DEG[0], YAW_OFFSETS_DEG[-1])):
        yield f"C{signs[x]}{signs[y]}{signs[int(np.sign(angle))]}", "initialization", request(
            [span[x + 1][0], span[y + 1][1]], angle)
    yield "X-OUT", "expected_rejection", request([lower[0] - .0001, 0], 0)
    yield "Y+OUT", "expected_rejection", request([0, upper[1] + .0001], 0)
    yield "R-OUT", "expected_rejection", request([0, 0], YAW_OFFSETS_DEG[-1] + .1)


def snap(base, art, index):
    snapshot = state.snapshot(base)
    for name, getter in (("device_force", art.get_qf),
                         ("device_target", art.get_drive_targets),
                         ("device_target_velocity", art.get_drive_velocities)):
        snapshot[name] = getter().detach().cpu().clone()
    marker = getattr(base, "key_target_marker", None)
    if marker is not None:
        snapshot["key_marker_pose"] = marker.pose.raw_pose.detach().cpu().clone()
    tensors = {name: torch.as_tensor(value[index]).cpu().numpy()
               for name, value in snapshot.items()}
    result = {name: hashlib.sha256(value.tobytes()).hexdigest()
              for name, value in tensors.items()}
    result["controller"] = state.controller_state(base, index)
    result["environment_rng"] = state.task_rng(base, index)
    return result


def measure(env, kind, art, index, expected, request, geometry, info):
    base = env.unwrapped
    device = base._position_device_name
    table, robot, colliders = geometry
    pose = read(art.pose.raw_pose[index])
    points = body_points(art, colliders, index)
    all_vertices = np.concatenate(list(points.values()))
    lower, upper = all_vertices.min(axis=0), all_vertices.max(axis=0)
    edge_margins = np.r_[lower[:2] - table[:, :2].min(axis=0),
                         table[:, :2].max(axis=0) - upper[:2]]
    controls = read_controls(base, kind, index)
    results = {}
    model_yaw = {
        "OpenLaptop": 0., "TypeKeys": KEYBOARD_MODELS[MODELS["TypeKeys"]]["yaw_offset"],
        "ClickMouse": MOUSE_MODEL["yaw_offset"],
    }[kind]
    rotation = orient(pose).as_matrix()
    yaw = (math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]) - model_yaw) + 180) % 360 - 180
    wanted = request[f"{device}_xy_m"]
    yaw_error = (yaw - request[f"{device}_yaw_offset_deg"] + 180) % 360 - 180
    qpos = read(art.qpos[index])
    qvel = read(art.qvel[index])
    bottom_gap = float(lower[2] - table[:, 2].max())
    results.update(root_xy=bool(np.max(np.abs(pose[:2] - wanted)) < TOLERANCE_M),
                   root_yaw=abs(yaw_error) < 1e-4,
                   inside_table=bool(min(edge_margins) > 0),
                   native_stand_off=bool(bottom_gap >= -.0001 and
                                         abs(bottom_gap - expected["table_gap"][index]) < TOLERANCE_M),
                   native_joint_position=bool(np.max(np.abs(qpos - expected["qpos"][index])) < TOLERANCE_M),
                   native_joint_velocity=bool(np.max(np.abs(qvel - expected["qvel"][index])) < TOLERANCE_M),
                   native_robot_pose=bool(np.max(np.abs(read(base.agent.robot.qpos[index]) -
                                                      expected["robot"][index])) < TOLERANCE_M),
                   initial_success_false=not bool(info["success"][index]))
    if kind == "TypeKeys":
        results.update(first_key_live=int(base.sequence_index[index]) == 0,
                       marker_follows_key=controls["marker"] is not None and
                                          controls["marker"]["error_m"] < TOLERANCE_M)
    elif kind == "OpenLaptop":
        opening = float(info["opening_angle_deg"][index])
        results["native_hinge_start"] = (base._cfg["start_angle_min_deg"] - 1e-5 <= opening
                                         <= base._cfg["start_angle_max_deg"] + 1e-5)
    else:
        results["released_buttons"] = (abs(float(info["left_press_fraction"][index])) < .001
                                        and abs(float(info["right_press_fraction"][index])) < .001)
    if kind == "OpenLaptop":
        lid = controls["lid"]
        hinge = np.asarray(lid["hinge_xyz_m"])
        screen = points[lid["link"]]
        frames = [Rotation.from_rotvec(v).apply(screen - hinge) + hinge
                  for v in lid.pop("sweep_rotation_vectors")]
        sweep = np.concatenate(frames)
        lid["collision_sweep_outline"] = outline(sweep)
        lid["sweep_bottom_table_gap_m"] = float(sweep[:, 2].min() - table[:, 2].max())
        lid["collision_sweep_height_range_m"] = [float(sweep[:, 2].min()), float(sweep[:, 2].max())]
        results["lid_sweep_table_clear"] = lid["sweep_bottom_table_gap_m"] >= -.0001

    attachments = [name for name in (controls.get("lid", {}).get("link"),
                   *controls.get("key_links", {}).values(), *controls.get("button_links", {}).values())
                   if name in points]
    return {
        "pose": pose.tolist(), "yaw_offset_deg": yaw, "qpos": qpos.tolist(), "qvel": qvel.tolist(),
        "controls": controls, "checks": results, "tightest_table_edge_m": float(min(edge_margins)),
        "edge_margins_m": edge_margins.tolist(), "initial_bottom_gap_m": bottom_gap,
        "table_outline": outline(table), "table_z_m": float(table[:, 2].max()),
        "robot_outlines": robot, "device_outline": outline(all_vertices),
        "support_outline": outline(all_vertices[all_vertices[:, 2] < lower[2] + .002]),
        "attachment_outlines": {name: outline(points[name]) for name in attachments},
    }


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_points(path, rows):
    fields = ("task", "id", "kind", "seed", "env_idx", "make_kwargs", "reset_options", "request",
              "pose", "yaw_offset_deg", "qpos", "initial_bottom_gap_m", "tightest_table_edge_m",
              "initialization_passed", "ik_passed", "support_passed", "short_attempt_passed",
              "isolation_passed", "rejection")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json.dumps(row[field], ensure_ascii=False, allow_nan=False)
                             if isinstance(row.get(field), (dict, list)) else row.get(field)
                             for field in fields})


def run(args):
    state.torch, state.np = torch, np
    kind = args.task
    gpu = args.backend == "physx_cuda"
    env_count = 2 if gpu else 1
    seed = SEEDS[kind]
    task = f"OfficeDesk{kind}-Sharpa-v1"
    make_kwargs = dict(num_envs=env_count, sim_backend=args.backend, control_mode="pd_joint_pos",
                       obs_mode="state", render_mode="rgb_array", reward_mode="sparse",
                       reconfiguration_freq=0)
    if gpu:
        make_kwargs["sim_config"] = {"gpu_memory_config": {"max_rigid_contact_count": 2**17,
            "max_rigid_patch_count": 2**16, "found_lost_pairs_capacity": 2**20}}
    if kind == "TypeKeys":
        make_kwargs["model_id"] = MODELS[kind]
        make_kwargs["show_guidance_markers"] = True
    assets.require_model_asset_root(kind)
    cache_before = assets.asset_hashes()
    collision_identity = assets.mouse_collision_identity() if kind == "ClickMouse" else None
    rows = []
    sources = [Path(__file__), ROOT / "tasks/office_desk/position_layout.py",
               ROOT / "tasks/office_desk/reset_scope.py"]
    sources += list((ROOT / "tasks/office_desk").glob("office_desk_*.py"))
    report = {
        "status": "running", "task": task, "platform": platform.platform(),
        "versions": {"python": platform.python_version(), "sapien": sapien.__version__,
                     "mani_skill": assets.metadata.version("mani-skill"), "torch": torch.__version__},
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_hashes": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(sources)},
        "model_asset_sha256": {path: sha for path, sha in cache_before.items() if path.startswith(MODELS[kind] + "/")},
        "mouse_collision_identity": collision_identity, "make_kwargs": make_kwargs,
        "ik_threshold_m": IK_THRESHOLD_M, "points": rows,
    }
    env = gym.make(task, **make_kwargs)
    try:
        base = env.unwrapped
        assert base.backend.sim_backend == args.backend and base.num_envs == env_count
        art = getattr(base, base._position_device_name)
        report["robot_asset_closure_sha256"] = assets.asset_closure(base)
        native = {
            "OpenLaptop": ("laptop_xy_noise", "laptop_xy_noise", "laptop_yaw_noise"),
            "TypeKeys": ("keyboard_random_x", "keyboard_random_y", "keyboard_random_yaw"),
            "ClickMouse": ("mouse_xy_noise", "mouse_xy_noise", "mouse_yaw_noise"),
        }[kind]
        report["native_xy_half_range_m"] = [getattr(base, name) for name in native[:2]]
        report["native_yaw_half_range_deg"] = math.degrees(getattr(base, native[2]))
        samples = list(position_samples(base))
        _, _, nominal = samples[0]
        env.reset(seed=seed)
        expected = {"qpos": read(art.qpos), "qvel": read(art.qvel), "robot": read(base.agent.robot.qpos)}
        geometry = {i: read_geometry(base, art, i) for i in range(env_count)}
        expected["table_gap"] = [
            float(min(part[:, 2].min() for part in body_points(art, colliders, i).values()) -
                  table[:, 2].max())
            for i, (table, _, colliders) in geometry.items()
        ]
        report["native_seed_reference"] = {"pose": read(art.pose.raw_pose).tolist(),
                                           "qpos": expected["qpos"].tolist(), "qvel": expected["qvel"].tolist(),
                                           "robot_qpos": expected["robot"].tolist(),
                                           "table_gap_m": expected["table_gap"]}
        for ordinal, (label, category, request) in enumerate(samples):
            index = ordinal % env_count
            layout = {str(i): (request if i == index else nominal) for i in range(env_count)}
            options = {"position_layout": layout}
            row = {"task": task, "id": label, "kind": category, "seed": seed, "env_idx": index,
                   "make_kwargs": make_kwargs, "reset_options": options, "request": request}
            rows.append(row)
            if category == "expected_rejection":
                before = [snap(base, art, i) for i in range(env_count)]
                try:
                    env.reset(seed=seed, options=options)
                except ValueError as error:
                    row["rejection"] = str(error)
                row["initialization_passed"] = ("rejection" in row and
                    before == [snap(base, art, i) for i in range(env_count)])
            else:
                _, info = env.reset(seed=seed, options=options)
                row.update(measure(env, kind, art, index, expected, request, geometry[index], info))
                row["initialization_passed"] = all(row["checks"].values())
                row["ik"] = solve_ik(base, kind, index, row["controls"])
                row["ik_passed"] = all(value["passed"] for value in row["ik"].values())
                if label == "N" or label.startswith("C"):
                    table, _, colliders = geometry[index]
                    row["support"] = table_probe(env, art, index, colliders, table)
                    row["support_passed"] = row["support"]["passed"]
            print(task, label, row["initialization_passed"], row.get("ik_passed"),
                  row.get("support_passed"), flush=True)
        eligible = [row for row in rows if row["id"].startswith("C") and row["initialization_passed"]]
        if eligible and not args.skip_attempts:
            difficult = max(eligible, key=lambda row: max(max(ik["errors_m"]) for ik in row["ik"].values()))
            for row in [rows[0], difficult]:
                _, info = env.reset(seed=row["seed"], options=row["reset_options"])
                row["short_attempt"] = short_attempt(env, art, kind, row["env_idx"],
                                                     row["controls"], row["ik"], info)
                row["short_attempt_passed"] = row["short_attempt"]["passed"]
        if gpu:
            report["local_reset"] = []
            for selected in (0, 1):
                other = 1 - selected
                counter = {"OpenLaptop": "hold_counter", "TypeKeys": "sequence_index",
                           "ClickMouse": "press_success_counter"}[kind]
                env.reset(seed=seed, options={"position_layout": {str(i): nominal for i in range(env_count)}})
                getattr(base, counter)[other] = 1
                before = snap(base, art, other)
                sample_id, _, request = next(sample for sample in samples
                                             if sample[0] == ("C---" if selected == 0 else "C+++"))
                options = {"env_idx": [selected], "position_layout": {str(selected): request}}
                env.reset(options=options)
                after = snap(base, art, other)
                readback = read(art.pose.raw_pose[selected])
                changes = [name for name in before if before[name] != after[name]]
                reference_yaw = {"OpenLaptop": 0., "TypeKeys": KEYBOARD_MODELS[MODELS["TypeKeys"]]["yaw_offset"],
                                 "ClickMouse": MOUSE_MODEL["yaw_offset"]}[kind]
                desired_yaw = math.radians(request[f"{base._position_device_name}_yaw_offset_deg"]) + reference_yaw
                error_rad = (orient(readback).inv() * Rotation.from_rotvec([0, 0, desired_yaw])).magnitude()
                ok = (np.max(np.abs(readback[:2] - request[f"{base._position_device_name}_xy_m"])) < TOLERANCE_M
                      and error_rad < 2e-6)
                row = {"kind": "indexed_isolation", "task": task, "id": f"ISO{selected}-{sample_id}",
                       "env_idx": selected, "seed": seed, "make_kwargs": make_kwargs,
                       "reset_options": options, "request": request, "pose": readback.tolist(),
                       "selected_yaw_error_rad": float(error_rad),
                       "isolation_passed": bool(ok and not changes)}
                rows.append(row)
                report["local_reset"].append({**row, "unselected_env_idx": other, "state_changes": changes,
                                             "stage_fixture": {counter: 1}, "before": before, "after": after})
        report["assets_unchanged"] = assets.asset_hashes() == cache_before
        if collision_identity is not None:
            report["mouse_collision_unchanged"] = assets.mouse_collision_identity() == collision_identity
        report["status"] = "passed" if (
            all(row.get("initialization_passed", True) and row.get("support_passed", True)
                and row.get("isolation_passed", True) for row in rows)
            and report["assets_unchanged"] and report.get("mouse_collision_unchanged", True)
        ) else "failed"
    finally:
        env.close()
        write_json(args.output / "results.json", report)
        write_points(args.output / "POINTS.csv", rows)
    return report["status"] != "passed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=tuple(SEEDS), required=True)
    parser.add_argument("--backend", choices=("physx_cpu", "physx_cuda"), default="physx_cpu")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--physx-gpu-dir", type=Path)
    parser.add_argument("--skip-attempts", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.backend == "physx_cuda" and os.name == "nt" and not sapien.physx.is_gpu_enabled():
        if args.physx_gpu_dir is None:
            parser.error("Windows CUDA requires the verified private SDK launcher")
        sapien.physx._enable_gpu()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
