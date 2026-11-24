"""Quantify independent native fixed-action trace variation without changing tolerances."""
import hashlib,json,os,sys
from pathlib import Path
import gymnasium as gym
import torch
sys.path.insert(0,str(Path.cwd()))
import tasks
import check_ten_environment as check
from check_package_opening import TASKS
from tasks.package_opening import package_opening_long as package
check.FAMILY="package"
root=Path('/data/home/pb/package-a4a5-r2-20261120')
assets=Path('/mnt/ceph2/DexArena/assets/task_object_meshes/package_opening')
package.PACKAGE_URDF_PATH=assets/'package/mobility.urdf';package.ROBOCASA_OBJECT_DIR=assets/'robocasa/objects/objaverse'
previous_path=root/'trace-123847/trace.json';previous=json.loads(previous_path.read_text())
result={"job":os.environ.get("SLURM_JOB_ID"),"gpu":os.environ.get("SLURM_JOB_GPUS"),"previous_trace_sha256":hashlib.sha256(previous_path.read_bytes()).hexdigest(),"stages":{}}
for stage,task in TASKS.items():
 env=gym.make(task,num_envs=2,sim_backend="physx_cuda",obs_mode="state",render_mode=None,reconfiguration_freq=0,robot_init_qpos_noise=0)
 try:
  env.reset(seed=7);t=env.unwrapped;trace=[]
  for i in range(4):
   action=.01*torch.sin(torch.arange(env.action_space.shape[-1],device=t.device,dtype=torch.float32)+i);action=action.expand(env.action_space.shape).clone()
   _,reward,terminated,truncated,info=env.step(action)
   trace.append({"state":[check.row_state(t,k) for k in range(2)],"reward":check.plain(reward),"terminated":check.plain(terminated),"truncated":check.plain(truncated),"info":check.plain(info)})
  differences=check.diffs(previous['stages'][stage]['native_trace'],check.plain(trace))
  numeric=[d['delta'] for d in differences if d['delta'] is not None]
  result['stages'][stage]={"trace":trace,"differences":differences,"max_numeric_delta":max(numeric,default=0),"nonnumeric_differences":[d for d in differences if d['delta'] is None]}
  print('NATIVE NOISE',stage,result['stages'][stage]['max_numeric_delta'],flush=True)
 finally:env.close()
check.dump(root/('native-noise-'+os.environ['SLURM_JOB_ID']+'.json'),result)
