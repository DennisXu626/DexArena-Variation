"""Usage: python -B partial_reset_probe.py <PR checkout> <b22 mani_skill directory>.

CPU source-level witness for PR31. Tasks, BaseEnv reset, combined-controller
dispatch and arm reset/set_action execute reviewed method bodies. Scene,
articulation I/O, force application, layout and observation are stand-ins.
"""
from __future__ import annotations

import ast
import gzip
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import torch

repo, sdk = map(Path, sys.argv[1:3])
pkg = repo / "tasks/package_opening"
sdk_hashes = {
    "envs/sapien_env.py": "83066a0e68f8679b02aa7afc56b7f5fcea1e1886b31e9cf50e1aaa3758f56f2c",
    "agents/controllers/base_controller.py": "a39aa1ec3666ccca4820d0c8c42d3422b266a5a2561c0ca38ab34e42a9d5c249",
    "agents/base_agent.py": "64b0c9f45577ef842ae41449af36529e476ad68d26e726de5c9d858496f8824d",
}
for name, digest in sdk_hashes.items():
    assert hashlib.sha256((sdk / name).read_bytes()).hexdigest() == digest, name


def extract(path, name, methods, parent=object, flags=()):
    cls = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
               if isinstance(n, ast.ClassDef) and n.name == name)
    cls.decorator_list = []
    if name.startswith("PackageOpening"):
        assert not any(isinstance(n, ast.FunctionDef) and n.name == "reset" for n in cls.body), (
            "Package reset now has its own implementation; include it in the fixture", name)
    cls.bases = [ast.Name(id="Parent", ctx=ast.Load())]
    cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in methods
                or isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) in flags]
    assert set(methods) == {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    cls.body = cls.body or [ast.Pass()]
    scope = dict(globals(), Parent=parent)
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    exec(compile(module, str(path), "exec"), scope)
    return scope[name]


def noop(*args):
    pass


def apply_arm_init_qpos(agent, qpos):
    return qpos


def arm_qpos_noise(rng, agent, batch, noise, device):
    return [0], torch.zeros(batch, 1)


def episode_rng(env, i):
    return None


base_path = sdk / "agents/controllers/base_controller.py"
Controller = extract(base_path, "BaseController", ["reset", "_preprocess_action"])
DictController = extract(base_path, "DictController", ["reset"], Controller)
Arm = extract(repo / "tasks/robots/franka_joint_impedance_controller.py", "FrankaJointImpedanceController",
              ["reset", "set_action"], Controller)
Agent = extract(sdk / "agents/base_agent.py", "BaseAgent", ["reset"])
Base = extract(sdk / "envs/sapien_env.py", "BaseEnv", ["reset"])
Long = extract(pkg / "package_opening_long.py", "PackageOpeningLongEnv",
               ["_initialize_episode", "_initialize_agent"], Base, ["LOAD_APPLE", "LOAD_PACKAGE"])
Sub = extract(pkg / "package_opening_long.py", "PackageOpeningSubtaskEnv", ["_initialize_episode"], Long)
tasks = {"long": Long}
for stage, suffix in [("open", "OpenPackage"), ("extract", "ExtractApple")]:
    fn = "open_package" if stage == "open" else "extract_apple"
    tasks[stage] = extract(pkg / f"package_opening_{fn}.py", f"PackageOpening{suffix}Env", [], Sub,
                           ["LOAD_APPLE", "LOAD_PACKAGE", "TARGET_STAGE"])


def witness(stage, task, selected):
    other = 1 - selected
    e = task()
    e.num_envs, e.device, e.gpu_sim_enabled = 2, "cpu", False
    e._enhanced_determinism = False
    e.reconfiguration_freq = e._reconfig_counter = 0
    e._set_main_rng = e._set_episode_rng = e._clear_sim_state = noop
    e._elapsed_steps = torch.tensor([3, 5])
    e.scene = NS(num_envs=2, _reset_mask=torch.ones(2, dtype=torch.bool))
    e.scene_config = NS(initial_box_qpos=[0., 0.])
    e.table_scene = NS(initialize=noop)
    e._set_work_table_pose = e._randomize_layout = noop
    e.robot_init_qpos_noise, e._robot_base_pose = 0., None
    e.box = NS(max_dof=2, set_qpos=noop, set_qvel=noop)
    e.apple = NS(set_linear_velocity=noop, set_angular_velocity=noop)
    e.task_evaluator = NS(reset=noop, stage=torch.zeros(2, dtype=torch.int32))
    e.package_appearance = NS(finish_reset=noop)
    e.agent = Agent()
    e.agent.device = "cpu"
    e.agent.controller = DictController()
    e.agent.controller.controllers = {}
    arms = e.agent.controller.controllers
    evidence = repo / "docs/variation/evidence/package_opening/pr31_r1_g3" / stage
    report, signatures = [json.loads(gzip.decompress((evidence / (key + ".json.gz")).read_bytes()))
                          for key in ("report", "signatures")]
    initial = signatures[report["A5"][0]["before"]["control_targets"]][0]["arm_impedance_qpos"]
    for full_name, rest in initial.items():
        name = full_name.split("/")[-1]
        arm = Arm()
        arm.scene, arm.device = e.scene, "cpu"
        arm.config = NS(stiffness=[1.] * 7, force_limit=[40.] * 7)
        # Use the author's recorded reset pose and offset just the first joint.
        arm.qpos = torch.tensor([rest, rest])
        arm._normalize_action = False
        arm.action_space = NS(shape=(2, 7))
        arm._apply_impedance_torque = noop
        command = arm.qpos.clone()
        command[:, 0] += torch.tensor([.125, -.125])
        arm.set_action(command)
        arms[name] = arm
    def set_joint_position(qpos):
        for arm in arms.values():
            arm.qpos[e.scene._reset_mask] = qpos
    e.agent.get_reset_pos = lambda device: torch.tensor(next(iter(initial.values())))
    e.agent.robot = NS(max_dof=7, set_qpos=set_joint_position, set_qvel=noop, set_qf=noop, set_root_pose=noop)
    def target():
        return {k: v._target_qpos.clone() for k, v in arms.items()}
    e.get_info = lambda: {"target": target(), "mask": e.scene._reset_mask.tolist()}
    e.get_obs = lambda info: target()
    before = target()
    obs, info = e.reset(options={"env_idx": torch.tensor([selected])})
    after = target()
    for k in arms:
        assert before[k][other, 0] != arms[k].qpos[other, 0]
        assert torch.equal(after[k], obs[k]) and torch.equal(after[k], info["target"][k])
    print(json.dumps(dict(task=stage, selected=selected, other=other, mask=info["mask"],
                          other_before={k: float(v[other, 0]) for k, v in before.items()},
                          other_after={k: float(v[other, 0]) for k, v in after.items()},
                          other_qpos={k: float(v.qpos[other, 0]) for k, v in arms.items()},
                          other_step=int(e._elapsed_steps[other]),
                          isolated=all(torch.equal(v[other], after[k][other]) for k,v in before.items()))))


for stage, task in tasks.items():
    for selected in (0, 1):
        witness(stage, task, selected)
