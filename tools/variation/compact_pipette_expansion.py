"""Recheck and archive the Pipette expansion from the recorded PT, PNG and SDK inputs."""
import argparse
from collections import Counter
from contextlib import contextmanager
import copy
from itertools import combinations
from pathlib import Path
import re
import shutil

import numpy as np
from PIL import Image

import check_pipette_runtime as runtime
import compact_task_runtime as raw
import compact_pipette_rendering as depth
from check_pipette_runtime import ROOT, SCHEMES, TASKS, dump, sha
from pipette_preview_materials import input_file_sha256

FAMILY = 'pipette_transfer'
PROFILE = raw.PROFILES[FAMILY]
GPU_RUNS = ('gpu_aspirate', 'gpu_dispense')
PROBE_RUNS = ('probe_aspirate', 'probe_dispense')
CAMERAS = ('base_camera', 'wrist_camera', 'human')
MONITOR = ROOT / 'tools/variation/monitor_pipette_expansion.py'
ARCHIVE = ROOT / 'assets/appearance/objects/pipette_transfer/previews/runtime'
require = raw.require


def sdk_receipt(capture, checker, source, build, *, gpu):
    sdk, expected, required, _ = build
    path = capture / 'private_sdk.json'
    row = raw.read(path)
    require(row['binaries_unchanged'] and row['version'] == sdk['version']
            and row['artifact_sha256'] == sdk['artifact_sha256'], 'Private SDK receipt differs')
    raw.launcher_check(row, ROOT, 'tools/variation/' + checker, source, raw.LAUNCHER, sdk)
    native, binding = raw.sdk_check(row['before'], row['after'], expected, required, gpu=gpu)
    return dict(native=native, python=raw.sdk_python_check(row, binding),
                vulkan=raw.vulkan_loader_check(row)), binding


def console_receipt(directory, capture, limit):
    path = directory / 'process.json'
    row = raw.read(path)
    require(row['returncode'] == 0 and row['timed_out'] is False, 'Checker process failed')
    require((ROOT / raw.flag(row['command'], '--output')).resolve() == capture, 'Wrong checker output')
    streams = {name: raw.track(directory / name) for name in ('stdout.txt', 'stderr.txt')}
    require(row['streams_sha256'] == streams, 'Checker streams changed')
    require(raw.read(directory / 'resource.json')['launcher_sha256'] == raw.track(MONITOR),
            'Capture monitor differs')
    return dict(process_sha256=raw.track(path), streams_sha256=streams, returncode=0,
                command=raw.portable_command(row['command'], ROOT),
                resources=raw.resource_check(directory, row['command'], limit))


def capture_receipt(capture, checker, build, *, gpu):
    manifest = raw.read(capture / 'manifest.json')
    result = raw.read(capture / 'results.json')
    require(result['status'] == 'passed' and all(result[key] is True for key in
            ('source_hashes_unchanged', 'external_hashes_unchanged', 'asset_hashes_unchanged')),
            'Capture source, external or asset closure failed')
    require(manifest['sim_backend'] == ('physx_cuda' if gpu else 'physx_cpu')
            and manifest['num_envs'] == (2 if gpu else 1)
            and re.fullmatch(r'[0-9a-f]{40}', manifest['git_commit'])
            and manifest['schemes'] == list(SCHEMES),
            'Capture scope or baseline differs')
    require(not gpu or (result['formal_acceptance'] == 'passed'
            and manifest['test_mode'] == 'standard' and manifest['capture_path'] == PROFILE['capture']),
            'GPU capture is not standard CUDA')
    sdk, binding = sdk_receipt(capture, checker, manifest['files'], build, gpu=gpu)
    identity = dict(git_commit=manifest['git_commit'], source=raw.source_identity(manifest['files'], ROOT),
                    external=raw.external_identity(manifest['external_files']), sdk=sdk)
    return manifest, result, identity, binding


