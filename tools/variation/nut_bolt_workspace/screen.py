"""Compile continuous Nut & Bolt placement cells from a measured Sharpa model.

Run capture.py in the simulator first. This offline compiler only needs NumPy,
SciPy and Numba. Metres/radians internally; the stored cell bounds use mm.
"""

import csv
from itertools import product
import json
from pathlib import Path

import numpy as np
from numba import njit
from routes import route

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "docs/variation/evidence/nut_bolt_workspace"
TABLE = ROOT / "tasks/nut_bolt/workspace_cells.json"
TASKS = ("PickBolt", "SeatNut", "TurnNut")
TIP_TOL = 0.012
PALM_MARGIN = 0.002
STEP_LIMIT = 0.90


@njit
def cross_matrix(axis):
    x, y, z = axis
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


@njit
def forward(q, origins, axes, home, tips):
    rot = np.eye(3)
    trans = np.zeros(3)
    joint = np.empty_like(origins)
    axis = np.empty_like(axes)
    for j in range(7):
        joint[j] = rot @ origins[j] + trans
        axis[j] = rot @ axes[j]
        skew = cross_matrix(axes[j])
        dq = q[j] - home[j]
        local = np.eye(3) + np.sin(dq) * skew + (1 - np.cos(dq)) * (skew @ skew)
        trans += rot @ (origins[j] - local @ origins[j])
        rot = rot @ local
    return tips @ rot.T + trans, rot, trans, joint, axis


@njit
def solve(goal, q, origins, axes, home, bounds, tips):
    q = q.copy()
    for _ in range(48):
        p, _, _, joints, axes_now = forward(q, origins, axes, home, tips)
        error = (goal - p).ravel()
        if np.max(np.abs(error)) < 0.001:
            break
        jac = np.empty((3 * len(tips), 7))
        for j in range(7):
            for k in range(len(tips)):
                jac[3 * k : 3 * k + 3, j] = np.cross(axes_now[j], p[k] - joints[j])
        update = np.linalg.solve(jac.T @ jac + np.eye(7) * 0.0002, jac.T @ error)
        q = np.minimum(bounds[:, 1], np.maximum(bounds[:, 0], q + np.clip(update, -0.16, 0.16)))
    return q


@njit
def route_check(goals, shaft_axes, origins, axes, home, bounds, tips, palm, table_x0, obstacle):
    q = home.copy()
    bound_points = np.empty((3, 3))
    bound_points[:2] = tips
    peak, gap, step = 0.0, 10.0, 0.0
    for stage in range(len(goals)):
        bound_bolt = len(shaft_axes) > 0 and 1 < stage < len(goals) - 1
        target = np.empty((3, 3)) if bound_bolt else goals[stage].copy()
        if bound_bolt:
            target[:2] = goals[stage]
            target[2] = (target[0] + target[1]) / 2 + 0.060 * shaft_axes[stage]
        control = bound_points if bound_bolt else tips
        nxt = solve(target, q, origins, axes, home, bounds, control)
        actual, rot, _, _, _ = forward(nxt, origins, axes, home, control)
        if len(shaft_axes) and stage == 1:
            # Bind a 60 mm virtual shaft witness to the solved grasp transform.
            # Rotating the hand about its pinch line must bring the shaft upright.
            bound_points[2] = (tips[0] + tips[1]) / 2 + rot.T @ (0.060 * shaft_axes[stage])
        for j in range(len(target)):
            peak = max(peak, np.linalg.norm(actual[j] - target[j]))
        if peak > TIP_TOL:
            return 1, stage, peak, gap, step
        delta = np.max(np.abs(nxt - q))
        if stage:
            step = max(step, delta)
            if step > STEP_LIMIT:
                return 2, stage, peak, gap, step
        segments = max(1, int(np.ceil(delta / 0.12)))
        for k in range(1, segments + 1):
            _, rot, trans, joints, _ = forward(q + (nxt - q) * k / segments, origins, axes, home, tips)
            witnesses = palm @ rot.T + trans
            for point in witnesses:
                if point[0] >= table_x0:
                    gap = min(gap, point[2])
                # Solid cylindrical enclosure of the upright bolt and stand.
                if obstacle[2] > 0:
                    radial = np.hypot(point[0] - obstacle[0], point[1] - obstacle[1]) - obstacle[3]
                    gap = min(gap, max(radial, point[2] - obstacle[2]))
            for j in range(3, 7):
                if joints[j, 0] >= table_x0:
                    gap = min(gap, joints[j, 2] - 0.035)
            if gap < PALM_MARGIN:
                return 3, stage, peak, gap, step
        q = nxt
    return 0, len(goals) - 1, peak, gap, step


