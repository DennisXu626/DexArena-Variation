"""ManiSkill 3.0.0b22 reset/action method excerpts (Apache-2.0).
Source hashes in SDK_SOURCE_HASHES; physics I/O is replaced only in tests.
"""

from __future__ import annotations

import torch

import numpy as np

class BaseEnv(object):

    def reset(self, seed: Union[None, int, list[int]]=None, options: Union[None, dict]=None):
        """Reset the ManiSkill environment with given seed(s) and options. Typically seed is either None (for unseeded reset) or an int (seeded reset).
        For GPU parallelized environments you can also pass a list of seeds for each parallel environment to seed each one separately.

        If options["env_idx"] is given, will only reset the selected parallel environments. If
        options["reconfigure"] is True, will call self._reconfigure() which deletes the entire physx scene and reconstructs everything.
        Users building custom tasks generally do not need to override this function.

        If options["reset_to_env_states"] is given, we expect there to be options["reset_to_env_states"]["env_states"] and optionally options["reset_to_env_states"]["obs"], both with
        batch size equal to the number of environments being reset. "env_states" can be a dictionary or flat tensor and we skip calling the environment's _initialize_episode function which
        generates the initial state on a normal reset. If "obs" is given we skip calling the environment's get_obs function which can save some compute/time.

        Returns the observations and an info dictionary. The info dictionary is of type


        .. highlight:: python
        .. code-block:: python

            {
                "reconfigure": bool # (True if the env reconfigured. False otherwise)
            }



        Note that ManiSkill always holds two RNG states, a main RNG, and an episode RNG. The main RNG is used purely to sample an episode seed which
        helps with reproducibility of episodes and is for internal use only. The episode RNG is used by the environment/task itself to
        e.g. randomize object positions, randomize assets etc. Episode RNG is accessible by using `self._batched_episode_rng` which is numpy based and `torch.rand`
        which can be used to generate random data on the GPU directly and is seeded. Note that it is recommended to use `self._batched_episode_rng`
        if you need to ensure during reconfiguration the same objects are loaded. Reproducibility and seeding when there is GPU and CPU simulation can be tricky and we recommend reading
        the documentation for more recommendations and details on RNG https://maniskill.readthedocs.io/en/latest/user_guide/concepts/rng.html

        Upon environment creation via gym.make, the main RNG is set with fixed seeds of 2022 to 2022 + num_envs - 1 (seed is just 2022 if there is only one environment)
        During each reset call, if seed is None, main RNG is unchanged and an episode seed is sampled from the main RNG to create the episode RNG.
        If seed is not None, main RNG is set to that seed and the episode seed is also set to that seed. This design means the main RNG determines
        the episode RNG deterministically.

        """
        if options is None:
            options = dict()
        reconfigure = options.get('reconfigure', False)
        reconfigure = reconfigure or (self._reconfig_counter == 0 and self.reconfiguration_freq != 0)
        if 'env_idx' in options:
            env_idx = options['env_idx']
            if len(env_idx) != self.num_envs and reconfigure:
                raise RuntimeError('Cannot do a partial reset and reconfigure the environment. You must do one or the other.')
        else:
            env_idx = torch.arange(0, self.num_envs, device=self.device)
        self._set_main_rng(seed)
        if reconfigure:
            self._set_episode_rng(seed if seed is not None else self._batched_main_rng.randint(2 ** 31), env_idx)
            with torch.random.fork_rng():
                torch.manual_seed(seed=self._episode_seed[0])
                self._reconfigure(options)
                self._after_reconfigure(options)
            self._set_episode_rng(self._episode_seed, env_idx)
        else:
            self._set_episode_rng(seed, env_idx)
        self.scene._reset_mask = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)
        self.scene._reset_mask[env_idx] = True
        self._elapsed_steps[env_idx] = 0
        self._clear_sim_state()
        if self.reconfiguration_freq != 0:
            self._reconfig_counter -= 1
        if self.agent is not None:
            self.agent.reset()
        reset_to_env_states_obs = None
        if 'reset_to_env_states' in options:
            env_states = options['reset_to_env_states']['env_states']
            reset_to_env_states_obs = options['reset_to_env_states'].get('obs', None)
            if isinstance(env_states, dict):
                self.set_state_dict(env_states, env_idx)
            else:
                self.set_state(env_states, env_idx)
        elif seed is not None or self._enhanced_determinism:
            with torch.random.fork_rng():
                torch.manual_seed(self._episode_seed[0])
                self._initialize_episode(env_idx, options)
        else:
            self._initialize_episode(env_idx, options)
        self.scene._reset_mask = torch.ones(self.num_envs, dtype=bool, device=self.device)
        if self.gpu_sim_enabled:
            self.scene._gpu_apply_all()
            self.scene.px.gpu_update_articulation_kinematics()
            self.scene._gpu_fetch_all()
        if self.agent is not None:
            if isinstance(self.agent.controller, dict):
                for controller in self.agent.controller.values():
                    controller.reset()
            else:
                self.agent.controller.reset()
        info = self.get_info()
        if reset_to_env_states_obs is None:
            obs = self.get_obs(info)
        else:
            obs = self._last_obs
            tree.replace(obs, env_idx, common.to_tensor(reset_to_env_states_obs, device=self.device))
        info['reconfigure'] = reconfigure
        self._last_obs = obs
        return (obs, info)

