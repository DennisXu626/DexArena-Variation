"""Screened Furniture placements. The offline table is native to this family."""
from collections.abc import Mapping
from functools import lru_cache
import json
import math
from numbers import Integral, Real
from sys import float_info
from pathlib import Path

import numpy as np
import torch

from .reset_scope import FurnitureResetScopeMixin


TABLE = Path(__file__).with_name("position_workspace.json")
ROLES = {"LayFlatPanel": ("rack",), "InsertRail": ("panel", "rail"), "FastenScrew": ("panel",)}


def rotate(xy, angle):
    radians = math.radians(angle)
    c, s = math.cos(radians), math.sin(radians)
    x, y = xy
    return np.array([c*x - s*y, s*x + c*y])


def world_layout(kind, angles, coordinates):
    """The free rail displacement is stored in the panel frame."""
    anchor = np.asarray(coordinates[:2])
    roles = ROLES[kind]
    result = {roles[0] + "_xy_m": anchor.tolist(), roles[0] + "_yaw_deg": angles[0]}
    if len(roles) == 2:
        result["rail_xy_m"] = (anchor + rotate(coordinates[2:], angles[0])).tolist()
        result["rail_yaw_deg"] = angles[1]
    return result


@lru_cache(maxsize=None)
def workspace(kind):
    raw = json.loads(TABLE.read_text(encoding="utf-8"))
    spec = raw["tasks"][kind]
    groups = []
    for group in spec["groups"]:
        centers = np.array(group["centers_m"])
        half = np.array(group["half_m"])
        groups.append((tuple(group["yaw_deg"]), centers, half))
    return raw["version"], groups, spec["presets"]


def draw(kind, rng):
    _, groups, _ = workspace(kind)
    angles, centers, half = groups[int(rng.integers(len(groups)))]
    # Cells within each yaw combination have equal volume and disjoint interiors.
    center = centers[int(rng.integers(len(centers)))]
    return world_layout(kind, angles, center + rng.uniform(-half, half))


def fixed_layout(kind, item):
    _, groups, presets = workspace(kind)
    if isinstance(item, str):
        if item not in presets:
            raise ValueError(f"unknown Furniture workspace preset {item!r}")
        item = presets[item]
    roles = ROLES[kind]
    keys = {role + suffix for role in roles for suffix in ("_xy_m", "_yaw_deg")}
    if not isinstance(item, Mapping) or set(item) != keys:
        raise ValueError("workspace_placement requires all and only task XY and yaw fields")
    for role in roles:
        xy, yaw = item[role + "_xy_m"], item[role + "_yaw_deg"]
        if not isinstance(xy, (tuple, list)) or len(xy) != 2 or any(
            isinstance(a, bool) or not isinstance(a, Real) or not -float_info.max <= a <= float_info.max for a in (*xy, yaw)
        ):
            raise ValueError("workspace_placement requires finite numeric coordinates and angles")
    angles = tuple(item[role + "_yaw_deg"] for role in roles)
    xy = np.array(item[roles[0] + "_xy_m"], dtype=float)
    if kind == "InsertRail":
        xy = np.r_[xy, rotate(np.array(item["rail_xy_m"]) - xy, -angles[0])]
    for layer, centers, half in groups:
        if angles == layer and np.any(np.all(np.abs(centers - xy) <= half + 2e-8, axis=1)):
            return world_layout(kind, angles, xy)
    raise ValueError("outside screened Furniture workspace")


