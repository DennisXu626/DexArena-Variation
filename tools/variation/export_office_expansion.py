"""Recompute Office appearance evidence from the raw CPU and CUDA captures."""
import argparse
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.variation import compact_task_runtime as audit
from tools.variation import check_office_devices_runtime as runtime
from tools.variation.check_office_devices import catalog_check

FAMILY = 'office_desk'
PROFILE = audit.PROFILES[FAMILY]
REVIEW_IMAGES = (
    'OpenLaptop/original_human_env0.png',
    'OpenLaptop/variant_3_human_env0.png',
    'OpenLaptop/variant_10_human_env0.png',
    'TypeKeys/local_0_base_camera_env0.png',
    'TypeKeys/local_0_base_camera_env1.png',
    'OpenLaptop/keycaps_variant_8_front_detail_env0.png',
    'TypeKeys/keycaps_variant_4_human_env0.png',
)


def check_process(directory):
    receipt = directory.with_suffix('.process.json')
    record = audit.read(receipt)
    assert record['exit_code'] == 0
    assert (ROOT / audit.flag(record['command'], '--output')).resolve() == directory.resolve()
    for stream in ('stdout', 'stderr'):
        log = directory.with_suffix(f'.{stream}.log')
        assert audit.track(log) == record[f'{stream}_sha256']
        assert not re.search(r'contact.{0,15}overflow|lost.{0,8}contacts|dropped.{0,8}contacts|out of memory|fall(?:ing)? back to CPU',
                             log.read_text(encoding='utf-8', errors='replace'), re.IGNORECASE)
    return {**{key: record[key] for key in ('started_utc', 'ended_utc', 'exit_code', 'stdout_sha256', 'stderr_sha256')},
            'arguments': audit.portable_command([record['executable'], *record['command']], ROOT),
            'receipt_sha256': audit.track(receipt)}


def check_sdk(directory, source, checker, artifact, expected, required, gpu):
    file = directory / 'private_sdk.json'
    record = audit.read(file)
    assert record['artifact_sha256'] == audit.track(artifact)
    assert record['version'] == '3.0.3+dexarena.gpu1.wininterop5' and record['binaries_unchanged']
    audit.launcher_check(record, ROOT, f'tools/variation/{checker}', source)
    native, binding = audit.sdk_check(record['before'], record['after'], expected, required, gpu=gpu)
    return {'receipt_sha256': audit.track(file), 'binaries': native,
            'python': audit.sdk_python_check(record, binding)['map_sha256'],
            'system_vulkan_loader': audit.vulkan_loader_check(record)}


def check_strip(directory, evidence, parameters, native, fixed_materials, schemes):
    stages = {'native_off': None, **{s: s for s in schemes},
              **{f'restored_from_{s}': 'original' for s in schemes[1:]}}
    assert set(evidence['stages']) == set(stages)
    file = audit.inside(directory, evidence['file'])
    assert evidence['schema_version'] == 1 and audit.track(file) == evidence['sha256']
    with np.load(file, allow_pickle=False) as archive:
        seen = set()

        def read_pixels(row, key):
            assert row['key'] == key and key not in seen
            array = archive[key]
            assert array.shape == (721, 1547, 4) and list(array.shape) == row['shape']
            assert array.dtype == np.uint8 and row['dtype'] == 'uint8' and np.all(array[..., 3] == 255)
            assert hashlib.sha256(array.tobytes()).hexdigest() == row['sha256']
            seen.add(key)
            return array

        def safe_sha(materials):
            row, = [x for x in materials if x['logical_group'] == 'safe']
            return row['material']['base_color_texture']['data_sha256']

        original = []
        for stage, scheme in stages.items():
            rows = evidence['stages'][stage]
            assert len(rows) == 2
            for env_id, row in enumerate(rows):
                prefix = f'{stage}_env{env_id}'
                assert row['env_idx'] == env_id and row['descriptor'] == audit.STRIP_DESCRIPTOR
                if scheme is None:
                    original.append(read_pixels(row['native'], prefix))
                    assert row['native']['sha256'] == safe_sha(native[env_id])
                    continue
                assert row['bound_handle_stable'] and row['bound_handle_exclusive']
                source, bound, expected = (read_pixels(row[k], f'{prefix}_{k}') for k in ('source', 'bound', 'expected'))
                assert np.array_equal(source, original[env_id]) and np.array_equal(bound, expected)
                if scheme == 'original':
                    assert np.array_equal(bound, source)
                else:
                    color = parameters[scheme]['keyboard']['shell_strip']['base_color']
                    assert row['bound']['sha256'] == audit.strip_pixels_sha(color)
                if stage in fixed_materials:
                    assert row['bound']['sha256'] == safe_sha(fixed_materials[stage][env_id])
        assert set(archive.files) == seen
    return {'sha256': evidence['sha256'], 'stages': len(stages), 'arrays_recomputed': len(seen)}


