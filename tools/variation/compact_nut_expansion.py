"""Recompute and export Nut & Bolt ten-candidate evidence from one raw run."""
import argparse
import hashlib
from itertools import combinations
import json
from pathlib import Path
import subprocess

import numpy as np

import compact_task_runtime as raw
from check_nut_bolt_runtime import MIN_WITNESS_CHANNEL_DELTA, MIN_WITNESS_PIXELS, SCHEMES

ROOT = Path(__file__).resolve().parents[2]
PROFILE = raw.PROFILES['nut_bolt']
TASKS = PROFILE['tasks']
CASES = {'PickBolt': (7, 'base_camera'), 'SeatNut': (1, 'wrist_camera'), 'TurnNut': (26, 'human')}
DYNAMIC_SCHEMES = ('native_off', 'native_repeat', *SCHEMES)
require = raw.require


def check_baseline(baseline):
    """Audit preserved definitions and the publication delta against the exact PR head."""
    for obj in ('bolt', 'nut'):
        name = f'assets/appearance/objects/nut_bolt/{obj}/variants/v1/catalog.json'
        old = json.loads(subprocess.check_output(['git', 'show', f'{baseline}:{name}'], cwd=ROOT))
        new = raw.read(ROOT / name)
        require(tuple(new['schemes']) == SCHEMES, f'{obj} scheme inventory differs')
        require(all(new['schemes'][key] == value for key, value in old['schemes'].items()),
                f'{obj} original or an existing scheme changed')
        require({k: v for k, v in old.items() if k not in ('schemes', 'version')} ==
                {k: v for k, v in new.items() if k not in ('schemes', 'version')},
                f'{obj} binding properties changed')
    locked = ('tasks/nut_bolt', 'assets/appearance/objects/nut_bolt/bolt/bindings.json',
              'assets/appearance/objects/nut_bolt/nut/bindings.json',
              'assets/appearance/objects/nut_bolt/previews/runtime',
              'tools/variation/compact_task_runtime.py', 'tools/variation/sapien_sdk')
    require(subprocess.run(['git', 'diff', '--quiet', baseline, '--', *locked], cwd=ROOT).returncode == 0,
            'Frozen task logic, bindings, old evidence or shared SDK tools changed')


def verify_private(path, sdk, checker, source, *, gpu):
    receipt = raw.read(path)
    require(receipt['private_sdk'] and receipt['artifact_sha256'] == sdk['artifact_sha256']
            and receipt['version'] == sdk['version'] and receipt['binaries_unchanged'], 'Private SDK receipt differs')
    raw.launcher_check(receipt, ROOT, f'tools/variation/{checker}', source, PROFILE['launcher'], sdk)
    loaded, binding = raw.sdk_check(receipt['before'], receipt['after'], sdk['expected_loaded'],
                                    set(sdk['required_loaded']), gpu=gpu)
    return loaded, raw.sdk_python_check(receipt, binding), raw.vulkan_loader_check(receipt)


def verify_pairs(directory, task, witness):
    frames = {(scheme, env): raw.pair(directory / f'fixed_{scheme}_{witness}_env{env}.png')[1]
              for scheme in SCHEMES for env in (0, 1)}
    recomputed = []
    for left, right in combinations(SCHEMES, 2):
        for env in (0, 1):
            delta = np.abs(frames[left, env].astype(np.int16) - frames[right, env].astype(np.int16))
            pixels = int((delta.max(axis=-1) >= MIN_WITNESS_CHANNEL_DELTA).sum())
            require(pixels >= MIN_WITNESS_PIXELS, f'Visually near pair: {left}/{right} env{env} {pixels}')
            recomputed.append({'schemes': [left, right], 'env_idx': env, 'camera': witness,
                               'pixels_at_min_delta': pixels, 'max_absolute_error': int(delta.max())})
    require(recomputed == task['checks']['candidate_visibility_pairs'], 'Raw witness pair values differ from PNGs')
    return recomputed


