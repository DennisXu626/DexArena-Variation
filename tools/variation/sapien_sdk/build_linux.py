"""Prepare locked SAPIEN inputs and build the private Linux x86-64 CUDA wheel."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
from zipfile import ZipFile

from prepare import GIT as WINDOWS_GIT
from prepare import HERE, LOCK, clone, download, extract, io_path, run, sha, source_identity, tree_identity


LOCK_PATH = HERE / 'lock_linux.json'
GIT = WINDOWS_GIT if os.name == 'nt' else ['git', '-c', 'http.version=HTTP/1.1']
LINUX = json.loads(LOCK_PATH.read_text(encoding='utf-8'))
PATCHES = [patch for patch in LOCK['patches'] if patch['group'] in LINUX['patch_groups']]
GIT_DEPS = LOCK['git_dependencies'] + LINUX['git_dependencies']
ARCHIVES = [LINUX['physx_host'], *LINUX['archives'],
            next(entry for entry in LOCK['archives'] if entry['name'] == 'oidn')]
GPU = LINUX['physx_gpu']
NUMPY = LINUX['probe_numpy']
NUMPY_WHEEL = NUMPY['url'].rsplit('/', 1)[-1]
BINDING = 'sapien/pysapien.cpython-310-x86_64-linux-gnu.so'
PINOCCHIO = 'sapien/pysapien_pinocchio.cpython-310-x86_64-linux-gnu.so'
CORE = 'sapien.libs/libsapien.so'
RENDERER = 'sapien.libs/libsvulkan2.so'
OIDN = tuple(f'sapien/oidn_library/libOpenImageDenoise{part}.so.2.0.1'
             for part in ('_core', '', '_device_cuda'))
INDEXED = 'indexed_gpu_apply_patch_version'


def command_output(*args, cwd=None, env=None):
    return subprocess.check_output(args, cwd=cwd, env=env, text=True).strip()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def verify_locks():
    if sha(HERE / 'lock.json') != LINUX['base_lock_sha256']:
        raise ValueError('The shared upstream and patch lock has changed.')
    for patch in PATCHES:
        path = HERE / patch['file']
        if sha(path) != patch['sha256'] or b'\r' in path.read_bytes():
            raise ValueError(f'Patch hash or LF mismatch: {path}')


def dep_path(work, name):
    return work / 'deps' / f'{name}-src'


def clone_commit(entry, destination, reference=None, release_tag=None):
    if reference and reference.is_dir():
        clone(entry, destination, reference)
        return
    destination.mkdir(parents=True, exist_ok=True)
    run(*GIT, 'init', str(destination))
    fetch_ref = f'refs/tags/{release_tag}:refs/tags/{release_tag}' if release_tag else entry['commit']
    run(*GIT, 'fetch', '--depth=1', entry['url'], fetch_ref, cwd=destination)
    run(*GIT, 'checkout', '--detach', entry['commit'], cwd=destination)


def pinocchio_build_files(work):
    # A FetchContent source override skips upstream PATCH_COMMAND. Apply the same files here.
    cmake = work / 'source' / 'pinocchio' / 'cmake'
    overrides = {
        'tinyxml': {'tinyxml_CMakeLists.txt': 'CMakeLists.txt'},
        'urdfdom_headers': {'urdfdom_headers_CMakeLists.txt': 'CMakeLists.txt'},
        'urdfdom': {'urdfdom_CMakeLists.txt': 'CMakeLists.txt',
                    'urdfdom_parser_CMakeLists.txt': 'urdf_parser/CMakeLists.txt'},
        'pinocchio': {'pinocchio_CMakeLists.txt': 'CMakeLists.txt',
                      'pinocchio_post-project.cmake': 'cmake/post-project.cmake',
                      'pinocchio_src_CMakeLists.txt': 'src/CMakeLists.txt'},
    }
    for name, files in overrides.items():
        for source, target in files.items():
            shutil.copyfile(cmake / source, dep_path(work, name) / target)


def dependency_record(work):
    paths = {dep_path(work, entry['name']): entry for entry in GIT_DEPS}
    paths.update({dep_path(work, 'pinocchio') / path: entry
                  for path, entry in LINUX['pinocchio_submodules'].items()})
    record = {}
    for path, entry in paths.items():
        if command_output(*GIT, 'rev-parse', 'HEAD', cwd=path) != entry['commit']:
            raise ValueError(f'Unexpected dependency commit: {path}')
        names = subprocess.check_output([*GIT, 'ls-files', '-z'], cwd=path).decode().split('\0')
        tracked = {name: sha(path / name) for name in names if name and io_path(path / name).is_file()}
        relative = path.relative_to(work).as_posix()
        record[relative] = {'commit': entry['commit'], 'tracked_sha256': json_digest(tracked)}
    return record


def json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()


def input_record(work):
    if sha(work / 'physx-runtime' / GPU['file']) != GPU['sha256']:
        raise ValueError('Linux PhysX GPU ELF hash mismatch.')
    if sha(work / 'probe-inputs' / NUMPY_WHEEL) != NUMPY['sha256']:
        raise ValueError('NumPy wheel for the native import probe has changed.')
    tag = command_output(*GIT, 'rev-parse', f'{LOCK["upstream"]["tag"]}^{{commit}}', cwd=work / 'source')
    if tag != LOCK['upstream']['commit']:
        raise ValueError('The upstream release tag does not resolve to the locked source.')
    for patch in PATCHES:
        run(*GIT, 'apply', '--reverse', '--check', str(HERE / patch['file']), cwd=work / 'source')
    source = source_identity(work)
    return {
        'linux_lock_sha256': sha(LOCK_PATH),
        'source_commit': LOCK['upstream']['commit'],
        'source': {path: {'commit': entry['commit'],
                          'tracked_sha256': json_digest(entry['tracked_sha256'])}
                   for path, entry in source.items()},
        'dependencies': dependency_record(work),
        'archive_trees': {entry['name']: tree_identity(dep_path(work, entry['name'])) for entry in ARCHIVES},
        'physx_gpu': GPU,
        'probe_numpy': NUMPY,
    }


def prepare(work, cache, source_reference, dependency_reference):
    work.mkdir(parents=True, exist_ok=False)
    cache.mkdir(parents=True, exist_ok=True)
    # KTX's LFS objects are test data and precompiled libraries for other platforms.
    os.environ['GIT_LFS_SKIP_SMUDGE'] = '1'
    source = work / 'source'
    clone_commit(LOCK['upstream'], source, source_reference, LOCK['upstream']['tag'])
    for path, commit in LOCK['upstream']['submodules'].items():
        entry = {'url': LOCK['upstream']['submodule_urls'][path], 'commit': commit}
        clone_commit(entry, source / path, source_reference / path if source_reference else None)
    for patch in PATCHES:
        patch_path = str(HERE / patch['file'])
        run(*GIT, 'apply', '--check', patch_path, cwd=source)
        run(*GIT, 'apply', patch_path, cwd=source)
    for entry in GIT_DEPS:
        name = entry['name']
        clone_commit(entry, dep_path(work, name), dependency_reference / f'{name}-src' if dependency_reference else None)
    # Upstream's Pinocchio wrapper disables tests and does not use its example robot data.
    for path, entry in LINUX['pinocchio_submodules'].items():
        reference = dependency_reference / 'pinocchio-src' / path if dependency_reference else None
        clone_commit(entry, dep_path(work, 'pinocchio') / path, reference)
    for entry in ARCHIVES:
        extract(download(entry, cache), dep_path(work, entry['name']), entry['strip'])
    pinocchio_build_files(work)
    extract(download(GPU, cache, 'archive_sha256'), work / 'physx-runtime', 0)
    probe_inputs = work / 'probe-inputs'
    probe_inputs.mkdir()
    shutil.copyfile(download(NUMPY, cache), probe_inputs / NUMPY_WHEEL)
    write_json(work / 'prepared_linux.json', input_record(work))
    print(f'Prepared Linux source, build dependencies and GPU library in {work}')


def verify(work):
    record = json.loads((work / 'prepared_linux.json').read_text(encoding='utf-8'))
    if record != input_record(work):
        raise ValueError('Prepared source, dependencies or archives changed.')
    print(f'Verified prepared Linux inputs in {work}')
    return record


def toolchain():
    if (sys.platform != 'linux' or platform.machine() != 'x86_64'
            or platform.python_implementation() != 'CPython' or sys.version_info[:2] != (3, 10)):
        raise ValueError('Building requires Linux x86_64 and CPython 3.10.')
    if not os.environ.get('CUDA_PATH'):
        raise ValueError('CUDA_PATH must point to the CUDA 11.8 toolkit.')
    cuda = Path(os.environ['CUDA_PATH']).resolve(strict=True)
    nvcc = cuda / 'bin' / 'nvcc'
    if not (cuda / 'lib64' / 'libcudart_static.a').is_file():
        raise ValueError(f'CUDA static runtime missing at {cuda}/lib64/libcudart_static.a')
    versions = {tool: command_output(tool, '--version') for tool in ('cmake', 'make', 'auditwheel')}
    versions['cuda'] = command_output(str(nvcc), '--version')
    if f'release {LINUX["cuda_release"]},' not in versions['cuda']:
        raise ValueError(f'CUDA {LINUX["cuda_release"]} required, found {versions["cuda"]}')
    versions['cc'] = command_output(os.environ.get('CC', 'cc'), '--version')
    versions['cxx'] = command_output(os.environ.get('CXX', 'c++'), '--version')
    versions['python'] = sys.version
    versions['platform'] = platform.platform()
    versions['libc'] = platform.libc_ver()
    return nvcc, versions


def cmake_inputs(work):
    defines = {
        'BUILD_TESTING': 'OFF',
        'FETCHCONTENT_FULLY_DISCONNECTED': 'ON',
        'KTX_FEATURE_TOOLS': 'OFF',
    }
    for entry in GIT_DEPS + ARCHIVES:
        defines[f'FETCHCONTENT_SOURCE_DIR_{entry["name"].upper()}'] = dep_path(work, entry['name']).as_posix()
    return ''.join(f'set({key} [==[{value}]==] CACHE STRING "Locked DexArena input")\n'
                   for key, value in defines.items())


def wheel_identity(wheel):
    with ZipFile(wheel) as archive:
        natives = {}
        for item in archive.infolist():
            if item.is_dir() or '.so' not in Path(item.filename).name:
                continue
            with archive.open(item) as content:
                header = content.read(20)
                if not header.startswith(b'\x7fELF'):
                    continue
                if header[4:6] != b'\x02\x01' or header[18:20] != b'\x3e\x00':
                    raise ValueError(f'Non-x86_64 ELF in wheel: {item.filename}')
                digest = hashlib.sha256(header)
                for block in iter(lambda: content.read(1024 * 1024), b''):
                    digest.update(block)
                natives[item.filename] = digest.hexdigest()
    missing = {BINDING, PINOCCHIO, CORE, RENDERER, *OIDN} - natives.keys()
    if missing:
        raise ValueError(f'Repaired wheel lacks expected native members: {sorted(missing)}')
    return natives


def probe(wheel, numpy_wheel, natives, target, capabilities=(INDEXED,)):
    subprocess.run([sys.executable, '-Im', 'pip', '--isolated', 'install', '--disable-pip-version-check',
                    '--no-input', '--no-index', '--no-deps', '--no-cache-dir',
                    '--target', str(target), str(wheel), str(numpy_wheel)], check=True)
    code = '''
import ctypes
import hashlib
from importlib.metadata import version
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import runpy
import sys
from types import BuiltinFunctionType

target, receipt, binding, pinocchio, oidn, expected, wheel_version, physx_version, numpy_version, *names = sys.argv[1:]
expected = json.loads(expected)
sys.path.insert(0, target)
import numpy

root = Path(target).resolve()
package = root / 'sapien'
if numpy.__version__ != numpy_version or not Path(numpy.__file__).resolve().is_relative_to(root):
    raise ValueError('Native import probe requires its locked private NumPy installation.')

os.environ['SAPIEN_PACKAGE_PATH'] = str(package)
# Load CUDA OIDN's library and dependencies by path, without creating any device.
oidn_handles = [ctypes.CDLL(str(root / item), ctypes.RTLD_LOCAL) for item in json.loads(oidn)]

def import_binding(member):
    path = root / member
    spec = spec_from_file_location(path.name.split('.', 1)[0], path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != path:
        raise ValueError(f'Unexpected native module: {module.__file__}')
    return module

native = import_binding(binding)
pinocchio_native = import_binding(pinocchio)
loaded_paths = {Path(row.split(maxsplit=5)[-1]) for row in Path('/proc/self/maps').read_text().splitlines()}
for relative, digest in expected.items():
    path = (root / relative).resolve()
    if path not in loaded_paths or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f'Expected wheel ELF was not loaded with its recorded hash: {path}')
if runpy.run_path(str(package / 'version.py'))['__version__'] != wheel_version or version('sapien') != wheel_version:
    raise ValueError('Wheel package or metadata version differs from the Linux lock.')
if (native.physx.version() != physx_version or native.physx.is_gpu_enabled()
        or any(path.name == 'libPhysXGpu_64.so' for path in loaded_paths)):
    raise ValueError('Unexpected PhysX version or GPU solver in the native CPU probe.')
values = {}
for name in names:
    marker = getattr(native.physx, name, None)
    if not isinstance(marker, BuiltinFunctionType):
        raise ValueError(f'No native binding for {name}')
    value = marker()
    if type(value) is not int or value != 1:
        raise ValueError(f'Unexpected native value for {name}: {value}')
    values[name] = value
with Path(receipt).open('x', encoding='utf-8') as stream:
    json.dump(values, stream)
'''
    env = os.environ.copy()
    env.pop('LD_LIBRARY_PATH', None)
    env.pop('LD_PRELOAD', None)
    env['CUDA_VISIBLE_DEVICES'] = ''
    expected = {member: natives[member] for member in (BINDING, PINOCCHIO, CORE, RENDERER, *OIDN)}
    receipt = target.parent / 'native-capabilities.json'
    command = [sys.executable, '-I', '-B', '-c', code, str(target), str(receipt), BINDING, PINOCCHIO,
               json.dumps(OIDN), json.dumps(expected),
               LINUX['version'], GPU['version'], NUMPY['version'], *capabilities]
    subprocess.run(command, env=env, check=True)
    result = json.loads(receipt.read_bytes())
    if result != dict.fromkeys(capabilities, 1):
        raise ValueError('Missing native capability results from the build-time CPU probe.')
    return result


def build(work, jobs, capabilities=(INDEXED,)):
    nvcc, versions = toolchain()
    inputs = verify(work)
    build_dir = work / 'build'
    build_dir.mkdir(exist_ok=False)
    cmake_file = build_dir / 'inputs.cmake'
    cmake_file.write_text(cmake_inputs(work), encoding='utf-8')
    env = os.environ.copy()
    env.update(CMAKE_TOOLCHAIN_FILE=str(cmake_file), CMAKE_GENERATOR='Unix Makefiles',
               CMAKE_BUILD_PARALLEL_LEVEL=str(jobs), CUDACXX=str(nvcc),
               CUDA_PATH=str(nvcc.parent.parent), CPLUS_INCLUDE_PATH=sysconfig.get_path('include'),
               SAPIEN_LOCAL_VERSION=LINUX['version'].split('+', 1)[1])
    source = work / 'source'
    setup = [sys.executable, 'setup.py', f'--build-dir={build_dir}']
    subprocess.run([*setup, 'bdist_wheel', '--sapien-only'], cwd=source, env=env, check=True)
    raw_dir = build_dir / 'raw-wheel'
    subprocess.run([*setup, 'bdist_wheel', '--pybind-only', '--dist-dir', str(raw_dir)],
                   cwd=source, env=env, check=True)
    (raw_wheel,) = raw_dir.glob(f'sapien-{LINUX["version"]}-cp310-cp310-linux_x86_64.whl')
    wheels = work / 'wheels'
    libdir = build_dir / '_sapien_install'
    env['LD_LIBRARY_PATH'] = os.pathsep.join(filter(None, (
        str(libdir / 'lib'), str(libdir / 'lib64'), env.get('LD_LIBRARY_PATH'))))
    subprocess.run(['auditwheel', 'repair', '--plat', LINUX['wheel_platform'],
                    '--exclude', 'libvulkan*', '--exclude', 'libOpenImageDenoise*',
                    '--internal', 'libsapien', '--internal', 'libsvulkan2',
                    '--wheel-dir', str(wheels), str(raw_wheel)], env=env, check=True)
    (wheel,) = wheels.glob(f'sapien-{LINUX["version"]}-cp310-cp310-*{LINUX["wheel_platform"]}*.whl')
    natives = wheel_identity(wheel)
    verified = probe(wheel, work / 'probe-inputs' / NUMPY_WHEEL, natives, build_dir / 'probe-site',
                     capabilities=capabilities)
    write_json(work / 'artifact.json', {
        'schema': 'dexarena-sapien-linux-artifact-v1',
        'version': LINUX['version'],
        'wheel': wheel.relative_to(work).as_posix(),
        'wheel_sha256': sha(wheel),
        'native_files': natives,
        'native_binding': BINDING,
        **verified,
        'lock_sha256': sha(HERE / 'lock.json'),
        'linux_lock_sha256': sha(LOCK_PATH),
        'recipe_sha256': sha(Path(__file__)),
        'source_commit': inputs['source_commit'],
        'patches': [{key: patch[key] for key in ('file', 'sha256')} for patch in PATCHES],
        'physx_gpu': GPU,
        'prepared_inputs': inputs,
        'toolchain': versions,
    })
    print(f'Built and probed {wheel}. Artifact receipt: {work / "artifact.json"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'verify', 'build'))
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--download-cache', type=Path)
    parser.add_argument('--source-reference', type=Path)
    parser.add_argument('--dependency-reference', type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    verify_locks()
    work = args.work_dir.resolve()
    if args.action == 'prepare':
        cache = args.download_cache.resolve() if args.download_cache else work / 'downloads'
        prepare(work, cache, args.source_reference, args.dependency_reference)
    elif args.action == 'verify':
        verify(work)
    else:
        build(work, args.jobs)


if __name__ == '__main__':
    main()
