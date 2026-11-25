"""Exercise independently initialized Pipette workspace layouts through the registered task."""
import argparse
from collections import Counter
from contextlib import closing
import csv
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_pipette_positions import (ROOT, TASKS, XY_OFFSETS_M, geometry, git, gym, initial_checks,
                                     np, pose_rows, position_centers, release_probe, sapien,
                                     short_attempt, snapshot, stand_dish_gap_m, torch, version)
from build_pipette_workspace import envelope, TABLE
from check_furniture_appearance import controller_state
from pipette_workspace_motion import capture, screen
from tasks.pipette_transfer import position_workspace as ws


def serial(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(serial(value).encode()).hexdigest()


def digest(env, i):
    stream = env._workspace_streams[i].bit_generator.state
    native = env._batched_episode_rng[i].get_state()
    state = snapshot(env, i)
    controls = controller_state(env, i)
    return fingerprint([state, controls, stream, native[0], native[1].tolist(), *native[2:]])


def numeric_examples(task):
    objects, slices, _, half, _ = ws.workspace(task)
    for yaw, cells in slices.items():
        for label, axis, order in [('near', 0, -1), ('far', 0, 1), ('right', 1, -1), ('left', 1, 1)]:
            center = cells[(cells[:, axis] * order).argmax()].astype(float)
            center[axis] += order * half
            yield f'edge-{yaw}-{label}', ws.public_row(objects, center / 1000, yaw), False
            if label == 'near':
                center[axis] += order * .1
                yield f'outside-{yaw}', ws.public_row(objects, center / 1000, yaw), True


def kinematics(env, task, i, poses, geo):
    outcomes = []
    for obj, side in [('cup', 'right'), ('rack', 'left')]:
        if obj not in poses:
            continue
        chain = capture(env, side, i)
        passive = capture(env, 'left' if side == 'right' else 'right', i) if task == 'Long' else None
        yaw = np.rad2deg(2 * np.arctan2(poses['stand'][6], poses['stand'][3]))
        ok, error, route, paths = screen(chain, np.asarray([poses['stand'][:2]]),
            np.asarray([poses[obj][:2]]), yaw, envelope(env, geo, obj), side, witnesses=True, passive=passive)
        outcomes.append((dict(hand=side, passed=bool(ok[0]), max_tip_error_mm=float(error[0]*1000),
                              approach_deg=(-35, 35)[route[0]]), paths[0]))
    return outcomes


def workpoints(env, i, poses, geo):
    root = np.asarray(poses['pipette'][:3])
    barrel = geo['dimensions']['pipette']['shapes'][0]['pose'][:3]
    tip_link = env.pipette.links_map['tip'].pose.p[i].detach().cpu().numpy()
    return {'barrel_xyz': (root + barrel).tolist(), 'tip_link_xyz': tip_link.tolist(),
            **{name+'_mouth_xyz':[ *poses[name][:2], poses[name][2]+height] for name, height in
               [('cup', env.cfg.cup_h), ('tube', env.cfg.tube_h)] if name in poses}}


def feature(row, task):
    names = ['stand'] + (['cup', 'rack'] if task == 'Long' else ['cup' if task == 'AspirateLiquid' else 'rack'])
    return np.concatenate([row['stand'][:2], *[np.subtract(row[name][:2], row['stand'][:2])
                                                for name in names[1:]]])


def legacy_random(env, task, seed):
    rng = np.random.default_rng(seed)
    centers = position_centers(env.cfg)
    objects = ws.workspace(task)[0]
    for _ in range(512):
        row = {name+'_xy_m': (centers[name] + rng.uniform(*XY_OFFSETS_M[name])).tolist() for name in objects}
        row['stand_yaw_deg'] = int(rng.choice([78, 90, 102]))
        if 'cup' not in objects or stand_dish_gap_m(row['stand_xy_m'], row['cup_xy_m'], row['stand_yaw_deg']) >= .02:
            return row
    raise AssertionError('failed to draw a legal legacy control')


def group_summary(rows):
    features = np.asarray([r[0] for r in rows]) * 1000
    return dict(n=len(rows), feature_mm_p05_p50_p95=np.percentile(features, [5,50,95],axis=0).tolist(),
                reach_pass=sum(r[1] for r in rows), reset_ms_median=float(np.median([r[2] for r in rows])))


def check_task(writer, task, backend, base):
    n = base['num_envs']
    task_id = 'PipetteTransfer' + task + '-Sharpa-v1'
    results = {}
    tests = []
    def test(ok, label):
        tests.append((label, bool(ok)))
        if not ok:
            raise AssertionError(f'{task}: {label}')
    # Compare true native and legacy controls to the opt-in mode on held-out seeds.
    native_ref = {}
    for mode in ('native', 'legacy', 'workspace'):
        options = {**base, 'position_workspace': mode == 'workspace'}
        samples = []
        with closing(gym.make(task_id, **options)) as wrapped:
            env = wrapped.unwrapped
            geo = geometry(env)
            for seed in range(88301, 88313):
                extras = {}
                if mode == 'legacy':
                    extras['position_layout'] = {str(j): legacy_random(env,task,seed+j*10000) for j in range(n)}
                start = perf_counter()
                _, info = wrapped.reset(seed=seed, options=extras)
                ms = (perf_counter() - start) * 1000
                poses = pose_rows(env, 0)
                valid = kinematics(env, task, 0, poses, geo)
                passed = all(v['passed'] for v, _ in valid)
                samples.append((feature(poses, task), passed, ms))
                q = env.agent.robot.qpos.detach().cpu().numpy().tobytes()
                if mode == 'native':
                    native_ref[seed] = q
                else:
                    test(native_ref[seed] == q, mode+' robot seed '+str(seed))
                row = dict(task=task_id, make=options, id=mode+'-'+str(seed), seed=seed,
                           env=0, request=extras, actual=poses, workpoints=workpoints(env,0,poses,geo),
                           ik=[v for v,_ in valid], outcome='initial_passed')
                request = (info['workspace_placement']['0'] if mode == 'workspace' else
                           extras['position_layout']['0'] if mode == 'legacy' else None)
                row['initial'] = initial_checks(env, 0, task, request, poses, geo)
                test(all(row['initial']['checks'].values()), row['id'])
                writer.writerow({k:serial(v) if isinstance(v,(dict,list)) else v for k,v in row.items()})
        results[mode] = group_summary(samples)

    make = {**base,'position_workspace':True}
    with closing(gym.make(task_id, **make)) as wrapped:
        env = wrapped.unwrapped
        geo = geometry(env)
        def both(item):
            return {'workspace_placement': {str(j):item for j in range(n)}}
        def sequence():
            result = []
            for seed in (8361, None, None):
                _, info = wrapped.reset(seed=seed)
                result.append(info['workspace_placement'])
            return result
        first = sequence()
        test(first == sequence() and first[0] != first[1], 'seeded sequence')
        wrapped.reset(seed=8361)
        wrapped.reset(options=both('left'))
        test(wrapped.reset()[1]['workspace_placement'] == first[1], 'fixed preset consumes no position draw')
        wrapped.reset(seed=8361)
        wrapped.reset(options={'position_layout': {str(j):{} for j in range(n)}})
        test(wrapped.reset()[1]['workspace_placement'] == first[1], 'legacy request consumes no position draw')
        snap = env.get_state_dict()
        before_streams = [fingerprint(s.bit_generator.state) for s in env._workspace_streams.values()]
        # State restore format is owned by ManiSkill; use the registered production convention.
        wrapped.reset(options={'reset_to_env_states': {'env_states':snap}})
        test(before_streams == [fingerprint(s.bit_generator.state) for s in env._workspace_streams.values()],
             'state restore consumes no position draw')
        presets = ws.workspace(task)[2]
        cases = [(name, name, False) for name in presets] + list(numeric_examples(task))
        for k, (label, item, bad) in enumerate(cases):
            i = k % n
            seed = 6135 + k
            wrapped.reset(seed=seed)
            request={'env_idx':[i], 'workspace_placement':{str(i):item}}
            protected = [j for j in range(n) if bad or j != i]
            before = {j:digest(env,j) for j in protected}
            row=dict(task=task_id,make=make,id=label,seed=seed,env=i,request=request)
            try:
                _, info = wrapped.reset(options=request)
            except ValueError as exc:
                if not bad:
                    raise
                row.update(outcome='rejected',reason=str(exc))
            else:
                test(not bad,'expected rejection '+label)
                expected = ws.resolve(task,item)
                test(info['workspace_placement'][str(i)] == expected,'resolved placement '+label)
                poses = pose_rows(env,i)
                init = initial_checks(env,i,task,expected,poses,geo)
                test(all(init['checks'].values()),'readback '+label)
                row.update(outcome='initial_passed',actual=poses,initial=init,workpoints=workpoints(env,i,poses,geo))
            test(before == {j:digest(env,j) for j in protected},'isolation '+label)
            row['protected_sha256'] = before
            if not bad:
                motion = kinematics(env,task,i,poses,geo)
                row['ik'] = [v for v,_ in motion]
                if label in ('center','far'):
                    row['support'] = release_probe(wrapped,env,i,poses)
                    test(row['support']['passed'],'release '+label)
                    if task != 'Long':
                        wrapped.reset(seed=seed)
                        wrapped.reset(options=request)
                        path = kinematics(env,task,i,pose_rows(env,i),geo)[0][1]
                        short = short_attempt(wrapped,env,i,{'joint_targets_rad':[path[j] for j in (1,2,4)]})
                        short['native_success'] = bool(env.evaluate()['success'][i])
                        row['short'] = short
            writer.writerow({k:serial(v) if isinstance(v,(dict,list)) else v for k,v in row.items()})
        invalids = [both('missing-preset'), {**both('center'),'position_layout':{str(j):{} for j in range(n)}}]
        if n == 2:
            invalids.append({'workspace_placement':{'0':'center','1':'missing-preset'}})
            invalids.append({'env_idx':[1,0],'workspace_placement':{'0':'center','1':'far'}})
        for req in invalids:
            before = [digest(env,j) for j in range(n)]
            try:
                wrapped.reset(options=req)
            except ValueError:
                test(before == [digest(env,j) for j in range(n)],'atomic invalid batch')
            else:
                raise AssertionError('accepted invalid request')
        for i in range(n):
            before = {j:digest(env,j) for j in range(n) if j!=i}
            _,info = wrapped.reset(options={'env_idx':[i]})
            test(before == {j:digest(env,j) for j in before} and set(info['workspace_placement']) == {str(i)},
                 'local random '+str(i))
    results['contracts_checked'] = len(tests)
    return results


def replay(task):
    a,b = [np.random.default_rng(20261125) for _ in range(2)]
    counts = Counter()
    for i in range(8192):
        sample = ws.sample(task,a)
        assert sample == ws.sample(task,b)
        # Independent numeric membership check for each draw.
        assert ws.resolve(task,sample) == sample
        counts[sample['stand_yaw_deg']] += 1
    return counts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--sim-backend',choices=('physx_cpu','physx_cuda'),required=True)
    parser.add_argument('--physx-gpu-dir',type=Path)
    parser.add_argument('--task',choices=TASKS,action='append')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    backend=args.sim_backend
    make=dict(num_envs=2 if backend=='physx_cuda' else 1,sim_backend=backend,obs_mode='state',
              render_mode=None,control_mode='pd_joint_pos',reconfiguration_freq=0)
    report=dict(commit=git('rev-parse','HEAD'),sim_backend=backend,sapien=sapien.__version__,
                mani_skill=version('mani_skill'),sha256={},tasks={})
    for path in [TABLE,*sorted((ROOT/'tasks/pipette_transfer').glob('*.py')),Path(__file__).resolve(),
                 *[Path(__file__).with_name(s) for s in ('build_pipette_workspace.py','pipette_workspace_motion.py',
                                                          'check_pipette_positions.py','check_cabinet_positions.py')]]:
        report['sha256'][str(path.relative_to(ROOT).as_posix())]=hashlib.sha256(path.read_bytes()).hexdigest()
    fields='task make id seed env request outcome reason initial actual workpoints protected_sha256 ik support short'.split()
    with (args.output/'POINTS.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for task in args.task or TASKS:
            summary=check_task(writer,task,backend,make)
            if backend=='physx_cpu':
                summary['replayed']=replay(task)
            report['tasks'][task]=summary
            stream.flush()
            print(task,summary,flush=True)
    (args.output/'RESULTS.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()

