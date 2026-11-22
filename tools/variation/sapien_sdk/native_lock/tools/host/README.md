# Clean Windows PhysX host helpers

These importable modules prepare, build and stage the fixed PhysX 5.3.1 native lock-sync backport. Import has no build, download, compiler or GPU side effects. The outer clean orchestrator must inject absolute paths and then call the desired main function; no helper main was run while authoring this package.

## Injection contract

- All three: `BASE` is a fresh host-work directory; `VENDOR` is the newly prepared clean sdk-work, never the locked v5 vendor. Both default to `None`.
- `prepare_physx`: `VENDOR/deps/physx5-src/include` supplies the read-only reference headers. Official source commit and archive SHA256, patch0 commit and both preserved source SHA256 values are fixed in the module. Preparation keeps the native setter backport, link-anchored C capability and build-only external-DLL-copy guard.
- `build_host`: inject `CMAKE`, `NINJA`, `VSDEV` as absolute tool file paths, plus `GPU_IDENTITY = published_v5_lock['runtime_physx']`. `EXPECTED_TOOLSET` defaults to `14.43.34808`; `VCVARS_VERSION` defaults to `14.43`. Call `main(['--all-host-libs'])` for the nine-library build. The optional configure-only and explicit generated-object rebuild flags are retained.
- `stage_host`: inject the same `GPU_IDENTITY`; optionally inject an absolute `DUMPBIN` path, otherwise it is resolved beside the recorded compiler. Call `main()` only after the nine-library build.

The GPU identity is the full published mapping containing `version`, `dll_sha256` and any source/archive metadata. Exactly the pinned `PhysXDevice64.dll` and `PhysXGpu_64.dll` hashes are checked against actual files under `VENDOR/physx-runtime`. No synthetic artifact.json is read or generated to satisfy this contract.

## Invariants

Writes stay under injected BASE. The locked v5 SDK is not an input path default. Two compile jobs remain enforced. The compiler showIncludes output is captured as raw bytes and retained in the plan. At function execution, `build_host` loads the sibling `../write_msvc_prefix.py` without calling its main, and uses its strict UTF-8 / Windows ANSI fallback decoder and UTF-8 CMake payload writer. Raw CP936 is not written directly into CMake input. The plan records the raw prefix, decoded encoding, UTF-8 prefix and payload SHA, common helper SHA and an ANSI projection marked as a candidate rather than actual Ninja output evidence. Actual Ninja output encoding must be checked separately; the native lock object must have at least 20 recorded header dependencies. The source-manifest hash must remain stable through build and must match build-status before staging. Stage verifies nine library identities, the link-anchored C marker and out-of-line setter, plus actual pinned GPU DLL hashes. Runtime/GPU/family acceptance remains separate.

Import or AST validation does not prove configuration, compilation, linking, runtime or GPU acceptance. The original private scripts are preserved outside this helper package; host-helper-manifest.json records their exact source SHA256 and the reviewed adaptations.
