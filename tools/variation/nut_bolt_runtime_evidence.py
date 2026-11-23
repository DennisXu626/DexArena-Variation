"""Capture raw receipts around main's validators without changing their logic."""
import copy
import hashlib
from pathlib import Path
from weakref import WeakKeyDictionary

ROOT = Path(__file__).resolve().parents[2]
MATERIAL_FIELDS = ('base_color', 'roughness', 'metallic', 'specular', 'emission',
    'ior', 'transmission', 'transmission_roughness', 'base_color_texture',
    'roughness_texture', 'metallic_texture', 'normal_texture',
    'emission_texture', 'transmission_texture')
TABLE_ASSET = 'mani_skill/utils/scene_builder/table/assets/table.glb'
TEXTURE_CACHE = WeakKeyDictionary()


def texture_reference(filename):
    path = Path(filename).resolve(strict=True)
    if path.is_relative_to(ROOT):
        return path.relative_to(ROOT).as_posix()
    import mani_skill
    package = Path(mani_skill.__file__).resolve().parent
    if path.is_relative_to(package):
        return 'mani_skill/' + path.relative_to(package).as_posix()
    return 'external/' + path.name


def material_values(common, material, owner, texture_cache=None):
    """Read all 14 independent PBR attributes; diffuse_texture is an alias."""
    values = {}
    for field in MATERIAL_FIELDS:
        value = getattr(material, field)
        if field.endswith('_texture') and value is not None:
            texture = value
            filename = Path(texture.filename) if texture.filename else None
            if filename is not None and not filename.is_file():
                raise FileNotFoundError(f'Missing referenced native texture: {filename}')
            value = {'name': filename.name if filename else '',
                **{key: common.plain(getattr(texture, key)) for key in
                   ('width', 'height', 'mipmap_levels', 'channels', 'filter_mode', 'address_mode', 'is_srgb')},
                'format': str(texture.format),
                'sha256': hashlib.sha256(filename.read_bytes()).hexdigest() if filename and filename.is_file() else None,
                'asset_ref': texture_reference(filename) if filename and filename.is_file() else None,
                'source_kind': 'file' if filename else 'embedded_glb',
                'owner': {**owner, 'field': field}}
            if filename is None:
                import numpy as np
                source = owner.get('source_asset', {})
                if not owner.get('entity', '').endswith('table-workspace') or source.get('asset_ref') != TABLE_ASSET:
                    raise ValueError('Unidentified embedded texture owner')
                cache = [] if texture_cache is None else texture_cache
                recorded = next((data for previous, data in cache if previous == texture), None)
                if recorded is None:
                    data = np.ascontiguousarray(texture.download())
                    assert data.shape == (texture.height, texture.width, texture.channels)
                    recorded = {'data_dtype': str(data.dtype), 'data_shape': list(data.shape),
                                'data_sha256': hashlib.sha256(data.tobytes()).hexdigest()}
                    cache.append((texture, recorded))
                value.update(recorded, asset_ref=TABLE_ASSET, embedded_asset_sha256=source['sha256'])
        values[field] = common.plain(value)
    return values


def materials(common, base):
    result = []
    texture_cache = TEXTURE_CACHE.setdefault(base, [])
    for env_id, slots in enumerate(common.material_slots(base)):
        owners = {}
        for entity in base.scene.sub_scenes[env_id].entities:
            body = entity.find_component_by_type(common.sapien.render.RenderBodyComponent)
            if body is None:
                continue
            for shape_index, shape in enumerate(body.render_shapes):
                for part_index, part in enumerate(shape.parts):
                    if not any(getattr(part.material, field) is not None for field in MATERIAL_FIELDS
                               if field.endswith('_texture')):
                        continue
                    owner = {'env_idx': env_id, 'entity': entity.name, 'shape': shape_index,
                             'part': part_index, 'shape_type': type(shape).__name__}
                    filename = Path(shape.filename) if getattr(shape, 'filename', '') else None
                    if filename and filename.is_file():
                        owner['source_asset'] = {'asset_ref': texture_reference(filename),
                            'sha256': hashlib.sha256(filename.read_bytes()).hexdigest()}
                    else:
                        import numpy as np
                        attributes = {'vertices': part.vertices, 'triangles': part.triangles,
                            'normal': part.get_vertex_normal(), 'uv': part.get_vertex_uv()}
                        owner['observed_geometry'] = {name: None if value is None else {'sha256': hashlib.sha256(np.asarray(value).tobytes()).hexdigest(),
                            'dtype': str(np.asarray(value).dtype), 'shape': list(np.asarray(value).shape)}
                            for name, value in attributes.items()}
                    owners.setdefault((entity.name, shape_index, part_index), []).append((part, owner))
        rows = []
        for name, shape, part_index, part in slots:
            matches = [owner for candidate, owner in owners.get((name, shape, part_index), []) if candidate == part]
            assert len(matches) <= 1
            owner = matches[0] if matches else {'env_idx': env_id, 'entity': name, 'shape': shape, 'part': part_index}
            rows.append({'entity': name, 'shape': shape, 'part': part_index,
                         'material': material_values(common, part.material, owner, texture_cache)})
        result.append(rows)
    return result


def material_roles(common, base):
    result, slots = {}, common.material_slots(base)
    for env_id, bindings in enumerate(base._nut_bolt_appearance.bindings):
        for object_id, role, part, material, captured in bindings:
            matches = [index for index, slot in enumerate(slots[env_id]) if slot[-1] == part]
            assert len(matches) == 1, (object_id, role, matches)
            key = f'/{env_id}/{matches[0]}/material'
            assert key not in result and part.material == material
            result[key] = {'object_id': object_id, 'role': role}
    return result


