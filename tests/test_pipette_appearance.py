"""CPU-only contract checks; no task import or renderer construction."""
import copy
import ast
from collections import Counter
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
class IdentityNamespace(SimpleNamespace):
    __eq__ = object.__eq__

SPEC = importlib.util.spec_from_file_location('pipette_appearance_test', ROOT / 'tasks/pipette_transfer/appearance.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def adapter(config=None, material_type=SimpleNamespace):
    value = MODULE.PipetteAppearance({'enabled': True, **(config or {})}, 2, rendering_enabled=True)
    for i in range(2):
        rows = []
        for oid, role in [('pipette', 'body'), ('pipette', 'plunger'),
                          ('sample_cup', 'wall'), ('tip_cup', 'tip_cup')]:
            native = {'base_color': [.2 + .1 * i, .3, .4, .94], 'roughness': .27,
                      'metallic': .04, 'specular': .83, 'transmission': .12,
                      'ior': 1.46, 'emission': [0., 0., 0., 1.],
                      'transmission_roughness': .0}
            native.update({field: None for field in MODULE.MATERIAL_FIELDS if field.endswith('_texture')})
            mat = material_type(**copy.deepcopy(native))
            rows.append((oid, role, SimpleNamespace(material=mat), mat, copy.deepcopy(native)))
        value.bindings[i] = rows
    return value


def reset(value, ids=(0, 1), config=None):
    value.finish_reset(np.asarray(ids), {} if config is None else {'pipette_appearance': config})


def state(value):
    return [copy.deepcopy(vars(row[3])) for bindings in value.bindings for row in bindings]


def public_reset_spy(appearance, *, apply=False):
    """Use the actual public method with a parent that records native reset effects."""
    import torch
    path = ROOT / 'tasks/pipette_transfer/pipette_transfer_long.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PipetteTransferLongEnv')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'reset')

    class Parent:
        def reset(self, seed=None, options=None):
            self.parent_calls.append((seed, options))
            self.effects['native_reset'] += 1
            self.effects['task_rng'] += 1
            self.task_rng.random()
            self.effects['state_write'] += 1
            self.state['qpos'] += 1
            self.effects['lock_write'] += 1
            self.lock = True
            request = options or {}
            if apply and self._pipette_appearance is not None and 'reset_to_env_states' not in request:
                indices = request.get('env_idx', np.arange(self.num_envs))
                self._pipette_appearance.finish_reset(indices, request)
            return 'parent_result'

    source = ast.ClassDef(name='UnderTest', bases=[ast.Name(id='Parent', ctx=ast.Load())],
                          keywords=[], body=[method], decorator_list=[])
    namespace = {'Parent': Parent, 'torch': torch, 'validate_reset_request': MODULE.validate_reset_request}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[source], type_ignores=[])),
                 str(path), 'exec'), namespace)
    env = namespace['UnderTest']()
    env._pipette_appearance = appearance
    env.num_envs, env.parent_calls = 2, []
    env._elapsed_steps = torch.zeros(2, dtype=torch.long)
    env.effects, env.task_rng = Counter(), np.random.default_rng(7)
    env.state, env.lock = {'qpos': 0}, False
    return env


