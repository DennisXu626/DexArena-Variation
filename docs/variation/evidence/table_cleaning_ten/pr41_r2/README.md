# PR41 R2 integration

2026-11-26. Expansion head: `ad6a19d79c9e347808921ec7fcb7cfbdc432b231`.
Integrated target main: `6e3467b` (includes accepted PR12 `3082024`).

The four reported conflicts were resolved in catalog.json, appearance.py,
table_cleaning_long.py and table_cleaning_contract.py. Comparing both sides
showed that the expansion already carries the accepted PR12 runtime. Its
resolved versions preserve that baseline and add IDs 3–10, their texture
mapping and independent contract, and the per-step hold guard. Other main
changes are retained by the merge.

## Effective changes against main

- original and IDs 1/2 retain their fixed recipes. IDs 3–10 map the original
  sugar texture's mean RGB brightness, normalized by its 95th percentile,
  onto the specified target color; alpha and auxiliary texture slots remain.
- `_hold_step` makes repeated evaluation in one control step idempotent;
  reset/state restore invalidate selected rows and partial reset preserves
  neighbours. The 8/10-step thresholds remain unchanged.
- The pixel adapter retains compatibility class names but removes the old
  single-environment trampoline and builder shim, delegating to native tasks.
- Accepted reset validation, held-row controller targets, original restoration
  and saved-state motion-cache invalidation remain in place.

See [effective runtime diff](effective-runtime.diff). The full effective diff
is available with `git diff 6e3467b HEAD` after the integration commit.

## Evidence mapping

[Snapshot audit](snapshot_audit.json) records hashes and both byte and
LF-normalized comparisons. Production runtime, adapter and checker content
is unchanged from expansion head (apart from Windows checkout line endings).
The main tested snapshot matches the final files except the critical-reset
checker; that checker matches the final recheck snapshot. All three files in
the final recheck snapshot match after LF normalization. The historical
checker corrections and failed jobs remain documented in the parent README.
No historical evidence or source snapshot was overwritten.

## Checks performed on the integrated tree

- `python -B tools/variation/check_static.py`: passed (87 Python sources).
- `python -B tools/variation/check_appearance_archive.py`: passed.
- `check_table_cleaning_reset_cpu.py`: 11 tests passed, including original
  restoration and rejection of swapped ID/material contracts.
- `check_table_cleaning_single_env_cpu.py`: 64 cases, maximum delta 0.
- `check_table_cleaning_hold_cpu.py`: passed repeated-read/reset checks.
- `check_table_cleaning_state_restore_cpu.py`: 16 cases passed, both rows,
  appearance on/off, direct/reset restore and task-state present/absent.
  The saved actors are displaced by 1 cm; first/repeated reads reject stale
  containment, while neighbour and subsequent-step counts are preserved.
- `check_table_cleaning_isolation_cpu.py`: 4 tests passed, including partial
  reset, returned observations, controller targets and exception cleanup.
- `git diff --check` and staged whitespace check: required before commit.

State restore and isolation use AST-loaded methods from the published
`mani_skill==3.0.0b22` wheel, CPU Torch 2.6.0 and NumPy 2.2.6; poses and contacts
are test doubles. Commands require the repository plus extracted SDK package
for state restore, or `--mani-skill-wheel` for isolation. Results are saved in
[state restore](state-restore.json) and [isolation](isolation.json).

No new GPU run was performed. Prior GPU results apply to their archived
snapshots and retain their documented scope; this integration is ready for
independent review of the new IDs and affected runtime paths.
