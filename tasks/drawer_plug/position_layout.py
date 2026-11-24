"""Validate explicit per-environment positions for the three Drawer short tasks."""
from collections.abc import Mapping
import math
from numbers import Real

import numpy as np

_FIELDS = {
    "OpenDrawer": {"drawer_xy_m", "drawer_yaw_deg"},
    "PickCharger": {"drawer_xy_m", "drawer_yaw_deg", "charger_drawer_local_xy_m"},
    "InsertPlug": {"socket_xy_m", "socket_yaw_deg", "charger_table_xy_m"},
}


def _xy(value, center, extent, circular=False, tolerance=1e-9):
    if (not isinstance(value, (tuple, list)) or len(value) != 2
            or any(not isinstance(axis, Real) or isinstance(axis, bool) for axis in value)):
        raise ValueError("expected a pair of numeric coordinates")
    point = np.asarray(value, dtype=float)
    delta = np.abs(point - center)
    if not np.isfinite(point).all():
        raise ValueError("expected finite coordinates")
    excess = np.linalg.norm(delta) - extent if circular else (delta - extent).max()
    if excess > tolerance:
        raise ValueError("outside approved position bounds")
    return point.tolist()


def _angle(value, options):
    if isinstance(value, bool) or not isinstance(value, Real) or value not in options:
        raise ValueError(f"yaw must be one of {options} degrees")
    return math.radians(value)


def requested_layout(env, options, env_idx, task):
    """Return rows in reset-index order. Omitting the option delegates to native."""
    if "position_layout" not in options:
        return None
    requests = options["position_layout"]
    indices = list(map(str, env_idx.tolist()))
    if not isinstance(requests, Mapping) or set(requests) != set(indices):
        raise ValueError("position_layout must have exactly one string key per selected environment")
    rows = []
    for index in indices:
        row = requests[index]
        if not isinstance(row, Mapping) or set(row) - _FIELDS[task]:
            raise ValueError(f"position_layout env {index}: unsupported request fields for {task}")
        try:
            if task == "InsertPlug":
                item = {
                    "socket_xy": _xy(row.get("socket_xy_m", env.socket_center_xy),
                                     env.socket_center_xy, .02, circular=True),
                    "socket_yaw": _angle(row.get("socket_yaw_deg", 90), (85, 90, 95)),
                }
                if "charger_table_xy_m" in row:
                    item["charger_table_xy"] = _xy(row["charger_table_xy_m"],
                        env.charger_place_center_xy, .75 * env.charger_place_radius, circular=True)
            else:
                item = {
                    "drawer_xy": _xy(row.get("drawer_xy_m", env.drawer_xy), env.drawer_xy, .05),
                    "drawer_yaw": _angle(row.get("drawer_yaw_deg", 0), (-5, 0, 5)),
                }
                if task == "PickCharger":
                    center = env._charger_drawer_center()
                    item["charger_drawer_xy"] = _xy(row.get("charger_drawer_local_xy_m", center),
                                                     center, [.01, .02], tolerance=1e-6)
        except ValueError as exc:
            raise ValueError(f"position_layout env {index}: {exc}") from exc
        rows.append(item)
    return rows
