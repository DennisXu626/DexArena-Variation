"""Sample and replay measured Pipette workstations, in scene metres."""
from collections.abc import Mapping
from functools import lru_cache
import json
from numbers import Real
from pathlib import Path
from sys import float_info

import numpy as np


@lru_cache(maxsize=3)
def workspace(task):
    source = json.loads(Path(__file__).with_name('workspace_cells.json').read_bytes())
    group = source['tasks'][task]
    cells = {int(yaw): np.asarray(rows, dtype=np.int32) for yaw, rows in group['cells'].items()}
    return group['objects'], cells, group['presets'], source['half_mm'], source['version']


def public_row(objects, values, yaw):
    xy = np.asarray(values).reshape(len(objects), 2)
    return {'stand_yaw_deg': yaw, **{name + '_xy_m': point.tolist() for name, point in zip(objects, xy)}}


def resolve(task, item):
    objects, cells, presets, half, _ = workspace(task)
    if isinstance(item, str) and item in presets:
        return public_row(objects, np.asarray(presets[item]) / 1000, 90)
    fields = {'stand_yaw_deg', *(obj + '_xy_m' for obj in objects)}
    if not isinstance(item, Mapping) or set(item) != fields:
        raise ValueError('workspace_placement requires a known preset or all active placement fields')
    yaw = item['stand_yaw_deg']
    if isinstance(yaw, bool) or not isinstance(yaw, Real) or yaw not in cells:
        raise ValueError('unsupported workspace stand yaw')
    coords = []
    for name in objects:
        pair = item[name + '_xy_m']
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                any(isinstance(x, bool) or not isinstance(x, Real) or not -float_info.max <= x <= float_info.max for x in pair)):
            raise ValueError(f'workspace {name} requires two finite scene coordinates')
        coords.extend(map(float, pair))
    if not np.any(np.all(np.abs(cells[yaw] - np.asarray(coords) * 1000) <= half + 1e-5, axis=1)):
        raise ValueError('outside screened joint Pipette workspace')
    return public_row(objects, coords, int(yaw))


def sample(task, stream):
    objects, cells, _, half, _ = workspace(task)
    # Every box at one yaw has the same volume (also on the dual-arm rig).
    yaw = int(stream.choice(list(cells)))
    row = cells[yaw][stream.integers(len(cells[yaw]))]
    return public_row(objects, (row + stream.uniform(-half, half, size=len(row))) / 1000, yaw)
