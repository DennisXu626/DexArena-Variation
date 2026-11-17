"""Reject empty/stale image evidence in the furniture checker."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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


class StaticBaselineTests(unittest.TestCase):
    def test_committed_scoped_baseline_is_supported(self):
        self.assertEqual(CHECK.static_check('HEAD')['status'], 'passed')

    def test_native_baseline_is_supported(self):
        baseline = '435f835038d22cfe21b452681747cf3d85d6a67c'
        try:
            CHECK.git('cat-file', '-e', baseline + '^{commit}')
        except subprocess.CalledProcessError:
            self.skipTest('Native baseline is absent from this checkout')
        self.assertEqual(CHECK.static_check(baseline)['status'], 'passed')

    def test_scope_normalization_does_not_hide_judgment_changes(self):
        git = CHECK.git

        def changed_baseline(*arguments):
            if arguments[0] != 'show' or not arguments[1].startswith('fixture:'):
                return git(*arguments)
            filename = arguments[1].split(':', 1)[1]
            text = git('show', 'HEAD:' + filename)
            if filename == CHECK.TASKS['LayFlatPanel']:
                tree = ast.parse(text)
                evaluate = next(node for node in ast.walk(tree)
                                if isinstance(node, ast.FunctionDef) and node.name == 'evaluate')
                comparison = next(node for node in ast.walk(evaluate)
                                  if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.GtE))
                comparison.ops[0] = ast.Gt()
                text = ast.unparse(tree)
            return text

        with patch.object(CHECK, 'git', side_effect=changed_baseline), self.assertRaisesRegex(
                AssertionError, 'task judgment/reward AST changed'):
            CHECK.static_check('fixture')


if __name__ == '__main__':
    unittest.main()
