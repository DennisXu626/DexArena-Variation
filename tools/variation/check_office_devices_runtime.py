"""Formal Office short-task checks using the reset/controller/RGB checks in main.

CPU: one environment, no image capture. CUDA: two real solver environments and
standard ManiSkill RGB, selected reset intent/readback, controller/task/appearance
RNG and pixel isolation, both selection directions, and two control steps.
"""
import argparse
import copy
import gc
import hashlib
from importlib import metadata
from itertools import combinations
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.variation import check_furniture_appearance as C
from tools.variation.office_devices_materials import _RUNTIME as P
TASKS = {'OpenLaptop':'laptop', 'TypeKeys':'keyboard', 'ClickMouse':'mouse'}
MOUSE_CATALOG = ROOT / 'tasks/assets/variation/office_desk/mouse_101408/v1/catalog.json'
DEVICE_SCHEMES = tuple(json.loads(P.CATALOG.read_text(encoding='utf-8'))['schemes'])
SCHEMES = {'OpenLaptop': DEVICE_SCHEMES, 'TypeKeys': DEVICE_SCHEMES,
           'ClickMouse': tuple(json.loads(MOUSE_CATALOG.read_text(encoding='utf-8'))['schemes'])}
BASELINE = '56a4aec4740b7139307e01048fa0e8e6ed430f14'
MODEL_ASSET_ROOT = ROOT / 'tasks/assets/task_object_meshes/office'


def dump(path, value):
    C.dump(path,value)


def source_hashes():
    sources = set()
    sources.update((ROOT/'tasks').rglob('*.py'))
    for name in ('tasks/furniture_assembly/reset_scope.py','tools/variation/check_furniture_appearance.py','tools/variation/check_furniture_dynamics.py','tools/variation/sapien_sdk/run_task_check.py'):
        sources.add(ROOT/name)
    sources.update((ROOT/'tools/variation').glob('*office_devices*.py'))
    sources.update((ROOT/'tasks/assets/variation/office_desk').rglob('*.json'))
    sources.update((ROOT/'assets/appearance/objects/office_desk').rglob('*.json'))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)}


def asset_hashes():
    root=MODEL_ASSET_ROOT
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for model in ('10211','13106','101408') for p in sorted((root/model).rglob('*')) if p.is_file()}


def require_model_asset_root(task):
    from importlib import import_module

    module, variable = {'OpenLaptop': ('open_laptop', 'LAPTOP_ASSET_DIR'),
                        'TypeKeys': ('type_keys', 'KEYBOARD_ASSET_DIR'),
                        'ClickMouse': ('click_mouse', 'MOUSE_ASSET_DIR')}[task]
    task_module = import_module(f'tasks.office_desk.office_desk_{module}')
    assert Path(task_module.__file__).resolve().parent == (ROOT / 'tasks/office_desk').resolve()
    actual_root = getattr(task_module, variable).resolve(strict=True)
    assert actual_root == MODEL_ASSET_ROOT.resolve(strict=True), f'{task} uses an uncaptured asset root: {actual_root}'
    return MODEL_ASSET_ROOT.relative_to(ROOT).as_posix()


def asset_closure(base):
    import shlex
    import xml.etree.ElementTree as ET
    paths={Path(base.agent.urdf_path).resolve(strict=True)};pending=list(paths)
    while pending:
        path=pending.pop();references=[]
        if path.suffix.lower()=='.urdf':
            references=[node.get('filename') for node in ET.parse(path).getroot().iter()
                        if node.tag in ('mesh','texture') and node.get('filename')]
        elif path.suffix.lower() in ('.obj','.mtl'):
            for line in path.read_text(encoding='utf-8').splitlines():
                values=shlex.split(line,comments=True)
                if values and (values[0]=='mtllib' or values[0].startswith('map_')):references.extend(values[1:])
        for reference in references:
            target=(path.parent/reference).resolve(strict=True)
            if not target.is_relative_to(ROOT):raise ValueError('Office robot asset escapes repository')
            if target not in paths:paths.add(target);pending.append(target)
    return {path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def closure_unchanged(files):
    return all((ROOT/name).is_file() and hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected
               for name,expected in files.items())


def external_hashes():
    import mani_skill
    package=Path(mani_skill.__file__).resolve().parent
    files=list(package.rglob('*.py'))+[package/'utils/scene_builder/table/assets/table.glb',
                                     package/'utils/building/assets/grid_texture.png']
    return {'mani_skill/'+path.relative_to(package).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(files))}


def mouse_collision_identity():
    import coacd
    import trimesh
    import xml.etree.ElementTree as ET

    coacd_python = Path(coacd.__file__).resolve(strict=True)
    coacd_native = Path(coacd._lib._name).resolve(strict=True)
    if platform.system() == 'Windows':
        import ctypes
        loaded_name = ctypes.create_unicode_buffer(32768)
        loader = ctypes.WinDLL('kernel32').GetModuleFileNameW
        loader.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
        loader.restype = ctypes.c_uint32
        assert loader(coacd._lib._handle, loaded_name, len(loaded_name))
        assert Path(loaded_name.value).resolve(strict=True) == coacd_native
    assert coacd_native.parent == coacd_python.parent
    version = metadata.version('coacd')
    assert version == '1.0.14', 'ClickMouse requires the verified CoACD version 1.0.14'
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    files = {f'coacd/{path.name}': sha(path) for path in (coacd_python, coacd_native)}
    if platform.system() == 'Windows':
        assert files == {'coacd/__init__.py': '6a521661951e15382e52f385722f64bfdd6f3e09cfd1e95c7c3967ba3533b4c6',
                         'coacd/lib_coacd.dll': 'a32e801d260b774ebc723edfc05e45e179c09d0d2355592c64cbff490698e806'}
    model = MODEL_ASSET_ROOT / '101408'
    meshes = sorted({node.attrib['filename'] for node in ET.parse(model / 'mobility.urdf').findall('.//collision/geometry/mesh')})
    assert len(meshes) == 5
    caches = {}
    parameters = ('threshold=0.05, max_convex_hull=-1, preprocess_mode=auto, preprocess_resolution=30, '
                  'resolution=2000, mcts_nodes=20, mcts_iterations=150, mcts_max_depth=3, pca=False, merge=True, seed=0')
    for name in meshes:
        mesh = (model / name).resolve(strict=True)
        assert mesh.is_relative_to(model)
        cache = mesh.with_name(mesh.name + '.coacd.ply')
        md5 = hashlib.md5(mesh.read_bytes()).hexdigest()
        with cache.open('rb') as stream:
            header = [stream.readline() for _ in range(3)]
        assert header == [b'ply\n', b'format binary_little_endian 1.0\n',
                          f'comment md5={md5}, {parameters}\n'.encode('ascii')], name
        caches[cache.relative_to(ROOT).as_posix()] = {'sha256': sha(cache), 'mesh_source_md5': md5}
    return {'coacd_version': version, 'coacd_files': files,
            'trimesh_version': metadata.version('trimesh'),
            'trimesh_import_sha256': sha(Path(trimesh.__file__)), 'caches': caches}


def adapter(base):
    return base._mouse_appearance if hasattr(base,'_mouse_appearance') else base._office_devices_appearance


def key_for(task):
    return 'mouse_appearance' if task=='ClickMouse' else 'office_devices_appearance'


