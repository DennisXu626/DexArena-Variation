"""CPU binding/readback check for a freshly rebuilt SAPIEN; not a GPU regression.

Run explicitly after installing the candidate runtime. No simulator is imported
by the repository's stdlib unit tests.
"""
import numpy as np
import sapien


assert sapien.physx.version() == "107.3-physx-5.6.1+dexarena.1", sapien.physx.version()
scene = sapien.Scene([sapien.physx.PhysxCpuSystem()])
builder = scene.create_articulation_builder()
root = builder.create_link_builder()
root.set_name("root")
child = builder.create_link_builder(root)
child.set_name("child")
child.set_joint_name("hinge")
child.set_joint_properties("revolute", [[-1.0, 1.0]], sapien.Pose(), sapien.Pose())
child.add_box_collision(half_size=[0.01, 0.01, 0.01])
articulation = builder.build(fix_root_link=True)
joint = articulation.get_active_joints()[0]
joint.set_drive_properties(3.0, 0.2, 1.5)
joint.set_armature([0.001])
before = (joint.stiffness, joint.damping, joint.force_limit, joint.armature.copy())
joint.set_friction(0.0)
joint.set_friction_params(0.01276, 0.01276, 0.0)
np.testing.assert_allclose(joint.get_friction_params(), [0.01276, 0.01276, 0.0])
assert joint.get_friction() == 0.0
assert joint.friction_params_enabled
assert (joint.stiffness, joint.damping, joint.force_limit) == before[:3]
np.testing.assert_array_equal(joint.armature, before[3])
cloned = articulation.clone_links()
np.testing.assert_allclose(cloned[1].joint.get_friction_params(), joint.get_friction_params())
assert cloned[1].joint.friction_params_enabled
print("PASS: native effort readback, legacy coefficient zero, PD/armature unchanged, clone preserved")
