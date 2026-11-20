"""PR19-R1 real CPU Torch probes, with external simulator/render objects replaced.

Public reset comes from the actual JuiceResetMixin. Actual evaluate methods and
their state helpers are AST-loaded from the six production files without importing
SAPIEN or registering tasks. Geometric/contact inputs are controlled CPU fixtures.
"""
import argparse
import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FAMILY = ROOT / "tasks/juice_preparation"
FROZEN = "fc028483b5d865c05ee6e7e18b95975c836c9935"


def compile_nodes(nodes, namespace, filename):
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(filename), "exec",
                 flags=__import__("__future__").annotations.compiler_flag), namespace)


def numeric_constants(tree, ns):
    remaining = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id.isupper()]
    for _ in range(5):
        for node in remaining:
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                if any(isinstance(n, ast.Call) and not (
                    isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "np" and n.func.attr in ("array", "asarray", "sqrt", "deg2rad")) for n in ast.walk(node.value)):
                    continue
                try:
                    value = eval(compile(ast.Expression(node.value), "numeric_constants", "eval"), ns)
                except (NameError, AttributeError, TypeError):
                    continue
            ns[node.targets[0].id] = value


def source_namespace(name, source=None):
    path = FAMILY / f"juice_preparation_{name}.py"
    source = path.read_text(encoding="utf-8") if source is None else source
    tree = ast.parse(source)
    ns = {"torch": torch, "np": np}
    numeric_constants(ast.parse((ROOT / "tasks/config/workspace_rig.py").read_text(encoding="utf-8")), ns)
    numeric_constants(tree, ns)
    helpers = {"door_settle_update", "button_press_update", "new_apple_motion_state", "apple_motion_update", "apple_settled", "apple_route_latches"}
    compile_nodes([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in helpers], ns, path)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith("JuicePreparation"))
    compile_nodes([n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ("evaluate", "_tick_stage_counter", "_apple_quantities")], ns, path)
    return ns


spec = importlib.util.spec_from_file_location("juice_reset_guard_cpu", FAMILY / "reset_guard.py")
GUARD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(GUARD)
MIXIN = GUARD.JuiceResetMixin
package = ModuleType("juice_cpu_fixture")
package.__path__ = [str(FAMILY)]
sys.modules[package.__name__] = package
appearance_ns = {"Path": Path, "json": json, "np": np, "__file__": str(FAMILY / "appearance.py"), "__package__": package.__name__}
appearance_tree = ast.parse((FAMILY / "appearance.py").read_text(encoding="utf-8"))
compile_nodes([n for n in appearance_tree.body if isinstance(n, ast.ClassDef)], appearance_ns, FAMILY / "appearance.py")
APPEARANCE = appearance_ns["JuiceAppearance"]


class SpyBase:
    def reset(self, seed=None, options=None):
        self.events.extend(("base_reset", "random_draw", "state_write"))
        indices = options.get("env_idx", list(range(self.num_envs)))
        for name in self.state_fields:
            item = getattr(self, name)
            if isinstance(item, dict):
                for tensor in item.values(): tensor[indices] = 0
            else:
                item[indices] = 0
        self._elapsed_steps[indices] = 0
        if self.juice_appearance is not None:
            self.juice_appearance.apply(list(map(int, indices)), options)
        return {}, self.evaluate()


NSPACE = {name: source_namespace(name) for name in ("open_fridge", "close_fridge", "apple_to_blender", "place_lid", "press_button", "long")}
for key in ("door_settle_update", "ARM_STATIC_THRESHOLD", "DOOR_STATIC_THRESHOLD", "SUCCESS_SETTLE_STEPS"):
    NSPACE["close_fridge"][key] = NSPACE["open_fridge"][key]
long_ns = NSPACE["long"]
for name, keys in (("open_fridge", ("door_settle_update",)), ("press_button", ("button_press_update", "BUTTON_HOLD_STEPS")),
                   ("apple_to_blender", ("apple_motion_update", "apple_settled", "apple_route_latches"))):
    for key in keys: long_ns[key] = NSPACE[name][key]
long_ns.update(DOOR_SETTLE_STEPS=NSPACE["open_fridge"]["SUCCESS_SETTLE_STEPS"],
               APPLE_SETTLE_STEPS=NSPACE["apple_to_blender"]["SUCCESS_SETTLE_STEPS"],
               LID_SETTLE_STEPS=NSPACE["place_lid"]["SUCCESS_SETTLE_STEPS"],
               PICK_HEIGHT=NSPACE["place_lid"]["PICK_HEIGHT"], TABLE_TOP_Z=NSPACE["place_lid"]["TABLE_TOP_Z"])
