"""Build a bounded continuous Pipette placement map from native CPU robot and collision geometry."""
import argparse
from contextlib import closing
import hashlib
from itertools import product
import json
from pathlib import Path

from check_pipette_positions import (ROOT, geometry, gym, initial_checks, np, pose_rows,
                                     PIPETTE_MIN_STAND_CUP_GAP, stand_dish_gap_m, STAND_YAW_DEG)
from pipette_workspace_motion import capture, screen

TABLE = ROOT / 'tasks/pipette_transfer/workspace_cells.json'
HALF_MM = 5
DELTA = HALF_MM / 1000
CORNER = np.sqrt(2) * DELTA
IK_LIMIT = .015
TASKS = ('AspirateLiquid', 'DispenseLiquid', 'Long')


def envelope(env, geo, obj):
    dims = geo['dimensions']
    grip = env.cfg.pipette_stand_z + dims['pipette']['shapes'][0]['pose'][2]
    tip = dims['pipette_tip']
    grip_to_tip = grip - env.cfg.pipette_stand_z - tip['pose'][2] + tip['half_length']
    # Cruise above the tallest actual structure, including the stand crossbar.
    top = max(dims[key]['max'][2] for key in ('stand', 'cup', 'rack', 'tube') if key in dims)
    rim = (env.cfg.cup_h if obj == 'cup' else env.cfg.tube_h + .003)
    return dict(grip=grip, cruise=grip_to_tip + top + .025,
                dip=grip_to_tip + rim - .009, stand_top=dims['stand']['max'][2],
                cell_corner=CORNER, ik_limit=IK_LIMIT)


def geometry_filter(geo, bounds, stand, end, yaw, obj):
    radians = np.deg2rad(yaw)
    rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
    foot = np.asarray(geo['local_hulls_xy']['stand']) @ rotation.T
    target = np.asarray(geo['local_hulls_xy'][obj])
    low, high = np.asarray(bounds)
    for shape, center in [(foot, stand), (target, end)]:
        if (center + shape.min(axis=0) - DELTA <= low).any() or (center + shape.max(axis=0) + DELTA >= high).any():
            return False
    if obj == 'cup':
        return stand_dish_gap_m(stand, end, yaw) >= PIPETTE_MIN_STAND_CUP_GAP + 2 * CORNER
    # Separate the entire upright rack from the stand at all points in both cells.
    return (end[1] + target[:, 1].min() - (stand[1] + foot[:, 1].max())) > 2 * DELTA


def build(task, audit):
    dual = task == 'Long'
    with closing(gym.make(f'PipetteTransfer{task}-Sharpa-v1', num_envs=1, sim_backend='physx_cpu',
                          robot_init_qpos_noise=0., obs_mode='state', render_mode=None,
                          control_mode='pd_joint_pos', reconfiguration_freq=0)) as wrapped:
        wrapped.reset(seed=701, options={'position_layout': {'0': {}}})
        env = wrapped.unwrapped
        geo, poses = geometry(env), pose_rows(env, 0)
        observed = initial_checks(env, 0, task, {}, poses, geo)
        assert all(observed['checks'].values())
        bounds = observed['table_bounds_m']
        entities = (['cup', 'rack'] if dual else ['cup' if task == 'AspirateLiquid' else 'rack'])
        chains = {obj: capture(env, 'right' if obj == 'cup' else 'left') for obj in entities}
        anchor = np.rint(np.asarray(env.cfg.pipette_stand_xy) * 1000).astype(int)
        probes = {}
        valid_by_yaw = {}
        for yaw in STAND_YAW_DEG:
            groups = {}
            for obj in entities:
                delta = np.rint((np.asarray(poses[obj][:2]) - np.asarray(poses['stand'][:2])) * 1000).astype(int)
                # Joint cells share a stand grid. End cells have several working
                # distances/lateral lanes, rather than two independently drawn boxes.
                candidates = [[*(anchor + [x, y]), *(anchor + [x, y] + delta + [dx, dy])]
                              for x, y in product(range(-80, 41, 10), range(-40, 61, 10))
                              for dx, dy in product((-40, 0, 40), (-30, 0, 30))]
                geom = [row for row in candidates if geometry_filter(
                    geo, bounds, np.array(row[:2]) / 1000, np.array(row[2:]) / 1000, yaw, obj)]
                cells = np.asarray(geom, dtype=int)
                groups[obj] = {}
                side = 'right' if obj == 'cup' else 'left'
                other = 'rack' if obj == 'cup' else 'cup'
                env_geom = envelope(env, geo, obj)
                diagnostics = []
                for chunk in np.array_split(cells, max(1, len(cells) // 192)):
                    ok, error, route, _ = screen(chains[obj], chunk[:, :2] / 1000, chunk[:, 2:] / 1000,
                                                 yaw, env_geom, side, passive=chains.get(other))
                    for row, passed, err, r in zip(chunk, ok, error, route):
                        if passed:
                            groups[obj].setdefault(tuple(row[:2]), []).append(tuple(row[2:]))
                        diagnostics.append([*map(int, row), bool(passed), round(float(err) * 1000, 3), int(r)])
                probes[f'{yaw}/{obj}'] = dict(tried=len(candidates), geometry_pass=len(cells),
                    route_pass=sum(map(len, groups[obj].values())), cells=diagnostics)
            if dual:
                rows = [list(map(int, (*s, *cup, *rack))) for s in sorted(groups['cup'].keys() & groups['rack'])
                        for cup, rack in product(groups['cup'][s], groups['rack'][s])
                        if (rack[1] - cup[1]) / 1000 > DELTA * 2 + .059 + geo['dimensions']['rack']['max'][1]]
            else:
                rows = [list(map(int, (*s, *point))) for s, targets in groups[obj].items() for point in targets]
            print(task, yaw, len(rows), {k:v['route_pass'] for k,v in probes.items()}, flush=True)
            if not rows:
                raise RuntimeError(f'No screened layouts for {task} at {yaw} degrees')
            valid_by_yaw[str(yaw)] = rows
        nominal = np.concatenate([np.rint(np.asarray(poses[obj][:2]) * 1000) for obj in ['stand', *entities]])
        cells = np.asarray(valid_by_yaw['90'])
        center = cells[np.argmin(np.linalg.norm(cells - nominal, axis=1))]
        def nearest(rows):
            return rows[np.argmin(np.linalg.norm(rows - center, axis=1))].tolist()
        presets = {'center': center.tolist(),
                   'near': nearest(cells[cells[:, 0] == cells[:, 0].min()]),
                   'far': nearest(cells[cells[:, 0] == cells[:, 0].max()]),
                   'left': nearest(cells[cells[:, 1] == cells[:, 1].max()]),
                   'right': nearest(cells[cells[:, 1] == cells[:, 1].min()])}
        audit[task] = dict(robot_uid=env.robot_uids, bounds=bounds, objects=entities,
                           chains={obj:{key:v.tolist() for key,v in chain.items()} for obj,chain in chains.items()},
                           geometry={obj:envelope(env,geo,obj) for obj in entities}, probes=probes)
        return dict(objects=['stand', *entities], cells=valid_by_yaw, presets=presets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    audit = {}
    spec = dict(version=1, half_mm=HALF_MM, tasks={})
    for task in TASKS:
        spec['tasks'][task] = build(task, audit)
    TABLE.write_text(json.dumps(spec, separators=(',', ':')) + '\n', encoding='ascii')
    audit['table_sha256'] = hashlib.sha256(TABLE.read_bytes()).hexdigest()
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, separators=(',', ':')) + '\n', encoding='ascii')


if __name__ == '__main__':
    main()

