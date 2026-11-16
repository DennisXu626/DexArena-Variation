"""Cabinet #10 single-process short check. --static uses only the standard library.

Runtime requires a separate, explicitly confirmed storage-risk approval and an
allocated GPU job. Fail once and retain partial results; never step a policy.
"""
import argparse
import copy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
TASKS = {'OpenCabinet': (2, {'cabinet'}), 'PickBottle': (2, {'cabinet', 'beads'}),
         'UnscrewCap': (2, {'beads'}), 'PourBeads': (2, {'bowl', 'beads'}),
         'Long': (1, {'cabinet', 'bowl', 'beads'})}
SCHEMES = ['original', 'ocean', 'citrus', 'violet']
ROOT_APPROVED = '/mnt/ceph2/xkl/DexArena/cabinet_remaining_appearance_20261116'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--static', action='store_true')
parser.add_argument('--approved-runtime', action='store_true')
parser.add_argument('--approval', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
catalog = json.loads((ROOT / 'tasks/assets/variation/cabinet_pouring/v1/catalog.json').read_text())
if args.static:
    import ast
    ast.parse(Path(__file__).read_text())
    assert all(set(catalog['schemes'][s]['objects']) == {'cabinet', 'bowl', 'beads'} for s in ['ocean', 'citrus'])
    assert 'objects' not in catalog['schemes']['violet']
    print(json.dumps({'status': 'static_passed', 'tasks': TASKS, 'runtime': 'NOT RUN', 'GPU_seconds': 0}, default=list))
    sys.exit(0)
if not args.approved_runtime or args.approval is None or args.output is None:
    parser.error('Requires --approved-runtime --approval --output; resource approval alone is insufficient')
approval = json.loads(args.approval.read_text())
assert approval.get('budget_approved') is True
assert approval.get('storage_risk_confirmed_by_Dennis') is True
assert approval.get('storage_root') == ROOT_APPROVED
assert approval.get('accept_sampled_limit_overshoot') is True
assert approval.get('blockers_resolved') is True
assert approval.get('max_GPU_seconds') == 600 and approval.get('max_jobs') == 1
assert os.environ.get('SLURM_JOB_ID'), 'Allocated job required'
assert args.output.resolve().is_relative_to(Path(ROOT_APPROVED).resolve())
args.output.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(ROOT))
import gymnasium as gym
import numpy as np
import torch
import sapien.render as sr
from PIL import Image
import tasks

OUT = args.output
results = {'status': 'running', 'tasks': {}, 'user_physics_steps': 0,
           'internal_gpu_warm_start': 'native framework behavior; not robot execution'}


def plain(value):
    if torch.is_tensor(value): return value.detach().cpu().tolist()
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, np.generic): return value.item()
    if isinstance(value, dict): return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [plain(v) for v in value]
    return value


def dump(path, value):
    path.write_text(json.dumps(plain(value), indent=2) + '\n')


def entries(e):
    """Read actual loaded objects independently of the adapter's binding list."""
    rows = []
    for name in ['source', 'source_fixed', 'source_open', 'cap', 'cap_fixed', 'cap_twin']:
        for i, raw in enumerate(getattr(getattr(e, name, None), '_objs', [])):
            rows.append((name, i, raw))
    for i, cabinet in enumerate(getattr(e, '_cabinets', [])):
        for link in cabinet.get_links():
            rows.extend(('cabinet:' + link.name, i, raw) for raw in link._objs)
    rows.extend(('bowl', i, raw) for i, raw in enumerate(getattr(getattr(e, 'target', None), '_objs', [])))
    for j, particle in enumerate(getattr(e, 'particles', [])):
        assert len(particle._objs) == e.num_envs, 'Particle index/environment mapping mismatch'
        rows.extend((f'particle:{j}', i, raw) for i, raw in enumerate(particle._objs))
    return rows


def body(raw):
    return getattr(raw, 'entity', raw).find_component_by_type(sr.RenderBodyComponent)


