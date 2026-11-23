"""Juice public-reset validation and selected-row evaluation scope."""
import torch


class JuiceResetMixin:
    def reset(self, seed=None, options=None):
        options = {} if options is None else options
        selected = options.get("env_idx")
        indices = list(range(self.num_envs)) if selected is None else (
            selected.tolist() if hasattr(selected, "tolist") else list(selected))
        appearance = getattr(self, "juice_appearance", None)
        if appearance is not None:
            # No RNG, physics, material or episode-record mutation before this.
            appearance.resolve_requests(indices, options)
        partial = len(set(indices)) < self.num_envs
        if partial and seed is not None:
            raise ValueError("Juice partial reset does not support seed; use a full reset to reseed.")
        saved = []
        if partial and getattr(self, "agent", None) is not None:
            keep = torch.ones(self.num_envs, dtype=torch.bool, device=self.device)
            keep[indices] = False
            def collect(controller):
                if isinstance(controller, dict):
                    for child in controller.values():
                        collect(child)
                    return
                for key, value in vars(controller).items():
                    if torch.is_tensor(value) and value.ndim and value.shape[0] == self.num_envs:
                        saved.append((controller, key, value[keep].clone()))
                for child in getattr(controller, "controllers", {}).values():
                    collect(child)
            collect(self.agent.controller)
        def restore():
            for controller, key, value in saved:
                getattr(controller, key)[keep] = value
        previous_restore = getattr(self, "_juice_restore_controller", None)
        self._juice_restore_controller = restore
        previous = getattr(self, "_juice_reset_mask", None)
        mask = None
        if selected is not None:
            mask = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)
            mask[indices] = True
        self._juice_reset_mask = mask
        try:
            return super().reset(seed=seed, options=options)
        finally:
            restore()
            self._juice_restore_controller = previous_restore
            self._juice_reset_mask = previous

    def get_info(self):
        # BaseEnv resets controllers after restoring the scene mask to all rows.
        # Restore before observations can expose overwritten unselected targets.
        restore = getattr(self, "_juice_restore_controller", None)
        if restore is not None:
            restore()
        return super().get_info()

    def _juice_active_mask(self):
        mask = getattr(self, "_juice_reset_mask", None)
        if mask is None:
            return torch.ones(self.num_envs, dtype=torch.bool, device=self.device)
        return mask

    def _juice_update(self, previous, updated):
        """Keep unselected counters/history during reset; normal steps use updated."""
        mask = getattr(self, "_juice_reset_mask", None)
        if mask is None:
            return updated
        if isinstance(previous, dict):
            return {key: self._juice_update(value, updated[key]) for key, value in previous.items()}
        if isinstance(previous, tuple):
            return tuple(self._juice_update(old, new) for old, new in zip(previous, updated))
        return torch.where(mask.reshape((-1,) + (1,) * (updated.ndim - 1)), updated, previous)