class PublicResetTests(unittest.TestCase):
    def counted_appearance(self, config=None, *, rendering_enabled=True):
        writes = Counter()

        class Material(SimpleNamespace):
            def __setattr__(self, key, value):
                writes['material_write'] += 1
                super().__setattr__(key, value)

        value = adapter(config, material_type=Material)
        value.rendering_enabled = rendering_enabled

        def choice(rng, choices):
            writes['appearance_rng'] += 1
            return rng.choice(choices)

        value.rng = [SimpleNamespace(bit_generator=rng.bit_generator,
                                     choice=lambda choices, rng=rng: choice(rng, choices)) for rng in value.rng]
        env = public_reset_spy(value, apply=True)
        env.effects = writes
        return env, value

    def assert_rejected_without_effects(self, env, options, message, *, seed=None):
        value = env._pipette_appearance
        def snapshot():
            return copy.deepcopy((env.parent_calls, env.effects, env.task_rng.bit_generator.state,
                                  env.state, env.lock, value.records, value.schemes, value.episodes,
                                  [rng.bit_generator.state for rng in value.rng],
                                  state(value) if all(value.bindings) else None))
        before = snapshot()
        with self.assertRaisesRegex(ValueError, message):
            env.reset(seed=seed, options=options)
        self.assertEqual(snapshot(), before)

    def test_public_reset_rejects_a_last_env_typo_for_every_published_candidate(self):
        env, value = self.counted_appearance()
        for scheme in value.catalog['schemes'][1:]:
            with self.subTest(scheme=scheme):
                request = {'pipette_appearance': {'scheme_id': scheme, 'per_env': {
                    '1': {'scheme_id': scheme + '_typo'}}}}
                self.assert_rejected_without_effects(env, request, f'{scheme}_typo', seed=7)
        self.assertEqual(env.effects, Counter())

    def test_public_reset_checks_every_random_choice_before_any_draw(self):
        env, _ = self.counted_appearance({'mode': 'random_choice', 'scheme_ids': ['jade', 'coral']})
        request = {'pipette_appearance': {'per_env': {'1': {'scheme_ids': ['original', 'coral', 'wrong_id']}}}}
        self.assert_rejected_without_effects(env, request, 'wrong_id')
        request = {'pipette_appearance': {'per_env': {'1': {'scheme_ids': []}}}}
        self.assert_rejected_without_effects(env, request, 'nonempty')

    def test_public_reset_forwards_valid_ids_and_preserves_override_precedence(self):
        env, value = self.counted_appearance({'scheme_id': 'original', 'per_env': {'1': {'scheme_id': 'coral'}}})
        self.assertEqual(env.reset(seed=7), 'parent_result')
        self.assertEqual(value.schemes, ['original', 'coral'])
        for scheme in value.catalog['schemes']:
            with self.subTest(scheme=scheme):
                options = {'pipette_appearance': {'scheme_id': scheme}}
                self.assertEqual(env.reset(options=options), 'parent_result')
                self.assertIs(env.parent_calls[-1][1], options)
                self.assertEqual(value.schemes, [scheme, scheme])
        request = {'env_idx': [0], 'pipette_appearance': {'scheme_id': 'jade',
                    'per_env': {'0': {'scheme_id': 'coral'}, '1': {'scheme_id': 'wrong_unselected'}}}}
        preceding = value.schemes[1]
        self.assertEqual(env.reset(options=request), 'parent_result')
        self.assertEqual(value.schemes, ['coral', preceding])
        self.assertEqual(request['env_idx'], [0])
        self.assertEqual(env.effects['appearance_rng'], 0)
        self.assert_rejected_without_effects(env, {**request, 'env_idx': [1]}, 'wrong_unselected')
        random_request = {'env_idx': [1], 'pipette_appearance': {'mode': 'random_choice', 'scheme_ids': ['jade']}}
        self.assertEqual(env.reset(options=random_request), 'parent_result')
        self.assertEqual(value.schemes, ['coral', 'jade'])
        self.assertEqual(env.effects['appearance_rng'], 1)

    def test_public_reset_rejects_active_overrides_that_require_construction_or_rendering(self):
        env, value = self.counted_appearance(rendering_enabled=False)
        for request, message in (
                ({'enabled': False}, 'only at construction'),
                ({'per_env': {'1': {'seed': 9}}}, 'only at construction'),
                ({'scheme_id': 'jade'}, 'pipette_rendering'),
                ({'scheme_id': 'coral'}, 'pipette_rendering'),
                ({'mode': 'random_choice', 'scheme_ids': ['original', 'jade']}, 'pipette_rendering'),
                ({'mode': 'bad'}, 'Unsupported')):
            with self.subTest(request=request):
                self.assert_rejected_without_effects(env, {'pipette_appearance': request}, message)
        self.assertEqual(env.reset(), 'parent_result')
        self.assertEqual(value.schemes, ['original', 'original'])

    def test_public_reset_preserves_disabled_and_state_restore_routes(self):
        disabled = public_reset_spy(None)
        options = {'pipette_appearance': {'scheme_id': 'jade'}}
        self.assertEqual(disabled.reset(options=options), 'parent_result')
        self.assertIs(disabled.parent_calls[-1][1], options)
        self.assertIsNone(disabled._pipette_appearance)
        env, value = self.counted_appearance({'mode': 'random_choice', 'scheme_ids': ['jade', 'coral']})
        restore = {'reset_to_env_states': {'env_states': {'qpos': [1, 2]}}}
        self.assert_rejected_without_effects(
            env, {**restore, 'pipette_appearance': {'scheme_id': 'original'}}, 'state restoration')
        self.assertEqual(env.reset(options=restore), 'parent_result')
        self.assertIs(env.parent_calls[-1][1], restore)
        self.assertEqual(value.records, [])
        self.assertEqual(env.effects['appearance_rng'], 0)
        self.assertEqual(env.effects['material_write'], 0)

    def test_public_reset_preflights_initial_reconfigure_with_unbound_materials(self):
        value = MODULE.PipetteAppearance({'scheme_id': 'jade', 'per_env': {'1': {'scheme_id': 'wrong_id'}}},
                                        2, rendering_enabled=True)
        env = public_reset_spy(value)
        initial = {'reconfigure': True}
        self.assert_rejected_without_effects(env, initial, 'wrong_id', seed=[2022, 2023])
        self.assertEqual(env.effects, Counter())
        valid = {**initial, 'pipette_appearance': {'scheme_id': 'coral'}}
        self.assertEqual(env.reset(seed=[2022, 2023], options=valid), 'parent_result')
        self.assertIs(env.parent_calls[-1][1], valid)
        self.assertEqual(value.bindings, [None, None])
        self.assertEqual(value.records, [])