def materials(e):
    data = {}
    for name, i, raw in entries(e):
        render = body(raw)
        if render is None: continue
        values = []
        for shape in render.render_shapes:
            for part in shape.parts:
                m = part.material
                values.append({k: plain(getattr(m, k)) for k in ['base_color', 'roughness', 'metallic',
                              'specular', 'transmission', 'transmission_roughness', 'ior', 'emission']})
                for k in ['base_color_texture', 'roughness_texture', 'metallic_texture',
                          'normal_texture', 'transmission_texture', 'emission_texture']:
                    texture = getattr(m, k)
                    values[-1][k] = None if texture is None else str(texture.filename)
        data[f'{name}/{i}'] = values
    return data


def physical(e):
    data = {}
    for name, i, raw in entries(e):
        c = e._raw_collision_component(raw)
        shapes = []
        for sh in c.get_collision_shapes():
            geometry = {}
            if hasattr(sh, 'get_vertices'):
                geometry['mesh_sha256'] = hashlib.sha256(np.asarray(sh.get_vertices()).tobytes()).hexdigest()
            else:
                for key in ['radius', 'half_length', 'half_size']:
                    if hasattr(sh, key): geometry[key] = plain(getattr(sh, key))
                assert geometry, f'Unhandled collision type {type(sh).__name__}'
            m = sh.physical_material
            shapes.append({'type': type(sh).__name__, 'geometry': geometry,
                'pose': [plain(sh.local_pose.p), plain(sh.local_pose.q)],
                'groups': list(sh.get_collision_groups()), 'contact': sh.contact_offset, 'rest': sh.rest_offset,
                'friction_restitution': [m.static_friction, m.dynamic_friction, m.restitution]})
        render = body(raw)
        visuals = [] if render is None else [hashlib.sha256(np.asarray(p.vertices).tobytes() +
            np.asarray(p.triangles).tobytes() + np.asarray(p.get_vertex_uv()).tobytes()).hexdigest()
            for s in render.render_shapes for p in s.parts]
        data[f'{name}/{i}'] = {'mass': c.mass, 'inertia': plain(c.inertia),
            'cmass': [plain(c.cmass_local_pose.p), plain(c.cmass_local_pose.q)],
            'collision': shapes, 'visual_geometry_UV': visuals}
    for i, cabinet in enumerate(getattr(e, '_cabinets', [])):
        data[f'cabinet_joints/{i}'] = {'limits': plain(cabinet.get_qlimits()),
            'joints': [{k: plain(getattr(j, k)) for k in ['stiffness', 'damping', 'force_limit', 'friction']}
                       for j in cabinet.get_active_joints()]}
    return plain(data)


def snapshot(e):
    articulations = {'robot': e.agent.robot}
    for name in ['bottle_screw', 'bottle_screw_fixed']:
        if getattr(e, name, None) is not None: articulations[name] = getattr(e, name)
    drives = {name: {j.name: {'position': j.drive_target, 'velocity': j.drive_velocity_target}
                    for j in articulation.get_active_joints()} for name, articulation in articulations.items()}
    return plain({'state': e.get_state_dict(), 'drive_targets': drives, 'task_tensors':
                  {k: v for k, v in vars(e).items() if torch.is_tensor(v)}})


def unselected(a, b, n):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for k in a: unselected(a[k], b[k], n)
    elif isinstance(a, list) and len(a) == n:
        assert a[0] == b[0], 'Unselected environment state changed'
    else:
        assert a == b


