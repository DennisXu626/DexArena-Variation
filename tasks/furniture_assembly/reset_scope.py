"""Scope bookkeeping and random draws to selected furniture environments."""
import sapien
import torch


_MISSING = object()


def is_full_reset(env_idx, num_envs):
    return env_idx is None or {int(i) for i in env_idx} == set(range(num_envs))


def _require_indexed_gpu_apply():
    capability = getattr(getattr(sapien, 'physx', None), 'indexed_gpu_apply_patch_version', None)
    if not callable(capability) or capability() != 1:
        raise RuntimeError('Furniture partial GPU reset requires SAPIEN indexed_gpu_apply_patch_version() == 1')


def _gpu_apply_selected(scene, env_idx):
    """Apply GPU buffers using PhysX object indices for the selected environments."""
    _require_indexed_gpu_apply()
    assert not scene._needs_fetch, 'Fetch GPU state before applying it again'
    selected = {int(i) for i in env_idx}
    selected = {i + scene.num_envs if i < 0 else i for i in selected}
    rigid_indices = {
        body.gpu_index
        for actor in scene.actors.values() if actor.px_body_type != 'static'
        for i, body in zip(actor._scene_idxs.tolist(), actor._bodies)
        if i in selected
    }
    articulation_indices = {
        raw.gpu_index
        for articulation in scene.articulations.values()
        for i, raw in zip(articulation._scene_idxs.tolist(), articulation._objs)
        if i in selected
    }
    rigid_tensor = torch.tensor(
        sorted(rigid_indices), dtype=torch.int32, device=scene.device,
    ).contiguous()
    articulation_tensor = torch.tensor(
        sorted(articulation_indices), dtype=torch.int32, device=scene.device,
    ).contiguous()
    if rigid_tensor.is_cuda:
        torch.cuda.synchronize(scene.device)
    try:
        if rigid_indices:
            scene.px.gpu_apply_rigid_dynamic_data(sapien.CudaArray(rigid_tensor))
        if articulation_indices:
            indices = sapien.CudaArray(articulation_tensor)
            for buffer in ('qpos', 'qvel', 'qf', 'root_pose', 'root_velocity',
                           'target_position', 'target_velocity'):
                getattr(scene.px, f'gpu_apply_articulation_{buffer}')(indices)
    finally:
        # CudaArray borrows tensor memory; PhysX may consume it on another stream.
        if rigid_tensor.is_cuda:
            torch.cuda.synchronize(scene.device)
    scene._needs_fetch = True


def _reset_controller_selected(scene, env_idx, reset):
    """Keep the selected reset mask active while the controller resets its buffers."""
    previous = scene._reset_mask
    mask = torch.zeros_like(previous)
    mask[env_idx] = True
    scene._reset_mask = mask
    try:
        return reset()
    finally:
        scene._reset_mask = previous


class FurnitureResetScopeMixin:
    def reset(self, seed=None, options=None):
        env_idx = options.get('env_idx') if options is not None else None
        partial = not is_full_reset(env_idx, self.num_envs)
        if partial and (
            options.get('reconfigure', False)
            or (self._reconfig_counter == 0 and self.reconfiguration_freq != 0)
        ):
            raise RuntimeError('Cannot reconfigure during a partial furniture reset')
        scene = self.scene if partial else None
        gpu_scope = partial and self.gpu_sim_enabled
        if gpu_scope:
            _require_indexed_gpu_apply()
        previous_apply = vars(scene).get('_gpu_apply_all', _MISSING) if gpu_scope else _MISSING
        controller_resets = []
        previous_scope = getattr(self, '_furniture_reset_env_idx', _MISSING)
        previous_masks = getattr(self, '_furniture_reset_scope_masks', _MISSING)
        self._furniture_reset_env_idx = None
        self._furniture_reset_scope_masks = {}
        try:
            if options is not None and 'env_idx' in options:
                self._furniture_reset_env_idx = options['env_idx']
            if gpu_scope:
                scene._gpu_apply_all = lambda: _gpu_apply_selected(scene, env_idx)
            if scene is not None and getattr(self, 'agent', None) is not None:
                controllers = self.agent.controller
                controllers = controllers.values() if isinstance(controllers, dict) else [controllers]
                for controller in controllers:
                    previous = vars(controller).get('reset', _MISSING)
                    reset = controller.reset
                    controller_resets.append((controller, previous))
                    controller.reset = lambda reset=reset: _reset_controller_selected(scene, env_idx, reset)
            return super().reset(seed=seed, options=options)
        finally:
            for controller, previous in reversed(controller_resets):
                if previous is _MISSING:
                    del controller.reset
                else:
                    controller.reset = previous
            if gpu_scope:
                if previous_apply is _MISSING:
                    del scene._gpu_apply_all
                else:
                    scene._gpu_apply_all = previous_apply
            for name, previous in (
                ('_furniture_reset_env_idx', previous_scope),
                ('_furniture_reset_scope_masks', previous_masks),
            ):
                if previous is _MISSING:
                    delattr(self, name)
                else:
                    setattr(self, name, previous)

    def _furniture_reset_mask(self, reference):
        """Cache one boolean vector per device for this reset, then reshape it."""
        if reference.ndim == 0 or reference.shape[0] != self.num_envs:
            raise ValueError('Scoped reset values must have num_envs as their first dimension')
        cache = self._furniture_reset_scope_masks
        mask = cache.get(reference.device)
        if mask is None:
            mask = torch.zeros(self.num_envs, dtype=torch.bool, device=reference.device)
            indices = torch.as_tensor(
                self._furniture_reset_env_idx, dtype=torch.long, device=reference.device,
            )
            mask[indices] = True
            cache[reference.device] = mask
        return mask.reshape((self.num_envs,) + (1,) * (reference.ndim - 1))

    def _reset_scoped_value(self, current, proposed):
        if getattr(self, '_furniture_reset_env_idx', None) is None:
            return proposed
        return torch.where(self._furniture_reset_mask(current), proposed, current)

    def _reset_scoped_predicate(self, predicate):
        if getattr(self, '_furniture_reset_env_idx', None) is None:
            return predicate
        return predicate & self._furniture_reset_mask(predicate)
