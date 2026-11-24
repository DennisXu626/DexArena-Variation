"""Record workstation position, support, two-fingertip IK and reset isolation."""

import argparse
from contextlib import closing
import csv
import hashlib
from importlib.metadata import version
from itertools import product
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]

import gymnasium as gym
import numpy as np
import sapien
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation
import torch
import tasks  # register the native entry points

from check_cabinet_positions import env_digest, setup_motion, solve_arm, value
from tasks.pipette_transfer.pipette_transfer_long import (
    PIPETTE_MIN_STAND_CUP_GAP,
    PipetteConfig,
)
from tasks.pipette_transfer.position_layout import (
    DISH_COLLISION_RADIUS_LIMIT_M,
    STAND_YAW_DEG,
    XY_OFFSETS_M,
    position_centers,
    stand_dish_gap_m,
)


TASKS = ('AspirateLiquid', 'DispenseLiquid', 'Long')
OBJECTS = {'stand': 'pipette_stand', 'pipette': 'pipette', 'cup': 'sample_cup',
           'rack': 'tube_rack', 'tube': 'test_tube'}
IK_LIMIT_M = .015
RELEASE_STEPS = 18


def xy_samples(name, center):
    lo, hi = XY_OFFSETS_M[name]
    ax = [[center[i] + lo[i], center[i], center[i] + hi[i]] for i in range(2)]
    return dict(zip(('SW', 'W', 'NW', 'S', 'N0', 'N', 'SE', 'E', 'NE'), product(*ax)))


def matrix(task):
    centers = position_centers(PipetteConfig())
    yield 'native', 'native', None, False
    yield 'stand-xy', 'N0', {}, False
    names = ['stand', 'cup' if task == 'AspirateLiquid' else 'rack']
    if task == 'Long':
        names = []  # masks, center, and combined layout witness on the shared pipeline
    for name in names:
        for label, xy in xy_samples(name, centers[name]).items():
            if name == 'stand' and label == 'N0':
                continue
            yield name + '-xy', label, {name + '_xy_m': list(xy)}, False
    if task != 'Long':
        for yaw in STAND_YAW_DEG:
            yield 'stand-yaw', f'Y{yaw}', {'stand_yaw_deg': yaw}, False
    stand_far = list(xy_samples('stand', centers['stand'])['SE'])
    if task == 'AspirateLiquid':
        near = {f'{name}_xy_m': list(xy_samples(name, centers[name])[point])
                for name, point in (('stand', 'N'), ('cup', 'S'))}
        near_cup = [near['cup_xy_m'][0], centers['cup'][1] - .0009]
        yield 'combined', 'C-gap', {**near, 'cup_xy_m': near_cup, 'stand_yaw_deg': STAND_YAW_DEG[1]}, False
        bad = {'stand_xy_m': [centers['stand'][0] - .020, near['stand_xy_m'][1]],
               'cup_xy_m': near['cup_xy_m'], 'stand_yaw_deg': 102}
        yield 'reject', 'X-gap', bad, True
    else:
        far = list(xy_samples('rack', centers['rack'])['NE'])
        yield 'combined', 'C-far', {'rack_xy_m': far, 'stand_xy_m': stand_far,
                                    'stand_yaw_deg': STAND_YAW_DEG[-1]}, False
    yield 'reject', 'X-stand', {'stand_xy_m': [stand_far[0] + .0001, stand_far[1]]}, True
    yield 'reject', 'X-yaw', {'stand_yaw_deg': STAND_YAW_DEG[-1] + .1}, True
    if task != 'Long':
        absent = 'rack' if task == 'AspirateLiquid' else 'cup'
        yield 'reject', 'X-absent', {absent + '_xy_m': list(centers[absent])}, True


def rotation(q):
    return Rotation.from_quat(np.asarray(q)[[1, 2, 3, 0]])


def box_vertices(pose, half):
    corners = np.asarray(list(product((-1, 1), repeat=3))) * half
    return rotation(pose[3:]).apply(corners) + pose[:3]


def collision_shapes(body, slot):
    row = []
    for shape in body._bodies[slot].collision_shapes:
        record = {'pose': [*shape.local_pose.p.tolist(), *shape.local_pose.q.tolist()]}
        if hasattr(shape, 'half_size'):
            record['half'] = shape.half_size.tolist()
        else:
            record['radius'] = float(shape.radius)
            record['half_length'] = float(getattr(shape, 'half_length', 0))
        row.append(record)
    return row


