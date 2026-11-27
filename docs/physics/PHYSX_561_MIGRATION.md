# Joint friction and GPU articulation repair: PhysX 5.3.1 → 5.6.1

This change requires **PhysX 5.6.1 (the 5.6 series)**, a matching rebuilt SAPIEN
core and Python bindings, and the GPU fixes below. Installing stock PhysX 5.6.1
or replacing only `libPhysXGpu_64.so` is insufficient.

**Integration status: draft.** The source patches and Python mapping are ready
for review. A new native wheel has not been built or released, and the new
repository integration has not passed GPU regression. The earlier isolated
runtime passed the three fixed full episodes described below; those results
must not be presented as tests of this new binding or as benchmark-wide success.

## What changes, and why this is task independent

1. MJCF `frictionloss` is an effort: N m for revolute joints, N for prismatic
   joints. SAPIEN's legacy `set_friction` sets a **dimensionless coefficient**
   whose resistance grows with the force transmitted through the joint. Passing
   a friction torque to that setter changes the physical model, particularly
   under sustained contact. The shared `apply_joint_physics` now sets the legacy
   coefficient to zero and supplies `(frictionloss, frictionloss, 0)` to the new
   PhysX static-effort, dynamic-effort and viscous-friction interface.
2. The GPU solver cleared an articulation's accumulated dependency paths in
   partitions where that articulation had no work. When the articulation next
   appeared, relevant link paths could be missing and produce a large impulse.
   The patch retains paths across those gaps and clears them when the next
   referencing partition consumes them. This follows
   [PhysX PR #538](https://github.com/NVIDIA-Omniverse/PhysX/pull/538), which was
   still unmerged when this integration was prepared. It is not an algorithm
   invented by this PR.
3. The validated base runtime also includes the TGS body-velocity launch coverage
   repair from [PhysX PR #544](https://github.com/NVIDIA-Omniverse/PhysX/pull/544)
   / [issue #543](https://github.com/NVIDIA-Omniverse/PhysX/issues/543). Keep it
   when rebuilding; the partition patch alone does not reproduce that base.

No task name, object identity, episode index, time/frame condition, fixed joint
count or right-hand-only condition appears in the repair. The mapping visits the
actual active joints and every native joint in a ManiSkill batch; side prefixes
are handled by the existing gain lookup. Sharpa, Wuji and XHand use the same
entry point. Tables, PD gains, force limits, armature, collision geometry,
contact materials, control frequency and success conditions are not retuned.
Callers that do not request `frictionloss` retain their existing behavior.

This changes simulation semantics and the collection code fingerprint. Record
the runtime and source revision with new datasets; do not relabel old datasets
or promise unchanged trajectories, existing-policy scores or throughput.

## Source bundle

The [manifest](../../tools/physics/physx561/manifest.json) pins both source
commits, each patch checksum and the earlier binary evidence hashes.

| Component | Required source/change |
|---|---|
| PhysX | `107.3-physx-5.6.1`, commit `5ca9f472105a90d70d957c243cb0ef36fe251a9f` |
| GPU dependency paths | `physx-5.6.1-partition-paths.patch` |
| TGS velocity coverage | `physx-5.6.1-tgs-velocity-coverage.patch` |
| SAPIEN | 3.0.3, commit `731622eac5b140b320076c8a1b6eb4b553c3ccd4` |
| Direct GPU API adapter | `sapien-3.0.3-direct-gpu-561.patch` |
| Native friction setter/readback | `sapien-3.0.3-friction-params.patch` |
| Matched source build and explicit GPU library loading | `sapien-3.0.3-runtime-build.patch` |

The Direct GPU API adapter carries forward the existing validated conversion of
rigid-body and articulation layouts, synchronization before temporary-buffer
reuse, and packing of **selected environment rows** for partial uploads. The
native setter is new: it replaces the diagnostic raw-pointer bridge with a
SAPIEN C++/Python API and preserves effort friction when cloning/reparenting
links. Legacy `set_friction` retains its coefficient meaning.

Patched SAPIEN exposes `joint.set_friction_params(static_effort, dynamic_effort,
viscous)`, `joint.get_friction_params()` and `joint.friction_params_enabled`.
As with SAPIEN 3.0.3 itself, supported movable joint types are revolute,
revolute-unwrapped and prismatic; this does not add spherical-joint support.

## Build/review recipe

These are explicit build instructions, **not an installer run by task import**.
Use a fresh build directory and the same compiler/CUDA ABI for PhysX, SAPIEN core
and bindings. Provision build space and resource limits before executing them.
There is no published replacement wheel in this draft. Existing requirements
and the Variation `tools/variation/sapien_sdk` 5.3.1 locks do not install this
candidate; update the runtime distribution and its hashes after build acceptance.

Set `DEXARENA`, `PHYSX_SOURCE` and `SAPIEN_SOURCE` to absolute local checkout
paths; the two source checkouts must be at the commits in the manifest. Fetch
SAPIEN's pinned submodules through its normal source-build procedure.

```bash
PATCHES="$DEXARENA/tools/physics/physx561"
git -C "$PHYSX_SOURCE" apply --check \
  "$PATCHES/physx-5.6.1-partition-paths.patch" \
  "$PATCHES/physx-5.6.1-tgs-velocity-coverage.patch"
git -C "$PHYSX_SOURCE" apply \
  "$PATCHES/physx-5.6.1-partition-paths.patch" \
  "$PATCHES/physx-5.6.1-tgs-velocity-coverage.patch"
git -C "$SAPIEN_SOURCE" apply --check "$PATCHES"/sapien-3.0.3-*.patch
git -C "$SAPIEN_SOURCE" apply "$PATCHES"/sapien-3.0.3-*.patch
```

The earlier experiment used Linux, CUDA 12.4 and A100 (`sm80`). The optional
`physx-5.6.1-sm80-build.patch` reproduces that **build profile**, restricting GPU
code generation to sm80 and using one NVCC worker per translation unit. Apply it
only for that profile. Other GPU/toolchain targets need their own build and
acceptance; do not treat sm80 evidence as Windows or other-GPU validation.

Example configuration for the documented Linux/sm80 profile, after applying
that optional patch (set `BUILD`, `DIST`, `CUDA_PATH`, `JOBS` explicitly):

```bash
cmake -S "$PHYSX_SOURCE/physx/compiler/public" -B "$BUILD/physx" \
  -DTARGET_BUILD_PLATFORM=linux -DCMAKE_BUILD_TYPE=release \
  -DPHYSX_ROOT_DIR="$PHYSX_SOURCE/physx" \
  -DPX_OUTPUT_LIB_DIR="$DIST" -DPX_OUTPUT_BIN_DIR="$DIST" -DPX_OUTPUT_ARCH=x86 \
  -DPX_GENERATE_STATIC_LIBRARIES=ON -DPX_GENERATE_GPU_PROJECTS=ON \
  -DPX_GENERATE_GPU_REDUCED_ARCHITECTURES=ON \
  -DPX_BUILDSNIPPETS=OFF -DPX_BUILDPVDRUNTIME=OFF \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DCMAKE_CUDA_COMPILER="$CUDA_PATH/bin/nvcc" \
  -DCMAKE_CUDA_ARCHITECTURES=80 -DCUDAToolkit_ROOT="$CUDA_PATH"
cmake --build "$BUILD/physx" --parallel "$JOBS"
```

For SAPIEN, export `SAPIEN_PHYSX5_DIR="$PHYSX_SOURCE/physx"` and set
`SAPIEN_PHYSX5_LIB_DIR` to the resulting directory containing the seven matching
`libPhysX*_static_64.a` files. Build the core **and** Python bindings with
SAPIEN's source-wheel procedure (`python setup.py --build-dir "$BUILD/sapien"
bdist_wheel`). Package the shared dependencies using SAPIEN's platform wheel
procedure; test installation in a clean environment. The CMake patch rejects
headers other than 5.6.1 and disables fallback to precompiled 5.3.1.

At runtime, set `SAPIEN_PHYSX_GPU_LIBRARY` to the **absolute path** of the patched
GPU library from the same build. The loader performs no download or cache
fallback. Keep core/bindings/GPU library together and record their actual paths
and SHA-256 hashes after installation. The new core adds a native API, so the
earlier isolated core hash is provenance, not the expected hash of the new build.

## Validation and acceptance

Local source checks for this PR:

```bash
python -B -m unittest discover -s tests -p test_joint_friction_mapping.py -v
```

Seven tests cover the three current hand tables, both sides, shuffled joint
order, three native environments, native joints, zero friction, an unsupported
runtime, empty wrappers, reconfigure/repeated application and preserved
PD/armature/velocity settings. These are interface tests, not simulated motion.
All source patches also pass `git apply --check` on their pinned bases.

After building/installing the candidate, run
`python tools/physics/check_friction_runtime.py` for CPU native readback,
unchanged drive/armature and clone preservation. **This has not run yet.**

Before changing this PR from draft / merging:

- Build/install matching Linux core, Python binding and GPU library; record
  compiler, CUDA, GPU, source/patch hashes and loaded binary paths/hashes.
- Run the native check above, add a low-torque free-joint test of the friction
  effort on CPU and GPU, and check reparent/reconfigure readback.
- Run single, left/right/dual-hand and batched scenes; change/reset selected
  environments in reordered/noncontiguous batches and compare untouched
  environments' qpos/qvel, root state, targets and RGB. Cover both fixed and
  floating bases, including the existing Variation partial-reset/render fixes.
- Reproduce a nonadjacent GPU-partition case, then repeat the three frozen
  original episodes with identical controls and acceptance gates. Include a
  second manipulation/contact task and another supported hand. Preserve failures
  and compare displacement, rotation, contact force and runtime cost.
- Integrate the accepted wheel/artifact into repository setup/SDK locks. Validate
  Windows separately before advertising Windows support. No automatic CI or
  GPU job is enabled by this PR.

## Earlier isolated evidence (2026-11-27)

The failing case used eight GPU partitions. A 53-link articulation occurred in
partitions 0, 1, 3, 5 and 7; the gaps exposed lost paths to links 43 and 46.
In a matched-state intervention, the first contact-force peak fell from
**147.988 N to 5.208 N**; the later peak from **249.808 N to 5.196 N**.
The 50 ms relative displacement fell from **2.488930 mm to 0.002156 mm** and
rotation from **4.185507° to 0.005131°**. All 2,615 recorded pre-intervention
prefix fields matched. This ties the large impulse to the partition defect.

With both corrections active from initialization, all **3/3** fixed full
episodes passed the original frozen grasp + planned transport + 1 s hold gate.
The formerly failing episode's grasp-force peak fell from **249.808 N to
8.167 N**. Physics/control frequencies remained 400/20 Hz and solver iterations
24/8; there was no PD retuning, task-specific joint cap or retraining.

Retain the limitations: a mid-episode patch intervention still failed transport;
it is not one of the 3/3 passes. Another episode's peak 50 ms displacement during
closing increased from 1.101 mm to 1.865 mm. This is evidence for the diagnosed
failure and the fixed episodes, not a claim that every metric or every task
improves. Raw traces/videos remain external experiment evidence and are not
committed as repository assets.

## Attribution and rollback

The PhysX patches apply to NVIDIA's BSD-3-Clause source; the SAPIEN patches apply
to its Apache-2.0 source and retain the original source notices. The GPU fixes
are attributed above. The compatibility adapter is carried forward from the
earlier integration, with task-specific names removed; this draft does not
claim a new numerical solver.

Rollback restores the prior repository revision **and its complete matching
runtime**. Do not mix a 5.3.1 core with 5.6.1 GPU binaries or silently fall back
to the old coefficient mapping. Keep old and new collection provenance separate.
