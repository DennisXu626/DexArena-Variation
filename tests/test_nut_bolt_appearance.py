"""CPU contracts; no task import, simulator or renderer."""
import ast
import copy
import importlib.util
import pickle
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARENT = load('furniture_appearance_cpu', 'tasks/furniture_assembly/appearance.py')
with patch.dict(sys.modules, {'tasks.furniture_assembly.appearance': PARENT}):
    MODULE = load('nut_bolt_appearance_cpu', 'tasks/nut_bolt/appearance.py')


def adapter(config=None):
    value = MODULE.NutBoltAppearance({'enabled': True, **(config or {})}, 2)
    for env_id in range(2):
        rows = []
        for oid, role in [('bolt', 'shaft'), ('bolt', 'head'), ('bolt', 'tip'),
                          ('bolt', 'thread'), ('nut', 'body'), ('nut', 'reference_face'),
                          ('nut', 'body'), ('nut', 'reference_face')]:
            captured = dict(base_color=[.1 + env_id / 10, .2, .3, 1.], roughness=.73, metallic=.17)
            material = SimpleNamespace(**copy.deepcopy(captured), specular=.29)
            rows.append((oid, role, SimpleNamespace(material=material), material, captured))
        value.bindings[env_id] = rows
    return value


def reset(value, indices, config=None):
    value.finish_reset(np.asarray(indices), {'nut_bolt_appearance': config or {}})


def state(value):
    return {'pbr': [[(oid, role, {key: copy.deepcopy(getattr(material, key)) for key in MODULE.FIELDS})
                     for oid, role, _, material, _ in rows] for rows in value.bindings],
            'rng': [copy.deepcopy(rng.bit_generator.state) for rng in value.rng],
            'schemes': value.schemes.copy(), 'episodes': value.episodes.copy(),
            'records': copy.deepcopy(value.records)}


class NativeResetSpy:
    def __init__(self):
        self.num_envs = 2
        self.device = 'cpu'
        self.scene = None
        self._reconfig_counter = 0
        self.reconfiguration_freq = 0
        self.gpu_sim_enabled = False
        self.rng = np.random.RandomState(71)
        self.native_state = np.array([[1., 2.], [3., 4.]])
        self.records = [{'env_idx': 0, 'episode_index': 1}]
        self._nut_bolt_appearance = adapter({'mode': 'random_choice', 'scheme_ids': ['original', 'variant_1']})
        self.calls = []
        self.effects = []
        self.run_episode = False

    def reset(self, seed=None, options=None):
        self.calls.append((seed, options))
        if seed is not None:
            self.rng = np.random.RandomState(seed)
        self.effects.append('task_rng')
        self.native_state = self.rng.uniform(size=(2, 2))
        self.effects.append('state_write')
        self.records.append({'native_reset': True})
        if self.run_episode:
            options = options or {}
            if 'reset_to_env_states' not in options:
                self._initialize_episode(options.get('env_idx', torch.arange(self.num_envs)), options)
        return self.native_state.copy()

    def _write_task_state(self, *args, **kwargs):
        self.effects.append('task_state_write')

    _reset_episode_buffers = _write_task_state
    _initialize_workspace = _write_task_state
    _place_bolt = _write_task_state
    _place_nut_on_table = _write_task_state
    _place_nut_on_platform = _write_task_state
    _update_platform_pose = _write_task_state

    def _refresh_hold_state(self):
        self.effects.append('lock_write')


with patch.dict(sys.modules, {'sapien': SimpleNamespace()}):
    PARENT_SCOPE = load('furniture_reset_scope_cpu', 'tasks/furniture_assembly/reset_scope.py')
with patch.dict(sys.modules, {'tasks.furniture_assembly.reset_scope': PARENT_SCOPE,
                              'tasks.nut_bolt.appearance': MODULE}):
    RESET_MODULE = load('nut_bolt_reset_scope_cpu', 'tasks/nut_bolt/reset_scope.py')


