"""Mouse 101408 only. --static never imports simulation; runtime needs fresh GPU approval.
No step(), training, new cameras or constructed task success. Fail once, save evidence.
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
BASE = '00a3695193680e0bfc0d37b8c77986b2fbfb8357'
TASK = 'tasks/office_desk/office_desk_click_mouse.py'
FILES = [TASK, 'tasks/office_desk/mouse_appearance.py',
         'tasks/assets/variation/office_desk/mouse_101408/v1/catalog.json']
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--static', action='store_true')
parser.add_argument('--output', type=Path)
parser.add_argument('--approved-runtime', action='store_true', help='Explicit runtime intent; does not grant resource authorization')
args = parser.parse_args()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if args.static:
    old = subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), '-C', str(ROOT),
                                   'show', BASE + ':' + TASK], text=True, encoding='utf-8')
    new = (ROOT / TASK).read_text(encoding='utf-8')
    tree = ast.parse(new)
    # Strip only the documented appearance import, argument, assignment and hooks.
    class Strip(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            return None if node.module == 'tasks.office_desk.mouse_appearance' else node
        def visit_If(self, node):
            if ast.unparse(node.test) == 'self._mouse_appearance is not None':
                return None
            return self.generic_visit(node)
        def visit_Assign(self, node):
            if any(ast.unparse(t) == 'self._mouse_appearance' for t in node.targets):
                return None
            return self.generic_visit(node)
        def visit_FunctionDef(self, node):
            if node.name == '__init__' and 'mouse_appearance' in [a.arg for a in node.args.kwonlyargs]:
                index = [a.arg for a in node.args.kwonlyargs].index('mouse_appearance')
                del node.args.kwonlyargs[index]; del node.args.kw_defaults[index]
            return self.generic_visit(node)
    assert ast.dump(Strip().visit(tree), include_attributes=False) == ast.dump(ast.parse(old), include_attributes=False)
    long_file = 'tasks/office_desk/office_desk_long.py'
    original = subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), '-C', str(ROOT),
                                        'show', BASE + ':' + long_file])
    assert original.replace(b'\r\n', b'\n') == (ROOT / long_file).read_bytes().replace(b'\r\n', b'\n')
    ast.parse((ROOT / FILES[1]).read_text(encoding='utf-8'))
    catalog = json.loads((ROOT / FILES[2]).read_text(encoding='utf-8'))
    assert set(catalog['schemes']) == {'original', 'ivory_matte', 'navy_satin'}
    for scheme, roles in catalog['schemes'].items():
        if scheme == 'original': continue
        assert set(roles) == {'shell', 'buttons', 'wheel'}
        for params in roles.values():
            assert len(params['base_color']) == 4
            assert all(0 <= v <= 1 for v in params['base_color'])
            assert 0 <= params['roughness'] <= 1 and params['metallic'] == 0
    examples = list((ROOT / 'examples/variation/office_desk/mouse_101408').glob('*.json'))
    for path in examples:
        cfg = json.loads(path.read_text(encoding='utf-8'))
        assert cfg['task_id'] == 'OfficeDeskClickMouse-Sharpa-v1'
    print(json.dumps({'status': 'passed', 'baseline': BASE, 'task_after_removing_appearance_hooks': 'AST identical',
                      'Long': 'unchanged', 'examples': len(examples), 'GPU_seconds': 0,
                      'runtime': 'NOT TESTED'}))
    sys.exit(0)

if not args.approved_runtime or args.output is None:
    parser.error('runtime requires --approved-runtime and fresh --output, plus separate resource approval')
args.output.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(ROOT))
import gymnasium as gym
import numpy as np
import sapien
import torch
from PIL import Image
import tasks

catalog = json.loads((ROOT / FILES[2]).read_text(encoding='utf-8'))
manifest = {'task_id': 'OfficeDeskClickMouse-Sharpa-v1', 'num_envs': 2, 'physics_steps': 0,
            'command': sys.argv, 'backend': 'physx_cuda', 'python': sys.version,
            'versions': {p: metadata.version(p) for p in ['torch', 'sapien', 'mani_skill', 'gymnasium', 'numpy']},
            'files': {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FILES}}
from tasks.office_desk.office_desk_click_mouse import MOUSE_ASSET_DIR
asset = MOUSE_ASSET_DIR / '101408'
manifest['git_commit'] = subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
manifest['job_id'] = os.environ.get('SLURM_JOB_ID')
manifest['asset_files'] = {p.relative_to(asset).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in [asset / 'mobility.urdf', *sorted((asset / 'textured_objs').glob('*.obj')),
                                     *sorted((asset / 'textured_objs').glob('*.mtl'))]}
dump(args.output / 'manifest.json', manifest)
results = {'status': 'running', 'checks': {}, 'physics_steps': 0}
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
        {'state': e.get_state_dict(), 'elapsed_steps': e._elapsed_steps,
         'mouse_pose': e.mouse.pose.raw_pose, 'mouse_qpos': e.mouse.get_qpos(), 'mouse_qvel': e.mouse.get_qvel(),
         **{k: getattr(e, k) for k in ['press_started', 'hold_completed', 'released_after_hold', 'success_latched',
              'hold_counter', 'release_counter', 'final_counter', 'press_success_counter', 'spawn_xy', 'spawn_yaw']}}).items() if torch.is_tensor(v)}


def state_changes(a, b, indices=None):
    assert set(a) == set(b)
    return [p for p in a if not torch.equal(a[p] if indices is None else a[p][indices],
                                            b[p] if indices is None else b[p][indices])]


def physical(e):
    rows = []
    for mouse in e._mice:
        links = []
        for name, link in mouse.links_map.items():
            for component in link._objs:
                collisions = []
                for shape in component.get_collision_shapes():
                    material = shape.physical_material
                    collisions.append({'type': type(shape).__name__,
                        'vertices': plain(shape.vertices), 'pose': [plain(shape.local_pose.p), plain(shape.local_pose.q)],
                        'groups': list(shape.get_collision_groups()),
                        'contact_offset': shape.contact_offset, 'rest_offset': shape.rest_offset,
                        'material': [material.static_friction, material.dynamic_friction, material.restitution]})
                body = component.entity.find_component_by_type(sapien.render.RenderBodyComponent)
                visuals = [] if body is None else [
                    {'pose': [plain(s.local_pose.p), plain(s.local_pose.q)], 'scale': plain(s.scale),
                     'meshes': [hashlib.sha256(np.asarray(p.vertices).tobytes() + np.asarray(p.triangles).tobytes()
                                              + np.asarray(p.get_vertex_uv()).tobytes()).hexdigest() for p in s.parts]}
                    for s in body.render_shapes]
                links.append({'name': name, 'mass': component.mass, 'inertia': plain(component.inertia),
                              'cmass': [plain(component.cmass_local_pose.p), plain(component.cmass_local_pose.q)],
                              'collisions': collisions, 'visuals': visuals})
        rows.append({'links': links, 'limits': plain(mouse.get_qlimits())})
    return rows


def materials(e):
    rows = []
    from tasks.office_desk.mouse_appearance import ROLES, FIELDS
    for mouse in e._mice:
        row = {}
        for name in ROLES:
            parts = []
            for component in mouse.links_map[name]._objs:
                body = component.entity.find_component_by_type(sapien.render.RenderBodyComponent)
                for shape in body.render_shapes:
                    parts.extend({k: plain(getattr(p.material, k)) for k in FIELDS} for p in shape.parts)
            assert parts, name
            row[name] = parts
        rows.append(row)
    return rows


def verify(e, ids, native):
    from tasks.office_desk.mouse_appearance import ROLES
    rows = materials(e)
    for i, name in enumerate(ids):
        for link, parts in rows[i].items():
            for j, params in enumerate(parts):
                expected = native[i][link][j] if name == 'original' else catalog['schemes'][name][ROLES[link]]
                for key in expected:
                    np.testing.assert_allclose(params[key], expected[key], rtol=0, atol=1e-7)
    assert e._mouse_appearance.schemes == ids
    assert all(r['catalog_version'] == catalog['version'] for r in e._mouse_appearance.records)


def capture(env):
    obs = env.unwrapped.get_obs()['sensor_data']
    images = {name: value['rgb'].detach().cpu().numpy().copy() for name, value in obs.items()}
    images['human'] = env.render().detach().cpu().numpy().copy()
    return images


def make(config=None):
    kwargs = {} if config is None else {'mouse_appearance': config}
    return gym.make('OfficeDeskClickMouse-Sharpa-v1', num_envs=2, sim_backend='physx_cuda',
                    reconfiguration_freq=0, obs_mode='rgb', render_mode='rgb_array', **kwargs)


env = None
started = time.monotonic()
try:
    env = make(); env.reset(seed=7); e = env.unwrapped
    assert e._mouse_appearance is None
    native, baseline, properties = materials(e), snapshot(e), physical(e)
    native_info = plain(e.get_info())
    dump(args.output / 'native_physical.json', properties)
    torch.save(baseline, args.output / 'native_state.pt')
    results['checks']['default_disabled'] = 'passed'
    env.close(); env = None
    env = make({'enabled': False}); env.reset(seed=7); e = env.unwrapped
    assert e._mouse_appearance is None
    assert not state_changes(baseline, snapshot(e)) and physical(e) == properties
    assert materials(e) == native
    results['checks']['explicit_disabled'] = 'passed'
    env.close(); env = None
    for name in catalog['schemes']:
        tick = time.monotonic()
        env = make({'enabled': True, 'scheme_id': name}); env.reset(seed=7); e = env.unwrapped
        verify(e, [name] * 2, native)
        assert not state_changes(baseline, snapshot(e))
        assert physical(e) == properties
        assert plain(e.get_info()) == native_info
        records = list(e._mouse_appearance.records)
        for camera, rgb in capture(env).items():
            for i in [0, 1]:
                Image.fromarray(rgb[i, ..., :3]).save(args.output / f'{name}_{camera}_env{i}.png')
        capture(env)
        assert records == e._mouse_appearance.records
        results['checks'][name] = {'status': 'passed', 'materials': materials(e),
                                  'records': records, 'load_reset_render_seconds': time.monotonic() - tick}
        env.close(); env = None
    traces = []
    for repeat in range(2):
        env = make({'enabled': True, 'mode': 'random_choice', 'scheme_ids': list(catalog['schemes']), 'seed': 71})
        trace = []
        for selected in [None, [1], [0, 1], [1]]:
            env.reset(seed=7 if selected is None else None,
                      options={} if selected is None else {'env_idx': torch.tensor(selected, device=env.unwrapped.device)})
            e = env.unwrapped
            ids = list(e._mouse_appearance.schemes); verify(e, ids, native); trace.append(ids)
        traces.append(trace); env.close(); env = None
    assert traces[0] == traces[1]
    results['checks']['random_reproducibility'] = traces
    env = make({'enabled': True, 'scheme_id': 'ivory_matte', 'per_env': {'1': {'scheme_id': 'navy_satin'}}})
    env.reset(seed=7); e = env.unwrapped
    verify(e, ['ivory_matte', 'navy_satin'], native)
    images, state, mats = capture(env), snapshot(e), materials(e)
    records = list(e._mouse_appearance.records)
    for round_index, name in enumerate(['original', 'ivory_matte']):
        tick = time.monotonic()
        env.reset(options={'env_idx': torch.tensor([1], device=e.device),
                           'mouse_appearance': {'per_env': {'1': {'scheme_id': name}}}})
        after_images, after, after_mats = capture(env), snapshot(e), materials(e)
        verify(e, ['ivory_matte', name], native)
        changes = state_changes(state, after, [0])
        pixels = {k: int(np.count_nonzero(images[k][0] != after_images[k][0])) for k in images}
        torch.save({'before': state, 'after': after}, args.output / f'local_{round_index}.pt')
        for camera in images:
            for i in [0, 1]:
                pair = np.concatenate([images[camera][i], after_images[camera][i]], axis=1)
                Image.fromarray(pair[..., :3]).save(args.output / f'local_{round_index}_{camera}_env{i}.png')
        row = {'selected': [1], 'scheme_id': name, 'unselected_state_changes': changes,
               'unselected_pixel_changes': pixels, 'before_materials': mats, 'after_materials': after_mats,
               'records': list(e._mouse_appearance.records), 'reset_render_seconds': time.monotonic() - tick}
        dump(args.output / f'local_{round_index}.json', row)
        assert not changes and not any(pixels.values())
        assert mats[0] == after_mats[0] and physical(e) == properties
        assert [r for r in records if r['env_idx'] == 0] == [r for r in e._mouse_appearance.records if r['env_idx'] == 0]
        results['checks'][f'local_reset_{round_index}'] = row
        images, state, mats = after_images, after, after_mats
    results['status'] = 'passed'
except Exception:
    results.update(status='failed', error=traceback.format_exc())
finally:
    if env is not None: env.close()
    results['elapsed_seconds'] = time.monotonic() - started
    try:
        import resource
        results['process_max_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        results['gpu_memory_snapshot'] = subprocess.run(
            ['nvidia-smi', '--query-gpu=index,memory.used,memory.total', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=5).stdout
    except Exception as exc:
        results['memory_probe_unavailable'] = str(exc)
    dump(args.output / 'results.json', results)
    print(json.dumps({'status': results['status'], 'checks': list(results['checks'])}))
if results['status'] != 'passed': sys.exit(1)
