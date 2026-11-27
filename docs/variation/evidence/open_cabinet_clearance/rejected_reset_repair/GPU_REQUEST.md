# Dennis approval requested — one OpenCabinet reset check

| Item | Proposed limit |
| --- | --- |
| Work | One two-environment `physx_cuda` job. Reuse the read-only frozen scene/assets and deploy only the checked changes. Exercise the registered public reset and compare immediate physical/task bytes, counters, mask and RNG states. Record actual cabinet, arm and start clearance for accepted cases. |
| Time | One card, at most **180 allocation seconds**, application timeout **150 seconds**. Total wall clock **45 minutes** from approval, including network and queue. Submit by minute 25 with at least 20 minutes left. At most 120 seconds pending, then cancel that job. Reserve the final **15 minutes** for handback. |
| Output | Server `/mnt/ceph2/xkl/DexArena/open_cabinet_start_clearance_20261125/reset_repair_001/`. Local logs and transfers `D:/Logs/DexArena/open_cabinet_start_clearance/reset_repair_001/`. |
| Storage snapshot | 26 November 2026, 12:54 China time. Existing Ceph project used 51,597,707 bytes (49.21 MiB). Available filesystem space: Ceph 393.26 GiB, D: 110.52 GiB. Refresh both and verify resolved paths immediately before submission. |
| Growth and limits | Evidence estimate under 2 MiB, expected incremental private growth under 8 MiB. Sample the **entire** Ceph project about once a second and stop at 128 MiB, including previous evidence. Sampling permits transient overshoot. Free-space floors: 20 GiB on Ceph, 10 GiB on D:. Cap application logs at 8 MiB and ordinary files at 64 MiB. Disable core dumps. |
| Stop and cleanup | Stop at the first failed assertion, unexpected write, timeout, storage threshold or free-space floor. Save the first differing field and recover partial evidence. Use the owned process group and scheduler guard, verify terminal status, queue and cleanup. No requeue or retry. |

Required decision: approve this new submission, its paths and sampled-capacity risk. Job 142435 used the previous authorization. The CPU repair used zero GPU seconds.
