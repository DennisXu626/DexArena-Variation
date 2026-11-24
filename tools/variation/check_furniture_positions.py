"""Read back Furniture position requests, exercise support and estimate fingertip reach."""

import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import time

import gymnasium as gym
import numpy as np
import sapien
from scipy.spatial.transform import Rotation
import torch

from tasks.furniture_assembly.furniture_assembly_fasten_screw import WING_HALF, WING_SCREW_STEM_HEIGHT
from tasks.furniture_assembly.furniture_assembly_insert_rail import (
    RAIL_HALF, RAIL_REST_Z, RAIL_SCREW_LOCAL_POSITIONS, RAIL_SEATED_X_LOCAL,
    RAIL_SEATED_Z_LOCAL, SCREW_HEAD_HALF_H,
)
from tasks.furniture_assembly.furniture_assembly_lay_flat_panel import (
    GROOVE_HALF_W, PANEL_HALF, PANEL_IN_SLOT_Z, PLACE_CENTER, RACK_SLOT_FLOOR_Z, RACK_SLOT_HALF_W,
)
from tasks.furniture_assembly.position_layout import YAW_DEGREES
from tools.variation.check_cabinet_positions import env_digest, setup_motion, solve_arm, value
from tools.variation.furniture_position_samples import CENTERS, TASK_ROLES, cases, extent_clearance


IK_LIMIT_M = .015
RELEASE_STEPS = 8
POSE_TOLERANCE = 2e-5
ROT_TOLERANCE_DEG = .01
ATTEMPT_STEPS = (20, 26, 22)
HARD_POINT = {"LayFlatPanel": "C-far", "InsertRail": "C-far", "FastenScrew": "C-far"}


def pose(actor, i):
    return value(actor.pose.raw_pose[i]).astype(float)


def rotation(p):
    return Rotation.from_quat(p[[4, 5, 6, 3]])


def table_geometry(e):
    table = e.table_scene.table
    tab = pose(table, 0)
    shape, = table._bodies[0].collision_shapes
    center = tab[:3] + rotation(tab).apply(shape.local_pose.p)
    orient = rotation(tab) * Rotation.from_quat(shape.local_pose.q[[1, 2, 3, 0]])
    half = np.abs(orient.as_matrix()) @ shape.half_size
    return center[:2], half[:2], float(center[2] + half[2])


def check_pose(actual, xyz, expected_rot):
    return bool(np.max(np.abs(actual[:3] - xyz)) <= POSE_TOLERANCE
                and (rotation(actual).inv() * expected_rot).magnitude() <= np.deg2rad(ROT_TOLERANCE_DEG))