def use_material_inputs(manifest, assets):
    raw.CAPTURE_FILES.clear()
    for inputs in (manifest['files'], manifest['external_files'], assets):
        raw.CAPTURE_FILES.update(inputs)


def validate_plate_texture(native, actual, scheme, bindings):
    definition = raw.read(ROOT / 'assets/appearance/objects/pipette_transfer/pipette_stand/bindings.json')
    label = definition['roles']['base_plate']['candidate_color_texture']
    # Verify the complete native texture descriptor as well as the declared file.
    raw.material_rows(actual)
    normal = copy.deepcopy(actual)
    changes = []
    plates = set()
    for key, role in bindings.items():
        if (role['object_id'], role['role']) != ('pipette_stand', 'base_plate'):
            continue
        env, slot = map(int, key.split('/')[1:3])
        plates.add(env)
        baseline = native[env][slot]['material']['base_color_texture']
        measured = actual[env][slot]['material']['base_color_texture']
        current = scheme[env] if isinstance(scheme, list) else scheme
        require(baseline is None, 'Native stand already has a base-plate texture')
        if current == 'original':
            require(measured is None, 'Stand texture was retained after native restore')
        else:
            asset = Path(label['directory']) / f'{current}.png'
            path = ROOT / asset
            with Image.open(path) as image:
                require(image.mode == 'RGB', 'Stand label must be opaque RGB')
                width, height = image.size
            expected = {'asset_ref': asset.as_posix(), 'sha256': raw.track(path), 'name': path.name,
                        'width': width, 'height': height, 'mipmap_levels': label['mipmap_levels'],
                        'is_srgb': True}
            require(measured is not None and all(measured.get(k) == v for k, v in expected.items()),
                    'Stand label does not match the captured catalog asset')
            normal[env][slot]['material']['base_color_texture'] = baseline
            changes.append(key + '/base_color_texture')
    require(plates == set(range(len(actual))), 'Stand base plate binding coverage differs')
    return normal, changes


@contextmanager
def pipette_material_check():
    original = raw.material_check

    def check(native, actual, scheme, bindings, parameters, roles, counts):
        normalized, changes = validate_plate_texture(native, actual, scheme, bindings)
        result = original(native, normalized, scheme, bindings, parameters, roles, counts)
        result['canonical_sha256'] = raw.H.canonical_sha(actual)
        result['changed_fields'].extend(changes)
        return result

    raw.material_check = check
    try:
        yield
    finally:
        raw.material_check = original


def gpu_task(capture, console, name, build, images):
    with pipette_material_check():
        return checked_gpu_task(capture, console, name, build, images)


