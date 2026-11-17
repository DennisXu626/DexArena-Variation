"""Reject empty/stale image evidence in the furniture checker."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'furniture_validation', ROOT / 'tools/variation/check_furniture_appearance.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
CHECK.np = np


class ImageEvidenceTests(unittest.TestCase):
    def valid(self):
        frames = np.zeros((2, 2, 3, 3), dtype=np.uint8)
        frames[:, 1, 2] = [20, 30, 40]
        return {'base_camera': frames}

    def test_valid_batched_task_images(self):
        frames = self.valid()
        self.assertIs(CHECK.validate_images(frames, 2), frames)

    def test_solid_color_and_blank_images_rejected(self):
        for color in ([0, 0, 0], [255, 0, 0], [255, 255, 255]):
            with self.subTest(color=color), self.assertRaises(AssertionError):
                CHECK.validate_images({'base_camera': np.tile(np.uint8(color), (2, 2, 3, 1))}, 2)

    def test_wrong_shape_dtype_and_missing_task_cameras_rejected(self):
        frames = self.valid()['base_camera']
        for invalid in ({}, {'human': frames}, {'base_camera': frames[:1]},
                        {'base_camera': frames[..., :2]}, {'base_camera': frames.astype(float)},
                        {'base_camera': frames[:, :0]}):
            with self.subTest(shapes={k: v.shape for k, v in invalid.items()}), self.assertRaises(AssertionError):
                CHECK.validate_images(invalid, 2)

    def test_selected_pixel_changes_are_measured_independently(self):
        before = self.valid()
        after = {key: value.copy() for key, value in before.items()}
        after['base_camera'][1, 0, 0] = [3, 4, 5]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            unselected = CHECK.image_changes(before, after, output, 'local')
            selected = CHECK.image_changes(before, after, output, 'local', env_id=1)
            self.assertEqual(unselected['base_camera']['changed_values'], 0)
            self.assertEqual(selected['base_camera']['changed_values'], 3)
            self.assertEqual(selected['base_camera']['changed_pixels'], 1)
            filename = selected['base_camera']['coordinates']
            self.assertIn('env1', filename)
            with np.load(output / filename) as evidence:
                self.assertEqual(evidence['coordinates_yxc'].tolist(), [[0, 0, 0], [0, 0, 1], [0, 0, 2]])


if __name__ == '__main__':
    unittest.main()
