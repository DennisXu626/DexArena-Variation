"""Stage verified private host libraries without touching the locked SDK."""
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess

BASE = None
VENDOR = None
GPU_IDENTITY = None
DUMPBIN = None


def _configured_path(value, name, *, file=False):
    if value is None:
        raise RuntimeError(f'{name} must be injected by the clean build orchestrator')
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f'{name} must be an absolute path')
    path = path.resolve()
    if file and not path.is_file():
        raise FileNotFoundError(f'{name} tool is missing: {path}')
    return path


def gpu_dll_identities():
    """Validate the published v5 lock.runtime_physx identity, without an artifact shim."""
    if not isinstance(GPU_IDENTITY, dict) or not isinstance(GPU_IDENTITY.get('dll_sha256'), dict):
        raise RuntimeError('GPU_IDENTITY must be the published v5 lock.runtime_physx mapping')
    identities = GPU_IDENTITY['dll_sha256']
    if set(identities) != {'PhysXDevice64.dll', 'PhysXGpu_64.dll'}:
        raise ValueError('GPU_IDENTITY must name the two pinned Windows PhysX runtime DLLs')
    for name, value in identities.items():
        if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
            raise ValueError(f'Invalid GPU SHA256 identity: {name}')
    return dict(identities)


def verify_gpu_dlls():
    identities = gpu_dll_identities()
    for name, expected in identities.items():
        path = VENDOR / 'physx-runtime' / name
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f'Pinned GPU DLL identity mismatch: {name}')
    return identities


def configure():
    global BASE, VENDOR, DUMPBIN
    BASE = _configured_path(BASE, 'BASE')
    VENDOR = _configured_path(VENDOR, 'VENDOR')
    if not BASE.is_dir() or not VENDOR.is_dir():
        raise FileNotFoundError('BASE and VENDOR must already exist before staging')
    if DUMPBIN is not None:
        DUMPBIN = _configured_path(DUMPBIN, 'DUMPBIN', file=True)
    if (BASE / 'physx-stage-native-lock-v1').resolve().is_relative_to(VENDOR):
        raise ValueError('Host stage must not overlap the read-only VENDOR input')
    return verify_gpu_dlls()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    gpu_identities = configure()
    status = json.loads((BASE / 'build-status.json').read_text(encoding='utf-8'))
    if status['status'] != 'host_libraries_built_runtime_untested' or len(status['libraries']) != 9:
        raise RuntimeError('Expected a completed nine-library isolated host build')
    if status.get('native_lock_object_header_dependencies', 0) < 20:
        raise RuntimeError('Header dependency tracking was not verified')
    if sha(BASE / 'source-manifest.json') != status['source_manifest_sha256']:
        raise RuntimeError('Source manifest changed after the recorded host build; rebuild before staging')
    if status.get('gpu_dlls_to_preserve') != gpu_identities:
        raise RuntimeError('Injected GPU identity differs from the recorded host build')
    compiler = Path(status['compiler'])
    dumpbin = DUMPBIN or compiler.with_name('dumpbin.exe')
    if not dumpbin.is_file():
        raise FileNotFoundError(f'dumpbin tool is missing: {dumpbin}')
    libraries = BASE / 'host-output'
    core = next(libraries.rglob('PhysX_static_64.lib'))
    symbols = subprocess.check_output([str(dumpbin), '/nologo', '/linkermember:1', str(core)])
    symbol = b'dexarena_physx_native_lock_sync_patch_version'
    if symbol not in symbols:
        raise RuntimeError('Patched PhysX archive lacks the link-anchored capability symbol')
    if b'setRigidDynamicLockFlags@BodyCore@Sc@physx' not in symbols:
        raise RuntimeError('Out-of-line lock setter is absent from the host archive')
    (BASE / 'core-linker-symbols.txt').write_bytes(symbols)
    stage = BASE / 'physx-stage-native-lock-v1'
    if stage.exists():
        raise FileExistsError(stage)
    stage.mkdir()
    include = BASE / 'source-patched/physx/include'
    shutil.copytree(include, stage / 'include')
    shutil.copy2(BASE / 'source-upstream/LICENSE.md', stage / 'LICENSE.md')
    for rel, identity in status['libraries'].items():
        source = libraries / rel
        if source.stat().st_size != identity['bytes'] or sha(source) != identity['sha256']:
            raise RuntimeError(f'Host library identity changed: {rel}')
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if verify_gpu_dlls() != gpu_identities:
        raise RuntimeError('GPU identity changed during staging')
    files = {path.relative_to(stage).as_posix(): {'bytes': path.stat().st_size, 'sha256': sha(path)}
             for path in stage.rglob('*') if path.is_file()}
    manifest = {'scope': 'Private PhysX host build/staging only; no native load, GPU or task acceptance',
        'source_manifest_sha256': sha(BASE / 'source-manifest.json'),
        'build_status_sha256': sha(BASE / 'build-status.json'),
        'stage': str(stage), 'files': files,
        'capability_symbol': symbol.decode(), 'capability_in_linker_index': True,
        'out_of_line_lock_setter_in_linker_index': True,
        'locked_gpu_dlls_unchanged': gpu_identities,
        'gpu_runtime_version': GPU_IDENTITY.get('version'),
        'header_dependencies': status['native_lock_object_header_dependencies'],
        'status': 'staged_host_runtime_untested'}
    (BASE / 'host-stage-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': manifest['status'], 'stage': str(stage), 'host_libraries': 9,
                      'header_dependencies': manifest['header_dependencies']}))


if __name__ == '__main__':
    main()
