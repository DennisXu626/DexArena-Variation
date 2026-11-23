"""Bounded two-environment Drawer & Plug position check."""
import argparse
import csv
import json
import math
import os
from itertools import product
from pathlib import Path

import gymnasium as gym
import numpy as np
from scipy.spatial.transform import Rotation
from shapely.geometry import MultiPoint
import torch

from check_cabinet_positions import env_digest, rotation, setup_motion, solve_arm, value
from mani_skill.utils.structs.pose import Pose


def as_pose(actor, i):
    return value(actor.pose.raw_pose[i]).astype(float)


def orient(pose):
    return Rotation.from_quat(pose[[4, 5, 6, 3]])


def yaw_deg(pose):
    return math.degrees(2 * math.atan2(pose[6], pose[3]))


def vertices(half, center, pose):
    local = np.array(list(product(*[(-h, h) for h in half]))) + center
    return orient(pose).apply(local) + pose[:3]


def charger_parts(e, pose):
    prong_z = -e.charger_half[2] - e.charger_prong_half[2]
    return [vertices(e.charger_half, [0, 0, 0], pose)] + [
        vertices(e.charger_prong_half, [dx, 0, prong_z], pose)
        for dx in (-e.socket_slot_offset_x, e.socket_slot_offset_x)
    ]


def outline_gap(e, charger, socket):
    shell = vertices([e.socket_side / 2] * 2 + [e.socket_thickness / 2], [0,0,0], socket)
    footprint = MultiPoint(shell[:, :2]).convex_hull
    return min(footprint.distance(MultiPoint(p[:, :2]).convex_hull) for p in charger_parts(e, charger))


def full_action(e, env):
    ctrl = e.agent.controller
    action = torch.empty((2, env.action_space.shape[-1]), device=e.device)
    for key, (lo, hi) in ctrl.action_mapping.items():
        action[:, lo:hi] = e.agent.robot.qpos[:, ctrl.controllers[key].active_joint_indices]
    return action


def support_probe(env, e, i, kind, pose, long_hold):
    action = full_action(e, env)
    support = e.drawer_link if kind == "PickCharger" else e.table_scene.table
    forces = []
    for _ in range(24 if long_hold else 2):
        env.step(action)
        forces.append(float(e.scene.get_pairwise_contact_forces(e.charger, support)[i].norm()))
    after = as_pose(e.charger, i)
    vertical = orient(after).apply([0,1,0])
    tilt = math.degrees(math.acos(np.clip(vertical[2], -1, 1)))
    bottom = min(p[:, 2].min() for p in charger_parts(e, after))
    min_x = min(p[:, 0].min() for p in charger_parts(e, after))
    return dict(settled_pose=after.tolist(), displacement_m=float(np.linalg.norm(after[:3]-pose[:3])),
                tilt_deg=tilt, peak_contact_N=max(forces), final_contact_N=forces[-1],
                bottom_z_m=float(bottom), left_edge_margin_m=float(min_x+.4245002),
                hold_steps=len(forces), hold_seconds=len(forces)/e.control_freq)


def motion_targets(e, kind, i, item):
    chain = setup_motion(e, i)
    tips = chain[-1]
    axis = rotation(item.get("drawer_yaw_deg",0))[:, 0]
    forward = np.r_[axis, 0.]
    if kind == "OpenDrawer":
        goal = np.asarray(item["handle_xyz_m"])
        waypoints = [goal-.055*forward, goal, goal-.04*forward]
        tangent = np.array([0.,0.,1.])
        stages = ["approach", "handle", "pull"]
    else:
        goal = np.asarray(item["charger_pose"][:3])
        goal[2] += .025
        side = orient(np.asarray(item["charger_pose"])).apply([1,0,0])
        tangent = side / np.linalg.norm(side)
        if kind == "PickCharger":
            above_front = max(e.drawer_wall_top_z+.045, goal[2]+.10)
            lift = np.r_[goal[:2], above_front]
            exit_point = lift - .26*forward
            waypoints = [goal+[0,0,.065], goal, lift, exit_point]
            stages = ["approach", "charger_body", "lift", "exit"]
        else:
            socket = np.asarray(item["socket_pose"])
            target = socket[:3]+[0,0,e.socket_mouth_z-e.charger_prong_tip_z+.045]
            waypoints = [goal+[0,0,.065], goal, goal+[0,0,.16], target]
            stages = ["approach", "charger_body", "lift", "above_socket"]
    if np.dot(tips[1]-tips[0], tangent) < 0:
        tangent = -tangent
    span = np.linalg.norm(tips[1]-tips[0])
    offset = np.stack([-tangent, tangent])*span/2
    selected = None
    for orientation in (offset, .707*offset+np.array([[0,0,.3535*span],[0,0,-.3535*span]])):
        q = chain[2]
        solutions, errors = [], []
        for point in waypoints:
            q,error = solve_arm(chain,point+orientation,q)
            solutions.append(q.tolist())
            errors.append(error)
        if selected is None or max(errors)<max(selected["tip_errors_m"]):
            selected = dict(stages=stages, arm_targets=solutions, tip_errors_m=errors,
                            passed=max(errors)<=.015, targets_xyz_m=np.array(waypoints).tolist())
    return selected


