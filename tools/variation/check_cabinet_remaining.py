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
parser.add_argument('--visual-evidence', action='store_true', help='Single-variable texture probes and independent bead scene')
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
assert (approval.get('max_GPU_seconds'), approval.get('max_jobs')) in [(600, 1), (300, 2), (300, 3), (300, 4), (300, 5)]
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


def texture_signature(texture, cache):
    if texture is None:
        return None
    for previous, signature in cache:
        if texture == previous:
            return signature
    pixels = texture.download()
    signature = {'pixels_sha256': hashlib.sha256(pixels.tobytes()).hexdigest(),
                 'shape': list(pixels.shape), 'dtype': str(pixels.dtype)}
    cache.append((texture, signature))
    return signature


def materials(e):
    data = {}
    texture_cache = []
    for name, i, raw in entries(e):
        render = body(raw)
        if render is None: continue
        values = []
        for shape in render.render_shapes:
            for part in shape.parts:
                m = part.material
                values.append({k: plain(getattr(m, k)) for k in ['base_color', 'roughness', 'metallic',
                              'specular', 'transmission', 'transmission_roughness', 'ior', 'emission']})
                if name.startswith('cabinet:') and Path(getattr(shape, 'filename', '')).name == 'original-36.obj':
                    values[-1]['protected_handle'] = True
                for k in ['base_color_texture', 'roughness_texture', 'metallic_texture',
                          'normal_texture', 'transmission_texture', 'emission_texture']:
                    texture = getattr(m, k)
                    values[-1][k] = (texture_signature(texture, texture_cache)
                                    if k == 'base_color_texture' and (name.startswith('cabinet:') or name == 'bowl')
                                    else None if texture is None else str(texture.filename))
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
    if e.has_cabinet:
        for i in range(e.num_envs):
            assert any(p.get('protected_handle') for p in actual[f'cabinet:link_0/{i}']), 'Cabinet handle mapping absent'
    texture_cache = []
    owners = []
    assert sum(len(v) for v in actual.values()) == sum(len(v) for v in a._bindings), 'Unbound render parts'
    for i, bindings in enumerate(a._bindings):
        scheme = catalog['schemes'][ids[i]]
        for b in bindings:
            m, original, role = b['material'], b['original'], b['role']
            new_object = role in ['cabinet', 'cabinet_detail', 'bowl', 'beads']
            params = scheme.get('objects', {}).get(role) if new_object else None
            if 'live_texture' in b:
                live = b['live_texture']['texture']
                assert m.base_color_texture == live, 'Live texture binding replaced'
                assert not any(live == previous and i != owner for previous, owner in owners), 'Shared mutable texture across environments'
                owners.append((live, i))
                expected_texture = original['base_color_texture']
                if params is not None and 'texture_files' in params:
                    filename = params['texture_files'][Path(expected_texture.filename).name]
                    expected_texture = a._textures[str(ROOT / 'tasks/assets/variation/cabinet_pouring/v1' / filename)]
                assert texture_signature(live, texture_cache) == texture_signature(expected_texture, texture_cache), 'Uploaded texture pixels differ from source'
            if ids[i] == 'original' or (new_object and params is None):
                for k, expected in original.items():
                    if k == 'base_color_texture' and 'live_texture' in b: continue
                    if k == 'base_color': np.testing.assert_array_equal(m.base_color, expected)
                    else: assert getattr(m, k) == expected
            elif new_object:
                expected = list(params['base_color']); expected[3] = float(original['base_color'][3])
                np.testing.assert_allclose(m.base_color, expected, rtol=0, atol=1e-7)
                if original['base_color_texture'] is not None and 'texture_files' in params:
                    assert 'live_texture' in b
                else:
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
            if p.get('protected_handle'):
                assert p == old, ('Cabinet handle appearance changed', key)
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


