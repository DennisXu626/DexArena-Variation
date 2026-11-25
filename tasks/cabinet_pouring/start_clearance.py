"""Closed-cabinet screen for the uncommanded left Sharpa hand and its approach."""
from functools import lru_cache
from pathlib import Path

import numpy as np

MIN_START_CLEARANCE_MM = 60.0
MIN_APPROACH_CLEARANCE_MM = 12.0
MAX_PLACEMENT_DRAWS = 48
PATH_INTERVALS = 32


@lru_cache(maxsize=1)
def geometry():
    with np.load(Path(__file__).with_name("open_cabinet_clearance.npz"), allow_pickle=False) as f:
        return {key: f[key] for key in f.files}


def wrist_frames(q):
    """World poses of link7. The wrist, palm and open fingers are rigid in its frame."""
    data = geometry()
    q = np.atleast_2d(q)
    position = np.zeros((len(q), 3))
    rotation = np.broadcast_to(np.eye(3), (len(q), 3, 3))
    for joint, frame in enumerate(data["frames"]):
        position += rotation @ frame[:3, 3]
        rot = rotation @ frame[:3, :3]
        c, s = np.cos(q[:, joint])[:, None], np.sin(q[:, joint])[:, None]
        rotation = rot.copy()
        rotation[:, :, 0] = c * rot[:, :, 0] + s * rot[:, :, 1]
        rotation[:, :, 1] = -s * rot[:, :, 0] + c * rot[:, :, 1]
    return position, rotation


def orientation(yaw):
    a = np.deg2rad(yaw)
    return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])


def pregrasp(geometry_data, xy, yaw):
    """Interpolate the four verified IK solutions; validate the resulting actual target."""
    data = geometry_data
    u, v = np.array(xy) * 100
    # Round-trip float32 poses can land a few millionths of a cm beyond a grid edge.
    x, y = int(np.floor(u)), int(np.floor(v))
    nodes = data["pre_q"][int((yaw-10)//5)]
    for j in (y, y-1, y+1):
        for i in (x, x-1, x+1):
            a, b = u-i, v-j
            if not (-2e-6 <= a <= 1+2e-6 and -2e-6 <= b <= 1+2e-6):
                continue
            ix, iy = i-data["grid_min"][0], j-data["grid_min"][1]
            if ix<0 or iy<0 or iy+1>=nodes.shape[0] or ix+1>=nodes.shape[1]:
                continue
            patch = nodes[iy:iy+2, ix:ix+2]
            if not np.isfinite(patch).all():
                continue
            q = (1-b)*((1-a)*patch[0,0]+a*patch[0,1]) + b*((1-a)*patch[1,0]+a*patch[1,1])
            pos, rot = wrist_frames(q)
            idx = int((yaw-10)//5)
            target = np.r_[xy,0.] + data["target"][idx]
            if np.linalg.norm(pos[0]+rot[0]@data["grip"]-target) <= .001 and (
                    np.sum(rot[0]*data["rotation"][idx])-1 >= 2*np.cos(np.deg2rad(.75))):
                return q
    return None


def clearance(xy, yaw, start, end):
    """Conservative separations in mm, retaining the limiting interval and piece indices."""
    data = geometry()
    angles = np.linspace(start, end, PATH_INTERVALS+1)
    pos, rot = wrist_frames(angles)
    axes = orientation(yaw)
    trans = (pos-np.r_[xy,0.]) @ axes
    corners = data["corners"].reshape(-1,3)
    points = (corners @ (rot.transpose(0,2,1) @ axes)).reshape(len(pos),-1,8,3)
    points += trans[:,None,None,:]
    lo, hi = points.min(axis=2), points.max(axis=2)
    # A rotated link vector's acceleration along linear joint interpolation is
    # bounded by length*(sum of absolute joint travel)^2. Sum over the serial
    # chain; chord deviation on a segment is bounded by max acceleration/8.
    lengths = np.linalg.norm(data["frames"][1:,:3,3],axis=1)
    radius = lengths.sum()+np.linalg.norm(corners, axis=1).max()
    sag = radius * (np.abs(end-start).sum()/PATH_INTERVALS)**2/8
    lower = np.concatenate([lo[:1], np.minimum(lo[:-1],lo[1:])-sag])
    upper = np.concatenate([hi[:1], np.maximum(hi[:-1],hi[1:])+sag])
    boxes = data["boxes"]
    delta = np.maximum(0., np.maximum(lower[:,:,None]-boxes[:,1], boxes[:,0]-upper[:,:,None]))
    squared = np.einsum("...i,...i->...",delta,delta)
    def minimum(arr):
        idx = np.unravel_index(np.argmin(arr), arr.shape)
        return float(1000*np.sqrt(arr[idx])), tuple(int(i) for i in idx)
    return minimum(squared[:1]), minimum(squared[1:])


def evaluate_start(xy, yaw, arm_qpos):
    data = geometry()
    end = pregrasp(data, xy, yaw)
    if end is None:
        return False, "interpolated pre-grasp exceeds IK tolerance"
    (start, _), (approach, _) = clearance(xy, yaw, np.asarray(arm_qpos), end)
    return (start >= MIN_START_CLEARANCE_MM and approach >= MIN_APPROACH_CLEARANCE_MM,
            f"start {start:.2f} mm, approach {approach:.2f} mm")