def checked_gpu_task(capture, console, name, build, images):
    manifest, result, identity, binding = capture_receipt(capture, PROFILE['checker'], build, gpu=True)
    require(len(result['tasks']) == 1 and result['tasks'][0]['task'] == name, 'GPU task scope differs')
    row, directory = result['tasks'][0], capture / name
    checks = row['checks']
    require(row['status'] == 'passed' and not row['native_buffer_errors'] and not row.get('error'),
            'Failed task or native buffer diagnostic')
    require(raw.track(directory / 'native.log') == row['native_log_sha256'], 'Native log changed')
    require(manifest['resolved_sim_config'][name] == row['resolved_sim_config']
            and manifest['gpu_memory_profile'] == row['gpu_memory_profile'] == 'two_env',
            'Resolved simulator profile differs')
    assets = raw.asset_identity(FAMILY, manifest, row, ROOT)
    use_material_inputs(manifest, assets['raw_sha256'])
    shader = raw.shaders_check(row['rendering'], binding, ROOT, name, 2)
    native, physical = [raw.read(directory / n) for n in ('native_materials.json', 'native_physical.json')]
    parameters, roles, counts = raw.catalog_parameters(ROOT, FAMILY, name)
    bindings = checks['material_roles']
    args = (bindings, parameters, roles, counts)
    original = raw.native_capture_check(directory, checks)
    interface = raw.interface_check(directory, checks, native, physical, SCHEMES, *args,
                                    raw.option_for(PROFILE, name))
    selected, states = [], {}
    for entry in checks['selected_reset_state']:
        key = entry['evidence']
        require(key not in states, 'Duplicate selected-state receipt')
        receipt, tensors = raw.selected_check(directory, entry)
        states[key] = {'selected': entry['selected'], 'states': tensors}
        selected.append(receipt)
    expanded = SCHEMES[3:]
    require(len(states) == 23 + len(expanded) + len(SCHEMES[1:]) + 3 * len(expanded),
            'Unexpected selected-state coverage')
    robot_names = sorted({k.rsplit('/', 1)[-1] + '.urdf' for record in states.values()
                          for k in record['states']['expected'] if '/state/articulations/panda_' in k})
    robot = raw.robot_closure(assets['raw_sha256'], ROOT, robot_names)
    fixed, restored, frames, retained_images = {}, {}, {}, {}
    restorations = checks['candidate_restorations']
    require(set(restorations) == set(SCHEMES[1:]), 'Missing candidate restoration')
    for scheme in SCHEMES:
        entry = checks[scheme]
        require(entry['status'] == 'passed', 'Fixed scheme failed')
        fixed[scheme] = raw.material_check(native, entry['materials'], scheme, *args)
        require(all([r for r in entry['records'] if r['env_idx'] == i][-1]['scheme_id'] == scheme for i in (0, 1)),
                'Fixed record scheme differs')
        fixed[scheme]['records'] = entry['records']
        rgb_sha = fixed[scheme]['rgb_sha256'] = {}
        for i in (0, 1):
            task_pixels = []
            for camera in CAMERAS:
                key = f'{camera}_env{i}'
                path = directory / f'{scheme}_{key}.png'
                frame = frames[scheme, key] = raw.png(path)
                rgb_sha[key] = raw.track(path)
                if scheme == 'original':
                    off, _ = raw.pair(directory / f'native_capture_{key}.png')
                    require(np.array_equal(off, frame), 'Native off and original RGB differ')
                elif camera != 'human':
                    task_pixels.append(np.any(frame != frames['original', key]))
                if i == 0 and camera == 'human':
                    images[f'{name}/{scheme}_human_env0.png'] = path
                    if scheme == 'original':
                        previous = ARCHIVE / name / f'{scheme}_human_env0.png'
                        require(np.array_equal(frame, raw.png(previous)), 'Native appearance differs from PR #14')
                        retained_images[scheme] = raw.track(previous)
            require(scheme == 'original' or any(task_pixels), 'No native task camera RGB change')
        if scheme == 'original':
            continue
        restore = restorations[scheme]
        raw.material_check(native, restore['materials'], 'original', *args)
        raw.record_check(entry['records'], restore['records'], [0, 1], ['original', 'original'])
        require(states[restore['selected_state_evidence']]['selected'] == [0, 1], 'Restoration readback missing')
        restored[scheme] = {}
        for i in (0, 1):
            restored[scheme][i] = {}
            for camera in CAMERAS:
                key = f'{camera}_env{i}'
                candidate, after = raw.pair(directory / f'restored_{scheme}_{key}.png')
                require(np.array_equal(candidate, frames[scheme, key])
                        and np.array_equal(after, frames['original', key]), 'Fixed candidate restoration differs')
                require(restore['pixel_changes'][str(i)][camera]['changed_values'] == 0,
                        'Reported native-to-restored RGB drift')
                pixel = restore['pixel_changes'][str(i)][camera]
                coords = raw.inside(directory, pixel['coordinates'])
                raw.track(coords)
                with np.load(coords, allow_pickle=False) as diff:
                    require(all(not diff[key].size for key in ('coordinates_yxc', 'before', 'after')),
                            'Native-to-restored difference evidence is not empty')
                restored[scheme][i][camera] = dict(max_rgb_difference=0,
                    pair_sha256=raw.track(directory / f'restored_{scheme}_{key}.png'))
    segment_path = directory / 'witness_segmentation.npz'
    raw.track(segment_path)
    ids = raw.read(directory / 'witness_render_ids.json')
    require(all(set(values) == set(roles) for values in ids), 'Witness does not cover each bound object')
    with np.load(segment_path, allow_pickle=False) as segments:
        require(set(segments.files) == {f'{camera}_env{i}' for camera in CAMERAS for i in (0, 1)},
                'Witness cameras differ')
        # The capture entry normally binds NumPy in load_runtime alongside the
        # simulator. Only the array module is needed for the raw-image replay.
        runtime.np = np
        witness = runtime.appearance_witness(directory, SCHEMES, ids, segments)
    require(witness == raw.read(directory / 'witness_pairs.json') and len(witness) == 2 * len(roles) *
            len(list(combinations(SCHEMES, 2))) and all(w['passed'] for w in witness),
            'Object-region RGB witness failed')
    native_rows = checks['native_local_reset_control']['rounds']
    local_native = [raw.local_check(directory, subrow, f'native_local_{i}', i, states, native, appearance=False)
                    for i, subrow in zip((1, 0), native_rows, strict=True)]
    steps = {step['evidence']: step for step in checks['step_evidence']}
    native_step = steps.pop('native_local_0_step.pt')
    def local_pair(pair_rows, prefixes, schemes):
        compact = []
        for j, (i, subrow, prefix) in enumerate(zip((1, 0), pair_rows, prefixes, strict=True)):
            require(raw.read(directory / (prefix + '.json')) == subrow, 'Raw local reset report differs')
            expected_before = schemes if j == 0 else [schemes[0], 'original']
            expected_after = [schemes[0], 'original'] if j == 0 else ['original', 'original']
            raw.material_check(native, subrow['before_materials'], expected_before, *args)
            raw.material_check(native, subrow['after_materials'], expected_after, *args)
            require(subrow['precondition_control_steps'] == j, 'Missing pre/post-step case')
            compact.append(raw.local_check(directory, subrow, prefix, i, states, native, appearance=True))
        gpu_steps = raw.steps_check(directory, [native_step, steps.pop(prefixes[1] + '_step.pt')],
                                    pair_rows, native_rows, FAMILY)
        return dict(initial_schemes=schemes, rounds=compact, appearance_step=gpu_steps[1])
    original_pair = local_pair([checks['local_reset_1'], checks['local_reset_0']],
                               ['local_reset_1', 'local_reset_0'], list(SCHEMES[1:3]))
    require(set(checks['expansion_local_pairs']) == set(expanded), 'Missing expanded local pair')
    expanded_pairs = {}
    for j, scheme in enumerate(expanded):
        entry = checks['expansion_local_pairs'][scheme]
        initial = [scheme, expanded[(j + 1) % len(expanded)]]
        prefixes = [f'local_{initial[0]}_{initial[1]}_{i}' for i in (1, 0)]
        require(entry['initial_schemes'] == initial and [r['prefix'] for r in entry['rounds']] == prefixes,
                'Expanded local pairing differs')
        expanded_pairs[scheme] = local_pair([{k: v for k, v in row.items() if k != 'prefix'}
                                              for row in entry['rounds']], prefixes, initial)
    controls = 2 + len(expanded)
    require(not steps and result['control_steps'] == row['control_steps'] == controls
            and result['physics_steps'] == row['physics_steps'] == 20 * controls, 'Step coverage differs')
    if name == TASKS[0]:
        first, second = expanded[:2]
        for i in (0, 1):
            filename = f'local_{first}_{second}_1_base_camera_env{i}.png'
            images[f'{name}/{filename}'] = directory / filename
    return dict(control_steps=controls, physics_steps=20*controls, fixed=fixed, restored=restored,
                interface=interface, selected_state=selected, witness=witness, assets=assets,
                retained_pr14_human_rgb_sha256=retained_images,
                robot=robot, shader=shader, native_capture=original, native_local_reset=local_native,
                retained_local_reset=original_pair, expansion_local_pairs=expanded_pairs,
                native_step_sha256=raw.track(directory / native_step['evidence']),
                resolved_sim_config=row['resolved_sim_config'], asset_closure_sha256=row['asset_closure_sha256'],
                capture={n: raw.track(capture / n) for n in ('results.json', 'manifest.json', 'private_sdk.json')},
                console=raw.console_check(console, capture, result, None, ROOT, PROFILE)), identity