def physical_attempt(env, e, kind, i, ik):
    action = full_action(e, env)
    ctrl = e.agent.controller
    arm_lo,arm_hi = ctrl.action_mapping["arm"]
    hand_lo,hand_hi = ctrl.action_mapping["hand"]
    start_hand = action[i,hand_lo:hand_hi].clone()
    close = start_hand.clone()
    limits=e.agent.robot.get_qlimits()[i,ctrl.controllers["hand"].active_joint_indices]
    for j,name in enumerate(e.agent.hand_joint_names):
        if name.endswith(("PIP","DIP","_IP","MCP_FE")):
            close[j]=torch.clamp(start_hand[j]+.45,min=limits[j,0],max=limits[j,1])
    target = e.drawer_link if kind=="OpenDrawer" else e.charger
    fingers=[e.agent.robot.links_map[n] for n in e.agent.grip_link_names]
    thumb = [link for link in fingers if "thumb" in link.name.lower()]
    trace=[]
    start_travel=float(e.drawer_travel[i]) if e.has_drawer else None
    start_pose=as_pose(target,i)
    contact_seen=False
    grasp_seen=False
    dual_contact_steps = 0
    crossed=False
    above=False
    contact_qualified_motion=0.
    for phase,q in enumerate(ik["arm_targets"]):
        start=action[i,arm_lo:arm_hi].clone()
        for step in range(30):
            blend=min((step+1)/22,1.)
            action[i,arm_lo:arm_hi]=torch.lerp(start,start.new_tensor(q),blend)
            if phase==1:
                action[i,hand_lo:hand_hi]=torch.lerp(start_hand,close,blend)
            env.step(action)
            force=max(float(e.scene.get_pairwise_contact_forces(target,f)[i].norm()) for f in fingers)
            if kind!="OpenDrawer":
                # Preserve the time series so contact and free motion can be distinguished.
                # Track an opposed qualification on the same step, separately from any contact.
                thumb_forces = [value(e.scene.get_pairwise_contact_forces(target,f)[i]) for f in thumb]
                finger_forces = [value(e.scene.get_pairwise_contact_forces(target,f)[i])
                                 for f in fingers if "thumb" not in f.name.lower()]
                grasp = any(np.linalg.norm(a)>.05 and np.linalg.norm(b)>.05 and
                            np.dot(a,b)<-.25*np.linalg.norm(a)*np.linalg.norm(b)
                            for a in thumb_forces for b in finger_forces)
                dual_contact_steps += int(grasp)
                grasp_seen |= grasp
            travel=float(e.drawer_travel[i]) if e.has_drawer else None
            pose=as_pose(target,i)
            if kind=="OpenDrawer":
                contact_seen |= force>.001
                if contact_seen:
                    contact_qualified_motion=max(contact_qualified_motion,travel-start_travel)
            if kind=="PickCharger":
                root=as_pose(e.drawer,i)
                full_body=vertices(e.charger_half,[0,0,0],pose)
                delta=full_body-root[:3]
                rel=orient(root).inv().apply(delta)
                rel[:,0]+=travel
                crossed |= (grasp and rel[:,0].max()<e.drawer_interior_x[0]
                            and full_body[:,2].min()>e.drawer_wall_top_z)
            tip_error=None
            if kind=="InsertPlug":
                socket=as_pose(e.socket,i)
                offsets=np.array([[-e.socket_slot_offset_x,0,e.charger_prong_tip_z],
                                  [e.socket_slot_offset_x,0,e.charger_prong_tip_z]])
                pos=orient(pose).apply(offsets)+pose[:3]
                rel=orient(socket).inv().apply(pos-socket[:3])
                local=rel[:,:2]-offsets[:,:2]
                reversed_local=rel[:,:2]-offsets[::-1,:2]
                tip_error=float(min(np.linalg.norm(local,axis=1).max(),
                                    np.linalg.norm(reversed_local,axis=1).max()))
                align=float(np.dot(orient(pose).apply([0,0,1]),orient(socket).apply([0,0,1])))
                above |= tip_error<=.004 and align>=.95 and np.all(
                    (rel[:,2]>=e.socket_mouth_z)&(rel[:,2]<=e.socket_mouth_z+.08)
                )
            trace.append(dict(phase=phase,substep=step,contact_N=force,drawer_open_m=travel,
                              object_pose=pose.tolist(),prong_error_m=tip_error))
    delta=as_pose(target,i)[:3]-start_pose[:3]
    passed={"OpenDrawer":contact_qualified_motion>=.01, "PickCharger":crossed, "InsertPlug":above}[kind]
    return dict(passed=passed,peak_contact_N=max(p["contact_N"] for p in trace),
                object_displacement_m=delta.tolist(),drawer_pull_m=contact_qualified_motion,
                opposed_contact_seen=grasp_seen,opposed_contact_steps=dual_contact_steps,body_cleared_front=crossed,prongs_above_holes=above,trace=trace)