def measure(e, kind, i, request, table):
    names = list(TASK_ROLES[kind])
    names.extend({"LayFlatPanel": ["panel"], "InsertRail": ["rail_body", "screw_head"],
                  "FastenScrew": ["rail", "rail_body", "screw_head"]}[kind])
    actual = {name: pose(getattr(e, name), i) for name in names}
    checks = {}
    angles = {}
    for role in TASK_ROLES[kind]:
        xyz = [*request.get(f"{role}_xy_m", CENTERS[role]),
               {"rack": 0., "panel": PANEL_HALF[2], "rail": RAIL_REST_Z}[role]]
        requested_yaw = request.get(f"{role}_yaw_deg", 0.)
        checks[f"{role}_request"] = check_pose(actual[role], xyz, Rotation.from_euler("z", requested_yaw, degrees=True))
    for role in ("panel", "rack", "rail"):
        if role in actual:
            x_axis = rotation(actual[role]).as_matrix()[:, 0]
            angles[role] = float(np.rad2deg(np.arctan2(x_axis[1], x_axis[0])))
    clearance = extent_clearance(kind, {role: [*actual[role][:2], yaw] for role, yaw in angles.items()}, table)
    checks["clearance"] = all(margin > 0 for margin in clearance.values())
    if kind == "LayFlatPanel":
        panel, rack = actual["panel"], actual["rack"]
        upright = rotation(rack) * Rotation.from_euler("x", 90., degrees=True)
        checks["panel_in_slot"] = check_pose(panel, [*rack[:2], PANEL_IN_SLOT_Z], upright)
        clearance["slot_floor_start_gap_m"] = float(panel[2] - PANEL_HALF[1] - RACK_SLOT_FLOOR_Z)
        clearance["slot_wall_half_play_m"] = RACK_SLOT_HALF_W - PANEL_HALF[2]
        initial_flags = (e.grasp_achieved[i], e.extract_achieved[i], e.settle_counter[i])
        place = value(e.place_center[i])
    else:
        panel, rail, screw = actual["panel"], actual["rail"], actual["screw_head"]
        checks["rail_body_attached"] = check_pose(actual["rail_body"], rail[:3], rotation(rail))
        screw_local = np.asarray(RAIL_SCREW_LOCAL_POSITIONS[0]).copy()
        if kind == "InsertRail":
            # The slotted head origin lies one half-height above the web.
            screw_local[2] += SCREW_HEAD_HALF_H
            initial_flags = (e.grasp_achieved[i], e.lift_achieved[i], e.align_achieved[i], e.settle_counter[i])
        else:
            rail_xyz = panel[:3] + rotation(panel).apply([RAIL_SEATED_X_LOCAL, 0., RAIL_SEATED_Z_LOCAL])
            checks["seated_rail_follows_panel"] = check_pose(rail, rail_xyz, rotation(panel))
            clearance["seated_rail_half_play_m"] = GROOVE_HALF_W - RAIL_HALF[1]
            initial_flags = (e.touched_once[i], e.rotation_progress[i], e.success_counter[i])
        screw_xyz = rail[:3] + rotation(rail).apply(screw_local)
        checks["screw_follows_rail"] = check_pose(screw, screw_xyz, rotation(rail))
        checks["zero_screw_angle"] = abs(float(e.rail.get_qpos()[i, 0])) <= POSE_TOLERANCE
        place = pose(e.place_marker, i)[:3]
    checks["task_bookkeeping_zero"] = not any(bool(flag) for flag in initial_flags)
    checks["native_place_center"] = bool(np.allclose(place, [*PLACE_CENTER, 0.], atol=POSE_TOLERANCE))
    measured = {k: p.tolist() for k, p in actual.items()}
    return dict(checks=checks, measured_poses=measured, measured_yaw_deg=angles, clearances_m=clearance)


def hold_action(e, env):
    controller = e.agent.controller
    action = e.agent.robot.qpos.new_zeros((e.num_envs, env.action_space.shape[-1]))
    for part, (lo, hi) in controller.action_mapping.items():
        action[:, lo:hi] = e.agent.robot.qpos[:, controller.controllers[part].active_joint_indices]
    return action


def release_probe(env, e, kind, i):
    if kind == "FastenScrew":
        return {"method": "native kinematic panel and fixed rail root; support and relative pose checked at reset"}
    body, support = ((e.panel, e.rack) if kind == "LayFlatPanel" else (e.rail_body, e.table_scene.table))
    first = pose(body, i)
    force_peak = 0.
    action = hold_action(e, env)
    for _ in range(RELEASE_STEPS):
        env.step(action)
        force_peak = max(force_peak, float(e.scene.get_pairwise_contact_forces(body, support)[i].norm()))
    final = pose(body, i)
    delta = float(np.linalg.norm(first[:3] - final[:3]))
    rotation_change = float(np.rad2deg((rotation(first).inv() * rotation(final)).magnitude()))
    return dict(steps=RELEASE_STEPS, displacement_m=delta, angle_change_deg=rotation_change,
                peak_support_N=force_peak, final_pose=final.tolist(),
                passed=bool(force_peak > .001 and delta <= .008 and rotation_change <= 5.))