def collision_vertices(shapes):
    out = []
    unit = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    for shape in shapes:
        pose = np.asarray(shape['pose'])
        if 'half' in shape:
            out.extend(box_vertices(pose, shape['half']))
        else:
            r, length = shape['radius'], shape['half_length']
            if length:
                for x in (-length, length):
                    out.extend(rotation(pose[3:]).apply(np.c_[np.full(64, x), r*np.cos(unit), r*np.sin(unit)]) + pose[:3])
            else:
                out.extend(pose[:3] + np.r_[np.eye(3), -np.eye(3)] * r)
    return np.asarray(out)


def geometry(env):
    hulls = {}
    dimensions = {}
    objects = {name: getattr(env, attr) for name, attr in OBJECTS.items()}
    objects.update(table=env.table_scene.table)
    for name, body in objects.items():
        if body is None:
            continue
        shapes = collision_shapes(body.root if name == 'pipette' else body, 0)
        vertices = collision_vertices(shapes)
        outline = vertices[ConvexHull(vertices[:, :2]).vertices, :2]
        hulls[name] = outline.tolist()
        dimensions[name] = {'min': vertices.min(axis=0).tolist(), 'max': vertices.max(axis=0).tolist(),
                            'shapes': shapes}
    tip = env.pipette.links_map['tip']
    dimensions['pipette_tip'] = collision_shapes(tip, 0)[0]
    if 'cup' in hulls:
        assert np.linalg.norm(hulls['cup'], axis=1).max() < DISH_COLLISION_RADIUS_LIMIT_M
    base_vertices = []
    for name, link in env.agent.robot.links_map.items():
        if not name.startswith('mobile_base'):
            continue
        parent_pose = value(link.pose.raw_pose[0])
        for shape in link._bodies[0].collision_shapes:
            local = shape.local_pose
            points = rotation(local.q).apply(np.asarray(shape.vertices) * shape.scale) + local.p
            base_vertices.extend(rotation(parent_pose[3:]).apply(points) + parent_pose[:3])
    base = np.asarray(base_vertices)[:, :2]
    return {'dimensions': dimensions, 'local_hulls_xy': hulls,
            'robot_base_world_hull_xy': base[ConvexHull(base).vertices].tolist()}


def pose_rows(env, i):
    return {name: value(getattr(env, attr).pose.raw_pose[i]).tolist()
            for name, attr in OBJECTS.items() if getattr(env, attr) is not None}


def snapshot(env, index):
    state = env.get_state_dict()
    digest = env_digest({'task': state['pipette_task_state'], 'elapsed_steps': env.elapsed_steps}, index)
    registry = env.scene.state_dict_registry
    for kind in ('actors', 'articulations'):
        digest[kind] = {}
        objects = getattr(registry, kind)
        for name, raw in state.get(kind, {}).items():
            # The registry includes both merged and individual actors.
            for slot, scene_idx in enumerate(objects[name]._scene_idxs.tolist()):
                if scene_idx == index:
                    digest[kind][f'{name}/{slot}'] = env_digest(raw, slot)
    return digest


