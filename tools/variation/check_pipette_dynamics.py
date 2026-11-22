"""Exact CPU rollouts for two native controls and every catalog scheme."""
import argparse
import copy
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_pipette_runtime import TASKS, asset_closure, closure_unchanged, dump, external_hashes, read, sha, source_hashes as runtime_source_hashes
from check_pipette_runtime import SCHEMES as MATERIAL_SCHEMES

SCHEMES = ('native_off', 'native_repeat', *MATERIAL_SCHEMES)


def source_hashes():
    return runtime_source_hashes(include_probe=False)


def worker(args):
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')
    sys.path.insert(0, str(ROOT))
    import numpy as np
    import torch
    import sapien
    import gymnasium as gym
    from check_furniture_dynamics import numeric_leaves
    from check_pipette_runtime import load_runtime
    shared = load_runtime()
    import tasks
    from mani_skill.utils import download_asset
    def reject_download(*unused_args, **unused_kwargs):
        raise RuntimeError('Asset download disabled during validation')
    download_asset.download = download_asset.download_from_hf_datasets = reject_download
    torch.set_num_threads(1)
    env, start = None, time.monotonic()
    report = {'status': 'running', 'task': args.task, 'scheme': args.scheme, 'seed': args.seed,
              'control_steps': 0, 'physics_steps': 0, 'requested_control_steps': args.steps,
              'source_sha256': source_hashes(), 'image_capture': False,
              'external_sha256': external_hashes(),
              'packages': {name: metadata.version(name) for name in ('sapien', 'mani_skill', 'torch', 'numpy', 'gymnasium')},
              'sapien_binary': {'sha256': sha(sapien.pysapien.__file__)},
              'pipette_rendering': {'enabled': True}}
    def snapshot(obs, info, reward=None, terminated=None, truncated=None):
        return numeric_leaves({'state': base.get_state_dict(),
            'joints': shared.joint_targets(base), 'elapsed_steps': base._elapsed_steps,
            'controller': shared.controller_state(base, 0), 'obs': obs, 'info': info,
            'reward': reward, 'terminated': terminated, 'truncated': truncated})
    try:
        config = {'enabled': False} if args.scheme in ('native_off', 'native_repeat') else {
            'enabled': True, 'scheme_id': args.scheme, 'seed': 71}
        report['appearance_config'] = config
        env = gym.make(f'PipetteTransfer{args.task}-Sharpa-v1', num_envs=1,
            sim_backend='physx_cpu', obs_mode='state', control_mode='pd_joint_pos', reward_mode='dense',
            reconfiguration_freq=0, render_mode=None, pipette_appearance=config,
            pipette_rendering={'enabled': True})
        base = env.unwrapped
        assert not base.gpu_sim_enabled and base.device.type == 'cpu'
        obs, info = env.reset(seed=args.seed, options={'reconfigure': True})
        report['asset_closure_sha256'] = asset_closure(base)
        report['backend'] = str(base.backend)
        report['sim_steps_per_control'] = int(base._sim_steps_per_control)
        report['sim_config'] = repr(base.sim_config)
        report['rendering'] = copy.deepcopy(base._pipette_rendering.identity)
        adapter = base._pipette_appearance
        assert (adapter is None) == (args.scheme in ('native_off', 'native_repeat'))
        initial_materials, physical = shared.materials(base), shared.physical(base)
        if adapter is not None:
            assert adapter.schemes == [args.scheme]
            report['appearance_records'] = copy.deepcopy(adapter.records)
        if args.actions.exists():
            actions = np.load(args.actions, allow_pickle=False)
        else:
            assert args.scheme == 'native_off'
            initial = base.agent.robot.get_qpos().detach().cpu().numpy().reshape(env.action_space.shape)
            initial = np.clip(initial, env.action_space.low, env.action_space.high)
            actions = np.repeat(initial[None], args.steps, axis=0).astype(np.float32)
            channels = np.arange(actions[0].size, dtype=np.float64).reshape(actions[0].shape)
            for index in range(15, min(50, args.steps)):
                actions[index] += .015 * np.sin((index - 15) * .21 + channels * .37)
            actions = np.clip(actions, env.action_space.low, env.action_space.high)
            np.save(args.actions, actions, allow_pickle=False)
        assert actions.shape == (args.steps, *env.action_space.shape)
        assert all(env.action_space.contains(action) for action in actions)
        report['actions'] = {'sha256': sha(args.actions), 'shape': list(actions.shape), 'legal': True,
                             'sequence': '15 initial-position hold, up to 35 sine target offsets, remaining hold'}
        trajectory = [snapshot(obs, info)]
        for action in actions:
            obs, reward, terminated, truncated, info = env.step(torch.from_numpy(action.copy()))
            report['control_steps'] += 1
            report['physics_steps'] += report['sim_steps_per_control']
            trajectory.append(snapshot(obs, info, reward, terminated, truncated))
            assert shared.materials(base) == initial_materials, 'Materials changed during step'
            if adapter is not None:
                assert adapter.schemes == [args.scheme] and adapter.records == report['appearance_records']
        assert physical == shared.physical(base), 'Physical definitions changed during rollout'
        torch.save(trajectory, args.output / 'trajectory.pt')
        report['materials_stable'] = True
        report['final_success'] = shared.plain(info['success'])
        report['source_hashes_unchanged'] = source_hashes() == report['source_sha256']
        report['asset_hashes_unchanged'] = closure_unchanged(report['asset_closure_sha256'])
        report['external_hashes_unchanged'] = external_hashes() == report['external_sha256']
        assert report['source_hashes_unchanged']
        assert report['asset_hashes_unchanged']
        assert report['external_hashes_unchanged']
        report['status'] = 'completed'
    except BaseException:
        report.update(status='failed', traceback=traceback.format_exc())
        raise
    finally:
        report['elapsed_seconds'] = time.monotonic() - start
        dump(args.output / 'run.json', report)
        if env is not None:
            env.close()