def check_keycaps(directory, checks, task, schemes, images):
    evidence = checks['independent_keycaps']
    assert evidence['status'] == evidence['device_only_keycaps_native'] == 'passed'
    assert evidence['combined_preflight_atomicity'] == 'passed'
    assert evidence['editable_native_parts_per_env'] == (153 if task == 'OpenLaptop' else 77)
    camera = 'front_detail' if task == 'OpenLaptop' else 'human'
    assert evidence['camera'] == camera
    separator = audit.read(directory / 'keycaps_fixed_scheme_pairwise.json')
    assert separator['schemes'] == list(schemes) and separator['camera'] == camera
    assert separator['minimum_fraction_over_8'] == .001
    native = [audit.png(directory / f'keycaps_native_{camera}_env{i}.png') for i in (0, 1)]
    frames = {}
    for scheme in schemes:
        row = evidence['fixed'][scheme]
        assert row['status'] == 'passed'
        frames[scheme] = []
        for i in (0, 1):
            frame = directory / f'keycaps_{scheme}_{camera}_env{i}.png'
            rendered = audit.png(frame)
            frames[scheme].append(rendered)
            if i == 0:
                images[f'{task}/{frame.name}'] = frame
            count = int(np.count_nonzero(np.any(rendered != native[i], axis=-1)))
            assert row['detail_changed_pixels'][i] == count
            if scheme == 'original':
                assert count == 0
            else:
                assert count > 0 and row['exact_original_restoration']
                restored = audit.png(directory / f'keycaps_restored_from_{scheme}_{camera}_env{i}.png')
                assert np.array_equal(native[i], restored)
    for (left, arrays_left), (right, arrays_right) in combinations(frames.items(), 2):
        values = []
        for a, b in zip(arrays_left, arrays_right, strict=True):
            delta = np.abs(a.astype(np.int16) - b.astype(np.int16))
            pixels = int(np.count_nonzero(delta.max(axis=-1) > 8))
            assert pixels / delta[..., 0].size >= .001
            values.append({'pixels_over_8': pixels, 'fraction_over_8': pixels / delta[..., 0].size,
                           'mean_absolute_difference': float(delta.mean())})
        assert separator['pairs'][f'{left}/{right}'] == values
    selected = {}
    for item in checks['keycap_selected_reset_state']:
        assert item['evidence'] not in selected
        audit.selected_check(directory, item)
        selected[item['evidence']] = item['selected']
    for i, row in zip((1, 0), evidence['local_resets'], strict=True):
        assert row['selected'] == i and row['unselected'] == 1 - i
        assert selected[row['state_evidence']] == [i]
        assert row['keycap_schemes'][i] == 'original'
        assert len(set(row['device_schemes'])) == 1 and row['device_schemes'][i] != 'original'
        for view, pixels in row['unselected_pixel_changes'].items():
            before, after = audit.pair(directory / f'keycaps_reset_{i}_{view}_env{1-i}.png')
            assert pixels['changed_values'] == 0 and np.array_equal(before, after)
    return {'camera': camera, 'fixed_pairs': len(separator['pairs']), 'selected_state_checks': len(selected),
            'editable_native_parts_per_env': evidence['editable_native_parts_per_env'],
            'raw_slot_evidence_sha256': audit.track(directory / evidence['keycaps_only_slot_evidence']),
            'raw_geometry_sha256': audit.track(directory / 'keycaps_only_actual_geometry.pt')}


