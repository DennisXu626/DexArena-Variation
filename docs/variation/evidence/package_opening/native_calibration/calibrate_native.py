"""Native-only repeatability calibration; no acceptance thresholds are changed."""
import argparse,gzip,hashlib,json,os,sys
from pathlib import Path
import numpy as np
import torch
import gymnasium as gym
sys.path.insert(0,str(Path.cwd()));sys.path.insert(0,str(Path.cwd()/"tools/variation"))
import tasks
import check_ten_environment as c
from tasks.package_opening import package_opening_long as package
package.PACKAGE_URDF_PATH=Path('/mnt/ceph2/DexArena/assets/task_object_meshes/package_opening/package/mobility.urdf')
package.ROBOCASA_OBJECT_DIR=Path('/mnt/ceph2/DexArena/assets/task_object_meshes/package_opening/robocasa/objects/objaverse')
ROOT=Path('/data/home/pb/native-calibration-20261121')


def delta(a,b):
 d=c.diffs(c.plain(a),c.plain(b));return {'max':max([x['delta'] for x in d if x['delta'] is not None]+[0]),'nonnumeric':[x for x in d if x['delta'] is None],'fields':d}


def rgb(a,b,idx):
 result={}
 for k,x in a.items():
  d=np.abs(x[idx].astype(np.int16)-b[k][idx].astype(np.int16));pixels=np.any(d>0,axis=-1)
  result[k]={'max':int(d.max()),'channels':int(np.count_nonzero(d)),'pixels':int(pixels.sum()),'mean_abs':float(d.mean()),'gt1':int(np.count_nonzero(d>1)),'gt2':int(np.count_nonzero(d>2)),'coordinates':np.argwhere(pixels)[:20].tolist()}
 return result


def capture(env,info):
 t=env.unwrapped;images,seg=c.images(env,info)
 return {'images':images,'seg':seg,'object_ids':[{n:[e.per_scene_id for e in es] for n,es in c.object_entities(t,i)} for i in range(2)],'state':[c.row_state(t,i) for i in range(2)],'counters':[c.counters(t,i) for i in range(2)],'rng':[c.rng(t,i) for i in range(2)],'materials':[c.materials(t,i) for i in range(2)],'info':c.plain(info)}


def target(a,b,idx):
 out={}
 for camera in a['seg']:
  out[camera]={}
  for name,ids in a['object_ids'][idx].items():
   mask=np.isin(a['seg'][camera][idx],ids)|np.isin(b['seg'][camera][idx],b['object_ids'][idx][name]);d=np.abs(a['images'][camera][idx].astype(np.int16)-b['images'][camera][idx].astype(np.int16));v=d[mask]
   out[camera][name]={'max':int(v.max(initial=0)),'channels':int(np.count_nonzero(v)),'pixels':int(mask.sum()),'mean_abs':float(v.mean()) if v.size else 0}
 return out


def reference(cap,path):
 if path.with_suffix('.json.gz').exists():
  with gzip.open(path.with_suffix('.json.gz'),'rt') as f:other=json.load(f)
  arrays=np.load(path.with_suffix('.npz'));other['images']={k[4:]:arrays[k] for k in arrays.files if k.startswith('rgb_')};other['seg']={k[4:]:arrays[k] for k in arrays.files if k.startswith('seg_')};return other
 with gzip.open(path.with_suffix('.json.gz'),'wt') as f:json.dump({k:c.plain(v) for k,v in cap.items() if k not in ('images','seg')},f)
 np.savez_compressed(path.with_suffix('.npz'),**{'rgb_'+k:v for k,v in cap['images'].items()},**{'seg_'+k:v for k,v in cap['seg'].items()});return cap


def main():
 p=argparse.ArgumentParser();p.add_argument('family');p.add_argument('stage');p.add_argument('batch',type=int);a=p.parse_args();c.FAMILY=a.family;c.STAGE=a.stage;c.KEY='meal_appearance' if a.family=='meal' else 'package_appearance'
 if a.family=='meal':from check_meal_parallel import TASKS
 else:from check_package_opening import TASKS
 c.TASKS=TASKS
 out=ROOT/'results'/a.family/a.stage;out.mkdir(parents=True,exist_ok=True)
 result={'job':os.environ.get('SLURM_JOB_ID'),'gpu':os.environ.get('SLURM_JOB_GPUS'),'batch':a.batch,'family':a.family,'task':TASKS[a.stage],'seed_schedule':[7,7,7,19,41],'rows':[],'native_only':True}
 for rep,seed in enumerate(result['seed_schedule']):
  row={'repeat':a.batch*5+rep,'seed':seed,'partial':{}}
  env=c.make(None)
  try:
   _,info=env.reset(seed=seed);cap=capture(env,info);ref=reference(cap,out/f'seed{seed}_full')
   row['full']={'state':delta(ref['state'],cap['state']),'info':delta(ref['info'],cap['info']),'materials':delta(ref['materials'],cap['materials']),'rgb':[rgb(ref['images'],cap['images'],i) for i in range(2)]}
   for selected in (1,0):
    _,info=env.reset(seed=seed);before=capture(env,info)
    _,info=env.reset(options={'env_idx':torch.tensor([selected],device=env.unwrapped.device)});after=capture(env,info);ref=reference(after,out/f'seed{seed}_partial{selected}');other=1-selected
    row['partial'][str(selected)]={'unselected_state':delta(before['state'][other],after['state'][other]),'unselected_counters':delta(before['counters'][other],after['counters'][other]),'unselected_rng_equal':before['rng'][other]==after['rng'][other],'unselected_materials':delta(before['materials'][other],after['materials'][other]),'unselected_rgb':rgb(before['images'],after['images'],other),'selected_repeat_state':delta(ref['state'][selected],after['state'][selected]),'selected_repeat_rgb':rgb(ref['images'],after['images'],selected),'selected_repeat_target':target(ref,after,selected)}
  finally:env.close()
  env=gym.make(TASKS[a.stage],num_envs=2,sim_backend='physx_cuda',obs_mode='state',render_mode=None,reconfiguration_freq=0,robot_init_qpos_noise=0,**{c.KEY:None})
  try:
   env.reset(seed=seed);t=env.unwrapped;trace=[]
   for step in range(4):
    action=.01*torch.sin(torch.arange(env.action_space.shape[-1],device=t.device,dtype=torch.float32)+step);action=action.expand(env.action_space.shape).clone()
    _,reward,terminated,truncated,info=env.step(action);trace.append({'state':[c.row_state(t,i) for i in range(2)],'reward':c.plain(reward),'terminated':c.plain(terminated),'truncated':c.plain(truncated),'info':c.plain(info)})
   path=out/f'seed{seed}_trace.json'
   if path.exists():ref=json.loads(path.read_text());row['trace']=delta(ref,c.plain(trace))
   else:c.dump(path,trace);row['trace']=delta(c.plain(trace),c.plain(trace))
   with gzip.open(out/f'trace_batch{a.batch}_rep{rep}.json.gz','wt') as f:json.dump(c.plain(trace),f)
  finally:env.close()
  result['rows'].append(row);c.dump(out/f'batch{a.batch}.json',result);print('MEASURED',a.family,a.stage,a.batch,rep,seed,flush=True)
 c.dump(out/f'identity{a.batch}.json',{'checker_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(Path(c.__file__).read_bytes()).hexdigest(),'job':os.environ.get('SLURM_JOB_ID'),'gpu':os.environ.get('SLURM_JOB_GPUS')})


if __name__=='__main__':main()
