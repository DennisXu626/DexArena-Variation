# OpenCabinet VR placement trial

For the updated sampler and headset calls, see the [start-clearance investigation](../open_cabinet_clearance/RESULTS.md). The measurements below describe the original PR #46 presets.

**Simulator update, 25 November.** All four presets passed the 1 mm handle-position check. The measured separations were 18.000007 cm near–far and 26.000002 cm left–right. [GPU reset results and VR invocation](runtime_001/RESULTS.md)

**Start with `near` and `far`.** The closed handle moves 18 cm in depth at the same lateral position. Then try `left` and `right`: the handle moves 26 cm sideways at the same depth. All four use a 15° cabinet yaw and the native closed door. CPU evidence is ready for review. Actual reset, contacts and operability still need the runtime short check and a VR pull.

## What ordinary resets do

The starting revision is `128526c9588098c940b6664372eca8b8eb52aab9`. Gym registers the left angled mobile-base Sharpa for this task. The short task calls `requested_layout`, resets the workspace, and passes the result to `_initialize_cabinet(..., door_open=False)`. With no layout, the parent samples two independent Torch uniforms about (14, 12) cm using `cabinet_init_xy_noise=0.01`, with yaw fixed at 15°. PR #32 validates absolute coordinates on explicit reset and overwrites that native draw. Its 10 × 10 cm box does not supply a distribution for ordinary resets. [Registration](../../../../tasks/config/hands.py) · [Short-task reset](../../../../tasks/cabinet_pouring/cabinet_pouring_open_cabinet.py) · [Native initialization](../../../../tasks/cabinet_pouring/cabinet_pouring_long.py) · [PR #32 parser](../../../../tasks/cabinet_pouring/position_layout.py)

The repository includes the recording/replay side. Replay passes the stored `env_kwargs` to `gym.make` and can restore both episode seed and saved state. The live teleoperation launcher is external. Dennis’s session manifest and live reset calls were unavailable. The unknowns are the actual `cabinet_xy` and `cabinet_init_xy_noise` overrides, whether the launcher passed a fixed `position_layout`, and whether it reused a seed or restored the same snapshot each episode. Repeatedly restoring one saved state would supersede any new draw. [Recording boundary](../../../../data_gen/recordings/README.md) · [Replay entry](../../../../data_gen/recordings/replay_recording.py) · [Seed handling](../../../../data_gen/recordings/episode_store.py)

## Activate it

Use this branch’s task registration. Add `{"handle_workspace": true}` to the launcher's Gym construction kwargs. Start each trial with an episode reset. Use a fixed seed once for a repeatable sequence; subsequent ordinary resets advance the stream.

```python
import gymnasium as gym
import tasks  # register environments

env = gym.make("CabinetPouringOpenCabinet-Sharpa-v1", handle_workspace=True)
obs, info = env.reset(seed=7)
obs, info = env.reset()  # new interior XY and one of the three yaws

env.reset(options={"handle_placement": {"0": "near"}})
env.reset(options={"handle_placement": {"0": "far"}})
env.reset(options={"handle_placement": {"0": "left"}})
env.reset(options={"handle_placement": {"0": "right"}})

# After any reset, read the effective single-environment pose.
e = env.unwrapped
print(e.cabinet.pose.p[0], e.cabinet.pose.q[0], e.door_handle_xyz)
```

For a selected environment in a batch use `options={"env_idx": torch.tensor([1], device=e.device), "handle_placement": {"1": "far"}}`. Numeric requests use the same key, e.g. `{"0": {"cabinet_xy_m": [0.095, 0.055], "yaw_deg": 15}}`. Only the selected environment streams advance on random requests. Named and numeric requests draw no layout random numbers. Existing `position_layout` calls continue through the PR #32 bounds; supplying both explicit interfaces raises an error. The new opt-in is restricted to the registered left angled Sharpa. [Sampler](../../../../tasks/cabinet_pouring/open_cabinet_workspace.py) · [Screened cells and presets](../../../../tasks/cabinet_pouring/open_cabinet_cells.json)

