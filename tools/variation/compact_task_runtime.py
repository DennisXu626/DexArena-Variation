"""Compact verified Nut/Pipette/Office receipts; never run a simulator.

Uses main's compact_furniture_runtime helpers. Raw captures remain external and
are bound by SHA-256. In addition to the existing checker schema, independent
verification needs checks.interface_evidence (disabled snapshots, precedence
cases, invalid-request before/after values and both random runs), fixed measured
materials, local before/after private values, and checks.step_evidence.

Interface contract: disabled rows have config/adapter_present/materials/physical/
state_evidence (a before/after .pt). Precedence is a list of constructor/reset/
selected/schemes/records cases. Atomicity has request/error_type/before/after.
Random has constructor/runs; each of two runs contains reset rows with selected,
before_rng/after_rng, before_records/after_records. Local rows use the existing
Pipette keys, plus before_physical/after_physical and selected_state_evidence.
Step rows have evidence (before/after/action .pt), control_steps/physics_steps.
checks.material_roles maps measured /env/slot/material paths to object_id/role;
it covers all adapter bindings, including preserved roles; numeric values are
always read from the existing catalog. Priming state_evidence has
before/after snapshots plus controller_after. Step evidence includes context
native/appearance and links the first reset's state to the second local round.
Missing raw evidence is an error, never a passed boolean or reconstructed log.
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys


PROFILES = {
    'nut_bolt': dict(folder='nut-bolt', tasks=('PickBolt', 'SeatNut', 'TurnNut'),
        prefix='NutBolt', checker='check_nut_bolt_runtime.py',
        dynamics='check_nut_bolt_dynamics.py', option='nut_bolt_appearance',
        launcher='tools/variation/sapien_sdk/native_lock/tools/run_task_check.py',
        capture='standard ManiSkill CUDA RGB'),
    'pipette_transfer': dict(folder='pipette-transfer', tasks=('AspirateLiquid', 'DispenseLiquid'),
        prefix='PipetteTransfer', checker='check_pipette_runtime.py',
        dynamics='check_pipette_dynamics.py', option='pipette_appearance',
        capture='original ManiSkill RGB cameras with explicit opt-in repaired default shaders'),
    'office_desk': dict(folder='office-desk', tasks=('OpenLaptop', 'TypeKeys', 'ClickMouse'),
        prefix='OfficeDesk', checker='check_office_devices_runtime.py',
        dynamics='check_office_devices_dynamics.py', option='office_devices_appearance',
        capture='original ManiSkill CUDA RGB cameras'),
}
LAUNCHER = 'tools/variation/sapien_sdk/run_task_check.py'
BASE_HELPER = 'tools/variation/compact_furniture_runtime.py'
ACTOR_COLUMNS = ('position_x', 'position_y', 'position_z', 'quaternion_w',
    'quaternion_x', 'quaternion_y', 'quaternion_z', 'linear_velocity_x',
    'linear_velocity_y', 'linear_velocity_z', 'angular_velocity_x',
    'angular_velocity_y', 'angular_velocity_z')
PBR_FIELDS = frozenset(('base_color', 'roughness', 'metallic', 'specular', 'emission',
    'ior', 'transmission', 'transmission_roughness', 'base_color_texture',
    'roughness_texture', 'metallic_texture', 'normal_texture', 'emission_texture',
    'transmission_texture'))
H = None
WATCHED = {}
CAPTURE_FILES = {}


def configure(repo):
    global H, np, torch
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location('_compact_furniture_runtime', repo / BASE_HELPER)
    H = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(H)
    import numpy as np
    import torch
    CAPTURE_FILES.clear()


def require(condition, message):
    H.require(condition, message)


def fields(value, names, context):
    require(isinstance(value, dict), f'{context}: raw object required, got {type(value).__name__}')
    missing = set(names) - value.keys()
    require(not missing, f'{context}: missing raw fields {sorted(missing)}')


def relative(name):
    require(isinstance(name, str) and name and '\\' not in name
            and not PureWindowsPath(name).is_absolute()
            and not PurePosixPath(name).is_absolute()
            and '..' not in PurePosixPath(name).parts, f'Nonportable relative path: {name!r}')
    return name


def inside(root, name):
    path = (root / relative(name)).resolve(strict=True)
    require(path.is_relative_to(root.resolve()) and path.is_file(), f'File escapes evidence root: {name}')
    return path


def track(path):
    path = path.resolve(strict=True)
    value = H.sha(path)
    require(path not in WATCHED or WATCHED[path] == value, f'Input changed during export: {path.name}')
    WATCHED[path] = value
    return value


def read(path):
    track(path)
    return H.read(path)


def load(path):
    track(path)
    return torch.load(path, map_location='cpu', weights_only=True)


def source_identity(files, root, allowed_tool_changes=()):
    H.digest_map(files, 'recorded file closure')
    unchanged, changed = {}, {}
    for name, expected in files.items():
        path = inside(root, name)
        current = track(path)
        if current != expected:
            require(name in allowed_tool_changes, f'Current bytes differ from capture: {name}')
            changed[name] = {'recorded_raw_sha256': expected, 'current_raw_sha256': current,
                'current_lf_sha256': H.lf_text_sha(path.read_bytes(), path.suffix),
                'recorded_lf_sha256': None,
                'reason': 'Named verification tool revision; recorded bytes unavailable; no old LF identity inferred'}
        else:
            unchanged[name] = expected
    return {'raw_sha256': files, 'lf_sha256': H.files_lf_identity(unchanged, root=root),
            'tool_revision_differences': changed}


def tensors(values, context, envs=None):
    require(isinstance(values, dict) and values, f'{context}: empty/non-dict tensor snapshot')
    for key, value in values.items():
        require(isinstance(key, str) and torch.is_tensor(value), f'{context}: non-tensor {key}')
        require(bool(torch.isfinite(value).all()), f'{context}: nonfinite {key}')
        if envs is not None:
            require(value.ndim > 0 and value.shape[0] == envs, f'{context}: wrong environment axis {key}')


def signatures(a, b, context, envs=None):
    tensors(a, context, envs)
    tensors(b, context, envs)
    require(a.keys() == b.keys(), f'{context}: tensor key coverage differs')
    for key, value in a.items():
        require(value.dtype == b[key].dtype and value.shape == b[key].shape,
                f'{context}: dtype/shape differs: {key}')


def exact(a, b, context, indices=None):
    signatures(a, b, context, 2 if indices is not None else None)
    for key, value in a.items():
        other = b[key]
        if indices is not None:
            value, other = value[indices], other[indices]
        require(torch.equal(value, other), f'{context}: changed {key}')


def physical_field(key):
    return ('/state/actors/' in key or '/state/articulations/' in key
        or ('/joint_targets/' in key and key.rsplit('/', 1)[-1] in ('qpos', 'qvel')))


def selected_check(directory, row):
    path = inside(directory, row['evidence'])
    report, states = read(path), load(path.with_suffix('.pt'))
    require(report == {k: v for k, v in row.items() if k != 'evidence'}, 'Selected inline/raw report differs')
    fields(states, ('before', 'expected', 'fetched', 'final'), path.name)
    for stage in ('before', 'fetched', 'final'):
        signatures(states['expected'], states[stage], path.name + '/' + stage, 2)
    keys = set(states['expected'])
    physical = {k for k in keys if physical_field(k)}
    require(physical, 'Selected reset has no physical fields')
    for field, expected in (('checked_fields', keys), ('final_physical_fields', physical),
                           ('buffer_only_fields', {k for k in keys if k.endswith('/qf')})):
        require(isinstance(report.get(field), list) and len(report[field]) == len(expected)
                and set(report[field]) == expected, f'Selected reset omitted/duplicated {field}')
    selected = report['selected']
    require(selected in ([0], [1], [0, 1], [1, 0]) and report['physics_steps'] == 0,
            'Selected reset has invalid indices or steps')
    require(report['expected_capture'] == 'after native _initialize_episode'
            and report['observed_capture'] == 'first following PhysX _gpu_fetch_all, before controller reset',
            'Selected reset capture order changed')
    intent = {}
    for key in sorted(physical):
        a, b = states['before'][key][selected], states['expected'][key][selected]
        changed = a != b
        if bool(changed.any()):
            coords = changed.nonzero().tolist()
            item = dict(max_absolute_error=float((a.double() - b.double()).abs().max()),
                shape=list(a.shape), coordinates=coords,
                before_values=a[changed].tolist(), after_values=b[changed].tolist())
            if '/actors/' in key and a.shape[-1] == 13:
                item['components'] = [ACTOR_COLUMNS[c[-1]] for c in coords]
            intent[key] = item
    require(intent == report['selected_physical_intent_changes'], 'Recorded selected intent differs from raw PT')
    require(len(selected) == 2 or bool(intent), 'Trivial selected physical intent')
    # The existing helper independently recomputes expected->fetched/final,
    # including integer equality and float atol=2e-6, rtol=0.
    compact = H.selected_check(directory, row)
    compact['raw_state_file'] = path.with_suffix('.pt').name
    compact['qf_semantics'] = 'API buffer only; no solver force-readback claim'
    return compact, states


def png(path):
    from PIL import Image
    track(path)
    with Image.open(path) as image:
        require(image.format == 'PNG' and image.mode in ('RGB', 'RGBA'), f'Unexpected PNG format: {path.name}')
        value = np.array(image)
    require(value.dtype == np.uint8 and value.ndim == 3, f'Unexpected PNG pixels: {path.name}')
    return value[..., :3]


def pair(path):
    value = png(path)
    require(value.shape[1] % 2 == 0, f'Uneven before/after PNG: {path.name}')
    width = value.shape[1] // 2
    return value[:, :width], value[:, width:]


def metrics(a, b):
    require(a.shape == b.shape and a.dtype == b.dtype, 'RGB shape/dtype differs')
    delta = a != b
    return dict(changed_values=int(delta.sum()), changed_pixels=int(delta.any(axis=-1).sum()),
                max_absolute_error=int(np.abs(a.astype(np.int16) - b.astype(np.int16)).max()))


def pixel_check(directory, rows, prefix, env, *, zero=False, changed=False):
    require(isinstance(rows, dict) and 'base_camera' in rows, f'{prefix}: missing original task RGB')
    measured = {}
    for camera, row in rows.items():
        require(re.fullmatch(r'[A-Za-z0-9_]+', camera) is not None, 'Invalid camera name')
        before, after = pair(inside(directory, f'{prefix}_{camera}_env{env}.png'))
        value = metrics(before, after)
        require(value == H.pixel_metrics({camera: row})[camera], f'{prefix}/{camera}: RGB metrics differ')
        coords = np.argwhere(before != after)
        archive = inside(directory, row['coordinates'])
        track(archive)
        with np.load(archive, allow_pickle=False) as data:
            require(set(data.files) == {'coordinates_yxc', 'before', 'after'}, 'Pixel coordinate schema differs')
            require(np.array_equal(coords, data['coordinates_yxc'])
                    and np.array_equal(before[tuple(coords.T)], data['before'])
                    and np.array_equal(after[tuple(coords.T)], data['after']), 'Raw pixel coordinates/values differ')
        samples = [list(map(int, c)) + [int(before[tuple(c)]), int(after[tuple(c)])] for c in coords[:20]]
        require(samples == row['samples_yxc_before_after'], 'Raw pixel sample values differ')
        measured[camera] = value
    require(not zero or H.zero_pixels(measured), f'{prefix}: unselected/original RGB changed')
    require(not changed or H.changed_task_pixels(measured), f'{prefix}: selected task RGB did not change')
    return measured


def pbr_profile(value, entity, context):
    fields(value, PBR_FIELDS, context + '/complete SDK PBR')
    H.canonical_sha(value)
    for name in ('base_color', 'emission'):
        require(isinstance(value[name], list) and len(value[name]) == 4
                and all(type(v) in (int, float) for v in value[name]), context + ': invalid ' + name)
    for name in ('roughness', 'metallic', 'specular', 'ior', 'transmission', 'transmission_roughness'):
        require(type(value[name]) in (int, float), context + ': invalid scalar ' + name)
    for name in sorted(k for k in PBR_FIELDS if k.endswith('_texture')):
        texture = value[name]
        if texture is None:
            continue
        fields(texture, ('name', 'width', 'height', 'format', 'mipmap_levels', 'sha256',
                         'filter_mode', 'address_mode', 'is_srgb'), context + '/' + name)
        require(all(type(texture[k]) is int and texture[k] > 0 for k in ('width', 'height', 'mipmap_levels'))
                and isinstance(texture['name'], str) and isinstance(texture['format'], str) and texture['format']
                and isinstance(texture['filter_mode'], str) and texture['filter_mode']
                and isinstance(texture['address_mode'], str) and texture['address_mode']
                and type(texture['is_srgb']) is bool, context + ': incomplete actual texture metadata')
        if 'channels' in texture:
            require(type(texture['channels']) is int and texture['channels'] > 0, 'Invalid texture channels')
        if texture['sha256'] is not None:
            H.digest_map({'texture': texture['sha256']}, context + '/texture bytes')
            source = texture.get('asset_ref', texture.get('asset_reference'))
            relative(source)
            require('asset_ref' not in texture or 'asset_reference' not in texture
                    or texture['asset_ref'] == texture['asset_reference'], 'Conflicting actual texture source references')
            require(Path(source).name == texture['name'] and CAPTURE_FILES.get(source) == texture['sha256'],
                    context + ': texture bytes outside captured asset/external closure')
        else:
            require(not texture['name'], context + ': named texture lacks a real file digest')
            fields(texture, ('asset_ref', 'embedded_asset_sha256', 'data_sha256', 'data_dtype',
                             'data_shape', 'source_kind'), context + '/embedded texture source')
            require(entity.endswith('table-workspace')
                    and texture['asset_ref'] == 'mani_skill/utils/scene_builder/table/assets/table.glb'
                    and CAPTURE_FILES.get(texture['asset_ref']) == texture['embedded_asset_sha256']
                    and isinstance(texture['source_kind'], str) and texture['source_kind'],
                    context + ': embedded texture source differs')
            H.digest_map({'downloaded_data': texture['data_sha256'], 'source_glb': texture['embedded_asset_sha256']}, 'Actual embedded texture identities')
            shape = texture['data_shape']
            require(isinstance(shape, list) and len(shape) == 3
                    and all(type(v) is int and v > 0 for v in shape)
                    and shape[:2] == [texture['height'], texture['width']]
                    and np.dtype(texture['data_dtype']).kind in 'uif', 'Invalid downloaded embedded texture dtype/shape')
            if 'channels' in texture:
                require(shape[2] == texture['channels'], 'Embedded texture channel count differs')
            # data_sha256 is the actual native download receipt. It is compared
            # exactly across material profiles, not relabeled as an image-file SHA.
    if 'diffuse_texture' in value:
        require(value['diffuse_texture'] == value['base_color_texture'], 'Legacy diffuse_texture alias differs')


def material_rows(value, prefix='', entity=''):
    if isinstance(value, dict) and 'material' in value:
        pbr_profile(value['material'], str(value.get('entity', entity)), prefix)
        return {prefix + '/material': value['material']}
    if isinstance(value, dict) and PBR_FIELDS & value.keys():
        pbr_profile(value, entity, prefix)
        return {prefix: value}
    result = {}
    if isinstance(value, (dict, list)):
        iterator = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in iterator:
            result.update(material_rows(child, prefix + '/' + str(key), entity))
    return result


def logical_key(row):
    fields(row, ('entity', 'source_visual', 'source_native_part', 'logical_group'), 'Office logical identity')
    require(isinstance(row['entity'], str) and row['entity']
            and all(type(row[k]) is int and row[k] >= 0 for k in ('source_visual', 'source_native_part'))
            and row['logical_group'] in ('safe', 'protected', 'whole'), 'Invalid Office logical identity')
    return tuple(row[k] for k in ('entity', 'source_visual', 'source_native_part', 'logical_group'))


def logical_scene(rows):
    result = {}
    require(isinstance(rows, list) and rows, 'Missing logical material scene')
    for row in rows:
        key = logical_key(row)
        fields(row, ('triangles', 'triangle_attributes_sha256', 'material'), 'Office logical source group')
        require(key not in result and type(row['triangles']) is int and row['triangles'] > 0,
                'Duplicate/empty Office logical group')
        H.digest_map({'group': row['triangle_attributes_sha256']}, 'Office logical triangle attributes')
        pbr_profile(row['material'], row['entity'], 'Office logical PBR')
        result[key] = row
    return result


def scene_materials_equal(a, b):
    logical = bool(a) and isinstance(a[0], dict) and 'logical_group' in a[0]
    return logical_scene(a) == logical_scene(b) if logical else a == b


def triangle_group_sha(values):
    import hashlib
    require(isinstance(values, list) and values, 'Empty triangle attribute group')
    H.digest_map({str(i): value for i, value in enumerate(values)}, 'Per-triangle attribute hashes')
    # Sorting retains duplicate triangles. Do not turn this sequence into a set.
    return hashlib.sha256(b''.join(bytes.fromhex(value) for value in sorted(values))).hexdigest()


def office_audit_check(materials, audit, geometry):
    """Validate the exact Office actual_slot_audit schema, with raw CPU tensors."""
    import hashlib
    require(audit.get('representation') == 'actual native render topology and logical source-group mapping'
            and isinstance(audit.get('envs'), list) and len(audit['envs']) == len(materials) == 2,
            'Missing Office actual topology audit')
    require(isinstance(geometry, dict) and geometry, 'Missing Office actual geometry tensors')
    used_tensors, environments = set(), []
    for env, (scene, record) in enumerate(zip(materials, audit['envs'])):
        logical = logical_scene(scene)
        fields(record, ('actual_shapes', 'actual_parts', 'actual_slots', 'logical_to_actual'), 'Office actual scene')
        actual, triangle_hashes, consumed, transforms = {}, {}, {}, {}
        for slot in record['actual_slots']:
            fields(slot, ('entity', 'actual_visual', 'actual_part', 'source_visual', 'source_native_part',
                'triangles', 'vertices', 'geometry_tensor_key', 'material',
                'per_triangle_position_normal_uv_winding_sha256'), 'Office actual part')
            key = (slot['entity'], slot['actual_visual'], slot['actual_part'])
            require(key not in actual and all(type(v) is int and v >= 0 for v in key[1:]), 'Duplicate/invalid Office actual part')
            tensor_key = slot['geometry_tensor_key']
            require(tensor_key == f'{env}/{key[0]}/{key[1]}/{key[2]}' and tensor_key in geometry
                    and tensor_key not in used_tensors, 'Office actual part/raw tensor link differs')
            used_tensors.add(tensor_key)
            raw = geometry[tensor_key]
            fields(raw, ('vertices', 'triangles', 'normal', 'uv', 'scale', 'position', 'quaternion', 'front_face'), 'Office part raw geometry')
            for name in ('vertices', 'triangles', 'normal', 'uv', 'scale', 'position', 'quaternion'):
                require(torch.is_tensor(raw[name]) and bool(torch.isfinite(raw[name]).all()), 'Nonfinite Office geometry tensor')
            vertices, triangles = raw['vertices'], raw['triangles']
            require(vertices.ndim == 2 and vertices.shape[1] == 3 and vertices.dtype == torch.float32
                    and triangles.ndim == 2 and triangles.shape[1] == 3 and triangles.dtype != torch.bool
                    and not torch.is_floating_point(triangles) and not torch.is_complex(triangles)
                    and len(vertices) == slot['vertices'] and len(triangles) == slot['triangles'] > 0,
                    'Office raw geometry signature differs')
            indices = triangles.long()
            require(bool((indices >= 0).all() and (indices < len(vertices)).all()), 'Office triangle index out of bounds')
            arrays = [vertices]
            for name, columns in (('normal', 3), ('uv', 2)):
                values = raw[name]
                if values.numel():
                    require(values.dtype == torch.float32 and values.shape == (len(vertices), columns), 'Office vertex attribute coverage differs')
                    arrays.append(values)
            attributes = torch.cat(arrays, dim=1)[indices].contiguous().reshape(len(triangles), -1).numpy()
            hashes = [hashlib.sha256(np.ascontiguousarray(row).tobytes()).hexdigest() for row in attributes]
            require(hashes == slot['per_triangle_position_normal_uv_winding_sha256'], 'Office actual triangle attributes differ from raw tensors')
            for name, size in (('scale', 3), ('position', 3), ('quaternion', 4)):
                require(tuple(raw[name].shape) == (size,), 'Office shape transform signature differs')
            require(isinstance(raw['front_face'], str) and raw['front_face'], 'Missing Office winding mode')
            transforms[key] = {k: raw[k].tolist() if torch.is_tensor(raw[k]) else raw[k]
                               for k in ('scale', 'position', 'quaternion', 'front_face')}
            pbr_profile(slot['material'], slot['entity'], 'Office actual part PBR')
            actual[key], triangle_hashes[key], consumed[key] = slot, hashes, []
        require(actual and record['actual_parts'] == len(actual)
                and record['actual_shapes'] == len({key[:2] for key in actual}), 'Office actual topology counts differ')
        groups = {}
        for mapping in record['logical_to_actual']:
            fields(mapping, ('logical_key', 'actual_visual', 'actual_part', 'actual_triangle_indices',
                             'triangles', 'triangle_attributes_sha256'), 'Office logical/actual mapping')
            key = logical_key(mapping['logical_key'])
            require(key in logical and key not in groups, 'Unknown/duplicate Office logical mapping')
            part = (key[0], mapping['actual_visual'], mapping['actual_part'])
            require(part in actual and actual[part]['source_visual'] == key[1]
                    and actual[part]['source_native_part'] == key[2], 'Office source/actual mapping differs')
            indices = mapping['actual_triangle_indices']
            require(isinstance(indices, list) and indices and all(type(i) is int and 0 <= i < len(triangle_hashes[part]) for i in indices)
                    and len(indices) == len(set(indices)) == mapping['triangles'] == logical[key]['triangles'],
                    'Office logical group has missing/duplicate triangle indices')
            digest = triangle_group_sha([triangle_hashes[part][i] for i in indices])
            require(digest == mapping['triangle_attributes_sha256'] == logical[key]['triangle_attributes_sha256']
                    and actual[part]['material'] == logical[key]['material'], 'Office logical geometry/PBR projection differs')
            consumed[part].extend(indices)
            groups[key] = {'part': part, 'triangles': len(indices), 'attributes_sha256': digest,
                           'transform': transforms[part]}
        entities = {key[0] for key in actual}
        require(set(groups) == {key for key in logical if key[0] in entities}
                and all(sorted(consumed[key]) == list(range(len(triangle_hashes[key]))) for key in actual),
                'Office raw/logical mapping omits or overlaps actual triangles')
        require(all(key in groups for key in logical if key[-1] != 'whole'), 'Office partition absent from actual audit')
        environments.append({'actual_shapes': record['actual_shapes'], 'actual_parts': record['actual_parts'], 'groups': groups})
    require(used_tensors == geometry.keys(), 'Office raw geometry tensor closure differs')
    return environments


def office_partition_check(native, original, native_audit, original_audit, native_geometry, original_geometry, task,
                           expected_partition=None):
    before = office_audit_check(native, native_audit, native_geometry)
    after = office_audit_check(original, original_audit, original_geometry)
    compact = []
    for env, (a, b) in enumerate(zip(before, after)):
        require(logical_scene(native[env]) == logical_scene(original[env]), 'Office enabled original differs from native logical PBR/geometry')
        require(a['groups'].keys() == b['groups'].keys(), 'Office native/enabled furniture group coverage differs')
        partitions = {}
        for key, source in a['groups'].items():
            target = b['groups'][key]
            require(all(source[k] == target[k] for k in ('triangles', 'attributes_sha256', 'transform')),
                    'Office source group geometry/UV/normal/winding/transform changed')
            if key[-1] != 'whole':
                partitions.setdefault(key[:-1], {})[key[-1]] = (source, target)
        require(len(partitions) == (1 if task == 'TypeKeys' else 0), 'Unexpected Office partition coverage')
        for key, groups in partitions.items():
            require(set(groups) == {'safe', 'protected'}, 'Incomplete Office safe/protected partition')
            fields(expected_partition, ('safe', 'protected', 'total'), 'Current approved Office partition counts')
            require(expected_partition['total'] == 502
                    and all(type(expected_partition[k]) is int and expected_partition[k] > 0 for k in ('safe', 'protected'))
                    and expected_partition['safe'] + expected_partition['protected'] == expected_partition['total'],
                    'Invalid approved Office source partition counts')
            safe, protected = groups['safe'], groups['protected']
            require(safe[0]['triangles'] == safe[1]['triangles'] == expected_partition['safe']
                    and protected[0]['triangles'] == protected[1]['triangles'] == expected_partition['protected']
                    and safe[0]['part'] == protected[0]['part'] and safe[1]['part'] != protected[1]['part'],
                    'Office actual part split differs from current approved bindings/proof')
        require(b['actual_parts'] == a['actual_parts'] + (1 if task == 'TypeKeys' else 0), 'Office actual part-count change exceeds approved split')
        compact.append({'native_actual_shapes': a['actual_shapes'], 'native_actual_parts': a['actual_parts'],
            'original_actual_shapes': b['actual_shapes'], 'original_actual_parts': b['actual_parts'],
            'logical_groups': len(a['groups']), 'approved_partitions': len(partitions)})
    return compact


def office_material_evidence(directory, native, original, mapping, repo, task):
    fields(mapping, ('schema_version', 'native_slots', 'native_geometry', 'enabled_original_slots',
                     'enabled_original_geometry', 'logical_materials'), 'Office actual/logical evidence references')
    require(mapping['schema_version'] == 1, 'Unknown Office actual/logical audit schema')
    filenames = {'native_slots': 'native_actual_slots.json', 'native_geometry': 'native_actual_geometry.pt',
        'enabled_original_slots': 'original_actual_slots.json', 'enabled_original_geometry': 'original_actual_geometry.pt',
        'logical_materials': 'native_materials.json'}
    require(all(mapping[k] == filename for k, filename in filenames.items()), 'Office actual audit filenames differ from reviewed schema')
    paths = {key: inside(directory, value) for key, value in filenames.items()}
    require(read(paths['logical_materials']) == native, 'Office logical native evidence differs')
    before, after = read(paths['native_slots']), read(paths['enabled_original_slots'])
    source_geometry, target_geometry = load(paths['native_geometry']), load(paths['enabled_original_geometry'])
    expected_partition, approved_source = None, None
    if task == 'TypeKeys':
        fields(mapping, ('input_bindings', 'uv_proof'), 'Approved Office keyboard partition source')
        require(mapping['input_bindings'] == 'assets/appearance/objects/office_desk/keyboard/bindings.json', 'Wrong Office keyboard partition bindings')
        binding_path = inside(repo, mapping['input_bindings'])
        bindings = read(binding_path)
        partitions = [(entry, slot) for entry in bindings['part_bindings']
                      for slot in entry['editable_slots'] if 'partition' in slot]
        require(len(partitions) == 1, 'Office approved partition is not unique')
        source_entry, source_slot = partitions[0]
        partition = source_slot['partition']
        require(bindings['model_id'] == '13106' and source_entry['index'] == 1
                and source_entry['mesh'] == 'textured_objs/original-80.obj'
                and source_slot['material'] == 'material_0_0' and source_slot['role'] == 'shell_strip'
                and source_slot['triangles'] == 502 and partition['margin_texels'] == 8
                and partition['mipmap_levels'] == 1, 'Office partition exceeds the approved source/role/sampling scope')
        proof_path = inside(repo, mapping['uv_proof'])
        require(mapping['uv_proof'] == partition['proof'] and track(proof_path) == partition['proof_sha256'],
                'Office UV protection proof changed')
        proof = read(proof_path)
        fields(proof, ('schema_version', 'coverage_contract', 'size', 'key_mask_rows',
                       'all_moving_keys_complete_pbr_protected'), 'Actual Office UV protection proof')
        contract = proof['coverage_contract']
        fields(contract, ('method', 'address_mode', 'filter_mode', 'is_srgb', 'mipmap_levels',
                          'margin_texels', 'coordinates', 'support'), 'Continuous Office UV protection contract')
        require(proof['schema_version'] == 2
                and contract['method'] == partition['coverage_method'] == 'exact_integer_sat_closed_bilinear_support'
                and contract['address_mode'] == 'repeat' and contract['filter_mode'] == 'linear'
                and contract['is_srgb'] is True and contract['mipmap_levels'] == 1
                and contract['margin_texels'] == partition['margin_texels'] == 8
                and contract['coordinates'] == 'native float32 exact dyadic rationals'
                and contract['support'] == '[(s-.5)/W,(e+.5)/W] for texel run [s,e); touching rejects'
                and type(partition['integer_scale']) is int and partition['integer_scale'] > 0
                and type(partition['protected_rectangle_count']) is int and partition['protected_rectangle_count'] > 0,
                'Office partition lacks the current approved continuous bilinear protection proof')
        require(partition['expected_sampler'] == {key: contract[key] for key in ('address_mode', 'filter_mode', 'is_srgb')},
                'Office binding/proof sampler contracts differ')
        require(proof['all_moving_keys_complete_pbr_protected'] is True
                and len(proof['size']) == 2 and all(type(v) is int and v > 0 for v in proof['size'])
                and len(proof['key_mask_rows']) == proof['size'][1], 'Office UV protection proof is incomplete')
        expected_ids = partition['safe_native_triangle_position_uv_sha256']
        safe_count, total = partition['safe_triangles'], source_slot['triangles']
        require(type(safe_count) is int and 0 < safe_count < total and len(expected_ids) == safe_count
                and len(partition['safe_source_triangle_position_uv_sha256']) == safe_count,
                'Office approved safe source/native triangle counts differ')
        expected_partition = {'safe': safe_count, 'protected': total - safe_count, 'total': total}
        approved_source = {**expected_partition, 'role': source_slot['role'],
            'coverage_method': contract['method'], 'proof_schema_version': proof['schema_version'],
            'bindings': {'file': mapping['input_bindings'], 'sha256': track(binding_path)},
            'proof': {'file': mapping['uv_proof'], 'sha256': track(proof_path)}}
    measured = office_partition_check(native, original, before, after, source_geometry, target_geometry, task,
                                     expected_partition=expected_partition)
    import xml.etree.ElementTree as ET
    model = {'OpenLaptop': '10211', 'TypeKeys': '13106', 'ClickMouse': '101408'}[task]
    urdf_path = repo / f'tasks/assets/task_object_meshes/office/{model}/mobility.urdf'
    track(urdf_path)
    expected_visual_counts = sorted(len(link.findall('visual')) for link in ET.parse(urdf_path).getroot().findall('link')
                                    if link.findall('visual'))
    for scene in before['envs']:
        source_visuals = {}
        for slot in scene['actual_slots']:
            require(slot['actual_visual'] == slot['source_visual'] and slot['actual_part'] == slot['source_native_part'],
                    'Office native actual indices were replaced by logical indices')
            source_visuals.setdefault(slot['entity'], set()).add(slot['source_visual'])
        require(sorted(len(values) for values in source_visuals.values()) == expected_visual_counts
                and all(sorted(values) == list(range(len(values))) for values in source_visuals.values()),
                'Office native audit omits a source object link/visual')
    if task == 'TypeKeys':
        import hashlib
        from collections import Counter
        for env, scene in enumerate(before['envs']):
            safe = [row for row in scene['logical_to_actual'] if row['logical_key']['logical_group'] == 'safe']
            require(len(safe) == 1 and safe[0]['logical_key']['source_visual'] == 1, 'Office partition changed source visual')
            group = safe[0]
            slot = next(row for row in scene['actual_slots'] if row['entity'] == group['logical_key']['entity']
                        and row['actual_visual'] == group['actual_visual'] and row['actual_part'] == group['actual_part'])
            texture = slot['material']['base_color_texture']
            require(isinstance(texture, dict) and texture['address_mode'] == 'repeat'
                    and texture['filter_mode'] == 'linear' and texture['mipmap_levels'] == 1
                    and texture['is_srgb'] is True
                    and texture['sha256'] == partition['texture_sha256'],
                    'Office partition sampler/image differs from the approved UV proof')
            raw = source_geometry[slot['geometry_tensor_key']]
            vertices = torch.cat((raw['vertices'], raw['uv']), dim=1).numpy()
            triangles = raw['triangles'].long().numpy()
            safe_uv = raw['uv'][raw['triangles'].long()[group['actual_triangle_indices']]]
            require(bool(((safe_uv >= 0) & (safe_uv <= 1)).all()), 'Office partition includes unapproved out-of-bounds UV triangles')
            ids = [hashlib.sha256(b''.join(sorted(np.ascontiguousarray(vertices[i]).tobytes()
                   for i in triangles[index]))).hexdigest() for index in group['actual_triangle_indices']]
            require(Counter(ids) == Counter(expected_ids), 'Office safe group differs from approved position/UV triangles')
    return {'representation': 'logical source triangle groups; actual native topology independently retained',
        'files': {key: {'file': mapping[key], 'sha256': track(path)} for key, path in paths.items()},
        'environments': measured,
        **({'approved_source_partition': approved_source} if approved_source is not None else {})}


def native_capture_check(directory, checks):
    control = checks.get('native_local_reset_control')
    fields(control, ('capture_diagnostic', 'rounds'), 'Native capture control')
    diagnostic = control['capture_diagnostic']
    fields(diagnostic, ('first_capture_state_changes', 'repeat_capture_state_changes',
                        'repeat_capture_pixel_changes'), 'Native capture diagnostic')
    json_path, states_path = directory / 'native_capture_diagnostic.json', directory / 'native_capture_states.pt'
    require(read(json_path) == diagnostic, 'Native capture inline/raw diagnostic differs')
    states = load(states_path)
    stages = ('before_capture', 'after_first_capture', 'after_repeat_capture')
    fields(states, stages, 'Native raw capture stages')
    baselines = []
    flat_path = directory / 'native_state.pt'
    if flat_path.is_file():
        baselines.append((load(flat_path), {'file': flat_path.name, 'tensor_path': [], 'sha256': track(flat_path)}))
    interface = checks.get('interface_evidence', {})
    default = interface.get('default_disabled') if isinstance(interface, dict) else None
    if default is not None:
        fields(default, ('config', 'adapter_present', 'state_evidence'), 'Default-disabled native baseline')
        require(default['config'] is None and default['adapter_present'] is False,
                'Fallback baseline was not captured with appearance disabled by default')
        default_path = inside(directory, default['state_evidence'])
        default_states = load(default_path)
        fields(default_states, ('before', 'after'), 'Default-disabled raw baseline states')
        signatures(default_states['before'], default_states['after'], 'Default-disabled baseline pair', 2)
        exact(default_states['before'], default_states['after'], 'Default-disabled baseline pair')
        baselines.append((default_states['before'], {'file': default['state_evidence'],
            'tensor_path': ['before'], 'sha256': track(default_path)}))
    require(baselines, 'Missing independently captured native/default-disabled baseline snapshot')
    for native, reference in baselines:
        signatures(native, states['before_capture'], 'Native state-to-first-capture', 2)
        exact(native, states['before_capture'], 'Native state-to-before-capture: ' + reference['file'])
    for before, after in zip(stages, stages[1:]):
        signatures(states[before], states[after], 'Native capture ' + after, 2)
        exact(states[before], states[after], 'Native capture ' + after)
    require(not diagnostic['first_capture_state_changes'] and not diagnostic['repeat_capture_state_changes'],
            'Native capture reported changed state')
    rows = diagnostic['repeat_capture_pixel_changes']
    require(isinstance(rows, dict), 'Missing native repeated-capture pixel evidence')
    per_env = set(rows) == {'0', '1'}
    rows0 = rows['0'] if per_env else rows
    require(isinstance(rows0, dict) and {'human', 'base_camera'} <= rows0.keys(), 'Incomplete native capture cameras')
    cameras = set(rows0)
    pixels = {'0': pixel_check(directory, rows0, 'native_capture', 0, zero=True), '1': {}}
    if per_env:
        require(set(rows['1']) == cameras, 'Native repeated-capture environment camera coverage differs')
        pixels['1'] = pixel_check(directory, rows['1'], 'native_capture', 1, zero=True)
    for env in (0, 1):
        discovered = {p.name[len('native_capture_'):-len(f'_env{env}.png')]
                      for p in directory.glob(f'native_capture_*_env{env}.png')}
        require(discovered == cameras, 'Native capture PNG camera coverage differs')
        for camera in sorted(cameras):
            before, after = pair(inside(directory, f'native_capture_{camera}_env{env}.png'))
            measured = metrics(before, after)
            require(H.zero_pixels({camera: measured}), f'Native repeated capture changed env{env}/{camera}')
            if env == 1:
                require(not per_env or pixels['1'][camera] == measured, 'Native env1 recorded/recomputed RGB differs')
                pixels['1'][camera] = measured
    return {'diagnostic_sha256': track(json_path), 'states_sha256': track(states_path),
            'native_baseline': baselines[0][1],
            'verified_baseline_sources': [reference for _, reference in baselines],
            **({'native_state_sha256': track(flat_path)} if flat_path.is_file() else {}),
            'state_changed_fields': 0, 'pixels': pixels,
            'recorded_pixel_scope': 'both environments' if per_env else 'env0; env1 independently recomputed from original PNG'}


def catalog_parameters(repo, family, task):
    """Read the three existing catalogs; no alternate numeric configuration."""
    if family == 'pipette_transfer':
        index = read(repo / 'tasks/assets/variation/pipette_transfer/v1/catalog.json')
        values = read(inside(repo, index['parameters']))
        parameters, roles, counts = {}, {}, {}
        for oid in index['tasks'][task]:
            definition = read(inside(repo, index['bindings'][oid]))
            roles[oid] = set(definition['roles'])
            if oid != 'tip_cup':
                for role, entry in definition['roles'].items():
                    owner = entry.get('parameters_from', oid)
                    counts[owner, role] = len(entry['visual_indices']) if 'visual_indices' in entry else 1
            for scheme in index['schemes']:
                params = values['objects'][oid]['schemes'][scheme]
                require(all(definition['roles'][r]['editable'] for r in params), 'Catalog edits protected Pipette role')
                parameters.setdefault(scheme, {})[oid] = params
        return parameters, roles, counts
    if task == 'ClickMouse':
        import xml.etree.ElementTree as ET
        index = read(repo / 'tasks/assets/variation/office_desk/mouse_101408/v1/catalog.json')
        urdf = repo / 'tasks/assets/task_object_meshes/office/101408/mobility.urdf'
        require(urdf.is_file(), 'Missing captured Office Mouse source URDF: tasks/assets/task_object_meshes/office/101408/mobility.urdf')
        track(urdf)
        links = {node.get('name'): node for node in ET.parse(urdf).getroot().findall('link')}
        counts = {}
        for link, role in {'link_0': 'buttons', 'link_1': 'buttons', 'link_2': 'wheel', 'link_3': 'shell'}.items():
            counts['mouse', role] = counts.get(('mouse', role), 0) + len(links[link].findall('visual'))
        return {s: {'mouse': {} if s == 'original' else index['schemes'][s]}
                for s in schemes_for(family, task)}, {'mouse': {'buttons', 'wheel', 'shell'}}, counts
    path = ('tasks/assets/variation/nut_bolt/v1/catalog.json' if family == 'nut_bolt'
            else 'tasks/assets/variation/office_desk/devices/v1/catalog.json')
    index, parameters, roles, counts = read(repo / path), {}, {}, {}
    for oid in index['tasks'][task]:
        entry = index['objects'][oid]
        catalog = read(inside(repo, entry['catalog']))
        if family == 'office_desk':
            definition = read(repo / f'assets/appearance/objects/office_desk/{oid}/bindings.json')
            roles[oid] = {slot.get('role', definition['editable_role'])
                          for part in definition['part_bindings'] for slot in part['editable_slots']}
            for part in definition['part_bindings']:
                for slot in part['editable_slots']:
                    role = slot.get('role', definition['editable_role'])
                    counts[oid, role] = counts.get((oid, role), 0) + 1
        else:
            roles[oid] = set(catalog['preserve_roles'])
            count = {'shaft': 1, 'tip': 20, 'thread': 192, 'head': 1} if oid == 'bolt' else {'reference_face': 2, 'body': 10}
            counts.update({(oid, role): value for role, value in count.items()})
        for scheme in index['schemes']:
            source = catalog['schemes'][entry['scheme_map'][scheme]]
            params = {} if scheme == 'original' else source.get('roles', source)
            if family == 'nut_bolt':
                require(not set(params) & set(catalog['preserve_roles']), 'Catalog edits protected Nut role')
                roles[oid].update(params)
            else:
                require(set(params) <= roles[oid], 'Catalog edits unknown Office role')
                if scheme != 'original':
                    for role, source in catalog.get('role_aliases', {}).items():
                        require(oid == 'keyboard' and role == 'shell_strip' and source == 'shell', 'Unknown Office role alias')
                        params = {**params, role: {**params[source], 'base_color_texture': None}}
            parameters.setdefault(scheme, {})[oid] = params
    return parameters, roles, counts


def material_check(native, actual, scheme, bindings, parameters, roles, counts):
    a, b = material_rows(native), material_rows(actual)
    logical = bool(native) and bool(native[0]) and 'logical_group' in native[0][0]
    if logical:
        require(len(native) == len(actual) == 2, 'Office logical material environment count differs')
        aligned = []
        for before_scene, after_scene in zip(native, actual):
            source, target = logical_scene(before_scene), logical_scene(after_scene)
            require(source.keys() == target.keys(), 'Office logical source group coverage differs')
            aligned.append([source[logical_key(row)] for row in after_scene])
        # These indices are JSON material-row references, never renderer indices.
        # Renderer topology is separately proved by actual_slot_audit.
        native = aligned
        a = material_rows(native)
    require(a and a.keys() == b.keys(), f'{scheme}: PBR slot coverage differs')
    require(isinstance(bindings, dict) and bindings and set(bindings) <= a.keys(), 'Raw object/role to material-slot bindings required')
    for path, binding in bindings.items():
        fields(binding, ('object_id', 'role'), 'Material role binding')
        require(binding['object_id'] in roles and binding['role'] in roles[binding['object_id']], 'Unknown material object/role')
    from collections import Counter
    for env in (0, 1):
        observed = Counter((value['object_id'], value['role']) for key, value in bindings.items()
                           if key.startswith('/' + str(env) + '/'))
        require(observed == counts, f'Incomplete material-slot role coverage in env{env}')
    H.canonical_sha(actual)  # Reject nonfinite JSON values as well.
    changed = []
    require(len(native) == len(actual) == 2 and all(len(x) == len(y) for x, y in zip(native, actual)), 'Material environment/slot counts differ')
    for before_env, after_env in zip(native, actual):
        require(all({k: v for k, v in a.items() if k != 'material'} ==
                    {k: v for k, v in b.items() if k != 'material'}
                    for a, b in zip(before_env, after_env)), 'Material entity/shape/part identity differs')
    for key, baseline in a.items():
        require(baseline.keys() == b[key].keys(), f'{scheme}: PBR field coverage differs')
        expected = copy.deepcopy(baseline)
        env = int(key.split('/')[1])
        selected_scheme = scheme[env] if isinstance(scheme, list) else scheme
        if key in bindings:
            binding = bindings[key]
            params = parameters[selected_scheme][binding['object_id']].get(binding['role'], {})
            for field, value in params.items():
                if field == 'base_color_rgb':
                    expected['base_color'][:3] = value
                elif field == 'base_color_alpha':
                    expected['base_color'][3] = value
                else:
                    require(field in ('base_color', 'roughness', 'metallic') or
                            (field == 'base_color_texture' and value is None
                             and binding['object_id'] == 'keyboard' and binding['role'] == 'shell_strip'), 'Unsupported catalog PBR field')
                    expected[field] = value
        for field, value in baseline.items():
            if expected[field] == value or selected_scheme == 'original':
                require(b[key][field] == value, f'{scheme}: protected PBR changed: {key}/{field}')
            else:
                matches = b[key][field] is None if expected[field] is None else np.allclose(np.asarray(b[key][field]), np.asarray(expected[field]), rtol=0, atol=2e-6)
                require(matches,
                        f'{scheme}: PBR differs from catalog: {key}/{field}')
            if value != b[key][field]:
                changed.append(key + '/' + field)
    require(scheme == 'original' or isinstance(scheme, list) or changed, f'{scheme}: candidate PBR is unchanged')
    return {'canonical_sha256': H.canonical_sha(actual), 'changed_fields': changed}


def schemes_for(family, task):
    if family == 'pipette_transfer':
        return ('original', 'jade', 'coral')
    if family == 'office_desk' and task == 'ClickMouse':
        return ('original', 'ivory_matte', 'navy_satin')
    return ('original', 'variant_1', 'variant_2')


def option_for(profile, task):
    return 'mouse_appearance' if task == 'ClickMouse' else profile['option']


def record_check(before, after, selected, schemes=None):
    require(isinstance(before, list) and isinstance(after, list)
            and after[:len(before)] == before and len(after) == len(before) + len(selected),
            'Episode history is not append-only for exactly the selected environments')
    for index, env in enumerate(selected):
        row = after[len(before) + index]
        fields(row, ('env_idx', 'episode_index', 'scheme_id', 'catalog_version'), 'Episode record')
        previous = [r['episode_index'] for r in before if r['env_idx'] == env]
        require(row['env_idx'] == env and row['episode_index'] == max(previous, default=0) + 1
                and bool(row['catalog_version']), 'Incorrect per-environment episode record')
        if schemes is not None:
            require(row['scheme_id'] == schemes[env], 'Recorded scheme differs from resolved request')


def resolve_requests(constructor, override, selected, schemes):
    require(isinstance(constructor, dict) and isinstance(override, dict), 'Missing raw selection requests')
    resolved = {}
    for env in selected:
        request = {**constructor, **constructor.get('per_env', {}).get(str(env), {}),
                   **override, **override.get('per_env', {}).get(str(env), {})}
        mode = request.get('mode', 'explicit')
        choices = ([request.get('scheme_id', 'original')] if mode == 'explicit' else request.get('scheme_ids', []))
        require(mode in ('explicit', 'random_choice') and isinstance(choices, list) and choices
                and all(c in schemes for c in choices), 'Invalid recorded selection request')
        resolved[env] = (mode, choices)
    return resolved


def reset_preflight_check(directory, evidence, option, schemes):
    fields(evidence, ('reset_preflight_rejections', 'constructor_per_env_rejection'), 'Reset preflight')
    rows = evidence['reset_preflight_rejections']
    expected = {'descending_env_idx_rejection': ('strictly increasing', False),
                'restore_override_rejection': ('state restoration', True),
                'reset_per_env_rejection': ('per_env', False)}
    require(isinstance(rows, dict) and rows.keys() == expected.keys(), 'Incomplete reset rejection set')
    compact = {}
    for name, (message, restore) in expected.items():
        row = rows[name]
        fields(row, ('request', 'seed', 'actual_state_restore_payload', 'error', 'before', 'after',
                     'state_evidence', 'state_sha256'), name)
        fields(row['error'], ('type', 'message'), name + '/error')
        require(row['error']['type'] == 'ValueError' and message in row['error']['message']
                and row['seed'] is None and row['actual_state_restore_payload'] is restore,
                name + ': wrong rejection or reset context')
        request = row['request']
        if name == 'descending_env_idx_rejection':
            require(request == {'env_idx': [1, 0]}, name + ': expected descending full-batch indices')
        else:
            fields(request, (option,), name + '/request')
            config = request[option]
            require(isinstance(config, dict), name + ': invalid recorded option')
            if restore:
                require(config.get('scheme_id') in schemes, name + ': expected a valid appearance override')
            else:
                require(isinstance(config.get('per_env'), dict) and '2' in config['per_env'],
                        name + ': expected an out-of-range per_env key')
        before = row['before']
        fields(before, ('materials', 'controller', 'episode_rng', 'main_rng', 'batched_main_rng',
                        'appearance_rng', 'records', 'episodes', 'schemes'), name + '/before')
        for field in ('materials', 'controller', 'episode_rng', 'batched_main_rng', 'appearance_rng',
                      'episodes', 'schemes'):
            require(isinstance(before[field], list) and len(before[field]) == 2 and all(before[field]),
                    name + ': missing actual two-environment ' + field)
        require(before['main_rng'] and before['records'] and before == row['after'],
                name + ': rejected request mutated state or lacks evidence')
        path = inside(directory, row['state_evidence'])
        states = load(path)
        fields(states, ('before', 'after'), name + '/state')
        require(track(path) == row['state_sha256'] and read(inside(directory, name + '.json')) == row,
                name + ': raw and inline evidence differ')
        require(any(physical_field(key) for key in states['before']), name + ': missing physics state')
        exact(states['before'], states['after'], name)
        compact[name] = {'state_sha256': row['state_sha256'], 'raw_values_sha256': H.canonical_sha(row)}
    constructor = evidence['constructor_per_env_rejection']
    fields(constructor, ('config', 'error'), 'Constructor rejection')
    fields(constructor['config'], ('per_env',), 'Constructor request')
    fields(constructor['error'], ('type', 'message'), 'Constructor error')
    require(isinstance(constructor['config']['per_env'], dict) and '2' in constructor['config']['per_env']
            and constructor['error']['type'] == 'ValueError' and 'per_env' in constructor['error']['message'],
            'Constructor did not reject an out-of-range per_env key')
    compact['constructor_per_env_rejection'] = H.canonical_sha(constructor)
    return compact


def interface_check(directory, checks, native, physical, schemes, bindings, parameters, roles, counts, option):
    evidence = checks.get('interface_evidence')
    fields(evidence, ('default_disabled', 'explicit_disabled', 'selection_precedence',
                     'invalid_request_atomicity', 'random_reproducibility'), 'checks.interface_evidence')
    compact = {}
    for key, config in (('default_disabled', None), ('explicit_disabled', {'enabled': False})):
        row = evidence[key]
        fields(row, ('config', 'adapter_present', 'materials', 'physical', 'state_evidence'), key)
        require(row['config'] == config and row['adapter_present'] is False
                and row['materials'] == native and row['physical'] == physical, f'{key}: native default differs')
        states = load(inside(directory, row['state_evidence']))
        exact(states['before'], states['after'], key)
        compact[key] = {'state_sha256': track(inside(directory, row['state_evidence'])),
                        'raw_values_sha256': H.canonical_sha(row)}
    cases = evidence['selection_precedence']
    require(isinstance(cases, list) and len(cases) >= 2, 'Missing constructor/reset precedence cases')
    levels = set()
    for row in cases:
        fields(row, ('constructor', 'reset', 'selected', 'schemes', 'before_records', 'after_records', 'materials'), 'Precedence case')
        selected = row['selected']
        require(selected in ([0], [1], [0, 1], [1, 0]), 'Invalid precedence environment indices')
        resolved = resolve_requests(row['constructor'], row['reset'], selected, schemes)
        for env, (mode, choices) in resolved.items():
            require(mode == 'explicit' and row['schemes'][env] == choices[0], 'Configuration precedence differs')
        record_check(row['before_records'], row['after_records'], selected, row['schemes'])
        material_check(native, row['materials'], row['schemes'], bindings, parameters, roles, counts)
        for source, name in ((row['constructor'], 'constructor'), (row['reset'], 'reset')):
            if 'scheme_id' in source:
                levels.add(name)
            if source.get('per_env'):
                levels.add(name + '/per_env')
    require(levels == {'constructor', 'constructor/per_env', 'reset', 'reset/per_env'}, 'Precedence coverage is incomplete')
    atomic = evidence['invalid_request_atomicity']
    fields(atomic, ('request', 'error_type', 'before', 'after'), 'Invalid request atomicity')
    require(atomic['error_type'] == 'ValueError', 'Invalid last-environment request was not rejected')
    invalid = atomic['request'].get('per_env', {}).get('1', {})
    choices = invalid.get('scheme_ids', [invalid.get('scheme_id', 'original')])
    require(choices and any(s not in schemes for s in choices), 'Atomicity did not exercise invalid final environment')
    fields(atomic['before'], ('materials', 'appearance_rng', 'episodes', 'schemes', 'records'), 'Atomic before')
    initial = atomic['before']
    require(isinstance(initial['materials'], list) and len(initial['materials']) == 2
            and all(material_rows(v) for v in initial['materials'])
            and len(initial['appearance_rng']) == len(initial['episodes']) == len(initial['schemes']) == 2
            and all(isinstance(v, dict) and v for v in initial['appearance_rng'])
            and all(type(v) is int and v > 0 for v in initial['episodes'])
            and all(v in schemes for v in initial['schemes'])
            and all(any(r['env_idx'] == env for r in initial['records']) for env in (0, 1)),
            'Atomicity lacks nonempty actual two-environment values')
    require(atomic['before'] == atomic['after'], 'Rejected request changed material/RNG/episode/history')
    random = evidence['random_reproducibility']
    fields(random, ('constructor', 'runs'), 'Independent random evidence')
    require(random['constructor'].get('enabled') is True and isinstance(random['runs'], list)
            and len(random['runs']) == 2 and random['runs'][0] == random['runs'][1], 'Both reproducible random runs required')
    coverage = set()
    for run in random['runs']:
        require(isinstance(run, list) and len(run) >= 3, 'Random run needs partial and full reset traces')
        initial = run[0]
        seed = int(random['constructor'].get('seed', 0))
        for env in (0, 1):
            generator = np.random.default_rng(np.random.SeedSequence([seed, env]))
            mode, choices = resolve_requests(random['constructor'], {}, [env], schemes)[env]
            for record in [r for r in initial['before_records'] if r['env_idx'] == env]:
                chosen = str(generator.choice(choices)) if mode == 'random_choice' else choices[0]
                require(record['scheme_id'] == chosen, 'Initial random episode history differs from independent seed')
            require(generator.bit_generator.state == initial['before_rng'][env], 'Initial per-env random stream does not match seed')
        previous = None
        for row in run:
            fields(row, ('selected', 'before_rng', 'after_rng', 'before_records', 'after_records'), 'Random reset')
            selected = row['selected']
            require(selected in ([0], [1], [0, 1], [1, 0]), 'Invalid random selection')
            coverage.add(tuple(sorted(selected)))
            if previous is not None:
                require(row['before_rng'] == previous['after_rng']
                        and row['before_records'] == previous['after_records'], 'Random reset trace is discontinuous')
            requests = resolve_requests(random['constructor'], row.get('reset', {}), selected, schemes)
            require(len(row['before_rng']) == len(row['after_rng']) == 2, 'Missing independent per-env RNG states')
            chosen = {}
            for env in range(2):
                generator = np.random.default_rng()
                generator.bit_generator.state = copy.deepcopy(row['before_rng'][env])
                if env in selected:
                    mode, choices = requests[env]
                    require(mode == 'random_choice', 'Random evidence used explicit selection')
                    chosen[env] = str(generator.choice(choices))
                require(generator.bit_generator.state == row['after_rng'][env], 'Appearance RNG consumption differs')
            record_check(row['before_records'], row['after_records'], selected, chosen)
            previous = row
    require({(0,), (1,), (0, 1)} <= coverage, 'Independent random coverage lacks either local direction/full reset')
    compact.update(selection_precedence_sha256=H.canonical_sha(cases),
        invalid_request_atomicity_sha256=H.canonical_sha(atomic),
        random_reproducibility_sha256=H.canonical_sha(random),
        reset_preflight=reset_preflight_check(directory, evidence, option, schemes))
    return compact


def raw_pair(row, key, context):
    fields(row, ('before_' + key, 'after_' + key), context)
    require(isinstance(row['before_' + key], dict) and row['before_' + key]
            and row['before_' + key] == row['after_' + key],
            f'{context}: changed or missing {key}')
    return H.canonical_sha(row['before_' + key])


def local_check(directory, row, prefix, expected_selected, selected_states, captured_native, *, appearance):
    selected = row.get('selected')
    if isinstance(selected, int):
        selected = [selected]
    require(selected == [expected_selected] and not row['state_changes'], f'{prefix}: wrong direction/state changes')
    other = 1 - expected_selected
    path = inside(directory, row.get('state_evidence', prefix + '.pt'))
    states = load(path)
    after = states.get('after', states.get('after_capture'))
    exact(states['before'], after, prefix + '/unselected', [other])
    fields(row, ('selected_state_evidence',), prefix)
    require(row['selected_state_evidence'] in selected_states, f'{prefix}: unknown selected reset association')
    selected_record = selected_states[row['selected_state_evidence']]
    require(selected_record['selected'] == selected, f'{prefix}: selected-reset direction differs')
    selected_raw = selected_record['states']
    exact(states['before'], selected_raw['before'], prefix + '/selected-link-before')
    exact(after, selected_raw['final'], prefix + '/selected-link-after')
    private = {}
    for key in ('controller', 'task_rng'):
        suffix = key + '_unselected' if 'before_' + key + '_unselected' in row else key + f'_env{other}'
        private[key] = raw_pair(row, suffix, prefix)
        if key == 'task_rng':
            require('batched_episode_rng' in row['before_' + suffix]
                    and (other != 0 or 'episode_rng_alias' in row['before_' + suffix]),
                    f'{prefix}: task random-stream coverage is incomplete')
    fields(row, ('before_materials', 'after_materials', 'before_physical', 'after_physical',
                 'before_shared_controller_counters', 'after_shared_controller_counters',
                 'controller_precondition', 'precondition_control_steps', 'precondition_physics_steps'), prefix)
    require(material_rows(row['before_materials']) and material_rows(row['after_materials']),
            f'{prefix}: missing complete local material profiles')
    require(scene_materials_equal(row['before_materials'][other], row['after_materials'][other]), f'{prefix}: unselected PBR changed')
    private['physical'] = raw_pair(row, 'physical', prefix)
    require(len(row['before_physical'].get('scenes', [])) == 2, 'Physical definitions lack both environments')
    before_counters, after_counters = row['before_shared_controller_counters'], row['after_shared_controller_counters']
    require(isinstance(before_counters, dict) and before_counters.keys() == after_counters.keys(), 'Shared controller counter coverage differs')
    for key, before_counter in before_counters.items():
        after_counter = after_counters[key]
        require(before_counter['scope'] == after_counter['scope'] == 'shared'
                and before_counter['interpolation_enabled'] == after_counter['interpolation_enabled']
                and (not before_counter['interpolation_enabled'] or before_counter == after_counter),
                'Shared interpolated controller counter changed')
    precondition = row['controller_precondition']
    fields(precondition, ('nontrivial_targets_all_envs', 'generalized_forces_all_envs', 'controller_all_envs'), prefix + '/precondition')
    for env in (0, 1):
        targets = precondition['nontrivial_targets_all_envs'].get(str(env))
        forces = np.asarray(precondition['generalized_forces_all_envs'].get(str(env)), dtype=float)
        require(isinstance(targets, dict) and targets and all(v is True for v in targets.values())
                and forces.size > 0 and np.isfinite(forces).all() and np.any(forces != 0),
                f'{prefix}: missing nonzero original controller target/qf in env{env}')
        controllers = precondition['controller_all_envs'].get(str(env))
        require(isinstance(controllers, dict) and controllers
                and any('_target_qpos' in value or '_target_pose' in value for value in controllers.values()),
                f'{prefix}: missing actual controller internals in env{env}')
        target_keys = [k for k in states['before'] if k.endswith('/robot/position_target')]
        require(len(target_keys) == 1, 'Ambiguous/missing original robot targets')
        target_key = target_keys[0]
        qpos = states['before'][target_key.rsplit('/', 1)[0] + '/qpos'][env]
        target = states['before'][target_key][env]
        qf = states['before'][target_key.rsplit('/', 1)[0] + '/qf'][env]
        require(target.shape == qpos.shape and not torch.equal(target, qpos)
                and bool(torch.count_nonzero(qf)), f'{prefix}: raw original target/qf is trivial')
        # Step updates qf. The prime report is tied to its own raw snapshot so a
        # stale pre-step force report is never confused with the later buffer.
        fields(precondition, ('state_evidence',), prefix + '/raw priming state')
        primed = load(inside(directory, precondition['state_evidence']))
        signatures(primed['before'], primed['after'], prefix + '/priming', 2)
        for key in primed['before']:
            if physical_field(key):
                require(torch.equal(primed['before'][key], primed['after'][key]), 'Controller priming changed physical state')
        require(primed['after'][target_key.rsplit('/', 1)[0] + '/qf'][env].tolist() ==
                precondition['generalized_forces_all_envs'][str(env)], 'Reported prime qf differs from raw buffer')
        fields(primed, ('controller_after',), 'Raw priming controller state')
        require(primed['controller_after'][str(env)] == controllers, 'Reported priming controller differs from raw private values')
        if row['precondition_control_steps'] == 0:
            exact(primed['after'], states['before'], prefix + '/priming-to-reset')
    require(row['precondition_control_steps'] in (0, 1)
            and row['precondition_physics_steps'] == 20 * row['precondition_control_steps'], 'Bad local step provenance')
    # Shared counters are diagnostic. Do not call them per-env private state.
    pixels = pixel_check(directory, row['pixel_changes'], prefix, other, zero=True)
    result = {'selected': selected, 'unselected': [other], 'state_sha256': track(path),
        'private_values_sha256': private, 'precondition_sha256': H.canonical_sha(precondition),
        'precondition_control_steps': row['precondition_control_steps'],
        'precondition_physics_steps': row['precondition_physics_steps'], 'unselected_pixels': pixels,
        'unselected_materials_sha256': H.canonical_sha(row['before_materials'][other]),
        'shared_controller_counters': {'before': row['before_shared_controller_counters'],
                                      'after': row['after_shared_controller_counters']}}
    if appearance:
        require(scene_materials_equal(row['after_materials'][expected_selected], captured_native[expected_selected]),
                f'{prefix}: selected environment did not restore captured native PBR')
        private['appearance_rng'] = raw_pair(row, 'appearance_rng_unselected', prefix)
        fields(row, ('before_records', 'after_records'), prefix)
        record_check(row['before_records'], row['after_records'], selected, {expected_selected: 'original'})
        result['records_sha256'] = H.canonical_sha([row['before_records'], row['after_records']])
        result['selected_pixels'] = pixel_check(directory, row['selected_pixel_changes'], prefix, expected_selected, changed=True)
    return result


def steps_check(directory, rows, local_rows, native_rows, family):
    require(isinstance(rows, list) and len(rows) == 2, 'Two actual GPU step before/after receipts required')
    compact, files, hashes, contexts = [], set(), set(), set()
    for row in rows:
        require(row['control_steps'] == 1 and row['physics_steps'] == 20, 'GPU step counts differ')
        path = inside(directory, row['evidence'])
        require(path not in files and track(path) not in hashes, 'Duplicate GPU step receipt')
        files.add(path)
        hashes.add(track(path))
        states = load(path)
        fields(states, ('before', 'after', 'action'), 'GPU step raw tensors')
        signatures(states['before'], states['after'], 'GPU step', 2)
        action = states['action']
        require(torch.is_tensor(action) and action.ndim >= 2 and action.shape[0] == 2
                and bool(torch.isfinite(action).all()) and bool(torch.count_nonzero(action)), 'Invalid/trivial step action')
        elapsed = [k for k in states['before'] if k.endswith('/elapsed_steps')]
        require(elapsed and all(torch.equal(states['after'][k], states['before'][k] + 1) for k in elapsed),
                'GPU step did not advance both episode clocks exactly once')
        require(any(physical_field(k) and not torch.equal(v, states['after'][k])
                    for k, v in states['before'].items()), 'GPU step exercised no physical motion')
        context = row.get('context')
        require(context in ('native', 'appearance') and context not in contexts, 'One distinct step required in each native/appearance run')
        require(states.get('context') == context, 'Raw step context differs from receipt')
        contexts.add(context)
        cases = native_rows if context == 'native' else local_rows
        def local_path(index):
            default = (f'native_local_{1-index}' if family == 'pipette_transfer' else f'native_local_{index}') if context == 'native' else (
                f'local_reset_{1-index}' if family == 'pipette_transfer' else f'local_{index}')
            return inside(directory, cases[index].get('state_evidence', default + '.pt'))
        first, second = load(local_path(0)), load(local_path(1))
        first_after = first.get('after', first.get('after_capture'))
        second_before = second['before']
        exact(states['after'], second_before, 'Step after-to-local-before')
        primed = cases[1]['controller_precondition']
        prime_states = load(inside(directory, primed['state_evidence']))
        exact(states['before'], prime_states['after'], 'Priming-to-step-before')
        require(torch.equal(action, torch.as_tensor(primed['action'], dtype=action.dtype)), 'Raw step action differs from original controller request')
        for key in states['before']:
            if physical_field(key):
                require(torch.equal(states['before'][key], first_after[key]), 'Step before is not the preceding local-reset physical state')
        compact.append({'raw_state_sha256': track(path), 'control_steps': 1, 'physics_steps': 20})
    return compact


def nut_stage_check(task_directory, reference):
    fields(reference, ('file', 'sha256', 'status'), 'SeatNut stage fixture')
    path = inside(task_directory, reference['file'])
    require(reference['status'] == 'passed' and path == task_directory / 'stage_visibility_fixture/checks.json'
            and track(path) == reference['sha256'], 'SeatNut stage evidence path, status or hash differs')
    row, directory = read(path), path.parent
    require(row['status'] == 'passed' and row['capture_path'] == 'standard ManiSkill CUDA RGB'
            and row['selected'] == 1 and row['unselected'] == 0
            and row['control_steps'] == row['physics_steps'] == 0, 'Wrong SeatNut stage validation scope')
    initial = {'free': [1., 1.], 'threaded': [0., 0.]}
    require(row['before_visibility'] == row['restored_visibility'] == initial
            and row['engaged_visibility'] == {'free': [1., 0.], 'threaded': [0., 1.]},
            'Nut twin visibility did not toggle and restore in selected environment alone')
    states_path = inside(directory, row['state_evidence'])
    states = load(states_path)
    require(track(states_path) == row['state_sha256'] and set(states) == {'initial', 'engaged', 'restored'},
            'SeatNut stage state capture differs')
    for key, snapshots in states.items():
        require(set(snapshots) == {'before_capture', 'after_first_capture', 'after_repeat_capture'},
                'SeatNut first/repeat state is incomplete')
        exact(snapshots['before_capture'], snapshots['after_first_capture'], key + ' first')
        exact(snapshots['before_capture'], snapshots['after_repeat_capture'], key + ' repeat')
    for first, second in (('initial', 'engaged'), ('engaged', 'restored')):
        exact(states[first]['after_repeat_capture'], states[second]['before_capture'], first + ' unselected', [0])
    for key in ('materials', 'physical', 'controller_unselected', 'task_rng_unselected', 'appearance_rng_unselected'):
        fields(row, ('before_' + key, 'after_' + key, 'engaged_private'), 'SeatNut private stage state')
        require(row['before_' + key] == row['engaged_private'][key] == row['after_' + key],
                'SeatNut stage changed protected/unselected ' + key)
    require(row['engaged_private']['records'] == row['before_records'], 'Native engage changed appearance records')
    record_check(row['before_records'], row['after_records'], [1])
    measured, frames = {}, {}
    cameras = {'base_camera', 'task_wrist_camera', 'human'}
    for stage in ('before', 'engaged', 'restored'):
        rows = row['first_vs_repeat'][stage]
        require(len(rows) == 2 and all(set(r) == cameras for r in rows), 'SeatNut repeat camera set differs')
        measured[stage + '_repeat'] = [pixel_check(directory, r, stage + '_repeat', env, zero=True)
                                        for env, r in enumerate(rows)]
        for env in range(2):
            for camera in cameras:
                frames[stage, env, camera] = pair(inside(directory, f'{stage}_repeat_{camera}_env{env}.png'))[0]
    for direction, before, after in (('forward', 'before', 'engaged'), ('reverse', 'engaged', 'restored')):
        rows = row['transition_pixels'][direction]
        prefix = direction + '_swap'
        require(len(rows) == 2 and all(set(r) == cameras for r in rows), 'SeatNut transition camera set differs')
        measured[direction] = [pixel_check(directory, r, prefix, env, zero=(env == 0), changed=(env == 1))
                               for env, r in enumerate(rows)]
        for env in range(2):
            for camera in cameras:
                images = pair(inside(directory, f'{prefix}_{camera}_env{env}.png'))
                require(np.array_equal(images[0], frames[before, env, camera])
                        and np.array_equal(images[1], frames[after, env, camera]), 'SeatNut transition frames differ')
    return {'sha256': track(path), 'state_sha256': track(states_path), 'control_steps': 0, 'physics_steps': 0,
            'selected': 1, 'unselected': 0, 'measurements': measured}


def office_counter_check(directory, rows, task, selected_states, cameras):
    require(isinstance(rows, list) and len(rows) == 2, 'Office counter fixture needs both directions')
    expected = {
        'OpenLaptop': ('office_laptop_task_state', {'reached_once': 0, 'hold_counter': 1}, 2,
                       {'reached_once': True, 'hold_counter': 2}),
        'TypeKeys': ('office_keyboard_task_state', {'press_started': 0, 'press_achieved': 1,
                     'sequence_index': 5, 'press_hold_counter': -5, 'release_counter': -4}, 4,
                     {'press_started': True, 'press_achieved': True, 'sequence_index': 1,
                      'press_hold_counter': 1, 'release_counter': 1}),
        'ClickMouse': ('office_mouse_task_state', {'press_started': 0, 'hold_counter': 4,
                       'release_counter': 5, 'final_counter': 6, 'press_success_counter': 7}, 3,
                       {'press_started': True, 'hold_counter': 1, 'release_counter': 1,
                        'final_counter': 1, 'press_success_counter': 1})}
    state_name, positions, success_index, values = expected[task]
    compact = []
    for row, selected in zip(rows, (1, 0)):
        other = 1 - selected
        prefix = f'diagnostic_counter_scope_{selected}'
        raw = inside(directory, row['evidence'])
        state = inside(directory, row['state_evidence'])
        selected_path = inside(directory, row['selected_state_evidence'])
        require(raw.name == prefix + '.json' and track(raw) == row['evidence_sha256']
                and read(raw) == {k: v for k, v in row.items() if k not in ('evidence', 'evidence_sha256')}
                and state.name == prefix + '.pt' and track(state) == row['state_sha256']
                and track(selected_path) == row['selected_state_sha256'], 'Office counter raw evidence drift')
        require(row['selected'] == [selected] and row['status'] == 'passed' and row['state_changes'] == {}
                and row['physics_steps'] == 0 and row['task_success_claim'] is False
                and row['before_controller'] == row['after_controller']
                and row['before_task_rng'] == row['after_task_rng'], 'Office counter scope check differs')
        fixture = row['fixture']
        require(fixture['env_idx'] == other and fixture['classification'] == 'diagnostic/counter-scope fixture'
                and fixture['physical_state_modified'] is False and fixture['task_success_claim'] is False
                and fixture['success_latched'] is False, 'Office fixture scope differs')
        states = load(state)
        require(set(states) == {'before', 'after'}, 'Office counter fixture missing paired states')
        exact(states['before'], states['after'], prefix + ' unselected', [other])
        observed = states['before']['/state/' + state_name][other]
        require(observed[success_index].item() == 0 and all(observed[pos].item() == values[k]
                for k, pos in positions.items()), 'Office raw counters are missing or trivial')
        fixture_values = dict(values)
        if task == 'TypeKeys':
            seq = [bool(i) for i in observed[6:-5].tolist()]
            require(seq == [True] + [False] * (len(seq) - 1), 'Office keyboard fixture sequence differs')
            fixture_values['sequence_completed'] = seq
        require(fixture['fields'] == fixture_values, 'Office diagnostic raw/reported counters differ')
        linked = selected_states[row['selected_state_evidence']]
        require(linked['selected'] == [selected], 'Office fixture linked to a different selected environment')
        for stage, side in (('before', 'before'), ('final', 'after')):
            exact(states[side], linked['states'][stage], prefix + ' selected capture link')
        require(set(row['png_pairs']) == {'0', '1'} and set(row['coordinates']) == set(cameras)
                and set(row['pixel_changes']) == set(cameras), 'Office diagnostic camera coverage differs')
        for env, records in row['png_pairs'].items():
            require(set(records) == set(cameras), 'Office diagnostic paired PNG camera coverage differs')
            for camera, record in records.items():
                path = inside(directory, record['file'])
                require(path.name == f'{prefix}_{camera}_env{env}.png' and track(path) == record['sha256'],
                        'Office diagnostic PNG does not match its receipt')
                pair(path)
        for camera, reference in row['coordinates'].items():
            require(reference['file'] == row['pixel_changes'][camera]['coordinates']
                    and track(inside(directory, reference['file'])) == reference['sha256'], 'Office diagnostic NPZ differs')
        pixels = pixel_check(directory, row['pixel_changes'], prefix, other, zero=True)
        compact.append({k: row[k] for k in ('fixture', 'selected', 'evidence_sha256', 'state_sha256',
                                           'selected_state_sha256', 'png_pairs', 'coordinates', 'physics_steps')}
                       | {'unselected_pixels': pixels})
    return compact


def office_asset_root(row):
    require(row.get('object_asset_root') == 'tasks/assets/task_object_meshes/office',
            'Office runtime did not use verified checkout task assets')
    return row['object_asset_root']


def mouse_collision_check(row, repo):
    import hashlib
    import xml.etree.ElementTree as ET
    require(row.get('mouse_collision_inputs_unchanged') is True, 'Mouse collision dependency changed during capture')
    value = row['mouse_collision_identity']
    require(value['coacd_version'] == '1.0.14' and value['coacd_files'] == {
            'coacd/__init__.py': '6a521661951e15382e52f385722f64bfdd6f3e09cfd1e95c7c3967ba3533b4c6',
            'coacd/lib_coacd.dll': 'a32e801d260b774ebc723edfc05e45e179c09d0d2355592c64cbff490698e806'},
            'Mouse loaded CoACD dependency differs from reviewed Windows inputs')
    H.digest_map({'trimesh': value['trimesh_import_sha256']}, 'Mouse trimesh identity')
    require(isinstance(value['trimesh_version'], str) and bool(value['trimesh_version']), 'Mouse trimesh version missing')
    directory = repo / office_asset_root(row) / '101408'
    names = {n.attrib['filename'] for n in ET.parse(directory / 'mobility.urdf').findall('.//collision/geometry/mesh')}
    require(len(names) == 5 and len(value['caches']) == 5, 'Mouse needs five native collision meshes/caches')
    parameters = ('threshold=0.05, max_convex_hull=-1, preprocess_mode=auto, preprocess_resolution=30, '
                  'resolution=2000, mcts_nodes=20, mcts_iterations=150, mcts_max_depth=3, pca=False, merge=True, seed=0')
    for name in names:
        mesh = inside(directory, name)
        track(mesh)
        cache = inside(directory, name + '.coacd.ply')
        md5 = hashlib.md5(mesh.read_bytes()).hexdigest()
        with cache.open('rb') as stream:
            header = [stream.readline() for _ in range(3)]
        require(header == [b'ply' + bytes([10]), b'format binary_little_endian 1.0' + bytes([10]),
                           f'comment md5={md5}, {parameters}'.encode('ascii') + bytes([10])]
                and value['caches'][cache.relative_to(repo).as_posix()] == {
                    'mesh_source_md5': md5, 'sha256': track(cache)}, 'Mouse collision mesh cache differs: ' + name)
    return value


def task_check(root, task, family, profile, images, repo):
    name = task['task']
    require(task['status'] == 'passed' and not task.get('error') and not task.get('close_error'), f'{name}: task failed')
    require(task['control_steps'] == 2 and task['physics_steps'] == 40, f'{name}: expected two control/40 physics steps')
    directory, checks, schemes = root / name, task['checks'], schemes_for(family, name)
    nut_stage = nut_stage_check(directory, checks.get('stage_visibility_fixture')) if family == 'nut_bolt' and name == 'SeatNut' else None
    capture_diagnostic = native_capture_check(directory, checks)
    native, physical = read(directory / 'native_materials.json'), read(directory / 'native_physical.json')
    office_audit = None
    if family == 'office_desk':
        fields(checks, ('material_partition_mapping', 'original'), 'Office actual topology evidence')
        fields(checks['original'], ('materials',), 'Office enabled original PBR')
        office_audit = office_material_evidence(directory, native, checks['original']['materials'],
                                                checks['material_partition_mapping'], repo, name)
    parameters, roles, counts = catalog_parameters(repo, family, name)
    fields(checks, ('material_roles',), name + '/raw material slot roles')
    bindings = checks['material_roles']
    interface = interface_check(directory, checks, native, physical, schemes, bindings, parameters, roles, counts,
                                option_for(profile, name))
    selected, selected_states = [], {}
    require(len(checks['selected_reset_state']) >= 22, f'{name}: fewer than 22 selected readback checks')
    for row in checks['selected_reset_state']:
        require(row['evidence'] not in selected_states, 'Duplicate selected evidence')
        compact, states = selected_check(directory, row)
        selected.append(compact)
        selected_states[row['evidence']] = {'selected': row['selected'], 'states': states}
    native_rows = checks['native_local_reset_control']['rounds']
    require(len(native_rows) == 2, 'Native-off local reset control missing')
    cameras = tuple(capture_diagnostic['pixels']['0'])
    office_counter = office_counter_check(directory, checks.get('diagnostic_counter_scope'), name, selected_states,
                                          cameras) if family == 'office_desk' else None
    require(set(cameras) == set(native_rows[0]['pixel_changes']), 'Native/local capture camera set differs')
    require('human' in cameras and 'base_camera' in cameras, f'{name}: native human/task camera missing')
    native_prefix = 'native_capture'
    native_frames = {(camera, env): pair(inside(directory, f'{native_prefix}_{camera}_env{env}.png'))[0]
                     for camera in cameras for env in (0, 1)}
    fixed, frames = {}, {}
    for scheme in schemes:
        row = checks.get(scheme, checks.get('fixed_' + scheme))
        fields(row, ('status', 'materials', 'records'), name + '/fixed/' + scheme)
        require(row['status'] == 'passed', f'{name}: fixed scheme failed')
        fixed[scheme] = material_check(native, row['materials'], scheme, bindings, parameters, roles, counts)
        require(isinstance(row['materials'], list) and len(row['materials']) == 2, 'Fixed PBR needs both environments')
        for env in (0, 1):
            records = [r for r in row['records'] if r['env_idx'] == env]
            matching = [r for r in records if r['scheme_id'] == scheme]
            require(matching and matching[-1]['episode_index'] > 0
                    and (family == 'nut_bolt' or records[-1]['scheme_id'] == scheme),
                    'Fixed scheme missing episode record')
        fixed[scheme]['records'] = row['records']
        prefix = 'fixed_' + scheme if family == 'nut_bolt' else scheme
        for camera in cameras:
            require(re.fullmatch(r'[A-Za-z0-9_]+', camera) is not None, 'Invalid fixed camera')
            for env in (0, 1):
                path = inside(directory, f'{prefix}_{camera}_env{env}.png')
                if family == 'nut_bolt':
                    before, after = pair(path)
                    if scheme == 'original':
                        require(np.array_equal(before, after), 'Native/original RGB differs')
                    else:
                        require(np.array_equal(before, frames['original', camera, env]), 'Fixed native baseline differs')
                else:
                    after = png(path)
                if scheme == 'original':
                    require(np.array_equal(native_frames[camera, env], after), 'Full native-off/original RGB differs')
                frames[scheme, camera, env] = after
                if camera == 'human' and env == 0:
                    images[f'{name}/{scheme}_human_env0.png'] = path
        if family != 'nut_bolt':
            comparison_path = directory / f'{scheme}_pixel_comparison.json'
            if comparison_path.is_file():
                pixels = read(comparison_path)
                require(set(pixels) == {'0', '1'}, 'Fixed pixels omit an environment')
                for env in (0, 1):
                    for camera, row_pixels in pixels[str(env)].items():
                        if scheme != 'original':
                            actual = metrics(frames['original', camera, env], frames[scheme, camera, env])
                            require(actual == H.pixel_metrics({camera: row_pixels})[camera], 'Fixed metrics differ from PNG')
                        else:
                            require(H.zero_pixels({camera: row_pixels}), 'Original RGB is not native')
        fixed[scheme]['pixels_vs_original'] = {str(env): {camera: metrics(frames['original', camera, env],
            frames[scheme, camera, env]) for camera in cameras} for env in (0, 1)}
        if scheme != 'original':
            require(all(H.changed_task_pixels(v) for v in fixed[scheme]['pixels_vs_original'].values()), 'Fixed task candidate invisible')
        # Compare restoration at the same fixed seed, across all original cameras.
        for camera in cameras:
            for env in (0, 1):
                restored_prefix = 'restored_' + scheme if family == 'nut_bolt' else 'original_restoration'
                before_restore, restored = pair(inside(directory, f'{restored_prefix}_{camera}_env{env}.png'))
                if family == 'nut_bolt':
                    require(np.array_equal(before_restore, native_frames[camera, env]), 'Nut restore native side differs')
                elif scheme == schemes[-1]:
                    require(np.array_equal(before_restore, frames[schemes[-1], camera, env]), 'Restoration candidate side differs')
                require(np.array_equal(frames['original', camera, env], restored), 'Full original RGB restoration differs')
    require(all(not np.array_equal(frames[schemes[1], 'base_camera', e], frames[schemes[2], 'base_camera', e])
                for e in (0, 1)), 'Two candidate task RGB frames are identical')
    if family == 'nut_bolt':
        local_rows, prefixes = checks['local_reset_isolation'], ('local_0', 'local_1')
    else:
        keys = ('local_reset_1', 'local_reset_0') if family == 'pipette_transfer' else ('local_reset_0', 'local_reset_1')
        local_rows = [checks[k] for k in keys]
        prefixes = keys if family == 'pipette_transfer' else ('local_0', 'local_1')
    require(len(local_rows) == 2, 'Missing two appearance local rounds')
    locals_compact = []
    for index, (row, prefix, selected_env) in enumerate(zip(local_rows, prefixes, (1, 0))):
        raw_path = directory / (prefix + '.json')
        if raw_path.is_file():
            require(read(raw_path) == row, 'Local raw/inline values differ')
        locals_compact.append(local_check(directory, row, prefix, selected_env, selected_states, native, appearance=True))
        require(row['precondition_control_steps'] == index, 'Appearance isolation lacks pre/post-step cases')
        for env in (0, 1):
            images[f'{name}/local_{index}_base_camera_env{env}.png'] = inside(directory, f'{prefix}_base_camera_env{env}.png')
    native_compact = []
    for index, row in enumerate(native_rows):
        env = row['selected'][0] if isinstance(row['selected'], list) else row['selected']
        prefix = f'native_local_{env}' if family == 'pipette_transfer' else f'native_local_{index}'
        native_compact.append(local_check(directory, row, prefix, env, selected_states, native, appearance=False))
        require(row['precondition_control_steps'] == index, 'Native isolation lacks pre/post-step cases')
    return {'task_id': f"{profile['prefix']}{name}-Sharpa-v1", 'status': 'passed',
        'control_steps': 2, 'physics_steps': 40, 'interface': interface, 'fixed': fixed,
        'native_materials_sha256': H.canonical_sha(native), 'native_physical_sha256': H.canonical_sha(physical),
        'native_capture_diagnostic': capture_diagnostic,
        'selected_reset_checks': selected, 'appearance_local_reset': locals_compact,
        'native_local_reset': native_compact,
        'material_roles_sha256': H.canonical_sha(bindings),
        **({'actual_logical_material_audit': office_audit} if office_audit is not None else {}),
        **({'diagnostic_counter_scope': office_counter} if office_counter is not None else {}),
        **({'stage_visibility_fixture': nut_stage} if nut_stage is not None else {}),
        'robot_urdf_names': sorted({k.rsplit('/', 1)[-1] + '.urdf'
            for record in selected_states.values() for k in record['states']['expected']
            if '/state/articulations/panda_' in k}),
        'steps': steps_check(directory, checks.get('step_evidence'), local_rows, native_rows, family)}


def flag(command, name):
    require(command.count(name) == 1, f'Missing/duplicate command option {name}')
    index = command.index(name)
    require(index + 1 < len(command), f'Missing command argument {name}')
    return command[index + 1]


def portable_command(command, repo):
    command = list(command)
    require(command and all(isinstance(v, str) for v in command), 'Invalid command receipt')
    if command[0].endswith('.py'):
        script = (repo / command[0]).resolve()
        require(script.is_relative_to(repo), 'Checker command escapes repository')
        command[0] = script.relative_to(repo).as_posix()
    else:
        command[0] = '{python}'
    placeholders = {'--repo-root': '.', '--output': '{capture_directory}', '--sapien-root': '{sdk_root}',
        '--artifact': '{sdk_artifact}', '--physx-gpu-dir': '{physx_gpu_directory}', '--actions': '{actions_file}',
        '--sdk-provenance-root': '{sdk_provenance}', '--sdk-base-root': '{base_sdk_root}'}
    for i, token in enumerate(command[1:], 1):
        if command[i - 1] in placeholders:
            command[i] = placeholders[command[i - 1]]
        elif Path(token).is_absolute() or PureWindowsPath(token).is_absolute():
            target = Path(token).resolve()
            require(target.is_relative_to(repo), f'Unreviewed absolute command path: {Path(token).name}')
            command[i] = target.relative_to(repo).as_posix()
    return command


def sdk_check(before, after, expected, required, *, gpu):
    require(isinstance(before, dict) and before == after, 'Loaded child SDK/DLL identity changed')
    core = {n for n in required if not n.startswith('PhysX')}
    require(core <= before.keys() and (not gpu or required <= before.keys()), 'Actual child SDK/DLL closure missing')
    compact, binding = {}, None
    for name, row in before.items():
        require(name in expected, f'Unknown loaded native library: {name}')
        if row == {'loaded': False}:
            require(not gpu and name.startswith('PhysX'), 'Required runtime library was not loaded')
            compact[name] = row
            continue
        fields(row, ('path', 'sha256'), 'Loaded SDK ' + name)
        path = Path(row['path']).resolve(strict=True)
        require(path.name == name and row['sha256'] == expected[name] == track(path), 'Actual native bytes differ: ' + name)
        compact[name] = {'sha256': row['sha256']}
        if name.endswith('.pyd'):
            binding = path
    require(binding is not None and all(Path(before[n]['path']).resolve().parent == binding.parent
                for n in core), 'SDK core loaded outside binding directory')
    return compact, binding


def sdk_python_check(receipt, binding):
    fields(receipt, ('python_before', 'python_after', 'python_source_unchanged'),
           'Private SDK Python identity')
    before = receipt['python_before']
    H.digest_map(before, 'Private SDK Python source')
    require(receipt['python_source_unchanged'] is True and before == receipt['python_after'],
            'Private SDK Python sources changed during capture')
    private_root = binding.parent.parent
    package = private_root / 'sapien'
    require(binding.parent == package, 'Binding is outside the private SDK sapien package')
    paths = {path.relative_to(private_root).as_posix(): path for path in package.rglob('*.py')}
    require('sapien/__init__.py' in paths and before.keys() == paths.keys(),
            'Private SDK Python file set differs from the recorded closure')
    for name, path in sorted(paths.items()):
        require(path.resolve(strict=True).is_relative_to(package) and track(path) == before[name],
                'Private SDK Python bytes differ: ' + name)
    return {'raw_sha256': before, 'map_sha256': H.canonical_sha(before),
            'file_count': len(before), 'unchanged_during_capture': True}


def launcher_check(row, repo, checker, source, launcher_path=LAUNCHER, sdk_record=None):
    require(row.get('private_sdk') is True and row.get('indexed_gpu_apply_patch_version') == 1,
            'Private SDK/native indexed capability not proved')
    launcher = row.get('launcher')
    fields(launcher, ('file', 'sha256', 'checker', 'checker_sha256'), 'Actual launcher identity')
    require(launcher['file'] == 'run_task_check.py' and launcher['checker'] == checker
            and launcher['sha256'] == source.get(launcher_path) == track(repo / launcher_path)
            and launcher['checker_sha256'] == source.get(checker) == track(repo / checker),
            'Launcher/checker identity differs from current source closure')
    if launcher_path == PROFILES['nut_bolt']['launcher']:
        validator = str(PurePosixPath(launcher_path).with_name('native_lock_identity.py'))
        fields(launcher, ('validator', 'validator_sha256'), 'Native SDK validator')
        require(launcher['validator'] == validator
                and launcher['validator_sha256'] == source.get(validator) == track(repo / validator),
                'Native SDK validator differs from captured source')
        require(sdk_record is not None and row.get('sdk_identity') == sdk_record
                and row.get('sdk_schema') == sdk_record['schema']
                and row.get('native_capabilities') == sdk_record['capabilities_expected']
                and row.get('lock_sha256') == sdk_record['lock_sha256'], 'Native SDK capability/build evidence differs')


def vulkan_loader_check(row):
    record = row.get('system_vulkan_loader')
    fields(record, ('before', 'after', 'unchanged'), 'System Vulkan loader')
    before = record['before']
    fields(before, ('path', 'sha256'), 'System Vulkan loader identity')
    path = Path(before['path']).resolve(strict=True)
    require(record['unchanged'] is True and before == record['after']
            and path.name.lower() == 'vulkan-1.dll' and path.parent.name.lower() == 'system32'
            and track(path) == before['sha256'], 'System Vulkan loader identity differs')
    return {'module': 'System32/vulkan-1.dll', 'sha256': before['sha256'], 'retained_for_process_lifetime': True}


def probe_sdk_check(path, repo, gpu, expected, required, sdk_record):
    """Verify SDK identity for the raw runs named by a supplementary optical summary."""
    summary = read(path)
    fields(summary, ('status', 'tasks'), 'Supplementary probe summary')
    tasks = summary['tasks']
    require(summary['status'] == 'passed' and summary['fresh_constructions'] == 56
            and summary['camera_environment_view_pairs'] == 112
            and summary['control_steps'] == summary['physics_steps'] == 0 and isinstance(tasks, list)
            and summary['exporter_sha256'] == track(repo / 'tools/variation/compact_pipette_rendering.py')
            and sorted(task['task'] for task in tasks) == sorted(PROFILES['pipette_transfer']['tasks']),
            'Supplementary probe summary has incomplete task coverage')
    verified = {}
    capture_tool = 'tools/variation/check_pipette_rendering.py'
    for task in tasks:
        require(task.get('status') == 'passed', 'Supplementary probe task did not pass')
        require(task['fresh_constructions'] == 28 and task['camera_environment_view_pairs'] == 56
                and task['control_steps'] == task['physics_steps'] == 0
                and set(task['source']) == set(gpu['files']) | {capture_tool}
                and {k: v for k, v in task['source'].items() if k != capture_tool} == gpu['files']
                and task['external_files'] == gpu['external_files']
                and task['resources']['max_delta_mib'] <= 1792 and task['resources']['min_free_mib'] > 512,
                'Supplementary task source, counts or resource limits differ')
        raw_files = task['raw_file_sha256']
        for name, expected_sha in raw_files.items():
            require(track(inside(repo, name)) == expected_sha, 'Supplementary raw evidence changed: ' + name)
        paths = [name for name in raw_files if PurePosixPath(name).name == 'private_sdk.json']
        require(len(paths) == 1, 'Supplementary probe must reference one raw private SDK receipt per task')
        receipt_path = inside(repo, paths[0])
        receipt = read(receipt_path)
        require(track(receipt_path) == raw_files[paths[0]], 'Supplementary probe SDK receipt hash differs')
        require(receipt.get('artifact_sha256') == sdk_record['artifact_sha256']
                and receipt.get('version') == sdk_record['version']
                and receipt.get('binaries_unchanged') is True, 'Supplementary probe SDK artifact/version differs')
        native, binding = sdk_check(receipt['before'], receipt['after'], expected, required, gpu=True)
        python = sdk_python_check(receipt, binding)
        launcher_check(receipt, repo, capture_tool, task['source'])
        require(track(inside(repo, capture_tool)) == task['source'][capture_tool], 'Optical capture tool changed')
        require(vulkan_loader_check(receipt) == gpu['system_vulkan_loader'], 'Supplementary Vulkan loader differs')
        require(native == gpu['sdk'] and python == gpu['sdk_python'],
                'Supplementary probe and formal CUDA SDK identities differ')
        require(task['sdk']['artifact_sha256'] == receipt['artifact_sha256']
                and task['sdk']['version'] == receipt['version']
                and task['sdk']['loaded_native_binary_sha256'] == {k: v['sha256'] for k, v in native.items()},
                'Supplementary probe summary and raw SDK receipt differ')
        verified[task['task']] = {'private_sdk_file': paths[0], 'private_sdk_sha256': track(receipt_path),
                                  'sdk_python_map_sha256': python['map_sha256']}
    return {'summary_sha256': track(path), 'summary_file': 'rendering_probe_summary.json',
            'capture_tool': capture_tool, 'capture_tool_sha256': tasks[0]['source'][capture_tool],
            'exporter': 'tools/variation/compact_pipette_rendering.py', 'exporter_sha256': summary['exporter_sha256'],
            'identity_scope': 'Private SDK Python sources and native libraries',
            'tasks': verified}


def resource_check(directory, command, limit):
    path = directory / 'resource.json'
    report = read(path)
    start, samples = report['initial'], report['samples']
    require(report['command'] == command and report['returncode'] == 0 and not report.get('stopped')
            and start['free_mib'] >= 2048 and start['util_percent'] < 70
            and report['delta_limit_mib'] == limit and report['stop_free_mib'] == 512
            and type(report['owned_pid']) is int and report['owned_pid'] > 0 and samples,
            'Resource receipt differs from the completed checker or does not meet startup limits')
    prior_time, peak, low = start['time'], 0, start['free_mib']
    for row in samples:
        delta = row['used_mib'] - start['used_mib']
        require(row['time'] >= prior_time and row['free_mib'] > 512
                and delta <= limit and row['delta_mib'] == delta, 'Resource sample violates limits or differs')
        prior_time, peak, low = row['time'], max(peak, delta), min(low, row['free_mib'])
    require(report['final']['time'] >= prior_time and report['max_delta_mib'] == peak
            and report['min_free_mib'] == low, 'Resource summary differs from raw samples')
    return dict(sha256=track(path), sample_count=len(samples), initial_free_mib=start['free_mib'],
                initial_util_percent=start['util_percent'], max_delta_mib=peak, min_free_mib=low)


def console_check(directory, capture, results, sdk, repo, profile):
    process = read(directory / 'process.json')
    require(process['returncode'] == 0 and process['timed_out'] is False, 'GPU process failed/timed out')
    streams = {n: track(directory / n) for n in ('stdout.txt', 'stderr.txt')}
    require(streams == process['streams_sha256'], 'Raw GPU console stream SHA differs')
    printed = read(directory / 'stdout.txt')
    actual = printed['tasks']
    pairs = [(r['task'], r['status']) for r in results['tasks']]
    if actual and isinstance(actual[0], dict):
        verdicts = [(r['task'], r['status']) for r in actual]
    else:
        verdicts = [(r[0], r[1]) for r in actual]
        if profile['prefix'] == 'OfficeDesk':
            require(actual == [[r['task'], r['status'], r.get('stage')] for r in results['tasks']], 'Console task stage differs')
    require(printed['status'] == 'passed' and verdicts == pairs, 'Console/raw task verdict differs')
    command = process['command']
    scripts = [v for v in command if isinstance(v, str) and v.endswith('.py')]
    require(scripts and (repo / scripts[0]).resolve() == (repo / profile.get('launcher', LAUNCHER)).resolve()
            and Path(flag(command, '--repo-root')).resolve() == repo
            and flag(command, '--checker') == 'tools/variation/' + profile['checker']
            and (repo / flag(command, '--output')).resolve() == capture.resolve(), 'GPU console launcher/output/checker differs')
    warnings, continuation = {}, False
    text = re.sub(r'\x1b\[[0-9;]*m', '', (directory / 'stderr.txt').read_text(encoding='utf-8'))
    for line in filter(None, (v.strip() for v in text.splitlines())):
        if continuation:
            require(line == 'warnings.warn(', 'Unreviewed warning continuation')
            continuation = False
            continue
        if re.fullmatch(r'.+[/\\]pinocchio_model\.py:\d+: UserWarning: pinnochio package is not installed, robotics functionalities will not be available', line):
            kind, continuation = 'optional_pinocchio_unavailable', True
        else:
            match = re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ - mani_skill\s+- WARNING - Overriding registered agent (panda|panda_wristcam)', line)
            require(match is not None, 'Unreviewed console stderr: ' + line)
            kind = 'agent_registration_override:' + match.group(1)
        warnings[kind] = warnings.get(kind, 0) + 1
    require(not continuation, 'Incomplete optional Pinocchio warning')
    return dict(process_sha256=track(directory / 'process.json'), streams_sha256=streams,
        returncode=0, timed_out=False, command=portable_command(command, repo), known_warning_types=warnings,
        resources=resource_check(directory, command, 1792))


def cpu_console_check(directory, capture, repo, profile):
    process = read(directory / 'process.json')
    require(process['returncode'] == 0 and process['timed_out'] is False, 'CPU process failed/timed out')
    command = process['command']
    scripts = [arg for arg in command if isinstance(arg, str) and arg.endswith('.py')]
    require(scripts and (repo / scripts[0]).resolve() == (repo / 'tools/variation' / profile['dynamics']).resolve()
            and (repo / flag(command, '--output')).resolve() == capture,
            'CPU console checker/output does not match the evidence')
    streams = {name: track(directory / name) for name in ('stdout.txt', 'stderr.txt')}
    require(streams == process['streams_sha256'], 'Raw CPU console stream SHA differs')
    return dict(process_sha256=track(directory / 'process.json'), streams_sha256=streams,
                command=portable_command(command, repo), resources=resource_check(directory, command, 1024))


def asset_identity(family, manifest, task, repo):
    if family == 'office_desk':
        source = manifest['asset_files']
        base = repo / 'tasks/assets/task_object_meshes/office'
        require(all((base / model / 'mobility.urdf').is_file() for model in ('10211', '13106', '101408')),
                'Office source model asset root incomplete (10211/13106/101408)')
        expected_keys = {p.relative_to(base).as_posix() for model in ('10211', '13106', '101408')
                         for p in (base / model).rglob('*') if p.is_file()}
        require(expected_keys and set(source) == expected_keys, 'Office original model asset closure incomplete')
        assets = {'tasks/assets/task_object_meshes/office/' + relative(k): v for k, v in source.items()}
        # Imported model assets alone do not close the robot mesh/texture inputs.
        fields(task, ('asset_closure_sha256',), task['task'] + '/actual robot asset closure')
        assets.update(task['asset_closure_sha256'])
    elif family == 'pipette_transfer':
        assets = task['asset_closure_sha256']
    else:
        assets = {k: v for k, v in manifest['files'].items() if k.startswith('tasks/assets/')}
    result = source_identity(assets, repo)
    if 'generated_urdf' in task:
        row = task['generated_urdf']
        require(track(inside(repo, row['path'])) == row['sha256'], 'Generated URDF changed')
        result['generated_urdf'] = row
    return result


def robot_closure(files, repo, urdf_names):
    import shlex
    import xml.etree.ElementTree as ET
    require(urdf_names, 'Raw state identifies no actual robot articulation')
    roots = [inside(repo, name) for name in files if Path(name).name in urdf_names]
    require({p.name for p in roots} == set(urdf_names), 'Actual robot URDF absent from asset closure')
    found, pending = set(roots), list(roots)
    while pending:
        path = pending.pop()
        refs = []
        if path.suffix.lower() == '.urdf':
            refs = [node.get('filename') for node in ET.parse(path).getroot().iter()
                    if node.tag in ('mesh', 'texture') and node.get('filename')]
        elif path.suffix.lower() in ('.obj', '.mtl'):
            for line in path.read_text(encoding='utf-8').splitlines():
                parts = shlex.split(line, comments=True)
                if parts and (parts[0] == 'mtllib' or parts[0].startswith('map_')):
                    refs.extend(parts[1:])
        for reference in refs:
            target = (path.parent / reference).resolve(strict=True)
            require(target.is_relative_to(repo), 'Robot dependency escapes repository')
            key = target.relative_to(repo).as_posix()
            require(files.get(key) == track(target), 'Robot mesh/texture dependency omitted: ' + key)
            if target not in found:
                found.add(target)
                pending.append(target)
    return {'files': len(found), 'sha256': {p.relative_to(repo).as_posix(): track(p) for p in sorted(found)}}


def shaders_check(rendering, binding, repo, task, environments):
    fields(rendering, ('shader_pack', 'bias_ndc', 'source_shader_sha256', 'generated_shader_sha256', 'patch_sha256'), 'Pipette shader closure')
    require(rendering['shader_pack'] == 'default' and rendering['bias_ndc'] == 2e-6, 'Unreviewed repaired shader configuration')
    root = binding.parent / 'vulkan_shader'
    files = {p.relative_to(root).as_posix(): track(p) for folder in ('common', 'default')
             for p in sorted((root / folder).rglob('*')) if p.is_file()}
    require(files == rendering['source_shader_sha256'], 'Current full shader source closure differs')
    H.digest_map(rendering['generated_shader_sha256'], 'Generated shader closure')
    require(files.keys() == rendering['generated_shader_sha256'].keys(), 'Generated shader coverage differs')
    # Reconstruct the reviewed two-fragment transformation in memory only. The
    # transient generated files no longer exist after capture; do not claim a reread.
    constants = ('layout(constant_id=20) const int pipetteTipRenderId=-1;\n'
                 'layout(constant_id=21) const float pipetteDepthBias=0.0;\n\n')
    patch = ('\n  gl_FragDepth = gl_FragCoord.z;\n'
             '  if (int(inSegmentation.x) == pipetteTipRenderId)\n'
             '    gl_FragDepth = clamp(gl_FragCoord.z-pipetteDepthBias, 0.0, 1.0);')
    import hashlib
    require(hashlib.sha256((constants + patch).encode()).hexdigest() == rendering['patch_sha256'], 'Shader patch SHA differs')
    generated = dict(files)
    for name in ('default/gbuffer.frag', 'default/gbuffer1.frag'):
        text = (root / name).read_text(encoding='utf-8')
        require(text.count('#define SET_NUM 0') == text.count('void main() {') == 1, 'Shader anchors differ')
        text = text.replace('#define SET_NUM 0', constants + '#define SET_NUM 0', 1).replace('void main() {', 'void main() {' + patch, 1)
        # Path.write_text uses the capture platform's newline convention.
        generated[name] = hashlib.sha256(text.replace('\n', '\r\n').encode()).hexdigest() if sys.platform == 'win32' else hashlib.sha256(text.encode()).hexdigest()
    require(generated == rendering['generated_shader_sha256'], 'Recomputed generated shader bytes differ')
    arm = environments if task == 'AspirateLiquid' else 0
    require(rendering.get('sample_cup_original_shading_modes') == [0] * arm
            and rendering.get('sample_cup_fixed_shading_modes') == [1] * arm,
            'Pipette original and fixed transparency modes do not match the task and backend')
    ids = rendering.get('tip_render_ids')
    require(isinstance(ids, list) and len(ids) == environments
            and all(type(i) is int and i > 0 for i in ids), 'Pipette tip render IDs are invalid')
    return rendering


def shared_shader_identity(rendering):
    scoped = {'tip_render_ids', 'sample_cup_original_shading_modes', 'sample_cup_fixed_shading_modes'}
    return {k: v for k, v in rendering.items() if k not in scoped}


def external_identity(files):
    spec = importlib.util.find_spec('mani_skill')
    require(spec is not None and spec.origin, 'Cannot locate captured ManiSkill package')
    package = Path(spec.origin).parent
    H.digest_map(files, 'External ManiSkill closure')
    expected_names = {'mani_skill/' + p.relative_to(package).as_posix() for p in package.rglob('*.py')}
    expected_names.update('mani_skill/' + name for name in ('utils/scene_builder/table/assets/table.glb',
                                                          'utils/building/assets/grid_texture.png'))
    require(set(files) == expected_names, 'External ManiSkill/table/ground closure has omissions or extra entries')
    for name, expected in files.items():
        require(name.startswith('mani_skill/'), 'Unknown external package root')
        require(track(inside(package, name[len('mani_skill/'):])) == expected, 'External package/asset changed: ' + name)
    return {'raw_sha256': files,
        'lf_sha256': {name: H.lf_text_sha((package / name[len('mani_skill/'):]).read_bytes(), Path(name).suffix)
                     for name in files if Path(name).suffix in ('.py', '.json')}}


def cpu_coverage(sample, index, family):
    keys = set(sample)
    for fragment in ('/state/articulations/', '/controller/', '/obs', '/info/success'):
        require(any(fragment in k for k in keys), 'CPU snapshot omits required field group: ' + fragment)
    for suffix in ('/elapsed_steps', '/robot/qpos', '/robot/qvel', '/robot/qf',
                   '/robot/position_target', '/robot/velocity_target'):
        require(any(k.endswith(suffix) for k in keys), 'CPU snapshot omits required field: ' + suffix)
    if index:
        require({'/reward', '/terminated', '/truncated'} <= keys, 'CPU step snapshot omits reward/termination')
    task_state = 'screwing_task_state' if family == 'nut_bolt' else 'pipette_task_state' if family == 'pipette_transfer' else None
    if task_state:
        require(any(k.endswith('/' + task_state) for k in keys), 'CPU snapshot omits serialized task bookkeeping')
    if family == 'nut_bolt':
        for suffix in ('_success_hold_count', '_success_last_eval_step', '_task_phase', '_bolt_locked',
                       '_bolt_lock_pose', '_cum_rotation', '_threaded_depth'):
            require('/bookkeeping/' + suffix in keys, 'Nut CPU snapshot omits bookkeeping: ' + suffix)


def cpu_check(root, gpu, family, profile, repo, expected, required, sdk_record):
    report = read(root / 'summary.json')
    expected_total = len(profile['tasks']) * 5 * 60
    require(report['status'] == 'passed' and report['source_hashes_unchanged'] is True
            and not report['failures'] and report['control_steps_per_run'] == 60
            and report['completed_runs'] == len(profile['tasks']) * 5
            and report['total_control_steps'] == expected_total
            and report['total_physics_steps'] == expected_total * 20
            and report.get('counts_complete', True) is True and not report.get('unknown_runs', []),
            'CPU requires all tasks x five schemes x 60 control steps (900/600 total), including native_repeat')
    require(set(report['tasks']) == set(profile['tasks']), 'CPU task coverage differs')
    source = report['source_sha256']
    external_key = 'external_files' if family == 'office_desk' else 'external_sha256'
    if external_key in report:
        require(report[external_key] == gpu['external_files'] and report.get('external_hashes_unchanged') is True,
                'CPU summary external closure differs or changed during capture')
    # Only named verification tools may differ between CPU and GPU maps. Never
    # exclude production code, bindings, catalogs, shaders or assets by glob.
    excluded = {'tools/variation/' + profile['checker'], 'tools/variation/' + profile['dynamics']}
    if family == 'pipette_transfer':
        excluded.add('tools/variation/check_pipette_rendering.py')
    identity = source_identity(source, repo, allowed_tool_changes=excluded)
    a = {k: v for k, v in source.items() if k not in excluded}
    b = {k: v for k, v in gpu['files'].items() if k not in excluded}
    require(a and a == b, 'CPU/GPU production/asset closure differs; missing CPU=' + str(sorted(b.keys() - a.keys()))
            + ', missing GPU=' + str(sorted(a.keys() - b.keys())) + ', changed=' + str(sorted(k for k in a.keys() & b.keys() if a[k] != b[k])))
    compact = dict(summary_sha256=track(root / 'summary.json'), control_steps=expected_total,
        physics_steps=expected_total * 20, source=identity, seed=report['seed'], tasks={},
        sdk_python=gpu['sdk_python'],
        cpu_gpu_overlap={'files': len(a), 'map_sha256': H.canonical_sha(a),
                         'explicit_tool_exclusions': sorted(excluded)})
    for task in profile['tasks']:
        schemes = schemes_for(family, task)
        aliases = ('native_off', 'native_repeat', *schemes)
        if family == 'office_desk' and task == 'ClickMouse':
            aliases = ('native_off', 'native_repeat', 'original', 'variant_1', 'variant_2')
        require(set(report['tasks'][task]) == set(aliases), task + ': CPU requires exactly all five schemes')
        actions_path = root / task / 'actions.npy'
        action_sha = track(actions_path)
        actions = np.load(actions_path, allow_pickle=False)
        require(actions.dtype == np.float32 and actions.ndim >= 2 and actions.shape[0] == 60
                and np.isfinite(actions).all() and np.any(actions != 0), 'CPU action sequence is invalid/trivial')
        baseline, runs, motion = None, {}, 0.0
        for index, alias in enumerate(aliases):
            directory = root / task / alias
            run = read(directory / 'run.json')
            status = report['tasks'][task][alias]
            actual_scheme = 'native_off' if index < 2 else schemes[index - 2]
            require(run['task'] == task and run['scheme'] == alias and run['status'] == 'completed'
                    and run['source_sha256'] == source and run['seed'] == report['seed']
                    and run['requested_control_steps'] == run['control_steps'] == 60
                    and run['sim_steps_per_control'] == 20 and run['physics_steps'] == 1200
                    and run['image_capture'] is False and run['actions']['legal'] is True
                    and run['actions']['sha256'] == action_sha and run['actions']['shape'] == list(actions.shape),
                    task + '/' + alias + ': CPU worker scope/action/source mismatch')
            if 'actual_scheme_id' in run:
                require(run['actual_scheme_id'] == actual_scheme, 'Office Mouse actual scheme ID differs')
            if isinstance(status, dict):
                require(status.get('returncode', 0) == 0, 'CPU child process failed')
                if 'run_sha256' in status:
                    require(status['run_sha256'] == track(directory / 'run.json'), 'CPU summary/run SHA differs')
            kwargs = run.get('constructor_kwargs', {})
            if family == 'pipette_transfer':
                require('physx_cpu' in run['backend'] and 'cpu' in run['backend']
                        and run['pipette_rendering'] == {'enabled': True}, 'Pipette CPU/rendering scope differs')
                config = run['appearance_config']
            elif family == 'office_desk':
                require(kwargs.get('sim_backend') == 'physx_cpu' and kwargs.get('num_envs') == 1, 'CPU worker backend/environment mismatch')
                config = run['appearance_config']
            else:
                require(kwargs.get('sim_backend') == 'physx_cpu' and kwargs.get('num_envs') == 1, 'CPU worker backend/environment mismatch')
                config = kwargs[option_for(profile, task)]
            require(isinstance(config, dict) and (config.get('enabled') is False if index < 2
                    else config.get('enabled') is True and config.get('scheme_id') == actual_scheme), 'CPU appearance configuration differs')
            private_path = directory / 'private_sdk.json'
            require(private_path.is_file(), f'{task}/{alias}: missing private SDK worker receipt')
            sdk = read(private_path)
            require(sdk.get('binaries_unchanged') is True
                    and sdk.get('artifact_sha256') == sdk_record['artifact_sha256']
                    and sdk.get('version') == sdk_record['version'], 'CPU child SDK artifact/version differs')
            launcher_check(sdk, repo, 'tools/variation/' + profile['dynamics'], source,
                           profile.get('launcher', LAUNCHER), sdk_record)
            require(vulkan_loader_check(sdk) == gpu['system_vulkan_loader'], 'CPU/GPU system Vulkan loader differs')
            sdk_compact, binding = sdk_check(sdk['before'], sdk['after'], expected, required, gpu=False)
            worker_python = sdk_python_check(sdk, binding)
            require(worker_python == gpu['sdk_python'], f'{task}/{alias}: CPU/GPU private SDK Python identity differs')
            require(run['sapien_binary']['sha256'] == expected[binding.name], 'CPU run binding differs from loaded DLL identity')
            fields(run, (external_key,), task + '/' + alias + '/external closure')
            require(run[external_key] == gpu['external_files']
                    and run.get('external_hashes_unchanged', True) is True, 'CPU/GPU external ManiSkill/table closure differs')
            external_identity(run[external_key])
            if family == 'nut_bolt':
                if task != 'PickBolt':
                    require(run['generated_urdf'] == gpu['tasks'][task]['generated_urdf'], 'CPU/GPU generated nut URDF differs')
                    require(track(inside(repo, run['generated_urdf']['path'])) == run['generated_urdf']['sha256'], 'Generated nut URDF changed')
            else:
                assets = run.get('asset_closure_sha256')
                fields({'asset_closure_sha256': assets}, ('asset_closure_sha256',), 'CPU assets')
                require(isinstance(assets, dict) and assets == gpu['tasks'][task]['asset_closure_sha256'], 'CPU/GPU robot asset closure differs')
                source_identity(assets, repo)
                if family == 'office_desk':
                    require(run.get('asset_files') == gpu['asset_files'], 'CPU/GPU Office model asset closure differs')
                    require(office_asset_root(run) == gpu['tasks'][task]['object_asset_root'], 'CPU/GPU Office asset roots differ')
                    if task == 'ClickMouse':
                        require(mouse_collision_check(run, repo) == gpu['tasks'][task]['mouse_collision_identity'],
                                'CPU/GPU Mouse collision inputs differ')
            if family == 'pipette_transfer':
                rendering = shaders_check(run['rendering'], binding, repo, task, 1)
                require(shared_shader_identity(rendering) == shared_shader_identity(gpu['tasks'][task]['rendering_identity']),
                        'CPU/GPU shader/patch/bias identity differs')
            states = load(directory / 'trajectory.pt')
            require(isinstance(states, list) and len(states) == 61, 'CPU trajectory requires all 61 initial/step samples')
            if baseline is None:
                baseline = states
            for sample, (reference, actual) in enumerate(zip(baseline, states)):
                exact(reference, actual, f'{task}/{alias}/sample{sample}')
                cpu_coverage(actual, sample, family)
                if sample:
                    for key, value in actual.items():
                        if key in baseline[0] and key.endswith('/qpos') and value.numel():
                            motion = max(motion, float((value.double() - baseline[0][key].double()).abs().max()))
            runs[alias] = dict(actual_scheme_id=actual_scheme, run_sha256=track(directory / 'run.json'),
                run_file=f'{task}/{alias}/run.json', trajectory_file=f'{task}/{alias}/trajectory.pt',
                trajectory_sha256=track(directory / 'trajectory.pt'), samples=61, control_steps=60,
                physics_steps=1200, max_absolute_error_vs_native=0, sdk=sdk_compact,
                private_sdk_sha256=track(private_path), sdk_python_map_sha256=worker_python['map_sha256'])
            if family == 'pipette_transfer':
                runs[alias]['rendering_identity'] = {k: v for k, v in rendering.items() if k not in shared_shader_identity(rendering)}
            if index:
                comparison_path = directory / 'comparison.json'
                comparison = read(comparison_path)
                require(comparison['status'] == 'passed' and comparison['samples'] == 61
                        and comparison['initial_state_equal'] is True and not comparison['failed_steps']
                        and comparison['worst_difference']['max_absolute_error'] == 0, 'CPU recorded exact comparison differs')
                runs[alias]['comparison_sha256'] = track(comparison_path)
        require(motion > 0, 'CPU trajectory exercises no joint motion')
        compact['tasks'][task] = dict(actions_file=f'{task}/actions.npy', actions_sha256=action_sha, action_shape=list(actions.shape),
            maximum_joint_displacement_rad=motion, runs=runs)
    return compact


def repository(profile):
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ('tasks/' + profile['prefix'].replace('NutBolt', 'nut_bolt').replace('PipetteTransfer', 'pipette_transfer').replace('OfficeDesk', 'office_desk'))).is_dir():
            return parent
    candidate = here.parent.parent / 'family-work' / profile['folder']
    if candidate.is_dir():
        return candidate.resolve()
    raise ValueError('Cannot locate family repository; deploy to tools/variation or keep in workspace .coordination')


def sdk_build_identity(family, repo, artifact, lock):
    if family == 'nut_bolt':
        launcher = PROFILES[family]['launcher']
        validator = inside(repo, str(PurePosixPath(launcher).with_name('native_lock_identity.py')))
        validator_hash = track(validator)
        spec = importlib.util.spec_from_file_location('_native_lock_identity', validator)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sdk = module.validate_sdk(artifact.parent, expected_artifact_sha256=track(artifact),
                                  base_recipe_root=repo / 'tools/variation/sapien_sdk')
        require(sdk['version'] == '3.0.3+dexarena.gpu1.wininterop7'
                and sdk['build']['clean_full_build_executed'] is True
                and track(lock) == sdk['lock_sha256'], 'Nut requires the clean visibility-capable SDK')
        patches = read(lock)['patches']
        visibility = [patch for patch in patches if Path(patch['file']).name == '0310-batched-render-visibility.patch']
        require(len(visibility) == 1 and track(inside(lock.parent, visibility[0]['file'])) == visibility[0]['sha256'],
                'Nut visibility fix is not covered by the selected source recipe')
        public = {k: sdk[k] for k in ('schema', 'version', 'source_commit', 'artifact_sha256', 'lock_sha256',
                  'wheel_sha256', 'native_files', 'physx_gpu', 'wheel_record_entries_verified', 'capabilities_expected')}
        public.update(build_mode=sdk['build']['build_mode'], clean_full_build_scope=sdk['build']['clean_full_build_scope'],
                      physx_host_dependency_reused=sdk['build']['physx_host_dependency_reused'],
                      sdk_validator_sha256=validator_hash, patches=patches,
                      build_provenance_canonical_sha256=H.canonical_sha(sdk['build']),
                      build_acceptance_canonical_sha256=H.canonical_sha(sdk['build_acceptance']))
        return sdk, sdk['expected_loaded'], set(sdk['required_loaded']), public
    sdk, expected, required = H.sdk_identity(artifact, lock)
    public = {k: v for k, v in sdk.items() if k not in ('actual_toolchain', 'build_acceptance')}
    public['actual_toolchain_canonical_sha256'] = H.canonical_sha(sdk['actual_toolchain'])
    public['build_acceptance_canonical_sha256'] = H.canonical_sha(sdk['build_acceptance'])
    for name in ('prepare.py', 'build_windows.ps1', 'unpack_wheel.py', 'run_check.py'):
        track(lock.parent / name)
    for patch in sdk['patches']:
        track(inside(lock.parent, patch['file']))
    return sdk, expected, required, public


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--family', choices=tuple(PROFILES), required=True)
    parser.add_argument('--run', type=Path, action='append', required=True)
    parser.add_argument('--console-run', type=Path, action='append', required=True)
    parser.add_argument('--sdk-artifacts', type=Path, required=True)
    parser.add_argument('--sdk-lock', type=Path, required=True)
    parser.add_argument('--cpu-run', type=Path, required=True)
    parser.add_argument('--cpu-console-run', type=Path, required=True)
    parser.add_argument('--probe-summary', type=Path, help='Verify the SDK identity of a supplementary Pipette optical summary')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    family, profile = args.family, PROFILES[args.family]
    if args.probe_summary is not None and family != 'pipette_transfer':
        parser.error('--probe-summary requires --family pipette_transfer')
    repo = repository(profile)
    configure(repo)
    WATCHED.clear()
    require(not args.output.exists(), 'Choose a fresh output directory')
    require(len(args.run) == len(args.console_run), 'One --console-run is required per --run')
    artifact, lock = args.sdk_artifacts.resolve(strict=True), args.sdk_lock.resolve(strict=True)
    track(artifact)
    track(lock)
    sdk, expected, required, sdk_out = sdk_build_identity(family, repo, artifact, lock)
    launcher_path = profile.get('launcher', LAUNCHER)
    prepared, images, captures, gpu_identity = {}, {}, [], None
    for capture, console in zip(args.run, args.console_run):
        capture, console = capture.resolve(strict=True), console.resolve(strict=True)
        results, manifest, private = (read(capture / n) for n in ('results.json', 'manifest.json', 'private_sdk.json'))
        require(results['status'] == results['formal_acceptance'] == 'passed'
                and results['test_mode'] == manifest['test_mode'] == 'standard'
                and results['source_hashes_unchanged'] is True
                and manifest['sim_backend'] == 'physx_cuda' and manifest['num_envs'] == 2,
                'Complete standard two-environment CUDA acceptance required')
        require('--diagnostic-native-readback' not in manifest['command'], 'Diagnostic readback cannot be exported')
        source = manifest['files']
        identity = source_identity(source, repo)
        for filename in (launcher_path, 'tools/variation/' + profile['checker'], 'tools/variation/' + profile['dynamics'],
                         'tools/variation/check_furniture_appearance.py', 'tools/variation/check_furniture_dynamics.py',
                         'tasks/furniture_assembly/reset_scope.py'):
            require(filename in source, 'Missing verification source closure: ' + filename)
        if family in ('nut_bolt', 'pipette_transfer'):
            require('tasks/furniture_assembly/appearance.py' in source, 'Missing shared appearance production closure')
        if family == 'nut_bolt':
            require('tasks/assets/task_object_meshes/screwing/bolt_hex_head.obj' in source, 'Missing original bolt mesh input')
        production = [p for folder in (family, 'robots', 'config', 'scene_builders')
                      for p in (repo / 'tasks' / folder).rglob('*.py')]
        require(all(p.relative_to(repo).as_posix() in source for p in production), 'Family/robot/reset production source closure incomplete')
        launcher_check(private, repo, 'tools/variation/' + profile['checker'], source, launcher_path, sdk)
        require(private.get('binaries_unchanged') is True and private.get('artifact_sha256') == sdk['artifact_sha256']
                and private.get('version') == manifest['versions']['sapien'] == sdk['version'], 'GPU SDK artifact/version differs')
        loaded, binding = sdk_check(private['before'], private['after'], expected, required, gpu=True)
        sdk_python = sdk_python_check(private, binding)
        recorded_binding = manifest.get('sapien_binary_sha256', manifest.get('sapien_binary', {}).get('sha256'))
        if recorded_binding is not None:
            require(recorded_binding == expected[binding.name], 'GPU manifest binding differs from actual loaded SDK')
        for key, expected_value in (('physx_gpu_library_sha256', sdk['physx_gpu']['dll_sha256']),
                                    ('physx_version', sdk['physx_gpu']['version'])):
            if key in manifest:
                require(manifest[key] == expected_value, 'GPU PhysX manifest identity differs')
        tasks = results['tasks']
        require(tasks and all(t['task'] in profile['tasks'] for t in tasks), 'Unknown/empty GPU task set')
        current = {'files': source, 'versions': manifest['versions'], 'sdk': loaded, 'sdk_python': sdk_python,
                   'system_vulkan_loader': vulkan_loader_check(private)}
        fields(manifest, ('external_files',), family + '/captured external closure')
        require(results.get('external_hashes_unchanged') is True, 'External inputs changed or unchanged receipt missing')
        current['external_files'] = manifest['external_files']
        current['external_identity'] = external_identity(current['external_files'])
        if family == 'office_desk':
            current['asset_files'] = manifest['asset_files']
            require(manifest.get('material_representation') ==
                    'logical source visual/nativepart/groups; actual render topology retained separately per task',
                    'Office manifest lacks reviewed logical/actual material representation')
        require(gpu_identity is None or all(current[k] == gpu_identity[k] for k in current), 'GPU captures use different source/SDK/assets')
        if gpu_identity is None:
            gpu_identity = {**current, 'tasks': {}, 'source_identity': identity}
        task_control, task_physics = 0, 0
        for task in tasks:
            name = task['task']
            require(name not in prepared, 'Duplicate GPU task: ' + name)
            capture_path = task.get('capture_path') if family == 'nut_bolt' else manifest.get('capture_path')
            require(capture_path == profile['capture'], 'Task is not the reviewed standard CUDA camera path')
            asset_record = asset_identity(family, manifest, task, repo)
            CAPTURE_FILES.clear()
            CAPTURE_FILES.update(source)
            CAPTURE_FILES.update(current['external_files'])
            CAPTURE_FILES.update(asset_record['raw_sha256'])
            task_identity = {'assets': asset_record}
            for key in ('asset_closure_sha256', 'generated_urdf'):
                if key in task:
                    task_identity[key] = task[key]
            if family == 'pipette_transfer':
                task_identity['rendering_identity'] = shaders_check(task['rendering'], binding, repo, name, 2)
            if family == 'office_desk':
                task_identity['object_asset_root'] = office_asset_root(task)
                if name == 'ClickMouse':
                    task_identity['mouse_collision_identity'] = mouse_collision_check(task, repo)
            gpu_identity['tasks'][name] = task_identity
            prepared[name] = task_check(capture, task, family, profile, images, repo)
            task_identity['robot_closure'] = robot_closure(asset_record['raw_sha256'], repo, prepared[name]['robot_urdf_names'])
            prepared[name]['inputs'] = task_identity
            task_control += task['control_steps']
            task_physics += task['physics_steps']
        require(results['physics_steps'] == task_physics
                and ('control_steps' not in results or results['control_steps'] == task_control), 'GPU aggregate step counts differ')
        captures.append(dict(results_sha256=track(capture / 'results.json'), manifest_sha256=track(capture / 'manifest.json'),
            private_sdk_sha256=track(capture / 'private_sdk.json'), task_ids=[f"{profile['prefix']}{t['task']}-Sharpa-v1" for t in tasks],
            sdk_python_map_sha256=sdk_python['map_sha256'],
            capture_path=profile['capture'], command=portable_command(manifest['command'], repo),
            control_steps=task_control, physics_steps=task_physics,
            launcher=private['launcher'], console=console_check(console, capture, results, private, repo, profile)))
    require(set(prepared) == set(profile['tasks']), 'All family tasks must be captured exactly once')
    cpu_run = args.cpu_run.resolve(strict=True)
    cpu = cpu_check(cpu_run, gpu_identity, family, profile, repo, expected, required, sdk)
    cpu['console'] = cpu_console_check(args.cpu_console_run.resolve(strict=True), cpu_run, repo, profile)
    require(len(images) == len(profile['tasks']) * 7, 'Expected seven unchanged original PNGs per task')
    sdk_out.update(runtime_python=gpu_identity['sdk_python'], loaded_native=gpu_identity['sdk'],
                   system_vulkan_loader=gpu_identity['system_vulkan_loader'],
                   identity_scope='Private SDK Python sources and native libraries')
    summary = dict(format='task-runtime-evidence-v1', family=family, status='passed',
        scope='Short-task appearance/reset acceptance; CPU exact dynamics and two standard CUDA environments; no complete robot task, Long or Linux claim',
        exporter={'file': Path(__file__).name, 'sha256': track(Path(__file__)),
                  'lf_sha256': H.lf_text_sha(Path(__file__).read_bytes(), '.py'),
                  'helper': BASE_HELPER, 'helper_sha256': track(repo / BASE_HELPER)},
        source_identity=gpu_identity['source_identity'], sdk=sdk_out, captures=captures, tasks={}, images={})
    if 'external_identity' in gpu_identity:
        summary['external_identity'] = gpu_identity['external_identity']
    if args.probe_summary is not None:
        summary['supplementary_probe_sdk'] = probe_sdk_check(args.probe_summary, repo, gpu_identity, expected, required, sdk)
    captured_paths = {inside(repo, name) for name in gpu_identity['files']}
    if args.probe_summary is not None:
        supplementary = summary['supplementary_probe_sdk']
        captured_paths.update(inside(repo, supplementary[k]) for k in ('capture_tool', 'exporter'))
    for identity in gpu_identity['tasks'].values():
        captured_paths.update(inside(repo, name) for name in identity['assets']['raw_sha256'])
        if 'generated_urdf' in identity:
            captured_paths.add(inside(repo, identity['generated_urdf']['path']))
    for path in WATCHED:
        if path.is_relative_to(repo) and path not in captured_paths:
            rel = path.relative_to(repo).as_posix()
            require(path == Path(__file__).resolve() or rel == BASE_HELPER or rel.startswith('tools/variation/sapien_sdk/')
                    or rel.startswith('outputs/') or rel.startswith('.local/'),
                    'Captured closure omits an input used by exporter: ' + rel)
    payloads = {'cpu_checks.json': cpu}
    for task, checks in prepared.items():
        payloads[task + '/checks.json'] = checks
    encoded = {name: (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
               for name, value in payloads.items()}
    import hashlib
    if args.probe_summary is not None:
        probe_bytes = args.probe_summary.read_bytes()
        require(hashlib.sha256(probe_bytes).hexdigest() == supplementary['summary_sha256'], 'Optical summary changed')
        encoded[supplementary['summary_file']] = probe_bytes
    summary['cpu_dynamics'] = {'checks': 'cpu_checks.json', 'sha256': hashlib.sha256(encoded['cpu_checks.json']).hexdigest()}
    for task in prepared:
        name = task + '/checks.json'
        summary['tasks'][task] = {'checks': name, 'sha256': hashlib.sha256(encoded[name]).hexdigest()}
    # Cache original bytes after verification. Never re-encode images.
    png_bytes = {}
    for name, path in images.items():
        png(path)
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == WATCHED[path.resolve()], 'PNG changed after validation')
        png_bytes[name] = raw
        summary['images'][name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'source_file': name.split('/')[0] + '/' + path.name,
            'layout': 'native | scheme' if family == 'nut_bolt' and '_human_env0' in name else
                      'before | after' if '/local_' in name else 'single frame'}
    for path, expected_sha in WATCHED.items():
        require(H.sha(path) == expected_sha, 'Input changed before export: ' + path.name)
    require(not args.output.exists(), 'Output appeared during verification')
    # All validation and serialization precedes the first output filesystem write.
    args.output.mkdir(parents=True, exist_ok=False)
    for name, raw in {**encoded, **png_bytes}.items():
        path = args.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    H.write(args.output / 'summary.json', summary)
    print(json.dumps({'status': 'exported', 'family': family, 'tasks': len(prepared), 'images': len(images)}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, FileNotFoundError, TypeError) as error:
        print(f'Evidence export rejected: {error}', file=sys.stderr)
        raise SystemExit(2)
