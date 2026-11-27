"""Unit/contract tests; no simulator, assets, GPU or task imports."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "tasks/robots/hand_controller_gains.py"
SPEC = importlib.util.spec_from_file_location("hand_controller_gains", SOURCE)
gains = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gains)


class NativeJoint:
    def __init__(self, name):
        self.name = name
        self.coefficient = 0.05
        self.params = None
        self.armature = [0.001]
        self.max_velocity = 100.0
        self.drive = (3.0, 0.2, 1.5, "force")

    def set_friction(self, value):
        self.coefficient = value

    def set_friction_params(self, static_effort, dynamic_effort, viscous):
        self.params = (static_effort, dynamic_effort, viscous)

    def set_armature(self, value):
        self.armature = value

    def set_max_velocity(self, value):
        self.max_velocity = value


def robot(joints):
    return SimpleNamespace(get_active_joints=lambda: joints)


class JointFrictionMappingTest(unittest.TestCase):
    def test_all_current_hand_tables_both_sides_and_batched_environments(self):
        for table in (gains.SHARPA_HAND_FRICTIONLOSS, gains.WUJI_HAND_FRICTIONLOSS,
                      gains.XHAND_HAND_FRICTIONLOSS):
            with self.subTest(table_size=len(table)):
                names = [side + name for side in ("left_", "right_") for name in table]
                joints = [SimpleNamespace(name=name, _objs=[NativeJoint(name) for _ in range(3)])
                          for name in names]
                arm_joint = NativeJoint("arm_joint")
                gains.apply_joint_physics(robot([arm_joint, *reversed(joints)]), names, table)
                for joint in joints:
                    expected = table[gains._strip_side(joint.name)]
                    for native in joint._objs:
                        self.assertEqual(native.params, (expected, expected, 0.0))
                        self.assertEqual(native.coefficient, 0.0)
                        self.assertEqual(native.armature, [0.001])
                        self.assertEqual(native.max_velocity, 100.0)
                        self.assertEqual(native.drive, (3.0, 0.2, 1.5, "force"))
                self.assertIsNone(arm_joint.params)
                self.assertEqual(arm_joint.coefficient, 0.05)

    def test_native_joint_and_explicit_zero_friction(self):
        joint = NativeJoint("hinge")
        gains.apply_joint_physics(robot([joint]), ["hinge"], {"hinge": 0.0})
        self.assertEqual(joint.params, (0.0, 0.0, 0.0))
        self.assertEqual(joint.coefficient, 0.0)

    def test_missing_runtime_fails_before_mutating_that_batch(self):
        good = NativeJoint("hinge")
        old = SimpleNamespace(set_friction=lambda _: self.fail("legacy setter must not be used"))
        joint = SimpleNamespace(name="hinge", _objs=[good, old])
        with self.assertRaisesRegex(RuntimeError, "PhysX 5.6.1"):
            gains.apply_joint_physics(robot([joint]), ["hinge"], {"hinge": 0.2})
        self.assertIsNone(good.params)
        self.assertEqual(good.coefficient, 0.05)

    def test_empty_native_batch_cannot_silently_skip_friction(self):
        joint = SimpleNamespace(name="hinge", _objs=[])
        with self.assertRaisesRegex(RuntimeError, "PhysX 5.6.1"):
            gains.apply_joint_physics(robot([joint]), ["hinge"], {"hinge": 0.2})

    def test_reconfigure_and_repeated_application(self):
        for _ in range(2):
            native = NativeJoint("left_hinge")
            joint = SimpleNamespace(name=native.name, _objs=[native])
            for _ in range(2):
                gains.apply_joint_physics(robot([joint]), [joint.name], {"hinge": 0.2})
                self.assertEqual(native.params, (0.2, 0.2, 0.0))
                self.assertEqual(native.coefficient, 0.0)

    def test_armature_and_velocity_configuration_keeps_existing_behavior(self):
        native = NativeJoint("right_hinge")
        joint = SimpleNamespace(name=native.name, _objs=[native])
        gains.apply_joint_physics(robot([joint]), [joint.name], {"hinge": 0.2},
                                  {"hinge": 0.004}, max_velocity=12.0)
        self.assertEqual(native.armature, [0.004])
        self.assertEqual(native.max_velocity, 12.0)
        self.assertEqual(native.drive, (3.0, 0.2, 1.5, "force"))

    def test_unspecified_friction_leaves_legacy_objects_untouched(self):
        joint = SimpleNamespace(name="hinge")
        gains.apply_joint_physics(robot([joint]), [joint.name])


if __name__ == "__main__":
    unittest.main()
