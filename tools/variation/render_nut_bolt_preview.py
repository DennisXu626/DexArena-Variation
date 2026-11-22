"""Export Nut & Bolt authoring previews after a coordinator assigns GPU time."""
import argparse
from datetime import datetime, timezone
import hashlib
import html
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/variation'))
from nut_bolt_preview_materials import (
    BASE, FIELDS, SCHEMES, TASKS, readback, bind, catalogs, digest, material_state,
    plain, snapshot,
)

SCOPE = 'Formal short-task appearance at one fixed initial state; no dynamics, GPU isolation, Long or complete task success'


def local_output(raw):
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    allowed = (ROOT / 'outputs/variation/nut_bolt', ROOT / '.local/nut_bolt')
    if not any(path.is_relative_to(folder.resolve()) for folder in allowed):
        raise ValueError('Output must be under outputs/variation/nut_bolt or .local/nut_bolt')
    return path


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def palette(path):
    """Flat parameter swatches only, deliberately separate from task imagery."""
    definition = catalogs()
    rows = (len(SCHEMES) - 1 + 1) // 2
    height = 120 + 2 * (rows * 118 + 40)
    content = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1050" height="{height}" viewBox="0 0 1050 {height}">',
               f'<rect width="1050" height="{height}" fill="#f6f5f1"/>',
               '<g font-family="sans-serif" fill="#20272c">',
               '<text x="30" y="36" font-size="22">Nut &amp; Bolt / material parameters</text>',
               '<text x="30" y="62" font-size="14">CPU flat swatches. No object, lighting, physics or task-render validation.</text>']
    for j, obj in enumerate(('bolt', 'nut')):
        top = 105 + (rows * 118 + 40) * j
        content.append(f'<text x="30" y="{top}" font-size="20">{obj}</text>')
        content.append(f'<text x="30" y="{top+28}" font-size="13">original: restore native</text>')
        for k, scheme in enumerate(SCHEMES[1:]):
            x = 270 + 380 * (k % 2)
            y = top + 118 * (k // 2)
            candidate = definition[obj]['schemes'][scheme]
            content.append(f'<text x="{x}" y="{y}" font-size="16">{scheme}: {html.escape(candidate["label"])}</text>')
            for i, (role, params) in enumerate(candidate['roles'].items()):
                color = '#' + ''.join(f'{round(v*255):02x}' for v in params['base_color'][:3])
                ry = y + 15 + i * 47
                content.append(f'<rect x="{x}" y="{ry}" width="72" height="36" rx="4" fill="{color}"/>')
                label = f'{role}  r={params["roughness"]} m={params["metallic"]}'
                content.append(f'<text x="{x+84}" y="{ry+23}" font-size="13">{html.escape(label)}</text>')
    content += [f'<text x="30" y="{height - 18}" font-size="13">Bolt tip/thread stay native. Nut reference_face is existing segment 0 in both twins.</text>', '</g></svg>']
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(content) + '\n', encoding='utf-8')
    print(json.dumps({'scope': 'CPU flat parameter swatches only', 'file': str(path)}))


def make_task(task, seed):
    mesh = ROOT / 'tasks/assets/task_object_meshes/screwing/bolt_hex_head.obj'
    if not mesh.is_file():
        raise FileNotFoundError(f'Authorized original asset required: {mesh}')
    sys.path.insert(0, str(ROOT))
    import gymnasium as gym
    import tasks  # Register unchanged repository environments.

    env = gym.make(TASKS[task], num_envs=1, sim_backend='physx_cpu', obs_mode='state',
                   control_mode='pd_joint_pos', render_mode='human', reconfiguration_freq=0,
                   nut_bolt_appearance={'enabled': True, 'scheme_id': 'original'})
    try:
        env.reset(seed=seed)
    except BaseException:
        env.close()
        raise
    return env


