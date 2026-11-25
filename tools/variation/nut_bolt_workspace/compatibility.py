"""Compare the original PR samples and exercise appearance with workspace resets."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import gymnasium as gym
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parents[1])]
from check_nut_bolt_positions import TASKS, state
from check import isolated_state


def exterior_neighbors(env):
    """Pair each yaw/axis extremum with an exterior point 10 micrometres away."""
    workspace = env.unwrapped._nut_workspace
    rejects = []
    for yaw, cells in workspace.cells.items():
        for axis, size in enumerate(workspace.size):
            for sign in (-1, 1):
                idx = np.argmax(sign * cells[:, axis])
                point = cells[idx] + workspace.size / 2
                point[axis] += sign * size / 2
                edge = workspace.row(yaw, point)
                env.reset(options={"workspace_placement": {"0": edge}})
                before = isolated_state(env.unwrapped, 0)
                point[axis] += sign * 0.01
                outside = workspace.row(yaw, point)
                try:
                    env.reset(options={"workspace_placement": {"0": outside}})
                except ValueError as exc:
                    assert before == isolated_state(env.unwrapped, 0)
                    rejects.append(
                        dict(yaw=yaw, axis=axis, sign=sign, edge=edge, outside=outside, error=str(exc))
                    )
                else:
                    raise AssertionError(outside)
    return rejects


def appearance(task):
    task_id = f"NutBolt{task}-Sharpa-v1"
    common = dict(
        sim_backend="physx_cpu",
        obs_mode="state",
        render_mode=None,
        reconfiguration_freq=0,
        control_mode="pd_joint_pos",
        position_workspace=True,
    )
    rows = []
    edge_pairs = []
    for with_appearance in (False, True):
        kwargs = dict(common)
        if with_appearance:
            kwargs["nut_bolt_appearance"] = {"enabled": True, "scheme_id": "variant_1", "seed": 71}
        env = gym.make(task_id, **kwargs)
        try:
            env.reset(seed=637)
            first = env.unwrapped.get_position_workspace_records()
            options = {"workspace_placement": {"0": "far"}}
            if with_appearance:
                options["nut_bolt_appearance"] = {"scheme_id": "original"}
            env.reset(options=options)
            fixed = env.unwrapped.get_position_workspace_records()
            if with_appearance:
                fixed_scheme = env.unwrapped._nut_bolt_appearance.records[-1]
                assert fixed_scheme["scheme_id"] == "original"
            env.reset()
            rows.append([first, fixed, env.unwrapped.get_position_workspace_records()])
            if with_appearance:
                return_scheme = env.unwrapped._nut_bolt_appearance.records[-1]
                assert return_scheme["scheme_id"] == "variant_1"
                prior = state(env.unwrapped, 0)
                try:
                    env.reset(
                        options={
                            "nut_bolt_appearance": {"scheme_id": "bad-id"},
                            "workspace_placement": {"0": "near"},
                        }
                    )
                except ValueError:
                    assert state(env.unwrapped, 0) == prior
                    assert env.unwrapped.get_position_workspace_records() == rows[-1][-1]
                else:
                    raise AssertionError("invalid sibling appearance override accepted")
            else:
                edge_pairs = exterior_neighbors(env)
        finally:
            env.close()
    assert rows[0] == rows[1]
    return dict(
        edge_pairs=edge_pairs,
        layout_sequences_identical=True,
        seed=637,
        fixed=fixed_scheme,
        next=return_scheme,
        failed_appearance_preserved_layout=True,
    )


def previous(path):
    original = ROOT / "docs/variation/evidence/nut_bolt_position_boundaries/runtime_001/raw/CPU.json"
    old = json.loads(original.read_text())
    new = json.loads(path.read_text())
    results = {}
    fields = ("readback", "support", "ik", "rejected_reason", "rejection_state_diffs")
    for task, items in new["tasks"].items():
        old_rows = old["tasks"][task]["rows"]
        new_rows = items["rows"]
        assert len(new_rows) == len(old_rows)
        for a, b in zip(old_rows, new_rows):
            assert a["label"] == b["label"] and a["options"] == b["options"]
            assert all(a.get(k) == b.get(k) for k in fields)
        results[task] = {
            "rows": len(new_rows),
            "legal": sum(r["kind"] == "initialization" for r in new_rows),
            "rejected": sum(r["kind"] == "rejection" for r in new_rows),
            "exact_fields": fields,
        }
    return dict(
        checked_commit=new["settings"]["commit"],
        original_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        rerun_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        results=results,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("legacy_rerun", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = previous(args.legacy_rerun)
    report["appearance"] = {t: appearance(t) for t in TASKS}
    report["check_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    report["checker_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.write_text(json.dumps(report, indent=2) + "\n")