class FurnitureWorkspaceMixin(FurnitureResetScopeMixin):
    """Limit workspace handling to the three Furniture short-task classes."""

    def __init__(self, *args, position_workspace=False, **kwargs):
        if not isinstance(position_workspace, bool):
            raise ValueError("position_workspace must be boolean")
        self.position_workspace = position_workspace
        self._placement = None
        self._workspace_zero_step = None
        self.workspace_records = {}
        self._workspace_stream = {}
        if position_workspace:
            side = "left" if self.WORKSPACE_TASK == "LayFlatPanel" else "right"
            if kwargs.get("robot_uids") != f"panda_sharpa_hand_{side}_angled_mobile_base":
                raise ValueError("Furniture position_workspace requires the registered Sharpa configuration")
            if not 0 <= self.robot_init_qpos_noise <= .01:
                raise ValueError("screened Furniture arm initialization noise is 0 to 0.01 rad")
            if getattr(self, "place_random_x", 0) or getattr(self, "place_random_y", 0):
                raise ValueError("Furniture position_workspace requires the fixed native handoff region")
        super().__init__(*args, **kwargs)

    def reset(self, seed=None, options=None):
        options = options or {}
        has_request = "workspace_placement" in options
        if has_request and (not self.position_workspace or "position_layout" in options
                            or "reset_to_env_states" in options):
            raise ValueError("workspace_placement requires position_workspace and one placement source")
        if not self.position_workspace:
            return super().reset(seed=seed, options=options)
        indices = options.get("env_idx", list(range(self.num_envs)))
        if hasattr(indices, "tolist"):
            indices = indices.tolist()
        if (not isinstance(indices, (tuple, list, range)) or not indices
                or any(isinstance(i, bool) or not isinstance(i, Integral)
                       or not 0 <= i < self.num_envs for i in indices)
                or len(set(indices)) != len(indices)):
            raise ValueError("invalid Furniture workspace environment indices")
        indices = sorted(indices)
        replay = "position_layout" in options or "reset_to_env_states" in options
        full = len(indices) == self.num_envs
        if not full and seed is not None and not replay:
            raise ValueError("only full resets may re-seed the Furniture workspace")
        if "env_idx" in options and not replay:
            options = {**options, "env_idx": torch.as_tensor(indices, device=self.device)}
        kind = self.WORKSPACE_TASK
        fixed = {}
        if has_request:
            requests = options["workspace_placement"]
            if not isinstance(requests, Mapping) or set(requests) != {str(i) for i in indices}:
                raise ValueError("workspace_placement needs one string key per selected environment")
            fixed = {i: fixed_layout(kind, requests[str(i)]) for i in indices}
        stream = dict(self._workspace_stream)
        if (full and seed is not None) or not stream:
            seeds = np.atleast_1d(seed) if seed is not None else [int(np.random.SeedSequence().entropy)]
            if len(seeds) not in (1, self.num_envs):
                raise ValueError("supply one seed or one per environment")
            stream = {i: (int(seeds[0 if len(seeds) == 1 else i]), 0) for i in range(self.num_envs)}
        records = {}
        if not replay:
            for i in indices:
                base, count = stream[i]
                if has_request:
                    layout = fixed[i]
                else:
                    rng = np.random.default_rng(np.random.SeedSequence([base, i, count, 0x4655524e]))
                    layout = draw(kind, rng)
                    stream[i] = base, count + 1
                records[i] = dict(version=workspace(kind)[0], seed=base, draw_index=count,
                                  mode="fixed" if has_request else "random", layout=layout)
            self._placement = {i: {role: [*r["layout"][role+"_xy_m"], math.radians(r["layout"][role+"_yaw_deg"])]
                                   for role in ROLES[kind]} for i, r in records.items()}
        previous_mask = self._workspace_zero_step
        mask = (previous_mask.clone() if previous_mask is not None
                else torch.zeros(self.num_envs, dtype=torch.bool, device=self.device))
        mask[indices] = bool(records)
        self._workspace_zero_step = mask
        try:
            result = super().reset(seed=seed, options=options)
        except BaseException:
            self._workspace_zero_step = previous_mask
            raise
        finally:
            self._placement = None
        self._workspace_stream = stream
        for i in indices:
            if i in records:
                self.workspace_records[i] = records[i]
            else:
                self.workspace_records.pop(i, None)
        return result

    def _resolved_furniture_rows(self, env_idx):
        if self._placement is not None:
            return [self._placement[i] for i in env_idx.tolist()]
        return getattr(self, "_furniture_position_rows", None)

    def _workspace_contact_counts(self, counts):
        # PhysX contact forces are from the last physical step. None has occurred
        # at the newly selected initial poses, even if the preceding episode grasped.
        if self._workspace_zero_step is None:
            return counts
        return counts.masked_fill(self._workspace_zero_step & (self._elapsed_steps == 0), 0)
