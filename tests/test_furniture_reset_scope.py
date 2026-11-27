"""CPU-only reset-scope tests; fake routing does not validate PhysX internals."""
import ast
import copy
import importlib.util
from importlib import metadata
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'furniture_reset_scope_under_test', ROOT / 'tasks/furniture_assembly/reset_scope.py')
MODULE = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {'sapien': SimpleNamespace(CudaArray=None)}):
    SPEC.loader.exec_module(MODULE)

APPLY = ['gpu_apply_rigid_dynamic_data'] + [
    'gpu_apply_articulation_' + field for field in
    ('qpos', 'qvel', 'qf', 'root_pose', 'root_velocity', 'target_position', 'target_velocity')]


class FakeCudaArray:
    def __init__(self, tensor):
        self.tensor = tensor


class FakePx:
    def __init__(self, events):
        self.events, self.calls, self.fail_on = events, [], None

    def __getattr__(self, name):
        if name not in APPLY:
            raise AttributeError(name)

        def apply(indices):
            self.events.append(name)
            self.calls.append((name, indices.tensor.clone()))
            if name == self.fail_on:
                raise RuntimeError('mock PhysX apply failure')
        return apply


class FakeScene:
    def __init__(self):
        self.device, self.num_envs, self._needs_fetch = 'cpu', 2, False
        self._reset_mask = torch.ones(2, dtype=torch.bool)
        self.events = []
        self.px = FakePx(self.events)
        raw = lambda index: SimpleNamespace(gpu_index=index, gpu_pose_index=index + 1000)
        view = lambda kind, ids, indices: SimpleNamespace(
            px_body_type=kind, _scene_idxs=torch.tensor(ids), _bodies=[raw(i) for i in indices])
        self.actors = {'dynamic': view('dynamic', [0, 1], [11, 17]),
                       'alias': view('dynamic', [1], [17]),
                       'kinematic': view('kinematic', [1], [3]),
                       'static': SimpleNamespace(px_body_type='static',
                                                 _scene_idxs=torch.tensor([1]), _bodies=[object()])}
        self.articulations = {'rail': SimpleNamespace(_scene_idxs=torch.tensor([0, 1]),
                                                      _objs=[raw(31), raw(29)]),
                              'alias': SimpleNamespace(_scene_idxs=torch.tensor([1]), _objs=[raw(29)])}

    def _gpu_apply_all(self):
        assert not self._needs_fetch
        self.events.append('native_apply')
        self._needs_fetch = True

    def _gpu_fetch_all(self):
        assert self._needs_fetch
        self.events.append('fetch')
        self._needs_fetch = False


class FakeController:
    def __init__(self, scene, offset=0):
        self.scene, self.fail = scene, False
        self.qpos = torch.tensor([[1.], [2.]]) + offset
        self._start_qpos, self._target_qpos = self.qpos + 10, self.qpos + 20

    def reset(self):
        self.mask_seen = self.scene._reset_mask.clone()
        self.reset_was_overridden = 'reset' in vars(self)
        for name in ('_start_qpos', '_target_qpos'):
            setattr(self, name, torch.where(self.mask_seen[:, None], self.qpos, getattr(self, name)))
        if self.fail:
            raise RuntimeError('mock controller reset failure')


