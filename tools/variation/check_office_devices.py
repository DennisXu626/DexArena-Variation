"""Office device catalogs, exact task source scope and source-asset checks; no simulation."""
import argparse
import ast
import copy
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import subprocess
import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from tools.variation.office_devices_assets import ROOT, DEFAULT_ASSET_ROOT, OBJECT_IDS, inspect_assets, load_definition

BASELINE = '56a4aec4740b7139307e01048fa0e8e6ed430f14'
EXPANSION_BASELINE = '66c7a1569d92487ab918df31014e0d86a70f29c2'
DEVICE_CATALOG = 'tasks/assets/variation/office_desk/devices/v1/catalog.json'
MOUSE_CATALOG = 'tasks/assets/variation/office_desk/mouse_101408/v1/catalog.json'
TASKS = ('open_laptop', 'type_keys', 'click_mouse')
FIELDS = ('base_color', 'roughness', 'metallic')


def git(*arguments):
    return subprocess.check_output(['git', '-C', str(ROOT), *arguments], text=True, encoding='utf-8')


def restore_legacy_marker_ast(current, original):
    def function(tree, name):
        return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)

    native = function(original, 'move_key_target_marker')
    wrapper = function(current, native.name)
    pose = function(current, '_key_target_marker_pose')
    expected = copy.deepcopy(native)
    expected.name = pose.name
    expected.args = ast.parse('def _key_target_marker_pose(key_link, park=False, pose=None): pass').body[0].args
    expected.body = expected.body[2:]

    class ReturnPose(ast.NodeTransformer):
        def visit_If(self, node):
            if (len(node.body) == 2 and isinstance(node.body[1], ast.Return)
                    and node.body[1].value is None and ast.unparse(node.body[0]).startswith('marker.set_pose(')):
                del node.body[1]
            return self.generic_visit(node)

        def visit_Expr(self, node):
            if ast.unparse(node).startswith('marker.set_pose('):
                return ast.Return(value=node.value.args[0])
            return node

        def visit_Assign(self, node):
            if ast.unparse(node) == 'pose = raw.entity.pose':
                return ast.parse('pose = raw.entity.pose if pose is None else pose').body[0]
            return node

    transformed = ReturnPose().visit(expected)
    assert ast.dump(transformed, include_attributes=False) == ast.dump(pose, include_attributes=False), 'Keyboard marker placement math changed'
    expected_wrapper = copy.deepcopy(native)
    expected_wrapper.body[1:] = ast.parse('''if marker is not None:
    marker.set_pose(_key_target_marker_pose(key_link, park=park))''').body
    assert ast.dump(expected_wrapper, include_attributes=False) == ast.dump(wrapper, include_attributes=False), 'Keyboard CPU/Long marker behavior changed'
    current.body.remove(pose)
    current.body[current.body.index(wrapper)] = copy.deepcopy(native)


def normalize_workspace_setup(task, constructor):
    """Match only the reviewed, top-level workspace setup before comparing native code."""
    hand = 'robot_uids == DEFAULT_ROBOT_UID and self.target_finger_id == 1'
    limits = {
        'open_laptop': ('0 <= self.robot_init_qpos_noise <= .02 and collision_decomposition == "simplified"'
                        ' and cfg["scale"] == profile["scale"]'
                        ' and cfg["start_angle_min_deg"] >= profile["start_angle_min_deg"]'
                        ' and cfg["start_angle_max_deg"] <= profile["start_angle_max_deg"]'),
        'type_keys': ('0 <= self.robot_init_qpos_noise <= .01 and self.keyboard_clearance == .002'
                      ' and self.available_model_ids.tolist() == ["13106"]'),
        'click_mouse': '0 <= self.robot_init_qpos_noise <= .02',
    }
    setup = f'self._configure_position_workspace(kwargs, num_envs, {hand} and {limits[task]})'
    if task == 'open_laptop':
        setup = 'profile = LAPTOP_MODELS[MODEL_ID]\n' + setup
    expected = [ast.dump(stmt) for stmt in ast.parse(setup).body]
    actual = [ast.dump(stmt) for stmt in constructor.body]
    starts = [i for i in range(len(actual)) if actual[i:i + len(expected)] == expected]
    assert len(starts) == 1, f'{task}: workspace constructor contract changed'
    start = starts[0]
    del constructor.body[start:start + len(expected)]


