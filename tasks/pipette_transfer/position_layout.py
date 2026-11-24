"""Deterministic Pipette workstation requests in world metres and degrees."""

from collections.abc import Mapping
from math import cos, hypot, isfinite, radians, sin
from numbers import Real


# Offsets from PipetteConfig centers, in order ((min X, min Y), (max X, max Y)).
XY_OFFSETS_M = {
    "stand": ((-.030, -.030), (.030, .010)),
    "cup": ((-.035, -.010), (.035, .040)),
    "rack": ((-.040, -.030), (.040, .030)),
}
STAND_YAW_DEG = (78, 90, 102)
STAND_BASE_HALF_XY_M = (.060, .055)
DISH_COLLISION_RADIUS_LIMIT_M = .059  # conservative circumscribed collision band


def stand_dish_gap_m(stand, cup, yaw_deg):
    """Lower bound on clearance from the rotated base to the dish collision wall."""
    dx, dy = (b - a for a, b in zip(stand, cup))
    angle = radians(yaw_deg)
    local = (cos(angle) * dx + sin(angle) * dy, -sin(angle) * dx + cos(angle) * dy)
    return hypot(*(max(0., abs(value) - half) for value, half in
                   zip(local, STAND_BASE_HALF_XY_M))) - DISH_COLLISION_RADIUS_LIMIT_M


def position_centers(cfg):
    return {"stand": cfg.pipette_stand_xy, "cup": cfg.cup_xy, "rack": cfg.rack_xy}


def _xy(value, base, name):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(axis, bool) or not isinstance(axis, Real) or not isfinite(axis)
                   for axis in value)):
        raise ValueError(f"{name}_xy_m requires two finite world coordinates")
    lo, hi = XY_OFFSETS_M[name]
    if any(not origin + left - 1e-9 <= axis <= origin + right + 1e-9
           for axis, origin, left, right in zip(value, base, lo, hi)):
        raise ValueError(f"{name}_xy_m outside position bounds")
    return tuple(map(float, value))


def requested_layout(env, options, indices, min_stand_dish_gap_m):
    """Validate the entire request before ManiSkill changes state or random streams."""
    if "reset_to_env_states" in options:
        raise ValueError("Pipette state restoration cannot include position_layout")
    entries = options["position_layout"]
    keys = list(map(str, indices))
    if not isinstance(entries, Mapping) or set(entries) != set(keys):
        raise ValueError("position_layout requires one string key per selected environment")
    centers = position_centers(env.cfg)
    active = {"stand"}
    if env.LOAD_CUP:
        active.add("cup")
    if env.LOAD_RACK:
        active.add("rack")
    allowed = {f"{name}_xy_m" for name in active} | {"stand_yaw_deg"}
    rows = []
    for key in keys:
        row = entries[key]
        if not isinstance(row, Mapping) or set(row) - allowed:
            raise ValueError(f"position_layout env {key}: unsupported position fields")
        try:
            item = {name: _xy(row.get(f"{name}_xy_m", base), base, name)
                    for name, base in centers.items()}
            yaw = row.get("stand_yaw_deg", STAND_YAW_DEG[1])
            if isinstance(yaw, bool) or not isinstance(yaw, Real) or yaw not in STAND_YAW_DEG:
                raise ValueError(f"stand_yaw_deg must be one of {STAND_YAW_DEG}")
            if env.LOAD_CUP and stand_dish_gap_m(item["stand"], item["cup"], yaw) < min_stand_dish_gap_m - 1e-9:
                raise ValueError("stand and sample dish do not clear the minimum gap")
            item["stand_yaw_deg"] = yaw
        except ValueError as exc:
            raise ValueError(f"position_layout env {key}: {exc}") from exc
        rows.append(item)
    return rows