def reach(e, kind, i):
    chain = setup_motion(e, i)
    tips = chain[-1]
    # As in the Cabinet probe, hold the current thumb–index span during the arm solve.
    # Check paired fingertip targets around the active surface, with no collision solver.
    if kind == "LayFlatPanel":
        axis = rotation(pose(e.rack, i)).apply([0., 1., 0.])
        center = value(e.grasp_position[i]).copy()
        targets = [center + [0, 0, .07], center, center + [0, 0, .08]]
    elif kind == "InsertRail":
        axis = rotation(pose(e.rail, i)).apply([0., 1., 0.])
        center = value(e.rail_grasp_position[i]).copy() + [0, 0, .008]
        targets = [center + [0, 0, .055], center, center + [0, 0, .05]]
    else:
        axis = rotation(pose(e.screw_head, i)).apply([1., 0., 0.])
        center = pose(e.screw_head, i)[:3] + [0, 0, WING_SCREW_STEM_HEIGHT + WING_HALF[2]]
        targets = [center + [0, 0, .055], center, center]
    span = float(np.linalg.norm(tips[1] - tips[0]))
    if np.dot(tips[1] - tips[0], axis) < 0.:
        axis = -axis
    best = None
    for incline in (0., 30., -30.):
        tilt = np.deg2rad(incline)
        aligned = np.cos(tilt) * axis + np.sin(tilt) * np.array([0., 0., 1.])
        arm_angles, errors, target_pairs = [], [], []
        q = chain[2]
        for stage, target in enumerate(targets):
            approach_axis = aligned
            if kind == "FastenScrew" and stage == 2:
                approach_axis = Rotation.from_euler("z", -15., degrees=True).apply(aligned)
            pairs = target + span / 2. * np.outer([-1., 1.], approach_axis)
            q, error = solve_arm(chain, pairs, q)
            arm_angles.append(q.tolist())
            errors.append(error)
            target_pairs.append(pairs.tolist())
        if best is None or max(errors) < max(best["tip_errors_m"]):
            best = dict(tip_errors_m=errors, targets_xyz_m=target_pairs, ik_pass=max(errors) <= IK_LIMIT_M,
                        arm_targets_rad=arm_angles, native_fingertip_span_m=span, pair_incline_deg=incline)
    if kind == "InsertRail":
        mouth = value(e.groove_landmarks[i, 0]).copy()
        x_axis = rotation(pose(e.panel, i)).apply([1., 0., 0.])
        entry = mouth - .06 * x_axis + [0, 0, .045]
        pinch_axis = rotation(pose(e.panel, i)).apply([0., 1., 0.])
        if np.dot(tips[1] - tips[0], pinch_axis) < 0.:
            pinch_axis = -pinch_axis
        mouths = entry + span / 2. * np.outer([-1., 1.], pinch_axis)
        _, error = solve_arm(chain, mouths, np.asarray(best["arm_targets_rad"][-1]))
        best["groove_approach_error_m"] = error
        best["groove_approach_xyz_m"] = mouths.tolist()
        best["ik_pass"] = best["ik_pass"] and error <= IK_LIMIT_M
    return best