class ResetHarness(RESET_MODULE.NutBoltResetScopeMixin, NativeResetSpy):
    pass


def load_reset_task(file_name, method, namespace):
    source = ROOT / f'tasks/nut_bolt/nut_bolt_{file_name}.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    task, = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    task.decorator_list = []
    task.body = [node for node in task.body if isinstance(node, ast.FunctionDef) and node.name == method]
    assert len(task.body) == 1
    env = {'torch': torch, **namespace}
    exec(compile(ast.Module(body=[task], type_ignores=[]), str(source), 'exec'), env)
    return env[task.name]


LONG_TASK = load_reset_task('long', '_finish_appearance_reset', {
    'NutBoltResetScopeMixin': RESET_MODULE.NutBoltResetScopeMixin, 'BaseEnv': NativeResetSpy,
})
SHORT_TASKS = {name: load_reset_task(name, '_initialize_episode', {'NutBoltLongEnv': LONG_TASK})
               for name in ('seat_nut', 'pick_bolt', 'turn_nut')}


class NutBoltResetScopeTests(unittest.TestCase):
    @staticmethod
    def snapshot(env):
        return {'native_rng': pickle.dumps(env.rng.get_state()),
                'native_state': env.native_state.tobytes(),
                'records': copy.deepcopy(env.records),
                'appearance': state(env._nut_bolt_appearance), 'calls': env.calls.copy(),
                'effects': env.effects.copy(),
                'global_numpy_rng': pickle.dumps(np.random.get_state()),
                'global_torch_rng': torch.get_rng_state().numpy().tobytes()}

    def test_partial_seed_rejected_before_any_write(self):
        for seed in (0, 7, [7, 8]):
            env = ResetHarness()
            before = self.snapshot(env)
            with self.assertRaisesRegex(ValueError, 'partial reset must omit seed'):
                env.reset(seed=seed, options={'env_idx': [1]})
            self.assertEqual(self.snapshot(env), before)

    def test_invalid_indices_rejected_before_parent_reset(self):
        for indices in ([1, 0], [], [0, 0], [-1], [2], [.5], [True], np.array([[0]])):
            env = ResetHarness()
            before = self.snapshot(env)
            with self.subTest(indices=indices), self.assertRaisesRegex(ValueError, 'strictly increasing'):
                env.reset(options={'env_idx': indices})
            self.assertEqual(self.snapshot(env), before)

    def test_state_restore_conflict_is_atomic_and_plain_restore_delegates(self):
        restore = {'env_idx': torch.tensor([1]), 'reset_to_env_states': {'env_states': {'native': [[7., 8.]]}}}
        env, native = ResetHarness(), NativeResetSpy()
        before = self.snapshot(env)
        for appearance in ({}, {'scheme_id': 'variant_1'}, {'scheme_id': 'unknown'}):
            with self.assertRaisesRegex(ValueError, 'state restoration cannot include'):
                env.reset(options={**restore, 'nut_bolt_appearance': appearance})
            self.assertEqual(self.snapshot(env), before)
        np.testing.assert_array_equal(env.reset(options=restore), native.reset(options=restore))
        self.assertIs(env.calls[0][1], restore)

    def test_invalid_per_env_rejected_for_reset_and_adapter_construction(self):
        malformed = (None, [], {1: {}}, {'01': {}}, {'-1': {}}, {'2': {}},
                     {'1': None}, {'1': []}, {'1': 'variant_1'})
        env = ResetHarness()
        before = self.snapshot(env)
        for per_env in malformed:
            with self.subTest(per_env=per_env):
                request = {'per_env': per_env}
                with self.assertRaisesRegex(ValueError, 'per_env'):
                    adapter(request)
                with self.assertRaisesRegex(ValueError, 'per_env'):
                    env.reset(options={'env_idx': [0], 'nut_bolt_appearance': request})
                self.assertEqual(self.snapshot(env), before)

    def test_full_reseed_delegates_native_bit_stream(self):
        for options in (None, {}, {'env_idx': torch.arange(2)}):
            env, native = ResetHarness(), NativeResetSpy()
            np.testing.assert_array_equal(env.reset(seed=7, options=options),
                                          native.reset(seed=7, options=options))
            self.assertEqual(pickle.dumps(env.rng.get_state()), pickle.dumps(native.rng.get_state()))
            self.assertEqual(env.calls, native.calls)
            self.assertIs(env.calls[0][1], options)
        env, native = ResetHarness(), NativeResetSpy()
        np.testing.assert_array_equal(env.reset(seed=7, options={'env_idx': None}), native.reset(seed=7, options={}))
        self.assertEqual(env.calls, native.calls)

    def test_partial_without_seed_delegates_unchanged(self):
        env, native = ResetHarness(), NativeResetSpy()
        options = {'env_idx': torch.tensor([1])}
        np.testing.assert_array_equal(env.reset(options=options), native.reset(options=options))
        self.assertEqual(pickle.dumps(env.rng.get_state()), pickle.dumps(native.rng.get_state()))
        self.assertIs(env.calls[0][1], options)

    def test_valid_index_sequences_normalize_to_long_without_mutating_options(self):
        for indices in ([0, 1], (0, 1), np.array([0, 1]), torch.tensor([0, 1], dtype=torch.uint8)):
            env = ResetHarness()
            options = {'env_idx': indices, 'nut_bolt_appearance': {'scheme_id': 'original'}}
            env.reset(options=options)
            self.assertIs(options['env_idx'], indices)
            self.assertIs(env.calls[0][1]['nut_bolt_appearance'], options['nut_bolt_appearance'])
            self.assertTrue(torch.equal(env.calls[0][1]['env_idx'], torch.arange(2)))
            self.assertEqual(env.calls[0][1]['env_idx'].dtype, torch.long)

    def task(self, name, config):
        env = SHORT_TASKS[name]()
        env.run_episode = True
        env._nut_bolt_appearance = adapter(config)
        appearance = env._nut_bolt_appearance
        appearance.rng = [SimpleNamespace(bit_generator=rng.bit_generator, choice=Mock(wraps=rng.choice))
                          for rng in appearance.rng]
        return env

    def assert_appearance_rejected(self, env, options, message, *, seed=None):
        appearance = env._nut_bolt_appearance
        before_choices = [rng.choice.call_count for rng in appearance.rng]
        before = self.snapshot(env)
        with self.assertRaisesRegex(ValueError, message):
            env.reset(seed=seed, options=options)
        self.assertEqual(self.snapshot(env), before)
        self.assertEqual([rng.choice.call_count for rng in appearance.rng], before_choices)

    def test_public_reset_rejects_last_explicit_id_before_native_reset(self):
        for task in SHORT_TASKS:
            env = self.task(task, {'mode': 'random_choice', 'scheme_ids': ['variant_1']})
            options = {'env_idx': torch.arange(2), 'nut_bolt_appearance': {'per_env': {
                '1': {'mode': 'explicit', 'scheme_id': 'wrong_id'},
            }}}
            with self.subTest(task=task):
                self.assert_appearance_rejected(env, options, 'env 1.*wrong_id', seed=17)
                self.assertEqual(env.calls, [])
                self.assertEqual(env.effects, [])
                for rng in env._nut_bolt_appearance.rng:
                    rng.choice.assert_not_called()

    def test_public_reset_checks_each_candidate_and_rejects_a_bad_random_tail(self):
        for task in SHORT_TASKS:
            env = self.task(task, {})
            for scheme in env._nut_bolt_appearance.catalog['schemes']:
                with self.subTest(task=task, scheme=scheme):
                    valid = {'mode': 'random_choice', 'scheme_ids': [scheme]}
                    options = {'nut_bolt_appearance': {'per_env': {
                        '0': valid, '1': {**valid, 'scheme_ids': [scheme, f'{scheme}_typo']},
                    }}}
                    self.assert_appearance_rejected(env, options, 'scheme_ids for env 1')
                    old_calls = len(env.calls)
                    old_effects = len(env.effects)
                    env.reset(options={'nut_bolt_appearance': valid})
                    self.assertEqual(len(env.calls), old_calls + 1)
                    self.assertEqual(env._nut_bolt_appearance.schemes, [scheme, scheme])
                    effects = env.effects[old_effects:]
                    self.assertEqual(effects[:2], ['task_rng', 'state_write'])
                    self.assertIn('task_state_write', effects)
                    self.assertEqual(effects[-1], 'lock_write')

    def test_public_reset_resolves_precedence_for_selected_environments(self):
        env = self.task('seat_nut', {'scheme_id': 'variant_1', 'per_env': {'1': {'scheme_id': 'variant_2'}}})
        appearance = env._nut_bolt_appearance
        env.reset()
        self.assertEqual(appearance.schemes, ['variant_1', 'variant_2'])
        env.reset(options={'env_idx': torch.tensor([1]), 'nut_bolt_appearance': {
            'mode': 'explicit', 'scheme_id': 'original', 'per_env': {'0': {'scheme_id': 'wrong_id'}},
        }})
        self.assertEqual(appearance.schemes, ['variant_1', 'original'])
        override = {'scheme_id': 'wrong_id', 'per_env': {
            '0': {'scheme_id': 'variant_2'}, '1': {'scheme_id': 'variant_1'},
        }}
        options = {'nut_bolt_appearance': override}
        env.reset(options=options)
        self.assertIs(env.calls[-1][1], options)
        self.assertEqual(appearance.schemes, ['variant_2', 'variant_1'])
        self.assertEqual(appearance.episodes, [2, 3])

    def test_public_reset_checks_effective_constructor_config_before_initial_binding(self):
        env = self.task('seat_nut', {'per_env': {'1': {'scheme_id': 'wrong_id'}}})
        env.run_episode = False  # Native scene construction is replaced by the spy.
        appearance = env._nut_bolt_appearance
        appearance.bindings = [None, None]
        before = [copy.deepcopy(rng.bit_generator.state) for rng in appearance.rng]
        with self.assertRaisesRegex(ValueError, 'env 1.*wrong_id'):
            env.reset(options={'reconfigure': True})
        self.assertEqual(env.calls, [])
        self.assertEqual(env.effects, [])
        options = {'reconfigure': True, 'nut_bolt_appearance': {'scheme_id': 'variant_1'}}
        env.reset(options=options)
        self.assertIs(env.calls[-1][1], options)
        self.assertEqual(appearance.bindings, [None, None])
        self.assertEqual([rng.bit_generator.state for rng in appearance.rng], before)

    def test_public_reset_keeps_constructor_enablement_and_plain_restore(self):
        env = self.task('seat_nut', {})
        appearance = env._nut_bolt_appearance
        env.reset(options={'nut_bolt_appearance': {'enabled': False, 'scheme_id': 'variant_1'}})
        self.assertEqual(appearance.schemes, ['variant_1', 'variant_1'])
        self.assert_appearance_rejected(env, {'nut_bolt_appearance': {
            'enabled': False, 'scheme_id': 'wrong_id',
        }}, 'Unknown.*wrong_id')
        restore = {'env_idx': torch.tensor([1]), 'reset_to_env_states': {'env_states': {}}}
        self.assert_appearance_rejected(env, {**restore, 'nut_bolt_appearance': {}}, 'state restoration')
        before = state(appearance)
        env.reset(options=restore)
        self.assertIs(env.calls[-1][1], restore)
        self.assertEqual(state(appearance), before)
        env._nut_bolt_appearance = None
        disabled = {'nut_bolt_appearance': {'enabled': True, 'scheme_id': 'wrong_id'}}
        env.reset(options=disabled)
        self.assertIsNone(env._nut_bolt_appearance)
        self.assertIs(env.calls[-1][1], disabled)

    def test_public_reset_rejects_invalid_selection_types_before_native_reset(self):
        for override, message in (
            ({'scheme_id': ['variant_1']}, 'Unknown Nut & Bolt scheme'),
            ({'mode': 'unknown'}, 'Unsupported Nut & Bolt selection mode'),
            ({'mode': 'random_choice', 'scheme_ids': []}, 'scheme_ids'),
            ({'mode': 'random_choice', 'scheme_ids': 'variant_1'}, 'scheme_ids'),
        ):
            env = self.task('seat_nut', {})
            with self.subTest(override=override):
                self.assert_appearance_rejected(env, {'nut_bolt_appearance': override}, message)


