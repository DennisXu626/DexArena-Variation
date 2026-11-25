"""Exercise the actual Nut & Bolt workspace reset path on CPU or two CUDA environments."""

import argparse
import csv
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import time

import gymnasium as gym
import numpy as np
import sapien

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(HERE), str(HERE.parent)]
from check_nut_bolt_positions import (
    GPU_MEMORY,
    TASKS,
    check_long,
    geometry,
    readback,
    setup_motion,
    short_attempt,
    solve_arm,
    state,
    support_probe,
    value,
)
from routes import route
from tasks.nut_bolt.position_layout import (
    BOLT_SPAWN_RADIUS_M,
    UPRIGHT_BOLT_RADIUS_M,
    TABLE_NUT_HALF_RANGE_M,
)
from tasks.nut_bolt.workspace import NutWorkspace, _catalog

MODEL = json.loads((ROOT / "docs/variation/evidence/nut_bolt_workspace/model.json").read_text())


def source():
    paths = [
        *(HERE / name for name in ("capture.py", "check.py", "routes.py", "screen.py")),
        *sorted((ROOT / "tasks/nut_bolt").glob("*.py")),
        ROOT / "tasks/nut_bolt/workspace_cells.json",
        HERE.parent / "check_nut_bolt_positions.py",
        HERE.parent / "check_cabinet_positions.py",
        ROOT / "docs/variation/evidence/nut_bolt_workspace/model.json",
    ]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def isolated_state(e, i):
    rng = [r[i].get_state() for r in (e._batched_main_rng, e._batched_episode_rng)]
    ws = e._nut_workspace
    return (
        state(e, i),
        hashlib.sha256(pickle.dumps(rng)).hexdigest(),
        json.dumps([ws.seeds[i], ws.counts[i], ws.records[i]], sort_keys=True),
        value(e.agent.robot.qpos[i]).tobytes(),
        value(e.agent.robot.qvel[i]).tobytes(),
        value(e.agent.robot.drive_targets[i]).tobytes(),
    )


def get_route(e, t, i, row, read):
    table = _catalog()["tasks"][t]
    g = MODEL[t].copy()
    chain = setup_motion(e, i)
    g["chain"] = [a.tolist() for a in chain]
    if t == "PickBolt":
        yaw = row["bolt_spawn_yaw_deg"]
        pos = read["bolt_pose"][:2]
    else:
        yaw = row.get("threaded_nut_relative_yaw_deg", 0)
        pos = read["bolt_pose"][:2]
        if t == "SeatNut":
            pos = [*pos, *np.subtract(read["target_pose"][:2], pos)]
    mm = np.array(pos) * 1000
    cells = table["cells"].get(str(int(yaw)), [])
    side = next(
        (
            c[-1]
            for c in cells
            if np.all(np.asarray(c[:-1]) - 2e-5 <= mm)
            and np.all(mm <= np.array(c[:-1]) + table["cell_size_mm"] + 2e-5)
        ),
        90,
    )
    angle = np.deg2rad(side + (yaw if t == "TurnNut" else 0))
    goals, _, _ = route(t, mm, yaw, angle, g)
    prev = chain[2]
    qs, errors = [], []
    for target in goals[:3]:
        prev, error = solve_arm(chain, target, prev)
        qs.append(prev.tolist())
        errors.append(error)
    return dict(
        stages=["pregrasp", "opposed approach", "15 degree turn" if t == "TurnNut" else "lift"],
        arm_qpos=qs,
        fingertip_max_errors_m=errors,
        route_deg=side,
    )


def legacy_draw(e, t, rng):
    def disc(c, r):
        a = rng.uniform(-np.pi, np.pi)
        return (np.array(c) + r * np.sqrt(rng.random()) * np.array([np.cos(a), np.sin(a)])).tolist()

    if t == "PickBolt":
        return {
            "bolt_spawn_xy_m": disc(e.bolt_spawn_xy, BOLT_SPAWN_RADIUS_M),
            "bolt_spawn_yaw_deg": int(rng.choice([-90, 0, 90])),
        }
    row = {"upright_bolt_xy_m": disc(e.bolt_place_center_xy, UPRIGHT_BOLT_RADIUS_M)}
    if t == "TurnNut":
        row["threaded_nut_relative_yaw_deg"] = int(rng.choice([-20, 0, 20]))
    else:
        row["table_nut_xy_m"] = (e.nut_spawn_xy + rng.uniform(-1, 1, 2) * TABLE_NUT_HALF_RANGE_M).tolist()
    return row


def actual(e, t, i):
    bolt = value(e.bolt.pose.p[i])[:2]
    if t == "SeatNut":
        return [*bolt, *value(e.nut.pose.p[i])[:2]]
    return list(bolt)


def pure(t):
    ws = NutWorkspace(t, 2)
    rng1 = np.random.default_rng(963)
    rng2 = np.random.default_rng(963)
    freq = {}
    for _ in range(8192):
        row = ws.sample(rng1)
        assert row == ws.sample(rng2) and ws.resolve(row) == row
        yaw = row.get("bolt_spawn_yaw_deg", row.get("threaded_nut_relative_yaw_deg", 0))
        freq[yaw] = freq.get(yaw, 0) + 1
    assert set(freq) == set(ws.cells)
    return freq


