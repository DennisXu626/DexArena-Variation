"""Full clean-source v6 SDK recipe; never imports or runs the resulting SDK."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PHYSX_SOURCE_COMMIT = '85befb639eb736bc8ec7d4a2e9726ec2ab1d0434'
PHYSX_PATCH0_COMMIT = '8026efddef81130fb97ec3b4a51da66fab39f09d'
PHYSX_ARCHIVE_SHA256 = 'c9f104b5f426134d656e54c8667e3aea596f920f7e88be69a25b897b2e67d3c4'
REVIEWED_LOCK_PATCH_SHA256 = '762a5e3aa9673785ec3ef49a978e7dcbb5ba3ef9e440172ee43f85523b015fea'
REVIEWED_CAPABILITY_PATCH_SHA256 = 'b057c3f91158469539ba50f79234c5543a34890ff8da1573688e1612d5813342'
PATCH0_FILE_SHA256 = {
    'physx/README.md': '92c650dc4e3ceee1c242ed8e9008cd3d1b95ff28db8cdc91e3accdb3a432fa51',
    'physx/source/geomutils/src/cooking/GuCookingConvexMesh.cpp': '1aacef3971d24ccb40ae19239cc9ddc6beb7b0f6401d341f123a85cae3f4ea4e',
}
HOST_LIBRARY_NAMES = {
    'PhysXCharacterKinematic_static_64.lib', 'PhysXCommon_static_64.lib',
    'PhysXCooking_static_64.lib', 'PhysXExtensions_static_64.lib',
    'PhysXFoundation_static_64.lib', 'PhysXPvdSDK_static_64.lib',
    'PhysXVehicle2_static_64.lib', 'PhysXVehicle_static_64.lib', 'PhysX_static_64.lib',
}
LOCKED_HOST_TOOLSET = '14.43.34808'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def executable(value):
    found = shutil.which(value)
    if found is None:
        raise FileNotFoundError(value)
    return Path(found).resolve()


def run(command, cwd, log_name):
    log = cwd / log_name
    print(json.dumps({'command': [str(item) for item in command], 'log': str(log)}), flush=True)
    with log.open('wb') as stream:
        subprocess.run([str(item) for item in command], cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def resolve_vs_install(explicit):
    if explicit:
        candidates = [explicit.resolve()]
    else:
        vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        candidates = []
        if vswhere.is_file():
            for query in (
                ['-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64'],
                ['-all', '-products', '*'],
            ):
                try:
                    value = subprocess.check_output([str(vswhere), *query, '-property', 'installationPath'], text=True)
                    candidates.extend(Path(line.strip()).resolve() for line in value.splitlines() if line.strip())
                except subprocess.CalledProcessError:
                    pass
        if os.environ.get('VSINSTALLDIR'):
            candidates.append(Path(os.environ['VSINSTALLDIR']).resolve())
        for program_files in {os.environ.get('ProgramFiles', 'C:/Program Files'),
                              os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')}:
            root = Path(program_files) / 'Microsoft Visual Studio'
            for developer_command in sorted(root.glob('*/*/Common7/Tools/VsDevCmd.bat'), reverse=True):
                candidates.append(developer_command.parents[2].resolve())
    for install in dict.fromkeys(candidates):
        if ((install / 'Common7/Tools/VsDevCmd.bat').is_file()
                and (install / f'VC/Tools/MSVC/{LOCKED_HOST_TOOLSET}/bin/Hostx64/x64/cl.exe').is_file()):
            return install
    raise RuntimeError(f'No Visual Studio installation has VsDevCmd and locked MSVC {LOCKED_HOST_TOOLSET}; pass --vs-install')


def archive_native_lock_definitions(path):
    """Read actual COFF external definitions, not just diagnostic marker strings."""
    raw = path.read_bytes()
    require(raw[:8] == b'!<arch>\n', 'PhysX core is not a COFF static archive')
    offset, long_names = 8, b''
    definitions = {'capability': [], 'out_of_line_setter': []}
    while offset + 60 <= len(raw):
        header = raw[offset:offset + 60]
        size = int(header[48:58])
        name = header[:16].decode('ascii').strip()
        body = raw[offset + 60:offset + 60 + size]
        if name == '//':
            long_names = body
        elif name.startswith('/') and name[1:].isdigit():
            name = long_names[int(name[1:]):].split(b'\0', 1)[0].split(b'\n', 1)[0].decode('utf-8', errors='replace').rstrip('/')
        if name not in ('/', '//') and len(body) >= 20:
            big = body[:4] == b'\0\0\xff\xff'
            if big and len(body) < 56:
                offset += 60 + size + size % 2
                continue
            pointer, count = struct.unpack_from('<II', body, 48 if big else 8)
            stride = 20 if big else 18
            strings = pointer + count * stride
            if pointer and count and strings + 4 <= len(body):
                index = 0
                while index < count:
                    symbol = body[pointer + index * stride:pointer + (index + 1) * stride]
                    if symbol[:4] == b'\0' * 4:
                        start = strings + struct.unpack_from('<I', symbol, 4)[0]
                        value = body[start:].split(b'\0', 1)[0]
                    else:
                        value = symbol[:8].split(b'\0', 1)[0]
                    section = struct.unpack_from('<i' if big else '<h', symbol, 12)[0]
                    storage, auxiliary = symbol[18 if big else 16], symbol[19 if big else 17]
                    if storage == 2 and section > 0:
                        if value == b'dexarena_physx_native_lock_sync_patch_version':
                            definitions['capability'].append(name)
                        elif b'setRigidDynamicLockFlags@BodyCore@Sc@physx' in value:
                            definitions['out_of_line_setter'].append(name)
                    index += 1 + auxiliary
        offset += 60 + size + size % 2
    require(len(definitions['capability']) == 1 and len(definitions['out_of_line_setter']) == 1,
            'Expected exactly one real capability and out-of-line setter definition in PhysX core')
    return definitions


def verify_host_stage(manifest_path, gpu_identity, reused):
    """Verify prebuilt dependency identity without claiming this invocation built it."""
    manifest_path = manifest_path.resolve(strict=True)
    provenance = manifest_path.parent
    source_path, build_path = provenance / 'source-manifest.json', provenance / 'build-status.json'
    stage_record = json.loads(manifest_path.read_text(encoding='utf-8'))
    require(sha(source_path) == stage_record['source_manifest_sha256'], 'Host source-manifest SHA chain differs')
    require(sha(build_path) == stage_record['build_status_sha256'], 'Host build-status SHA chain differs')
    source = json.loads(source_path.read_text(encoding='utf-8'))
    build = json.loads(build_path.read_text(encoding='utf-8'))
    require(build['source_manifest_sha256'] == stage_record['source_manifest_sha256'], 'Host build/source chain differs')
    require(source['commit'] == PHYSX_SOURCE_COMMIT and source['tree'] == PHYSX_SOURCE_COMMIT,
            'Host does not identify the fixed PhysX 5.3.1 source')
    require(source['archive_sha256'] == PHYSX_ARCHIVE_SHA256 and source['patch0_commit'] == PHYSX_PATCH0_COMMIT,
            'Host official archive/patch0 identity differs')
    require(source['patch_sha256'] == REVIEWED_LOCK_PATCH_SHA256
            and source['capability_patch_sha256'] == REVIEWED_CAPABILITY_PATCH_SHA256,
            'Host native lock/capability patch differs from the reviewed implementation')
    require({name: item['sha256'] for name, item in source['preserved_patch0_files'].items()} == PATCH0_FILE_SHA256,
            'Host does not preserve the reviewed patch0 files')
    require(build['status'] == 'host_libraries_built_runtime_untested'
            and stage_record['status'] == 'staged_host_runtime_untested', 'Host build/stage is incomplete')
    require(0 < build['max_compile_jobs'] <= 2, 'Host build exceeded the two-job limit')
    require(build['toolset'] == LOCKED_HOST_TOOLSET, 'Host build toolset differs from the locked platform')
    require(build.get('native_lock_object_header_dependencies', 0) >= 20
            and stage_record.get('header_dependencies') == build['native_lock_object_header_dependencies'],
            'Host header-dependency evidence is missing or inconsistent')
    expected_gpu = gpu_identity['dll_sha256']
    require(stage_record['locked_gpu_dlls_unchanged'] == expected_gpu
            and build['gpu_dlls_to_preserve'] == expected_gpu, 'Host pinned GPU identity differs')
    require(stage_record['capability_symbol'] == 'dexarena_physx_native_lock_sync_patch_version'
            and stage_record['capability_in_linker_index'] is True
            and stage_record['out_of_line_lock_setter_in_linker_index'] is True,
            'Host native capability/out-of-line setter record is absent')
    stage = Path(stage_record['stage']).resolve(strict=True)
    require(stage.is_dir(), 'Host stage path is not a directory')
    files = stage_record['files']
    require(len(files) == 375, f'Expected 375 reviewed host stage files, got {len(files)}')
    actual = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()}
    require(actual == set(files), 'Host stage has missing or unrecorded files')
    for relative, item in files.items():
        path = (stage / relative).resolve()
        require(path.is_relative_to(stage), 'Host stage file escapes its root')
        require(path.stat().st_size == item['bytes'] and sha(path) == item['sha256'],
                f'Host stage content differs: {relative}')
    libraries = build['libraries']
    require(len(libraries) == 9 and {Path(name).name for name in libraries} == HOST_LIBRARY_NAMES,
            'Expected exactly the nine reviewed PhysX host libraries')
    for relative, item in libraries.items():
        require(files.get(relative) == item, f'Host build/stage library identity differs: {relative}')
    core = stage / 'bin/win.x86_64.vc143.mt/release/PhysX_static_64.lib'
    definitions = archive_native_lock_definitions(core)
    # Verify the recorded source bodies when choosing this explicitly reviewed dependency.
    source_root = Path(build['source'])
    if not source_root.is_dir():
        source_root = provenance / 'source-patched/physx'
    header = source_root / 'source/simulationcontroller/include/ScBodyCore.h'
    cpp = source_root / 'source/simulationcontroller/src/ScBodyCore.cpp'
    require(sha(header) == source['patch']['physx/source/simulationcontroller/include/ScBodyCore.h']['patched_sha256'],
            'Host out-of-line header source differs')
    require(sha(cpp) == source['final_runtime_cpp_sha256'], 'Host final setter/capability source differs')
    body = cpp.read_text(encoding='utf-8')
    require('mCore.lockFlags = flags;' in body and 'updateBodySim(*this);' in body
            and 'extern "C" unsigned dexarena_physx_native_lock_sync_patch_version()' in body,
            'Host setter/capability source markers are missing')
    for relative, digest in PATCH0_FILE_SHA256.items():
        require(sha(source_root.parent / relative) == digest, f'Host preserved patch0 source differs: {relative}')
    dependency = {
        'schema': 'dexarena-clean-host-dependency-v1', 'reused': bool(reused), 'dependency_reused': bool(reused),
        'provenance_root': str(provenance), 'physx_stage': {'path': str(stage)}, 'hoststage': str(stage),
        'stage_manifest': {'path': str(manifest_path), 'sha256': sha(manifest_path)},
        'source_manifest': {'path': str(source_path), 'sha256': sha(source_path)},
        'build_status': {'path': str(build_path), 'sha256': sha(build_path)},
        'checks': {'stage_files_verified': len(files), 'host_libraries_verified': len(libraries),
                   'gpu_lock_identity_matches': True, 'fixed_source_and_patch0_match': True,
                   'source_body_identity_matches': True, 'coff_native_definitions': definitions},
        'scope': 'Verified PhysX host dependency identity only; no new native load/GPU acceptance',
    }
    return dependency, source, build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', required=True, type=Path, help='Checkout containing the published, locked v5 SDK recipe')
    parser.add_argument('--work-dir', required=True, type=Path, help='New private source/build/runtime root')
    parser.add_argument('--python', required=True, type=Path, help='Locked CPython 3.10.22 x64 interpreter')
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--ninja', default='ninja')
    parser.add_argument('--powershell', default='pwsh')
    parser.add_argument('--vs-install', type=Path)
    parser.add_argument('--git-bash', type=Path)
    parser.add_argument('--download-cache', type=Path)
    parser.add_argument('--source-reference', type=Path, help='Read committed Git objects only; never copy working files/build objects')
    parser.add_argument('--dependency-reference', type=Path, help='Read NAME-src committed Git objects only')
    parser.add_argument('--host-stage-manifest', type=Path, help='Explicitly reuse a fully verified nine-library PhysX host dependency')
    parser.add_argument('--prepare-only', action='store_true', help='Create/verify the complete recipe bundle only; no fetching or compiling')
    parser.add_argument('--resume', action='store_true', help='Resume an existing private work root after verifying its preparation')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This recipe is Windows-only')
    work = args.work_dir.resolve()
    repo = args.repo_root.resolve()
    if work == repo or work.is_relative_to(repo / 'tools'):
        parser.error('Use a private output root, outside the published recipe source')
    if work.exists() and not args.resume:
        parser.error('Work root already exists; choose a new root or explicitly --resume')
    if not (work / 'recipe-v6').exists():
        subprocess.run([str(args.python), '-B', str(HERE / 'prepare_clean_recipe.py'),
                        '--repo-root', str(repo), '--work-dir', str(work), '--bundle-root', str(HERE)], check=True)
    recipe = work / 'recipe-v6'
    recipe_manifest = json.loads((recipe / 'clean-recipe-manifest.json').read_text(encoding='utf-8'))
    for relative, expected in recipe_manifest['output_recipe_files_sha256'].items():
        candidate = (recipe / relative).resolve()
        if not candidate.is_relative_to(recipe.resolve()) or sha(candidate) != expected:
            raise RuntimeError(f'Prepared recipe identity mismatch: {relative}')
    lock = json.loads((recipe / 'lock.json').read_text(encoding='utf-8'))
    host_context = None
    if args.host_stage_manifest:
        host_context = verify_host_stage(args.host_stage_manifest, lock['runtime_physx'], reused=True)
        write_json(work / 'host-dependency.json', host_context[0])
    mode = ('clean_sapien_full_source_with_verified_prebuilt_physx_host'
            if host_context else 'clean_full_source')
    status = {'schema': 'dexarena-native-lock-clean-build-v1', 'status': 'recipe_prepared',
        'build_mode': mode, 'version': lock['local_version'], 'max_compile_jobs': 2,
        'native_objects_reused_from_v5': 0, 'pybind_objects_reused_from_v5': 0,
        'physx_host_dependency_reused': host_context is not None,
        'v5_recipe_source': str(repo / 'tools/variation/sapien_sdk'),
        'recipe_lock_sha256': sha(recipe / 'lock.json'),
        'public_bundle': {p.relative_to(HERE).as_posix(): sha(p) for p in HERE.rglob('*')
                          if p.is_file() and '__pycache__' not in p.parts},
        'native_runtime_or_gpu_run': False}
    if host_context:
        status['host_dependency'] = {'path': str(work / 'host-dependency.json'),
                                     'sha256': sha(work / 'host-dependency.json')}
    write_json(work / 'clean-build-status.json', status)
    if args.prepare_only:
        print(json.dumps({'status': status['status'], 'work_dir': str(work), 'not_run': 'source fetch, compilation, SDK load or GPU'}))
        return
    cmake, ninja, powershell = executable(args.cmake), executable(args.ninja), executable(args.powershell)
    sdk_work = work / 'sapien-clean'
    prepare = [args.python, '-B', recipe / 'prepare.py']
    if (sdk_work / 'prepared_inputs.json').exists():
        prepare += ['--verify-work-dir', sdk_work]
    else:
        prepare += ['--work-dir', sdk_work]
        if args.download_cache:
            prepare += ['--download-cache', args.download_cache.resolve()]
        if args.source_reference:
            prepare += ['--source-reference', args.source_reference.resolve()]
        if args.dependency_reference:
            prepare += ['--dependency-reference', args.dependency_reference.resolve()]
    try:
        run(prepare, work, 'prepare-sdk.log')
        # Both host branches need the same resolved VS installation for SAPIEN.
        vs_install = resolve_vs_install(args.vs_install)
        if host_context is None:
            host_work = work / 'physx-host-clean'
            host_work.mkdir(exist_ok=True)
            upstream = load('native_lock_clean_source', HERE / 'host/prepare_physx.py')
            upstream.BASE, upstream.VENDOR = host_work, sdk_work
            upstream.main()
            builder = load('native_lock_clean_host', HERE / 'host/build_host.py')
            builder.BASE, builder.VENDOR = host_work, sdk_work
            builder.CMAKE, builder.NINJA = cmake, ninja
            builder.GPU_IDENTITY = lock['runtime_physx']
            builder.VSDEV = vs_install / 'Common7/Tools/VsDevCmd.bat'
            builder.main(['--all-host-libs'])
            staging = load('native_lock_clean_stage', HERE / 'host/stage_host.py')
            staging.BASE, staging.VENDOR = host_work, sdk_work
            staging.GPU_IDENTITY = lock['runtime_physx']
            if not (host_work / 'physx-stage-native-lock-v1').exists():
                staging.main()
            host_context = verify_host_stage(host_work / 'host-stage-manifest.json', lock['runtime_physx'], reused=False)
            write_json(work / 'host-dependency.json', host_context[0])
        dependency, host_source, host_build = host_context
        host_stage = Path(dependency['physx_stage']['path'])
        status['host_dependency'] = {'path': str(work / 'host-dependency.json'),
                                     'sha256': sha(work / 'host-dependency.json')}
        command = [powershell, '-NoProfile', '-File', recipe / 'build_windows.ps1',
            '-WorkDir', sdk_work, '-Python', args.python.resolve(), '-CMake', cmake, '-Ninja', ninja,
            '-VsInstall', vs_install, '-PhysXStage', host_stage, '-Jobs', '2']
        if args.git_bash:
            command += ['-GitBash', args.git_bash.resolve()]
        run(command, work, 'build-sdk.log')
        wheel = sdk_work / 'wheels' / f'sapien-{lock["local_version"]}-cp310-cp310-win_amd64.whl'
        runtime, artifact = work / 'runtime', work / 'artifact.json'
        run([args.python, '-B', recipe / 'unpack_wheel.py', '--wheel', wheel, '--runtime', runtime,
             '--receipt', artifact, '--source', sdk_work / 'source', '--build-info', sdk_work / 'build_identity.json'],
            work, 'package-sdk.log')
        receipt = json.loads(artifact.read_text(encoding='utf-8'))
        gpu_runtime = work / 'physx-runtime'
        gpu_runtime.mkdir(exist_ok=False)
        for name, expected in lock['runtime_physx']['dll_sha256'].items():
            original = sdk_work / 'physx-runtime' / name
            if sha(original) != expected:
                raise RuntimeError(f'Prepared GPU runtime identity mismatch: {name}')
            shutil.copyfile(original, gpu_runtime / name)
            if sha(gpu_runtime / name) != expected:
                raise RuntimeError(f'Packaged GPU runtime identity mismatch: {name}')
        receipt['host_physx'] = {'source': host_source, 'build': host_build,
            'source_manifest_sha256': dependency['source_manifest']['sha256'],
            'stage_manifest_sha256': dependency['stage_manifest']['sha256'],
            'build_status_sha256': dependency['build_status']['sha256'],
            'dependency_reused': dependency['reused'], 'provenance_root': dependency['provenance_root'],
            'stage': str(host_stage), 'provenance': dependency}
        receipt['host_dependency'] = {'path': str(work / 'host-dependency.json'),
                                      'sha256': sha(work / 'host-dependency.json')}
        receipt['build_mode'] = mode
        receipt['incremental_link'] = {'mode': mode, 'native_objects_reused_from_v5': 0,
            'pybind_objects_reused_from_v5': 0, 'clean_full_build_executed': True,
            'clean_full_build_scope': 'SAPIEN native and pybind; PhysX dependency provenance is recorded separately',
            'physx_host_dependency_reused': dependency['reused']}
        receipt['capabilities'] = {'native_gpu_lock_sync_patch_version': {'expected': 1,
            'physx_link_symbol': 'dexarena_physx_native_lock_sync_patch_version', 'runtime_checked': False},
            'indexed_gpu_apply_patch_version': {'expected': 1, 'runtime_checked': False}}
        receipt['acceptance'] = ('Clean-source SAPIEN native/pybind CPU build/package only; '
            + ('verified prebuilt PhysX host dependency reused. ' if dependency['reused'] else 'PhysX host built from source. ')
            + 'Native load, actual GPU physics/RGB and family acceptance remain untested.')
        write_json(artifact, receipt)
        status.update(status='clean_source_sdk_built_runtime_untested', artifact=str(artifact),
                      artifact_sha256=sha(artifact), runtime=str(runtime), physx_runtime=str(gpu_runtime),
                      wheel=str(wheel), wheel_sha256=sha(wheel))
    except Exception as error:
        status.update(status='failed', error_type=type(error).__name__, error=str(error))
        write_json(work / 'clean-build-status.json', status)
        raise
    write_json(work / 'clean-build-status.json', status)
    print(json.dumps(status))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    main()