def initial_checks(env, i, task, request, poses, geo):
    stand = np.asarray(poses['stand'])
    pipette = np.asarray(poses['pipette'])
    yaw = math.degrees(2 * math.atan2(stand[6], stand[3]))
    table = value(env.table_scene.table.pose.raw_pose[i])
    table_points = rotation(table[3:]).apply(np.c_[geo['local_hulls_xy']['table'], np.zeros(4)]) + table[:3]
    lo, hi = table_points[:, :2].min(axis=0), table_points[:, :2].max(axis=0)
    margins = {}
    support_z = {}
    for name in ('stand', 'cup', 'rack', 'tube'):
        if name in poses:
            pose = np.asarray(poses[name])
            hull = geo['local_hulls_xy'][name]
            xy = rotation(pose[3:]).apply(np.c_[hull, np.zeros(len(hull))])[:, :2] + pose[:2]
            margins[name] = float(min((xy - lo).min(), (hi - xy).min()))
            support_z[name] = float(pose[2] + geo['dimensions'][name]['min'][2])
    tip = geo['dimensions']['pipette_tip']
    actual_tip_z = pipette[2] + tip['pose'][2] - tip['half_length']
    tip_cup = geo['dimensions']['stand']['shapes'][4]
    tip_rest_gap = actual_tip_z - (stand[2] + tip_cup['pose'][2] + tip_cup['half_length'])
    stage = int(env.eval.stage[i])
    checks = {'stage': stage == (1 if task == 'DispenseLiquid' else 0),
              'plunger_rest': bool(torch.all(env.pipette.qpos[i] == 0)),
              'pipette_centered': np.allclose(pipette[:2], stand[:2], atol=1e-6),
              'pipette_upright': np.allclose(pipette[3:], [1, 0, 0, 0], atol=1e-6),
              'complete_table_support': min(margins.values()) > 0,
              'native_release_heights': all(-1e-6 <= m <= .003001 for m in support_z.values()),
              'tip_above_rest': 0 < tip_rest_gap < .012}
    measured = {'stand_yaw_deg': yaw, 'stage': stage, 'table_bounds_m': [lo.tolist(), hi.tolist()],
                'table_margin_m': margins, 'footprint_bottom_z_m': support_z,
                'physical_tip_rest_gap_m': tip_rest_gap}
    if 'tube' in poses:
        delta = np.asarray(poses['tube'][:2]) - poses['rack'][:2]
        checks['tube_in_slot'] = np.allclose(delta, np.asarray(env.cfg.tube_xy) - env.cfg.rack_xy, atol=1e-6)
        # Grid inner edge from actual collision bars sitting on each side of the center slot.
        bars = geo['dimensions']['rack']['shapes']
        slot_half = min(abs(p['pose'][axis]) - p['half'][axis] for p in bars[:16]
                        for axis in (0, 1) if 0 < abs(p['pose'][axis]) < .020)
        tube_radius = max(np.linalg.norm(geo['local_hulls_xy']['tube'], axis=1))
        measured['tube_slot_margin_m'] = float(slot_half - tube_radius - abs(delta).max())
        checks['tube_wall_clearance'] = measured['tube_slot_margin_m'] > 0
    if 'cup' in poses:
        gap = stand_dish_gap_m(stand[:2], poses['cup'][:2], yaw)
        measured['stand_dish_gap_lower_bound_m'] = gap
        checks['stand_dish_clear'] = gap >= (PIPETTE_MIN_STAND_CUP_GAP - 1e-6 if request is not None else 0)
    if request is not None:
        centers = position_centers(env.cfg)
        for name in centers.keys() & poses.keys():
            checks[name + '_request'] = np.allclose(poses[name][:2], request.get(name + '_xy_m', centers[name]), atol=1e-6)
        checks['yaw_request'] = abs(yaw - request.get('stand_yaw_deg', 90)) < 1e-4
    return {'checks': {key: bool(result) for key, result in checks.items()}, **measured}


def approach(env, i, task, poses, geo):
    chain = setup_motion(env, i)
    initial_tips = chain[-1]
    grip = np.asarray(poses['pipette'][:3])
    grip[2] += geo['dimensions']['pipette']['shapes'][0]['pose'][2]
    lift = grip.copy()
    # The collision tip must clear the upper guide before a horizontal exit.
    lift[2] += .175
    vessel = 'cup' if task == 'AspirateLiquid' else 'tube'
    goal = np.asarray(poses[vessel][:3])
    goal[2] += (env.cfg.cup_h if vessel == 'cup' else env.cfg.tube_h) + .03 + .245
    arm_label = 'right' if task == 'AspirateLiquid' else 'left'
    labels = ('approach', 'barrel', 'lift_above_guide', 'above_' + vessel)
    best = None
    for angle in np.deg2rad([0, -35, 35]):
        gather = np.asarray([math.sin(angle), math.cos(angle), 0])
        if np.dot(initial_tips[1] - initial_tips[0], gather) < 0:
            gather = -gather
        prior = chain[2]
        targets, errors, refs = [], [], []
        for center in (grip - [.045, 0, 0], grip, lift, goal):
            goals = np.stack([center - gather * .018, center + gather * .018])
            prior, err = solve_arm(chain, goals, prior)
            targets.append(prior.tolist())
            errors.append(err)
            refs.append(goals.tolist())
        if best is None or max(errors) < max(best['errors_m']):
            best = {'hand': arm_label, 'labels': labels, 'errors_m': errors, 'joint_targets_rad': targets,
                    'goal_tip_xyz_m': refs, 'limit_m': IK_LIMIT_M, 'passed': max(errors) <= IK_LIMIT_M}
    return best


def joint_action(env):
    ctrl = env.agent.controller
    action = torch.empty((env.num_envs, ctrl.action_space.shape[-1]), device=env.device)
    for name, (start, end) in ctrl.action_mapping.items():
        action[:, start:end] = env.agent.robot.qpos[:, ctrl.controllers[name].active_joint_indices]
    return action


