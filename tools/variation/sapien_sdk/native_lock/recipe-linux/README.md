# Nut & Bolt Linux SDK

Nut & Bolt requires the common indexed GPU writeback patch, the native PhysX lock update, and batched raster visibility for SeatNut. This recipe builds a private Linux x86-64 host and a CPython 3.10 SAPIEN wheel. The upstream PhysX version remains `105.1-physx-5.3.1.patch0`.

## Private host and wheel

Use the shared Linux build environment and pinned CUDA toolkit. Run host and wheel builds with the same resolved C and C++ compilers. The vendor archives and their SHA-256 values are in [lock.json](lock.json). Download the PhysX fork source, the Linux release reference and the Linux solver archive to a private directory. The reference archive supplies header comparisons. The final host libraries come from a fresh Release/PIC build. [PhysX fork](https://github.com/sapien-sim/PhysX/tree/8026efddef81130fb97ec3b4a51da66fab39f09d) · [Linux publisher recipe](https://github.com/sapien-sim/physx-precompiled/blob/088814a38c9f1068b3a4e4a43ade1d4a17887864/build-linux.sh) · [Vendor archives](https://github.com/sapien-sim/physx-precompiled/releases/tag/105.1-physx-5.3.1.patch0)

```bash
recipe=tools/variation/sapien_sdk/native_lock/recipe-linux
common=tools/variation/sapien_sdk
bash "$recipe/build.sh" "$common/build_linux.py" "$work/host" "$work/sdk" \
  "$inputs/PhysX-8026efddef81130fb97ec3b4a51da66fab39f09d.tar.gz" \
  "$inputs/linux-release.zip" "$inputs/linux-so.zip"
```

The private host patch moves the original setter out of line without changing the PhysX structure layout. It writes lock flags and calls the existing `updateBodySim` in the same `ScBodyCore` object that defines the native capability. The recipe checks all nine archives, the generated `PxConfig.h`, the setter and marker object membership, and a linked CPU lock/unlock fixture before releasing the stage.

`host/physx-host` supplies `include/`, `bin/linux.clang/release/` and the upstream license. SAPIEN uses it through `SAPIEN_PHYSX5_DIR`. The independent solver remains under `physx-runtime/`. The Nut wheel layers 0300 and 0310 over the shared indexed and packaging patches. The isolated wheel import checks both native functions before the build writes `sdk/artifact.json`.

`artifact.json` uses the shared `dexarena-sapien-linux-artifact-v1` schema. The Nut profile uses `dexarena-nut-linux-wheel-profile-v1` in `nut_linux.schema`. Both capability fields are top-level integers. Patch paths in `patches` and `nut_linux.sapien_extra_patches` are relative to `tools/variation/sapien_sdk`. Runtime integrations must select the Nut profile for this version and check both native capabilities. Keep the sources, compiler identity, original license notices and output receipts with their corresponding artifact.

## Verification

From the repository root, use Python 3.10 or newer for the CPU-only recipe checks.

```bash
python -B -m unittest discover -s tests -p test_nut_linux_recipe.py
bash -n "$recipe/build.sh"
```

The authorized Linux GPU checks use an audited interpreter with the GPU dependencies and a single selected physical GPU. Supply a reviewed artifact hash and run both probes serially in the project resource window. Use a fresh output path for each run.

```bash
artifact="$work/sdk/artifact.json"
python3.10 -B "$recipe/run_probes_linux.py" lock --common-runner "$common/run_linux_check.py" \
  --artifact "$artifact" --artifact-sha256 "$artifact_sha256" \
  --approved-gpu --gpu-uuid "$gpu_uuid" --output "$work/probe-lock"
python3.10 -B "$recipe/run_probes_linux.py" raster --common-runner "$common/run_linux_check.py" \
  --artifact "$artifact" --artifact-sha256 "$artifact_sha256" \
  --approved-gpu --gpu-uuid "$gpu_uuid" --output "$work/probe-raster"
```

The lock fixture checks six independent axes, indexed state restoration, unaffected bodies and actual contact over 160 PhysX steps. The raster fixture checks the first CUDA frames of two scenes, free and threaded visibility, exact restoration and rejection of structural changes. Linux adapters use actual mapped ELF paths and hashes and retain both source versions. The child process verifies that its private `libcuda.so` alias and `libcuda.so.1` open the same system driver handle. Separately run PickBolt, SeatNut and TurnNut with the Nut-aware common task launcher. Use standard CUDA RGB, two environments and both reset directions. Include SeatNut's stage transition and preservation of the unselected environment in task acceptance.

Source verification and shell parsing can run without a Linux execution environment. Compiled archives, an executable host-link probe, an isolated Linux import and native GPU captures require their corresponding Linux environments and evidence.
