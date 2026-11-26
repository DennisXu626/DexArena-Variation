"""PR19 CPU reset review fixture. Arguments: repository root and mani_skill package directory."""
from __future__ import annotations

import ast
import copy
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
                                      "get_obs", "_get_obs_state_dict", "_flatten_raw_obs"])
ControllerBase = extract(sdk / "agents/controllers/base_controller.py", "BaseController", ["reset"])
Controller = extract(controller_source, "FrankaJointImpedanceController", ["reset"], ControllerBase)

Juice = extract(repo/'tasks/juice_preparation/reset_guard.py','JuiceResetMixin',['reset','get_info','_juice_active_mask'],Base)
for selected in [0,1]:
 for seed in [None,123]:
    e=Juice(); e.num_envs=2; e.device='cpu'; e._enhanced_determinism=False
    e.reconfiguration_freq=0; e._reconfig_counter=0; e._batched_rng_backend='numpy:random_state'
    e._main_seed=e._batched_episode_rng=None; e._set_main_rng(7); e._set_episode_rng(7,torch.arange(2))
    e._elapsed_steps=torch.zeros(2,dtype=torch.long); e.gpu_sim_enabled=False
    e.scene=SimpleNamespace(_reset_mask=torch.ones(2,dtype=torch.bool))
    arm=Controller();arm.qpos=torch.zeros(2,7);arm._target_qpos=torch.full((2,7),.25)
    arm.scene=e.scene;arm.device='cpu';arm.config=SimpleNamespace(stiffness=[1.]*7,force_limit=[40.]*7)
    e.agent=SimpleNamespace(reset=lambda:None,controller=arm)
    e._clear_sim_state=lambda:None;e._initialize_episode=lambda *args:None;e.evaluate=lambda:{};e.elapsed_steps=e._elapsed_steps;e.get_obs=lambda info:{'target':arm._target_qpos.clone()}
    other=1-selected
    before=int(copy.deepcopy(e._batched_episode_rng[other]).randint(2**31))
    rejected=False
    try:
        obs,info=e.reset(seed=seed,options={'env_idx':torch.tensor([selected])})
    except ValueError as error:
        assert seed is not None and 'partial reset' in str(error)
        rejected=True
    assert rejected == (seed is not None)
    assert torch.equal(arm._target_qpos[other],torch.full((7,),.25))
    if seed is None:
        assert torch.equal(obs['target'][other],torch.full((7,),.25))
        assert torch.equal(arm._target_qpos[selected],torch.zeros(7))
    after=int(copy.deepcopy(e._batched_episode_rng[other]).randint(2**31))
    assert before == after
    print(json.dumps(dict(selected=selected,unselected=other,seed=seed,arm_before=.25,arm_after=float(arm._target_qpos[other,0]),next_before=before,next_after=after)))
