"""Check the three Furniture Assembly appearance interfaces.

--static uses only the standard library. Runtime requires explicit intent and a
fresh output directory. CPU checks use one environment without image readback;
CUDA checks use two environments and the task's existing cameras, including two
control steps per task. No training, new cameras or constructed task success.
Save the first failure and stop.
"""
import argparse
import ast
import copy
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
CATALOG = ROOT / 'tasks/assets/variation/furniture_assembly/v1/catalog.json'
ADAPTER = 'tasks/furniture_assembly/appearance.py'
FINISHES = 'tasks/furniture_assembly/finishes.py'
RESET_SCOPE = 'tasks/furniture_assembly/reset_scope.py'
IMPEDANCE = 'tasks/robots/franka_joint_impedance_controller.py'
TASKS = {
    'LayFlatPanel': 'tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py',
    'InsertRail': 'tasks/furniture_assembly/furniture_assembly_insert_rail.py',
    'FastenScrew': 'tasks/furniture_assembly/furniture_assembly_fasten_screw.py',
}
SCHEMES = tuple(json.loads(CATALOG.read_text(encoding='utf-8'))['schemes'])
FIELDS = ('base_color', 'roughness', 'metallic')
MATERIAL_FIELDS = FIELDS + ('specular', 'emission', 'ior', 'transmission',
    'transmission_roughness', 'base_color_texture', 'roughness_texture',
    'metallic_texture', 'normal_texture', 'emission_texture', 'transmission_texture')


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def git(*arguments):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(),
        '-C', str(ROOT), *arguments], text=True, encoding='utf-8').strip()


def protected_scheme_fields(scheme):
    """Ignore editable PBR values while retaining the alpha and role structure."""
    protected = {}
    for key, value in scheme.items():
        if key in ('label', 'surface'):
            continue
        if key == 'base_color':
            protected[key] = value[3:]
        elif key == 'roughness' and isinstance(value, dict):
            protected[key] = sorted(value)
        elif key in ('roughness', 'metallic'):
            protected[key] = None
        elif isinstance(value, dict):
            protected[key] = protected_scheme_fields(value)
        else:
            protected[key] = value
    return protected


def static_check(baseline):
    catalog = read(CATALOG)
    assert catalog['version'] == 'furniture-appearance-v2'
    assert catalog['scope'] == 'material_appearance'
    assert tuple(catalog['schemes']) == SCHEMES
    assert SCHEMES[:3] == ('original', 'variant_1', 'variant_2')
    assert len(SCHEMES) == len(set(SCHEMES))
    released = '56a4aec4740b7139307e01048fa0e8e6ed430f14'
    released_index = json.loads(git('show', f'{released}:{CATALOG.relative_to(ROOT).as_posix()}'))
    assert catalog['tasks'] == released_index['tasks']
    sources = [ADAPTER, FINISHES, RESET_SCOPE, IMPEDANCE, 'tools/variation/check_furniture_appearance.py', *TASKS.values()]
    for source in sources:
        ast.parse((ROOT / source).read_text(encoding='utf-8'), filename=source)
    for object_id, entry in catalog['objects'].items():
        path = (ROOT / entry['catalog']).resolve()
        assert path.is_relative_to(ROOT.resolve()), entry
        obj = read(path)
        old_entry = released_index['objects'][object_id]
        old_obj = json.loads(git('show', f"{released}:{old_entry['catalog']}"))
        assert obj['object_id'].split('.')[-1] == object_id, object_id
        assert set(entry['scheme_map']) == set(SCHEMES), object_id
        assert entry['scheme_map']['original'] == 'original', object_id
        assert len(set(entry['scheme_map'].values())) == len(SCHEMES), object_id
        assert set(entry['scheme_map'].values()) == set(obj['schemes']), object_id
        assert entry['catalog'] == old_entry['catalog'], object_id
        assert all(entry['scheme_map'][key] == value for key, value in old_entry['scheme_map'].items()), object_id
        assert obj['schemes']['original'] == old_obj['schemes']['original'], object_id
        protected = set(old_obj) - {'schemes', 'scheme_descriptions', 'preserve_properties'}
        assert all(obj[key] == old_obj[key] for key in protected), object_id
        if object_id == 'flat_panel':
            assert set(obj['preserve_properties']) == {
                'normal_texture', 'roughness_texture', 'metallic_texture', 'emission_texture',
                'transmission_texture', 'uv', 'specular',
            }
        else:
            assert obj.get('preserve_properties') == old_obj.get('preserve_properties'), object_id
        template = old_obj['schemes'][old_entry['scheme_map']['variant_1']]
        for scheme in SCHEMES[1:]:
            candidate = obj['schemes'][entry['scheme_map'][scheme]]
            assert protected_scheme_fields(candidate) == protected_scheme_fields(template), (object_id, scheme)
            assert candidate['label'], (object_id, scheme)
            if object_id == 'flat_panel':
                assert candidate['metallic'] == 0 and candidate['surface'], scheme
        for name, scheme in obj['schemes'].items():
            if name == 'original':
                assert scheme['mode'] == 'restore_native'
                continue
            assert scheme['mode'] == 'material_override'
            roles = scheme.get('roles')
            if roles is None:
                roles = {role: {'base_color': scheme['base_color'], 'roughness': value,
                               'metallic': scheme['metallic']}
                         for role, value in scheme['roughness'].items()}
                assert set(obj['color_factors']) == set(roles)
                assert all(0 < value <= 1 for value in obj['color_factors'].values())
            for params in roles.values():
                assert len(params['base_color']) == 4
                assert all(0 <= value <= 1 for value in params['base_color'])
                assert params['base_color'][3] == 1
                assert all(0 <= params[key] <= 1 for key in ('roughness', 'metallic'))
    unchanged, scope_normalizations = {}, {}
    protected = {'_task_quantities', 'evaluate', '_get_obs_extra',
                 'compute_dense_reward', 'compute_normalized_dense_reward'}
    for task, filename in TASKS.items():
        assert set(catalog['tasks'][task]) <= set(catalog['objects']), task
        current = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
        previous = ast.parse(git('show', baseline + ':' + filename))
        class NormalizeScope(ast.NodeTransformer):
            def visit_Call(self, node):
                node = self.generic_visit(node)
                if not isinstance(node.func, ast.Attribute) or ast.unparse(node.func.value) != 'self':
                    return node
                if node.func.attr == '_reset_scoped_value':
                    assert len(node.args) == 2 and not node.keywords
                    expected_counter = 'self.success_counter' if task == 'FastenScrew' else 'self.settle_counter'
                    assert ast.unparse(node.args[0]) == expected_counter
                    counts['value'] += 1
                    return node.args[1]
                if node.func.attr == '_reset_scoped_predicate':
                    assert len(node.args) == 1 and not node.keywords
                    counts['predicate'] += 1
                    return node.args[0]
                return node
        normalized_counts = []
        for tree in (current, previous):
            counts = {'value': 0, 'predicate': 0}
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name in protected:
                    NormalizeScope().visit(node)
            normalized_counts.append(counts)
        counts, previous_counts = normalized_counts
        expected_counts = {'LayFlatPanel': (1, 2), 'InsertRail': (1, 3), 'FastenScrew': (1, 0)}[task]
        assert tuple(counts.values()) == expected_counts, (task, counts)
        assert tuple(previous_counts.values()) in ((0, 0), expected_counts), (task, previous_counts)
        methods = lambda tree: {node.name: ast.dump(node, include_attributes=False)
            for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in protected}
        assert methods(current) == methods(previous), f'{task}: task judgment/reward AST changed'
        unchanged[task] = sorted(methods(current))
        scope_normalizations[task] = counts
        assert 'furniture_appearance' in (ROOT / filename).read_text(encoding='utf-8'), task
    long_file = ROOT / 'tasks/furniture_assembly/furniture_assembly_long.py'
    if long_file.exists():
        assert long_file.read_text(encoding='utf-8').strip() == git(
            'show', baseline + ':' + long_file.relative_to(ROOT).as_posix())
    impedance = ast.parse((ROOT / IMPEDANCE).read_text(encoding='utf-8'))
    old_impedance = ast.parse(git('show', baseline + ':' + IMPEDANCE))
    authorized_reset = ast.parse('''if getattr(self, "_target_qpos", None) is None:
    self._target_qpos = self.qpos.clone()
else:
    mask = self.scene._reset_mask
    self._target_qpos[mask] = self.qpos[mask].clone()
''').body[0]
    native_assignment = ast.parse('self._target_qpos = self.qpos.clone()').body[0]
    def normalize_impedance(tree):
        found, scoped = 0, 0
        for cls in tree.body:
            if isinstance(cls, ast.ClassDef) and cls.name == 'FrankaJointImpedanceController':
                for method in cls.body:
                    if isinstance(method, ast.FunctionDef) and method.name == 'reset':
                        found += 1
                        assignment = ast.dump(method.body[1], include_attributes=False)
                        if assignment == ast.dump(authorized_reset, include_attributes=False):
                            method.body[1] = copy.deepcopy(native_assignment)
                            scoped += 1
                        else:
                            assert assignment == ast.dump(native_assignment, include_attributes=False), \
                                'Unexpected impedance reset change'
        assert found == 1
        return scoped

    normalized_impedance = normalize_impedance(impedance)
    normalize_impedance(old_impedance)
    assert normalized_impedance == 1
    assert ast.dump(impedance, include_attributes=False) == ast.dump(old_impedance, include_attributes=False), \
        'Impedance source changed outside the scoped reset assignment'
    examples = [ROOT / 'examples/variation/furniture_assembly' / name
                for name in ('default.json', 'fixed.json', 'random.json')]
    for path in examples:
        example = read(path)
        assert example['task_id'] in [f'FurnitureAssembly{task}-Sharpa-v1' for task in TASKS], path
        assert isinstance(example['furniture_appearance']['enabled'], bool), path
    return {'status': 'passed', 'baseline': baseline, 'catalog_version': catalog['version'],
            'objects': sorted(catalog['objects']), 'schemes': list(SCHEMES), 'protected_task_methods': unchanged,
            'reset_scope_normalizations': scope_normalizations,
            'impedance_reset_normalizations': normalized_impedance,
            'examples': len(examples), 'physics_steps': 0, 'runtime': 'NOT TESTED'}


