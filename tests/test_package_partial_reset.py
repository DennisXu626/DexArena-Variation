"""Source-level public-reset regression; no physics scene or GPU is created."""
from __future__ import annotations
import ast
import gzip
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('b22', ROOT / 'tests/fixtures/package_b22_reset.py')
SDK = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SDK)


def noop(*args, **kwargs):
    pass


def load_class(path, name, methods, parent):
    cls = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef) and n.name == name)
    cls.decorator_list = []
    cls.bases = [ast.Name(id='Parent', ctx=ast.Load())]
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in methods
                or isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', None) in ('LOAD_APPLE', 'LOAD_PACKAGE', 'TARGET_STAGE')]
    scope = dict(globals(), Parent=parent, apply_arm_init_qpos=lambda agent, q: q,
                 arm_qpos_noise=lambda *args, **kwargs: ([0], torch.zeros(1, 1)), episode_rng=lambda *args: None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), 'exec'), scope)
    return scope[name]


FrankaJointImpedanceController = load_class(ROOT / 'tasks/robots/franka_joint_impedance_controller.py',
    'FrankaJointImpedanceController', ['reset', 'set_action'], SDK.BaseController)
pkg = ROOT / 'tasks/package_opening'
Long = load_class(pkg / 'package_opening_long.py', 'PackageOpeningLongEnv',
                  ['reset', 'get_info', '_initialize_episode', '_initialize_agent'], SDK.BaseEnv)
Sub = load_class(pkg / 'package_opening_long.py', 'PackageOpeningSubtaskEnv', ['_initialize_episode'], Long)
TASKS = {'long': Long, 'open': load_class(pkg / 'package_opening_open_package.py', 'PackageOpeningOpenPackageEnv', [], Sub),
         'extract': load_class(pkg / 'package_opening_extract_apple.py', 'PackageOpeningExtractAppleEnv', [], Sub)}

# Capture the real checker preparation and comparator, without importing SAPIEN.
scope = dict(globals(), sapien=NS(Pose=type('Pose', (), {})))
tree = ast.parse((ROOT / 'tools/variation/check_ten_environment_paired.py').read_text(encoding='utf-8'))
names = {'plain', 'diffs', 'numeric_equal', 'control_targets', 'compare_control_targets', 'prime_package_control_targets'}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), '<checker>', 'exec'), scope)


def build(stage, legacy=False):
    cls = TASKS[stage]
    if legacy:
        # Same task initialization, with the pre-fix inherited BaseEnv entry point.
        cls = type('Legacy', (cls,), {'reset': SDK.BaseEnv.reset, 'get_info': SDK.BaseEnv.get_info})
    e = cls()
    e.unwrapped = e
    e.num_envs, e.device, e.gpu_sim_enabled = 2, 'cpu', False
    e._enhanced_determinism = False
    e.reconfiguration_freq = e._reconfig_counter = 0
    e._set_main_rng = e._set_episode_rng = e._clear_sim_state = noop
    e._elapsed_steps = torch.tensor([3, 5])
    e.scene = NS(num_envs=2, _reset_mask=torch.ones(2, dtype=torch.bool), gpu_sim_enabled=False)
    e.scene_config = NS(initial_box_qpos=[0., 0.])
    e.table_scene = NS(initialize=noop)
    e._set_work_table_pose = e._randomize_layout = noop
    e.robot_init_qpos_noise, e._robot_base_pose = 0., None
    e.box = NS(max_dof=2, set_qpos=noop, set_qvel=noop)
    e.apple = NS(set_linear_velocity=noop, set_angular_velocity=noop)
    e.task_evaluator = NS(reset=noop, stage=torch.zeros(2, dtype=torch.int32))
    e.package_appearance = NS(finish_reset=noop)
    evidence = ROOT / 'docs/variation/evidence/package_opening/pr31_r1_g3' / stage
    report, sig = [json.loads(gzip.decompress((evidence / (k+'.json.gz')).read_bytes())) for k in ('report', 'signatures')]
    initial = sig[report['A5'][0]['before']['control_targets']][0]['arm_impedance_qpos']
    e.agent = SDK.BaseAgent()
    e.agent.device, e.agent.scene = 'cpu', e.scene
    combo = e.agent.controller = SDK.CombinedController()
    combo.scene = e.scene
    combo.controllers, combo.action_mapping = {}, {}
    e.arms = {}
    offset = 0
    for full_name, rest in initial.items():
        name = full_name.split('/')[-1]
        arm = FrankaJointImpedanceController()
        arm.qpos = torch.tensor([rest, rest])
        arm._target_qpos = arm.qpos.clone()
        arm.scene, arm.device = e.scene, 'cpu'
        arm.config = NS(stiffness=[1.]*7, force_limit=[40.]*7, normalize_action=False)
        arm._normalize_action = False
        arm.action_space = NS(shape=(2, 7))
        arm.single_action_space = NS(low=np.full(7, -3.), high=np.full(7, 3.))
        arm._apply_impedance_torque = noop
        combo.controllers[name] = e.arms[name] = arm
        combo.action_mapping[name] = (offset, offset+7); offset += 7
    # Real b22 hand PD methods, with explicit backend storage (not get_state()).
    e.drive_targets = torch.tensor([[.2, .3], [.4, .5]])
    e.drive_velocities = torch.tensor([[.01, .02], [.03, .04]])
    e.drive_writes = 0
    def set_drive(targets, joints, indices):
        e.drive_writes += 1
        e.drive_targets[:] = targets
    hand = SDK.PDJointPosController()
    hand.scene = e.scene
    hand.qpos = torch.zeros(2, 2)
    hand._normalize_action = False
    hand._target_qpos = hand._start_qpos = None
    hand.config = NS(use_delta=False, use_target=False, interpolate=False, normalize_action=False)
    hand.action_space = NS(shape=(2, 2))
    hand.single_action_space = NS(low=np.full(2, -1.), high=np.full(2, 1.))
    hand.joints, hand.active_joint_indices = [0, 1], [0, 1]
    hand.articulation = NS(set_joint_drive_targets=set_drive)
    combo.controllers['hand'] = hand
    combo.action_mapping['hand'] = (offset, offset+2)
    combo.action_space = NS(shape=(2, offset+2))
    def set_qpos(qpos):
        for arm in e.arms.values():
            arm.qpos[e.scene._reset_mask] = qpos
        hand.qpos[e.scene._reset_mask] = 0
    e.agent.get_reset_pos = lambda device: torch.tensor(next(iter(initial.values())))
    e.agent.robot = NS(max_dof=7, set_qpos=set_qpos, set_qvel=noop, set_qf=noop, set_root_pose=noop,
                       get_drive_targets=lambda: e.drive_targets, get_drive_velocities=lambda: e.drive_velocities)
    e.reads = []
    def observe(phase):
        value = scope['control_targets'](e)
        e.reads.append((phase, value))
        return value
    e.observe = observe
    e.get_obs = lambda info: observe('obs')
    scope['prime_package_control_targets'](e)
    return e


