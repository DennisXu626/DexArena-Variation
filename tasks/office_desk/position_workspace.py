"""Office task-specific, path-screened distributions for opt-in resets."""

import json
import math
from collections.abc import Mapping
from functools import lru_cache
from numbers import Integral, Real
from pathlib import Path

import numpy as np


@lru_cache(maxsize=3)
def workspace_table(device):
    path = Path(__file__).with_name("workspace_maps") / f"{device}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def cell_at(table, xy, yaw):
    """Test the closed union, retaining only decimal-edge float32 roundoff."""
    for cell in table["cells"].get(str(yaw), []):
        x, y = cell[:2]
        step = cell[2]
        if x - 2e-8 <= xy[0] <= x + step + 2e-8 and y - 2e-8 <= xy[1] <= y + step + 2e-8:
            return cell
    return None


class OfficeWorkspace:
    def __init__(self, device, num_envs):
        self.device = device
        self.table = workspace_table(device)
        self.cell_weights = {
            yaw: np.cumsum([cell[2] ** 2 for cell in cells])
            for yaw, cells in self.table["cells"].items()
        }
        self.seeds = [0] * num_envs
        self.counts = [0] * num_envs
        self.episodes = [None] * num_envs

    def fixed(self, request):
        if isinstance(request, str):
            try:
                x, y, yaw = self.table["presets"][request]
            except KeyError as exc:
                raise ValueError(f"Unknown {self.device} workspace preset {request!r}") from exc
            return (x, y), yaw
        xy_field = f"{self.device}_xy_m"
        yaw_field = f"{self.device}_yaw_offset_deg"
        if not isinstance(request, Mapping) or set(request) != {xy_field, yaw_field}:
            raise ValueError(f"Office workspace needs {xy_field} and {yaw_field}")
        xy, yaw = request[xy_field], request[yaw_field]
        if (
            not isinstance(xy, (tuple, list))
            or len(xy) != 2
            or any(isinstance(x, bool) or not isinstance(x, Real) or not math.isfinite(x) for x in xy)
            or isinstance(yaw, bool)
            or not isinstance(yaw, Real)
            or yaw not in self.table["yaw_deg"]
            or cell_at(self.table, xy, int(yaw)) is None
        ):
            raise ValueError(f"Outside screened {self.device} workspace")
        return tuple(map(float, xy)), int(yaw)

    def draw(self, seed, index, count):
        rng = np.random.default_rng(np.random.SeedSequence([int(seed), index, count, 0x4F4646]))
        yaw = int(rng.choice(self.table["yaw_deg"]))
        cells = self.table["cells"][str(yaw)]
        cumulative = self.cell_weights[str(yaw)]
        cell = int(np.searchsorted(cumulative, rng.random() * cumulative[-1], side="right"))
        x, y, step = cells[cell][:3]
        xy = np.asarray((x, y)) + step * rng.random(2)
        return tuple(map(float, xy)), yaw

    def prepare(self, selected, seed, options):
        """Build the entire request transactionally, committing only after native reset succeeds."""
        seeds = self.seeds.copy()
        counts = self.counts.copy()
        records = self.episodes.copy()
        if seed is not None:
            values = [seed] if isinstance(seed, Integral) else list(seed)
            if len(values) == 1:
                values *= len(seeds)
            if len(values) != len(seeds) or any(not isinstance(v, Integral) or v < 0 for v in values):
                raise ValueError(
                    "Workspace reseeding needs an integer or one non-negative integer per environment"
                )
            seeds, counts = list(map(int, values)), [0] * len(seeds)
        if "workspace_placement" in options:
            if "position_layout" in options or "reset_to_env_states" in options:
                raise ValueError(
                    "workspace_placement conflicts with position_layout or state restoration"
                )
            requests = options["workspace_placement"]
            if not isinstance(requests, Mapping) or set(requests) != set(map(str, selected)):
                raise ValueError("workspace_placement needs one string key per selected environment")
            fixed = {i: self.fixed(requests[str(i)]) for i in selected}
        else:
            fixed = None
        if "position_layout" in options or "reset_to_env_states" in options:
            for i in selected:
                records[i] = None
            return options, (seeds, counts, records)
        layout = {}
        for i in selected:
            xy, yaw = fixed[i] if fixed is not None else self.draw(seeds[i], i, counts[i])
            layout[str(i)] = (xy, math.radians(yaw))
            records[i] = dict(
                version=self.table["version"],
                seed=seeds[i],
                draw_index=counts[i],
                mode="fixed" if fixed is not None else "random",
                xy_m=xy,
                yaw_offset_deg=yaw,
            )
            if fixed is None:
                counts[i] += 1
        return {**options, "position_layout": layout}, (seeds, counts, records)
