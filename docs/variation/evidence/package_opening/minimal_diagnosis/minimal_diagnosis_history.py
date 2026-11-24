"""Minimal controlled diagnostics; no production edits or acceptance changes."""
import copy,hashlib,json,os,sys
from pathlib import Path
import gymnasium as gym
import numpy as np
import torch
sys.path.insert(0,str(Path.cwd()));sys.path.insert(0,str(Path.cwd()/"tools/variation"))
import tasks
import check_ten_environment as c
from tasks.package_opening import package_opening_long as package
package.PACKAGE_URDF_PATH=Path('/mnt/ceph2/DexArena/assets/task_object_meshes/package_opening/package/mobility.urdf');package.ROBOCASA_OBJECT_DIR=Path('/mnt/ceph2/DexArena/assets/task_object_meshes/package_opening/robocasa/objects/objaverse')
OUT=Path('/data/home/pb/minimal-diagnosis-20261121')/('results-'+os.environ['SLURM_JOB_ID']);OUT.mkdir(parents=True,exist_ok=True)


def diff(a,b):
 d=c.diffs(c.plain(a),c.plain(b));return {'max':max([x['delta'] for x in d if x['delta'] is not None]+[0]),'fields':d}


def rgb(a,b,idx=0):
 out={}
 for name,x in a['images'].items():
  delta=np.abs(x[idx].astype(np.int16)-b['images'][name][idx].astype(np.int16));points=np.argwhere(np.any(delta>0,axis=-1));out[name]={'max':int(delta.max()),'channels':int(np.count_nonzero(delta)),'pixels':points[:30].tolist()}
 return out


def controls(t):
 out={}
 def visit(agent,label):
  robot=getattr(agent,'robot',None)
  if robot is not None:
   out[label+'/robot']= {n:c.plain(getattr(robot,n)()) for n in ('get_qpos','get_qvel','get_drive_targets','get_drive_velocities') if hasattr(robot,n)}
  ctl=getattr(agent,'controller',None)
  if ctl is not None and hasattr(ctl,'get_state'):out[label+'/controller']=c.plain(ctl.get_state())
  children=getattr(agent,'agents',[])
  if isinstance(children,dict):children=children.values()
  for i,a in enumerate(children):visit(a,label+'/'+str(i))
 visit(t.agent,'agent');return out


report={'job':os.environ['SLURM_JOB_ID'],'gpu':os.environ.get('SLURM_JOB_GPUS'),'meal':{},'package':{},'production_changed':False}
c.FAMILY='meal';c.KEY='meal_appearance'
from check_meal_parallel import TASKS as MEAL
c.TASKS=MEAL
for stage in ('open','long'):
 c.STAGE=stage;caps={};native_state=None
 for name,config in [('native',None),('enabled_original',{'enabled':True}),('variant_then_original',{'enabled':True}),('history_native',None),('history_original',{'enabled':True}),('history_variant_then_original',{'enabled':True})]:
  env=c.make(config);t=env.unwrapped
  try:
   if name.startswith('history_'):
    for scheme in ['original']+[f'variant_{i}' for i in range(1,11)]:
     request=scheme if name=='history_variant_then_original' else 'original'
     _,info=env.reset(seed=7,options={} if config is None else {c.KEY:{'scheme_id':request}});c.capture(env,info)
     if scheme!='original':
      _,info=env.reset(seed=7,options={} if config is None else {c.KEY:{'scheme_id':'original'}});c.capture(env,info)
   for selected in (1,0):
    options={} if config is None else {c.KEY:{'per_env':{'0':{'scheme_id':'variant_1' if name.endswith('variant_then_original') else 'original'},'1':{'scheme_id':'variant_2' if name.endswith('variant_then_original') else 'original'}}}}
    _,info=env.reset(seed=7,options=options);before=c.capture(env,info)
    options={'env_idx':torch.tensor([selected],device=t.device)}
    if config is not None:options[c.KEY]={'per_env':{str(selected):{'scheme_id':'original'}}}
    _,info=env.reset(options=options);after=c.capture(env,info)
   caps[name]=after
   if name=='native':native_state=copy.deepcopy(t.get_state_dict())
   if name=='variant_then_original':
    # Diagnostic intervention only: test whether matched native state removes RGB difference.
    def subset(x):
     if isinstance(x,dict):return {k:subset(v) for k,v in x.items() if not (k.startswith(('procedural_box_','partnet_box_')) and k.endswith('_1'))}
     if torch.is_tensor(x):return x[:1].clone() if x.ndim and x.shape[0]==2 else x.clone()
     return copy.deepcopy(x)
    try:
     t.set_state_dict(subset(native_state),env_idx=torch.tensor([0],device=t.device));caps['after_native_state_write']=c.capture(env,t.get_info())
    except Exception as error:report.setdefault('diagnostic_intervention_errors',{})[stage]=repr(error)
   from PIL import Image
   for cam,x in after['images'].items():Image.fromarray(x[0]).save(OUT/f'{stage}_{name}_{cam}.png')
  finally:env.close()
 base=caps['native'];result={}
 for name,cap in caps.items():
  result[name]={'state':diff(base['state'],cap['state']),'materials':diff(base['materials'][0],cap['materials'][0]),'rgb':rgb(base,cap),'controls_note':'no physical step in Meal diagnostic'}
 report['meal'][stage]=result;c.dump(OUT/'report.json',report);print('MEAL DIAG',stage,{k:v['rgb']['human'] for k,v in result.items()},flush=True)

