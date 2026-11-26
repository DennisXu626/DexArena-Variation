"""Measure the reset geometry for the registered, left-arm OpenCabinet task."""
import argparse
import copy
import hashlib
import json
import os
import sys
from contextlib import closing
from pathlib import Path

import gymnasium as gym
import numpy as np
import sapien
import torch
import tasks
from tasks.cabinet_pouring.cabinet_pouring_long import link_piece_bounds
from tasks.cabinet_pouring.open_cabinet_workspace import contains, workspace

TASK = "CabinetPouringOpenCabinet-Sharpa-v1"
SOURCE = Path(__file__).resolve().parents[3]
REFERENCE = SOURCE / "docs/variation/evidence/open_cabinet_reach/CPU_RESULTS.json"
TOL_MM = 1.0


def compare_handle(expected, measured):
    delta = (np.asarray(measured) - np.asarray(expected)) * 1000
    error = float(np.linalg.norm(delta))
    return dict(expected_xyz_m=list(expected), measured_xyz_m=list(measured),
                delta_xyz_mm=delta.tolist(), error_mm=error, passed=error <= TOL_MM)


def require_match(comparison):
    assert comparison["passed"], f"Closed-handle error exceeds {TOL_MM} mm: {comparison}"


def snapshot(state, i):
    if isinstance(state, dict):
        return {k: snapshot(v, i) for k, v in state.items()}
    a = state[i].detach().cpu().contiguous().numpy()
    return (a.dtype.str, a.shape, hashlib.sha256(a.tobytes()).hexdigest())


def physical(env, i):
    e = env.unwrapped
    art = e._cabinets[i]
    root = art.pose
    xy = root.p[0, :2].cpu().numpy()
    q = root.q[0].cpu().numpy()
    yaw = float(np.rad2deg(2 * np.arctan2(q[3], q[0])))
    door = art.links_map["link_0"]
    root_pose = sapien.Pose(p=root.p[0].cpu().numpy(), q=q)
    local = link_piece_bounds(door, relative_to=root_pose)
    handle_idx = int(np.argmin(local[:, 0, 0]))
    handle = link_piece_bounds(door)[handle_idx].mean(axis=0)
    return dict(root_xy_m=xy.tolist(), yaw_deg=yaw, handle_xyz_m=handle.tolist(),
                handle_piece=handle_idx, door_rad=float(art.qpos[0, 0]),
                door_latched=bool(e._stage_door[i]))


def map_prediction(pose, reference):
    # Apply the same rigid root transform used by the map to the 15-degree reference.
    anchor = reference["near"]
    angle = np.deg2rad(pose["yaw_deg"] - anchor["yaw_deg"])
    c, s = np.cos(angle), np.sin(angle)
    handle = np.array(anchor["closed_handle_xyz_m"])
    offset = handle[:2] - anchor["root_xy_m"]
    handle[:2] = np.array([[c, -s], [s, c]]) @ offset + pose["root_xy_m"]
    return handle.tolist()


