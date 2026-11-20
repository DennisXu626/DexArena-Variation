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
        previous = getattr(self, "_juice_reset_mask", None)
        mask = None
        if selected is not None:
            mask = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)
            mask[indices] = True
        self._juice_reset_mask = mask
        try:
            return super().reset(seed=seed, options=options)
        finally:
            self._juice_reset_mask = previous

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