def release_probe(wrapped, env, i, poses):
    action = joint_action(env)
    tip = env.pipette.links_map['tip']
    peak = {'tip_on_stand_N': 0., 'tube_on_table_N': 0.}
    for _ in range(RELEASE_STEPS):
        wrapped.step(action)
        peak['tip_on_stand_N'] = max(peak['tip_on_stand_N'],
                                    float(env.scene.get_pairwise_contact_forces(tip, env.pipette_stand)[i].norm()))
        if env.test_tube is not None:
            peak['tube_on_table_N'] = max(peak['tube_on_table_N'], float(env.scene.get_pairwise_contact_forces(
                env.test_tube, env.table_scene.table)[i].norm()))
    after = pose_rows(env, i)
    move = {name: float(np.linalg.norm(np.subtract(after[name][:3], start[:3])))
            for name, start in poses.items()}
    tilt = {name: math.degrees(math.acos(float(np.clip(rotation(pose[3:]).as_matrix()[2, 2], -1, 1))))
            for name, pose in after.items() if name in ('pipette', 'tube')}
    ok = (peak['tip_on_stand_N'] > .001 and ('tube' not in poses or peak['tube_on_table_N'] > .001)
          and max(move.values()) < .015 and max(tilt.values()) < 8)
    return {'steps': RELEASE_STEPS, 'shift_m': move, 'tilt_deg': tilt,
            'peak_contacts_N': peak, 'passed': ok}


