"""Verify both matched branches and derive the table displacement from saved float32 bytes."""
from pathlib import Path
import argparse
import json
import struct


def row(observation, env):
    packed = observation["state"]["actors/table-workspace"][env]
    assert packed["dtype"] == "<f4" and packed["shape"] == [13]
    return struct.unpack("<13f", bytes.fromhex(packed["hex"]))


def different_groups(before, after, env):
    assert before["state"].keys() == after["state"].keys()
    return [key for key, value in before["state"].items()
            if value[env] != after["state"][key][env]]


def verify(data):
    assert data["status"] == "complete"
    a, b = data["runs"]["near_then_far"], data["runs"]["far_only"]
    assert a["initial"] == b["initial"]
    assert a["far/arm_draws"] == b["far/arm_draws"] == [data["draws"]["far"]["arm_qpos"]]
    assert a["near/arm_draws"] == [data["draws"]["near"]["arm_qpos"]]
    assert "rejected for env 0" in a["near/result"] and a["far/result"] == b["far/result"] == "accepted"
    baseline, rejected, next_reset = a["near/before"], a["near/after"], a["far/after"]
    assert rejected == a["far/before"] and next_reset == b["far/after"]
    table = ["actors/table-workspace"]
    assert different_groups(baseline, rejected, 0) == table
    assert different_groups(baseline, rejected, 1) == []
    assert different_groups(rejected, next_reset, 0) == table
    assert different_groups(baseline, next_reset, 0) == []
    assert different_groups(b["far/before"], b["far/after"], 0) == []
    assert baseline["episode_rng"] == rejected["episode_rng"] == next_reset["episode_rng"]
    assert baseline["elapsed"] == rejected["elapsed"] == next_reset["elapsed"]
    assert [baseline["reset_mask"], rejected["reset_mask"], next_reset["reset_mask"]] == [
        [True, True], [True, False], [True, True]]
    near_trace = a["near/trace"]
    far_trace = a["far/trace"]
    assert row(near_trace["_clear_sim_state/return"], 0) == row(baseline, 0)
    assert row(near_trace["_set_work_table_pose/return"], 0) == row(rejected, 0)
    assert row(far_trace["_clear_sim_state/return"], 0) == row(baseline, 0)
    before_hex = bytes.fromhex(baseline["state"][table[0]][0]["hex"])
    after_hex = bytes.fromhex(rejected["state"][table[0]][0]["hex"])
    assert before_hex[:4] != after_hex[:4] and before_hex[4:] == after_hex[4:]
    x0, x1, x2 = [row(item, 0)[0] for item in (baseline, rejected, next_reset)]
    return dict(near_result=a["near/result"], far_arm_draw_matched=True,
                table_x_m=[x0,x1,x2], displacement_m=abs(x1-x0),
                displacement_mm=abs(x1-x0)*1000, control_passive_changed_fields=[],
                both_final_observations_identical=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path)
    print(json.dumps(verify(json.loads(parser.parse_args().observations.read_bytes())), indent=2))
