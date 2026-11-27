"""CPU reset/control regression using frozen b22 methods and real Meal wrappers.

Scene/appearance I/O and evaluation/observation callbacks are test doubles.
This checks call ordering and active targets, not PhysX, rendering or success.
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('meal_b22', ROOT / 'tests/fixtures/package_b22_reset.py')
SDK = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SDK)


def noop(*args, **kwargs):
    pass


class CallbackEnv(SDK.BaseEnv):
    def get_info(self):
        return self.evaluate()

    def evaluate(self):
        self.record('evaluate_entry')
        self.record('evaluate_exit')
        if self.fail_at == 'evaluate':
            raise RuntimeError('evaluate failed')
        return {}

    def get_obs(self, info):
        self.record('get_obs_entry')
        self.record('get_obs_exit')
        if self.fail_at == 'get_obs':
            raise RuntimeError('get_obs failed')
        return self.snapshot()


def load_classes(path, scope, methods):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        node.decorator_list = []
        node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in methods.get(node.name, ())] or [ast.Pass()]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), scope)


# Extract production methods without importing SAPIEN or loading robot assets.
scope = dict(globals(), BaseEnv=CallbackEnv, BaseController=SDK.BaseController)
robot = ast.parse((ROOT / 'tasks/robots/franka_joint_impedance_controller.py').read_text(encoding='utf-8'))
node = next(n for n in robot.body if isinstance(n, ast.ClassDef) and n.name == 'FrankaJointImpedanceController')
node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in ('reset', 'set_action')]
exec(compile(ast.Module(body=[node], type_ignores=[]), '<production Franka controller>', 'exec'), scope)
Franka = scope['FrankaJointImpedanceController']
meal = ROOT / 'tasks/meal_preparation'
load_classes(meal / 'meal_preparation_long.py', scope,
             {'MealPreparationBase': ('reset', 'get_info', '_initialize_episode')})
for filename in ('meal_preparation_open_lunch_box.py', 'meal_preparation_place_bread.py', 'meal_preparation_scoop_tomato.py'):
    load_classes(meal / filename, scope, {})
TASKS = {key: scope[name] for key, name in (
    ('open', 'MealPreparationOpenLunchBoxEnv'), ('bread', 'MealPreparationPlaceBreadEnv'),
    ('tomato', 'MealPreparationScoopTomatoEnv'), ('long', 'MealPreparationLongEnv'))}


def build(stage='open', legacy=False, appearance=True, dictionary=False):
    cls = TASKS[stage]
    if legacy:
        cls = type('Legacy', (cls,), {'reset': SDK.BaseEnv.reset, 'get_info': CallbackEnv.get_info})
    e = cls()
    e.num_envs, e.device, e.gpu_sim_enabled = 2, 'cpu', False
    e._enhanced_determinism = False
    e.reconfiguration_freq = e._reconfig_counter = 0
    e._set_main_rng = e._set_episode_rng = e._clear_sim_state = noop
    e._elapsed_steps = torch.tensor([3, 5])
    e.scene = NS(num_envs=2, _reset_mask=torch.ones(2, dtype=torch.bool), gpu_sim_enabled=False)
    e.agent = SDK.BaseAgent()
    e.agent.device, e.agent.scene = 'cpu', e.scene
    combo = SDK.CombinedController()
    combo.scene = e.scene
    combo.controllers, combo.action_mapping = {}, {}
    e.arms = {}
    for index, name in enumerate(('left', 'right')):
        arm = Franka()
        arm.scene, arm.device = e.scene, 'cpu'
        arm.qpos = torch.full((2, 7), -0.5)
        arm._target_qpos = arm.qpos.clone()
        arm.config = NS(stiffness=[1.] * 7, force_limit=[40.] * 7)
        arm._normalize_action = False
        arm.action_space = NS(shape=(2, 7))
        arm._apply_impedance_torque = noop
        combo.controllers[name] = e.arms[name] = arm
        combo.action_mapping[name] = (index * 7, (index + 1) * 7)
    combo.action_space = NS(shape=(2, 14))
    e.agent.controller = combo
    # Send real action methods targets different from each other AND qpos.
    action = torch.full((2, 14), -0.5)
    action[:, 0] = torch.tensor([-0.375, -0.625])
    action[:, 7] = torch.tensor([-0.25, -0.75])
    e.agent.set_action(action)
    if dictionary:
        e.agent.controller = {'robot': combo}
    def set_qpos(qpos):
        for arm in e.arms.values():
            arm.qpos[e.scene._reset_mask] = qpos
    e.agent.robot = NS(max_dof=7, set_qpos=set_qpos, set_qvel=noop, set_qf=noop)
    e._initialize_agent = lambda indices: e.agent.reset(torch.full((len(indices), 7), -0.5))
    e.lock_box_lid_until_opening = False
    e._configure_box_lid_drives = e._initialize_actors = e._set_lock_bodies_kinematic = noop
    e.appearance_records = ['variant_1', 'variant_9']
    def finish(indices, options):
        for idx in indices.tolist():
            e.appearance_records[idx] = options.get('meal_appearance', {}).get('variant', 'original')
    e.meal_appearance = NS(finish_reset=finish) if appearance else None
    e.reads, e.fail_at = [], None
    e.snapshot = lambda: {name: arm._target_qpos.tolist() for name, arm in e.arms.items()}
    e.record = lambda phase: e.reads.append({'phase': phase, 'targets': e.snapshot()})
    return e


def witness(stage, selected, legacy=False, **kwargs):
    e = build(stage, legacy, **kwargs)
    before = e.snapshot()
    obs, info = e.reset(options={'env_idx': torch.tensor([selected]), 'meal_appearance': {'variant': 'original'}})
    e.record('return')
    return {'task': stage, 'selected': selected, 'unselected': 1-selected,
            'implementation': 'legacy' if legacy else 'fixed', 'before': before,
            'callbacks_and_return': e.reads, 'after': e.snapshot(),
            'appearance_records_double': e.appearance_records}, e


class MealPartialResetTests(unittest.TestCase):
    def assert_isolated(self, result):
        other = result['unselected']
        for read in result['callbacks_and_return']:
            for name, before in result['before'].items():
                self.assertEqual(read['targets'][name][other], before[other], read['phase'])

    def test_eight_directions_detect_legacy_failure_and_preserve_fixed_targets(self):
        for stage in TASKS:
            for selected in (0, 1):
                with self.subTest(stage=stage, selected=selected):
                    old, _ = witness(stage, selected, legacy=True)
                    with self.assertRaises(AssertionError):
                        self.assert_isolated(old)
                    fixed, e = witness(stage, selected)
                    self.assert_isolated(fixed)
                    self.assertEqual([r['phase'] for r in fixed['callbacks_and_return']],
                                     ['evaluate_entry', 'evaluate_exit', 'get_obs_entry', 'get_obs_exit', 'return'])
                    for name, arm in e.arms.items():
                        self.assertEqual(fixed['after'][name][selected], arm.qpos[selected].tolist())
                        self.assertEqual(fixed['after'][name][selected], old['after'][name][selected])
                    self.assertEqual(e.appearance_records[selected], 'original')
                    self.assertEqual(e.appearance_records[1-selected], ['variant_1', 'variant_9'][1-selected])
                    self.assertEqual(e._elapsed_steps.tolist()[1-selected], [3, 5][1-selected])
                    self.assertFalse(hasattr(e, '_meal_partial_reset_restore'))

    def test_full_reset_matches_native_behavior(self):
        for stage in TASKS:
            for options in (None, {'env_idx': torch.tensor([0, 1])}):
                with self.subTest(stage=stage, options=options):
                    fixed, old = build(stage), build(stage, legacy=True)
                    self.assertEqual(fixed.reset(options=options), old.reset(options=options))
                    for arm in fixed.arms.values():
                        self.assertTrue(torch.equal(arm._target_qpos, arm.qpos))
                    self.assertFalse(hasattr(fixed, '_meal_partial_reset_restore'))

    def test_without_appearance_and_nested_controller_dictionary(self):
        for appearance, dictionary in ((False, False), (True, True)):
            for selected in (0, 1):
                result, _ = witness('long', selected, appearance=appearance, dictionary=dictionary)
                self.assert_isolated(result)

    def test_exception_cleanup_before_and_during_callbacks(self):
        for phase in ('initialize', 'evaluate', 'get_obs'):
            e = build()
            before = e.snapshot()
            e.fail_at = phase
            if phase == 'initialize':
                def fail(*args):
                    for arm in e.arms.values():
                        arm._target_qpos.fill_(0)
                    raise RuntimeError('initialize failed')
                e._initialize_agent = fail
            with self.assertRaisesRegex(RuntimeError, phase + ' failed'):
                e.reset(options={'env_idx': torch.tensor([0])})
            for name, value in before.items():
                self.assertEqual(e.snapshot()[name][1], value[1])
            self.assertFalse(hasattr(e, '_meal_partial_reset_restore'))

    def test_uninitialized_controller_target(self):
        e = build()
        for arm in e.arms.values():
            arm._target_qpos = None
        e.reset(options={'env_idx': torch.tensor([0])})
        for arm in e.arms.values():
            self.assertTrue(torch.equal(arm._target_qpos, arm.qpos))
        self.assertFalse(hasattr(e, '_meal_partial_reset_restore'))


if __name__ == '__main__':
    import sys
    if '--evidence' in sys.argv:
        print(json.dumps({'scope': 'CPU source-level harness; scene and callbacks are doubles',
                          'sdk_source_hashes': SDK.SDK_SOURCE_HASHES,
                          'cases': [witness(stage, selected, legacy)[0]
                                    for legacy in (True, False) for stage in TASKS for selected in (0, 1)]}, indent=2))
    else:
        unittest.main()
