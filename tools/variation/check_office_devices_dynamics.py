"""Office CPU dynamics for every catalog scheme, with the shared exact comparator."""
import argparse
import copy
from importlib import metadata
import json
import os
import subprocess
from pathlib import Path
import sys
import time
import traceback

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from tools.variation import check_furniture_dynamics as D
from tools.variation import check_office_devices_runtime as R

ROOT=R.ROOT
TASKS=tuple(R.TASKS)
SCHEMES=('native_off','native_repeat',*R.DEVICE_SCHEMES)
COMMON=dict(num_envs=1,sim_backend='physx_cpu',obs_mode='state',control_mode='pd_joint_pos',reward_mode='sparse',reconfiguration_freq=0,render_mode=None)


def source_hashes():return R.source_hashes()


def snapshot(base,obs,info,reward=None,terminated=None,truncated=None):
    return D.numeric_leaves({'runtime_state':R.C.snapshot(base),'controller':R.C.controller_state(base,0),
        'obs':obs,'info':info,'reward':reward,'terminated':terminated,'truncated':truncated})


def worker(args):
    os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('MKL_NUM_THREADS','1')
    sys.path.insert(0,str(ROOT));os.chdir(ROOT);R.configure_runtime()
    np,torch,gym,sapien=R.np,R.torch,R.gym,R.sapien
    import tasks
    torch.set_num_threads(1);env=None;start=time.perf_counter()
    legacy_mouse = dict(zip(R.DEVICE_SCHEMES[1:3], R.SCHEMES['ClickMouse'][1:3], strict=True))
    actual = ('native_off' if args.scheme in ('native_off','native_repeat') else
              legacy_mouse.get(args.scheme, args.scheme) if args.task == 'ClickMouse' else args.scheme)
    config={'enabled':False} if actual=='native_off' else {'enabled':True,'scheme_id':actual,'seed':71}
    report={'status':'running','task':args.task,'scheme':args.scheme,'actual_scheme_id':actual,'appearance_config':config,
        'seed':args.seed,'constructor_kwargs':COMMON,'source_sha256':source_hashes(),'requested_control_steps':args.steps,
        'python':sys.version,'packages':{p:metadata.version(p) for p in ('sapien','mani_skill','torch','numpy','gymnasium')},
        'sapien_binary':{'sha256':D.digest(sapien.pysapien.__file__)},'control_steps':0,'physics_steps':0,'image_capture':False,
        'asset_files':R.asset_hashes(),'external_files':R.external_hashes()}
    try:
        report['object_asset_root'] = R.require_model_asset_root(args.task)
        if args.task == 'ClickMouse':
            report['mouse_collision_identity'] = R.mouse_collision_identity()
        env=gym.make('OfficeDesk'+args.task+'-Sharpa-v1',**{R.key_for(args.task):config},**COMMON)
        base=env.unwrapped;assert not base.gpu_sim_enabled and base.device.type=='cpu'
        report['asset_closure_sha256']=R.asset_closure(base)
        obs,info=env.reset(seed=args.seed,options={'reconfigure':True});report['backend']=str(base.backend)
        release_targets = R.verify_release_targets(base, args.task)
        if release_targets is not None:
            report['release_target_readback'] = release_targets
        report['sim_steps_per_control']=int(base._sim_steps_per_control);a=R.adapter(base)
        assert (a is None)==(actual=='native_off')
        stable_materials=R.C.materials(base);stable_physical=R.physical(base)
        stable_records=copy.deepcopy(a.records) if a else None
        if args.actions.exists():actions=np.load(args.actions,allow_pickle=False)
        else:
            assert args.scheme=='native_off'
            initial=base.agent.robot.get_qpos().detach().cpu().numpy().reshape(env.action_space.shape)
            initial=np.clip(initial,env.action_space.low,env.action_space.high)
            actions=np.repeat(initial[None],args.steps,axis=0).astype(np.float32)
            channels=np.arange(actions[0].size,dtype=np.float64).reshape(actions[0].shape)
            for step in range(15,min(50,args.steps)):actions[step]+=.015*np.sin((step-15)*.21+channels*.37)
            actions=np.clip(actions,env.action_space.low,env.action_space.high);np.save(args.actions,actions,allow_pickle=False)
        assert actions.shape==(args.steps,*env.action_space.shape) and all(env.action_space.contains(action) for action in actions)
        report['actions']={'sha256':D.digest(args.actions),'shape':list(actions.shape),'legal':True,'sequence':'initial hold, small sine targets, hold'}
        trajectory=[snapshot(base,obs,info)]
        for action in actions:
            obs,reward,terminated,truncated,info=env.step(torch.from_numpy(action.copy()))
            report['control_steps']+=1;report['physics_steps']+=report['sim_steps_per_control']
            trajectory.append(snapshot(base,obs,info,reward,terminated,truncated))
            if a is not None:assert a.schemes==[actual] and a.records==stable_records
        assert R.C.materials(base)==stable_materials and R.physical(base)==stable_physical
        assert source_hashes()==report['source_sha256']
        assert R.asset_hashes()==report['asset_files'] and R.external_hashes()==report['external_files']
        assert R.closure_unchanged(report['asset_closure_sha256'])
        if args.task == 'ClickMouse':
            assert report['mouse_collision_identity'] == R.mouse_collision_identity()
            report['mouse_collision_inputs_unchanged'] = True
        torch.save(trajectory,args.output/'trajectory.pt');report.update(status='completed',materials_and_geometry_stable=True)
    except BaseException:report.update(status='failed',traceback=traceback.format_exc());raise
    finally:
        report['asset_hashes_unchanged']=R.asset_hashes()==report['asset_files'] and R.closure_unchanged(report.get('asset_closure_sha256',{}))
        report['external_hashes_unchanged']=R.external_hashes()==report['external_files']
        report['elapsed_seconds']=time.perf_counter()-start;D.dump(args.output/'run.json',report)
        if env is not None:env.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--steps',type=D.positive_int,default=60)
    parser.add_argument('--seed',type=int,default=7);parser.add_argument('--worker',action='store_true')
    parser.add_argument('--task',choices=TASKS);parser.add_argument('--scheme',choices=SCHEMES);parser.add_argument('--actions',type=Path)
    parser.add_argument('--sapien-root',type=Path);parser.add_argument('--artifact',type=Path);parser.add_argument('--physx-gpu-dir',type=Path)
    args=parser.parse_args();args.output=args.output.resolve()
    if args.worker:
        worker(args)
        return 0
    if not all((args.sapien_root,args.artifact,args.physx_gpu_dir)):
        parser.error('formal CPU workers require --sapien-root, --artifact and --physx-gpu-dir')
    D.TASKS,D.SCHEMES,D.ROOT,D.__file__=TASKS,SCHEMES,ROOT,str(Path(__file__).resolve())
    D.source_hashes=source_hashes
    actual_run=subprocess.run
    def private_worker(command,*positional,**kwargs):
        if (isinstance(command,list) and '--worker' in command
                and len(command)>2 and Path(command[2]).resolve()==Path(__file__).resolve()):
            extra=command[3:];output_index=extra.index('--output');branch=extra[output_index+1]
            extra=extra[:output_index]+extra[output_index+2:]
            command=[sys.executable,'-B',str(ROOT/'tools/variation/sapien_sdk/run_task_check.py'),
                '--repo-root',str(ROOT),'--checker','tools/variation/check_office_devices_dynamics.py',
                '--sapien-root',str(args.sapien_root),'--artifact',str(args.artifact),
                '--physx-gpu-dir',str(args.physx_gpu_dir),'--output',branch,*extra]
        return actual_run(command,*positional,**kwargs)
    subprocess.run=private_worker
    external_before=R.external_hashes()
    try:code=D.main(args)
    finally:subprocess.run=actual_run
    summary=json.loads((args.output/'summary.json').read_text(encoding='utf-8'))
    summary['external_files']=external_before;summary['external_hashes_unchanged']=external_before==R.external_hashes()
    if not summary['external_hashes_unchanged']:summary['status']='failed';code=1
    D.dump(args.output/'summary.json',summary)
    return code


if __name__=='__main__':raise SystemExit(main())