def plain(value):
    if hasattr(value, 'detach'):
        return plain(value.detach().cpu().numpy())
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def leaves(value, prefix=''):
    if isinstance(value, dict):
        return {path: item for key, child in value.items()
                for path, item in leaves(child, prefix + '/' + str(key)).items()}
    return {prefix: value}


def snapshot(base):
    values = {'state': base.get_state_dict(), 'elapsed_steps': base._elapsed_steps,
              'joint_targets': joint_targets(base)}
    return {path: value.detach().cpu().clone() for path, value in leaves(values).items()
            if torch.is_tensor(value)}


def state_changes(before, after, indices=None):
    assert set(before) == set(after), 'State fields changed'
    changes = {}
    for path, value in before.items():
        other = after[path]
        if indices is not None:
            assert value.ndim and value.shape[0] == other.shape[0] == 2, path
            value, other = value[indices], other[indices]
        if not torch.equal(value, other):
            error = float((value.double() - other.double()).abs().max())
            changed = value != other
            coordinates = changed.nonzero().tolist()
            row = {'max_absolute_error': error, 'shape': list(value.shape),
                   'coordinates': coordinates, 'before_values': value[changed].tolist(),
                   'after_values': other[changed].tolist()}
            if '/actors/' in path and value.shape[-1] == 13:
                columns = ('position_x', 'position_y', 'position_z', 'quaternion_w',
                    'quaternion_x', 'quaternion_y', 'quaternion_z', 'linear_velocity_x',
                    'linear_velocity_y', 'linear_velocity_z', 'angular_velocity_x',
                    'angular_velocity_y', 'angular_velocity_z')
                row['components'] = [columns[index[-1]] for index in coordinates]
            changes[path] = row
    return changes


def articulations(base):
    items = {'robot': base.agent.robot}
    if hasattr(base, 'rail') and hasattr(base.rail, 'get_active_joints'):
        items['rail'] = base.rail
    return items


def joint_targets(base):
    return {name: {'qpos': art.get_qpos(), 'qvel': art.get_qvel(),
                   'qf': art.get_qf(),
                   'position_target': art.get_drive_targets(),
                   'velocity_target': art.get_drive_velocities()}
            for name, art in articulations(base).items()}


def texture_values(texture):
    if texture is None:
        return None
    filename = Path(texture.filename) if texture.filename else None
    return {'name': filename.name if filename else '', 'width': texture.width,
            'height': texture.height, 'format': str(texture.format),
            'mipmap_levels': texture.mipmap_levels,
            'sha256': hashlib.sha256(filename.read_bytes()).hexdigest()
            if filename and filename.is_file() else None}


def material_values(material, panel_surface=None):
    values = {}
    for field in MATERIAL_FIELDS:
        value = getattr(material, field)
        if field.endswith('_texture'):
            if field == 'base_color_texture' and panel_surface is not None:
                assert value == panel_surface.texture, 'Panel albedo handle was replaced'
                pixels = value.download()
                if panel_surface.current == 'original':
                    np.testing.assert_array_equal(pixels, panel_surface.original_pixels)
                    value = texture_values(panel_surface.source)
                else:
                    value = {**texture_values(value),
                             'data_sha256': hashlib.sha256(pixels.tobytes()).hexdigest()}
            else:
                value = texture_values(value)
        values[field] = plain(value)
    return values


def material_slots(base):
    rows = []
    for scene in base.scene.sub_scenes:
        slots = []
        for entity in sorted(scene.entities, key=lambda obj: (obj.name, obj.per_scene_id)):
            body = entity.find_component_by_type(sapien.render.RenderBodyComponent)
            if body is None:
                continue
            for shape_index, shape in enumerate(body.render_shapes):
                for part_index, part in enumerate(shape.parts):
                    slots.append((entity.name, shape_index, part_index, part))
        rows.append(slots)
    return rows


def materials(base):
    adapter = base._furniture_appearance
    all_rows = []
    for env_id, slots in enumerate(material_slots(base)):
        surfaces = adapter.panel_surfaces[env_id] if adapter is not None else ()
        rows = []
        for name, shape, index, part in slots:
            material = part.material
            surface = next((surface for surface in surfaces if surface.material == material), None)
            rows.append({'entity': name, 'shape': shape, 'part': index,
                         'material': material_values(material, surface)})
        all_rows.append(rows)
    return all_rows


