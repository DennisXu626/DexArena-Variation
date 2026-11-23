"""R4 regression derived from AUTHOR state_restore_probe.py.

Arguments: repository root, ManiSkill 3.0.0b22 package directory, optional output JSON.
Real reset/set_state_dict/scene methods; CPU pose and contact doubles, no physics.
"""
from __future__ import annotations

import ast
import copy
import itertools
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

repo, sdk = map(Path, sys.argv[1:3])
long_task = repo / "tasks/table_cleaning/table_cleaning_long.py"
pick_task = repo / "tasks/table_cleaning/table_cleaning_pick_debris.py"
env_source = sdk / "envs/sapien_env.py"
controller_source = repo / "tasks/robots/franka_joint_impedance_controller.py"
common = SimpleNamespace(to_numpy=lambda x, dtype=None: np.asarray(x, dtype=dtype))

def extract(path, name, methods=None, parent=object):
    node = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n, ast.ClassDef) and n.name == name)
    node.decorator_list = []
    node.bases = [ast.Name(id="Parent", ctx=ast.Load())]
    if methods is not None:
        node.body = [m for m in node.body if isinstance(m, ast.FunctionDef) and m.name in methods]
        assert {m.name for m in node.body} == set(methods)
    ns = dict(globals(), Parent=parent)
    tree = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(tree, str(path), "exec"), ns)
    return ns[name]

BatchedRNG = extract(sdk / "envs/utils/randomization/batched_rng.py", "BatchedRNG", parent=np.random.RandomState)
Base = extract(env_source, "BaseEnv", ["reset", "_set_main_rng", "_set_episode_rng", "get_info",
                                      "set_state_dict", "get_obs", "_get_obs_state_dict", "_flatten_raw_obs"])
ControllerBase = extract(sdk / "agents/controllers/base_controller.py", "BaseController", ["reset"])
Controller = extract(controller_source, "FrankaJointImpedanceController", ["reset"], ControllerBase)
ROBOT_ROOT = None
HOLD_STEPS = 8
Task = extract(long_task, "TableCleanBase", ["set_state_dict", "reset", "get_info", "_get_obs_extra", "_debris_in_pan", "_update_pick", "_latch"], Base)
Pick = extract(pick_task, "TableCleaningPickDebrisEnv", ["evaluate"], Task)

CATALOG = repo / "tasks/assets/variation/table_cleaning/v1/catalog.json"
Appearance = extract(repo / "tasks/table_cleaning/appearance.py", "CleaningAppearance", ["__init__", "resolve_requests"])

def fixture(enabled):
    e = Pick()
    e.device, e.num_envs, e._obs_mode = "cpu", 2, "state_dict"
    e.obs_mode_struct = SimpleNamespace(state=False)
    e._enhanced_determinism, e.reconfiguration_freq, e._reconfig_counter = False, 0, 0
    e._batched_rng_backend = "numpy:random_state"
    e._main_seed = e._batched_episode_rng = None
    e._set_main_rng(7)
    e._set_episode_rng(7, torch.arange(2))
    e.FLAG_NAMES = ("f_picked", "f_grasp_pan", "f_poured", "f_stow_pan")
    for k in (*e.FLAG_NAMES, "success_latched"):
        setattr(e, k, torch.zeros(2, dtype=torch.bool))
    e._elapsed_steps, e.stage, e.hold = [torch.zeros(2, dtype=torch.long) for _ in range(3)]
    e.elapsed_steps = e._elapsed_steps
    e.gpu_sim_enabled = False
    e.scene = SimpleNamespace(_reset_mask=torch.ones(2, dtype=torch.bool))
    arm = Controller()
    arm.device, arm.scene = "cpu", e.scene
    arm.config = SimpleNamespace(stiffness=[100.]*7, force_limit=[40.]*7)
    arm.qpos = torch.zeros(2, 7)
    arm._target_qpos = torch.full((2, 7), .25)
    pan_pose = SimpleNamespace(p=torch.zeros(2, 3), raw_pose=torch.zeros(2, 7),
                               to_transformation_matrix=lambda: torch.eye(4).repeat(2, 1, 1))
    e.agent = SimpleNamespace(reset=lambda: None, controller=arm, tcp=SimpleNamespace(pose=pan_pose))
    e.pan = SimpleNamespace(pose=pan_pose)
    e.bin = SimpleNamespace(pose=pan_pose)
    e._pan_lo, e._pan_hi = [-1., -1., 0.], [1., 1., 1.]
    e.PAN_STATIC_STEP, e.PAN_FLOOR_BAND, e.STAGE_ONE_HOT_CLASSES = .003, .09, 2
    e._pick_target = 3
    e.debris = [SimpleNamespace(pose=SimpleNamespace(p=torch.tensor([[0., 0., .02]]*2))) for _ in range(3)]
    e._debris_local_prev = [a.pose.p + torch.tensor([.01, 0., 0.]) for a in e.debris]
    e._any_debris_grasped = lambda: torch.zeros(2, dtype=torch.bool)
    e._debris_in_bin = lambda: torch.zeros(2)
    e.cleaning_appearance = Appearance({"scheme_id":"variant_1"}, 2) if enabled else None
    e._get_obs_agent = lambda: {}
    e._clear_sim_state = lambda: None
    e._initialize_episode = lambda indices, options: None
    return e

