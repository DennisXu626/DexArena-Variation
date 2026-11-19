"""CPU-only capture-contract spies; no simulator, renderer or production runs."""
import copy
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('nut_evidence_cpu', ROOT / 'tools/variation/nut_bolt_runtime_evidence.py')
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


def native_material():
    values = {name: None for name in E.MATERIAL_FIELDS}
    values.update(base_color=[.1, .2, .3, 1.], roughness=.5, metallic=.6,
                  specular=.2, emission=[0., 0., 0., 1.], ior=1.5,
                  transmission=0., transmission_roughness=.1)
    return SimpleNamespace(**values)


class RawEvidenceTests(unittest.TestCase):
    def test_complete_canonical_pbr_and_explicit_null_textures(self):
        value = E.material_values(SimpleNamespace(plain=copy.deepcopy), native_material(), {'entity': 'bolt'})
        self.assertEqual(set(value), set(E.MATERIAL_FIELDS))
        self.assertEqual(len(value), 14)
        self.assertTrue(all(value[name] is None for name in E.MATERIAL_FIELDS if name.endswith('_texture')))

    def test_missing_pbr_field_fails(self):
        material = native_material()
        del material.specular
        with self.assertRaises(AttributeError):
            E.material_values(SimpleNamespace(plain=copy.deepcopy), material, {})

    def test_real_texture_file_and_sampling_metadata(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / 'texture.bin'
            path.write_bytes(b'actual-file-content')
            material = native_material()
            material.base_color_texture = SimpleNamespace(filename=str(path), width=8, height=4,
                mipmap_levels=2, channels=4, filter_mode='linear', address_mode='repeat',
                is_srgb=True, format='R8G8B8A8Unorm')
            owner = {'env_idx': 0, 'entity': 'actual_actor', 'shape': 2, 'part': 1}
            value = E.material_values(SimpleNamespace(plain=copy.deepcopy), material, owner)['base_color_texture']
            self.assertEqual(value['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(value['asset_ref'], path.relative_to(ROOT).as_posix())
            self.assertEqual(value['channels'], 4)
            self.assertEqual(value['filter_mode'], 'linear')
            self.assertEqual(value['address_mode'], 'repeat')
            self.assertIs(value['is_srgb'], True)
            self.assertEqual(value['owner'], {**owner, 'field': 'base_color_texture'})

    def test_embedded_texture_has_owner_without_fabricated_file_digest(self):
        material = native_material()
        pixels = np.arange(4 * 8 * 3, dtype=np.uint8).reshape(4, 8, 3)
        material.normal_texture = SimpleNamespace(filename='', width=8, height=4,
            mipmap_levels=1, channels=3, filter_mode='nearest', address_mode='edge',
            is_srgb=False, format='R8G8B8Unorm', download=lambda: pixels)
        asset_sha = hashlib.sha256(b'table GLB fixture').hexdigest()
        owner = {'entity': 'scene-0_table-workspace', 'source_asset': {'asset_ref': E.TABLE_ASSET, 'sha256': asset_sha}}
        value = E.material_values(SimpleNamespace(plain=copy.deepcopy), material, owner)['normal_texture']
        self.assertIsNone(value['sha256'])
        self.assertEqual(value['asset_ref'], E.TABLE_ASSET)
        self.assertEqual(value['source_kind'], 'embedded_glb')
        self.assertEqual(value['owner']['source_asset'], owner['source_asset'])
        self.assertEqual(value['embedded_asset_sha256'], asset_sha)
        self.assertEqual(value['data_sha256'], hashlib.sha256(pixels.tobytes()).hexdigest())
        self.assertEqual(value['data_shape'], [4, 8, 3])
        self.assertEqual(value['data_dtype'], 'uint8')

    def test_missing_named_texture_fails(self):
        material = native_material()
        material.base_color_texture = SimpleNamespace(filename=str(ROOT / 'missing_named_texture_for_test.png'))
        with self.assertRaises(FileNotFoundError):
            E.material_values(SimpleNamespace(plain=copy.deepcopy), material, {})

    def test_material_readback_is_frozen_before_later_restore(self):
        material = native_material()
        measured = E.material_values(SimpleNamespace(plain=copy.deepcopy), material, {})
        material.base_color[0] = .9
        material.roughness = .1
        self.assertEqual(measured['base_color'][0], .1)
        self.assertEqual(measured['roughness'], .5)

    def test_roles_use_actual_slot_positions_including_protected_parts(self):
        a, b = SimpleNamespace(material=object()), SimpleNamespace(material=object())
        base = SimpleNamespace(_nut_bolt_appearance=SimpleNamespace(bindings=[[
            ('bolt', 'shaft', a, a.material, {}), ('bolt', 'tip', b, b.material, {})]]))
        slots = [('unbound_robot', 0, 0, object()), ('bolt', 0, 0, a), ('bolt', 1, 0, b)]
        roles = E.material_roles(SimpleNamespace(material_slots=lambda base: [slots]), base)
        self.assertEqual(roles, {'/0/1/material': {'object_id': 'bolt', 'role': 'shaft'},
                                 '/0/2/material': {'object_id': 'bolt', 'role': 'tip'}})

    def fake_controller(self):
        import torch
        controller = SimpleNamespace(_target_qpos=torch.zeros((2, 3)), qpos=torch.zeros((2, 3)))
        base = SimpleNamespace(num_envs=2, device='cpu', _sim_steps_per_control=20,
            agent=SimpleNamespace(controller=controller), forces=torch.zeros((2, 3)), elapsed=torch.zeros(2, dtype=torch.int32))
        def snapshot(base):
            return {'/joint_targets/robot/qpos': controller.qpos.clone(),
                '/joint_targets/robot/position_target': controller._target_qpos.clone(),
                '/joint_targets/robot/qf': base.forces.clone(), '/elapsed_steps': base.elapsed.clone()}
        common = SimpleNamespace(snapshot=snapshot, plain=lambda value: value.tolist(),
            controller_state=lambda base, env: {'controller': {'_target_qpos': controller._target_qpos[env].tolist()}},
            joint_targets=lambda base: {'robot': {'qf': base.forces,
                'qpos': controller.qpos, 'position_target': controller._target_qpos}})
        return torch, base, common

    def test_priming_saves_real_before_after_and_both_private_controllers(self):
        torch, base, common = self.fake_controller()
        def native_prime(base):
            base.agent.controller._target_qpos[:] = torch.tensor([[1., 2., 3.], [4., 5., 6.]])
            base.forces[:] = torch.tensor([[.1, .2, .3], [.4, .5, .6]])
            return {'action': [[1., 2., 3.], [4., 5., 6.]]}
        with tempfile.TemporaryDirectory() as directory:
            row = E.prime(common, base, Path(directory), 'prime', native_prime)
            raw = torch.load(Path(directory) / row['state_evidence'], weights_only=True)
            self.assertEqual(set(raw['controller_after']), {'0', '1'})
            for env in (0, 1):
                self.assertTrue(row['nontrivial_targets_all_envs'][str(env)]['controller'])
                self.assertEqual(row['controller_all_envs'][str(env)], raw['controller_after'][str(env)])
                self.assertEqual(row['generalized_forces_all_envs'][str(env)], raw['after']['/joint_targets/robot/qf'][env].tolist())
            self.assertTrue(torch.equal(raw['before']['/joint_targets/robot/qpos'], raw['after']['/joint_targets/robot/qpos']))

    def test_distinct_step_contexts_count_once_and_freeze_real_action(self):
        torch, base, common = self.fake_controller()
        class Environment:
            unwrapped = base
            def step(self, action):
                base.elapsed += 1
                base.agent.controller.qpos += action
                return None, None, None, None, {'actual_step': True}
        result = {'control_steps': 0, 'physics_steps': 0, 'checks': {}}
        with tempfile.TemporaryDirectory() as directory:
            for context in ('native', 'appearance'):
                E.step(common, Environment(), {'action': [[1., 2., 3.], [4., 5., 6.]]},
                       Path(directory), result, context)
                raw = torch.load(Path(directory) / (context + '_step.pt'), weights_only=True)
                self.assertEqual(raw['context'], context)
                self.assertTrue(torch.equal(raw['after']['/elapsed_steps'], raw['before']['/elapsed_steps'] + 1))
            self.assertEqual(result['control_steps'], 2)
            self.assertEqual(result['physics_steps'], 40)
            self.assertEqual({row['evidence'] for row in result['checks']['step_evidence']},
                             {'native_step.pt', 'appearance_step.pt'})

    def test_native_helper_thin_wrapper_preserves_actual_reset_associations(self):
        import numpy as np
        torch, base, spies = self.fake_controller()
        spec = importlib.util.spec_from_file_location('native_helper_cpu_spy', ROOT / 'tools/variation/check_furniture_appearance.py')
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
        common.torch, common.np = torch, np
        for name in ('snapshot', 'plain', 'controller_state', 'joint_targets'):
            setattr(common, name, getattr(spies, name))
        common.materials = lambda base: [[{'slot': 0}], [{'slot': 0}]]
        common.physical = lambda base: {'scenes': [[], []], 'joints': {}}
        common.controller_counters = lambda base: {'controller': {'scope': 'shared', 'value': 0, 'interpolation_enabled': False}}
        common.task_rng = lambda base, env: {'batched_episode_rng': [env, 71], 'episode_rng_alias': [0, 71]}
        common.capture = lambda env, info: {'camera': np.arange(12, dtype=np.uint8).reshape(2, 1, 2, 3)}
        common.image_changes = lambda *args, **kwargs: {'camera': {'changed_values': 0}}
        common.save_image_pairs = lambda *args, **kwargs: None
        primed_envs = []
        def native_prime(base, env_id=0):
            primed_envs.append(env_id)
            base.agent.controller._target_qpos[:] = 1
            base.forces[:] = .5
            return {'action': [[1., 1., 1.], [1., 1., 1.]]}
        common.prime_controller_target = native_prime
        class Environment:
            unwrapped = base
            def step(self, action):
                base.elapsed += 1
                base.agent.controller.qpos += action * .1
                return None, None, None, None, {}
        selected_ids = []
        def reset(seed=None, options=None):
            selected = options['env_idx']
            base.agent.controller.qpos[selected] = .5
            base.agent.controller._target_qpos[selected] = .5
            base.elapsed[selected] = 0
            selected_ids.append('actual_selected_' + str(len(selected_ids)) + '.json')
            return None, {}
        result = {'control_steps': 0, 'physics_steps': 0, 'checks': {}}
        with tempfile.TemporaryDirectory() as directory:
            control = E.native_local(common, Environment(), {}, Path(directory), reset,
                lambda: selected_ids[-1], result, common.dump)
            self.assertIs(common.prime_controller_target, native_prime)
            self.assertEqual(primed_envs, [0, 0])
            self.assertEqual([row['selected_state_evidence'] for row in control['rounds']], selected_ids)
            self.assertEqual(result['control_steps'], 1)
            self.assertEqual(result['physics_steps'], 20)
            first = torch.load(Path(directory) / control['rounds'][0]['state_evidence'], weights_only=True)
            second = torch.load(Path(directory) / control['rounds'][1]['state_evidence'], weights_only=True)
            step = torch.load(Path(directory) / 'native_step.pt', weights_only=True)
            self.assertTrue(torch.equal(step['before']['/joint_targets/robot/qpos'], first['after']['/joint_targets/robot/qpos']))
            for key in step['after']:
                self.assertTrue(torch.equal(step['after'][key], second['before'][key]))


if __name__ == '__main__':
    unittest.main()
