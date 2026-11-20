"""Supplementary original task cameras; each bias/view has a fresh CUDA batch."""
import argparse
import copy
import gc
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_pipette_runtime import (GPU_MEMORY_PROFILES, TASKS, asset_closure, buffer_errors,
    closure_unchanged, dump, external_hashes, load_runtime, native_log, source_hashes)


def probe(*unused_args, **unused_kwargs):
    raise RuntimeError('Use this standalone checker; in-batch camera specialization changes are unsupported')


def capture_case(task, seed, dx, amount, directory, receipt):
    import numpy as np
    import torch
    import gymnasium as gym
    import sapien
    from PIL import Image
    from check_pipette_runtime import shared
    env, base = None, None
    try:
        env = gym.make(f'PipetteTransfer{task}-Sharpa-v1', num_envs=2,
            sim_backend='physx_cuda', reconfiguration_freq=0, obs_mode='state',
            render_mode='rgb_array', pipette_rendering={'enabled': True},
            sim_config={'gpu_memory_config': copy.deepcopy(GPU_MEMORY_PROFILES['two_env'])})
        base = env.unwrapped
        assert base.device.type == 'cuda' and base.gpu_sim_enabled and base.scene._gpu_sim_initialized
        _, info = env.reset(seed=seed)
        assert base.scene.render_system_group is None, 'Batch created before camera configuration'
        cameras = {'base_camera': base._sensors['base_camera'],
                   'human': base.scene.human_render_cameras['render_camera']}
        metadata = {}
        ids = base._pipette_rendering.identity['tip_render_ids']
        for name, sensor in cameras.items():
            assert sensor.camera.camera_group is None
            metadata[name] = []
            for i, camera in enumerate(sensor.camera._render_cameras):
                original = camera.get_local_pose()
                camera.set_local_pose(sapien.Pose(p=np.asarray(original.p) + [dx, 0., 0.], q=original.q))
                camera.set_property('pipetteDepthBias', float(amount))
                metadata[name].append({'env_idx': i, 'tip_render_id': ids[i],
                    'width': camera.width, 'height': camera.height, 'near': camera.near, 'far': camera.far,
                    'intrinsic': np.asarray(camera.get_intrinsic_matrix()).tolist(),
                    'model_matrix': np.asarray(camera.get_model_matrix()).tolist(),
                    'original_pose_p': original.p.tolist(), 'original_pose_q': original.q.tolist(),
                    'pose_p': camera.get_local_pose().p.tolist(), 'pose_q': camera.get_local_pose().q.tolist()})
            for field in ('_cached_local_pose', '_cached_model_matrix', '_cached_extrinsic_matrix'):
                setattr(sensor.camera, field, None)
        before = shared.snapshot(base)
        base.scene.update_render(update_sensors=True, update_human_render_cameras=True)
        frames, devices = {}, {}
        for name, sensor in base._sensors.items():
            sensor.capture()
            rgb = sensor.get_obs(rgb=True, depth=False, position=False, segmentation=False)['rgb']
            assert rgb.is_cuda and rgb.dtype == torch.uint8 and rgb.shape[0] == 2
            devices[name] = {'device': str(rgb.device), 'dtype': str(rgb.dtype), 'shape': list(rgb.shape)}
            frames[name] = rgb.detach().cpu().numpy().copy()
        human = env.render()
        assert human.is_cuda and human.dtype == torch.uint8 and human.shape[0] == 2
        devices['human'] = {'device': str(human.device), 'dtype': str(human.dtype), 'shape': list(human.shape)}
        frames['human'] = human.detach().cpu().numpy().copy()
        shared.validate_images(frames, 2)
        after = shared.snapshot(base)
        assert not shared.state_changes(before, after), 'Capture changed task state'
        torch.save({'before': before, 'after': after}, directory / 'state.pt')
        raw = {}
        for name, sensor in cameras.items():
            raw[name] = []
            for i, camera in enumerate(sensor.camera._render_cameras):
                values = {}
                for key in ('Color', 'Segmentation', 'PositionRaw', 'Position', 'GbufferDepth'):
                    tensor = camera.get_picture_cuda(key).torch()
                    assert tensor.is_cuda
                    values[key] = tensor.detach().clone().cpu().numpy()
                color = values['Color']
                assert color.dtype == np.float32 and np.isfinite(color).all()
                converted = (torch.as_tensor(color[..., :3]) * 255).to(torch.uint8).numpy()
                assert np.array_equal(converted, frames[name][i]), 'Raw/default conversion differs from standard RGB'
                metadata[name][i].update(raw_color_dtype=str(color.dtype), raw_color_shape=list(color.shape),
                    raw_color_rgb_min_max=[float(color[..., :3].min()), float(color[..., :3].max())])
                np.savez_compressed(directory / f'{name}_env{i}_attachments.npz', **values)
                Image.fromarray(frames[name][i]).save(directory / f'{name}_env{i}.png')
                raw[name].append(values)
        caps = []
        for i, actor in enumerate(base.pipette_stand._objs):
            body = actor.find_component_by_type(sapien.render.RenderBodyComponent)
            disk = body.render_shapes[4]
            pose = base.pipette_stand.pose.p[i].detach().cpu().numpy()
            caps.append({'center': [float(pose[0]), float(pose[1]), float(pose[2] + disk.local_pose.p[2] + disk.half_length)],
                         'radius': float(disk.radius)})
        receipt.update(status='passed', seed=seed, translation_x_m=dx, bias_ndc=amount,
            cameras=metadata, standard_rgb=devices, rendering=copy.deepcopy(base._pipette_rendering.identity),
            resolved_sim_config=shared.plain(base.sim_config.dict()), caps=caps,
            asset_closure_sha256=asset_closure(base), control_steps=0, physics_steps=0,
            state_evidence='state.pt', capture_path='Original ManiSkill CUDA RGB/human rgb_array and supplementary native CUDA attachments')
        dump(directory / 'capture.json', receipt)
        return {'frames': frames, 'raw': raw, 'state': before, 'receipt': receipt}
    finally:
        if env is not None:
            env.close()
        env, base = None, None
        gc.collect()
        torch.cuda.empty_cache()


