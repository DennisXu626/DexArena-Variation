"""Short Charger A4/A5 check; --static needs no simulator or GPU.

Runtime checks require separately approved single-GPU allocation. No physics
steps, training, new cameras, geometry edits or constructed task success.
"""
import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
BOB_HEAD = '5185f1dd61f2de88ab7d4ada7a2ef77f01e6b207'
FILES = ['tasks/drawer_plug/' + n for n in ['drawer_plug_long.py', 'drawer_plug_pick_charger.py',
                                         'drawer_plug_insert_plug.py', 'charger_appearance.py']]
CATALOG = ROOT / 'tasks/assets/variation/drawer_plug/v1/catalog.json'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--static', action='store_true')
parser.add_argument('--output', type=Path)
args = parser.parse_args()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if args.static:
    for file in FILES:
        ast.parse((ROOT / file).read_text(encoding='utf-8'))
    # Verify all existing methods except the three documented hook locations.
    # This includes every success predicate, robot reset and physics builder.
    for file in FILES[:3]:
        original = subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(),
                                           '-C', str(ROOT), 'show', BOB_HEAD + ':' + file], text=True, encoding='utf-8')
        old = ast.parse(original)
        new = ast.parse((ROOT / file).read_text(encoding='utf-8'))
        methods = lambda tree: {n.name: ast.dump(n, include_attributes=False)
                                for cls in tree.body if isinstance(cls, ast.ClassDef)
                                for n in cls.body if isinstance(n, ast.FunctionDef)}
        before, after = methods(old), methods(new)
        allowed = {'__init__', '_load_charger'} if file.endswith('drawer_plug_long.py') else {'_initialize_episode'}
        assert set(before) == set(after)
        assert all(before[k] == after[k] for k in before if k not in allowed), file
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    assert set(catalog['schemes']) == {'original', 'ivory_matte', 'navy_satin', 'copper_metal'}
    for file in (ROOT / 'examples/variation/drawer_plug').glob('*.json'):
        json.loads(file.read_text(encoding='utf-8'))
    print(json.dumps({'status': 'passed', 'scope': 'AST/JSON only; A4/A5 runtime not tested',
                      'bob_head': BOB_HEAD, 'success_and_other_existing_methods': 'unchanged'}))
    sys.exit(0)

if args.output is None:
    parser.error('--output is required for runtime checks')
args.output.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(ROOT))
import gymnasium as gym
import numpy as np
import sapien
import torch
from PIL import Image
import tasks

catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
results = []
manifest = {'bob_head': BOB_HEAD, 'physics_steps': 0,
            'backend': 'physx_cuda', 'num_envs': 2, 'seed': 7,
            'python': sys.executable, 'python_version': sys.version, 'command': sys.argv,
            'job_id': os.environ.get('SLURM_JOB_ID'),
            'versions': {p: metadata.version(p) for p in ['torch', 'sapien', 'mani_skill', 'gymnasium', 'numpy']},
            'files': {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FILES + [str(CATALOG.relative_to(ROOT))]}}
dump(args.output / 'manifest.json', manifest)


def plain(value):
    if torch.is_tensor(value): return value.detach().cpu().tolist()
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, dict): return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [plain(v) for v in value]
    return value


def leaves(value, prefix=''):
    if isinstance(value, dict):
        return {p: v for k, x in value.items() for p, v in leaves(x, prefix + '/' + k).items()}
    return {prefix: value}


def snapshot(e):
    return {p: v.detach().cpu().clone() for p, v in leaves(
        {'state': e.get_state_dict(), 'elapsed_steps': e._elapsed_steps}).items() if torch.is_tensor(v)}


def state_changes(a, b, indices=None):
    assert set(a) == set(b)
    return [p for p in a if not torch.equal(a[p] if indices is None else a[p][indices],
                                            b[p] if indices is None else b[p][indices])]


def groups(e):
    output = []
    for entity in e.charger._objs:
        body = entity.find_component_by_type(sapien.render.RenderBodyComponent)
        row = {'body': [], 'prongs': []}
        for shape in body.render_shapes:
            if np.allclose(shape.half_size, e.charger_half): role = 'body'
            elif np.allclose(shape.half_size, e.charger_prong_half): role = 'prongs'
            else: raise ValueError('Unexpected Charger geometry')
            row[role].extend(part.material for part in shape.parts)
        assert [len(row['body']), len(row['prongs'])] == [1, 2]
        output.append(row)
    return output