class NutBoltAppearanceTests(unittest.TestCase):
    def test_memory_profile_cannot_override_physics(self):
        tree = ast.parse((ROOT / 'tasks/nut_bolt/nut_bolt_long.py').read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'NutBoltLongEnv')
        init = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == '__init__')
        guard = compile(ast.Module(body=[init.body[0]], type_ignores=[]), '<memory_capacity_guard>', 'exec')
        valid = {'max_rigid_contact_count': 2**17, 'max_rigid_patch_count': 2**16,
                 'found_lost_pairs_capacity': 2**20}
        for kwargs in ({}, {'sim_config': None}, {'sim_config': {'gpu_memory_config': valid}}):
            exec(guard, {'kwargs': kwargs})
        invalid = [True, 1, 'invalid', {}, {'gpu_memory_config': {}},
                   {'sim_freq': 1}, {'scene_config': {'gravity': [0, 0, 0]}},
                   {'gpu_memory_config': valid, 'sim_freq': 1},
                   {'gpu_memory_config': {**valid, 'other': 1}}]
        invalid += [{'gpu_memory_config': {**valid, 'max_rigid_contact_count': value}}
                    for value in (0, -1, True, 1.5, '131072')]
        for config in invalid:
            with self.assertRaises(ValueError, msg=repr(config)):
                exec(guard, {'kwargs': {'sim_config': config}})

    def random_helpers(self):
        import torch
        tree = ast.parse((ROOT / 'tasks/nut_bolt/nut_bolt_long.py').read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'NutBoltLongEnv')
        methods = [node for node in cls.body if isinstance(node, ast.FunctionDef)
                   and node.name in ('_reset_random', '_reset_disc_xy')]
        namespace = {'np': np, 'torch': torch,
                     'is_full_reset': lambda indices, count: indices is None or set(indices) == set(range(count))}
        exec(compile(ast.Module(body=methods, type_ignores=[]), '<reset_draw_helpers>', 'exec'), namespace)
        dummy = SimpleNamespace(device='cpu', num_envs=2)
        dummy._reset_random = lambda shape, normal=False: namespace['_reset_random'](dummy, shape, normal)
        return torch, namespace, dummy

    def test_full_reset_preserves_native_torch_draws(self):
        torch, namespace, dummy = self.random_helpers()
        for seed in (0, 7, 71):
            torch.manual_seed(seed)
            angle = torch.rand(2) * 2 * np.pi
            radial = .1 * torch.sqrt(torch.rand(2))
            expected = torch.stack([-.2 + radial * torch.cos(angle), .3 + radial * torch.sin(angle)], dim=-1)
            expected_noise = torch.randn((2, 7))
            expected_state = torch.get_rng_state()
            torch.manual_seed(seed)
            actual = namespace['_reset_disc_xy'](dummy, [-.2, .3], .1, 2)
            actual_noise = dummy._reset_random((2, 7), normal=True)
            self.assertTrue(torch.equal(expected, actual))
            self.assertTrue(torch.equal(expected_noise, actual_noise))
            self.assertTrue(torch.equal(expected_state, torch.get_rng_state()))
            dummy._furniture_reset_env_idx = [0, 1]
            torch.manual_seed(seed)
            explicit = namespace['_reset_disc_xy'](dummy, [-.2, .3], .1, 2)
            explicit_noise = dummy._reset_random((2, 7), normal=True)
            self.assertTrue(torch.equal(expected, explicit))
            self.assertTrue(torch.equal(expected_noise, explicit_noise))
            self.assertTrue(torch.equal(expected_state, torch.get_rng_state()))

    def test_partial_reset_consumes_selected_task_rng_only(self):
        torch, namespace, dummy = self.random_helpers()
        dummy._furniture_reset_env_idx = [1]
        dummy._batched_episode_rng = [np.random.RandomState(7), np.random.RandomState(71)]
        before = copy.deepcopy(dummy._batched_episode_rng[0].get_state())
        global_before = torch.get_rng_state()
        for normal in (False, True):
            actual = dummy._reset_random((1, 7), normal=normal)
            self.assertEqual(tuple(actual.shape), (1, 7))
        after = dummy._batched_episode_rng[0].get_state()
        self.assertEqual(before[0], after[0])
        np.testing.assert_array_equal(before[1], after[1])
        self.assertEqual(before[2:], after[2:])
        self.assertTrue(torch.equal(global_before, torch.get_rng_state()))

    def test_precedence(self):
        value = adapter({'scheme_id': 'original', 'per_env': {'1': {'scheme_id': 'variant_1'}}})
        reset(value, [0, 1])
        self.assertEqual(value.schemes, ['original', 'variant_1'])
        reset(value, [1], {'scheme_id': 'variant_2'})
        self.assertEqual(value.schemes, ['original', 'variant_2'])
        reset(value, [1], {'scheme_id': 'variant_1', 'per_env': {'1': {'scheme_id': 'original'}}})
        self.assertEqual(value.schemes, ['original', 'original'])
        self.assertEqual(value.episodes, [1, 3])

    def test_original_and_protected_roles(self):
        value = adapter()
        native = state(value)['pbr']
        reset(value, [0, 1], {'scheme_id': 'variant_1'})
        for env_id in range(2):
            self.assertEqual(state(value)['pbr'][env_id][2:4], native[env_id][2:4])
            self.assertNotEqual(state(value)['pbr'][env_id][0], native[env_id][0])
            # Free and threaded reference faces share parameters without aliasing.
            self.assertEqual(state(value)['pbr'][env_id][5], state(value)['pbr'][env_id][7])
        reset(value, [0, 1], {'scheme_id': 'original'})
        self.assertEqual(state(value)['pbr'], native)
        self.assertTrue(all(row[3].specular == .29 for rows in value.bindings for row in rows))

    def test_atomic_invalid_second_environment(self):
        value = adapter({'mode': 'random_choice', 'seed': 71, 'scheme_ids': ['original', 'variant_1']})
        before = state(value)
        with self.assertRaises(ValueError):
            reset(value, [0, 1], {'per_env': {'1': {'scheme_ids': ['unknown']}}})
        self.assertEqual(state(value), before)

    def test_unbound_second_environment_is_atomic(self):
        value = adapter({'mode': 'random_choice', 'scheme_ids': ['variant_1']})
        value.bindings[1] = None
        rng = [copy.deepcopy(item.bit_generator.state) for item in value.rng]
        with self.assertRaises(RuntimeError):
            reset(value, [0, 1])
        self.assertEqual([item.bit_generator.state for item in value.rng], rng)
        self.assertEqual(value.records, [])

    def test_invalid_selection_indices(self):
        for indices in ([], [0, 0], [-1], [2], [.5], [True], [1, 0]):
            value = adapter()
            before = state(value)
            with self.assertRaises(ValueError):
                reset(value, indices)
            self.assertEqual(state(value), before)

    def test_empty_and_unknown_choices(self):
        for request in ({'mode': 'random_choice', 'scheme_ids': []},
                        {'mode': 'random_choice', 'scheme_ids': ['variant_1', 'missing']},
                        {'scheme_id': 'missing'}, {'mode': 'unsupported'},
                        {'per_env': {'2': {'scheme_id': 'variant_1'}}}, {'per_env': {'1': None}}):
            value = adapter()
            before = state(value)
            with self.assertRaises(ValueError):
                reset(value, [0, 1], request)
            self.assertEqual(state(value), before)

    def test_local_rng_and_records(self):
        config = {'mode': 'random_choice', 'seed': 71, 'scheme_ids': ['original', 'variant_1', 'variant_2']}
        value, control = adapter(config), adapter(config)
        reset(value, [0, 1]); reset(control, [0, 1])
        before = state(value)
        for _ in range(32):
            reset(value, [1])
        after = state(value)
        self.assertEqual(after['pbr'][0], before['pbr'][0])
        self.assertEqual(after['rng'][0], before['rng'][0])
        self.assertEqual([r for r in after['records'] if r['env_idx'] == 0],
                         [r for r in before['records'] if r['env_idx'] == 0])
        reset(value, [0]); reset(control, [0])
        self.assertEqual(value.schemes[0], control.schemes[0])
        self.assertEqual(value.rng[0].bit_generator.state, control.rng[0].bit_generator.state)

    def test_explicit_does_not_consume_rng(self):
        value = adapter()
        before = state(value)['rng']
        for name in ('variant_1', 'variant_2', 'original'):
            reset(value, [0, 1], {'scheme_id': name, 'seed': 9, 'enabled': False})
        self.assertEqual(state(value)['rng'], before)
        self.assertEqual(len(value.records), sum(value.episodes))

    def test_role_counts(self):
        from collections import Counter
        self.assertEqual(Counter(MODULE.role_order('bolt')), dict(shaft=1, tip=20, thread=192, head=1))
        self.assertEqual(Counter(MODULE.role_order('nut')), dict(reference_face=1, body=5))

    def test_protected_task_formulas_and_physics_match_main(self):
        # Scope wrappers only affect reset bookkeeping. Normalize those wrappers
        # and compare judgment, rewards, locking and geometry with the main tree.
        paths = [ROOT / 'tasks/nut_bolt' / f'nut_bolt_{name}.py'
                 for name in ('long', 'pick_bolt', 'seat_nut', 'turn_nut')]
        methods = {'evaluate', '_get_obs_extra', 'compute_dense_reward', '_refresh_hold_state', '_hold_pose',
                   '_before_control_step', '_default_sim_config', '_update_platform_pose', '_set_task_object_energy_fence',
                   '_bolt_placement_state', '_nut_seating_state', '_qualify_bolt_placement',
                   '_nut_engagement_ready', '_update_screwing_state', '_latch_success',
                   '_generate_threaded_nut_urdf', '_load_bolt', '_load_nut', '_load_threaded_nut', '_load_platform'}
        class Normalize(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                if node.name in ('_refresh_hold_state', '_hold_pose'):
                    node.body = [statement for statement in node.body if not (
                        isinstance(statement, ast.If) and ast.unparse(statement.test) == 'self.gpu_sim_enabled')]
                return self.generic_visit(node)
            def visit_If(self, node):
                if ast.unparse(node.test) == 'self._nut_bolt_appearance is not None':
                    return None
                return self.generic_visit(node)
            def visit_Call(self, node):
                node = self.generic_visit(node)
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == '_reset_scoped_value':
                        return node.args[1]
                    if node.func.attr == '_reset_scoped_predicate':
                        return node.args[0]
                return node
            def visit_Assign(self, node):
                node = self.generic_visit(node)
                if (len(node.targets) == 1 and ast.unparse(node.targets[0]) == 'self._threaded_depth'
                        and ast.unparse(node.value) == 'torch.zeros_like(self._threaded_depth)'):
                    return ast.parse('self._threaded_depth.zero_()').body[0]
                return node
        for path in paths:
            old = subprocess.check_output(['git', 'show', f'HEAD:{path.relative_to(ROOT).as_posix()}'], cwd=ROOT, text=True)
            def signatures(text):
                tree = Normalize().visit(ast.parse(text))
                return {node.name: ast.dump(node, include_attributes=False) for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name in methods}
            self.assertEqual(signatures(path.read_text()), signatures(old), path.name)


if __name__ == '__main__':
    unittest.main()