def short_attempt(env, e, kind, i, ik):
    action = hold_action(e, env)
    controller = e.agent.controller
    arm_lo, arm_hi = controller.action_mapping["arm"]
    hand_lo, hand_hi = controller.action_mapping["hand"]
    home_hand = action[i, hand_lo:hand_hi].clone()
    close_hand = home_hand.clone()
    hand_limits = e.agent.robot.get_qlimits()[i, controller.controllers["hand"].active_joint_indices]
    for j, name in enumerate(e.agent.hand_joint_names):
        if name.endswith(("PIP", "DIP", "_IP", "MCP_FE")):
            close_hand[j] = torch.clamp(home_hand[j] + .45, *hand_limits[j])
    actor = {"LayFlatPanel": e.panel,
             "InsertRail": getattr(e, "rail_body", None),
             "FastenScrew": getattr(e, "screw_head", None)}[kind]
    first_z = float(actor.pose.p[i, 2])
    contact_peak, max_lift, max_angle = 0., 0., 0.
    native_grasp, native_extract = False, False
    trace = []
    for stage, (target_q, steps) in enumerate(zip(ik["arm_targets_rad"], ATTEMPT_STEPS)):
        start_q = action[i, arm_lo:arm_hi].clone()
        end_q = start_q.new_tensor(target_q)
        for step in range(steps):
            factor = min((step + 1) / (steps - 8), 1.)
            action[i, arm_lo:arm_hi] = torch.lerp(start_q, end_q, factor)
            if stage == 1:
                action[i, hand_lo:hand_hi] = torch.lerp(home_hand, close_hand, factor)
            _, _, _, _, info = env.step(action)
            contact = max(float(e.scene.get_pairwise_contact_forces(actor, e.agent.robot.links_map[name])[i].norm())
                          for name in e.agent.grip_link_names)
            contact_peak = max(contact_peak, contact)
            max_lift = max(max_lift, float(actor.pose.p[i, 2]) - first_z)
            if kind == "FastenScrew":
                max_angle = max(max_angle, float(e.rail.get_qpos()[i, 0]))
            else:
                native_grasp |= bool(info["grasp_achieved"][i])
                if kind == "LayFlatPanel":
                    native_extract |= bool(info["extract_achieved"][i])
            if step == steps - 1:
                trace.append(dict(stage=stage, last_contact_N=contact, pose=pose(actor, i).tolist()))
    passed = {"LayFlatPanel": native_grasp and native_extract,
              "InsertRail": native_grasp and max_lift >= .025,
              "FastenScrew": contact_peak > .6 and max_angle >= np.deg2rad(3.)}[kind]
    return dict(steps=sum(ATTEMPT_STEPS), peak_contact_N=contact_peak, lift_m=max_lift,
                turn_rad=max_angle, native_grasp_seen=native_grasp, native_extract_seen=native_extract,
                passed=bool(passed), phases=trace)


def state(e):
    return {**e.get_state_dict(), "elapsed_steps": e._elapsed_steps}


def robot_pose(e, i):
    return (pose(e.agent.robot, i), value(e.agent.robot.qpos[i]).copy(), value(e.agent.robot.qvel[i]).copy())


def source_identity():
    repo = Path(__file__).resolve().parents[2]
    git = lambda *args: subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
    sources = sorted((repo / "tasks/furniture_assembly").glob("*.py"))
    sources += [Path(__file__), Path(__file__).with_name("furniture_position_samples.py"),
                Path(__file__).with_name("check_cabinet_positions.py")]
    return dict(commit=git("rev-parse", "HEAD"),
                input_sha256={p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})