def materials(e):
    return [{role: [{k: plain(getattr(m, k)) for k in ['base_color', 'roughness', 'metallic']}
                    for m in mats] for role, mats in row.items()} for row in groups(e)]


def verify_materials(e, ids):
    for row, name in zip(materials(e), ids):
        for role, mats in row.items():
            params = catalog['schemes'][name]['body'] if role == 'body' else catalog['prongs']
            for mat in mats:
                for key, value in params.items(): np.testing.assert_allclose(mat[key], value, rtol=0, atol=1e-7)


def physical(e):
    rows = []
    for entity in e.charger._objs:
        c = entity.find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)
        collision = [{'half_size': plain(s.half_size), 'pose_p': plain(s.local_pose.p),
                      'pose_q': plain(s.local_pose.q), 'groups': list(s.get_collision_groups()),
                      'contact_offset': s.contact_offset, 'rest_offset': s.rest_offset,
                      'material': [s.physical_material.static_friction, s.physical_material.dynamic_friction,
                                   s.physical_material.restitution]} for s in c.get_collision_shapes()]
        body = entity.find_component_by_type(sapien.render.RenderBodyComponent)
        visual = [{'half_size': plain(s.half_size), 'pose_p': plain(s.local_pose.p), 'pose_q': plain(s.local_pose.q),
                   'meshes': [hashlib.sha256(np.asarray(p.vertices).tobytes() + np.asarray(p.triangles).tobytes()
                                            + np.asarray(p.get_vertex_uv()).tobytes()).hexdigest() for p in s.parts]}
                  for s in body.render_shapes]
        rows.append({'mass': c.mass, 'inertia': plain(c.inertia), 'cmass_p': plain(c.cmass_local_pose.p),
                     'cmass_q': plain(c.cmass_local_pose.q), 'collision': collision, 'visual': visual})
    return rows


def capture(env):
    obs = env.unwrapped.get_obs()['sensor_data']
    images = {name: value['rgb'].detach().cpu().numpy().copy() for name, value in obs.items()}
    images['human'] = env.render().detach().cpu().numpy().copy()
    return images


def make(task, config=None):
    kwargs = {} if config is None else {'charger_appearance': config}
    return gym.make(f'DrawerPlug{task}-Sharpa-v1', num_envs=2, sim_backend='physx_cuda',
                    reconfiguration_freq=0, obs_mode='rgb', render_mode='rgb_array', **kwargs)


