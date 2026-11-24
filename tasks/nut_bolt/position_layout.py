"""Explicit Nut & Bolt reset positions in scene metres and degrees."""

from collections.abc import Mapping
import math
from numbers import Real


BOLT_SPAWN_RADIUS_M = 0.07
BOLT_SPAWN_YAW_DEG = (-90, 0, 90)
UPRIGHT_BOLT_RADIUS_M = 0.075
TABLE_NUT_HALF_RANGE_M = (0.04, 0.04)
THREADED_NUT_RELATIVE_YAW_DEG = (-20, 0, 20)

FIELDS = {
    "PickBolt": {"bolt_spawn_xy_m", "bolt_spawn_yaw_deg"},
    "SeatNut": {"upright_bolt_xy_m", "table_nut_xy_m"},
    "TurnNut": {"upright_bolt_xy_m", "threaded_nut_relative_yaw_deg"},
}


def _xy(value, center, *, radius=None, half_range=None):
    if (
        not isinstance(value, (tuple, list))
        or len(value) != 2
        or any(isinstance(axis, bool) or not isinstance(axis, Real) for axis in value)
    ):
        raise ValueError("expected two finite coordinates in metres")
    try:
        point = tuple(map(float, value))
    except OverflowError as exc:
        raise ValueError("expected two finite coordinates in metres") from exc
    if not all(map(math.isfinite, point)):
        raise ValueError("expected two finite coordinates in metres")
    if radius is not None:
        inside = math.dist(point, center) <= radius + 1e-9
    else:
        inside = all(abs(axis - origin) <= limit + 1e-9
                     for axis, origin, limit in zip(point, center, half_range))
    if not inside:
        raise ValueError("coordinates are outside the position domain")
    return point


def _yaw(value, choices):
    if isinstance(value, bool) or not isinstance(value, Real) or value not in choices:
        raise ValueError(f"yaw must be one of {choices} degrees")
    return math.radians(value)


def requested_layout(env, indices, options):
    """Validate all selected rows and return columns in reset-index order."""
    if options is None or "position_layout" not in options:
        return None
    task = getattr(env, "position_layout_task", None)
    if task not in FIELDS:
        raise ValueError("position_layout is available for the three Nut & Bolt short tasks")
    if "reset_to_env_states" in options:
        raise ValueError("position_layout cannot be combined with state restoration")
    requests = options["position_layout"]
    keys = [str(int(index)) for index in indices]
    if not isinstance(requests, Mapping) or set(requests) != set(keys):
        raise ValueError("position_layout must contain exactly one string key per selected environment")
    columns = {key: [] for key in FIELDS[task]}
    for key in keys:
        request = requests[key]
        if not isinstance(request, Mapping) or set(request) - FIELDS[task]:
            raise ValueError(f"position_layout env {key}: unsupported request fields for {task}")
        try:
            if task == "PickBolt":
                columns["bolt_spawn_xy_m"].append(
                    _xy(request.get("bolt_spawn_xy_m", env.bolt_spawn_xy),
                        env.bolt_spawn_xy, radius=BOLT_SPAWN_RADIUS_M)
                )
                columns["bolt_spawn_yaw_deg"].append(
                    _yaw(request.get("bolt_spawn_yaw_deg", 0), BOLT_SPAWN_YAW_DEG)
                )
            else:
                columns["upright_bolt_xy_m"].append(
                    _xy(request.get("upright_bolt_xy_m", env.bolt_place_center_xy),
                        env.bolt_place_center_xy, radius=UPRIGHT_BOLT_RADIUS_M)
                )
                if task == "SeatNut":
                    columns["table_nut_xy_m"].append(
                        _xy(request.get("table_nut_xy_m", env.nut_spawn_xy),
                            env.nut_spawn_xy, half_range=TABLE_NUT_HALF_RANGE_M)
                    )
                else:
                    columns["threaded_nut_relative_yaw_deg"].append(
                        _yaw(request.get("threaded_nut_relative_yaw_deg", 0),
                             THREADED_NUT_RELATIVE_YAW_DEG)
                    )
        except ValueError as exc:
            raise ValueError(f"position_layout env {key}: {exc}") from exc
    return columns
