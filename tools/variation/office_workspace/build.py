"""Rebuild the task-specific workspace maps from recorded native Office collision frames."""

import argparse
from collections import Counter
import csv
from functools import lru_cache
from itertools import product
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from kinematics import trace

ROOT = Path(__file__).resolve().parents[3]
FRAMES = ROOT / "docs/variation/evidence/office_workspace/frames"
MAPS = ROOT / "tasks/office_desk/workspace_maps"
EVIDENCE = FRAMES.parent
STEP = 0.04
ROUTES = {
    "ClickMouse": ("front", "shell_side"),
    "OpenLaptop": ("front", "side"),
    "TypeKeys": ("front", "side"),
}
GRID = {
    "ClickMouse": ((-3, 5), (-3, 4)),
    "OpenLaptop": ((-3, 4), (-2, 4)),
    "TypeKeys": ((-2, 4), (-2, 3)),
}


def zrot(yaw):
    return Rotation.from_euler("z", yaw, degrees=True).as_matrix()


def box(vertices):
    points = np.asarray(vertices)
    return 0.5 * (points.max(0) + points.min(0)), 0.5 * (points.max(0) - points.min(0))


class OfficeScreen:
    def __init__(self, frame):
        self.frame = frame
        self.origin = np.array(frame["origin"])
        self.tip = np.array(frame["tip"])
        self.palm = np.mean(np.asarray(frame["protected"]["hand_C_MC"]).reshape(-1, 3), axis=0)
        self.arm = [
            np.ascontiguousarray(frame[field], dtype=float)
            for field in ("home", "joints_xyz", "axes", "limits", "tip")
        ] + [self.palm]
        corner_groups, links = [], []
        for name, groups in frame["protected"].items():
            parent = int(name[-1]) if name.startswith("panda_link") else 7
            corner_groups.extend(groups)
            links.extend([parent] * len(groups))
        self.arm += [np.array(corner_groups), np.array(links)]
        self.footprint = np.array(frame["footprint"])
        self.table = np.array(frame["table"])

    def lift_path(self, route, start_angle):
        control = self.frame["controls"]
        points = []
        orientations = []
        if self.frame["device"] == "laptop":
            lid = control["lid"]
            edge = np.array(control["targets_xyz_m"]["lid edge"])
            axis, hinge = np.array(lid["axis_world"]), np.array(lid["hinge_xyz_m"])
            sign, original = self.frame["open_sign"], lid["angles_deg"][0]

            def at(angle):
                turn = Rotation.from_rotvec(axis * sign * np.deg2rad(angle - original))
                return hinge + turn.apply(edge - hinge)

            points.extend(
                [at(start_angle) + [-0.027, 0.023 if route == "side" else 0.0, 0.020], at(start_angle)]
            )
            orientations.extend([start_angle, start_angle])
            for angle in np.linspace(start_angle, 90.0, 9)[1:]:
                points.append(at(angle))
                orientations.append(angle)
            points.append(points[-1] + [-0.025, 0, 0.025])
            orientations.append(90.0)
        else:
            press = np.array(control["press_direction_xyz"])
            side = np.array([-0.007, -0.022 if route in ("side", "shell_side") else 0.0, 0.0])
            for point in control["targets_xyz_m"].values():
                top = np.array(point)
                points.extend(
                    [
                        top - 0.027 * press + side,
                        top - 0.012 * press,
                        top,
                        top + (0.001 if self.frame["device"] == "mouse" else 0.003) * press,
                        top - 0.027 * press,
                    ]
                )
            orientations = [0.0] * len(points)
        return np.asarray(points), orientations

    def evaluate(self, xy, yaw, route, start_angle=45.0, details=False):
        f = self.frame
        rot = zrot(yaw)
        shift = np.r_[xy, self.origin[2]] - rot @ self.origin
        footprint = self.footprint @ rot[:2, :2].T + shift[:2]
        table_gap = min(
            (footprint.min(0) - self.table[0, :2]).min(), (self.table[1, :2] - footprint.max(0)).min()
        )
        if table_gap < 0.001:
            return (4, 0, 0.0, table_gap, 0.0, None)
        centers, frames, half_sizes = [], [], []
        tc, ts = box(self.table)
        sc, ss = box(f["shell"])
        base_boxes = [(tc, np.eye(3), ts), (rot @ sc + shift, rot, ss)]
        path, angles = self.lift_path(route, start_angle)
        if "screen_hull" in f:
            hull = np.array(f["screen_hull"])
            _, _, vh = np.linalg.svd(hull - hull.mean(0), full_matrices=False)
            edge_center, edge_sizes = box((hull - hull.mean(0)) @ vh.T)
            screen_center = hull.mean(0) + vh.T @ edge_center
            lid = f["controls"]["lid"]
            hinge = np.asarray(lid["hinge_xyz_m"])
        goals, offsets = [], []
        hand_vector = self.palm - self.tip
        length = np.linalg.norm(hand_vector)
        # A raised palm and two azimuths select distinct kinematic solutions.
        side = route in ("side", "shell_side")
        direction = rot @ (zrot(-30.0 if side else 0.0) @ hand_vector)
        direction[2] = 0.10 if side else 0.095
        direction *= length / np.linalg.norm(direction)
        previous, prev_dir = self.tip, hand_vector
        previous_angle = angles[0]
        for target, angle in zip(path, angles):
            target = rot @ target + shift
            n = max(1, int(np.ceil(np.linalg.norm(target - previous) / 0.035)))
            for alpha in np.linspace(1.0 / n, 1.0, n):
                goals.append(previous + (target - previous) * alpha)
                offsets.append(prev_dir + (direction - prev_dir) * alpha)
                obstacles = list(base_boxes)
                if "screen_hull" in f:
                    current_angle = previous_angle + alpha * (angle - previous_angle)
                    moving = Rotation.from_rotvec(
                        np.array(lid["axis_world"])
                        * f["open_sign"]
                        * np.deg2rad(current_angle - lid["angles_deg"][0])
                    ).as_matrix()
                    obstacles.append(
                        (
                            rot @ (hinge + moving @ (screen_center - hinge)) + shift,
                            rot @ moving @ vh.T,
                            edge_sizes,
                        )
                    )
                c, b, s = zip(*obstacles)
                centers.append(c)
                frames.append(b)
                half_sizes.append(s)
            previous, prev_dir, previous_angle = target, direction, angle
        result = trace(
            *self.arm,
            np.array(goals),
            np.array(offsets),
            np.array(centers),
            np.array(frames),
            np.array(half_sizes),
        )
        return result if details else (*result[:5], None)