def candidate_cells(task):
    # Distinct, nonoverlapping coarse cells. Relative pickup offsets for Seat
    # stay coupled to a particular support region before any cell is accepted.
    if task == "PickBolt":
        for yaw, x, y in product(
            (-90, -60, -30, 0, 30, 60, 75, 90), range(-310, -194, 20), range(-285, -159, 20)
        ):
            yield yaw, (x, y), (20, 20)
    elif task == "TurnNut":
        for yaw, x, y in product((-20, 0, 20), range(-180, -60, 20), range(-60, 60, 20)):
            yield yaw, (x, y), (20, 20)
    else:
        for x, y, dx, dy in product(
            range(-180, -60, 30), range(-60, 60, 30), (0, 30, 60), range(-285, -165, 30)
        ):
            yield 0, (x, y, dx, dy), (30, 30, 30, 30)


def geometry_ok(task, p, yaw, model):
    g = model["geometry"]
    xy = np.asarray(p[:2]) / 1000
    if task == "PickBolt":
        # The projected shaft endpoints, hex-head width and tip fit on table.
        axis = np.array([np.cos(np.deg2rad(yaw)), np.sin(np.deg2rad(yaw))])
        ends = np.stack(
            (
                xy - axis * model["bolt_height"] / 2,
                xy + axis * (model["bolt_height"] / 2 + model["tip_height"]),
            )
        )
        return np.all(ends - g["bolt_head_circumradius_m"] >= g["table_lo"][:2]) and np.all(
            ends + g["bolt_head_circumradius_m"] <= g["table_hi"][:2]
        )
    head = np.array(g["bolt_local_vertices_m"])
    if np.linalg.norm(xy + head[:, :2] - g["handoff_xy_m"], axis=1).max() >= g["handoff_radius_m"] - 0.0005:
        return False
    if task == "SeatNut":
        offset = np.asarray(p[2:]) / 1000
        nut = xy + offset
        return (
            np.linalg.norm(offset) > model["nut_radius"] + g["platform_radius_m"]
            and np.all(nut - model["nut_radius"] > g["table_lo"][:2])
            and np.all(nut + model["nut_radius"] < g["table_hi"][:2])
        )
    return True