def main(args):
    import torch
    from check_furniture_dynamics import compare
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'CPU exact dynamic equivalence; no RGB, GPU or complete robot success claim',
              'source_sha256': source_hashes(), 'tasks': {}, 'failures': [],
              'external_sha256': external_hashes(),
              'seed': args.seed, 'control_steps_per_run': args.steps,
              'planned_control_steps': len(TASKS) * len(SCHEMES) * args.steps,
              'total_control_steps': 0, 'total_physics_steps': 0, 'completed_runs': 0,
              'counts_complete': True, 'unknown_runs': []}
    started = time.monotonic()
    try:
        for task in TASKS:
            folder = args.output / task
            folder.mkdir()
            rows = report['tasks'][task] = {}
            reference = None
            for scheme in SCHEMES:
                branch = folder / scheme
                branch.mkdir()
                extra = ['--worker', '--task', task, '--scheme', scheme, '--steps', str(args.steps),
                         '--seed', str(args.seed), '--actions', str(folder / 'actions.npy')]
                if args.sapien_root:
                    command = [sys.executable, '-B', str(ROOT / 'tools/variation/sapien_sdk/run_task_check.py'),
                        '--repo-root', str(ROOT), '--checker', 'tools/variation/check_pipette_dynamics.py',
                        '--sapien-root', str(args.sapien_root), '--artifact', str(args.artifact),
                        '--physx-gpu-dir', str(args.physx_gpu_dir), '--output', str(branch), *extra]
                else:
                    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--output', str(branch), *extra]
                print(f'{task} {scheme}: starting', flush=True)
                with (branch / 'console.txt').open('w', encoding='utf-8') as console:
                    process = subprocess.run(command, cwd=ROOT, stdout=console, stderr=subprocess.STDOUT, timeout=240)
                run = read(branch / 'run.json')
                report['total_control_steps'] += run['control_steps']
                report['total_physics_steps'] += run['physics_steps']
                rows[scheme] = {'status': run['status'], 'returncode': process.returncode,
                                'run_sha256': sha(branch / 'run.json')}
                assert process.returncode == 0 and run['status'] == 'completed', f'{task}/{scheme} failed'
                assert run['control_steps'] == args.steps
                assert run['physics_steps'] == args.steps * run['sim_steps_per_control']
                assert report['source_sha256'] == run['source_sha256']
                assert report['external_sha256'] == run['external_sha256'] and run['external_hashes_unchanged']
                assert run['asset_hashes_unchanged'] and closure_unchanged(run['asset_closure_sha256'])
                values = torch.load(branch / 'trajectory.pt', map_location='cpu', weights_only=True)
                assert len(values) == args.steps + 1
                if scheme == 'native_off':
                    reference = values
                else:
                    comparison = compare(reference, values)
                    dump(branch / 'comparison.json', comparison)
                    rows[scheme].update(comparison)
                    assert comparison['status'] == 'passed', f'{task}/{scheme} dynamics differ'
                report['completed_runs'] += 1
                dump(args.output / 'summary.json', report)
                print(f'{task} {scheme}: passed', flush=True)
        report['status'] = 'passed'
    except BaseException:
        report['failures'].append({'traceback': traceback.format_exc()})
        report['status'], report['counts_complete'] = 'failed', False
    finally:
        report['source_hashes_unchanged'] = source_hashes() == report['source_sha256']
        report['external_hashes_unchanged'] = external_hashes() == report['external_sha256']
        if not report['source_hashes_unchanged'] or not report['external_hashes_unchanged']:
            report['status'] = 'failed'
        report['elapsed_seconds'] = time.monotonic() - started
        dump(args.output / 'summary.json', report)
    print(json.dumps({'status': report['status'], 'total_control_steps': report['total_control_steps'],
                      'total_physics_steps': report['total_physics_steps']}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=60)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--task', choices=TASKS)
    parser.add_argument('--scheme', choices=SCHEMES)
    parser.add_argument('--actions', type=Path)
    parser.add_argument('--sapien-root', type=Path)
    parser.add_argument('--artifact', type=Path)
    parser.add_argument('--physx-gpu-dir', type=Path)
    args = parser.parse_args()
    if args.steps <= 0:
        parser.error('--steps must be positive')
    if args.sapien_root and (not args.artifact or not args.physx_gpu_dir):
        parser.error('Private SDK requires --artifact and --physx-gpu-dir')
    args.output = args.output.resolve()
    if args.worker:
        worker(args)
    else:
        raise SystemExit(main(args))