def run(out, backend, num_envs, tasks_to_run, skip_attempt):
    out.mkdir(parents=True, exist_ok=False)
    make = dict(num_envs=num_envs, sim_backend=backend, obs_mode="state", render_mode=None,
                control_mode="pd_joint_pos", reconfiguration_freq=0)
    result = dict(status="running", source=source_identity(), backend=backend, python=platform.python_version(),
                  sapien=sapien.__version__, torch=torch.__version__, platform=platform.platform(),
                  cuda_gpu=torch.cuda.get_device_name() if backend == "physx_cuda" else None,
                  indexed_gpu_apply=getattr(sapien.physx, "indexed_gpu_apply_patch_version", lambda: None)(),
                  ik_limit_m=IK_LIMIT_M, tasks={})
    json_path = out / "results.json"

    def flush():
        json_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    t0 = time.monotonic()
    all_rows = []
    for kind in tasks_to_run:
        task_id = f"FurnitureAssembly{kind}-Sharpa-v1"
        group = result["tasks"][kind] = dict(task_id=task_id, make=make, points=[])
        flush()
        with gym.make(task_id, **make) as env:
            e = env.unwrapped
            env.reset(seed=7)
            group["native_seed_7_poses"] = {n: value(getattr(e, n).pose.raw_pose).tolist()
                                             for n in ("rack", "panel", "rail") if hasattr(e, n)}
            table = table_geometry(e)
            group["table_collision"] = dict(center_xy_m=table[0].tolist(), half_xy_m=table[1].tolist(), top_z_m=table[2])
            if num_envs == 2:
                role = TASK_ROLES[kind][0]
                positive_yaw = YAW_DEGREES[role][-1]
                requests = {"0": {}, "1": {f"{role}_yaw_deg": positive_yaw}}
                # Also verify distinct simultaneous requests and reset-index row routing.
                env.reset(seed=[41, 42], options={"env_idx": torch.tensor([1, 0], device=e.device),
                                                 "position_layout": requests})
                group["full_reordered_layout"] = [measure(e, kind, i, requests[str(i)], table)["checks"] for i in range(2)]
                assert all(all(row.values()) for row in group["full_reordered_layout"]), group["full_reordered_layout"]
            for n, (point, figure, request, reject) in enumerate(cases(kind)):
                i = n % num_envs
                seed = 701 + n
                opts = {"position_layout": {str(i): request}}
                if num_envs == 2:
                    opts["env_idx"] = torch.tensor([i], device=e.device)
                row = dict(task_id=task_id, point=point, figure=figure, seed=seed, env_idx=i,
                           make=make, request=request, reset_options={"env_idx": [i], "position_layout": {str(i): request}},
                           expectation="reject" if reject else "initialize")
                if num_envs == 1:
                    del row["reset_options"]["env_idx"]
                group["points"].append(row)
                all_rows.append(row)
                if point == "N":
                    native_opts = {"env_idx": opts["env_idx"]} if num_envs == 2 else None
                    env.reset(seed=seed, options=native_opts)
                    native_robot = robot_pose(e, i)
                targets = [j for j in range(num_envs) if reject or j != i]
                before = {j: env_digest(state(e), j) for j in targets}
                flush()
                try:
                    env.reset(seed=seed, options=opts)
                except ValueError as exc:
                    row.update(result="rejected" if reject else "unexpected_rejection", reason=str(exc),
                               unchanged={j: before[j] == env_digest(state(e), j) for j in targets})
                    flush()
                    continue
                row["unchanged"] = {j: before[j] == env_digest(state(e), j) for j in targets}
                if reject:
                    row["result"] = "unexpected_acceptance"
                    flush()
                    continue
                row.update(measure(e, kind, i, request, table))
                if point == "N":
                    row["checks"]["robot_same_as_native_seed"] = all(np.array_equal(a, b)
                        for a, b in zip(native_robot, robot_pose(e, i)))
                row["reach"] = reach(e, kind, i)
                row["release"] = release_probe(env, e, kind, i)
                passed = all(row["checks"].values()) and row["release"].get("passed", True)
                row["result"] = "pass" if passed else "initial_state_failure"
                if not skip_attempt and point in {"N", HARD_POINT[kind]}:
                    env.reset(seed=seed, options=opts)
                    row["short_attempt"] = short_attempt(env, e, kind, i, row["reach"])
                flush()
    results_ok = all(row["result"] in {"pass", "rejected"} and all(row["unchanged"].values()) for row in all_rows)
    result.update(status="passed" if results_ok else "failed", runtime_wall_seconds=time.monotonic() - t0)
    flush()
    fields = ("task_id", "point", "figure", "seed", "env_idx", "expectation", "make", "reset_options",
              "measured_poses", "measured_yaw_deg", "clearances_m", "checks", "unchanged", "release",
              "reach", "short_attempt", "result", "reason")
    with (out / "POINTS.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fields, lineterminator="\n")
        writer.writeheader()
        for row in all_rows:
            writer.writerow({key: json.dumps(row[key], separators=(",", ":")) if isinstance(row.get(key), dict)
                             else row.get(key, "") for key in fields})
    return results_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--physx-gpu-dir", type=Path, help="Accepted from the verified Windows SDK launcher")
    parser.add_argument("--backend", choices=("physx_cpu", "physx_cuda"), default="physx_cpu")
    parser.add_argument("--task", choices=tuple(TASK_ROLES), action="append")
    parser.add_argument("--skip-attempt", action="store_true")
    args = parser.parse_args()
    sys_ok = run(args.output, args.backend, 2 if args.backend == "physx_cuda" else 1,
                 args.task or TASK_ROLES, args.skip_attempt)
    raise SystemExit(0 if sys_ok else 1)
