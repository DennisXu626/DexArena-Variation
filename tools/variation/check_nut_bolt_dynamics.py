"""Compare three short tasks over identical CPU action sequences."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TASKS = ('PickBolt', 'SeatNut', 'TurnNut')
SCHEMES = ('native_off', 'native_repeat', 'original', 'variant_1', 'variant_2')
BOOKKEEPING = ('_success_hold_count', '_success_last_eval_step', '_bolt_place_hold_count',
    '_bolt_place_last_eval_step', '_stage_bolt_placed', '_stage_nut_placed', '_stage_turned',
    '_nut_engaged', '_nut_engage_hold_count', '_nut_engage_last_eval_step', '_task_phase',
    '_bolt_locked', '_bolt_lock_pose', '_cum_rotation', '_threaded_depth', '_nut_yaw_prev',
    '_nut_aligned', '_nut_aligned_exit_streak', '_nut_vis_state')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def worker(args):
    import numpy as np
    import torch
    import gymnasium as gym
    import sapien
    import tasks
    from tools.variation.check_furniture_dynamics import numeric_leaves
    from tools.variation.check_nut_bolt_runtime import source_hashes, sha, helpers, sdk_identity, external_hashes
    common = helpers()
    torch.set_num_threads(1)
    env = None
    report = {'status': 'running', 'task': args.task, 'scheme': args.scheme,
        'seed': args.seed, 'requested_control_steps': args.steps, 'control_steps': 0,
        'physics_steps': 0, 'source_sha256': source_hashes(), 'image_capture': False,
        'sapien_binary': {'path': sapien.pysapien.__file__, 'sha256': sha(sapien.pysapien.__file__)},
        'sdk_native_before': sdk_identity(sapien), 'external_sha256': external_hashes()}
    try:
        config = {'enabled': False} if args.scheme.startswith('native_') else {
            'enabled': True, 'scheme_id': args.scheme, 'seed': 71}
        env = gym.make(f'NutBolt{args.task}-Sharpa-v1', num_envs=1, sim_backend='physx_cpu',
            obs_mode='state', control_mode='pd_joint_pos', reward_mode='sparse',
            render_mode=None, reconfiguration_freq=0, nut_bolt_appearance=config)
        base = env.unwrapped
        assert base.device.type == 'cpu' and not base.gpu_sim_enabled
        obs, info = env.reset(seed=args.seed, options={'reconfigure': True})
        if base.has_nut:
            generated = ROOT / 'tasks/assets/task_object_meshes/screwing/threaded_nut_revolute.urdf'
            report['generated_urdf'] = {'path': generated.relative_to(ROOT).as_posix(), 'sha256': sha(generated)}
        report['sim_steps_per_control'] = base._sim_steps_per_control
        report['constructor_kwargs'] = {'nut_bolt_appearance': config, 'sim_backend': 'physx_cpu', 'num_envs': 1}
        native_materials = common.materials(base)
        appearance = base._nut_bolt_appearance
        records = None if appearance is None else list(appearance.records)
        if args.actions.is_file():
            actions = np.load(args.actions, allow_pickle=False)
        else:
            assert args.scheme == 'native_off'
            initial = np.clip(base.agent.robot.get_qpos().detach().cpu().numpy().reshape(env.action_space.shape),
                              env.action_space.low, env.action_space.high)
            actions = np.repeat(initial[None], args.steps, axis=0).astype(np.float32)
            channels = np.arange(initial.size).reshape(initial.shape)
            for step in range(15, min(50, args.steps)):
                actions[step] += .015 * np.sin((step - 15) * .21 + channels * .37)
            actions = np.clip(actions, env.action_space.low, env.action_space.high)
            np.save(args.actions, actions, allow_pickle=False)
        assert actions.shape == (args.steps, *env.action_space.shape)
        assert all(env.action_space.contains(action) for action in actions)
        report['actions'] = {'sha256': sha(args.actions), 'shape': list(actions.shape), 'legal': True,
            'sequence': '15 initial-position holds, 35 small sine target offsets, remaining holds'}
        def snapshot(obs, info, reward=None, terminated=None, truncated=None):
            return numeric_leaves({'state': base.get_state_dict(), 'joint': common.joint_targets(base),
                'controller': common.controller_state(base, 0),
                'bookkeeping': {name: getattr(base, name) for name in BOOKKEEPING if hasattr(base, name)},
                'elapsed_steps': base._elapsed_steps, 'obs': obs, 'info': info,
                'reward': reward, 'terminated': terminated, 'truncated': truncated})
        trajectory = [snapshot(obs, info)]
        for action in actions:
            obs, reward, terminated, truncated, info = env.step(torch.from_numpy(action.copy()))
            report['control_steps'] += 1
            report['physics_steps'] += base._sim_steps_per_control
            trajectory.append(snapshot(obs, info, reward, terminated, truncated))
            assert common.materials(base) == native_materials, 'Material drift during dynamics'
            if appearance is not None:
                assert appearance.records == records and appearance.schemes == [args.scheme]
        torch.save(trajectory, args.output / 'trajectory.pt')
        assert source_hashes() == report['source_sha256']
        report['external_hashes_unchanged'] = external_hashes() == report['external_sha256']
        assert report['external_hashes_unchanged']
        if 'generated_urdf' in report:
            assert sha(ROOT / report['generated_urdf']['path']) == report['generated_urdf']['sha256']
        report['sdk_native_after'] = sdk_identity(sapien)
        assert report['sdk_native_before'] == report['sdk_native_after']
        report['status'] = 'completed'
    except BaseException:
        report.update(status='failed', traceback=traceback.format_exc())
        raise
    finally:
        dump(args.output / 'run.json', report)
        if env is not None:
            env.close()


def main(args):
    import torch
    from tools.variation.check_nut_bolt_runtime import external_hashes, sha, source_hashes
    from tools.variation.check_furniture_dynamics import compare
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'scope': 'CPU dynamic equivalence; no RGB, GPU, Long or full task success',
        'tasks': {}, 'seed': args.seed, 'control_steps_per_run': args.steps,
        'planned_control_steps': len(TASKS) * len(SCHEMES) * args.steps,
        'total_control_steps': 0, 'total_physics_steps': 0, 'completed_runs': 0,
        'source_sha256': source_hashes(), 'external_sha256': external_hashes(), 'failures': []}
    child_env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    artifact_sha256 = args.artifact_sha256 or sha(args.artifact)
    launcher = [sys.executable, '-B', str(ROOT / 'tools/variation/sapien_sdk/native_lock/tools/run_task_check.py'),
        '--repo-root', str(ROOT), '--checker', Path(__file__).resolve().relative_to(ROOT).as_posix(),
        '--sapien-root', str(args.sapien_root), '--artifact', str(args.artifact),
        '--artifact-sha256', artifact_sha256, '--physx-gpu-dir', str(args.physx_gpu_dir)]
    for flag, value in (('--sdk-provenance-root', args.sdk_provenance_root), ('--sdk-base-root', args.sdk_base_root)):
        if value is not None:
            launcher.extend((flag, str(value)))
    try:
        for task in TASKS:
            directory = args.output / task; directory.mkdir()
            rows = report['tasks'][task] = {}
            reference = None
            for scheme in SCHEMES:
                branch = directory / scheme; branch.mkdir()
                command = [*launcher, '--approved-runtime', '--worker', '--task', task,
                    '--scheme', scheme, '--steps', str(args.steps), '--seed', str(args.seed),
                    '--output', str(branch), '--actions', str(directory / 'actions.npy')]
                print(f'{task} {scheme}: starting', flush=True)
                with (branch / 'console.txt').open('w') as log:
                    process = subprocess.run(command, cwd=ROOT, env=child_env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
                assert process.returncode == 0, f'{task}/{scheme} failed (see {branch / "console.txt"})'
                run = json.loads((branch / 'run.json').read_text())
                sdk_receipt = branch / 'private_sdk.json'
                sdk = json.loads(sdk_receipt.read_text(encoding='utf-8'))
                assert sdk['artifact_sha256'] == artifact_sha256 and sdk['private_sdk'] is True
                assert sdk['before'] == sdk['after'] and sdk['binaries_unchanged'] is True
                assert sdk['python_before'] == sdk['python_after'] and sdk['python_source_unchanged'] is True
                vulkan = sdk['system_vulkan_loader']
                assert vulkan['before'] == vulkan['after'] and vulkan['unchanged'] is True
                rows[scheme] = {'run': str((branch / 'run.json').relative_to(args.output)),
                    'returncode': process.returncode, 'status': run['status'],
                    'run_sha256': sha(branch / 'run.json'), 'private_sdk_sha256': sha(sdk_receipt)}
                report['total_control_steps'] += run['control_steps']
                report['total_physics_steps'] += run['physics_steps']
                assert run['status'] == 'completed' and run['external_sha256'] == report['external_sha256'], branch
                assert run['control_steps'] == args.steps and run['source_sha256'] == report['source_sha256']
                trajectory = torch.load(branch / 'trajectory.pt', map_location='cpu', weights_only=True)
                assert len(trajectory) == args.steps + 1
                report['completed_runs'] += 1
                if scheme == 'native_off':
                    reference = trajectory
                else:
                    comparison = compare(reference, trajectory)
                    dump(branch / 'comparison.json', comparison)
                    rows[scheme].update({key: comparison[key] for key in ('status', 'initial_state_equal', 'worst_difference')})
                    assert comparison['status'] == 'passed', branch
                dump(args.output / 'summary.json', report)
                print(f'{task} {scheme}: passed', flush=True)
        report['status'] = 'passed'
    except BaseException:
        report.update(status='failed', error=traceback.format_exc())
        report['failures'].append(report['error'])
    finally:
        report['source_hashes_unchanged'] = source_hashes() == report['source_sha256']
        report['external_hashes_unchanged'] = external_hashes() == report['external_sha256']
        if not report['source_hashes_unchanged'] or not report['external_hashes_unchanged']:
            report['status'] = 'failed'
        dump(args.output / 'summary.json', report)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-runtime', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sapien-root', type=Path)
    parser.add_argument('--artifact', type=Path)
    parser.add_argument('--artifact-sha256')
    parser.add_argument('--physx-gpu-dir', type=Path)
    parser.add_argument('--sdk-provenance-root', type=Path)
    parser.add_argument('--sdk-base-root', type=Path)
    parser.add_argument('--steps', type=int, default=60)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--task', choices=TASKS)
    parser.add_argument('--scheme', choices=SCHEMES)
    parser.add_argument('--actions', type=Path)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.steps <= 0:
        parser.error('--steps must be positive')
    if args.worker:
        if not all((args.task, args.scheme, args.actions)):
            parser.error('Worker requires --task, --scheme and --actions')
        worker(args)
    else:
        for option in ('sapien_root', 'artifact', 'physx_gpu_dir', 'sdk_provenance_root', 'sdk_base_root'):
            path = getattr(args, option)
            if path is not None:
                setattr(args, option, path.resolve(strict=True))
            elif option in ('sapien_root', 'artifact', 'physx_gpu_dir'):
                parser.error('Formal CPU dynamics require --sapien-root, --artifact and --physx-gpu-dir')
        sys.exit(main(args))
