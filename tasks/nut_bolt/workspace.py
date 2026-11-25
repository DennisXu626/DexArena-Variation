"""Nut & Bolt joint placement domains compiled from the native Sharpa scene."""

from collections.abc import Mapping
from functools import lru_cache
import json
from math import isfinite, radians
from numbers import Real
from pathlib import Path

import numpy as np

from .position_layout import FIELDS


@lru_cache(maxsize=1)
def _catalog():
    return json.loads(Path(__file__).with_name("workspace_cells.json").read_text(encoding="utf-8"))


class NutWorkspace:
    def __init__(self, task, num_envs):
        catalog = _catalog()
        self.version = catalog["version"]
        self.task = task
        spec = catalog["tasks"][task]
        self.size = np.array(spec["cell_size_mm"])
        self.cells = {int(yaw): np.array(rows)[:, :-1] for yaw, rows in spec["cells"].items()}
        self.presets = spec["presets"]
        self.seeds = [2022 + i for i in range(num_envs)]
        self.counts = [0] * num_envs
        self.records = [None] * num_envs

    def row(self, yaw, point):
        xy = np.asarray(point, dtype=float) / 1000
        if self.task == "PickBolt":
            return {"bolt_spawn_xy_m": xy.tolist(), "bolt_spawn_yaw_deg": yaw}
        if self.task == "TurnNut":
            return {"upright_bolt_xy_m": xy.tolist(), "threaded_nut_relative_yaw_deg": yaw}
        return {"upright_bolt_xy_m": xy[:2].tolist(), "table_nut_xy_m": (xy[:2] + xy[2:]).tolist()}

    def sample(self, rng):
        # Compile-time cells have equal volume within a task. Each cell
        # appears once, even when several grasp routes passed.
        yaw = int(rng.choice(list(self.cells)))
        cells = self.cells[yaw]
        point = cells[rng.integers(len(cells))] + rng.random(len(self.size)) * self.size
        return self.row(yaw, point)

    def resolve(self, request):
        if isinstance(request, str) and request in self.presets:
            yaw, *point = self.presets[request]
            return self.row(yaw, point)
        if not isinstance(request, Mapping) or set(request) != FIELDS[self.task]:
            raise ValueError(f"{self.task} workspace_placement needs a named preset or all task fields")
        row = {}
        for name, value in request.items():
            values = value if name.endswith("xy_m") else [value]
            try:
                valid = (
                    isinstance(values, (list, tuple))
                    and len(values) == (2 if name.endswith("xy_m") else 1)
                    and all(not isinstance(v, bool) and isinstance(v, Real) and isfinite(v) for v in values)
                )
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError(f"invalid workspace field {name}")
            row[name] = list(map(float, values)) if name.endswith("xy_m") else float(values[0])
        if self.task == "PickBolt":
            yaw, point = row["bolt_spawn_yaw_deg"], row["bolt_spawn_xy_m"]
        elif self.task == "TurnNut":
            yaw, point = row["threaded_nut_relative_yaw_deg"], row["upright_bolt_xy_m"]
        else:
            anchor = row["upright_bolt_xy_m"]
            yaw, point = 0, [*anchor, *np.subtract(row["table_nut_xy_m"], anchor)]
        points = np.array(point) * 1000
        cells = self.cells.get(yaw)
        # Float32 scene poses round a decimal cell edge by a few nanometres.
        eps_mm = 2e-5
        if cells is None or not np.any(
            np.all((cells - eps_mm <= points) & (points <= cells + self.size + eps_mm), axis=1)
        ):
            raise ValueError(f"outside {self.task} workspace")
        return row

    def prepare(self, options, selected, seed):
        """Validate the whole batch, then stage copies for commit after reset."""
        raw = options.get("workspace_placement")
        if "workspace_placement" in options:
            if "position_layout" in options or "reset_to_env_states" in options:
                raise ValueError(
                    "workspace_placement conflicts with another explicit layout or state restoration"
                )
            if not isinstance(raw, Mapping) or set(raw) != {str(i) for i in selected}:
                raise ValueError("workspace_placement requires one string key per selected environment")
            fixed = {i: self.resolve(raw[str(i)]) for i in selected}
        else:
            fixed = None
        seeds, counts, records = self.seeds.copy(), self.counts.copy(), self.records.copy()
        if seed is not None:
            seeds = np.asarray(seed).reshape(-1).tolist()
            if len(seeds) == 1:
                seeds *= len(counts)
            if len(seeds) != len(counts):
                raise ValueError("full reset needs one seed or one seed per environment")
            counts = [0] * len(seeds)
        mode = (
            "restore"
            if "reset_to_env_states" in options
            else "explicit" if "position_layout" in options else "fixed" if fixed is not None else "sample"
        )
        columns = {key: [] for key in FIELDS[self.task]} if mode in ("fixed", "sample") else None
        for i in selected:
            record = {
                "version": self.version,
                "env_idx": i,
                "seed": seeds[i],
                "draw_index": counts[i],
                "mode": mode,
            }
            if columns is not None:
                if fixed is None:
                    rng = np.random.default_rng(np.random.SeedSequence([seeds[i], i, counts[i], 4501]))
                    row = self.sample(rng)
                    counts[i] += 1
                else:
                    row = fixed[i]
                record["layout"] = row
                for key, val in row.items():
                    columns[key].append(radians(val) if key.endswith("_deg") else val)
            records[i] = record
        return columns, (seeds, counts, records)