def cpu_dynamics(directory, console, gpu, identity, build):
    report = raw.read(directory / 'summary.json')
    aliases = ('native_off', 'native_repeat', *SCHEMES)
    controls = len(TASKS) * len(aliases) * 60
    source = report['source_sha256']
    require(report['status'] == 'passed' and not report['failures']
            and report['completed_runs'] == len(TASKS) * len(aliases)
            and report['total_control_steps'] == controls and report['total_physics_steps'] == controls * 20
            and report['control_steps_per_run'] == 60 and report['seed'] == 7 and report['counts_complete']
            and report['source_hashes_unchanged'] and report['external_hashes_unchanged']
            and source == identity['source']['raw_sha256'], 'CPU dynamic count or source differs')
    require(raw.external_identity(report['external_sha256']) == identity['external'], 'CPU external inputs differ')
    tasks = {}
    for task in TASKS:
        folder = directory / task
        require(set(report['tasks'][task]) == set(aliases), 'CPU dynamic scheme coverage differs')
        actions_path = folder / 'actions.npy'
        actions = np.load(actions_path, allow_pickle=False)
        require(actions.shape[0] == 60 and actions.dtype == np.float32
                and np.isfinite(actions).all() and np.any(actions != 0), 'Actions are invalid or trivial')
        action_sha = raw.track(actions_path)
        samples, runs, motion = None, {}, 0.
        for scheme in aliases:
            branch = folder / scheme
            run = raw.read(branch / 'run.json')
            parent = report['tasks'][task][scheme]
            require(run['task'] == task and run['scheme'] == scheme and run['seed'] == 7
                    and run['status'] == 'completed' and parent['returncode'] == 0
                    and parent['run_sha256'] == raw.track(branch / 'run.json')
                    and run['control_steps'] == run['requested_control_steps'] == 60
                    and run['sim_steps_per_control'] == 20 and run['physics_steps'] == 1200
                    and run['source_sha256'] == source and run['external_sha256'] == report['external_sha256']
                    and run['source_hashes_unchanged'] and run['external_hashes_unchanged']
                    and run['asset_hashes_unchanged'] and run['asset_closure_sha256'] == gpu[task]['asset_closure_sha256']
                    and run['materials_stable'] and not run['image_capture']
                    and run['pipette_rendering'] == {'enabled': True} and 'physx_cpu' in run['backend']
                    and run['actions']['legal'] and run['actions']['sha256'] == action_sha
                    and run['actions']['shape'] == list(actions.shape), 'CPU worker receipt differs')
            enabled = not scheme.startswith('native_')
            expected_config = {'enabled': True, 'scheme_id': scheme, 'seed': 71} if enabled else {'enabled': False}
            require(run['appearance_config'] == expected_config, 'CPU worker configuration differs')
            sdk, binding = sdk_receipt(branch, PROFILE['dynamics'], source, build, gpu=False)
            require(sdk == identity['sdk'] and run['sapien_binary']['sha256'] == build[1][binding.name],
                    'CPU worker SDK differs')
            shader = raw.shaders_check(run['rendering'], binding, ROOT, task, 1)
            require(raw.shared_shader_identity(shader) == raw.shared_shader_identity(gpu[task]['shader']),
                    'CPU worker shared shader configuration differs')
            trajectory_path = branch / 'trajectory.pt'
            trajectory = raw.load(trajectory_path)
            require(len(trajectory) == 61, 'CPU trajectory length differs')
            if samples is None:
                samples = trajectory
            for i, (a, b) in enumerate(zip(samples, trajectory, strict=True)):
                raw.exact(a, b, f'{task}/{scheme}/frame{i}')
                raw.cpu_coverage(b, i, FAMILY)
                if i:
                    for key, value in b.items():
                        if key.endswith('/qpos') and value.numel():
                            motion = max(motion, float((value.double() - samples[0][key].double()).abs().max()))
            runs[scheme] = dict(run_sha256=raw.track(branch / 'run.json'), frames=61,
                                trajectory_sha256=raw.track(trajectory_path), max_abs_error=0,
                                private_sdk_sha256=raw.track(branch / 'private_sdk.json'))
            if scheme != 'native_off':
                comparison = raw.read(branch / 'comparison.json')
                require(comparison['status'] == 'passed' and comparison['samples'] == 61
                        and comparison['initial_state_equal'] and not comparison['failed_steps']
                        and comparison['worst_difference']['max_absolute_error'] == 0,
                        'CPU original comparison receipt differs')
        require(motion > 0, 'CPU dynamics exercised no joint motion')
        tasks[task] = dict(actions_sha256=action_sha, max_joint_motion_rad=motion, runs=runs)
    return dict(control_steps=controls, physics_steps=controls*20, tasks=tasks,
                console=raw.cpu_console_check(console, directory, ROOT, PROFILE))


