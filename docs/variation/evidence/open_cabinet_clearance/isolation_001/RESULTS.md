# OpenCabinet rejected-reset isolation

A rejected `near` reset left env0 halfway through initialization. The next successful `far` reset in env1 synchronized a pending table-pose write in env0. The only differing component in env0's saved state was the table's X coordinate. The cabinet, robot articulation and task state compared byte-for-byte equal throughout those before/after comparisons.

| Two-environment sequence | Env0 table X before (m) | After rejected near (m) | After accepted far (m) |
| --- | ---: | ---: | ---: |
| Reject near in env0, then accept far in env1 | 0.18000006675720215 | 0.18000000715255737 | 0.18000006675720215 |
| Accept far in env1 directly | 0.18000006675720215 | — | 0.18000006675720215 |

The difference was **0.000059604645 mm** on a saved float32 coordinate. Both branches ended with identical state tensors, reset masks, elapsed-step counters and episode RNG records for both environments. The original VR hand penetration was a separate millimetre-scale geometry finding from job 142378.

## What the trace established

1. Both branches started from seed 7 in fresh pairs of environments. We held the seven sampled arm joint coordinates identical for both `far` requests. Under the diagnostic's controlled native noise draw, `near` predicted 59.31 mm of start clearance and triggered the 60 mm guard. The matched `far` draw predicted 143.43 mm and was accepted. These measurements used new noise draws. No action, glove command or physics step was issued by the diagnostic.
2. The first observed change in env0's table X was at the return of `_set_work_table_pose()` during the rejected reset. At the exception, the temporary reset mask still selected only env0. The simulator had skipped the normal end-of-reset mask restoration and GPU synchronization. Env1's saved state and both episode RNG records compared equal across the rejection.
3. During the following env1 reset, env0's table X was already back to its initial value by the return of `_clear_sim_state()`, which applies and fetches GPU state. This occurred before the task initialized env1's cabinet. Running the same `far` reset directly in the control preserved every recorded byte of env0's state.
4. Earlier job 142378 retained an aggregate equality result. This comparison reproduced the same failure signature and identified its field in the new run. It cannot reconstruct the missing field bytes from the earlier job.

## Repair and acceptance

Screen the candidate cabinet pose against the **same sampled arm posture** before committing a reset that can touch simulator state. Carry that validated pose and arm posture into the successful reset. A rejected request should return both environments, their random streams and the reset mask to their pre-request state. Keep the 60 mm start and 12 mm approach criteria and the byte-level isolation check.

The regression case should first compare both environments immediately after a rejected request, then accept a reset in the other environment and compare its passive neighbor against both the pre-rejection baseline and the matched control. Repeat in the opposite direction. The corrected left/right presets, ordinary resets and a glove trial remain open.

## Evidence

Job `142435` completed on the original PhysX CUDA backend. Slurm reported 12 of 120 allocation seconds and zero restarts. The application guard measured 10.713 of 90 seconds. All 379 frozen source files matched after collection. The queue, owned process group and visible job cgroup were empty. A CPU preflight caught an incompatible source-directory link and then a missing supervisor working directory. Both were resolved before the single GPU submission. Full scheduler and protection receipts are retained in the local delivery.

The raw record stores each state tensor's dtype, shape and original bytes. The offline verifier derives the table component and displacement directly from those bytes. From this directory run `python verify.py observations.json`. [Raw field observations](observations.json) · [GPU comparison](compare_resets.py) · [Offline verifier](verify.py) · [Run receipt](receipt.json)
