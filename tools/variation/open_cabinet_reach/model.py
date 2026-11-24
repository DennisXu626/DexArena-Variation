"""Offline FK and constrained IK for the registered left angled Sharpa. SI units."""
from pathlib import Path
import itertools
import json
import xml.etree.ElementTree as ET

import numpy as np
from numba import njit
from scipy.spatial.transform import Rotation
import trimesh

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/variation/evidence/open_cabinet_reach"
PREVIOUS = ROOT / "docs/variation/evidence/cabinet_position_boundaries/runtime_002"
URDF = ROOT / "tasks/assets/urdf/panda_sharpa_hand_left_angled_mobile_base.urdf"
PLAN = json.loads((PREVIOUS / "plan_geometry.json").read_bytes())
NOMINAL = next(p for p in json.loads((PREVIOUS / "raw/output/results.json").read_bytes())
               ["tasks"]["OpenCabinet"]["points"] if p["id"] == "F1-0")
HOME = np.array([-.5, -.2, 0, -2.6, 0, 2.4, np.pi/4])
REFERENCE = np.array(NOMINAL["ik"]["arm_targets"][1])
BASE = np.array([-.87, 0., 0.])
Z = NOMINAL["handle_xyz"][2]
STEP = .005
XYZ_TOL = .001
ANGLE_TOL = np.deg2rad(.75)


def rz(deg):
    return Rotation.from_euler("z", deg, degrees=True).as_matrix()


def origin(element):
    result = np.eye(4)
    if element is not None:
        result[:3, 3] = np.fromstring(element.get("xyz", "0 0 0"), sep=" ")
        result[:3, :3] = Rotation.from_euler("xyz", np.fromstring(element.get("rpy", "0 0 0"), sep=" ")).as_matrix()
    return result


tree = ET.parse(URDF)
joints = {j.find("child").get("link"): j for j in tree.findall("joint")}
arm_names = [f"panda_link{i}" for i in range(1, 8)]


def rest_pose(name):
    if name not in joints:
        pose = np.eye(4)
        pose[:3, 3] = BASE
        return pose
    joint = joints[name]
    return rest_pose(joint.find("parent").get("link")) @ origin(joint.find("origin"))


MOUNT = rest_pose("panda_link0")[:3, 3].copy()
frames = np.stack([origin(joints[n].find("origin")) for n in arm_names])
frames[0] = rest_pose("panda_link0") @ frames[0]
SHOULDER = frames[0,:3,3].copy()
limits = np.array([[float(joints[n].find("limit").get(k)) for k in ("lower","upper")] for n in arm_names])
assert all(joints[n].find("axis").get("xyz") == "0 0 1" for n in arm_names)
tips = np.array([rest_pose(f"left_{digit}_fingertip")[:3, 3] for digit in ("thumb", "index")])
grip_local = (np.linalg.inv(rest_pose(arm_names[-1])) @ np.r_[tips.mean(axis=0), 1])[:3].copy()
offsets = np.ascontiguousarray(frames[:,:3,3])
fixed_rot = np.ascontiguousarray(frames[:,:3,:3])


@njit
def fk(q):
    pos = np.zeros(3)
    rot = np.eye(3)
    origins = np.empty((7,3))
    rots = np.empty((7,3,3))
    for j in range(7):
        pos = pos + rot @ offsets[j]
        r = rot @ fixed_rot[j]
        c, s = np.cos(q[j]), np.sin(q[j])
        rot = r.copy()
        for k in range(3):
            rot[k,0] = c*r[k,0] + s*r[k,1]
            rot[k,1] = -s*r[k,0] + c*r[k,1]
        origins[j] = pos
        rots[j] = rot
    return pos + rot @ grip_local, rot, origins, rots


@njit
def solve(target, orientation, seed):
    q = seed.copy()
    for _ in range(45):
        p, rot, centres, rots = fk(q)
        dp = target-p
        error = np.zeros(3)
        for j in range(3):
            error += .5*np.cross(rot[:,j],orientation[:,j])
        cos_angle = (np.sum(rot*orientation)-1)*.5
        if np.linalg.norm(dp) <= XYZ_TOL and cos_angle >= np.cos(ANGLE_TOL):
            return True, q
        jac = np.empty((6,7))
        for j in range(7):
            ax = rots[j,:,2]
            jac[:3,j] = np.cross(ax,p-centres[j])
            jac[3:,j] = .24*ax
        step = jac.T @ np.linalg.solve(jac @ jac.T + .00016*np.eye(6), np.concatenate((dp,.24*error)))
        step *= min(1., .23/max(1.e-10,np.max(np.abs(step))))
        prev = q
        q = np.minimum(limits[:,1],np.maximum(limits[:,0],q+step))
        if np.max(np.abs(q-prev)) < .00001:
            break
    return False, q


def collision_boxes():
    """Enclose every available URDF collision part downstream of arm joint 1."""
    groups, local_corners, handle_contact = [], [], []
    for link in tree.findall("link"):
        name = link.get("name")
        anchor = name
        while anchor in joints and anchor not in arm_names:
            anchor = joints[anchor].find("parent").get("link")
        if anchor not in arm_names:
            continue
        transform = np.linalg.inv(rest_pose(anchor)) @ rest_pose(name)
        for coll in link.findall("collision"):
            geom = coll.find("geometry/mesh")
            assert geom is not None, name
            mesh = trimesh.load(URDF.parent / geom.get("filename"), process=False)
            scale = np.fromstring(geom.get("scale","1 1 1"),sep=" ")
            rigid = transform @ origin(coll.find("origin"))
            # The palm is oblique to the handle. Tighter triangle enclosures
            # avoid attributing an empty corner of its bounding box to the palm.
            parts = [mesh.triangles]
            if name == "left_hand_C_MC":
                for _ in range(4):
                    halves = []
                    for triangles in parts:
                        centres = triangles.mean(axis=1)
                        order = centres[:,np.ptp(centres,axis=0).argmax()].argsort()
                        halves.extend(triangles[ii] for ii in np.array_split(order, 2))
                    parts = halves
            for triangles in parts:
                v = triangles.reshape(-1,3)*scale
                corners = np.array(list(itertools.product(*zip(v.min(axis=0), v.max(axis=0)))))
                local_corners.append(corners @ rigid[:3,:3].T + rigid[:3,3])
                groups.append(arm_names.index(anchor))
                handle_contact.append(name.startswith(("left_thumb_", "left_index_", "left_middle_", "left_ring_", "left_pinky_")))
    return np.array(groups), np.array(local_corners), np.array(handle_contact)


HINGE = np.array(PLAN["hinge"])/100
HANDLE = (np.array(NOMINAL["handle_xyz"][:2]) - NOMINAL["cabinet_pose"][:2]) @ rz(15)[:2,:2]
BODY = np.array(PLAN["body"])/100
DOOR = np.array(PLAN["door"])/100
HARDWARE = np.array(PLAN["handle"])/100
TABLE = np.array(PLAN["table_xy_cm"])/100


def handle_offset(yaw, opening):
    return (HINGE + (HANDLE-HINGE) @ rz(-opening)[:2,:2].T) @ rz(yaw)[:2,:2].T