class BaseAgent(object):

    def set_action(self, action):
        """
        Set the agent's action which is to be executed in the next environment timestep.
        This is essentially a wrapper around the controller's set_action method.
        """
        if not self.scene.gpu_sim_enabled:
            if np.isnan(action).any():
                raise ValueError('Action cannot be NaN. Environment received:', action)
        self.controller.set_action(action)

    def reset(self, init_qpos: torch.Tensor=None):
        """
        Reset the robot to a clean state with zero velocity and forces.

        Args:
            init_qpos (torch.Tensor): The initial qpos to set the robot to. If None, the robot's qpos is not changed.
        """
        if init_qpos is not None:
            self.robot.set_qpos(init_qpos)
        self.robot.set_qvel(torch.zeros(self.robot.max_dof, device=self.device))
        self.robot.set_qf(torch.zeros(self.robot.max_dof, device=self.device))

class BaseController(object):

    def reset(self):
        """Resets the controller to an initial state. This is called upon environment creation and each environment reset"""

    def _preprocess_action(self, action: Array):
        if self.scene.num_envs > 1:
            action_dim = self.action_space.shape[1]
        else:
            action_dim = self.action_space.shape[0]
        assert action.shape == (self.scene.num_envs, action_dim), (action.shape, action_dim)
        if self._normalize_action:
            action = self._clip_and_scale_action(action)
        return action

class DictController(BaseController):

    def reset(self):
        for controller in self.controllers.values():
            controller.reset()

class CombinedController(DictController):

    def set_action(self, action: np.ndarray):
        if self.scene.num_envs > 1:
            action_dim = self.action_space.shape[1]
        else:
            action_dim = self.action_space.shape[0]
        assert action.shape == (self.scene.num_envs, action_dim), f'Received action of shape {action.shape} but expected shape ({self.scene.num_envs}, {action_dim})'
        for uid, controller in self.controllers.items():
            start, end = self.action_mapping[uid]
            controller.set_action(action[:, start:end])

    def from_action_dict(self, action_dict: dict):
        """Convert a dict of actions to a flat action."""
        return torch.hstack([action_dict[uid] for uid in self.controllers])

class PDJointPosController(BaseController):

    def reset(self):
        super().reset()
        self._step = 0
        if self._start_qpos is None:
            self._start_qpos = self.qpos.clone()
        else:
            self._start_qpos[self.scene._reset_mask] = self.qpos[self.scene._reset_mask].clone()
        if self._target_qpos is None:
            self._target_qpos = self.qpos.clone()
        else:
            self._target_qpos[self.scene._reset_mask] = self.qpos[self.scene._reset_mask].clone()

    def set_drive_targets(self, targets):
        self.articulation.set_joint_drive_targets(targets, self.joints, self.active_joint_indices)

    def set_action(self, action: Array):
        action = self._preprocess_action(action)
        self._step = 0
        self._start_qpos = self.qpos
        if self.config.use_delta:
            if self.config.use_target:
                self._target_qpos = self._target_qpos + action
            else:
                self._target_qpos = self._start_qpos + action
        else:
            self._target_qpos = torch.broadcast_to(action, self._start_qpos.shape).clone()
        if self.config.interpolate:
            self._step_size = (self._target_qpos - self._start_qpos) / self._sim_steps
        else:
            self.set_drive_targets(self._target_qpos)

SDK_SOURCE_HASHES = {'envs/sapien_env.py': '83066a0e68f8679b02aa7afc56b7f5fcea1e1886b31e9cf50e1aaa3758f56f2c', 'agents/base_agent.py': '64b0c9f45577ef842ae41449af36529e476ad68d26e726de5c9d858496f8824d', 'agents/controllers/base_controller.py': 'a39aa1ec3666ccca4820d0c8c42d3422b266a5a2561c0ca38ab34e42a9d5c249', 'agents/controllers/pd_joint_pos.py': 'ce05feb05c4370ec2be58c60465082dde15fd97e6398a187a648a5e932a4d58e'}
