"""Acquire and verify the fixed PhysX host source, then apply one native backport."""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import urllib.request

BASE = None
COMMIT = '85befb639eb736bc8ec7d4a2e9726ec2ab1d0434'
URL = f'https://codeload.github.com/NVIDIA-Omniverse/PhysX/tar.gz/{COMMIT}'
VENDOR = None
PATCH0 = '8026efddef81130fb97ec3b4a51da66fab39f09d'
ARCHIVE_SHA256 = 'c9f104b5f426134d656e54c8667e3aea596f920f7e88be69a25b897b2e67d3c4'
PATCH0_FILE_SHA256 = {
    'physx/README.md': '92c650dc4e3ceee1c242ed8e9008cd3d1b95ff28db8cdc91e3accdb3a432fa51',
    'physx/source/geomutils/src/cooking/GuCookingConvexMesh.cpp': '1aacef3971d24ccb40ae19239cc9ddc6beb7b0f6401d341f123a85cae3f4ea4e',
}
CAPABILITY = ('extern "C" unsigned dexarena_physx_native_lock_sync_patch_version()\n'
              '{\n\treturn 1;\n}\n\n')


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


def configure():
    global BASE, VENDOR
    BASE = _configured_path(BASE, 'BASE')
    VENDOR = _configured_path(VENDOR, 'VENDOR')
    if not (VENDOR / 'deps/physx5-src/include').is_dir():
        raise FileNotFoundError('VENDOR must be a prepared clean sdk-work with deps/physx5-src/include')
    for name in ('archives', 'source-upstream', 'source-patched', 'source-patch0-reference'):
        if (BASE / name).resolve().is_relative_to(VENDOR):
            raise ValueError('PhysX preparation output must not overlap the read-only VENDOR input')
    BASE.mkdir(parents=True, exist_ok=True)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request_json(url: str):
    request = urllib.request.Request(url, headers={'User-Agent': 'DexArena-private-native-backport'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def inside(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(BASE.resolve()):
        raise ValueError(f'Path outside exclusive investigation directory: {path}')
    return resolved


def main():
    configure()
    archive_dir = inside(BASE / 'archives')
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f'PhysX-{COMMIT}.tar.gz'
    if not archive.exists():
        request = urllib.request.Request(URL, headers={'User-Agent': 'DexArena-private-native-backport'})
        partial = inside(archive.with_suffix('.partial'))
        with urllib.request.urlopen(request, timeout=90) as response, partial.open('wb') as stream:
            shutil.copyfileobj(response, stream, 1024 * 1024)
        partial.replace(archive)
    if sha(archive.read_bytes()) != ARCHIVE_SHA256:
        raise RuntimeError('Fixed official PhysX source archive SHA256 mismatch')
    tree = request_json(f'https://api.github.com/repos/NVIDIA-Omniverse/PhysX/git/trees/{COMMIT}?recursive=1')
    if tree['truncated']:
        raise RuntimeError('Official file tree was truncated')
    expected = {item['path']: item['sha'] for item in tree['tree'] if item['type'] == 'blob'}
    original = inside(BASE / 'source-upstream')
    original.mkdir(exist_ok=True)
    source_files = {}
    with tarfile.open(archive, 'r:gz') as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts
            rel = PurePosixPath(*parts[1:])
            if rel.as_posix() != 'LICENSE.md' and (not rel.parts or rel.parts[0] != 'physx'):
                continue
            if any(part in ('..', '') for part in rel.parts):
                raise RuntimeError('Unsafe archive member')
            data = bundle.extractfile(member).read()
            blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if expected.get(rel.as_posix()) != blob:
                raise RuntimeError(f'Official Git blob identity mismatch: {rel}')
            destination = inside(original.joinpath(*rel.parts))
            if destination.exists():
                if destination.read_bytes() != data:
                    raise RuntimeError(f'Existing upstream source was modified: {rel}')
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            source_files[rel.as_posix()] = {'size': len(data), 'sha256': sha(data), 'git_blob_sha1': blob}
    patched = inside(BASE / 'source-patched')
    if not patched.exists():
        shutil.copytree(original, patched)
    header = Path('physx/source/simulationcontroller/include/ScBodyCore.h')
    implementation = Path('physx/source/simulationcontroller/src/ScBodyCore.cpp')
    changes = {}
    for rel in (header, implementation):
        before = (original / rel).read_text(encoding='utf-8')
        if rel == header:
            expression = (r'(?m)^[ \t]*PX_FORCE_INLINE void[ \t]+setRigidDynamicLockFlags'
                          r'\(PxRigidDynamicLockFlags flags\) \{ mCore.lockFlags = flags; \}$')
            after, count = re.subn(expression,
                                  '\t\t\t\t\t\tvoid\t\t\t\tsetRigidDynamicLockFlags(PxRigidDynamicLockFlags flags);', before)
            if count != 1:
                raise RuntimeError('Expected exactly one original inline lock setter')
        else:
            anchor = 'void Sc::BodyCore::setBody2World(const PxTransform& p)'
            if before.count(anchor) != 1:
                raise RuntimeError('Unexpected original implementation layout')
            addition = ('void Sc::BodyCore::setRigidDynamicLockFlags(PxRigidDynamicLockFlags flags)\n'
                        '{\n\tmCore.lockFlags = flags;\n\tupdateBodySim(*this);\n}\n\n')
            after = before.replace(anchor, addition + anchor, 1)
        target = patched / rel
        current = target.read_text(encoding='utf-8')
        capable_after = after
        if rel == implementation:
            capable_after = after.replace('void Sc::BodyCore::setRigidDynamicLockFlags(PxRigidDynamicLockFlags flags)',
                                          CAPABILITY + 'void Sc::BodyCore::setRigidDynamicLockFlags(PxRigidDynamicLockFlags flags)', 1)
        if current not in (before, after, capable_after):
            raise RuntimeError(f'Existing patched source has unrelated changes: {rel}')
        target.write_text(after, encoding='utf-8', newline='\n')
        changes[rel.as_posix()] = {'upstream_sha256': sha(before.encode()), 'patched_sha256': sha(after.encode())}
    patch = ''.join(''.join(difflib.unified_diff(
        (original / rel).read_text(encoding='utf-8').splitlines(True),
        (patched / rel).read_text(encoding='utf-8').splitlines(True),
        fromfile='a/' + rel.as_posix(), tofile='b/' + rel.as_posix())) for rel in (header, implementation))
    (BASE / '0001-physx531-runtime-lock-sync.patch').write_text(patch, encoding='utf-8', newline='\n')
    # Keep the shipping patch0 cooking workaround; do not silently revert it.
    patch0_files = {}
    for rel in ('physx/README.md', 'physx/source/geomutils/src/cooking/GuCookingConvexMesh.cpp'):
        url = f'https://raw.githubusercontent.com/sapien-sim/PhysX/{PATCH0}/{rel}'
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if sha(data) != PATCH0_FILE_SHA256[rel]:
            raise RuntimeError(f'Fixed patch0 reference SHA256 mismatch: {rel}')
        reference = inside(BASE / 'source-patch0-reference' / rel)
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_bytes(data)
        target = patched / rel
        if target.read_bytes() not in ((original / rel).read_bytes(), data):
            raise RuntimeError(f'Unrelated changes in patch0-preserved source: {rel}')
        target.write_bytes(data)
        patch0_files[rel] = {'source_url': url, 'sha256': sha(data)}
    # Put the capability in the patched PhysX object itself. A SAPIEN overlay
    # forwarding to this symbol cannot link against an unpatched host library.
    implementation_path = patched / implementation
    native_text = implementation_path.read_text(encoding='utf-8')
    native_anchor = 'void Sc::BodyCore::setRigidDynamicLockFlags(PxRigidDynamicLockFlags flags)'
    capability_text = native_text.replace(native_anchor, CAPABILITY + native_anchor, 1)
    implementation_path.write_text(capability_text, encoding='utf-8', newline='\n')
    capability_diff = ''.join(difflib.unified_diff(native_text.splitlines(True), capability_text.splitlines(True),
                                               fromfile='a/' + implementation.as_posix(),
                                               tofile='b/' + implementation.as_posix()))
    (BASE / '0002-physx-native-lock-capability.patch').write_text(capability_diff, encoding='utf-8', newline='\n')
    # Public CMake copies unrelated example DLLs even when snippets are OFF.
    # Honour its explicit copy switch in this private host-only build; leave
    # PUBLIC_RELEASE and all physics compilation definitions unchanged.
    windows_cmake = Path('physx/source/compiler/cmake/windows/CMakeLists.txt')
    cmake_before = (original / windows_cmake).read_text(encoding='utf-8')
    cmake_after = cmake_before.replace('IF(PX_COPY_EXTERNAL_DLL OR PUBLIC_RELEASE)', 'IF(PX_COPY_EXTERNAL_DLL)', 1)
    if cmake_before == cmake_after:
        raise RuntimeError('Unexpected external DLL copy guard')
    (patched / windows_cmake).write_text(cmake_after, encoding='utf-8', newline='\n')
    cmake_diff = ''.join(difflib.unified_diff(cmake_before.splitlines(True), cmake_after.splitlines(True),
                                            fromfile='a/' + windows_cmake.as_posix(),
                                            tofile='b/' + windows_cmake.as_posix()))
    (BASE / '0003-host-only-disable-example-dll-copy.patch').write_text(cmake_diff, encoding='utf-8', newline='\n')
    differences = []
    local_include = VENDOR / 'deps/physx5-src/include'
    for path in local_include.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(local_include)
        counterpart = original / 'physx/include' / rel
        if not counterpart.exists():
            differences.append({'header': rel.as_posix(), 'status': 'not_in_official_source'})
        elif path.read_bytes().replace(b'\r\n', b'\n') != counterpart.read_bytes().replace(b'\r\n', b'\n'):
            differences.append({'header': rel.as_posix(), 'status': 'content_differs'})
    manifest = {
        'scope': 'private build preparation only; no GPU or task acceptance',
        'upstream_url': URL, 'commit': COMMIT, 'tree': tree['sha'],
        'archive_sha256': sha(archive.read_bytes()), 'archive_bytes': archive.stat().st_size,
        'selected_files': source_files, 'patch': changes,
        'patch_sha256': sha(patch.encode()),
        'patch0_commit': PATCH0, 'preserved_patch0_files': patch0_files,
        'capability_patch_sha256': sha(capability_diff.encode()),
        'build_only_patch_sha256': sha(cmake_diff.encode()),
        'final_runtime_cpp_sha256': sha(implementation_path.read_bytes()),
        'backport_reference': 'https://github.com/NVIDIA-Omniverse/PhysX/blob/7d6f6ac8b83e1610bdf715f1f2f1d6b718aee586/physx/source/simulationcontroller/src/ScBodyCore.cpp#L472',
        'local_vendor_header_differences_after_LF_normalization': differences,
        'locked_vendor_untouched': True,
    }
    (BASE / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'source': str(patched), 'commit': COMMIT, 'archive_sha256': manifest['archive_sha256'],
                      'archive_bytes': manifest['archive_bytes'], 'verified_source_files': len(source_files),
                      'patch_files': list(changes), 'header_differences': differences}), flush=True)


if __name__ == '__main__':
    main()
