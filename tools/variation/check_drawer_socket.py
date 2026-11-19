"""Drawer/socket CPU preflight and separately authorized short runtime check.

No task/simulator import on --static. Runtime requires an explicit approval
receipt and a Slurm allocation; this script never submits jobs or retries.
"""
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
BASE = '793c74798c3291155e7010a0688053c1fbe57faa'
TASKS = ['OpenDrawer', 'InsertPlug', 'PickCharger', 'Long']
TASK_SEED = 7
TASK_FILES = ['tasks/drawer_plug/drawer_plug_' + name + '.py' for name in
              ['long', 'open_drawer', 'pick_charger', 'insert_plug']]
CAT = 'tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json'
FILES = TASK_FILES + ['tasks/drawer_plug/fixture_appearance.py', CAT,
                     'tasks/drawer_plug/charger_appearance.py',
                     'tasks/assets/variation/drawer_plug/v1/catalog.json']


def strip_fixture_hooks(tree, long_task=False):
    """Remove ONLY the new opt-in visual hooks for protected AST comparison."""
    class Strip(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node.name == '__init__':
                for i, arg in enumerate(node.args.kwonlyargs):
                    if arg.arg == 'drawer_plug_appearance':
                        node.args.kwonlyargs.pop(i); node.args.kw_defaults.pop(i); break
            return self.generic_visit(node)

        def visit_Assign(self, node):
            if len(node.targets) == 1 and ast.unparse(node.targets[0]) == 'self._fixture_appearance':
                return None
            return self.generic_visit(node)

        def visit_If(self, node):
            test = ast.unparse(node.test)
            if test == 'self._fixture_appearance is not None' or test.startswith('drawer_plug_appearance and'):
                return None
            # Long receives the existing Charger finish hook; subclasses already had it.
            if (long_task and test == 'self._charger_appearance is not None'
                    and len(node.body) == 1 and isinstance(node.body[0], ast.Expr)
                    and ast.unparse(node.body[0]) == 'self._charger_appearance.finish_reset(self, env_idx, options)'):
                return None
            return self.generic_visit(node)

        def visit_Set(self, node):
            if long_task and {getattr(x, 'value', None) for x in node.elts} == {
                    'DrawerPlugPickChargerEnv', 'DrawerPlugInsertPlugEnv', 'DrawerPlugLongEnv'}:
                node.elts = [x for x in node.elts if x.value != 'DrawerPlugLongEnv']
            return node

        def visit_Constant(self, node):
            if node.value == 'Charger appearance requires PickCharger, InsertPlug or Long':
                node.value = 'Charger appearance pilot supports only PickCharger and InsertPlug'
            return node
    return ast.fix_missing_locations(Strip().visit(tree))


def static_check(asset_root=None):
    for f in TASK_FILES:
        original = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':' + f],
                                           text=True, encoding='utf-8')
        current = (ROOT / f).read_text(encoding='utf-8')
        normalized = strip_fixture_hooks(ast.parse(current), f.endswith('_long.py'))
        assert ast.dump(normalized) == ast.dump(ast.parse(original)), f
    for f in FILES:
        if f.endswith('.py'): ast.parse((ROOT / f).read_text(encoding='utf-8'))
    for f in FILES[-2:]:
        original = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':' + f])
        assert original == (ROOT / f).read_bytes(), 'Charger implementation/catalog changed'
    cat = json.loads((ROOT / CAT).read_text(encoding='utf-8'))
    assert set(cat['schemes']) == {'original', 'warm_white', 'neutral_grey'}
    assert cat['schemes']['original'] == {}
    mapping = json.loads((ROOT / 'assets/appearance/objects/drawer_plug/drawer/bindings.json').read_text(encoding='utf-8'))
    assert len(cat['drawer_mesh_roles']) == len(mapping['visuals']) == 47
    assert all(cat['drawer_mesh_roles'][Path(v['mesh']).name]['role'] == v['role'] for v in mapping['visuals'])
    assert {k for v in mapping['visuals'] for m in v['materials'] for k, _ in m['maps']} == {'map_Kd'}
    for scheme in list(cat['schemes'].values())[1:]:
        assert set(scheme['drawer']) == {'panel'} and set(scheme['socket']) == {'shell'}
        for role in [scheme['drawer']['panel'], scheme['socket']['shell']]:
            assert role['metallic'] == 0 and role['base_color'][3] == 1
    for p in (ROOT / 'examples/variation/drawer_plug/fixtures').glob('*.json'):
        json.loads(p.read_text(encoding='utf-8'))
    if asset_root:
        for name, identity in mapping['source_files'].items():
            p = asset_root / name
            assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == identity['sha256'], name
    # Small CPU check of pixel encoding/alpha; no SAPIEN module is imported.
    spec = importlib.util.spec_from_file_location('fixture_cpu', ROOT / FILES[4])
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    import numpy as np
    pixels = np.full((2, 2, 4), 255, dtype=np.uint8); pixels[0, 0, 3] = 128
    converted = module.FixtureAppearance._solid_pixels({'pixels': pixels, 'srgb': True}, [.5, 0, 1])
    assert converted[0, 0].tolist() == [188, 0, 255, 128]
    assert pixels[0, 0].tolist() == [255, 255, 255, 128]
    # Selection/record contract without renderer: empty bindings deliberately
    # cannot establish real material or RGB correctness.
    from types import SimpleNamespace
    traces=[]
    for _ in range(2):
        adapter=module.FixtureAppearance(dict(enabled=True,seed=9,mode='random_choice',
                                             scheme_ids=list(cat['schemes'])),2)
        adapter._bind=lambda env: None
        adapter.finish_reset(SimpleNamespace(),np.array([0,1]),{})
        before=copy.deepcopy(adapter.rng[0].bit_generator.state)
        env0=[r for r in adapter.records if r['env_idx']==0]
        for _ in range(5): adapter.finish_reset(SimpleNamespace(),np.array([1]),{})
        assert before==adapter.rng[0].bit_generator.state
        assert env0==[r for r in adapter.records if r['env_idx']==0]
        traces.append(adapter.records)
    assert traces[0]==traces[1]
    assert not any(x in sys.modules for x in ['tasks', 'sapien', 'torch', 'mani_skill'])
    return {'status': 'passed', 'scope': 'CPU AST/catalog/source closure/pixel encoding only',
            'baseline': BASE, 'protected_task_AST': 'identical after enumerated visual hooks',
            'charger_code_catalog': 'byte identical', 'asset_hashes_checked': bool(asset_root),
            'CPU_selection_records': 'reproducible; env0 stream/records unchanged by env1 (no material bindings)',
            'runtime_realism_A4_A5': 'not run'}


