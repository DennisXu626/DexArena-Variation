"""Batched two-fingertip path screening from this task's measured joint screw axes."""
import numpy as np
from scipy.spatial.transform import Rotation


def capture(env, side, index=0):
    robot = env.agent.robot
    dual = hasattr(env.agent, 'left_tip_links') and hasattr(env.agent, 'right_tip_links')
    prefix = side + '_' if dual else ''
    names = getattr(env.agent, prefix + 'arm_joint_names')
    links = getattr(env.agent, prefix + 'tip_links')[:2]
    palm = getattr(env.agent, prefix + 'palm_link')
    ids = [next(i for i, j in enumerate(robot.active_joints) if j.name == name) for name in names]
    def xyz(t):
        return t.detach().cpu().numpy().astype(float)
    poses = np.stack([xyz(robot.joints_map[n].global_pose.raw_pose[index]) for n in names])
    return dict(origins=poses[:, :3], axes=Rotation.from_quat(poses[:, [4, 5, 6, 3]]).as_matrix()[:, :, 0],
                home=xyz(robot.qpos[index, ids]), limits=xyz(robot.get_qlimits()[index, ids]),
                points=np.stack([xyz(link.pose.p[index]) for link in [*links, palm]]))


def forward(chain, q):
    count = len(q)
    rot = np.broadcast_to(np.eye(3), (count, 3, 3))
    shift = np.zeros((count, 3))
    origins, axes = [], []
    for j, (origin, axis) in enumerate(zip(chain['origins'], chain['axes'])):
        current = rot @ origin + shift
        origins.append(current)
        axes.append(rot @ axis)
        change = Rotation.from_rotvec((q[:, j, None] - chain['home'][j]) * axis).as_matrix()
        rot = rot @ change
        shift = current - rot @ origin
    pts = (rot @ chain['points'].T).transpose(0, 2, 1) + shift[:, None]
    return pts, np.stack(origins, axis=1), np.stack(axes, axis=1)


def solve(chain, q, goals):
    """Damped least squares for two tips; retain the preceding path configuration."""
    q = q.copy()
    for _ in range(36):
        points, origins, axes = forward(chain, q)
        delta = goals - points[:, :2]
        if np.max(np.abs(delta)) < .0007:
            break
        jac = np.cross(axes[:, None], points[:, :2, None] - origins[:, None])
        jac = jac.transpose(0, 1, 3, 2).reshape(-1, 6, 7)
        transpose = jac.transpose(0, 2, 1)
        normal = transpose @ jac + .0012 * np.eye(7)
        step = np.linalg.solve(normal, transpose @ delta.reshape(-1, 6, 1))[..., 0]
        q = np.clip(q + np.clip(step, -.14, .14), *chain['limits'].T)
    points, origins, _ = forward(chain, q)
    error = np.linalg.norm(points[:, :2] - goals, axis=2).max(axis=1)
    return q, error, points, origins


def screen(chain, stand, vessel, yaw, geo, side, *, witnesses=False, passive=None):
    """Follow a vertical pipette through withdrawal, high transfer and vessel entry.

    The inverse route brings the pipe back through the same clearance envelope.
    The hand remains open in this kinematic probe. Contact and plunger dynamics
    belong to the native controller check.
    """
    n = len(stand)
    tip_delta = chain['points'][1] - chain['points'][0]
    half_span = np.linalg.norm(tip_delta) / 2
    grip_height, cruise, dip = geo['grip'], geo['cruise'], geo['dip']
    contact = np.column_stack((stand, np.full(n, grip_height)))
    high = contact.copy()
    high[:, 2] = cruise
    mouth = np.column_stack((vessel, np.full(n, dip)))
    over = mouth.copy()
    over[:, 2] = cruise
    home = np.broadcast_to(chain['points'][:2].mean(axis=0), contact.shape)
    best = np.full(n, np.inf)
    accepted = np.zeros(n, dtype=bool)
    best_waypoints = [[] for _ in range(n)] if witnesses else None
    best_route = np.zeros(n, dtype=int)
    for route_id, angle in enumerate((-35., 35.)):
        # Front and lateral approaches rotate with the guide frame.
        a = np.deg2rad(angle * (1 if side == 'right' else -1) + yaw - 90)
        direction = np.array([np.cos(a), np.sin(a), 0.])
        pre = contact - .048 * direction
        tangent = np.array([-np.sin(a), np.cos(a), .28 if side == 'right' else -.28])
        tangent /= np.linalg.norm(tangent)
        if tangent @ tip_delta < 0:
            tangent = -tangent
        offset = np.stack([-tangent, tangent]) * half_span
        centers = [(home + pre) / 2, pre, contact, (contact + high) / 2, high,
                   high * .75 + over * .25, (high + over) / 2, high * .25 + over * .75,
                   over, (over + mouth) / 2, mouth]
        q = np.tile(chain['home'], (n, 1))
        err = np.zeros(n)
        valid = np.ones(n, dtype=bool)
        trajectory = []
        for index, center in enumerate(centers):
            targets = center[:, None] + offset
            if index == 0:
                targets = (chain['points'][:2] + pre[:, None] + offset) / 2
            result, residual, points, joints = solve(chain, q, targets)
            err = np.maximum(err, residual)
            valid &= np.max(np.abs(result - q), axis=1) <= (2.0 if index < 2 else 1.25)
            # Wrist and palm height, and palm clearance from the stand's back wall.
            valid &= (points[:, 2, 2] > .024) & (joints[:, -2:, 2].min(axis=1) > .03)
            local = points[:, 2, :2] - stand
            c, s = np.cos(np.deg2rad(yaw)), np.sin(np.deg2rad(yaw))
            px = local[:, 0] * c + local[:, 1] * s
            py = -local[:, 0] * s + local[:, 1] * c
            valid &= ((points[:, 2, 2] > geo['stand_top'] + .027) |
                      (np.hypot(np.maximum(abs(px) - .046, 0),
                                np.maximum(abs(py + .045) - .008, 0)) > .027))
            if passive is not None:
                fixed = np.vstack([passive['origins'][3:], passive['points'][2]])
                moving = np.concatenate([joints[:, 3:], points[:, 2:]], axis=1)
                distances = np.linalg.norm(moving[:, :, None] - fixed, axis=-1)
                valid &= distances.min(axis=(1, 2)) > .085
            q = result
            if witnesses:
                trajectory.append(q.copy())
        # A fixed centre witness also bounds point-target translation throughout
        # the entire cell by its half diagonal. Precision of the guided insertion
        # and actual finger contacts are measured separately from this reach proxy.
        valid &= err + geo['cell_corner'] <= geo['ik_limit']
        better = valid & (~accepted | (err < best))
        diagnostic = (~valid & ~accepted & (err < best))
        chosen = better | diagnostic
        best[chosen] = err[chosen]
        best_route[chosen] = route_id
        if witnesses:
            for i in np.flatnonzero(chosen):
                best_waypoints[i] = [row[i].tolist() for row in trajectory]
        accepted |= valid
    return accepted, best, best_route, best_waypoints