def source_check(baseline=BASELINE):
    result = {}
    for task in TASKS:
        filename = 'tasks/office_desk/office_desk_' + task + '.py'
        current = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
        original = ast.parse(git('show', baseline + ':' + filename))
        counts = {}
        keyboard_cpu_target = ast.parse('''if not self.scene.gpu_sim_enabled:
    joint.set_drive_target(float(released[key_index]))''').body[0]
        keyboard_gpu_target = ast.parse('''if self.scene.gpu_sim_enabled:
    joints = keyboard.get_active_joints()
    release_targets = self._all_key_released[env_id].tolist()
    for joint, target in zip(joints, release_targets, strict=True):
        joint.set_drive_target(target)''').body[0]
        keyboard_gpu_marker = ast.parse('''if self.scene.gpu_sim_enabled and self.num_envs > 1:
    scene = marker.scene
    mask = scene._reset_mask
    if getattr(self, "_furniture_reset_env_idx", None) is not None:
        scene._reset_mask = mask & self._furniture_reset_mask(mask)
    try:
        rows = scene._reset_mask[marker._scene_idxs].nonzero().flatten().tolist()
        poses = []
        for row in rows:
            env_id = int(marker._scene_idxs[row])
            links = self._target_links[env_id]
            slot = int(self.sequence_index[env_id])
            key = links[slot] if 0 <= slot < len(links) else None
            poses.append(_key_target_marker_pose(key, pose=key.pose.sp if key is not None else None))
        if poses:
            marker.set_pose(Pose.create(poses, device=marker.device))
            body_ids = torch.tensor([marker._bodies[row].gpu_index for row in rows],
                                    dtype=torch.int32, device=marker.device)
            torch.cuda.synchronize(marker.device)
            try:
                scene.px.gpu_apply_rigid_dynamic_data(sapien.CudaArray(body_ids))
            finally:
                torch.cuda.synchronize(marker.device)
    finally:
        scene._reset_mask = mask
    return''').body[0]
        if task == 'type_keys':
            restore_legacy_marker_ast(current, original)
        device, center = {
            'open_laptop': ('laptop', '(LAPTOP_X, 0.0)'),
            'type_keys': ('keyboard', 'KEYBOARD_SPAWN_CENTER'),
            'click_mouse': ('mouse', '(MOUSE_X, MOUSE_Y)'),
        }[task]
        position_import = ast.parse('from tasks.office_desk.position_layout import apply_position_layout').body[0]
        position_fields = ast.parse(f'_position_device_name = {device!r}\n_position_center = {center}').body
        position_call = ast.parse('apply_position_layout(options, env_idx, xyz, yaw)').body[0]

        def same(left, right):
            return ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)

        class Normalize(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                if same(node, position_import):
                    counts['position_import'] = counts.get('position_import', 0) + 1
                    return None
                return None if node.module in ('tasks.office_desk.reset_scope', 'tasks.office_desk.devices_appearance') else node

            def visit_ClassDef(self, node):
                if any(ast.unparse(base) == 'OfficeResetScopeMixin' for base in node.bases):
                    constructor = next(item for item in node.body
                                       if isinstance(item, ast.FunctionDef) and item.name == '__init__')
                    normalize_workspace_setup(task, constructor)
                    counts['workspace_constructor'] = counts.get('workspace_constructor', 0) + 1
                    for field in position_fields:
                        matches = [item for item in node.body if same(item, field)]
                        assert len(matches) == 1, f'{task}: position class contract changed'
                        node.body.remove(matches[0])
                node.bases = [base for base in node.bases if ast.unparse(base) != 'OfficeResetScopeMixin']
                return self.generic_visit(node)

            def visit_If(self, node):
                if task == 'type_keys' and same(node, keyboard_cpu_target):
                    counts['keyboard_cpu_drive_target'] = counts.get('keyboard_cpu_drive_target', 0) + 1
                    return node.body
                if task == 'type_keys' and same(node, keyboard_gpu_target):
                    counts['keyboard_gpu_drive_target'] = counts.get('keyboard_gpu_drive_target', 0) + 1
                    return None
                if task == 'type_keys' and same(node, keyboard_gpu_marker):
                    counts['keyboard_gpu_marker_scope'] = counts.get('keyboard_gpu_marker_scope', 0) + 1
                    return None
                if ast.unparse(node.test) == 'self._office_devices_appearance is not None':
                    counts['appearance_hooks'] = counts.get('appearance_hooks', 0) + 1
                    return None
                return self.generic_visit(node)

            def visit_Assign(self, node):
                if any(ast.unparse(target) == 'self._office_devices_appearance' for target in node.targets):
                    return None
                return self.generic_visit(node)

            def visit_FunctionDef(self, node):
                if node.name == '__init__':
                    for index in reversed(range(len(node.args.kwonlyargs))):
                        if node.args.kwonlyargs[index].arg == 'office_devices_appearance':
                            del node.args.kwonlyargs[index]
                            del node.args.kw_defaults[index]
                if node.name == '_initialize_episode':
                    for statement in node.body:
                        if isinstance(statement, ast.With):
                            matches = [item for item in statement.body if same(item, position_call)]
                            for item in matches:
                                statement.body.remove(item)
                            counts['position_reset_hook'] = counts.get('position_reset_hook', 0) + len(matches)
                return self.generic_visit(node)

            def visit_IfExp(self, node):
                if task == 'click_mouse' and ast.unparse(node.test) == 'appearance_enabled(mouse_appearance, num_envs)':
                    counts['constructor_config_validation'] = counts.get('constructor_config_validation', 0) + 1
                    node.test = ast.parse("mouse_appearance and mouse_appearance.get('enabled', False)", mode='eval').body
                if ast.unparse(node.test) == 'is_full_reset(env_idx, self.num_envs)':
                    assert ast.unparse(node.body) == 'self._episode_rng'
                    assert ast.unparse(node.orelse) == 'self._batched_episode_rng[env_id]'
                    return node.body
                return self.generic_visit(node)

            def visit_Call(self, node):
                node = self.generic_visit(node)
                if isinstance(node.func, ast.Name) and node.func.id == 'office_capacity_config':
                    assert ast.unparse(node) == "office_capacity_config(kwargs.pop('sim_config', None), kwargs)"
                    counts['capacity_passthrough'] = counts.get('capacity_passthrough', 0) + 1
                    return node.args[0]
                if not isinstance(node.func, ast.Attribute) or ast.unparse(node.func.value) != 'self':
                    return node
                method = node.func.attr
                if method in ('_reset_scoped_value', '_reset_scoped_predicate', '_office_scoped_results'):
                    counts[method] = counts.get(method, 0) + 1
                    return node.args[0 if method == '_reset_scoped_predicate' else 1]
                if method == '_office_normal':
                    assert ast.unparse(node) == 'self._office_normal(env_idx, self.robot_init_qpos_noise, len(arm_indices))'
                    return ast.parse('self._episode_rng.normal(0.0, self.robot_init_qpos_noise, (batch_size, len(arm_indices)))', mode='eval').body
                if method == '_office_rand':
                    assert ast.unparse(node.args[0]) == 'env_idx'
                    shape = ast.literal_eval(node.args[1])
                    size = 'batch_size' if task == 'type_keys' else '(batch_size,)' if not shape else '(batch_size, 2)'
                    return ast.parse('torch.rand(' + size + ', device=self.device)', mode='eval').body
                return node

        normalized = Normalize().visit(current)
        assert ast.dump(normalized, include_attributes=False) == ast.dump(original, include_attributes=False), task + ': source changed outside authorized appearance/position/reset scope'
        assert counts.get('position_import') == counts.get('position_reset_hook') == 1, counts
        if task != 'click_mouse':
            assert counts.get('appearance_hooks') == 3, counts
        else:
            assert counts.get('constructor_config_validation') == 1, counts
        assert counts.get('_office_scoped_results', 0) == (0 if task == 'type_keys' else 1), counts
        assert counts.get('capacity_passthrough') == 1, counts
        if task == 'type_keys':
            assert counts.get('keyboard_cpu_drive_target') == counts.get('keyboard_gpu_drive_target') == 1, counts
            assert counts.get('keyboard_gpu_marker_scope') == 1, counts
        result[task] = {'normalized_task_ast': 'identical_to_main', 'normalizations': counts}
    long_path = 'tasks/office_desk/office_desk_long.py'
    assert (ROOT / long_path).read_text(encoding='utf-8') == git('show', baseline + ':' + long_path)
    mouse_path = 'tasks/office_desk/mouse_appearance.py'
    mouse_current = ast.parse((ROOT / mouse_path).read_text(encoding='utf-8'))
    mouse_original = ast.parse(git('show', baseline + ':' + mouse_path))
    imports = [node for node in mouse_current.body if isinstance(node, ast.ImportFrom)
               and node.module == 'tasks.office_desk.devices_appearance']
    assert len(imports) == 1 and [(alias.name, alias.asname) for alias in imports[0].names] == [
        ('resolve_reset_requests', None), ('validate_appearance_config', None),
        ('validate_reset_indices', None), ('validate_reset_override', None)]
    mouse_current.body.remove(imports[0])
    mouse_class = next(node for node in mouse_current.body if isinstance(node, ast.ClassDef) and node.name == 'MouseAppearance')
    constructor = next(node for node in mouse_class.body if isinstance(node, ast.FunctionDef) and node.name == '__init__')
    assert ast.unparse(constructor.body[0]) == 'validate_appearance_config(config, num_envs)'
    del constructor.body[0]
    for tree in (mouse_current, mouse_original):
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MouseAppearance')
        cls.body = [node for node in cls.body if not isinstance(node, ast.FunctionDef) or node.name != 'finish_reset']
    assert ast.dump(mouse_current, include_attributes=False) == ast.dump(mouse_original, include_attributes=False), 'Mouse material construction/binding changed'
    result['mouse_material_binding'] = 'AST identical to main after request prevalidation normalization'
    return result


def catalog_check():
    def read_catalog(path):
        return json.loads((ROOT / path).read_text(encoding='utf-8'))

    def verify_extension(path, current, old_key):
        previous = json.loads(git('show', EXPANSION_BASELINE + ':' + path))
        old_schemes = previous[old_key]
        new_schemes = current[old_key]
        assert list(new_schemes)[:len(old_schemes)] == list(old_schemes)
        if isinstance(old_schemes, dict):
            assert all(new_schemes[name] == values for name, values in old_schemes.items())
        assert current['version'] != previous['version']
        return previous

    def validate_material(params):
        assert set(params) == set(FIELDS)
        color = params['base_color']
        assert len(color) == 4 and color[3] == 1
        assert all(math.isfinite(value) and 0 <= value <= 1 for value in [*color, params['roughness'], params['metallic']])
        return color[:3]

    family = read_catalog(DEVICE_CATALOG)
    previous_family = verify_extension(DEVICE_CATALOG, family, 'schemes')
    added = [f'variant_{i}' for i in range(3, 11)]
    assert family['schemes'] == previous_family['schemes'] + added
    assert family['tasks'] == previous_family['tasks']
    for object_id in OBJECT_IDS:
        definition = load_definition(object_id)
        entry = family['objects'][object_id]
        old_entry = previous_family['objects'][object_id]
        assert entry['catalog'] == old_entry['catalog']
        assert entry['scheme_map'] == {**old_entry['scheme_map'], **{name: name for name in added}}
        catalog = read_catalog(entry['catalog'])
        previous = verify_extension(entry['catalog'], catalog, 'schemes')
        assert {k:v for k,v in catalog.items() if k not in ('version','schemes')} == {
            k:v for k,v in previous.items() if k not in ('version','schemes')}
        assert catalog['stage'] == 'runtime' and definition['runtime_integration'] == 'connected_short_task'
        assert definition['new_uv'] is False and definition['new_textures'] == []
        assert catalog['fields'] == list(FIELDS)
        if object_id == 'keyboard':
            assert catalog['role_aliases'] == {'shell_strip':'shell'}
            assert catalog['role_fields'] == {'shell':list(FIELDS), 'shell_strip':list(FIELDS)}
            partitions=[slot for row in definition['part_bindings'] for slot in row['editable_slots'] if 'partition' in slot]
            assert len(partitions)==1 and partitions[0]['role']=='shell_strip'
            assert definition['role_contracts']['shell_strip']['mutable_fields']==list(FIELDS)
            assert definition['role_contracts']['shell_strip']['texture_policy']=='private_in_place_rgba8_upload'
        else:
            assert not catalog.get('role_aliases')
        assert catalog['schemes']['original'] == {'restore': 'captured_native'}
        assert list(entry['scheme_map'].values()) == list(catalog['schemes'])
        colors = []
        for name, roles in catalog['schemes'].items():
            if name == 'original':
                continue
            assert set(roles) == {definition['editable_role']}
            colors.append(validate_material(roles[definition['editable_role']]))
        assert all(math.dist(a,b) > .3 for a,b in combinations(colors,2))
        assert len(definition['part_bindings']) == (1 if object_id == 'laptop' else 3)
    mouse = read_catalog(MOUSE_CATALOG)
    previous = verify_extension(MOUSE_CATALOG, mouse, 'schemes')
    assert list(mouse['schemes']) == list(previous['schemes']) + added
    assert {k:v for k,v in mouse.items() if k not in ('version','schemes')} == {
        k:v for k,v in previous.items() if k not in ('version','schemes')}
    colors = []
    for name, roles in mouse['schemes'].items():
        if name == 'original':
            continue
        assert set(roles) == set(mouse['binding'].values())
        validated = {role: validate_material(params) for role, params in roles.items()}
        colors.append(validated['shell'])
    assert all(math.dist(a,b) > .3 for a,b in combinations(colors,2))
    return 'passed'


def uv_proof_check(asset_dir):
    from tools.variation.audit_office_devices_uv import inspect_uv
    proof, report, *_ = inspect_uv(asset_dir)
    definition = load_definition('keyboard')
    partition = next(slot['partition'] for row in definition['part_bindings']
                     for slot in row['editable_slots'] if 'partition' in slot)
    path = ROOT / partition['proof']
    assert proof == json.loads(path.read_text(encoding='utf-8'))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == partition['proof_sha256']
    for key in ('safe_triangles', 'safe_source_triangle_position_uv_sha256', 'safe_native_triangle_position_uv_sha256',
                'source_uv_to_native', 'native_uv_to_image', 'key_uv_mask_sha256',
                'protected_mask_sha256', 'texture_sha256', 'out_of_bounds_triangles_protected',
                'safe_uv_range', 'margin_texels', 'touching_key_region_triangles_protected','coverage_method','integer_scale'):
        assert report[key] == partition[key], key
    assert (report['moving_key_visuals'], report['safe_triangles'], report['source_triangles'],
            report['out_of_bounds_triangles_protected'], report['margin_texels']) == (77,76,502,334,8)
    return {'status':'passed','safe_existing_triangles':76,'out_of_bounds_triangles_protected':334,
            'key_uv_mask_scope':'in-bounds atlas footprints; all 77 moving-key PBR/UV and original texture preserved',
            'margin_texels':8,'texture_unchanged':True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--require-assets', action='store_true')
    parser.add_argument('--baseline', default=BASELINE)
    args = parser.parse_args()
    sources = list((ROOT / 'tools/variation').glob('*office_devices*.py')) + list((ROOT / 'tasks/office_desk').glob('*.py'))
    for source in sources:
        ast.parse(source.read_text(encoding='utf-8'))
    catalogs, scope = catalog_check(), source_check(args.baseline)
    assets = {key: inspect_assets(key, args.asset_root) for key in OBJECT_IDS}
    ready = all(not row['missing'] and not row['errors'] and row['editable_count'] for row in assets.values())
    uv_proof = uv_proof_check(args.asset_root / '13106') if ready else {'status':'NOT TESTED'}
    for object_id, inventory in assets.items():
        definition = load_definition(object_id)
        for name, expected in definition['runtime_source_sha256'].items():
            assert inventory['files'].get(name) == expected, (object_id, name)
    result = {'status': 'passed', 'catalogs': catalogs, 'task_source_scope': scope, 'keyboard_uv_proof': uv_proof,
              'assets': assets, 'asset_status': 'explicit_parts_ready' if ready else 'blocked_or_unresolved',
              'editable_parts': {key: row['editable_count'] for key, row in assets.items()},
              'scope': 'CPU static only; no simulator, model/task rendering or dynamics claim',
              'source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ('assets', 'source_sha256')}, ensure_ascii=False))
    return 2 if args.require_assets and not ready else 0


if __name__ == '__main__':
    raise SystemExit(main())