def visual_evidence():
    """Diagnostic instances only. Never modify normal task poses or cameras."""
    diagnostic = {'surface_probes': {}, 'independent_beads': {}, 'robot_success': False}
    dump(OUT / 'visual_evidence.json', diagnostic)
    # Fixed object-only crops for the native 1280x720 human camera and seed 71.
    # Unlike a whole-frame difference, these exclude the independently tinted bottle.
    for task, role, box in [('OpenCabinet', 'cabinet', (625, 185, 760, 370)),
                            ('PourBeads', 'bowl', (690, 392, 755, 435))]:
        row = {'status': 'started', 'ROI_xyxy': box, 'fresh': {}, 'switches': {}}
        diagnostic['surface_probes'][task] = row
        def roi(frame):
            x0, y0, x1, y1 = box
            return frame['human'][0, y0:y1, x0:x1, :3].astype(np.int16)
        # Compare valid texture-to-texture paths. Removing a texture at runtime
        # tests a different renderer transition and is not a visibility oracle.
        fresh = {}
        for scheme in ['original', 'ocean', 'citrus']:
            first = gym.make(f'CabinetPouring{task}-Sharpa-v1', num_envs=1, sim_backend='physx_cuda',
                             obs_mode='rgb', render_mode='rgb_array', reconfiguration_freq=0,
                             variation=cfg(scheme))
            try:
                first.reset(seed=71)
                fresh[scheme] = roi(capture(first, f'DIAGNOSTIC_{task}_fresh_{scheme}'))
                row['fresh'][scheme] = {'mean_rgb': fresh[scheme].mean(axis=(0, 1)).tolist()}
            finally:
                first.close()
        for scheme in ['ocean', 'citrus']:
            delta = np.abs(fresh[scheme] - fresh['original'])
            count = int(np.count_nonzero(np.any(delta > 15, axis=-1)))
            row['fresh'][scheme]['changed_pixels_gt15'] = count
            dump(OUT / 'visual_evidence.json', diagnostic)
            assert count >= (100 if role == 'cabinet' else 20), ('Fresh object texture not visible', task, scheme, count)
        probe = gym.make(f'CabinetPouring{task}-Sharpa-v1', num_envs=1, sim_backend='physx_cuda',
                         obs_mode='rgb', render_mode='rgb_array', reconfiguration_freq=0, variation=cfg())
        try:
            probe.reset(seed=71); e = probe.unwrapped
            native = materials(e)
            for scheme in ['original', 'ocean', 'citrus', 'original', 'violet']:
                probe.reset(seed=71, options={'variation': {'appearance': {'scheme_id': scheme}}})
                verify(e, [scheme], native)
                current = roi(capture(probe, f'DIAGNOSTIC_{task}_switch_{scheme}'))
                expected = fresh['original' if scheme == 'violet' else scheme]
                delta = np.abs(current - expected)
                row['switches'][scheme] = {'max_channel_difference_from_fresh': int(delta.max()),
                                           'mean_difference_from_fresh': float(delta.mean())}
                dump(OUT / 'visual_evidence.json', diagnostic)
                assert delta.max() <= 3, ('Runtime texture switch differs from fresh instance', task, scheme, row['switches'][scheme])
            row['status'] = 'passed'
            dump(OUT / 'visual_evidence.json', diagnostic)
        finally:
            probe.close()

    import sapien
    from mani_skill.utils import sapien_utils
    from mani_skill.utils.structs import Pose
    # A separate diagnostic instance reuses native build_sphere + Actor.merge +
    # PilotVariation. The bottle stays outside this close camera's field of view.
    beads = gym.make('CabinetPouringUnscrewCap-Sharpa-v1', num_envs=2, sim_backend='physx_cuda',
                     obs_mode='rgb', render_mode='rgb_array', reconfiguration_freq=0, variation=cfg(),
                     human_render_camera_configs={'width': 512, 'height': 512, 'fov': .65,
                         'pose': sapien_utils.look_at([1, .90, .60], [1, 1, .50])})
    try:
        e = beads.unwrapped
        def place(indices):
            for j, particle in enumerate(e.particles):
                p = particle.pose.p.clone()
                p[indices] = torch.tensor([1 + (j % 4 - 1.5) * .018, 1 + (j // 4 - 1.5) * .018, .50], device=e.device)
                particle.set_pose(Pose.create_from_pq(p=p, q=particle.pose.q))
            e.scene.px.gpu_apply_rigid_dynamic_data(); e.scene._gpu_fetch_all()
        def frame(prefix):
            from PIL import ImageDraw
            a = beads.render().detach().cpu().numpy().copy()
            for i, image in enumerate(a):
                im = Image.fromarray(image[..., :3]); draw = ImageDraw.Draw(im)
                draw.rectangle((0, 0, 511, 18), fill='black')
                draw.text((4, 3), 'INDEPENDENT BEAD DIAGNOSTIC - NOT TASK INITIAL STATE', fill='white')
                im.save(OUT / f'INDEPENDENT_BEADS_{prefix}_{i}.png')
            return a
        def color_count(image, scheme):
            r,g,b = np.moveaxis(image[..., :3].astype(np.int16), -1, 0)
            color = {'original': (b > r + 20) & (b > g + 10),
                     'ocean': (r > g + 20) & (g > b + 10),
                     'citrus': (r > g + 20) & (b > g + 20),
                     'violet': (b > r + 20) & (b > g + 10)}[scheme]
            # Count only projected particle interiors, never arbitrary background.
            eye = np.array([1., .90, .60]); target = np.array([1., 1., .50])
            forward = target - eye; forward /= np.linalg.norm(forward)
            left = np.cross([0., 0., 1.], forward); left /= np.linalg.norm(left)
            up = np.cross(forward, left)
            yy, xx = np.mgrid[:image.shape[0], :image.shape[1]]
            focal = image.shape[0] / (2 * np.tan(.65 / 2))
            mask = np.zeros(xx.shape, dtype=bool)
            for j in range(len(e.particles)):
                v = np.array([1 + (j % 4 - 1.5) * .018, 1 + (j // 4 - 1.5) * .018, .50]) - eye
                depth = v @ forward
                cx = image.shape[1] / 2 - focal * (v @ left) / depth
                cy = image.shape[0] / 2 - focal * (v @ up) / depth
                radius = .65 * focal * e.particle_radius / depth
                mask |= (xx-cx)**2 + (yy-cy)**2 < radius**2
            return int(np.count_nonzero(color & mask))
        native = None; baseline = None
        for scheme in ['original', 'ocean', 'citrus', 'original', 'violet']:
            beads.reset(seed=71, options={'variation': {'appearance': {'scheme_id': scheme}}}); place([0, 1])
            if native is None: native = materials(e)
            verify(e, [scheme] * 2, native); images = frame(scheme)
            counts = [color_count(image, scheme) for image in images]
            assert min(counts) >= 100, ('Bead color not visually resolved', scheme, counts)
            if baseline is None: baseline = images.copy()
            if scheme in ['original', 'violet']: assert np.array_equal(images, baseline), 'Independent bead native restoration differs'
            diagnostic['independent_beads'][scheme] = {'status': 'passed', 'color_pixels': counts}
        beads.reset(seed=71, options={'variation': {'per_env': {'0': {'appearance': {'scheme_id': 'ocean'}}, '1': {'appearance': {'scheme_id': 'citrus'}}}}}); place([0, 1])
        for turn, scheme in enumerate(['original', 'ocean']):
            before, old_mat = snapshot(e), materials(e)
            rng = [copy.deepcopy(e._variation.rng[k][0].bit_generator.state) for k in [0, 1]]
            records = copy.deepcopy([x for x in e._variation.records if x['env_idx'] == 0])
            images = frame(f'local{turn}_before')
            beads.reset(options={'env_idx': torch.tensor([1], device=e.device), 'variation': {'per_env': {'1': {'appearance': {'scheme_id': scheme}}}}}); place([1])
            after = frame(f'local{turn}_after'); unselected(before, snapshot(e), 2)
            assert {k:v for k,v in old_mat.items() if k.endswith('/0')} == {k:v for k,v in materials(e).items() if k.endswith('/0')}
            assert rng == [e._variation.rng[k][0].bit_generator.state for k in [0, 1]]
            assert records == [x for x in e._variation.records if x['env_idx'] == 0]
            assert np.array_equal(images[0], after[0]) and not np.array_equal(images[1], after[1])
            assert color_count(after[1], scheme) >= 100
            verify(e, ['ocean', scheme], native)
            diagnostic['independent_beads'][f'local_{turn}'] = {'status': 'passed', 'env0_pixels': 0,
                'env1_changed_channels': int(np.count_nonzero(images[1] != after[1])), 'scheme': scheme}
        diagnostic['independent_beads']['geometry'] = {'radius_m': e.particle_radius, 'count_per_env': len(e.particles), 'user_steps': 0}
        diagnostic['status'] = 'passed'; dump(OUT / 'visual_evidence.json', diagnostic)
    finally:
        beads.close()


manifest_files = [p for p in (ROOT / 'tasks/cabinet_pouring').glob('*.py')]
manifest_files += [ROOT / 'tasks/assets/variation/cabinet_pouring/v1/catalog.json', Path(__file__)]
manifest_files += [p for p in (ROOT / 'tasks/assets/variation/cabinet_pouring/v1').rglob('*')
                   if p.is_file() and p.suffix in {'.png', '.json'} and p not in manifest_files]
manifest_files += [ROOT / 'tools/variation/make_cabinet_tints.py']
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
    if args.visual_evidence:
        visual_evidence()
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
        original_frames = None
        for scheme in SCHEMES + ['ocean', 'original']:
            env.reset(seed=71, options={'variation': {'appearance': {'scheme_id': scheme}}})
            dump(OUT / f'{task}_current_materials.json', materials(e))
            dump(OUT / f'{task}_current_state.json', snapshot(e))
            actual = verify(e, [scheme] * n, native)
            assert physical(e) == phys and snapshot(e) == state, 'Geometry/physics/initial-state mismatch'
            if scheme == 'original': assert actual == native
            row['checks'][scheme] = {'status': 'passed', 'materials': actual}
            frames = capture(env, f'{task}_{scheme}')
            if original_frames is None: original_frames = frames
            if args.visual_evidence and scheme in ['ocean', 'citrus']:
                rois = {'cabinet': (82, 38, 158, 150), 'bowl': (171, 176, 198, 199)}
                for role in loaded & rois.keys():
                    x0,y0,x1,y1 = rois[role]
                    delta = np.abs(frames['base_camera'][0,y0:y1,x0:x1,:3].astype(np.int16) -
                                   original_frames['base_camera'][0,y0:y1,x0:x1,:3].astype(np.int16))
                    changed = int(np.count_nonzero(np.any(delta > 10, axis=-1)))
                    assert changed > 20 and delta.mean() > 3, ('Native object RGB change too small', task, role, scheme)
                    row['checks'][scheme].setdefault('native_object_RGB', {})[role] = {
                        'ROI_xyxy': [x0,y0,x1,y1], 'pixels_delta_gt_10': changed, 'mean_channel_delta': float(delta.mean()),
                        'note': 'Object ROI evidence, final visual review also required'}
        row['checks']['candidate_to_original'] = 'passed'
        if n == 2:
            env.reset(seed=71, options={'variation': {'per_env': {'0': {'appearance': {'scheme_id': 'ocean'}},
                     '1': {'appearance': {'scheme_id': 'citrus'}}}}})
            for turn, scheme in enumerate(['violet', 'ocean']):
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
                selected_pixels = {k: int(np.count_nonzero(v[1] != after[k][1])) for k, v in images.items()}
                assert selected_pixels['human'] > 0, 'Selected environment did not visibly change'
                row['checks'][f'local_{turn}'] = {'status': 'passed', 'selected': [1], 'scheme': scheme,
                    'env0_pixels': pixels, 'env1_changed_channels': selected_pixels}
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
