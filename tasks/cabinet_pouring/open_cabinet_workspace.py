"""Opt-in, world-frame root sampling for the left Sharpa OpenCabinet task."""
from functools import lru_cache
import json
from pathlib import Path

import numpy as np


@lru_cache(maxsize=1)
def workspace():
    spec = json.loads(Path(__file__).with_name("open_cabinet_cells.json").read_bytes())
    return ({int(yaw): np.asarray(rows, dtype=int) for yaw, rows in spec["rows_cm"].items()},
            spec["presets_cm"])


def contains(rows, xy):
    """Closed union of the screened 1 cm cells, including their exterior edges."""
    x, y = np.asarray(xy, dtype=float) * 100
    eps = 2e-6  # cm; accept the same decimal cell edge returned as a float32 pose
    return bool(np.any((rows[:, 0] - eps <= y) & (y <= rows[:, 0] + 1 + eps) &
                       (rows[:, 1] - eps <= x) & (x <= rows[:, 2] + eps)))


def resolve_workspace(env, indices, requests):
    """Draw only selected episode streams; fixed requests consume no random draws."""
    regions, presets = workspace()
    if requests is not None and (not isinstance(requests, dict) or
                                 set(requests) != {str(i) for i in indices}):
        raise ValueError("handle_placement needs one string key per selected env_idx")

    poses = []
    for i in indices:
        if requests is None:
            rng = env._batched_episode_rng[i]
            yaw = int(rng.choice((10, 15, 20)))
            rows = regions[yaw]
            cumulative = np.cumsum(rows[:, 2] - rows[:, 1])
            cell = int(rng.randint(int(cumulative[-1])))
            row = int(np.searchsorted(cumulative, cell, side="right"))
            y, left, _ = rows[row]
            x = left + cell - (cumulative[row - 1] if row else 0)
            xy = (np.array([x, y]) + rng.uniform(size=2)) / 100
        else:
            item = requests[str(i)]
            if isinstance(item, str) and item in presets:
                xy = np.asarray(presets[item], dtype=float) / 100
                yaw = 15
            elif isinstance(item, dict) and set(item) == {"cabinet_xy_m", "yaw_deg"}:
                xy = np.asarray(item["cabinet_xy_m"], dtype=float)
                yaw = item["yaw_deg"]
            else:
                raise ValueError(f"Invalid handle_placement for environment {i}: {item!r}")
            if (not isinstance(yaw, (float, int, np.number)) or yaw not in regions or
                    xy.shape != (2,) or not np.isfinite(xy).all() or not contains(regions[yaw], xy)):
                raise ValueError(f"Outside OpenCabinet handle workspace for environment {i}: {item!r}")
        poses.append([*xy, yaw])
    return np.asarray(poses, dtype=np.float32)