def atomic_state(common, base):
    adapter = base._nut_bolt_appearance
    return {'materials': common.materials(base),
        'appearance_rng': [copy.deepcopy(value.bit_generator.state) for value in adapter.rng],
        'episodes': adapter.episodes.copy(), 'schemes': adapter.schemes.copy(),
        'records': copy.deepcopy(adapter.records)}


def prime(common, base, output, prefix, native_prime=None):
    import torch
    before = common.snapshot(base)
    result = (native_prime or common.prime_controller_target)(base)
    after = common.snapshot(base)
    targets = {}
    def describe(controller, path, env):
        if hasattr(controller, '_target_qpos'):
            targets[str(env)][path] = not torch.equal(controller._target_qpos[env], controller.qpos[env])
        for name, child in getattr(controller, 'controllers', {}).items():
            describe(child, path + '/' + name, env)
    for env in range(base.num_envs):
        targets[str(env)] = {}
        describe(base.agent.controller, 'controller', env)
        assert targets[str(env)] and all(targets[str(env)].values()), 'Trivial controller target'
    controllers = {str(env): common.controller_state(base, env) for env in range(base.num_envs)}
    joint = common.joint_targets(base)['robot']
    forces = joint['qf']
    for env in range(base.num_envs):
        targets[str(env)]['robot/position_target'] = not torch.equal(joint['position_target'][env], joint['qpos'][env])
        assert targets[str(env)]['robot/position_target'], 'Native robot drive target is trivial'
    assert all(bool(torch.count_nonzero(forces[env])) for env in range(base.num_envs)), 'Trivial controller qf buffer'
    filename = prefix + '.pt'
    torch.save({'before': before, 'after': after, 'controller_after': controllers}, output / filename)
    return {**result, 'state_evidence': filename, 'nontrivial_targets_all_envs': targets,
        'generalized_forces_all_envs': {str(env): common.plain(forces[env]) for env in range(base.num_envs)},
        'controller_all_envs': controllers,
        'qf_semantics': 'original controller API buffer; no solver-force readback claim'}


def step(common, env, primed, output, result, context):
    import torch
    base = env.unwrapped
    before = common.snapshot(base)
    action = torch.tensor(primed['action'], dtype=torch.float32, device=base.device)
    _, _, _, _, info = env.step(action)
    after = common.snapshot(base)
    filename = context + '_step.pt'
    torch.save({'before': before, 'after': after, 'action': action.detach().cpu().clone(),
                'context': context}, output / filename)
    result['control_steps'] += 1
    result['physics_steps'] += base._sim_steps_per_control
    result['checks'].setdefault('step_evidence', []).append({'evidence': filename,
        'context': context, 'control_steps': 1, 'physics_steps': int(base._sim_steps_per_control)})
    return info


def private_values(common, base, other, appearance=False):
    row = {'materials': common.materials(base), 'physical': common.physical(base),
        'controller_unselected': common.controller_state(base, other),
        'task_rng_unselected': common.task_rng(base, other),
        'shared_controller_counters': common.controller_counters(base)}
    if appearance:
        adapter = base._nut_bolt_appearance
        row.update(appearance_rng_unselected=copy.deepcopy(adapter.rng[other].bit_generator.state),
                   records=copy.deepcopy(adapter.records))
    return row


def pairs(before, after):
    return {prefix + key: value for prefix, values in (('before_', before), ('after_', after))
            for key, value in values.items()}


def native_local(common, env, info, output, reset, selected_id, result, dump):
    """Instrument the existing native helper's exact prime/reset/capture points."""
    import torch
    base, receipts, captures = env.unwrapped, [], []
    native_prime = common.prime_controller_target
    prime_index = 0
    def priming(base, *prime_args, **prime_kwargs):
        nonlocal prime_index
        row = prime(common, base, output, f'native_prime_{prime_index}',
                    lambda base: native_prime(base, *prime_args, **prime_kwargs))
        prime_index += 1
        return row
    def capture(environment, raw_info):
        images = common.capture(environment, raw_info)
        captures.append(common.snapshot(base))
        return images
    def checked_reset(seed=None, options=None):
        selected = [int(i) for i in options['env_idx']]
        other = 1 - selected[0]
        before, private_before = common.snapshot(base), private_values(common, base, other)
        value = reset(seed=seed, options=options)
        receipts.append({'before': before, 'after_reset': common.snapshot(base),
            'private_before': private_before, 'private_after': private_values(common, base, other),
            'selected_state_evidence': selected_id()})
        return value
    common.prime_controller_target = priming
    try:
        control = common.native_local_control(env, info, output, checked_reset, capture,
            lambda primed: step(common, env, primed, output, result, 'native'))
    finally:
        common.prime_controller_target = native_prime
    assert len(receipts) == 2 and len(captures) == 6
    for index, (row, receipt) in enumerate(zip(control['rounds'], receipts)):
        prefix = f'native_local_{index}'
        after = captures[3 + index * 2]
        assert not common.state_changes(receipt['after_reset'], after), 'Capture changed reset state'
        assert not common.state_changes(captures[2 + index * 2], receipt['before']), 'Local capture/reset association differs'
        for key in ('controller_unselected', 'task_rng_unselected', 'physical'):
            assert receipt['private_before'][key] == receipt['private_after'][key], key
        torch.save({'before': receipt['before'], 'after': after,
                    'after_reset_before_capture': receipt['after_reset']}, output / (prefix + '.pt'))
        row.update(pairs(receipt['private_before'], receipt['private_after']),
            state_evidence=prefix + '.pt', selected_state_evidence=receipt['selected_state_evidence'])
        dump(output / (prefix + '.json'), row)
    return control
