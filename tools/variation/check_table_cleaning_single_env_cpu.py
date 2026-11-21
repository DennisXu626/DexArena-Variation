"""Execute old/current single-env initialization with identical CPU actor spies.

Checks layout and robot-reset arithmetic/RNG consumption, not simulator behavior.
The reference is the frozen pre-appearance Git source; no imports of tasks/torch.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "acd6ba232b8da7a97fd313aa3df8a9f595fd55e0"
RELATIVE = "tasks/table_cleaning/table_cleaning_long.py"


class Tensor(np.ndarray):
    def view(self, *shape):
        return np.asarray(self).reshape(*shape).view(Tensor)
    def expand(self, *shape):
        target = tuple(self.shape[i] if n == -1 else n for i, n in enumerate(shape))
        return np.broadcast_to(self, target).copy().view(Tensor)
    def clone(self): return self.copy()
    def detach(self): return self
    def cpu(self): return self
    def numpy(self): return np.asarray(self)


def tensor(data, dtype=None, **kwargs):
    return np.array(data, dtype=dtype).view(Tensor)


def zeros(*shape, dtype=None, **kwargs):
    if len(shape) == 1 and isinstance(shape[0], tuple): shape = shape[0]
    return np.zeros(shape, dtype=dtype).view(Tensor)


def methods(source):
    cls, = [n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "TableCleanBase"]
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def namespace(source):
    torch = SimpleNamespace(tensor=tensor, as_tensor=tensor, zeros=zeros, float32=np.float32, long=np.int64, Tensor=Tensor)
    pose = SimpleNamespace(create_from_pq=lambda p, q: SimpleNamespace(p=p.copy(), q=q.copy()))
    ns = {"np": np, "torch": torch, "Pose": pose, "set_work_table_pose": lambda env: None,
          "ROBOT_ROOT": "same unchanged platform_root_pose expression"}
    layout = ast.parse((ROOT/"tasks/config/layout_randomization.py").read_text(encoding="utf-8"))
    exec(compile(ast.Module(body=[n for n in layout.body if isinstance(n, (ast.FunctionDef, ast.Assign))], type_ignores=[]),
                 "layout_randomization.py", "exec", flags=__import__('__future__').annotations.compiler_flag), ns)
    workspace = ast.parse((ROOT/"tasks/config/workspace_rig.py").read_text(encoding="utf-8"))
    for n in workspace.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in (
            "WORK_TABLE_X_OFFSET", "STOCK_TABLE_CENTER_X", "TABLE_CENTER_X", "ARM_INIT_QPOS"):
            exec(compile(ast.Module(body=[n], type_ignores=[]), "workspace_rig.py", "exec"), ns)
    ns["RIG_ARM_INIT_QPOS"] = ns["ARM_INIT_QPOS"]
    constants = {"PAN_REST_Z", "DEBRIS_SIZE", "PICK_DEBRIS_COUNT", "PICK_DEBRIS_SCALE", "PICK_DEBRIS_SPAWN_SPAN",
                 "ARM_INIT_QPOS", "DEBRIS_CENTER", "DUSTPAN_POS", "BIN_POS", "PAN_RANDOM_XY", "PAN_RANDOM_YAW_DEG",
                 "BIN_RANDOM_XY", "DEBRIS_SCATTER_HALF_SPAN", "DEBRIS_MIN_SEPARATION"}
    for n in ast.parse(source).body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in constants:
            exec(compile(ast.Module(body=[n], type_ignores=[]), "task_constants", "exec"), ns)
    selected = [n for name, n in methods(source).items() if name in (
        "_bin_layout_xy", "_reset_robot", "_place", "_place_batch", "_place_scene_start")]
    cls = ast.ClassDef(name="Initializer", bases=[], keywords=[], body=selected, decorator_list=[])
    tree = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    exec(compile(tree, "real_initialization_methods", "exec"), ns)
    return ns


class Actor:
    def __init__(self, yaw=0.):
        self.pose = SimpleNamespace(p=tensor([[0., 0., 0.]], np.float32),
            q=tensor([[np.cos(yaw/2), 0., 0., np.sin(yaw/2)]], np.float32))
    def set_pose(self, pose): self.pose = pose
    def set_linear_velocity(self, v): self.linear = v.copy()
    def set_angular_velocity(self, v): self.angular = v.copy()


def trial(ns, seed, noise, current):
    env = ns["Initializer"]()
    env.device, env.num_envs, env.debris_count = "cpu", 1, 3
    env.cleaning_appearance = None
    env.robot_init_qpos_noise = noise
    env._episode_seed = [seed]
    env._batched_episode_rng = [np.random.RandomState(seed)]
    env.table_scene = SimpleNamespace(initialize=lambda indices: None)
    env._reset_buffers = lambda indices: None
    env.pan, env.debris = Actor(.17), [Actor(.13 + i*.19) for i in range(3)]
    env._built_pan_q = env.pan.pose.q[0].numpy().astype(np.float64)
    env._built_debris_q = [a.pose.q[0].numpy().astype(np.float64) for a in env.debris]
    names = [f"arm{i}" for i in range(7)] + [f"finger{i}" for i in range(3)]
    env.agent = SimpleNamespace(keyframes={"rest": SimpleNamespace(qpos=np.arange(10)*.03)},
        arm_joint_names=names[:7], robot=SimpleNamespace(get_active_joints=lambda: [SimpleNamespace(name=n) for n in names],
        set_root_pose=lambda pose: setattr(env, "robot_pose", pose)),
        reset=lambda q: setattr(env, "robot_qpos", q.copy()))
    bin_xy = env._bin_layout_xy()
    # ManiSkill reseeds the episode stream after scene reconfiguration.
    env._batched_episode_rng = [np.random.RandomState(seed)]
    if current: env._place_scene_start(np.array([0]), {})
    else: env._place_scene_start(np.array([0]))
    values = [np.asarray(bin_xy), np.asarray(env.robot_qpos)]
    for actor in [env.pan, *env.debris]:
        values.extend([np.asarray(actor.pose.p), np.asarray(actor.pose.q), np.asarray(actor.linear), np.asarray(actor.angular)])
    return values, repr(env._batched_episode_rng[0].get_state())


def main(output):
    old = subprocess.check_output(["git", "show", f"{REFERENCE}:{RELATIVE}"], cwd=ROOT).decode("utf-8")
    new = (ROOT/RELATIVE).read_text(encoding="utf-8")
    left, right = namespace(old), namespace(new)
    records = []
    for seed in range(32):
        for noise in (0., .02):
            a, ar = trial(left, seed, noise, False)
            b, br = trial(right, seed, noise, True)
            delta = max(float(np.abs(x-y).max(initial=0)) for x, y in zip(a, b))
            assert delta <= 1e-6 and ar == br, (seed, noise, delta)
            records.append({"seed": seed, "noise": noise, "max_delta": delta, "rng_equal": ar == br})
    result = {"status": "passed", "reference_commit": REFERENCE, "reference_lf_sha256": hashlib.sha256(old.encode()).hexdigest(),
              "scope": "CPU real source methods with actor/tensor spies; bin/pan/debris layout and robot initialization only; no simulator",
              "cases": records}
    if output: output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"status": "passed", "cases": len(records), "max_delta": max(r["max_delta"] for r in records)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    main(parser.parse_args().output)
