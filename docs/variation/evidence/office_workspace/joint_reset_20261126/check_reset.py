"""Check Office appearance and position options together on the merged tree."""
import argparse
import copy
import json
from pathlib import Path

import gymnasium as gym
import sapien
import torch

import tasks


def check(task, device):
    kwargs = dict(
        position_workspace=True, num_envs=2, sim_backend="physx_cuda",
        obs_mode="state", control_mode="pd_joint_pos", reconfiguration_freq=0,
        sim_config={"gpu_memory_config": {"max_rigid_contact_count": 2**17,
                    "max_rigid_patch_count": 2**16, "found_lost_pairs_capacity": 2**20}},
    )
    channels = ["mouse_appearance"] if device == "mouse" else ["office_devices_appearance", "office_keyboard_appearance"]
    if device == "keyboard":
        kwargs["model_id"] = "13106"
    for name in channels:
        kwargs[name] = {"enabled": True, "scheme_id": "original"}
    env = gym.make(f"OfficeDesk{task}-Sharpa-v1", **kwargs)
    try:
        base = env.unwrapped
        ws = base.position_workspace
        looks = [getattr(base, "_" + name) for name in channels]
        env.reset(seed=717)

        def snapshot():
            return (base.get_state().clone(),
                    copy.deepcopy((ws.seeds, ws.counts, ws.episodes)),
                    copy.deepcopy([(obj.schemes, obj.episodes) for obj in looks]))

        def verify_rejection(opts):
            before = snapshot()
            try:
                env.reset(options={"env_idx": [1], **opts})
            except ValueError:
                pass
            else:
                raise AssertionError(f"accepted invalid options {opts}")
            after = snapshot()
            assert torch.equal(before[0], after[0]) and before[1:] == after[1:]

        before = snapshot()
        # Give the shell and keycaps different schemes to detect channel swaps.
        schemes = [[name for name in obj.catalog["schemes"] if name != "original"][i]
                   for i, obj in enumerate(looks)]
        assert all(s != "original" for s in schemes)
        change = {name: {"scheme_id": s} for name, s in zip(channels, schemes)}
        env.reset(options={"env_idx": [1], "workspace_placement": {"1": "far"}, **change})
        assert torch.equal(before[0][0], base.get_state()[0])
        assert ws.episodes[0] == before[1][2][0] and ws.episodes[1]["mode"] == "fixed"
        assert [obj.schemes for obj in looks] == [["original", s] for s in schemes]
        root = getattr(base, device).pose.p
        margin = float((root[1, :2] - root.new_tensor(ws.fixed("far")[0])).abs().max())
        assert margin < 1e-5, margin
        far = snapshot()
        env.reset(options={"env_idx": [0], "position_layout": {"0": {}}, **change})
        assert torch.equal(far[0][1], base.get_state()[1])
        assert ws.episodes[0] is None and ws.episodes[1] == far[1][2][1]
        assert [obj.schemes for obj in looks] == [[s, s] for s in schemes]
        root = getattr(base, device).pose.p
        assert torch.allclose(root[0, :2], root.new_tensor(base._position_center[:2]), atol=1e-5, rtol=0)
        bad_layout = {"1": {device + "_xy_m": [99, 99]}}
        verify_rejection({"position_layout": bad_layout, **change})
        for chan in channels:
            verify_rejection({"workspace_placement": {"1": "far"}, chan: {"scheme_id": "unknown"}})
            verify_rejection({"reset_to_env_states": {}, chan: {"scheme_id": "original"}})
        verify_rejection({"reset_to_env_states": {}, "position_layout": {"1": {}}})
        verify_rejection({"workspace_placement": {"1": "far"}, "position_layout": {"1": {}}})
        return {"task": task, "schemes": schemes, "far_xy_error_m": margin,
                "peer_state_equal_both_directions": True, "rejected_cases": 3 + 2 * len(channels)}
    finally:
        env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--physx-gpu-dir")
    parser.add_argument("--task", required=True, choices=("TypeKeys", "OpenLaptop", "ClickMouse"))
    args = parser.parse_args()
    if not sapien.physx.is_gpu_enabled():
        sapien.physx._enable_gpu()
    device = {"TypeKeys": "keyboard", "OpenLaptop": "laptop", "ClickMouse": "mouse"}[args.task]
    result = check(args.task, device)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