def runtime(args):
    approval = json.loads(args.approval.read_text())
    assert approval.get('approved') is True and approval.get('blockers_resolved') is True
    assert approval.get('scope') == 'drawer_socket_shortcheck'
    head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    assert approval.get('frozen_head') == head
    assert os.environ.get('SLURM_JOB_ID'), 'Run only inside separately approved allocation'
    assert args.output.resolve().is_relative_to(Path(approval['storage_root']).resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT))
    import gymnasium as gym
    import numpy as np
    import torch
    import sapien
    from PIL import Image
    import tasks
    from tasks.drawer_plug.fixture_appearance import FixtureAppearance
    from tasks.drawer_plug.drawer_plug_long import DRAWER_URDF_PATH
    import importlib.metadata as metadata
    cat = json.loads((ROOT / CAT).read_text())
    assert hashlib.sha256(DRAWER_URDF_PATH.read_bytes()).hexdigest() == cat['source_urdf_sha256']

    def plain(v):
        if torch.is_tensor(v): return v.detach().cpu().tolist()
        if isinstance(v, np.ndarray): return v.tolist()
        if isinstance(v, np.generic): return v.item()
        if isinstance(v, dict): return {str(k): plain(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)): return [plain(x) for x in v]
        return v

    def dump(name, value):
        (args.output / name).write_text(json.dumps(plain(value), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    def digest(v): return hashlib.sha256(np.asarray(v).tobytes()).hexdigest()

    def task_rng():
        # Native task samples from Torch, not from the appearance generators.
        return dict(cpu=digest(torch.get_rng_state().cpu().numpy()),
                    cuda=digest(torch.cuda.get_rng_state().cpu().numpy()))

    def entries(e):
        row = []
        for i, drawer in enumerate(getattr(e, '_drawers', [])):
            for link in drawer.get_links(): row.extend((f'drawer:{link.name}', i, raw) for raw in link._objs)
        for name in ['socket', 'charger']:
            row.extend((name, i, raw) for i, raw in enumerate(getattr(getattr(e, name, None), '_objs', [])))
        return row

    def materials(e):
        rows = {}
        for name, i, raw in entries(e):
            body = getattr(raw, 'entity', raw).find_component_by_type(sapien.render.RenderBodyComponent)
            values = []
            if body:
                for shape_index,s in enumerate(body.render_shapes):
                    for part in s.parts:
                        m = part.material
                        v = {k: plain(getattr(m, k)) for k in ['base_color', 'roughness', 'metallic', 'specular', 'transmission', 'ior', 'emission']}
                        v['role'] = (cat['drawer_mesh_roles'][Path(s.filename).name]['role'] if name.startswith('drawer:')
                                     else ('shell' if shape_index<6 else 'hole') if name=='socket' else 'charger')
                        for k in ['base_color_texture', 'normal_texture', 'roughness_texture', 'metallic_texture', 'emission_texture', 'transmission_texture']:
                            texture = getattr(m, k); v[k] = None if texture is None else digest(texture.download())
                        values.append(v)
            rows[f'{name}/{i}'] = values
        return rows

    def physical(e):
        rows = {}
        for name, i, raw in entries(e):
            entity = getattr(raw, 'entity', raw)
            c = raw if hasattr(raw, 'get_collision_shapes') else entity.find_component_by_type(sapien.physx.PhysxRigidBodyComponent)
            assert c is not None, name
            shapes = []
            for s in c.get_collision_shapes():
                geometry = {k: plain(getattr(s, k)) for k in ['radius', 'half_length', 'half_size'] if hasattr(s, k)}
                if hasattr(s, 'get_vertices'): geometry['vertices'] = digest(s.get_vertices())
                elif hasattr(s, 'vertices'): geometry['vertices'] = digest(s.vertices)
                assert geometry, type(s).__name__
                m = s.physical_material
                shapes.append(dict(geometry=geometry, pose=[plain(s.local_pose.p), plain(s.local_pose.q)],
                                   material=[m.static_friction, m.dynamic_friction, m.restitution],
                                   groups=list(s.get_collision_groups()), contact=s.contact_offset, rest=s.rest_offset))
            body = entity.find_component_by_type(sapien.render.RenderBodyComponent)
            visual = [] if body is None else [dict(vertices=digest(p.vertices), triangles=digest(p.triangles), uv=digest(p.get_vertex_uv()),
                          pose=[plain(s.local_pose.p),plain(s.local_pose.q)]) for s in body.render_shapes for p in s.parts]
            rows[f'{name}/{i}'] = dict(mass=c.mass, inertia=plain(c.inertia), collision=shapes, visual=visual,
                                      cmass=[plain(c.cmass_local_pose.p),plain(c.cmass_local_pose.q)])
        for i,d in enumerate(getattr(e,'_drawers',[])):
            rows[f'joints/{i}'] = dict(limits=plain(d.get_qlimits()), drives=[
                dict(name=j.name, stiffness=plain(j.stiffness), damping=plain(j.damping),
                     friction=plain(j.friction), force_limit=plain(j.force_limit)) for j in d.active_joints])
        return rows

    def state(e):
        result = {}
        def flatten(v, key):
            if isinstance(v, dict):
                for k,x in v.items(): flatten(x, key+'/'+k)
            elif torch.is_tensor(v): result[key] = v.detach().cpu().clone()
        flatten(e.get_state_dict(), 'state')
        for k,v in vars(e).items():
            if torch.is_tensor(v) and v.ndim and v.shape[0] == e.num_envs: flatten(v, k)
        # Joint targets/properties are inspected separately from state_dict.
        for i,d in enumerate(getattr(e,'_drawers',[])):
            for j in d.active_joints:
                result[f'joint/{i}/{j.name}/target'] = j.drive_target.detach().cpu().clone()
        return result

    def equal_state(a,b,env0=False):
        assert set(a)==set(b)
        for k in a:
            if env0 and k.startswith('joint/1/'): continue
            x,y=a[k],b[k]
            if env0 and not k.startswith('joint/'): x,y=x[:1],y[:1]
            assert torch.equal(x,y), k

    def frames(env, prefix=None, *, masks=False):
        obs=env.unwrapped.get_obs()['sensor_data']
        images={k:v['rgb'].detach().cpu().numpy().copy() for k,v in obs.items()}
        images['human']=env.render().detach().cpu().numpy().copy()
        if prefix is not None:
            for camera,rgb in images.items():
                for i in range(len(rgb)):
                    Image.fromarray(rgb[i,...,:3]).save(args.output/f'{prefix}_{camera}_env{i}.png')
        if masks:
            return images,{k:v['segmentation'].detach().cpu().numpy().copy()[...,0] for k,v in obs.items()}
        return images

    def same_rgb(first, second, idx):
        assert set(first)==set(second)
        for name in first:
            assert np.array_equal(first[name][idx],second[name][idx]), f'{name}: env{idx} RGB changed'

    def target_pixel_counts(e, first, second, segmentation, idx):
        groups={}
        for key, i, raw in entries(e):
            if i==idx and key!='charger':
                groups.setdefault(key.split(':')[0],set()).add(getattr(raw,'entity',raw).per_scene_id)
        results={}
        for obj, ids in groups.items():
            counts={}
            for name, seg in segmentation.items():
                mask=np.isin(seg[idx],list(ids))
                changed=np.any(first[name][idx,...,:3]!=second[name][idx,...,:3],axis=-1)
                counts[name]=dict(visible_pixels=int(mask.sum()),changed_pixels=int((mask & changed).sum()))
            results[obj]=counts
        return results

    def same_state_visual_probe(env, actual, labels, after, segmentation, idx):
        # Use the real writer with separate bookkeeping. Probe only selected materials at
        # the post-reset state, so changing a pose or Charger cannot explain these pixels.
        e=env.unwrapped
        probe=copy.copy(actual)
        probe.records=[]; probe.schemes=actual.schemes.copy(); probe.episodes=actual.episodes.copy()
        selected=np.array([idx])
        snapshot=state(e)
        probe.finish_reset(e, selected, {'drawer_plug_appearance':{'mode':'explicit','scheme_id':labels[0]}})
        try:
            reference=frames(env)
            counts=target_pixel_counts(e,reference,after,segmentation,idx)
        finally:
            probe.finish_reset(e, selected, {'drawer_plug_appearance':{'mode':'explicit','scheme_id':labels[1]}})
        equal_state(snapshot,state(e))
        restored=frames(env)
        for i in range(e.num_envs): same_rgb(after,restored,i)
        return counts

    def verify(e,ids):
        adapter=e._fixture_appearance
        assert adapter.schemes==ids
        for i,row in enumerate(adapter.bindings):
            for b in row:
                params=cat['schemes'][ids[i]].get(b['object'],{}).get(b['role'])
                for k in ['base_color','roughness','metallic']:
                    target=(params or b['native'])[k]
                    np.testing.assert_allclose(getattr(b['material'],k),target,atol=1e-7,rtol=0)
                if 'live' in b:
                    expected=b['live']['pixels'] if params is None else FixtureAppearance._solid_pixels(b['live'],params['base_color'][:3])
                    assert np.array_equal(b['live']['texture'].download(),expected)
        assert all(r['catalog_version']==cat['version'] for r in adapter.records)
        if e._charger_appearance is not None:
            cc=e._charger_appearance.catalog
            for i,entity in enumerate(e.charger._objs):
                for s in entity.find_component_by_type(sapien.render.RenderBodyComponent).render_shapes:
                    p=cc['schemes'][e._charger_appearance.schemes[i]]['body'] if np.allclose(s.half_size,e.charger_half) else cc['prongs']
                    for part in s.parts:
                        for k in ['base_color','roughness','metallic']: np.testing.assert_allclose(getattr(part.material,k),p[k],atol=1e-7,rtol=0)

    manifest=dict(head=head,job=os.environ['SLURM_JOB_ID'],seed=TASK_SEED,obs_mode='rgb+segmentation',files={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES+[__file__.replace(str(ROOT)+os.sep,'').replace('\\','/')]},
                  packages={p:metadata.version(p) for p in ['torch','sapien','mani_skill','gymnasium','numpy']},physics_steps=0)
    dump('manifest.json',manifest)
    results={'tasks':{},'realism':'pending human image review','status':'running','builds_started':0}
    env=None
    outer_cpu=torch.random.get_rng_state().clone()
    gpu=torch.cuda.current_device()
    outer_cuda=torch.cuda.get_rng_state(gpu).clone()
    capture_schemes=('original','warm_white','neutral_grey')
    capture_views={'OpenDrawer':('drawer',[452,0,850,330]),'InsertPlug':('socket',[603,319,733,430])}
    baselines={}
    candidate_pixels={}

    def start_sequence():
        # Reset the caller RNG once per independent sequence. Do not rewind it
        # between steps; ManiSkill's seeded reset has its own internal seed scope.
        torch.random.set_rng_state(outer_cpu)
        torch.cuda.set_rng_state(outer_cuda,gpu)

    def task_row(task):
        return results['tasks'].setdefault(task,dict(status='running',num_envs=1 if task=='Long' else 2,checks={}))

    def make(task,n,config=None,charger=False):
        kw={} if config is None else {'drawer_plug_appearance':config}
        if charger and task!='OpenDrawer':
            kw['charger_appearance']={'enabled':True,'scheme_id':'ivory_matte','seed':71}
        results['builds_started']+=1
        dump('results.json',results)
        return gym.make(f'DrawerPlug{task}-Sharpa-v1',num_envs=n,sim_backend='physx_cuda',
                        reconfiguration_freq=0,obs_mode='rgb+segmentation',render_mode='rgb_array',**kw)

    def check_rng(task,branch,stage,seq,reference):
        actual=seq[stage]
        if reference is not None and reference[stage]!=actual:
            detail=dict(task=task,branch=branch,stage=stage,expected=reference[stage],actual=actual)
            dump('first_rng_divergence.json',detail)
            raise AssertionError(f'Torch RNG divergence: {detail}')

    def state_hash(st):
        return {k:digest(v.numpy()) for k,v in st.items()}

    def fixed(task,name):
        nonlocal env
        n=task_row(task)['num_envs']
        baseline=baselines.get(task)
        ref=None if baseline is None else baseline[4]
        seq={}
        prefix=f'{task}_{name}'

        def mark(stage):
            seq[stage]=task_rng()
            dump(f'{prefix}_rng.json',seq)
            check_rng(task,name,stage,seq,ref)

        effective='native' if name=='native_replay' else name
        config=None if effective=='native' else {'enabled':name!='disabled','scheme_id':name,'seed':91}
        start_sequence()
        mark('before_build')
        env=make(task,n,config)
        mark('after_build')
        env.reset(seed=TASK_SEED)
        mark('after_seeded_reset')
        e=env.unwrapped
        # Keep original PNGs as soon as they are available, even when a
        # later state/material assertion stops this branch.
        rgb,seg=frames(env,prefix,masks=True)
        st,ph,ma=state(e),physical(e),materials(e)
        dump(f'{prefix}_state.json',st)
        dump(f'{prefix}_physical.json',ph)
        dump(f'{prefix}_materials.json',ma)
        if baseline is not None:
            dump(f'{prefix}_state_hashes.json',dict(expected=state_hash(baseline[0]),actual=state_hash(st)))
            equal_state(baseline[0],st)
            assert baseline[1]==ph, f'{prefix}: physical attributes'
            if effective in ['native','disabled','original']:
                assert baseline[2]==ma, f'{prefix}: baseline materials'
                for idx in range(n): same_rgb(rgb,baseline[3],idx)
            if effective not in ['native','disabled']:
                verify(e,[name]*n)
            for key,values in ma.items():
                for slot,value in enumerate(values):
                    if value['role'] in ['hardware','hole'] or key.startswith('charger/'):
                        assert value==baseline[2][key][slot], (prefix,key,slot)
            if name in capture_schemes[1:]:
                counts=target_pixel_counts(e,baseline[3],rgb,seg,0)
                candidate_pixels[task,name]=counts
                dump(f'{prefix}_target_pixels.json',counts)
        local=[]
        for i in range(2):
            env.reset(options={'env_idx':torch.tensor([n-1],device=e.device)})
            mark(f'after_unseeded_local_reset_{i+1}')
            local.append(state(e))
            dump(f'{prefix}_local_{i+1}_state.json',local[-1])
            if baseline is not None:
                equal_state(baseline[5][i],local[-1])
        env.close(); env=None
        if baseline is None:
            baselines[task]=(st,ph,ma,rgb,seq,local)

    def record_group(task):
        obj,box=capture_views[task]
        names=[f'{task}_{name}_human_env0.png' for name in capture_schemes]
        sizes=[]
        for name in names:
            with Image.open(args.output/name) as img: sizes.append(img.size)
        assert sizes==[(1280,720)]*3,sizes
        dump(f'{obj}_capture.json',dict(task=f'DrawerPlug{task}-Sharpa-v1',env_idx=0,seed=TASK_SEED,
             camera='render_camera (human)',size=list(sizes[0]),crop_xyxy=box,
             candidate_schemes=list(capture_schemes),frames=names,charger='native' if task=='InsertPlug' else 'absent',
             exposure='unchanged task camera default',lighting='unchanged native task lighting',
             case_initial_state='compared against native baseline'))

    try:
        # Gate the matrix on a genuine independent native replay. The first
        # instance then doubles as the OpenDrawer reference.
        task='OpenDrawer'; row=task_row(task)
        fixed(task,'native')
        fixed(task,'native_replay')
        row['checks']['native_baseline_replay']='passed'
        dump('results.json',results)
        for task in capture_views:
            row=task_row(task)
            if task!='OpenDrawer': fixed(task,'native')
            for scheme in capture_schemes: fixed(task,scheme)
            record_group(task)
            row['checks']['fixed_capture']='saved'
            dump('results.json',results)

        for task in TASKS:
            row=task_row(task); n=row['num_envs']; started=time.monotonic()
            if task in capture_views:
                fixed(task,'disabled')
            else:
                for case in ['native','disabled',*capture_schemes]: fixed(task,case)
            for scheme in capture_schemes[1:]:
                counts=candidate_pixels[task,scheme]
                assert any(x['changed_pixels'] for group in counts.values() for x in group.values()), (task,scheme,'No target RGB difference')
            baseline=baselines[task]
            row['checks']['fixed_native_physical']='passed'
            # One fresh instance serves both candidate restores and A5. Keep
            # original Charger for restoration before testing joint configuration.
            start_sequence()
            env=make(task,n,{'enabled':True,'scheme_id':'warm_white','seed':91,
                      'per_env':{str(n-1):{'scheme_id':'neutral_grey'}}},charger=True)
            e=env.unwrapped; a=e._fixture_appearance
            for variant in capture_schemes[1:]:
                env.reset(seed=TASK_SEED,options={'drawer_plug_appearance':{'scheme_id':variant}})
                verify(e,[variant]*n)
                opts={'drawer_plug_appearance':{'scheme_id':'original'}}
                if e._charger_appearance is not None: opts['charger_appearance']={'scheme_id':'original'}
                env.reset(seed=TASK_SEED,options=opts)
                verify(e,['original']*n)
                assert materials(e)==baseline[2]
                equal_state(state(e),baseline[0])
                restored_rgb=frames(env,f'{task}_{variant}_restore')
                for idx in range(n): same_rgb(baseline[3],restored_rgb,idx)
            row['checks']['both_candidates_restore']='passed'
            env.reset(seed=TASK_SEED, options={'charger_appearance':{'scheme_id':'ivory_matte'}})
            selected=[1] if n==2 else [0]
            idx=selected[0]
            for name in ['warm_white','original'] if n==2 else ['neutral_grey','original']:
                previous=a.schemes[idx]
                before=state(e); ma=materials(e); records=copy.deepcopy(a.records)
                rng=copy.deepcopy(a.rng[0].bit_generator.state)
                charger_before=e._charger_appearance.schemes.copy() if e._charger_appearance else None
                images=frames(env,f'{task}_before_{name}')
                opts={'env_idx':torch.tensor(selected,device=e.device),
                      'drawer_plug_appearance':{'scheme_id':name}}
                if charger_before is not None:
                    opts['charger_appearance']={'scheme_id':charger_before[idx]}
                env.reset(options=opts)
                after,seg=frames(env,f'{task}_after_{name}',masks=True)
                verify(e,['warm_white',name] if n==2 else [name])
                actual=materials(e)
                if n==2:
                    equal_state(before,state(e),True)
                    assert {k:v for k,v in ma.items() if k.endswith('/0')}=={k:v for k,v in actual.items() if k.endswith('/0')}
                    assert [r for r in records if r['env_idx']==0]==[r for r in a.records if r['env_idx']==0]
                    assert rng==a.rng[0].bit_generator.state
                    same_rgb(images,after,0)
                if charger_before is not None:
                    assert e._charger_appearance.schemes==charger_before
                    assert {k:v for k,v in ma.items() if k.startswith('charger/')}=={k:v for k,v in actual.items() if k.startswith('charger/')}
                if name=='original':
                    for key,value in baseline[2].items():
                        if key.endswith('/'+str(idx)) and not key.startswith('charger/'): assert actual[key]==value,key
                if n==2:
                    counts=same_state_visual_probe(env,a,(previous,name),after,seg,idx)
                    dump(f'{task}_{name}_local_target_pixels.json',counts)
                    assert any(x['changed_pixels'] for cs in counts.values() for x in cs.values()), 'No selected target-object RGB change at fixed state'
                    verify(e,['warm_white',name]); assert materials(e)==actual
                dump(f'{task}_{name}_records.json',a.records)
            row['checks']['restore_and_isolation']='passed' if n==2 else 'restoration passed; isolation N/A'
            if e._charger_appearance is not None:
                before=state(e); ma=materials(e); images=frames(env)
                ca=e._charger_appearance
                records=copy.deepcopy(ca.records); rng=copy.deepcopy(ca.rng[0].bit_generator.state)
                env.reset(options={'env_idx':torch.tensor(selected,device=e.device),
                                   'drawer_plug_appearance':{'scheme_id':'original'},
                                   'charger_appearance':{'scheme_id':'navy_satin'}})
                verify(e,['warm_white','original'] if n==2 else ['original'])
                actual=materials(e)
                assert ca.schemes[idx]=='navy_satin' and actual[f'charger/{idx}']!=ma[f'charger/{idx}']
                assert {k:v for k,v in ma.items() if not k.startswith('charger/')}=={k:v for k,v in actual.items() if not k.startswith('charger/')}
                if n==2:
                    equal_state(before,state(e),True)
                    same_rgb(images,frames(env),0)
                    assert actual['charger/0']==ma['charger/0']
                    assert [r for r in records if r['env_idx']==0]==[r for r in ca.records if r['env_idx']==0]
                    assert rng==ca.rng[0].bit_generator.state
                dump(f'{task}_charger_compatibility.json',dict(schemes=ca.schemes,records=ca.records,
                     selected_material_before=ma[f'charger/{idx}'],selected_material_after=actual[f'charger/{idx}']))
                row['checks']['charger_compatibility']='passed'
            if task=='Long':
                for phase in ['charger_pick_place','charger_insert']:
                    env.reset(seed=TASK_SEED,options={'task_phase':phase,'drawer_plug_appearance':{'scheme_id':'neutral_grey'}})
                    verify(e,['neutral_grey']); frames(env,f'Long_engineering_{phase}')
                row['checks']['native_phase_reset']='engineering only; no robot completion'
            env.close(); env=None
            traces=[]
            for repeat in range(2):
                start_sequence()
                env=make(task,n,{'enabled':True,'mode':'random_choice','scheme_ids':list(cat['schemes']),'seed':91})
                trace=[]
                for j in range(4):
                    env.reset(seed=TASK_SEED if j==0 else None, options={} if j==0 else {'env_idx':torch.tensor([n-1],device=env.unwrapped.device)})
                    a=env.unwrapped._fixture_appearance; verify(env.unwrapped,a.schemes)
                    trace.append(copy.deepcopy(a.records))
                    count=len(a.records)
                    frames(env,f'{task}_random_{repeat}_{j}')
                    assert len(a.records)==count, 'Rendering resampled appearance'
                traces.append(trace); env.close(); env=None
            assert traces[0]==traces[1]
            dump(f'{task}_random.json',traces)
            row['checks']['random_reproducibility']='passed'
            row.update(status='engineering_passed_pending_visual_review',seconds=time.monotonic()-started)
            dump('results.json',results)
        results['status']='engineering_passed_pending_visual_review'
    except Exception:
        results['status']='failed'; results['error']=traceback.format_exc()
        if 'row' in locals(): row['status']='failed'
        raise
    finally:
        if env is not None: env.close()
        dump('results.json',results)
        dump('post_files.json',{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES})


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--static',action='store_true'); p.add_argument('--asset-root',type=Path)
    p.add_argument('--approval',type=Path); p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.static: print(json.dumps(static_check(args.asset_root),ensure_ascii=False))
    elif args.approval is None or args.output is None: p.error('runtime requires --approval and --output')
    else: runtime(args)