def verify(e, ids, native):
    a = e._variation
    a._collect_bindings()
    assert a.schemes == ids
    actual = materials(e)
    assert sum(len(v) for v in actual.values()) == sum(len(v) for v in a._bindings), 'Unbound render parts'
    for i, bindings in enumerate(a._bindings):
        scheme = catalog['schemes'][ids[i]]
        for b in bindings:
            m, original, role = b['material'], b['original'], b['role']
            new_object = role in ['cabinet', 'cabinet_detail', 'bowl', 'beads']
            params = scheme.get('objects', {}).get(role) if new_object else None
            if ids[i] == 'original' or (new_object and params is None):
                for k, expected in original.items():
                    if k == 'base_color': np.testing.assert_array_equal(m.base_color, expected)
                    else: assert getattr(m, k) == expected
            elif new_object:
                expected = list(params['base_color']); expected[3] = float(original['base_color'][3])
                np.testing.assert_allclose(m.base_color, expected, rtol=0, atol=1e-7)
                assert m.base_color_texture == original['base_color_texture']
                assert abs(m.roughness - params['roughness']) < 1e-7
                assert abs(m.metallic - params['metallic']) < 1e-7
            else:
                if role == 'body_label':
                    assert Path(m.base_color_texture.filename).name == scheme['label_texture']
                    np.testing.assert_array_equal(m.base_color, [1, 1, 1, 1])
                else:
                    key = {'body_surface': 'body_color', 'cap_surface': 'cap_color', 'cap_reference': 'reference_color'}[role]
                    np.testing.assert_allclose(m.base_color, scheme[key], rtol=0, atol=1e-7)
                assert abs(m.roughness - scheme['roughness']) < 1e-7
                assert abs(m.metallic - scheme['metallic']) < 1e-7
    for key, parts in actual.items():
        for p, old in zip(parts, native[key]):
            for field in ['normal_texture', 'transmission', 'transmission_texture', 'transmission_roughness', 'ior']:
                assert p[field] == old[field], ('Preserved field changed', key, field)
    return actual


def capture(env, prefix):
    frames = {k: v['rgb'].detach().cpu().numpy().copy()
              for k, v in env.unwrapped.get_obs()['sensor_data'].items()}
    frames['human'] = env.render().detach().cpu().numpy().copy()
    for name, array in frames.items():
        for i, image in enumerate(array): Image.fromarray(image[..., :3]).save(OUT / f'{prefix}_{name}_{i}.png')
    return frames


def cfg(scheme='original', seed=91):
    return {'seed': seed, 'manifest_ref': 'manifest.json', 'config_ref': 'check_cabinet_remaining',
            'appearance': {'enabled': True, 'mode': 'explicit', 'scheme_id': scheme},
            'initial_pose': {'enabled': False}}


def make(task, config):
    return gym.make(f'CabinetPouring{task}-Sharpa-v1', num_envs=TASKS[task][0], sim_backend='physx_cuda',
                    obs_mode='rgb', render_mode='rgb_array', reconfiguration_freq=0,
                    **({} if config is None else {'variation': config}))


def engineering(env, task, row):
    e = env.unwrapped
    before, chosen = materials(e), list(e._variation.schemes)
    mask = torch.zeros(e.num_envs, dtype=torch.bool, device=e.device); mask[-1] = True
    if e.bottle_stage_twins:
        if task in ['PickBottle', 'Long']: e._swap_to_fixed_bottle(mask)
        assert int(e._active_bottle_rep[-1]) == 1
        e._cap_detached[-1] = True; e._swap_in_twin(e.num_envs - 1)
        e._flush_bottle_representation_state()
        assert bool(e._cap_free[-1])
        capture(env, f'{task}_ENGINEERING_free_cap')
        assert materials(e) == before
        e._swap_to_open_bottle(mask); e._flush_bottle_representation_state()
        assert int(e._active_bottle_rep[-1]) == 2
        capture(env, f'{task}_ENGINEERING_open_bottle')
    elif e.cap_articulated:
        # Follow the actual native mode; never force a different representation.
        e._cap_detached[0] = True; e._swap_in_twin(0)
        e._flush_bottle_representation_state()
        assert bool(e._cap_free[0])
        capture(env, f'{task}_ENGINEERING_native_free_cap')
    else:
        raise AssertionError('Expected native engineering switch absent; do not substitute another task mode')
    assert materials(e) == before and e._variation.schemes == chosen
    row['engineering'] = {'status': 'passed', 'robot_success': False,
                          'native_stage_twins': e.bottle_stage_twins, 'artificial_trigger': True}