def verify_release_targets(base, task):
    if task == 'TypeKeys':
        target = base.keyboard.get_drive_targets()
        expected = base._all_key_released
        compared = 'all active keys'
    elif task == 'ClickMouse':
        mouse_targets = base.mouse.get_drive_targets()
        indices = torch.arange(base.num_envs, device=mouse_targets.device)
        target = torch.stack((mouse_targets[indices, base._left_indices], mouse_targets[indices, base._right_indices]), dim=-1)
        expected = torch.stack((base.left_released, base.right_released), dim=-1)
        compared = 'left and right buttons'
    else:
        return None
    assert torch.equal(target, expected), f'{task} release drive target changed'
    return {'target_joints_per_environment': target.shape[-1], 'compared': compared,
            'actual': C.plain(target), 'expected': C.plain(expected)}


def articulations(base):
    result={'robot':base.agent.robot}
    for name in ('laptop','keyboard','mouse'):
        if hasattr(base,name):result[name]=getattr(base,name)
    return result


_ORIGINAL_SLOTS=C.material_slots
_ORIGINAL_PHYSICAL=C.physical
_ORIGINAL_MATERIAL_VALUES=C.material_values
_ORIGINAL_JOINT_SIGNATURE=C.joint_signature


def joint_signature(joint):
    def encode_limit(value):
        if isinstance(value, list):
            return [encode_limit(item) for item in value]
        if value == float('-inf'):
            return '-inf'
        if value == float('inf'):
            return '+inf'
        return value

    result = _ORIGINAL_JOINT_SIGNATURE(joint)
    for name in ('limits', 'force_limit'):
        if name in result:
            result[name] = encode_limit(result[name])
    return result


def texture_pixels(texture, cache):
    pixels = next((pixels for handle, pixels in cache if handle == texture), None)
    if pixels is None:
        pixels = np.ascontiguousarray(texture.download())
        assert pixels.dtype == np.uint8 and pixels.shape == (texture.height, texture.width, texture.channels)
        cache.append((texture, pixels))
    return pixels


def pixel_digest(pixels):
    return hashlib.sha256(pixels.tobytes()).hexdigest()


