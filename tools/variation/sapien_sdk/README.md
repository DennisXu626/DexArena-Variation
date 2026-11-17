# SAPIEN GPU build for furniture assembly

This bundle builds patched SAPIEN `3.0.3+dexarena.gpu1.wininterop5` for partial GPU reset and Windows CUDA RGB. A clean source/native/Python/wheel build and standard two-environment GPU checks passed for LayFlatPanel, InsertRail and FastenScrew. See the [validation summary](../../../assets/appearance/furniture_assembly/previews/runtime_check_20261117/summary.json).

The six patches have three groups:

- `0001`–`0002`: six indexed GPU apply corrections and native `indexed_gpu_apply_patch_version() == 1`. Required on every platform for furniture partial GPU reset, including Linux; stock `sapien==3.0.3` lacks these corrections.
- `0101`–`0103`: Windows Vulkan/CUDA handles and shared memory imports, header macro compatibility, and the `nvcuda.dll` driver loader.
- `0200`: an opt-in local package version shared by wheel metadata and runtime.

Use **PowerShell 7** (tested 7.6.9), 64-bit CPython 3.10.22, Git for Windows, CMake, Ninja, MSVC x64 C++ tools and an NVIDIA driver. Exact tool/dependency versions and official download hashes are in [lock.json](lock.json); the build rejects mismatched tools. The tested compiler pair is MSVC 19.43.34810 with nvcc/CUDAFE/PTXAS 12.4.131 and explicit `-allow-unsupported-compiler`. NVIDIA PhysX 5.3.1 GPU solver binaries are pinned separately by archive/DLL SHA because their compiler version is unpublished.

Run from this directory. Choose new build, runtime and output paths outside tracked source:

```powershell
$repo = 'D:\DexArena-Variation'
$work = 'D:\private-sdk-build'
$runtime = 'D:\private-sdk-runtime'
$python = 'C:\path\to\python.exe'
& $python .\prepare.py --work-dir $work
.\build_windows.ps1 -WorkDir $work -Python $python -Jobs 4
& $python .\unpack_wheel.py --wheel "$work\wheels\sapien-3.0.3+dexarena.gpu1.wininterop5-cp310-cp310-win_amd64.whl" --runtime $runtime --receipt "$work\artifact.json" --source "$work\source" --build-info "$work\build_identity.json"
& $python .\run_check.py --repo-root $repo --sapien-root $runtime --artifact "$work\artifact.json" --physx-gpu-dir "$work\physx-runtime" --output "$work\acceptance" --approved-runtime --sim-backend physx_cuda --experimental-windows-cuda
```

The existing task assets must be available before `run_check.py`. Optional build arguments `-VsInstall`, `-GitBash`, `-CMake` and `-Ninja` select tools explicitly. Use `-VsInstall` if vswhere does not discover the installed C++ toolset. Compilation is capped at four jobs; CUDA and build files stay private.

Optional preparation arguments `--download-cache PATH --source-reference CHECKOUT --dependency-reference DEPS` reuse SHA-checked archives and committed Git objects while creating new working trees. `prepared_inputs.json` records source/input hashes; `build_identity.json` records measured tools and recipe hashes; `artifact.json` identifies the wheel and matching native binaries. `run_check.py` verifies actual loaded SDK/PhysX paths and SHA before and after the standard repository checker. Keep these records and the build/checker logs together.

For Linux, `python prepare.py --work-dir /path/to/new/private/build --common-only` prepares the common indexed fixes/capability and version hook. Linux compilation and runtime checks remain unverified; use upstream Linux build instructions with CUDA enabled and a distinct local suffix such as `dexarena.gpu1`.

License/notice sources are listed in `lock.json`. Preserve SAPIEN and simsense licenses, svulkan2 per-file notices, dependency notices, and NVIDIA PhysX/CUDA terms when distributing a derived SDK. Keep source checkouts, wheels, DLLs, archives, caches and runtime directories outside Git. Patch hashes use LF bytes, as specified by this directory's `.gitattributes`.
