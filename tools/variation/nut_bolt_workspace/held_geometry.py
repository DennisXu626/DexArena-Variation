"""Audit the assumed rigidly-held paths using measured collision parts.

The motion screen solves the arm. This complementary geometry audit evaluates
the moving workpiece independently from the robot's open-hand tip model.
"""

from itertools import product
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation
from routes import route

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "docs/variation/evidence/nut_bolt_workspace"


def bolt_extent(g, rotation):
    head = rotation.apply(g["bolt_local_vertices_m"])
    low, high = head.min(axis=0), head.max(axis=0)
    for cyl in g["bolt_cylinders"]:
        p = np.asarray(cyl["local_pose"])
        axis = (rotation * Rotation.from_quat(np.roll(p[3:], -1))).as_matrix()[:, 0]
        bounds = np.abs(axis) * cyl["half_length_m"] + cyl["radius_m"] * np.sqrt(np.maximum(0, 1 - axis**2))
        center = rotation.apply(p[:3])
        low = np.minimum(low, center - bounds)
        high = np.maximum(high, center + bounds)
    return low, high


def table_margin(g, low, high):
    return np.minimum(low[:, :2] - g["table_lo"][:2], g["table_hi"][:2] - high[:, :2]).min()


def pick(g, model, yaw, points):
    theta = np.deg2rad(yaw)
    axis = np.array([np.cos(theta), np.sin(theta), 0.0])
    initial = (
        Rotation.from_euler("z", theta)
        * Rotation.from_euler("y", 90, degrees=True)
        * Rotation.from_euler("z", g["candidate"]["bolt_spawn_axial_spin_deg"], degrees=True)
    )
    origin_z = -bolt_extent(g, initial)[0][2] + 0.001
    node_centres = route("PickBolt", points[0] * 1000, yaw, 0.0, model)[0].mean(axis=1)
    delta_grip = node_centres[1] - np.r_[points[0], origin_z]
    shaft_offset = np.dot(delta_grip, axis) * axis
    start = np.column_stack((points, np.full(len(points), origin_z))) + shaft_offset
    finish = np.broadcast_to(node_centres[-2] - [0, 0, delta_grip[2]], start.shape)
    up = start.copy()
    up[:, 2] = node_centres[2, 2] - delta_grip[2]
    above = finish.copy()
    above[:, 2] = up[:, 2]
    stages = ((start, up, 0.0, 0.0), (up, above, 0.0, np.pi / 2), (above, finish, np.pi / 2, np.pi / 2))
    gap, edge = 10.0, 10.0
    for a, b, aa, bb in stages:
        steps = max(
            1, int(np.ceil(max(np.linalg.norm(b - a, axis=1).max() / 0.005, abs(bb - aa) / np.deg2rad(5))))
        )
        for f in np.linspace(0, 1, steps + 1):
            delta = Rotation.from_rotvec(np.cross(axis, [0, 0, 1]) * (aa + (bb - aa) * f))
            rotation = delta * initial
            root = a + (b - a) * f - delta.apply(shaft_offset)
            lo, hi = bolt_extent(g, rotation)
            low = root + lo
            high = root + hi
            gap = min(gap, low[:, 2].min() - g["table_hi"][2])
            edge = min(edge, table_margin(g, low, high))
    return dict(table_z_m=gap, table_edge_m=edge)


def annulus_clearance(parts, centers, boltxy, angle):
    # Each Nut wall is an oriented box. Its closest point to the bolt axis
    # is computed by clamping independently along its two planar axes.
    rotation = Rotation.from_euler("z", angle, degrees=True).as_matrix()[:2, :2]
    nearest = np.full(len(centers), np.inf)
    for part in np.asarray(parts):
        p = part[:, :2] @ rotation.T
        centre = p.mean(axis=0)
        d = boltxy - centers[:, :2] - centre
        u = (p[2] - p[0]) / 2
        v = (p[4] - p[0]) / 2
        hu, hv = np.linalg.norm(u), np.linalg.norm(v)
        dx = np.maximum(0, np.abs(d @ (u / hu)) - hu)
        dy = np.maximum(0, np.abs(d @ (v / hv)) - hv)
        nearest = np.minimum(nearest, np.hypot(dx, dy))
    return nearest


def nut(task, g, model, yaw, points):
    bolt = points[:, :2]
    h = g["nut_half_height_m"]
    goal = np.column_stack((bolt, np.full(len(bolt), g["platform_support_height_m"] + h)))
    if task == "SeatNut":
        start = np.column_stack((bolt + points[:, 2:], np.full(len(bolt), h + 0.001)))
        up = start.copy()
        centres = route(task, points[0] * 1000, yaw, 0.0, model)[0].mean(axis=1)
        up[:, 2] = centres[2, 2] - (centres[1, 2] - start[0, 2])
        above = goal.copy()
        above[:, 2] = up[:, 2]
        legs = ((start, up, 0, 0), (up, above, 0, 0), (above, goal, 0, 0))
        key = "nut_local_parts_m"
    else:
        legs = ((goal, goal, yaw, yaw + 180),)
        key = "threaded_nut_local_parts_m"
    edge, gap, radial, platform = 10.0, 10.0, 10.0, 10.0
    r_shaft = g["bolt_cylinders"][0]["radius_m"]
    for a, b, aa, bb in legs:
        steps = max(1, int(np.ceil(max(np.linalg.norm(b - a, axis=1).max() / 0.005, abs(aa - bb) / 5))))
        for f in np.linspace(0, 1, steps + 1):
            center = a + f * (b - a)
            ang = aa + f * (bb - aa)
            shape = Rotation.from_euler("z", ang, degrees=True).apply(np.vstack(g[key]))
            lo = center + shape.min(axis=0)
            hi = center + shape.max(axis=0)
            edge = min(edge, table_margin(g, lo, hi))
            gap = min(gap, lo[:, 2].min() - g["table_hi"][2])
            nearest = annulus_clearance(g[key], center, bolt, ang)
            vertical = lo[:, 2] - (model["bolt_height"] + model["tip_height"])
            radial = min(radial, np.maximum(vertical, nearest - r_shaft).min())
            platform = min(
                platform,
                np.maximum(
                    lo[:, 2] - g["platform_support_height_m"], nearest - g["platform_radius_m"]
                ).min(),
            )
    return dict(
        table_z_m=gap, table_edge_m=edge, bolt_envelope_clearance_m=radial, platform_clearance_m=platform
    )


def main():
    catalog = json.loads((ROOT / "tasks/nut_bolt/workspace_cells.json").read_text())["tasks"]
    models = json.loads((REPORT / "model.json").read_text())
    report = {}
    for task, spec in catalog.items():
        model = models[task]
        g = model["geometry"]
        size = np.array(spec["cell_size_mm"])
        probes = np.asarray([*product((0, 1), repeat=len(size)), np.full(len(size), 0.5)])
        report[task] = {}
        for yaw, cells in spec["cells"].items():
            points = np.unique(np.vstack([np.array(c[:-1]) + probes * size for c in cells]), axis=0) / 1000
            values = (
                pick(g, model, int(yaw), points)
                if task == "PickBolt"
                else nut(task, g, model, int(yaw), points)
            )
            # A touching support at the placement endpoints is expected.
            assert min(values.values()) >= -1e-6, (task, yaw, values)
            report[task][yaw] = dict(unique_layouts=len(points), **values)
    (REPORT / "held_geometry.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