class FakeNative:
    def __init__(self, gpu=False):
        self.scene, self.num_envs, self.gpu_sim_enabled = FakeScene(), 2, gpu
        self._reconfig_counter, self.reconfiguration_freq, self.parent_calls = 1, 0, 0
        self.counter, self.latch = torch.tensor([10, 20]), torch.zeros(2, dtype=torch.bool)
        self.agent = SimpleNamespace(controller=FakeController(self.scene))

    def reset(self, seed=None, options=None):
        self.parent_calls += 1
        self.forwarded = (seed, options)
        if hasattr(self, '_episode_rng'):
            self._episode_rng.uniform()
        if (options or {}).get('raise_parent'):
            raise RuntimeError('mock native reset failure')
        if self.gpu_sim_enabled:
            for _ in range(2):
                self.scene._gpu_apply_all()
                self.scene._gpu_fetch_all()
        if 'reset_to_env_states' in (options or {}):
            self.counter[options['env_idx']] = options['reset_to_env_states']['env_states']['counter']
        # BaseEnv restores an all-environment mask before the controller reset.
        self.native_reset_mask = self.scene._reset_mask = torch.ones(2, dtype=torch.bool)
        controllers = self.agent.controller
        for controller in controllers.values() if isinstance(controllers, dict) else [controllers]:
            controller.reset()
        return self.get_info()

    def get_info(self):
        self.scope_seen = self._furniture_reset_env_idx
        self.counter = self._reset_scoped_value(self.counter, self.counter + 1)
        self.latch |= self._reset_scoped_predicate(torch.ones(2, dtype=torch.bool))
        self.mask_count = len(self._furniture_reset_scope_masks)
        return {'counter': self.counter.clone()}


class FakeEnv(MODULE.FurnitureResetScopeMixin, FakeNative):
    pass


