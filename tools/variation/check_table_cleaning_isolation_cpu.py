"""CPU isolation regression using AST-loaded ManiSkill b22 and task methods.

Supply --mani-skill-wheel (3.0.0b22). Physics, contacts and poses are doubles;
reset, RNG, observation dispatch, impedance reset and PickDebris logic are real.
--revision 753b96e runs the same assertions against the unfixed source.
"""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Optional, Union
import unittest
import zipfile

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mani-skill-wheel', type=Path, required=True)
parser.add_argument('--revision')
parser.add_argument('--output', type=Path)
args = parser.parse_args()
wheel = zipfile.ZipFile(args.mani_skill_wheel)
records = []


def source(path):
    if args.revision:
        return subprocess.check_output(['git', 'show', f'{args.revision}:{path}'], cwd=ROOT).decode('utf-8')
    return (ROOT / path).read_text(encoding='utf-8')


def load_class(text, original, name, bases, methods, namespace):
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name == original)
    node.name, node.decorator_list = name, []
    node.bases = [ast.Name(id=b, ctx=ast.Load()) for b in bases]
    node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and (methods is None or n.name in methods)]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), original, 'exec'), namespace)
    return namespace[name]


def to_numpy(value, dtype=None):
    return np.asarray(value, dtype=dtype)


ns = dict(np=np, torch=torch, Union=Union, Optional=Optional, HOLD_STEPS=3, RandomState=np.random.RandomState,
          common=SimpleNamespace(to_numpy=to_numpy), tree=SimpleNamespace())
load_class(wheel.read('mani_skill/envs/utils/randomization/batched_rng.py').decode(),
           'BatchedRNG', 'BatchedRNG', ['RandomState'], None, ns)
Base = load_class(wheel.read('mani_skill/envs/sapien_env.py').decode(), 'BaseEnv', 'Base', [],
                  {'reset', 'get_info', 'get_obs', '_set_main_rng', '_set_episode_rng'}, ns)
Task = load_class(source('tasks/table_cleaning/table_cleaning_long.py'), 'TableCleanBase', 'Task', ['Base'],
                  {'reset', 'get_info', '_get_obs_extra', '_debris_in_pan', '_update_pick', '_latch', '_reset_buffers'}, ns)
Pick = load_class(source('tasks/table_cleaning/table_cleaning_pick_debris.py'),
                  'TableCleaningPickDebrisEnv', 'Pick', ['Task'], {'evaluate'}, ns)
ns['ControllerBase'] = type('ControllerBase', (), {'reset': lambda self: None})
Arm = load_class(source('tasks/robots/franka_joint_impedance_controller.py'),
                 'FrankaJointImpedanceController', 'Arm', ['ControllerBase'], {'reset'}, ns)


class Pose:
    def __init__(self, p):
        self.p = torch.tensor(p, dtype=torch.float32)
        self.raw_pose = torch.cat((self.p, torch.tensor([[1., 0, 0, 0]]).repeat(2, 1)), 1)

    def to_transformation_matrix(self):
        return torch.eye(4).repeat(2, 1, 1)


