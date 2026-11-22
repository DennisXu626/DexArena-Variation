# SAPIEN v7 Windows SDK source recipe

This source bundle builds the Nut & Bolt native lock and batched visibility fixes. `COPY_MANIFEST.json` lists the exact files and SHA-256 values to include. The recipe directory retains the name `recipe-v6` expected by the build entry point. Its lock selects `3.0.3+dexarena.gpu1.wininterop7` and includes `patches/0310-batched-render-visibility.patch`.

Use the exact Windows toolchain and Python package versions in [lock.json](recipe-v6/lock.json). Git for Windows with Git LFS and Git Bash is required. Run from this bundle directory and choose a private work path that does not exist:

```powershell
$sdkWork = 'C:/sdk/nut-lock-visibility-v7'
$sdkPython = 'C:/envs/dexarena-panel/python.exe'
$sdkRepo = 'C:/checkouts/nut-bolt'
& $sdkPython -B ./tools/clean_build_windows.py --repo-root $sdkRepo --work-dir $sdkWork `
  --python $sdkPython --cmake 'C:/CMake/bin/cmake.exe' --ninja 'C:/tools/ninja.exe' `
  --git-bash 'C:/Program Files/Git/bin/bash.exe'
```

The script verifies the published bundle, installs the pinned recipe, and fetches fixed source commits and archives. It builds the nine PhysX host libraries and compiles SAPIEN native and pybind with two jobs. `--host-stage-manifest` reuses a previously compiled host stage after verifying the source, build, library and header identity. The reference build used this host dependency and compiled all SAPIEN and pybind objects in a fresh directory. Both options produce `runtime`, `physx-runtime` and `artifact.json` in the private work root. Add `--prepare-only` to install and verify the recipe without downloading or compiling; use `--resume` to continue in that directory.

Use `tools/launch_native_lock.py --sdk-root <work> --python <locked Python> --artifact-sha256 <reviewed receipt SHA> --validate-only` to verify the build identities and wheel/runtime bytes. To take the separate GPU probe, replace `--validate-only` with `tools/probe_batched_visibility.py -- --output <new evidence directory>` in an authorized GPU window. The probe exercises the standard CUDA raster batch, first-frame poses, both environments, round-trip visibility and rejection of structural changes.

## License and notice sources

[lock.json](recipe-v6/lock.json) lists fixed dependency sources and their license and notice locations under `upstream_license_sources`. Keep SAPIEN and simsense `LICENSE` files, svulkan2 per-file notices, and each dependency's copyright and notice files. The PhysX host workflow preserves `LICENSE.md` from NVIDIA's pinned source archive and the notices in the staged headers. CUDA and PhysX runtime downloads remain subject to their upstream terms. The files listed here consist of build scripts, source patches, locks and documentation. Source checkouts, wheels, DLLs, archived vendor input, cache files and runtime evidence belong in the private work root.