def cpu_interface(directory, console, identity, build):
    manifest, result, source, _ = capture_receipt(directory, PROFILE['checker'], build, gpu=False)
    require(source == identity and result['control_steps'] == result['physics_steps'] == 0,
            'CPU interface closure or step scope differs')
    require([task['task'] for task in result['tasks']] == list(TASKS), 'CPU interface task coverage differs')
    tasks = {}
    for task in result['tasks']:
        name, checks = task['task'], task['checks']
        root = directory / name
        assets = raw.asset_identity(FAMILY, manifest, task, ROOT)
        use_material_inputs(manifest, assets['raw_sha256'])
        require(task['status'] == 'passed' and not task['native_buffer_errors']
                and raw.track(root / 'native.log') == task['native_log_sha256'], 'CPU interface task failed')
        native = raw.read(root / 'native_materials.json')
        parameters, _, counts = raw.catalog_parameters(ROOT, FAMILY, name)
        bindings = checks['material_roles']
        require(Counter((r['object_id'], r['role']) for r in bindings.values()) == counts,
                'CPU material role coverage differs')
        fixed = {}
        for scheme in SCHEMES:
            row = checks[scheme]
            require(row['status'] == 'passed' and row['records'][-1]['scheme_id'] == scheme,
                    'CPU interface fixed scheme failed')
            actual = row['materials']
            require(len(native) == len(actual) == 1, 'Expected one CPU interface environment')
            normalized, _ = validate_plate_texture(native, actual, scheme, bindings)
            original_slots, measured = map(raw.material_rows, (native, normalized))
            require(original_slots.keys() == measured.keys() and set(bindings) <= original_slots.keys(),
                    'CPU material slots differ')
            for slot, original in original_slots.items():
                expected = copy.deepcopy(original)
                if slot in bindings:
                    binding = bindings[slot]
                    params = parameters[scheme][binding['object_id']].get(binding['role'], {})
                    for field, value in params.items():
                        if field == 'base_color_rgb':
                            expected['base_color'][:3] = value
                        elif field == 'base_color_alpha':
                            expected['base_color'][3] = value
                        else:
                            expected[field] = value
                require(measured[slot].keys() == expected.keys(), 'CPU PBR fields differ')
                for field, value in expected.items():
                    observed = measured[slot][field]
                    require(observed == value if value == original[field] else
                            np.allclose(observed, value, rtol=0, atol=1e-7), 'CPU PBR value differs')
            fixed[scheme] = {'materials_sha256': raw.H.canonical_sha(actual), 'records': row['records']}
        require(checks['default_disabled'] == checks['explicit_disabled'] == 'passed'
                and checks['random_reproducibility']['status'] == checks['selection_precedence']['status'] == 'passed'
                and checks['invalid_last_environment_atomicity'] == 'passed', 'CPU interface contract failed')
        first, second = [raw.read(root / f'random_trace_{i}.json') for i in (1, 2)]
        require(first == second, 'CPU random trace differs')
        tasks[name] = dict(fixed=fixed, random_trace_sha256=raw.track(root / 'random_trace_1.json'),
                           retained_checks={key: checks[key] for key in
                               ('default_disabled', 'explicit_disabled', 'selection_precedence',
                                'invalid_last_environment_atomicity')})
    return dict(tasks=tasks, results_sha256=raw.track(directory / 'results.json'),
                console=console_receipt(console, directory, 1024))


