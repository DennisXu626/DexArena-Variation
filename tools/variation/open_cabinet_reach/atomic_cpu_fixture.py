"""Run the installed SDK's Python reset code on a two-row CPU tensor scene.

Pass the exact sapien_env.py and batched_rng.py sources from the runtime
installation. Actor writes below stand in for PhysX setters.
"""
import ast
import hashlib
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import torch


def definitions(path, name, keep, scope, parent=None):
    tree = ast.parse(path.read_bytes())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    cls.decorator_list = []
    if keep is not None:
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in keep]
        assert {n.name for n in cls.body} == set(keep)
    if parent is not None:
        scope["Parent"] = parent
        cls.bases = [ast.Name("Parent", ast.Load())]
    module = ast.fix_missing_locations(ast.Module([cls], []))
    exec(compile(module, str(path), "exec",
                 flags=__import__("__future__").annotations.compiler_flag), scope)
    return scope[name]


def build(sdk, rng_source):
    root = Path(__file__).resolve().parents[3] / "tasks/cabinet_pouring"
    pkg = types.ModuleType("atomic_cpu_cabinet")
    pkg.__path__ = [str(root)]
    sys.modules[pkg.__name__] = pkg
    sampler = importlib.import_module(pkg.__name__ + ".open_cabinet_workspace")
    geometry = importlib.import_module(pkg.__name__ + ".start_clearance")
    common = NS(to_numpy=lambda v, dtype=None: np.asarray(v, dtype=dtype))
    scope = dict(np=np, torch=torch, common=common, __package__=pkg.__name__)
    scope["BatchedRNG"] = definitions(rng_source, "BatchedRNG", None, scope)
    base = definitions(sdk, "BaseEnv", {"reset", "_set_main_rng", "_set_episode_rng"}, scope, object)
    long_path = root / "cabinet_pouring_long.py"
    constants = ast.parse(long_path.read_bytes())
    home = next(n for n in constants.body if isinstance(n, ast.Assign) and
                isinstance(n.targets[0], ast.Name) and n.targets[0].id == "DEFAULT_ARM_INIT_QPOS")
    exec(compile(ast.Module([home], []), str(long_path), "exec"), scope)
    long = definitions(long_path, "CabinetPouringLongEnv",
                       {"_initial_robot_qpos", "_initialize_workspace"}, scope, base)
    task = definitions(root / "cabinet_pouring_open_cabinet.py", "CabinetPouringOpenCabinetEnv",
                       {"reset", "_initialize_episode", "_workspace_arm_draw"}, scope, long)

    class Scene(task):
        def __init__(self, enabled=True):
            self.unwrapped = self
            self.num_envs = 2
            self.device = torch.device("cpu")
            self._handle_workspace = enabled
            self._workspace_next_seed = {}
            self._reconfig_counter = self.reconfiguration_freq = 0
            self._enhanced_determinism = self.gpu_sim_enabled = False
            self._main_seed = self._batched_episode_rng = None
            self._batched_rng_backend = "numpy:random_state"
            self.robot_init_qpos_noise = .02
            self._robot_base_pose = None
            self._family_appearance = self._cabinet_appearance = None
            self._elapsed_steps = torch.zeros(2, dtype=torch.int32)
            self.scene = NS(_reset_mask=torch.ones(2, dtype=torch.bool))
            self.q = torch.zeros(2, 9)
            self.pose = torch.zeros(2, 3)
            self.table = torch.zeros(2)
            self.velocity = torch.ones(2)
            self.latch = torch.ones(2, dtype=torch.bool)
            names = ["joint_" + str(i) for i in range(9)]
            self.agent = NS(arm_joint_names=names[:7],
                            keyframes={"rest": NS(qpos=np.arange(9, dtype=np.float32)/10)},
                            reset=self.apply, controller=NS(reset=lambda: None),
                            robot=NS(get_active_joints=lambda: [NS(name=n) for n in names],
                                     set_root_pose=lambda pose: None))
            self.table_scene = NS(initialize=lambda idx: None)
            self.reset(seed=[2022, 2023], options={"reconfigure": True})

        def _reconfigure(self, options): pass
        def _after_reconfigure(self, options): pass
        def close(self): pass
        def get_obs(self, info): return self.pose.clone()
        def get_info(self): return {}
        def _clear_sim_state(self): self.velocity[self.scene._reset_mask] = 0
        def _set_work_table_pose(self): self.table[self.scene._reset_mask] = .18
        def _reset_episode_buffers(self, idx): self.latch[idx] = False
        def apply(self, q=None): self.q[self.scene._reset_mask] = 0 if q is None else q
        def _initialize_cabinet(self, idx, b, door_open, layout):
            assert not door_open
            self.pose[idx] = torch.tensor([[.14, .12, 15.]] if layout is None else layout[:, :3])
        def get_state_dict(self):
            return dict(q=self.q, cabinet=self.pose, table=self.table, velocity=self.velocity, task=self.latch)

    def measure(e, i):
        pose, arm = e.pose[i].tolist(), e.q[i, :7].tolist()
        assert torch.equal(e.q[i, 7:], torch.tensor([.7, .8]))
        end = geometry.pregrasp(geometry.geometry(), pose[:2], pose[2])
        (gap, _), _ = geometry.clearance(pose[:2], pose[2], np.array(arm), end)
        return pose, arm, gap

    identity = {p.name: hashlib.sha256(p.read_text(encoding="utf8").encode()).hexdigest()
                for p in (sdk, rng_source)}
    return Scene, sampler, geometry, measure, identity
