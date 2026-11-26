"""CPU regression tests for furniture scheme selection and reset isolation."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'furniture_appearance_under_test', ROOT / 'tasks/furniture_assembly/appearance.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
FINISH_SPEC = importlib.util.spec_from_file_location(
    'furniture_finishes_under_test', ROOT / 'tasks/furniture_assembly/finishes.py')
FINISHES = importlib.util.module_from_spec(FINISH_SPEC)
FINISH_SPEC.loader.exec_module(FINISHES)


def make_adapter(config):
    adapter = MODULE.FurnitureAppearance({'enabled': True, **config}, 2)
    for env_id in range(2):
        bindings = []
        for object_id, role in [('flat_panel', 'face'), ('flat_panel', 'label'),
                                ('screw', 'grip'), ('screw', 'reference')]:
            native = {'base_color': [.17 + env_id * .1, .27, .37, 1.],
                      'roughness': .67, 'metallic': .13}
            material = SimpleNamespace(**copy.deepcopy(native), specular=.29)
            part = SimpleNamespace(material=material)
            bindings.append((object_id, role, part, material, native))
        adapter.bindings[env_id] = bindings
    return adapter


def reset(adapter, indices, override=None):
    options = {} if override is None else {'furniture_appearance': override}
    adapter.finish_reset(np.asarray(indices, dtype=int), options)


def material_state(adapter, env_id):
    return [
        (object_id, role, {key: copy.deepcopy(getattr(material, key))
                          for key in MODULE.FIELDS})
        for object_id, role, _, material, _ in adapter.bindings[env_id]
    ]


class FurnitureAppearanceTests(unittest.TestCase):
    def test_configuration_override_precedence(self):
        adapter = make_adapter({'scheme_id': 'original',
                                'per_env': {'1': {'scheme_id': 'variant_1'}}})
        reset(adapter, [0, 1])
        self.assertEqual(adapter.schemes, ['original', 'variant_1'])
        np.testing.assert_allclose(adapter.bindings[1][0][3].base_color,
                                   adapter.scheme_parameters('flat_panel', 'variant_1')['face']['base_color'])

        reset(adapter, [1], {'scheme_id': 'variant_2'})
        self.assertEqual(adapter.schemes, ['original', 'variant_2'])
        np.testing.assert_allclose(adapter.bindings[1][0][3].base_color,
                                   adapter.scheme_parameters('flat_panel', 'variant_2')['face']['base_color'])

        reset(adapter, [1], {'scheme_id': 'variant_1',
                             'per_env': {'1': {'scheme_id': 'original'}}})
        self.assertEqual(adapter.schemes, ['original', 'original'])
        self.assertEqual(adapter.episodes, [1, 3])
        self.assertEqual(adapter.records[-1], {
            'env_idx': 1, 'episode_index': 3, 'scheme_id': 'original',
            'catalog_version': 'furniture-appearance-v2'})

    def test_wood_profiles_differ_at_equal_color_and_plain_finish_is_uniform(self):
        def image(profile):
            return FINISHES.panel_albedo(profile, (.7, .6, .55, 1.), (0, 0), (.19, .095), 384, 288)

        plain = image('plain')
        np.testing.assert_array_equal(plain, np.broadcast_to(plain[0, 0], plain.shape))
        grains = []
        for profile in FINISHES.WOOD_FINISHES:
            pixels = image(profile)
            face = pixels[96:192, 96:192]
            self.assertGreater(float(np.ptp(face[:, :, 0])), .1, profile)
            np.testing.assert_array_equal(pixels[:, :, 3], 1)
            self.assertTrue(all(not np.array_equal(face, previous) for previous in grains), profile)
            self.assertIs(pixels, image(profile))
            grains.append(face)

    def test_local_reset_reuses_panel_texture_and_restores_native_pixels(self):
        class Texture:
            def __init__(self, array, **descriptor):
                self.array = array.copy()

            def upload(self, pixels):
                self.array = pixels.copy()

        adapter = make_adapter({'scheme_id': 'variant_1'})
        shape = SimpleNamespace(local_pose=SimpleNamespace(p=(0, 0, -.004)), half_size=(.19, .095, .005))
        native = []
        for env_id, bindings in enumerate(adapter.bindings):
            material = bindings[0][3]
            material.base_color_texture = None
            surface = FINISHES.PanelSurface(material, shape, Texture)
            adapter.panel_surfaces[env_id] = (surface,)
            native.append(surface.texture.array.copy())

        first, second = [row[0] for row in adapter.panel_surfaces]
        self.assertIsNot(first.texture, second.texture)
        first_texture, second_texture = first.texture, second.texture
        reset(adapter, [0, 1])
        self.assertFalse(np.array_equal(first.texture.array, native[0]))
        self.assertFalse(np.array_equal(second.texture.array, native[1]))
        frozen_pixels = first.texture.array.copy()
        reset(adapter, [1], {'scheme_id': 'variant_2'})
        np.testing.assert_array_equal(second.texture.array,
                                      np.broadcast_to(second.texture.array[0, 0], second.texture.array.shape))
        reset(adapter, [1], {'scheme_id': 'original'})
        np.testing.assert_array_equal(second.texture.array, native[1])
        self.assertIs(first.material.base_color_texture, first_texture)
        self.assertIs(second.material.base_color_texture, second_texture)
        np.testing.assert_array_equal(first.texture.array, frozen_pixels)

    def test_fixed_reset_leaves_unselected_materials_and_records_unchanged(self):
        adapter = make_adapter({'scheme_id': 'variant_1'})
        reset(adapter, [0, 1])
        before = material_state(adapter, 0)
        records = copy.deepcopy([row for row in adapter.records if row['env_idx'] == 0])
        reset(adapter, [1], {'scheme_id': 'variant_2'})
        self.assertEqual(material_state(adapter, 0), before)
        self.assertEqual([row for row in adapter.records if row['env_idx'] == 0], records)
        self.assertEqual(adapter.schemes, ['variant_1', 'variant_2'])
        self.assertEqual(adapter.episodes, [1, 2])

    def test_random_local_reset_preserves_unselected_rng(self):
        config = {'mode': 'random_choice', 'seed': 71,
                  'scheme_ids': ['original', 'variant_1', 'variant_2']}
        adapter, control = make_adapter(config), make_adapter(config)
        reset(adapter, [0, 1])
        reset(control, [0, 1])
        rng = copy.deepcopy(adapter.rng[0].bit_generator.state)
        materials = material_state(adapter, 0)
        records = copy.deepcopy([row for row in adapter.records if row['env_idx'] == 0])
        for _ in range(32):
            reset(adapter, [1])
        self.assertEqual(adapter.rng[0].bit_generator.state, rng)
        self.assertEqual(material_state(adapter, 0), materials)
        self.assertEqual([row for row in adapter.records if row['env_idx'] == 0], records)
        reset(adapter, [0])
        reset(control, [0])
        self.assertEqual(adapter.schemes[0], control.schemes[0])
        self.assertEqual(adapter.rng[0].bit_generator.state, control.rng[0].bit_generator.state)

    def test_original_restores_captured_fields_and_preserves_protected_roles(self):
        adapter = make_adapter({'scheme_id': 'variant_1'})
        native = [material_state(adapter, i) for i in range(2)]
        reset(adapter, [0, 1])
        for env_id in range(2):
            for row_index in (1, 3):
                self.assertEqual(material_state(adapter, env_id)[row_index], native[env_id][row_index])
            self.assertNotEqual(material_state(adapter, env_id)[0], native[env_id][0])
        reset(adapter, [1], {'scheme_id': 'original'})
        self.assertEqual(material_state(adapter, 1), native[1])
        self.assertEqual(adapter.schemes, ['variant_1', 'original'])
        for _, _, _, material, _ in adapter.bindings[1]:
            self.assertEqual(material.specular, .29)

    def test_same_seed_and_reset_sequence_reproduce_32_rounds(self):
        config = {'mode': 'random_choice', 'seed': 71,
                  'scheme_ids': ['original', 'variant_1', 'variant_2']}
        first, second = make_adapter(config), make_adapter(config)
        sequence = ([0, 1], [1], [0], [1, 0]) * 8
        traces = [[], []]
        for selected in sequence:
            for adapter, trace in zip((first, second), traces):
                reset(adapter, selected)
                trace.append((list(adapter.schemes), list(adapter.episodes)))
        self.assertEqual(traces[0], traces[1])
        self.assertEqual(first.records, second.records)
        for left, right in zip(first.rng, second.rng):
            self.assertEqual(left.bit_generator.state, right.bit_generator.state)

    def test_invalid_selection_rejected_without_material_or_record_update(self):
        for config in ({'scheme_id': 'missing'},
                       {'mode': 'random_choice', 'scheme_ids': []},
                       {'mode': 'random_choice', 'scheme_ids': ['missing']}):
            with self.subTest(config=config):
                adapter = make_adapter(config)
                before = material_state(adapter, 1)
                with self.assertRaises(ValueError):
                    reset(adapter, [1])
                self.assertEqual(material_state(adapter, 1), before)
                self.assertEqual(adapter.records, [])
                self.assertEqual(adapter.episodes, [0, 0])

    def test_later_invalid_request_preserves_all_materials_records_and_rng(self):
        for invalid in ({'mode': 'explicit', 'scheme_id': 'missing'}, {'mode': 'unsupported'},
                        {'mode': 'random_choice', 'scheme_ids': []},
                        {'mode': 'random_choice', 'scheme_ids': ['missing']}):
            with self.subTest(invalid=invalid):
                adapter = make_adapter({'mode': 'random_choice', 'seed': 71,
                    'scheme_ids': ['original', 'variant_1', 'variant_2'], 'per_env': {'1': invalid}})
                before = [material_state(adapter, i) for i in range(2)]
                rng = [copy.deepcopy(value.bit_generator.state) for value in adapter.rng]
                with self.assertRaises(ValueError):
                    reset(adapter, [0, 1])
                self.assertEqual([material_state(adapter, i) for i in range(2)], before)
                self.assertEqual([value.bit_generator.state for value in adapter.rng], rng)
                self.assertEqual(adapter.records, [])
                self.assertEqual(adapter.episodes, [0, 0])
                self.assertEqual(adapter.schemes, ['original', 'original'])

    def test_later_unbound_environment_preserves_earlier_random_stream(self):
        adapter = make_adapter({'mode': 'random_choice', 'seed': 71,
                                'scheme_ids': ['original', 'variant_1']})
        before = material_state(adapter, 0)
        rng = copy.deepcopy(adapter.rng[0].bit_generator.state)
        adapter.bindings[1] = None
        with self.assertRaises(RuntimeError):
            reset(adapter, [0, 1])
        self.assertEqual(material_state(adapter, 0), before)
        self.assertEqual(adapter.rng[0].bit_generator.state, rng)
        self.assertEqual(adapter.records, [])


if __name__ == '__main__':
    unittest.main()