class Environment(Pick):
    FLAG_NAMES = ('f_picked', 'f_grasp_pan', 'f_poured', 'f_stow_pan')
    PAN_STATIC_STEP, PAN_FLOOR_BAND, STAGE_ONE_HOT_CLASSES = .003, .09, 2

    def __init__(self, appearance, deterministic):
        self.num_envs, self.device = 2, 'cpu'
        self.gpu_sim_enabled, self._enhanced_determinism = False, deterministic
        self._reconfig_counter, self.reconfiguration_freq = 1, 0
        self._obs_mode = 'state_dict'
        self.scene = SimpleNamespace(_reset_mask=torch.ones(2, dtype=torch.bool))
        self._elapsed_steps = torch.ones(2, dtype=torch.int32)
        self._main_seed = self._batched_episode_rng = None
        self._batched_rng_backend = 'numpy:random_state'
        self._set_main_rng(7)
        self._set_episode_rng(7, torch.arange(2))
        self.stage = torch.zeros(2, dtype=torch.long)
        self.hold = torch.zeros(2, dtype=torch.int32)
        for key in (*self.FLAG_NAMES, 'success_latched'):
            setattr(self, key, torch.zeros(2, dtype=torch.bool))
        self._pick_target = 3
        self.pan = SimpleNamespace(pose=Pose([[0., 0, 0]] * 2))
        self.bin = SimpleNamespace(pose=Pose([[1., 1, 1]] * 2))
        self.debris = [SimpleNamespace(pose=Pose([[.02, 0, .01]] * 2)) for _ in range(3)]
        self._pan_lo, self._pan_hi = [-.1, -.1, 0], [.1, .1, .05]
        self._debris_local_prev = [torch.tensor([[.01, 0, .01]] * 2) for _ in range(3)]
        arm = Arm()
        arm.qpos = torch.zeros(2, 7)
        arm.device = 'cpu'
        arm.config = SimpleNamespace(stiffness=[1.] * 7, force_limit=[1.] * 7)
        arm._target_qpos = torch.full((2, 7), .25)
        controller = SimpleNamespace(controllers={'arm': arm}, reset=arm.reset)
        self.agent = SimpleNamespace(controller=controller, reset=lambda: None,
                                     tcp=SimpleNamespace(pose=self.pan.pose))
        self.cleaning_appearance = None
        if appearance:
            # Actual selector/material paths have their own CPU suite. Here it
            # only participates in reset validation, without loading renderers.
            from check_table_cleaning_reset_cpu import adapter
            self.cleaning_appearance = adapter({})
        self.get_info()  # moving debris: stage remains zero, history advances

    @property
    def elapsed_steps(self):
        return self._elapsed_steps

    def _clear_sim_state(self):
        pass

    def _initialize_episode(self, env_idx, options):
        self._reset_buffers(env_idx)
        # Selected rows visibly initialize, with a fresh observation.
        for d in self.debris:
            d.pose.p[env_idx, 0] = .04
        if self.cleaning_appearance:
            self.cleaning_appearance.reset(env_idx.tolist(), options)

    def _debris_in_bin(self):
        return torch.zeros(2)

    def _any_debris_grasped(self):
        return torch.zeros(2, dtype=torch.bool)

    def _get_obs_state_dict(self, info):
        return {'extra': self._get_obs_extra(info),
                'target': self.agent.controller.controllers['arm']._target_qpos.clone()}

    def _flatten_raw_obs(self, obs):
        return obs


