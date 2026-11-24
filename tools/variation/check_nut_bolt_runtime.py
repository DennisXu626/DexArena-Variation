"""Nut & Bolt runtime checks built on the main/PR11 evidence helpers."""
import argparse
import copy
from dataclasses import asdict
import gc
import hashlib
import importlib.metadata as metadata
from importlib.util import find_spec
import json
from itertools import combinations
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
TASKS = ('PickBolt', 'SeatNut', 'TurnNut')
CATALOG = ROOT / 'tasks/assets/variation/nut_bolt/v1/catalog.json'
SCHEMES = tuple(json.loads(CATALOG.read_text(encoding='utf-8'))['schemes'])
TWO_ENV_GPU_MEMORY = {'max_rigid_contact_count': 2**17, 'max_rigid_patch_count': 2**16,
                      'found_lost_pairs_capacity': 2**20}
NATIVE_RGB_CAMERAS = ('base_camera', 'task_wrist_camera', 'wrist_camera', 'human')
MIN_WITNESS_PIXELS = 12
MIN_WITNESS_CHANNEL_DELTA = 8


def visibility_pairs(frames, camera, environments):
    """Same-pose comparisons of each pair on the original camera."""
    import numpy as np

    rows = []
    for left, right in combinations(SCHEMES, 2):
        for index in range(environments):
            a = frames[left][camera][index]
            b = frames[right][camera][index]
            delta = np.abs(a.astype(np.int16) - b.astype(np.int16))
            pixels = int((delta.max(axis=-1) >= MIN_WITNESS_CHANNEL_DELTA).sum())
            rows.append({'schemes': [left, right], 'env_idx': index, 'camera': camera,
                         'pixels_at_min_delta': pixels, 'max_absolute_error': int(delta.max())})
    return rows


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sdk_identity(sapien):
    """Measure the libraries actually loaded by this process, including workers."""
    binary = Path(sapien.pysapien.__file__).resolve()
    result = {binary.name: {'path': str(binary), 'sha256': sha(binary)}}
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
        kernel32.GetModuleFileNameW.restype = ctypes.c_uint32
        for name in ('sapien.dll', 'svulkan2.dll', 'simsense.dll', 'PhysXDevice64.dll', 'PhysXGpu_64.dll'):
            handle = kernel32.GetModuleHandleW(name)
            if not handle:
                if name.startswith('PhysX'):
                    result[name] = {'loaded': False}
                    continue
                raise RuntimeError(f'Missing loaded SDK library: {name}')
            buffer = ctypes.create_unicode_buffer(32768)
            if not kernel32.GetModuleFileNameW(handle, buffer, len(buffer)):
                raise RuntimeError(f'Cannot identify loaded SDK library: {name}')
            path = Path(buffer.value).resolve(strict=True)
            if not name.startswith('PhysX') and path.parent != binary.parent:
                raise RuntimeError(f'SDK library loaded outside the binding directory: {path}')
            result[name] = {'path': str(path), 'sha256': sha(path)}
    return result


def source_hashes():
    files = list((ROOT / 'tasks/nut_bolt').glob('*.py'))
    files += list((ROOT / 'tasks/robots').glob('*.py'))
    files += list((ROOT / 'tasks/scene_builders').glob('*.py'))
    files += list((ROOT / 'tasks/config').glob('*.py'))
    for directory in ('urdf', 'franka_description', 'sharpa_hand_meshes',
                      'mobile_base_meshes', 'marvin_wrist_camera_meshes'):
        files += list((ROOT / 'tasks/assets' / directory).rglob('*'))
    files += list((ROOT / 'tools/variation').glob('*nut_bolt*.py'))
    files += [ROOT / name for name in ('tasks/furniture_assembly/appearance.py',
              'tasks/furniture_assembly/reset_scope.py', 'tools/variation/check_furniture_appearance.py',
              'tools/variation/check_furniture_dynamics.py', 'tools/variation/sapien_sdk/native_lock/tools/run_task_check.py',
              'tools/variation/sapien_sdk/native_lock/tools/native_lock_identity.py',
              'tasks/assets/task_object_meshes/screwing/bolt_hex_head.obj')]
    files += list((ROOT / 'assets/appearance/objects/nut_bolt').glob('*/bindings.json'))
    files += list((ROOT / 'assets/appearance/objects/nut_bolt').glob('*/variants/v1/catalog.json'))
    files.append(CATALOG)
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(files)) if p.is_file()}


def external_hashes():
    package = Path(find_spec('mani_skill').origin).resolve().parent
    files = list(package.rglob('*.py'))
    files += [package / 'utils/scene_builder/table/assets/table.glb',
              package / 'utils/building/assets/grid_texture.png']
    return {'mani_skill/' + path.relative_to(package).as_posix(): sha(path)
            for path in sorted(set(files)) if path.is_file()}