class ResetScopeTests(unittest.TestCase):
    def setUp(self):
        self.cuda = patch.object(MODULE.sapien, 'CudaArray', side_effect=FakeCudaArray)
        self.cuda.start()
        self.addCleanup(self.cuda.stop)
        capability = patch.object(MODULE.sapien, 'physx', create=True,
                                  new=SimpleNamespace(indexed_gpu_apply_patch_version=lambda: 1))
        capability.start()
        self.addCleanup(capability.stop)

    def assert_clean(self, env):
        self.assertNotIn('_gpu_apply_all', vars(env.scene))
        self.assertFalse(hasattr(env, '_furniture_reset_env_idx'))
        self.assertFalse(hasattr(env, '_furniture_reset_scope_masks'))

    def test_reset_mixin_forwards_other_families_layout(self):
        env = FakeEnv(gpu=False)
        options = {'env_idx': torch.tensor([1]), 'position_layout': {'1': {'socket_yaw_deg': 95}}}
        with patch.object(FakeNative, 'reset', autospec=True, return_value={}) as native_reset:
            env.reset(seed=3, options=options)
            native_reset.assert_called_once_with(env, seed=3, options=options)
        self.assert_clean(env)
        self.assertFalse(hasattr(env, '_furniture_position_rows'))

    def test_selected_indices_use_gpu_index_and_require_fetch(self):
        scene = FakeScene()
        MODULE._gpu_apply_selected(scene, torch.tensor([-1, 1, 1]))
        self.assertEqual([name for name, _ in scene.px.calls], APPLY)
        for name, indices in scene.px.calls:
            self.assertEqual(indices.tolist(), [3, 17] if name == APPLY[0] else [29])
            self.assertEqual(indices.dtype, torch.int32)
            self.assertEqual(indices.device.type, 'cpu')
            self.assertTrue(indices.is_contiguous())
        with self.assertRaises(AssertionError):
            MODULE._gpu_apply_selected(scene, [1])
        self.assertEqual(len(scene.px.calls), 8)
        scene._gpu_fetch_all()
        MODULE._gpu_apply_selected(scene, [1])
        self.assertEqual(scene.events, APPLY + ['fetch'] + APPLY)
        self.assertTrue(scene._needs_fetch)

    def test_gpu_capability_rejected_before_creating_or_applying_indices(self):
        for capability in (None, {}, {'indexed_gpu_apply_patch_version': 1},
                           {'indexed_gpu_apply_patch_version': lambda: 0},
                           {'indexed_gpu_apply_patch_version': lambda: 2}):
            with self.subTest(capability=capability):
                scene = FakeScene()
                physx = None if capability is None else SimpleNamespace(**capability)
                with patch.object(MODULE.sapien, 'physx', physx), patch.object(
                    MODULE.torch, 'tensor', side_effect=AssertionError('index allocation before capability check')):
                    with self.assertRaises(RuntimeError):
                        MODULE._gpu_apply_selected(scene, [1])
                self.assertEqual(scene.px.calls, [])
                self.assertFalse(scene._needs_fetch)
        with patch.object(MODULE.sapien, 'physx', SimpleNamespace()):
            for gpu in (False, True):
                env = FakeEnv(gpu=gpu)
                env.reset()
                self.assertEqual(env.counter.tolist(), [11, 21])

    def test_unsupported_partial_gpu_reset_rejects_before_any_scope_mutation(self):
        def forbid_scope_write(obj, name, value):
            if name in ('_furniture_reset_env_idx', '_furniture_reset_scope_masks',
                        '_gpu_apply_all', '_reset_mask', 'reset'):
                raise AssertionError('scope mutation before capability rejection: ' + name)
            object.__setattr__(obj, name, value)

        for existing in (False, True):
            for physx in (SimpleNamespace(), SimpleNamespace(indexed_gpu_apply_patch_version=lambda: 0)):
                with self.subTest(existing=existing, physx=physx):
                    env = FakeEnv(gpu=True)
                    controller = env.agent.controller
                    mask = env.scene._reset_mask = torch.tensor([True, False])
                    env._episode_rng = rng = np.random.RandomState(23)
                    before_rng = rng_state(rng)
                    if existing:
                        env._furniture_reset_env_idx = [0]
                        env._furniture_reset_scope_masks = {'saved': mask.clone()}
                        env.scene._gpu_apply_all = Mock(wraps=env.scene._gpu_apply_all)
                        controller.reset = Mock(wraps=controller.reset)
                    context = {name: getattr(env, name, MODULE._MISSING) for name in
                               ('_furniture_reset_env_idx', '_furniture_reset_scope_masks')}
                    methods = [(obj, name, vars(obj).get(name, MODULE._MISSING)) for obj, name in
                               ((env.scene, '_gpu_apply_all'), (controller, 'reset'))]
                    before = [(obj, name, getattr(obj, name).clone()) for obj, names in
                              ((env, ('counter', 'latch')), (controller, ('_start_qpos', '_target_qpos')))
                              for name in names]
                    indices = torch.tensor([1])
                    options = {'env_idx': indices, 'reconfigure': False}
                    with patch.object(MODULE.sapien, 'physx', physx), patch.object(
                        FakeEnv, '__setattr__', forbid_scope_write), patch.object(
                        FakeScene, '__setattr__', forbid_scope_write), patch.object(
                        FakeController, '__setattr__', forbid_scope_write):
                        with self.assertRaisesRegex(RuntimeError, 'indexed_gpu_apply_patch_version'):
                            env.reset(seed=7, options=options)
                    self.assertEqual(env.parent_calls, 0)
                    self.assertIs(env.scene._reset_mask, mask)
                    self.assertEqual(mask.tolist(), [True, False])
                    for name, value in context.items():
                        self.assertIs(getattr(env, name, MODULE._MISSING), value)
                    if existing:
                        self.assertEqual(env._furniture_reset_env_idx, [0])
                        self.assertTrue(torch.equal(env._furniture_reset_scope_masks['saved'], mask))
                    for obj, name, value in methods:
                        self.assertIs(vars(obj).get(name, MODULE._MISSING), value)
                        if value is not MODULE._MISSING:
                            value.assert_not_called()
                    for obj, name, value in before:
                        self.assertTrue(torch.equal(getattr(obj, name), value))
                    self.assertIs(env._episode_rng, rng)
                    self.assertEqual(rng_state(rng), before_rng)
                    self.assertEqual(set(options), {'env_idx', 'reconfigure'})
                    self.assertIs(options['env_idx'], indices)
                    self.assertEqual(indices.tolist(), [1])
                    self.assertIs(options['reconfigure'], False)
                    self.assertEqual(env.scene.events, [])
                    self.assertFalse(env.scene._needs_fetch)

    def test_empty_index_groups_are_not_applied(self):
        for rigid, articulation in ((False, False), (True, False), (False, True)):
            with self.subTest(rigid=rigid, articulation=articulation):
                scene = FakeScene()
                if not rigid:
                    scene.actors = {}
                if not articulation:
                    scene.articulations = {}
                MODULE._gpu_apply_selected(scene, [1])
                self.assertEqual(scene.events, (APPLY[:1] if rigid else []) +
                                 (APPLY[1:] if articulation else []))
                self.assertTrue(scene._needs_fetch)

    def test_cuda_sync_precedes_apply_and_runs_after_success_or_failure(self):
        native_tensor = torch.tensor

        class CudaLike:
            # CPU storage with only the interface consumed by the helper.
            is_cuda = True

            def __init__(self, *args, **kwargs):
                self.value = native_tensor(*args, **kwargs)

            def contiguous(self):
                return self

            def clone(self):
                return self.value.clone()

        for failure in (None, APPLY[1]):
            with self.subTest(failure=failure):
                scene = FakeScene()
                scene.px.fail_on = failure
                with patch.object(MODULE.torch, 'tensor', side_effect=CudaLike), patch.object(
                    MODULE.torch.cuda, 'synchronize', side_effect=lambda device: scene.events.append('sync')):
                    if failure:
                        with self.assertRaises(RuntimeError):
                            MODULE._gpu_apply_selected(scene, [1])
                    else:
                        MODULE._gpu_apply_selected(scene, [1])
                self.assertEqual(scene.events, ['sync'] + (APPLY[:2] if failure else APPLY) + ['sync'])

    def test_partial_gpu_wraps_both_apply_fetch_cycles_and_get_info(self):
        env = FakeEnv(gpu=True)
        indices, seed = torch.tensor([1]), object()
        options = {'env_idx': indices, 'reset_to_env_states': {'env_states': {'counter': 70}}}
        result = env.reset(seed=seed, options=options)
        self.assertEqual(env.scene.events, (APPLY + ['fetch']) * 2)
        self.assertEqual(result['counter'].tolist(), [10, 71])
        self.assertEqual(env.latch.tolist(), [False, True])
        self.assertIs(env.scope_seen, indices)
        self.assertIs(env.forwarded[0], seed)
        self.assertIs(env.forwarded[1], options)
        self.assertEqual(env.mask_count, 1)
        self.assertFalse(env.scene._needs_fetch)
        self.assert_clean(env)

    def test_duplicate_cpu_scope_and_helpers_return_to_normal_after_reset(self):
        env = FakeEnv()
        env.reset(options={'env_idx': [1, 1]})
        self.assertEqual(env.counter.tolist(), [10, 21])
        self.assertEqual(env.latch.tolist(), [False, True])
        self.assertEqual(env.mask_count, 1)
        self.assert_clean(env)
        proposed, predicate = env.counter + 1, torch.ones(2, dtype=torch.bool)
        self.assertIs(env._reset_scoped_value(env.counter, proposed), proposed)
        self.assertIs(env._reset_scoped_predicate(predicate), predicate)

    def test_partial_controller_reset_preserves_other_targets_and_ordinary_behavior(self):
        for gpu, dictionary in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(gpu=gpu, dictionary=dictionary):
                env = FakeEnv(gpu=gpu)
                controllers = [env.agent.controller, FakeController(env.scene, 100)] if dictionary else [env.agent.controller]
                env.agent.controller = dict(enumerate(controllers)) if dictionary else controllers[0]
                before = [(c._start_qpos.clone(), c._target_qpos.clone()) for c in controllers]
                env.reset(options={'env_idx': [1]})
                self.assertIs(env.scene._reset_mask, env.native_reset_mask)
                self.assertTrue(env.scene._reset_mask.all())
                for controller, (start, target) in zip(controllers, before):
                    self.assertEqual(controller.mask_seen.tolist(), [False, True])
                    self.assertTrue(controller.reset_was_overridden)
                    self.assertNotIn('reset', vars(controller))
                    for name, old in (('_start_qpos', start), ('_target_qpos', target)):
                        self.assertTrue(torch.equal(getattr(controller, name)[0], old[0]))
                        self.assertTrue(torch.equal(getattr(controller, name)[1], controller.qpos[1]))
                    controller.reset()  # A normal controller call must still reset every environment.
                    self.assertFalse(controller.reset_was_overridden)
                    self.assertTrue(torch.equal(controller._start_qpos, controller.qpos))
                    self.assertTrue(torch.equal(controller._target_qpos, controller.qpos))
                self.assert_clean(env)

    def test_controller_failure_restores_mask_and_instance_reset_attributes(self):
        for dictionary in (False, True):
            for overridden in (False, True):
                with self.subTest(dictionary=dictionary, overridden=overridden):
                    env = FakeEnv(gpu=True)
                    controllers = [env.agent.controller, FakeController(env.scene, 100)] if dictionary else [env.agent.controller]
                    env.agent.controller = dict(enumerate(controllers)) if dictionary else controllers[0]
                    originals = []
                    for controller in controllers:
                        if overridden:
                            controller.reset = Mock(wraps=controller.reset)
                        originals.append(vars(controller).get('reset'))
                    controllers[-1].fail = True
                    with self.assertRaisesRegex(RuntimeError, 'controller reset failure'):
                        env.reset(options={'env_idx': [1]})
                    self.assertIs(env.scene._reset_mask, env.native_reset_mask)
                    self.assertTrue(env.scene._reset_mask.all())
                    for controller, original in zip(controllers, originals):
                        self.assertIs(vars(controller).get('reset'), original)
                    self.assert_clean(env)

    def test_full_gpu_and_cpu_keep_native_apply(self):
        for gpu, indices in ((True, None), (True, [0, 1]), (True, [1, 0]), (False, [1])):
            with self.subTest(gpu=gpu, indices=indices):
                env = FakeEnv(gpu=gpu)
                options = None if indices is None else {'env_idx': indices}
                env.reset(options=options)
                self.assertEqual(env.scene.events, ['native_apply', 'fetch'] * 2 if gpu else [])
                self.assertEqual(env.scene.px.calls, [])
                self.assertEqual(env.counter.tolist(), [11, 21] if gpu else [10, 21])
                self.assertIs(env.scope_seen, indices)
                if gpu:
                    self.assertFalse(env.agent.controller.reset_was_overridden)
                    self.assertTrue(torch.equal(env.agent.controller._target_qpos, env.agent.controller.qpos))
                self.assert_clean(env)

    def test_failures_restore_instance_override_and_previous_scope(self):
        for failure in ('raise_parent', 'px'):
            for overridden in (False, True):
                with self.subTest(failure=failure, overridden=overridden):
                    env = FakeEnv(gpu=True)
                    previous_scope, previous_masks = [0], {}
                    env._furniture_reset_env_idx = previous_scope
                    env._furniture_reset_scope_masks = previous_masks
                    override = Mock(side_effect=env.scene._gpu_apply_all)
                    if overridden:
                        env.scene._gpu_apply_all = override
                    if failure == 'px':
                        env.scene.px.fail_on = APPLY[1]
                    with self.assertRaises(RuntimeError):
                        env.reset(options={'env_idx': [1], 'raise_parent': failure == 'raise_parent'})
                    self.assertIs(env._furniture_reset_env_idx, previous_scope)
                    self.assertIs(env._furniture_reset_scope_masks, previous_masks)
                    if overridden:
                        self.assertIs(vars(env.scene)['_gpu_apply_all'], override)
                    else:
                        self.assertNotIn('_gpu_apply_all', vars(env.scene))

    def test_partial_reconfiguration_rejected_before_native_reset(self):
        for gpu in (False, True):
            for automatic in (False, True):
                with self.subTest(gpu=gpu, automatic=automatic):
                    env = FakeEnv(gpu=gpu)
                    if automatic:
                        env._reconfig_counter, env.reconfiguration_freq = 0, 1
                    with self.assertRaises(RuntimeError):
                        env.reset(options={'env_idx': [1], 'reconfigure': not automatic})
                    self.assertEqual(env.parent_calls, 0)
                    self.assert_clean(env)