def options_for(ws):
    for name in ("near", "far"):
        yield name, name
    for yaw, cells in ws.cells.items():
        for axis in range(len(ws.size)):
            low = cells[np.argmin(cells[:, axis])].astype(float) + ws.size / 2
            high = cells[np.argmax(cells[:, axis])].astype(float) + ws.size / 2
            low[axis] -= ws.size[axis] / 2
            high[axis] += ws.size[axis] / 2
            yield f"yaw{yaw}-axis{axis}-min", ws.row(yaw, low)
            yield f"yaw{yaw}-axis{axis}-max", ws.row(yaw, high)
        yield f"yaw{yaw}-corner", ws.row(yaw, cells[0])
        yield f"yaw{yaw}-inner", ws.row(yaw, cells[-1] + ws.size * 0.73)


def check(task, args, output):
    n = 2 if args.sim_backend == "physx_cuda" else 1
    build = dict(
        num_envs=n,
        sim_backend=args.sim_backend,
        obs_mode="state",
        render_mode=None,
        control_mode="pd_joint_pos",
        reconfiguration_freq=0,
        enhanced_determinism=True,
    )
    if n == 2:
        build["sim_config"] = {"gpu_memory_config": GPU_MEMORY}
    task_id = f"NutBolt{task}-Sharpa-v1"
    baseline = gym.make(task_id, **build)
    native = []
    try:
        for seed in range(880, 892):
            start = time.perf_counter()
            baseline.reset(seed=seed)
            native.append(
                {
                    "seed": seed,
                    "xy": actual(baseline.unwrapped, task, 0),
                    "q": value(baseline.unwrapped.agent.robot.qpos[0]).tolist(),
                    "ms": 1000 * (time.perf_counter() - start),
                }
            )
        nominal = {str(i): {} for i in range(n)}
        baseline.reset(seed=925, options={"position_layout": nominal})
        baseline_digest = [state(baseline.unwrapped, i) for i in range(n)]
    finally:
        baseline.close()
    build["position_workspace"] = True
    env = gym.make(task_id, **build)
    try:
        e = env.unwrapped
        ws = e._nut_workspace
        geom = geometry(e)
        rows = []
        invalid = []
        comparison = []
        env.reset(seed=925, options={"position_layout": nominal})
        assert baseline_digest == [state(e, i) for i in range(n)]
        for base in native:
            seed = base["seed"]
            entries = legacy_draw(e, task, np.random.default_rng(seed))
            measure = {}
            for label, options in (
                ("old", {"position_layout": {str(i): entries for i in range(n)}}),
                ("workspace", {}),
            ):
                start = time.perf_counter()
                env.reset(seed=seed, options=options)
                elapsed = (time.perf_counter() - start) * 1000
                assert base["q"] == value(e.agent.robot.qpos[0]).tolist()
                measure[label] = {"xy": actual(e, task, 0), "ms": elapsed}
            comparison.append(dict(seed=seed, native={"xy": base["xy"], "ms": base["ms"]}, **measure))
        env.reset(seed=773)
        first = list(ws.records)
        env.reset()
        second = list(ws.records)
        env.reset(seed=773)
        assert ws.records == first
        env.reset(options={"workspace_placement": {str(i): "near" for i in range(n)}})
        env.reset()
        assert ws.records == second
        # Preserve a before/after simulation state roundtrip and layout stream.
        snapshot = e.get_state_dict()
        counts = ws.counts.copy()
        prior = [actual(e, task, i) for i in range(n)]
        env.reset(options={"reset_to_env_states": {"env_states": snapshot}})
        assert ws.counts == counts
        assert np.allclose(prior, [actual(e, task, i) for i in range(n)], atol=1e-6, rtol=0)
        options = [("nominal", None), *options_for(ws), ("random", None), ("random-reverse", None)]
        for j, (label, request) in enumerate(options):
            i = j % n
            seed = 930 + j
            env.reset(seed=seed)
            before = isolated_state(e, 1 - i) if n == 2 else None
            opts = {"env_idx": [i]}
            if label == "nominal":
                opts["position_layout"] = {str(i): {}}
            elif request is not None:
                opts["workspace_placement"] = {str(i): request}
            env.reset(options=opts)
            if n == 2:
                assert isolated_state(e, 1 - i) == before, (task, label, i)
            if label == "nominal":
                requested = (
                    {"bolt_spawn_xy_m": e.bolt_spawn_xy, "bolt_spawn_yaw_deg": 0}
                    if task == "PickBolt"
                    else (
                        {"upright_bolt_xy_m": e.bolt_place_center_xy, "table_nut_xy_m": e.nut_spawn_xy}
                        if task == "SeatNut"
                        else {
                            "upright_bolt_xy_m": e.bolt_place_center_xy,
                            "threaded_nut_relative_yaw_deg": 0,
                        }
                    )
                )
            else:
                requested = ws.records[i]["layout"]
            rb = readback(e, task, requested, i, geom)
            support = None
            action = None
            ik = None
            if label in ("near", "far", "nominal") or "corner" in label:
                support = support_probe(env, e, task, i, rb["target_pose"], geom)
                assert support["passed"], (task, label, support)
            if label in ("nominal", "far", "near"):
                env.reset(seed=seed)
                env.reset(options=opts)
                ik = get_route(e, task, i, requested, rb)
                action = short_attempt(env, e, task, i, ik)
                action["native_success_final"] = bool(e.evaluate()["success"][i])
            rows.append(
                dict(
                    id=label,
                    env_idx=i,
                    seed=seed,
                    options=opts,
                    request=requested,
                    bolt_pose=rb["bolt_pose"],
                    target_pose=rb["target_pose"],
                    stage=rb["task_phase"],
                    table_margin_m=rb["target_table_edge_clearance_m"],
                    support=support,
                    ik=ik,
                    action=action,
                    unselected_verified=n == 2,
                )
            )
        yaw = next(iter(ws.cells))
        lower = ws.cells[yaw][np.argmin(ws.cells[yaw][:, 0])].astype(float) + ws.size / 2
        lower[0] -= ws.size[0] / 2 + 0.01
        wrong = ws.row(yaw, lower)
        bad = [
            {"workspace_placement": {str(i): "near" if i == 0 and n > 1 else wrong for i in range(n)}},
            {"workspace_placement": {str(i): "far" for i in range(n)}, "position_layout": nominal},
            {"workspace_placement": {}},
            {"workspace_placement": {str(i): "near" for i in range(n)}, "reset_to_env_states": {}},
            {"workspace_placement": {str(i): {"extra": 0} for i in range(n)}},
        ]
        if n == 2:
            bad.extend([{"env_idx": [1, 0]}, {"env_idx": [1, 1]}])
        for opts in bad:
            before = [isolated_state(e, i) for i in range(n)]
            try:
                env.reset(options=opts)
            except ValueError as exc:
                assert before == [isolated_state(e, i) for i in range(n)]
                invalid.append({"options": opts, "error": str(exc)})
            else:
                raise AssertionError(opts)
        result = dict(
            task=task_id,
            build=build,
            rows=rows,
            invalid=invalid,
            comparison=comparison,
            native_legacy_exact=True,
            random_replay=True,
            fixed_preserves_stream=True,
            snapshot=True,
            offline_sampling_counts=pure(task),
        )
        (output / f"{task}.json").write_text(
            json.dumps(result, default=lambda x: x.item(), separators=(",", ":")) + "\n"
        )
        with (output / f"{task}.csv").open("w", newline="", encoding="utf-8") as stream:
            w = csv.writer(stream)
            w.writerow(
                [
                    "id",
                    "task",
                    "seed",
                    "env_idx",
                    "make",
                    "reset",
                    "layout",
                    "actual_object_pose",
                    "stage",
                    "table_margin_m",
                    "support",
                    "max_ik_error_m",
                    "short_action",
                    "native_success_final",
                    "isolation",
                ]
            )
            for r in rows:
                w.writerow(
                    [
                        r["id"],
                        task_id,
                        r["seed"],
                        r["env_idx"],
                        json.dumps(build),
                        json.dumps(r["options"]),
                        json.dumps(r["request"]),
                        json.dumps(r["target_pose"]),
                        r["stage"],
                        r["table_margin_m"],
                        (r["support"] or {}).get("passed"),
                        max((r["ik"] or {}).get("fingertip_max_errors_m", [0])) if r["ik"] else "",
                        (r["action"] or {}).get("passed"),
                        (r["action"] or {}).get("native_success_final"),
                        r["unselected_verified"],
                    ]
                )
        print(task, len(rows), "legal", len(invalid), "atomic errors", flush=True)
    finally:
        env.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sim-backend", choices=("physx_cpu", "physx_cuda"), required=True)
    ap.add_argument("--task", choices=TASKS)
    ap.add_argument("--physx-gpu-dir", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.sim_backend == "physx_cuda":
        if os.name == "nt" and not sapien.physx.is_gpu_enabled():
            if args.physx_gpu_dir is None:
                raise RuntimeError("use the native-lock SDK launcher")
            sapien.physx._enable_gpu()
        assert sapien.physx.indexed_gpu_apply_patch_version() == 1
        assert sapien.physx.native_gpu_lock_sync_patch_version() == 1
    manifest = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip(),
        "backend": args.sim_backend,
        "source_sha256": source(),
        "sapien": sapien.__version__,
        "mani_skill": version("mani-skill"),
    }
    for t in [args.task] if args.task else TASKS:
        check(t, args, args.output)
    if args.sim_backend == "physx_cpu" and not args.task:
        manifest["native_long"] = check_long()
    assert manifest["source_sha256"] == source()
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
