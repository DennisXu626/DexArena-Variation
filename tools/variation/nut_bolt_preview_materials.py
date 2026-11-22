"""Read back formal Nut & Bolt bindings and inspect native scene invariants."""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'assets/appearance/objects/nut_bolt'
FIELDS = ('base_color', 'roughness', 'metallic')
MATERIAL_FIELDS = FIELDS + (
    'specular', 'emission', 'transmission', 'ior', 'transmission_roughness',
    'base_color_texture', 'roughness_texture', 'metallic_texture',
    'normal_texture', 'emission_texture', 'transmission_texture',
)
TASKS = {name: f'NutBolt{name}-Sharpa-v1' for name in ('PickBolt', 'SeatNut', 'TurnNut')}
SCHEMES = tuple(json.loads((ROOT / 'tasks/assets/variation/nut_bolt/v1/catalog.json')
                           .read_text(encoding='utf-8'))['schemes'])


def catalogs():
    return {name: json.loads((BASE / name / 'variants/v1/catalog.json').read_text(encoding='utf-8'))
            for name in ('bolt', 'nut')}


def plain(value):
    if hasattr(value, 'detach'):
        return plain(value.detach().cpu().tolist())
    if hasattr(value, 'tolist'):
        return plain(value.tolist())
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, float) and not __import__('math').isfinite(value):
        return str(value)
    return value


def material_state(material):
    result = {}
    for field in MATERIAL_FIELDS:
        if not hasattr(material, field):
            continue
        value = getattr(material, field)
        if field.endswith('_texture'):
            value = None if value is None else {
                key: plain(getattr(value, key))
                for key in ('filename', 'width', 'height', 'format', 'mipmap_levels')
                if hasattr(value, key)}
        result[field] = plain(value)
    return result


def role_order(object_id, representation):
    from tasks.nut_bolt.appearance import role_order as runtime_roles
    if representation not in ('free', 'threaded'):
        raise ValueError(representation)
    return runtime_roles(object_id)


def _entity(handle):
    raw, = handle._objs
    return getattr(raw, 'entity', raw)


def _check_shape(base, shape, object_id, index):
    from tasks.nut_bolt.appearance import check_shape
    return check_shape(base, shape, object_id, index)


def bind(env, task):
    import sapien.render as sr

    base = env.unwrapped
    if task not in TASKS or base.num_envs != 1 or base.gpu_sim_enabled:
        raise ValueError('Preview inspection supports declared short tasks, physx_cpu, num_envs=1')
    targets = [('bolt', 'free', base.bolt)]
    if task != 'PickBolt':
        targets += [('nut', 'free', base.nut), ('nut', 'threaded', base.threaded_nut)]
    rows = []
    for object_id, representation, handle in targets:
        entity = _entity(handle)
        body = entity.find_component_by_type(sr.RenderBodyComponent)
        roles = role_order(object_id, representation)
        if body is None or len(body.render_shapes) != len(roles):
            raise RuntimeError(f'Unexpected render shapes: {object_id}/{representation}')
        for index, (shape, role) in enumerate(zip(body.render_shapes, roles)):
            _check_shape(base, shape, object_id, index)
            if len(shape.parts) != 1:
                raise RuntimeError('Unexpected material-part count')
            material = shape.parts[0].material
            rows.append(dict(object_id=object_id, representation=representation,
                             shape_index=index, role=role, entity=entity,
                             material=material, native=material_state(material),
                             restore={field: copy.deepcopy(getattr(material, field)) for field in FIELDS}))
    # A material may not alias another role, representation or any scene body.
    target_materials = [row['material'] for row in rows]
    for i, material in enumerate(target_materials):
        if any(material == other for other in target_materials[:i]):
            raise RuntimeError('Private object materials alias')
    counts = [0] * len(rows)
    for sub_scene in base.scene.sub_scenes:
        for entity in sub_scene.get_entities():
            body = entity.find_component_by_type(sr.RenderBodyComponent)
            if body is not None:
                for shape in body.render_shapes:
                    for part in shape.parts:
                        for i, material in enumerate(target_materials):
                            if part.material == material:
                                counts[i] += 1
    if any(count != 1 for count in counts):
        raise RuntimeError('Object material is shared outside its bound part')
    return rows


def readback(rows, definition, scheme):
    if scheme not in SCHEMES:
        raise ValueError(scheme)
    observed = []
    for row in rows:
        actual = material_state(row['material'])
        target = definition[row['object_id']]['schemes'][scheme].get('roles', {}).get(row['role'], row['restore'])
        for field in FIELDS:
            left, right = actual[field], target[field]
            if not isinstance(left, list):
                left, right = [left], [right]
            if any(abs(a - b) > 2e-6 for a, b in zip(left, right)):
                raise RuntimeError(f'Material readback mismatch: {row["role"]}/{field}')
        observed.append({key: row[key] for key in ('object_id', 'representation', 'shape_index', 'role')}
                        | {'material': actual})
    return observed