| Option | Cabinet XY, cm | Yaw | Closed handle XY, cm |
|---|---:|---:|---:|
| near | (−8.5, 5.5) | 15° | (−35.30, −19.31) |
| far | (9.5, 5.5) | 15° | (−17.30, −19.31) |
| left | (0.5, 14.5) | 15° | (−26.30, −10.31) |
| right | (0.5, −11.5) | 15° | (−26.30, −36.31) |
| Random example, standalone CPU stream initialized to 7 | (−9.68, −20.02) | 10° | (−38.54, −42.40) |

Handle height is 45.21 cm. These coordinates come from the actual sampler and closed-door transform on CPU. The runtime short check will record the poses and engine episode seeds from Gym. Operator directions assume the user is on the robot side looking along world +X: near = −X; left = +Y.

## Region and limits

| Yaw | World X bounds, cm | World Y bounds, cm | Near–far × left–right, cm | Accepted area, cm² |
|---|---:|---:|---:|---:|
| 10° | −11 to 10 | −26 to 8 | 21 × 34 | 487 |
| 15° | −10 to 12 | −20 to 16 | 22 × 36 | 554 |
| 20° | −10 to 14 | −16 to 24 | 24 × 40 | 641 |

The native jitter spans **2 × 2 cm** and the prior explicit box spans **10 × 10 cm**. The table lists the extreme coordinates of irregular blue regions. Points in the corners of their bounding rectangles can lie outside them. The sampler picks yaw with equal probability, a 1 cm² cell uniformly at that yaw, and continuous uniform XY inside the cell. [10° view](yaw_10.png) · [15° view](yaw_15.png) · [20° view](yaw_20.png)

**Near:** the first rejected neighbouring X nodes at all three western limits cross the physical table edge with part of the closed cabinet. **Far and left:** closed-handle reach alone overstates the available workspace. Later pull poses can miss the orientation/position tolerance or need an abrupt change in joint angles. At the old nominal root (14,12) cm and 15°, the chosen IK branch requires a 0.82 rad change in one joint at the 40°→50° step. The chosen 0.60 rad screen excludes that path. **Right:** the buffered, closed-grasp approach boundary cuts the low-Y extent. The discrete screen and IK branch also influence the exact outermost cells. The old interfaces still provide the nominal placement for comparison. [Per-side neighbouring-node classifications and individual pull poses](CPU_RESULTS.json)

## How the three boundaries were obtained

- **Red, arm reference.** The URDF puts the left arm mount at (−87,+22,0) cm and the shoulder axis at Z=33.3 cm. With the grip midpoint constrained to Z=45.21 cm and wrist orientation free, 18 bounded FK optimizations converged; nine found the best radius within 0.01 mm. The red circle uses that **105.99 cm** radius. It is a numerical reference. The independent, looser link-length upper bound at this height is 114.35 cm. Joint limits and obstacles prevent access to all points on the circle.
- **Green, closed-handle approach.** A 4.5 cm pre-grasp offset follows the cabinet normal. The pinch frame comes from the previously measured nominal thumb and index IK solution, with the hand joints in the task rest pose. Replaying the URDF gives a 0.00057 mm midpoint discrepancy against that archived target. A 4° roll about the thumb–index line preserves the two target tips and clears a conservative palm/handle-box overlap found at nominal. Only the CPU screening hand pose uses this roll. The search starts from the task’s nominal seven arm angles and uses URDF joint limits. The displayed search covers the forward work area; the straight edge at the arm mount is the search window. A 2 cm discovery pass is refined at **5 mm** over successful areas and 3 cm around them. IK tolerances are **1 mm** translation and **0.75°** orientation. The mask is eroded by **10 mm plus two pixel half-diagonals** so accepted pixels clear the modelled failed pixels by at least 1 cm. The requested buffer spans two fine-grid intervals. The finite search can omit reachable islands.
- **Blue, cabinet roots.** The actual table extends from X=−42.45 to +78.45 cm and Y=−120.90 to +120.90 cm. Each yaw transforms the full closed body, door and handle footprint. All must fit. The real hinge is taken from the moving link transform; the closed grip is the task’s measured handle centre. The door and hand move about that hinge clockwise in plan view. The screen solves pre-grasp, closed grasp, then **10°, 20°, …, 80°**, each from the preceding arm solution. Steps after pre-grasp are limited to 0.60 rad per joint. The hand orientation rotates with the door. The root map keeps 1 cm cells whose four corners and centre pass, whose translated closed handle lies in the buffered green area, and which belong to the largest edge-connected component. Interpolation inside a cell and between door-angle samples awaits simulation.
- **Collision coverage.** At the ten tested poses, transformed URDF arm, bracket and hand collision-mesh enclosures are screened against the tabletop and the 39 measured cabinet/door/handle piece enclosures. Finger contact with the intended hardware is allowed. The palm mesh uses tighter triangle-group boxes. Door sweep versus trolley is checked with height separation before planar overlap. The bearing cabinet and full closed footprint stay on the table; an open door may overhang its edge. No additional pull nodes were rejected by the box filter after the path checks with the selected grasp. Full self-collision, continuous collision, closing fingers, contact force, a successful pull and the five-step 80° success hold remain unverified. The earlier task test got 16/16 legal closed starts and 0/6 automated pulls reaching 3°. [Earlier measurements](../cabinet_position_boundaries/runtime_002/RESULTS.md) · [Collision input with export hash](collision_bounds.json) · [Filter counts](screen_counts.json)