def source_function(filename, class_name, method, namespace, nested=None):
    """Compile only the actual method/nested rand AST, never task imports."""
    tree = ast.parse((ROOT / 'tasks/furniture_assembly' / filename).read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    node = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method)
    if nested:
        node = next(child for child in ast.walk(node) if isinstance(child, ast.FunctionDef) and child.name == nested)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(node)], type_ignores=[])),
                 filename, 'exec'), namespace)
    return namespace[node.name]


def actual_franka_reset_class():
    """Compile real reset and SDK base properties inside classes so super() works."""
    namespace = {'torch': torch}
    sdk = Path(metadata.distribution('mani_skill').locate_file('mani_skill/agents/controllers/base_controller.py'))
    sources = [(sdk, 'BaseController', {'qpos', 'device', 'reset'}, []),
               (ROOT / 'tasks/robots/franka_joint_impedance_controller.py',
                'FrankaJointImpedanceController', {'reset'}, [ast.Name(id='BaseController', ctx=ast.Load())])]
    for path, name, methods, bases in sources:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name))
        cls.bases, cls.keywords, cls.decorator_list = bases, [], []
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in methods]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), 'exec'), namespace)
    return namespace['FrankaJointImpedanceController']


class FrankaResetTests(unittest.TestCase):
    def test_actual_reset_scopes_existing_target_and_initializes_all_rows(self):
        cls = actual_franka_reset_class()
        for scenario, mask in (('partial', [False, True]), ('empty', [False, False]),
                               ('full', [True, True]), ('first', [False, True]), ('none', [False, True])):
            with self.subTest(scenario=scenario):
                controller = cls.__new__(cls)
                qpos = torch.arange(8, dtype=torch.float32).reshape(2, 4) / 10
                controller.articulation = SimpleNamespace(device='cpu', get_qpos=lambda: qpos)
                controller.active_joint_indices = torch.tensor([3, 1])
                controller.scene = SimpleNamespace(_reset_mask=torch.tensor(mask))
                controller.config = SimpleNamespace(stiffness=[240., 60.], force_limit=[87., 12.])
                old = controller.qpos + 3
                if scenario != 'first':
                    controller._target_qpos = None if scenario == 'none' else old
                expected = controller.qpos.clone()
                if scenario not in ('first', 'none'):
                    expected[~controller.scene._reset_mask] = old[~controller.scene._reset_mask]
                controller.reset()
                self.assertTrue(torch.equal(controller._target_qpos, expected))
                if scenario not in ('first', 'none'):
                    self.assertIs(controller._target_qpos, old)
                self.assertTrue(torch.equal(controller._kp, torch.tensor([[240., 60.]])))
                self.assertTrue(torch.equal(controller._force_limit, torch.tensor([[87., 12.]])))
                qpos.add_(1)
                self.assertTrue(torch.equal(controller._target_qpos, expected))