def build(task, probe):
    data = json.loads((FRAMES / (task + ".json")).read_text(encoding="utf-8"))
    screen = OfficeScreen(data)
    center = screen.origin[:2]
    if probe:
        for dx, dy in [(0.0, 0.0), (-0.06, 0.06), (0.06, 0.06), (0.06, -0.06), (-0.06, -0.06)]:
            for route in ROUTES[task]:
                result = screen.evaluate(center + [dx, dy], 0, route)
                print(task, dx, dy, route, result[:5], flush=True)
        return
    table = {
        "version": "office-workspace-v1",
        "step_m": STEP,
        "device": data["device"],
        "yaw_deg": [],
        "cells": {},
        "presets": {},
    }
    stats = Counter()
    rows = []

    @lru_cache(maxsize=None)
    def test(x, y, yaw, route):
        # Laptop edge and screen posture change over the native 40–50 degree starting interval.
        angles = (40.0, 45.0, 50.0) if task == "OpenLaptop" else (0.0,)
        for angle in angles:
            record = screen.evaluate([x, y], yaw, route, angle)
            rows.append((x, y, yaw, route, angle, *record[:5]))
            stats[int(record[0])] += 1
            if record[0]:
                return False
        return True

    for yaw in (-10, 0, 10):
        cells = []
        xb, yb = GRID[task]

        def screen_cell(x, y, step):
            # The asymmetric interior point is held out from corner and centre screening.
            offsets = [(0, 0), (0, 1), (1, 0), (1, 1), (0.5, 0.5), (0.23, 0.71)]
            routes = [
                route
                for route in ROUTES[task]
                if all(
                    test(round(x + dx * step, 8), round(y + dy * step, 8), yaw, route)
                    for dx, dy in offsets
                )
            ]
            if routes:
                cells.append([round(x, 8), round(y, 8), step, routes])
            elif step == STEP:
                for dx, dy in product((0.0, 0.5), repeat=2):
                    screen_cell(x + dx * step, y + dy * step, step / 2)

        for ix, iy in product(range(*xb), range(*yb)):
            x, y = np.round(center + np.array([ix, iy]) * STEP, 8)
            screen_cell(x, y, STEP)
        if cells:
            table["yaw_deg"].append(yaw)
            table["cells"][str(yaw)] = cells
        print(task, yaw, "cells", len(cells), "tested", dict(stats), flush=True)
    if not table["cells"]:
        raise RuntimeError(f"{task}: empty screened domain")
    yaw = min(table["yaw_deg"], key=abs)
    coords = np.array([np.asarray(cell[:2]) + cell[2] / 2 for cell in table["cells"][str(yaw)]])
    nominal = coords[np.argmin(np.linalg.norm(coords - center, axis=1))]
    for name, i, sign in (("near", 0, 1), ("far", 0, -1), ("left", 1, -1), ("right", 1, 1)):
        target = coords[np.isclose(coords[:, 1 - i], nominal[1 - i])]
        value = target[np.argmin(sign * target[:, i])]
        table["presets"][name] = [*np.round(value, 8), yaw]
    contains_center = any(
        all(cell[j] - 2e-8 <= center[j] <= cell[j] + cell[2] + 2e-8 for j in range(2))
        for cell in table["cells"][str(yaw)]
    )
    table["presets"]["reference"] = [*np.round(center if contains_center else nominal, 8), yaw]
    MAPS.mkdir(parents=True, exist_ok=True)
    (MAPS / (data["device"] + ".json")).write_text(
        json.dumps(table, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    with (EVIDENCE / (task + "_screen.csv")).open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(
            (
                "root_x_m",
                "root_y_m",
                "yaw_deg",
                "route",
                "open_angle_deg",
                "reject_code",
                "waypoint",
                "tip_error_m",
                "clearance_m",
                "max_joint_step_rad",
            )
        )
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=tuple(ROUTES), required=True)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    build(args.task, args.probe)
