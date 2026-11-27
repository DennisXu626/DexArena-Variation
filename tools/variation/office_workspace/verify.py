"""Exercise Office workspace layouts, predicted controls, support, actions and local reset."""

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2])]

from capture import capture
from build import OfficeScreen, zrot
from tools.variation import check_office_positions as checks
from tasks.office_desk.position_workspace import cell_at
import gymnasium as gym
import numpy as np
import sapien
import torch


def options_for(task, backend):
    kw = dict(
        num_envs=2 if backend == "physx_cuda" else 1,
        sim_backend=backend,
        obs_mode="state",
        reward_mode="sparse",
        control_mode="pd_joint_pos",
        reconfiguration_freq=0,
    )
    if kw["num_envs"] == 2:
        kw["sim_config"] = {
            "gpu_memory_config": {
                "max_rigid_contact_count": 2**17,
                "max_rigid_patch_count": 2**16,
                "found_lost_pairs_capacity": 2**20,
            }
        }
    if task == "TypeKeys":
        kw.update(model_id="13106", show_guidance_markers=True)
    return kw


def boundaries(table, device):
    for yaw in table["yaw_deg"]:
        cells = table["cells"][str(yaw)]
        for axis, side in ((0, -1), (0, 1), (1, -1), (1, 1)):

            def face(cell):
                return cell[axis] + (cell[2] if side == 1 else 0.0)

            cell = min(cells, key=lambda c: -side * face(c))
            xy = np.array(cell[:2]) + cell[2] / 2
            xy[axis] = face(cell)
            for displacement, name in ((0.0, "boundary"), (0.0002, "exterior")):
                point = xy.copy()
                point[axis] += side * displacement
                yield (
                    f"{yaw}_{axis}_{side}_{name}",
                    {f"{device}_xy_m": point.tolist(), f"{device}_yaw_offset_deg": yaw},
                    name == "exterior",
                )


def predict_controls(nominal, root, xy, yaw):
    turn = zrot(yaw)
    return {
        label: turn @ (np.array(point) - root) + np.r_[xy, root[2]] for label, point in nominal.items()
    }


