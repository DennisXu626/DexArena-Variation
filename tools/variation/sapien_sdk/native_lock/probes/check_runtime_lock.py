"""Check native CUDA lock transitions, six individual axes and contact response."""
import argparse
import ctypes
import faulthandler
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
sdk_root = os.environ.get('DEXARENA_NATIVE_LOCK_SDK_ROOT')
artifact = os.environ.get('DEXARENA_NATIVE_LOCK_SDK_ARTIFACT')
artifact_sha256 = os.environ.get('DEXARENA_NATIVE_LOCK_SDK_ARTIFACT_SHA256')
loaded = json.loads(os.environ.get('DEXARENA_NATIVE_LOCK_SDK_LOADED_IDENTITY', '{}'))
if not (sdk_root and artifact and artifact_sha256 and loaded):
    parser.error('Run through tools/launch_native_lock.py with a reviewed artifact SHA')
sdk = Path(sdk_root).resolve(strict=True)
out = args.output.resolve()
assert not out.exists(), 'Fresh output required'
private, physx = sdk / 'runtime', sdk / 'physx-runtime'
receipt_path = Path(artifact).resolve(strict=True)
receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert receipt_path == sdk / 'artifact.json' and sha(receipt_path) == artifact_sha256
free, utilization = map(int, subprocess.check_output(['nvidia-smi',
    '--query-gpu=memory.free,utilization.gpu', '--format=csv,noheader,nounits'], text=True).strip().split(','))
assert free >= 2048 and utilization < 70, 'GPU start resource gate'
out.mkdir(parents=True, exist_ok=False)
source = Path(__file__).resolve()
(out / 'probe_source.py').write_bytes(source.read_bytes())
faulthandler.enable()
faulthandler.dump_traceback_later(50, exit=True)
import torch
torch.cuda.init()
import sapien
import sapien.pysapien as binary
import sapien.physx as px
assert Path(binary.__file__).resolve().is_relative_to(private)
assert sapien.__version__ == metadata.version('sapien') == receipt['version']
capabilities = {name: getattr(px, name)() for name in
                ('indexed_gpu_apply_patch_version', 'native_gpu_lock_sync_patch_version')}
assert all(type(value) is int and value == 1 for value in capabilities.values())
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel.GetModuleHandleW.restype = ctypes.c_void_p
kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
kernel.GetModuleFileNameW.restype = ctypes.c_uint32


def identity():
    rows = {}
    required = {Path(binary.__file__).name, 'sapien.dll', 'svulkan2.dll', 'simsense.dll'}
    required.update(receipt['physx_gpu']['dll_sha256'])
    assert set(loaded) == required, 'Launcher native module coverage differs'
    for name in sorted(required):
        module = kernel.GetModuleHandleW(name)
        buffer = ctypes.create_unicode_buffer(32768)
        size = kernel.GetModuleFileNameW(module, buffer, len(buffer)) if module else 0
        assert 0 < size < len(buffer), name
        path = Path(buffer.value).resolve(strict=True)
        directory = physx if name in receipt['physx_gpu']['dll_sha256'] else private / 'sapien'
        assert path == (directory / name).resolve(strict=True)
        rows[name] = {'path': str(path), 'sha256': sha(path)}
    assert rows == loaded, 'Actually loaded SDK module identity differs from launcher'
    return rows


def python_identity():
    package = private / 'sapien'
    paths = sorted(package.rglob('*.py'))
    assert package / '__init__.py' in paths and all(path.resolve().is_relative_to(package) for path in paths)
    return {path.relative_to(private).as_posix(): sha(path) for path in paths}


result = {'status': 'running', 'version': sapien.__version__, 'source_sha256': sha(source),
    'artifact_sha256': artifact_sha256, **capabilities, 'sdk_before': identity(),
    'sdk_python_before': python_identity(), 'physics_steps': 0, 'phase_steps': {},
    'resource_before': {'free_mib': free, 'gpu_utilization_percent': utilization},
    'scope': 'One native GPU PhysX scene; no renderer or task acceptance'}