def verify_gpu(root, sdk, commit):
    captures, tasks, image_paths = {}, {}, {}
    input_files = external_files = gpu_identity = None
    # The shared verifier owns all original task, step, PBR, state, PNG and reset checks.
    previous_schemes_for = raw.schemes_for
    raw.schemes_for = lambda family, task: SCHEMES if family == 'nut_bolt' else previous_schemes_for(family, task)
    try:
        for task_name in TASKS:
            directory = root / f'gpu-{task_name}'
            manifest = raw.read(directory / 'manifest.json')
            results = raw.read(directory / 'results.json')
            seed, witness = CASES[task_name]
            require(manifest['git_commit'] == commit and manifest['sim_backend'] == 'physx_cuda'
                    and manifest['num_envs'] == 2 and manifest['test_mode'] == results['test_mode'] == 'standard'
                    and manifest['reset_seed'] == seed and manifest['candidate_visibility_camera'] == witness
                    and '--diagnostic-native-readback' not in manifest['command']
                    and results['status'] == results['formal_acceptance'] == 'passed'
                    and results['source_hashes_unchanged'] and results['external_hashes_unchanged'],
                    f'{task_name}: incomplete standard CUDA capture')
            source, external = manifest['files'], manifest['external_files']
            require(input_files is None or (source == input_files and external == external_files),
                    'GPU tasks used different input bytes')
            input_files, external_files = source, external
            require(len(results['tasks']) == 1 and results['tasks'][0]['task'] == task_name,
                    f'{task_name}: capture contains a different task')
            task = results['tasks'][0]
            require(task['capture_path'] == PROFILE['capture'], 'Expected the standard native CUDA path')
            identity = verify_private(directory / 'private_sdk.json', sdk, PROFILE['checker'], source, gpu=True)
            require(gpu_identity is None or identity == gpu_identity, 'GPU tasks loaded different SDKs')
            gpu_identity = identity
            assets = raw.asset_identity('nut_bolt', manifest, task, ROOT)
            raw.CAPTURE_FILES.clear()
            raw.CAPTURE_FILES.update({**source, **external, **assets['raw_sha256']})
            verified = raw.task_check(directory, task, 'nut_bolt', PROFILE, image_paths, ROOT)
            verified['visibility_pairs'] = verify_pairs(directory / task_name, task, witness)
            verified['assets'] = assets
            verified['robot_closure'] = raw.robot_closure(verified['assets']['raw_sha256'], ROOT,
                                                          verified['robot_urdf_names'])
            tasks[task_name] = verified
            captures[task_name] = {'run': directory.name, 'seed': seed, 'visibility_camera': witness,
                'results_sha256': raw.track(directory / 'results.json'), 'manifest_sha256': raw.track(directory / 'manifest.json'),
                'private_sdk_sha256': raw.track(directory / 'private_sdk.json'),
                'console': raw.console_check(root / (directory.name + '-monitor'), directory, results,
                                             raw.read(directory / 'private_sdk.json'), ROOT, PROFILE),
                'generated_urdf': task.get('generated_urdf')}
    finally:
        raw.schemes_for = previous_schemes_for
    return captures, tasks, input_files, external_files, gpu_identity


def verify_cpu_console(root, name):
    receipt = raw.read(root / (name + '.process.json'))
    require(receipt['returncode'] == 0 and all(
        receipt[stream + '_sha256'] == raw.track(root / f'{name}.{stream}.txt')
        for stream in ('stdout', 'stderr')), f'{name}: console or process identity differs')
    return receipt


