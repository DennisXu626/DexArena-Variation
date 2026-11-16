"""Preview two material candidates in the real, single-env LayFlatPanel task.

This authoring tool does not install a task kwarg, randomization or reset API.
Use --view for manual inspection/screenshots, or --output for fixed-view exports.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from panel_preview_materials import (
    EDITABLE_ROLES, apply_roles, describe_serializable, inspect_panel,
    restore_native, snapshot_scene,
)

OBJECT = ROOT / 'assets/appearance/objects/furniture_assembly/flat_panel'
CATALOG = OBJECT / 'variants/v1/catalog.json'
TASK_ID = 'FurnitureAssemblyLayFlatPanel-Sharpa-v1'
SCHEMES = ('original', 'ivory_matte', 'navy_satin')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def load_catalog(path):
    catalog = json.loads(path.read_text(encoding='utf-8'))
    if (catalog['version'] != 'flat-panel-preview-v1'
            or catalog['object_id'] != 'furniture_assembly.flat_panel'
            or tuple(catalog['schemes']) != SCHEMES
            or set(catalog['color_factors']) != set(EDITABLE_ROLES)
            or catalog['preserve_roles'] != ['label', 'ink']
            or catalog['schemes']['original'] != {'mode': 'restore_native'}):
        raise ValueError('Unexpected panel preview catalog contract')
    for name in SCHEMES[1:]:
        candidate = catalog['schemes'][name]
        color = np.asarray(candidate['base_color'], dtype=float)
        if (candidate['mode'] != 'material_override' or color.shape != (4,)
                or not np.isfinite(color).all() or np.any(color < 0)
                or np.any(color > 1) or color[3] != 1 or candidate['metallic'] != 0
                or set(candidate['roughness']) != set(EDITABLE_ROLES)):
            raise ValueError(f'Invalid opaque non-metallic candidate: {name}')
        for role in EDITABLE_ROLES:
            if not 0 <= float(candidate['roughness'][role]) <= 1:
                raise ValueError(f'{name}: invalid roughness for {role}')
            if not 0 < float(catalog['color_factors'][role]) <= 1:
                raise ValueError(f'Invalid color factor for {role}')
    return catalog


def role_parameters(catalog, name):
    candidate = catalog['schemes'][name]
    color = candidate['base_color']
    return {role: {
        'base_color': [float(c) * catalog['color_factors'][role] for c in color[:3]] + [color[3]],
        'roughness': candidate['roughness'][role], 'metallic': candidate['metallic'],
    } for role in EDITABLE_ROLES}


def select_scheme(binding, catalog, name):
    restore_native(binding)
    if name != 'original':
        apply_roles(binding, role_parameters(catalog, name))
    observed = {}
    expected = None if name == 'original' else role_parameters(catalog, name)
    for role, rows in binding.groups.items():
        values = []
        for row in rows:
            material = row['material']
            actual = {'base_color': list(material.base_color),
                      'roughness': float(material.roughness), 'metallic': float(material.metallic)}
            target = row['native'] if expected is None or role not in expected else expected[role]
            for field in actual:
                np.testing.assert_allclose(actual[field], target[field], rtol=0, atol=2e-6)
            values.append(actual)
        observed[role] = {'parts_checked': len(rows), 'actual': values[0]}
    return observed


def make_task(seed):
    import gymnasium as gym
    import tasks  # Register the actual repository environments.
    env = gym.make(TASK_ID, num_envs=1, sim_backend='physx_cpu', obs_mode='state',
                   control_mode='pd_joint_pos', render_mode='human',
                   panel_color_jitter=False, visual_detail=True)
    try:
        env.reset(seed=seed)
        return env
    except BaseException:
        env.close()
        raise


def prepare_viewer(env):
    from sapien.utils.viewer.path_window import PathWindow
    from sapien.utils.viewer.transform_window import TransformWindow
    from mani_skill.utils import sapien_utils
    import sapien

    e = env.unwrapped
    viewer = e._viewer
    # These optional authoring panels auto-create a Pinocchio model on robot
    # selection. Other viewer plugins and the actual task scene remain intact.
    kept = []
    for plugin in viewer.plugins:
        if isinstance(plugin, (TransformWindow, PathWindow)):
            plugin.close()
        else:
            kept.append(plugin)
    viewer.plugins = kept
    viewer.selected_entity_visibility = 1.0
    camera = e.scene.human_render_cameras['render_camera'].camera._render_cameras[0]
    # Camera pose lives on the camera component, not its identity-pose entity.
    task_pose = camera.get_global_pose()
    center = e.panel.pose.p[0].cpu().numpy()
    detail = sapien_utils.look_at(center + np.array([0.20, -0.55, 0.18]), center)
    detail_pose = sapien.Pose(detail.p[0].tolist(), detail.q[0].tolist())
    views = {'task': task_pose, 'detail': detail_pose}
    config = {'width': int(camera.width), 'height': int(camera.height),
              'near': float(camera.near), 'far': float(camera.far), 'fovy': float(camera.fovy),
              'poses': {name: {'p_m': pose.p.tolist(), 'q_wxyz': pose.q.tolist()}
                        for name, pose in views.items()},
              'task_view': 'Native task render_camera extrinsics and projection; viewer shader',
              'detail_view': 'Additional fixed camera of the same unchanged task initial state',
              'capture_path': 'SAPIEN RenderWindow Color -> CPU NumPy (not CUDA image tensor)'}
    viewer.resolution = (config['width'], config['height'])
    viewer.window.set_camera_parameters(config['near'], config['far'], config['fovy'])
    viewer.set_camera_pose(views['task'])
    return viewer, views, config


def capture(viewer, pose):
    """Read the native human framebuffer; avoid Windows CUDA tensor readback."""
    from PIL import Image
    viewer.set_camera_pose(pose)
    # Draw no UI into exported frames. No physics or task reset is performed.
    for _ in range(2):
        viewer.window.update_render()
        viewer.window.render('Color', [])
    pixels = np.asarray(viewer.window.get_picture('Color'))[..., :3].copy()
    if np.issubdtype(pixels.dtype, np.floating):
        pixels = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    elif pixels.dtype != np.uint8:
        raise ValueError(f'Unexpected framebuffer dtype {pixels.dtype}')
    if pixels.ndim != 3 or pixels.shape[-1] != 3 or np.ptp(pixels) == 0:
        raise RuntimeError('Invalid or blank native task framebuffer')
    return Image.fromarray(pixels)


def compare_images(frames, path):
    from PIL import Image, ImageDraw
    width, height = frames[0][1].size
    sheet = Image.new('RGB', (width * len(frames), height + 36), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    for i, (name, frame) in enumerate(frames):
        draw.text((i * width + 12, 10), name, fill=(245, 245, 245))
        sheet.paste(frame, (i * width, 36))
    sheet.save(path)


def invariant_check(before, env):
    after = snapshot_scene(env)
    if before != after:
        changed = [key for key in before if before[key] != after[key]]
        raise RuntimeError(f'Task state or protected scene properties changed: {changed}')
    return {key: digest(value) for key, value in after.items()}


def export(env, binding, catalog, viewer, views, camera_config, output, seed):
    output.mkdir(parents=True, exist_ok=False)
    baseline = snapshot_scene(env)
    native_description = describe_serializable(binding)
    evidence = {'task_id': TASK_ID, 'num_envs': 1, 'seed': seed,
                'scope': 'Single-env initial-state authoring preview; not A4/A5 or task success',
                'native_bindings': native_description, 'schemes': {},
                'env_step_calls_after_reset': 0, 'checks': {}, 'screenshots_review': 'pending_human_review'}
    frames = {name: [] for name in views}
    try:
        for name in SCHEMES:
            actual = select_scheme(binding, catalog, name)
            evidence['schemes'][name] = {'actual_roles': actual, 'images': {}}
            for view, pose in views.items():
                image = capture(viewer, pose)
                filename = f'{name}_{view}.png'
                image.save(output / filename)
                evidence['schemes'][name]['images'][view] = {
                    'file': filename, 'sha256': hashlib.sha256((output / filename).read_bytes()).hexdigest(),
                    'size': list(image.size)}
                frames[view].append((name, image))
            evidence['schemes'][name]['invariant_digests'] = invariant_check(baseline, env)
        restore_native(binding)
        if describe_serializable(binding) != native_description:
            raise RuntimeError('Native material restoration did not match the captured original')
        invariant_check(baseline, env)
        evidence['checks'] = {'actual_22_shape_binding': len(binding.shapes) == 22,
                              'all_requested_material_parameters': True,
                              'same_reset_state_geometry_physics_and_uv': True,
                              'non_panel_and_protected_materials_unchanged': True,
                              'original_restoration_exact': True}
        for view, images in frames.items():
            compare_images(images, output / f'comparison_{view}.png')
        write_json(output / 'baseline_scene.json', baseline)
        write_json(output / 'evidence.json', evidence)
        files = ['tools/variation/render_panel_preview.py', 'tools/variation/panel_preview_materials.py',
                 'tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py', CATALOG.relative_to(ROOT).as_posix()]
        revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                                  capture_output=True, text=True, check=True).stdout.strip()
        manifest = {'created_utc': datetime.now(timezone.utc).isoformat(), 'task_id': TASK_ID,
                    'git_base_commit': revision, 'implementation_files_sha256': {
                        file: hashlib.sha256((ROOT / file).read_bytes()).hexdigest() for file in files},
                    'catalog_version': catalog['version'], 'num_envs': 1, 'seed': seed,
                    'panel_color_jitter': False, 'visual_detail': True,
                    'backend': str(env.unwrapped.backend), 'platform': platform.system(),
                    'versions': {p: metadata.version(p) for p in ('torch', 'sapien', 'mani_skill', 'numpy', 'gymnasium', 'trimesh', 'Pillow')},
                    'camera': camera_config, 'env_step_calls_after_reset': 0,
                    'wood_texture_files': {name: (ROOT / 'tasks/assets/textures' / name).is_file()
                                           for name in ('wood_albedo.png', 'wood_normal.png', 'wood_roughness.png')},
                    'scope': 'Real task initial-state material preview only; manually inspect images before acceptance'}
        write_json(output / 'manifest.json', manifest)
        print(f'Exported three schemes and two fixed views to {output}', flush=True)
    finally:
        restore_native(binding)


def interactive(env, binding, catalog, viewer, views, initial_scheme):
    baseline = snapshot_scene(env)
    name, view = initial_scheme, 'task'
    select_scheme(binding, catalog, name)
    invariant_check(baseline, env)
    viewer.set_camera_pose(views[view])
    print('Keys: 1 original | 2 ivory_matte | 3 navy_satin | V fixed task/detail view', flush=True)
    print('Camera: right-drag rotates, middle-drag pans, wheel zooms. Close window to exit.', flush=True)
    print(f'Scheme: {name}; view: {view}', flush=True)
    try:
        while not viewer.closed:
            env.render()
            if viewer.closed:
                break
            for key, candidate in zip(('1', '2', '3'), SCHEMES):
                if viewer.window.key_press(key):
                    viewer.select_entity(None)
                    select_scheme(binding, catalog, candidate)
                    invariant_check(baseline, env)
                    name = candidate
                    print(f'Scheme: {name}; view: {view}', flush=True)
            if viewer.window.key_press('v'):
                view = 'detail' if view == 'task' else 'task'
                viewer.select_entity(None)
                viewer.set_camera_pose(views[view])
                print(f'Scheme: {name}; view: {view}', flush=True)
            time.sleep(1 / 60)
    finally:
        restore_native(binding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--view', action='store_true', help='Open the real task for manual inspection/screenshots')
    parser.add_argument('--scheme', choices=SCHEMES, default='original', help='Starting scheme for --view')
    parser.add_argument('--output', type=Path, help='New directory for fixed-view exports and verification evidence')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--static', action='store_true', help='Validate the authoring catalog without importing the simulator')
    args = parser.parse_args()
    catalog = load_catalog(CATALOG)
    if args.static:
        print(json.dumps({'status': 'passed', 'scope': 'catalog only; no simulation', 'schemes': list(SCHEMES)}))
        return
    if not args.view and args.output is None:
        parser.error('Choose --view or --output DIRECTORY')
    if args.output is not None and args.output.exists():
        parser.error('Output directory must be new; existing results are never overwritten')
    env = None
    try:
        env = make_task(args.seed)
        binding = inspect_panel(env)
        viewer, views, camera_config = prepare_viewer(env)
        if args.output is not None:
            export(env, binding, catalog, viewer, views, camera_config, args.output, args.seed)
        if args.view:
            interactive(env, binding, catalog, viewer, views, args.scheme)
    except KeyboardInterrupt:
        pass
    finally:
        if env is not None:
            env.close()


if __name__ == '__main__':
    main()