## Reproduction and runtime request

The CPU audit replayed 8,192 draws exactly, checked every draw against its yaw-specific region, checked each named placement through all ten poses, tested both selected-env RNG directions, and accepted one exact boundary and rejected one exterior request at each yaw. [CPU results](CPU_RESULTS.json) · [Offline measurement code](../../../../tools/variation/open_cabinet_reach/measure.py) · [Proposed runtime checker](../../../../tools/variation/open_cabinet_reach/check_runtime.py)

From the repository root, use the existing NumPy/SciPy/Numba/trimesh/Shapely/Matplotlib CPU environment. The checked-in small collision bounds are sufficient. `measure.py --extract PATH_TO_STAGE2/runtime_geometry.json` regenerates those bounds from the historical mesh export.

```text
python -B tools/variation/open_cabinet_reach/measure.py
python -B tools/variation/open_cabinet_reach/check_cpu.py
python -B tools/variation/open_cabinet_reach/figures.py
python -B tools/variation/check_static.py
```

**GPU approval requested.** One single-card Slurm submission, **180 allocated seconds**, **150 application seconds**, **45 minutes total wall time** including a **15-minute handback reserve**. Queue allowance 120 seconds, submit by minute 25 at the latest, no requeue or retry. Use two environments with the original GPU backend. Capture ordinary seeded/unseeded sequences twice, the four fixed cases, exact boundary/exterior inputs per yaw, native and PR #32 controls, and env0-only/env1-only resets with the unselected physics, task state and RNG compared before any step. Read actual root poses, door angle and handle collision geometry. This short check ends at initialization; Dennis’s manual pull is a separate decision.

Proposed Ceph root `/mnt/ceph2/xkl/DexArena/open_cabinet_handle_workspace_20261124/runtime_001/`; local logs `D:/Logs/DexArena/open_cabinet_handle_workspace/runtime_001/`. Estimate <2 MiB of JSON, receipts and logs, <64 MiB of private run/cache growth with read-only source, assets and dependencies. Check resolved paths and ≥20 GiB free on Ceph and ≥10 GiB on D: immediately before submission. Use the existing private launcher/PGID guard, no core, 8 MiB retained logs, 64 MiB per file, 128 MiB project-root stop sampled about once a second. Sampling may overshoot; this is a new root and budget. Stop on failed preflight, insufficient reserve, first failed assertion, unaccounted write, capacity or time limit. Preserve partial evidence and the exact Slurm terminal state. GPU used in this handoff: **0 seconds**.