class IsolationTests(unittest.TestCase):
    def test_partial_reset(self):
        for appearance in (False, True):
            for selected in (0, 1):
                for deterministic in (False, True):
                    with self.subTest(appearance=appearance, selected=selected, deterministic=deterministic):
                        env = Environment(appearance, deterministic)
                        other = 1 - selected
                        before = [v[other].clone() for v in env._debris_local_prev]
                        rng = copy.deepcopy(env._batched_episode_rng[other]).randint(2**31)
                        main_rng = copy.deepcopy(env._batched_main_rng[other]).randint(2**31)
                        obs, info = env.reset(options={'env_idx': torch.tensor([selected])})
                        arm = env.agent.controller.controllers['arm']
                        records.append(dict(kind='unseeded_partial', appearance=appearance, selected=selected,
                            enhanced_determinism=deterministic, unselected_target=arm._target_qpos[other, 0].item(),
                            returned_stage=obs['extra']['stage_one_hot'][other].tolist(),
                            info_stage=info['stage'][other].item(), stored_stage=env.stage[other].item()))
                        torch.testing.assert_close(arm._target_qpos[other], torch.full((7,), .25))
                        torch.testing.assert_close(obs['target'][other], arm._target_qpos[other])
                        torch.testing.assert_close(arm._target_qpos[selected], torch.zeros(7))
                        self.assertEqual(obs['extra']['stage_one_hot'][other].tolist(), [1., 0.])
                        self.assertEqual(info['stage'][other].item(), 0)
                        self.assertEqual(env.stage[other].item(), 0)
                        self.assertEqual(obs['extra']['debris_pos'][selected, 0].item(), env.debris[0].pose.p[selected, 0].item())
                        for old, value in zip(before, env._debris_local_prev):
                            torch.testing.assert_close(value[other], old)
                        self.assertEqual(copy.deepcopy(env._batched_episode_rng[other]).randint(2**31), rng)
                        self.assertEqual(copy.deepcopy(env._batched_main_rng[other]).randint(2**31), main_rng)
                        self.assertFalse(hasattr(env, '_partial_reset_restore'))
                        env._elapsed_steps += 1  # next simulated time boundary
                        env.get_info()
                        self.assertEqual(env.stage[other].item(), 1)

    def test_seed_rejection_and_full_reset(self):
        for appearance in (False, True):
            for selected in (0, 1):
                with self.subTest(appearance=appearance, selected=selected):
                    env = Environment(appearance, True)
                    before = Environment(appearance, True)
                    rejected = False
                    try:
                        env.reset(seed=123, options={'env_idx': torch.tensor([selected])})
                    except ValueError as error:
                        self.assertRegex(str(error), 'partial reset.*seed')
                        rejected = True
                    other = 1 - selected
                    records.append(dict(kind='seeded_partial', appearance=appearance, selected=selected,
                        rejected=rejected, main_seed_before=int(before._main_seed[other]),
                        main_seed_after=int(env._main_seed[other]),
                        episode_next_before=int(copy.deepcopy(before._batched_episode_rng[other]).randint(2**31)),
                        episode_next_after=int(copy.deepcopy(env._batched_episode_rng[other]).randint(2**31))))
                    self.assertTrue(rejected, 'partial seed must be rejected before writes')
                    for key in ('_main_seed', '_episode_seed'):
                        np.testing.assert_array_equal(getattr(env, key), getattr(before, key))
                    for key in ('_batched_main_rng', '_batched_episode_rng'):
                        np.testing.assert_array_equal(getattr(env, key).randint(2**31), getattr(before, key).randint(2**31))
                    torch.testing.assert_close(env.stage, before.stage)
                    torch.testing.assert_close(env._elapsed_steps, before._elapsed_steps)
                    for a, b in zip(env._debris_local_prev, before._debris_local_prev):
                        torch.testing.assert_close(a, b)
                    if appearance:
                        self.assertEqual(env.cleaning_appearance.records, before.cleaning_appearance.records)
                    torch.testing.assert_close(env.agent.controller.controllers['arm']._target_qpos,
                                               before.agent.controller.controllers['arm']._target_qpos)
                    env.reset(seed=123)
                    self.assertEqual(env._main_seed[0], 123)
                    self.assertEqual(env._episode_seed[0], 123)

    def test_returned_stage_at_boundary(self):
        for appearance in (False, True):
            for selected in (0, 1):
                with self.subTest(appearance=appearance, selected=selected):
                    env = Environment(appearance, True)
                    obs, info = env.reset(options={'env_idx': torch.tensor([selected])})
                    other = 1 - selected
                    self.assertEqual(info['stage'][other].item(), env.stage[other].item())
                    self.assertEqual(obs['extra']['stage_one_hot'][other].tolist(), [1., 0.])

    def test_exception_cleanup(self):
        env = Environment(False, True)
        def fail():
            env.stage[:] = 1
            raise RuntimeError('evaluation failed')
        env.evaluate = fail
        with self.assertRaisesRegex(RuntimeError, 'evaluation failed'):
            env.reset(options={'env_idx': torch.tensor([1])})
        self.assertEqual(env.stage[0].item(), 0)
        torch.testing.assert_close(env.agent.controller.controllers['arm']._target_qpos[0], torch.full((7,), .25))
        self.assertFalse(hasattr(env, '_partial_reset_restore'))


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IsolationTests))
    if args.output:
        args.output.write_text(json.dumps({'passed': result.wasSuccessful(), 'revision': args.revision or 'working tree',
            'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'mani_skill_wheel': args.mani_skill_wheel.name,
            'reset_source_sha256': hashlib.sha256(source('tasks/table_cleaning/table_cleaning_long.py').encode()).hexdigest(),
            'cases': records,
            'scope': 'CPU Torch; AST-loaded ManiSkill 3.0.0b22 reset/RNG/observation and task methods; physics/contact doubles; no GPU'}, indent=2) + '\n')
    raise SystemExit(not result.wasSuccessful())
