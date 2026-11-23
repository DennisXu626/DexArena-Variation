"""Prepare and build the private PhysX 5.3.1 Linux host used by Nut & Bolt."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import struct
import subprocess
import sys
import tarfile
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
LOCK_PATH = HERE / 'lock.json'
LOCK = json.loads(LOCK_PATH.read_text(encoding='utf-8'))
PHYSX = LOCK['physx']
TARGETS = ('PhysX', 'PhysXFoundation', 'PhysXCommon', 'PhysXCooking', 'PhysXExtensions',
           'PhysXPvdSDK', 'PhysXCharacterKinematic', 'PhysXVehicle', 'PhysXVehicle2')
STAGE_LIBS = Path('bin/linux.clang/release')
CONFIG = 'PxConfig.h'
MARKER = 'dexarena_physx_native_lock_sync_patch_version'
SETTER = 'physx::Sc::BodyCore::setRigidDynamicLockFlags('


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(*argv, cwd=None, env=None):
    return subprocess.run([str(arg) for arg in argv], cwd=cwd, env=env, check=True)


def output(*argv):
    return subprocess.check_output([str(arg) for arg in argv], text=True).strip()


def write_json(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write('\n')


def file_map(directory):
    require(directory.is_dir(), f'Missing directory: {directory}')
    require(not any(p.is_symlink() for p in directory.rglob('*')), f'Symlink in {directory}')
    return {path.relative_to(directory).as_posix(): sha(path)
            for path in sorted(directory.rglob('*')) if path.is_file()}


def source_identity(source):
    files = file_map(source / 'physx')
    config = files.pop(f'include/{CONFIG}', None)
    require(config in (None, PHYSX['generated_header_sha256']), 'Wrong generated PxConfig.h')
    files['../LICENSE.md'] = sha(source / 'LICENSE.md')
    return {'file_count': len(files), 'sha256': digest(json.dumps(files, sort_keys=True).encode())}


def source_member(name):
    relative = PurePosixPath(name)
    parts = relative.parts
    require(len(parts) >= 2 and parts[0] == f"PhysX-{PHYSX['commit']}"
            and '..' not in parts and not any(':' in part or '\\' in part for part in parts),
            f'Unexpected PhysX source path: {name}')
    return PurePosixPath(*parts[1:])


def extract_source(archive, source):
    with tarfile.open(archive, 'r:gz') as bundle:
        for member in bundle:
            if member.name == f"PhysX-{PHYSX['commit']}":
                continue
            relative = source_member(member.name)
            if (relative.parts[0] != 'physx' and relative.as_posix() != 'LICENSE.md') or member.isdir():
                continue
            require(member.isfile(), f'Nonregular PhysX build input: {relative}')
            target = source.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as reader, target.open('xb') as writer:
                shutil.copyfileobj(reader, writer)


def reference_headers(archive, includes):
    with ZipFile(archive) as bundle:
        names = [p.filename for p in bundle.infolist() if p.filename.startswith('include/') and not p.is_dir()]
        expected = {name.removeprefix('include/'): digest(bundle.read(name)) for name in names}
    require(len(names) == len(expected) == PHYSX['header_count'], 'Reference header inventory differs')
    require(expected.pop(CONFIG) == PHYSX['generated_header_sha256'], 'Reference PxConfig.h differs')
    require(file_map(includes) == expected, 'Public headers differ from the official Linux host release')
    return expected


def check_gpu_abi(binary):
    with binary.open('rb') as stream:
        header = stream.read(20)
    require(header[:7] == b'\x7fELF\x02\x01\x01'
            and struct.unpack('<HH', header[16:20]) == (3, 62),
            'PhysX GPU must be a little-endian ELF64 x86-64 shared object')
    require(sha(binary) == PHYSX['gpu_sha256'], 'PhysX GPU solver SHA differs')


def require_host_symbols(symbols):
    def members(name):
        return {line.split(':', 2)[1] for line in symbols.splitlines()
                if name in line and ' T ' in line and len(line.split(':', 2)) == 3}

    anchored = members(MARKER)
    require(len(anchored) == 1 and anchored == members(SETTER)
            and 'ScBodyCore' in next(iter(anchored)), 'Native setter and marker must share the ScBodyCore object')
    return next(iter(anchored))


def prepare(work, vendor_source, host_reference, gpu_archive):
    archives = {key: sha(path) for key, path in (
        ('source_sha256', vendor_source), ('host_reference_sha256', host_reference),
        ('gpu_archive_sha256', gpu_archive))}
    require(all(value == PHYSX[key] for key, value in archives.items()), 'Locked PhysX input archive SHA differs')
    work.mkdir(parents=True, exist_ok=False)
    source = work / 'source'
    extract_source(vendor_source, source)
    physx = source / 'physx'
    headers = reference_headers(host_reference, physx / 'include')
    original = source_identity(source)
    patch = HERE / LOCK['physx_patch']
    require(sha(patch) == LOCK['physx_patch_sha256'], 'PhysX patch SHA differs')
    run('git', 'init', '--quiet', cwd=source)
    run('git', 'apply', '--check', patch, cwd=source)
    run('git', 'apply', patch, cwd=source)
    # The published Linux host build removes warning-as-error only. Keep all ABI/physics options.
    cmake = physx / 'source/compiler/cmake/linux/CMakeLists.txt'
    contents, count = re.subn(rb'-Werror(?=[ \\])', b'', cmake.read_bytes())
    require(count == 2, 'Unexpected PhysX release warning settings')
    cmake.write_bytes(contents)
    gpu = work / 'physx-runtime' / PHYSX['gpu_file']
    gpu.parent.mkdir()
    with ZipFile(gpu_archive) as bundle, gpu.open('xb') as stream:
        require(bundle.namelist() == [gpu.name], 'Unexpected files in the pinned solver archive')
        with bundle.open(gpu.name) as reader:
            shutil.copyfileobj(reader, stream)
    check_gpu_abi(gpu)
    write_json(work / 'prepared-host.json', {
        'lock_sha256': sha(LOCK_PATH), 'vendor_archives': archives, 'upstream_source': original,
        'patched_source': source_identity(source), 'physx_patch_sha256': sha(patch),
        'headers': headers, 'gpu_sha256': sha(gpu),
    })


def verify_prepared(work):
    record = json.loads((work / 'prepared-host.json').read_text(encoding='utf-8'))
    require(record['lock_sha256'] == sha(LOCK_PATH)
            and record['physx_patch_sha256'] == sha(HERE / LOCK['physx_patch'])
            and record['patched_source'] == source_identity(work / 'source'),
            'Prepared host inputs differ')
    check_gpu_abi(work / 'physx-runtime' / PHYSX['gpu_file'])
    return record


def compiler(name):
    candidate = shutil.which(name)
    require(candidate, f'Compiler missing: {name}')
    command = Path(candidate).absolute()
    target = output(command, '-dumpmachine')
    require(target.startswith('x86_64-') and 'linux' in target, f'Wrong Linux compiler target: {target}')
    return {'command': str(command), 'target': target, 'version': output(command, '--version'),
            'sha256': sha(command.resolve())}


def verify_gpu_symbols(path):
    dynamic = output('readelf', '-d', path)
    symbols = output('readelf', '--dyn-syms', '--wide', path)
    require(f"[{PHYSX['gpu_file']}]" in next((line for line in dynamic.splitlines() if '(SONAME)' in line), '')
            and 'Shared library: [libstdc++.so.6]' in dynamic
            and all(re.search(r'\bGLOBAL\s+DEFAULT\s+\d+\s+' + name + r'(?:@\S+)?$', symbols, re.M)
                    for name in ('PxCreatePhysXGpu', 'PxCreateCudaContextManager', 'PxGetSuggestedCudaDeviceOrdinal')),
            'Pinned GPU ELF loader ABI differs')


def build(work, cc, cxx, jobs):
    require(sys.platform == 'linux' and platform.machine() == 'x86_64', 'Build requires native Linux x86-64')
    prepared = verify_prepared(work)
    tools = {'cc': compiler(cc), 'cxx': compiler(cxx)}
    require(tools['cc']['target'] == tools['cxx']['target'], 'C and C++ compiler targets differ')
    gpu = work / 'physx-runtime' / PHYSX['gpu_file']
    verify_gpu_symbols(gpu)
    physx = work / 'source/physx'
    build_dir = work / 'build-host'
    build_dir.mkdir(exist_ok=False)
    products = build_dir / 'out'
    configure = [
        'cmake', '-S', physx / 'compiler/public', '-B', build_dir, '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=release', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
        f"-DCMAKE_C_COMPILER={tools['cc']['command']}", f"-DCMAKE_CXX_COMPILER={tools['cxx']['command']}",
        f'-DPHYSX_ROOT_DIR={physx}', f'-DPX_OUTPUT_LIB_DIR={products}', f'-DPX_OUTPUT_BIN_DIR={products}',
        '-DPX_OUTPUT_ARCH=x86', '-DTARGET_BUILD_PLATFORM=linux', '-DPX_GENERATE_STATIC_LIBRARIES=ON',
        '-DGPU_LIB_COPIED=1', '-DPX_BUILDSNIPPETS=OFF', '-DPX_BUILDPVDRUNTIME=OFF',
        '-DPX_GENERATE_GPU_PROJECTS=OFF', '-DPX_GENERATE_GPU_PROJECTS_ONLY=OFF',
        '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
    ]
    run(*configure)
    run('cmake', '--build', build_dir, '--target', *TARGETS, '--parallel', str(jobs))
    headers = file_map(physx / 'include')
    require(headers == {**prepared['headers'], CONFIG: PHYSX['generated_header_sha256']},
            'Generated host headers do not match the release ABI')
    libraries = []
    for name in TARGETS:
        filename = f'lib{name}_static_64.a'
        candidates = list(products.rglob(filename))
        require(len(candidates) == 1, f'Expected one freshly compiled library: {filename}')
        libraries.append(candidates[0])
    symbols = output('nm', '-A', '--defined-only', '--demangle', libraries[0])
    anchored_member = require_host_symbols(symbols)
    probe = build_dir / 'host-link-probe'
    run(tools['cxx']['command'], '-std=c++17', '-DNDEBUG', '-DPX_PHYSX_STATIC_LIB',
        '-I', physx / 'include', HERE / 'host_link_probe.cpp', '-o', probe,
        '-Wl,--start-group', *libraries, '-Wl,--end-group', '-ldl', '-pthread', '-lrt')
    run(probe, env={**os.environ, 'CUDA_VISIBLE_DEVICES': ''})
    require(prepared == verify_prepared(work), 'Source or solver changed during compilation')

    stage = work / 'physx-host'
    (stage / STAGE_LIBS).mkdir(parents=True, exist_ok=False)
    for library in libraries:
        shutil.copyfile(library, stage / STAGE_LIBS / library.name)
    shutil.copytree(physx / 'include', stage / 'include')
    shutil.copyfile(work / 'source/LICENSE.md', stage / 'LICENSE.md')
    write_json(work / 'host-stage.json', {
        'schema': 'dexarena-nut-linux-physx-host-stage-v1', 'prepared_sha256': sha(work / 'prepared-host.json'),
        'lock_sha256': sha(LOCK_PATH), 'recipe_sha256': sha(Path(__file__)),
        'physx_commit': PHYSX['commit'], 'gpu_sha256': sha(gpu), 'compiler': tools, 'files': file_map(stage),
        'anchored_member': anchored_member, 'cpu_link_probe_sha256': sha(probe),
        'cpu_probe_source_sha256': sha(HERE / 'host_link_probe.cpp'), 'cpu_probe_returncode': 0,
        'compile_commands_sha256': sha(build_dir / 'compile_commands.json'),
        'configure_argv': [str(arg) for arg in configure], 'gpu_runtime_executed': False,
    })


def verify_stage(work):
    verify_prepared(work)
    record = json.loads((work / 'host-stage.json').read_text(encoding='utf-8'))
    require(record['schema'] == 'dexarena-nut-linux-physx-host-stage-v1'
            and record['prepared_sha256'] == sha(work / 'prepared-host.json')
            and record['lock_sha256'] == sha(LOCK_PATH)
            and record['recipe_sha256'] == sha(Path(__file__))
            and record['physx_commit'] == PHYSX['commit'] and record['gpu_sha256'] == PHYSX['gpu_sha256']
            and record['cpu_probe_returncode'] == 0 and record['files'] == file_map(work / 'physx-host'),
            'Private host stage differs from its build receipt')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('prepare', 'build', 'verify'):
        command = commands.add_parser(action)
        command.add_argument('--work-dir', required=True, type=Path)
        if action == 'prepare':
            for flag in ('vendor-source', 'host-reference', 'gpu-archive'):
                command.add_argument('--' + flag, required=True, type=Path)
        if action == 'build':
            command.add_argument('--cc', required=True)
            command.add_argument('--cxx', required=True)
            command.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if args.action == 'prepare':
        prepare(work, args.vendor_source, args.host_reference, args.gpu_archive)
        print(json.dumps({'status': 'prepared', 'gpu_runtime_executed': False, 'work': str(work)}))
    elif args.action == 'build':
        require(args.jobs > 0, '--jobs must be positive')
        build(work, args.cc, args.cxx, args.jobs)
        print(json.dumps({'status': 'host-built', 'receipt': str(work / 'host-stage.json')}))
    else:
        verify_stage(work)
        print(json.dumps({'status': 'host-stage-verified', 'gpu_runtime_executed': False}))


if __name__ == '__main__':
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f'Nut Linux PhysX host: {error}')
