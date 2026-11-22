"""Indexed GPU publication for native lock flips and nut representation swaps."""
import torch


def require_native_gpu_lock():
    import sapien
    for name in ('indexed_gpu_apply_patch_version', 'native_gpu_lock_sync_patch_version'):
        capability = getattr(sapien.physx, name, None)
        if not callable(capability) or capability() != 1:
            raise RuntimeError(f'Nut & Bolt GPU holds require native {name}() == 1')


def hold_pose(base, actor, env_index, park_z):
    """Use authoritative CUDA poses, never the raw component's CPU shadow."""
    if actor is base.bolt:
        return base._bolt_lock_pose[env_index:env_index + 1].clone()
    pose = actor.pose.raw_pose[env_index:env_index + 1].clone()
    pose[:, 2] = park_z
    pose[:, 3:] = 0
    pose[:, 3] = 1
    return pose


def _publish(base, rigid_indices=(), articulation_indices=()):
    import sapien
    rigid = torch.tensor(sorted(set(rigid_indices)), dtype=torch.int32, device=base.device).contiguous()
    articulations = torch.tensor(sorted(set(articulation_indices)), dtype=torch.int32, device=base.device).contiguous()
    if rigid.is_cuda:
        torch.cuda.synchronize(base.device)
    try:
        if rigid.numel():
            base.scene.px.gpu_apply_rigid_dynamic_data(sapien.CudaArray(rigid))
        if articulations.numel():
            selected = sapien.CudaArray(articulations)
            for field in ('root_pose', 'root_velocity', 'qpos', 'qvel'):
                getattr(base.scene.px, 'gpu_apply_articulation_' + field)(selected)
    finally:
        # CudaArray borrows these tensors; retain them until PhysX has consumed them.
        if rigid.is_cuda:
            torch.cuda.synchronize(base.device)


def refresh_gpu_hold_state(base, write_pose=True):
    import sapien.physx as physx
    require_native_gpu_lock()
    publish = []
    reset_scope = getattr(base, '_furniture_reset_env_idx', None)
    selected = None if reset_scope is None else {int(index) for index in reset_scope}
    for actor, mask in base._hold_bodies():
        if actor is None:
            continue
        for env_id, raw in zip(actor._scene_idxs.tolist(), actor._objs):
            if selected is not None and env_id not in selected:
                continue
            component = raw.find_component_by_type(physx.PhysxRigidDynamicComponent)
            if component is None:
                continue
            want = bool(mask[env_id])
            held = all(bool(value) for value in component.get_locked_motion_axes())
            if held == want:
                continue
            if want and write_pose:
                pose = base._hold_pose(actor, env_id)
                state = torch.cat([pose, torch.zeros((1, 6), dtype=pose.dtype, device=base.device)], dim=-1)
                actor.set_state(state, env_idx=torch.tensor([env_id], dtype=torch.long, device=base.device))
                publish.append(component.gpu_index)
                if actor is base.bolt and base.has_platform:
                    # The task already placed this collision-only support at the
                    # latch pose. Publish its existing buffer for this env only.
                    publish.extend(body.gpu_index for index, body in zip(
                        base.platform._scene_idxs.tolist(), base.platform._bodies) if index == env_id)
            component.set_locked_motion_axes([want] * 6)
    if publish:
        _publish(base, rigid_indices=publish)
    # Do not fetch here: episode initialization may still have unpublished
    # robot/articulation buffers. The normal task/reset path owns that fetch.


def sync_nut_swap_gpu(base, env_idx):
    require_native_gpu_lock()
    selected = {int(index) for index in env_idx}
    rigid = [body.gpu_index for index, body in zip(base.nut._scene_idxs.tolist(), base.nut._bodies)
             if index in selected]
    articulations = [raw.gpu_index for index, raw in zip(
        base.nut_revolute._scene_idxs.tolist(), base.nut_revolute._objs) if index in selected]
    _publish(base, rigid, articulations)
    base.scene.px.gpu_update_articulation_kinematics()
    base.scene._gpu_fetch_all()
