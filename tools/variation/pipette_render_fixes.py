"""Pipette model rendering: default alpha blending and a tip-only depth bias."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import shutil

SOURCE_FRAGMENT_SHA256 = {
    'gbuffer.frag': '96bf1cd4330f90e29d7456b90dfea9bc8c8a839458a32e31ae525863072028fb',
    'gbuffer1.frag': '574745cffd6dd6b86ed9ecd2d94c7533fbe5b0cc0fdf36606efa5e1c5c5ab982',
}


def shader_hashes(folder):
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob('*')) if path.is_file()}


def depth_shader(sapien, output):
    """Copy installed shaders into the run, preserving their Apache headers."""
    source = Path(sapien.__file__).parent/'vulkan_shader'
    for name, expected in SOURCE_FRAGMENT_SHA256.items():
        if hashlib.sha256((source/'default'/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Unreviewed SAPIEN shader: {name}')
    for name in ('default', 'common'):
        shutil.copytree(source/name, output/name)
    source_hashes = shader_hashes(output)
    constants = ('layout(constant_id=20) const int pipetteTipRenderId=-1;\n'
                 'layout(constant_id=21) const float pipetteDepthBias=0.0;\n\n')
    patch = ('\n  gl_FragDepth = gl_FragCoord.z;\n'
             '  if (int(inSegmentation.x) == pipetteTipRenderId)\n'
             '    gl_FragDepth = clamp(gl_FragCoord.z-pipetteDepthBias, 0.0, 1.0);')
    for name in SOURCE_FRAGMENT_SHA256:
        path = output/'default'/name
        text = path.read_text(encoding='utf-8')
        if text.count('#define SET_NUM 0') != 1 or text.count('void main() {') != 1:
            raise ValueError(f'Unexpected shader patch anchors: {name}')
        text = text.replace('#define SET_NUM 0', constants+'#define SET_NUM 0', 1)
        text = text.replace('void main() {', 'void main() {'+patch, 1)
        path.write_text(text, encoding='utf-8')
    return output/'default', {'source_shader_sha256': source_hashes,
                              'generated_shader_sha256': shader_hashes(output),
                              'patch_sha256': hashlib.sha256((constants+patch).encode()).hexdigest(),
                              'scope': 'Fragment depth only; no vertex, PositionRaw or material changes'}


def model_camera(sapien, scene, size, shader, pose):
    camera = sapien.render.RenderCameraComponent(size, size, str(shader))
    camera.near, camera.far = .01, 10.
    camera.set_fovy(math.radians(40), True)
    entity = sapien.Entity()
    entity.name = 'pipette_model_camera'
    entity.add_component(camera)
    entity.pose = pose
    scene.add_entity(entity)
    return camera


def geometry_hash(records):
    import json

    def value(item):
        if hasattr(item, 'p') and hasattr(item, 'q'):
            return {'p': list(map(float, item.p)), 'q': list(map(float, item.q))}
        if hasattr(item, 'tolist'):
            return item.tolist()
        if isinstance(item, (list, tuple)):
            return [value(x) for x in item]
        return item
    entries = [{key: value(item) for key, item in vars(record).items() if key != 'material'}
               for record in records]
    return hashlib.sha256(json.dumps(entries, sort_keys=True, allow_nan=False).encode()).hexdigest()


def capture_rgb(scene, camera, size):
    import numpy as np
    scene.update_render()
    camera.take_picture()
    pixels = np.asarray(camera.get_picture('Color'))
    if pixels.shape[:2] != (size, size) or pixels.ndim != 3 or pixels.shape[2] < 3 or not np.isfinite(pixels).all():
        raise RuntimeError('Invalid or nonfinite native frame')
    rgb = (np.clip(pixels[..., :3], 0, 1)*255).astype(np.uint8)
    if np.ptp(rgb) == 0:
        raise RuntimeError('Blank native frame')
    return rgb


def material_state(records):
    """Capture actual imported PBR, including opaque source alpha and texture absence."""
    fields = ('base_color', 'roughness', 'metallic', 'specular', 'transmission', 'ior',
              'transmission_roughness', 'emission')
    textures = ('base_color_texture', 'roughness_texture', 'metallic_texture',
                'normal_texture', 'emission_texture', 'transmission_texture')
    result = []
    for record in records:
        values = {}
        for field in fields:
            value = getattr(record.material, field)
            values[field] = (list(map(float, value)) if isinstance(value, (list, tuple))
                             else value.tolist() if hasattr(value, 'tolist') else float(value))
        for field in textures:
            if getattr(record.material, field, None) is not None:
                raise ValueError('Unexpected texture in the audited primitive Pipette')
            values[field] = None
        result.append(values)
    return result


def pipette_native_state(bundle, sapien):
    """Read-only native asset baseline; task-specific drive/materials are not applied."""
    import numpy as np
    actor = bundle.actor
    links = actor.get_links()
    if {link.entity.name for link in links} != {'base', 'tip', 'plunger'}:
        raise RuntimeError('Native Pipette links differ from the reviewed URDF')
    by_name = {link.entity.name: link for link in links}
    if not np.allclose(by_name['plunger'].entity.pose.p-by_name['base'].entity.pose.p,
                       [0., 0., .075], atol=1e-7):
        raise RuntimeError('Native Pipette zero-qpos forward kinematics is not synchronized')
    active = actor.get_active_joints()
    if (len(active) != 1 or active[0].get_name() != 'plunger_joint'
            or active[0].get_type() != 'prismatic' or actor.get_dof() != 1
            or not np.allclose(active[0].get_limits(), [[0., .015]], atol=1e-8)):
        raise RuntimeError('Native Pipette active joint changed')
    base = bundle.links['base'].visual_records
    if (not np.isclose(base[0].length, .08) or not np.allclose(base[0].pose.p, [0., 0., .02])
            or not np.isclose(base[1].pose.p[2], .1)
            or not np.isclose(bundle.links['plunger'].joint_record.pose_in_parent.p[2], .075)):
        raise RuntimeError('Expected the task grip extension exactly once')
    details = []
    for link in links:
        body = link.entity.find_component_by_type(sapien.render.RenderBodyComponent)
        details.append({'link': link.entity.name, 'mass_kg': float(link.get_mass()),
                        'pose_p': link.entity.pose.p.tolist(), 'pose_q': link.entity.pose.q.tolist(),
                        'visual_count': len(body.render_shapes) if body is not None else 0,
                        'collision_count': len(link.get_collision_shapes()),
                        'collision_local_poses': [{'p': shape.local_pose.p.tolist(), 'q': shape.local_pose.q.tolist()}
                                                   for shape in link.get_collision_shapes()]})
    if sum(row['visual_count'] for row in details) != 6 or sum(row['collision_count'] for row in details) != 6:
        raise RuntimeError('Native Pipette shape counts changed')
    pose = actor.get_root_pose()
    return {'scope': 'Native asset baseline; no task-specific drive/friction/material application',
            'links': details, 'qpos': actor.get_qpos().tolist(), 'qvel': actor.get_qvel().tolist(),
            'root_p': pose.p.tolist(), 'root_q': pose.q.tolist(),
            'root_linear_velocity': actor.root_linear_velocity.tolist(),
            'root_angular_velocity': actor.root_angular_velocity.tolist(),
            'active_joints': [{'name': joint.get_name(), 'type': joint.get_type(),
                                'limits': joint.get_limits().tolist()} for joint in active]}


def optical_probe(sapien, scene, camera, body, records, key, catalog, output, size, pose_fn):
    """Full-frame stripe target, with a board-only calibration at the same camera."""
    import numpy as np
    from PIL import Image
    from pipette_preview_materials import apply_records, restore_records, snapshot_records

    saved_pose = camera.entity.pose
    native = snapshot_records(records)
    middle = .015 if key == 'sample_cup' else .09
    direction = [1., -1.6, 0.]
    camera.entity.pose = pose_fn(sapien, [0., 0., middle], .14 if key == 'sample_cup' else .18, direction)
    toward = np.array(direction[:2])/np.linalg.norm(direction[:2])
    lateral = np.array([-toward[1], toward[0]])
    yaw = math.atan2(lateral[1], lateral[0])
    builder = scene.create_actor_builder()
    width, height = (.008, .06) if key == 'sample_cup' else (.004, .24)
    for index in range(-18, 19):
        point = -toward*.09+lateral*index*width
        material = sapien.render.RenderMaterial(base_color=([.03]*3 if index % 2 else [.95]*3)+[1.], roughness=1.)
        builder.add_box_visual(half_size=[width/2, .001, height/2],
                               pose=sapien.Pose(p=[*point, middle], q=[math.cos(yaw/2), 0, 0, math.sin(yaw/2)]),
                               material=material)
    board = builder.build_kinematic(name='pipette_optical_test_stripes')
    body.visibility = 0.
    reference = capture_rgb(scene, camera, size)
    Image.fromarray(reference).save(output/f'{key}_optical_board_reference.png')
    body.visibility = 1.
    half_width, half_height = (.026, .006) if key == 'sample_cup' else (.005, .05)
    points = [np.r_[lateral*x, middle+z, 1.] for x in (-half_width, half_width)
              for z in (-half_height, half_height)]
    projection = camera.get_intrinsic_matrix()@camera.get_extrinsic_matrix()
    projected = np.array([projection@point for point in points])
    if not np.isfinite(projected).all() or np.any(projected[:, 2] <= 0):
        raise RuntimeError('Optical measurement target is behind the camera or nonfinite')
    uv = projected[:, :2]/projected[:, 2:]
    x0, y0 = np.floor(uv.min(axis=0)).astype(int)
    x1, y1 = np.ceil(uv.max(axis=0)).astype(int)
    if not (0 <= x0 < x1 <= size and 0 <= y0 < y1 <= size):
        raise RuntimeError('Optical measurement ROI is empty or outside the full frame')
    roi = (slice(y0, y1), slice(x0, x1))
    results, frames = [], []
    for scheme in ('original', *catalog['candidate_ids']):
        restore_records(native)
        apply_records(records, key, scheme, catalog)
        rgb = capture_rgb(scene, camera, size)
        Image.fromarray(rgb).save(output/f'{key}_optical_{scheme}.png')
        frames.append(rgb)
        gray = rgb[roi].mean(axis=2).astype(float)
        target = reference[roi].mean(axis=2).astype(float)
        if gray.std() <= 1e-8 or target.std() <= 1e-8:
            raise RuntimeError('Optical measurement ROI has no contrast')
        ratio = float(gray.std()/target.std())
        correlation = float(np.corrcoef(gray.ravel(), target.ravel())[0, 1])
        if not np.isfinite([ratio, correlation]).all():
            raise RuntimeError('Optical measurement is nonfinite')
        results.append({'scheme_id': scheme, 'contrast_ratio': ratio, 'stripe_correlation': correlation})
    for result in results[1:]:
        if result['contrast_ratio'] < .25 or result['stripe_correlation'] < .95:
            raise RuntimeError(f'{key}/{result["scheme_id"]}: through-wall target not readable')
    Image.fromarray(np.concatenate(frames, axis=1)).save(output/f'{key}_optical_comparison.png')
    restore_records(native)
    camera.entity.pose = saved_pose
    scene.remove_entity(board)
    return {'scope': 'Fixed stripe test scene; no liquid geometry', 'shader_pack': 'default',
            'measurement_roi_xyxy': [int(x0), int(y0), int(x1), int(y1)], 'schemes': results}


def depth_probe(sapien, scene, camera, tip_id, tip_record, bias, output, key, size, pose_fn):
    """Compare depth priority over a +/-0.5 degree orbit plus two distinct views."""
    import numpy as np
    from PIL import Image

    saved_pose = camera.entity.pose
    results, trajectory = [], []
    angles = (-.5, -.25, 0., .25, .5)
    views = [[math.cos(math.radians(a))-1.6*math.sin(math.radians(a)),
              math.sin(math.radians(a))+1.6*math.cos(math.radians(a)), 1.05] for a in angles]
    views += [[1., -1.6, 1.05], [-1., 1.6, .5]]
    radius = float(tip_record.radius)
    cap_center = np.asarray(tip_record.pose.p, dtype=float)
    cap_z = float(cap_center[2]+tip_record.length)
    for view, direction in enumerate(views):
        camera.entity.pose = pose_fn(sapien, [0., 0., .012], .095, direction)
        captures = []
        for value in (0., bias):
            camera.set_property('pipetteDepthBias', float(value))
            rgb = capture_rgb(scene, camera, size)
            name = f'{key}_depth_view{view}_{"native" if value == 0 else "fixed"}.png'
            Image.fromarray(rgb).save(output/name)
            captures.append((rgb, np.asarray(camera.get_picture('Segmentation'))[..., 0].copy(),
                             np.asarray(camera.get_picture('Position')).copy(),
                             np.asarray(camera.get_picture('PositionRaw')).copy(),
                             np.asarray(camera.get_picture('GbufferDepth')).copy()))
        before, after = captures
        first, second = before[1] == tip_id, after[1] == tip_id
        common, outside = first & second, ~(first | second)
        if not common.any() or not outside.any():
            raise RuntimeError('Missing target or control pixels in depth probe')
        world = after[3]@camera.get_model_matrix().T
        interior = ((world[..., 0]-cap_center[0])**2+(world[..., 1]-cap_center[1])**2 < (radius-.005)**2)
        interior &= np.abs(world[..., 2]-cap_z) < 1e-6
        if interior.sum() < 100:
            raise RuntimeError('Expected cap interior could not be located from PositionRaw')
        depth_delta = after[4][common]-before[4][common]
        position_w_delta = after[2][common, 3]-before[2][common, 3]
        result = {
            'view': view, 'camera_direction': direction, 'native_tip_pixels': int(first.sum()),
            'orbit_degrees': angles[view] if view < len(angles) else None,
            'camera_eye_m': list(map(float, camera.entity.pose.p)),
            'fixed_tip_pixels': int(second.sum()),
            'cap_interior_expected_pixels': int(interior.sum()),
            'native_cap_interior_missing_pixels': int((interior & ~first).sum()),
            'fixed_cap_interior_missing_pixels': int((interior & ~second).sum()),
            'rgb_changed_pixels_outside_tip_union': int(np.any(before[0] != after[0], axis=2)[outside].sum()),
            'position_xyz_max_abs_delta_common_tip': float(np.max(np.abs(after[2][common, :3]-before[2][common, :3]))),
            'position_raw_max_abs_delta_common_tip': float(np.max(np.abs(after[3][common]-before[3][common]))),
            'depth_delta_common_tip_min_max': [float(depth_delta.min()), float(depth_delta.max())],
            'position_w_ndc_delta_common_tip_min_max': [float(position_w_delta.min()), float(position_w_delta.max())],
            'depth_max_abs_delta_outside_tip_union': float(np.max(np.abs(after[4][outside]-before[4][outside]))),
        }
        if (result['fixed_cap_interior_missing_pixels'] or result['rgb_changed_pixels_outside_tip_union'] or result['depth_max_abs_delta_outside_tip_union']
                or result['position_xyz_max_abs_delta_common_tip'] or result['position_raw_max_abs_delta_common_tip']
                or np.max(np.abs(depth_delta+bias)) > 1e-7 or np.max(np.abs(position_w_delta-depth_delta)) > 1e-7):
            raise RuntimeError(f'Tip depth-bias isolation failed: {result}')
        pair = Image.fromarray(np.concatenate([before[0], after[0]], axis=1))
        pair.save(output/f'{key}_depth_view{view}_comparison.png')
        if view < len(angles):
            trajectory.append(pair)
        results.append(result)
    trajectory[0].save(output/f'{key}_depth_trajectory_comparison.gif', save_all=True,
                        append_images=trajectory[1:], duration=300, loop=0)
    camera.set_property('pipetteDepthBias', float(bias))
    camera.entity.pose = saved_pose
    return {'scope': 'Fragment depth change only; world/view positions remain unchanged',
            'tip_render_id': int(tip_id), 'bias_ndc': bias,
            'position_semantics': 'Position.xyz/PositionRaw are unchanged view-space positions; Position.w is biased NDC depth',
            'views': results}