for name in ("apple_to_blender", "long"):
    NSPACE[name]["apple_inside_fridge"] = lambda p, *args, **kw: torch.zeros(len(p), dtype=torch.bool)
    NSPACE[name]["apple_inside_blender"] = lambda p, *args, **kw: (torch.ones(len(p), dtype=torch.bool), torch.zeros_like(p), torch.zeros(len(p)))

CLASSES = {}
for name in ("open_fridge", "close_fridge", "apple_to_blender", "place_lid", "press_button", "long"):
    bases = (CLASSES["open_fridge"],) if name == "close_fridge" else (CLASSES["apple_to_blender"],) if name == "long" else (MIXIN, SpyBase)
    methods = {k: v for k, v in NSPACE[name].items() if k in ("evaluate", "_tick_stage_counter", "_apple_quantities")}
    CLASSES[name] = type("Cpu_" + name, bases, methods)


def make(name, stage=4):
    env = CLASSES[name]()
    env.num_envs, env.device, env.events = 2, "cpu", []
    env._elapsed_steps = torch.tensor([10, 10])
    env.juice_appearance = APPEARANCE({"per_env": {"0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "variant_2"}}}, 2)
    env.juice_appearance.bindings = [{"fridge": [(NS(base_color=[.8, .8, .8, 1.], roughness=.2), ([.8, .8, .8, 1.], .2))]} for _ in range(2)]
    env.juice_appearance.apply([0, 1], {"juice_appearance": {"scheme_id": "original"}})
    def state(name, value, dtype=torch.bool):
        setattr(env, name, torch.full((2,), value, dtype=dtype))
        env.state_fields.append(name)
    env.state_fields = []
    state("success_latched", False)
    ns = NSPACE[name]
    if name in ("open_fridge", "close_fridge"):
        state("success_settle_counter", ns["SUCCESS_SETTLE_STEPS"] - 1, torch.int32)
        state("hand_contact_latched", False)
        q = torch.full((2, 1), 1. if name == "open_fridge" else 0.)
        env.fridge = NS(get_qpos=lambda: q, get_qvel=lambda: torch.zeros((2, 1)))
        env.door_lower, env.target_open_qpos, env.success_open_qpos = 0., 1., 1.
        env.initial_open_qpos, env.success_closed_qpos = 1., .1
        env.current_handle_position_tensor = env._task_tcp_position = lambda: torch.zeros((2, 3))
        env._arm_qvel_norm = lambda: torch.zeros(2)
        env._hand_contacts_door = lambda: torch.ones(2, dtype=torch.bool)
    elif name == "press_button":
        state("button_hold_counter", ns["BUTTON_HOLD_STEPS"] - 1, torch.int32)
        env._task_quantities = lambda: {"button_pressed": torch.ones(2, dtype=torch.bool), "pressing_point_distance": torch.zeros(2)}
    elif name == "place_lid":
        for flag in ("picked_once", "transported_once", "seated_once", "released_once"): state(flag, flag == "picked_once")
        state("success_counter", ns["SUCCESS_SETTLE_STEPS"] - 1, torch.int32)
        env._task_quantities = lambda: {"lid_lift_height": torch.ones(2), "lid_xy_error": torch.zeros(2),
            "lid_position": torch.ones((2, 3)), "seat_target_position": torch.zeros((2, 3)),
            "lid_seated": torch.ones(2, dtype=torch.bool), "lid_stable": torch.ones(2, dtype=torch.bool),
            "end_effector_clear": torch.ones(2, dtype=torch.bool), "lid_to_seat_position": torch.zeros((2, 3))}
    else:
        state("apple_left_fridge_latched", True)
        state("apple_lifted_latched", True)
        p = torch.tensor([[0., 0., .2], [0., 0., .2]])
        q = torch.tensor([[1., 0., 0., 0.], [1., 0., 0., 0.]])
        env.apple = NS(pose=NS(p=p, q=q, raw_pose=torch.cat([p, q], -1)), linear_velocity=torch.zeros_like(p), angular_velocity=torch.zeros_like(p))
        env.fridge = NS(pose=NS(p=torch.zeros_like(p)), get_qpos=lambda: torch.full((2, 1), 1. if stage == 0 else 0.),
                        get_qvel=lambda: torch.zeros((2, 1)))
        env.handle_link = NS(pose=NS(p=torch.zeros_like(p)))
        env.apple_asset_info = NS(collision_bounds=np.zeros((2, 3)))
        env._batched_blender_geometry = lambda: None
        env.control_timestep = .05
        env.apple_motion = NSPACE["apple_to_blender"]["new_apple_motion_state"](2, "cpu")
        env.apple_motion.update(prev_p=p.clone(), prev_q=q.clone())
        env.state_fields.append("apple_motion")
        if name == "apple_to_blender":
            state("stable_counter", ns["SUCCESS_SETTLE_STEPS"] - 1, torch.int32)
        else:
            thresholds = (ns["DOOR_SETTLE_STEPS"], ns["APPLE_SETTLE_STEPS"], ns["DOOR_SETTLE_STEPS"], ns["LID_SETTLE_STEPS"], ns["BUTTON_HOLD_STEPS"])
            state("stage", stage, torch.long)
            state("stage_counter", thresholds[stage] - 1, torch.long)
            for flag in ("left_open_contact", "left_close_contact", "right_apple_contact", "right_lid_contact", "right_lid_lifted"):
                state(flag, flag == "right_lid_lifted")
            env.button_joint_index, env.button_rest_qpos, env.button_pressed_qpos = 0, 0., .003
            env.blender = NS(get_qpos=lambda: torch.full((2, 1), .003))
            env.blender_geometry = NS(lid_lower=np.zeros(3))
            env._lid_quantities = lambda: (torch.ones((2, 3)), torch.zeros((2, 3)), torch.ones(2, dtype=torch.bool), torch.ones(2, dtype=torch.bool))
            env._side_contacts = lambda *args: torch.ones(2, dtype=torch.bool)
            env.door_link = object()
            env.lid = object()
            env.success_open_qpos, env.success_closed_qpos = 1., .1
    return env


def row_state(env, index):
    def row(value):
        return {k: row(v) for k, v in value.items()} if isinstance(value, dict) else value[index].clone()
    return {name: row(getattr(env, name)) for name in env.state_fields}


def equal(a, b):
    return all(equal(v, b[k]) for k, v in a.items()) if isinstance(a, dict) else torch.equal(a, b)


class JuiceR1Tests(unittest.TestCase):
    def test_production_inheritance_uses_the_tested_reset_mixin(self):
        for name in CLASSES:
            tree = ast.parse((FAMILY / f"juice_preparation_{name}.py").read_text(encoding="utf-8"))
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith("JuicePreparation"))
            bases = [ast.unparse(base) for base in cls.bases]
            expected = ["JuicePreparationOpenFridgeEnv"] if name == "close_fridge" else ["JuicePreparationAppleToBlenderEnv"] if name == "long" else ["JuiceResetMixin", "BaseEnv"]
            self.assertEqual(bases, expected)

    def test_unknown_last_row_all_public_entries(self):
        for name in CLASSES:
            for selected in (None, [1]):
                with self.subTest(task=name, selected=selected):
                    env = make(name)
                    before = [row_state(env, i) for i in (0, 1)]
                    materials = copy.deepcopy(env.juice_appearance.bindings)
                    records = copy.deepcopy(env.juice_appearance.records)
                    options = {"juice_appearance": {"per_env": {"0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "wrong_id"}}}}
                    if selected is not None: options["env_idx"] = torch.tensor(selected)
                    with self.assertRaises(ValueError): env.reset(seed=7, options=options)
                    self.assertEqual(env.events, [])
                    self.assertTrue(all(equal(old, row_state(env, i)) for i, old in enumerate(before)))
                    self.assertEqual(records, env.juice_appearance.records)
                    self.assertEqual(materials, env.juice_appearance.bindings)

    def test_apply_validates_every_id_before_material_and_record_writes(self):
        env = make("press_button")
        before = copy.deepcopy((env.juice_appearance.bindings, env.juice_appearance.records))
        with self.assertRaises(ValueError):
            env.juice_appearance.apply([0, 1], {"juice_appearance": {"per_env": {"0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "wrong_id"}}}})
        self.assertEqual(before, (env.juice_appearance.bindings, env.juice_appearance.records))

    def test_frozen_apply_counterexample_reproduces(self):
        source = subprocess.check_output(["git", "show", f"{FROZEN}:tasks/juice_preparation/appearance.py"], cwd=ROOT).decode()
        cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "JuiceAppearance")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "apply")
        ns = dict(appearance_ns)
        compile_nodes([method], ns, "frozen_apply")
        env = make("press_button")
        with self.assertRaises(ValueError):
            ns["apply"](env.juice_appearance, [0, 1], {"juice_appearance": {"per_env": {
                "0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "wrong_id"}}}})
        self.assertEqual(env.juice_appearance.records[0]["scheme_id"], "variant_1")
        self.assertEqual(env.juice_appearance.records[0]["episode_index"], 2)
        self.assertEqual(env.juice_appearance.records[1]["scheme_id"], "original")

    def test_disabled_path_still_protects_unselected_counter(self):
        env = make("press_button")
        env.juice_appearance = None
        _, info = env.reset(options={"env_idx": torch.tensor([1]), "juice_appearance": {"scheme_id": "ignored_when_disabled"}})
        self.assertEqual(int(info["button_hold_counter"][0]), 3)
        self.assertFalse(bool(info["success"][0]))

    def test_override_order_and_original(self):
        env = make("press_button")
        env.juice_appearance.config = {"scheme_id": "wrong_id", "per_env": {"0": {"scheme_id": "variant_2"}}}
        env.reset(options={"juice_appearance": {"scheme_id": "original", "per_env": {"0": {"scheme_id": "variant_1"}}}})
        self.assertEqual([r["scheme_id"] for r in env.juice_appearance.records], ["variant_1", "original"])
        env.reset(options={"env_idx": torch.tensor([0]), "juice_appearance": {"scheme_id": "original"}})
        material, baseline = env.juice_appearance.bindings[0]["fridge"][0]
        self.assertEqual(material.base_color, baseline[0])
        self.assertEqual(material.roughness, baseline[1])

    def test_critical_states_in_both_reset_directions(self):
        for name in CLASSES:
            for stage in range(5) if name == "long" else (4,):
                for selected in (0, 1):
                    with self.subTest(task=name, stage=stage, selected=selected):
                        env = make(name, stage)
                        keep = 1 - selected
                        before = row_state(env, keep)
                        material = copy.deepcopy(env.juice_appearance.bindings[keep])
                        record = copy.deepcopy(env.juice_appearance.records[keep])
                        _, info = env.reset(options={"env_idx": torch.tensor([selected]), "juice_appearance": {"scheme_id": "original"}})
                        self.assertTrue(equal(before, row_state(env, keep)))
                        self.assertFalse(bool(info["success"][keep]))
                        self.assertEqual(material, env.juice_appearance.bindings[keep])
                        self.assertEqual(record, env.juice_appearance.records[keep])
                        self.assertIsNone(env._juice_reset_mask)
                        if name == "press_button":
                            self.assertEqual(int(info["button_hold_counter"][keep]), 3)
                            self.assertEqual(float(info["button_hold_progress"][keep]), .75)
                        env.evaluate()  # Ordinary step-time evaluation must still advance.
                        self.assertTrue(bool(env.success_latched[keep]) if name != "long" or stage == 4 else int(env.stage[keep]) > stage)

    def test_guard_is_restored_if_base_reset_raises(self):
        env = make("press_button")
        with patch.object(SpyBase, "reset", side_effect=RuntimeError("base error")):
            with self.assertRaisesRegex(RuntimeError, "base error"):
                env.reset(options={"env_idx": torch.tensor([1])})
        self.assertIsNone(env._juice_reset_mask)

    def test_frozen_button_counterexample_reproduces(self):
        source = subprocess.check_output(["git", "show", f"{FROZEN}:tasks/juice_preparation/juice_preparation_press_button.py"], cwd=ROOT).decode()
        old = source_namespace("press_button", source)
        env = make("press_button")
        old["evaluate"](env)
        self.assertEqual(env.button_hold_counter.tolist(), [4, 4])
        self.assertEqual(env.success_latched.tolist(), [True, True])

    def test_labels_follow_ids_in_reordered_and_extended_schemes(self):
        path = ROOT / "tools/variation/render_juice_preview.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("comparison_columns", "contact_sheet")]
        nodes += [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "LABELS" for t in n.targets)]
        ns = {"Image": Image, "ImageDraw": ImageDraw, "ImageFont": ImageFont}
        compile_nodes(nodes, ns, path)
        schemes = {"variant_2": {}, "original": {}, "variant_1": {}, "variant_future": {}}
        columns = ns["comparison_columns"](schemes)
        self.assertEqual([v[0] for v in columns], list(schemes))
        self.assertIn("Terracotta", columns[0][1])
        self.assertIn("Sage", columns[2][1])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            colors = [(20, 40, 60), (80, 90, 100), (110, 120, 130), (140, 150, 160)]
            for (scheme, _), color in zip(columns, colors):
                Image.new("RGB", (100, 20), color).save(folder / f"test_{scheme}.png")
            drawn = []
            with patch.object(ImageDraw, "Draw", return_value=NS(text=lambda xy, label, **kw: drawn.append(label))):
                ns["contact_sheet"](folder, "test", schemes)
            self.assertEqual(drawn, [label for _, label in columns])
            with Image.open(folder / "test_comparison.png") as sheet:
                self.assertEqual(sheet.width, 400)
                for i, color in enumerate(colors): self.assertEqual(sheet.getpixel((i * 100 + 50, 50)), color)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(JuiceR1Tests))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"status": "passed" if result.wasSuccessful() else "failed", "tests": result.testsRun,
            "failures": len(result.failures), "errors": len(result.errors), "torch": torch.__version__, "torch_device": "cpu",
            "public_reset_invalid_cases": 12, "critical_reset_cases": 20,
            "scope": "actual reset/evaluate/helpers; external BaseEnv, geometry and render inputs replaced; no simulator/GPU",
            "frozen_head": FROZEN}, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
