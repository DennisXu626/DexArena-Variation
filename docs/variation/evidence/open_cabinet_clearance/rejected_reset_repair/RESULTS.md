# OpenCabinet rejected reset — CPU verification

The recorded arm draw from job 142435 still refuses `near` at **59.31 mm**. The repaired public reset preserves both CPU fixture rows at the exception. Resetting the other row to `far` afterwards gives the same final state as a direct `far` reset, in both directions. PhysX CUDA verification is pending. [Original failure and raw trace](../isolation_001/RESULTS.md)

## Commit boundary

ManiSkill 3.0.0b22 sets RNG state, writes the scene mask, zeros elapsed steps, clears simulation state, and resets the agent before it calls the task initialization hook. On the opt-in path, OpenCabinet now plans the entire selected batch **before** calling that public base reset. Planning uses disposable per-environment NumPy streams and a device-local Torch generator with the native seven arm means and noise scale. Construction can plan before the articulation exists. The commit hook fills the single-arm rest keyframe with the seven screened coordinates and applies the validated root. The next seed for each selected workspace stream is published only on success. The seed-to-placement sequence changes with this repair.

The native task entry, PR #32 explicit coordinates and archived-state restore still delegate to the SDK. The geometry, named positions, 60 mm start threshold, 12 mm approach threshold and 48-candidate bound are unchanged. An unsafe named request reports its environment and measured reason.

## Results

| CPU check | Observation |
| --- | --- |
| `near` rejected, env0 and env1 separately | 59.31 mm start, 29.17 mm approach. Immediate physical/task tensor bytes, nonzero elapsed steps, reset mask, main/episode/workspace and process RNG states matched for both rows. |
| `near` rejected → opposite `far`, versus `far` alone | Both environment orders matched at baseline and end. Passive row unchanged at every checkpoint. Matched `far` had 143.43 mm start and 29.05 mm approach. |
| Mixed seeded request | Safe `far` in env0 followed by unsafe `near` in env1. Both pre-request rows and RNGs survived. |
| Draw exhaustion | Forced all 48 candidates to fail the screen. No 49th draw and no committed change. |
| Reverse-order accepted batch | Different arms supplied for env1 and env0. Each articulation row received its own arm in mask order. |
| `left` | Env0 108.47 / 29.85 mm, env1 63.30 / 29.93 mm (start / approach). |
| `right` | Env0 82.71 / 28.96 mm, env1 107.84 / 29.01 mm. |
| Ordinary resets | Four distinct poses, alternating env0/1. Same arm vectors and poses on replay after seeding once with 7. Lowest start 74.96 mm, lowest approach 28.08 mm. |
| Compatibility | Native initialization bypassed the workspace planner. PR #32 applied (0.19, 0.17) m at 20° with no change to the private placement stream. Historical geometry audit reran with an identical parsed result. |

For each accepted placement the [CPU results](cpu_results.json) contain the requested preset or sampling mode, planned and applied XY/yaw, screened and applied arm joints, start gap and approach screen. The CPU gaps come from the archived collision geometry. The tensor fixture uses the installed SDK's actual reset and RNG method bodies and the task's actual planning and initialization methods. It supplies storage and setters for two scene rows and compares physical and task tensors by dtype, shape and bytes. No controller step or GPU flush occurs in the rejection snapshot.

A separate CPU replay used the registered Gymnasium 0.29.1 `gym.make` entry, the installed ManiSkill `TimeLimitWrapper`, the production task class and CPU scene storage. It ran two fresh sessions with one seed each and ordinary local resets in the order 0, 1, 0, 1. The arm draw ran unmodified. Both sessions' four positions and all seven joint angles also matched the local fixture exactly. This registered-entry receipt predates the final normalization of unsorted index lists. A repeat lost its SSH connection. The final local suite separately verified reversed batch order and reproduced every registered replay coordinate exactly. [Registered-entry replay](gym_cpu_replay.json)

## Reproduction

With the repository on the Python path, run the CPU suite with the two source files from the deployed ManiSkill installation. The receipt records SHA-256 of the SDK text using LF line endings.

```sh
python -B tools/variation/open_cabinet_reach/check_atomic_reset.py \
  --cpu-sdk "$SITE/mani_skill/envs/sapien_env.py" "$SITE/mani_skill/envs/utils/randomization/batched_rng.py" \
  --output cpu_results.json
```

The proposed CUDA checker uses the same scenarios through the registered two-environment task. It reads the simulated articulation qpos, cabinet pose, door angle and current collision-link bounds immediately after accepted resets. It checks the immediate rejected state before another reset or explicit flush, then compares the matched branches. The remaining questions are whether the real deferred table writes remain absent, whether CUDA actors actually receive the screened poses and clearances, and whether resetting one environment preserves its neighbor. Dennis's glove trial follows that check. [GPU budget request](GPU_REQUEST.md)
