"""CPU audit and separately approved environment check for the ten family schemes."""

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
import traceback

import numpy as np

from cabinet_followup import CLOSEOUT_CHECKS

ROOT = Path(__file__).resolve().parents[2]
BASE = 'f0a09c9d1722abc831fd5c62ae77a42c9dece95c'
FAMILY = 'cabinet_pouring'
DIR = ROOT / 'tasks/assets/variation' / FAMILY
VARIANTS = ('original', *(f'variant_{i}' for i in range(1, 11)))
SEED = 7
LEGACY_MAP = (dict(cabinet='oak_warm_white', bottle='ocean', pouring='ocean'),
              dict(cabinet='sage_walnut', bottle='citrus', pouring='citrus'),
              dict(cabinet='smoked_linen', bottle='violet', pouring='violet'))


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def git(*args):
    return subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'-C',str(ROOT),*args])


def old(file):
    return git('show',BASE+':'+file.relative_to(ROOT).as_posix())


def load_standalone(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tasks'/FAMILY/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def static():
    family=load_standalone('family_appearance')
    c=read(DIR/'family_variants.json')['schemes']
    assert tuple(c)==VARIANTS
    assert all(v=='original' for v in c['original'].values())
    assert tuple(c[f'variant_{i}'] for i in (1, 2, 3)) == LEGACY_MAP
    for key, path in CATALOGS.items():
        cur=read(DIR/path); base=json.loads(old(DIR/path))
        assert {k:v for k,v in cur.items() if k!='schemes'}=={k:v for k,v in base.items() if k!='schemes'}
        assert all(cur['schemes'][k]==v for k,v in base['schemes'].items())
        assert all(c[v][key] in cur['schemes'] for v in VARIANTS)
        assert len({c[v][key] for v in VARIANTS})==11
    for task, roles in TASKS.items():
        selector=family.FamilyAppearance({'seed':91,'mode':'random_choice','scheme_ids':list(VARIANTS[1:])},2,roles)
        replica=family.FamilyAppearance(selector.config,2,roles)
        for indices in ([0,1],[1],[0],[1],[0,1]):
            frozen=copy.deepcopy(selector.rng[1-indices[0]].bit_generator.state) if len(indices)==1 else None
            for a in (selector,replica):
                for i,sid,mapping in a.select(np.array(indices),{}): a.record(i,sid,mapping)
            assert selector.records==replica.records
            if frozen is not None: assert frozen==selector.rng[1-indices[0]].bit_generator.state
        for sid in VARIANTS:
            i, actual, map_ = next(selector.select(np.array([1]),{'family_appearance':{'mode':'explicit','scheme_id':sid}}))
            assert (i,actual,map_)==(1,sid,c[sid])
    # Compare whole ASTs after removing only enumerated appearance changes.
    for suffix in (*TASKS, 'Long'):
        p=ROOT/'tasks'/FAMILY/(FAMILY+'_'+SNAKE[suffix]+'.py')
        previous=ast.parse(old(p))
        updated=ast.parse(p.read_text(encoding='utf-8'))
        def methods(tree):
            return {n.name:n for cl in tree.body if isinstance(cl,ast.ClassDef)
                    for n in cl.body if isinstance(n,ast.FunctionDef)}
        before,after=methods(previous),methods(updated)
        assert set(before)==set(after)-({'_finish_family_appearance','family_appearance_records'} if suffix=='Long' else set())
        for name,node in before.items():
            new=after[name]
            if suffix=='Long' and name=='__init__':
                pos=next(i for i,x in enumerate(new.args.kwonlyargs) if x.arg=='family_appearance')
                new.args.kwonlyargs.pop(pos);new.args.kw_defaults.pop(pos)
                new.body=[x for x in new.body if not (isinstance(x,ast.Assign) and any(
                    ast.unparse(t) in {'self._family_appearance','self._family_liquid'} for t in x.targets))
                    and not (isinstance(x,ast.If) and ast.unparse(x.test)=="family_appearance and family_appearance.get('enabled', False)")]
                for call in ast.walk(new):
                    if isinstance(call,ast.Call) and ast.unparse(call.func)=='PilotVariation':
                        call.keywords=[k for k in call.keywords if k.arg!='family']
            if suffix=='Long' and name=='_load_scene':
                new.body=[x for x in new.body if not (isinstance(x,ast.If) and
                   ast.unparse(x.test).startswith(('self._family_liquid','self._family_appearance')))]
            if suffix!='Long' and name=='_initialize_episode':
                with_ = new.body[-1]
                assert isinstance(with_,ast.With)
                cond=with_.body.pop()
                assert isinstance(cond,ast.If) and ast.unparse(cond.test)=='self._family_appearance is not None'
                with_.body.extend(cond.orelse)
            assert ast.dump(node)==ast.dump(new),(suffix,name)
    for mode in ('explicit', 'random'):
        example = read(ROOT/f'examples/variation/{FAMILY}/family/family_ten_{mode}.json')['family_appearance']
        selector = family.FamilyAppearance(example, 2, next(iter(TASKS.values())))
        choices = [sid for _, sid, _ in selector.select(np.array([0, 1]), {})]
        assert choices == ['variant_1', 'variant_10'] if mode == 'explicit' else all(x in VARIANTS[1:] for x in choices)
    extra = validate_assets(c)
    from cabinet_followup import static as check_followup_static
    extra['followup']=check_followup_static(DIR)
    assert not any(n in sys.modules for n in ('tasks','torch','sapien','mani_skill'))
    return dict(status='passed',family=FAMILY,scopes=list(TASKS),variants=len(VARIANTS)-1,
                legacy_catalog_values='exact',scope='CPU only',assets=extra)


def run(approval, output, *, followup=None):
    auth=read(approval)
    head=git('rev-parse','HEAD').decode().strip()
    scopes={'label-probe':'cabinet_label_probe','targeted':'cabinet_pouring_followup',
            'remaining':'cabinet_cap_pour_followup','finish':'cabinet_stage_and_pour_finish'}
    scopes.update(dict.fromkeys(CLOSEOUT_CHECKS,'cabinet_independent_closeout'))
    assert auth['approved'] is True and auth['scope']==scopes.get(followup,FAMILY+'_ten_variants')
    if followup:
        assert auth.get('blockers_resolved') is True
    if followup=='targeted':
        probe=auth['label_probe']
        assert str(probe['job_id']).isdigit() and probe['visible_pattern_passed'] is True
        assert probe['binding_path'] in {'current','private_upload'}
        assert len(probe['manifest_sha256'])==64
    elif followup=='remaining':
        reused=auth['reused_pick_bottle']
        assert reused['job_id']=='128933' and reused['status']=='passed'
        assert len(reused['manifest_sha256'])==64
    elif followup=='finish' or followup in CLOSEOUT_CHECKS:
        reused=auth['reused_evidence']
        expected={'128861','128933','128943'}
        if followup in CLOSEOUT_CHECKS:
            expected.add('128997')
            assert followup in auth['checks']
        assert set(reused)==expected
        for evidence in reused.values():
            assert evidence['verified'] is True
            assert len(evidence['manifest_sha256'])==len(evidence['results_sha256'])==64
    assert head==auth['frozen_head'] and os.environ.get('SLURM_JOB_ID')
    assert os.environ.get('SLURM_JOB_GPUS','').isdigit()
    limit=Path(auth['storage_root']).resolve(strict=True)
    assert output.resolve().is_relative_to(limit) and output.resolve()!=limit
    output.mkdir(exist_ok=False)
    import torch
    from PIL import Image
    import gymnasium as gym
    from mani_skill.utils import sapien_utils
    from sapien.render import RenderBodyComponent
    import tasks
    torch_rng=(torch.random.get_rng_state().clone(),torch.cuda.get_rng_state().clone())
    catalog=read(DIR/'family_variants.json')['schemes']
    def dump(name,obj):
        (output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=lambda x: x.item() if isinstance(x,np.generic) else list(x))+'\n',encoding='utf-8')
    def digest(a):
        return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()
    def walk(o, i, n):
        if isinstance(o,dict): return {k:walk(v,i,n) for k,v in o.items()}
        if torch.is_tensor(o):
            o=o.detach().cpu().numpy()
        if isinstance(o,np.ndarray):
            return digest(o[i] if o.ndim and o.shape[0]==n else o)
        return o
    def actors(e,i):
        def entities(raw):
            return getattr(raw,'entity',raw)
        def group(thing):
            if thing is None:return []
            if hasattr(thing,'get_links'):
                return [entities(o) for link in thing.get_links() for o in link._objs]
            return [entities(thing._objs[i])]
        return {'cabinet':group(e._cabinets[i]) if e.has_cabinet else [],
                'bottle':[x for attr in ('source','source_fixed','source_open')
                          for x in group(getattr(e,attr,None))],
                'cap':[x for attr in ('cap','cap_fixed','cap_twin')
                       for x in group(getattr(e,attr,None))] if e.has_cap else [],
                'bowl':group(getattr(e,'target',None)) if e.has_target else [],
                'beads':[x for actor in getattr(e,'particles',[]) for x in group(actor)]}
    def materials(e,i):
        result={}
        for role, es in actors(e,i).items():
            values=[]
            for ent in es:
                body=ent.find_component_by_type(RenderBodyComponent)
                if body is None:
                    continue
                for shape in body.render_shapes:
                    for p in shape.parts:
                        m=p.material
                        row={k:np.asarray(getattr(m,k)).tolist() for k in
                             ('base_color','roughness','metallic','specular','transmission','ior','emission')}
                        for k in ('base_color_texture','normal_texture','roughness_texture','metallic_texture',
                                  'emission_texture','transmission_texture'):
                            tex=getattr(m,k)
                            row[k]=None if tex is None else digest(tex.download())
                        values.append(row)
            if values: result[role]=values
        return result
    def assert_finish(m, rgb, roughness, metallic):
        assert np.allclose(m.base_color,rgb,atol=1e-6,rtol=0)
        assert abs(m.roughness-roughness)<1e-6 and abs(m.metallic-metallic)<1e-6

    def verify_bindings(e, i, sid, *, bottle_only=False):
        mapping=catalog[sid]
        counts={}
        if not bottle_only and e._cabinet_appearance is not None:
            adapter=e._cabinet_appearance
            for b in adapter.bindings[i]:
                params=adapter.catalog['schemes'][mapping['cabinet']][b['role']]
                rgb=[1.,1.,1.] if 'live' in b else params['color']
                m=b['material']
                assert_finish(m,[*rgb,b['native']['base_color'][3]],params['roughness'],params['metallic'])
                if 'live' in b:
                    assert digest(m.base_color_texture.download())==digest(b['live']['pixels'][mapping['cabinet']])
                counts[b['role']]=counts.get(b['role'],0)+1
        if e._variation is not None and e._variation.appearance:
            from tasks.cabinet_pouring.variation import ASSETS, resize_label_pixels
            adapter=e._variation
            params=adapter.catalog['schemes'][mapping['bottle']]
            label=adapter._textures[str(ASSETS / params['label_texture'])]
            for b in adapter._bindings[i]:
                role=b['role']
                key={'body_surface':'body_color','cap_surface':'cap_color','cap_reference':'reference_color'}
                rgb=[1.,1.,1.,1.] if role=='body_label' else params[key[role]]
                m=b['material']
                assert_finish(m,rgb,params['roughness'],params['metallic'])
                if role=='body_label':
                    pixels=label.download()
                    if 'label_live' in b:
                        pixels=resize_label_pixels(pixels,b['label_native'])
                    assert digest(m.base_color_texture.download())==digest(pixels)
                counts[b['name']+'/'+role]=counts.get(b['name']+'/'+role,0)+1
        if not bottle_only and e._family_liquid is not None:
            from tasks.cabinet_pouring.pouring_appearance import PALETTE, NEW_FINISHES
            liquid=mapping['pouring']
            tex, pixels, materials=e._family_liquid.bindings[i]
            if tex is not None:
                assert digest(tex.download())==digest(pixels[liquid])
            for m, role, native, roughness, metallic in materials:
                if liquid in NEW_FINISHES:
                    p=NEW_FINISHES[liquid]
                    roughness,metallic=p[role+'_roughness'],0.
                    rgb=[1.,1.,1.] if role=='bowl' else p['liquid_linear']
                else:
                    rgb,bowl_rough,bead_rough=PALETTE[liquid]
                    changed=bowl_rough if role=='bowl' else bead_rough
                    if changed is not None:roughness,metallic=changed,0.
                assert_finish(m,[*rgb,native[3]],roughness,metallic)
                counts[role]=counts.get(role,0)+1
            assert counts['beads']==16
        assert counts
        return counts

    def physics(e,i):
        result={}
        for ent in e.scene.sub_scenes[i].entities:
            for comp in ent.components:
                if not hasattr(comp,'get_collision_shapes'): continue
                slot={'type':type(comp).__name__}
                for attr in ('mass','inertia','disable_gravity','linear_damping','angular_damping'):
                    if hasattr(comp,attr):slot[attr]=np.asarray(getattr(comp,attr)).tolist()
                shapes=[]
                for shape in comp.get_collision_shapes():
                    p=shape.local_pose; mat=shape.physical_material
                    geom={k:np.asarray(getattr(shape,k)).tolist()
                          for k in ('radius','half_size','half_length','scale') if hasattr(shape,k)}
                    if hasattr(shape,'get_vertices'):geom['vertices']=digest(shape.get_vertices())
                    shapes.append(dict(kind=type(shape).__name__,geom=geom,
                        pose=[list(p.p),list(p.q)],friction=[mat.static_friction,mat.dynamic_friction],
                        restitution=mat.restitution,groups=list(shape.get_collision_groups())))
                slot['collision']=shapes
                result[str(ent.per_scene_id)+':'+slot['type']]=slot
        return result
    def task_state(e,i):
        state=walk(e.get_state_dict(),i,e.num_envs)
        state['episode_buffers']={k:walk(v,i,e.num_envs) for k,v in vars(e).items()
                                  if torch.is_tensor(v) and v.ndim and v.shape[0]==e.num_envs}
        return state

    def capture(env):
        x=env.unwrapped.get_obs()['sensor_data']
        data={name:(v['rgb'].detach().cpu().numpy()[...,:3].copy(),
                    v['segmentation'].detach().cpu().numpy()[...,0].copy()) for name,v in x.items()}
        data['human']=(env.render().detach().cpu().numpy()[...,:3].copy(),None)
        return data
    def rgb_equal(a,b,i=None):
        return set(a)==set(b) and all(np.array_equal(a[k][0] if i is None else a[k][0][i],
                                                     b[k][0] if i is None else b[k][0][i]) for k in a)
    def info_signature(info):
        return {k:walk(v,None,-1) for k,v in info.items()}
    def snap(env,info):
        e=env.unwrapped
        return dict(state=[task_state(e,i) for i in (0,1)],
                    physics=[physics(e,i) for i in (0,1)], info=info_signature(info),
                    materials=[materials(e,i) for i in (0,1)],frames=capture(env))
    def measures(e,frames,base,roles,env_idx):
        found={}
        for role, ents in actors(e,env_idx).items():
            if role not in roles:continue
            ids=[ent.per_scene_id for ent in ents]
            counts={}
            for k,(ims,seg) in frames.items():
                if seg is None: continue
                mask=np.isin(seg[env_idx],ids) & np.isin(base[k][1][env_idx],ids)
                delta=np.any(ims[env_idx]!=base[k][0][env_idx],axis=-1)
                counts[k]=dict(visible=int(mask.sum()),changed=int((mask&delta).sum()),
                    before_rgb_median=np.median(base[k][0][env_idx][mask],axis=0).tolist() if mask.any() else None,
                    after_rgb_median=np.median(ims[env_idx][mask],axis=0).tolist() if mask.any() else None)
            found[role]=counts
        return found
    def save_frames(task,stem,frames,idx=0):
        files={}
        for cam in ('base_camera','human'):
            path=output/f'{task}_{stem}_{cam}_env{idx}.png'
            Image.fromarray(frames[cam][0][idx]).save(path)
            files[cam]=dict(file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            size_wh=list(frames[cam][0][idx].shape[1::-1]))
        return files
    def crop_boxes(e,frames):
        seg=frames['base_camera'][1][0]
        result={}
        for role, ents in actors(e,0).items():
            ys,xs=np.where(np.isin(seg,[ent.per_scene_id for ent in ents]))
            if xs.size:
                h,w=seg.shape
                result[role]=[max(0,int(xs.min())-12),max(0,int(ys.min())-12),
                              min(w,int(xs.max())+13),min(h,int(ys.max())+13)]
        return result
    def opts(sid,idx=None,mode='explicit'):
        appearance={'mode':mode,'scheme_id':sid}
        if mode=='random_choice': appearance['scheme_ids']=list(VARIANTS[1:])
        o={'family_appearance':appearance}
        if idx is not None:o['env_idx']=torch.tensor([idx],device='cuda')
        return o
    def restore_outer_rng():
        torch.random.set_rng_state(torch_rng[0])
        torch.cuda.set_rng_state(torch_rng[1])
    def full_reset(env, options=None):
        restore_outer_rng()
        return env.reset(seed=SEED, options=options)
    def make(task, config=None, diagnostic=False, legacy=None, review_view=None):
        restore_outer_rng()
        eye,at,fov=BEAD_CAMERA if diagnostic else VIEWS[task]
        camera=dict(width=960,height=720,fov=fov,pose=sapien_utils.look_at(eye,at))
        review_camera=camera
        if review_view:
            review_eye,review_at,review_fov=review_view
            review_camera=dict(width=960,height=720,fov=review_fov,
                               pose=sapien_utils.look_at(review_eye,review_at))
        return gym.make(TASK_PREFIX+task+'-Sharpa-v1',num_envs=2,sim_backend='physx_cuda',
            obs_mode='rgb+segmentation',render_mode='rgb_array',reconfiguration_freq=0,
            sensor_configs={'base_camera':camera},human_render_camera_configs=review_camera,
            **({'family_appearance':config} if config is not None else (legacy or {})))
    def bead_display(e):
        from mani_skill.utils.structs import Pose
        assert len(e.particles)==16 and e.particle_radius==.004
        for j,particle in enumerate(e.particles):
            p=particle.pose.p.clone()
            p[:]=torch.tensor([1+(j%4-1.5)*.018,1+(j//4-1.5)*.018,.5],device=e.device)
            particle.set_pose(Pose.create_from_pq(p=p,q=particle.pose.q))
        e.scene.px.gpu_apply_rigid_dynamic_data()
        e.scene._gpu_fetch_all()
    tracked=git('diff','--name-only',BASE,'HEAD','--','tasks',
                str(Path(__file__).resolve().relative_to(ROOT))).decode().splitlines()
    if followup:
        tracked.append('tools/variation/cabinet_followup.py')
    from importlib.metadata import version
    dump('manifest.json',dict(head=head,baseline=BASE,seed=SEED,backend='physx_cuda',
         job=os.environ['SLURM_JOB_ID'],gpu=os.environ['SLURM_JOB_GPUS'],
         versions={name:version(name) for name in ('sapien','mani_skill','torch','gymnasium','numpy')},
         asset_identity=auth['asset_identity'],
         hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in tracked}))
    report=dict(family=FAMILY,head=head,seed=SEED,job=os.environ['SLURM_JOB_ID'],tasks={},status='running')
    if followup:
        from cabinet_followup import run as run_followup

        run_followup(followup, auth, report=report, output=output, make=make, full_reset=full_reset,
                     opts=opts, capture=capture, snap=snap, task_state=task_state, materials=materials,
                     verify_bindings=verify_bindings, rgb_equal=rgb_equal, bead_display=bead_display,
                     variants=VARIANTS, catalog=catalog)
        return
    env=None
    try:
        for task,roles in TASKS.items():
            row=report['tasks'][task]=dict(loaded=roles,view=VIEWS[task],captures={},legacy_equivalence={},isolation=[])
            dump('results.json',report)
            env=make(task)
            _,info=full_reset(env)
            n=snap(env,info)
            assert set(n['materials'][0])==set(roles), (task,'native roles',list(n['materials'][0]))
            row['native_frames']=save_frames(task,'native',n['frames'])
            env.close(); env=None
            accepted_frames = {}
            # Independent accepted ID path, using its original adapter.
            for sid, kwargs, accepted in legacy_cases(task,catalog):
                env=make(task,legacy=kwargs)
                full_reset(env)
                accepted_frames[sid]=capture(env)
                row['legacy_equivalence'][sid]={'surfaces':accepted,'fingerprints':[
                    {k:v for k,v in materials(env.unwrapped,i).items() if k in accepted} for i in (0,1)]}
                env.close();env=None
            env=make(task,{'enabled':True,'seed':109})
            e=env.unwrapped; family=e._family_appearance
            for sid in VARIANTS:
                _,info=full_reset(env, opts(sid))
                now=snap(env,info)
                event=dict(files=save_frames(task,sid,now['frames']),record=copy.deepcopy(family.records[-2:]),
                           targets=measures(e,now['frames'],n['frames'],roles,0))
                row['captures'][sid]=event
                dump('results.json',report)
                assert all(now[k]==n[k] for k in ('state','physics','info')),(task,sid,'initial state/physics/info')
                assert set(now['materials'][0])==set(roles),(task,sid,set(now['materials'][0]),set(roles))
                assert all(x['family_id']==sid and x['objects']=={r:catalog[sid][k] for r,k in roles.items()} for x in event['record'])
                if sid=='original':
                    row['same_coordinate_crops']=crop_boxes(e,now['frames'])
                    assert now['materials']==n['materials'] and rgb_equal(now['frames'],n['frames'])
                    continue
                event['verified_render_slots']=[verify_bindings(e,i,sid) for i in (0,1)]
                for r, cams in event['targets'].items():
                    assert now['materials'][0][r]!=n['materials'][0][r],(task,sid,r,'material unchanged')
                    if r!='beads':assert any(c['changed'] for c in cams.values()),(task,sid,r,'no changed target pixels')
                if sid in row['legacy_equivalence']:
                    chk=row['legacy_equivalence'][sid]
                    assert all({k:v for k,v in now['materials'][i].items() if k in chk['surfaces']}==chk['fingerprints'][i]
                               for i in (0,1)),(task,sid,'legacy material mismatch')
                    pixels=measures(e,now['frames'],accepted_frames.pop(sid),chk['surfaces'],0)
                    chk['target_pixels']=pixels
                    # Other objects can change indirect lighting in this comparison, so
                    # record that evidence separately from exact material equality.
                    chk['material_equivalent']=True
                full_reset(env, opts('original'))
                restored=capture(env)
                assert [materials(e,i) for i in (0,1)]==n['materials'] and rgb_equal(restored,n['frames']), (task,sid,'restore')
                event['restored']=True
            o={'family_appearance':{'per_env':{'0':{'scheme_id':'variant_4'},'1':{'scheme_id':'variant_10'}}}}
            full_reset(env, o)
            for selected in (1,0):
                still=1-selected
                before=capture(env)
                phase=dict(index=selected,before=save_frames(task,f'A5_{selected}_before',before,selected),
                    before_unselected=save_frames(task,f'A5_{selected}_before_other',before,still))
                row['isolation'].append(phase)
                custody=(task_state(e,still),materials(e,still),
                         copy.deepcopy([r for r in family.records if r['env_idx']==still]),
                         copy.deepcopy(family.rng[still].bit_generator.state))
                env.reset(options=opts('original',selected))
                after=capture(env)
                phase.update(after=save_frames(task,f'A5_{selected}_after',after,selected),
                             after_unselected=save_frames(task,f'A5_{selected}_after_other',after,still),
                             targets=measures(e,after,before,roles,selected))
                dump('results.json',report)
                assert rgb_equal(before,after,still)
                assert custody==(task_state(e,still),materials(e,still),
                                 [r for r in family.records if r['env_idx']==still],family.rng[still].bit_generator.state)
                assert family.schemes[selected]=='original' and family.records[-1]['env_idx']==selected
                assert materials(e,selected)==n['materials'][selected]
                assert all(any(x['changed'] for x in cams.values()) for r,cams in phase['targets'].items() if r!='beads')
                phase['passed']=True
            if task=='UnscrewCap' and e.bottle_stage_twins:
                from tasks.cabinet_pouring.cabinet_pouring_long import BOTTLE_REP_OPEN
                full_reset(env,opts('variant_4'))
                before=materials(e,0)
                e._swap_in_twin(0)
                e._swap_to_open_bottle(torch.tensor([True,False],device=e.device))
                assert int(e._active_bottle_rep[0])==BOTTLE_REP_OPEN
                assert materials(e,0)==before and family.schemes[0]=='variant_4'
                row['engineered_stage_switch']=dict(active_bottle_rep=int(e._active_bottle_rep[0]),
                    files=save_frames(task,'engineered_open',capture(env)),scope='engineering only')
                dump('results.json',report)
            env.close();env=None
            traces=[]
            for _ in range(2):
                env=make(task,{'enabled':True,'seed':109})
                for idx in (None,1,0,1): env.reset(seed=SEED,options=opts(None,idx,mode='random_choice'))
                traces.append(env.unwrapped._family_appearance.records.copy())
                env.close();env=None
            assert traces[0]==traces[1]
            row['random_reproducibility']=traces[0]
            dump('results.json',report)
        if FAMILY=='cabinet_pouring':
            task='PourBeads_diagnostic'
            env=make('PourBeads',{'enabled':True},diagnostic=True)
            row=report['tasks'][task]=dict(radius_m=.004,count=16,frames={})
            base=None
            for sid in VARIANTS:
                full_reset(env, opts(sid))
                bead_display(env.unwrapped)
                frames=capture(env)
                row['frames'][sid]=save_frames(task,sid,frames)
                if base is None: base=frames
                m=measures(env.unwrapped,frames,base,{'beads'},0)['beads']['base_camera']
                assert m['visible']>0 and (sid=='original' or m['changed']>0),(sid,m)
                row['frames'][sid]['beads_mask']=m
                dump('results.json',report)
        report['status']='engineering_passed_pending_visual_review'
    except Exception:
        report.update(status='failed',failed_task=task,traceback=traceback.format_exc()[-8000:])
        raise
    finally:
        dump('results.json',report)
        if env is not None:env.close()



TASK_PREFIX='CabinetPouring'
TASKS={
 'OpenCabinet':dict(cabinet='cabinet'),
 'PickBottle':dict(cabinet='cabinet',bottle='bottle',cap='bottle',beads='pouring'),
 'UnscrewCap':dict(bottle='bottle',cap='bottle',beads='pouring'),
 'PourBeads':dict(bottle='bottle',bowl='pouring',beads='pouring')}
SNAKE=dict(OpenCabinet='open_cabinet',PickBottle='pick_bottle',UnscrewCap='unscrew_cap',PourBeads='pour_beads',Long='long')
CATALOGS={'cabinet':'cabinet_v1/catalog.json','bottle':'v1/catalog.json'}
VIEWS={
 'OpenCabinet':([-.93,-.73,1.01],[.11,.10,.38],.75),
 'PickBottle':([-1.06,-.54,1.02],[-.06,.16,.35],.83),
 'UnscrewCap':([-.62,-.54,.46],[-.22,-.2,.14],.72),
 'PourBeads':([-.71,-.72,.86],[-.16,-.2,.16],.80)}
BEAD_CAMERA=([1,.9,.62],[1,1,.5],.61)

def validate_assets(table):
    from PIL import Image
    bowl=load_standalone('pouring_appearance')
    cabinet=load_standalone('cabinet_appearance')
    past=ast.parse(old(ROOT/'tasks'/FAMILY/'pouring_appearance.py'))
    legacy=next(n.value for n in past.body if isinstance(n,ast.Assign) and n.targets[0].id=='PALETTE')
    assert ast.literal_eval(legacy)==bowl.PALETTE
    assert all(table[v]['pouring'] in {'original',*bowl.PALETTE,*bowl.NEW_FINISHES} for v in VARIANTS)
    assert len({table[v]['pouring'] for v in VARIANTS})==11
    bodies=read(DIR/'v1/catalog.json')['schemes']
    names=set()
    for sid in VARIANTS[1:]:
        row=bodies[table[sid]['bottle']]
        p=DIR/'v1'/row['label_texture']
        s=hashlib.sha256(p.read_bytes()).hexdigest()
        assert s==row['sha256'] and s not in names
        names.add(s)
        with Image.open(p) as im:assert im.size==(388,490) and im.mode=='RGB'
        assert np.linalg.norm(np.array(row['cap_color'][:3])-row['reference_color'][:3])>.1
    tex=np.zeros((32,32,4),dtype=np.uint8);tex[...,3]=255
    for sid in VARIANTS[1:]:
        cs=read(DIR/'cabinet_v1/catalog.json')['schemes'][table[sid]['cabinet']]
        assert set(cs)=={'door','shell_top','shell_side','shell_edge','interior_side','interior_back','interior_floor','shelf','handle'}
        for f in cs.values():
            p=cabinet.finish_pixels(tex,True,f,'V')
            assert p.shape==tex.shape and np.array_equal(p[...,3],tex[...,3])
    return {'distinct_bottle_label_pngs':len(names),'legacy_bowl_beads_palette':'exact'}

def legacy_cases(task, catalog):
    for k in range(1,4):
        sid=f'variant_{k}'; ids=catalog[sid]; kw={}; roles=[]
        if k<=2 and task in ('OpenCabinet','PickBottle'):
            kw['cabinet_appearance']=dict(enabled=True,scheme_id=ids['cabinet']);roles+=['cabinet']
        if task in ('PickBottle','UnscrewCap'):
            kw['variation']=dict(appearance=dict(enabled=True,scheme_id=ids['bottle']));roles+=['bottle','cap']
        if task=='PourBeads':
            kw['pouring_appearance']=dict(enabled=True,scheme_id=ids['pouring']);roles+=['bowl','beads']
        if roles:yield sid,kw,roles


def gallery(root):
    from PIL import Image, ImageDraw

    report = read(root / 'results.json')
    for task, result in report['tasks'].items():
        frames = result.get('captures', result.get('frames', {}))
        ordered = [sid for sid in VARIANTS if sid in frames]
        if not ordered:
            continue
        boxes = result.get('same_coordinate_crops', {})
        for label, box in [('scene', None), *boxes.items()]:
            width, height = 480, 360
            columns = 3
            rows = (len(ordered)+columns-1)//columns
            board = Image.new('RGB', (width*columns, (height+26)*rows), '#182029')
            draw = ImageDraw.Draw(board)
            for i, sid in enumerate(ordered):
                camera = result.get('gallery_camera','base_camera')
                frame = frames[sid].get('files', frames[sid])[camera]
                with Image.open(root/frame['file']) as source:
                    contents = source.crop(box) if box is not None else source.copy()
                contents.thumbnail((width,height), Image.Resampling.LANCZOS)
                col,row = i%columns, i//columns
                board.paste(contents,(width*col+(width-contents.width)//2,(height+26)*row+26))
                draw.text((width*col+8,(height+26)*row+5),sid,fill='white')
            board.save(root/f'{task}_{label}_board.jpg',quality=93)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--static',action='store_true')
    p.add_argument('--approval',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--followup',choices=('label-probe','targeted','remaining','finish',*CLOSEOUT_CHECKS))
    p.add_argument('--gallery',type=Path,help='Compose boards from existing task RGB; no simulation')
    args=p.parse_args()
    if args.static: print(json.dumps(static(),ensure_ascii=False))
    elif args.gallery: gallery(args.gallery)
    elif args.approval and args.output: run(args.approval,args.output,followup=args.followup)
    else: p.error('Use --static or a separately authorized --approval and --output')