def verify(base, expected_ids, native):
    adapter = base._furniture_appearance
    assert adapter.schemes == expected_ids
    actual = materials(base)
    expected = copy.deepcopy(native)
    slots = material_slots(base)
    for env_id, scheme in enumerate(expected_ids):
        assert adapter.bindings[env_id], 'Missing furniture material bindings'
        for object_id, role, part, material, captured in adapter.bindings[env_id]:
            assert part.material == material, 'Bound material was replaced'
            params = adapter.scheme_parameters(object_id, scheme).get(role, captured)
            matches = [index for index, slot in enumerate(slots[env_id]) if slot[-1] == part]
            assert len(matches) == 1, (object_id, role, matches)
            index, = matches
            for key in FIELDS:
                np.testing.assert_allclose(captured[key], native[env_id][index]['material'][key], rtol=0, atol=1e-7)
                expected[env_id][index]['material'][key] = params[key]
            surface = next((surface for surface in adapter.panel_surfaces[env_id]
                            if surface.material == material), None)
            if surface is not None:
                assert object_id == 'flat_panel' and role == 'face' and surface.current == scheme
                if scheme != 'original':
                    pixels = surface.pixels(scheme, adapter.panel_finish(scheme), params['base_color'])
                    expected[env_id][index]['material']['base_color_texture'] = {
                        **texture_values(surface.texture), 'data_sha256': hashlib.sha256(pixels.tobytes()).hexdigest(),
                    }
        for observed, target in zip(actual[env_id], expected[env_id]):
            assert observed.keys() == target.keys()
            for key in FIELDS:
                np.testing.assert_allclose(observed['material'][key], target['material'][key], rtol=0, atol=1e-7)
            assert {k: v for k, v in observed['material'].items() if k not in FIELDS} == {
                k: v for k, v in target['material'].items() if k not in FIELDS}, observed['entity']
            assert {k: v for k, v in observed.items() if k != 'material'} == {
                k: v for k, v in target.items() if k != 'material'}
    assert len(adapter.records) == sum(adapter.episodes)
    for env_id, episode in enumerate(adapter.episodes):
        records = [record for record in adapter.records if record['env_idx'] == env_id]
        assert [record['episode_index'] for record in records] == list(range(1, episode + 1))
        assert records[-1]['scheme_id'] == expected_ids[env_id]
    assert all(record['catalog_version'] == adapter.catalog['version'] for record in adapter.records)
    return actual


def geometry(shape):
    row = {'type': type(shape).__name__, 'pose': [plain(shape.local_pose.p), plain(shape.local_pose.q)]}
    for name in ('half_size', 'radius', 'half_length', 'scale', 'density', 'contact_offset', 'rest_offset'):
        if hasattr(shape, name):
            row[name] = plain(getattr(shape, name))
    for name in ('vertices', 'triangles'):
        if hasattr(shape, name):
            row[name + '_sha256'] = hashlib.sha256(np.asarray(getattr(shape, name)).tobytes()).hexdigest()
    if hasattr(shape, 'parts'):
        row['meshes'] = [{name: hashlib.sha256(np.asarray(value).tobytes()).hexdigest()
            for name, value in {'vertices': part.vertices, 'triangles': part.triangles,
                                'uv': part.get_vertex_uv(), 'normal': part.get_vertex_normal()}.items()}
            for part in shape.parts]
    return row


def physical(base):
    scenes = []
    for scene in base.scene.sub_scenes:
        entities = []
        for entity in sorted(scene.entities, key=lambda obj: (obj.name, obj.per_scene_id)):
            row = {'name': entity.name, 'bodies': [], 'visuals': []}
            for component in entity.components:
                if isinstance(component, sapien.render.RenderBodyComponent):
                    row['visuals'].extend(geometry(shape) for shape in component.render_shapes)
                if isinstance(component, sapien.physx.PhysxRigidBaseComponent):
                    body = {'type': type(component).__name__, 'collision': []}
                    for name in ('mass', 'inertia', 'linear_damping', 'angular_damping', 'kinematic'):
                        if hasattr(component, name):
                            body[name] = plain(getattr(component, name))
                    if hasattr(component, 'cmass_local_pose'):
                        body['cmass'] = [plain(component.cmass_local_pose.p), plain(component.cmass_local_pose.q)]
                    for shape in component.collision_shapes:
                        collision = geometry(shape)
                        collision['groups'] = list(shape.get_collision_groups())
                        collision['material'] = [getattr(shape.physical_material, field) for field in
                                                 ('static_friction', 'dynamic_friction', 'restitution')]
                        body['collision'].append(collision)
                    row['bodies'].append(body)
            entities.append(row)
        scenes.append(entities)
    joints = {}
    for name, articulation in articulations(base).items():
        joints[name] = [[joint_signature(joint) for joint in native.get_joints()]
                       for native in articulation._objs]
    return {'scenes': scenes, 'joints': joints}


def joint_signature(joint):
    row = {'name': joint.name, 'type': joint.type, 'dof': joint.dof,
           'pose_in_parent': [plain(joint.pose_in_parent.p), plain(joint.pose_in_parent.q)],
           'pose_in_child': [plain(joint.pose_in_child.p), plain(joint.pose_in_child.q)]}
    if joint.dof:
        row.update({field: plain(getattr(joint, field)) for field in
                    ('limits', 'friction', 'stiffness', 'damping', 'force_limit', 'drive_mode')})
    return row


def capture(env, info, native_readback=False):
    base = env.unwrapped
    if native_readback:
        assert platform.system() == 'Windows' and base.scene.gpu_sim_enabled
        # Use the existing native cameras and their own projection/size. GPU
        # physics stays batched; only the Color readback goes through the CPU.
        base.scene.px.sync_poses_gpu_to_cpu()
        for scene in base.scene.sub_scenes:
            scene.update_render()
        images = {}
        cameras = {**base._sensors, **{'human__' + name: camera
                   for name, camera in base.scene.human_render_cameras.items()}}
        for name, sensor in cameras.items():
            frames = []
            for camera in sensor.camera._render_cameras:
                camera.take_picture()
                pixels = np.asarray(camera.get_picture('Color')).copy()[..., :3]
                assert pixels.shape == (camera.height, camera.width, 3), name
                assert np.isfinite(pixels).all() and np.ptp(pixels) > 0, name
                if np.issubdtype(pixels.dtype, np.floating):
                    pixels = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
                assert pixels.dtype == np.uint8, (name, pixels.dtype)
                frames.append(pixels)
            assert len(frames) == base.num_envs, name
            images[name] = np.stack(frames)
        return validate_images(images, base.num_envs)
    observation = base.get_obs(info=info)
    images = {name: values['rgb'].detach().cpu().numpy().copy()
              for name, values in observation['sensor_data'].items()}
    images['human'] = env.render().detach().cpu().numpy().copy()
    return validate_images(images, base.num_envs)


def validate_images(images, num_envs):
    assert images and any(not name.startswith('human') for name in images), 'Missing task cameras'
    for name, pixels in images.items():
        assert pixels.ndim == 4 and pixels.shape[0] == num_envs and pixels.shape[-1] == 3, (name, pixels.shape)
        assert pixels.shape[1] > 0 and pixels.shape[2] > 0 and pixels.dtype == np.uint8, (name, pixels.shape, pixels.dtype)
        for frame in pixels:
            assert np.isfinite(frame).all() and np.any(frame != frame[0, 0]), f'{name}: invalid or constant RGB frame'
    from tools.variation.sapien_sdk.linux_render_receipt import record_render_readback

    record_render_readback()
    return images


