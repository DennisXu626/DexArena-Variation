"""CPU regression for Package A5's live-target coverage; no simulator needed."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np
import torch


class FrankaJointImpedanceController:
    def __init__(self):
        self._target_qpos = torch.tensor([[0., 1.], [5., 6.]])

    def get_state(self):
        return {}


def load_checker_functions():
    # Execute the production functions without importing the GPU task registry.
    path = Path(__file__).resolve().parents[1] / 'tools/variation/check_ten_environment_paired.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'plain', 'diffs', 'numeric_equal', 'control_targets', 'compare_control_targets', 'row_state', 'sig'}
    module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    scope = dict(torch=torch, np=np, sapien=SimpleNamespace(Pose=type('Pose', (), {})),
                 FrankaJointImpedanceController=FrankaJointImpedanceController, FAMILY='package')
    exec(compile(module, str(path), 'exec'), scope)
    return scope


CHECK = load_checker_functions()


class ControlTargetCoverageTests(unittest.TestCase):
    def env(self, dual=False):
        arms = {'left_arm' if dual else 'arm': FrankaJointImpedanceController()}
        if dual:
            arms['right_arm'] = FrankaJointImpedanceController()
        self.arms = arms
        self.positions = torch.tensor([[2., 3.], [11., 12.]])
        self.velocities = torch.zeros(2, 2)
        robot = SimpleNamespace(get_drive_targets=lambda: self.positions,
                                get_drive_velocities=lambda: self.velocities)
        return SimpleNamespace(agent=SimpleNamespace(controller=SimpleNamespace(controllers=arms), robot=robot),
                               get_state_dict=lambda: {'articulations': {'robot': torch.tensor([[3.], [4.]])}})

    def cap(self, env):
        return {'state': [CHECK['row_state'](env, i) for i in range(2)],
                'control_targets': CHECK['control_targets'](env)}

    def test_unchanged_targets_pass(self):
        for dual in (False, True):
            env = self.env(dual)
            before = self.cap(env)
            for idx in (0, 1):
                self.assertEqual(CHECK['compare_control_targets'](before, self.cap(env), idx, 'A5'), [])
            self.assertEqual(len(before['control_targets'][0]['arm_impedance_qpos']), 2 if dual else 1)

    def test_each_unselected_target_mutation_is_detected(self):
        for selected in (0, 1):
            for target in ('left_arm', 'right_arm', 'positions', 'velocities'):
                with self.subTest(selected=selected, target=target):
                    env = self.env(dual=True)
                    before = self.cap(env)
                    other = 1 - selected
                    buffer = self.arms[target]._target_qpos if target in self.arms else getattr(self, target)
                    buffer[other, 0] += 4
                    after = self.cap(env)
                    self.assertEqual(before['state'], after['state'])
                    self.assertTrue(all(not arm.get_state() for arm in self.arms.values()))
                    CHECK['compare_control_targets'](before, after, selected, 'selected unchanged')
                    with self.assertRaises(AssertionError):
                        CHECK['compare_control_targets'](before, after, other, 'A5 other control targets')

    def test_missing_and_invalid_targets_fail_closed(self):
        for value in (None, torch.zeros(1, 2), torch.empty(2, 0), torch.full((2, 2), float('nan'))):
            env = self.env()
            self.arms['arm']._target_qpos = value
            with self.subTest(value=value), self.assertRaises(AssertionError):
                self.cap(env)
        env = self.env()
        env.agent.controller.controllers = {}
        with self.assertRaises(AssertionError):
            self.cap(env)
        for value in (torch.zeros(1, 2), torch.full((2, 2), float('inf'))):
            env = self.env()
            self.velocities = value
            with self.assertRaises(AssertionError):
                self.cap(env)

    def test_signature_includes_control_targets(self):
        scope = CHECK.copy()
        scope['store'] = lambda value: value
        # Rebind sig to the same production code with a transparent evidence store.
        from types import FunctionType
        sig = FunctionType(CHECK['sig'].__code__, scope)
        cap = {key: [] for key in ('state', 'control_targets', 'info', 'counters', 'materials', 'physics', 'rng', 'records')}
        self.assertIn('control_targets', sig(cap))


if __name__ == '__main__':
    unittest.main()