def run(out):
    reference = json.loads(REFERENCE.read_bytes())["presets"]
    regions, presets = workspace()
    cpu = os.environ.get("OPEN_CABINET_PREFLIGHT") == "1"
    launch = dict(cwd=os.getcwd(), argv=sys.argv, python=sys.executable, task=TASK,
                  registered=gym.spec(TASK).id, tasks_module=tasks.__file__,
                  checker=str(Path(__file__).resolve()), reference=str(REFERENCE),
                  reference_sha256=hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
                  output=str(out), cpu_preflight=cpu)
    assert Path.cwd() == SOURCE and Path(tasks.__file__).resolve().parent == SOURCE / "tasks"
    if cpu:
        expected = reference["near"]["closed_handle_xyz_m"]
        match = compare_handle(expected, expected)
        displaced = compare_handle(expected, np.asarray(expected) + [0, .002, 0])
        require_match(match)
        try:
            require_match(displaced)
        except AssertionError:
            launch.update(match=match, displaced=displaced, displaced_rejected=True)
        else:
            raise AssertionError("2 mm displacement accepted")
        with out.open("x") as f:
            json.dump(launch, f, indent=2)
        return

    results = []
    def save():
        out.write_text(json.dumps(dict(launch=launch, checks=results), indent=2) + "\n")

    kwargs = dict(num_envs=2, sim_backend="physx_cuda", obs_mode="state", reconfiguration_freq=0)
    def observed(env, seed=None, options=None):
        env.reset(seed=seed, options=options)
        return [physical(env, i) for i in (0, 1)]

    def verify_pose(pose, xy, yaw):
        assert np.allclose(pose["root_xy_m"], xy, rtol=0, atol=1e-5)
        assert abs(pose["yaw_deg"] - yaw) < .001 and abs(pose["door_rad"]) < 1e-4
        assert not pose["door_latched"]

    def check_map(poses):
        comparisons = [compare_handle(map_prediction(p, reference), p["handle_xyz_m"]) for p in poses]
        return comparisons

    def record(test, **fields):
        row = dict(test=test, **fields)
        results.append(row)
        save()
        return row

    save()
    try:
        with closing(gym.make(TASK, **kwargs)) as native:
            poses = observed(native, 7)
            row = record("native control", poses=poses)
            for p in poses:
                assert np.all(np.abs(np.array(p["root_xy_m"]) - [.14, .12]) <= .01001)
                verify_pose(p, p["root_xy_m"], 15)
            row["passed"] = True
            poses = observed(native, options={"position_layout": {
                str(i): {"cabinet_xy_m": [.19, .17], "yaw_deg": 20} for i in (0, 1)}})
            row = record("PR32 control", poses=poses)
            for p in poses:
                verify_pose(p, [.19, .17], 20)
            row["passed"] = True
            save()

        with closing(gym.make(TASK, handle_workspace=True, **kwargs)) as env:
            e = env.unwrapped
            selected = lambda i: torch.tensor([i], device=e.device)
            for name in ("near", "far", "left", "right"):
                pose = observed(env, options={"env_idx": selected(0),
                                "handle_placement": {"0": name}})[0]
                comparison = compare_handle(reference[name]["closed_handle_xyz_m"], pose["handle_xyz_m"])
                row = record("preset", name=name, pose=pose, comparison=comparison)
                require_match(comparison)
                verify_pose(pose, np.array(presets[name]) / 100, 15)
                row["passed"] = True
                save()

            first, second = observed(env, 7), observed(env)
            replay, following = observed(env, 7), observed(env)
            comparisons = check_map(first + second)
            row = record("seeded and advancing ordinary resets", first=first, second=second,
                         replay=replay, following=following, comparisons=comparisons)
            assert first == replay and second == following and first != second
            for p, comp in zip(first + second, comparisons):
                angle = round(p["yaw_deg"])
                verify_pose(p, p["root_xy_m"], angle)
                assert contains(regions[angle], p["root_xy_m"])
                require_match(comp)
            row["passed"] = True
            save()
            for i in (0, 1):
                other = 1 - i
                before = snapshot(e.get_state_dict(), other)
                stream = copy.deepcopy(e._batched_episode_rng[other].get_state())
                pose = observed(env, options={"env_idx": selected(i)})[i]
                after = snapshot(e.get_state_dict(), other)
                current = e._batched_episode_rng[other].get_state()
                rng_equal = all(np.array_equal(a, b) for a, b in zip(stream, current))
                row = record("local reset", selected=i, passive=other, pose=pose, before=before,
                             after=after, unchanged=before == after, rng_equal=rng_equal)
                angle = round(pose["yaw_deg"])
                verify_pose(pose, pose["root_xy_m"], angle)
                assert contains(regions[angle], pose["root_xy_m"]) and before == after and rng_equal
                row["passed"] = True
                save()

            for yaw, rows in regions.items():
                y, x, _ = rows[0]
                xy = [x / 100, y / 100]
                def request(point):
                    return {"env_idx": selected(0), "handle_placement": {
                        "0": {"cabinet_xy_m": point, "yaw_deg": yaw}}}
                pose = observed(env, options=request(xy))[0]
                comp = check_map([pose])[0]
                row = record("boundary", yaw=yaw, xy=xy, pose=pose, comparison=comp)
                require_match(comp)
                verify_pose(pose, xy, yaw)
                row["passed"] = True
                outside = [(rows[:, 1].min() - 1) / 100, y / 100]
                try:
                    observed(env, options=request(outside))
                except ValueError as exc:
                    assert "Outside OpenCabinet handle workspace" in str(exc)
                    record("exterior", yaw=yaw, xy=outside, reason=str(exc), passed=True)
                else:
                    raise AssertionError(f"outside request accepted: {yaw} {outside}")
    except Exception as exc:
        record("first failure", error=repr(exc))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