def helpers():
    # These helpers are already in main. Bind their runtime imports without
    # changing product/task objects or copying the validation framework.
    import numpy as np
    import torch
    import sapien
    import gymnasium as gym
    from tools.variation import check_furniture_appearance as common
    from tools.variation import nut_bolt_runtime_evidence as evidence
    common.np, common.torch, common.sapien, common.gym = np, torch, sapien, gym
    common.articulations = lambda base: {'robot': base.agent.robot, **{
        name: value for name, value in base.scene.articulations.items() if value is not base.agent.robot}}
    if not hasattr(common, '_nut_bolt_native_physical'):
        common._nut_bolt_native_physical = common.physical
    common.physical = lambda base: physical_json(common._nut_bolt_native_physical(base))
    common.materials = lambda base: evidence.materials(common, base)
    return common


class EvidenceView:
    def __init__(self, base):
        self.base = base
        self._furniture_appearance = base._nut_bolt_appearance

    def __getattr__(self, name):
        return getattr(self.base, name)


def appearance_state(base):
    value = base._nut_bolt_appearance
    return {'rng': [copy.deepcopy(rng.bit_generator.state) for rng in value.rng],
            'schemes': value.schemes.copy(), 'episodes': value.episodes.copy(),
            'records': copy.deepcopy(value.records)}


def verify(common, base, schemes, native):
    return common.verify(EvidenceView(base), schemes, native)


def visual_state(common, base):
    import sapien.render as sr
    import sapien.physx as px
    rows = []
    for scene in base.scene.sub_scenes:
        entries = []
        for entity in sorted(scene.entities, key=lambda item: (item.name, item.per_scene_id)):
            body = entity.find_component_by_type(sr.RenderBodyComponent)
            dynamic = entity.find_component_by_type(px.PhysxRigidDynamicComponent)
            entries.append({'entity': entity.name, 'visibility': float(body.visibility) if body else None,
                'locked_axes_cpu_flags': list(dynamic.get_locked_motion_axes()) if dynamic else None})
        rows.append(entries)
    return rows


def physical_json(value):
    """Continuous-joint bounds are legitimate infinities, encoded explicitly."""
    result = copy.deepcopy(value)
    def bound(value):
        if isinstance(value, list):
            return [bound(item) for item in value]
        if isinstance(value, float) and math.isinf(value):
            return '-Infinity' if value < 0 else 'Infinity'
        return value
    for environments in result['joints'].values():
        for joints in environments:
            for joint in joints:
                if 'limits' in joint:
                    joint['limits'] = bound(joint['limits'])
    return result


