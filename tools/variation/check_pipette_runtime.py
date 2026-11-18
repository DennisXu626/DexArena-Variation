"""Check Pipette short-task materials, native reset readback and standard CUDA RGB."""
import argparse
import ast
import copy
from contextlib import contextmanager
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
TASKS = ('AspirateLiquid', 'DispenseLiquid')
SCHEMES = ('original', 'jade', 'coral')
CATALOG = ROOT / 'tasks/assets/variation/pipette_transfer/v1/catalog.json'
GPU_MEMORY_PROFILES = {
    'native': {},
    'two_env': {'max_rigid_contact_count': 2**17, 'max_rigid_patch_count': 2**16,
                'found_lost_pairs_capacity': 2**20},
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def native_log(path):
    """Capture native fd output as well as Python logging for buffer-overflow checks."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved = [os.dup(fd) for fd in (1, 2)]
    with path.open('wb') as handle:
        try:
            os.dup2(handle.fileno(), 1)
            os.dup2(handle.fileno(), 2)
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            if os.name == 'nt':
                import ctypes
                ctypes.CDLL('msvcrt').fflush(None)
            for fd, previous in zip((1, 2), saved):
                os.dup2(previous, fd)
                os.close(previous)


def buffer_errors(path):
    result = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        lower = line.lower().replace('_', ' ')
        if ('out of memory' in lower or 'out of device memory' in lower or 'allocation failed' in lower
                or (any(word in lower for word in ('physx', 'pxg', 'contact', 'patch', 'buffer', 'capacity', 'collision stack'))
                    and any(word in lower for word in ('overflow', 'overflown', 'exceed', 'insufficient', 'increase')))):
            result.append(line)
    return result


def source_hashes(*, include_probe=True):
    files = set((ROOT / 'tasks').rglob('*.py'))
    files.update((ROOT / 'assets/appearance/objects/pipette_transfer').glob('*/bindings.json'))
    files.update((ROOT / 'tasks/assets/variation/pipette_transfer').rglob('*.json'))
    files.add(ROOT / 'assets/appearance/objects/pipette_transfer/catalog.json')
    files.update(ROOT / 'tools/variation' / name for name in (
        'check_pipette_runtime.py', 'check_pipette_dynamics.py'))
    if include_probe:
        files.add(ROOT / 'tools/variation/check_pipette_rendering.py')
    files.update(ROOT / 'tools/variation' / name for name in (
        'check_furniture_appearance.py', 'check_furniture_dynamics.py', 'sapien_sdk/run_task_check.py'))
    files.update((ROOT / 'tasks/assets/task_object_meshes/pipette').glob('*'))
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(files) if path.is_file()}


def asset_closure(base):
    """Actual robot URDF plus directly referenced meshes/textures and OBJ materials."""
    import xml.etree.ElementTree as ET
    import shlex
    paths = {Path(base.agent.urdf_path).resolve()}
    pending = list(paths)
    while pending:
        path = pending.pop()
        references = []
        if path.suffix.lower() == '.urdf':
            references = [node.get('filename') for node in ET.parse(path).getroot().iter()
                          if node.tag in ('mesh', 'texture') and node.get('filename')]
        elif path.suffix.lower() in ('.obj', '.mtl'):
            for line in path.read_text(encoding='utf-8', errors='strict').splitlines():
                pieces = shlex.split(line, comments=True)
                if pieces and (pieces[0] == 'mtllib' or pieces[0].startswith('map_')):
                    references.extend(pieces[1:])
        for name in references:
            target = (path.parent / name).resolve(strict=True)
            if not target.is_relative_to(ROOT.resolve()):
                raise ValueError(f'Robot asset outside repository: {target.name}')
            if target not in paths:
                paths.add(target)
                pending.append(target)
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(paths)}


def closure_unchanged(files):
    return all((ROOT / name).is_file() and sha(ROOT / name) == expected
               for name, expected in files.items())


def external_hashes():
    import mani_skill
    package = Path(mani_skill.__file__).resolve().parent
    files = list(package.rglob('*.py'))
    files += [package / 'utils/scene_builder/table/assets/table.glb',
              package / 'utils/building/assets/grid_texture.png']
    return {'mani_skill/' + path.relative_to(package).as_posix(): sha(path)
            for path in sorted(set(files)) if path.is_file()}


def map_state_views(values, num_envs, registries):
    """Losslessly expose original per-scene state leaves to the shared batched checker."""
    import torch
    mapped, metadata = {}, {}
    for path, value in values.items():
        pieces = path.split('/')
        if (value.ndim and value.shape[0] != num_envs and len(pieces) == 4
                and pieces[1] == 'state' and pieces[2] in registries):
            handle = registries[pieces[2]][pieces[3]]
            indices = handle._scene_idxs.detach().cpu().long()
            assert len(indices) == len(value) and len(indices.unique()) == len(indices)
            assert bool(((indices >= 0) & (indices < num_envs)).all())
            full = torch.zeros((num_envs, *value.shape[1:]), dtype=value.dtype)
            full[indices] = value
            original_bytes = value.contiguous().view(torch.uint8).numpy().tobytes()
            restored_bytes = full[indices].contiguous().view(torch.uint8).numpy().tobytes()
            assert original_bytes == restored_bytes, 'Per-scene state mapping is not byte-preserving'
            membership = torch.zeros(num_envs, dtype=torch.bool)
            membership[indices] = True
            mapped[path] = full
            mapped[path + '/environment_membership'] = membership
            metadata[path] = {'original_shape': list(value.shape), 'scene_idxs': indices.tolist(),
                              'mapped_shape': list(full.shape), 'valid_rows': membership.tolist(),
                              'original_value_sha256': hashlib.sha256(original_bytes).hexdigest(),
                              'reconstructed_value_sha256': hashlib.sha256(restored_bytes).hexdigest()}
        else:
            mapped[path] = value
    assert all(path in mapped for path in values), 'Original state leaf was omitted'
    return mapped, metadata


def static_check(baseline='HEAD'):
    from check_pipette_appearance import check
    foundation = check()
    catalog = read(CATALOG)
    assert catalog['scope'] == 'material_appearance' and tuple(catalog['schemes']) == SCHEMES
    assert set(catalog['tasks']) == set(TASKS)
    for path in [*sorted((ROOT / 'tasks/pipette_transfer').glob('*.py')),
                 *sorted((ROOT / 'tools/variation').glob('*pipette*.py'))]:
        ast.parse(path.read_text(encoding='utf-8'), filename=path.name)
    source = 'tasks/pipette_transfer/pipette_transfer_long.py'
    current = ast.parse((ROOT / source).read_text(encoding='utf-8'))
    previous = ast.parse(subprocess.check_output(['git', 'show', baseline + ':' + source],
                                                cwd=ROOT, text=True, encoding='utf-8'))
    counts = {'predicate': 0, 'value': 0}
    class Normalize(ast.NodeTransformer):
        def visit_Call(self, node):
            node = self.generic_visit(node)
            if isinstance(node.func, ast.Attribute) and ast.unparse(node.func.value) == 'e':
                if node.func.attr == '_reset_scoped_predicate':
                    assert len(node.args) == 1 and not node.keywords
                    counts['predicate'] += 1
                    return node.args[0]
                if node.func.attr == '_reset_scoped_value':
                    assert len(node.args) == 2 and ast.unparse(node.args[0]) == 'self.stage'
                    counts['value'] += 1
                    return node.args[1]
            return node
    protected = {'evaluate', '_get_obs_extra', 'get_state_dict', 'set_state_dict',
                 'compute_dense_reward', 'compute_normalized_dense_reward',
                 '_mat', '_glass_mat', '_box', '_cyl', '_open_glass_wall', '_ring',
                 '_build_glass_beaker', '_build_test_tube', '_build_test_tube_rack',
                 '_build_pipette_stand', '_lengthen_pipette_grip', '_sample_layout'}
    def methods(tree, normalize=False):
        result = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in protected:
                if normalize:
                    node = Normalize().visit(node)
                result.append(ast.dump(node, include_attributes=False))
        return result
    assert methods(current, True) == methods(previous), 'Pipette geometry/judgment/reward/state AST changed'
    assert counts == {'predicate': 4, 'value': 2}, counts
    examples = sorted((ROOT / 'examples/variation/pipette_transfer').glob('*.json'))
    assert len(examples) == 3
    for path in examples:
        value = read(path)
        assert value['task_id'] in [f'PipetteTransfer{task}-Sharpa-v1' for task in TASKS]
    return {'status': 'passed', 'scope': 'CPU source/configuration/mock checks only',
            'catalog_version': catalog['version'], 'baseline': baseline,
            'geometry_judgment_reward_state_unchanged': True, 'scope_normalizations': counts,
            'foundation_checks': foundation['checks'], 'historical_model_previews': foundation['archived_model_previews'],
            'physics_steps': 0, 'runtime': 'NOT TESTED'}


def load_runtime():
    global np, torch, gym, sapien, shared
    sys.path.insert(0, str(ROOT))
    import numpy as np
    import torch
    import gymnasium as gym
    import sapien
    import check_furniture_appearance as shared
    shared.np, shared.torch, shared.gym, shared.sapien = np, torch, gym, sapien
    native_material_values = shared.material_values
    def complete_material_values(material, owner=None, texture_cache=None):
        values = native_material_values(material)
        for field in shared.MATERIAL_FIELDS:
            texture = getattr(material, field) if field.endswith('_texture') else None
            if texture is not None:
                values[field].update({name: getattr(texture, name) for name in
                                      ('channels', 'filter_mode', 'address_mode', 'is_srgb')})
                if not texture.filename:
                    assert owner is not None and owner.endswith('table-workspace'), 'Unknown embedded texture owner'
                    import mani_skill
                    package = Path(mani_skill.__file__).resolve().parent
                    cached = next((data for previous, data in texture_cache if previous == texture), None)
                    if cached is None:
                        data = np.ascontiguousarray(texture.download())
                        asset = package / 'utils/scene_builder/table/assets/table.glb'
                        cached = {'asset_ref': 'mani_skill/utils/scene_builder/table/assets/table.glb',
                                  'embedded_asset_sha256': sha(asset), 'data_sha256': hashlib.sha256(data.tobytes()).hexdigest(),
                                  'data_dtype': str(data.dtype), 'data_shape': list(data.shape),
                                  'source_kind': 'embedded GLB texture; original has no separate image filename'}
                        texture_cache.append((texture, cached))
                    values[field].update(copy.deepcopy(cached))
                    continue
                filename = Path(texture.filename).resolve(strict=True)
                if filename.is_relative_to(ROOT.resolve()):
                    values[field]['asset_ref'] = filename.relative_to(ROOT).as_posix()
                else:
                    import mani_skill
                    package = Path(mani_skill.__file__).resolve().parent
                    assert filename.is_relative_to(package), 'Unidentified external texture source'
                    values[field]['asset_ref'] = 'mani_skill/' + filename.relative_to(package).as_posix()
        return values
    shared.material_values = complete_material_values
    def measured_materials(base):
        if not hasattr(base, '_pipette_texture_measurements'):
            base._pipette_texture_measurements = []
        return [[{'entity': name, 'shape': shape, 'part': index,
                  'material': complete_material_values(part.material, name, base._pipette_texture_measurements)}
                 for name, shape, index, part in slots] for slots in shared.material_slots(base)]
    shared.materials = measured_materials
    shared.articulations = lambda base: {'robot': base.agent.robot, 'pipette': base.pipette}
    native_snapshot = shared.snapshot
    def mapped_snapshot(base):
        values = native_snapshot(base)
        registries = {'actors': base.scene.actors, 'articulations': base.scene.articulations}
        mapped, metadata = map_state_views(values, base.num_envs, registries)
        base._pipette_state_view_map = metadata
        return mapped
    shared.snapshot = mapped_snapshot
    return shared


def verify(base, schemes, native):
    adapter = base._pipette_appearance
    assert adapter.schemes == schemes
    slots, actual, expected = shared.material_slots(base), shared.materials(base), copy.deepcopy(native)
    for i, scheme in enumerate(schemes):
        assert adapter.bindings[i]
        for oid, role, part, material, captured in adapter.bindings[i]:
            assert part.material == material
            matches = [index for index, slot in enumerate(slots[i]) if slot[-1] == part]
            assert len(matches) == 1, (oid, role, matches)
            index, = matches
            assert shared.material_values(material).keys() == captured.keys()
            for field in shared.MATERIAL_FIELDS:
                if field.endswith('_texture'):
                    assert captured[field] is None
                else:
                    np.testing.assert_allclose(captured[field], native[i][index]['material'][field], rtol=0, atol=1e-7)
            values = adapter.resolved_parameters(captured, adapter.scheme_parameters(oid, scheme).get(role, {}))
            expected[i][index]['material'] = {key: shared.plain(value) for key, value in values.items()}
        for observed, target in zip(actual[i], expected[i]):
            assert {k: v for k, v in observed.items() if k != 'material'} == {
                k: v for k, v in target.items() if k != 'material'}
            for field in shared.MATERIAL_FIELDS:
                if field.endswith('_texture'):
                    assert observed['material'][field] == target['material'][field]
                else:
                    np.testing.assert_allclose(observed['material'][field], target['material'][field], rtol=0, atol=1e-7)
        records = [row for row in adapter.records if row['env_idx'] == i]
        assert [row['episode_index'] for row in records] == list(range(1, adapter.episodes[i] + 1))
        assert records[-1]['scheme_id'] == scheme
    assert len(adapter.records) == sum(adapter.episodes)
    assert all(row['catalog_version'] == adapter.catalog['version'] for row in adapter.records)
    return actual


def material_roles(base):
    slots, result = shared.material_slots(base), {}
    for env_id, rows in enumerate(base._pipette_appearance.bindings):
        for oid, role, part, _, _ in rows:
            indices = [i for i, slot in enumerate(slots[env_id]) if slot[-1] == part]
            assert len(indices) == 1
            result[f'/{env_id}/{indices[0]}/material'] = {'object_id': oid, 'role': role}
    return result


def prime_controller_targets(base):
    """Use the reviewed native action path, then verify every environment's precondition."""
    primed = shared.prime_controller_target(base)
    targets = shared.joint_targets(base)['robot']['position_target']
    conditions, forces, controllers = {}, {}, {}
    for env_id in range(base.num_envs):
        assert not torch.equal(targets[env_id], base.agent.robot.get_qpos()[env_id]), \
            f'Environment {env_id} has a trivial native controller target'
        conditions[str(env_id)] = {}
        def check(controller, path):
            if hasattr(controller, '_target_qpos'):
                nontrivial = not torch.equal(controller._target_qpos[env_id], controller.qpos[env_id])
                conditions[str(env_id)][path] = nontrivial
                assert nontrivial, f'Trivial {env_id}/{path} controller target'
            if type(controller).__name__ == 'FrankaJointImpedanceController':
                assert torch.count_nonzero(shared.joint_targets(base)['robot']['qf'][env_id]), \
                    f'Environment {env_id} has a trivial impedance force precondition'
            for name, child in getattr(controller, 'controllers', {}).items():
                check(child, path + '/' + name)
        check(base.agent.controller, 'controller')
        assert conditions[str(env_id)]
        forces[str(env_id)] = shared.plain(shared.joint_targets(base)['robot']['qf'][env_id])
        controllers[str(env_id)] = shared.controller_state(base, env_id)
    primed.update(nontrivial_targets_all_envs=conditions,
                  generalized_forces_all_envs=forces, controller_all_envs=controllers)
    return primed


def render_body_poses(base):
    data = base.scene.px.cuda_rigid_body_data.torch()
    return {f'{body.entity.name}#{index}': data[index, :7].detach().cpu().clone()
            for body, index in base.scene._get_all_render_bodies() if body is not None}


def raw_human_frame(base):
    camera = next(iter(base.scene.human_render_cameras.values())).camera._render_cameras[1]
    return {key: camera.get_picture_cuda(key).torch().detach().clone().cpu().numpy()
            for key in ('Color', 'Segmentation', 'PositionRaw', 'Position')}


def run_task(task, args, output, result):
    gpu = args.sim_backend == 'physx_cuda'
    num_envs, env, reset_index = (2 if gpu else 1), None, 0
    base, adapter = None, None
    result.update(control_steps=0, physics_steps=0, checks={})
    interface = result['checks']['interface_evidence'] = {}
    result['checks']['step_evidence'] = []
    last_selected_evidence = None

    def make(config=None):
        kwargs = {} if config is None else {'pipette_appearance': config}
        memory_profile = GPU_MEMORY_PROFILES[args.gpu_memory_profile]
        if memory_profile:
            kwargs['sim_config'] = {'gpu_memory_config': copy.deepcopy(memory_profile)}
        created = gym.make(f'PipetteTransfer{task}-Sharpa-v1', num_envs=num_envs,
            sim_backend=args.sim_backend, reconfiguration_freq=0,
            obs_mode='rgb' if gpu else 'state', render_mode='rgb_array',
            pipette_rendering={'enabled': True}, **kwargs)
        base = created.unwrapped
        assert base.num_envs == num_envs and base.backend.sim_backend == args.sim_backend
        assert base.device.type == ('cuda' if gpu else 'cpu')
        if gpu:
            assert base.scene.gpu_sim_enabled and base.scene._gpu_sim_initialized
        resolved = shared.plain(base.sim_config.dict())
        expected = shared.plain(base._default_sim_config.dict())
        expected['gpu_memory_config'].update(memory_profile)
        assert resolved == expected, 'Simulator configuration changed beyond the explicit capacity profile'
        if 'resolved_sim_config' in result:
            assert result['resolved_sim_config'] == resolved
        result['resolved_sim_config'] = resolved
        result['gpu_memory_profile'] = args.gpu_memory_profile
        return created

    def close():
        nonlocal env, base, adapter
        if env is not None:
            env.close()
            env = None
        base, adapter = None, None
        import gc
        gc.collect()
        if gpu:
            torch.cuda.empty_cache()

    def checked_reset(seed=None, options=None):
        nonlocal reset_index, last_selected_evidence
        if not gpu:
            return env.reset(seed=seed, options=options)
        report = {}
        prefix = f'selected_reset_{reset_index:02d}'
        last_selected_evidence = prefix + '.json'
        reset_index += 1
        try:
            return shared.selected_reset_check(env, seed, options, output, prefix, report)
        finally:
            result['checks'].setdefault('selected_reset_state', []).append({'evidence': prefix + '.json', **report})

    def reset(config=None):
        nonlocal env
        env = make(config)
        _, info = checked_reset(seed=7)
        return env.unwrapped, info

    def images(info):
        return shared.capture(env, info)

    def step(primed, context, prefix):
        before = shared.snapshot(env.unwrapped)
        action = torch.tensor(primed['action'], dtype=torch.float32, device=env.unwrapped.device)
        _, _, _, _, info = env.step(action)
        after = shared.snapshot(env.unwrapped)
        filename = prefix + '_step.pt'
        torch.save({'before': before, 'after': after, 'action': action.detach().cpu().clone(),
                    'context': context}, output / filename)
        result['checks']['step_evidence'].append({'evidence': filename, 'context': context,
            'control_steps': 1, 'physics_steps': env.unwrapped._sim_steps_per_control})
        result['control_steps'] += 1
        result['physics_steps'] += env.unwrapped._sim_steps_per_control
        return info

    def local_round(base, info, selected, prefix, appearance=False, do_step=False):
        other = 1 - selected
        before_prime = shared.snapshot(base)
        primed = prime_controller_targets(base)
        prime_file = prefix + '_prime.pt'
        torch.save({'before': before_prime, 'after': shared.snapshot(base),
                    'controller_after': copy.deepcopy(primed['controller_all_envs'])}, output / prime_file)
        primed['state_evidence'] = prime_file
        primed['state_sha256'] = sha(output / prime_file)
        if do_step:
            info = step(primed, 'appearance' if appearance else 'native', prefix)
        before_images = images(info)
        before_state, before_mat = shared.snapshot(base), shared.materials(base)
        before_controller, before_rng = shared.controller_state(base, other), shared.task_rng(base, other)
        before_counters = shared.controller_counters(base)
        before_physical = shared.physical(base)
        adapter = base._pipette_appearance
        before_records = copy.deepcopy(adapter.records) if appearance else None
        before_arng = copy.deepcopy(adapter.rng[other].bit_generator.state) if appearance else None
        options = {'env_idx': torch.tensor([selected], device=base.device)}
        if appearance:
            options['pipette_appearance'] = {'scheme_id': 'original'}
        _, info = checked_reset(options=options)
        after_images = images(info)
        after_state, after_mat = shared.snapshot(base), shared.materials(base)
        after_controller, after_rng = shared.controller_state(base, other), shared.task_rng(base, other)
        after_counters = shared.controller_counters(base)
        changes = shared.state_changes(before_state, after_state, [other])
        pixels = shared.image_changes(before_images, after_images, output, prefix, env_id=other)
        selected_pixels = shared.image_changes(before_images, after_images, output, prefix, env_id=selected)
        row = {'selected': [selected], 'unselected': [other], 'state_changes': changes,
               'pixel_changes': pixels, 'selected_pixel_changes': selected_pixels,
               'controller_precondition': primed, 'precondition_control_steps': int(do_step),
               'precondition_physics_steps': base._sim_steps_per_control if do_step else 0,
               'before_controller_unselected': before_controller, 'after_controller_unselected': after_controller,
               'before_shared_controller_counters': before_counters, 'after_shared_controller_counters': after_counters,
               'before_task_rng_unselected': before_rng, 'after_task_rng_unselected': after_rng,
               'before_materials': before_mat, 'after_materials': after_mat,
               'before_physical': before_physical, 'after_physical': shared.physical(base),
               'selected_state_evidence': last_selected_evidence,
               'controller_unchanged': before_controller == after_controller,
               'task_rng_unchanged': before_rng == after_rng,
               'materials_unchanged': before_mat[other] == after_mat[other],
               'physical_unchanged': before_physical == shared.physical(base)}
        if appearance:
            row.update(appearance_rng_unchanged=before_arng == adapter.rng[other].bit_generator.state,
                       before_appearance_rng_unselected=before_arng,
                       after_appearance_rng_unselected=copy.deepcopy(adapter.rng[other].bit_generator.state),
                       before_records=before_records, after_records=copy.deepcopy(adapter.records))
            assert adapter.records[:len(before_records)] == before_records
            assert len(adapter.records) == len(before_records) + 1 and adapter.records[-1]['env_idx'] == selected
            assert row['appearance_rng_unchanged']
            assert any(value['changed_values'] for name, value in selected_pixels.items() if not name.startswith('human'))
        torch.save({'before': before_state, 'after': after_state}, output / f'{prefix}.pt')
        row['state_evidence'] = f'{prefix}.pt'
        row['state_sha256'] = sha(output / f'{prefix}.pt')
        dump(output / f'{prefix}.json', row)
        shared.save_image_pairs(before_images, after_images, output, prefix)
        assert not changes and not any(item['changed_values'] for item in pixels.values()), 'Unselected state/RGB changed'
        assert all(row[field] for field in ('controller_unchanged', 'task_rng_unchanged', 'materials_unchanged', 'physical_unchanged'))
        return info, row

    try:
        result['stage'] = 'native baseline'
        base, info = reset()
        assert base._pipette_appearance is None
        native, baseline, properties, native_info = shared.materials(base), shared.snapshot(base), shared.physical(base), shared.plain(info)
        result['state_view_map'] = copy.deepcopy(base._pipette_state_view_map)
        result['asset_closure_sha256'] = asset_closure(base)
        result['rendering'] = copy.deepcopy(base._pipette_rendering.identity)
        torch.save({'before': baseline, 'after': shared.snapshot(base)}, output / 'default_disabled_state.pt')
        interface['default_disabled'] = {'config': None, 'adapter_present': False,
            'materials': native, 'physical': properties, 'state_evidence': 'default_disabled_state.pt'}
        native_images, diagnostic = None, None
        if gpu:
            before_capture = shared.snapshot(base)
            native_images = images(info)
            first_capture = shared.snapshot(base)
            repeat_images = images(info)
            repeat_capture = shared.snapshot(base)
            torch.save({'before_capture': before_capture, 'after_first_capture': first_capture,
                        'after_repeat_capture': repeat_capture}, output / 'native_capture_states.pt')
            diagnostic = {'first_capture_state_changes': shared.state_changes(before_capture, first_capture),
                'repeat_capture_state_changes': shared.state_changes(first_capture, repeat_capture),
                'repeat_capture_pixel_changes': {str(i): shared.image_changes(native_images, repeat_images,
                    output, 'native_capture', env_id=i) for i in range(num_envs)}}
            dump(output / 'native_capture_diagnostic.json', diagnostic)
            shared.save_image_pairs(native_images, repeat_images, output, 'native_capture')
            assert not diagnostic['first_capture_state_changes'] and not diagnostic['repeat_capture_state_changes']
            assert not any(v['changed_values'] for rows in diagnostic['repeat_capture_pixel_changes'].values() for v in rows.values())
        native_render_poses = render_body_poses(base) if gpu else None
        native_raw_human = raw_human_frame(base) if gpu else None
        dump(output / 'native_materials.json', native)
        dump(output / 'native_physical.json', properties)
        result['checks']['default_disabled'] = 'passed'
        if gpu and args.rendering_probe_only:
            from check_pipette_rendering import probe
            result['checks']['rendering_probe'] = probe(env, info, output, shared, checked_reset)
            result.update(status='passed', stage='supplementary rendering probe complete')
            return
        if gpu:
            rounds = []
            for selected in (1, 0):
                info, row = local_round(base, info, selected, f'native_local_{selected}', do_step=selected == 0)
                rounds.append(row)
            result['checks']['native_local_reset_control'] = {'capture_diagnostic': diagnostic, 'rounds': rounds}
        close()
        result['stage'] = 'explicit disabled'
        base, info = reset({'enabled': False})
        assert base._pipette_appearance is None
        assert not shared.state_changes(baseline, shared.snapshot(base))
        assert native == shared.materials(base) and properties == shared.physical(base) and native_info == shared.plain(info)
        torch.save({'before': baseline, 'after': shared.snapshot(base)}, output / 'explicit_disabled_state.pt')
        interface['explicit_disabled'] = {'config': {'enabled': False}, 'adapter_present': False,
            'materials': shared.materials(base), 'physical': shared.physical(base),
            'state_evidence': 'explicit_disabled_state.pt'}
        result['checks']['explicit_disabled'] = 'passed'
        close()
        for scheme in SCHEMES:
            result['stage'] = 'fixed ' + scheme
            base, info = reset({'enabled': True, 'scheme_id': scheme})
            measured = verify(base, [scheme] * num_envs, native)
            roles = material_roles(base)
            assert not result['checks'].get('material_roles') or result['checks']['material_roles'] == roles
            result['checks']['material_roles'] = roles
            assert not shared.state_changes(baseline, shared.snapshot(base))
            assert properties == shared.physical(base) and native_info == shared.plain(info)
            records = copy.deepcopy(base._pipette_appearance.records)
            if gpu:
                from PIL import Image
                observed = images(info)
                differences = {str(i): shared.image_changes(native_images, observed, output, f'fixed_{scheme}', env_id=i)
                               for i in range(num_envs)}
                for rows in differences.values():
                    assert (any(row['changed_values'] for name, row in rows.items() if not name.startswith('human'))
                            if scheme != 'original' else not any(row['changed_values'] for row in rows.values()))
                for name, frames in observed.items():
                    for i, frame in enumerate(frames):
                        Image.fromarray(frame).save(output / f'{scheme}_{name}_env{i}.png')
                assert records == base._pipette_appearance.records
            result['checks'][scheme] = {'status': 'passed', 'materials': measured, 'records': records}
            close()
        traces = []
        for repeat in range(2):
            result['stage'] = f'random repeat {repeat}'
            base, info = reset({'enabled': True, 'mode': 'random_choice', 'scheme_ids': list(SCHEMES), 'seed': 71})
            trace = []
            partitions = ([1], [0], [0, 1]) if gpu else ([0], [0], [0])
            inputs = (('list', list(partitions[0])), ('tuple', tuple(partitions[1])),
                      ('torch.uint8', torch.tensor(partitions[2], dtype=torch.uint8, device=base.device)))
            for selected, (input_type, env_idx) in zip(partitions, inputs):
                adapter = base._pipette_appearance
                before_rng = copy.deepcopy([rng.bit_generator.state for rng in adapter.rng])
                before_records = copy.deepcopy(adapter.records)
                options = {'env_idx': env_idx}
                checked_reset(options=options)
                assert options['env_idx'] is env_idx
                verify(base, base._pipette_appearance.schemes, native)
                trace.append({'selected': list(selected), 'env_idx_input_type': input_type,
                    'reset': {}, 'before_rng': before_rng,
                    'after_rng': copy.deepcopy([rng.bit_generator.state for rng in adapter.rng]),
                    'before_records': before_records, 'after_records': copy.deepcopy(adapter.records)})
            traces.append(trace)
            dump(output / f'random_trace_{repeat + 1}.json', {
                'records': copy.deepcopy(base._pipette_appearance.records), 'trace': trace})
            close()
        assert traces[0] == traces[1]
        result['checks']['random_reproducibility'] = {'status': 'passed', 'records': traces[0][-1]['after_records'],
            'traces': [{'file': f'random_trace_{repeat + 1}.json',
                        'sha256': sha(output / f'random_trace_{repeat + 1}.json')} for repeat in range(2)]}
        interface['random_reproducibility'] = {'constructor': {'enabled': True, 'mode': 'random_choice',
            'scheme_ids': list(SCHEMES), 'seed': 71}, 'runs': copy.deepcopy(traces)}
        constructor = {'enabled': True, 'scheme_id': 'original', 'per_env': {'0': {'scheme_id': 'coral'}}}
        base, info = reset(constructor)
        precedence_cases = []
        for override, scheme in (({'scheme_id': 'original'}, 'original'),
                ({'scheme_id': 'original', 'per_env': {'0': {'scheme_id': 'jade'}}}, 'jade')):
            before_records = copy.deepcopy(base._pipette_appearance.records)
            checked_reset(options={'env_idx': torch.tensor([0], device=base.device), 'pipette_appearance': override})
            verify(base, [scheme] + ['original'] * (num_envs - 1), native)
            precedence_cases.append({'constructor': constructor, 'reset': override, 'selected': [0],
                'schemes': list(base._pipette_appearance.schemes), 'before_records': before_records,
                'after_records': copy.deepcopy(base._pipette_appearance.records), 'materials': shared.materials(base)})
        interface['selection_precedence'] = precedence_cases
        result['checks']['selection_precedence'] = {'status': 'passed',
            'constructor_config': {'enabled': True, 'scheme_id': 'original', 'per_env': {'0': {'scheme_id': 'coral'}}},
            'reset_override': {'scheme_id': 'original', 'per_env': {'0': {'scheme_id': 'jade'}}},
            'actual_schemes': list(base._pipette_appearance.schemes),
            'records': copy.deepcopy(base._pipette_appearance.records)}
        adapter = base._pipette_appearance
        before_mat = shared.materials(base)
        before_rng = copy.deepcopy([rng.bit_generator.state for rng in adapter.rng])
        before_records, before_episodes = copy.deepcopy(adapter.records), list(adapter.episodes)
        before_schemes = list(adapter.schemes)
        invalid_request = {'mode': 'random_choice', 'scheme_ids': ['jade', 'coral'],
                           'per_env': {str(num_envs - 1): {'mode': 'explicit', 'scheme_id': 'unknown'}}}
        rejected = False
        error_type = None
        try:
            adapter.finish_reset(torch.arange(num_envs, device=base.device), {'pipette_appearance': invalid_request})
        except ValueError as error:
            rejected = True
            error_type = type(error).__name__
        assert rejected and before_mat == shared.materials(base)
        assert before_rng == [rng.bit_generator.state for rng in adapter.rng]
        assert before_records == adapter.records and before_episodes == adapter.episodes
        interface['invalid_request_atomicity'] = {'request': invalid_request, 'error_type': error_type,
            'before': {'materials': before_mat, 'appearance_rng': before_rng, 'episodes': before_episodes,
                       'schemes': before_schemes, 'records': before_records},
            'after': {'materials': shared.materials(base),
                      'appearance_rng': copy.deepcopy([rng.bit_generator.state for rng in adapter.rng]),
                      'episodes': list(adapter.episodes), 'schemes': list(adapter.schemes),
                      'records': copy.deepcopy(adapter.records)}}
        result['checks']['invalid_last_environment_atomicity'] = 'passed'
        if gpu:
            def rejection_state():
                return {'materials': shared.materials(base),
                        'controller': [shared.controller_state(base, i) for i in range(num_envs)],
                        'episode_rng': [shared.task_rng(base, i) for i in range(num_envs)],
                        'main_rng': shared.plain(base._main_rng.get_state()),
                        'batched_main_rng': [shared.plain(base._batched_main_rng[i].get_state()) for i in range(num_envs)],
                        'appearance_rng': copy.deepcopy([rng.bit_generator.state for rng in adapter.rng]),
                        'records': copy.deepcopy(adapter.records), 'episodes': list(adapter.episodes),
                        'schemes': list(adapter.schemes)}

            def reject_reset(name, request, expected_message, *, seed=None, restore=False):
                options = copy.deepcopy(request)
                if 'env_idx' in options:
                    options['env_idx'] = torch.tensor(options['env_idx'], device=base.device)
                if restore:
                    options['reset_to_env_states'] = {'env_states': base.get_state_dict()}
                before_rejection, before_state = rejection_state(), shared.snapshot(base)
                try:
                    env.reset(seed=seed, options=options)
                except ValueError as error:
                    assert expected_message in str(error), f'{name}: {error}'
                    rejection = {'type': type(error).__name__, 'message': str(error)}
                else:
                    raise AssertionError(f'Reset accepted {name}')
                after_rejection, after_state = rejection_state(), shared.snapshot(base)
                assert before_rejection == after_rejection and not shared.state_changes(before_state, after_state), name
                state_file = f'{name}.pt'
                torch.save({'before': before_state, 'after': after_state}, output / state_file)
                row = {'request': request, 'seed': seed, 'actual_state_restore_payload': restore,
                       'error': rejection, 'before': before_rejection, 'after': after_rejection,
                       'state_evidence': state_file, 'state_sha256': sha(output / state_file)}
                dump(output / f'{name}.json', row)
                return row

            reject_reset('partial_seed_rejection', {'env_idx': [1]}, 'omit seed', seed=17)
            result['checks']['partial_seed_rejection'] = 'passed'
            requests = {
                'descending_env_idx_rejection': ({'env_idx': [1, 0]}, 'strictly increasing', False),
                'restore_override_rejection': ({'pipette_appearance': {'scheme_id': 'coral'}},
                                               'state restoration', True),
                'reset_per_env_rejection': ({'pipette_appearance': {
                    'mode': 'random_choice', 'scheme_ids': ['jade', 'coral'],
                    'per_env': {str(num_envs): {'scheme_id': 'coral'}}}}, 'per_env', False),
            }
            interface['reset_preflight_rejections'] = {
                name: reject_reset(name, request, message, restore=restore)
                for name, (request, message, restore) in requests.items()}
        close()
        if gpu:
            invalid_constructor = {'enabled': False, 'per_env': {str(num_envs): {'scheme_id': 'jade'}}}
            try:
                env = make(invalid_constructor)
            except ValueError as error:
                assert 'per_env' in str(error)
                interface['constructor_per_env_rejection'] = {
                    'config': invalid_constructor, 'error': {'type': type(error).__name__, 'message': str(error)}}
            else:
                raise AssertionError('Constructor accepted an out-of-range per_env key')
        if gpu:
            base, info = reset({'enabled': True, 'scheme_id': 'jade', 'per_env': {'1': {'scheme_id': 'coral'}}})
            verify(base, ['jade', 'coral'], native)
            for selected in (1, 0):
                info, row = local_round(base, info, selected, f'local_reset_{selected}', appearance=True, do_step=selected == 0)
                result['checks'][f'local_reset_{selected}'] = row
                verify(base, ['jade', 'original'] if selected == 1 else ['original', 'original'], native)
            close()
            base, info = reset({'enabled': True, 'scheme_id': 'coral'})
            candidate_images = images(info)
            _, info = checked_reset(seed=7, options={'pipette_appearance': {'scheme_id': 'original'}})
            verify(base, ['original'] * num_envs, native)
            assert not shared.state_changes(baseline, shared.snapshot(base))
            restored = images(info)
            pixels = {str(i): shared.image_changes(native_images, restored, output, 'original_restoration', env_id=i)
                      for i in range(num_envs)}
            shared.save_image_pairs(candidate_images, restored, output, 'original_restoration')
            restored_render_poses = render_body_poses(base)
            torch.save({'native': native_render_poses, 'restored': restored_render_poses}, output / 'original_render_body_poses.pt')
            pose_changes = shared.state_changes(native_render_poses, restored_render_poses)
            dump(output / 'original_render_body_pose_changes.json', pose_changes)
            repeated = images(info)
            repeat_pixels = {str(i): shared.image_changes(restored, repeated, output, 'original_restore_repeat', env_id=i)
                             for i in range(num_envs)}
            dump(output / 'original_restoration_pixels.json', {'native_to_restored': pixels, 'restore_repeat': repeat_pixels})
            raw_restored = raw_human_frame(base)
            changed = np.any(native_images['human'][1] != restored['human'][1], axis=-1)
            coordinates = np.argwhere(changed)
            raw_rows = []
            for y, x in coordinates:
                raw_rows.append({'yx': [int(y), int(x)], 'native': {key: shared.plain(value[y, x]) for key, value in native_raw_human.items()},
                                 'restored': {key: shared.plain(value[y, x]) for key, value in raw_restored.items()}})
            dump(output / 'original_raw_changed_pixels.json', raw_rows)
            assert not any(row['changed_values'] for rows in pixels.values() for row in rows.values())
            result['checks']['original_rgb_restoration'] = {'status': 'passed', 'pixel_changes': pixels}
        else:
            result['checks']['local_reset_isolation'] = {'status': 'NOT TESTED', 'reason': 'CPU uses one environment'}
        result.update(status='passed', stage='complete')
    finally:
        close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static', action='store_true')
    parser.add_argument('--baseline', default='HEAD')
    parser.add_argument('--approved-runtime', action='store_true')
    parser.add_argument('--sim-backend', choices=('physx_cpu', 'physx_cuda'))
    parser.add_argument('--experimental-windows-cuda', action='store_true')
    parser.add_argument('--physx-gpu-dir', type=Path)
    parser.add_argument('--gpu-memory-profile', choices=tuple(GPU_MEMORY_PROFILES), default='native',
                        help='Capacity only; two_env keeps all solver/contact/frequency settings and original cameras')
    parser.add_argument('--rendering-probe-only', action='store_true',
                        help='Separate supplementary camera/depth probe; does not claim task isolation acceptance')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--task', choices=TASKS, action='append')
    args = parser.parse_args()
    if args.static:
        print(json.dumps(static_check(args.baseline), ensure_ascii=False))
        return 0
    if not args.approved_runtime or args.output is None or args.sim_backend is None:
        parser.error('Runtime requires --approved-runtime, --sim-backend and fresh --output')
    if args.gpu_memory_profile != 'native' and args.sim_backend != 'physx_cuda':
        parser.error('The two_env capacity profile is for the two-environment CUDA check only')
    if args.rendering_probe_only and args.sim_backend != 'physx_cuda':
        parser.error('--rendering-probe-only requires the CUDA path')
    args.output.mkdir(parents=True, exist_ok=False)
    results = {'status': 'running', 'tasks': [], 'test_mode': 'standard', 'formal_acceptance': 'pending',
               'scope': 'standard two-environment CUDA RGB and local reset' if args.sim_backend == 'physx_cuda'
                        else 'CPU single-environment materials/state; no RGB or batching claim'}
    started = time.monotonic()
    include_probe = args.rendering_probe_only
    before = source_hashes(include_probe=include_probe)
    external_before = None
    try:
        load_runtime()
        external_before = external_hashes()
        gpu_libraries = {}
        if args.sim_backend == 'physx_cuda' and platform.system() == 'Windows':
            if not args.experimental_windows_cuda:
                raise RuntimeError('Windows CUDA requires --experimental-windows-cuda and the reviewed SDK launcher')
            import ctypes
            cache = args.physx_gpu_dir or Path.home() / '.sapien/physx' / sapien.physx.version()
            dll_directory = os.add_dll_directory(str(cache))
            dlls = [ctypes.WinDLL(str(cache / name)) for name in ('PhysXDevice64.dll', 'PhysXGpu_64.dll')]
            gpu_libraries = {name: sha(cache / name) for name in ('PhysXDevice64.dll', 'PhysXGpu_64.dll')}
            if not sapien.physx.is_gpu_enabled():
                sapien.physx._enable_gpu()
        from mani_skill.utils import download_asset
        def reject_download(*unused_args, **unused_kwargs):
            raise RuntimeError('Asset downloading disabled; prepare authorized assets before validation')
        download_asset.download = download_asset.download_from_hf_datasets = reject_download
        import tasks
        selected = args.task or list(TASKS)
        manifest = {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'command': sys.argv, 'platform': platform.system(), 'python': sys.version,
            'sim_backend': args.sim_backend, 'num_envs': 2 if args.sim_backend == 'physx_cuda' else 1,
            'task_ids': [f'PipetteTransfer{task}-Sharpa-v1' for task in selected],
            'test_mode': 'standard', 'catalog_version': read(CATALOG)['version'],
            'rendering_probe_only': args.rendering_probe_only,
            'gpu_memory_profile': args.gpu_memory_profile,
            'gpu_memory_overrides': GPU_MEMORY_PROFILES[args.gpu_memory_profile],
            'resolved_sim_config': {},
            'capture_path': 'original ManiSkill RGB cameras with explicit opt-in repaired default shaders'
                            if args.sim_backend == 'physx_cuda' else 'not captured',
            'pipette_rendering': {'enabled': True}, 'native_default_shader': 'minimal; unchanged and separate',
            'versions': {name: metadata.version(name) for name in ('torch', 'sapien', 'mani_skill', 'gymnasium', 'numpy')},
            'physx_gpu_library_sha256': gpu_libraries, 'files': before}
        manifest['external_files'] = external_before
        dump(args.output / 'manifest.json', manifest)
        for task in selected:
            row = {'task': task, 'status': 'running', 'checks': {}}
            results['tasks'].append(row)
            folder = args.output / task
            folder.mkdir()
            try:
                with native_log(folder / 'native.log'):
                    run_task(task, args, folder, row)
                row['native_buffer_errors'] = buffer_errors(folder / 'native.log')
                row['native_log_sha256'] = sha(folder / 'native.log')
                assert not row['native_buffer_errors'], 'Native capacity/buffer overflow or allocation failure'
            except BaseException:
                row.update(status='failed', error=traceback.format_exc())
                raise
            finally:
                if 'resolved_sim_config' in row:
                    manifest['resolved_sim_config'][task] = row['resolved_sim_config']
                    manifest.setdefault('asset_closure_sha256', {})[task] = row.get('asset_closure_sha256', {})
                    dump(args.output / 'manifest.json', manifest)
                dump(args.output / 'results.json', results)
        results['status'] = 'passed'
        results['formal_acceptance'] = ('NOT TESTED: supplementary rendering probe only' if args.rendering_probe_only
            else 'passed' if args.sim_backend == 'physx_cuda' else 'NOT TESTED: CPU only')
    except BaseException:
        results.update(status='failed', error=traceback.format_exc(), formal_acceptance='failed')
    finally:
        results['source_hashes_unchanged'] = source_hashes(include_probe=include_probe) == before
        results['external_hashes_unchanged'] = external_before is not None and external_hashes() == external_before
        results['asset_hashes_unchanged'] = all(closure_unchanged(row['asset_closure_sha256'])
            for row in results['tasks'] if row.get('asset_closure_sha256'))
        if (not results['source_hashes_unchanged'] or not results['asset_hashes_unchanged']
                or not results['external_hashes_unchanged']):
            results.update(status='failed', formal_acceptance='failed', source_hash_error='Inputs changed during validation')
        results['control_steps'] = sum(row.get('control_steps', 0) for row in results['tasks'])
        results['physics_steps'] = sum(row.get('physics_steps', 0) for row in results['tasks'])
        results['elapsed_seconds'] = time.monotonic() - started
        dump(args.output / 'results.json', results)
        print(json.dumps({'status': results['status'], 'tasks': [{key: row[key] for key in ('task', 'status')}
                                                              for row in results['tasks']]}))
    return 0 if results['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