def rng_state(rng):
    state = rng.get_state()
    return (state[0], state[1].tobytes(), *state[2:])


def rng_env(num_envs):
    generators = [np.random.RandomState(101 + i) for i in range(num_envs)]
    return SimpleNamespace(num_envs=num_envs, device='cpu', _episode_rng=generators[0],
                           _batched_episode_rng=generators)


class NativeRandomStreamTests(unittest.TestCase):
    def test_actual_reset_agent_preserves_original_full_and_selected_streams(self):
        for count, indices in ((1, [0]), (2, None), (2, [0, 1]), (2, [1])):
            with self.subTest(count=count, indices=indices):
                env = rng_env(count)
                env.robot_uids, env.robot_init_qpos_noise = 'fake_mobile', .02
                robot = SimpleNamespace(get_active_joints=lambda: [SimpleNamespace(name=str(i)) for i in range(8)],
                                        set_root_pose=Mock())
                env.agent = SimpleNamespace(robot=robot, arm_joint_names=[str(i) for i in range(7)],
                                            keyframes={'rest': SimpleNamespace(qpos=np.zeros(8))})
                env.agent.reset = lambda q: setattr(env.agent, 'qpos', q.clone())
                function = source_function('furniture_assembly_lay_flat_panel.py', 'FurnitureAssemblyLayFlatPanelEnv',
                                          '_reset_agent', {'torch': torch, 'np': np, 'is_full_reset': MODULE.is_full_reset,
                                          'MOBILE_ROBOT_UIDS': ['fake_mobile'], 'ARM_INIT_QPOS': [.1] * 7,
                                          'ROBOT_ROOT_POSE': object(),
                                          'common': SimpleNamespace(to_tensor=lambda v, device: torch.as_tensor(v, device=device))})
                selected = None if indices is None else torch.tensor(indices)
                full = MODULE.is_full_reset(selected, count)
                batch = count if indices is None else len(indices)
                before_zero = rng_state(env._episode_rng)
                expected_rng = np.random.RandomState(101 if full else 102)
                noise = expected_rng.normal(0, .02, (batch, 7) if full else 7)
                expected = torch.full((batch, 7), .1, dtype=torch.float32)
                expected += torch.as_tensor(noise)
                function(env, batch, selected)
                self.assertTrue(torch.equal(env.agent.qpos[:, :7], expected))
                self.assertTrue(torch.equal(env.agent.qpos[:, 7], torch.zeros(batch)))
                self.assertEqual(rng_state(env._batched_episode_rng[0 if full else 1]), rng_state(expected_rng))
                if not full:
                    self.assertEqual(rng_state(env._episode_rng), before_zero)

    def test_actual_nested_rand_preserves_full_torch_and_partial_numpy_streams(self):
        sources = [('furniture_assembly_lay_flat_panel.py', 'FurnitureAssemblyLayFlatPanelEnv'),
                   ('furniture_assembly_insert_rail.py', 'FurnitureAssemblyInsertRailEnv')]
        for filename, cls in sources:
            for count, indices in ((1, [0]), (2, [0, 1]), (2, [1])):
                with self.subTest(filename=filename, count=count, indices=indices), torch.random.fork_rng(devices=[]):
                    env, selected = rng_env(count), torch.tensor(indices)
                    namespace = {'torch': torch, 'is_full_reset': MODULE.is_full_reset,
                                 'self': env, 'env_idx': selected, 'b': len(indices)}
                    rand = source_function(filename, cls, '_initialize_episode', namespace, nested='rand')
                    before = [rng_state(rng) for rng in env._batched_episode_rng]
                    torch.manual_seed(71)
                    scales = (.03, 0., .2)
                    if MODULE.is_full_reset(selected, count):
                        expected = [(torch.rand(len(indices)) * 2 - 1) * scale for scale in scales]
                        after = torch.get_rng_state().clone()
                        torch.manual_seed(71)
                        actual = [rand(scale) for scale in scales]
                        self.assertTrue(torch.equal(torch.get_rng_state(), after))
                        self.assertEqual([rng_state(rng) for rng in env._batched_episode_rng], before)
                    else:
                        state = torch.get_rng_state().clone()
                        reference = np.random.RandomState(102)
                        expected = [torch.tensor([reference.uniform(-1, 1) * scale]) for scale in scales]
                        actual = [rand(scale) for scale in scales]
                        self.assertEqual(rng_state(env._batched_episode_rng[0]), before[0])
                        self.assertEqual(rng_state(env._batched_episode_rng[1]), rng_state(reference))
                        self.assertTrue(torch.equal(torch.get_rng_state(), state))
                    self.assertTrue(all(torch.equal(a, b) for a, b in zip(actual, expected)))


if __name__ == '__main__':
    unittest.main()