def run(task, backend, out):
    checks.state.torch, checks.state.np = torch, np
    checks.assets.require_model_asset_root(task)
    kw = options_for(task, backend)
    task_id = f"OfficeDesk{task}-Sharpa-v1"
    seed = checks.SEEDS[task]
    n = kw["num_envs"]
    asset_hashes = checks.assets.asset_hashes()
    old_opt = {"position_layout": {str(i): {} for i in range(n)}}
    native = gym.make(task_id, **kw)
    try:
        native.reset(seed=seed)
        old = native.unwrapped
        robot_ref = checks.read(old.agent.robot.qpos)
        native_root = checks.read(getattr(old, old._position_device_name).pose.raw_pose)
        native.reset(seed=seed, options=old_opt)
        refart = getattr(old, old._position_device_name)
        old_pose = checks.read(refart.pose.raw_pose)
        controls = [checks.read_controls(old, task, i) for i in range(n)]
        nominal_joint = checks.read(refart.qpos)
        if n == 1:
            # The same seeds are reused in the comparison of all three distributions.
            baseline = []
            rng = np.random.default_rng(39043)
            device = old._position_device_name
            center = np.asarray(old._position_center)
            for j in range(24):
                for mode in ("native", "old_reference"):
                    pairseed = seed + j
                    opts = {}
                    if mode == "old_reference":
                        lo, hi = np.array(checks.XY_BOUNDS_M[device])
                        opts = {
                            "position_layout": {
                                "0": {
                                    f"{device}_xy_m": (center + rng.uniform(lo, hi)).tolist(),
                                    f"{device}_yaw_offset_deg": int(rng.choice(checks.YAW_OFFSETS_DEG)),
                                }
                            }
                        }
                    start = time.perf_counter()
                    native.reset(seed=pairseed, options=opts)
                    duration = time.perf_counter() - start
                    baseline.append(
                        dict(
                            mode=mode,
                            seed=pairseed,
                            root=checks.read(refart.pose.p[0]).tolist(),
                            targets=checks.read_controls(old, task, 0)["targets_xyz_m"],
                            reset_ms=duration * 1e3,
                        )
                    )
        else:
            baseline = []
    finally:
        native.close()
    kw["position_workspace"] = True
    env = gym.make(task_id, **kw)
    rows = []
    checks_done = []

    def require(condition, label):
        if not bool(condition):
            raise AssertionError(f"{task}/{backend}: {label}")
        checks_done.append(label)

    info_report = {
        "task": task_id,
        "make_kwargs": kw,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=checks.ROOT, text=True
        ).strip(),
        "versions": {
            "sapien": sapien.__version__,
            "torch": torch.__version__,
            "python": platform.python_version(),
            "mani_skill": checks.assets.metadata.version("mani-skill"),
        },
        "checks": checks_done,
        "points": rows,
        "distributions": baseline,
        "actions": [],
    }
    try:
        base = env.unwrapped
        api = base.position_workspace
        art = getattr(base, base._position_device_name)
        device = api.device
        geometry = checks.read_geometry(base, art, 0)
        info_report["assets"] = {
            k: v for k, v in asset_hashes.items() if k.startswith(checks.MODELS[task] + "/")
        }
        info_report["robot_assets"] = checks.assets.asset_closure(base)
        pathset = [
            *HERE.glob("*.py"),
            *list((checks.ROOT / "tasks/office_desk").glob("*.py")),
            checks.ROOT / "tasks/office_desk/workspace_maps" / (device + ".json"),
        ]
        info_report["inputs_sha256"] = {
            p.relative_to(checks.ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(pathset)
        }

        def opts(item):
            return {"workspace_placement": {str(i): item for i in range(n)}}

        def snap(i):
            return [checks.snap(base, art, i), api.counts[i], api.seeds[i], api.episodes[i]]

        def pose_rows():
            return checks.read(art.pose.raw_pose).tolist()

        env.reset(seed=seed, options=old_opt)
        require(np.allclose(checks.read(art.pose.raw_pose), old_pose, rtol=0, atol=2e-6), "old explicit")
        require(
            np.array_equal(robot_ref, checks.read(base.agent.robot.qpos)), "native robot initialization"
        )
        if n == 1:
            env.reset(seed=seed)
            p1 = pose_rows()
            env.reset()
            p2 = pose_rows()
            env.reset(seed=seed)
            require(p1 == pose_rows(), "seeded replay")
            env.reset(options=opts("far"))
            env.reset()
            require(p2 == pose_rows() and p1 != p2, "fixed requests do not consume layout draws")
        else:
            env.reset(seed=seed)
            replay = pose_rows()
            env.reset()
            next_poses = pose_rows()
            env.reset(seed=seed)
            require(replay == pose_rows(), "two-env seeded replay")
            env.reset()
            require(next_poses == pose_rows() and next_poses != replay, "two-env advancing replay")
        if n == 1:
            for j in range(24):
                start = time.perf_counter()
                env.reset(seed=seed + j)
                duration = time.perf_counter() - start
                point = checks.read_controls(base, task, 0)
                baseline.append(
                    dict(
                        mode="workspace",
                        seed=seed + j,
                        root=checks.read(art.pose.p[0]).tolist(),
                        targets=point["targets_xyz_m"],
                        reset_ms=duration * 1e3,
                    )
                )
        for ordinal, (label, req, reject) in enumerate(
            [(name, name, False) for name in api.table["presets"]] + list(boundaries(api.table, device))
        ):
            selected = ordinal % n
            options = opts(req)
            if reject and n == 2:
                options["workspace_placement"]["0"] = "reference"
            row = dict(id=label, seed=seed, env_idx=selected, reset_options=options)
            rows.append(row)
            if reject:
                before = [snap(i) for i in range(n)]
                try:
                    env.reset(seed=seed, options=options)
                except ValueError as exc:
                    row["rejection"] = str(exc)
                require("rejection" in row and before == [snap(i) for i in range(n)], label)
                continue
            xy, yaw = api.fixed(req)
            _, info = env.reset(seed=seed, options=options)
            measured = checks.read(art.pose.raw_pose[selected])
            ctrl = checks.read_controls(base, task, selected)
            pred = predict_controls(controls[selected]["targets_xyz_m"], old_pose[selected, :3], xy, yaw)
            errs = {
                k: float(np.linalg.norm(value - ctrl["targets_xyz_m"][k])) for k, value in pred.items()
            }
            quat_err = (
                checks.orient(measured).inv()
                * checks.Rotation.from_matrix(zrot(yaw))
                * checks.orient(old_pose[selected])
            ).magnitude()
            joint_ok = np.allclose(
                checks.read(art.qpos[selected]), nominal_joint[selected], atol=2e-6, rtol=0
            )
            support = checks.body_points(art, geometry[2], selected)
            points = np.concatenate(list(support.values()))
            table = geometry[0]
            gap = min(
                np.min(points[:, :2].min(0) - table[:, :2].min(0)),
                np.min(table[:, :2].max(0) - points[:, :2].max(0)),
            )
            row.update(
                pose=measured.tolist(),
                yaw_offset_deg=yaw,
                targets=ctrl["targets_xyz_m"],
                point_error_m=errs,
                footprint_margin_m=float(gap),
                root_yaw_error_rad=float(quat_err),
            )
            require(
                cell_at(api.table, xy, yaw) is not None
                and np.linalg.norm(measured[:2] - xy) < 2e-6
                and max(errs.values()) < 0.0001
                and quat_err < 1e-5
                and gap > 0
                and joint_ok
                and not bool(info["success"][selected]),
                label,
            )
            if task == "TypeKeys":
                require(ctrl["marker"]["error_m"] < 2e-6, label + " key marker")
            if label in api.table["presets"]:
                row["support"] = checks.table_probe(env, art, selected, geometry[2], table)
                require(row["support"]["passed"], label + " support")
        if n == 2:
            for i in range(2):
                env.reset(seed=seed, options=opts("reference"))
                other = 1 - i
                counter = {
                    "OpenLaptop": "hold_counter",
                    "TypeKeys": "sequence_index",
                    "ClickMouse": "press_success_counter",
                }[task]
                getattr(base, counter)[other] = 1
                if task == "TypeKeys":
                    base.sequence_completed[other, 0] = True
                    base._update_key_target_marker()
                    base.scene._gpu_apply_all()
                    base.scene._gpu_fetch_all()
                before = snap(other)
                for request in (
                    {"env_idx": [i], "workspace_placement": {str(i): "far"}},
                    {"env_idx": [i]},
                ):
                    env.reset(options=request)
                    rec = api.episodes[i]
                    measured = checks.read(art.pose.p[i, :2])
                    idle = snap(other)
                    confirmed = before == idle and np.linalg.norm(measured - rec["xy_m"]) < 2e-6
                    if task == "TypeKeys":
                        confirmed = (
                            confirmed and checks.read_controls(base, task, i)["marker"]["error_m"] < 2e-6
                        )
                    require(confirmed, f"env{i} isolated {rec['mode']}")
                    rows.append(
                        dict(
                            id=f"env{i}-{rec['mode']}",
                            seed=seed,
                            env_idx=i,
                            reset_options=request,
                            measured_xy=measured.tolist(),
                            passive_state_identical=before == idle,
                            episode=rec,
                        )
                    )
            ordered = {"env_idx": [1, 0], "workspace_placement": {"0": "near", "1": "far"}}
            env.reset(options=ordered)
            require(
                all(
                    np.linalg.norm(checks.read(art.pose.p[i, :2]) - api.fixed(name)[0]) < 2e-6
                    for i, name in enumerate(("near", "far"))
                ),
                "unordered selected IDs",
            )
        for case in ("reference", "far"):
            for route in ("front", "shell_side") if task == "ClickMouse" else ("front",):
                _, info = env.reset(seed=seed, options=opts(case))
                frame = capture(env, task, 0)
                model = OfficeScreen(frame)
                start_angle = frame["controls"].get("lid", {}).get("angles_deg", [0])[0]
                code, stage, err, clearance, jump, q = model.evaluate(
                    model.origin[:2], 0, route, start_angle, True
                )
                action = dict(
                    preset=case,
                    route=route,
                    seed=seed,
                    env_idx=0,
                    code=int(code),
                    waypoint=int(stage),
                    predicted_error_m=float(err),
                    clearance_m=float(clearance),
                    max_joint_jump_rad=float(jump),
                )
                if not code:
                    # Use every connected pose. Limit keyboard trial to the first press/release.
                    targets = q[: stage + 1]
                    if task == "TypeKeys":
                        first5, _ = model.lift_path(route, start_angle)
                        last = model.tip
                        count = 0
                        for point in first5[:5]:
                            count += max(1, int(np.ceil(np.linalg.norm(point - last) / 0.035)))
                            last = point
                        targets = targets[:count]
                    key = next(iter(frame["controls"]["targets_xyz_m"]))
                    probe = checks.short_attempt(
                        env, art, task, 0, frame["controls"], {key: {"joint_targets": targets}}, info
                    )
                    action["short_action"] = probe
                info_report["actions"].append(action)
        require(asset_hashes == checks.assets.asset_hashes(), "asset files preserved")
        info_report["status"] = "passed"
    finally:
        env.close()
        out.mkdir(parents=True, exist_ok=True)
        checks.write_json(out / "report.json", info_report)
        with (out / "POINTS.csv").open("w", encoding="utf-8", newline="") as stream:
            fields = sorted({k for row in rows for k in row})
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        k: (
                            json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                            if isinstance(v, (list, dict))
                            else v
                        )
                        for k, v in row.items()
                    }
                )
    print(task, backend, info_report["status"], len(rows), "points")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=tuple(checks.SEEDS), required=True)
    parser.add_argument("--backend", choices=("physx_cpu", "physx_cuda"), default="physx_cpu")
    parser.add_argument("--physx-gpu-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.backend == "physx_cuda" and os.name == "nt" and not sapien.physx.is_gpu_enabled():
        if args.physx_gpu_dir is None:
            parser.error("run via the verified private SDK launcher")
        sapien.physx._enable_gpu()
    run(args.task, args.backend, args.output)
