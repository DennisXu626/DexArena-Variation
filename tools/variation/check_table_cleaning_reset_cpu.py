"""CPU regression of real reset entry/selector using AST-loaded code and spies.

No simulator, torch, SAPIEN, GPU or task registration is imported. Only external
BaseEnv/render objects are replaced; the tested reset and selector come from source.
"""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np
from table_cleaning_contract import check_catalog, check_materials

ROOT = Path(__file__).resolve().parents[2]


def load_code():
    appearance_path = ROOT / "tasks/table_cleaning/appearance.py"
    task_path = ROOT / "tasks/table_cleaning/table_cleaning_long.py"
    cls, = [n for n in ast.parse(appearance_path.read_text(encoding="utf-8")).body
            if isinstance(n, ast.ClassDef) and n.name == "CleaningAppearance"]
    namespace = {"json": json, "np": np, "CATALOG": ROOT / "tasks/assets/variation/table_cleaning/v1/catalog.json"}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(appearance_path), "exec"), namespace)
    task, = [n for n in ast.parse(task_path.read_text(encoding="utf-8")).body
             if isinstance(n, ast.ClassDef) and n.name == "TableCleanBase"]
    reset, = [n for n in task.body if isinstance(n, ast.FunctionDef) and n.name == "reset"]
    public = ast.ClassDef(name="PublicReset", bases=[ast.Name(id="SpyBase", ctx=ast.Load())],
                          keywords=[], body=[reset], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[public], type_ignores=[]))
    namespace.update(SpyBase=SpyBase, torch=SimpleNamespace(
        ones=lambda n, **kw: np.ones(n, dtype=bool).view(Array), bool=bool))
    exec(compile(module, str(task_path), "exec"), namespace)
    return namespace["CleaningAppearance"], namespace["PublicReset"]


class Array(np.ndarray):
    def clone(self):
        return self.copy()


class SpyBase:
    def reset(self, seed=None, options=None):
        self.events.extend(["base_reset", "random_draw", "state_write"])
        self.stage[:] = 9  # Deliberately observable external side effect.
        if self.cleaning_appearance is not None:
            indices = (options or {}).get("env_idx", range(self.num_envs))
            self.cleaning_appearance.reset(indices, options or {})
        return "base_result"


class Texture:
    def __init__(self, pixels):
        self.pixels = pixels.copy()

    def upload(self, pixels):
        self.pixels = pixels.copy()


def adapter(config, count=2):
    item = Appearance(config, count)
    item.pixels = {"original": np.array([[[120, 130, 140, 255], [230, 200, 180, 128]]], dtype=np.uint8)}
    for index in range(count):
        body = SimpleNamespace(base_color=[0., .3, 1., 1.], roughness=.2)
        frame = SimpleNamespace(base_color=[.1, .1, .1, 1.])
        textures = [Texture(item.pixels["original"]) for _ in range(3)]
        item.bindings[index] = (body, frame, textures, body.base_color.copy(), body.roughness, frame.base_color.copy())
    return item


def public(config, count=2):
    env = PublicReset()
    env.num_envs, env.device, env.events = count, "cpu", []
    env.FLAG_NAMES = ("f_picked", "f_grasp_pan", "f_poured", "f_stow_pan")
    for name in ("stage", "hold", "success_latched", *env.FLAG_NAMES):
        setattr(env, name, np.arange(count).view(Array))
    env.cleaning_appearance = adapter(config, count) if config is not None else None
    return env


def snapshot(item, index):
    body, frame, textures, *_ = item.bindings[index]
    result = {"pan/0/1": {"color": list(body.base_color), "roughness": body.roughness, "metallic": 0., "base_color_texture": None},
              "bin/0/1": {"color": list(frame.base_color), "roughness": .5, "metallic": 0., "base_color_texture": None}}
    for i, texture in enumerate(textures):
        p = texture.pixels
        result[f"debris_{i}/0/0"] = {"color": [1., 1., 1., 1.], "roughness": .8, "metallic": 0.,
            "base_color_texture": [True, [list(p.shape), str(p.dtype), hashlib.sha256(p.tobytes()).hexdigest()]]}
    return result


Appearance, PublicReset = load_code()


