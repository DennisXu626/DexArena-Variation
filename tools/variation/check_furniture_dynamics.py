"""Compare Furniture Assembly CPU dynamics across fixed appearance schemes."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
TASKS = ('LayFlatPanel', 'InsertRail', 'FastenScrew')
SCHEMES = ('native_off', 'original', 'variant_1', 'variant_2')
COMMON = dict(num_envs=1, sim_backend='physx_cpu', obs_mode='state',
              control_mode='pd_joint_pos', reward_mode='dense',
              reconfiguration_freq=0, render_mode=None)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('steps must be a positive integer')
    return number


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def source_hashes():
    files = sorted((ROOT / 'tasks/furniture_assembly').glob('*.py'))
    files += sorted((ROOT / 'tasks/robots').glob('*.py'))
    files += [ROOT / 'tasks/config/task_state.py',
              ROOT / 'tasks/assets/variation/furniture_assembly/v1/catalog.json', Path(__file__).resolve()]
    files += sorted((ROOT / 'assets/appearance/objects/furniture_assembly').glob('*/variants/v1/catalog.json'))
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in files}


def numeric_leaves(value, path=''):
    import numpy as np
    import torch
    if isinstance(value, dict):
        return {p: v for key, child in value.items()
                for p, v in numeric_leaves(child, path + '/' + str(key)).items()}
    if isinstance(value, (torch.Tensor, np.ndarray, np.generic, int, float, bool)):
        return {path: torch.as_tensor(value).detach().cpu().clone()}
    if isinstance(value, (list, tuple)):
        return {p: v for i, child in enumerate(value)
                for p, v in numeric_leaves(child, path + '/' + str(i)).items()}
    if value is None or isinstance(value, str):
        return {}
    raise TypeError(f'Unsupported numeric snapshot value at {path}: {type(value)}')


def snapshot(base, obs, info, reward=None, terminated=None, truncated=None):
    arts = base.scene.articulations
    return numeric_leaves({
        'state': base.get_state_dict(),
        'joint': {name: {'qpos': art.get_qpos(), 'qvel': art.get_qvel(),
                         'qf': art.get_qf(), 'position_target': art.get_drive_targets(),
                         'velocity_target': art.get_drive_velocities()}
                  for name, art in arts.items()},
        'bookkeeping': {field.name: getattr(base, field.name) for field in base.TASK_STATE_FIELDS},
        'elapsed_steps': base._elapsed_steps, 'obs': obs, 'info': info,
        'reward': reward, 'terminated': terminated, 'truncated': truncated,
    })


def worker(args):
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    import numpy as np
    import torch
    import gymnasium as gym
    import sapien
    import tasks
    torch.set_num_threads(1)
    output, env, start = args.output, None, time.perf_counter()
    report = {'status': 'running', 'task': args.task, 'scheme': args.scheme,
              'seed': args.seed, 'constructor_kwargs': COMMON,
              'reset_options': {'reconfigure': True}, 'requested_control_steps': args.steps,
              'source_sha256': source_hashes(), 'python': sys.version,
              'executable': sys.executable, 'platform': platform.platform(),
              'packages': {name: metadata.version(name) for name in ('sapien', 'mani_skill', 'torch', 'numpy', 'gymnasium')},
              'sapien_binary': {'path': sapien.pysapien.__file__, 'sha256': digest(sapien.pysapien.__file__)},
              'control_steps': 0, 'physics_steps': 0, 'image_capture': False}
    try:
        config = {'enabled': False} if args.scheme == 'native_off' else {
            'enabled': True, 'mode': 'explicit', 'scheme_id': args.scheme, 'seed': 71}
        report['appearance_config'] = config
        env = gym.make(f'FurnitureAssembly{args.task}-Sharpa-v1', furniture_appearance=config, **COMMON)
        base = env.unwrapped
        assert not base.gpu_sim_enabled and base.device.type == 'cpu'
        obs, info = env.reset(seed=args.seed, options={'reconfigure': True})
        report['backend'] = str(base.backend)
        report['sim_steps_per_control'] = int(base._sim_steps_per_control)
        report['panel_color_jitter'] = getattr(base, 'panel_color_jitter', 'not applicable')
        report['sim_config'] = repr(base.sim_config)
        adapter = base._furniture_appearance
        assert (adapter is None) == (args.scheme == 'native_off')
        if adapter is not None:
            assert adapter.schemes == [args.scheme]
            report['appearance_records'] = adapter.records
        if args.actions.exists():
            actions = np.load(args.actions, allow_pickle=False)
        else:
            assert args.scheme == 'native_off'
            # Hold, small fixed target offsets, then hold; saved before the first step.
            initial = base.agent.robot.get_qpos().detach().cpu().numpy().reshape(env.action_space.shape)
            initial = np.clip(initial, env.action_space.low, env.action_space.high)
            actions = np.repeat(initial[None], args.steps, axis=0).astype(np.float32)
            channels = np.arange(actions[0].size, dtype=np.float64).reshape(actions[0].shape)
            for step in range(15, min(50, args.steps)):
                actions[step] += .015 * np.sin((step - 15) * .21 + channels * .37)
            actions = np.clip(actions, env.action_space.low, env.action_space.high)
            np.save(args.actions, actions, allow_pickle=False)
        assert actions.shape == (args.steps, *env.action_space.shape)
        assert all(env.action_space.contains(action) for action in actions)
        report['actions'] = {'path': str(args.actions), 'sha256': digest(args.actions),
                             'shape': list(actions.shape), 'space': repr(env.action_space),
                             'sequence': f'{min(args.steps, 15)} initial-position hold + '
                                         f'{max(0, min(args.steps, 50) - 15)} sine target offsets + '
                                         f'{max(0, args.steps - 50)} hold', 'legal': True}
        trajectory = [snapshot(base, obs, info)]
        for action in actions:
            obs, reward, terminated, truncated, info = env.step(torch.from_numpy(action.copy()))
            report['control_steps'] += 1
            report['physics_steps'] += report['sim_steps_per_control']
            trajectory.append(snapshot(base, obs, info, reward, terminated, truncated))
        torch.save(trajectory, output / 'trajectory.pt')
        assert report['source_sha256'] == source_hashes(), 'Sources changed during rollout'
        report['status'] = 'completed'
    except BaseException:
        report['status'], report['traceback'] = 'failed', traceback.format_exc()
        raise
    finally:
        report['elapsed_seconds'] = time.perf_counter() - start
        dump(output / 'run.json', report)
        if env is not None:
            env.close()


def compare(reference, candidate):
    import torch
    failures, worst = [], {'max_absolute_error': 0., 'step': None, 'path': None}
    for step, (left, right) in enumerate(zip(reference, candidate)):
        assert left.keys() == right.keys(), (step, left.keys() ^ right.keys())
        changes = []
        for path, expected in left.items():
            actual = right[path]
            assert expected.shape == actual.shape and expected.dtype == actual.dtype, (step, path)
            assert torch.isfinite(expected).all() and torch.isfinite(actual).all(), (step, path, 'nonfinite')
            if torch.equal(expected, actual):
                continue
            error = (actual.double() - expected.double()).abs()
            flat = int(error.reshape(-1).argmax())
            row = {'path': path, 'max_absolute_error': float(error.max()),
                   'changed_elements': int((expected != actual).sum()),
                   'flat_worst_index': flat, 'native': expected.reshape(-1)[flat].item(),
                   'candidate': actual.reshape(-1)[flat].item()}
            changes.append(row)
            if row['max_absolute_error'] > worst['max_absolute_error']:
                worst = {**row, 'step': step}
        if changes:
            failures.append({'step': step, 'changes': changes})
    assert len(reference) == len(candidate)
    return {'status': 'passed' if not failures else 'failed', 'comparison': 'exact equality; no tolerance',
            'samples': len(reference), 'initial_state_equal': not failures or failures[0]['step'] != 0,
            'worst_difference': worst, 'failed_steps': failures}


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'git_head': None, 'source_sha256': None, 'seed': args.seed, 'control_steps_per_run': args.steps,
              'planned_control_steps': len(TASKS) * len(SCHEMES) * args.steps,
              'total_control_steps': 0, 'total_physics_steps': 0,
              'counts_complete': True, 'unknown_runs': [], 'completed_runs': 0,
              'step_count_scope': 'Confirmed run reports; unknown runs are excluded from totals',
              'scope': 'CPU dynamic equivalence only; not GPU, RGB, or task-completion acceptance',
              'tasks': {}, 'failures': []}
    task = scheme = None
    stage, counted = 'initialize', True

    def reject_json_constant(value):
        raise ValueError(f'Invalid run.json numeric constant: {value}')

    try:
        import torch
        report['git_head'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report['source_sha256'] = source_hashes()
        dump(args.output / 'summary.json', report)
        for task in TASKS:
            stage = 'prepare_task'
            task_output = args.output / task
            task_output.mkdir()
            task_report = report['tasks'][task] = {}
            reference = None
            for scheme in SCHEMES:
                stage, counted = 'prepare_run', True
                branch = task_output / scheme
                branch.mkdir()
                task_report[scheme] = {'run': str((branch / 'run.json').relative_to(args.output)), 'status': 'running'}
                command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', '--task', task,
                           '--scheme', scheme, '--steps', str(args.steps), '--seed', str(args.seed),
                           '--output', str(branch), '--actions', str(task_output / 'actions.npy')]
                print(f'{task} {scheme}: starting', flush=True)
                stage, counted = 'launch_worker', False
                with (branch / 'console.txt').open('w', encoding='utf-8') as log:
                    process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                task_report[scheme]['returncode'] = process.returncode
                stage = 'read_run'
                result = json.loads((branch / 'run.json').read_text(encoding='utf-8'), parse_constant=reject_json_constant)
                stage = 'validate_run'
                if not isinstance(result, dict):
                    raise ValueError('Invalid run.json: expected an object')
                for field in ('control_steps', 'physics_steps'):
                    if type(result.get(field)) is not int or result[field] < 0:
                        raise ValueError(f'Invalid run.json {field}: expected a nonnegative integer')
                if result['control_steps'] > args.steps:
                    raise ValueError('Invalid run.json: control_steps exceeds requested steps')
                if result.get('status') not in ('completed', 'failed'):
                    raise ValueError('Invalid run.json status')
                if result.get('sim_steps_per_control') is not None:
                    ratio = result['sim_steps_per_control']
                    if type(ratio) is not int or ratio <= 0 or result['physics_steps'] != result['control_steps'] * ratio:
                        raise ValueError('Invalid run.json physics step count')
                elif result['control_steps'] or result['physics_steps'] or result['status'] == 'completed':
                    raise ValueError('Invalid run.json: missing sim_steps_per_control')
                report['total_control_steps'] += result['control_steps']
                report['total_physics_steps'] += result['physics_steps']
                counted = True
                task_report[scheme].update(status=result['status'])
                if process.returncode or result['status'] != 'completed':
                    report['counts_complete'] = False
                    report['unknown_runs'].append({'task': task, 'scheme': scheme, 'stage': 'worker_failed'})
                    task_report[scheme]['worker_traceback'] = result.get('traceback')
                    raise RuntimeError(f'Worker failed: exit {process.returncode}; see {branch / "console.txt"}')
                if result['control_steps'] != args.steps:
                    raise ValueError('Completed worker did not execute all requested control steps')
                report['completed_runs'] += 1
                stage = 'verify_source'
                assert result['source_sha256'] == report['source_sha256'], 'Sources changed between workers'
                stage = 'load_trajectory'
                trajectory = torch.load(branch / 'trajectory.pt', map_location='cpu', weights_only=True)
                assert len(trajectory) == result['control_steps'] + 1, 'Trajectory sample count differs from run.json'
                if scheme == 'native_off':
                    reference = trajectory
                else:
                    stage = 'compare'
                    comparison = compare(reference, trajectory)
                    dump(branch / 'comparison.json', comparison)
                    task_report[scheme].update({key: comparison[key] for key in ('status', 'initial_state_equal', 'worst_difference')})
                    if comparison['status'] != 'passed':
                        report['failures'].append({'task': task, 'scheme': scheme, 'stage': stage, 'kind': 'state difference'})
                dump(args.output / 'summary.json', report)
                print(f'{task} {scheme}: {task_report[scheme]["status"]}', flush=True)
        assert report['completed_runs'] == len(TASKS) * len(SCHEMES), 'Not all requested runs completed'
    except BaseException:
        failure = {'task': task, 'scheme': scheme, 'stage': stage, 'traceback': traceback.format_exc()}
        report['failures'].append(failure)
        if task in report['tasks'] and scheme in report['tasks'][task]:
            report['tasks'][task][scheme]['status'] = 'failed'
        if not counted:
            report['counts_complete'] = False
            report['unknown_runs'].append({'task': task, 'scheme': scheme, 'stage': stage})
    finally:
        try:
            report['source_hashes_unchanged'] = report['source_sha256'] == source_hashes()
            if report['source_sha256'] is not None and not report['source_hashes_unchanged']:
                raise RuntimeError('Sources changed during the diagnostic')
        except BaseException:
            report['source_hashes_unchanged'] = False
            report['failures'].append({'task': task, 'scheme': scheme, 'stage': 'final_source_check',
                                       'traceback': traceback.format_exc()})
        report['status'] = 'failed' if report['failures'] else 'passed'
        dump(args.output / 'summary.json', report)
    print(f'{report["status"]}: {args.output / "summary.json"}', flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--steps', type=positive_int, default=60)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--task', choices=TASKS)
    parser.add_argument('--scheme', choices=SCHEMES)
    parser.add_argument('--actions', type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.worker:
        worker(args)
    else:
        raise SystemExit(main(args))
