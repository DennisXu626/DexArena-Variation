"""Immediate rejected-reset comparisons. Use --cpu-sdk for a CPU storage fixture."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import pickle
import random
import traceback
from unittest.mock import patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/variation/evidence/open_cabinet_clearance"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(e):
    envs = [{}, {}]

    def visit(node, name):
        if isinstance(node, dict):
            for k, v in node.items():
                visit(v, name + "/" + k)
        else:
            for i, row in enumerate(envs):
                a = node[i].detach().cpu().contiguous().numpy()
                row[name] = [a.dtype.str, list(a.shape), a.tobytes().hex()]

    visit(e.get_state_dict(), "state")
    visit(e._elapsed_steps, "elapsed")
    visit(e.scene._reset_mask, "mask")

    def rng(r):
        return digest(pickle.dumps(r.get_state(), protocol=4))

    for i, row in enumerate(envs):
        row.update(main=rng(e._batched_main_rng[i]), episode=rng(e._batched_episode_rng[i]),
                   main_seed=int(e._main_seed[i]), episode_seed=int(e._episode_seed[i]),
                   workspace=e._workspace_next_seed.get(i))
    global_state = dict(legacy_main=rng(e._main_rng), legacy_episode=rng(e._episode_rng),
                        numpy=rng(np.random), python=digest(pickle.dumps(random.getstate())),
                        torch_cpu=digest(torch.get_rng_state().numpy().tobytes()))
    if e.device.type == "cuda":
        global_state["torch_cuda"] = digest(torch.cuda.get_rng_state(e.device).cpu().numpy().tobytes())
    return dict(envs=envs, streams=global_state)


def cuda_backend():
    import gymnasium as gym
    import tasks
    from tasks.cabinet_pouring import open_cabinet_workspace as sampler, start_clearance
    from check_runtime import TASK, physical
    from check_start_runtime import capture

    def make(enabled=True):
        return gym.make(TASK, **({"handle_workspace": True} if enabled else {}),
                        num_envs=2, sim_backend="physx_cuda",
                        obs_mode="state", reconfiguration_freq=0)

    def measure(e, i):
        actual = capture(e, i)
        pos = physical(e, i)
        assert abs(actual["door_angle"]) < 1e-4
        return [*pos["root_xy_m"], pos["yaw_deg"]], actual["arm_qpos"], actual["bounds_gap_mm"]

    return make, sampler, start_clearance, measure, {"backend": "physx_cuda"}


def run(output, backend, cpu):
    make, sampler, sc, measure, identity = backend
    draws = json.loads((EVIDENCE / "isolation_001/observations.json").read_bytes())["draws"]
    report = dict(backend=identity, checks=[], placements=[], status="incomplete")

    def save():
        output.write_text(json.dumps(report, indent=1, allow_nan=False) + "\n", encoding="utf8")

    def equal(label, actual, expected):
        same = actual == expected
        row = dict(check=label, equal=same)
        if not same:
            row.update(actual=actual, expected=expected)
        report["checks"].append(row)
        save()
        assert same, label

    def options(e, indices, names=None):
        opts = {"env_idx": torch.tensor(indices, device=e.device)}
        if names is not None:
            opts["handle_placement"] = {str(i): n for i, n in zip(indices, names)}
        return opts

    def fresh():
        # Align external streams at branch construction only.
        random.seed(17)
        np.random.seed(17)
        torch.manual_seed(17)
        return closing(make())

    def start(env):
        env.reset(seed=7)
        if cpu:
            e = env.unwrapped
            e._elapsed_steps[:] = torch.tensor([13, 29])
            e.latch[:] = True
            e.velocity[:] = torch.tensor([.25, -.125])

    def refuse(env, opts, name, seed=None):
        e = env.unwrapped
        before = snapshot(e)
        try:
            env.reset(seed=seed, options=opts)
        except ValueError as err:
            after = snapshot(e)  # first operation on the environment after rejection
            row = dict(check=name, rejection=str(err), before=before, after=after)
            report["checks"].append(row)
            save()
            equal(name + "/unchanged", after, before)
            return str(err)
        raise AssertionError("Expected rejection: " + name)

    def fixture(e, names):
        return patch.object(e, "_workspace_arm_draw", side_effect=[
            torch.tensor(draws[n]["arm_qpos"], device=e.device) for n in names])

    def accepted(env, i, name=None):
        e = env.unwrapped
        before = snapshot(e)
        real = sampler.resolve_workspace
        plan = {}

        def observe(*args, **kwargs):
            value = real(*args, **kwargs)
            plan.update(arm=kwargs["start_qpos"][0].tolist(), pose=value[0].tolist())
            return value

        opts = options(e, [i], None if name is None else [name])
        with patch.object(sampler, "resolve_workspace", observe):
            try:
                env.reset(options=opts)
            except ValueError as exc:
                after = snapshot(e)
                if name not in ("left", "right") or f"placement {name!r} rejected for env {i}" not in str(exc):
                    raise
                report["placements"].append(dict(env=i, request=name, refusal=str(exc)))
                equal("legitimate preset rejection", after, before)
                return None
        after = snapshot(e)
        equal(f"{name or 'ordinary'}/{i}/passive", after["envs"][1-i], before["envs"][1-i])
        pose, arm, gap = measure(e, i)
        ok, detail = sc.evaluate_start(plan["pose"][:2], plan["pose"][2], np.asarray(arm))
        record = dict(env=i, request=name or "ordinary", planned_pose=plan["pose"],
                      applied_xy_m_yaw_deg=pose, screened_arm=plan["arm"], applied_arm=arm,
                      start_clearance_mm=gap, screen=detail)
        report["placements"].append(record)
        save()
        if name:
            named = sampler.workspace(start_clearance=True)[1][name]
            assert np.allclose(plan["pose"], [named[0]/100, named[1]/100, 15], rtol=0, atol=1e-7)
        assert np.allclose(pose[:2], plan["pose"][:2], rtol=0, atol=1e-5)
        assert abs(pose[2]-plan["pose"][2]) < .001
        assert arm == plan["arm"] and ok and gap >= sc.MIN_START_CLEARANCE_MM, record
        return record

    try:
        for i in (0, 1):
            baseline = final = None
            for reject in (True, False):
                with fresh() as env:
                    e = env.unwrapped
                    start(env)
                    pre = snapshot(e)
                    if reject:
                        baseline = pre
                        with fixture(e, ["near"]):
                            message = refuse(env, options(e, [i], ["near"]), f"near/{i}")
                        assert f"'near' rejected for env {i}: start 59.31 mm" in message
                    else:
                        equal(f"matched baseline/{i}", pre, baseline)
                    with fixture(e, ["far"]):
                        accepted(env, 1-i, "far")
                    post = snapshot(e)
                    equal(f"near env unchanged after far/{i}", post["envs"][i], baseline["envs"][i])
                    if reject:
                        final = post
                    else:
                        equal(f"matched final/{i}", post, final)

        with fresh() as env:
            start(env)
            e = env.unwrapped
            with fixture(e, ["far", "near"]):
                msg = refuse(env, options(e, [0, 1], ["far", "near"]), "mixed, explicit seed", seed=99)
            assert "'near' rejected for env 1: start 59.31 mm" in msg
            # The request arrives in reverse order; physics setters address rows by mask.
            # Both recorded arm vectors are safe at far, and differ from one another.
            with fixture(e, ["near", "far"]):
                env.reset(options=options(e, [1, 0], ["far", "far"]))
            for i, draw in enumerate(("near", "far")):
                pose, arm, gap = measure(e, i)
                equal(f"reverse order applied arm/{i}", arm, draws[draw]["arm_qpos"])
                assert gap >= sc.MIN_START_CLEARANCE_MM
            if cpu:
                with patch.object(sc, "evaluate_start", return_value=(False, "forced exhaustion")) as probe:
                    msg = refuse(env, options(e, [1]), "bounded exhaustion")
                    assert probe.call_count == 48 and "48 candidates" in msg
            for name in ("left", "right"):
                for i in (0, 1):
                    accepted(env, i, name)
            before = snapshot(e)
            explicit = {"cabinet_xy_m": [.19, .17], "yaw_deg": 20}
            env.reset(options={**options(e, [1]), "position_layout": {"1": explicit}})
            equal("#32 bypasses workspace streams", e._workspace_next_seed[1], before["envs"][1]["workspace"])
            pose, _, _ = measure(e, 1) if not cpu else (e.pose[1].tolist(), None, None)
            assert np.allclose(pose, [.19, .17, 20], atol=.001, rtol=0)

        sessions = []
        for _ in range(2):
            with fresh() as env:
                start(env)
                session = []
                for i in (0, 1, 0, 1):
                    session.append(accepted(env, i))
                sessions.append(session)
        equal("seed-once ordinary sequence", sessions[0], sessions[1])
        assert len({tuple(r["planned_pose"]) for r in sessions[0]}) == 4
        with closing(make(False)) as native:
            with patch.object(sampler, "resolve_workspace", side_effect=AssertionError("unexpected planner")):
                native.reset(seed=7)
                e = native.unwrapped
                equal("native reset bypasses workspace streams", e._workspace_next_seed, {})
        report["status"] = "passed"
    except Exception:
        report["exception"] = traceback.format_exc()
        raise
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cpu-sdk", nargs=2, type=Path, metavar=("SAPIEN_ENV_PY", "BATCHED_RNG_PY"))
    args = parser.parse_args()
    if args.cpu_sdk:
        from atomic_cpu_fixture import build
        backend = build(*args.cpu_sdk)
    else:
        backend = cuda_backend()
    run(args.output, backend, bool(args.cpu_sdk))
