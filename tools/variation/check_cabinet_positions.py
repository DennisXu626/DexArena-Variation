"""One bounded two-environment Cabinet position check; output is flushed per point."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path

import gymnasium as gym
import numpy as np
import torch
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
import tasks


def value(t):
    return t.detach().cpu().numpy()


def env_digest(state, index):
    if isinstance(state, dict):
        return {k: env_digest(v, index) for k, v in state.items()}
    return hashlib.sha256(value(state[index]).tobytes()).hexdigest()


def rotation(yaw):
    a = math.radians(yaw)
    return np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def setup_motion(e, i):
    robot = e.agent.robot
    joints = [robot.joints_map[n] for n in e.agent.arm_joint_names]
    poses = np.stack([value(j.global_pose.raw_pose[i]) for j in joints])
    axes = Rotation.from_quat(poses[:, [4, 5, 6, 3]]).as_matrix()[:, :, 0]
    arm = e.agent.controller.controllers['arm']
    ids = arm.active_joint_indices
    q0 = value(robot.qpos[i, ids]).astype(float)
    bounds = value(robot.get_qlimits()[i, ids]).astype(float)
    tips = np.stack([value(link.pose.p[i]) for link in e.agent.tip_links[:2]])
    return poses[:, :3], axes, q0, bounds, tips


def solve_arm(chain, goals, previous):
    origins, axes, home, limits, tips = chain
    def residual(q):
        points = tips.copy()
        for index in range(len(q)-1, -1, -1):
            axis = axes[index] * (q[index] - home[index])
            points = Rotation.from_rotvec(axis).apply(points-origins[index])+origins[index]
        return (points-goals).flatten()
    q = least_squares(residual, np.clip(previous, *limits.T), bounds=limits.T,
                      max_nfev=45, ftol=1e-6, xtol=1e-6).x
    err = np.linalg.norm(residual(q).reshape(2, 3), axis=1).max()
    return q, float(err)


def motion_targets(e, task, i, yaw, data):
    chain = setup_motion(e, i)
    tips = chain[-1]
    normal = np.r_[rotation(yaw)[:, 0], 0.]
    tangent = np.r_[rotation(yaw)[:, 1], 0.]
    if task=='OpenCabinet':
        center = np.asarray(data['handle_xyz'])
        exit_vector = -.04*normal
    elif task=='UnscrewCap':
        center = value(e._cap_p()[i])
        exit_vector = np.zeros(3)
    else:
        center = value(e._source_pose().p[i]).copy()
        center[2] += .01
        exit_vector = -.10*normal
        if task=='PourBeads':
            target = value(e.target.pose.p[i]).copy()
            direction = center[:2]-target[:2]
            target[:2] += .075*direction/np.linalg.norm(direction)
            target[2] += e.target_z_hi+.04-e.source_z_hi
            exit_vector = target-center
    if np.dot(tips[1]-tips[0], tangent)<0:
        tangent = -tangent
    span=np.linalg.norm(tips[1]-tips[0])
    spread=np.stack([-tangent,tangent])*span/2
    best=None
    for axis in (spread, .70710678*spread+np.outer([-1,1],[0,0,span*.35355339])):
        q=chain[2]
        solutions=[];errors=[]
        for offset in (-.045*normal, np.zeros(3),exit_vector):
            q,err=solve_arm(chain, center+offset+axis, q)
            solutions.append(q.tolist());errors.append(err)
        if best is None or max(errors)<max(best['tip_errors_m']):
            best=dict(tip_errors_m=errors,arm_targets=solutions,target_xyz=center.tolist(),
                      exit_vector=exit_vector.tolist(),ik_pass=max(errors)<=.015)
    return best


def physical_attempt(env,e,task,i,ik):
    ctrl=e.agent.controller
    parts=ctrl.controllers
    action=torch.empty((2,env.action_space.shape[-1]),device=e.device)
    for key,(lo,hi) in ctrl.action_mapping.items():
        action[:,lo:hi]=e.agent.robot.qpos[:,parts[key].active_joint_indices]
    arm_lo,arm_hi=ctrl.action_mapping['arm']
    hand_lo,hand_hi=ctrl.action_mapping['hand']
    hand0=action[i,hand_lo:hand_hi].clone()
    lim=e.agent.robot.get_qlimits()[i,parts['hand'].active_joint_indices]
    names=e.agent.hand_joint_names
    close=hand0.clone()
    for j,name in enumerate(names):
        if name.endswith(('PIP','DIP','_IP','MCP_FE')):
            close[j]=torch.clamp(hand0[j]+.45,min=lim[j,0],max=lim[j,1])
    contacts=[];distances=[];grasp=False
    target = e.door_link if task=='OpenCabinet' else (
        e.cap_fixed if task=='UnscrewCap' else e.source)
    for phase,q in enumerate(ik['arm_targets']):
        start=action[i,arm_lo:arm_hi].clone()
        for k in range(12):
            f=min((k+1)/8,1.)
            action[i,arm_lo:arm_hi]=torch.lerp(start,start.new_tensor(q),f)
            if phase==1:action[i,hand_lo:hand_hi]=torch.lerp(hand0,close,f)
            env.step(action)
        tip=np.mean([value(t.pose.p[i]) for t in e.agent.tip_links[:2]],axis=0)
        distances.append(float(np.linalg.norm(tip-ik['target_xyz'])))
        links=[e.agent.robot.links_map[n] for n in e.agent.grip_link_names]
        contacts.append(max(float(torch.linalg.norm(e.scene.get_pairwise_contact_forces(target,l)[i])) for l in links))
        if task in ('PickBottle','PourBeads'):grasp |= bool(e._is_grasping(e.source)[i].item())
    contact=max(contacts)>1e-4
    result=dict(contact_N=contacts,tip_midpoint_distance_m=distances,native_grasp_seen=grasp)
    if task=='OpenCabinet':
        angle=float(e.cabinet.qpos[i,0]);result.update(angle_rad=angle,passed=angle>=math.radians(3) and contact)
    elif task=='UnscrewCap': result.update(passed=contact and min(distances)<.045)
    elif task=='PickBottle':
        out=bool(e._bottle_out_of_cabinet(e._source_pose())[i].item())
        result.update(bottle_out=out,passed=grasp and out)
    else:
        p=e.source.pose;mouth=p.p[i]+p.to_transformation_matrix()[i,:3,2]*e.source_z_hi
        rel=value(mouth-e.target.pose.p[i]);radius=float(np.linalg.norm(rel[:2]))
        result.update(mouth_rel_m=rel.tolist(),passed=bool(grasp and abs(radius-.09)<.025 and rel[2]>e.target_z_hi))
    return result


def run(root):
    source=Path(__file__).resolve().parents[2]
    table=list(csv.DictReader((source/'tools/variation/cabinet_position_points.csv').open()))
    region='cabinet_pouring.bottle_table.xy_v2'
    result=dict(job=os.environ['SLURM_JOB_ID'],tasks={},status='running')
    root.mkdir(exist_ok=False)
    def flush():
        tmp=root/'results.tmp'
        tmp.write_text(json.dumps(result,indent=2,allow_nan=False));tmp.replace(root/'results.json')
    for task in ('PickBottle','OpenCabinet','UnscrewCap','PourBeads'):
        task_id='CabinetPouring'+task+'-Sharpa-v1'
        config=dict(variation={'initial_pose':dict(enabled=True,mode='native',region_id=region)}) if task in ('PickBottle','UnscrewCap') else {}
        record=result['tasks'][task]=dict(task_id=task_id,kwargs=config,points=[])
        flush()
        with __import__('contextlib').closing(gym.make(task_id,num_envs=2,sim_backend='physx_cuda',obs_mode='state',reconfiguration_freq=0,**config)) as env:
            e=env.unwrapped
            env.reset(seed=7)
            rows=[p for p in table if p['tasks']==task]
            for p in rows:
                i=int(p['env']); other=1-i
                req=json.loads(p['options'])
                opts=dict(req,env_idx=torch.tensor([i],device=e.device))
                seed=int(p['seed']); state=env_digest(e.get_state_dict(),other)
                item=dict(id=p['id'],figure=p['figure'],task_id=task_id,seed=seed,env=i,options=req,status='resetting')
                record['points'].append(item);flush()
                try:env.reset(seed=seed,options=opts)
                except ValueError as error:
                    if p['kind']!='reject' or 'Shelf position outside approved bounds' not in str(error):raise
                    item.update(status='rejected',reason=str(error),passive_unchanged=state==env_digest(e.get_state_dict(),other))
                    flush();assert item['passive_unchanged'];continue
                assert p['kind']!='reject'
                item['passive_unchanged']=state==env_digest(e.get_state_dict(),other)
                flush();assert item['passive_unchanged'],item['id']
                layout=req.get('position_layout',{}).get(str(i),{})
                yaw=layout.get('yaw_deg',15); checks={}
                if e.has_cabinet:
                    cab=value(e.cabinet.pose.raw_pose[i]);ang=math.degrees(2*math.atan2(cab[6],cab[3]))
                    door=float(e.cabinet.qpos[i,0]);item.update(cabinet_pose=cab.tolist(),yaw_deg=ang,door_rad=door)
                    checks.update(cabinet=np.allclose(cab[:2],layout.get('cabinet_xy_m',[.14,.12]),atol=1e-6),
                                  yaw=abs(ang-yaw)<1e-4,door=abs(door-(math.pi/2 if task=='PickBottle' else 0))<1e-4,
                                  cabinet_z=abs(cab[2]-e.cabinet_z)<1e-5)
                    handle=e._door_handle_xyz_nominal.copy()
                    handle[:2]=cab[:2]+rotation(yaw-15)@(handle[:2]-e.cabinet_xy)
                    item['handle_xyz']=handle.tolist()
                if e.has_bottle:
                    pos=value(e._source_pose().raw_pose[i]);item['bottle_pose']=pos.tolist()
                    zmin=e.source_z_lo+pos[2]
                    expected_height=e.shelf_ceiling_z if task=='PickBottle' else 0.
                    checks['support_height']=abs(zmin-expected_height-.001)<.0001
                    item['support_clearance_m']=float(zmin-expected_height)
                    if task=='PickBottle':
                        shelf=rotation(-yaw)@(pos[:2]-cab[:2]);item['shelf_xy_m']=shelf.tolist()
                        checks['shelf_xy']=np.allclose(shelf,layout.get('shelf_xy_m',[-.21,-.005]),atol=2e-6)
                        item['shelf_edge_margin_m']=float(shelf[0]+.2466840571-e._source_bottom_support_radius)
                        checks['full_ring']=item['shelf_edge_margin_m']>=-1e-6
                    if task=='UnscrewCap':
                        checks['final_B']=int(e._active_bottle_rep[i])==1
                        checks['table_xy']=np.allclose(pos[:2],req['variation']['initial_pose']['xy_m'],atol=2e-6)
                    particles=value(e._particle_positions()[i]) if hasattr(e,'_particle_positions') else np.stack([value(x.pose.p[i]) for x in e.particles])
                    delta=np.abs(particles-pos[:3]-value(e._particle_local_xyz))
                    item['particle_offset_max_m']=float(delta.max())
                    checks['particles']=len(particles)==16 and delta.max()<.004
                if task=='PourBeads':
                    bowl=value(e.target.pose.raw_pose[i]);item['bowl_pose']=bowl.tolist()
                    gap=float(np.linalg.norm(bowl[:2]-pos[:2])-.09-.030278)
                    checks.update(bowl_xy=np.allclose(bowl[:2],layout['bowl_xy_m'],atol=1e-6),bowl_z=abs(bowl[2]+e.target_z_lo-.001)<1e-5,xy_gap=gap>=0)
                    item['bowl_bottle_gap_m']=gap
                item['checks']={k:bool(v) for k,v in checks.items()}
                item['status']='init_pass' if all(checks.values()) else 'init_fail'
                flush()
                if not all(checks.values()):continue
                stage={k:bool(getattr(e,'_stage_'+k)[i]) for k in ('door','bottle_out','bottle_placed','cap_turned','cap_placed')}
                item['stage']=stage
                expected={'OpenCabinet':[False]*5,'PickBottle':[True,False,False,False,False],
                          'UnscrewCap':[True,True,True,False,False],'PourBeads':[True]*5}[task]
                if list(stage.values())!=expected:
                    item.update(status='init_fail',reason='incorrect initial stage');flush();continue
                ctrl=e.agent.controller
                hold=torch.empty((2,env.action_space.shape[-1]),device=e.device)
                for key,(lo,hi) in ctrl.action_mapping.items():
                    hold[:,lo:hi]=e.agent.robot.qpos[:,ctrl.controllers[key].active_joint_indices]
                env.step(hold)
                if e.has_bottle:
                    current=value(e._source_pose().p[i])
                    item['bottle_shift_after_hold_m']=float(np.linalg.norm(current-pos[:3]))
                    holding=e.source_fixed if task=='UnscrewCap' else e.source
                    support=e.cabinet.links_map['link_1'] if task=='PickBottle' else e.table_scene.table
                    item['support_contact_N']=float(e.scene.get_pairwise_contact_forces(holding,support)[i].norm())
                    if current[2]<expected_height+(-e.source_z_lo)-.003 or item['bottle_shift_after_hold_m']>.02:
                        item.update(status='init_fail',reason='settling displacement or support penetration');flush();continue
                ik=motion_targets(e,task,i,yaw,item)
                item['ik']=ik;flush()
                if ik['ik_pass'] and p['dynamic']=='yes':
                    item['motion']=physical_attempt(env,e,task,i,ik)
                flush()
    result['status']='completed';flush()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