def verify_cpu(root, sdk, source, external, gpu_identity, captures, commit):
    interface = root / 'cpu-interface'
    manifest = raw.read(interface / 'manifest.json')
    result = raw.read(interface / 'results.json')
    require(manifest['git_commit'] == commit and manifest['files'] == source and manifest['external_files'] == external
            and manifest['num_envs'] == 1 and manifest['sim_backend'] == 'physx_cpu'
            and result['status'] == 'passed' and result['source_hashes_unchanged'] and result['external_hashes_unchanged'],
            'CPU formal interface source or verdict differs')
    cpu_identity = verify_private(interface / 'private_sdk.json', sdk, PROFILE['checker'], source, gpu=False)
    require(cpu_identity[1:] == gpu_identity[1:], 'CPU interface SDK Python or loader differs from GPU')
    require(tuple(t['task'] for t in result['tasks']) == TASKS and all(
        task['status'] == 'passed' and task['checks']['default_disabled'] == 'passed'
        and task['checks']['explicit_disabled'] == task['checks']['precedence_and_atomicity'] == 'passed'
        and task['checks']['random_reproducibility']['status'] == 'passed'
        and all(task['checks']['fixed_' + scheme]['status'] == 'passed' for scheme in SCHEMES)
        for task in result['tasks']), 'CPU interface omitted a task, scheme, or contract')

    dynamics = root / 'cpu-dynamics'
    summary = raw.read(dynamics / 'summary.json')
    count = len(TASKS) * len(DYNAMIC_SCHEMES)
    require(summary['status'] == 'passed' and summary['source_sha256'] == source and summary['external_sha256'] == external
            and summary['source_hashes_unchanged'] and summary['external_hashes_unchanged'] and not summary['failures']
            and summary['completed_runs'] == count and summary['total_control_steps'] == count * 60
            and summary['total_physics_steps'] == count * 1200, 'CPU dynamics scope or input closure differs')
    tasks = {}
    for task in TASKS:
        require(set(summary['tasks'][task]) == set(DYNAMIC_SCHEMES), f'{task}: dynamic sequence set differs')
        action_file = dynamics / task / 'actions.npy'
        actions = np.load(action_file, allow_pickle=False)
        action_sha = raw.track(action_file)
        require(actions.dtype == np.float32 and actions.shape[0] == 60 and np.isfinite(actions).all()
                and np.any(actions != 0), 'Missing nontrivial CPU action sequence')
        motion, baseline, branches = 0., None, {}
        for scheme in DYNAMIC_SCHEMES:
            directory = dynamics / task / scheme
            run = raw.read(directory / 'run.json')
            record = summary['tasks'][task][scheme]
            private_path = directory / 'private_sdk.json'
            require(record['returncode'] == 0 and record['run_sha256'] == raw.track(directory / 'run.json')
                    and record['private_sdk_sha256'] == raw.track(private_path)
                    and run['status'] == 'completed' and run['scheme'] == scheme and run['task'] == task
                    and run['seed'] == summary['seed'] and run['image_capture'] is False
                    and run['requested_control_steps'] == run['control_steps'] == 60
                    and run['physics_steps'] == 1200 and run['sim_steps_per_control'] == 20
                    and run['source_sha256'] == source and run['external_sha256'] == external
                    and run['external_hashes_unchanged'] and run['sdk_native_before'] == run['sdk_native_after']
                    and run['actions']['legal'] and run['actions']['sha256'] == action_sha
                    and run['actions']['shape'] == list(actions.shape), f'{task}/{scheme}: CPU scope or inputs differ')
            kwargs = run['constructor_kwargs']
            expected = {'enabled': False} if scheme.startswith('native_') else {'enabled': True, 'scheme_id': scheme, 'seed': 71}
            require(kwargs == {'nut_bolt_appearance': expected, 'sim_backend': 'physx_cpu', 'num_envs': 1},
                    f'{task}/{scheme}: CPU constructor differs')
            private = verify_private(private_path, sdk, PROFILE['dynamics'], source, gpu=False)
            require(private[1:] == gpu_identity[1:] and run['sapien_binary']['sha256'] ==
                    sdk['expected_loaded'][Path(run['sapien_binary']['path']).name], 'CPU worker actual SDK differs')
            require(run.get('generated_urdf') == captures[task]['generated_urdf'], 'CPU/GPU nut URDF identity differs')
            path = directory / 'trajectory.pt'
            trajectory = raw.load(path)
            require(len(trajectory) == 61, 'Incomplete raw stepped CPU trajectory')
            if baseline is None:
                baseline = trajectory
            for index, (ref, observed) in enumerate(zip(baseline, trajectory)):
                raw.exact(ref, observed, f'{task}/{scheme}/{index}')
                raw.cpu_coverage(observed, index, 'nut_bolt')
                for key in observed.keys() & baseline[0].keys():
                    if key.endswith('/qpos') and observed[key].numel():
                        motion = max(motion, float((observed[key].double() - baseline[0][key].double()).abs().max()))
            branches[scheme] = {'worker_sha256': record['run_sha256'], 'private_sdk_sha256': record['private_sdk_sha256'],
                'trajectory_sha256': raw.track(path), 'samples': 61, 'max_absolute_error_vs_native': 0}
        require(motion > 0, f'{task}: dynamics exercised no joint motion')
        tasks[task] = {'actions_sha256': action_sha, 'maximum_joint_displacement_rad': motion, 'runs': branches}
    return {'interface': {'schemes_per_task': len(SCHEMES), 'results_sha256': raw.track(interface / 'results.json'),
                            'manifest_sha256': raw.track(interface / 'manifest.json'),
                            'console': verify_cpu_console(root, 'cpu-interface')},
            'dynamics': {'summary_sha256': raw.track(dynamics / 'summary.json'), 'control_steps': count * 60,
                         'physics_steps': count * 1200, 'completed_runs': count, 'tasks': tasks,
                         'console': verify_cpu_console(root, 'cpu-dynamics')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--sdk-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', help='Optional prior Git commit for the preserved-definition and delta audit')
    args = parser.parse_args()
    root, sdk_root, output = args.run.resolve(strict=True), args.sdk_root.resolve(strict=True), args.output.resolve()
    raw.configure(ROOT)
    require(not output.exists(), 'Choose a new evidence directory')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if args.baseline:
        baseline = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options', args.baseline + '^{commit}'],
                                           cwd=ROOT, text=True).strip()
        check_baseline(baseline)
    else:
        baseline = None
    sdk, _, _, public_sdk = raw.sdk_build_identity('nut_bolt', ROOT, sdk_root / 'artifact.json',
                                                    sdk_root / 'recipe-v6/lock.json')
    captures, tasks, source, external, gpu_identity = verify_gpu(root, sdk, commit)
    cpu = verify_cpu(root, sdk, source, external, gpu_identity, captures, commit)
    public_sdk.update(loaded_native=gpu_identity[0], runtime_python=gpu_identity[1], system_vulkan_loader=gpu_identity[2])
    probe_summary = root / 'sdk_probe_checks.json'
    probes = raw.nut_probe_summary(probe_summary, ROOT, public_sdk)
    summary = {'schema': 'nut-bolt-appearance-expansion-evidence-v1', 'status': 'passed',
               'baseline': baseline, 'capture_git_commit': commit,
               'schemes': SCHEMES, 'added_schemes': SCHEMES[3:], 'sdk': public_sdk,
               'witness_min_pixels': MIN_WITNESS_PIXELS, 'witness_min_channel_delta': MIN_WITNESS_CHANNEL_DELTA,
               'source_identity': raw.source_identity(source, ROOT), 'external_identity': raw.external_identity(external),
               'cpu': cpu, 'captures': captures, 'supplementary_sdk': probes,
               'exporter_sha256': raw.track(Path(__file__)), 'shared_verifier_sha256': raw.track(Path(raw.__file__))}
    figures = {'display/PickBolt-variant_4-human.png': ('PickBolt', 'fixed_variant_4_human_env0.png')}
    summary['witness_images'] = {}
    for task in TASKS:
        _, camera = CASES[task]
        paths = {scheme: f'witness/{task}/{scheme}.png' for scheme in SCHEMES}
        figures.update({path: (task, f'fixed_{scheme}_{camera}_env0.png') for scheme, path in paths.items()})
        summary['witness_images'][task] = {'camera': camera, 'env_idx': 0, 'files': paths}
        for direction, selected in enumerate((1, 0)):
            for env in (0, 1):
                figures[f'local/{task}/reset-env{selected}-view-env{env}.png'] = (
                    task, f'local_{direction}_base_camera_env{env}.png')
    for direction in ('forward', 'reverse'):
        for env in (0, 1):
            figures[f'stage/SeatNut-{direction}-env{env}.png'] = (
                'SeatNut', f'stage_visibility_fixture/{direction}_swap_wrist_camera_env{env}.png')
    summary['featured_figures'] = [
        'display/PickBolt-variant_4-human.png', 'witness/SeatNut/variant_6.png', 'witness/TurnNut/variant_10.png',
        'local/PickBolt/reset-env1-view-env0.png', 'local/PickBolt/reset-env0-view-env1.png',
    ]
    payloads = {f'{name}.json': json.dumps(value, indent=2, allow_nan=False).encode() + b'\n'
                for name, value in tasks.items()}
    summary['tasks'] = {name: {'file': name + '.json', 'sha256': hashlib.sha256(payloads[name + '.json']).hexdigest()}
                        for name in tasks}
    summary['figures'] = {}
    for name, (task, image) in figures.items():
        path = root / f'gpu-{task}' / task / image
        raw.pair(path)
        payloads[name] = path.read_bytes()
        summary['figures'][name] = {'source': path.relative_to(root).as_posix(), 'sha256': raw.track(path),
            'layout': 'native | scheme' if name.startswith(('display/', 'witness/')) else 'before | after'}
    payloads['sdk_probe_checks.json'] = probe_summary.read_bytes()
    for path, expected in raw.WATCHED.items():
        require(raw.H.sha(path) == expected, f'Evidence changed while exporting: {path}')
    output.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    raw.H.write(output / 'summary.json', summary)
    print(json.dumps({'status': 'passed', 'tasks': len(tasks), 'images': len(figures),
                      'featured': len(summary['featured_figures']), 'archive': str(output)}))


if __name__ == '__main__':
    main()
