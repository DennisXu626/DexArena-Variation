"""Validate reset options before BaseEnv can change episode state."""
import torch

from tasks.furniture_assembly.reset_scope import FurnitureResetScopeMixin, is_full_reset
from tasks.nut_bolt.appearance import reset_indices, validate_per_env
from tasks.nut_bolt.position_layout import requested_layout


class NutBoltResetScopeMixin(FurnitureResetScopeMixin):
    def get_position_workspace_records(self):
        """Return per-environment replay metadata from the last completed reset."""
        from copy import deepcopy

        workspace = getattr(self, "_nut_workspace", None)
        return deepcopy(workspace.records) if workspace is not None else None

    def _requested_position_layout(self, indices, options):
        if getattr(self, "_nut_workspace_columns", None) is not None:
            return self._nut_workspace_columns
        return requested_layout(self, indices, options)

    def reset(self, seed=None, options=None):
        if options is not None and not isinstance(options, dict):
            raise ValueError('Nut & Bolt reset options must be a dictionary')
        env_idx = options.get('env_idx') if options is not None else None
        if env_idx is not None:
            indices = reset_indices(env_idx, self.num_envs)
        else:
            indices = None
            if options is not None and 'env_idx' in options:
                options = {key: value for key, value in options.items() if key != 'env_idx'}
        if seed is not None and not is_full_reset(indices, self.num_envs):
            raise ValueError('Nut & Bolt partial reset must omit seed; reseed with a full reset')
        selected = range(self.num_envs) if indices is None else indices
        requested_layout(self, selected, options)
        workspace = getattr(self, "_nut_workspace", None)
        if options is not None and "workspace_placement" in options and workspace is None:
            raise ValueError("workspace_placement requires position_workspace=True")
        override = {}
        restoring = options is not None and 'reset_to_env_states' in options
        if options is not None and 'nut_bolt_appearance' in options:
            if restoring:
                raise ValueError('Nut & Bolt state restoration cannot include an appearance override')
            override = options['nut_bolt_appearance']
            validate_per_env(override, self.num_envs)
        if self._nut_bolt_appearance is not None and not restoring:
            self._nut_bolt_appearance.validate_selection(selected, override)
        if env_idx is not None:
            canonical = torch.as_tensor(env_idx, dtype=torch.long, device=self.device)
            if canonical is not env_idx:
                options = {**options, 'env_idx': canonical}
        if workspace is None:
            return super().reset(seed=seed, options=options)
        columns, next_state = workspace.prepare(options or {}, selected, seed)
        self._nut_workspace_columns = columns
        try:
            obs, info = super().reset(seed=seed, options=options)
        finally:
            self._nut_workspace_columns = None
        workspace.seeds, workspace.counts, workspace.records = next_state
        return obs, info