def diagnostic_place(e, i, center):
    """Isolated constructed pose for the native placement predicate."""
    pose = e.charger.pose.raw_pose.clone()
    pose[i,:3] = pose.new_tensor([*center, e.charger_half[1]])
    pose[i,3:] = pose.new_tensor(e.charger_initial_quat)
    e.charger.set_pose(Pose.create(pose))
    e.scene.px.gpu_apply_rigid_dynamic_data()
    e.scene._gpu_fetch_all()
    e._charger_prev_p[i] = e.charger.pose.p[i]
    e._charger_prev_q[i] = e.charger.pose.q[i]
    e._charger_speed[i] = 0
    e._charger_ang_speed[i] = 0
    e._charger_motion_last_step[i] = e._elapsed_steps[i]
    placed,outside,bottom,radius,settled = e._charger_table_state()
    return dict(status="placement_predicate_measured", placed=bool(placed[i]),
                charger_out=bool(outside[i]), settled=bool(settled[i]), radial_distance_m=float(radius[i]),
                bottom_z_m=float(bottom[i]), charger_pose=as_pose(e.charger,i).tolist())


def diagnostic_socket(e, i):
    """Feed aligned and mismatched physical poses to the current socket predicate."""
    original = e.charger.pose.raw_pose.clone()
    current = e.socket.pose.raw_pose[i].clone()
    def evaluate(aligned):
        pose = original.clone()
        pose[i] = current
        pose[i,2] += e.socket_mouth_z-e.charger_prong_tip_z-.024
        if not aligned:
            # Rotate 90 degrees about world Z relative to the socket.
            w,z=pose[i,3].clone(),pose[i,6].clone()
            pose[i,3],pose[i,6]=(w-z)/math.sqrt(2),(w+z)/math.sqrt(2)
        e.charger.set_pose(Pose.create(pose))
        e.scene.px.gpu_apply_rigid_dynamic_data()
        e.scene._gpu_fetch_all()
        e._charger_prev_p[i] = e.charger.pose.p[i]
        e._charger_prev_q[i] = e.charger.pose.q[i]
        e._charger_speed[i] = 0
        e._charger_ang_speed[i] = 0
        e._charger_motion_last_step[i] = e._elapsed_steps[i]
        seated,depth,_,_,error,alignment,_ = e._charger_socket_state()
        return dict(seated=bool(seated[i]),depth_m=float(depth[i]),prong_error_m=float(error[i]),
                    alignment=float(alignment[i]))
    return dict(aligned=evaluate(True), mismatched=evaluate(False), engineering_fixture=True)