def next_draw(rng):
    return int(copy.deepcopy(rng).randint(2**31))



Scene = extract(sdk/'envs/scene.py', 'ManiSkillScene', ['set_sim_state'])
records = []
for selected, enabled, mode, with_task in itertools.product((0, 1), (False, True), ('direct', 'reset'), (False, True)):
    e=fixture(enabled)
    e.TASK_STATE_DIM=7
    e.hold=e.hold.to(torch.int32)
    e.agent.robot=SimpleNamespace(set_root_pose=lambda pose: None)
    e.scene=Scene()
    e.scene._reset_mask=torch.ones(2,dtype=torch.bool)
    e.agent.controller.scene=e.scene
    actors={}
    def setter(actor):
        def set_state(value,idx):
            actor.pose.p[e.scene._reset_mask] = value[:,:3]
        return set_state
    for i, actor in enumerate(e.debris):
        actors[str(i)]=SimpleNamespace(set_state=setter(actor))
    e.scene.state_dict_registry=SimpleNamespace(actors=actors)
    e._debris_local_prev=[a.pose.p.clone() for a in e.debris]
    e.get_info()
    other = 1 - selected
    neighbour_step = e._debris_motion_step[other].clone()
    neighbour_still = [value[other].clone() for value in e._debris_still]
    neighbour_previous = [value[other].clone() for value in e._debris_local_prev]
    e.stage[selected] = 0
    e.f_picked[selected] = False
    e.success_latched[selected] = False
    e.hold[selected] = 0
    target=torch.tensor([[.01,0.,.02,1.,0.,0.,0.,0.,0.,0.,0.,0.,0.]])
    saved={'actors':{str(i):target.clone() for i in range(3)},'table_clean_task_state':torch.zeros(1,7)}
    if not with_task:
        saved.pop('table_clean_task_state')
    if mode == 'reset':
        obs,info=e.reset(options={'env_idx':torch.tensor([selected]),'reset_to_env_states':{'env_states':saved}})
    else:
        e.set_state_dict(saved, torch.tensor([selected]))
        info=e.get_info()
        obs=e.get_obs(info)
    assert info['n_in_pan'][selected].item() == 0
    assert obs['extra']['n_in_pan'][selected].item() == 0
    assert info['stage'][selected].item() == 0
    assert e._debris_motion_step[other].item() == neighbour_step.item()
    for still, previous, old_still, old_previous in zip(e._debris_still, e._debris_local_prev, neighbour_still, neighbour_previous):
        torch.testing.assert_close(still[other], old_still)
        torch.testing.assert_close(previous[other], old_previous)
    for _ in range(2):
        repeated=e.get_info()
        assert repeated['n_in_pan'][selected].item() == 0
        assert repeated['n_in_pan'][other].item() == 3
        assert repeated['stage'][selected].item() == 0
    e._elapsed_steps += 1
    advanced=e.get_info()
    assert advanced['n_in_pan'][selected].item() == 3
    assert advanced['stage'][selected].item() == 1
    record=dict(selected=selected,appearance=enabled,mode=mode,task_state=with_task,
                first_count=0,first_stage=0,repeated_count=0,neighbour_count=3,next_step_count=3,next_step_stage=1)
    records.append(record)
    print(json.dumps(record))
if len(sys.argv) > 3:
    Path(sys.argv[3]).write_text(json.dumps(dict(passed=True,cases=records),indent=2)+'\n',encoding='utf-8')
