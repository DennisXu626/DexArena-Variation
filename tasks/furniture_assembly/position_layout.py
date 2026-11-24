"""Validate explicit Furniture short-task resets before touching simulation state."""

from collections.abc import Mapping
import math
from numbers import Integral, Real


# World XY offsets from the task's native centre, in metres. Yaw is absolute.
XY_OFFSETS_M = {
    "rack": ((-.045, .045), (-.01, .045)),
    "panel": ((-.015, .015), (-.012, .012)),
    "rail": ((-.06, .06), (-.055, .04)),
}
YAW_DEGREES = {"rack": (-10, 0, 10), "panel": (-7, 0, 7), "rail": (-10, 0, 10)}


def _xy(value, center, offsets):
    if (not isinstance(value, (tuple, list)) or len(value) != 2
            or any(isinstance(axis, bool) or not isinstance(axis, Real)
                   or not math.isfinite(axis) for axis in value)):
        raise ValueError("expected two finite coordinates in metres")
    if any(not lo - 1e-9 <= axis - origin <= hi + 1e-9
           for axis, origin, (lo, hi) in zip(value, center, offsets)):
        raise ValueError("outside the explicit position bounds")
    return list(value)


def requested_layout(options, num_envs, role_centers):
    """Return validated rows in reset-index order when a layout was requested."""
    if not options or "position_layout" not in options:
        return None
    env_idx = options.get("env_idx", range(num_envs))
    if hasattr(env_idx, "tolist"):
        env_idx = env_idx.tolist()
    if (not isinstance(env_idx, (list, tuple, range)) or not env_idx
            or any(isinstance(i, bool) or not isinstance(i, Integral) or not 0 <= i < num_envs
                   for i in env_idx) or len(set(env_idx)) != len(env_idx)):
        raise ValueError("position_layout requires valid unique selected environment indices")
    keys = [str(i) for i in env_idx]
    requests = options["position_layout"]
    if not isinstance(requests, Mapping) or set(requests) != set(keys):
        raise ValueError("position_layout must have exactly one string key per selected environment")
    allowed = {f"{role}_{suffix}" for role in role_centers for suffix in ("xy_m", "yaw_deg")}
    rows = []
    for key in keys:
        row = requests[key]
        if not isinstance(row, Mapping) or set(row) - allowed:
            raise ValueError(f"position_layout env {key}: unsupported request fields")
        parsed = {}
        for role, center in role_centers.items():
            try:
                xy = _xy(row.get(f"{role}_xy_m", center), center, XY_OFFSETS_M[role])
                yaw = row.get(f"{role}_yaw_deg", 0)
                choices = YAW_DEGREES[role]
                if isinstance(yaw, bool) or not isinstance(yaw, Real) or yaw not in choices:
                    raise ValueError(f"yaw must be one of {choices} degrees")
            except ValueError as exc:
                raise ValueError(f"position_layout env {key} {role}: {exc}") from exc
            parsed[role] = [*xy, math.radians(yaw)]
        rows.append(parsed)
    return rows


def role_pose_tensor(rows, role, like):
    """Pack the selected absolute XY and yaw into one tensor on the caller's device."""
    return like.new_tensor([row[role] for row in rows])
