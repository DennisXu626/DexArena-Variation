"""Preflight or render isolated Pipette models; --render requires a GPU window."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipette_preview_materials import (
    BUILDERS, CATALOG, ROOT, apply_material, apply_records, build_pipette_model,
    fresh_output, input_file_sha256, inspect_pipette_asset, load_catalog, private_material, restore_records,
    snapshot_records, source_digest, source_namespace,
)
from check_pipette_appearance import check
from pipette_render_fixes import (
    capture_rgb, depth_probe, depth_shader, geometry_hash, material_state, model_camera,
    optical_probe, pipette_native_state, shader_hashes,
)

OBJECTS = ('pipette', 'sample_cup', 'test_tube', 'tube_rack', 'pipette_stand', 'tip_cup')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')


def camera_pose(sapien, target, distance, direction):
    import numpy as np
    eye = np.asarray(target)+np.asarray(direction)*distance
    forward = np.asarray(target)-eye
    forward /= np.linalg.norm(forward)
    left = np.cross([0., 0., 1.], forward)
    left /= np.linalg.norm(left)
    up = np.cross(forward, left)
    matrix = np.eye(4)
    matrix[:3, :3] = np.column_stack([forward, left, up])
    matrix[:3, 3] = eye
    return sapien.Pose(matrix)


def render_object(key, output, catalog, urdf, size, verify_visuals=False):
    import numpy as np
    import sapien
    from PIL import Image, ImageDraw

    engine = sapien.Engine()
    renderer = sapien.SapienRenderer()
    engine.set_renderer(renderer)
    scene = engine.create_scene()
    scene.set_ambient_light([.55, .55, .55])
    scene.add_directional_light([1., -1., -2.], [2., 2., 2.], shadow=True)
    ns = source_namespace(sapien)
    parent = 'pipette_stand' if key == 'tip_cup' else key
    source_geometry = None
    pipette_bundle, pipette_state, pipette_pbr = None, None, None
    if key == 'pipette':
        pipette_bundle = build_pipette_model(scene, urdf, sapien, ns)
        actor, records = pipette_bundle.actor, pipette_bundle.selected
        # Native CPU construction needs a same-value qpos write to synchronize FK.
        actor.set_qpos(actor.get_qpos().copy())
        builder = pipette_bundle.builder
        source_geometry = {'visual': geometry_hash(pipette_bundle.visual_records),
                           'collision': geometry_hash(pipette_bundle.collision_records)}
        pipette_state = pipette_native_state(pipette_bundle, sapien)
        pipette_pbr = material_state(pipette_bundle.visual_records)
    else:
        builder = scene.create_actor_builder()
        if parent in ('sample_cup', 'test_tube'):
            ns[BUILDERS[parent]](builder, ns['cfg'])
        else:
            ns[BUILDERS[parent]](builder)
        records = list(builder.visual_records)
        source_geometry = {'visual': geometry_hash(records), 'collision': geometry_hash(builder.collision_records)}
        # Own each material before any object enters the scene.
        for record in records:
            record.material = private_material(sapien, record.material)
        actor = builder.build_kinematic(name=parent)
    shader_root = Path(sapien.__file__).parent/'vulkan_shader'
    shader = shader_root/'default'
    shader_evidence = {'shader_pack': 'default', 'source_shader_sha256': {
        f'{name}/{path}': value for name in ('default', 'common')
        for path, value in shader_hashes(shader_root/name).items()}}
    body = actor.find_component_by_type(sapien.render.RenderBodyComponent) if key != 'pipette' else None
    tip_id, bias = None, 0.
    if parent == 'pipette_stand':
        shader, shader_evidence = depth_shader(sapien, output/'shader')
        tip_id = body.render_shapes[4].per_scene_id
        bias = catalog['rendering']['tip_depth_bias_ndc']
    native = snapshot_records(pipette_bundle.visual_records if pipette_bundle else records)
    target = [0., 0., -.04] if key == 'pipette' else [0., 0., .08]
    distance = .29 if key == 'pipette' else .22
    if key == 'sample_cup':
        target, distance = [0., 0., .016], .15
    if key == 'tip_cup':
        target, distance = [0., 0., .012], .095
    direction = [1., 1.6, 1.05] if parent == 'pipette_stand' else [1., -1.6, 1.05]
    camera = model_camera(sapien, scene, size, shader, camera_pose(sapien, target, distance, direction))
    if tip_id is not None:
        camera.set_property('pipetteTipRenderId', int(tip_id))
        camera.set_property('pipetteDepthBias', float(bias))
    textures = {}

    def label_texture(path, levels):
        if path not in textures:
            textures[path] = sapien.render.RenderTexture2D(str(path), mipmap_levels=levels)
        return textures[path]

    frames = []
    for scheme in ('original', *catalog['candidate_ids'], 'original_restored'):
        restore_records(native)
        if scheme not in ('original', 'original_restored'):
            if key == 'pipette':
                apply_material(records[0].material, catalog['objects'][key]['schemes'][scheme]['body'])
            else:
                apply_records(records, parent, scheme, catalog, load_texture=label_texture)
        rgb = capture_rgb(scene, camera, size)
        if pipette_bundle:
            if pipette_native_state(pipette_bundle, sapien) != pipette_state:
                raise RuntimeError('Pipette physical state changed during render-only preview')
            current_pbr = material_state(pipette_bundle.visual_records)
            if current_pbr[1:] != pipette_pbr[1:]:
                raise RuntimeError('Protected Pipette visual materials changed')
            if scheme in ('original', 'original_restored') and current_pbr != pipette_pbr:
                raise RuntimeError('Pipette original PBR did not restore exactly')
        frame = Image.fromarray(rgb)
        frame.save(output/f'{key}_{scheme}.png')
        frames.append((scheme, rgb.copy(), frame))
    restore_records(native)
    drift = int(np.max(np.abs(frames[0][1].astype(int)-frames[-1][1].astype(int))))
    if drift:
        raise RuntimeError(f'{key}: restored RGB differs from original (max difference {drift})')
    for start in range(1, len(frames) - 1, 4):
        page = [frames[0], *frames[start:min(start + 4, len(frames) - 1)]]
        sheet = Image.new('RGB', (len(page)*size, size+40), (28, 31, 35))
        draw = ImageDraw.Draw(sheet)
        for index, (scheme, _, frame) in enumerate(page):
            draw.text((index*size+12, 12), scheme, fill='white')
            sheet.paste(frame, (index*size, 40))
        sheet.save(output/f'{key}_comparison_{start // 4 + 1}.png')
    verification = {}
    if verify_visuals and key in ('sample_cup', 'test_tube'):
        verification['optical_probe'] = optical_probe(sapien, scene, camera, body, records, key,
                                                       catalog, output, size, camera_pose)
    if verify_visuals and parent == 'pipette_stand':
        verification['depth_probe'] = depth_probe(sapien, scene, camera, tip_id, records[4], bias, output,
                                                   key, size, camera_pose)
    if source_geometry is not None:
        visual_records = pipette_bundle.visual_records if pipette_bundle else records
        if source_geometry != {'visual': geometry_hash(visual_records), 'collision': geometry_hash(builder.collision_records) if not pipette_bundle
                               else geometry_hash(pipette_bundle.collision_records)}:
            raise RuntimeError('Model geometry/collision records changed')
    # No simulation step, task import, robot, task reset or initial-pose update.
    return {'object_id': key, 'parent_model': parent, 'scope': 'isolated model preview',
            'camera_target': target, 'camera_distance_factor': distance,
            'camera_direction': direction, 'image_size': [size, size], 'camera_fovy_deg': 40.,
            'restored_rgb_max_abs_difference': drift,
            'native_geometry_sha256': source_geometry, 'shader': shader_evidence,
            'pipette_native_baseline': pipette_state, 'pipette_native_pbr': pipette_pbr,
            'tip_depth_bias_ndc': bias, **verification,
            'review_required': ['candidate distinction', 'openings and functional detail',
                                'glass readability where applicable']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects', nargs='+', choices=OBJECTS, default=list(OBJECTS))
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid4().hex[:8]
    parser.add_argument('--output', type=Path, default=ROOT/f'outputs/variation/pipette_transfer/preview_{run_id}')
    parser.add_argument('--pipette-urdf', type=Path,
                        default=ROOT/'tasks/assets/task_object_meshes/pipette/mobility.urdf')
    parser.add_argument('--size', type=int, default=512)
    parser.add_argument('--render', action='store_true', help='Use GPU; run only in an assigned window')
    parser.add_argument('--verify-visuals', action='store_true', help='Add fixed-target glass or multi-view depth tests')
    parser.add_argument('--physx-gpu-dir', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if len(args.objects) != len(set(args.objects)):
        parser.error('--objects must be unique')
    if args.render and len(args.objects) != 1:
        parser.error('Render exactly one object per process; launch models serially')
    if not 128 <= args.size <= 2048:
        parser.error('--size must be between 128 and 2048')
    catalog = load_catalog()
    if args.render and args.pipette_urdf.resolve() != (ROOT/'tasks/assets/task_object_meshes/pipette/mobility.urdf').resolve():
        parser.error('Render from the audited installed Pipette path so manifest identities match')
    args.output = fresh_output(args.output)
    result = {'scope': 'CPU preflight; no GPU or task construction',
              'cpu_check': check(), 'objects': args.objects,
              'pipette_asset': inspect_pipette_asset(args.pipette_urdf)}
    if 'pipette' in args.objects and result['pipette_asset']['status'] != 'reviewed':
        result['render_ready'] = False
        result['blocker'] = 'Pipette source asset and editable body material must be reviewed first'
    else:
        result['render_ready'] = True
    write_json(args.output/'preflight.json', result)
    if not args.render:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if not result['render_ready']:
        raise SystemExit(result['blocker'])
    report = {
        'status': 'running',
        'scope': 'Native SAPIEN isolated models; not task images or A4/A5 acceptance',
        'source_geometry_ast_sha256': source_digest(),
        'catalog_sha256': hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        'input_file_sha256': input_file_sha256(),
        'runtime': {package: metadata.version(package) for package in ('sapien', 'numpy', 'Pillow')},
        'objects': [],
    }
    try:
        for key in args.objects:
            report['objects'].append(render_object(key, args.output, catalog, args.pipette_urdf, args.size, args.verify_visuals))
        if input_file_sha256() != report['input_file_sha256']:
            raise RuntimeError('Preview input files changed during rendering')
    except Exception as error:
        report.update(status='failed', error=str(error))
        write_json(args.output/'manifest.json', report)
        raise
    report['status'] = 'model_preview_checks_passed'
    write_json(args.output/'manifest.json', report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
