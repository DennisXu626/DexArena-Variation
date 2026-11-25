"""Independent, CPU-only tests for the Office workspace API and frozen maps."""

import importlib.util
from pathlib import Path
import unittest

import numpy as np


SRC = Path(__file__).resolve().parents[1] / "tasks/office_desk/position_workspace.py"
spec = importlib.util.spec_from_file_location("office_workspace", SRC)
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)


class OfficeWorkspaceTests(unittest.TestCase):
    def test_area_weighted_cells_are_disjoint_and_presets_are_members(self):
        for device in ("mouse", "laptop", "keyboard"):
            api = workspace.OfficeWorkspace(device, 2)
            for yaw, cells in api.table["cells"].items():
                for i, (x, y, size, routes) in enumerate(cells):
                    self.assertTrue(routes)
                    for other_x, other_y, other_size, _ in cells[i + 1 :]:
                        overlap_x = min(x + size, other_x + other_size) - max(x, other_x)
                        overlap_y = min(y + size, other_y + other_size) - max(y, other_y)
                        self.assertFalse(overlap_x > 1e-8 and overlap_y > 1e-8)
            for name in api.table["presets"]:
                xy, yaw = api.fixed(name)
                self.assertIsNotNone(workspace.cell_at(api.table, xy, yaw))
                self.assertEqual(
                    (xy, yaw), api.fixed({device + "_xy_m": xy, device + "_yaw_offset_deg": yaw})
                )

    def test_batches_are_atomic_and_layout_sequence_is_independent(self):
        api = workspace.OfficeWorkspace("mouse", 2)
        with self.assertRaises(ValueError):
            api.prepare([0, 1], 77, {"workspace_placement": {"0": "far", "1": "unknown"}})
        self.assertEqual(api.seeds, [0, 0])
        self.assertEqual(api.counts, [0, 0])
        options, initial = api.prepare([0, 1], 77, {})
        api.seeds, api.counts, api.episodes = initial
        _, fixed = api.prepare([1], None, {"workspace_placement": {"1": "near"}})
        self.assertEqual(fixed[1], initial[1])
        _, following = api.prepare([0], None, {})
        self.assertEqual(following[1], [2, 1])
        self.assertEqual(following[2][1], initial[2][1])
        self.assertEqual(api.prepare([1, 0], 77, {})[0], options)

    def test_invalid_numeric_and_conflicting_options(self):
        api = workspace.OfficeWorkspace("laptop", 1)
        for req in (
            {},
            {"laptop_xy_m": [np.nan, 0], "laptop_yaw_offset_deg": 0},
            {"laptop_xy_m": [0, 0], "laptop_yaw_offset_deg": False},
            {"laptop_xy_m": [3, 0], "laptop_yaw_offset_deg": 0},
        ):
            with self.assertRaises(ValueError):
                api.fixed(req)
        for option in ("reset_to_env_states", "position_layout"):
            with self.assertRaises(ValueError):
                api.prepare([0], None, {"workspace_placement": {"0": "far"}, option: {}})


if __name__ == "__main__":
    unittest.main()