SDK.BaseEnv.get_info = lambda e: {'control_targets': e.observe('info')}


def witness(stage, selected, legacy=False):
    e = build(stage, legacy)
    before = scope['control_targets'](e)
    writes = e.drive_writes
    obs, info = e.reset(options={'env_idx': torch.tensor([selected])})
    after = scope['control_targets'](e)
    other = 1-selected
    isolated = before[other] == after[other]
    for phase, observed in e.reads:
        if not legacy:
            assert observed[other] == before[other], phase
    assert obs == after == info['control_targets']
    assert e.drive_writes == writes  # PD.reset did not write backend targets.
    assert before[other]['drive_targets'] == after[other]['drive_targets']
    assert before[other]['drive_velocities'] == after[other]['drive_velocities']
    for name, arm in e.arms.items():
        assert torch.equal(arm._target_qpos[selected], arm.qpos[selected])
    assert e._elapsed_steps[other].item() == [3, 5][other]
    assert not hasattr(e, '_package_partial_reset_restore')
    return {'task': stage, 'selected': selected, 'other': other, 'before': before, 'after': after,
            'info': info, 'obs': obs, 'other_step': int(e._elapsed_steps[other]), 'isolated': isolated}


class PublicPartialResetTests(unittest.TestCase):
    def test_old_implementation_fails_new_precondition_and_fixed_passes(self):
        for stage in TASKS:
            for selected in (0, 1):
                with self.subTest(stage=stage, selected=selected):
                    old = witness(stage, selected, legacy=True)
                    fixed = witness(stage, selected)
                    self.assertFalse(old['isolated'])
                    self.assertTrue(fixed['isolated'])
                    with self.assertRaises(AssertionError):
                        scope['compare_control_targets']({'control_targets': old['before']},
                            {'control_targets': old['after']}, 1-selected, 'A5 other control targets')
                    scope['compare_control_targets']({'control_targets': fixed['before']},
                        {'control_targets': fixed['after']}, 1-selected, 'A5 other control targets')
                    self.assertEqual(old['after'][selected], fixed['after'][selected])

    def test_command_precondition_rejects_noop_action_dispatch(self):
        e = build('open')
        for arm in e.arms.values():
            arm._target_qpos = arm.qpos.clone()
        e.agent.set_action = noop
        with self.assertRaises(AssertionError):
            scope['prime_package_control_targets'](e)

    def test_full_reset_preserves_original_behavior(self):
        for stage in TASKS:
            for options in (None, {'env_idx': torch.tensor([0, 1])}):
                fixed, legacy = build(stage), build(stage, legacy=True)
                a, b = fixed.reset(options=options), legacy.reset(options=options)
                self.assertEqual(a, b)
                for arm in fixed.arms.values():
                    self.assertTrue(torch.equal(arm._target_qpos, arm.qpos))
                self.assertFalse(hasattr(fixed, '_package_partial_reset_restore'))

    def test_exception_restores_targets_and_clears_guard(self):
        e = build('long')
        before = scope['control_targets'](e)
        e.get_obs = lambda info: (_ for _ in ()).throw(RuntimeError('observation failed'))
        with self.assertRaisesRegex(RuntimeError, 'observation failed'):
            e.reset(options={'env_idx': torch.tensor([0])})
        self.assertEqual(before[1], scope['control_targets'](e)[1])
        self.assertFalse(hasattr(e, '_package_partial_reset_restore'))


if __name__ == '__main__':
    import sys
    if '--evidence' in sys.argv:
        for legacy in (True, False):
            for stage in TASKS:
                for selected in (0, 1):
                    print(json.dumps(dict(implementation='legacy' if legacy else 'fixed', **witness(stage, selected, legacy))))
    else:
        unittest.main()
