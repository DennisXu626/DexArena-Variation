"""CPU regression: save/restore must preserve per-control-step hold processing."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import torch

repo = Path(__file__).resolve().parents[2]
long_file = repo / "tasks/table_cleaning/table_cleaning_long.py"
pick_file = repo / "tasks/table_cleaning/table_cleaning_pick_debris.py"

class PhysicsFixture:
    def get_state_dict(self):
        return {}
    def set_state_dict(self, state, env_idx=None):
        pass

def methods(file, original, name, parent, keep, extra):
    node = next(n for n in ast.parse(file.read_text(encoding="utf-8-sig")).body
                if isinstance(n, ast.ClassDef) and n.name == original)
    node.name = name
    node.bases = [ast.Name(id="Parent", ctx=ast.Load())]
    node.decorator_list = []
    node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in keep]
    assert {n.name for n in node.body} == set(keep)
    scope = {"torch": torch, "Parent": parent, **extra}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(file), "exec"), scope)
    return scope[name]

common = methods(long_file, "TableCleanBase", "ScopedTable", PhysicsFixture,
                 ["get_state_dict", "set_state_dict", "_latch", "_update_pick", "_dump_success"],
                 {"HOLD_STEPS": 8, "DUMP_HOLD_STEPS": 10, "ROBOT_ROOT": None})
pick = methods(pick_file, "TableCleaningPickDebrisEnv", "ScopedPick", common, ["evaluate"], {})

def fixture(selected, mode):
    env = pick()
    env.num_envs, env.device = 2, "cpu"
    env.FLAG_NAMES = ("f_picked", "f_grasp_pan", "f_poured", "f_stow_pan")
    env.TASK_STATE_DIM = 7
    env.agent = SimpleNamespace(robot=SimpleNamespace(set_root_pose=lambda pose: None))
    env.stage = torch.zeros(2, dtype=torch.long)
    env.hold = torch.zeros(2, dtype=torch.int32)
    for field in (*env.FLAG_NAMES, "success_latched"):
        setattr(env, field, torch.zeros(2, dtype=torch.bool))
    counts = torch.zeros(2, dtype=torch.long)
    counts[selected] = 3
    env._pick_target, env.debris = 3, (1, 2, 3)
    env._debris_in_pan = lambda resting=True: counts
    env._debris_in_bin = lambda: torch.zeros_like(counts)
    env._any_debris_grasped = lambda: torch.zeros(2, dtype=torch.bool)
    env._debris_on_bin_floor = lambda: counts
    env._elapsed_steps = torch.zeros(2, dtype=torch.long)
    def read():
        if mode == "pick":
            env.evaluate()
        else:
            env._dump_success(torch.ones(2, dtype=torch.bool))
        return (env.hold.tolist(), env.success_latched.tolist())
    return env, read


results = []
for mode, threshold in [("pick", 8), ("dump", 10)]:
    for selected in (0, 1):
        for counted in (False, True):
            for wrapped in (False, True):
                for clock_offset in (0, 100):
                    control, control_read = fixture(selected, mode)
                    restored, restored_read = fixture(selected, mode)
                    for env, read in [(control, control_read), (restored, restored_read)]:
                        for _ in range(threshold - 1):
                            env._elapsed_steps += 1
                            read()
                        if not counted:
                            env._elapsed_steps += 1
                    idx = torch.tensor([selected])
                    state = {k: v[idx].clone() for k, v in restored.get_state_dict().items()}
                    saved_reading = (restored.hold.tolist(), restored.success_latched.tolist())
                    if wrapped:
                        state = {k: {"value": v} for k, v in state.items()}
                    neighbour = (restored.hold[1-selected].item(), restored._hold_step[1-selected].item())
                    # Loading into a different episode clock must preserve processing status.
                    restored._elapsed_steps[selected] += clock_offset
                    restored.set_state_dict(state, idx)
                    assert (restored.hold[1-selected].item(), restored._hold_step[1-selected].item()) == neighbour
                    loaded_reading = (restored.hold.tolist(), restored.success_latched.tolist())
                    readings = []
                    for _ in range(3):
                        actual, expected = restored_read(), control_read()
                        assert actual == expected
                        readings.append(dict(restored=actual, continuous=expected))
                    if counted:
                        assert restored.hold[selected] == threshold - 1
                        assert not restored.success_latched[selected]
                    else:
                        assert restored.hold[selected] == threshold
                    restored._elapsed_steps += 1
                    control._elapsed_steps += 1
                    next_actual, next_expected = restored_read(), control_read()
                    assert next_actual == next_expected
                    assert restored.success_latched[selected]
                    results.append(dict(mode=mode, selected=selected, counted=counted, wrapped=wrapped,
                                        clock_offset=clock_offset, saved=saved_reading, loaded=loaded_reading,
                                        same_frame_reads=readings, next_step=dict(restored=next_actual, continuous=next_expected)))
        for task_present in (False, True):
            env, read = fixture(selected, mode)
            env._elapsed_steps += 1
            read()
            state = {k: v[selected:selected+1].clone() for k, v in env.get_state_dict().items()}
            state.pop("table_clean_hold_counted")
            if not task_present:
                state.pop("table_clean_task_state")
            env.set_state_dict(state, torch.tensor([selected]))
            assert env._hold_step[selected] == -1
            read()
            assert env.hold[selected] == 2
            read()
            assert env.hold[selected] == 2
            results.append(dict(mode=mode, selected=selected, legacy_task=task_present))

# Save before any evaluation, then restore the full batch with no env_idx.
env, read = fixture(0, "pick")
state = env.get_state_dict()
assert not state["table_clean_hold_counted"].any()
env.set_state_dict(state)
read()
assert env.hold.tolist() == [1, 0]
print(json.dumps(dict(status="passed", cases=len(results)+1, results=results), indent=2))