def compile_task(task, model, writer):
    chain = [np.array(a, dtype=float) for a in model["chain"]]
    palm = np.array(model["palm_witnesses"])
    cache, cells = {}, {}

    def evaluate(p, yaw, side):
        key = (tuple(p), yaw, side)
        if key not in cache:
            if not geometry_ok(task, p, yaw, model):
                cache[key] = (4, 0, 0.0, 0.0, 0.0)
            else:
                angle = np.deg2rad(side + (yaw if task == "TurnNut" else 0))
                goals, shaft, obstacle = route(task, p, yaw, angle, model)
                cache[key] = route_check(
                    goals, shaft, *chain, palm, model["geometry"]["table_lo"][0], obstacle
                )
        return cache[key]

    sides = (-90, 90) if task == "PickBolt" else (30, 90, 150)

    def cells_to_check():
        for yaw, lo, size in candidate_cells(task):
            if len(lo) == 4:
                yield yaw, lo, size
                continue
            half = np.asarray(size) // 2
            # Probe a coarse cell before subdividing its live portion and
            # nearby edges. Final planar cells all have equal area.
            corners = [np.array(lo) + np.array(bit) * size for bit in product((0, 1), repeat=2)]
            if any(
                evaluate(p, yaw, side)[0] == 0 for p in [np.array(lo) + half, *corners] for side in sides
            ):
                for bit in product((0, 1), repeat=2):
                    yield yaw, tuple(np.array(lo) + np.array(bit) * half), tuple(half)
            else:
                writer.writerow(
                    [task, yaw, str(tuple(lo)), str(tuple(size)), "", "coarse screen", 0, "", "", "", 0]
                )

    for yaw, lo, size in cells_to_check():
        low = np.array(lo)
        corners = [tuple(low + np.array(bit) * size) for bit in product((0, 1), repeat=len(low))]
        probes = [*corners, tuple(low + np.array(size) / 2), tuple(low + np.array(size) * 0.27)]
        # Select one common route for every tested point of a cell.
        best = None
        for side in sides:
            rows = []
            for p in probes:
                result = evaluate(p, yaw, side)
                rows.append(result)
                if result[0]:
                    break
            if not rows[-1][0]:
                best = side
                break
        writer.writerow(
            [
                task,
                yaw,
                *[str(tuple(lo)), str(tuple(size))],
                side,
                ("pass", "IK residual", "joint jump", "clearance", "geometry")[rows[-1][0]],
                rows[-1][1],
                max(row[2] for row in rows),
                min(row[3] for row in rows),
                max(row[4] for row in rows),
                len(rows),
            ]
        )
        if best is not None:
            cells.setdefault(str(yaw), []).append([*lo, side])
    if not cells:
        raise ValueError(f"{task}: no accepted placement cells")
    sizes = list(map(int, size))
    # This point is off the build diagonal. A failed audit quarantines this
    # version instead of accepting a point unsupported by its compiled route.
    for yaw, bucket in cells.items():
        for cell in bucket:
            point = np.array(cell[:-1]) + np.array(sizes) * np.resize([0.73, 0.31, 0.42, 0.68], len(sizes))
            witness = evaluate(point, int(yaw), cell[-1])
            if witness[0]:
                raise ValueError(f"{task} cell failed independent interior witness: {cell}, {witness}")
    # Name near/far in the same yaw. In SeatNut hold the bolt location fixed
    # so differences measure transfer distance rather than a different support.
    centre = lambda c: np.array(c[:-1]) + np.array(sizes) / 2
    selected_yaw = "0" if "0" in cells else max(cells, key=lambda y: len(cells[y]))
    candidates = cells[selected_yaw]
    if task == "SeatNut":
        anchors = {tuple(c[:2]) for c in candidates}
        group = max(sorted(anchors), key=lambda a: len([c for c in candidates if tuple(c[:2]) == a]))
        candidates = [c for c in candidates if tuple(c[:2]) == group]
        distance = lambda c: np.linalg.norm(centre(c)[2:])
    else:
        ys = {c[1] for c in candidates}
        y = max(sorted(ys), key=lambda y: np.ptp([c[0] for c in candidates if c[1] == y]))
        candidates = [c for c in candidates if c[1] == y]
        distance = lambda c: centre(c)[0]
    presets = {
        name: [int(selected_yaw), *centre(fn(candidates, key=distance)).tolist()]
        for name, fn in (("near", min), ("far", max))
    }
    print(task, {y: len(cs) for y, cs in cells.items()}, presets, flush=True)
    cells = {yaw: [[int(v) for v in c] for c in bucket] for yaw, bucket in cells.items()}
    return {"cell_size_mm": sizes, "cells": cells, "presets": presets}


if __name__ == "__main__":
    model = json.loads((REPORT / "model.json").read_text())
    data = {"version": 1, "tasks": {}}
    with (REPORT / "screen.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "task",
                "yaw_deg",
                "lower_mm",
                "size_mm",
                "route_deg",
                "result",
                "stage",
                "max_tip_error_m",
                "min_clearance_m",
                "max_joint_step_rad",
                "tested_points_on_last_route",
            ]
        )
        for task in TASKS:
            data["tasks"][task] = compile_task(task, model[task], writer)
            stream.flush()
    TABLE.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
