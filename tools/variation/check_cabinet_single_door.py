"""CPU asset check and separately approved two-task cabinet RGB shortcheck."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
BASE = 'aee41a3439287a17ce9d4c14c6320fa6f5b4579d'
CATALOG = ROOT / 'tasks/assets/variation/cabinet_pouring/cabinet_v1/catalog.json'
SOURCE_MANIFEST = ROOT / 'assets/appearance/objects/cabinet_pouring/cabinet/source_manifest.json'
ADAPTER = ROOT / 'tasks/cabinet_pouring/cabinet_appearance.py'
SEED = 7
SIZE = (1280, 960)
SCHEMES = ('original', 'oak_warm_white', 'sage_walnut')
VIEWS = {
    'OpenCabinet': dict(eye=[-.93,-.73,1.01], target=[.11,.10,.38], fov=.75, crop=[310,40,925,870]),
    'PickBottle': dict(eye=[-1.06,-.54,1.02], target=[-.06,.16,.35], fov=.83, crop=[260,65,1010,910]),
}


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def static(asset):
    import ast
    from collections import Counter
    from types import SimpleNamespace
    from xml.etree import ElementTree as ET

    catalog = load(CATALOG)
    assert list(catalog['schemes']) == list(SCHEMES)
    roles = Counter()
    meshes = catalog['meshes']
    source = load(SOURCE_MANIFEST)['files']
    assert source['mobility.urdf']['sha256'] == catalog['urdf_sha256']
    for name, info in source.items():
        assert sha(asset / name) == info['sha256'], name
    shapes = {}
    for link in ET.parse(asset/'mobility.urdf').getroot().findall('link'):
        for v in link.findall('visual'):
            p = asset/v.find('geometry/mesh').get('filename')
            lines = p.read_text().splitlines()
            mtls = {}
            for line in (p.parent/next(l.split(None,1)[1] for l in lines if l.startswith('mtllib '))).read_text().splitlines():
                if line.startswith('newmtl '):
                    slot = line.split()[1]
                    mtls[slot] = 'untextured'
                elif line.startswith('map_Kd '):
                    mtls[slot] = Path(line.split()[1]).name
            used = {line.split()[1] for line in lines if line.startswith('usemtl ')}
            row = meshes[p.name]
            assert (row['link'],row['visual']) == (link.get('name'),v.get('name'))
            assert {v['slot']: k for k,v in row['slots'].items()} == {k:mtls[k] for k in used}
            shapes[p.name] = row
            roles.update(v['role'] for v in row['slots'].values())
    assert len(shapes) == len(meshes) == 32 and sum(roles.values()) == 76
    for face in ['original-34.obj','original-35.obj']:
        assert meshes[face]['slots']['texture_1.jpg']['grain_axis'] == 'V'
    assert {s['role'] for s in meshes['original-36.obj']['slots'].values()} == {'handle'}
    for sid in SCHEMES[1:]:
        assert set(catalog['schemes'][sid]) == set(roles)-{'native_detail'}

    spec = importlib.util.spec_from_file_location('cabinet_cpu',ADAPTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    native = np.zeros((64,64,4),np.uint8)
    native[:,:,3] = 197
    a,b = [catalog['schemes'][sid] for sid in SCHEMES[1:]]
    for axis in ['U','V']:
        wood=module.finish_pixels(native,True,a['door'],axis)
        increments=[np.abs(np.diff(wood[:,:,:3].astype(float),axis=i)).mean() for i in (0,1)]
        assert increments[0 if axis=='U' else 1] > 3*increments[1 if axis=='U' else 0]
        assert np.all(wood[:,:,3] == 197)
    plain=module.finish_pixels(native,True,b['door'],'V')
    assert np.unique(plain.reshape(-1,4),axis=0).shape[0]==1

    class Texture:
        def __init__(self): self.data=native.copy()
        def upload(self,data): self.data=data.copy()
    adapter=module.CabinetAppearance({'scheme_id':'original'},2)
    for i in range(2):
        adapter.bindings[i]=[dict(role='door',
            material=SimpleNamespace(base_color=[.3,.4,.5,1.],roughness=.2,metallic=0),
            native=dict(base_color=[.3,.4,.5,1.],roughness=.2,metallic=0),
            live=dict(texture=Texture(),pixels={sid:native if sid=='original' else
                module.finish_pixels(native,True,catalog['schemes'][sid]['door'],'V') for sid in SCHEMES}))]
    for sid in SCHEMES[1:]:
        adapter.finish_reset(np.array([1]),{'cabinet_appearance':{'scheme_id':sid}})
        assert adapter.schemes==['original',sid]
        assert np.array_equal(adapter.bindings[0][0]['live']['texture'].data,native)
        assert not np.array_equal(adapter.bindings[1][0]['live']['texture'].data,native)
        adapter.finish_reset(np.array([1]),{})
        assert adapter.schemes==['original','original']
        assert np.array_equal(adapter.bindings[1][0]['live']['texture'].data,native)
        assert vars(adapter.bindings[1][0]['material'])==adapter.bindings[1][0]['native']

    paths = [ROOT/'tasks/cabinet_pouring'/f'cabinet_pouring_{t}.py' for t in ('long','open_cabinet','pick_bottle')]
    for path in paths:
        rel=path.relative_to(ROOT).as_posix()
        base=subprocess.check_output(['git','-C',str(ROOT),'show',BASE+':'+rel],encoding='utf-8')
        s=path.read_text(encoding='utf-8')
        # Remove only the exact cabinet opt-in and rendering hooks.
        s=s.replace('        cabinet_appearance=None,\n','')
        if path.stem.endswith('_long'):
            a=s.index('        self._cabinet_appearance = None\n')
            b=s.index('        self._variation = None\n',a)
            s=s[:a]+s[b:]
            s=s.replace('        if self._cabinet_appearance is not None:\n'
                        '            self._cabinet_appearance.bind(self._cabinets, CABINET_URDF_PATH)\n','')
        else:
            s=s.replace('            if self._cabinet_appearance is not None:\n'
                        '                self._cabinet_appearance.finish_reset(env_idx, options)\n','')
        assert ast.dump(ast.parse(s))==ast.dump(ast.parse(base)),rel
    assert 'sapien' not in sys.modules and 'torch' not in sys.modules and 'tasks' not in sys.modules
    return dict(status='passed',asset_files=len(source),meshes=len(meshes),slots_by_role=roles,
                protected_task_ast=True,scope='CPU asset, palette and reset stub only; no rendering')


def run(approval_path, output):
    approval=load(approval_path)
    head=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()
    approved_root=Path(approval['storage_root']).resolve(strict=True)
    assert approval['approved'] is True and approval['scope']=='cabinet_single_door_rgb'
    assert approval['frozen_head']==head and os.environ.get('SLURM_JOB_ID')
    gpu_ids=os.environ.get('SLURM_JOB_GPUS','').split(',')
    assert len(gpu_ids)==1 and gpu_ids[0].isdigit(), 'Review requires a single allocated physical GPU'
    output=output.resolve()
    assert output.is_relative_to(approved_root) and output!=approved_root
    output.mkdir(exist_ok=False)
    sys.path.insert(0,str(ROOT))
    import gymnasium as gym
    import torch
    from PIL import Image
    from mani_skill.utils import sapien_utils
    from sapien.render import RenderBodyComponent
    import tasks  # noqa: F401
    from tasks.cabinet_pouring.cabinet_appearance import FIELDS

    def dump(name, data):
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    def digest(array):
        return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()

    def batch_state(env, idx):
        def rec(v):
            if isinstance(v,dict):
                return {k:rec(i) for k,i in v.items()}
            if isinstance(v,torch.Tensor):
                return (v[idx] if v.ndim and v.shape[0]==env.num_envs else v).detach().cpu().tolist()
            if isinstance(v,np.ndarray):
                return (v[idx] if v.ndim and v.shape[0]==env.num_envs else v).tolist()
            return v
        return rec(env.get_state_dict())

    def snapshot(env, i):
        cabinet_ids={raw.entity.per_scene_id for link in env._cabinets[i].get_links() for raw in link._objs}
        cabinet, other = {}, {}
        tex_cache = {}
        for ent in env.scene.sub_scenes[i].entities:
            body=ent.find_component_by_type(RenderBodyComponent)
            if body is None: continue
            is_cabinet=ent.per_scene_id in cabinet_ids
            rows=[]
            for shape in body.render_shapes:
                for part in shape.parts:
                    m=part.material
                    tex=m.base_color_texture
                    key=None if tex is None else tex.filename
                    if tex is not None and (is_cabinet or not key or key not in tex_cache):
                        pixels=digest(tex.download())
                        if not is_cabinet and key: tex_cache[key]=pixels
                    else:
                        pixels=None if tex is None else tex_cache[key]
                    rows.append([np.asarray(getattr(m,k)).tolist() for k in FIELDS]+[
                        float(m.transmission),pixels])
            (cabinet if is_cabinet else other)[ent.per_scene_id]=rows
        return cabinet,other

    def render(env):
        return env.render().detach().cpu().numpy()[...,:3].copy()

    torch_rng=(torch.random.get_rng_state().clone(),torch.cuda.get_rng_state().clone())
    def construct(task, camera, **opt):
        torch.random.set_rng_state(torch_rng[0])
        torch.cuda.set_rng_state(torch_rng[1])
        return gym.make(f'CabinetPouring{task}-Sharpa-v1',num_envs=2,sim_backend='physx_cuda',
                        obs_mode='rgb',render_mode='rgb_array',reconfiguration_freq=0,
                        human_render_camera_configs=camera,**opt)
    report=dict(commit=head,job_id=os.environ['SLURM_JOB_ID'],seed=SEED,results={})
    for task,view in VIEWS.items():
        camera=dict(pose=sapien_utils.look_at(view['eye'],view['target']),fov=view['fov'],
                    width=SIZE[0],height=SIZE[1])
        with_native=construct(task,camera)
        try:
            with_native.reset(seed=SEED); n=with_native.unwrapped
            state=[batch_state(n,i) for i in (0,1)]
            ref=render(with_native); mats=[snapshot(n,i) for i in (0,1)]
            angle=n.cabinet.get_qpos().detach().cpu().numpy()[:,0].tolist()
            target_angle=0 if task=='OpenCabinet' else np.pi/2
            np.testing.assert_allclose(angle,target_angle,atol=1e-5,rtol=0)
        finally:
            with_native.close()
        env=construct(task,camera,cabinet_appearance=dict(enabled=True,scheme_id='original'))
        try:
            e=env.unwrapped
            files=[]
            for sid in SCHEMES:
                env.reset(seed=SEED,options={'cabinet_appearance':{'scheme_id':sid}})
                assert [batch_state(e,i) for i in (0,1)] == state
                rgb=render(env)
                sig=[snapshot(e,i) for i in (0,1)]
                assert all(sig[i][1]==mats[i][1] for i in (0,1))
                assert e._cabinet_appearance.schemes==[sid,sid]
                if sid=='original':
                    assert np.array_equal(ref,rgb) and sig==mats
                else:
                    assert not np.array_equal(ref,rgb) and sig[0][0]!=mats[0][0]
                    for row in e._cabinet_appearance.bindings[0]:
                        finish=e._cabinet_appearance.catalog['schemes'][sid][row['role']]
                        m=row['material']
                        assert abs(m.roughness-finish['roughness'])<1e-6
                        assert abs(m.metallic-finish['metallic'])<1e-6
                        if 'live' in row:
                            live=row['live']
                            assert np.array_equal(live['texture'].download(),live['pixels'][sid])
                file=output/f'{task}_{sid}_env0.png'
                Image.fromarray(rgb[0]).save(file)
                files.append(dict(file=file.name,scheme_id=sid,sha256=sha(file)))
            dump(f'{task}_capture.json',dict(task=f'CabinetPouring{task}-Sharpa-v1',env_idx=0,
                 seed=SEED,door_qpos=angle[0],camera=view,resolution=SIZE,frames=files,
                 bottle='native' if task=='PickBottle' else 'absent'))
            for sid in SCHEMES[1:]:
                env.reset(seed=SEED,options={'cabinet_appearance':{'scheme_id':sid}})
                env.reset(seed=SEED,options={'cabinet_appearance':{'scheme_id':'original'}})
                assert [snapshot(e,i) for i in (0,1)]==mats
                assert np.array_equal(render(env),ref)
            for sid in SCHEMES[1:]:
                env.reset(seed=SEED)
                before=snapshot(e,0); before_state=batch_state(e,0)
                pre=render(env); before_outside=snapshot(e,1)[1]
                # No physics step; native seed/zero display changes in env0.
                env.reset(seed=SEED,options={'env_idx':torch.tensor([1],device=e.device),
                                            'cabinet_appearance':{'scheme_id':sid}})
                post=render(env)
                assert batch_state(e,0)==before_state and snapshot(e,0)==before
                assert snapshot(e,1)[1]==before_outside
                assert np.array_equal(pre[0],post[0])
                assert snapshot(e,1)[0]!=mats[1][0] and e._cabinet_appearance.schemes==['original',sid]
                assert not np.array_equal(pre[1],post[1])
            report['results'][task]=dict(restore='passed',isolation='passed',
                                         other_materials='unchanged',door_qpos=angle)
            dump('RESULTS.json',report)
        finally:
            env.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--static-asset',type=Path)
    p.add_argument('--approval',type=Path)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.static_asset is not None: print(json.dumps(static(args.static_asset),ensure_ascii=False))
    elif args.approval is not None and args.output is not None: run(args.approval,args.output)
    else: p.error('use --static-asset or a separately approved --approval and --output')
