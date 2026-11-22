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

ROOT = Path(__file__).resolve().parents[2]
BASE = 'f0a09c9d1722abc831fd5c62ae77a42c9dece95c'
FAMILY = 'drawer_plug'
DIR = ROOT / 'tasks/assets/variation' / FAMILY
VARIANTS = ('original', *(f'variant_{i}' for i in range(1, 11)))
SEED = 7
LEGACY_MAP = (dict(fixture='warm_white', charger='ivory_matte'),
              dict(fixture='neutral_grey', charger='navy_satin'),
              dict(fixture='ash_greige', charger='copper_metal'))


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
    assert not any(n in sys.modules for n in ('tasks','torch','sapien','mani_skill'))
    return dict(status='passed',family=FAMILY,scopes=list(TASKS),variants=len(VARIANTS)-1,
                legacy_catalog_values='exact',scope='CPU only',assets=extra)


def run(approval, output):
    auth=read(approval)
    head=git('rev-parse','HEAD').decode().strip()
    assert auth['approved'] is True and auth['scope']==FAMILY+'_ten_variants'
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
        return {k:group(e._drawers[i] if k=='drawer' and e.has_drawer else getattr(e,k,None))
                    for k in ('drawer','socket','charger')}
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

    def verify_bindings(e, i, sid):
        mapping=catalog[sid]
        counts={}
        adapter=e._fixture_appearance
        if adapter is not None:
            finish=adapter.catalog['schemes'][mapping['fixture']]
            for b in adapter.bindings[i]:
                m=b['material']
                params=finish.get(b['object'],{}).get(b['role'])
                if params is None:
                    params=b['native']
                    rgb=params['base_color']
                else:
                    rgb=adapter._surface_color(b,params)
                assert_finish(m,rgb,params['roughness'],params['metallic'])
                if 'live' in b:
                    p=finish.get(b['object'],{}).get(b['role'])
                    expected=adapter._texture_pixels(b['live'],p)
                    assert digest(m.base_color_texture.download())==digest(expected)
                role=b['object']+'/'+b['role']
                counts[role]=counts.get(role,0)+1
        if e._charger_appearance is not None:
            charger=e._charger_appearance.catalog
            entity=e.charger._objs[i]
            body=entity.find_component_by_type(RenderBodyComponent)
            for shape in body.render_shapes:
                role='body' if np.allclose(shape.half_size,e.charger_half) else 'prongs'
                p=charger['schemes'][mapping['charger']]['body'] if role=='body' else charger['prongs']
                for part in shape.parts:
                    assert_finish(part.material,p['base_color'],p['roughness'],p['metallic'])
                counts['charger/'+role]=counts.get('charger/'+role,0)+1
            assert counts['charger/body']==1 and counts['charger/prongs']==2
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
        if e.has_drawer:
            drawer=e._drawers[i]
            result['drawer_joints']=dict(limits=walk(drawer.get_qlimits(),None,-1),drives={
                j.name:{k:walk(getattr(j,k),None,-1) for k in ('stiffness','damping','friction','force_limit')}
                for j in drawer.active_joints})
        return result
    def task_state(e,i):
        state=walk(e.get_state_dict(),i,e.num_envs)
        state['episode_buffers']={k:walk(v,i,e.num_envs) for k,v in vars(e).items()
                                  if torch.is_tensor(v) and v.ndim and v.shape[0]==e.num_envs}
        if e.has_drawer:
            state['drawer_drive_targets']={j.name:walk(j.drive_target,None,-1)
                                           for j in e._drawers[i].active_joints}
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
    def make(task, config=None, legacy=None):
        restore_outer_rng()
        eye,at,fov=VIEWS[task]
        camera=dict(width=960,height=720,fov=fov,pose=sapien_utils.look_at(eye,at))
        return gym.make(TASK_PREFIX+task+'-Sharpa-v1',num_envs=2,sim_backend='physx_cuda',
            obs_mode='rgb+segmentation',render_mode='rgb_array',reconfiguration_freq=0,
            sensor_configs={'base_camera':camera},human_render_camera_configs=camera,
            **({'family_appearance':config} if config is not None else (legacy or {})))
    tracked=git('diff','--name-only',BASE,'HEAD','--','tasks',
                str(Path(__file__).resolve().relative_to(ROOT))).decode().splitlines()
    from importlib.metadata import version
    dump('manifest.json',dict(head=head,baseline=BASE,seed=SEED,backend='physx_cuda',
         job=os.environ['SLURM_JOB_ID'],gpu=os.environ['SLURM_JOB_GPUS'],
         versions={name:version(name) for name in ('sapien','mani_skill','torch','gymnasium','numpy')},
         asset_identity=auth['asset_identity'],
         hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in tracked}))
    report=dict(family=FAMILY,head=head,seed=SEED,job=os.environ['SLURM_JOB_ID'],tasks={},status='running')
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
        report['status']='engineering_passed_pending_visual_review'
    except Exception:
        report.update(status='failed',failed_task=task,traceback=traceback.format_exc()[-8000:])
        raise
    finally:
        dump('results.json',report)
        if env is not None:env.close()