class PipetteAppearanceTests(unittest.TestCase):
    def test_configuration_precedence(self):
        value = adapter({'scheme_id': 'original', 'per_env': {'1': {'scheme_id': 'jade'}}})
        reset(value)
        self.assertEqual(value.schemes, ['original', 'jade'])
        reset(value, [1], {'scheme_id': 'coral'})
        self.assertEqual(value.schemes, ['original', 'coral'])
        reset(value, [1], {'scheme_id': 'coral', 'per_env': {'1': {'scheme_id': 'original'}}})
        self.assertEqual(value.schemes, ['original', 'original'])
        self.assertEqual(value.episodes, [1, 3])

    def test_original_complete_restore_and_protected_fields(self):
        value = adapter({'scheme_id': 'jade'})
        native = state(value)
        reset(value)
        for rows in value.bindings:
            self.assertEqual(vars(rows[1][3]), rows[1][4])
            self.assertEqual(rows[2][3].base_color[3], .22)
            for oid, role, _, mat, captured in rows:
                for field in set(MODULE.MATERIAL_FIELDS) - set(MODULE.FIELDS):
                    self.assertEqual(getattr(mat, field), captured[field])
        reset(value, config={'scheme_id': 'original'})
        self.assertEqual(state(value), native)

    def test_local_rng_records_and_materials(self):
        config = {'mode': 'random_choice', 'scheme_ids': ['original', 'jade', 'coral'], 'seed': 71}
        first, second = adapter(config), adapter(config)
        reset(first)
        reset(second)
        rng = copy.deepcopy(first.rng[0].bit_generator.state)
        before, records = state(first)[:4], copy.deepcopy(first.records)
        for _ in range(20):
            reset(first, [1])
        self.assertEqual(first.rng[0].bit_generator.state, rng)
        self.assertEqual(state(first)[:4], before)
        self.assertEqual(first.records[:len(records)], records)
        reset(first, [0])
        reset(second, [0])
        self.assertEqual(first.schemes[0], second.schemes[0])
        self.assertEqual(first.rng[0].bit_generator.state, second.rng[0].bit_generator.state)

    def test_explicit_does_not_consume_rng(self):
        value = adapter({'scheme_id': 'coral'})
        before = copy.deepcopy([rng.bit_generator.state for rng in value.rng])
        reset(value)
        self.assertEqual(before, [rng.bit_generator.state for rng in value.rng])

    def test_later_invalid_environment_is_atomic(self):
        value = adapter({'mode': 'random_choice', 'scheme_ids': ['jade', 'coral']})
        before = state(value)
        rng = copy.deepcopy([item.bit_generator.state for item in value.rng])
        with self.assertRaises(ValueError):
            reset(value, config={'per_env': {'1': {'scheme_id': 'unknown', 'mode': 'explicit'}}})
        self.assertEqual(state(value), before)
        self.assertEqual([item.bit_generator.state for item in value.rng], rng)
        self.assertEqual(value.records, [])
        self.assertEqual(value.episodes, [0, 0])

    def test_replaced_later_material_is_atomic(self):
        value = adapter({'mode': 'random_choice', 'scheme_ids': ['jade', 'coral']})
        value.bindings[1][0][2].material = SimpleNamespace()
        before, rng = state(value), copy.deepcopy([item.bit_generator.state for item in value.rng])
        with self.assertRaises(RuntimeError):
            reset(value)
        self.assertEqual(state(value), before)
        self.assertEqual([item.bit_generator.state for item in value.rng], rng)

    def test_illegal_selection_rejected(self):
        for ids in ([], [0, 0], [-1], [2], [0.5]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                reset(adapter(), ids)
        for request in ({'mode': 'invalid'}, {'mode': 'random_choice', 'scheme_ids': []},
                        {'scheme_id': 'unknown'}, {'enabled': False}, {'seed': 4},
                        {'per_env': {'1': {'seed': 7}}}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                reset(adapter(), config=request)

    def test_record_identity(self):
        value = adapter({'scheme_id': 'jade'})
        reset(value)
        reset(value, [1], {'scheme_id': 'coral'})
        self.assertEqual(value.records[-1], {'env_idx': 1, 'episode_index': 2,
            'scheme_id': 'coral', 'catalog_version': 'pipette-appearance-v3'})

    def test_candidate_requires_compatible_rendering(self):
        value = adapter({'scheme_id': 'jade'})
        value.rendering_enabled = False
        with self.assertRaises(ValueError):
            reset(value)
        reset(value, config={'scheme_id': 'original'})

    def test_arm_reset_consumes_and_writes_only_selected_environment(self):
        import torch
        tree = ast.parse((ROOT / 'tasks/pipette_transfer/pipette_transfer_long.py').read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PipetteTransferLongEnv')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == '_reset_arms')
        draws, writes, calls = [], {}, []
        robot = SimpleNamespace(get_qpos=lambda: torch.zeros((2, 9)), get_qvel=lambda: torch.zeros((2, 9)),
            get_active_joints=lambda: [SimpleNamespace(name=f'j{i}') for i in range(9)],
            set_qpos=lambda value: writes.update(qpos=value.clone()),
            set_qvel=lambda value: writes.update(qvel=value.clone()))
        env = SimpleNamespace(agent=SimpleNamespace(robot=robot, arm_joint_names=[f'j{i}' for i in range(7)],
            controller=SimpleNamespace(reset=lambda: calls.append('controller_reset'))),
            device=torch.device('cpu'), robot_init_qpos_noise=.02)
        def rng(value, i):
            draws.append(i)
            return i
        namespace = {'torch': torch, 'ARM_INIT_QPOS': [.1] * 7, 'episode_rng': rng,
                     'arm_qpos_noise': lambda *args, **kwargs: (torch.arange(7), torch.ones((1, 7)) * .02)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<scoped-arm-reset>', 'exec'), namespace)
        namespace['_reset_arms'](env, torch.tensor([1]))
        self.assertEqual(draws, [1])
        self.assertEqual(tuple(writes['qpos'].shape), (1, 9))
        self.assertEqual(tuple(writes['qvel'].shape), (1, 9))
        self.assertEqual(calls, ['controller_reset'])

    def test_state_view_mapping_preserves_aliases_and_catches_both_errors(self):
        import torch
        sys.path.insert(0, str(ROOT / 'tools/variation'))
        import check_pipette_runtime as runtime
        import check_furniture_appearance as shared
        shared.torch = torch
        keys = ['/state/actors/a0', '/state/actors/a1', '/state/actors/merged']
        values = {keys[0]: torch.tensor([[1., -0.]]), keys[1]: torch.tensor([[3., 4.]]),
                  keys[2]: torch.tensor([[1., 2.], [3., 4.]])}
        registries = {'actors': {'a0': SimpleNamespace(_scene_idxs=torch.tensor([0])),
                                 'a1': SimpleNamespace(_scene_idxs=torch.tensor([1]))}}
        mapped, metadata = runtime.map_state_views(values, 2, registries)
        self.assertTrue(set(values) <= set(mapped))
        for row in metadata.values():
            self.assertEqual(row['original_value_sha256'], row['reconstructed_value_sha256'])
        for path, env_id in ((keys[0], 0), (keys[1], 1)):
            wrong = {key: value.clone() for key, value in mapped.items()}
            wrong[path][env_id, 0] += 1
            self.assertIn(path, shared.state_changes(mapped, wrong, [env_id]))
        with self.assertRaises(KeyError):
            runtime.map_state_views(values, 2, {'actors': {}})

    def test_partial_seed_rejected_before_state_rng_or_records_change(self):
        tree = ast.parse((ROOT / 'tasks/pipette_transfer/pipette_transfer_long.py').read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PipetteTransferLongEnv')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'reset')
        source = ast.parse((ROOT / 'tasks/furniture_assembly/reset_scope.py').read_text(encoding='utf-8'))
        helper = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'is_full_reset')
        namespace = {'validate_reset_request': MODULE.validate_reset_request,
                     'validate_per_env': MODULE.validate_per_env}
        exec(compile(ast.Module(body=[helper, method], type_ignores=[]), '<partial-seed-contract>', 'exec'), namespace)
        value = adapter({'scheme_id': 'jade'})
        reset(value)
        holder = SimpleNamespace(num_envs=2, state={'joint': [1., 2.]}, records=value.records,
                                 task_rng=np.random.RandomState(7), appearance=value)
        before = (copy.deepcopy(holder.state), copy.deepcopy(holder.records), state(value),
                  copy.deepcopy(holder.task_rng.get_state()), copy.deepcopy([rng.bit_generator.state for rng in value.rng]))
        with self.assertRaises(ValueError):
            namespace['reset'](holder, seed=17, options={'env_idx': [1]})
        self.assertEqual(before[:3], (holder.state, holder.records, state(value)))
        self.assertEqual(before[3][0], holder.task_rng.get_state()[0])
        np.testing.assert_array_equal(before[3][1], holder.task_rng.get_state()[1])
        self.assertEqual(before[3][2:], holder.task_rng.get_state()[2:])
        self.assertEqual(before[4], [rng.bit_generator.state for rng in value.rng])

    def test_parent_reset_preflight_rejects_indices_per_env_and_restore_without_side_effects(self):
        import torch

        source = ast.parse((ROOT / 'tasks/pipette_transfer/pipette_transfer_long.py').read_text(encoding='utf-8'))
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'PipetteTransferLongEnv')
        method = copy.deepcopy(next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'reset'))
        scope = ast.parse((ROOT / 'tasks/furniture_assembly/reset_scope.py').read_text(encoding='utf-8'))
        helper = next(n for n in scope.body if isinstance(n, ast.FunctionDef) and n.name == 'is_full_reset')
        class Parent:
            def reset(self, seed=None, options=None):
                self.parent_calls.append((seed, options))
                return 'parent_result'
        test_class = ast.ClassDef(name='UnderTest', bases=[ast.Name(id='Parent', ctx=ast.Load())],
            keywords=[], body=[method], decorator_list=[])
        namespace = {'Parent': Parent, 'torch': torch, 'validate_per_env': MODULE.validate_per_env,
                     'validate_reset_request': MODULE.validate_reset_request}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[helper, test_class], type_ignores=[])),
                     '<preflight-parent-spy>', 'exec'), namespace)
        env = namespace['UnderTest']()
        env.num_envs, env.parent_calls, env.device = 2, [], torch.device('cpu')
        env._elapsed_steps = torch.zeros(2, dtype=torch.long, device=env.device)
        env._pipette_appearance = adapter({'scheme_id': 'jade'})
        reset(env._pipette_appearance)
        env.task_rng, env.state = np.random.RandomState(7), {'qpos': [1., 2.]}
        before = (state(env._pipette_appearance), copy.deepcopy(env._pipette_appearance.records),
                  copy.deepcopy([r.bit_generator.state for r in env._pipette_appearance.rng]),
                  copy.deepcopy(env.task_rng.get_state()), copy.deepcopy(env.state))
        requests = [{'env_idx': [1, 0]}, {'env_idx': [0, 0]}, {'env_idx': [-1]}, {'env_idx': [2]},
                    {'env_idx': []}, {'env_idx': [True]},
                    {'reset_to_env_states': {'payload': [1]}, 'pipette_appearance': {'scheme_id': 'coral'}}]
        for entries in ({'2': {}}, {'-1': {}}, {'env1': {}}, {'01': {}}, {1: {}}, {'1': None}, []):
            requests.append({'pipette_appearance': {'mode': 'random_choice', 'scheme_ids': ['jade', 'coral'], 'per_env': entries}})
        for options in requests:
            with self.subTest(options=options), self.assertRaises(ValueError):
                env.reset(options=options)
        self.assertEqual(env.parent_calls, [])
        self.assertEqual(before[:3], (state(env._pipette_appearance), env._pipette_appearance.records,
                                     [r.bit_generator.state for r in env._pipette_appearance.rng]))
        np.testing.assert_array_equal(before[3][1], env.task_rng.get_state()[1])
        self.assertEqual(before[3][2:], env.task_rng.get_state()[2:])
        self.assertEqual(before[4], env.state)
        sorted_options = {'env_idx': torch.tensor([0, 1], dtype=torch.long)}
        self.assertEqual(env.reset(seed=7, options=sorted_options), 'parent_result')
        self.assertIs(env.parent_calls[-1][1], sorted_options)
        for incoming in ([1], (1,), torch.tensor([1], dtype=torch.uint8)):
            options = {'env_idx': incoming}
            with self.subTest(input_type=type(incoming)), self.assertRaises(ValueError):
                env.reset(seed=7, options=options)
            self.assertEqual(env.reset(options=options), 'parent_result')
            normalized = env.parent_calls[-1][1]
            self.assertIsNot(normalized, options)
            self.assertIs(options['env_idx'], incoming)
            self.assertEqual(normalized['env_idx'].tolist(), [1])
            self.assertEqual(normalized['env_idx'].dtype, torch.long)
            self.assertEqual(normalized['env_idx'].device, env.device)
        restore = {'env_idx': (1,), 'reset_to_env_states': {'payload': [1]}}
        self.assertEqual(env.reset(options=restore), 'parent_result')
        self.assertIs(env.parent_calls[-1][1]['reset_to_env_states'], restore['reset_to_env_states'])
        self.assertEqual(env.parent_calls[-1][1]['env_idx'].tolist(), [1])
        self.assertEqual(restore['env_idx'], (1,))
        self.assertEqual(env.reset(), 'parent_result')
        self.assertEqual(env.parent_calls[-1], (None, None))

    def test_constructor_per_env_validation_precedes_rng_creation(self):
        for entries in ({'2': {}}, {'-1': {}}, {'env1': {}}, {'01': {}}, {1: {}}, {'1': None}, []):
            with self.subTest(entries=entries), patch.object(MODULE.np.random, 'default_rng') as draw:
                with self.assertRaises(ValueError):
                    MODULE.PipetteAppearance({'enabled': True, 'per_env': entries}, 2, rendering_enabled=True)
                draw.assert_not_called()

    def test_native_binding_shape_and_parent_mapping(self):
        value = MODULE.PipetteAppearance({'enabled': True}, 2, rendering_enabled=True)
        def shape():
            return SimpleNamespace(parts=[SimpleNamespace(material=IdentityNamespace(
                base_color=[.1, .2, .3, 1.], roughness=.5, metallic=0., base_color_texture=None))])
        def entity(count):
            body = SimpleNamespace(render_shapes=[shape() for _ in range(count)])
            return SimpleNamespace(find_component_by_type=lambda cls: body)
        stands = [entity(47) for _ in range(2)]
        articulations = []
        for i in range(2):
            links = [SimpleNamespace(name=f'pipette_{i}_{name}', entity=entity(count))
                     for name, count in [('base', 4), ('tip', 1), ('plunger', 1)]]
            articulations.append(SimpleNamespace(get_links=lambda links=links: links))
        base = SimpleNamespace(sample_cup=None, test_tube=None, tube_rack=None,
            pipette_stand=SimpleNamespace(_objs=stands), pipette=SimpleNamespace(_objs=articulations))
        base.scene = SimpleNamespace(sub_scenes=[SimpleNamespace(render_system=SimpleNamespace(
            _internal_scene=SimpleNamespace(force_rebuild=lambda: None))) for _ in range(2)])
        texture = object()
        render = SimpleNamespace(RenderBodyComponent=object, RenderTexture2D=Mock(return_value=texture))
        with patch.dict(sys.modules, {'sapien': SimpleNamespace(render=render), 'sapien.render': render}):
            value.bind(base, 0)
            value.bind(base, 1)
            self.assertEqual(len(value.bindings[0]), 53)
            tips = [row for row in value.bindings[0] if row[:2] == ('tip_cup', 'tip_cup')]
            self.assertEqual(len(tips), 1)
            self.assertIs(tips[0][2], stands[0].find_component_by_type(object).render_shapes[4].parts[0])
            counts = {role: sum(row[:2] == ('pipette', role) for row in value.bindings[0])
                      for role in value.definitions['pipette']['roles']}
            self.assertEqual(counts, {role: 1 for role in counts})
            reset(value)
            render.RenderTexture2D.assert_not_called()
            reset(value, [1], {'scheme_id': 'jade'})
            for i, rows in enumerate(value.bindings):
                textured = [(oid, role) for oid, role, _, mat, _ in rows
                            if mat.base_color_texture is texture]
                self.assertEqual(textured, [('pipette_stand', 'base_plate')] if i == 1 else [])
            reset(value, [0], {'scheme_id': 'coral'})
            render.RenderTexture2D.assert_called_once_with(
                str(value._plate_label_path), mipmap_levels=value._plate_label_levels)
            reset(value, [1])
            self.assertIs(value.bindings[0][0][3].base_color_texture, texture)
            self.assertIsNone(value.bindings[1][0][3].base_color_texture)
            # A shared environment material is rejected before storing bindings.
            stands[1].find_component_by_type(object).render_shapes[0].parts[0].material = value.bindings[0][0][3]
            with self.assertRaises(RuntimeError):
                value.bind(base, 1)

    def test_material_isolation_keeps_native_aliases_within_one_build_only(self):
        wall = IdentityNamespace(base_color=[.7, .9, 1., .94], roughness=.08, metallic=0.)
        rim = IdentityNamespace(base_color=[.7, .9, 1., .94], roughness=.08, metallic=0.)
        records = [SimpleNamespace(material=material) for material in (wall, wall, rim)]
        builder = SimpleNamespace(visual_records=records)
        builder.build_render_component = lambda: SimpleNamespace(render_shapes=[
            SimpleNamespace(parts=[SimpleNamespace(material=record.material)]) for record in records])
        render = SimpleNamespace(RenderMaterial=IdentityNamespace)
        with patch.dict(sys.modules, {'sapien': SimpleNamespace(render=render), 'sapien.render': render}):
            MODULE.PipetteAppearance.isolate_builder_materials(builder)
            first = builder.build_render_component()
            first_mats = [shape.parts[0].material for shape in first.render_shapes]
            self.assertIs(first_mats[0], first_mats[1])
            self.assertIsNot(first_mats[0], first_mats[2])
            self.assertIsNot(first_mats[0], wall)
            second = builder.build_render_component()
            second_mats = [shape.parts[0].material for shape in second.render_shapes]
            self.assertIs(second_mats[0], second_mats[1])
            self.assertTrue(all(first_mat is not second_mat for first_mat in first_mats for second_mat in second_mats))

    def test_repaired_pass_policy_is_identical_native_and_enabled_and_cup_only(self):
        spec = importlib.util.spec_from_file_location('pipette_rendering_test', ROOT / 'tasks/pipette_transfer/rendering.py')
        rendering = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rendering)
        render = SimpleNamespace(RenderBodyComponent=object)
        outputs = []
        for enabled in (False, True):
            cups = [SimpleNamespace(shading_mode=0, render_shapes=[SimpleNamespace(material={'alpha': 1.}) for _ in range(57)])
                    for _ in range(2)]
            tube = SimpleNamespace(shading_mode=0)
            originals = [copy.deepcopy([shape.material for shape in body.render_shapes]) for body in cups]
            base = SimpleNamespace(sample_cup=SimpleNamespace(_objs=[SimpleNamespace(
                find_component_by_type=lambda cls, body=body: body) for body in cups]),
                test_tube=tube, _pipette_appearance=object() if enabled else None)
            pipeline = rendering.PipetteRendering.__new__(rendering.PipetteRendering)
            pipeline.identity = {}
            with patch.dict(sys.modules, {'sapien': SimpleNamespace(render=render), 'sapien.render': render}):
                pipeline.prepare_objects(base)
            self.assertEqual([body.shading_mode for body in cups], [1, 1])
            self.assertEqual(tube.shading_mode, 0)
            self.assertEqual(originals, [[shape.material for shape in body.render_shapes] for body in cups])
            outputs.append(pipeline.identity)
        self.assertEqual(outputs[0], outputs[1])


if __name__ == '__main__':
    unittest.main()
