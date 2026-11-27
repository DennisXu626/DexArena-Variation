"""Office reset bookkeeping using the indexed reset support already in main."""
import copy
import numpy as np
import torch

from tasks.furniture_assembly.reset_scope import FurnitureResetScopeMixin, is_full_reset
from tasks.office_desk.devices_appearance import (
    resolve_reset_requests, validate_reset_indices, validate_reset_override,
)
from tasks.office_desk.position_layout import resolve_position_layout


def office_capacity_config(config, kwargs):
    """Allow only solver buffer capacities through the locked physics config."""
    if isinstance(config, dict) and set(config) == {'gpu_memory_config'}:
        capacities = config['gpu_memory_config']
        allowed = {'max_rigid_contact_count', 'max_rigid_patch_count', 'found_lost_pairs_capacity'}
        if (not isinstance(capacities, dict) or set(capacities) != allowed
                or any(type(value) is not int or value <= 0 for value in capacities.values())):
            raise ValueError('Office GPU capacities require exactly three positive integer capacities')
        kwargs['sim_config'] = copy.deepcopy(config)
        return None
    return config


class OfficeResetScopeMixin(FurnitureResetScopeMixin):
    def _configure_position_workspace(self, kwargs, num_envs, supported):
        enabled = kwargs.pop('position_workspace', False)
        if not isinstance(enabled, bool) or (enabled and not supported):
            raise ValueError('Office position_workspace requires the screened Sharpa, fingertip and asset configuration')
        self.position_workspace = None
        if enabled:
            from tasks.office_desk.position_workspace import OfficeWorkspace
            self.position_workspace = OfficeWorkspace(self._position_device_name, num_envs)

    def reset(self, seed=None, options=None):
        env_idx = options.get('env_idx') if options is not None else None
        workspace = getattr(self, 'position_workspace', None)
        if options is not None and 'workspace_placement' in options and workspace is None:
            raise ValueError('workspace_placement requires position_workspace=True')
        if (workspace is not None and env_idx is not None
                and 'position_layout' not in options and 'reset_to_env_states' not in options):
            # Native Office selection expects ascending IDs. The public layout is keyed by actual env ID.
            supplied = env_idx.tolist() if hasattr(env_idx, 'tolist') else env_idx
            if isinstance(supplied, (tuple, list)) and all(type(i) is int for i in supplied):
                env_idx = sorted(supplied)
        selected = range(self.num_envs)
        if env_idx is not None:
            selected = validate_reset_indices(env_idx, self.num_envs)
        elif options is not None and 'env_idx' in options:
            options = dict(options)
            del options['env_idx']
        if seed is not None and not is_full_reset(env_idx, self.num_envs):
            raise ValueError('Office partial reset must omit seed; reseed only a full reset')
        if hasattr(self, '_mouse_appearance'):
            channels = ('mouse_appearance',)
        else:
            channels = ('office_devices_appearance', 'office_keyboard_appearance')
        restoring = options is not None and 'reset_to_env_states' in options
        for key in channels:
            override = {}
            if options is not None and key in options:
                if restoring:
                    raise ValueError('Office state restoration cannot include an appearance override')
                override = options[key]
                validate_reset_override(override, self.num_envs)
            appearance = getattr(self, '_' + key, None)
            if appearance is not None and not restoring:
                resolve_reset_requests(appearance.config, override, selected, appearance.catalog['schemes'])
        if env_idx is not None:
            indices = torch.as_tensor(env_idx, dtype=torch.long, device=self._elapsed_steps.device)
            if indices is not env_idx:
                options = {**options, 'env_idx': indices}
        if options is not None and 'position_layout' in options:
            if restoring:
                raise ValueError('Office state restoration cannot include a position layout')
            layout = resolve_position_layout(
                options['position_layout'], selected, self._position_device_name, self._position_center,
            )
            options = {**options, 'position_layout': layout}
        if workspace is None:
            return super().reset(seed=seed, options=options)
        options, pending = workspace.prepare(selected, seed, options or {})
        result = super().reset(seed=seed, options=options)
        workspace.seeds, workspace.counts, workspace.episodes = pending
        return result

    def _office_rand(self, env_idx, shape):
        if is_full_reset(env_idx, self.num_envs):
            return torch.rand((len(env_idx), *shape), device=self.device)
        return torch.as_tensor(np.stack([
            self._batched_episode_rng[int(i)].uniform(0.0, 1.0, size=shape)
            for i in env_idx
        ]), dtype=torch.float32, device=self.device)

    def _office_normal(self, env_idx, scale, width):
        if is_full_reset(env_idx, self.num_envs):
            return self._episode_rng.normal(0.0, scale, (len(env_idx), width))
        return np.stack([
            self._batched_episode_rng[int(i)].normal(0.0, scale, width)
            for i in env_idx
        ])

    def _office_scoped_results(self, fields, proposed):
        values = list(proposed)
        for index, field in enumerate(fields):
            values[index] = self._reset_scoped_value(getattr(self, field), values[index])
        return tuple(values)
