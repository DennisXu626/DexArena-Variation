"""Opt-in world XY and relative root yaw for the Office Desk short tasks."""

import math
from collections.abc import Mapping
from numbers import Real
from sys import float_info


XY_BOUNDS_M = {
    "laptop": ((-0.04, -0.04), (0.04, 0.04)),
    "keyboard": ((-0.01, -0.04), (0.02, 0.04)),
    "mouse": ((-0.04, -0.04), (0.04, 0.04)),
}
YAW_OFFSETS_DEG = (-10, 0, 10)


def resolve_position_layout(requests, selected, device_name, center):
    """Validate all selected rows before any reset state can change."""
    indices = [str(i) for i in selected]
    if not isinstance(requests, Mapping) or set(requests) != set(indices):
        raise ValueError("position_layout requires exactly one string key per selected environment")

    xy_key = f"{device_name}_xy_m"
    yaw_key = f"{device_name}_yaw_offset_deg"
    lower, upper = XY_BOUNDS_M[device_name]
    layouts = {}
    for index in indices:
        request = requests[index]
        if not isinstance(request, Mapping) or set(request) - {xy_key, yaw_key}:
            raise ValueError(f"position_layout env {index}: unknown {device_name} fields")

        xy = request.get(xy_key, list(center))
        if (not isinstance(xy, (tuple, list)) or len(xy) != 2
                or any(not isinstance(axis, Real) or isinstance(axis, bool)
                       or not -float_info.max <= axis <= float_info.max for axis in xy)):
            raise ValueError(f"position_layout env {index}: {xy_key} requires two finite numbers")
        if any(not low - 1e-8 <= axis - origin <= high + 1e-8
               for axis, origin, low, high in zip(xy, center, lower, upper)):
            raise ValueError(f"position_layout env {index}: {xy_key} outside approved bounds")

        yaw = request.get(yaw_key, 0)
        if (not isinstance(yaw, Real) or isinstance(yaw, bool)
                or yaw not in YAW_OFFSETS_DEG):
            raise ValueError(f"position_layout env {index}: {yaw_key} must be one of {YAW_OFFSETS_DEG}")
        layouts[index] = (tuple(float(axis) for axis in xy), math.radians(yaw))
    return layouts


def apply_position_layout(options, env_idx, xyz, yaw):
    """Replace only requested root XY/yaw, after native draws and before placement."""
    layout = options.get("position_layout")
    if layout is not None:
        rows = [layout[str(i)] for i in env_idx.tolist()]
        xy, angles = zip(*rows)
        xyz[:, :2] = xyz.new_tensor(xy)
        yaw[:] = yaw.new_tensor(angles)