def stage_visibility_fixture(common, env, seed, output):
    """Exercise the native representation swap, without claiming a task success."""
    import sapien.render as sr
    import torch
    from tools.variation import nut_bolt_runtime_evidence as evidence

    output.mkdir()
    base = env.unwrapped
    _, info = env.reset(seed=seed)
    chosen, other = 1, 0
    selected = torch.tensor([chosen], device=base.device)
    adapter = base._nut_bolt_appearance
    assert all(scheme in SCHEMES[1:] for scheme in adapter.schemes)

    def visibility():
        result = {}
        for name, handle in (('free', base.nut), ('threaded', base.threaded_nut)):
            rows = []
            for raw in handle._objs:
                entity = getattr(raw, 'entity', raw)
                body = entity.find_component_by_type(sr.RenderBodyComponent)
                rows.append(float(body.visibility))
            result[name] = rows
        return result

    def capture_pair(label, current_info, first_obs=None):
        before = common.snapshot(base)
        if first_obs is None:
            first = common.capture(env, current_info)
        else:
            first = {name: values['rgb'].detach().cpu().numpy().copy()
                     for name, values in first_obs['sensor_data'].items()}
            first['human'] = env.render().detach().cpu().numpy().copy()
            common.validate_images(first, base.num_envs)
        after_first = common.snapshot(base)
        again = common.capture(env, current_info)
        after_repeat = common.snapshot(base)
        assert not common.state_changes(before, after_first)
        assert not common.state_changes(after_first, after_repeat)
        assert set(first) == set(NATIVE_RGB_CAMERAS)
        common.save_image_pairs(first, again, output, label + '_repeat')
        pixels = [common.image_changes(first, again, output, label + '_repeat', env_id=index)
                  for index in range(base.num_envs)]
        assert not any(row['changed_values'] for values in pixels for row in values.values()), label
        snapshots = {'before_capture': before, 'after_first_capture': after_first, 'after_repeat_capture': after_repeat}
        return first, pixels, snapshots

    def verify_transition(before_images, after_images, before_state, after_state, label):
        assert not common.state_changes(before_state, after_state, [other]), label
        common.save_image_pairs(before_images, after_images, output, label)
        pixels = [common.image_changes(before_images, after_images, output, label, env_id=index)
                  for index in range(base.num_envs)]
        assert not any(row['changed_values'] for row in pixels[other].values()), label
        assert any(row['changed_values'] for row in pixels[chosen].values()), label
        return pixels

    initial_images, initial_repeat, initial_state = capture_pair('before', info)
    initial_visibility = visibility()
    assert initial_visibility == {'free': [1., 1.], 'threaded': [0., 0.]}
    before = evidence.private_values(common, base, other, appearance=True)
    before_appearance = appearance_state(base)
    elapsed_before = base._elapsed_steps.clone()
    mask = torch.zeros(base.num_envs, dtype=torch.bool, device=base.device)
    mask[selected] = True
    assert bool(base._bolt_locked[chosen]) and not bool(base._nut_engaged.any())
    base._engage_newly_placed_nuts(mask)
    assert torch.equal(base._nut_engaged, mask)
    assert torch.equal(base._elapsed_steps, elapsed_before)
    engaged_visibility = visibility()
    assert engaged_visibility == {'free': [1., 0.], 'threaded': [0., 1.]}
    engaged_images, engaged_repeat, engaged_state = capture_pair('engaged', info)
    forward = verify_transition(initial_images, engaged_images, initial_state['after_repeat_capture'],
                                engaged_state['before_capture'], 'forward_swap')
    engaged = evidence.private_values(common, base, other, appearance=True)
    assert engaged == before and appearance_state(base) == before_appearance

    first_obs, info = env.reset(options={'env_idx': selected})
    restored_visibility = visibility()
    assert not bool(base._nut_engaged.any()) and restored_visibility == initial_visibility
    restored_images, restored_repeat, restored_state = capture_pair('restored', info, first_obs=first_obs)
    reverse = verify_transition(engaged_images, restored_images, engaged_state['after_repeat_capture'],
                                restored_state['before_capture'], 'reverse_swap')
    restored = evidence.private_values(common, base, other, appearance=True)
    for key in ('materials', 'physical', 'controller_unselected', 'task_rng_unselected', 'appearance_rng_unselected'):
        assert restored[key] == before[key], key
    expected_episode = before_appearance['episodes'].copy()
    expected_episode[chosen] += 1
    assert adapter.episodes == expected_episode and adapter.schemes == before_appearance['schemes']
    assert adapter.records[:-1] == before['records'] and adapter.records[-1]['env_idx'] == chosen
    torch.save({'initial': initial_state, 'engaged': engaged_state, 'restored': restored_state}, output / 'states.pt')
    report = {'status': 'passed', 'scope': 'direct native stage swap and local reset; no policy or task completion',
              'capture_path': 'standard ManiSkill CUDA RGB', 'selected': chosen, 'unselected': other,
              'reset_seed': seed, 'camera_names': sorted(initial_images),
              'control_steps': 0, 'physics_steps': 0, 'before_visibility': initial_visibility,
              'engaged_visibility': engaged_visibility, 'restored_visibility': restored_visibility,
              'first_vs_repeat': {'before': initial_repeat, 'engaged': engaged_repeat, 'restored': restored_repeat},
              'transition_pixels': {'forward': forward, 'reverse': reverse},
              **evidence.pairs(before, restored), 'engaged_private': engaged,
              'state_evidence': 'states.pt', 'state_sha256': sha(output / 'states.pt')}
    dump(output / 'checks.json', report)
    return {'status': 'passed', 'file': f'{output.name}/checks.json', 'sha256': sha(output / 'checks.json')}