for task in ['PickCharger', 'InsertPlug']:
    current = {'task': task, 'checks': {}, 'status': 'running'}
    results.append(current)
    env = None
    try:
        started = time.monotonic()
        env = make(task)
        env.reset(seed=7)
        e = env.unwrapped
        assert e._charger_appearance is None
        verify_materials(e, ['original'] * 2)
        baseline_state, baseline_physics, baseline_info = snapshot(e), physical(e), plain(e.get_info())
        torch.save(baseline_state, args.output / f'{task}_native.pt')
        dump(args.output / f'{task}_native_physical.json', baseline_physics)
        current['checks']['default_native'] = 'passed'
        dump(args.output / f'{task}_native_info.json', baseline_info)
        env.close(); env = None
        fixed = []
        for name in catalog['schemes']:
            env = make(task, {'enabled': True, 'scheme_id': name, 'seed': 71})
            env.reset(seed=7); e = env.unwrapped
            current['active_scheme'] = name
            dump(args.output / f'{task}_{name}_physical.json', physical(e))
            torch.save(snapshot(e), args.output / f'{task}_{name}_state.pt')
            verify_materials(e, [name] * 2)
            assert not state_changes(baseline_state, snapshot(e))
            assert physical(e) == baseline_physics
            assert plain(e.get_info()) == baseline_info
            adapter = e._charger_appearance
            assert adapter.schemes == [name] * 2
            assert all(r['catalog_version'] == catalog['version'] for r in adapter.records)
            count = len(adapter.records)
            images = capture(env)
            for camera, rgb in images.items():
                Image.fromarray(rgb[0, ..., :3]).save(args.output / f'{task}_{name}_{camera}.png')
            capture(env)
            assert len(adapter.records) == count and adapter.schemes == [name] * 2
            fixed.append({'scheme_id': name, 'materials': materials(e), 'records': list(adapter.records),
                          'state_equal': True, 'physical_equal': True, 'initial_success_info_equal': True})
            env.close(); env = None
        current['checks']['fixed_and_physical'] = fixed
        traces = []
        for repeat in range(2):
            env = make(task, {'enabled': True, 'seed': 71, 'mode': 'random_choice',
                             'scheme_ids': ['ivory_matte', 'navy_satin', 'copper_metal']})
            trace = []
            for index in [None, [1], [0, 1], [1], [0]]:
                options = {} if index is None else {'env_idx': torch.tensor(index, device=env.unwrapped.device)}
                env.reset(seed=7 if index is None else None, options=options)
                e = env.unwrapped
                ids = list(e._charger_appearance.schemes)
                assert all(x in ['ivory_matte', 'navy_satin', 'copper_metal'] for x in ids)
                verify_materials(e, ids)
                trace.append(ids)
            traces.append(trace)
            env.close(); env = None
        assert traces[0] == traces[1]
        current['checks']['random_reproducibility'] = traces
        env = make(task, {'enabled': True, 'seed': 71, 'scheme_id': 'ivory_matte',
                          'per_env': {'1': {'scheme_id': 'navy_satin'}}})
        env.reset(seed=7); e = env.unwrapped
        verify_materials(e, ['ivory_matte', 'navy_satin'])
        before_images = capture(env)
        before, before_mat = snapshot(e), materials(e)
        before_records = list(e._charger_appearance.records)
        before_physical = physical(e)
        env.reset(options={'env_idx': torch.tensor([1], device=e.device),
                           'charger_appearance': {'per_env': {'1': {'scheme_id': 'copper_metal'}}}})
        after_images = capture(env)
        after, after_mat = snapshot(e), materials(e)
        torch.save({'before': before, 'after': after}, args.output / f'{task}_a5_state.pt')
        for camera in before_images:
            for i in [0, 1]:
                pair = np.concatenate([before_images[camera][i], after_images[camera][i]], axis=1)
                Image.fromarray(pair[..., :3]).save(args.output / f'{task}_a5_{camera}_env{i}.png')
        dump(args.output / f'{task}_a5_raw.json', {'before_materials': before_mat, 'after_materials': after_mat,
                                                  'before_records': before_records, 'after_records': e._charger_appearance.records})
        verify_materials(e, ['ivory_matte', 'copper_metal'])
        assert e._charger_appearance.schemes == ['ivory_matte', 'copper_metal']
        records = e._charger_appearance.records
        assert [r for r in records if r['env_idx'] == 0] == [r for r in before_records if r['env_idx'] == 0]
        assert records[-1]['env_idx'] == 1 and records[-1]['scheme_id'] == 'copper_metal'
        assert before_mat[0] == after_mat[0] and physical(e) == before_physical
        changes = state_changes(before, after, [0])
        pixels = {k: int(np.count_nonzero(before_images[k][0] != after_images[k][0])) for k in before_images}
        assert not changes and not any(pixels.values()), (changes, pixels)
        current['checks']['A5'] = {'status': 'passed', 'selected': [1], 'physics_steps': 0,
                                   'unselected_state_changes': changes, 'unselected_pixel_changes': pixels,
                                   'before_materials': before_mat, 'after_materials': after_mat,
                                   'before_records': before_records, 'after_records': records,
                                   'rgb_shapes': {k: list(v.shape) for k, v in after_images.items()}}
        current.update(status='passed', elapsed_seconds=time.monotonic() - started)
    except Exception:
        current.update(status='failed', error=traceback.format_exc())
    finally:
        if env is not None: env.close()
        dump(args.output / 'results.json', results)
        print(json.dumps({'task': task, 'status': current['status'], 'checks': list(current['checks'])}), flush=True)
    if current['status'] != 'passed': sys.exit(1)
manifest['gpu_memory'] = subprocess.run(['nvidia-smi', '--query-gpu=index,memory.used,memory.total',
                                         '--format=csv,noheader'], capture_output=True, text=True).stdout
dump(args.output / 'manifest.json', manifest)