def measure_reset(e, kind, i, request, item):
    checks={}
    if e.has_drawer:
        drawer=as_pose(e.drawer,i)
        yaw=yaw_deg(drawer)
        drawer_open=float(e.drawer_travel[i])
        item.update(drawer_pose=drawer.tolist(),drawer_yaw_deg=yaw,drawer_open_m=drawer_open,
                    handle_xyz_m=value(e.drawer_handle_world_position()[i]).tolist(),
                    rail_direction_xyz=orient(drawer).apply([-1,0,0]).tolist())
        checks.update(drawer_xy=bool(np.allclose(drawer[:2],request.get("drawer_xy_m",e.drawer_xy),atol=2e-6)),
                      drawer_yaw=abs(yaw-request.get("drawer_yaw_deg",0))<1e-4,
                      drawer_open=abs(drawer_open-(.22 if kind=="PickCharger" else 0))<1e-5,
                      drawer_qvel=float(e.drawer.qvel[i].abs().max())<1e-5,
                      stage=bool(e._stage_drawer_open[i])==(kind=="PickCharger"))
    if e.has_charger:
        cp=as_pose(e.charger,i)
        body=charger_parts(e,cp)[0]
        item.update(charger_pose=cp.tolist(),
                    initial_linear_m_s=value(e.charger.linear_velocity[i]).tolist(),
                    initial_angular_rad_s=value(e.charger.angular_velocity[i]).tolist())
        checks["charger_rest_velocity"]=(np.linalg.norm(item["initial_linear_m_s"])<1e-5 and
                                        np.linalg.norm(item["initial_angular_rad_s"])<1e-5)
        if kind=="PickCharger":
            actual=value(e._world_to_drawer_local_xy(e.charger.pose.p[:,:2],e.drawer_travel)[i]).tolist()
            item["charger_drawer_xy_m"]=actual
            cp_prong = orient(cp).apply([0,0,-1])
            expected = orient(drawer).apply([1,0,0])
            checks.update(charger_local=bool(np.allclose(actual,request.get("charger_drawer_local_xy_m",e._charger_drawer_center()),atol=2e-6)),
                          charger_prong_orientation=bool(np.allclose(cp_prong,expected,atol=1e-5)),
                          charger_in_drawer=not bool(e._out_of_drawer(e.charger.pose.p)[i]),
                          charger_bottom=abs(body[:,2].min()-e.drawer_floor_z-.001)<2e-5)
            # Same world point transformed from a known just-outside local point.
            probe=e.charger.pose.p.clone()
            local=np.r_[e.drawer_interior_x[0]-.03-drawer_open,actual[1],cp[2]-drawer[2]]
            probe[i]=probe.new_tensor(orient(drawer).apply(local)+drawer[:3])
            checks["rotated_outside_test"]=bool(e._out_of_drawer(probe)[i])
        else:
            sp=as_pose(e.socket,i)
            svg=outline_gap(e,cp,sp)
            margin=float(body[:,0].min()+.4245002)
            item.update(socket_pose=sp.tolist(),socket_yaw_deg=yaw_deg(sp),outline_gap_m=svg,left_edge_margin_m=margin)
            checks.update(socket_xy=bool(np.allclose(sp[:2],request.get("socket_xy_m",e.socket_center_xy),atol=2e-6)),
                          socket_yaw=abs(yaw_deg(sp)-request.get("socket_yaw_deg",90))<1e-4,
                          socket_foot=abs(sp[2]-e.socket_thickness/2)<1e-5,
                          charger_bottom=abs(body[:,2].min()-.001)<2e-5,
                          supported_footprint=margin>=-1e-6, no_initial_xy_overlap=svg>0,
                          stage=bool(e._stage_drawer_open[i] and e._stage_charger_placed[i]) and not bool(e._stage_charger_inserted[i]))
            if "charger_table_xy_m" in request:
                checks["charger_table_xy"]=bool(np.allclose(cp[:2],request["charger_table_xy_m"],atol=2e-6))
            else:
                checks["charger_native_disk"]=np.linalg.norm(cp[:2]-e.charger_place_center_xy)<.105001
    return checks


def order(rows,kind):
    def priority(row):
        name=row["id"]
        if name=="F1-0" or (kind=="InsertPlug" and name=="F5-0"): return 0
        if name=="F4-5" and kind=="InsertPlug":return 1
        if name=="C-near-95":return 2
        if name.startswith("C-"):return 3
        if row["kind"]=="expected_reject":return 4
        if row["kind"].startswith("native_predicate"):return 6
        return 5
    return sorted(rows,key=priority)