manifest_files = [p for p in (ROOT / 'tasks/cabinet_pouring').glob('*.py')]
manifest_files += [ROOT / 'tasks/assets/variation/cabinet_pouring/v1/catalog.json', Path(__file__)]
from tasks.cabinet_pouring.cabinet_pouring_long import TASK_ASSET_DIR
manifest = {'git_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
    'files': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in manifest_files},
    'asset_files': {str(p.relative_to(TASK_ASSET_DIR)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in TASK_ASSET_DIR.rglob('*') if p.is_file()},
    'versions': {x: importlib.metadata.version(x) for x in ['torch', 'sapien', 'mani_skill', 'numpy', 'gymnasium']},
    'job_id': os.environ['SLURM_JOB_ID'], 'backend': 'physx_cuda', 'catalog_version': catalog['version']}
dump(OUT / 'manifest.json', manifest)
env = None
started = time.monotonic()
try:
    for task, (n, loaded) in TASKS.items():
        row = {'status': 'started', 'objects': {k: 'pending' if k in loaded else 'not_applicable'
               for k in ['cabinet', 'bowl', 'beads']}, 'checks': {}}
        results['tasks'][task] = row
        env = make(task, None); env.reset(seed=71); e = env.unwrapped
        native, state, phys = materials(e), snapshot(e), physical(e)
        dump(OUT / f'{task}_native_materials.json', native)
        dump(OUT / f'{task}_native_physical.json', phys)
        dump(OUT / f'{task}_native_state.json', state)
        assert len(getattr(e, 'particles', [])) == (e.num_particles if e.has_bottle else 0)
        env.close(); env = None
        env = make(task, cfg()); e = env.unwrapped
        for scheme in SCHEMES + ['ocean', 'original']:
            env.reset(seed=71, options={'variation': {'appearance': {'scheme_id': scheme}}})
            dump(OUT / f'{task}_current_materials.json', materials(e))
            dump(OUT / f'{task}_current_state.json', snapshot(e))
            actual = verify(e, [scheme] * n, native)
            assert physical(e) == phys and snapshot(e) == state, 'Geometry/physics/initial-state mismatch'
            if scheme == 'original': assert actual == native
            row['checks'][scheme] = {'status': 'passed', 'materials': actual}
            capture(env, f'{task}_{scheme}')
        row['checks']['candidate_to_original'] = 'passed'
        if n == 2:
            env.reset(seed=71, options={'variation': {'per_env': {'0': {'appearance': {'scheme_id': 'ocean'}},
                     '1': {'appearance': {'scheme_id': 'citrus'}}}}})
            for turn, scheme in enumerate(['violet', 'original']):
                before_state, before_mat = snapshot(e), materials(e)
                rng = [copy.deepcopy(e._variation.rng[k][0].bit_generator.state) for k in [0, 1]]
                records = [copy.deepcopy(x) for x in e._variation.records if x['env_idx'] == 0]
                images = capture(env, f'{task}_local{turn}_before')
                env.reset(options={'env_idx': torch.tensor([1], device=e.device), 'variation':
                    {'per_env': {'1': {'appearance': {'scheme_id': scheme}}}}})
                dump(OUT / f'{task}_local{turn}_actual_materials.json', materials(e))
                dump(OUT / f'{task}_local{turn}_actual_state.json', snapshot(e))
                actual = verify(e, ['ocean', scheme], native)
                unselected(before_state, snapshot(e), n)
                assert {k: v for k, v in before_mat.items() if k.endswith('/0')} == {k: v for k, v in actual.items() if k.endswith('/0')}
                assert rng == [e._variation.rng[k][0].bit_generator.state for k in [0, 1]]
                assert records == [x for x in e._variation.records if x['env_idx'] == 0]
                after = capture(env, f'{task}_local{turn}_after')
                pixels = {k: int(np.count_nonzero(v[0] != after[k][0])) for k, v in images.items()}
                assert not any(pixels.values()), pixels
                row['checks'][f'local_{turn}'] = {'status': 'passed', 'selected': [1], 'scheme': scheme, 'env0_pixels': pixels}
            assert physical(e) == phys
        if task in ['PickBottle', 'UnscrewCap', 'Long']:
            env.reset(seed=71, options={'variation': {'appearance': {'scheme_id': 'violet'},
                      'per_env': {str(i): {'appearance': {'scheme_id': 'violet'}} for i in range(n)}}})
            verify(e, ['violet'] * n, native)
            engineering(env, task, row)
        dump(OUT / f'{task}_episodes.json', e._variation.records)
        env.close(); env = None
        sequences = []
        for repeat in range(2):
            config = cfg(); config['appearance'] = {'enabled': True, 'mode': 'random_choice', 'scheme_ids': SCHEMES}
            env = make(task, config); e = env.unwrapped; seq = []
            for idx in [None, [n - 1], list(range(n))]:
                env.reset(seed=71 if idx is None else None,
                          options={} if idx is None else {'env_idx': torch.tensor(idx, device=e.device)})
                ids = list(e._variation.schemes); verify(e, ids, native)
                assert all(x['appearance'] == ids[x['env_idx']] for x in e._variation.records[-(n if idx is None else len(idx)):])
                records = copy.deepcopy(e._variation.records); capture(env, f'{task}_random_{repeat}_{len(seq)}')
                assert records == e._variation.records
                seq.append(ids)
            sequences.append(seq); env.close(); env = None
        assert sequences[0] == sequences[1]
        row['checks']['random_reproducibility'] = sequences
        if task in ['PickBottle', 'UnscrewCap']:
            config = cfg('ocean'); config['initial_pose'] = {'enabled': True, 'mode': 'fixed',
                'region_id': 'cabinet_pouring.bottle_table.xy_v2', 'xy_m': [-.25, -.35]}
            env = make(task, config); env.reset(seed=71); e = env.unwrapped
            assert e.place_center_xy == (-.25, -.35)
            if task == 'UnscrewCap': np.testing.assert_allclose(e._source_pose().p[:, :2].cpu(), [[-.25, -.35]] * n, atol=1e-7)
            else: assert not np.allclose(e._source_pose().p[:, :2].cpu(), [-.25, -.35]), 'Cabinet spawn was moved'
            old = snapshot(e); image = capture(env, f'{task}_xy_before')
            rng = copy.deepcopy(e._variation.rng[1][0].bit_generator.state)
            env.reset(options={'env_idx': torch.tensor([1], device=e.device)})
            unselected(old, snapshot(e), n); after = capture(env, f'{task}_xy_after')
            assert all(np.array_equal(image[k][0], after[k][0]) for k in image)
            assert rng == e._variation.rng[1][0].bit_generator.state
            row['checks']['xy_v2_legal_point_regression'] = 'passed'
            env.close(); env = None
        row['objects'] = {k: 'passed' if k in loaded else 'not_applicable' for k in row['objects']}
        row['status'] = 'passed'; dump(OUT / 'results.json', results)
    results['status'] = 'passed'
except Exception:
    results.update(status='failed', failure=traceback.format_exc())
    if 'row' in globals(): row['status'] = 'failed'
finally:
    if env is not None: env.close()
    for task, (_, loaded) in TASKS.items():
        results['tasks'].setdefault(task, {'status': 'not_run', 'objects':
            {k: 'not_run' if k in loaded else 'not_applicable' for k in ['cabinet', 'bowl', 'beads']}})
    results['elapsed_seconds'] = time.monotonic() - started
    dump(OUT / 'results.json', results)
    print(json.dumps({'status': results['status'], 'tasks': {k: v['status'] for k, v in results['tasks'].items()}}))
if results['status'] != 'passed': sys.exit(1)