def material_values(material,owner=None,texture_cache=None,partition=None):
    result = _ORIGINAL_MATERIAL_VALUES(material)
    for field in C.MATERIAL_FIELDS:
        texture = getattr(material, field, None) if field.endswith('_texture') else None
        if texture is not None:
            result[field].update({name: getattr(texture, name) for name in
                                 ('channels', 'filter_mode', 'address_mode', 'is_srgb')})
            import mani_skill
            package=Path(mani_skill.__file__).resolve().parent
            if partition is not None and field == 'base_color_texture':
                strip, pixel_cache = partition
                pixels = texture_pixels(texture, pixel_cache)
                result[field].update(data_dtype=str(pixels.dtype), data_shape=list(pixels.shape),
                                     data_sha256=pixel_digest(pixels))
                if strip is not None:
                    assert texture == strip.texture and not texture.filename and texture != strip.source
                    source = Path(strip.source.filename).resolve(strict=True)
                    assert source.is_relative_to(MODEL_ASSET_ROOT)
                    result[field].update(asset_ref=source.relative_to(ROOT).as_posix(),
                        source_kind='office_keyboard_private_strip',
                        source_asset_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
                    continue
            if not texture.filename:
                assert owner is not None and owner.endswith('table-workspace'), 'Unknown embedded Office texture owner'
                cached=next((value for previous,value in texture_cache if previous==texture),None)
                if cached is None:
                    pixels=np.ascontiguousarray(texture.download());asset=package/'utils/scene_builder/table/assets/table.glb'
                    cached={'asset_ref':'mani_skill/utils/scene_builder/table/assets/table.glb',
                        'embedded_asset_sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),
                        'data_sha256':hashlib.sha256(pixels.tobytes()).hexdigest(),'data_dtype':str(pixels.dtype),
                        'data_shape':list(pixels.shape),'source_kind':'embedded GLB texture; no separate image filename'}
                    texture_cache.append((texture,cached))
                result[field].update(copy.deepcopy(cached));continue
            path=Path(texture.filename).resolve(strict=True)
            if path.is_relative_to(ROOT):result[field]['asset_ref']=path.relative_to(ROOT).as_posix()
            else:
                assert path.is_relative_to(package), 'Office texture file lies outside captured repository/ManiSkill roots'
                result[field]['asset_ref']='mani_skill/'+path.relative_to(package).as_posix()
    return result


def strip_context(base, env_id, metadata, pixel_cache):
    group = metadata['logical_group']
    if group not in ('safe', 'protected'):
        return None
    appearance = adapter(base)
    texture = (appearance.prepared[env_id].strip_texture if appearance is not None and group == 'safe' else None)
    return texture, pixel_cache


def logical_material(row):
    material = row['material']
    if row['logical_group'] != 'safe':
        return material
    storage = ('name', 'sha256', 'source_kind', 'source_asset_sha256')
    return {**material, 'base_color_texture': {key: value for key, value in material['base_color_texture'].items()
                                                if key not in storage}}


def verify_restored_materials(actual, native):
    assert [{**row, 'material': logical_material(row)} for row in actual] == [
        {**row, 'material': logical_material(row)} for row in native]


def record_strip_stage(base, stage, scheme, arrays, stages):
    appearance = adapter(base)
    strips = [part.strip_texture for part in appearance.prepared] if appearance is not None else []
    rows = []
    for env_id, slots in enumerate(logical_slots(base)):
        row, = [row for row in slots if row['metadata']['logical_group'] == 'safe']
        texture = row['part'].material.base_color_texture
        prefix = f'{stage}_env{env_id}'
        descriptor = P.texture_descriptor(texture)

        def record(key, pixels):
            assert key not in arrays
            arrays[key] = pixels
            return {'key': key, 'sha256': pixel_digest(pixels), 'dtype': str(pixels.dtype), 'shape': list(pixels.shape)}

        pixels = texture_pixels(texture, [])
        if appearance is None:
            assert stage == 'native_off' and texture.filename
            rows.append({'env_idx': env_id, 'descriptor': descriptor, 'native': record(prefix, pixels)})
            continue
        strip = strips[env_id]
        color = None if scheme == 'original' else appearance.scheme_parameters(scheme)[P.STRIP_ROLE]['base_color']
        original = texture_pixels(strip.source, [])
        expected = strip.pixels_for(color)
        stable = texture == strip.texture
        private = texture != strip.source and all(texture != other.texture for i, other in enumerate(strips) if i != env_id)
        assert stable and private and descriptor == strip.descriptor
        assert np.array_equal(original, arrays[f'native_off_env{env_id}']) and np.array_equal(pixels, expected)
        if scheme == 'original':
            assert np.array_equal(expected, original)
        rows.append({'env_idx': env_id, 'descriptor': descriptor,
                     'source': record(prefix + '_source', original), 'bound': record(prefix + '_bound', pixels),
                     'expected': record(prefix + '_expected', expected),
                     'bound_handle_stable': stable, 'bound_handle_exclusive': private})
    stages[stage] = rows


def logical_slots(base):
    """Measure stable source groups without changing native render topology."""
    cached = getattr(base, '_office_checker_logical_slots', None)
    if cached is not None:
        return cached
    keyboard_entities = []
    partition = definition = reader = None
    if hasattr(base, '_keyboards'):
        definition = json.loads((P.OBJECTS / 'keyboard/bindings.json').read_text(encoding='utf-8'))
        source_slot = next(slot for row in definition['part_bindings'] for slot in row['editable_slots'] if 'partition' in slot)
        partition = source_slot['partition']
        from tasks.office_desk.office_desk_type_keys import KEYBOARD_ASSET_DIR
        reader = P.OfficePartMaterials(definition, KEYBOARD_ASSET_DIR / '13106')
        keyboard_entities = [raw.entity for keyboard in base._keyboards
                             for raw in keyboard.links_map['link_0']._objs]
    rows = []
    for scene in base.scene.sub_scenes:
        measured = []
        for entity in sorted(scene.entities, key=lambda obj: (obj.name, obj.per_scene_id)):
            body = entity.find_component_by_type(sapien.render.RenderBodyComponent)
            if body is None: continue
            for visual_index, shape in enumerate(body.render_shapes):
                for part_index, part in enumerate(shape.parts):
                    source_visual, source_part = P.source_slot(shape, visual_index, part_index)
                    groups = [('whole', np.arange(len(part.triangles), dtype=np.int64))]
                    if '::office_group:' in shape.name:
                        group = shape.name.rsplit('::office_group:', 1)[1]
                        assert group in ('safe', 'protected')
                        groups = [(group, groups[0][1])]
                    elif (partition is not None and any(entity == target for target in keyboard_entities)
                          and source_visual == 1 and len(part.triangles) == 502
                          and np.allclose(part.material.base_color, [1.,1.,1.,1.], rtol=0, atol=2e-6)):
                        mask = reader._partition_mask(part, partition)
                        groups = [('safe', np.flatnonzero(mask)), ('protected', np.flatnonzero(~mask))]
                    attributes = P.triangle_attribute_rows(part)
                    triangle_hashes = [hashlib.sha256(np.ascontiguousarray(row).tobytes()).hexdigest() for row in attributes]
                    for group, indices in groups:
                        hashes = [triangle_hashes[int(index)] for index in indices]
                        metadata = {'entity':entity.name,'source_visual':source_visual,
                            'source_native_part':source_part,'logical_group':group,'triangles':len(indices),
                            'triangle_attributes_sha256':hashlib.sha256(b''.join(bytes.fromhex(value) for value in sorted(hashes))).hexdigest()}
                        measured.append({'metadata':metadata,'part':part,'entity':entity,
                            'actual_visual':visual_index,'actual_part':part_index,'indices':indices.tolist(),
                            'triangle_attribute_sha256':triangle_hashes})
        rows.append(measured)
    base._office_checker_logical_slots = rows
    return rows


def materials(base):
    if not hasattr(base,'_office_texture_proof_cache'):base._office_texture_proof_cache=[]
    pixel_cache = []
    return [[{**row['metadata'], 'material':material_values(row['part'].material,row['metadata']['entity'],
              base._office_texture_proof_cache, strip_context(base, env_id, row['metadata'], pixel_cache))} for row in rows]
            for env_id, rows in enumerate(logical_slots(base))]


def actual_slot_audit(base, geometry_output):
    objects = []
    for field in ('_laptops','_keyboards','_mice'):
        for handle in getattr(base, field, []):
            for link in handle.get_links():
                objects.extend(raw.entity for raw in link._objs)
    result = {'representation':'actual native render topology and logical source-group mapping', 'envs':[]}
    tensors = {}
    pixel_cache = []
    for env_id, rows in enumerate(logical_slots(base)):
        actual, mapping = {}, []
        for row in rows:
            if not any(row['entity'] == entity for entity in objects): continue
            metadata = row['metadata'];key=(metadata['entity'],row['actual_visual'],row['actual_part'])
            if key not in actual:
                part=row['part']
                shape = row['entity'].find_component_by_type(sapien.render.RenderBodyComponent).render_shapes[row['actual_visual']]
                tensor_key = f'{env_id}/{metadata["entity"]}/{row["actual_visual"]}/{row["actual_part"]}'
                tensors[tensor_key] = {'vertices':torch.from_numpy(np.asarray(part.vertices).copy()),
                    'triangles':torch.from_numpy(np.asarray(part.triangles).copy()),
                    'normal':torch.from_numpy(np.asarray(part.get_vertex_normal()).copy()),
                    'uv':torch.from_numpy(np.asarray(part.get_vertex_uv()).copy()),
                    'scale':torch.from_numpy(np.asarray(shape.scale).copy()),
                    'position':torch.from_numpy(np.asarray(shape.local_pose.p).copy()),
                    'quaternion':torch.from_numpy(np.asarray(shape.local_pose.q).copy()),'front_face':shape.front_face}
                actual[key]={'entity':metadata['entity'],'actual_visual':row['actual_visual'],'actual_part':row['actual_part'],
                    'source_visual':metadata['source_visual'],'source_native_part':metadata['source_native_part'],
                    'triangles':len(part.triangles),'vertices':len(part.vertices),
                    'geometry_tensor_key':tensor_key,'material':material_values(part.material,
                        partition=strip_context(base, env_id, metadata, pixel_cache)),
                    'per_triangle_position_normal_uv_winding_sha256':row['triangle_attribute_sha256']}
            mapping.append({'logical_key':{key:metadata[key] for key in ('entity','source_visual','source_native_part','logical_group')},
                'actual_visual':row['actual_visual'],'actual_part':row['actual_part'],'actual_triangle_indices':row['indices'],
                'triangles':metadata['triangles'],'triangle_attributes_sha256':metadata['triangle_attributes_sha256']})
        result['envs'].append({'actual_shapes':len({(key[0],key[1]) for key in actual}),
            'actual_parts':len(actual),'actual_slots':list(actual.values()),'logical_to_actual':mapping})
    torch.save(tensors, geometry_output)
    return result


def physical(base):
    result=_ORIGINAL_PHYSICAL(base)
    for scene, raw_scene in zip(result['scenes'], base.scene.sub_scenes):
        entities = sorted(raw_scene.entities, key=lambda obj: (obj.name, obj.per_scene_id))
        for row, entity in zip(scene, entities):
            body = entity.find_component_by_type(sapien.render.RenderBodyComponent)
            row['visuals'] = P.render_geometry(body) if body else []
    return result


def configure_runtime():
    global np,torch,gym,sapien
    import numpy as np
    import torch
    import gymnasium as gym
    import sapien
    C.np,C.torch,C.gym,C.sapien=np,torch,gym,sapien
    C.articulations,C.physical=articulations,physical
    C.materials=materials
    C.material_values = material_values
    C.joint_signature = joint_signature


def require_cuda_runtime(args):
    """Check indexed GPU reset before creating any CUDA scene."""
    windows_handles = []
    if platform.system() == 'Windows':
        assert args.experimental_windows_cuda
        import ctypes
        physx = (args.physx_gpu_dir.resolve(strict=True) if args.physx_gpu_dir
                 else Path.home() / '.sapien/physx' / sapien.physx.version())
        windows_handles.append(os.add_dll_directory(str(physx)))
        windows_handles.extend(ctypes.WinDLL(str(physx / name))
                               for name in ('PhysXDevice64.dll', 'PhysXGpu_64.dll'))
        if not sapien.physx.is_gpu_enabled():
            sapien.physx._enable_gpu()
    capability = getattr(sapien.physx, 'indexed_gpu_apply_patch_version', None)
    if not callable(capability) or capability() != 1:
        raise RuntimeError('Office CUDA requires SAPIEN indexed_gpu_apply_patch_version() == 1')
    if not sapien.physx.is_gpu_enabled():
        raise RuntimeError('Launch Office CUDA with the verified SDK launcher and native PhysX GPU enabled')
    return windows_handles


def verify(base, ids, native):
    a=adapter(base);assert a.schemes==ids
    actual=C.materials(base);slots=logical_slots(base)
    for i,name in enumerate(ids):
        assert a.bindings[i]
        native_slots={(row['entity'],row['source_visual'],row['source_native_part'],row['logical_group']):logical_material(row) for row in native[i]}
        assert len(native_slots)==len(native[i]), 'Native Office slot identity is ambiguous'
        expected=[copy.deepcopy(native_slots[(row['entity'],row['source_visual'],row['source_native_part'],row['logical_group'])]) for row in actual[i]]
        for role,part,material,captured in a.bindings[i]:
            assert part.material==material
            matches=[index for index,row in enumerate(slots[i]) if row['part']==part]
            assert len(matches)==1
            index,=matches
            params=captured if name=='original' else (a.catalog['schemes'][name][role] if hasattr(base,'_mouse_appearance') else a.scheme_parameters(name)[role])
            for field in C.FIELDS:
                np.testing.assert_allclose(captured[field],expected[index][field],rtol=0,atol=1e-7)
                expected[index][field]=params[field]
            if role == P.STRIP_ROLE:
                strip = a.prepared[i].strip_texture
                assert material.base_color_texture == strip.texture and strip.texture != strip.source
                pixels = strip.pixels_for(None if name == 'original' else params['base_color'])
                expected[index]['base_color_texture']['data_sha256'] = pixel_digest(pixels)
        for observed,target in zip(actual[i],expected):
            observed = logical_material(observed)
            for field in C.FIELDS:
                np.testing.assert_allclose(observed[field],target[field],rtol=0,atol=1e-7)
            assert {k:v for k,v in observed.items() if k not in C.FIELDS}=={k:v for k,v in target.items() if k not in C.FIELDS}
        records=[row for row in a.records if row['env_idx']==i]
        assert [row['episode_index'] for row in records]==list(range(1,a.episodes[i]+1))
        assert records[-1]['scheme_id']==name
    assert len(a.records)==sum(a.episodes)
    assert all(row['catalog_version']==a.catalog['version'] for row in a.records)
    return actual


def appearance_snapshot(base):
    a=adapter(base)
    return {'materials':C.materials(base),'appearance_rng':copy.deepcopy([r.bit_generator.state for r in a.rng]),
            'episodes':list(a.episodes),'schemes':list(a.schemes),'records':copy.deepcopy(a.records)}


def atomic_check(base,task):
    a=adapter(base);before=appearance_snapshot(base)
    request={'mode':'random_choice','scheme_ids':list(SCHEMES[task]),'per_env':{str(base.num_envs-1):{'mode':'explicit','scheme_id':'missing'}}}
    error_type=None
    try:a.finish_reset(torch.arange(base.num_envs,device=base.device),{key_for(task):request})
    except ValueError as error:error_type=type(error).__name__
    else:raise AssertionError('Invalid later Office selection accepted')
    after=appearance_snapshot(base)
    assert before==after
    return {'request':request,'error_type':error_type,'before':before,'after':after,
            'scope':'appearance-only atomicity; no native physical reset rollback claim'}


def preflight_rejections(env, output, key, schemes):
    base = env.unwrapped
    def rejection_state():
        return {**appearance_snapshot(base),
                'controller': [C.controller_state(base, i) for i in range(base.num_envs)],
                'episode_rng': [C.task_rng(base, i) for i in range(base.num_envs)],
                'main_rng': C.plain(base._main_rng.get_state()),
                'batched_main_rng': [C.plain(base._batched_main_rng[i].get_state()) for i in range(base.num_envs)]}

    def reject_reset(name, request, expected_message, *, seed=None, restore=False):
        options = copy.deepcopy(request)
        if 'env_idx' in options:
            options['env_idx'] = torch.tensor(options['env_idx'], device=base.device)
        if restore:
            options['reset_to_env_states'] = {'env_states': base.get_state_dict()}
        before, before_state = rejection_state(), C.snapshot(base)
        try:
            env.reset(seed=seed, options=options)
        except ValueError as error:
            assert expected_message in str(error), f'{name}: {error}'
            rejection = {'type': type(error).__name__, 'message': str(error)}
        else:
            raise AssertionError(f'Reset accepted {name}')
        after, after_state = rejection_state(), C.snapshot(base)
        assert before == after and not C.state_changes(before_state, after_state), name
        state_file = f'{name}.pt'
        torch.save({'before': before_state, 'after': after_state}, output / state_file)
        row = {'request': request, 'seed': seed, 'actual_state_restore_payload': restore,
               'error': rejection, 'before': before, 'after': after, 'state_evidence': state_file,
               'state_sha256': hashlib.sha256((output / state_file).read_bytes()).hexdigest()}
        dump(output / f'{name}.json', row)
        return row

    reject_reset('partial_seed_rejection', {'env_idx': [1]}, 'omit seed', seed=17)
    return {
        'descending_env_idx_rejection': reject_reset(
            'descending_env_idx_rejection', {'env_idx': [1, 0]}, 'strictly increasing'),
        'restore_override_rejection': reject_reset(
            'restore_override_rejection', {key: {'scheme_id': schemes[2]}}, 'state restoration', restore=True),
        'reset_per_env_rejection': reject_reset('reset_per_env_rejection', {key: {
            'mode': 'random_choice', 'scheme_ids': list(schemes[1:]),
            'per_env': {str(base.num_envs): {'scheme_id': schemes[2]}}}}, 'per_env'),
    }


def material_role_map(base, task):
    result={};slots=logical_slots(base)
    for env_id,bindings in enumerate(adapter(base).bindings):
        for role,part,material,captured in bindings:
            matches=[i for i,row in enumerate(slots[env_id]) if row['part']==part]
            assert len(matches)==1
            result[f'/{env_id}/{matches[0]}/material']={'object_id':TASKS[task],'role':role}
    return result


def reset_images(env, observation):
    frames = {name: values['rgb'].detach().cpu().numpy().copy()
              for name, values in observation['sensor_data'].items()}
    frames['human'] = env.render().detach().cpu().numpy().copy()
    return C.validate_images(frames, env.unwrapped.num_envs)


def compare_fixed_schemes(frames, output):
    """Use the PR16 native human camera in both environments for all pairs."""
    pairs = {}
    for (left, before), (right, after) in combinations(frames.items(), 2):
        rows = []
        for a, b in zip(before, after, strict=True):
            delta = np.abs(a.astype(np.int16) - b.astype(np.int16))
            pixels = int(np.count_nonzero(delta.max(axis=-1) > 8))
            rows.append({'pixels_over_8': pixels, 'fraction_over_8': pixels / delta[..., 0].size,
                         'mean_absolute_difference': float(delta.mean())})
        pairs[f'{left}/{right}'] = rows
    path = output / 'fixed_scheme_pairwise.json'
    dump(path, {'camera': 'human', 'schemes': list(frames), 'minimum_fraction_over_8': .001, 'pairs': pairs})
    failures = [name for name, rows in pairs.items() if any(row['fraction_over_8'] < .001 for row in rows)]
    assert not failures, f'Insufficient fixed camera RGB separation: {failures}'
    return {'file': path.name, 'camera': 'human', 'pairs': len(pairs), 'minimum_observed_fraction':
            min(row['fraction_over_8'] for rows in pairs.values() for row in rows)}


def prime_controller(base,output,prefix):
    before=C.snapshot(base)
    report=C.prime_controller_target(base)
    action=torch.tensor(report['action'],dtype=torch.float32,device=base.device)
    space=base.agent.controller.single_action_space
    low=torch.as_tensor(space.low,device=base.device);high=torch.as_tensor(space.high,device=base.device)
    offsets=.012*torch.sin(torch.arange(action.shape[-1],device=base.device,dtype=torch.float32)*.37+.3)
    action=torch.clamp(action+offsets,min=low,max=high)
    base.agent.set_action(action)
    if base.scene.gpu_sim_enabled:
        base.scene.px.gpu_apply_articulation_target_position();base.scene.px.gpu_apply_articulation_target_velocity()
        base.scene.px.gpu_fetch_articulation_target_qpos();base.scene.px.gpu_fetch_articulation_target_qvel()
    after=C.snapshot(base)
    physical_keys=[key for key in before if '/state/actors/' in key or '/state/articulations/' in key or ('/joint_targets/' in key and key.rsplit('/',1)[-1] in ('qpos','qvel'))]
    assert not C.state_changes({key:before[key] for key in physical_keys},{key:after[key] for key in physical_keys})
    controller={str(i):C.controller_state(base,i) for i in range(base.num_envs)}
    targets={str(i):{} for i in range(base.num_envs)}
    def visit(value,path):
        if hasattr(value,'_target_qpos'):
            for i in range(base.num_envs):targets[str(i)][path]=not torch.equal(value._target_qpos[i],value.qpos[i])
        for name,child in getattr(value,'controllers',{}).items():visit(child,path+'/'+name)
    visit(base.agent.controller,'controller')
    forces=C.joint_targets(base)['robot']['qf']
    for i in range(base.num_envs):
        assert targets[str(i)] and all(targets[str(i)].values())
        assert torch.count_nonzero(forces[i])
    filename=prefix+'_priming.pt'
    torch.save({'before':before,'after':after,'controller_after':controller},output/filename)
    report.update(action=C.plain(action),nontrivial_targets_all_envs=targets,
        generalized_forces_all_envs={str(i):C.plain(forces[i]) for i in range(base.num_envs)},
        controller_all_envs=controller,state_evidence=filename,
        controller_env0=controller['0'],nontrivial_targets_env0=targets['0'],
        generalized_forces_env0=C.plain(forces[0]),
        position_targets_env0=C.plain(C.joint_targets(base)['robot']['position_target'][0]),
        method='original agent.set_action with legal nontrivial targets in both environments; no physical step')
    return report


def counter_fixture(base, task, env_id):
    """Non-success bookkeeping fixture; no collision pose or physics step."""
    fields = {
        'OpenLaptop': {'reached_once': True, 'hold_counter': 2},
        'TypeKeys': {'press_started': True, 'press_achieved': True,
                     'press_hold_counter': 1, 'release_counter': 1, 'sequence_index': 1},
        'ClickMouse': {'press_started': True, 'hold_counter': 1,
                      'release_counter': 1, 'final_counter': 1, 'press_success_counter': 1},
    }[task]
    for name, value in fields.items():
        getattr(base, name)[env_id] = value
    base.success_latched[env_id] = False
    if task == 'TypeKeys':
        base.sequence_completed[env_id] = False
        base.sequence_completed[env_id, 0] = True
        fields['sequence_completed'] = base.sequence_completed[env_id].tolist()
        base._update_key_target_marker()
    assert not bool(base.success_latched[env_id])
    return {'classification': 'diagnostic/counter-scope fixture', 'fields': fields,
            'env_idx': env_id, 'success_latched': False,
            'guidance_marker_refreshed': task == 'TypeKeys' and base.key_target_marker is not None,
            'physical_state_modified': False, 'task_success_claim': False}


def run_task(task,args,output,result):
    gpu=args.sim_backend=='physx_cuda';n=2 if gpu else 1;schemes=SCHEMES[task];key=key_for(task)
    env=base=a=info=first_frames=_=None;reset_index=0;last_selected=None;constructor_records=[]
    result.update(control_steps=0,physics_steps=0)
    interface={};result['checks']['interface_evidence']=interface
    strip_arrays,strip_stages={},{}
    def capture_strip(stage, scheme='original'):
        if task == 'TypeKeys':
            record_strip_stage(env.unwrapped, stage, scheme, strip_arrays, strip_stages)
    def make(config=None):
        options={}
        if gpu and args.gpu_memory_profile=='two_env':
            options['sim_config']={'gpu_memory_config':{'max_rigid_contact_count':2**17,
                'max_rigid_patch_count':2**16,'found_lost_pairs_capacity':2**20}}
        return gym.make('OfficeDesk'+task+'-Sharpa-v1',num_envs=n,sim_backend=args.sim_backend,
            reconfiguration_freq=0,obs_mode='rgb' if gpu else 'state',render_mode='rgb_array',
            control_mode='pd_joint_pos',reward_mode='sparse',
            **options,**({} if config is None else {key:config}))
    def checked_reset(seed=None,options=None):
        nonlocal reset_index,last_selected
        if not gpu:return env.reset(seed=seed,options=options)
        row={};prefix=f'selected_reset_{reset_index:02d}';reset_index+=1;last_selected=prefix+'.json'
        try:return C.selected_reset_check(env,seed,options,output,prefix,row)
        finally:result['checks'].setdefault('selected_reset_state',[]).append({'evidence':last_selected,**row})
    def fresh(config=None, camera_first=False):
        nonlocal env,constructor_records,first_frames
        env=make(config);base=env.unwrapped;a=adapter(base)
        constructor_records=copy.deepcopy(a.records) if a is not None else []
        observation,info=checked_reset(seed=7)
        first_frames=reset_images(env,observation) if gpu and camera_first else None
        assert base.num_envs==n and base.backend.sim_backend==args.sim_backend
        assert base.device.type==('cuda' if gpu else 'cpu')
        if gpu:assert base.scene.gpu_sim_enabled and base.scene._gpu_sim_initialized
        release_targets = verify_release_targets(base, task)
        if release_targets is not None:
            result['release_target_readback'] = release_targets
        resolved=base.sim_config.dict();locked=base._default_sim_config.dict()
        for field in ('spacing','sim_freq','control_freq','scene_config','default_materials_config'):
            assert resolved[field]==locked[field], 'Office locked physical config changed: '+field
        capacities=dict(locked['gpu_memory_config'])
        if gpu and args.gpu_memory_profile=='two_env':
            capacities.update(max_rigid_contact_count=2**17,max_rigid_patch_count=2**16,found_lost_pairs_capacity=2**20)
        assert resolved['gpu_memory_config']==capacities
        result.update(resolved_sim_config=resolved,gpu_memory_profile=args.gpu_memory_profile,
            asset_closure_sha256=asset_closure(base))
        return base,info
    def close():
        nonlocal env,base,a,info,first_frames,_
        if env is not None:env.close()
        env=base=a=info=first_frames=_=None
        gc.collect()
        if gpu:torch.cuda.empty_cache()
    def first_repeat(frames, info, prefix):
        repeated = C.capture(env,info)
        pixels = {str(i):C.image_changes(frames,repeated,output,prefix,i) for i in range(n)}
        C.save_image_pairs(frames,repeated,output,prefix)
        result['checks'].setdefault('first_repeat_frames',{})[prefix] = pixels
        assert not any(value['changed_values'] for row in pixels.values() for value in row.values())
    def step(primed,context):
        before=C.snapshot(env.unwrapped)
        action=torch.tensor(primed['action'],dtype=torch.float32,device=env.unwrapped.device)
        _,_,_,_,info=env.step(action)
        after=C.snapshot(env.unwrapped)
        physics=int(env.unwrapped._sim_steps_per_control);assert physics==20
        result['control_steps']+=1;result['physics_steps']+=physics
        name=context+'_step.pt'
        torch.save({'before':before,'after':after,'action':action.detach().cpu().clone(),'context':context},output/name)
        result['checks'].setdefault('step_evidence',[]).append({'evidence':name,'context':context,'control_steps':1,'physics_steps':physics})
        return info
    def local_rounds(info,appearance):
        base=env.unwrapped;rows=[];context='appearance' if appearance else 'native'
        for index,selected in enumerate((1,0)):
            other=1-selected;prefix=('local_' if appearance else 'native_local_')+str(index)
            primed=prime_controller(base,output,prefix)
            if index:info=step(primed,context)
            before_images=C.capture(env,info);before=C.snapshot(base)
            before_marker = (base.key_target_marker.pose.raw_pose.detach().cpu().clone()
                             if task == 'TypeKeys' and base.key_target_marker is not None else None)
            before_materials=C.materials(base);before_physical=physical(base)
            before_controller=C.controller_state(base,other);before_rng=C.task_rng(base,other)
            before_counters=C.controller_counters(base)
            a=adapter(base)
            if appearance:
                before_appearance=copy.deepcopy(a.rng[other].bit_generator.state);before_records=copy.deepcopy(a.records)
            options={'env_idx':torch.tensor([selected],device=base.device)}
            if appearance:options[key]={'scheme_id':'original'}
            observation,info=checked_reset(options=options);selected_evidence=last_selected
            after_images=reset_images(env,observation);after=C.snapshot(base)
            if before_marker is not None:
                first_repeat(after_images,info,prefix+'_first_repeat')
            after_materials=C.materials(base);after_physical=physical(base)
            after_controller=C.controller_state(base,other);after_rng=C.task_rng(base,other)
            changes=C.state_changes(before,after,[other]);pixels=C.image_changes(before_images,after_images,output,prefix,other)
            row={'status':'passed','selected':[selected],'state_changes':changes,'pixel_changes':pixels,
                'state_evidence':prefix+'.pt','selected_state_evidence':selected_evidence,
                'before_materials':before_materials,'after_materials':after_materials,
                'before_physical':before_physical,'after_physical':after_physical,
                'before_controller_unselected':before_controller,'after_controller_unselected':after_controller,
                'before_task_rng_unselected':before_rng,'after_task_rng_unselected':after_rng,
                'before_shared_controller_counters':before_counters,'after_shared_controller_counters':C.controller_counters(base),
                'controller_precondition':primed,'precondition_control_steps':index,'precondition_physics_steps':20*index}
            assert not changes and not any(value['changed_values'] for value in pixels.values())
            assert before_controller==after_controller and before_rng==after_rng
            assert before_materials[other]==after_materials[other] and before_physical==after_physical
            if before_marker is not None:
                from tasks.office_desk.office_desk_type_keys import _key_target_marker_pose
                after_marker = base.key_target_marker.pose.raw_pose.detach().cpu().clone()
                slot = int(base.sequence_index[selected])
                links = base._target_links[selected]
                target_link = links[slot] if 0 <= slot < len(links) else None
                pose = _key_target_marker_pose(target_link, pose=target_link.pose.sp if target_link is not None else None)
                expected_marker = torch.as_tensor(np.concatenate([pose.p, pose.q]))
                assert torch.equal(before_marker[other],after_marker[other])
                torch.testing.assert_close(after_marker[selected],expected_marker,rtol=0,atol=2e-6)
                row['guidance_marker'] = {'before': C.plain(before_marker), 'after': C.plain(after_marker),
                                          'selected_expected': C.plain(expected_marker), 'selected_slot': slot}
            if appearance:
                row.update(before_appearance_rng_unselected=before_appearance,
                    after_appearance_rng_unselected=copy.deepcopy(a.rng[other].bit_generator.state),
                    before_records=before_records,after_records=copy.deepcopy(a.records),
                    selected_pixel_changes=C.image_changes(before_images,after_images,output,prefix,selected))
                assert row['before_appearance_rng_unselected']==row['after_appearance_rng_unselected']
                assert a.records[:len(before_records)]==before_records and len(a.records)==len(before_records)+1
                assert [r for r in a.records if r['env_idx']==other]==[r for r in before_records if r['env_idx']==other]
                verify_restored_materials(after_materials[selected], native[selected])
                verify(base,list(a.schemes),native)
                assert any(value['changed_values'] for name,value in row['selected_pixel_changes'].items() if not name.startswith('human'))
            torch.save({'before':before,'after':after},output/(prefix+'.pt'))
            C.save_image_pairs(before_images,after_images,output,prefix);dump(output/(prefix+'.json'),row);rows.append(row)
        return rows,info
    try:
        result['stage'] = 'model asset identity'
        result['object_asset_root'] = require_model_asset_root(task)
        if task == 'ClickMouse':
            result['stage'] = 'Mouse collision input identity'
            result['mouse_collision_identity'] = mouse_collision_identity()
        result['stage']='native baseline';base,info=fresh();assert adapter(base) is None
        baseline,native,properties=C.snapshot(base),C.materials(base),physical(base);native_info=C.plain(info)
        capture_strip('native_off')
        dump(output/'native_materials.json',native);dump(output/'native_physical.json',properties);torch.save(baseline,output/'native_state.pt')
        dump(output/'native_actual_slots.json',actual_slot_audit(base,output/'native_actual_geometry.pt'))
        _,info=checked_reset(seed=7);repeated=C.snapshot(base)
        assert not C.state_changes(baseline,repeated) and C.materials(base)==native and physical(base)==properties
        torch.save({'before':baseline,'after':repeated},output/'default_disabled_state.pt')
        interface['default_disabled']={'config':None,'adapter_present':adapter(base) is not None,
            'materials':C.materials(base),'physical':physical(base),'state_evidence':'default_disabled_state.pt'}
        result['checks']['default_disabled']='passed'
        if gpu:
            before_capture=C.snapshot(base);native_images=C.capture(env,info);first_capture=C.snapshot(base)
            repeat_images=C.capture(env,info);repeat_capture=C.snapshot(base)
            pixel_rows={str(i):C.image_changes(native_images,repeat_images,output,'native_capture',i) for i in range(n)}
            diagnostic={'first_capture_state_changes':C.state_changes(before_capture,first_capture),
                'repeat_capture_state_changes':C.state_changes(first_capture,repeat_capture),
                'repeat_capture_pixel_changes':pixel_rows['0'],'repeat_capture_pixel_changes_all_envs':pixel_rows}
            torch.save({'before_capture':before_capture,'after_first_capture':first_capture,'after_repeat_capture':repeat_capture},output/'native_capture_states.pt')
            C.save_image_pairs(native_images,repeat_images,output,'native_capture');dump(output/'native_capture_diagnostic.json',diagnostic)
            assert not diagnostic['first_capture_state_changes'] and not diagnostic['repeat_capture_state_changes']
            assert not any(value['changed_values'] for rows in pixel_rows.values() for value in rows.values())
            rows,info=local_rounds(info,False)
            result['checks']['native_local_reset_control']={'capture_diagnostic':diagnostic,'rounds':rows}
        close()
        result['stage']='explicit disabled';base,info=fresh({'enabled':False});disabled_state=C.snapshot(base)
        assert adapter(base) is None and not C.state_changes(baseline,disabled_state)
        assert C.materials(base)==native and physical(base)==properties and C.plain(info)==native_info
        torch.save({'before':baseline,'after':disabled_state},output/'explicit_disabled_state.pt')
        interface['explicit_disabled']={'config':{'enabled':False},'adapter_present':adapter(base) is not None,
            'materials':C.materials(base),'physical':physical(base),'state_evidence':'explicit_disabled_state.pt'}
        result['checks']['explicit_disabled']='passed';close()
        fixed_frames = {}
        restorations = {}
        for scheme in schemes:
            result['stage']='fixed '+scheme;base,info=fresh({'enabled':True,'scheme_id':scheme},camera_first=True)
            if gpu:first_repeat(first_frames,info,'fixed_'+scheme+'_first_repeat')
            measured=verify(base,[scheme]*n,native)
            capture_strip(scheme, scheme)
            assert not C.state_changes(baseline,C.snapshot(base)) and physical(base)==properties and C.plain(info)==native_info
            records=copy.deepcopy(adapter(base).records)
            if scheme=='original':
                result['checks']['material_roles']=material_role_map(base,task)
                dump(output/'original_materials.json',measured)
                dump(output/'original_actual_slots.json',actual_slot_audit(base,output/'original_actual_geometry.pt'))
                result['checks']['material_partition_mapping']={'schema_version':1,'native_slots':'native_actual_slots.json',
                    'native_geometry':'native_actual_geometry.pt','enabled_original_slots':'original_actual_slots.json',
                    'enabled_original_geometry':'original_actual_geometry.pt','logical_materials':'native_materials.json',
                    'representation':'logical source visual/nativepart/whole|safe|protected groups measured from actual material handles'}
                if task=='TypeKeys':result['checks']['material_partition_mapping'].update(
                    input_bindings='assets/appearance/objects/office_desk/keyboard/bindings.json',
                    uv_proof='assets/appearance/objects/office_desk/keyboard/key_uv_protection.json')
                interface['invalid_request_atomicity']=atomic_check(base,task)
                if gpu:
                    interface['reset_preflight_rejections'] = preflight_rejections(env, output, key, schemes)
                    result['checks']['partial_seed_rejection'] = 'passed'
            if gpu:
                from PIL import Image
                images=first_frames
                differences={str(i):C.image_changes(native_images,images,output,'fixed_'+scheme,i) for i in range(n)}
                for values in differences.values():
                    if scheme=='original':assert not any(value['changed_values'] for value in values.values()),'Original task RGB differs from native'
                    else:assert any(value['changed_values'] for name,value in values.items() if not name.startswith('human')),'Candidate invisible in task camera'
                for camera,pixels in images.items():
                    for i in range(n):Image.fromarray(pixels[i]).save(output/f'{scheme}_{camera}_env{i}.png')
                fixed_frames[scheme] = images['human']
                dump(output/(scheme+'_pixel_comparison.json'),differences)
                assert records==adapter(base).records
            result['checks'][scheme]={'status':'passed','materials':measured,'records':records}
            if scheme != 'original':
                result['stage'] = f'restore from {scheme}'
                observation,info=checked_reset(seed=7,options={key:{'scheme_id':'original'}})
                prefix = f'restored_from_{scheme}'
                row = {'status': 'passed', 'state_evidence': last_selected if gpu else None}
                if gpu:
                    images=reset_images(env,observation)
                    first_repeat(images,info,prefix+'_first_repeat')
                    row['pixel_changes']={str(i):C.image_changes(native_images,images,output,prefix,i) for i in range(n)}
                    assert not any(v['changed_values'] for cameras in row['pixel_changes'].values() for v in cameras.values())
                verify(base,['original']*n,native)
                assert not C.state_changes(baseline,C.snapshot(base)) and physical(base)==properties
                capture_strip(prefix)
                restorations[scheme] = row
            close()
        result['checks']['original_restoration_by_scheme'] = restorations
        if gpu:
            result['stage'] = 'fixed pairwise RGB separation'
            result['checks']['fixed_pairwise_rgb'] = compare_fixed_schemes(fixed_frames,output)
        random_config={'enabled':True,'mode':'random_choice','scheme_ids':list(schemes),'seed':71};traces=[]
        for repeat in range(2):
            result['stage']='random repeat '+str(repeat);env=make(random_config);trace=[]
            for selected in ([list(range(n)),[1],[0],[0,1]] if gpu else [[0]]*4):
                base=env.unwrapped;a=adapter(base);before=copy.deepcopy(a.records);before_rng=copy.deepcopy([r.bit_generator.state for r in a.rng])
                checked_reset(seed=7 if not trace else None,options={'env_idx':torch.tensor(selected,device=base.device)})
                verify(base,list(a.schemes),native);assert a.records[:len(before)]==before
                assert [r['env_idx'] for r in a.records[len(before):]]==selected
                trace.append({'selected':selected,'reset':{},'before_rng':before_rng,
                    'after_rng':copy.deepcopy([r.bit_generator.state for r in a.rng]),
                    'before_records':before,'after_records':copy.deepcopy(a.records),
                    'schemes':list(a.schemes),'episodes':list(a.episodes)})
            traces.append(trace);close()
        assert traces[0]==traces[1]
        interface['random_reproducibility']={'constructor':random_config,'runs':traces}
        result['checks']['random_reproducibility']={'status':'passed','independent_constructions':2,'runs':traces}
        result['stage']='selection precedence'
        constructor={'enabled':True,'scheme_id':schemes[1],'per_env':{'0':{'scheme_id':schemes[2]}}}
        base,info=fresh(constructor);a=adapter(base);cases=[]
        verify(base,[schemes[2]]+[schemes[1]]*(n-1),native)
        cases.append({'constructor':constructor,'reset':{},'selected':list(range(n)),'schemes':list(a.schemes),
            'before_records':constructor_records,'after_records':copy.deepcopy(a.records),'materials':C.materials(base)})
        for request in ({'scheme_id':'original'},{'scheme_id':'original','per_env':{'0':{'scheme_id':schemes[1]}}}):
            before=copy.deepcopy(a.records)
            checked_reset(options={'env_idx':torch.tensor([0],device=base.device),key:request})
            expected=request.get('per_env',{}).get('0',{}).get('scheme_id',request['scheme_id'])
            verify(base,[expected]+[schemes[1]]*(n-1),native)
            cases.append({'constructor':constructor,'reset':request,'selected':[0],'schemes':list(a.schemes),
                'before_records':before,'after_records':copy.deepcopy(a.records),'materials':C.materials(base)})
        interface['selection_precedence']=cases;result['checks']['selection_precedence']='passed';close()
        if gpu:
            invalid_constructor = {'enabled': False, 'per_env': {str(n): {'scheme_id': schemes[1]}}}
            try:
                env = make(invalid_constructor)
            except ValueError as error:
                assert 'per_env' in str(error)
                interface['constructor_per_env_rejection'] = {'config': invalid_constructor,
                    'error': {'type': type(error).__name__, 'message': str(error)}}
            else:
                raise AssertionError('Constructor accepted an out-of-range per_env key')
            left,right=schemes[-2:]
            result['stage']='bidirectional local reset';base,info=fresh({'enabled':True,'scheme_id':left,'per_env':{'1':{'scheme_id':right}}})
            verify(base,[left,right],native);rows,info=local_rounds(info,True)
            for index,row in enumerate(rows):result['checks'][f'local_reset_{index}']=row
            assert result['control_steps']==2 and result['physics_steps']==40
            result['stage']='diagnostic counter-scope fixtures';diagnostic=[]
            result['checks']['diagnostic_counter_scope']=diagnostic
            for selected in (1,0):
                other=1-selected;fixture=counter_fixture(base,task,other);before_images=C.capture(env,info)
                before=C.snapshot(base);controller=C.controller_state(base,other);rng=C.task_rng(base,other)
                _,info=checked_reset(options={'env_idx':torch.tensor([selected],device=base.device),key:{'scheme_id':'original'}})
                after_images=C.capture(env,info);after=C.snapshot(base)
                prefix=f'diagnostic_counter_scope_{selected}'
                changes=C.state_changes(before,after,[other]);pixels=C.image_changes(before_images,after_images,output,prefix,other)
                C.save_image_pairs(before_images,after_images,output,prefix)
                def reference(name):
                    return {'file':name,'sha256':hashlib.sha256((output/name).read_bytes()).hexdigest()}
                png_pairs={str(env_id):{camera:reference(f'{prefix}_{camera}_env{env_id}.png')
                                      for camera in before_images} for env_id in range(base.num_envs)}
                coordinates={camera:reference(value['coordinates']) for camera,value in pixels.items()}
                state_file=prefix+'.pt';torch.save({'before':before,'after':after},output/state_file)
                row={'fixture':fixture,'selected':[selected],'state_changes':changes,'pixel_changes':pixels,
                    'state_evidence':state_file,'state_sha256':reference(state_file)['sha256'],
                    'selected_state_evidence':last_selected,'selected_state_sha256':reference(last_selected)['sha256'],
                    'png_pairs':png_pairs,'coordinates':coordinates,
                    'before_controller':controller,'after_controller':C.controller_state(base,other),
                    'before_task_rng':rng,'after_task_rng':C.task_rng(base,other),'physics_steps':0,'task_success_claim':False}
                passed=(not changes and not any(value['changed_values'] for value in pixels.values())
                    and row['before_controller']==row['after_controller'] and row['before_task_rng']==row['after_task_rng'])
                row['status']='passed' if passed else 'failed'
                evidence=prefix+'.json';dump(output/evidence,row)
                diagnostic.append({**row,'evidence':evidence,'evidence_sha256':reference(evidence)['sha256']})
                assert passed, f'{task} counter fixture changed unselected env {other}'
        else:result['checks']['local_reset_isolation']={'status':'NOT TESTED','reason':'one CPU environment; no RGB/batching claim'}
        if task == 'ClickMouse':
            assert result['mouse_collision_identity'] == mouse_collision_identity()
            result['mouse_collision_inputs_unchanged'] = True
        result.update(status='passed',stage='complete')
    finally:
        close()
        if strip_arrays:
            path=output/'strip_textures.npz'
            np.savez_compressed(path,**strip_arrays)
            result['checks']['strip_texture_evidence']={'schema_version':1,'file':path.name,
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'stages':strip_stages}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static',action='store_true');parser.add_argument('--approved-runtime',action='store_true')
    parser.add_argument('--sim-backend',choices=('physx_cpu','physx_cuda'));parser.add_argument('--output',type=Path)
    parser.add_argument('--task',choices=tuple(TASKS),action='append');parser.add_argument('--experimental-windows-cuda',action='store_true')
    parser.add_argument('--physx-gpu-dir',type=Path)
    parser.add_argument('--gpu-memory-profile', choices=('production','two_env'), default='production')
    args=parser.parse_args()
    if args.static:
        from tools.variation.check_office_devices import catalog_check,source_check
        print(json.dumps({'status':'passed','catalogs':catalog_check(),'source_scope':source_check()}));return 0
    if not args.approved_runtime or not args.output or not args.sim_backend:parser.error('runtime needs --approved-runtime, --sim-backend and fresh --output')
    args.output.mkdir(parents=True,exist_ok=False);report={'status':'running','formal_acceptance':'pending' if args.sim_backend=='physx_cuda' else 'NOT TESTED: CPU only','test_mode':'standard','tasks':[]};start=time.monotonic()
    before=source_hashes();assets=asset_hashes();external_before=None
    try:
        sys.path.insert(0,str(ROOT));configure_runtime()
        if args.sim_backend == 'physx_cuda':
            # Retain the Windows loader and DLL handles through capture.
            sdk_handles = require_cuda_runtime(args)
        from mani_skill.utils import download_asset
        def reject(*unused,**kwargs):raise RuntimeError('Asset download disabled during verification')
        download_asset.download=reject;download_asset.download_from_hf_datasets=reject
        import tasks
        external_before=external_hashes()
        manifest={'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'command':sys.argv,'files':before,'asset_files':assets,'platform':platform.platform(),'python':sys.version,'versions':{name:metadata.version(name) for name in ('sapien','mani_skill','torch','numpy','gymnasium')},'num_envs':2 if args.sim_backend=='physx_cuda' else 1,'sim_backend':args.sim_backend,'gpu_memory_profile':args.gpu_memory_profile,'gpu_capacity_override':({'max_rigid_contact_count':2**17,'max_rigid_patch_count':2**16,'found_lost_pairs_capacity':2**20} if args.sim_backend=='physx_cuda' and args.gpu_memory_profile=='two_env' else None),'test_mode':'standard','capture_path':'original ManiSkill CUDA RGB cameras' if args.sim_backend=='physx_cuda' else 'not captured','sapien_binary_sha256':hashlib.sha256(Path(sapien.pysapien.__file__).read_bytes()).hexdigest()}
        manifest['external_files']=external_before
        manifest['material_representation']='logical source visual/nativepart/groups; actual render topology retained separately per task'
        manifest['task_ids']=['OfficeDesk'+task+'-Sharpa-v1' for task in (args.task or TASKS)]
        manifest['schemes']={task:list(SCHEMES[task]) for task in (args.task or TASKS)}
        manifest['planned_control_steps_per_task']=2 if args.sim_backend=='physx_cuda' else 0
        dump(args.output/'manifest.json',manifest)
        for task in args.task or TASKS:
            row={'task':task,'status':'running','checks':{}};report['tasks'].append(row);directory=args.output/task;directory.mkdir()
            try:run_task(task,args,directory,row)
            except BaseException:row.update(status='failed',error=traceback.format_exc());raise
            finally:dump(args.output/'results.json',report)
        report['status']='passed'
        if args.sim_backend=='physx_cuda':report['formal_acceptance']='passed'
    except BaseException:report.update(status='failed',error=traceback.format_exc());report['formal_acceptance']='failed' if args.sim_backend=='physx_cuda' else 'NOT TESTED: CPU only'
    finally:
        report['source_hashes_unchanged']=before==source_hashes();report['asset_hashes_unchanged']=assets==asset_hashes()
        report['external_hashes_unchanged']=external_before is not None and external_before==external_hashes()
        report['robot_asset_hashes_unchanged']=all(closure_unchanged(row.get('asset_closure_sha256',{})) for row in report['tasks'])
        if not all(report[field] for field in ('source_hashes_unchanged','asset_hashes_unchanged','external_hashes_unchanged','robot_asset_hashes_unchanged')):
            report.update(status='failed', formal_acceptance='failed')
            report.setdefault('error', 'Inputs changed during verification')
        report['elapsed_seconds']=time.monotonic()-start
        report['physics_steps']=sum(row.get('physics_steps',0) for row in report['tasks'])
        report['control_steps']=sum(row.get('control_steps',0) for row in report['tasks'])
        dump(args.output/'results.json',report)
    print(json.dumps({'status':report['status'],'tasks':[(row['task'],row['status'],row.get('stage')) for row in report['tasks']]}),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
