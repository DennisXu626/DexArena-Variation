"""CPU regression for PR30/31 shared row-state conflict resolution."""
import ast
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
CHECKERS = ('check_ten_environment.py', 'check_ten_environment_paired.py')


def load(source, family):
    tree = ast.parse(source)
    namespace = dict(FAMILY=family, torch=torch, np=np,
                     sapien=SimpleNamespace(Pose=type('Pose', (), {})))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('plain', 'row_state')]
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<actual checker functions>', 'exec'), namespace)
    return namespace['row_state']


class SharedRowStateTests(unittest.TestCase):
    def state(self):
        return {'articulations': {
            'robot': torch.tensor([[10., 11.], [20., 21.]]),
            'box_0': torch.tensor([[100.]]), 'box_1': torch.tensor([[200.]]),
            'procedural_box_0': torch.tensor([[1.]]), 'procedural_box_1': torch.tensor([[2.]]),
            'partnet_box_0': torch.tensor([[3.]]), 'partnet_box_1': torch.tensor([[4.]]),
            'package_0': torch.tensor([[5.]]), 'package_1': torch.tensor([[6.]])},
            'metadata': {'global': 7, 'stage': torch.tensor([0, 1])}}

    def test_package_filters_other_environment_in_both_directions(self):
        for filename in CHECKERS:
            row_state = load((ROOT / 'tools/variation' / filename).read_text(encoding='utf-8'), 'package')
            state = self.state()
            for idx in (0, 1):
                with self.subTest(checker=filename, env=idx):
                    row = row_state(SimpleNamespace(get_state_dict=lambda: state), idx)
                    self.assertEqual(set(row['articulations']), {'robot', *(f'{prefix}_{idx}' for prefix in ('box', 'procedural_box', 'partnet_box', 'package'))})
                    self.assertEqual(row['articulations']['robot'], [10.+idx*10, 11.+idx*10])
                    self.assertEqual(row['metadata'], {'global': 7, 'stage': idx})

    def test_meal_matches_original_pr30_and_preserves_unprefixed_keys(self):
        for filename in CHECKERS:
            current = load((ROOT / 'tools/variation' / filename).read_text(encoding='utf-8'), 'meal')
            original = load(subprocess.check_output(['git', 'show', '049bca9:tools/variation/'+filename], cwd=ROOT).decode(), 'meal')
            state = self.state()
            env = SimpleNamespace(get_state_dict=lambda: state)
            for idx in (0, 1):
                with self.subTest(checker=filename, env=idx):
                    row = current(env, idx)
                    self.assertEqual(row, original(env, idx))
                    self.assertTrue({'box_0', 'box_1'} <= row['articulations'].keys())
                    self.assertIn(f'procedural_box_{idx}', row['articulations'])
                    self.assertNotIn(f'procedural_box_{1-idx}', row['articulations'])
                    state['articulations']['robot'][idx, 0] += 1
                    self.assertNotEqual(row['articulations']['robot'], current(env, idx)['articulations']['robot'])


if __name__ == '__main__':
    unittest.main()