TASK_PREFIX='DrawerPlug'
TASKS={'OpenDrawer':dict(drawer='fixture'),'PickCharger':dict(drawer='fixture',charger='charger'),
       'InsertPlug':dict(socket='fixture',charger='charger')}
SNAKE=dict(OpenDrawer='open_drawer',PickCharger='pick_charger',InsertPlug='insert_plug',Long='long')
CATALOGS={'fixture':'fixtures_v1/catalog.json','charger':'v1/catalog.json'}
VIEWS={
 'OpenDrawer':([-1.03,-.67,.79],[.14,.18,.29],.78),
 'PickCharger':([-.95,.69,1.16],[-.04,.18,.30],.73),
 'InsertPlug':([-.62,-.94,.70],[-.17,-.38,.08],.75)}

def validate_assets(table):
    fixture=load_standalone('fixture_appearance')
    cat=read(DIR/'fixtures_v1/catalog.json')
    roles={r['role'] for r in cat['drawer_mesh_roles'].values()}
    assert len(cat['drawer_mesh_roles'])==47
    for idx in VARIANTS[1:]:
        s=cat['schemes'][table[idx]['fixture']]
        assert set(s['drawer'])==roles-{'slider'}
        assert set(s['socket'])=={'shell'}
        assert s['drawer']['top']==s['drawer']['top_front_trim']
    p=read(DIR/'v1/catalog.json')
    assert p['prongs']==json.loads(old(DIR/'v1/catalog.json'))['prongs']
    live=dict(pixels=np.arange(4096,dtype=np.uint8).reshape((32,32,4)),srgb=True)
    got=fixture.FixtureAppearance._texture_pixels(live,cat['schemes']['ash_greige']['drawer']['front'])
    assert got.shape==live['pixels'].shape and np.array_equal(got[...,3],live['pixels'][...,3])
    return {'drawer_meshes':47,'charger_prongs':'exact','socket_liner':'unaltered'}

def legacy_cases(task,catalog):
    for k in range(1,4):
        sid=f'variant_{k}'; ids=catalog[sid]; kw={}; roles=[]
        if k<=2:
            kw['drawer_plug_appearance']=dict(enabled=True,scheme_id=ids['fixture'])
            roles+=['socket' if task=='InsertPlug' else 'drawer']
        if task!='OpenDrawer':
            kw['charger_appearance']=dict(enabled=True,scheme_id=ids['charger']);roles+=['charger']
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
                frame = frames[sid].get('files', frames[sid])['base_camera']
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
    p.add_argument('--gallery',type=Path,help='Compose boards from existing task RGB; no simulation')
    args=p.parse_args()
    if args.static: print(json.dumps(static(),ensure_ascii=False))
    elif args.gallery: gallery(args.gallery)
    elif args.approval and args.output: run(args.approval,args.output)
    else: p.error('Use --static or a separately authorized --approval and --output')