def check_task(root, task, capture_commit, sources, artifact, expected, required, images):
    capture = root / f'{task}_cuda'
    directory = capture / task
    schemes = runtime.SCHEMES[task]
    manifest = audit.read(capture / 'manifest.json')
    results = audit.read(capture / 'results.json')
    row, = results['tasks']
    checks = row['checks']
    assert manifest['git_commit'] == capture_commit and manifest['files'] == sources
    assert manifest['num_envs'] == 2 and manifest['sim_backend'] == 'physx_cuda'
    assert manifest['capture_path'] == 'original ManiSkill CUDA RGB cameras'
    assert manifest['schemes'] == {task: list(schemes)}
    assert row['task'] == task and row['status'] == results['status'] == results['formal_acceptance'] == 'passed'
    printed = capture.with_suffix('.stdout.log').read_text(encoding='utf-8').splitlines()[-1]
    assert json.loads(printed) == {'status': 'passed', 'tasks': [[task, 'passed', 'complete']]}
    assert (row['control_steps'], row['physics_steps']) == (2, 40)
    assert all(results[k] for k in ('source_hashes_unchanged', 'asset_hashes_unchanged',
                                    'robot_asset_hashes_unchanged', 'external_hashes_unchanged'))
    sdk = check_sdk(capture, sources, PROFILE['checker'], artifact, expected, required, gpu=True)
    assets = audit.asset_identity(FAMILY, manifest, row, ROOT)
    audit.external_identity(manifest['external_files'])
    audit.CAPTURE_FILES.clear()
    audit.CAPTURE_FILES.update(sources)
    audit.CAPTURE_FILES.update(manifest['external_files'])
    audit.CAPTURE_FILES.update(assets['raw_sha256'])
    native, physical = (audit.read(directory / f'native_{key}.json') for key in ('materials', 'physical'))
    with patch.object(audit, 'schemes_for', return_value=schemes):
        parameters, roles, counts = audit.catalog_parameters(ROOT, FAMILY, task)
    bindings = checks['material_roles']
    interface = audit.interface_check(directory, checks, native, physical, schemes, bindings,
                                      parameters, roles, counts, runtime.key_for(task))
    provenance = audit.office_material_evidence(directory, native, checks['original']['materials'],
                                                checks['material_partition_mapping'], ROOT, task)
    diagnostic = audit.native_capture_check(directory, checks)
    cameras = tuple(diagnostic['pixels']['0'])
    frames, fixed_materials = {}, {}
    for scheme in schemes:
        entry = checks[scheme]
        assert entry['status'] == 'passed'
        fixed_materials[scheme] = entry['materials']
        audit.material_check(native, entry['materials'], scheme, bindings, parameters, roles, counts)
        for i in (0, 1):
            assert [r for r in entry['records'] if r['env_idx'] == i][-1]['scheme_id'] == scheme
            for camera in cameras:
                frame = directory / f'{scheme}_{camera}_env{i}.png'
                frames[scheme, camera, i] = audit.png(frame)
                if camera == 'human' and i == 0:
                    images[f'{task}/{frame.name}'] = frame

    separation = audit.read(directory / 'fixed_scheme_pairwise.json')
    assert separation['schemes'] == list(schemes) and separation['camera'] == 'human'
    assert separation['minimum_fraction_over_8'] == .001
    pairs = {}
    for left, right in combinations(schemes, 2):
        rows = []
        for i in (0, 1):
            delta = np.abs(frames[left, 'human', i].astype(np.int16) - frames[right, 'human', i].astype(np.int16))
            pixels = int(np.count_nonzero(delta.max(axis=-1) > 8))
            fraction = pixels / delta[..., 0].size
            assert fraction >= .001
            rows.append({'pixels_over_8': pixels, 'fraction_over_8': fraction,
                         'mean_absolute_difference': float(delta.mean())})
        pairs[f'{left}/{right}'] = rows
    assert separation['pairs'] == pairs

    restored = checks['original_restoration_by_scheme']
    assert set(restored) == set(schemes[1:])
    first_repeat = checks['first_repeat_frames']
    expected_stages = {f'fixed_{s}_first_repeat' for s in schemes}
    expected_stages.update(f'restored_from_{s}_first_repeat' for s in schemes[1:])
    if task == 'TypeKeys':
        expected_stages.update(f'{context}local_{i}_first_repeat' for context in ('', 'native_') for i in (0, 1))
    assert set(first_repeat) == expected_stages
    for stage, rows in first_repeat.items():
        assert set(rows) == {'0', '1'}
        for i in (0, 1):
            assert set(rows[str(i)]) == set(cameras)
            audit.pixel_check(directory, rows[str(i)], stage, i, zero=True)
            for camera in cameras:
                first, _ = audit.pair(directory / f'{stage}_{camera}_env{i}.png')
                if stage.startswith('fixed_'):
                    scheme = stage.removeprefix('fixed_').removesuffix('_first_repeat')
                    assert np.array_equal(first, frames[scheme, camera, i])
                if stage.startswith('restored_from_'):
                    scheme = stage.removeprefix('restored_from_').removesuffix('_first_repeat')
                    assert restored[scheme]['status'] == 'passed'
                    assert not audit.metrics(first, frames['original', camera, i])['changed_values']
                    assert restored[scheme]['pixel_changes'][str(i)][camera]['changed_values'] == 0
                    archive = audit.inside(directory, restored[scheme]['pixel_changes'][str(i)][camera]['coordinates'])
                    with np.load(archive, allow_pickle=False) as data:
                        assert set(data.files) == {'coordinates_yxc', 'before', 'after'}
                        assert not any(data[k].size for k in data.files)
                    audit.track(archive)
                if stage.startswith(('local_', 'native_local_')):
                    _, after = audit.pair(directory / f'{stage.removesuffix("_first_repeat")}_{camera}_env{i}.png')
                    assert np.array_equal(first, after)

    baseline_images = ROOT / 'assets/appearance/objects/office_desk/previews/runtime' / task
    for scheme in schemes[:3]:
        previous = audit.png(baseline_images / f'{scheme}_human_env0.png')
        assert np.array_equal(frames[scheme, 'human', 0], previous) == (scheme == 'original')
    for camera in cameras:
        for i in (0, 1):
            raw, _ = audit.pair(directory / f'native_capture_{camera}_env{i}.png')
            assert np.array_equal(raw, frames['original', camera, i])
            assert all(any(not np.array_equal(frames[s, c, i], frames['original', c, i])
                           for c in cameras if c != 'human') for s in schemes[1:])

    selected, reads = {}, []
    for item in checks['selected_reset_state']:
        assert item['evidence'] not in selected
        checked, states = audit.selected_check(directory, item)
        selected[item['evidence']] = {'selected': item['selected'], 'states': states}
        reads.append(checked)
    assert len(selected) == 42 and all(selected[v['state_evidence']]['selected'] == [0, 1]
                                       for v in restored.values())
    native_local = checks['native_local_reset_control']['rounds']
    local = [checks[f'local_reset_{i}'] for i in (0, 1)]
    local_evidence = []
    for index, i in enumerate((1, 0)):
        for prefix, item, enabled in ((f'native_local_{index}', native_local[index], False),
                                      (f'local_{index}', local[index], True)):
            assert audit.read(directory / f'{prefix}.json') == item
            local_evidence.append(audit.local_check(directory, item, prefix, i, selected, native, appearance=enabled))
            if task == 'TypeKeys':
                marker = item['guidance_marker']
                assert marker['before'][1-i] == marker['after'][1-i]
                np.testing.assert_allclose(marker['after'][i], marker['selected_expected'], atol=2e-6, rtol=0)
            if enabled:
                for env in (0, 1):
                    p = directory / f'{prefix}_base_camera_env{env}.png'
                    images[f'{task}/{p.name}'] = p
    audit.steps_check(directory, checks['step_evidence'], local, native_local, FAMILY)
    counter = audit.office_counter_check(directory, checks['diagnostic_counter_scope'], task, selected, cameras)
    strip = (check_strip(directory, checks['strip_texture_evidence'], parameters, native, fixed_materials, schemes)
             if task == 'TypeKeys' else None)
    mouse = audit.mouse_collision_check(row, ROOT) if task == 'ClickMouse' else None
    keycaps = check_keycaps(directory, checks, task, schemes, images) if task != 'ClickMouse' else None
    identity = {**manifest, 'robot_asset_closure': row['asset_closure_sha256'],
                'mouse_collision_identity': row.get('mouse_collision_identity')}
    return {'manifest_sha256': audit.track(capture / 'manifest.json'), 'results_sha256': audit.track(capture / 'results.json'),
            'process': check_process(capture), 'sdk': sdk, 'asset_closure': assets, 'interface': interface,
            'logical_material_proof': provenance, 'fixed_camera_pairwise': separation,
            'original_restorations': list(restored), 'first_repeat_stages': len(first_repeat),
            'native_cameras': list(cameras), 'selected_state_checks': len(reads), 'control_steps': 2, 'physics_steps': 40,
            'bidirectional_resets': local_evidence, 'counter_scope': counter, 'keyboard_private_strip': strip,
            'mouse_collision': mouse, 'independent_keycaps': keycaps, 'legacy_original_rgb_equal': True}, identity