c.dump(OUT/'identity.json',{'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(Path(c.__file__).read_bytes()).hexdigest(),'job':os.environ['SLURM_JOB_ID']});raise SystemExit(0)

c.FAMILY='package';c.KEY='package_appearance'
from check_package_opening import TASKS

def snapshot(env):
 t=env.unwrapped;return {'state':[c.row_state(t,i) for i in range(2)],'controls':controls(t),'qpos':c.plain(t.box.qpos),'qvel':c.plain(t.box.qvel)}


def trace(env,scheme=None):
 _,info=env.reset(seed=7,options={} if scheme is None else {c.KEY:{'scheme_id':scheme}});result={'initial':snapshot(env),'steps':[]}
 for i in range(4):
  t=env.unwrapped;action=.01*torch.sin(torch.arange(env.action_space.shape[-1],device=t.device,dtype=torch.float32)+i);action=action.expand(env.action_space.shape).clone()
  _,reward,terminated,truncated,info=env.step(action);result['steps'].append({'state':snapshot(env),'reward':c.plain(reward),'terminated':c.plain(terminated),'info':c.plain(info)})
 return result

for name,config,schemes in [('native',None,[None,None]),('enabled_original',{'enabled':True},['original','original']),('fresh_variant',{'enabled':True,'scheme_id':'variant_1'},['variant_1']),('original_then_variant',{'enabled':True},['original','variant_1'])]:
 env=gym.make(TASKS['long'],num_envs=2,sim_backend='physx_cuda',obs_mode='state',render_mode=None,reconfiguration_freq=0,robot_init_qpos_noise=0,package_appearance=config)
 try:report['package'][name]=[trace(env,x) for x in schemes]
 finally:env.close()
 c.dump(OUT/'report.json',report)
p=report['package'];pairs={}
for label,a,b in [('fresh_original_vs_native',p['native'][0],p['enabled_original'][0]),('fresh_variant_vs_native',p['native'][0],p['fresh_variant'][0]),('native_episode2_vs_episode1',p['native'][0],p['native'][1]),('matched_history_variant_vs_native',p['native'][1],p['original_then_variant'][1]),('matched_history_original_vs_native',p['native'][1],p['enabled_original'][1])]:
 pairs[label]={'initial':diff(a['initial'],b['initial']),'steps':[diff(x,y) for x,y in zip(a['steps'],b['steps'])]}
report['package_comparisons']=pairs;c.dump(OUT/'report.json',report)
c.dump(OUT/'identity.json',{'job':os.environ['SLURM_JOB_ID'],'gpu':os.environ.get('SLURM_JOB_GPUS'),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(Path(c.__file__).read_bytes()).hexdigest()})
print('PACKAGE DIAG',{k:[x['max'] for x in v['steps']] for k,v in pairs.items()},flush=True)
