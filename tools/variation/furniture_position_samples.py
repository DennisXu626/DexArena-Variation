"""Furniture position matrix and projections derived from task collision geometry."""

from itertools import product

import numpy as np
from scipy.spatial.transform import Rotation

from tasks.furniture_assembly.furniture_assembly_lay_flat_panel import (
    PANEL_HALF, PLACE_CENTER, PLACE_REGION_HALF_SIZE, RACK_BASE_HALF, RACK_CENTER,
    RAIL_PICK_CENTER,
)
from tasks.furniture_assembly.furniture_assembly_insert_rail import RAIL_HALF
from tasks.furniture_assembly.position_layout import XY_OFFSETS_M, YAW_DEGREES


TASK_ROLES = {
    "LayFlatPanel": ("rack",), "InsertRail": ("rail", "panel"), "FastenScrew": ("panel",),
}
CENTERS = {"rack": RACK_CENTER, "panel": PLACE_CENTER, "rail": RAIL_PICK_CENTER}
FIGURE_PREFIX = {"rack": "R", "panel": "P", "rail": "L"}


def rect(xy, half, yaw=0):
    corners = np.array([(-half[0], -half[1]), (half[0], -half[1]),
                        (half[0], half[1]), (-half[0], half[1])])
    return Rotation.from_euler("z", yaw, degrees=True).as_matrix()[:2, :2] @ corners.T + np.asarray(xy)[:, None]


def rectangle_clearance(vertices, xy, half):
    return float((np.asarray(half) - np.abs(vertices.T - xy)).min())


def extent_clearance(kind, poses, table):
    areas = {
        role: rect(pose[:2], half, pose[2])
        for role, half in (("rack", RACK_BASE_HALF), ("panel", PANEL_HALF), ("rail", RAIL_HALF))
        if (pose := poses.get(role)) is not None and (role != "panel" or kind != "LayFlatPanel")
    }
    clearance = {f"{role}_table_edge_m": rectangle_clearance(v, table[0], table[1])
                 for role, v in areas.items()}
    if kind == "LayFlatPanel":
        clearance["rack_to_place_y_m"] = float(areas["rack"][1].min() - PLACE_CENTER[1] - PLACE_REGION_HALF_SIZE[1])
    else:
        clearance["panel_inside_place_m"] = rectangle_clearance(areas["panel"], PLACE_CENTER, PLACE_REGION_HALF_SIZE)
        if kind == "InsertRail":
            clearance["rail_to_panel_y_m"] = float(areas["panel"][1].min() - areas["rail"][1].max())
    return clearance


def xy_request(role, offset):
    return {f"{role}_xy_m": [round(sum(pair), 6) for pair in zip(CENTERS[role], offset)]}


def midpoint_cases(kind):
    """Supplement an asymmetric Y domain's true centre and the two adjacent edge midpoints."""
    for role in TASK_ROLES[kind]:
        (xmin, xmax), (ymin, ymax) = XY_OFFSETS_M[role]
        ymid = (ymin + ymax) / 2
        if ymid:
            for number, x in enumerate((xmin, 0, xmax), start=10):
                point = f"{FIGURE_PREFIX[role]}XY-{number}"
                yield point, f"{role}_xy_midpoints", xy_request(role, (x, ymid)), False


def cases(kind):
    """A shared nominal, corners, centreline points, endpoints and mixed stress cases."""
    yield "N", "nominal", {}, False
    for role in TASK_ROLES[kind]:
        prefix = FIGURE_PREFIX[role]
        (xmin, xmax), (ymin, ymax) = XY_OFFSETS_M[role]
        for number, offset in enumerate(product((xmin, 0, xmax), (ymin, 0, ymax)), start=1):
            if offset != (0, 0):
                yield f"{prefix}XY-{number}", f"{role}_xy", xy_request(role, offset), False
        for number, yaw in enumerate(YAW_DEGREES[role], start=1):
            if yaw:
                yield f"{prefix}W-{number}", f"{role}_yaw", {f"{role}_yaw_deg": yaw}, False
        yield f"{prefix}-out-xy", "expected_reject", xy_request(role, (xmax + 0.0001, 0)), True
        yield f"{prefix}-out-yaw", "expected_reject", {f"{role}_yaw_deg": YAW_DEGREES[role][-1] + 0.1}, True

    def corner(role, x, y, angle):
        bounds = XY_OFFSETS_M[role]
        return {**xy_request(role, (bounds[0][x], bounds[1][y])),
                f"{role}_yaw_deg": YAW_DEGREES[role][angle]}

    if kind == "LayFlatPanel":
        yield "C-edge", "combined", corner("rack", 0, 0, 0), False
        yield "C-far", "combined", corner("rack", 1, 1, 2), False
    if kind == "InsertRail":
        yield "C-lane", "combined", {**corner("rail", 0, 1, 2), **corner("panel", 0, 0, 0)}, False
        yield "C-far", "combined", {**corner("rail", 1, 0, 0), **corner("panel", 1, 1, 2)}, False
    if kind == "FastenScrew":
        yield "C-near", "combined", corner("panel", 0, 0, 2), False
        yield "C-far", "combined", corner("panel", 1, 1, 0), False
    yield from midpoint_cases(kind)
