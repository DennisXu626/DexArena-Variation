"""CPU API spies for GPU publication; no native engine or CUDA execution."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import torch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('nut_gpu_hold_cpu', ROOT / 'tasks/nut_bolt/gpu_hold.py')
H = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(H)


class Component:
    def __init__(self, index):
        self.gpu_index = index
        self.axes = [False] * 6
        self.flag_writes = 0

    def get_locked_motion_axes(self):
        return self.axes.copy()

    def set_locked_motion_axes(self, value):
        self.axes = value.copy()
        self.flag_writes += 1

    def set_pose(self, value):
        raise AssertionError('Raw CPU-shadow pose write')


class Raw:
    def __init__(self, body):
        self.body = body

    def find_component_by_type(self, kind):
        return self.body

    def get_pose(self):
        raise AssertionError('Raw CPU-shadow pose read')


class Actor:
    def __init__(self, indices):
        self._scene_idxs = torch.tensor([0, 1])
        self._bodies = [Component(index) for index in indices]
        self._objs = [Raw(body) for body in self._bodies]
        self.state = torch.arange(26, dtype=torch.float32).reshape(2, 13)
        self.state[:, 3:7] = torch.tensor([1., 0., 0., 0.])
        self.state_writes = []

    @property
    def pose(self):
        return SimpleNamespace(raw_pose=self.state[:, :7])

    def set_state(self, state, env_idx):
        self.state_writes.append((state.clone(), env_idx.clone()))
        self.state[env_idx] = state


def fixture():
    bolt, nut, platform = Actor([40, 90]), Actor([41, 91]), Actor([42, 92])
    base = SimpleNamespace(device='cpu', bolt=bolt, nut=nut, platform=platform,
        has_platform=True, _bolt_locked=torch.tensor([False, True]), _nut_engaged=torch.tensor([False, False]),
        _bolt_lock_pose=torch.tensor([[.1, .2, .3, 1., 0., 0., 0.], [.4, .5, .6, 1., 0., 0., 0.]]))
    base._hold_bodies = lambda: [(bolt, base._bolt_locked), (nut, base._nut_engaged)]
    base._hold_pose = lambda actor, index: H.hold_pose(base, actor, index, 5.)
    return base


def fake_sdk(native_version=1, indexed_version=1):
    sdk, physx = ModuleType('sapien'), ModuleType('sapien.physx')
    physx.PhysxRigidDynamicComponent = Component
    physx.native_gpu_lock_sync_patch_version = lambda: native_version
    physx.indexed_gpu_apply_patch_version = lambda: indexed_version
    sdk.physx, sdk.CudaArray = physx, lambda value: value.clone()
    return {'sapien': sdk, 'sapien.physx': physx}


class GPUHoldContractTests(unittest.TestCase):
    def test_native_capability_gates_both_patches(self):
        for native, indexed in ((0, 1), (1, 0)):
            with patch.dict(sys.modules, fake_sdk(native, indexed)):
                with self.assertRaises(RuntimeError):
                    H.require_native_gpu_lock()
        with patch.dict(sys.modules, fake_sdk()):
            H.require_native_gpu_lock()

    def test_hold_flip_uses_selected_state_and_native_body_indices_once(self):
        base = fixture()
        unselected = base.bolt.state[0].clone()
        with patch.dict(sys.modules, fake_sdk()), patch.object(H, '_publish') as publish:
            H.refresh_gpu_hold_state(base)
            self.assertTrue(torch.equal(base.bolt.state[0], unselected))
            self.assertTrue(torch.equal(base.bolt.state[1, :7], base._bolt_lock_pose[1]))
            self.assertTrue(torch.equal(base.bolt.state[1, 7:], torch.zeros(6)))
            self.assertEqual(len(base.bolt.state_writes), 1)
            self.assertEqual(publish.call_args.kwargs['rigid_indices'], [90, 92])
            self.assertEqual(base.bolt._bodies[0].flag_writes, 0)
            self.assertEqual(base.bolt._bodies[1].flag_writes, 1)
            H.refresh_gpu_hold_state(base)
            self.assertEqual(publish.call_count, 1)
            self.assertEqual(len(base.bolt.state_writes), 1)
            base._bolt_locked[1] = False
            H.refresh_gpu_hold_state(base)
            self.assertEqual(publish.call_count, 1)
            self.assertEqual(len(base.bolt.state_writes), 1)
            self.assertEqual(base.bolt._bodies[1].axes, [False] * 6)

    def test_restore_keeps_all_nonzero_velocity_and_pose(self):
        base = fixture()
        before = base.bolt.state.clone()
        with patch.dict(sys.modules, fake_sdk()), patch.object(H, '_publish') as publish:
            H.refresh_gpu_hold_state(base, write_pose=False)
            self.assertTrue(torch.equal(base.bolt.state, before))
            self.assertEqual(base.bolt.state_writes, [])
            publish.assert_not_called()
            self.assertEqual(base.bolt._bodies[1].axes, [True] * 6)

    def test_nut_park_xy_comes_from_current_actor_buffer(self):
        base = fixture()
        pose = H.hold_pose(base, base.nut, 1, 5.)
        self.assertTrue(torch.equal(pose[0, :2], base.nut.state[1, :2]))
        self.assertEqual(pose[0, 2].item(), 5.)
        self.assertTrue(torch.equal(pose[0, 3:], torch.tensor([1., 0., 0., 0.])))

    def test_partial_scope_never_touches_mismatched_unselected_flags(self):
        base = fixture()
        base._furniture_reset_env_idx = torch.tensor([1])
        base._bolt_locked = torch.tensor([True, False])
        before = base.bolt.state.clone()
        with patch.dict(sys.modules, fake_sdk()), patch.object(H, '_publish') as publish:
            H.refresh_gpu_hold_state(base)
            self.assertTrue(torch.equal(base.bolt.state, before))
            self.assertEqual(base.bolt._bodies[0].flag_writes, 0)
            publish.assert_not_called()

    def test_swap_publishes_only_actual_selected_nut_and_articulation(self):
        base = fixture()
        base.nut_revolute = SimpleNamespace(_scene_idxs=torch.tensor([0, 1]),
            _objs=[SimpleNamespace(gpu_index=17), SimpleNamespace(gpu_index=33)])
        calls = []
        base.scene = SimpleNamespace(px=SimpleNamespace(gpu_update_articulation_kinematics=lambda: calls.append('kinematics')),
            _gpu_fetch_all=lambda: calls.append('fetch'))
        with patch.dict(sys.modules, fake_sdk()), patch.object(H, '_publish') as publish:
            H.sync_nut_swap_gpu(base, torch.tensor([1]))
            self.assertEqual(publish.call_args.args[1:], ([91], [33]))
            self.assertEqual(calls, ['kinematics', 'fetch'])

    def test_publish_is_indexed_int32_for_each_buffer(self):
        calls = []
        px = SimpleNamespace(gpu_apply_rigid_dynamic_data=lambda index: calls.append(('rigid', index)))
        for name in ('root_pose', 'root_velocity', 'qpos', 'qvel'):
            setattr(px, 'gpu_apply_articulation_' + name,
                    lambda index, name=name: calls.append((name, index)))
        base = SimpleNamespace(device='cpu', scene=SimpleNamespace(px=px))
        with patch.dict(sys.modules, fake_sdk()):
            H._publish(base, [90, 40, 90], [33])
        self.assertEqual([name for name, _ in calls], ['rigid', 'root_pose', 'root_velocity', 'qpos', 'qvel'])
        self.assertTrue(all(index.dtype == torch.int32 for _, index in calls))
        self.assertEqual(calls[0][1].tolist(), [40, 90])
        self.assertTrue(all(index.tolist() == [33] for _, index in calls[1:]))


if __name__ == '__main__':
    unittest.main()
