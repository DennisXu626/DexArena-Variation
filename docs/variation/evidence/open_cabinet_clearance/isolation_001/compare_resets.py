"""Read-only state observers for two matched reset sequences on PR 47."""
import argparse
from contextlib import closing, ExitStack
import hashlib
import json
import os
from pathlib import Path
import traceback
from unittest.mock import patch

import gymnasium as gym
import numpy as np
import torch
import tasks
from tasks.cabinet_pouring.open_cabinet_workspace import workspace
from tasks.cabinet_pouring.start_clearance import evaluate_start, MIN_START_CLEARANCE_MM


TASK = "CabinetPouringOpenCabinet-Sharpa-v1"


def pack(value):
    array = value.detach().cpu().contiguous().numpy()
    return {"shape": list(array.shape), "dtype": array.dtype.str, "hex": array.tobytes().hex()}


def fields(tree, prefix=""):
    out = {}
    for key, value in tree.items():
        path = prefix + key
        if isinstance(value, dict):
            out.update(fields(value, path + "/"))
        else:
            assert value.shape[0] == 2, (path, value.shape)
            out[path] = [pack(value[i]) for i in (0, 1)]
    return out


def rng_tag(generator):
    algorithm, state, pos, gauss, cached = generator.get_state()
    return [algorithm, hashlib.sha256(state.tobytes()).hexdigest(), pos, gauss, cached]


def observe(e):
    return dict(state=fields(e.get_state_dict()),
                reset_mask=e.scene._reset_mask.cpu().tolist(),
                elapsed=e._elapsed_steps.cpu().tolist(),
                episode_rng=[rng_tag(e._batched_episode_rng[i]) for i in (0, 1)])


def changed(before, after, index):
    assert before["state"].keys() == after["state"].keys()
    return [k for k in before["state"] if before["state"][k][index] != after["state"][k][index]]


def seeded_scope(e):
    return torch.random.fork_rng(devices=[torch.cuda.current_device()])


def arm_indices(e):
    names = [joint.name for joint in e.agent.robot.get_active_joints()]
    return [names.index(n) for n in e.agent.arm_joint_names]


def choose_draw(e, name):
    # Select an ordinary native qpos draw in isolation. Do not call reset, mutate
    # simulation state, or consume the live torch stream while selecting it.
    xy = np.asarray(workspace(start_clearance=True)[1][name], dtype=np.float32) / 100
    with seeded_scope(e):
        for seed in range(256):
            torch.manual_seed(seed)
            q = e._initial_robot_qpos(1)[0, arm_indices(e)].detach().cpu().numpy()
            ok, detail = evaluate_start(xy, 15, q)
            if (name == "far" and ok) or (name == "near" and not ok
                    and detail.startswith("start ") and float(detail.split()[1]) < MIN_START_CLEARANCE_MM):
                return dict(seed=seed, arm_qpos=q.tolist(), prediction=detail)
    raise RuntimeError("No suitable native draw in bounded CPU/GPU seed preview: " + name)


def run(out):
    receipt = {"runs": {}, "draws": {}, "status": "started"}

    def save():
        data = json.dumps(receipt, separators=(",", ":"), allow_nan=False)
        assert len(data) < 2 << 20, "Evidence limit exceeded"
        out.write_text(data, encoding="utf-8")

    try:
        for name, cases in (("near_then_far", [(0, "near"), (1, "far")]),
                            ("far_only", [(1, "far")])):
            steps = receipt["runs"][name] = {}
            with closing(gym.make(TASK, handle_workspace=True, num_envs=2,
                                  sim_backend="physx_cuda", obs_mode="state", reconfiguration_freq=0)) as env:
                e = env.unwrapped
                env.reset(seed=7)
                steps["initial"] = observe(e)
                if name == "near_then_far":
                    receipt["draws"] = {p: choose_draw(e, p) for p in ("near", "far")}
                save()
                for i, preset in cases:
                    pre = steps[preset + "/before"] = observe(e)
                    draw = receipt["draws"][preset]
                    timings = steps[preset + "/trace"] = {}
                    qlog = steps[preset + "/arm_draws"] = []

                    def watch(method_name):
                        original = getattr(e, method_name)
                        def wrapped(*args, **kwargs):
                            try:
                                result = original(*args, **kwargs)
                            except Exception:
                                timings[method_name + "/exception"] = observe(e)
                                raise
                            timings[method_name + "/return"] = observe(e)
                            return result
                        return wrapped

                    original_draw = e._initial_robot_qpos
                    def log_draw(batch):
                        with seeded_scope(e):
                            torch.manual_seed(draw["seed"])
                            q = original_draw(batch)
                        qlog.append(q[0, arm_indices(e)].detach().cpu().tolist())
                        return q

                    def get_info_hook(original):
                        def wrapped(*args, **kwargs):
                            timings["get_info/entry"] = observe(e)
                            info = original(*args, **kwargs)
                            timings["get_info/return"] = observe(e)
                            return info
                        return wrapped

                    with ExitStack() as hooks, seeded_scope(e):
                        for method in ("_clear_sim_state", "_set_work_table_pose", "_initialize_episode"):
                            hooks.enter_context(patch.object(e, method, watch(method)))
                        hooks.enter_context(patch.object(e, "get_info", get_info_hook(e.get_info)))
                        hooks.enter_context(patch.object(e, "_initial_robot_qpos", log_draw))
                        torch.manual_seed(draw["seed"])
                        opts = {"env_idx": torch.tensor([i], device=e.device),
                                "handle_placement": {str(i): preset}}
                        try:
                            env.reset(options=opts)
                            steps[preset + "/result"] = "accepted"
                        except ValueError as exc:
                            if preset != "near" or "placement 'near' rejected for env 0" not in str(exc):
                                raise
                            steps[preset + "/result"] = str(exc)
                    post = steps[preset + "/after"] = observe(e)
                    steps[preset + "/changed"] = [changed(pre, post, idx) for idx in (0, 1)]
                    save()
                    assert qlog == [draw["arm_qpos"]], (preset, "different qpos from preview")
                    assert (steps[preset + "/result"] == "accepted") == (preset == "far")
        a, b = receipt["runs"].values()
        receipt["baseline_field_diffs"] = [changed(a["initial"], b["initial"], i) for i in (0, 1)]
        receipt["matched_initial_state"] = a["initial"] == b["initial"]
        receipt["matched_far_draw"] = a["far/arm_draws"] == b["far/arm_draws"]
        assert receipt["matched_initial_state"] and receipt["matched_far_draw"]
        receipt["status"] = "complete"
    except Exception:
        receipt["status"] = "incomplete"
        receipt["exception"] = traceback.format_exc()
        raise
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    run(parser.parse_args().output)