def prepare_views(env, task, rows):
    import numpy as np
    import sapien
    from mani_skill.utils import sapien_utils
    from sapien.utils.viewer.path_window import PathWindow
    from sapien.utils.viewer.transform_window import TransformWindow

    env.render()
    base = env.unwrapped
    viewer = base._viewer
    keep = []
    for plugin in viewer.plugins:
        if isinstance(plugin, (PathWindow, TransformWindow)):
            plugin.close()
        else:
            keep.append(plugin)
    viewer.plugins = keep
    viewer.select_entity(None)
    native_camera = base.scene.human_render_cameras['render_camera'].camera._render_cameras[0]
    config = {field: plain(getattr(native_camera, field)) for field in ('width', 'height', 'near', 'far', 'fovy')}
    viewer.resolution = (config['width'], config['height'])
    viewer.window.set_camera_parameters(config['near'], config['far'], config['fovy'])
    views = {'task': native_camera.get_global_pose()}
    for obj in ('bolt', 'nut'):
        representation = 'threaded' if obj == 'nut' and task == 'TurnNut' else 'free'
        row = next((row for row in rows if row['object_id'] == obj and row['representation'] == representation), None)
        if row is None:
            continue
        target = np.asarray(row['entity'].pose.p)
        offset = np.array([0.12, -0.16, 0.13]) if obj == 'bolt' else np.array([0.08, -0.10, 0.13])
        pose = sapien_utils.look_at(target + offset, target)
        views[obj] = sapien.Pose(pose.p[0].tolist(), pose.q[0].tolist())
    config['poses'] = {key: {'p_m': plain(pose.p), 'q_wxyz': plain(pose.q)} for key, pose in views.items()}
    config['projection_matrix'] = plain(viewer.window.get_camera_projection_matrix())
    config['capture'] = 'Native SAPIEN RenderWindow Color to CPU; native task camera plus fixed detail views'
    return viewer, views, config


def capture(viewer, pose):
    import numpy as np
    from PIL import Image

    viewer.set_camera_pose(pose)
    for _ in range(2):
        viewer.window.update_render()
        viewer.window.render('Color', [])
    pixels = np.asarray(viewer.window.get_picture('Color'))[..., :3].copy()
    if np.issubdtype(pixels.dtype, np.floating):
        pixels = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[-1] != 3 or np.ptp(pixels) == 0:
        raise RuntimeError('Invalid or blank native framebuffer')
    return Image.fromarray(pixels)


