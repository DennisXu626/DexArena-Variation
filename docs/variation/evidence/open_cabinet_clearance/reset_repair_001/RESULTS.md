# OpenCabinet rejected reset — PhysX CUDA handback

Job **142978** passed the two-environment reset check at `77c46c05a64716c8c17d398b597540283df062e9`. The original 59.31 mm arm draw was refused before either scene changed. Applying `far` to the other environment afterwards gave the same result as applying `far` directly. Both environment orders passed.

## The field that originally failed

When env0 rejected `near`, its table X was **0.18000006675720215 m** immediately before and after the exception. The mask stayed `[true, true]`. The matched env1 `far` reset also left every byte of env0 intact. The checker read the immediate after-snapshot before any intervening reset, explicit scene flush, physics step or controller action. Job 142435 had recorded the table X changing to 0.18000000715255737 m at the corresponding exception. [Earlier diagnostic](../isolation_001/RESULTS.md)

| CUDA exercise | Outcome |
| --- | --- |
| Reject env0, then accept env1; exchange indices and repeat | Identical before/after rejection for both scenes, including table, robot, cabinet, task state, elapsed counters, mask and RNG records. Passive scene stayed identical after the following reset. Both complete branch endpoints matched their direct controls. |
| Seeded mixed batch | Env0 requested safe `far`, env1 requested unsafe `near`. Both scenes and all recorded streams retained their pre-request values. |
| Two accepted requests in reverse index order | Both arms received the intended joint coordinates. |
| Four ordinary local resets, seed once at 7 | Alternating 0, 1, 0, 1 gave four distinct poses. A fresh second session reproduced every placement record exactly, including actual simulator XY, yaw, arm and clearance. |
| Native path and PR #32 explicit coordinates | Native reset bypassed workspace sampling. PR #32 applied (0.19, 0.17) m at 20° and left the placement stream unchanged. |

## Hand clearance at reset

The start gap is measured between enclosing boxes formed from the simulator's live hand and cabinet collision geometry. The approach column is the conservative geometric screen along the planned pre-grasp path. The controller did not execute that path. Both environments' actual screened arm joints agreed exactly with the coordinates read after reset. All accepted cabinet XY/yaws met the checker tolerances.

| Request | Start gap env0 (mm) | Start gap env1 (mm) | Lowest approach screen (mm) |
| --- | ---: | ---: | ---: |
| `near`, historical adverse arm | Rejected | Rejected | 29.17; start screen **59.31**, below 60 |
| `far`, matched diagnostic arm | 148.27 | 148.27 | 29.05 |
| `left` | 109.16 | 108.22 | 29.87 |
| `right` | 92.84 | 96.76 | 28.92 |
| Ordinary, two resets per environment | 93.63, 104.14 | 95.28, 86.64 | 28.08 |

Each accepted case includes the requested and applied pose, screened and applied arm, predicted screen and first-frame measured clearance. Each refusal includes both scenes' raw tensor bytes and RNG observations. The earlier CPU run separately exercised nonzero elapsed counters and the 48-draw rejection limit. [CUDA observations](observations.json) · [CPU tests](../rejected_reset_repair/RESULTS.md)

## VR handoff

Ready for Dennis to try the accepted starts. Launch `CabinetPouringOpenCabinet-Sharpa-v1` with `handle_workspace=True` and use a fresh episode. For a one-environment VR session:

```python
env.reset(seed=7)  # ordinary placement; omit seed for successive draws
env.reset(options={"handle_placement": {"0": "left"}})  # also far, right, near
```

An unsafe named placement raises with its measured reason and preserves the current episode. This run supplies a rejected `near` witness. Finger–handle contact, the first glove-commanded frame, operator comfort and the continuous pull still require VR assessment.

## Execution receipt

One submission on Server 3, physical GPU 6. Slurm recorded **COMPLETED**, exit **0:0**, zero queue seconds, **32/180 allocation seconds**, no requeue and zero restarts. The application used **30.23/150 seconds**. Slurm accounting history was unavailable; the terminal job record supplied the timing. The owned process group, visible job cgroup and queue were empty. All **381** frozen files matched after the run. The guard sampled a peak of **98.10 MiB** against the **128 MiB** project threshold and retained 1,608 log bytes. SAPIEN logged its existing oblong-convex-hull fallback and continued through all assertions. [Run and cleanup receipt](receipt.json) · [Scheduler record](terminal.json)
