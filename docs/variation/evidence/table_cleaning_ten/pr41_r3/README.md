# PR41 R3: preserve hold processing status across state restore

2026-11-27. Reviewed head: `fd6340818c195adaedc970acc4ac5668cc9bda2e`.

The saved task tensor contained the hold count but omitted whether the current
control step had already contributed. Restoring it invalidated `_hold_step`,
so reading the same physical frame counted it twice and could latch success.

New snapshots include a per-row boolean `table_clean_hold_counted` of shape
N x 1. Restoration maps this relative processing status to the receiving
episode's current clock. Already-counted frames stay counted; frames saved
before evaluation still contribute once. Raw tensors and flattened `value`
wrappers are supported. The original seven-field task tensor is unchanged.
Old task snapshots cannot identify processing status and retain the legacy
first-read behavior; physics-only inputs also retain their invalidation path.
No count is subtracted. Only selected rows are restored. Motion-cache
invalidation remains independent and the 8/10-step thresholds are unchanged.

## Validation

- [Original reviewer probe before](reviewer-before.json): both cases reproduce
  early success on fd63408; [after](reviewer-after.json): both equivalent.
- [Hold restore](hold-restore.txt): 25 cases, actual PickDebris evaluation and
  dump success helper; both row directions, counted/uncounted frames,
  wrapped/raw states, different receiving clocks, legacy/physics-only states,
  full-batch restore before first evaluation, repeated reads and next step.
  Continuous execution and restored execution agree; neighbours are preserved.
- [State restore](state-restore.json): 48 cases, including direct and public
  reset-to-state, appearance on/off, task state present/absent, and absent,
  false or true processing markers at the existing 1 cm displacement boundary.
- [Isolation](isolation.json): 4 tests passed. Reset 11 tests, single-environment
  64 cases, prior hold checks, static and archive checks all passed. See
  [check summary](checks.json) and adjacent text outputs.

CPU tests load real task methods through AST and use physics/pose doubles.
State restore/isolation use published ManiSkill 3.0.0b22 sources, Torch 2.6.0
CPU and NumPy 2.2.6. They are not simulation runs. No new GPU job was run.
The old 138555/138600 evidence retains its archived identity and scope;
this changed saved-state path is validated by the new CPU outputs.

Modified production file: tasks/table_cleaning/table_cleaning_long.py.
Added check: tools/variation/check_table_cleaning_hold_restore_cpu.py.
Expanded check: tools/variation/check_table_cleaning_state_restore_cpu.py.