def check_cpu(batch, capture_commit, sources, manifests, artifact, expected, required):
    from tools.variation import check_office_devices_dynamics as D

    capture = batch / 'cpu_interface'
    interface = audit.read(capture / 'results.json')
    manifest = audit.read(capture / 'manifest.json')
    assert manifest['git_commit'] == capture_commit and manifest['files'] == sources
    assert interface['status'] == 'passed' and manifest['sim_backend'] == 'physx_cpu' and manifest['num_envs'] == 1
    assert all(interface[k] for k in ('source_hashes_unchanged', 'asset_hashes_unchanged',
                                      'robot_asset_hashes_unchanged', 'external_hashes_unchanged'))
    assert [row['task'] for row in interface['tasks']] == list(runtime.TASKS)
    for row in interface['tasks']:
        schemes = runtime.SCHEMES[row['task']]
        assert [key for key in row['checks']['original_restoration_by_scheme']] == list(schemes[1:])
        assert row['status'] == 'passed' and all(row['checks'][s]['status'] == 'passed' for s in schemes)
        gpu = manifests[row['task']]
        assert (manifest['asset_files'], manifest['external_files'], row['asset_closure_sha256']) == (
            gpu['asset_files'], gpu['external_files'], gpu['robot_asset_closure'])
    interface_sdk = check_sdk(capture, sources, PROFILE['checker'], artifact, expected, required, gpu=False)
    root = batch / 'cpu_dynamics'
    summary = audit.read(root / 'summary.json')
    assert summary['status'] == 'passed' and summary['source_sha256'] == sources
    assert summary['git_head'] == capture_commit and summary['completed_runs'] == 39
    assert summary['counts_complete'] and not summary['failures'] and not summary['unknown_runs']
    assert (summary['total_control_steps'], summary['total_physics_steps']) == (2340, 46800)
    runs = {}
    for task, gpu in manifests.items():
        expected_schemes = ('native_off', 'native_off', *runtime.SCHEMES[task])
        assert list(summary['tasks'][task]) == list(D.SCHEMES) and len(expected_schemes) == len(D.SCHEMES)
        reference = None
        actions = root / task / 'actions.npy'
        action_sha = audit.track(actions)
        action_array = np.load(actions, allow_pickle=False)
        assert action_array.shape[0] == 60 and action_array.dtype == np.float32
        assert np.isfinite(action_array).all() and np.any(action_array != 0)
        motion = 0.0
        for alias, scheme in zip(D.SCHEMES, expected_schemes, strict=True):
            directory = root / task / alias
            run = audit.read(directory / 'run.json')
            assert run['status'] == 'completed' and run['source_sha256'] == sources and run['seed'] == 7
            assert run['actual_scheme_id'] == scheme and run['actions']['sha256'] == action_sha and run['actions']['legal']
            assert run['actions']['shape'] == list(action_array.shape)
            assert run['asset_files'] == gpu['asset_files'] and run['external_files'] == gpu['external_files']
            assert run['asset_closure_sha256'] == gpu['robot_asset_closure']
            assert run['asset_hashes_unchanged'] and run['external_hashes_unchanged'] and not run['image_capture']
            assert run['constructor_kwargs']['sim_backend'] == 'physx_cpu' and run['constructor_kwargs']['num_envs'] == 1
            assert (run['control_steps'], run['physics_steps']) == (60, 1200)
            if task == 'ClickMouse':
                assert run['mouse_collision_inputs_unchanged']
                assert run['mouse_collision_identity'] == gpu['mouse_collision_identity']
            sdk = check_sdk(directory, sources, PROFILE['dynamics'], artifact, expected, required, gpu=False)
            states = audit.load(directory / 'trajectory.pt')
            assert len(states) == 61
            if reference is None:
                reference = states
            for step, (before, after) in enumerate(zip(reference, states, strict=True)):
                audit.exact(before, after, f'{task}/{alias}/{step}')
                audit.cpu_coverage(after, step, FAMILY)
                if alias == 'native_off' and step:
                    for key, value in after.items():
                        if key.endswith('/qpos') and value.numel():
                            displacement = (value.double() - reference[0][key].double()).abs().max()
                            motion = max(motion, float(displacement))
            runs[f'{task}/{alias}'] = {'actual_scheme_id': scheme, 'samples': len(states),
                                      'run_sha256': audit.track(directory / 'run.json'),
                                      'trajectory_sha256': audit.track(directory / 'trajectory.pt'), 'sdk': sdk['receipt_sha256']}
        assert motion > 0, f'{task} did not move during the CPU trajectory'
    return {'interface': {'process': check_process(capture), 'sdk': interface_sdk,
                           'results_sha256': audit.track(capture / 'results.json'), 'manifest_sha256': audit.track(capture / 'manifest.json')},
            'dynamics': {'process': check_process(root), 'summary_sha256': audit.track(root / 'summary.json'),
                         'runs': runs, 'control_steps': 2340, 'physics_steps': 46800}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--capture-commit',
                        help='Commit recorded by all CPU and CUDA captures (defaults to the current HEAD)')
    args = parser.parse_args()
    assert not args.output.exists()
    revision = args.capture_commit or 'HEAD'
    capture_commit = subprocess.check_output(
        ['git', 'rev-parse', '--verify', '--end-of-options', f'{revision}^{{commit}}'], cwd=ROOT, text=True).strip()
    capture_tree = subprocess.check_output(
        ['git', 'rev-parse', f'{capture_commit}^{{tree}}'], cwd=ROOT, text=True).strip()
    catalog_check()
    audit.configure(ROOT)
    sources = runtime.source_hashes()
    if args.capture_commit:
        changed = subprocess.check_output(
            ['git', 'diff', '--name-only', capture_commit, '--', *sources], cwd=ROOT, text=True).splitlines()
        assert not changed, f'Runtime source differs from the capture commit: {changed}'
    _, expected, required, sdk = audit.sdk_build_identity(FAMILY, ROOT, args.artifact,
                                                          ROOT / 'tools/variation/sapien_sdk/lock.json')
    tasks, captures, images = {}, {}, {}
    for task in runtime.TASKS:
        tasks[task], captures[task] = check_task(args.batch, task, capture_commit, sources, args.artifact, expected, required, images)
    cpu = check_cpu(args.batch, capture_commit, sources, captures, args.artifact, expected, required)
    expected_images = 45 + len(runtime.DEVICE_SCHEMES) * 2
    assert len(images) == expected_images and set(REVIEW_IMAGES) <= images.keys()
    args.output.mkdir(parents=True)
    for name, path in images.items():
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        assert audit.track(path) == audit.H.sha(target)
    assert sources == runtime.source_hashes()
    audit.H.write(args.output / 'summary.json', {'format': 'office-realistic-evidence-v1', 'status': 'passed',
        'baseline': capture_commit, 'capture_tree': capture_tree, 'source_identity': audit.source_identity(sources, ROOT), 'sdk': sdk,
        'tasks': tasks, 'cpu': cpu, 'images': {name: audit.track(path) for name, path in images.items()},
        'review_images': list(REVIEW_IMAGES),
        'exporter_sha256': audit.track(Path(__file__)),
        'scope': 'Windows native short tasks, fixed RGB, precise recovery, CPU dynamics and two CUDA environments'})
    print(args.output / 'summary.json')


if __name__ == '__main__':
    main()