def short_attempt(wrapped, env, i, ik):
    action = joint_action(env)
    ctrl = env.agent.controller
    alo, ahi = ctrl.action_mapping['arm']
    hlo, hhi = ctrl.action_mapping['hand']
    open_hand = action[i, hlo:hhi].clone()
    close = open_hand.clone()
    lim = env.agent.robot.get_qlimits()[i, ctrl.controllers['hand'].active_joint_indices]
    for j, name in enumerate(env.agent.hand_joint_names):
        if name.endswith(('PIP', 'DIP', '_IP', 'MCP_FE')):
            close[j] = torch.clamp(open_hand[j] + .40, min=lim[j, 0], max=lim[j, 1])
    tip = env.pipette.links_map['tip']
    p0 = float(tip.pose.p[i, 2])
    max_lift = 0.
    contacts = 0.
    for phase, q in enumerate(ik['joint_targets_rad'][:3]):
        start = action[i, alo:ahi].clone()
        for k in range(24):
            f = min((k + 1) / 16, 1.)
            action[i, alo:ahi] = torch.lerp(start, start.new_tensor(q), f)
            if phase == 1:
                action[i, hlo:hhi] = torch.lerp(open_hand, close, f)
            wrapped.step(action)
            max_lift = max(max_lift, float(tip.pose.p[i, 2]) - p0)
            contacts = max(contacts, *(float(env.scene.get_pairwise_contact_forces(env.pipette.root, t)[i].norm())
                                       for t in env.agent.tip_links[:2]))
    # A brief grasp/lift probe stops long before the liquid/return success predicate.
    final_lift = float(tip.pose.p[i, 2]) - p0
    return {'steps': 72, 'peak_tip_link_lift_m': max_lift, 'final_tip_link_lift_m': final_lift,
            'peak_fingertip_contact_N': contacts, 'lift_limit_m': .025,
            'passed': final_lift >= .025 and contacts > .001,
            'native_success': bool(env.eval.stage[i] >= 3)}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def serial(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def run(out, backend, tasks_to_run):
    num_envs = 2 if backend == 'physx_cuda' else 1
    kwargs = dict(sim_backend=backend, num_envs=num_envs, obs_mode='state', render_mode=None,
                  control_mode='pd_joint_pos', reconfiguration_freq=0)
    changes = git('status', '--porcelain', '--', 'tasks/pipette_transfer', 'tools/variation/check_pipette_positions.py')
    manifest = {'source_commit': git('rev-parse', 'HEAD'), 'dirty_runtime_paths': changes,
                'python': sys.version.split()[0], 'sapien': sapien.__version__, 'mani_skill': version('mani_skill'),
                'torch': torch.__version__, 'backend': backend, 'tasks': tasks_to_run}
    paths = [Path(__file__).resolve(), ROOT / 'tools/variation/check_cabinet_positions.py',
             *sorted((ROOT / 'tasks/pipette_transfer').glob('*.py')),
             *sorted(p for p in (ROOT / 'tasks/assets/task_object_meshes/pipette').rglob('*') if p.is_file())]
    manifest['sha256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    out.mkdir(parents=True, exist_ok=False)
    (out / 'IDENTITY.json').write_text(serial(manifest) + '\n', encoding='utf-8')
    failures = []
    with (out / 'POINTS.csv').open('w', newline='', encoding='utf-8') as stream:
        columns = ['task', 'category', 'id', 'seed', 'env_idx', 'make_kwargs', 'reset_options',
                   'status', 'reason', 'passive_before', 'passive_after', 'pose_wxyz', 'measurements',
                   'ik', 'support_release', 'short_attempt']
        writer = csv.DictWriter(stream, columns)
        writer.writeheader()
        for task in tasks_to_run:
            task_id = f'PipetteTransfer{task}-Sharpa-v1'
            with closing(gym.make(task_id, **kwargs)) as wrapped:
                env = wrapped.unwrapped
                geo = geometry(env)
                (out / f'GEOMETRY-{task}.json').write_text(serial(geo) + '\n', encoding='utf-8')
                wrapped.reset(seed=1519)
                native_robot = env.agent.robot.qpos.clone()
                wrapped.reset(seed=1519, options={'position_layout': {str(j): {} for j in range(num_envs)}})
                robot_unchanged = bool(torch.equal(native_robot, env.agent.robot.qpos))
                for index, (kind, label, request, reject) in enumerate(matrix(task)):
                    i = index % num_envs
                    seed = 1520 + index
                    wrapped.reset(seed=seed)
                    row = {'task': task_id, 'category': kind, 'id': label, 'seed': seed,
                           'env_idx': i, 'make_kwargs': serial(kwargs)}
                    options = {'env_idx': [i]}
                    if request is not None:
                        options['position_layout'] = {str(i): request}
                    row['reset_options'] = serial(options)
                    if num_envs == 2:
                        # Give the passive row a non-default predecessor flag so isolation
                        # tests preservation of task tensors as well as physical buffers.
                        env.eval.primed[1 - i] = True
                    before = [snapshot(env, j) for j in range(num_envs)]
                    try:
                        wrapped.reset(options=options)
                    except ValueError as error:
                        row.update(status='rejected' if reject else 'unexpected_reject', reason=str(error))
                    else:
                        poses = pose_rows(env, i)
                        measurements = initial_checks(env, i, task, request, poses, geo)
                        if label == 'N0' and kind == 'stand-xy':
                            measurements['checks']['native_robot_reseed_exact'] = robot_unchanged
                        ok = all(measurements['checks'].values())
                        row.update(status='initial_passed' if ok and not reject else 'initial_failed',
                                   pose_wxyz=serial(poses), measurements=serial(measurements))
                    protected = [j for j in range(num_envs) if j != i or reject]
                    row['passive_before'] = serial({j: before[j] for j in protected})
                    after = {j: snapshot(env, j) for j in protected}
                    row['passive_after'] = serial(after)
                    if before and any(before[j] != after[j] for j in protected):
                        row['status'] = 'isolation_failed'
                    if num_envs == 2:
                        env.eval.primed[1 - i] = False
                    if row['status'] == 'initial_passed' and task != 'Long':
                        ik = approach(env, i, task, poses, geo)
                        row['ik'] = serial(ik)
                        if label in ('N0', 'NE', 'SW', 'Y78', 'Y102') or kind == 'combined':
                            row['support_release'] = serial(release_probe(wrapped, env, i, poses))
                            if not json.loads(row['support_release'])['passed']:
                                row['status'] = 'release_failed'
                        if (kind == 'stand-xy' and label == 'N0') or kind == 'combined':
                            wrapped.reset(options=options)
                            ik = approach(env, i, task, pose_rows(env, i), geo)
                            row['short_attempt'] = serial(short_attempt(wrapped, env, i, ik))
                    print(task, kind, label, row['status'], flush=True)
                    if row['status'] not in ('initial_passed', 'rejected'):
                        failures.append((task, kind, label, row['status']))
                    writer.writerow(row)
                    stream.flush()
    if failures:
        raise SystemExit(f'Initialization or isolation failures: {failures}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--sim-backend', choices=('physx_cpu', 'physx_cuda'), required=True)
    parser.add_argument('--task', choices=TASKS, action='append')
    parser.add_argument('--physx-gpu-dir', type=Path, help='Used by the verified SDK launcher')
    args = parser.parse_args()
    run(args.output, args.sim_backend, args.task or TASKS)