def export(env, task, seed, output):
    import numpy as np
    import sapien
    from PIL import Image, ImageDraw
    from tools.variation.check_nut_bolt_runtime import source_hashes, external_hashes, sdk_identity

    frozen_sources, frozen_external, frozen_sdk = source_hashes(), external_hashes(), sdk_identity(sapien)
    definition = catalogs()
    rows = bind(env, task)
    def select(scheme):
        env.unwrapped._nut_bolt_appearance.finish_reset(np.asarray([0]),
            {'nut_bolt_appearance': {'scheme_id': scheme}})
        return readback(rows, definition, scheme)
    viewer, views, camera = prepare_views(env, task, rows)
    baseline = snapshot(env, rows)
    native = [material_state(row['material']) for row in rows]
    output.mkdir(parents=True, exist_ok=False)
    frames = {view: [] for view in views}
    report = dict(scope=SCOPE, task_id=TASKS[task], seed=seed, num_envs=1, sim_backend='physx_cpu',
                  env_step_calls_after_reset=0, schemes={}, screenshots_review='pending')
    try:
        for scheme in SCHEMES:
            observed = select(scheme)
            pictures = {}
            for view, pose in views.items():
                frame = capture(viewer, pose)
                name = f'{scheme}_{view}.png'
                frame.save(output / name)
                pictures[view] = dict(file=name, sha256=sha(output / name))
                frames[view].append(frame)
            if snapshot(env, rows) != baseline:
                raise RuntimeError(f'Geometry/physics/pose/visibility/protected material changed: {scheme}')
            report['schemes'][scheme] = dict(materials=observed, images=pictures)
        select('original')
        if [material_state(row['material']) for row in rows] != native or snapshot(env, rows) != baseline:
            raise RuntimeError('Original restoration or scene invariants failed')
        restored = {}
        for view, pose in views.items():
            before = np.asarray(frames[view][0])
            after = np.asarray(capture(viewer, pose))
            restored[view] = dict(identical=bool(np.array_equal(before, after)),
                                  max_abs_diff=int(np.abs(before.astype(int)-after.astype(int)).max()))
            width, height = frames[view][0].size
            for start in range(1, len(SCHEMES), 2):
                indices = (0, *range(start, min(start + 2, len(SCHEMES))))
                sheet = Image.new('RGB', (width * len(indices), height + 32), (30, 30, 30))
                draw = ImageDraw.Draw(sheet)
                for column, index in enumerate(indices):
                    draw.text((column * width + 12, 9), SCHEMES[index], fill=(245, 245, 245))
                    sheet.paste(frames[view][index], (column * width, 32))
                sheet.save(output / f'comparison_{view}_{(start + 1) // 2:02d}.png')
        report['checks'] = dict(material_readback=True, recorded_scene_geometry_physics_uv_pose_visibility_unchanged=True,
                                original_materials_restored=True, original_pixels=restored)
        if not all(result['identical'] for result in restored.values()):
            report['status'] = 'failed_original_pixel_restoration'
            write_json(output / 'evidence.json', report)
            raise RuntimeError('Original RGB pixels did not restore exactly; see evidence.json')
        if snapshot(env, rows) != baseline:
            raise RuntimeError('Scene invariants changed during restored-original capture')
        report['status'] = 'formal_initial_state_checks_passed_screenshot_review_pending'
        report['appearance_records'] = env.unwrapped._nut_bolt_appearance.records
        report['baseline_sha256'] = digest(baseline)
        write_json(output / 'baseline_scene.json', baseline)
        write_json(output / 'evidence.json', report)
        if frozen_sources != source_hashes() or frozen_external != external_hashes() or frozen_sdk != sdk_identity(sapien):
            raise RuntimeError('Sources, assets or SDK changed during image capture')
        manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(), scope=SCOPE, camera=camera,
                        versions={key: metadata.version(key) for key in ('sapien', 'mani_skill', 'numpy', 'torch', 'Pillow')},
                        source_sha256=frozen_sources, external_sha256=frozen_external,
                        sdk_native_files=frozen_sdk, inputs_unchanged=True,
                        head_asset_sha256=sha(ROOT / 'tasks/assets/task_object_meshes/screwing/bolt_hex_head.obj'),
                        evidence_sha256=sha(output / 'evidence.json'),
                        generated_urdf_sha256=(sha(ROOT / 'tasks/assets/task_object_meshes/screwing/threaded_nut_revolute.urdf')
                                               if task != 'PickBolt' else None))
        write_json(output / 'manifest.json', manifest)
    except BaseException as error:
        write_json(output / 'failure.json', dict(scope=SCOPE, error_type=type(error).__name__, error=str(error)))
        raise
    finally:
        select('original')
    print(json.dumps({'status': 'exported_formal_initial_state_preview', 'task': task, 'output': str(output),
                      'screenshots_review': 'pending', 'original_pixels': restored}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='CPU stdlib checks; no simulator import')
    mode.add_argument('--palette', action='store_true', help='CPU flat SVG parameter swatches')
    mode.add_argument('--render', action='store_true', help='Needs separately assigned GPU rendering time')
    parser.add_argument('--task', choices=tuple(TASKS), default='PickBolt')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--output', help='New output path in outputs/variation/nut_bolt or .local/nut_bolt')
    args = parser.parse_args()
    if args.check:
        command = [sys.executable, '-B', str(ROOT / 'tools/variation/check_nut_bolt_appearance.py')]
        if args.output:
            command += ['--output', args.output]
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    if not args.output:
        parser.error('--output is required for --palette and --render')
    output = local_output(args.output)
    if output.exists():
        raise FileExistsError(output)
    if args.palette:
        if output.suffix.lower() != '.svg':
            parser.error('--palette output must end in .svg')
        palette(output)
    else:
        env = make_task(args.task, args.seed)
        try:
            export(env, args.task, args.seed, output)
        finally:
            env.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
