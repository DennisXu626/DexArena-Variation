"""Real AST-loaded hold logic; repeated reads must not advance simulation time."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import torch

source = Path("tasks/table_cleaning/table_cleaning_long.py")
node = next(n for c in ast.parse(source.read_text()).body if isinstance(c, ast.ClassDef)
            and c.name == "TableCleanBase" for n in c.body
            if isinstance(n, ast.FunctionDef) and n.name == "_latch")
scope = {"torch": torch, "HOLD_STEPS": 8}
exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), "exec"), scope)
e = SimpleNamespace(hold=torch.tensor([7, 9]), _elapsed_steps=torch.tensor([10, 10]))
latch = scope["_latch"]
assert latch(e, torch.tensor([True, True]), 10).tolist() == [False, True]
assert e.hold.tolist() == [8, 10]
for _ in range(3):
    latch(e, torch.tensor([True, True]), 10)
    assert e.hold.tolist() == [8, 10]
e._elapsed_steps += 1
latch(e, torch.tensor([True, False]), 10)
assert e.hold.tolist() == [9, 0]
e._hold_step[0] = -1  # selected reset/state restore invalidation
e.hold[0] = 0
latch(e, torch.tensor([True, True]), 10)
assert e.hold.tolist() == [1, 0], e.hold
print(json.dumps({"status": "passed", "repeated_reads": 3, "final_hold": e.hold.tolist()}))