def controller_state(base, env_id):
    """Include PD controller internals omitted by its public get_state()."""
    values = {}

    def select(value):
        if hasattr(value, 'raw_pose'):
            value = value.raw_pose
        if torch.is_tensor(value) or isinstance(value, np.ndarray):
            if value.ndim and value.shape[0] == base.num_envs:
                value = value[env_id]
            return plain(value)
        if isinstance(value, dict):
            return {str(key): select(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [select(item) for item in value]
        assert value is None or isinstance(value, (str, bool, int, float)), type(value)
        return value

    def visit(controller, path):
        row = {'type': type(controller).__name__, 'public_state': select(controller.get_state())}
        for name in ('_start_qpos', '_target_qpos', '_step_size', '_step', '_start_pose', '_target_pose'):
            if hasattr(controller, name):
                if name == '_step' and not getattr(controller.config, 'interpolate', False):
                    row['_step_scope'] = 'shared counter; interpolation disabled; excluded from environment state'
                    continue
                row[name] = select(getattr(controller, name))
        values[path] = row
        for name, child in getattr(controller, 'controllers', {}).items():
            visit(child, path + '/' + name)

    visit(base.agent.controller, 'controller')
    return values


def controller_counters(base):
    values = {}

    def visit(controller, path):
        if hasattr(controller, '_step'):
            values[path] = {'value': int(controller._step), 'scope': 'shared',
                'interpolation_enabled': bool(getattr(controller.config, 'interpolate', False))}
        for name, child in getattr(controller, 'controllers', {}).items():
            visit(child, path + '/' + name)

    visit(base.agent.controller, 'controller')
    return values


def prime_controller_target(base, env_id=0):
    """Set a legal nontrivial action through the real controller without stepping."""
    controller = base.agent.controller
    space = controller.single_action_space
    assert isinstance(space, gym.spaces.Box), 'Expected a flat joint-position action space'
    assert np.isfinite(space.low).all() and np.isfinite(space.high).all()
    low = torch.as_tensor(space.low, device=base.device)
    high = torch.as_tensor(space.high, device=base.device)
    action = ((low + high) / 2).expand(base.num_envs, -1).clone()
    movable = ((high - low) > 1e-3).nonzero().flatten()
    assert len(movable), 'No movable controller action dimension'
    column = int(movable[0])
    action[env_id, column] += torch.minimum((high[column] - low[column]) * 0.1,
                                     torch.tensor(0.05, device=base.device))
    assert ((action >= low) & (action <= high)).all()
    before = snapshot(base)
    base.agent.set_action(action)
    if base.scene.gpu_sim_enabled:
        # Match BaseEnv's target-application path, without a simulation step or
        # applying any actor/root/qpos buffers.
        base.scene.px.gpu_apply_articulation_target_position()
        base.scene.px.gpu_apply_articulation_target_velocity()
        base.scene.px.gpu_fetch_articulation_target_qpos()
        base.scene.px.gpu_fetch_articulation_target_qvel()
    after = snapshot(base)
    physical_before = {path: value for path, value in before.items()
                       if '/state/controller/' not in path and (
                           '/joint_targets/' not in path or path.rsplit('/', 1)[-1] in ('qpos', 'qvel'))}
    physical_after = {path: after[path] for path in physical_before}
    assert not state_changes(physical_before, physical_after), 'Setting controller action changed physical state'
    targets = joint_targets(base)['robot']['position_target']
    assert not torch.equal(targets[env_id], base.agent.robot.get_qpos()[env_id]), 'Controller target is trivial'
    effects, nontrivial = {}, {}

    def describe(controller, path):
        config = getattr(controller, 'config', None)
        if hasattr(controller, '_target_qpos'):
            nontrivial[path] = not torch.equal(controller._target_qpos[env_id], controller.qpos[env_id])
        if hasattr(config, 'gpu_apply'):
            effects[path] = {'type': type(controller).__name__,
                'native_action_gpu_qf_apply': bool(base.scene.gpu_sim_enabled and config.gpu_apply),
                'native_action_gpu_qpos_fetch': bool(base.scene.gpu_sim_enabled and config.gpu_fetch)}
        for name, child in getattr(controller, 'controllers', {}).items():
            describe(child, path + '/' + name)

    describe(controller, 'controller')
    assert nontrivial and all(nontrivial.values()), 'A controller target still equals its current joint positions'
    if any(row['type'] == 'FrankaJointImpedanceController' for row in effects.values()):
        assert torch.count_nonzero(joint_targets(base)['robot']['qf'][env_id]), 'Impedance force precondition is trivial'
    return {'method': 'agent.set_action, including native impedance qf writes; native target apply/fetch; no step',
            'native_controller_effects': effects,
            f'nontrivial_targets_env{env_id}': nontrivial,
            'action': plain(action), 'physics_steps': 0, 'physical_state_unchanged': True,
            f'controller_env{env_id}': controller_state(base, env_id),
            f'generalized_forces_env{env_id}': plain(joint_targets(base)['robot']['qf'][env_id]),
            f'position_targets_env{env_id}': plain(targets[env_id])}


def task_rng(base, env_id):
    states = {}
    if hasattr(base, '_batched_episode_rng'):
        states['batched_episode_rng'] = plain(base._batched_episode_rng[env_id].get_state())
    if env_id == 0 and hasattr(base, '_episode_rng'):
        states['episode_rng_alias'] = plain(base._episode_rng.get_state())
    assert states, 'Task episode RNG state is unavailable'
    return states


def image_changes(before, after, output, prefix, env_id=0):
    assert set(before) == set(after), 'Original camera set changed'
    result = {}
    for name, images in before.items():
        image, other = images[env_id], after[name][env_id]
        assert image.shape == other.shape
        coordinates = np.argwhere(image != other)
        positions = tuple(coordinates.T)
        filename = f'{prefix}_{name}_env{env_id}_coordinates.npz'
        np.savez_compressed(output / filename, coordinates_yxc=coordinates,
                            before=image[positions], after=other[positions])
        result[name] = {'changed_values': len(coordinates),
            'changed_pixels': int(np.any(image != other, axis=-1).sum()),
            'max_absolute_error': int(np.abs(image.astype('int16') - other.astype('int16')).max()),
            'coordinates': filename,
            'samples_yxc_before_after': [list(map(int, coordinate)) +
                [int(image[tuple(coordinate)]), int(other[tuple(coordinate)])]
                for coordinate in coordinates[:20]]}
    return result


def save_image_pairs(before, after, output, prefix):
    from PIL import Image
    for name, images in before.items():
        for env_id, image in enumerate(images):
            Image.fromarray(np.concatenate([image, after[name][env_id]], axis=1)[..., :3]).save(
                output / f'{prefix}_{name}_env{env_id}.png')


def selected_reset_check(env, seed, options, output, prefix, report):
    """Compare reset's buffered intent with its first PhysX readback."""
    base = env.unwrapped
    scene = base.scene
    assert base.scene.gpu_sim_enabled
    options = {} if options is None else options
    assert 'reset_to_env_states' not in options, 'State replay skips episode initialization'
    selected = options.get('env_idx', range(base.num_envs))
    selected = [int(index) % base.num_envs for index in selected]
    assert selected and len(set(selected)) == len(selected)
    saved = {'before': snapshot(base)}
    missing = object()
    previous_initialize = vars(base).get('_initialize_episode', missing)
    previous_fetch = vars(scene).get('_gpu_fetch_all', missing)
    initialize, fetch = base._initialize_episode, scene._gpu_fetch_all
    report.update(selected=selected, physics_steps=0, status='running',
        expected_capture='after native _initialize_episode',
        observed_capture='first following PhysX _gpu_fetch_all, before controller reset',
        float_absolute_tolerance=2e-6, float_relative_tolerance=0)

    def capture_intent(env_idx, reset_options):
        value = initialize(env_idx, reset_options)
        assert 'expected' not in saved, 'Episode initialization repeated'
        saved['expected'] = snapshot(base)
        return value

    def capture_readback():
        value = fetch()
        if 'expected' in saved and 'fetched' not in saved:
            saved['fetched'] = snapshot(base)
        return value

    base._initialize_episode = capture_intent
    scene._gpu_fetch_all = capture_readback
    try:
        observation, info = env.reset(seed=seed, options=options)
        saved['final'] = snapshot(base)
        assert 'expected' in saved and 'fetched' in saved, 'Missing reset intent/readback'
        expected = saved['expected']

        def physical_field(path):
            return ('/state/actors/' in path or '/state/articulations/' in path
                    or ('/joint_targets/' in path and path.rsplit('/', 1)[-1] in ('qpos', 'qvel')))

        intent_changes = state_changes(
            {path: value for path, value in saved['before'].items() if physical_field(path)},
            {path: value for path, value in expected.items() if physical_field(path)}, selected)
        report['selected_physical_intent_changes'] = intent_changes
        if len(selected) < base.num_envs:
            assert intent_changes, 'Partial reset did not exercise a new selected physical state'

        def compare(actual, physical_only=False):
            assert set(expected) == set(actual), 'Reset state fields changed'
            failures, fields = {}, []
            for path, value in expected.items():
                if physical_only and not physical_field(path):
                    continue
                other = actual[path]
                assert value.shape == other.shape and value.dtype == other.dtype, path
                assert value.ndim and value.shape[0] == base.num_envs, path
                value, other = value[selected], other[selected]
                if torch.is_floating_point(value):
                    assert torch.isfinite(value).all() and torch.isfinite(other).all(), path
                    matches = torch.isclose(value, other, rtol=0, atol=2e-6)
                else:
                    matches = value == other
                fields.append(path)
                if not matches.all():
                    changed = ~matches
                    failures[path] = {'max_absolute_error': float((value.double() - other.double()).abs().max()),
                        'coordinates': changed.nonzero().tolist(),
                        'expected_values': value[changed].tolist(), 'fetched_values': other[changed].tolist()}
            assert fields, 'No selected reset state fields checked'
            return fields, failures

        fields, failures = compare(saved['fetched'])
        final_fields, final_failures = compare(saved['final'], physical_only=True)
        report.update(checked_fields=fields, mismatches=failures,
            buffer_only_fields=[path for path in fields if path.endswith('/qf')],
            final_physical_fields=final_fields, final_physical_mismatches=final_failures)
        assert not failures and not final_failures, 'Selected reset state differs from native initialization intent'
        report['status'] = 'passed'
        return observation, info
    except BaseException:
        report['status'] = 'failed'
        raise
    finally:
        for owner, name, previous in ((base, '_initialize_episode', previous_initialize),
                                       (scene, '_gpu_fetch_all', previous_fetch)):
            if previous is missing:
                delattr(owner, name)
            else:
                setattr(owner, name, previous)
        torch.save(saved, output / f'{prefix}.pt')
        dump(output / f'{prefix}.json', report)


def native_local_control(env, info, output, reset, capture, step, *, bidirectional=False):
    """Separate capture synchronization from unselected-environment reset effects."""
    base = env.unwrapped
    initial = snapshot(base)
    first_images = capture(env, info)
    first = snapshot(base)
    repeat_images = capture(env, info)
    repeated = snapshot(base)
    diagnostic = {'first_capture_state_changes': state_changes(initial, first),
                  'repeat_capture_state_changes': state_changes(first, repeated),
                  'repeat_capture_pixel_changes': image_changes(first_images, repeat_images, output, 'native_capture')}
    if bidirectional:
        diagnostic['repeat_capture_pixel_changes_env1'] = image_changes(first_images, repeat_images, output, 'native_capture', env_id=1)
        assert all(not item['changed_values'] for item in diagnostic['repeat_capture_pixel_changes_env1'].values())
    torch.save({'before_capture': initial, 'after_first_capture': first,
                'after_repeat_capture': repeated}, output / 'native_capture_states.pt')
    save_image_pairs(first_images, repeat_images, output, 'native_capture')
    dump(output / 'native_capture_diagnostic.json', diagnostic)
    rounds = []
    for index, selected in enumerate((1, 0) if bidirectional else (1, 1)):
        frozen = 1 - selected
        primed = prime_controller_target(base, frozen)
        if index == 1:
            info = step(primed)
        before_images = capture(env, info)
        before_state, before_materials = snapshot(base), materials(base)
        before_controller = controller_state(base, frozen)
        before_counters = controller_counters(base)
        before_rng, before_physical = task_rng(base, frozen), physical(base)
        _, info = reset(options={'env_idx': torch.tensor([selected], device=base.device)})
        reset_state = snapshot(base)
        after_images = capture(env, info)
        after_state, after_materials = snapshot(base), materials(base)
        after_controller = controller_state(base, frozen)
        after_counters = controller_counters(base)
        after_rng, after_physical = task_rng(base, frozen), physical(base)
        row = {'selected': [selected], 'appearance': 'disabled', 'physics_steps': 0,
            'controller_precondition': primed,
            'precondition_control_steps': int(index == 1),
            'precondition_physics_steps': base._sim_steps_per_control if index == 1 else 0,
            f'before_controller_env{frozen}': before_controller, f'after_controller_env{frozen}': after_controller,
            'before_shared_controller_counters': before_counters, 'after_shared_controller_counters': after_counters,
            'controller_unchanged': before_controller == after_controller,
            'reset_before_capture_state_changes': state_changes(before_state, reset_state, [frozen]),
            'capture_state_changes': state_changes(reset_state, after_state, [frozen]),
            'state_changes': state_changes(before_state, after_state, [frozen]),
            'pixel_changes': image_changes(before_images, after_images, output, f'native_local_{index}', env_id=frozen),
            'before_materials': before_materials, 'after_materials': after_materials,
            f'materials_env{frozen}_unchanged': before_materials[frozen] == after_materials[frozen],
            'physical_unchanged': before_physical == after_physical,
            f'before_task_rng_env{frozen}': before_rng, f'after_task_rng_env{frozen}': after_rng,
            'task_rng_unchanged': before_rng == after_rng}
        torch.save({'before': before_state, 'after_reset_before_capture': reset_state,
                    'after_capture': after_state}, output / f'native_local_{index}.pt')
        dump(output / f'native_local_{index}.json', row)
        dump(output / f'native_local_{index}_physical.json', after_physical)
        save_image_pairs(before_images, after_images, output, f'native_local_{index}')
        rounds.append(row)
    return {'capture_diagnostic': diagnostic, 'rounds': rounds}


def run_task(task, args, output, result):
    num_envs = 2 if args.sim_backend == 'physx_cuda' else 1
    gpu = num_envs == 2
    native_readback = gpu and args.diagnostic_native_readback
    env = None
    reset_index = 0
    result.update(control_steps=0, physics_steps=0)

    def capture_images(env, info):
        return capture(env, info, native_readback=native_readback)

    def step_once(primed):
        action = torch.tensor(primed['action'], dtype=torch.float32, device=env.unwrapped.device)
        _, _, _, _, info = env.step(action)
        result['control_steps'] += 1
        result['physics_steps'] += env.unwrapped._sim_steps_per_control
        return info

    def checked_reset(seed=None, options=None):
        nonlocal reset_index
        if not gpu:
            return env.reset(seed=seed, options=options)
        report = {}
        prefix = f'selected_reset_{reset_index:02d}'
        reset_index += 1
        try:
            return selected_reset_check(env, seed, options, output, prefix, report)
        finally:
            result['checks'].setdefault('selected_reset_state', []).append(
                {'evidence': prefix + '.json', **report})

    def make(config=None, detail=True, jitter=False):
        kwargs = {} if config is None else {'furniture_appearance': config}
        if task != 'FastenScrew':
            kwargs['panel_color_jitter'] = jitter
        created = gym.make(f'FurnitureAssembly{task}-Sharpa-v1', num_envs=num_envs,
            sim_backend=args.sim_backend, reconfiguration_freq=0, visual_detail=detail,
            obs_mode='rgb' if gpu and not native_readback else 'state', render_mode='rgb_array', **kwargs)
        try:
            base = created.unwrapped
            assert base.num_envs == num_envs and base.backend.sim_backend == args.sim_backend
            assert base.device.type == ('cuda' if gpu else 'cpu')
            if gpu:
                assert base.scene.gpu_sim_enabled and base.scene._gpu_sim_initialized
            return created
        except BaseException:
            created.close()
            raise

    def close():
        nonlocal env
        if env is not None:
            env.close()
            env = None

    def reset(config=None, detail=True, jitter=False, reconfigure=False):
        nonlocal env
        env = make(config, detail=detail, jitter=jitter)
        _, info = checked_reset(seed=7, options={'reconfigure': True} if reconfigure else {})
        return env.unwrapped, plain(info), info

    try:
        result['stage'] = 'native baseline'
        base, native_info, raw_info = reset()
        result['backend'] = str(base.backend)
        result['capture_path'] = 'original native camera Color -> CPU NumPy RGB; GPU poses synchronized' \
            if native_readback else ('original ManiSkill RGB cameras' if gpu else 'not captured')
        result['test_mode'] = 'diagnostic' if native_readback else 'standard'
        assert base._furniture_appearance is None
        native, baseline, properties = materials(base), snapshot(base), physical(base)
        dump(output / 'native_physical.json', properties)
        dump(output / 'native_materials.json', native)
        torch.save(baseline, output / 'native_state.pt')
        result['checks']['default_disabled'] = 'passed'
        native_images = capture_images(env, raw_info) if gpu else None
        if gpu:
            result['stage'] = 'native local reset control'
            control = native_local_control(env, raw_info, output, checked_reset, capture_images, step_once, bidirectional=True)
            result['checks']['native_local_reset_control'] = control
            for row in control['rounds']:
                assert not row['state_changes'], 'Native unselected state changed'
                assert not any(item['changed_values'] for item in row['pixel_changes'].values()), 'Native unselected RGB changed'
                assert row[f"materials_env{1 - row['selected'][0]}_unchanged"] and row['physical_unchanged']
                assert row['task_rng_unchanged'], 'Native unselected task RNG changed'
                assert row['controller_unchanged'], 'Native unselected controller state changed'
        close()
        result['stage'] = 'explicit disabled'
        base, info, _ = reset({'enabled': False})
        assert base._furniture_appearance is None
        assert not state_changes(baseline, snapshot(base))
        assert materials(base) == native and physical(base) == properties and info == native_info
        result['checks']['explicit_disabled'] = 'passed'
        close()
        fixed_fingerprints = [set() for _ in range(num_envs)]
        for scheme in SCHEMES:
            result['stage'] = 'fixed ' + scheme
            base, info, raw_info = reset({'enabled': True, 'scheme_id': scheme})
            measured = verify(base, [scheme] * num_envs, native)
            observed_state = snapshot(base)
            torch.save(observed_state, output / f'{scheme}_state.pt')
            assert not state_changes(baseline, observed_state)
            assert physical(base) == properties and info == native_info
            records = copy.deepcopy(base._furniture_appearance.records)
            if gpu:
                from PIL import Image
                observed_images = capture_images(env, raw_info)
                fixed_pixels = {
                    str(index): image_changes(native_images, observed_images, output,
                        f'fixed_{scheme}', env_id=index) for index in range(num_envs)
                }
                dump(output / f'{scheme}_pixel_comparison.json', fixed_pixels)
                for differences in fixed_pixels.values():
                    if scheme == 'original':
                        assert not any(row['changed_values'] for row in differences.values()), 'Original RGB differs from native'
                    else:
                        assert any(row['changed_values'] for name, row in differences.items()
                                   if not name.startswith('human')), 'Candidate RGB did not change'
                for index in range(num_envs):
                    fingerprint = tuple(hashlib.sha256(pixels[index].tobytes()).hexdigest()
                        for name, pixels in sorted(observed_images.items()) if not name.startswith('human'))
                    assert fingerprint not in fixed_fingerprints[index], f'{scheme}: duplicate task-camera RGB'
                    fixed_fingerprints[index].add(fingerprint)
                for camera, pixels in observed_images.items():
                    for index in range(num_envs):
                        Image.fromarray(pixels[index, ..., :3]).save(output / f'{scheme}_{camera}_env{index}.png')
                assert records == base._furniture_appearance.records
            result['checks'][scheme] = {'status': 'passed', 'materials': measured, 'records': records}
            if scheme != 'original':
                result['stage'] = 'restore original after ' + scheme
                _, raw_info = checked_reset(seed=7, options={'furniture_appearance': {'scheme_id': 'original'}})
                assert verify(base, ['original'] * num_envs, native) == native
                assert not state_changes(baseline, snapshot(base)) and physical(base) == properties
                restoration = {'materials_match_native': True, 'physical_state_match_native': True}
                if gpu:
                    restored_images = capture_images(env, raw_info)
                    restoration['pixel_changes'] = {
                        str(i): image_changes(native_images, restored_images, output, f'restored_{scheme}', env_id=i)
                        for i in range(num_envs)}
                    assert all(not row['changed_values'] for values in restoration['pixel_changes'].values()
                               for row in values.values()), f'{scheme}: restored original RGB differs'
                    save_image_pairs(observed_images, restored_images, output, f'restored_{scheme}')
                result['checks'][scheme]['original_restoration'] = restoration
            close()
        if gpu:
            result['stage'] = 'original RGB restoration'
            base, _, raw_info = reset({'enabled': True, 'scheme_id': 'variant_2'})
            candidate_images = capture_images(env, raw_info)
            _, raw_info = checked_reset(seed=7, options={'furniture_appearance': {'scheme_id': 'original'}})
            verify(base, ['original'] * num_envs, native)
            assert not state_changes(baseline, snapshot(base)) and physical(base) == properties
            restored_images = capture_images(env, raw_info)
            restored_pixels = {
                str(index): image_changes(native_images, restored_images, output,
                    'restored_original', env_id=index) for index in range(num_envs)
            }
            dump(output / 'original_restoration.json', restored_pixels)
            save_image_pairs(candidate_images, restored_images, output, 'original_restoration')
            assert all(not row['changed_values'] for values in restored_pixels.values() for row in values.values()), 'Restored original RGB differs from native'
            result['checks']['original_rgb_restoration'] = {'status': 'passed', 'pixel_changes': restored_pixels}
            close()
        traces = []
        for repeat in range(2):
            result['stage'] = f'random repeat {repeat}'
            env = make({'enabled': True, 'mode': 'random_choice', 'scheme_ids': list(SCHEMES), 'seed': 71})
            trace = []
            for selected in ([list(range(num_envs)), [1], [0, 1], [1]] if gpu else [[0]] * 4):
                adapter = env.unwrapped._furniture_appearance
                before = copy.deepcopy(adapter.records)
                checked_reset(seed=7 if not trace else None,
                          options={'env_idx': torch.tensor(selected, device=env.unwrapped.device)})
                base = env.unwrapped
                ids = list(adapter.schemes)
                assert all(name in SCHEMES for name in ids)
                verify(base, ids, native)
                added = adapter.records[len(before):]
                assert [record['env_idx'] for record in added] == selected
                assert adapter.records[:len(before)] == before
                trace.append({'schemes': ids, 'episodes': list(adapter.episodes),
                              'records': copy.deepcopy(adapter.records)})
            traces.append(trace)
            close()
        assert traces[0] == traces[1]
        result['checks']['random_reproducibility'] = traces[0]
        result['stage'] = 'selection precedence'
        base, _, _ = reset({'enabled': True, 'scheme_id': 'original',
                            'per_env': {'0': {'scheme_id': 'variant_2'}}})
        checked_reset(options={'env_idx': torch.tensor([0], device=base.device),
            'furniture_appearance': {'scheme_id': 'original',
                                    'per_env': {'0': {'scheme_id': 'variant_1'}}}})
        ids = ['variant_1'] + ['original'] * (num_envs - 1)
        verify(base, ids, native)
        result['checks']['selection_precedence'] = 'passed'
        close()
        if not gpu:
            if task != 'FastenScrew':
                result['stage'] = 'native color jitter original preservation'
                base, jitter_info, _ = reset(jitter=True, reconfigure=True)
                jitter_native, jitter_state, jitter_physical = materials(base), snapshot(base), physical(base)
                dump(output / 'jitter_native_materials.json', jitter_native)
                torch.save(jitter_state, output / 'jitter_native_state.pt')
                close()
                base, info, _ = reset({'enabled': True, 'scheme_id': 'original'},
                                      jitter=True, reconfigure=True)
                assert verify(base, ['original'], jitter_native) == jitter_native
                assert not state_changes(jitter_state, snapshot(base))
                assert physical(base) == jitter_physical and info == jitter_info
                result['checks']['native_color_jitter'] = {'status': 'passed', 'seed': 7,
                    'reconfigure': True, 'panel_color_jitter': True}
                close()
            result['stage'] = 'visual_detail=False'
            base, detail_info, _ = reset(detail=False)
            detail_native, detail_state, detail_physical = materials(base), snapshot(base), physical(base)
            dump(output / 'minimal_native_materials.json', detail_native)
            close()
            base, info, _ = reset({'enabled': True, 'scheme_id': 'original'}, detail=False)
            detail_trace = []
            for scheme in (*SCHEMES, 'original'):
                if detail_trace:
                    _, raw_info = checked_reset(seed=7, options={'furniture_appearance': {'scheme_id': scheme}})
                    info = plain(raw_info)
                measured = verify(base, [scheme], detail_native)
                assert not state_changes(detail_state, snapshot(base))
                assert physical(base) == detail_physical and info == detail_info
                if scheme == 'original':
                    assert measured == detail_native
                detail_trace.append(scheme)
            result['checks']['minimal_visuals'] = {'status': 'passed', 'schemes': detail_trace,
                'visual_detail': False, 'records': copy.deepcopy(base._furniture_appearance.records)}
            close()
            result['checks']['local_reset_isolation'] = {'status': 'NOT TESTED',
                'reason': 'CPU uses one environment; no GPU batching or RGB isolation claim'}
        else:
            result['stage'] = 'two-environment local reset'
            initial = [SCHEMES[-1], SCHEMES[3] if len(SCHEMES) > 3 else SCHEMES[-2]]
            base, _, raw_info = reset({'enabled': True, 'scheme_id': initial[0],
                'per_env': {'1': {'scheme_id': initial[1]}}})
            verify(base, initial, native)
            expected = initial.copy()
            for index, selected in enumerate((1, 0)):
                frozen = 1 - selected
                scheme = 'original'
                result['stage'] = f'two-environment local reset {index}'
                adapter = base._furniture_appearance
                primed = prime_controller_target(base, frozen)
                if index == 1:
                    raw_info = step_once(primed)
                before_state, before_materials = snapshot(base), materials(base)
                before_controller = controller_state(base, frozen)
                before_counters = controller_counters(base)
                before_records = copy.deepcopy(adapter.records)
                before_rng = copy.deepcopy(adapter.rng[frozen].bit_generator.state)
                before_task_rng = task_rng(base, frozen)
                before_images = capture_images(env, raw_info)
                request = {'scheme_id': scheme} if index == 0 else {
                    'scheme_id': initial[0], 'per_env': {str(selected): {'scheme_id': scheme}}}
                _, raw_info = checked_reset(options={'env_idx': torch.tensor([selected], device=base.device),
                                                'furniture_appearance': request})
                after_images = capture_images(env, raw_info)
                after_state, after_materials = snapshot(base), materials(base)
                after_controller = controller_state(base, frozen)
                after_counters = controller_counters(base)
                after_rng = copy.deepcopy(adapter.rng[frozen].bit_generator.state)
                after_task_rng = task_rng(base, frozen)
                changes = state_changes(before_state, after_state, [frozen])
                pixels = image_changes(before_images, after_images, output, f'local_{index}', env_id=frozen)
                selected_pixels = image_changes(before_images, after_images, output,
                                                f'local_{index}', env_id=selected)
                row = {'selected': [selected], 'scheme_id': scheme, 'state_changes': changes,
                       'controller_precondition': primed,
                       'precondition_control_steps': int(index == 1),
                       'precondition_physics_steps': base._sim_steps_per_control if index == 1 else 0,
                       f'before_controller_env{frozen}': before_controller, f'after_controller_env{frozen}': after_controller,
                       'before_shared_controller_counters': before_counters, 'after_shared_controller_counters': after_counters,
                       'controller_unchanged': before_controller == after_controller,
                       'pixel_changes': pixels, 'selected_pixel_changes': selected_pixels,
                       'before_materials': before_materials,
                       'after_materials': after_materials, 'before_records': before_records,
                       'after_records': copy.deepcopy(adapter.records),
                       f'before_appearance_rng_env{frozen}': before_rng, f'after_appearance_rng_env{frozen}': after_rng,
                       f'before_task_rng_env{frozen}': before_task_rng, f'after_task_rng_env{frozen}': after_task_rng,
                       'appearance_rng_unchanged': before_rng == after_rng,
                       'task_rng_unchanged': before_task_rng == after_task_rng}
                torch.save({'before': before_state, 'after': after_state}, output / f'local_{index}.pt')
                dump(output / f'local_{index}.json', row)
                save_image_pairs(before_images, after_images, output, f'local_{index}')
                result['checks'][f'local_reset_{index}'] = row
                expected[selected] = scheme
                verify(base, expected, native)
                assert after_materials[selected] == native[selected]
                assert not changes and not any(value['changed_values'] for value in pixels.values())
                assert any(value['changed_values'] for name, value in selected_pixels.items()
                           if not name.startswith('human')), 'Selected environment RGB did not change'
                assert before_materials[frozen] == after_materials[frozen] and physical(base) == properties
                assert before_rng == after_rng, 'Unselected appearance RNG changed'
                assert before_task_rng == after_task_rng, 'Unselected task RNG changed'
                assert before_controller == after_controller, 'Unselected controller state changed'
                assert [record for record in before_records if record['env_idx'] == frozen] == [
                    record for record in adapter.records if record['env_idx'] == frozen]
                assert adapter.records[:len(before_records)] == before_records
                assert len(adapter.records) == len(before_records) + 1 and adapter.records[-1]['env_idx'] == selected
        result.update(status='diagnostic_passed' if native_readback else 'passed', stage='complete')
    finally:
        handling_error = sys.exc_info()[0] is not None
        try:
            close()
        except Exception:
            if not handling_error:
                raise
            result['close_error'] = traceback.format_exc()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static', action='store_true')
    parser.add_argument('--baseline', default='HEAD', help='Task judgment/reward source baseline')
    parser.add_argument('--approved-runtime', action='store_true', help='Explicit runtime intent; resource approval remains separate')
    parser.add_argument('--sim-backend', choices=('physx_cpu', 'physx_cuda'))
    parser.add_argument('--experimental-windows-cuda', action='store_true',
                        help='Bootstrap Windows CUDA with cached official PhysX DLLs; standard RGB remains required')
    parser.add_argument('--physx-gpu-dir', type=Path,
                        help='Official Windows PhysX GPU DLL directory; defaults to the SAPIEN cache')
    parser.add_argument('--diagnostic-native-readback', action='store_true',
                        help='Windows CUDA diagnostic only: native camera CPU readback; no formal acceptance')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--task', choices=tuple(TASKS), action='append', help='Default: all three tasks')
    args = parser.parse_args()
    if args.static:
        print(json.dumps(static_check(args.baseline), ensure_ascii=False))
        return 0
    if not args.approved_runtime or args.output is None or args.sim_backend is None:
        parser.error('runtime requires --approved-runtime, --sim-backend and fresh --output')
    if args.sim_backend == 'physx_cuda' and platform.system() != 'Linux':
        if platform.system() != 'Windows' or not args.experimental_windows_cuda:
            parser.error('CUDA requires native Linux, or --experimental-windows-cuda on Windows')
    if args.diagnostic_native_readback and not (args.sim_backend == 'physx_cuda'
        and platform.system() == 'Windows' and args.experimental_windows_cuda):
        parser.error('--diagnostic-native-readback requires experimental Windows CUDA')
    args.output.mkdir(parents=True, exist_ok=False)
    results = {'status': 'running', 'physics_steps': 0, 'tasks': [],
        'test_mode': 'diagnostic' if args.diagnostic_native_readback else 'standard',
        'formal_acceptance': 'NOT TESTED' if args.diagnostic_native_readback else 'pending',
        'scope': 'two-environment GPU reset isolation' if args.sim_backend == 'physx_cuda'
                 else 'single-environment CPU material/state checks; no RGB or parallel isolation'}
    started = time.monotonic()
    try:
        global np, torch, sapien, gym
        sys.path.insert(0, str(ROOT))
        import numpy as np
        import torch
        import sapien
        import gymnasium as gym
        windows_cuda = args.sim_backend == 'physx_cuda' and platform.system() == 'Windows'
        gpu_libraries = {}
        if windows_cuda:
            # Explicit experimental process only. Keep the official DLLs and
            # directory handle alive; a missing library is an error, not a
            # download or a silent fallback to the CPU pipeline.
            import ctypes
            import sapien.physx as px
            cache = args.physx_gpu_dir.resolve(strict=True) if args.physx_gpu_dir else Path.home() / '.sapien/physx' / px.version()
            filenames = ('PhysXDevice64.dll', 'PhysXGpu_64.dll')
            for filename in filenames:
                path = cache / filename
                assert path.is_file(), f'Missing cached official PhysX GPU library: {filename}'
                gpu_libraries[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
            dll_directory = os.add_dll_directory(str(cache))
            dll_handles = [ctypes.WinDLL(str(cache / filename)) for filename in filenames]
            if not px.is_gpu_enabled():
                px._enable_gpu()
            assert px.is_gpu_enabled()
        from mani_skill.utils import download_asset
        def reject_download(*unused_args, **unused_kwargs):
            raise RuntimeError('Asset download disabled: prepare the authorized assets before checking')
        download_asset.download = reject_download
        download_asset.download_from_hf_datasets = reject_download
        import tasks  # Register existing repository tasks only.
        selected = args.task or list(TASKS)
        catalog = read(CATALOG)
        files = [ADAPTER, FINISHES, RESET_SCOPE, IMPEDANCE, 'tools/variation/check_furniture_appearance.py',
                 CATALOG.relative_to(ROOT).as_posix(), *TASKS.values(),
                 *(entry['catalog'] for entry in catalog['objects'].values())]
        manifest = {'git_commit': git('rev-parse', 'HEAD'), 'command': sys.argv,
            'platform': platform.system(), 'python': sys.version, 'sim_backend': args.sim_backend,
            'experimental_windows_cuda': args.experimental_windows_cuda and platform.system() == 'Windows',
            'test_mode': 'diagnostic' if args.diagnostic_native_readback else 'standard',
            'formal_acceptance': 'NOT TESTED' if args.diagnostic_native_readback else 'pending',
            'gpu_bootstrap': 'cached official DLLs + process-local sapien.physx._enable_gpu'
                             if windows_cuda else 'native default',
            'physx_gpu_library_sha256': gpu_libraries,
            'physx_version': sapien.physx.version(),
            'capture_path': 'original native camera Color -> CPU NumPy RGB; GPU poses synchronized'
                            if args.diagnostic_native_readback else ('original ManiSkill RGB cameras'
                            if args.sim_backend == 'physx_cuda' else 'not captured'),
            'num_envs': 2 if args.sim_backend == 'physx_cuda' else 1,
            'planned_control_steps_per_task': 2 if args.sim_backend == 'physx_cuda' else 0,
            'physics_steps': 'see results.json',
            'task_ids': [f'FurnitureAssembly{task}-Sharpa-v1' for task in selected],
            'catalog_version': catalog['version'], 'schemes': list(SCHEMES), 'job_id': os.environ.get('SLURM_JOB_ID'),
            'versions': {name: metadata.version(name) for name in ('torch', 'sapien', 'mani_skill', 'gymnasium', 'numpy')},
            'files': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}}
        dump(args.output / 'manifest.json', manifest)
        for task in selected:
            row = {'task': task, 'status': 'running', 'checks': {}}
            results['tasks'].append(row)
            directory = args.output / task
            directory.mkdir()
            try:
                run_task(task, args, directory, row)
            except BaseException:
                row.update(status='failed', error=traceback.format_exc())
                raise
            finally:
                dump(args.output / 'results.json', results)
        results['status'] = 'diagnostic_passed' if args.diagnostic_native_readback else 'passed'
        results['formal_acceptance'] = 'NOT TESTED' if args.diagnostic_native_readback else (
            'passed' if args.sim_backend == 'physx_cuda' else 'NOT TESTED: CPU only')
    except BaseException:
        results.update(status='failed', error=traceback.format_exc())
        results['formal_acceptance'] = 'NOT TESTED' if args.diagnostic_native_readback else (
            'failed' if args.sim_backend == 'physx_cuda' else 'NOT TESTED: CPU only')
    finally:
        if 'manifest' in locals():
            changed_sources = [name for name, expected in manifest['files'].items()
                if not (ROOT / name).is_file()
                or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected]
            results['source_hashes_unchanged'] = not changed_sources
            if changed_sources:
                results.update(status='failed', changed_sources=changed_sources,
                               error='Source files changed during validation')
                if args.sim_backend == 'physx_cuda' and not args.diagnostic_native_readback:
                    results['formal_acceptance'] = 'failed'
        results['elapsed_seconds'] = time.monotonic() - started
        results['control_steps'] = sum(row.get('control_steps', 0) for row in results['tasks'])
        results['physics_steps'] = sum(row.get('physics_steps', 0) for row in results['tasks'])
        dump(args.output / 'results.json', results)
        print(json.dumps({'status': results['status'], 'scope': results['scope'],
                          'tasks': [{key: row[key] for key in ('task', 'status')} for row in results['tasks']]}))
    return 0 if results['status'] in ('passed', 'diagnostic_passed') else 1


if __name__ == '__main__':
    sys.exit(main())