def _pose(pose):
    return dict(p=plain(pose.p), q_wxyz=plain(pose.q))


def _array(value):
    import numpy as np
    array = np.ascontiguousarray(value)
    return dict(shape=list(array.shape), dtype=str(array.dtype),
                sha256=hashlib.sha256(array.tobytes()).hexdigest())


def _geometry(shape):
    result = dict(type=type(shape).__name__, local_pose=_pose(shape.local_pose))
    for field in ('half_size', 'scale', 'radius', 'half_length', 'front_face'):
        if hasattr(shape, field):
            result[field] = plain(getattr(shape, field))
    if hasattr(shape, 'parts'):
        result['parts'] = [{field: _array(getattr(part, field)) for field in ('vertices', 'triangles')}
                           | {'normal': _array(part.get_vertex_normal()), 'uv': _array(part.get_vertex_uv())}
                           for part in shape.parts]
    elif hasattr(shape, 'vertices'):
        result['vertices'] = _array(shape.vertices)
        result['triangles'] = _array(shape.triangles)
    return result


def snapshot(env, rows):
    """Read scene geometry/UV, physics, visibility and all noneditable fields."""
    import sapien.render as sr
    import sapien.physx as px

    base = env.unwrapped
    definition = catalogs()
    entities = []
    for sub_scene in base.scene.sub_scenes:
        for entity in sub_scene.get_entities():
            entry = dict(name=entity.name, pose=_pose(entity.pose), render=None, physics=[])
            body = entity.find_component_by_type(sr.RenderBodyComponent)
            if body is not None:
                shapes = []
                for shape in body.render_shapes:
                    materials = []
                    for part in shape.parts:
                        state = material_state(part.material)
                        match = next((row for row in rows if row['material'] == part.material), None)
                        editable = match and match['role'] in definition[match['object_id']]['schemes']['variant_1']['roles']
                        if editable:
                            state = {key: value for key, value in state.items() if key not in FIELDS}
                        materials.append(state)
                    shapes.append(dict(geometry=_geometry(shape), materials=materials))
                entry['render'] = dict(visibility=plain(body.visibility), shapes=shapes)
            for component in entity.components:
                if not isinstance(component, px.PhysxRigidBaseComponent):
                    continue
                physics = dict(type=type(component).__name__, shapes=[])
                for field in ('mass', 'inertia', 'cmass_local_pose', 'linear_velocity', 'angular_velocity',
                              'linear_damping', 'angular_damping', 'kinematic', 'disable_gravity'):
                    if hasattr(component, field):
                        value = getattr(component, field)
                        physics[field] = _pose(value) if field.endswith('_pose') else plain(value)
                if hasattr(component, 'get_locked_motion_axes'):
                    physics['locked_axes'] = plain(component.get_locked_motion_axes())
                for shape in component.get_collision_shapes():
                    physical_material = shape.get_physical_material()
                    physics['shapes'].append(dict(
                        geometry=_geometry(shape), collision_groups=plain(shape.get_collision_groups()),
                        material={key: plain(getattr(physical_material, key)) for key in
                                  ('static_friction', 'dynamic_friction', 'restitution')},
                        **{key: plain(getattr(shape, key)) for key in ('contact_offset', 'rest_offset')
                           if hasattr(shape, key)}))
                entry['physics'].append(physics)
            entities.append(entry)
    articulations = {}
    for name, articulation in base.scene.articulations.items():
        raw, = articulation._objs
        joints = []
        for joint in raw.joints:
            row = dict(name=joint.name, type=joint.type, dof=joint.dof)
            if joint.parent_link is not None:
                row.update(pose_in_parent=_pose(joint.pose_in_parent), pose_in_child=_pose(joint.pose_in_child))
            if joint.dof:
                for field in ('limits', 'friction', 'max_velocity', 'armature', 'stiffness', 'damping',
                              'force_limit', 'drive_mode', 'drive_target', 'drive_velocity_target'):
                    row[field] = plain(getattr(joint, field))
            joints.append(row)
        articulations[name] = dict(qpos=plain(articulation.get_qpos()), qvel=plain(articulation.get_qvel()),
                                   root_joint_type=raw.root.joint.type, joints=joints)
    return dict(entities=entities, articulations=articulations, state=plain(base.get_state_dict()),
                task_masks={key: plain(getattr(base, key)) for key in
                            ('_bolt_locked', '_nut_engaged', '_nut_vis_state', '_stage_bolt_placed', '_stage_nut_placed')
                            if hasattr(base, key)})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()
