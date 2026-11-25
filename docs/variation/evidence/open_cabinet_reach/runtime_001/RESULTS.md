# OpenCabinet simulator reset check

**All four VR presets passed the 1 mm handle-position requirement.** The handle is measured from the simulated collision geometry at the closed-door reset, before any simulation step. All four cabinet yaws were 15°, all four door angles were zero, and all four measurements used door collision piece 13. The sampled ordinary and boundary placements also met the same tolerance. The check covers initialization on the original two-environment physx_cuda backend. Finger contact and a continuous pull await Dennis's VR trial.

| Preset | Expected world XYZ (m) | Measured world XYZ (m) | 3D error (mm) | Result |
|---|---|---|---:|---|
| near | (-0.3530145, -0.1931087, 0.4520987) | (-0.3530141, -0.1931085, 0.4520986) | 0.000440 | Pass |
| far | (-0.1730145, -0.1931087, 0.4520987) | (-0.1730140, -0.1931085, 0.4520986) | 0.000495 | Pass |
| left | (-0.2630145, -0.1031087, 0.4520987) | (-0.2630139, -0.1031086, 0.4520986) | 0.000539 | Pass |
| right | (-0.2630145, -0.3631087, 0.4520987) | (-0.2630139, -0.3631086, 0.4520986) | 0.000533 | Pass |

Measured near–far separation was **18.000006676 cm** (predicted 18 cm). Left–right was **26.000002027 cm** (predicted 26 cm). The [raw observations](observations.json) preserve the expected and measured coordinates and signed XYZ differences at full precision. All four reference coordinates come directly from the [frozen CPU predictions](../CPU_RESULTS.json). Source baseline was 2faa652. Tested commit was `01ef9aed779e0c6d2b50062716b9063f0a87cd37`. The only code change was the runtime checker.

## Reset outcomes

- Native reset and PR #32 explicit-coordinate control both passed in both environments. The explicit request placed both roots at (0.19, 0.17) m and 20°.
- Seed 7 reproduced both environments' root poses, yaw, closed-door state and measured handles on replay, including the next ordinary reset. For env0, the seeded reset produced root XY (-0.0968103, -0.2002177) m, yaw 10.00°, handle XYZ (-0.3856075, -0.4240051, 0.4520987) m. The next unseeded reset produced root XY (0.0153849, -0.0949888) m, yaw 10.00°, handle XYZ (-0.2734125, -0.3187762, 0.4520987) m. Across those four placements the maximum handle error was **0.183159 mm**.
- Resetting env0 alone and env1 alone each preserved the other environment’s physical state, task-state tensor and random stream exactly. The observations contain both state digests for each direction. Each selected environment started with the door closed. Offline comparison of its saved handle with the map gave 0.183114 mm (env0) and 0.179414 mm (env1). [Local handle audit](local_handle_audit.json)
- At 10°, 15° and 20° respectively, one exact boundary placement was accepted and one exterior request rejected. Handle errors at the three accepted points were **0.179637, 0.000426, 0.183108 mm**. For these wider poses, the checker transforms the map’s nominal closed-handle offset to the actual root pose. These measurements cover the sampled points. The previous 8,192-draw CPU coverage is linked in the [map report](../RESULTS.md).
- SAPIEN reported oblong convex-hull cooking warnings and continued on its GPU backend. No physical step or contact was exercised here.

## Launch and accounting

The [CPU launch](cpu_launch.json) and [simulator launch](observations.json) used the same staged working directory, interpreter, task package, Python argv, reference, checker and writable output path. The CPU preflight exercised the same comparison: exact match 0 mm, a displaced test point 2 mm rejected. It exited normally under the owned-process guard. All 375 staged runtime file identities matched the frozen commit after the run.

Slurm job **142152**, lyg0295 card 6, **COMPLETED**, exit **0:0**, one allocation of **10/180 seconds**, application **9.675/150 seconds**. Submit and start share the same scheduler second. No requeue or restart. The accounting database was unavailable, so the [terminal receipt](terminal.json) records the live controller's final status, start, end and runtime. The queue, owned PGID and visible job cgroup were empty after completion. [Guard](guard.json) · [CPU guard](cpu_guard.json) · [Capacity](capacity.json) · [Submission](submission.json) · [Source verification](source.json)

Pre-submit free space was 536.72 GiB on Ceph and 109.14 GiB on D:. Peak observed during the guarded run was 48.60 MiB against the 128 MiB sampled stop. The uncompressed raw evidence totals 159,391 bytes, including two preallocated receipts. Logs and temporary transfer were confined locally to `D:/Logs/DexArena/open_cabinet_handle_workspace/runtime_001/`.

## Use in VR

Use the PR version of the registered task. In the VR launcher's Gym construction settings add `"handle_workspace": true`. Use a normal episode reset to advance the stream. An external launcher that reapplies a saved scene snapshot will restore that snapshot instead.

```python
import gymnasium as gym
import tasks

env = gym.make("CabinetPouringOpenCabinet-Sharpa-v1", handle_workspace=True)
env.reset(seed=7)
env.reset()  # next random placement

env.reset(options={"handle_placement": {"0": "near"}})
env.reset(options={"handle_placement": {"0": "far"}})
env.reset(options={"handle_placement": {"0": "left"}})
env.reset(options={"handle_placement": {"0": "right"}})
```