snapshots, indices, axis_indices = {}, [], []
try:
    px._enable_gpu()
    system = px.PhysxGpuSystem()
    scene = sapien.Scene([system])
    scene.set_timestep(1 / 240)
    bodies = []
    for index in range(3):
        builder = scene.create_actor_builder()
        builder.add_box_collision(half_size=[.02, .02, .02])
        builder.initial_pose = sapien.Pose(p=[index * .2, 0, 1])
        actor = builder.build(name=f'box{index}')
        bodies.append(actor.find_component_by_type(px.PhysxRigidDynamicComponent))
    bodies[2].set_locked_motion_axes([True] * 6)
    axes_bodies = []
    for axis in range(6):
        builder = scene.create_actor_builder()
        builder.add_box_collision(half_size=[.02, .02, .02])
        builder.initial_pose = sapien.Pose(p=[2 + axis * .4, 0, 1])
        actor = builder.build(name=f'axis{axis}')
        body = actor.find_component_by_type(px.PhysxRigidDynamicComponent)
        body.disable_gravity = True
        axes_bodies.append(body)
    contact_bodies = []
    for name, position, half_size, no_gravity in (
        ('runtime_locked_support', [6, 0, .3], [.08, .08, .04], True),
        ('contact_drop', [6, 0, 1.1], [.025, .025, .025], False),
        ('free_drop', [6.5, 0, 1.1], [.025, .025, .025], False)):
        builder = scene.create_actor_builder()
        builder.add_box_collision(half_size=half_size)
        builder.initial_pose = sapien.Pose(p=position)
        actor = builder.build(name=name)
        body = actor.find_component_by_type(px.PhysxRigidDynamicComponent)
        body.disable_gravity = no_gravity
        contact_bodies.append(body)
    system.gpu_init()

    def snapshot():
        system.gpu_fetch_rigid_dynamic_data()
        torch.cuda.synchronize()
        return system.cuda_rigid_body_data.torch().detach().cpu().clone()

    def step(phase):
        system.step()
        result['physics_steps'] += 1
        result['phase_steps'][phase] = result['phase_steps'].get(phase, 0) + 1

    snapshots['initial'] = snapshot()
    indices = [body.gpu_pose_index for body in bodies]
    bodies[1].set_locked_motion_axes([True] * 6)
    result['all_axis_lock_flags'] = [list(body.get_locked_motion_axes()) for body in bodies]
    assert result['all_axis_lock_flags'] == [[False] * 6, [True] * 6, [True] * 6]
    snapshots['after_runtime_lock_before_step'] = snapshot()
    assert torch.equal(snapshots['initial'], snapshots['after_runtime_lock_before_step'])
    for _ in range(20):
        step('runtime_lock')
    snapshots['after_lock_20'] = snapshot()
    bodies[0].set_locked_motion_axes([True] * 6)
    bodies[1].set_locked_motion_axes([False] * 6)
    bodies[2].set_locked_motion_axes([False] * 6)
    result['all_axis_switch_flags'] = [list(body.get_locked_motion_axes()) for body in bodies]
    assert result['all_axis_switch_flags'] == [[True] * 6, [False] * 6, [False] * 6]
    snapshots['after_switch_before_step'] = snapshot()
    assert torch.equal(snapshots['after_lock_20'], snapshots['after_switch_before_step'])
    for _ in range(20):
        step('runtime_switch')
    snapshots['after_switch_20'] = snapshot()
    a, b, c = indices
    first, second = snapshots['after_lock_20'], snapshots['after_switch_20']
    assert first[a, 2] < .99 and first[a, 9] < 0
    assert first[b, 2] == snapshots['initial'][b, 2] and first[c, 2] == snapshots['initial'][c, 2]
    assert first[b, 9] == first[c, 9] == 0
    assert second[a, 2] == first[a, 2] and second[a, 9] == 0
    assert second[b, 2] < .99 and second[c, 2] < .99
    assert second[b, 2] - first[b, 2] == second[c, 2] - first[c, 2]
    assert torch.equal(second[b, 3:], second[c, 3:])
    # Apply genuine forces and torques after runtime lock changes. Each fixture
    # has exactly one of the six native lock bits, not a replacement constraint.
    for axis, body in enumerate(axes_bodies):
        flags = [False] * 6
        flags[axis] = True
        body.set_locked_motion_axes(flags)
    contact_bodies[0].set_locked_motion_axes([True] * 6)
    result['one_axis_lock_flags'] = [list(body.get_locked_motion_axes()) for body in axes_bodies]
    assert result['one_axis_lock_flags'] == [[axis == component for component in range(6)] for axis in range(6)]
    snapshots['before_axes'] = snapshot()
    axis_indices = [body.gpu_pose_index for body in axes_bodies]
    force = system.cuda_rigid_body_force.torch()
    torque = system.cuda_rigid_body_torque.torch()
    force.zero_()
    torque.zero_()
    force[axis_indices, :3] = torch.tensor([.001, .002, .003], device='cuda')
    torque[axis_indices, :3] = torch.tensor([.0001, .0002, .0003], device='cuda')
    for _ in range(20):
        system.gpu_apply_rigid_dynamic_force()
        system.gpu_apply_rigid_dynamic_torque()
        step('individual_lock')
    snapshots['after_axes_locked_20'] = snapshot()
    for axis, index in enumerate(axis_indices):
        values = snapshots['after_axes_locked_20'][index]
        if axis < 3:
            assert values[axis] == snapshots['before_axes'][index, axis]
        assert values[7 + axis] == 0, ('locked velocity axis', axis, values.tolist())
        assert all(values[7 + other] != 0 for other in range(6) if other != axis)
    for body in axes_bodies:
        body.set_locked_motion_axes([False] * 6)
    result['one_axis_unlock_flags'] = [list(body.get_locked_motion_axes()) for body in axes_bodies]
    assert result['one_axis_unlock_flags'] == [[False] * 6] * 6
    snapshots['after_axes_unlock_before_step'] = snapshot()
    assert torch.equal(snapshots['after_axes_locked_20'], snapshots['after_axes_unlock_before_step'])
    for _ in range(20):
        system.gpu_apply_rigid_dynamic_force()
        system.gpu_apply_rigid_dynamic_torque()
        step('individual_unlock')
    snapshots['after_axes_unlocked_20'] = snapshot()
    assert all(snapshots['after_axes_unlocked_20'][index, 7 + axis] != 0
               for axis, index in enumerate(axis_indices))
    # Restore a selected locked body with nonzero velocity exactly once. Read
    # back every untouched body too; no whole-buffer write or later teleport.
    snapshots['before_indexed_restore'] = snapshot()
    data = system.cuda_rigid_body_data.torch()
    data[a, 0] += .001
    data[a, 7:13] = torch.tensor([.01, .02, .03, .04, .05, .06], device='cuda')
    expected_restore = data[a].detach().cpu().clone()
    chosen = torch.tensor([a], dtype=torch.int32, device='cuda')
    torch.cuda.synchronize()
    system.gpu_apply_rigid_dynamic_data(sapien.CudaArray(chosen))
    snapshots['after_indexed_restore'] = snapshot()
    other_indices = [i for i in range(len(data)) if i != a]
    assert torch.equal(snapshots['before_indexed_restore'][other_indices],
                       snapshots['after_indexed_restore'][other_indices])
    assert torch.allclose(expected_restore, snapshots['after_indexed_restore'][a], rtol=0, atol=2e-6)
    force.zero_()
    torque.zero_()
    system.gpu_apply_rigid_dynamic_force()
    system.gpu_apply_rigid_dynamic_torque()
    query = system.gpu_create_contact_pair_impulse_query([(contact_bodies[0], contact_bodies[1])])
    impulses = []
    for _ in range(80):
        step('contact')
        system.gpu_query_contact_pair_impulses(query)
        torch.cuda.synchronize()
        impulses.append(query.cuda_impulses.torch().detach().cpu().clone())
    snapshots['after_contact_80'] = snapshot()
    support, drop, free_drop = [body.gpu_pose_index for body in contact_bodies]
    contact_after = snapshots['after_contact_80']
    torch.save({'expected_selected': expected_restore, 'contact_impulses': impulses}, out / 'auxiliary.pt')
    assert torch.equal(contact_after[support, :7], snapshots['before_axes'][support, :7])
    assert contact_after[drop, 2] > .36 and contact_after[free_drop, 2] < .2
    assert any(bool(torch.count_nonzero(value)) for value in impulses)
    assert contact_after[a, 0] == snapshots['after_indexed_restore'][a, 0]
    assert not bool(torch.count_nonzero(contact_after[a, 7:13]))
    assert result['physics_steps'] == 160 and len(set([*indices, *axis_indices, support, drop, free_drop])) == 12
    result.update(status='passed', indices=indices, axis_indices=axis_indices,
        auxiliary_sha256=sha(out / 'auxiliary.pt'),
        contact_indices=[support, drop, free_drop],
        indexed_restore_absolute_tolerance=2e-6,
        flags=[list(body.get_locked_motion_axes()) for body in bodies])
except BaseException:
    result.update(status='failed', error=traceback.format_exc())
finally:
    if snapshots:
        torch.save(snapshots, out / 'states.pt')
        result['states_sha256'] = sha(out / 'states.pt')
        result['values'] = {k: v.tolist() for k, v in snapshots.items()}
        result['indices'] = indices
    result['sdk_after'] = identity()
    result['binaries_unchanged'] = result['sdk_before'] == result['sdk_after']
    result['sdk_python_after'] = python_identity()
    result['python_source_unchanged'] = result['sdk_python_before'] == result['sdk_python_after']
    result['inputs_unchanged'] = (sha(receipt_path) == artifact_sha256
                                  and sha(source) == sha(out / 'probe_source.py') == result['source_sha256'])
    if not all(result[key] for key in ('binaries_unchanged', 'python_source_unchanged', 'inputs_unchanged')):
        result.update(status='failed', error='SDK, receipt or probe source changed during the run')
    (out / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    faulthandler.cancel_dump_traceback_later()
    print(json.dumps({'status': result['status'], 'version': result['version'],
        'physics_steps': result.get('physics_steps'), 'error': result.get('error')}), flush=True)
sys.exit(0 if result['status'] == 'passed' else 1)
