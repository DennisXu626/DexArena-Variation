"""Stage 1 of ``CabinetPouringLong-Sharpa-v1``: swing the cabinet door open.

Only the cabinet stands on the work table -- the bottle, its cap and the bowl
are all left out, since this stage never touches them.  The cabinet is placed
and randomised over exactly the range the long-horizon task uses, its door
starts shut, and everything else (table, robot start pose, cameras)
is inherited from ``CabinetPouringLongEnv``.

Success is the long task's first milestone, ``stage_door_open``, with the
same 80-degree acceptance angle as the full task, held for
five consecutive control steps as in every other task in the repo.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tasks.config.hands import register_task
from mani_skill.utils.wrappers.record import RecordEpisode

from tasks.cabinet_pouring.cabinet_pouring_long import (
    DEFAULT_ARM_INIT_QPOS, DEFAULT_CONTROL_MODE, DEFAULT_ROBOT_UID_LEFT, CabinetPouringLongEnv,
)


ENV_ID = "CabinetPouringOpenCabinet-Sharpa-v1"

MAX_EPISODE_STEPS = 600


@register_task(
    "CabinetPouringOpenCabinet",
    side="left",
    max_episode_steps=MAX_EPISODE_STEPS,
    obs_mode="state",
    control_mode=DEFAULT_CONTROL_MODE,
    reward_mode="sparse",
    render_mode="rgb_array",
)
class CabinetPouringOpenCabinetEnv(CabinetPouringLongEnv):
    """Cabinet only; open the door past 80 degrees."""

    has_bottle = False
    has_cap = False
    has_target = False
    placement_region = None
    lock_bottle_during_cap_stages = False

    def __init__(self, *args, handle_workspace=False, **kwargs):
        if handle_workspace and kwargs.get("robot_uids") != DEFAULT_ROBOT_UID_LEFT:
            raise ValueError("handle_workspace requires the registered left angled Sharpa arm")
        self._handle_workspace = handle_workspace
        self._workspace_next_seed = {}  # Advanced only for a successfully reset environment.
        super().__init__(*args, **kwargs)

    def _workspace_arm_draw(self, seed):
        # The constructor also enters reset, before the articulation exists.
        # Same seven native means, Gaussian noise and device, with a private RNG.
        generator = torch.Generator(device=self.device).manual_seed(seed)
        home = torch.tensor(DEFAULT_ARM_INIT_QPOS, dtype=torch.float32, device=self.device)
        noise = torch.randn(home.shape, dtype=home.dtype, device=self.device, generator=generator)
        return home + noise * self.robot_init_qpos_noise

    def reset(self, seed=None, options=None):
        options = {} if options is None else options
        if not self._handle_workspace or "reset_to_env_states" in options:
            return super().reset(seed=seed, options=options)
        if "position_layout" in options:
            if "handle_placement" in options:
                raise ValueError("handle_placement requires a single layout request")
            return super().reset(seed=seed, options=options)

        # BaseEnv.reset writes the reset mask, elapsed steps and GPU buffers.
        # Finish every fallible placement check before crossing that boundary.
        from .open_cabinet_workspace import resolve_workspace

        indices = list(range(self.num_envs))
        if "env_idx" in options:
            selected = torch.as_tensor(options["env_idx"], device=self.device)
            if selected.ndim != 1 or selected.dtype not in (torch.int32, torch.int64):
                raise ValueError("env_idx must contain integer environment indices")
            indices = sorted(selected.tolist())
            if (not indices or indices[0] < 0 or indices[-1] >= self.num_envs
                    or len(indices) != len(set(indices))):
                raise ValueError("env_idx must contain distinct, in-range environment indices")
            # Articulation setters consume rows in boolean-mask (scene index) order.
            options = {**options, "env_idx": selected.new_tensor(indices, dtype=torch.long)}
        seeds = self._workspace_next_seed.copy()
        if seed is not None:
            values = np.atleast_1d(seed).tolist()
            if len(values) == 1:
                expansion = np.random.RandomState(values[0])
                values += expansion.randint(2**31, size=self.num_envs - 1).tolist()
            if len(values) != self.num_envs:
                raise ValueError("Expected one seed or one per environment")
            seeds.update((i, values[i]) for i in indices)
        streams = {i: np.random.RandomState(seeds[i]) for i in indices}
        arm = torch.stack([self._workspace_arm_draw(int(streams[i].randint(2**31))) for i in indices])
        layout = resolve_workspace(self, indices, options.get("handle_placement"),
                                   start_qpos=arm.cpu().numpy(), streams=streams)
        seeds.update((i, int(streams[i].randint(2**31))) for i in indices)
        result = super().reset(seed=seed, options={**options, "_workspace_plan": (layout, arm)})
        self._workspace_next_seed = seeds
        return result

    def _initialize_episode(self, env_idx: torch.Tensor, options: dict):
        from .position_layout import requested_layout
        if "handle_placement" in options and (not self._handle_workspace or "position_layout" in options):
            raise ValueError("handle_placement requires handle_workspace and a single layout request")
        layout = requested_layout(options, env_idx, "OpenCabinet")
        with torch.device(self.device):
            b = len(env_idx)
            if self._handle_workspace and layout is None:
                layout, arm = options["_workspace_plan"]
                self.table_scene.initialize(env_idx)
                self._set_work_table_pose()
                # For this single-arm registration, rest is in active joint order.
                start = torch.as_tensor(self.agent.keyframes["rest"].qpos, device=self.device,
                                        dtype=torch.float32).expand(b, -1).clone()
                names = [joint.name for joint in self.agent.robot.get_active_joints()]
                start[:, [names.index(name) for name in self.agent.arm_joint_names]] = arm
                self._reset_episode_buffers(env_idx)
                self.agent.reset(start)
                self.agent.robot.set_root_pose(self._robot_base_pose)
            else:
                self._reset_episode_buffers(env_idx)
                self._initialize_workspace(env_idx)
            self._initialize_cabinet(env_idx, b, door_open=False, layout=layout)
            if self._family_appearance is not None:
                self._finish_family_appearance(env_idx, options)
            elif self._cabinet_appearance is not None:
                self._cabinet_appearance.finish_reset(env_idx, options)

    def evaluate(self):
        with torch.device(self.device):
            door_angle, door_open_now, door_open = self._door_status()
            self._stage_door |= door_open
            return dict(
                door_angle=door_angle,
                door_angle_deg=torch.rad2deg(door_angle),
                door_open_now=door_open_now,
                door_open=door_open,
                door_open_hold_count=self._door_open_hold_count.clone(),
                stage_door_open=self._stage_door.clone(),
                success_condition=door_open,
                success=door_open,
            )

    def _get_obs_extra(self, info: dict):
        obs = dict(
            tcp_pose=self.agent.tcp.pose.raw_pose,
            door_qpos=info["door_angle"][:, None],
        )
        if "state" in self.obs_mode:
            obs.update(
                door_pose=self.door_link.pose.raw_pose,
                cabinet_xy=self._cabinet_episode_xy,
                tcp_to_door_pos=self.door_link.pose.p - self.agent.tcp.pose.p,
                stages=info["stage_door_open"][:, None].float(),
            )
        return obs

    def compute_sparse_reward(self, obs: Any, action: torch.Tensor, info: dict):
        return info["stage_door_open"].to(torch.float32)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env_id", default=ENV_ID)
    parser.add_argument("--robot_uids", default=DEFAULT_ROBOT_UID_LEFT)
    parser.add_argument("--control_mode", default=DEFAULT_CONTROL_MODE)
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output_dir", default="videos/cabinet_pour_door_open")
    args = parser.parse_args()

    env = gym.make(
        args.env_id,
        num_envs=1,
        obs_mode="state",
        reward_mode="sparse",
        robot_uids=args.robot_uids,
        control_mode=args.control_mode,
        render_mode="rgb_array",
    )
    env = RecordEpisode(
        env,
        output_dir=args.output_dir,
        save_trajectory=False,
        save_video_trigger=lambda episode_idx: True,
        max_steps_per_video=args.steps,
        video_fps=25,
    )
    print("Observation space", env.observation_space)
    print("Action space", env.action_space)
    print("Robot DoF", env.unwrapped.agent.robot.dof)

    env.reset(seed=args.seed)
    for step in range(args.steps):
        _, reward, terminated, truncated, info = env.step(env.action_space.sample())
        env.render()
        if step % 25 == 0:
            print(
                f"step {step}: door {float(info['door_angle_deg']):.1f} deg  "
                f"reward {float(reward):.1f}"
            )
        if bool(terminated.any()) or bool(truncated.any()):
            break
    env.close()