class ResetTests(unittest.TestCase):
    def reject(self, env, options):
        before = env.stage.copy()
        records = copy.deepcopy(env.cleaning_appearance.records)
        materials = [snapshot(env.cleaning_appearance, i) for i in range(env.num_envs)]
        with self.assertRaisesRegex(ValueError, "Unknown Table Cleaning"):
            env.reset(seed=7, options=options)
        self.assertEqual(env.events, [])
        np.testing.assert_array_equal(before, env.stage)
        self.assertEqual(records, env.cleaning_appearance.records)
        self.assertEqual(materials, [snapshot(env.cleaning_appearance, i) for i in range(env.num_envs)])

    def test_last_invalid_full_reset(self):
        self.reject(public({}), {"table_cleaning_appearance": {"per_env": {
            "0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "wrong_id"}}}})

    def test_last_invalid_local_reset(self):
        self.reject(public({}), {"env_idx": np.array([1]), "table_cleaning_appearance": {"scheme_id": "wrong_id"}})

    def test_invalid_constructor_config_at_public_reset(self):
        self.reject(public({"per_env": {"1": {"scheme_id": "wrong_id"}}}), {})

    def test_invalid_single_environment(self):
        self.reject(public({}, 1), {"table_cleaning_appearance": {"scheme_id": "wrong_id"}})

    def test_override_order_and_legal_public_reset(self):
        env = public({"scheme_id": "wrong_id", "per_env": {"0": {"scheme_id": "variant_2"}}})
        self.assertEqual(env.reset(options={"table_cleaning_appearance": {
            "scheme_id": "original", "per_env": {"0": {"scheme_id": "variant_1"}}}}), "base_result")
        self.assertEqual([r["scheme_id"] for r in env.cleaning_appearance.records], ["variant_1", "original"])
        self.assertEqual(env.events.count("base_reset"), 1)

    def test_config_per_env_over_global(self):
        item = adapter({"scheme_id": "variant_1", "per_env": {"1": {"scheme_id": "variant_2"}}})
        self.assertEqual(item.resolve_requests([0, 1], {}), [(0, "variant_1"), (1, "variant_2")])

    def test_local_reset_ignores_unselected_invalid_config(self):
        env = public({"per_env": {"0": {"scheme_id": "wrong_id"}}})
        env.reset(options={"env_idx": np.array([1]), "table_cleaning_appearance": {"scheme_id": "variant_2"}})
        self.assertEqual(env.stage[0], 0)
        self.assertIsNone(env.cleaning_appearance.records[0])
        self.assertEqual(env.cleaning_appearance.records[1]["scheme_id"], "variant_2")

    def test_disabled_path_delegates(self):
        env = public(None)
        self.assertEqual(env.reset(options={"table_cleaning_appearance": {"scheme_id": "wrong_id"}}), "base_result")
        self.assertEqual(env.events.count("base_reset"), 1)

    def test_actual_apply_two_ids_and_restore(self):
        item = adapter({"per_env": {"0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "variant_2"}}})
        base = [snapshot(item, i) for i in (0, 1)]
        source = item.pixels["original"].copy()
        check_catalog(item.catalog)
        item.reset([0, 1], {})
        for i, scheme in enumerate(("variant_1", "variant_2")):
            check_materials(base[i], snapshot(item, i), scheme, source)
        keep = snapshot(item, 0)
        item.reset([1], {"table_cleaning_appearance": {"scheme_id": "original"}})
        check_materials(base[1], snapshot(item, 1), "original", source)
        self.assertEqual(keep, snapshot(item, 0))
        np.testing.assert_array_equal(source, item.pixels["original"])

    def test_swapped_legal_catalog_is_rejected(self):
        catalog = adapter({}).catalog
        schemes = catalog["schemes"]
        schemes["variant_1"], schemes["variant_2"] = schemes["variant_2"], schemes["variant_1"]
        with self.assertRaises(AssertionError):
            check_catalog(catalog)

    def test_swapped_actual_materials_are_rejected(self):
        item = adapter({"scheme_id": "variant_2"})
        base = snapshot(item, 0)
        item.reset([0], {})
        with self.assertRaises(AssertionError):
            check_materials(base, snapshot(item, 0), "variant_1", item.pixels["original"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ResetTests))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"status": "passed" if result.wasSuccessful() else "failed", "tests": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors), "platform": "CPU; AST-loaded real methods; external BaseEnv/render spies",
            "invalid_request_base_calls": 0 if result.wasSuccessful() else None,
            "scope": "explicit modes only; no simulation or GPU; no claim of measured physical state on error"}, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
