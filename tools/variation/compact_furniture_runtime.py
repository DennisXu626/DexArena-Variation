"""Export compact evidence only from complete standard CUDA RGB acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

TASKS = ('LayFlatPanel', 'InsertRail', 'FastenScrew')
ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / 'tasks/furniture_assembly/appearance.py').is_file())
CATALOG = ROOT / 'tasks/assets/variation/furniture_assembly/v1/catalog.json'
SCHEMES = tuple(json.loads(CATALOG.read_text(encoding='utf-8'))['schemes'])
CPU_SCHEMES = ('native_off', 'native_repeat', *SCHEMES)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def lf_text_sha(raw, suffix):
    if suffix.lower() not in ('.py', '.json'):
        return None
    raw.decode('utf-8', errors='strict')
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


def files_lf_identity(files, root=ROOT):
    normalized = {}
    for name, expected in files.items():
        path = (root / name).resolve(strict=True)
        require(path.is_relative_to(root.resolve()), f'Source outside repository: {name}')
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected,
                f'Current source differs from capture bytes: {name}')
        value = lf_text_sha(raw, path.suffix)
        if value is not None:
            normalized[name] = value
    return normalized


def digest_map(values, label):
    require(isinstance(values, dict) and values, f'Missing {label}')
    require(all(isinstance(value, str) and len(value) == 64
                and set(value) <= set('0123456789abcdef') for value in values.values()),
            f'Invalid SHA-256 in {label}')


def sdk_identity(path, lock_path=None):
    artifact = read(path)
    digest_map(artifact['native_files'], 'SDK native files')
    native = artifact['native_files']
    require(all(Path(name).name == name for name in native), 'SDK binary name contains a path')
    core = {'sapien.dll', 'svulkan2.dll', 'simsense.dll'}
    bindings = {name for name in native if name.endswith('.pyd')}
    require(core <= set(native) and len(bindings) == 1, 'SDK native binding/core is incomplete')
    result = {key: artifact[key] for key in ('wheel_sha256', 'source_commit', 'native_files')}
    result['artifact_sha256'] = sha(path)
    required_loaded, expected_loaded = core | bindings, dict(native)
    require('actual_toolchain' in artifact, 'Complete portable SDK build receipt is required')
    require(lock_path is not None, 'Portable SDK receipt requires --sdk-lock')
    lock = read(lock_path)
    actual, source = artifact['actual_toolchain'], artifact['actual_source']
    require(artifact['lock_sha256'] == actual['lock_sha256'] == source['lock_sha256'] == sha(lock_path),
            'Portable SDK lock identities differ')
    require(artifact['version'] == lock['local_version']
            and artifact['source_commit'] == lock['upstream']['commit']
            and artifact['patches'] == lock['patches']
            and artifact['reference_toolchain'] == lock['tested_toolchain']
            and artifact['physx_gpu'] == lock['runtime_physx'], 'Portable SDK receipt differs from lock')
    patches = {row['file']: row['sha256'] for row in artifact['patches']}
    require(len(patches) == len(artifact['patches']), 'Duplicate SDK patch identity')
    digest_map(patches, 'SDK patches')
    require(set(actual['recipe_sha256']) == {'prepare.py', 'build_windows.ps1', 'unpack_wheel.py', 'run_check.py'},
            'Portable SDK build recipe closure changed')
    digest_map(actual['recipe_sha256'], 'SDK build recipes')
    for filename, expected in {**patches, **actual['recipe_sha256']}.items():
        target = (lock_path.parent / filename).resolve(strict=True)
        require(target.is_relative_to(lock_path.parent.resolve()) and sha(target) == expected,
                f'Portable SDK patch/recipe changed: {filename}')
    require(set(source) == {'lock_sha256', 'common_only', 'source', 'dependencies', 'archive_trees'}
            and source['common_only'] is False, 'Unsupported SDK prepared-source schema')
    commits = {'.': lock['upstream']['commit'], **lock['upstream']['submodules']}
    require(set(source['source']) == set(commits), 'SDK source closure changed')
    compact_source = {}
    for name, record in source['source'].items():
        require(set(record) == {'commit', 'tracked_sha256'} and record['commit'] == commits[name],
                f'SDK source commit/schema changed: {name}')
        digest_map(record['tracked_sha256'], 'SDK tracked source')
        compact_source[name] = {'commit': record['commit'],
            'tracked_files': len(record['tracked_sha256']),
            'tracked_files_map_sha256': canonical_sha(record['tracked_sha256'])}
    dependencies = {entry['name']: entry['commit'] for entry in lock['git_dependencies']}
    require(set(source['dependencies']) == set(dependencies), 'SDK dependency closure changed')
    for name, record in source['dependencies'].items():
        require(record['commit'] == dependencies[name], f'SDK dependency commit changed: {name}')
        digest_map({'tree': record['tracked_tree_sha256']}, 'SDK dependency tree')
    digest_map(source['archive_trees'], 'SDK prepared archives')
    reference = lock['tested_toolchain']
    require(actual['python']['python'] == reference['python']
            and all(actual['python'][name] == lock['reference_packages'][name]
                    for name in ('setuptools', 'wheel'))
            and actual['cmake'] == reference['cmake'] and actual['ninja'] == reference['ninja']
            and actual['msvc_toolset'] == reference['toolset']
            and actual['msvc_file_version'] == reference['msvc'] + '.0'
            and ('V' + reference['cuda_nvcc']) in actual['nvcc_raw'].split()
            and actual['cuda_flags'].split() == reference['flags']
            and 1 <= actual['max_compile_jobs'] <= 4 and bool(actual['completed_utc']),
            'Actual SDK toolchain is not the locked complete build')
    physx = artifact['physx_gpu']['dll_sha256']
    digest_map(physx, 'PhysX GPU runtime')
    require(not (set(physx) & set(native)), 'SDK/PhysX binary names overlap')
    required_loaded |= set(physx)
    expected_loaded.update(physx)
    result.update(schema='portable-sdk-build-receipt', version=artifact['version'],
        lock_sha256=artifact['lock_sha256'], patches=artifact['patches'],
        reference_toolchain=artifact['reference_toolchain'], actual_toolchain=actual,
        actual_source={'record_canonical_sha256': canonical_sha(source),
            'source': compact_source, 'dependencies': source['dependencies'],
            'archive_trees': source['archive_trees'],
            'hash_semantics': 'Complete prepared-source record and tracked-file maps are represented by canonical JSON SHA-256; no path or file-byte normalization.'},
        physx_gpu=artifact['physx_gpu'], build_acceptance=artifact['acceptance'])
    return result, expected_loaded, required_loaded


def console_check(directory, run_directory, results, sdk_record):
    process = read(directory / 'process.json')
    require(process['returncode'] == 0 and process['timed_out'] is False,
            'Acceptance process failed or timed out')
    streams = {name: sha(directory / name) for name in ('stdout.txt', 'stderr.txt')}
    require(process['streams_sha256'] == streams, 'Console stream hashes changed')
    printed = read(directory / 'stdout.txt')
    require(printed['status'] == 'passed' and printed['scope'] == results['scope']
            and printed['tasks'] == [{key: row[key] for key in ('task', 'status')}
                                     for row in results['tasks']], 'Console/result verdict differs')
    command = process['command']
    require((ROOT / command[command.index('--output') + 1]).resolve() == run_directory.resolve(),
            'Console logs belong to another capture')
    runner = (ROOT / next(part for part in command[1:] if part.endswith('.py'))).resolve(strict=True)
    require(runner.name == 'run_check.py' and sdk_record['schema'] == 'portable-sdk-build-receipt'
            and sha(runner) == sdk_record['actual_toolchain']['recipe_sha256']['run_check.py'],
            'Console runner does not match the built SDK recipe')
    counts, continuation = {}, False
    text = re.sub(r'\x1b\[[0-9;]*m', '', (directory / 'stderr.txt').read_text(encoding='utf-8'))
    for line in filter(None, (value.strip() for value in text.splitlines())):
        if continuation:
            require(line == 'warnings.warn(', 'Unexpected warning continuation')
            continuation = False
            continue
        if re.fullmatch(r'.+[/\\]pinocchio_model\.py:\d+: UserWarning: pinnochio package is not installed, robotics functionalities will not be available', line):
            kind, continuation = 'optional_pinocchio_unavailable', True
        else:
            match = re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ - mani_skill\s+- WARNING - Overriding registered agent (panda|panda_wristcam)', line)
            require(match is not None, f'Unreviewed console stderr: {line}')
            kind = 'agent_registration_override:' + match.group(1)
        counts[kind] = counts.get(kind, 0) + 1
    require(not continuation, 'Incomplete optional-package warning')
    return {'process_sha256': sha(directory / 'process.json'), 'returncode': 0,
        'timed_out': False, 'streams_sha256': streams, 'known_warning_types': counts,
        'unreviewed_stderr_lines': 0, 'runner': {'file': runner.name, 'sha256': sha(runner)}}


def write(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2,
                                allow_nan=False) + '\n').encode('utf-8'))


def pixel_metrics(value):
    return {name: {key: row[key] for key in
            ('changed_values', 'changed_pixels', 'max_absolute_error')}
            for name, row in value.items()}


def zero_pixels(value):
    return bool(value) and all(row['changed_values'] == row['changed_pixels'] ==
                               row['max_absolute_error'] == 0 for row in value.values())


def changed_task_pixels(value):
    return any(row['changed_values'] > 0 for name, row in value.items()
               if not name.startswith('human'))


def selected_check(directory, row):
    import torch
    report = read(directory / row['evidence'])
    require(report == {key: value for key, value in row.items() if key != 'evidence'},
            'Selected reset inline/file reports differ')
    require(report['status'] == 'passed' and not report['mismatches']
            and not report['final_physical_mismatches'], 'Selected reset failed')
    require(report['float_absolute_tolerance'] == 2e-6
            and report['float_relative_tolerance'] == 0, 'Selected tolerance changed')
    path = directory / Path(row['evidence']).with_suffix('.pt')
    states = torch.load(path, map_location='cpu', weights_only=True)
    selected = report['selected']
    measurements = {}
    for stage, fields in (('fetched', report['checked_fields']),
                          ('final', report['final_physical_fields'])):
        values, total, changed = {}, 0, 0
        for field in fields:
            expected, actual = states['expected'][field][selected], states[stage][field][selected]
            require(expected.shape == actual.shape and expected.dtype == actual.dtype,
                    'Selected tensor signature changed')
            require(bool(torch.isfinite(expected).all() and torch.isfinite(actual).all()),
                    'Nonfinite selected tensor')
            error = float((expected.double() - actual.double()).abs().max()) if expected.numel() else 0.0
            tolerance = 2e-6 if torch.is_floating_point(expected) else 0
            require(error <= tolerance, 'Selected tensor exceeds recorded tolerance')
            values[field] = error
            total += expected.numel()
            changed += int((expected != actual).sum())
        measurements[stage] = {'fields': values, 'values_checked': total,
            'changed_values_within_tolerance': changed,
            'max_absolute_error': max(values.values(), default=0)}
    intent = report['selected_physical_intent_changes']
    if len(selected) == 1:
        require(bool(intent), 'Partial reset lacks nontrivial selected intent')
    return {'capture_id': Path(row['evidence']).stem, 'selected': selected, 'physics_steps': report['physics_steps'],
        'capture_order': [report['expected_capture'], report['observed_capture']],
        'float_atol': report['float_absolute_tolerance'], 'float_rtol': 0,
        'intent_changes': {name: {'changed_values': len(value['coordinates']),
                                 'max_absolute_error': value['max_absolute_error']}
                           for name, value in intent.items()},
        'buffer_only_fields': report['buffer_only_fields'], 'measurements': measurements,
        'raw_json_sha256': sha(directory / row['evidence']), 'raw_state_sha256': sha(path)}


def local_check(row, directory, prefix, native=False):
    import numpy as np
    from PIL import Image
    import torch

    require(row['selected'] in ([0], [1]), 'Invalid local reset direction')
    selected = row['selected'][0]
    frozen = 1 - selected
    raw_pt = directory / f'{prefix}.pt'
    states = torch.load(raw_pt, map_location='cpu', weights_only=True)
    after_state = 'after_capture' if native else 'after'
    for stage in (('after_reset_before_capture', after_state) if native else (after_state,)):
        exact_state(states['before'], states[stage], env=frozen)
    require(read(directory / f'{prefix}.json') == row, 'Local reset report differs from on-disk evidence')
    for camera in row['pixel_changes']:
        with Image.open(directory / f'{prefix}_{camera}_env{frozen}.png') as image:
            frames = np.array(image)
        require(frames.shape[1] % 2 == 0 and np.array_equal(*np.split(frames, 2, axis=1)),
                'Unselected raw before/after RGB differs')
    require(not row['state_changes']
            and row['controller_unchanged'] and row['task_rng_unchanged']
            and zero_pixels(row['pixel_changes']), 'Unselected isolation failed')
    require(all(row['controller_precondition'][f'nontrivial_targets_env{frozen}'].values()),
            'Controller precondition is trivial')
    precondition = row['controller_precondition']
    require(precondition['physics_steps'] == 0 and precondition['physical_state_unchanged']
            and any(value != 0 for value in precondition[f'generalized_forces_env{frozen}']),
            'Controller precondition lacks real force or changes physical state')
    require(row[f'before_controller_env{frozen}'] == row[f'after_controller_env{frozen}'],
            'Unselected controller changed')
    require(row[f'before_task_rng_env{frozen}'] == row[f'after_task_rng_env{frozen}'], 'Unselected task RNG changed')
    if native:
        require(row[f'materials_env{frozen}_unchanged'] and row['physical_unchanged'],
                'Native physical/material isolation failed')
    else:
        require(row['before_materials'][frozen] == row['after_materials'][frozen]
                and row['appearance_rng_unchanged']
                and row[f'before_appearance_rng_env{frozen}'] == row[f'after_appearance_rng_env{frozen}'], 'Unselected appearance changed')
        require(changed_task_pixels(row['selected_pixel_changes']), 'Selected RGB is stale')
        before = [r for r in row['before_records'] if r['env_idx'] == frozen]
        after = [r for r in row['after_records'] if r['env_idx'] == frozen]
        require(before == after and row['after_records'][:-1] == row['before_records']
                and row['after_records'][-1]['env_idx'] == selected, 'Episode records changed incorrectly')
    return {'selected': [selected], 'unselected_env_idx': frozen, 'raw_state_sha256': sha(raw_pt),
        'raw_json_sha256': sha(directory / f'{prefix}.json'), 'precondition_control_steps': row['precondition_control_steps'],
        'precondition_physics_steps': row['precondition_physics_steps'],
        'controller_precondition': row['controller_precondition'][f'nontrivial_targets_env{frozen}'],
        'precondition_action_sha256': canonical_sha(precondition['action']),
        'precondition_max_abs_force': max(abs(v) for v in precondition[f'generalized_forces_env{frozen}']),
        'shared_controller_counters': {'before': row['before_shared_controller_counters'],
                                       'after': row['after_shared_controller_counters']},
        'unselected': {'state_changed_fields': 0, 'controller_changed': False,
            'materials_changed': False, 'task_rng_changed': False,
            'controller_sha256': canonical_sha(row[f'before_controller_env{frozen}']),
            'materials_sha256': canonical_sha(row['before_materials'][frozen]),
            'task_rng_sha256': canonical_sha(row[f'before_task_rng_env{frozen}']),
            'pixel_changes': pixel_metrics(row['pixel_changes'])},
        **({} if native else {'scheme_id': row['scheme_id'],
            'appearance_rng_changed': False, 'unselected_episode_records_changed': False,
            'appearance_rng_sha256': canonical_sha(row[f'before_appearance_rng_env{frozen}']),
            'selected_pixel_changes': pixel_metrics(row['selected_pixel_changes'])})}


def fixed_rgb_check(directory, fixed):
    import numpy as np
    from PIL import Image
    by_env = {0: set(), 1: set()}
    for scheme in SCHEMES:
        for env in by_env:
            fingerprints = []
            for camera in sorted(fixed[scheme]['pixels_vs_native'][str(env)]):
                with Image.open(directory / f'{scheme}_{camera}_env{env}.png') as stream:
                    frame = np.array(stream)
                if not camera.startswith('human'):
                    fingerprints.append(hashlib.sha256(frame.tobytes()).hexdigest())
                if scheme == 'original':
                    with Image.open(directory / f'native_capture_{camera}_env{env}.png') as stream:
                        pair = np.array(stream)
                    require(np.array_equal(pair, np.concatenate((frame, frame), axis=1)),
                            f'{camera}/env{env}: original RGB differs from native repeat')
                if 'restoration_pixels' in fixed[scheme]:
                    with Image.open(directory / f'restored_{scheme}_{camera}_env{env}.png') as stream:
                        pair = np.array(stream)
                    with Image.open(directory / f'original_{camera}_env{env}.png') as stream:
                        original = np.array(stream)
                    require(np.array_equal(pair, np.concatenate((frame, original), axis=1)),
                            f'{scheme}/{camera}/env{env}: raw restoration RGB differs')
            fingerprint = tuple(fingerprints)
            require(fingerprint and fingerprint not in by_env[env], 'Fixed candidate camera RGB is not distinct')
            by_env[env].add(fingerprint)
    return {str(index): len(values) for index, values in by_env.items()}


def measured_gpu_step(directory, prefix, after_key):
    import torch

    first = torch.load(directory / f'{prefix}_0.pt', map_location='cpu', weights_only=True)[after_key]
    second = torch.load(directory / f'{prefix}_1.pt', map_location='cpu', weights_only=True)['before']
    require(torch.equal(second['/elapsed_steps'], first['/elapsed_steps'] + 1),
            'GPU isolation did not exercise a control step in both environments')
    qpos = '/joint_targets/robot/qpos'
    motion = (second[qpos] - first[qpos]).abs().amax(dim=1)
    require(bool(torch.all(torch.isfinite(motion) & (motion > 0))), 'GPU control step did not move both robots')
    return motion.tolist()


def task_check(directory, task):
    require(task['status'] == 'passed' and task['stage'] == 'complete'
            and task['test_mode'] == 'standard'
            and task['capture_path'] == 'original ManiSkill RGB cameras'
            and not task.get('close_error'), 'Task is not complete standard RGB acceptance')
    require(task['control_steps'] == 2 and task['physics_steps'] == 40, 'Unexpected step counts')
    checks = task['checks']
    version = checks['original']['records'][0]['catalog_version']
    restored_schemes = SCHEMES[1:] if version == 'furniture-appearance-v2' else SCHEMES[3:]
    require(checks['default_disabled'] == checks['explicit_disabled'] ==
            checks['selection_precedence'] == 'passed', 'Interface checks failed')
    selected = [selected_check(directory, row) for row in checks['selected_reset_state']]
    require(len(selected) >= 22 + 2 * len(SCHEMES[3:]), 'Selected reset coverage is incomplete')
    fixed = {}
    for scheme in SCHEMES:
        require(checks[scheme]['status'] == 'passed', 'Fixed scheme failed')
        pixels = read(directory / f'{scheme}_pixel_comparison.json')
        require(set(pixels) == {'0', '1'}, 'Missing fixed environment')
        require(all(zero_pixels(v) if scheme == 'original' else changed_task_pixels(v)
                    for v in pixels.values()), 'Fixed RGB comparison failed')
        fixed[scheme] = {'materials_sha256': canonical_sha(checks[scheme]['materials']),
            'records': checks[scheme]['records'],
            'pixels_vs_native': {i: pixel_metrics(v) for i, v in pixels.items()}}
        if scheme in restored_schemes:
            restored = checks[scheme]['original_restoration']
            require(restored['materials_match_native'] is True and restored['physical_state_match_native'] is True
                    and set(restored['pixel_changes']) == {'0', '1'} and all(zero_pixels(v) for v in restored['pixel_changes'].values()),
                    'New candidate did not restore original materials, physical state or RGB')
            fixed[scheme]['restoration_pixels'] = {i: pixel_metrics(v) for i, v in restored['pixel_changes'].items()}
    distinct = fixed_rgb_check(directory, fixed)
    restoration = checks['original_rgb_restoration']
    require(restoration['status'] == 'passed'
            and all(zero_pixels(v) for v in restoration['pixel_changes'].values()),
            'Original RGB restoration failed')
    native = checks['native_local_reset_control']
    require(len(native['rounds']) == 2
            and [row['precondition_control_steps'] for row in native['rounds']] == [0, 1]
            and [checks[f'local_reset_{i}']['precondition_control_steps'] for i in range(2)] == [0, 1]
            and [row['selected'] for row in native['rounds']] == [[1], [0]]
            and [checks[f'local_reset_{i}']['selected'] for i in range(2)] == [[1], [0]],
            'Missing pre/post-step isolation cases')
    capture = native['capture_diagnostic']
    require(not capture['first_capture_state_changes'] and not capture['repeat_capture_state_changes']
            and zero_pixels(capture['repeat_capture_pixel_changes'])
            and zero_pixels(capture['repeat_capture_pixel_changes_env1']), 'Capture changes state/RGB')
    capture_path = directory / 'native_capture_states.pt'
    import torch
    states = torch.load(capture_path, map_location='cpu', weights_only=True)
    exact_state(states['before_capture'], states['after_first_capture'])
    exact_state(states['after_first_capture'], states['after_repeat_capture'])
    physical = read(directory / 'native_physical.json')
    return {'task_id': f"FurnitureAssembly{task['task']}-Sharpa-v1", 'status': 'passed',
        'control_steps': task['control_steps'], 'physics_steps': task['physics_steps'],
        'native_physical': {'file_sha256': sha(directory / 'native_physical.json'),
            'canonical_sha256': canonical_sha(physical),
            'entities_per_env': [len(scene) for scene in physical['scenes']]},
        'fixed': fixed, 'distinct_fixed_task_camera_schemes': distinct, 'selected_reset_checks': selected,
        'native_capture_state_sha256': sha(capture_path),
        'gpu_step_maximum_joint_displacement_by_env': {
            'native_off': measured_gpu_step(directory, 'native_local', 'after_capture'),
            'appearance': measured_gpu_step(directory, 'local', 'after')},
        'original_rgb_restoration': {i: pixel_metrics(v) for i, v in restoration['pixel_changes'].items()},
        'random_reproducibility': checks['random_reproducibility'], 'selection_precedence': 'passed',
        'native_local_reset': [local_check(row, directory, f'native_local_{i}', native=True)
                               for i, row in enumerate(native['rounds'])],
        'appearance_local_reset': [local_check(checks[f'local_reset_{i}'], directory, f'local_{i}') for i in range(2)]}


def exact_state(left, right, env=None):
    import torch

    require(left and left.keys() == right.keys(), 'State field coverage differs')
    for field, value in left.items():
        actual = right[field]
        require(value.shape == actual.shape and value.dtype == actual.dtype, f'State signature differs: {field}')
        if env is not None:
            require(value.ndim and value.shape[0] == 2, f'State lacks a two-environment axis: {field}')
            value, actual = value[env], actual[env]
        require(torch.equal(value, actual) and bool(torch.isfinite(value).all()), f'State changed or is nonfinite: {field}')


def cpu_interface_check(root, gpu_identity, sdk_record, expected_native):
    import torch

    results = read(root / 'results.json')
    manifest = read(root / 'manifest.json')
    sdk = read(root / 'private_sdk.json')
    require(results['status'] == 'passed' and results['source_hashes_unchanged'] is True
            and results['control_steps'] == results['physics_steps'] == 0 and manifest['sim_backend'] == 'physx_cpu'
            and manifest['num_envs'] == 1 and manifest['capture_path'] == 'not captured', 'CPU interface receipt scope differs')
    require(manifest['files'] == gpu_identity['files'] and tuple(manifest['schemes']) == SCHEMES,
            'CPU interface input identity differs from CUDA')
    require(sdk['binaries_unchanged'] is True and sdk['before'] == sdk['after']
            and sdk['artifact_sha256'] == sdk_record['artifact_sha256']
            and sdk['version'] == manifest['versions']['sapien'] == sdk_record['version']
            and {name: row['sha256'] for name, row in sdk['before'].items()} == expected_native,
            'CPU interface did not use the verified SDK')
    require([row['task'] for row in results['tasks']] == list(TASKS), 'CPU interface task coverage differs')
    checked = {}
    for row in results['tasks']:
        task = row['task']
        directory = root / task
        checks = row['checks']
        require(row['status'] == 'passed' and row['stage'] == 'complete'
                and all(checks[name] == 'passed' for name in ('default_disabled', 'explicit_disabled', 'selection_precedence'))
                and checks['minimal_visuals']['schemes'] == [*SCHEMES, 'original'], 'CPU interface checks are incomplete')
        baseline = torch.load(directory / 'native_state.pt', map_location='cpu', weights_only=True)
        states = {}
        for name in SCHEMES:
            state_path = directory / f'{name}_state.pt'
            exact_state(baseline, torch.load(state_path, map_location='cpu', weights_only=True))
            require(checks[name]['status'] == 'passed' and checks[name]['records'][-1]['scheme_id'] == name,
                    f'{task}/{name}: CPU interface materials or episode record failed')
            if name in (SCHEMES[1:] if manifest['catalog_version'] == 'furniture-appearance-v2' else SCHEMES[3:]):
                require(checks[name]['original_restoration'] == {'materials_match_native': True, 'physical_state_match_native': True},
                        f'{task}/{name}: CPU interface original restoration failed')
            states[name] = sha(state_path)
        checked[task] = {'native_state_sha256': sha(directory / 'native_state.pt'), 'fixed_state_sha256': states}
    return {'status': 'passed', 'scope': results['scope'], 'manifest_sha256': sha(root / 'manifest.json'),
            'results_sha256': sha(root / 'results.json'), 'private_sdk_sha256': sha(root / 'private_sdk.json'),
            'tasks': checked}


def cpu_check(root, gpu_identity):
    import numpy as np
    import torch
    expected_control = len(TASKS) * len(CPU_SCHEMES) * 60
    report = read(root / 'summary.json')
    require(report['status'] == 'passed' and report['source_hashes_unchanged']
            and report.get('control_steps_per_run') == 60
            and report.get('total_control_steps') == expected_control
            and report.get('completed_runs') == len(TASKS) * len(CPU_SCHEMES)
            and report.get('counts_complete') is True and report.get('unknown_runs') == [],
            'CPU receipt must cover all catalog schemes and two native baselines')
    require(set(report['tasks']) == set(TASKS), 'CPU receipt lacks a task')
    source = report['source_sha256']
    for name, value in gpu_identity['files'].items():
        if name != 'tools/variation/check_furniture_appearance.py':
            require(source.get(name) == value, f'CPU/GPU source differs: {name}')
    require('tools/variation/check_furniture_dynamics.py' in source,
            'CPU dynamics tool must be deliverable')
    compact = {'scope': 'Single CPU environment; no RGB/GPU or task-completion claim',
        'summary_sha256': sha(root / 'summary.json'), 'seed': report['seed'],
        'control_steps_per_run': 60, 'control_steps': expected_control,
        'physics_steps': report['total_physics_steps'], 'source_sha256': source,
        'source_lf_sha256': files_lf_identity(source),
        'source_hash_semantics': 'source_sha256 retains raw capture bytes; source_lf_sha256 verifies those bytes before UTF-8 .py/.json CRLF-to-LF normalization only.',
        'tasks': {}}
    receipt_path = root / 'receipt.json'
    if receipt_path.is_file():
        receipt = read(receipt_path)
        require(receipt['status'] == 'passed' and receipt['summary_sha256'] == sha(root / 'summary.json')
                and receipt['source_sha256'] == source
                and receipt['tool_sha256'] == source['tools/variation/check_furniture_dynamics.py'],
                'CPU receipt does not match summary/tool')
        compact['receipt_sha256'] = sha(receipt_path)
        compact['command'] = receipt['command']
    control_total, physics_total = 0, 0
    for name in TASKS:
        runs, baseline = {}, None
        require(set(report['tasks'][name]) == set(CPU_SCHEMES), 'Wrong CPU scheme coverage')
        actions_path = root / name / 'actions.npy'
        action_hash = sha(actions_path)
        actions = np.load(actions_path, allow_pickle=False)
        require(actions.dtype == np.float32 and actions.shape[0] == 60 and np.isfinite(actions).all(), 'Invalid CPU actions')
        for scheme in CPU_SCHEMES:
            directory = root / name / scheme
            run = read(directory / 'run.json')
            require(run['status'] == 'completed' and run['source_sha256'] == source
                    and run['task'] == name and run['scheme'] == scheme,
                    'CPU worker failed or source changed')
            appearance = run['appearance_config']
            require((appearance['enabled'] is False if scheme in ('native_off', 'native_repeat') else
                     appearance['enabled'] is True and appearance['scheme_id'] == scheme), 'CPU scheme configuration differs')
            require(run['constructor_kwargs']['num_envs'] == 1
                    and run['constructor_kwargs']['sim_backend'] == 'physx_cpu'
                    and run['control_steps'] == 60 and not run['image_capture']
                    and run['actions']['legal'], 'CPU worker scope mismatch')
            require(run['sapien_binary']['sha256'] == gpu_identity['binding_sha256']
                    and run['packages']['sapien'] == gpu_identity['versions']['sapien'],
                    'CPU worker SAPIEN binding/version differs from CUDA')
            require(action_hash == run['actions']['sha256'] and list(actions.shape) == run['actions']['shape'],
                    'CPU modes used different actions')
            trajectory_path = directory / 'trajectory.pt'
            states = torch.load(trajectory_path, map_location='cpu', weights_only=True)
            require(len(states) == 61, 'CPU trajectory misses initial/step samples')
            if baseline is None:
                baseline = states
            for expected, actual in zip(baseline, states):
                require(expected.keys() == actual.keys(), 'CPU trajectory fields differ')
                require(all(value.dtype == actual[field].dtype and value.shape == actual[field].shape
                            and torch.equal(value, actual[field]) and bool(torch.isfinite(value).all())
                            for field, value in expected.items()), 'CPU trajectory difference/nonfinite state')
            if scheme != 'native_off':
                comparison = read(directory / 'comparison.json')
                require(comparison['status'] == 'passed' and comparison['samples'] == 61
                        and comparison['initial_state_equal'] and not comparison['failed_steps']
                        and comparison['worst_difference']['max_absolute_error'] == 0,
                        'CPU recorded comparison failed')
            control_total += run['control_steps']
            physics_total += run['physics_steps']
            runs[scheme] = {'run_sha256': sha(directory / 'run.json'),
                'trajectory_sha256': sha(trajectory_path), 'control_steps': 60,
                'physics_steps': run['physics_steps'], 'samples': 61,
                'max_absolute_error_vs_native': 0, 'panel_color_jitter': run['panel_color_jitter'],
                'packages': run['packages'], 'sapien_binary_sha256': run['sapien_binary']['sha256']}
        motion = max(float((state[field].double() - baseline[0][field].double()).abs().max())
                     for state in baseline for field in state if field.startswith('/joint/')
                     and field.endswith('/qpos') and state[field].numel())
        require(motion > 0, 'CPU trajectory does not exercise motion')
        compact['tasks'][name] = {'actions_sha256': action_hash,
            'maximum_joint_displacement_rad': motion, 'runs': runs}
    require(control_total == expected_control and physics_total == expected_control * 20 == report['total_physics_steps'],
            'CPU total step count mismatch')
    return compact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, action='append', required=True)
    parser.add_argument('--console-run', type=Path, action='append', required=True)
    parser.add_argument('--sdk-artifacts', type=Path, required=True)
    parser.add_argument('--sdk-lock', type=Path, help='Required for portable build receipts')
    parser.add_argument('--cpu-run', type=Path, required=True)
    parser.add_argument('--cpu-interface', type=Path, required=True)
    parser.add_argument('--cpu-interface-console', type=Path, required=True)
    parser.add_argument('--fixed-camera', choices=('human', 'base_camera', 'external_camera'), default='human')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'Choose a new output directory')
    require(len(args.run) == len(args.console_run), 'Provide one --console-run per --run')
    sdk_record, expected_loaded, required_loaded = sdk_identity(args.sdk_artifacts, args.sdk_lock)
    summary = {'format': 'furniture-runtime-evidence-v1', 'status': 'passed',
        'scope': 'Appearance/reset acceptance; three short tasks; two CUDA environments; no policy/task-success claim',
        'image_selection': {'fixed_camera': args.fixed_camera, 'isolation_camera': 'base_camera',
                            'encoding': 'unchanged original PNG bytes'},
        'exporter': {'file': Path(__file__).name, 'sha256': sha(Path(__file__)),
                     'lf_sha256': lf_text_sha(Path(__file__).read_bytes(), '.py')},
        'sdk': sdk_record,
        'captures': [], 'tasks': {}, 'images': {}}
    prepared, images, source_identity = {}, {}, None
    for root, console_directory in zip(args.run, args.console_run):
        results, manifest, sdk = (read(root / name) for name in
                                 ('results.json', 'manifest.json', 'private_sdk.json'))
        require(results['status'] == results['formal_acceptance'] == 'passed'
                and results['test_mode'] == manifest['test_mode'] == 'standard'
                and results.get('source_hashes_unchanged') is True,
                'Diagnostic, incomplete or failed acceptance cannot be exported')
        require(tuple(manifest['schemes']) == SCHEMES, 'Capture does not cover the current catalog order')
        require(manifest['sim_backend'] == 'physx_cuda' and manifest['num_envs'] == 2
                and manifest['capture_path'] == 'original ManiSkill RGB cameras',
                'CPU/readback fallback cannot be exported')
        require('--diagnostic-native-readback' not in manifest['command'], 'Diagnostic command rejected')
        console = console_check(console_directory, root, results, sdk_record)
        require(sdk['indexed_gpu_apply_patch_version'] == 1 and sdk['binaries_unchanged']
                and sdk['before'] == sdk['after'], 'SDK identity changed')
        require(required_loaded <= set(sdk['before']), 'Loaded SDK/PhysX identity is incomplete')
        require(all(value['sha256'] == expected_loaded[name]
                    for name, value in sdk['before'].items()), 'Loaded SDK does not match artifact lock')
        require(all(sha(Path(value['path'])) == value['sha256'] for value in sdk['before'].values()),
                'Current loaded SDK file bytes differ from capture')
        if sdk_record['schema'] == 'portable-sdk-build-receipt':
            require(sdk.get('artifact_sha256') == sdk_record['artifact_sha256']
                    and sdk.get('version') == manifest['versions']['sapien'] == sdk_record['version']
                    and manifest['physx_gpu_library_sha256'] == sdk_record['physx_gpu']['dll_sha256']
                    and manifest['physx_version'] == sdk_record['physx_gpu']['version'],
                    'Loaded portable SDK/version/PhysX does not match build receipt')
        identity = {'git_commit': manifest['git_commit'], 'files': manifest['files'],
            'files_lf_sha256': files_lf_identity(manifest['files']),
            'binding_sha256': next(value['sha256'] for name, value in sdk['before'].items() if name.endswith('.pyd')),
            'source_hash_semantics': {
                'files': 'Unchanged raw capture-time file-byte SHA-256.',
                'files_lf_sha256': 'Current bytes first verified against files; UTF-8 .py/.json only; CRLF replaced by LF; all other bytes unchanged.'},
            'versions': manifest['versions'], 'physx_version': manifest['physx_version'],
            'physx_gpu_library_sha256': manifest['physx_gpu_library_sha256']}
        require(source_identity is None or source_identity == identity, 'Source/SDK identity differs between runs')
        source_identity = identity
        command = list(manifest['command'])
        command[0] = 'tools/variation/check_furniture_appearance.py'
        command[command.index('--output') + 1] = '{capture_directory}'
        if '--physx-gpu-dir' in command:
            command[command.index('--physx-gpu-dir') + 1] = '{physx_gpu_directory}'
        require(not any(Path(value).is_absolute() for value in command), 'Absolute path in capture command')
        summary['captures'].append({'results_sha256': sha(root / 'results.json'),
            'manifest_sha256': sha(root / 'manifest.json'), 'private_sdk_sha256': sha(root / 'private_sdk.json'),
            'manifest': {key: manifest[key] for key in ('platform', 'python', 'sim_backend',
                'num_envs', 'test_mode', 'gpu_bootstrap', 'experimental_windows_cuda', 'catalog_version')},
            'command': command, 'capture_path': manifest['capture_path'],
            'task_ids': manifest['task_ids'], 'control_steps': results['control_steps'],
            'physics_steps': results['physics_steps'], 'console': console})
        for task in results['tasks']:
            name = task['task']
            require(name in TASKS and name not in prepared, 'Unknown or duplicate task')
            prepared[name] = task_check(root / name, task)
            names = [f'{scheme}_{args.fixed_camera}_env0.png' for scheme in SCHEMES] + [
                f'local_{i}_base_camera_env{env}.png' for i in range(2) for env in range(2)]
            for filename in names:
                source = root / name / filename
                from PIL import Image
                with Image.open(source) as image:
                    image.verify()
                images[f'{name}/{filename}'] = source
    require(set(prepared) == set(TASKS), 'All three tasks are required')
    require(sum(row['control_steps'] for row in prepared.values()) == 6
            and sum(row['physics_steps'] for row in prepared.values()) == 120, 'Incomplete dynamic coverage')
    cpu = cpu_check(args.cpu_run, source_identity)
    loaded = {name: expected_loaded[name] for name in required_loaded}
    interface = cpu_interface_check(args.cpu_interface, source_identity, sdk_record, loaded)
    interface['console'] = console_check(args.cpu_interface_console, args.cpu_interface,
                                         read(args.cpu_interface / 'results.json'), sdk_record)
    summary['identity'] = source_identity
    summary['schemes'] = list(SCHEMES)
    # No filesystem output is created until every acceptance check above succeeds.
    args.output.mkdir(parents=True)
    write(args.output / 'cpu_checks.json', cpu)
    write(args.output / 'cpu_interface.json', interface)
    summary['cpu_dynamics'] = {'checks': 'cpu_checks.json', 'sha256': sha(args.output / 'cpu_checks.json')}
    summary['cpu_interface'] = {'checks': 'cpu_interface.json', 'sha256': sha(args.output / 'cpu_interface.json')}
    for name, value in prepared.items():
        (args.output / name).mkdir()
        write(args.output / name / 'checks.json', value)
        summary['tasks'][name] = {'checks': f'{name}/checks.json',
            'sha256': sha(args.output / name / 'checks.json')}
    for target, source in images.items():
        shutil.copyfile(source, args.output / target)
        require(sha(args.output / target) == sha(source), 'PNG bytes changed')
        summary['images'][target] = {'sha256': sha(source), 'bytes': source.stat().st_size}
    write(args.output / 'summary.json', summary)
    print(json.dumps({'status': 'exported', 'images': len(images),
        'bytes': sum(path.stat().st_size for path in args.output.rglob('*') if path.is_file())}))


if __name__ == '__main__':
    main()
