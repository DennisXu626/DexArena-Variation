"""Build the isolated PhysX 5.3.1 host library with at most two compile jobs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time

BASE = None
CMAKE = None
NINJA = None
VSDEV = None
VENDOR = None
GPU_IDENTITY = None
EXPECTED_TOOLSET = '14.43.34808'
VCVARS_VERSION = '14.43'


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
    global BASE, VENDOR, CMAKE, NINJA, VSDEV
    BASE = _configured_path(BASE, 'BASE')
    VENDOR = _configured_path(VENDOR, 'VENDOR')
    CMAKE = _configured_path(CMAKE, 'CMAKE', file=True)
    NINJA = _configured_path(NINJA, 'NINJA', file=True)
    VSDEV = _configured_path(VSDEV, 'VSDEV', file=True)
    if not VENDOR.is_dir():
        raise FileNotFoundError('VENDOR must be the prepared clean sdk-work')
    if (BASE / 'host-output').resolve().is_relative_to(VENDOR):
        raise ValueError('Host build output must not overlap the read-only VENDOR input')
    identities = verify_gpu_dlls()
    BASE.mkdir(parents=True, exist_ok=True)
    return identities


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def msvc_environment():
    helper = BASE / 'compiler-env.cmd'
    helper.write_text('@echo off\ncall "' + str(VSDEV) + '" -host_arch=x64 -arch=x64 -vcvars_ver=' + VCVARS_VERSION + ' >nul\n'
                      'if errorlevel 1 exit /b %errorlevel%\nset\n', encoding='utf-8', newline='\r\n')
    command = [os.environ.get('ComSpec', 'cmd.exe'), '/d', '/c', 'call', str(helper)]
    process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if process.returncode:
        raise RuntimeError('VsDevCmd failed: ' + process.stderr[-1000:])
    environment = os.environ.copy()
    for line in process.stdout.splitlines():
        if '=' in line and not line.startswith('='):
            key, value = line.split('=', 1)
            environment[key] = value
    if environment.get('VCToolsVersion', '').rstrip('\\') != EXPECTED_TOOLSET:
        raise RuntimeError('MSVC toolset differs from the v5 build identity')
    compiler = Path(environment['VCToolsInstallDir']) / 'bin/Hostx64/x64/cl.exe'
    environment['PATH'] = os.pathsep.join((str(compiler.parent), str(CMAKE.parent), str(NINJA.parent), environment['PATH']))
    environment['VSLANG'] = '1033'
    environment['CMAKE_BUILD_PARALLEL_LEVEL'] = '2'
    environment['CMAKE_GENERATOR'] = 'Ninja'
    temporary = BASE / 'tmp'
    temporary.mkdir(exist_ok=True)
    environment['TEMP'] = environment['TMP'] = str(temporary)
    return environment, compiler


def run_logged(name, command, environment):
    log = BASE / f'{name}.log'
    print(json.dumps({'starting': name, 'command': command, 'log': str(log)}), flush=True)
    with log.open('wb') as stream:
        process = subprocess.Popen(command, cwd=BASE, env=environment, stdout=stream, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        while process.poll() is None:
            time.sleep(2)
    if process.returncode:
        lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
        print('\n'.join(lines[-35:]), flush=True)
        raise RuntimeError(f'{name} failed with exit {process.returncode}; see {log}')
    print(json.dumps({'completed': name}), flush=True)


def include_prefix(environment, compiler):
    probe = BASE / 'include-probe.cpp'
    probe.write_text('#include <stddef.h>\nint dexarena_include_probe;\n', encoding='ascii')
    process = subprocess.run([str(compiler), '/nologo', '/showIncludes', '/c', str(probe),
                              '/Fo' + str(BASE / 'include-probe.obj')], cwd=BASE, env=environment,
                             capture_output=True)
    if process.returncode:
        raise RuntimeError('MSVC include-prefix probe failed')
    for line in process.stdout.splitlines():
        match = re.match(rb'^(.*?)[A-Za-z]:\\.*\.h\s*$', line)
        if match:
            return match.group(1)
    raise RuntimeError('MSVC include-prefix probe found no header line')


def cmake_prefix_input(prefix_bytes, code_page=None):
    """Keep raw evidence, but obtain valid UTF-8 CMake input from the common helper."""
    helper_path = Path(__file__).resolve().parent.parent / 'write_msvc_prefix.py'
    spec = importlib.util.spec_from_file_location('_dexarena_clean_host_msvc_prefix', helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError('Cannot load the common MSVC prefix helper')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    if code_page is None:
        code_page = helper.windows_ansi_code_page()
    unicode_prefix, decoded_as = helper.decode_prefix(prefix_bytes, code_page)
    payload = helper.cmake_bytes(unicode_prefix)
    prefix_utf8 = unicode_prefix.encode('utf-8')
    acp_projection = unicode_prefix.encode(f'cp{code_page}', errors='strict')
    return payload, {
        'helper_sha256': sha(helper_path),
        'raw_prefix_hex': prefix_bytes.hex(),
        'prefix_decoded_as': decoded_as,
        'windows_ansi_code_page': code_page,
        'cmake_input_encoding': 'utf-8',
        'cmake_payload_sha256': hashlib.sha256(payload).hexdigest(),
        'utf8_prefix_hex': prefix_utf8.hex(),
        'ninja_acp_projection_prefix_hex': acp_projection.hex(),
        'ninja_acp_projection_matches_raw': acp_projection == prefix_bytes,
        'ninja_acp_projection_status': 'candidate_only_not_actual_generated_Ninja_evidence',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure-only', action='store_true')
    parser.add_argument('--all-host-libs', action='store_true')
    parser.add_argument('--rebuild-untracked', action='store_true', help='Recompile only generated objects in this private build')
    args = parser.parse_args(argv)
    gpu_identities = configure()
    environment, compiler = msvc_environment()
    source = BASE / 'source-patched/physx'
    build = BASE / 'build-host'
    output = BASE / 'host-output'
    prefix = BASE / 'msvc-prefix.cmake'
    prefix_bytes = include_prefix(environment, compiler)
    prefix_payload, prefix_input = cmake_prefix_input(prefix_bytes)
    prefix.write_bytes(prefix_payload)
    configure_command = [str(CMAKE), '-S', str(source / 'compiler/public'), '-B', str(build), '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=release', f'-DCMAKE_MAKE_PROGRAM={NINJA.as_posix()}',
        f'-DCMAKE_C_COMPILER={compiler.as_posix()}', f'-DCMAKE_CXX_COMPILER={compiler.as_posix()}',
        '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
        f'-DCMAKE_PROJECT_INCLUDE={prefix.as_posix()}', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
        f'-DPHYSX_ROOT_DIR={source.as_posix()}',
        f'-DPHYSX_CMAKE_MODULES_PATH={(source / "source/compiler/cmake/modules").as_posix()}',
        '-DTARGET_BUILD_PLATFORM=windows', '-DPX_OUTPUT_ARCH=x86',
        f'-DPX_OUTPUT_LIB_DIR={output.as_posix()}', f'-DPX_OUTPUT_BIN_DIR={output.as_posix()}',
        '-DPX_GENERATE_STATIC_LIBRARIES=ON', '-DNV_USE_STATIC_WINCRT=ON', '-DNV_USE_DEBUG_WINCRT=ON',
        '-DPX_BUILDSNIPPETS=OFF', '-DPX_BUILDPVDRUNTIME=OFF', '-DPX_GENERATE_GPU_PROJECTS=OFF',
        '-DPX_GENERATE_GPU_PROJECTS_ONLY=OFF', '-DPX_COPY_EXTERNAL_DLL=OFF', '-DGPU_DLL_COPIED=1',
        '-DPX_USE_NVTX=OFF', '-DPX_FLOAT_POINT_PRECISE_MATH=OFF']
    targets = ['PhysX']
    if args.all_host_libs:
        targets += ['PhysXFoundation', 'PhysXCommon', 'PhysXCooking', 'PhysXExtensions', 'PhysXPvdSDK',
                    'PhysXCharacterKinematic', 'PhysXVehicle', 'PhysXVehicle2']
    compile_command = [str(CMAKE), '--build', str(build), '--target', *targets, '--parallel', '2']
    plan = {'scope': 'CPU host compilation only; no SDK deployment or GPU acceptance',
            'source_manifest_sha256': sha(BASE / 'source-manifest.json'),
            'compiler': str(compiler), 'toolset': environment['VCToolsVersion'], 'max_compile_jobs': 2,
            'msvc_include_prefix_bytes_hex': prefix_bytes.hex(),
            'msvc_prefix_helper_sha256': prefix_input['helper_sha256'],
            'msvc_include_prefix_input': prefix_input,
            'cmake_version': subprocess.check_output([str(CMAKE), '--version'], text=True).splitlines()[0],
            'ninja_version': subprocess.check_output([str(NINJA), '--version'], text=True).strip(),
            'configure_command': configure_command, 'build_command': compile_command,
            'source': str(source), 'build': str(build), 'output': str(output),
            'gpu_dlls_to_preserve': gpu_identities,
            'gpu_runtime_version': GPU_IDENTITY.get('version'),
            'status': 'prepared'}
    write_json(BASE / 'build-plan.json', plan)
    try:
        run_logged('configure-host', configure_command, environment)
        plan['status'] = 'configured'
        write_json(BASE / 'build-status.json', plan)
        if not args.configure_only:
            if args.rebuild_untracked:
                objects = list((build / 'sdk_source_bin').rglob('*.obj'))
                for obj in objects:
                    if not obj.resolve().is_relative_to(build.resolve()):
                        raise RuntimeError('Refused generated-object cleanup outside private build')
                for obj in objects:
                    obj.unlink()
                print(json.dumps({'recompile_generated_objects': len(objects)}), flush=True)
            run_logged('compile-host', compile_command, environment)
            body_object = next(build.rglob('ScBodyCore.cpp.obj'))
            dependencies = subprocess.check_output([str(NINJA), '-C', str(build), '-t', 'deps',
                                                     str(body_object.relative_to(build))])
            dependency_count = re.search(rb'#deps (\d+)', dependencies)
            if dependency_count is None or int(dependency_count.group(1)) < 20:
                raise RuntimeError('Ninja did not record the native lock object header dependencies')
            if sha(BASE / 'source-manifest.json') != plan['source_manifest_sha256']:
                raise RuntimeError('Source manifest changed during the recorded host build')
            if verify_gpu_dlls() != gpu_identities:
                raise RuntimeError('GPU identity changed during the host build')
            libraries = {p.relative_to(output).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
                         for p in output.rglob('*.lib')}
            plan.update(status='host_libraries_built_runtime_untested', libraries=libraries,
                        native_lock_object_header_dependencies=int(dependency_count.group(1)))
            write_json(BASE / 'build-status.json', plan)
    except Exception as error:
        plan.update(status='failed', error_type=type(error).__name__, error=str(error))
        write_json(BASE / 'build-status.json', plan)
        raise
    print(json.dumps({'status': plan['status'], 'receipt': str(BASE / 'build-status.json')}), flush=True)


if __name__ == '__main__':
    main()
