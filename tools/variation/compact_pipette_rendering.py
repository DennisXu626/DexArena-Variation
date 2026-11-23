"""Recompute small supplementary receipts from real task-camera PNG/NPZ/PT captures."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def exact(left, right):
    import torch
    require(left.keys() == right.keys(), 'State fields differ')
    for key, value in left.items():
        require(torch.is_tensor(value) and value.dtype == right[key].dtype
                and value.shape == right[key].shape and torch.equal(value, right[key]), 'State differs: ' + key)


def sdk_check(path, artifact):
    report = read(path)
    require(report['private_sdk'] is True and report['binaries_unchanged'] is True
            and report['indexed_gpu_apply_patch_version'] == 1
            and report['artifact_sha256'] == sha(artifact), 'SDK receipt mismatch')
    require(report['before'] == report['after'], 'Loaded SDK identity changed')
    binaries = {}
    for name, row in report['before'].items():
        require(sha(row['path']) == row['sha256'], 'Loaded binary differs: ' + name)
        binaries[name] = row['sha256']
    receipt = read(artifact)
    require(report['version'] == receipt['version'], 'SDK version differs')
    core = {'sapien.dll', 'simsense.dll', 'svulkan2.dll'}
    bindings = [name for name in binaries if name.endswith('.pyd')]
    require(core <= set(binaries) and len(bindings) == 1, 'Loaded SDK core/binding coverage is incomplete')
    require(all(binaries[name] == receipt['native_files'][name] for name in core | set(bindings)), 'SDK native/wheel mismatch')
    private = Path(report['before'][bindings[0]]['path']).parent
    require(all(sha(private / name) == value for name, value in receipt['native_files'].items()), 'SDK artifact native file changed')
    python_files = {path.relative_to(private.parent).as_posix(): sha(path)
                    for path in sorted(private.rglob('*.py'))}
    require(python_files and report.get('python_source_unchanged') is True
            and report.get('python_before') == python_files == report.get('python_after'),
            'Private SDK Python identity is missing, incomplete or changed')
    loader = report['system_vulkan_loader']
    loader_before = loader['before']
    loader_path = Path(loader_before['path']).resolve(strict=True)
    require(loader['unchanged'] is True and loader_before == loader['after']
            and loader_path.name.lower() == 'vulkan-1.dll' and sha(loader_path) == loader_before['sha256'],
            'Loaded system Vulkan loader identity differs')
    return {'artifact_sha256': sha(artifact), 'version': report['version'],
            'wheel_sha256': receipt['wheel_sha256'], 'loaded_native_binary_sha256': binaries,
            'artifact_native_sha256': receipt['native_files'],
            'python_source_sha256': python_files,
            'system_vulkan_loader_sha256': loader_before['sha256'],
            'indexed_gpu_apply_patch_version': 1}


def recorded_identity(manifest):
    for name, expected in manifest['files'].items():
        path = (ROOT / name).resolve(strict=True)
        require(path.is_relative_to(ROOT.resolve()) and sha(path) == expected, 'Source input changed: ' + name)
    package = Path(metadata.distribution('mani_skill').locate_file('mani_skill')).resolve()
    for name, expected in manifest['external_files'].items():
        require(name.startswith('mani_skill/'), 'Unknown external source')
        path = (package / name[len('mani_skill/'):]).resolve(strict=True)
        require(path.is_relative_to(package) and sha(path) == expected, 'External input changed: ' + name)


def pair_metrics(first, second, folder):
    import torch
    exact(first['state'], second['state'])
    rows = []
    for camera in ('base_camera', 'human'):
        for env in (0, 1):
            old, new = first['raw'][camera][env], second['raw'][camera][env]
            meta = second['receipt']['cameras'][camera][env]
            native_meta = first['receipt']['cameras'][camera][env]
            require(meta == native_meta, 'Bias pair camera K/pose/format differs')
            tip_id = meta['tip_render_id']
            a, b = old['Segmentation'][..., 0] == tip_id, new['Segmentation'][..., 0] == tip_id
            common, outside = a & b, ~(a | b)
            rgb, other = first['frames'][camera][env], second['frames'][camera][env]
            row = {'seed': second['receipt']['seed'], 'view': second['receipt']['view'], 'camera': camera, 'env_idx': env,
                'translation_x_m': second['receipt']['translation_x_m'], 'tip_render_id': tip_id,
                'native_tip_pixels': int(a.sum()), 'fixed_tip_pixels': int(b.sum()), 'common_tip_pixels': int(common.sum()),
                'rgb_changed_values_outside_tip_union': int(np.count_nonzero(rgb[outside] != other[outside])),
                'depth_changed_values_outside_tip_union': int(np.count_nonzero(old['GbufferDepth'][outside] != new['GbufferDepth'][outside]))}
            require(outside.any() and row['rgb_changed_values_outside_tip_union'] == 0
                    and row['depth_changed_values_outside_tip_union'] == 0, 'Target exterior RGB/depth changed')
            bias = second['receipt']['bias_ndc']
            if common.any():
                delta = new['GbufferDepth'][common] - old['GbufferDepth'][common]
                pos_w = new['Position'][common, 3] - old['Position'][common, 3]
                row.update(position_xyz_max_abs_delta_common_tip=float(np.max(np.abs(new['Position'][common, :3] - old['Position'][common, :3]))),
                    position_raw_max_abs_delta_common_tip=float(np.max(np.abs(new['PositionRaw'][common] - old['PositionRaw'][common]))),
                    depth_delta_common_tip_min_max=[float(delta.min()), float(delta.max())],
                    position_w_delta_common_tip_min_max=[float(pos_w.min()), float(pos_w.max())])
                require(row['position_xyz_max_abs_delta_common_tip'] == row['position_raw_max_abs_delta_common_tip'] == 0,
                        'Common target positions changed')
                require(np.max(np.abs(delta + bias)) < 1e-7
                        and np.max(np.abs(pos_w - delta.reshape(pos_w.shape))) < 1e-7, 'NDC depth differs from declared bias')
            else:
                row['visibility_limit'] = 'No common tip pixel in this original task camera view'
            world = new['PositionRaw'] @ np.asarray(meta['model_matrix']).T
            cap = second['receipt']['caps'][env]
            center = cap['center']
            interior = ((world[..., 0] - center[0]) ** 2 + (world[..., 1] - center[1]) ** 2 < (cap['radius'] - .005) ** 2)
            interior &= np.abs(world[..., 2] - center[2]) < 2e-6
            row['fixed_cap_interior_visible_pixels'] = int(interior.sum())
            row['fixed_cap_interior_missing_pixels'] = int((interior & ~b).sum())
            require(row['fixed_cap_interior_missing_pixels'] == 0, 'Visible cap interior has missing target pixels')
            image = np.asarray(Image.open(folder / f'{camera}_env{env}_comparison.png'))
            require(np.array_equal(image, np.concatenate([rgb, other], axis=1)), 'Comparison PNG differs from original frames')
            rows.append(row)
    return rows


def task_check(root, resource_path, artifact):
    import torch
    from check_pipette_runtime import buffer_errors
    manifest, report = read(root / 'manifest.json'), read(root / 'results.json')
    require(report['status'] == 'passed' and report['completed_constructions'] == 28
            and report['control_steps'] == report['physics_steps'] == 0, 'Incomplete supplementary run')
    require(manifest['num_envs'] == 2 and manifest['gpu_memory_profile'] == 'two_env'
            and manifest['sim_backend'] == 'physx_cuda', 'Wrong probe backend/profile')
    recorded_identity(manifest)
    require(all(report[k] is True for k in ('source_hashes_unchanged', 'external_hashes_unchanged', 'asset_hashes_unchanged')),
            'Capture input closure changed')
    pairs, case_receipts = [], []
    for seed in (7, 19):
        for view, dx in enumerate((-.002, -.001, 0., .001, .002, -.004, .004)):
            folder, captured = root / f'seed{seed}_view{view}', []
            for label in ('native_depth', 'fixed_depth'):
                directory = folder / label
                receipt = read(directory / 'capture.json')
                require(receipt['status'] == 'passed' and receipt['seed'] == seed and receipt['view'] == view
                        and receipt['translation_x_m'] == dx and receipt['label'] == label
                        and receipt['control_steps'] == receipt['physics_steps'] == 0, 'Capture case scope differs')
                require(not buffer_errors(directory / 'native.log'), 'Native buffer warning in probe')
                expected_bias = 0. if label == 'native_depth' else receipt['rendering']['bias_ndc']
                require(receipt['bias_ndc'] == expected_bias, 'Probe bias differs')
                for name, expected in receipt['asset_closure_sha256'].items():
                    require(sha(ROOT / name) == expected, 'Actual robot asset changed')
                states = torch.load(directory / 'state.pt', map_location='cpu', weights_only=True)
                exact(states['before'], states['after'])
                frames, raw = {}, {}
                for camera in ('base_camera', 'human'):
                    frames[camera], raw[camera] = [], []
                    for env in (0, 1):
                        meta = receipt['cameras'][camera][env]
                        require(meta['env_idx'] == env and abs(meta['near'] - .01) < 1e-8 and meta['far'] == 100., 'Task near/far differs')
                        require((meta['width'], meta['height']) == ((640, 480) if camera == 'base_camera' else (1280, 720)), 'Task camera size differs')
                        rgb = np.asarray(Image.open(directory / f'{camera}_env{env}.png'))
                        with np.load(directory / f'{camera}_env{env}_attachments.npz', allow_pickle=False) as values:
                            arrays = {key: values[key].copy() for key in values.files}
                        require(arrays.keys() == {'Color', 'Segmentation', 'PositionRaw', 'Position', 'GbufferDepth'}, 'Missing raw attachments')
                        converted = (torch.from_numpy(arrays['Color'][..., :3]) * 255).to(torch.uint8).numpy()
                        require(rgb.dtype == np.uint8 and np.array_equal(rgb, converted), 'Default float Color conversion differs')
                        require(receipt['standard_rgb'][camera]['device'].startswith('cuda')
                                and receipt['standard_rgb'][camera]['dtype'] == 'torch.uint8', 'Standard CUDA RGB metadata differs')
                        frames[camera].append(rgb)
                        raw[camera].append(arrays)
                captured.append({'receipt': receipt, 'frames': frames, 'raw': raw, 'state': states['before']})
                case_receipts.append(receipt)
            rows = pair_metrics(*captured, folder)
            require(read(folder / 'comparison.json') == {'status': 'passed', 'rows': rows}, 'Recorded depth metrics differ from raw data')
            pairs.extend(rows)
    require(pairs == report['comparisons'], 'Run comparison rows differ from raw recomputation')
    require(all(any(row['common_tip_pixels'] for row in pairs if row['camera'] == camera and row['env_idx'] == env)
                for camera in ('base_camera', 'human') for env in (0, 1)), 'A camera/environment has no measurable common tip pixel')
    resource = read(resource_path)
    require(resource['returncode'] == 0 and not resource.get('stopped') and resource['max_delta_mib'] <= 1792
            and resource['min_free_mib'] > 512 and resource['initial']['free_mib'] >= 2048
            and resource['initial']['util_percent'] < 70, 'Probe resource policy failed')
    raw_files = {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(root.rglob('*')) if path.is_file()}
    raw_files[resource_path.relative_to(ROOT).as_posix()] = sha(resource_path)
    return {'task': report['task'], 'scope': report['scope'], 'control_steps': 0, 'physics_steps': 0,
            'fresh_constructions': 28, 'camera_environment_view_pairs': len(pairs),
            'source': manifest['files'], 'external_files': manifest['external_files'], 'sdk': sdk_check(root / 'private_sdk.json', artifact),
            'rendering': case_receipts[0]['rendering'], 'gpu_memory_config': case_receipts[0]['resolved_sim_config']['gpu_memory_config'],
            'metrics': pairs, 'visibility_limits': [row for row in pairs if row['common_tip_pixels'] == 0],
            'raw_file_sha256': raw_files, 'resources': {key: resource[key] for key in ('max_delta_mib', 'min_free_mib')},
            'status': 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aspirate', type=Path, required=True)
    parser.add_argument('--dispense', type=Path, required=True)
    parser.add_argument('--aspirate-resource', type=Path, required=True)
    parser.add_argument('--dispense-resource', type=Path, required=True)
    parser.add_argument('--sdk-artifact', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'Summary output already exists')
    tasks = [task_check(args.aspirate.resolve(), args.aspirate_resource.resolve(), args.sdk_artifact.resolve()),
             task_check(args.dispense.resolve(), args.dispense_resource.resolve(), args.sdk_artifact.resolve())]
    require([task['task'] for task in tasks] == ['AspirateLiquid', 'DispenseLiquid'], 'Task order/coverage differs')
    require(tasks[0]['source'] == tasks[1]['source'] and tasks[0]['external_files'] == tasks[1]['external_files']
            and tasks[0]['sdk'] == tasks[1]['sdk'], 'Task source/external/SDK identities differ')
    result = {'status': 'passed', 'scope': 'Supplementary standard CUDA task cameras; explicit rendering configuration only',
              'formal_task_isolation': 'See the separate runtime summary',
              'validation': 'Recomputed all PNG/NPZ/PT values, camera/source/asset/SDK identity, no simulator invoked',
              'exporter_sha256': sha(__file__), 'control_steps': 0, 'physics_steps': 0,
              'fresh_constructions': 56, 'camera_environment_view_pairs': 112, 'tasks': tasks}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print({'status': result['status'], 'task_count': len(tasks), 'camera_environment_view_pairs': 112})


if __name__ == '__main__':
    main()