def run_task(task, args, output, result):
    import gymnasium as gym
    import torch
    from tools.variation import nut_bolt_runtime_evidence as evidence
    common = helpers()
    env, base, reset_index, last_selected_evidence = None, None, 0, None
    gpu = args.sim_backend == 'physx_cuda'
    count = 2 if gpu else 1
    selected_all = list(range(count))
    interface = result['checks'].setdefault('interface_evidence', {})
    result.update(control_steps=0, physics_steps=0, reset_seed=args.seed,
                  candidate_visibility_camera=args.visibility_camera)

    def make(config=None):
        nonlocal env, base
        kwargs = {} if config is None else {'nut_bolt_appearance': config}
        if args.gpu_memory_profile == 'two_env':
            kwargs['sim_config'] = {'gpu_memory_config': TWO_ENV_GPU_MEMORY.copy()}
        env = gym.make(f'NutBolt{task}-Sharpa-v1', num_envs=count,
            sim_backend=args.sim_backend, obs_mode='rgb' if gpu else 'state',
            control_mode='pd_joint_pos', render_mode='rgb_array', reconfiguration_freq=0, **kwargs)
        base = env.unwrapped
        assert base.num_envs == count and base.backend.sim_backend == args.sim_backend
        assert base.device.type == ('cuda' if gpu else 'cpu')
        if gpu:
            assert base.scene.gpu_sim_enabled and base.scene._gpu_sim_initialized
        expected_config = common.plain(asdict(base._default_sim_config))
        if args.gpu_memory_profile == 'two_env':
            expected_config['gpu_memory_config'].update(TWO_ENV_GPU_MEMORY)
        resolved_config = common.plain(asdict(base.sim_config))
        assert resolved_config == expected_config, 'Unexpected resolved simulation config'
        assert result.setdefault('resolved_sim_config', resolved_config) == resolved_config
        memory = base.sim_config.gpu_memory_config
        result['resolved_gpu_memory_capacities'] = {name: int(getattr(memory, name)) for name in (
            'max_rigid_contact_count', 'max_rigid_patch_count', 'found_lost_pairs_capacity')}
        return base

    def reset(seed=None, options=None):
        nonlocal reset_index, last_selected_evidence
        if not gpu:
            return env.reset(seed=seed, options=options)
        row, prefix = {}, f'selected_reset_{reset_index:02d}'
        reset_index += 1
        try:
            value = common.selected_reset_check(env, seed, options, output, prefix, row)
            last_selected_evidence = prefix + '.json'
            return value
        finally:
            result['checks'].setdefault('selected_reset_state', []).append({'evidence': prefix + '.json', **row})

    def close():
        nonlocal env, base
        if env is not None:
            env.close()
            env = base = None
            gc.collect()
            if gpu:
                torch.cuda.empty_cache()

    def verify_measured(base, expected, native):
        measured = verify(common, base, expected, native)
        roles = evidence.material_roles(common, base)
        if 'material_roles' in result['checks']:
            assert roles == result['checks']['material_roles'], 'Actual material slot binding changed'
        else:
            result['checks']['material_roles'] = roles
        return measured

    def disabled_receipt(base, config, before, after, filename):
        torch.save({'before': before, 'after': after}, output / filename)
        return {'config': config, 'adapter_present': base._nut_bolt_appearance is not None,
            'materials': common.materials(base), 'physical': common.physical(base), 'state_evidence': filename}

    try:
        result['stage'] = 'reject malformed constructor per_env'
        invalid_constructor = {'enabled': False, 'per_env': {str(count): {'scheme_id': 'variant_1'}}}
        try:
            make(invalid_constructor)
        except ValueError as error:
            assert 'per_env' in str(error)
            interface['constructor_per_env_rejection'] = {
                'config': invalid_constructor, 'error': {'type': type(error).__name__, 'message': str(error)}}
        else:
            raise AssertionError('Malformed constructor per_env was accepted')
        result['stage'] = 'native baseline'
        base = make()
        _, info = reset(seed=args.seed)
        baseline_before = common.snapshot(base)
        native, physical = common.materials(base), common.physical(base)
        visibility = visual_state(common, base)
        _, info = reset(seed=args.seed)
        baseline = common.snapshot(base)
        assert base._nut_bolt_appearance is None
        assert not common.state_changes(baseline_before, baseline)
        assert common.materials(base) == native and common.physical(base) == physical
        native_info = common.plain(info)
        if base.has_nut:
            generated = ROOT / 'tasks/assets/task_object_meshes/screwing/threaded_nut_revolute.urdf'
            result['generated_urdf'] = {'path': generated.relative_to(ROOT).as_posix(), 'sha256': sha(generated)}
        original_images = common.capture(env, info) if gpu else None
        if gpu:
            assert set(original_images) == set(NATIVE_RGB_CAMERAS)
        result['backend'] = str(base.backend)
        result['capture_path'] = 'standard ManiSkill CUDA RGB' if gpu else 'not captured'
        dump(output / 'native_materials.json', native)
        dump(output / 'native_physical.json', physical)
        dump(output / 'native_visibility.json', visibility)
        torch.save(baseline, output / 'native_state.pt')
        interface['default_disabled'] = disabled_receipt(base, None, baseline_before, baseline,
                                                        'interface_default_disabled.pt')
        result['checks']['default_disabled'] = 'passed'
        if gpu:
            control = evidence.native_local(common, env, info, output, reset,
                lambda: last_selected_evidence, result, dump)
            for row in control['rounds']:
                assert not row['state_changes']
                assert not any(item['changed_values'] for item in row['pixel_changes'].values())
                assert row['materials_env0_unchanged'] and row['physical_unchanged']
                assert row['task_rng_unchanged'] and row['controller_unchanged']
            result['checks']['native_local_reset_control'] = control
        close()

        result['stage'] = 'explicit disabled'
        base = make({'enabled': False})
        _, info = reset(seed=args.seed)
        disabled_state = common.snapshot(base)
        assert base._nut_bolt_appearance is None
        assert not common.state_changes(baseline, disabled_state)
        assert common.materials(base) == native and common.physical(base) == physical
        assert common.plain(info) == native_info and visual_state(common, base) == visibility
        interface['explicit_disabled'] = disabled_receipt(base, {'enabled': False}, baseline,
            disabled_state, 'interface_explicit_disabled.pt')
        result['checks']['explicit_disabled'] = 'passed'
        close()

        candidate_images = {'original': original_images} if gpu else {}
        for scheme in SCHEMES:
            result['stage'] = 'fixed ' + scheme
            base = make({'enabled': True, 'scheme_id': scheme, 'seed': 71})
            _, info = reset(seed=args.seed)
            measured = verify_measured(base, [scheme] * count, native)
            fixed_records = copy.deepcopy(base._nut_bolt_appearance.records)
            assert not common.state_changes(baseline, common.snapshot(base))
            assert common.physical(base) == physical and common.plain(info) == native_info
            assert visual_state(common, base) == visibility
            before = appearance_state(base)
            if gpu:
                fixed = common.capture(env, info)
                common.save_image_pairs(original_images, fixed, output, 'fixed_' + scheme)
                differences = [common.image_changes(original_images, fixed, output,
                    f'fixed_{scheme}', env_id=index) for index in range(count)]
                if scheme == 'original':
                    assert not any(row['changed_values'] for item in differences for row in item.values())
                else:
                    assert all(any(row['changed_values'] for row in item.values()) for item in differences)
                    if args.visibility_camera:
                        assert all(item[args.visibility_camera]['changed_values'] > 0 for item in differences)
                    candidate_images[scheme] = fixed
            else:
                differences = []
            assert appearance_state(base) == before
            _, info = reset(seed=args.seed, options={'nut_bolt_appearance': {'scheme_id': 'original'}})
            verify_measured(base, ['original'] * count, native)
            if gpu:
                restored = common.capture(env, info)
                common.save_image_pairs(original_images, restored, output, 'restored_' + scheme)
                pixels = [common.image_changes(original_images, restored, output,
                    f'restored_{scheme}', env_id=index) for index in range(count)]
                assert not any(row['changed_values'] for item in pixels for row in item.values())
            result['checks']['fixed_' + scheme] = {'status': 'passed', 'materials': measured,
                'pixel_differences': differences, 'records': fixed_records,
                'restored_records': copy.deepcopy(base._nut_bolt_appearance.records)}
            close()

        if gpu and args.visibility_camera:
            pairs = visibility_pairs(candidate_images, args.visibility_camera, count)
            result['checks']['candidate_visibility_pairs'] = pairs
            close_pairs = [row for row in pairs if row['pixels_at_min_delta'] < MIN_WITNESS_PIXELS]
            assert not close_pairs, f'Candidate pairs not clearly separated: {close_pairs}'
        del candidate_images

        result['stage'] = 'configuration precedence and invalid request atomicity'
        constructor = {'enabled': True, 'scheme_id': 'original', 'seed': 71,
                       'per_env': {str(count - 1): {'scheme_id': 'variant_1'}}}
        base = make(constructor)
        cases = []
        for override, expected in (({}, ['variant_1'] if count == 1 else ['original', 'variant_1']),
                ({'scheme_id': 'variant_2', 'per_env': {str(count - 1): {'scheme_id': 'original'}}},
                 ['original'] if count == 1 else ['variant_2', 'original'])):
            before_records = copy.deepcopy(base._nut_bolt_appearance.records)
            _, info = reset(seed=args.seed, options={'nut_bolt_appearance': override})
            measured = verify_measured(base, expected, native)
            cases.append({'constructor': copy.deepcopy(constructor), 'reset': copy.deepcopy(override),
                'selected': selected_all.copy(), 'schemes': base._nut_bolt_appearance.schemes.copy(),
                'before_records': before_records, 'after_records': copy.deepcopy(base._nut_bolt_appearance.records),
                'materials': measured})
        interface['selection_precedence'] = cases
        request = {'mode': 'random_choice', 'scheme_ids': ['variant_1', 'variant_2'],
                   'per_env': {str(count - 1): {'scheme_ids': ['missing']}}}
        before = evidence.atomic_state(common, base)
        try:
            env.reset(options={'nut_bolt_appearance': request})
        except ValueError as error:
            error_type = type(error).__name__
        else:
            raise AssertionError('Invalid final environment request was accepted')
        after = evidence.atomic_state(common, base)
        assert after == before
        interface['invalid_request_atomicity'] = {'request': request, 'error_type': error_type,
                                                  'before': before, 'after': after}
        if gpu:
            result['stage'] = 'pre-reset option rejection'

            def rejection_state():
                return {**evidence.atomic_state(common, base),
                        'controller': [common.controller_state(base, index) for index in selected_all],
                        'episode_rng': [common.task_rng(base, index) for index in selected_all],
                        'main_rng': common.plain(base._main_rng.get_state()),
                        'batched_main_rng': [common.plain(base._batched_main_rng[index].get_state())
                                             for index in selected_all]}

            def reject_reset(name, request, expected_message, *, seed=None, restore=False):
                options = copy.deepcopy(request)
                if 'env_idx' in options:
                    options['env_idx'] = torch.tensor(options['env_idx'], device=base.device)
                if restore:
                    options['reset_to_env_states'] = {'env_states': base.get_state_dict()}
                before_rejection, before_state = rejection_state(), common.snapshot(base)
                try:
                    env.reset(seed=seed, options=options)
                except ValueError as error:
                    assert expected_message in str(error), f'{name}: {error}'
                    rejection = {'type': type(error).__name__, 'message': str(error)}
                else:
                    raise AssertionError(f'Reset accepted {name}')
                after_rejection, after_state = rejection_state(), common.snapshot(base)
                assert before_rejection == after_rejection and not common.state_changes(before_state, after_state), name
                state_file = f'{name}.pt'
                torch.save({'before': before_state, 'after': after_state}, output / state_file)
                row = {'request': request, 'seed': seed, 'actual_state_restore_payload': restore,
                       'error': rejection, 'before': before_rejection, 'after': after_rejection,
                       'state_evidence': state_file, 'state_sha256': sha(output / state_file)}
                dump(output / f'{name}.json', row)
                return row

            reject_reset('partial_seed_rejection', {'env_idx': [1]}, 'omit seed', seed=17)
            result['checks']['partial_seed_rejection'] = 'passed'
            requests = {
                'descending_env_idx_rejection': ({'env_idx': [1, 0]}, 'strictly increasing', False),
                'restore_override_rejection': ({'nut_bolt_appearance': {'scheme_id': 'variant_2'}},
                                               'state restoration', True),
                'reset_per_env_rejection': ({'nut_bolt_appearance': {
                    'mode': 'random_choice', 'scheme_ids': ['variant_1', 'variant_2'],
                    'per_env': {str(count): {'scheme_id': 'variant_2'}}}}, 'per_env', False),
            }
            interface['reset_preflight_rejections'] = {
                name: reject_reset(name, request, message, restore=restore)
                for name, (request, message, restore) in requests.items()}
        result['checks']['precedence_and_atomicity'] = 'passed'
        close()

        result['stage'] = 'random reproducibility'
        constructor = {'enabled': True, 'mode': 'random_choice', 'seed': 71, 'scheme_ids': list(SCHEMES)}
        runs, sequences = [], []
        pattern = ([0], [1], [0, 1]) if gpu else ([0],)
        for repeat in range(2):
            base = make(constructor)
            trace = []
            for index in range(12):
                selected = pattern[index % len(pattern)]
                before = appearance_state(base)
                reset(seed=args.seed if len(selected) == count else None,
                    options={'env_idx': torch.tensor(selected, device=base.device)})
                after = appearance_state(base)
                trace.append({'selected': selected.copy(), 'reset': {},
                    'before_rng': before['rng'], 'after_rng': after['rng'],
                    'before_records': before['records'], 'after_records': after['records']})
                dump(output / f'random_trace_{repeat + 1}.json', {'constructor': constructor, 'resets': trace,
                    'records': after['records']})
                verify_measured(base, base._nut_bolt_appearance.schemes, native)
            runs.append(trace)
            sequences.append(copy.deepcopy(base._nut_bolt_appearance.records))
            close()
        assert runs[0] == runs[1] and sequences[0] == sequences[1]
        interface['random_reproducibility'] = {'constructor': constructor, 'runs': runs}
        result['checks']['random_reproducibility'] = {'status': 'passed', 'records': sequences[0],
            'traces': [{'file': f'random_trace_{repeat + 1}.json',
                        'sha256': sha(output / f'random_trace_{repeat + 1}.json')} for repeat in range(2)]}

        if gpu:
            result['stage'] = 'two-environment local reset isolation'
            base = make({'enabled': True, 'scheme_id': SCHEMES[3], 'seed': 71,
                         'per_env': {'1': {'scheme_id': SCHEMES[-1]}}})
            _, info = reset(seed=args.seed)
            rounds = []
            for index, selected in enumerate((1, 0)):
                other, prefix = 1 - selected, f'local_{index}'
                primed = evidence.prime(common, base, output, f'appearance_prime_{index}')
                if index:
                    info = evidence.step(common, env, primed, output, result, 'appearance')
                before_capture = common.snapshot(base)
                before_images = common.capture(env, info)
                before_state = common.snapshot(base)
                assert not common.state_changes(before_capture, before_state), 'Capture changed local initial state'
                private_before = evidence.private_values(common, base, other, appearance=True)
                appearance = appearance_state(base)
                visibility_before = visual_state(common, base)
                _, info = reset(options={'env_idx': torch.tensor([selected], device=base.device),
                    'nut_bolt_appearance': {'scheme_id': 'original'}})
                associated = last_selected_evidence
                after_reset = common.snapshot(base)
                after_images = common.capture(env, info)
                after_state = common.snapshot(base)
                assert not common.state_changes(after_reset, after_state), 'Capture changed reset state'
                private_after = evidence.private_values(common, base, other, appearance=True)
                changes = common.state_changes(before_state, after_state, [other])
                pixels = common.image_changes(before_images, after_images, output, prefix, env_id=other)
                selected_pixels = common.image_changes(before_images, after_images, output, prefix, env_id=selected)
                assert not changes and not any(row['changed_values'] for row in pixels.values())
                for key in ('controller_unselected', 'task_rng_unselected', 'appearance_rng_unselected', 'physical'):
                    assert private_before[key] == private_after[key], key
                assert private_before['materials'][other] == private_after['materials'][other]
                assert private_after['materials'][selected] == native[selected]
                assert visual_state(common, base)[other] == visibility_before[other]
                assert visual_state(common, base)[selected] == visibility[selected]
                after = appearance_state(base)
                assert after['episodes'][other] == appearance['episodes'][other]
                assert [r for r in after['records'] if r['env_idx'] == other] == [
                    r for r in appearance['records'] if r['env_idx'] == other]
                expected = appearance['schemes'].copy()
                expected[selected] = 'original'
                verify_measured(base, expected, native)
                torch.save({'before': before_state, 'after': after_state,
                            'after_reset_before_capture': after_reset}, output / (prefix + '.pt'))
                common.save_image_pairs(before_images, after_images, output, prefix)
                row = {'selected': [selected], 'unselected': other, 'state_changes': changes,
                    'state_evidence': prefix + '.pt', 'selected_state_evidence': associated,
                    'controller_precondition': primed, 'precondition_control_steps': index,
                    'precondition_physics_steps': index * int(base._sim_steps_per_control),
                    'pixel_changes': pixels, 'selected_pixel_changes': selected_pixels,
                    **evidence.pairs(private_before, private_after), 'status': 'passed'}
                dump(output / (prefix + '.json'), row)
                rounds.append(row)
                # This additional cycle follows the frozen local raw receipt and
                # does not alter the reset/step causal sequence or physical state.
                for scheme in (appearance['schemes'][selected], 'original'):
                    base._nut_bolt_appearance.finish_reset(torch.tensor([selected]),
                        {'nut_bolt_appearance': {'scheme_id': scheme}})
                restored = common.capture(env, info)
                restoration = common.image_changes(after_images, restored, output,
                    f'local_original_{index}', env_id=selected)
                common.save_image_pairs(after_images, restored, output, f'local_original_{index}')
                assert not any(item['changed_values'] for item in restoration.values())
            verify_measured(base, base._nut_bolt_appearance.schemes, native)
            result['checks']['local_reset_isolation'] = rounds
            assert result['control_steps'] == 2 and result['physics_steps'] == 40
            if task == 'SeatNut':
                result['stage'] = 'standard CUDA RGB across native nut representation changes'
                result['checks']['stage_visibility_fixture'] = stage_visibility_fixture(
                    common, env, args.seed, output / 'stage_visibility_fixture')
        result['status'] = 'passed'
    finally:
        try:
            if 'generated_urdf' in result:
                assert sha(ROOT / result['generated_urdf']['path']) == result['generated_urdf']['sha256']
        finally:
            close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-runtime', action='store_true', required=True)
    parser.add_argument('--sim-backend', choices=('physx_cpu', 'physx_cuda'), required=True)
    parser.add_argument('--experimental-windows-cuda', action='store_true')
    parser.add_argument('--physx-gpu-dir', type=Path)
    parser.add_argument('--gpu-memory-profile', choices=('default', 'two_env'), default='default',
                        help='Checker-only GPU buffer allocation profile; physical solver settings stay frozen')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', action='append', choices=TASKS)
    parser.add_argument('--seed', type=int, default=7, help='Task reset seed, independent of appearance seed')
    parser.add_argument('--visibility-camera', choices=NATIVE_RGB_CAMERAS,
                        help='Compare all scheme pairs in this original RGB camera for both environments')
    args = parser.parse_args()
    if not 0 <= args.seed < 2**32:
        parser.error('--seed must be within the native 32-bit reset range')
    if args.visibility_camera and args.sim_backend != 'physx_cuda':
        parser.error('--visibility-camera requires standard CUDA RGB')
    args.output.mkdir(parents=True, exist_ok=False)
    result = {'status': 'running', 'tasks': [], 'control_steps': 0, 'physics_steps': 0,
              'test_mode': 'standard', 'formal_acceptance': 'pending' if args.sim_backend == 'physx_cuda' else 'NOT TESTED: CPU only',
              'scope': 'two-environment GPU reset isolation' if args.sim_backend == 'physx_cuda' else 'single-environment CPU material/state checks'}
    started, manifest = time.monotonic(), None
    try:
        sys.path.insert(0, str(ROOT))
        import sapien
        if args.sim_backend == 'physx_cuda' and platform.system() == 'Windows':
            if not args.experimental_windows_cuda:
                raise RuntimeError('Windows CUDA requires the explicit experimental bootstrap')
            import ctypes
            cache = args.physx_gpu_dir or Path.home() / '.sapien/physx' / sapien.physx.version()
            dll_directory = os.add_dll_directory(str(cache))
            dll_handles = [ctypes.WinDLL(str(cache / name)) for name in ('PhysXDevice64.dll', 'PhysXGpu_64.dll')]
            if not sapien.physx.is_gpu_enabled():
                sapien.physx._enable_gpu()
        from mani_skill.utils import download_asset
        def reject_download(*args, **kwargs):
            raise RuntimeError('Prepare authorized task assets before running checks')
        download_asset.download = download_asset.download_from_hf_datasets = reject_download
        import tasks
        selected = args.task or TASKS
        manifest = {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'command': sys.argv, 'platform': platform.platform(), 'sim_backend': args.sim_backend,
            'num_envs': 2 if args.sim_backend == 'physx_cuda' else 1, 'test_mode': 'standard',
            'reset_seed': args.seed, 'candidate_visibility_camera': args.visibility_camera,
            'gpu_memory_profile': args.gpu_memory_profile,
            'catalog_version': json.loads(CATALOG.read_text())['version'], 'task_ids': [f'NutBolt{task}-Sharpa-v1' for task in selected],
            'versions': {name: metadata.version(name) for name in ('sapien', 'mani_skill', 'torch', 'numpy', 'gymnasium')},
            'sapien_binary': {'path': sapien.pysapien.__file__, 'sha256': sha(sapien.pysapien.__file__)},
            'sdk_native_files': sdk_identity(sapien),
            'native_capabilities': {name: getattr(sapien.physx, name)()
                if callable(getattr(sapien.physx, name, None)) else None for name in
                ('indexed_gpu_apply_patch_version', 'native_gpu_lock_sync_patch_version')},
            'files': source_hashes(), 'external_files': external_hashes()}
        dump(args.output / 'manifest.json', manifest)
        for task in selected:
            row = {'task': task, 'status': 'running', 'checks': {}}
            result['tasks'].append(row)
            directory = args.output / task; directory.mkdir()
            try:
                run_task(task, args, directory, row)
            except BaseException:
                row.update(status='failed', error=traceback.format_exc())
                raise
            finally:
                dump(args.output / 'results.json', result)
        result['status'] = 'passed'
        if args.sim_backend == 'physx_cuda':
            result['formal_acceptance'] = 'passed'
    except BaseException:
        result.update(status='failed', error=traceback.format_exc())
        if args.sim_backend == 'physx_cuda':
            result['formal_acceptance'] = 'failed'
    finally:
        if manifest is not None:
            result['source_hashes_unchanged'] = manifest['files'] == source_hashes()
            result['external_hashes_unchanged'] = manifest['external_files'] == external_hashes()
            result['sdk_native_files_unchanged'] = manifest['sdk_native_files'] == sdk_identity(sapien)
            if not result['source_hashes_unchanged']:
                result.update(status='failed', error='Source files changed during validation')
            if not result['sdk_native_files_unchanged']:
                result.update(status='failed', error='SDK libraries changed during validation')
            if not result['external_hashes_unchanged']:
                result.update(status='failed', error='External dependencies changed during validation')
        result['elapsed_seconds'] = time.monotonic() - started
        result['png_sha256'] = {path.relative_to(args.output).as_posix(): sha(path)
                               for path in sorted(args.output.rglob('*.png'))}
        for key in ('control_steps', 'physics_steps'):
            result[key] = sum(row.get(key, 0) for row in result['tasks'])
        if args.sim_backend == 'physx_cuda' and result['status'] != 'passed':
            result['formal_acceptance'] = 'failed'
        if manifest is not None:
            manifest['resolved_sim_config'] = {row['task']: row.get('resolved_sim_config') for row in result['tasks']}
            manifest['resolved_gpu_memory_capacities'] = {
                row['task']: row.get('resolved_gpu_memory_capacities') for row in result['tasks']}
            dump(args.output / 'manifest.json', manifest)
        dump(args.output / 'results.json', result)
        print(json.dumps({'status': result['status'], 'tasks': [(row['task'], row['status']) for row in result['tasks']]}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
