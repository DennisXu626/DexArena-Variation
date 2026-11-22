"""Recompute build, raster and native PhysX evidence from saved Nut SDK probes, without simulation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import sys

import torch


VERSION = '3.0.3+dexarena.gpu1.wininterop7'
RELEASE = Path('tools/variation/sapien_sdk/native_lock')
PHASE_STEPS = {'runtime_lock': 20, 'runtime_switch': 20, 'individual_lock': 20,
               'individual_unlock': 20, 'contact': 80}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as handle:
        digest = hashlib.sha256()
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def tensor(value, shape, dtype=torch.float32):
    require(isinstance(value, torch.Tensor) and tuple(value.shape) == shape
            and value.dtype == dtype and bool(torch.isfinite(value).all()), f'Unexpected raw tensor: {shape}/{dtype}')
    return value


def load_pt(directory, name, expected):
    path = directory / name
    require(sha(path) == expected, f'{name}: raw SHA differs')
    return torch.load(path, map_location='cpu', weights_only=True)


def raw_hashes(directory, names):
    require({path.name for path in directory.iterdir()} == set(names), 'Unexpected or missing probe file')
    return {name: sha(directory / name) for name in names}


def sdk_identity(repo, sdk_root, expected):
    release = repo / RELEASE
    manifest = read(release / 'COPY_MANIFEST.json')
    require(manifest['version'] == VERSION, 'Wrong released SDK source manifest')
    for name, digest in manifest['files_sha256'].items():
        path = (release / name).resolve(strict=True)
        require(path.is_relative_to(release) and sha(path) == digest, f'Released SDK source differs: {name}')
    spec = importlib.util.spec_from_file_location('_released_nut_identity', release / 'tools/native_lock_identity.py')
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    identity = validator.validate_sdk(sdk_root, expected_artifact_sha256=expected,
                                      base_recipe_root=repo / RELEASE.parent)
    receipt = read(sdk_root / 'artifact.json')
    patch = 'recipe-v6/patches/0310-batched-render-visibility.patch'
    require(identity['version'] == VERSION and identity['build']['clean_full_build_executed'] is True
            and sha(release / 'recipe-v6/lock.json') == manifest['recipe_lock_sha256'] == identity['lock_sha256']
            and sha(release / patch) == manifest['visibility_patch_sha256']
            and [row['sha256'] for row in receipt['patches']
                 if row['file'] == 'patches/0310-batched-render-visibility.patch'] == [manifest['visibility_patch_sha256']],
            'Build/visibility patch does not match released v7')
    public = {name: identity[name] for name in ('version', 'artifact_sha256', 'source_commit', 'wheel_sha256',
        'lock_sha256', 'capabilities_expected', 'wheel_record_entries_verified')}
    public.update(visibility_patch_sha256=manifest['visibility_patch_sha256'],
                  release_manifest_sha256=sha(release / 'COPY_MANIFEST.json'),
                  build_mode=identity['build']['build_mode'],
                  clean_full_build_executed=True,
                  physx_host_dependency_reused=identity['build']['physx_host_dependency_reused'])
    return identity, public


def monitor(directory, capture, repo, source, sdk, monitor_tool):
    process, resource = (read(directory / name) for name in ('process.json', 'resource.json'))
    command = process['command']
    require(resource['command'] == command and len(command) >= 5
            and process['returncode'] == resource['returncode'] == 0
            and process['timed_out'] is False and not resource.get('stopped')
            and type(resource['owned_pid']) is int and resource['owned_pid'] > 0
            and sha(monitor_tool) == resource['launcher_sha256'], 'Process/monitor receipt differs or did not complete')
    windows_path = PureWindowsPath
    captured_repo = windows_path(command[command.index('--repo-root') + 1])
    captured_sdk = windows_path(command[command.index('--sdk-root') + 1])
    captured_output = windows_path(command[command.index('--output') + 1])
    require(windows_path(command[2]) == captured_repo / windows_path((RELEASE / 'tools/launch_native_lock.py').as_posix())
            and windows_path(command[command.index('--') - 1]) == captured_repo / windows_path(source.relative_to(repo).as_posix())
            and captured_output.name == capture.name
            and command[command.index('--artifact-sha256') + 1] == sdk['artifact_sha256'],
            'Recorded launch did not select the reviewed probe/source/SDK')
    streams = {name: sha(directory / name) for name in ('stdout.txt', 'stderr.txt')}
    require(process['streams_sha256'] == streams, 'Probe console bytes differ')
    initial, samples = resource['initial'], resource['samples']
    require(initial['free_mib'] >= 2048 and initial['util_percent'] < 70 and samples
            and resource['delta_limit_mib'] == 1792 and resource['stop_free_mib'] == 512, 'Resource gates differ')
    low, peak, time = initial['free_mib'], 0, initial['time']
    for row in samples:
        delta = row['used_mib'] - initial['used_mib']
        require(delta == row['delta_mib'] and delta <= 1792 and row['free_mib'] > 512 and row['time'] >= time,
                'Resource sample violated a gate')
        low, peak, time = min(low, row['free_mib']), max(peak, delta), row['time']
    require(peak == resource['max_delta_mib'] and low == resource['min_free_mib']
            and resource['final']['time'] >= time, 'Monitored samples disagree with summary')
    return captured_sdk, {'returncode': 0, 'initial_free_mib': initial['free_mib'],
        'sample_count': len(samples), 'max_delta_mib': peak, 'min_free_mib': low,
        'raw_file_sha256': raw_hashes(directory, ['process.json', 'resource.json', 'stdout.txt', 'stderr.txt']),
        'empty_console_streams': all((directory / name).stat().st_size == 0 for name in streams)}


def loaded_check(loaded, sdk, captured_root):
    require(set(loaded) == set(sdk['required_loaded']), 'Missing loaded SDK modules')
    module_hashes = {}
    for name, row in loaded.items():
        subdir = 'physx-runtime' if name in sdk['physx_gpu']['dll_sha256'] else 'runtime/sapien'
        target = Path(sdk['sdk_root']) / subdir / name
        require(PureWindowsPath(row['path']) == captured_root / PureWindowsPath(subdir) / name
                and row['sha256'] == sdk['expected_loaded'][name] == sha(target), f'Loaded module path/SHA differs: {name}')
        module_hashes[name] = row['sha256']
    return module_hashes


def validate_source(directory, source, report, digest_key):
    source_digest = sha(source)
    require(report[digest_key] == source_digest == sha(directory / 'probe_source.py'), 'Retained and released probe sources differ')
    return source_digest


def buffers(raw):
    require(isinstance(raw, (list, tuple)) and len(raw) == 2 and all(len(side) == 2 for side in raw),
            'Two environments are required in both transform buffers')
    return [[tensor(value, shape) for value in group] for group, shape in zip(raw, ((2, 4, 4), (66,)))]


def raster_check(directory, report):
    raw = load_pt(directory, 'captures.pt', report['captures_sha256'])
    frames = {'first_gpu_frame': (0, 0), 'env0_threaded': (1, 0), 'env0_free_restored': (0, 0),
              'env1_threaded': (0, 1), 'env1_free_restored': (0, 0)}
    require(set(raw) == {'cpu_warmup', *frames} and set(report['captures']) == set(frames),
            'Missing baseline, flip or restore frames')
    warmup = buffers(raw['cpu_warmup']['actor_and_camera_buffers'])
    first = raw['first_gpu_frame']
    baseline = tensor(first['cuda_poses'], (6, 7))
    expected_baseline = torch.tensor([[2, -.375, 0, 1, 0, 0, 0], [2, .375, 0, 1, 0, 0, 0], [0, 0, 0, 1, 0, 0, 0],
        [2, -.25, 0, 1, 0, 0, 0], [2, .5, 0, 1, 0, 0, 0], [0, .125, 0, 1, 0, 0, 0]], dtype=torch.float32)
    require(torch.equal(baseline, expected_baseline), 'Initial device poses differ from the source fixture')
    first_buffers = buffers(first['before'])
    for env in range(2):
        require(torch.equal(warmup[0][env][:2, 3, :3], torch.tensor([[2., 8., 0.], [2., 8., 0.]]))
                and torch.equal(warmup[1][env][44:47], torch.tensor([0., -8., 0.]))
                and not torch.equal(warmup[0][env], first_buffers[0][env])
                and not torch.equal(warmup[1][env][:16], first_buffers[1][env][:16]),
                'CPU warmup cannot distinguish device poses')
    ids = []
    for env in range(2):
        def foreground_ids(value):
            identifiers = value.unique().tolist()
            require(len(identifiers) == 2 and identifiers[0] == 0 and identifiers[1] > 0, 'Ambiguous raster segmentation')
            return identifiers[1]
        free = foreground_ids(first['segmentation'][env])
        threaded = foreground_ids(raw[f'env{env}_threaded']['segmentation'][env])
        require(free != threaded, 'Representations do not have distinct segmentation IDs')
        ids.append((free, threaded))
    buffer_marker = None
    reviewed = {}
    for label, representations in frames.items():
        case, row = raw[label], report['captures'][label]
        before, after = buffers(case['before']), buffers(case['after'])
        poses = tensor(case['cuda_poses'], (6, 7))
        rgb = tensor(case['rgb'], (2, 64, 80, 3))
        seg = tensor(case['segmentation'], (2, 64, 80), torch.int32)
        marker = [*row['object_buffers'], *row['camera_buffers']]
        require(len(row['object_buffers']) == len(row['camera_buffers']) == 2
                and len(set(marker)) == 4 and all(type(ptr) is int and ptr > 0 for ptr in marker)
                and (buffer_marker is None or marker == buffer_marker), 'A recorded transform/camera buffer pointer changed')
        buffer_marker = marker
        require(row['phase'] == 'passed' and row['visible_representation'] == list(representations),
                f'{label}: captured visibility labels differ')
        expected = baseline.clone()
        if 1 in representations:
            env = representations.index(1)
            expected[env * 3:env * 3 + 3, 1] += torch.tensor([.125, -.125, .125])
        require(torch.equal(poses, expected), f'{label}: selected CUDA pose edits or unselected input changed')
        counts, changes, seg_changes = [], [], []
        for env, visible in enumerate(representations):
            measured = [int((seg[env] == value).sum()) for value in ids[env]]
            require(measured[visible] > 0 and measured[1 - visible] == 0
                    and set(seg[env].unique().tolist()) == {0, ids[env][visible]}, f'{label}: wrong segmentation')
            counts.append(measured)
            require(torch.equal(before[0][env][:2, 3, :3], poses[env * 3:env * 3 + 2, :3])
                    and torch.equal(before[1][env][44:47], poses[env * 3 + 2, :3])
                    and all(torch.equal(prev[env], cur[env]) for prev, cur in zip(before, after)),
                    f'{label}: raw actor/camera pose overwritten while rendering')
            pixel_changes = int((rgb[env] != first['rgb'][env]).any(-1).sum())
            seg_delta = int((seg[env] != first['segmentation'][env]).sum())
            require((pixel_changes > 0 and seg_delta > 0) if visible else (pixel_changes == seg_delta == 0),
                    f'{label}: expected selected pixel change or exact unselected/restored pixels')
            if not visible:
                require(all(torch.equal(cur[env], base[env]) for cur, base in zip(before, first_buffers)),
                        f'{label}: unselected or restored transform/camera buffer changed')
            changes.append(pixel_changes)
            seg_changes.append(seg_delta)
        require(counts == row['object_pixel_counts'], 'Segmentation counts disagree with actual pixels')
        reviewed[label] = {'visible_representation': list(representations), 'segmentation_pixels': counts,
                           'changed_rgb_pixels_vs_first': changes, 'changed_segmentation_pixels_vs_first': seg_changes}
    negatives = report['structure_negative']
    require([row['case'] for row in negatives] == ['add_object_env0', 'remove_camera_env1']
            and all('Modifying a scene (add/remove object/camera) is not allowed' in row['error'] for row in negatives),
            'Structural negative cases are incomplete or report the wrong guard')
    require(report['artifact_and_loaded_files_unchanged'] is True, 'Raster changed its captured input bytes')
    return {'device_rgb_resolution': [64, 80], 'environments': 2, 'physics_steps': 0,
            'scoped_rgb_and_segmentation_restored_exactly': True, 'frames': reviewed,
            'cpu_shadow_distinguished_in_both_environments': True, 'pose_and_camera_buffers_before_after_exact': True,
            'four_recorded_buffer_pointer_markers_stable': True, 'structure_guard_cases': negatives,
            'identity_limit': 'Native modules verified during launch; capture rehashed files after. No Python before/after receipt in this raster probe.'}


def native_check(directory, report):
    states = load_pt(directory, 'states.pt', report['states_sha256'])
    auxiliary = load_pt(directory, 'auxiliary.pt', report['auxiliary_sha256'])
    phases = ('initial', 'after_runtime_lock_before_step', 'after_lock_20', 'after_switch_before_step', 'after_switch_20',
              'before_axes', 'after_axes_locked_20', 'after_axes_unlock_before_step', 'after_axes_unlocked_20',
              'before_indexed_restore', 'after_indexed_restore', 'after_contact_80')
    require(set(states) == set(phases) and set(auxiliary) == {'expected_selected', 'contact_impulses'}
            and report['physics_steps'] == sum(PHASE_STEPS.values()) and report['phase_steps'] == PHASE_STEPS,
            'Native phases or explicit step counts differ')
    for name in phases:
        tensor(states[name], (12, 13))
        require(states[name].tolist() == report['values'][name], f'{name}: raw tensor and printout differ')
    indices, axes, contact = (report[key] for key in ('indices', 'axis_indices', 'contact_indices'))
    require([len(indices), len(axes), len(contact)] == [3, 6, 3]
            and all(type(i) is int for i in indices + axes + contact)
            and sorted(indices + axes + contact) == list(range(12)), 'Fixture body IDs overlap or omit bodies')
    require(report['all_axis_lock_flags'] == [[False] * 6, [True] * 6, [True] * 6]
            and report['all_axis_switch_flags'] == report['flags'] == [[True] * 6, [False] * 6, [False] * 6]
            and report['one_axis_lock_flags'] == torch.eye(6, dtype=torch.bool).tolist()
            and report['one_axis_unlock_flags'] == [[False] * 6] * 6, 'Actual lock-mask receipt differs')
    for before, after in [('initial', 'after_runtime_lock_before_step'), ('after_lock_20', 'after_switch_before_step'),
                          ('after_axes_locked_20', 'after_axes_unlock_before_step'),
                          ('after_axes_unlocked_20', 'before_indexed_restore')]:
        require(torch.equal(states[before], states[after]), f'Native state changed without an explicit step: {before}')
    initial, locked, switched = (states[name] for name in ('initial', 'after_lock_20', 'after_switch_20'))
    free, follower, prelocked = indices
    require(locked[free, 2] < .99 and locked[free, 9] < 0
            and torch.equal(locked[[follower, prelocked], :7], initial[[follower, prelocked], :7])
            and not locked[[follower, prelocked], 7:].count_nonzero()
            and torch.equal(switched[free, :7], locked[free, :7]) and not switched[free, 7:].count_nonzero()
            and bool((switched[[follower, prelocked], 2] < .99).all())
            and switched[follower, 2] - locked[follower, 2] == switched[prelocked, 2] - locked[prelocked, 2]
            and torch.equal(switched[follower, 3:], switched[prelocked, 3:]), 'Six-axis lock/release did not affect actual motion')
    locked_axes = states['after_axes_locked_20'][axes]
    unlocked_axes = states['after_axes_unlocked_20'][axes]
    matrix = locked_axes[:, 7:]
    diagonal = torch.eye(6, dtype=torch.bool)
    require(not matrix[diagonal].count_nonzero() and bool((matrix[~diagonal] != 0).all())
            and bool((unlocked_axes[:, 7:][diagonal] != 0).all())
            and torch.equal(locked_axes[:3, :3].diag(), states['before_axes'][axes[:3], :3].diag()),
            'Per-axis actual velocity or linear coordinate differs from lock/release contract')
    before, after = states['before_indexed_restore'], states['after_indexed_restore']
    expected = before[free].clone()
    expected[0] += .001
    expected[7:] = torch.tensor([.01, .02, .03, .04, .05, .06])
    limit = 2e-6
    error = float((expected - after[free]).abs().max())
    unaffected = [index for index in range(12) if index != free]
    require(torch.equal(tensor(auxiliary['expected_selected'], (13,)), expected) and error <= limit
            and report['indexed_restore_absolute_tolerance'] == limit
            and bool((after[free, 7:] != 0).all()) and torch.equal(before[unaffected], after[unaffected]),
            'Indexed restore either misses an intended field or affects another body')
    support, supported, unsupported = contact
    final = states['after_contact_80']
    impulses = auxiliary['contact_impulses']
    require(len(impulses) == 80, 'Missing contact step impulses')
    peaks = [float(tensor(value, (1, 3)).abs().max()) for value in impulses]
    require(torch.equal(final[support, :7], states['before_axes'][support, :7])
            and final[supported, 2] > .36 and final[unsupported, 2] < .2
            and any(peak > 0 for peak in peaks)
            and final[free, 0] == after[free, 0] and not final[free, 7:].count_nonzero(),
            'Missing active contact or unintended movement of a locked body')
    return {'scene_count': 1, 'body_count': 12, 'step_seconds': 1 / 240, 'physics_steps': sum(PHASE_STEPS.values()),
            'phase_steps': PHASE_STEPS, 'snapshot_count': len(states), 'six_locked_velocity_components': matrix.diag().tolist(),
            'six_released_velocity_components': unlocked_axes[:, 7:].diag().tolist(),
            'unselected_restore_body_count': len(unaffected), 'unselected_restore_exact': True,
            'selected_restore_absolute_error': error, 'selected_restore_absolute_tolerance': limit,
            'selected_restored_linear_angular_velocities': after[free, 7:].tolist(),
            'locked_support_pose_drift': 0, 'contact_frames_with_nonzero_impulse': sum(peak > 0 for peak in peaks),
            'contact_peak_abs_axis_impulse': max(peaks), 'supported_and_unsupported_final_z': final[[supported, unsupported], 2].tolist()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('repo', 'sdk-root', 'raster', 'raster-monitor', 'native-lock', 'native-lock-monitor', 'monitor-tool', 'output'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args()
    repo, sdk_root = args.repo.resolve(strict=True), args.sdk_root.resolve(strict=True)
    release = repo / RELEASE
    reports = {name: read(directory / 'results.json') for name, directory in
               (('raster', args.raster), ('native', args.native_lock))}
    expected = reports['raster']['artifact_sha256']
    require(reports['native']['artifact_sha256'] == expected and all(row['status'] == 'passed' for row in reports.values()),
            'Probes did not complete or use the same artifact')
    sdk, identity = sdk_identity(repo, sdk_root, expected)
    rows = {}
    for name, directory, monitor_dir, source, digest_key, loader_key, file_names in (
            ('raster', args.raster, args.raster_monitor, release / 'tools/probe_batched_visibility.py',
             'probe_source_sha256', 'loaded_modules', ['captures.pt']),
            ('native', args.native_lock, args.native_lock_monitor, release / 'probes/check_runtime_lock.py',
             'source_sha256', 'sdk_before', ['states.pt', 'auxiliary.pt'])):
        report = reports[name]
        source_digest = validate_source(directory, source, report, digest_key)
        require(report['resource_before']['free_mib'] >= 2048 and
                report['resource_before'].get('utilization_percent', report['resource_before'].get('gpu_utilization_percent', 100)) < 70,
                'Probe in-process startup gate was not met')
        captured_sdk, resources = monitor(monitor_dir, directory, repo, source, sdk, args.monitor_tool)
        modules = loaded_check(report[loader_key], sdk, captured_sdk)
        if name == 'raster':
            verified = raster_check(directory, report)
        else:
            require(all(report.get(flag) is True for flag in ('inputs_unchanged', 'binaries_unchanged', 'python_source_unchanged'))
                    and report['sdk_after'] == report['sdk_before'] and report['version'] == VERSION
                    and all(report[key] == expected for key, expected in sdk['capabilities_expected'].items()),
                    'Native probe capability/SDK identity differs')
            python_root = sdk_root / 'runtime'
            python_hashes = {path.relative_to(python_root).as_posix(): sha(path)
                             for path in sorted((python_root / 'sapien').rglob('*.py'))}
            require(python_hashes and python_hashes == report['sdk_python_before'] == report['sdk_python_after'],
                    'Private SDK Python sources changed')
            verified = native_check(directory, report)
            verified['sdk_python_sha256'] = python_hashes
        rows[name] = {**verified, 'loaded_native_sha256': modules, 'monitor': resources,
                      'probe_source': source.relative_to(repo).as_posix(), 'probe_source_sha256': source_digest,
                      'raw_file_sha256': raw_hashes(directory, ['results.json', 'probe_source.py', *file_names])}
    require(rows['raster']['loaded_native_sha256'] == rows['native']['loaded_native_sha256'], 'Raw loaded SDKs differ')
    report = {'schema': 'nut-bolt-v7-sdk-probe-evidence-v1', 'status': 'passed',
              'scope': 'Offline recomputation of supplementary raster/PhysX fixtures, separate from task acceptance',
              'exporter_sha256': sha(Path(__file__)), 'sdk': identity, **rows}
    with args.output.open('x', encoding='utf-8', newline=chr(10)) as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'status': 'passed', 'raster_frames': len(rows['raster']['frames']),
                      'native_steps': rows['native']['physics_steps']}))


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, RuntimeError, ValueError) as error:
        print(f'Probe evidence rejected: {error}', file=sys.stderr)
        raise SystemExit(2)
