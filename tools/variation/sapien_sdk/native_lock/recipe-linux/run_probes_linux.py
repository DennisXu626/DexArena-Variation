"""Run the checked Nut native lock or raster fixture on an authorized Linux GPU."""
import argparse
import ctypes
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import BuiltinFunctionType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_host_linux as host
from build_nut_linux import CAPABILITIES, load_common, portable_nut_patches

FIXTURES = {'lock': 'probes/check_runtime_lock.py', 'raster': 'tools/probe_batched_visibility.py'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify_artifact(path, artifact_sha256, sdk_tools):
    host.require(host.sha(path) == artifact_sha256, 'Review and supply the build receipt SHA-256')
    record = read(path)
    profile = record['nut_linux']
    host.require(record['schema'] == 'dexarena-sapien-linux-artifact-v1'
                 and record['version'] == host.LOCK['version']
                 and record['source_commit'] == host.LOCK['sapien_commit']
                 and all(record.get(name) == 1 for name in CAPABILITIES)
                 and record['gpu_runtime_executed'] is False
                 and profile['schema'] == 'dexarena-nut-linux-wheel-profile-v1'
                 and profile['nut_lock_sha256'] == host.sha(host.LOCK_PATH)
                 and profile['host_stage_sha256'] == record['private_host_stage_sha256']
                 and profile['sapien_extra_patches'] == portable_nut_patches(),
                 'A matching private Nut Linux wheel receipt is required')
    common = read(sdk_tools / 'lock.json')
    linux = read(sdk_tools / 'lock_linux.json')
    common_files = ('build_linux.py', 'prepare.py', 'lock.json', 'lock_linux.json')
    host.require(profile['common_recipe_sha256'] == {name: host.sha(sdk_tools / name) for name in common_files}
                 and record['physx_gpu'] == linux['physx_gpu'],
                 'Common Linux recipe or solver receipt differs')
    patches = {row['file']: row['sha256'] for row in common['patches'] if row['group'] in linux['patch_groups']}
    extra = portable_nut_patches()
    patches.update(extra)
    patch_roots = {name: host.HERE.parents[1] if name in extra else sdk_tools for name in patches}
    host.require(record['patches'] == [{'file': name, 'sha256': sha} for name, sha in patches.items()]
                 and all(host.sha(patch_roots[name] / name) == digest for name, digest in patches.items()),
                 'Actual patch files differ from the Nut wheel receipt')
    wheel = (path.parent / record['wheel']).resolve(strict=True)
    host.require(wheel.is_relative_to(path.parent) and host.sha(wheel) == record['wheel_sha256'], 'Wheel differs')
    solver = path.parent / 'physx-runtime' / host.PHYSX['gpu_file']
    host.require(solver.resolve(strict=True) == solver, 'PhysX solver must use its private path')
    host.check_gpu_abi(solver)
    return record, linux, wheel, solver


def fixture_source(kind):
    relative = FIXTURES[kind]
    path = host.HERE.parent / relative
    payload = path.read_bytes()
    host.require(host.digest(payload) == host.LOCK['gpu_probe_sources'][relative], f'Original fixture differs: {relative}')
    source = payload.decode('utf-8')
    resource = re.compile(r"map\(int, subprocess\.check_output\(\['nvidia-smi',\n[^\n]+\.split\(','\)\)")
    source, count = resource.subn('linux_gpu_resource()', source)
    host.require(count == 1, 'The original GPU resource guard changed')
    if kind == 'lock':
        original_paths = "private, physx = sdk / 'runtime', sdk / 'physx-runtime'"
        host.require(source.count(original_paths) == 1, 'The original native fixture path setup changed')
        source = source.replace(original_paths, 'private = linux_runtime_path')
        start = source.index("kernel = ctypes.WinDLL('kernel32'")
        end = source.index('def python_identity():', start)
        source = source[:start] + 'def identity():\n    return linux_native_identity()\n\n\n' + source[end:]
    else:
        anchor = "        require(extra.per_scene_id != 0, 'Negative test object was not attached')\n"
        host.require(source.count(anchor) == 1, 'The original raster completion anchor changed')
        source = source.replace(anchor, anchor + '        linux_observe_vulkan()\n')
    return payload, source


def gpu_resource(gpu_uuid):
    fields = host.output('nvidia-smi', '-i', gpu_uuid, '--query-gpu=memory.free,utilization.gpu',
                         '--format=csv,noheader,nounits')
    return tuple(map(int, fields.split(',')))


def load_cuda_driver(common, runtime, physx_dir, expected):
    driver = ctypes.CDLL('libcuda.so.1', ctypes.RTLD_GLOBAL)
    alias = ctypes.CDLL('libcuda.so', ctypes.RTLD_GLOBAL)
    host.require(driver._handle == alias._handle
                 and common.system_driver(common.mapped_files(), runtime, physx_dir) == expected,
                 'Both CUDA names must load the same verified system driver')
    return driver, alias


def run_fixture(args, record, linux, wheel, solver):
    def resource():
        return gpu_resource(args.gpu_uuid)

    free, utilization = resource()
    host.require(free >= 2048 and utilization < 70, 'Requested GPU did not pass the probe startup resource gate')
    original, adapted = fixture_source(args.kind)
    args.output.mkdir(parents=True, exist_ok=False)
    runtime = args.output / 'private-runtime'
    common = load_common(args.common_runner)
    binding, natives, code_files, assets = common.wheel_inventory(wheel, record, linux, runtime, stage=True)
    sys.path.insert(0, str(runtime))
    import sapien
    import sapien.pysapien as binary

    host.require(Path(binary.__file__).resolve() == runtime / binding
                 and sapien.__version__ == metadata.version('sapien') == record['version']
                 and sapien.physx.version() == host.PHYSX['version'], 'Different SAPIEN or PhysX was imported')
    for name in CAPABILITIES:
        marker = getattr(binary.physx, name, None)
        host.require(isinstance(marker, BuiltinFunctionType) and getattr(sapien.physx, name) is marker,
                     f'Native capability is missing: {name}')
        value = marker()
        host.require(type(value) is int and value == 1, f'Native capability did not report 1: {name}')
    host.require(not sapien.physx.is_gpu_enabled(), 'PhysX GPU activated before private solver verification')
    # Keep the handles alive without enabling PhysX; the native fixture owns that step.
    driver_handles = load_cuda_driver(common, runtime, solver.parent, args._driver)
    solver_handle = ctypes.CDLL(str(solver), ctypes.RTLD_LOCAL)

    def native_identity():
        mapped, _ = common.runtime_identity(runtime, binding, solver, natives, gpu=True)
        return mapped

    vulkan_live = None

    def observe_vulkan():
        nonlocal vulkan_live
        host.require(vulkan_live is None, 'Raster fixture observed Vulkan more than once')
        vulkan_live = common.vulkan_identity(common.mapped_files(), required=True)

    before = native_identity()
    os.environ.update(DEXARENA_NATIVE_LOCK_SDK_ROOT=str(args.artifact.parent),
                      DEXARENA_NATIVE_LOCK_SDK_ARTIFACT=str(args.artifact),
                      DEXARENA_NATIVE_LOCK_SDK_ARTIFACT_SHA256=args.artifact_sha256,
                      DEXARENA_NATIVE_LOCK_SDK_LOADED_IDENTITY=json.dumps(before))
    (args.output / 'original_fixture.py').write_bytes(original)
    source = args.output / 'linux_fixture.py'
    source.write_text(adapted, encoding='utf-8', newline='\n')
    capture = args.output / 'capture'
    sys.argv = [str(source), '--output', str(capture)]
    code = None
    try:
        exec(compile(adapted, str(source), 'exec'),
             {'__name__': '__main__', '__file__': str(source), 'linux_gpu_resource': resource,
              'linux_native_identity': native_identity, 'linux_runtime_path': runtime,
              'linux_observe_vulkan': observe_vulkan})
    except SystemExit as exit_error:
        code = exit_error.code
    host.require(code == 0 and read(capture / 'results.json')['status'] == 'passed',
                 f'{args.kind} fixture did not pass')
    mapped = native_identity()
    if args.kind == 'raster':
        host.require(vulkan_live is not None, 'Raster fixture did not observe Vulkan while its scenes were live')
        teardown_vulkan = common.vulkan_identity(common.mapped_files(), required=False)
        if teardown_vulkan is not None:
            host.require(teardown_vulkan == vulkan_live, 'Vulkan loader changed between capture and teardown')
            mapped['vulkan/libvulkan.so.1'] = teardown_vulkan
    host.require(all(mapped.get(key) == value for key, value in before.items())
                 and host.sha(args.artifact) == args.artifact_sha256 and host.sha(wheel) == record['wheel_sha256'],
                 'Mapped native code or build identity changed during the fixture')
    common.check_staged_files(runtime, {**natives, **code_files, **assets})
    receipt = {
        'status': 'passed', 'fixture': args.kind, 'gpu_uuid': args.gpu_uuid, 'artifact_sha256': args.artifact_sha256,
        'wheel_sha256': record['wheel_sha256'], 'mapped_before': before, 'mapped_after': mapped,
        'original_fixture_sha256': host.digest(original), 'linux_fixture_sha256': host.sha(source),
        'fixture_results_sha256': host.sha(capture / 'results.json'),
    }
    if args.kind == 'raster':
        receipt['vulkan_live'] = vulkan_live
    host.write_json(args.output / 'linux-loader-receipt.json', receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=tuple(FIXTURES))
    parser.add_argument('--common-runner', type=Path, required=True, help='Shared run_linux_check.py')
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--artifact-sha256', required=True)
    parser.add_argument('--gpu-uuid', required=True)
    parser.add_argument('--approved-gpu', required=True, action='store_true')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--_child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--_driver', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    host.require(sys.platform == 'linux' and platform.machine() == 'x86_64' and sys.version_info[:2] == (3, 10),
                 'The probe requires native Linux x86-64 CPython 3.10')
    host.require(re.fullmatch(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', args.gpu_uuid),
                 'Select the authorized GPU by UUID')
    args.artifact = args.artifact.resolve(strict=True)
    args.common_runner = args.common_runner.resolve(strict=True)
    args.output = args.output.resolve()
    host.require(not args.output.exists(), 'Provide a fresh output directory per probe')
    record, linux, wheel, solver = verify_artifact(args.artifact, args.artifact_sha256, args.common_runner.parent)
    if args._child:
        paths = os.environ.get('LD_LIBRARY_PATH', '').split(os.pathsep)
        host.require(sys.flags.isolated and not sys.flags.optimize
                     and os.environ.get('CUDA_VISIBLE_DEVICES') == args.gpu_uuid
                     and len(paths) >= 2 and paths[1] == str(solver.parent) and not os.environ.get('LD_PRELOAD')
                     and args._driver is not None, 'Use the isolated Nut probe launcher')
        directory = Path(paths[0])
        alias = directory / 'libcuda.so'
        host.require(directory.parent == args.output.parent
                     and directory.name.startswith('.dexarena-nut-cuda-') and alias.is_symlink()
                     and alias.resolve(strict=True) == args._driver,
                     'Use the isolated Nut probe launcher')
        return run_fixture(args, record, linux, wheel, solver)
    host.require(args._driver is None, 'The CUDA driver argument is internal')
    env = {key: value for key, value in os.environ.items() if key != 'LD_PRELOAD'}
    common = load_common(args.common_runner)
    driver_handle = ctypes.CDLL('libcuda.so.1', ctypes.RTLD_LOCAL)
    driver = common.system_driver(common.mapped_files(), args.output / 'private-runtime', solver.parent)
    inherited = list(filter(None, env.get('LD_LIBRARY_PATH', '').split(os.pathsep)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.dexarena-nut-cuda-', dir=args.output.parent) as alias_dir:
        (Path(alias_dir) / 'libcuda.so').symlink_to(driver)
        env.update(CUDA_VISIBLE_DEVICES=args.gpu_uuid,
                   LD_LIBRARY_PATH=os.pathsep.join([alias_dir, str(solver.parent), *inherited]))
        return subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), *sys.argv[1:],
                               '--_child', '--_driver', str(driver)], env=env, check=False).returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (AttributeError, KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f'Nut Linux probe: {error}')