def run(out, matrix):
    out.mkdir(exist_ok=False)
    with matrix.open(encoding="utf-8",newline="") as stream:
        rows=list(csv.DictReader(stream))
    result=dict(job=os.environ["SLURM_JOB_ID"],backend="physx_cuda",tasks={},status="running")
    def flush():
        # Both checkpoint names stay present after creation for the capacity sampler.
        encoded=json.dumps(result,indent=2,allow_nan=False,default=lambda n: n.item())
        current=out/"results.json"
        previous=out/"results.previous.json"
        if current.is_file():
            previous.write_bytes(current.read_bytes())
        current.write_text(encoded)
    make=dict(num_envs=2,sim_backend="physx_cuda",obs_mode="state",reconfiguration_freq=0)
    kinds = ("InsertPlug", "OpenDrawer", "PickCharger")
    phases = [(kind, priority) for priority in (True, False) for kind in kinds]
    for kind,priority in phases:
        task_id="DrawerPlug"+kind+"-Sharpa-v1"
        def urgent(row):
            return (row["id"]=="F1-0" or row["id"].startswith("C-") or
                    row["kind"]=="expected_reject" or
                    (kind=="InsertPlug" and row["id"] in ("F5-0","F4-5")))
        batch=order([p for p in rows if p["task"]==task_id and urgent(p)==priority],kind)
        task=result["tasks"].setdefault(kind,dict(task_id=task_id,make_kwargs=make,points=[]))
        flush()
        with gym.make(task_id,**make) as env:
            e=env.unwrapped
            env.reset(seed=7)
            native={}
            for name in ("drawer","charger","socket"):
                if getattr(e,"has_"+name):
                    native[name]=value(getattr(e,name).pose.raw_pose).tolist()
            task.setdefault("native_seed_7_pose",native)
            task.setdefault("native_drawer_travel",value(e.drawer_travel).tolist() if e.has_drawer else None)
            flush()
            for row in batch:
                i=int(row["env_idx"])
                request=json.loads(row["request"])
                seed=int(row["seed"])
                id=row["id"]
                idx=torch.tensor([i],device=e.device)
                pickup_diagnostic=row["kind"].startswith("native_predicate")
                opts={"env_idx":idx}
                if not pickup_diagnostic:
                    opts["position_layout"]={str(i):request}
                before=env_digest(e.get_state_dict(),1-i)
                item=dict(id=id,figure=row["figure"],kind=row["kind"],env_idx=i,seed=seed,request=request,
                          reset_options={**opts,"env_idx":[i]},status="resetting")
                task["points"].append(item)
                flush()
                try:
                    env.reset(seed=seed,options=opts)
                except ValueError as exc:
                    if row["kind"]!="expected_reject" or "position_layout" not in str(exc):
                        item.update(status="unexpected_reset_error",reason=str(exc));flush()
                        raise
                    item.update(status="rejected",reason=str(exc), passive_unchanged=before==env_digest(e.get_state_dict(),1-i))
                    flush()
                    assert item["passive_unchanged"],id
                    continue
                item["passive_unchanged"]=before==env_digest(e.get_state_dict(),1-i)
                if not item["passive_unchanged"] or row["kind"]=="expected_reject":
                    item["status"]="isolation_fail" if not item["passive_unchanged"] else "unexpected_accept"
                    flush()
                    raise AssertionError(id)
                if pickup_diagnostic:
                    item.update(diagnostic_place(e,i,request["diagnostic_place_center_xy_m"]))
                    flush()
                    continue
                item["checks"]=measure_reset(e,kind,i,request,item)
                item["status"]="init_pass" if all(item["checks"].values()) else "init_fail"
                if item["status"]=="init_fail":
                    item["reason"]=", ".join(k for k,v in item["checks"].items() if not v)
                flush()
                if item["status"]=="init_fail":
                    continue
                if e.has_charger:
                    evidence=support_probe(env,e,i,kind,np.asarray(item["charger_pose"]),id=="F4-5")
                    item["support"]=evidence
                    if (evidence["peak_contact_N"]<.001 or evidence["tilt_deg"]>5 or evidence["displacement_m"]>.008):
                        item.update(status="support_probe_fail",reason="support force, tilt or displacement")
                    flush()
                    if item["status"]=="support_probe_fail": continue
                # Bound physical actions to one nominal point per task; report all IK independently.
                ik=motion_targets(e,kind,i,item)
                item["ik"]=ik
                flush()
                nominal=id=="F1-0" or (kind=="InsertPlug" and id=="F5-0")
                if nominal and max(ik["tip_errors_m"][:2])<.025:
                    item["motion"]=physical_attempt(env,e,kind,i,ik)
                    flush()
                if kind=="InsertPlug" and id in ("C-near","C-near-85","C-near-95"):
                    item["socket_predicate_test"]=diagnostic_socket(e,i)
                    flush()
    result["status"]="completed"
    flush()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--samples",required=True,type=Path)
    args=parser.parse_args()
    run(args.output,args.samples)