def compare_pair(before, after, output, seed, view):
    import numpy as np
    from PIL import Image
    from check_pipette_runtime import shared
    assert not shared.state_changes(before['state'], after['state']), 'Bias-pair task states differ'
    bias = after['receipt']['bias_ndc']
    rows = []
    for name in ('base_camera', 'human'):
        for env_id in (0, 1):
            old, new = before['raw'][name][env_id], after['raw'][name][env_id]
            meta = after['receipt']['cameras'][name][env_id]
            tip_id = meta['tip_render_id']
            assert tip_id == before['receipt']['cameras'][name][env_id]['tip_render_id']
            first, second = old['Segmentation'][..., 0] == tip_id, new['Segmentation'][..., 0] == tip_id
            common, outside = first & second, ~(first | second)
            rgb, other = before['frames'][name][env_id], after['frames'][name][env_id]
            row = {'seed': seed, 'view': view, 'camera': name, 'env_idx': env_id,
                   'translation_x_m': after['receipt']['translation_x_m'], 'tip_render_id': tip_id,
                   'native_tip_pixels': int(first.sum()), 'fixed_tip_pixels': int(second.sum()),
                   'common_tip_pixels': int(common.sum()),
                   'rgb_changed_values_outside_tip_union': int(np.count_nonzero(rgb[outside] != other[outside])),
                   'depth_changed_values_outside_tip_union': int(np.count_nonzero(old['GbufferDepth'][outside] != new['GbufferDepth'][outside]))}
            assert outside.any()
            assert row['rgb_changed_values_outside_tip_union'] == row['depth_changed_values_outside_tip_union'] == 0
            if common.any():
                delta = new['GbufferDepth'][common] - old['GbufferDepth'][common]
                pos_w = new['Position'][common, 3] - old['Position'][common, 3]
                row.update(position_xyz_max_abs_delta_common_tip=float(np.max(np.abs(new['Position'][common, :3] - old['Position'][common, :3]))),
                    position_raw_max_abs_delta_common_tip=float(np.max(np.abs(new['PositionRaw'][common] - old['PositionRaw'][common]))),
                    depth_delta_common_tip_min_max=[float(delta.min()), float(delta.max())],
                    position_w_delta_common_tip_min_max=[float(pos_w.min()), float(pos_w.max())])
                assert row['position_xyz_max_abs_delta_common_tip'] == row['position_raw_max_abs_delta_common_tip'] == 0
                assert np.max(np.abs(delta + bias)) < 1e-7
                assert np.max(np.abs(pos_w - delta.reshape(pos_w.shape))) < 1e-7
            else:
                row['visibility_limit'] = 'No common tip pixel in this original task camera view'
            world = new['PositionRaw'] @ np.asarray(meta['model_matrix']).T
            cap = after['receipt']['caps'][env_id]
            center = cap['center']
            interior = ((world[..., 0] - center[0]) ** 2 + (world[..., 1] - center[1]) ** 2 < (cap['radius'] - .005) ** 2)
            interior &= np.abs(world[..., 2] - center[2]) < 2e-6
            row['fixed_cap_interior_visible_pixels'] = int(interior.sum())
            row['fixed_cap_interior_missing_pixels'] = int((interior & ~second).sum())
            assert not row['fixed_cap_interior_missing_pixels']
            Image.fromarray(np.concatenate([rgb, other], axis=1)).save(output / f'{name}_env{env_id}_comparison.png')
            rows.append(row)
    dump(output / 'comparison.json', {'status': 'passed', 'rows': rows})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-runtime', action='store_true')
    parser.add_argument('--sim-backend', choices=('physx_cuda',), default='physx_cuda')
    parser.add_argument('--experimental-windows-cuda', action='store_true')
    parser.add_argument('--gpu-memory-profile', choices=('two_env',), default='two_env')
    parser.add_argument('--physx-gpu-dir', type=Path)
    parser.add_argument('--task', choices=TASKS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.approved_runtime:
        parser.error('Supplementary runtime needs explicit intent and a separate renderer window')
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {'status': 'running', 'task': args.task, 'formal_acceptance': 'NOT TESTED: supplementary rendering only',
              'scope': 'Two task layout seeds, seven millimeter translations, two independent pre-batch bias cases',
              'control_steps': 0, 'physics_steps': 0, 'completed_constructions': 0, 'cases': [], 'comparisons': []}
    files, external = source_hashes(include_probe=True), None
    try:
        load_runtime()
        import sapien
        assert sapien.physx.indexed_gpu_apply_patch_version() == 1
        if not sapien.physx.is_gpu_enabled():
            sapien.physx._enable_gpu()
        import tasks
        from mani_skill.utils import download_asset
        def reject_download(*unused_args, **unused_kwargs):
            raise RuntimeError('Asset download disabled during supplementary validation')
        download_asset.download = download_asset.download_from_hf_datasets = reject_download
        external = external_hashes()
        dump(args.output / 'manifest.json', {'files': files, 'external_files': external,
            'task_id': f'PipetteTransfer{args.task}-Sharpa-v1', 'sim_backend': 'physx_cuda', 'num_envs': 2,
            'gpu_memory_profile': 'two_env', 'control_steps': 0, 'physics_steps': 0, 'command': sys.argv,
            'camera_configuration_timing': 'Before each fresh batch; no in-batch specialization or pose updates'})
        for seed in (7, 19):
            for view, dx in enumerate((-.002, -.001, 0., .001, .002, -.004, .004)):
                folder = args.output / f'seed{seed}_view{view}'
                folder.mkdir()
                pair = []
                for label in ('native_depth', 'fixed_depth'):
                    directory = folder / label
                    directory.mkdir()
                    receipt = {'status': 'running', 'seed': seed, 'view': view, 'label': label}
                    report['cases'].append(receipt)
                    amount = 0. if label == 'native_depth' else pair[0]['receipt']['rendering']['bias_ndc']
                    with native_log(directory / 'native.log'):
                        captured = capture_case(args.task, seed, dx, amount, directory, receipt)
                    receipt['native_buffer_errors'] = buffer_errors(directory / 'native.log')
                    assert not receipt['native_buffer_errors']
                    report['completed_constructions'] += 1
                    pair.append(captured)
                report['comparisons'].extend(compare_pair(*pair, folder, seed, view))
                dump(args.output / 'results.json', report)
                print(f'{args.task}: seed {seed}, view {view} passed', flush=True)
                pair = None
                gc.collect()
        assert report['completed_constructions'] == 28
        assert all(any(row['common_tip_pixels'] for row in report['comparisons']
                       if row['camera'] == camera and row['env_idx'] == env)
                   for camera in ('base_camera', 'human') for env in (0, 1))
        report['status'] = 'passed'
    except BaseException:
        report.update(status='failed', error=traceback.format_exc())
    finally:
        report['source_hashes_unchanged'] = files == source_hashes(include_probe=True)
        report['external_hashes_unchanged'] = external is not None and external == external_hashes()
        report['asset_hashes_unchanged'] = all(closure_unchanged(case['asset_closure_sha256'])
            for case in report['cases'] if case.get('asset_closure_sha256'))
        if not all(report[key] for key in ('source_hashes_unchanged', 'external_hashes_unchanged', 'asset_hashes_unchanged')):
            report['status'] = 'failed'
        report['elapsed_seconds'] = time.monotonic() - started
        dump(args.output / 'results.json', report)
        print({key: report[key] for key in ('status', 'task', 'completed_constructions', 'control_steps', 'physics_steps')})
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