def model_check(capture, console, name, build):
    manifest = raw.read(capture / 'manifest.json')
    require(manifest['status'] == 'model_preview_checks_passed'
            and manifest['input_file_sha256'] == input_file_sha256()
            and len(manifest['objects']) == 1, 'Model capture failed or its source differs')
    source = raw.source_identity(manifest['input_file_sha256'], ROOT)
    sdk, _ = sdk_receipt(capture, 'render_pipette_preview.py', manifest['input_file_sha256'], build, gpu=False)
    row, frames = manifest['objects'][0], {}
    require(row['object_id'] == name and row['restored_rgb_max_abs_difference'] == 0, 'Model original failed')
    for scheme in (*SCHEMES, 'original_restored'):
        frames[scheme] = raw.png(capture / f'{name}_{scheme}.png')
    require(np.array_equal(frames['original'], frames['original_restored']), 'Model native restoration differs')
    require(all(np.any(frames[a] != frames[b]) for a, b in combinations(SCHEMES, 2)),
            'Model contains duplicate RGB outputs')
    if name in ('sample_cup', 'test_tube'):
        optical = row['optical_probe']
        x0, y0, x1, y1 = optical['measurement_roi_xyxy']
        reference = raw.png(capture / f'{name}_optical_board_reference.png')
        target = reference[y0:y1, x0:x1].mean(axis=2).astype(float)
        require([record['scheme_id'] for record in optical['schemes']] == list(SCHEMES),
                'Optical scheme coverage differs')
        for record in optical['schemes']:
            scheme = record['scheme_id']
            rgb = raw.png(capture / f'{name}_optical_{scheme}.png')
            gray = rgb[y0:y1, x0:x1].mean(axis=2).astype(float)
            ratio = float(gray.std()/target.std())
            corr = float(np.corrcoef(gray.ravel(), target.ravel())[0, 1])
            require(ratio == record['contrast_ratio'] and corr == record['stripe_correlation']
                    and (scheme == 'original' or (ratio >= .25 and corr >= .95)), 'Glass stripe readability failed')
    return dict(metrics=row, source=source, sdk=sdk, console=console_receipt(console, capture, 1792),
                manifest_sha256=raw.track(capture / 'manifest.json'),
                png_sha256={path.name: raw.track(path) for path in sorted(capture.glob('*.png'))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', type=Path, required=True)
    parser.add_argument('--consoles', type=Path, required=True)
    parser.add_argument('--sdk-artifact', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-baseline', help='Optional exact capture commit to check')
    args = parser.parse_args()
    raw.configure(ROOT)
    captures, consoles = args.captures.resolve(strict=True), args.consoles.resolve(strict=True)
    artifact = args.sdk_artifact.resolve(strict=True)
    args.output = args.output.resolve()
    require(not args.output.exists(), 'Choose a fresh archive directory')
    lock = ROOT / 'tools/variation/sapien_sdk/lock.json'
    build = raw.sdk_build_identity(FAMILY, ROOT, artifact, lock)
    images, gpu, identity = {}, {}, None
    for run, task in zip(GPU_RUNS, TASKS, strict=True):
        gpu[task], current = gpu_task(captures / run, consoles / run, task, build, images)
        require(identity is None or current == identity, 'GPU task source, SDK or external closure differs')
        identity = current
    require(len(images) == len(TASKS) * len(SCHEMES) + 2, 'Expected all fixed task PNGs and both local examples')
    require(args.expected_baseline is None or args.expected_baseline == identity['git_commit'],
            'Capture did not use the expected commit')
    cpu = cpu_dynamics(captures / 'cpu_dynamics', consoles / 'cpu_dynamics', gpu, identity, build)
    interface = cpu_interface(captures / 'cpu_interface', consoles / 'cpu_interface', identity, build)
    models = {}
    for name in ('pipette', 'sample_cup', 'test_tube', 'tube_rack', 'pipette_stand', 'tip_cup'):
        folder = f'model_{name}'
        models[name] = model_check(captures / folder, consoles / folder, name, build)
    probes = {}
    identity_source = identity['source']['raw_sha256']
    for run, task in zip(PROBE_RUNS, TASKS, strict=True):
        capture, console = captures / run, consoles / run
        probe = depth.task_check(capture, console / 'resource.json', artifact)
        require(probe['task'] == task and all(probe['source'][name] == digest for name, digest in identity_source.items())
                and raw.external_identity(probe['external_files']) == identity['external']
                and raw.shared_shader_identity(probe['rendering']) == raw.shared_shader_identity(gpu[task]['shader']),
                'Task depth probe scope or production identity differs')
        source = raw.read(capture / 'manifest.json')['files']
        sdk, _ = sdk_receipt(capture, 'check_pipette_rendering.py', source, build, gpu=True)
        require(sdk == identity['sdk'], 'Task depth probe SDK differs')
        probe['console'] = console_receipt(console, capture, 1792)
        probes[task] = probe
    args.output.mkdir(parents=True)
    for name, image in images.items():
        new = args.output / name
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, new)
        require(sha(new) == raw.track(image), 'Copied RGB proof changed')
    for task, result in gpu.items():
        dump(args.output / task / 'checks.json', result)
    dump(args.output / 'cpu_checks.json', {'dynamics': cpu, 'interface': interface})
    dump(args.output / 'optical_checks.json', {'isolated_models': models, 'task_depth': probes})
    frames = {}
    for run, task in zip(GPU_RUNS, TASKS, strict=True):
        frames[task] = {}
        for scheme, row in gpu[task]['fixed'].items():
            frames[task][scheme] = {}
            for camera, digest in row['rgb_sha256'].items():
                name = f'{task}/{scheme}_{camera}.png'
                frames[task][scheme][camera] = {
                    'raw_path': f'{run}/{name}', 'sha256': digest,
                    **({'archive_path': name} if name in images else {})}
    dump(args.output / 'fixed_frames.json', {'path_base': 'original capture directory', 'tasks': frames})
    for path, digest in raw.WATCHED.items():
        require(sha(path) == digest, 'Input changed before export completed')
    dump(args.output / 'summary.json', dict(status='passed', baseline=identity['git_commit'], schemes=list(SCHEMES),
        gpu={task: dict(control_steps=row['control_steps'], physics_steps=row['physics_steps'],
                        selected_state_checks=len(row['selected_state']), witness_pairs=len(row['witness']),
                        minimum_witness_pixels=min(max(v['pixels_delta_ge_8'] for v in w['views'])
                                                   for w in row['witness']),
                        candidate_restorations=len(row['restored'])) for task, row in gpu.items()},
        cpu_control_steps=cpu['control_steps'], cpu_physics_steps=cpu['physics_steps'],
        optical_camera_pairs=sum(probe['camera_environment_view_pairs'] for probe in probes.values()),
        identity=identity, sdk_build=build[3], exporter_sha256=sha(Path(__file__)),
        verifier_sha256=sha(Path(raw.__file__)), depth_verifier_sha256=sha(Path(depth.__file__)),
        capture_monitor_sha256=sha(MONITOR),
        images={name: sha(args.output / name) for name in images}))
    print(f'Pipette expansion raw recomputation passed; {len(images)} unchanged PNGs archived.')


if __name__ == '__main__':
    main()
