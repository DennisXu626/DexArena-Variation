"""Run a task checker with a verified private SAPIEN and PhysX runtime."""
import argparse
import ctypes
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import runpy
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo-root', type=Path, required=True)
parser.add_argument('--checker', type=Path, required=True)
parser.add_argument('--sapien-root', type=Path, required=True)
parser.add_argument('--artifact', type=Path, required=True)
parser.add_argument('--physx-gpu-dir', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args, remaining = parser.parse_known_args()
if os.name != 'nt':
    parser.error('This loaded-DLL verification wrapper is Windows-only.')
repo = args.repo_root.resolve(strict=True)
private = args.sapien_root.resolve(strict=True)
physx = args.physx_gpu_dir.resolve(strict=True)
receipt = json.loads(args.artifact.read_text(encoding='utf-8'))
lock_path = Path(__file__).resolve().parent / 'lock.json'
lock = json.loads(lock_path.read_text(encoding='utf-8'))
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
if sha(lock_path) != receipt['lock_sha256']:
    raise ValueError('Artifact receipt and current source lock differ.')
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
kernel32.GetModuleFileNameW.restype = ctypes.c_uint32
kernel32.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
kernel32.GetSystemDirectoryW.restype = ctypes.c_uint32


def module_path(handle):
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel32.GetModuleFileNameW(handle, buffer, len(buffer))
    if not 0 < size < len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    return Path(buffer.value).resolve(strict=True)


def retain_system_vulkan():
    buffer = ctypes.create_unicode_buffer(32768)
    size = kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < size < len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    path = (Path(buffer.value) / 'vulkan-1.dll').resolve(strict=True)
    already_loaded = kernel32.GetModuleHandleW(path.name)
    if already_loaded and module_path(already_loaded) != path:
        raise ValueError('A non-system Vulkan loader is already loaded.')
    return path, ctypes.WinDLL(str(path), use_last_error=True)


def vulkan_identity():
    handle = kernel32.GetModuleHandleW(vulkan_path.name)
    if handle != vulkan_loader._handle or module_path(handle) != vulkan_path:
        raise ValueError('Loaded Vulkan loader differs from the retained system module.')
    return {'path': str(vulkan_path), 'sha256': sha(vulkan_path)}


vulkan_path, vulkan_loader = retain_system_vulkan()
vulkan_before = vulkan_identity()
handles = [os.add_dll_directory(str(private / 'sapien')), os.add_dll_directory(str(physx))]
for name, expected in lock['runtime_physx']['dll_sha256'].items():
    if sha(physx / name) != expected:
        raise ValueError(f'Wrong official PhysX DLL: {name}')
    handles.append(ctypes.WinDLL(str(physx / name)))
sys.path[:0] = [str(private), str(repo)]


def python_identity():
    paths = sorted((private / 'sapien').rglob('*.py'))
    if not paths:
        raise ValueError('Private SAPIEN Python source is missing.')
    return {path.relative_to(private).as_posix(): sha(path) for path in paths}


python_before = python_identity()
import sapien
import sapien.pysapien as binary

if not Path(binary.__file__).resolve().is_relative_to(private):
    raise ValueError(f'Loaded another SAPIEN binding: {binary.__file__}')
if sapien.__version__ != receipt['version'] or metadata.version('sapien') != receipt['version']:
    raise ValueError('Runtime and wheel metadata versions do not match the artifact receipt.')
capability = sapien.physx.indexed_gpu_apply_patch_version()
if capability != 1:
    raise ValueError('Native indexed GPU apply fix is required.')
def identity():
    for name, expected in receipt['native_files'].items():
        if sha(private / 'sapien' / name) != expected:
            raise ValueError(f'Runtime binary changed: {name}')
    rows = {}
    names = {'sapien.dll': private / 'sapien', 'svulkan2.dll': private / 'sapien',
             'simsense.dll': private / 'sapien', **{name: physx for name in lock['runtime_physx']['dll_sha256']}}
    for name, directory in names.items():
        module = kernel32.GetModuleHandleW(name)
        if not module:
            raise ValueError(f'Module is not loaded: {name}')
        path = module_path(module)
        if path != (directory / name).resolve(strict=True):
            raise ValueError(f'Loaded DLL outside requested runtime: {path}')
        rows[name] = {'path': str(path), 'sha256': sha(path)}
    path = Path(binary.__file__).resolve(strict=True)
    rows[path.name] = {'path': str(path), 'sha256': sha(path)}
    return rows


before = identity()
checker = (repo / args.checker).resolve(strict=True)
if not checker.is_relative_to(repo / 'tools/variation') or checker.suffix != '.py':
    raise ValueError('Checker must be a Python tool within the repository variation directory.')
sys.argv = [str(checker), '--physx-gpu-dir', str(physx), '--output', str(args.output), *remaining]
code = 0
try:
    runpy.run_path(str(checker), run_name='__main__')
except SystemExit as error:
    code = error.code if isinstance(error.code, int) else 1
finally:
    after = identity()
    python_after = python_identity()
    vulkan_after = vulkan_identity()
    report = {'private_sdk': True, 'artifact_sha256': sha(args.artifact),
              'indexed_gpu_apply_patch_version': capability, 'version': sapien.__version__,
              'before': before, 'after': after, 'binaries_unchanged': before == after,
              'python_before': python_before, 'python_after': python_after,
              'python_source_unchanged': python_before == python_after,
              'system_vulkan_loader': {'before': vulkan_before, 'after': vulkan_after,
                                       'unchanged': vulkan_before == vulkan_after},
              'launcher': {'file': Path(__file__).name, 'sha256': sha(Path(__file__)),
                           'checker': checker.relative_to(repo).as_posix(), 'checker_sha256': sha(checker)}}
    if args.output.is_dir():
        (args.output / 'private_sdk.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if before != after:
        raise ValueError('Loaded binaries changed during verification.')
    if python_before != python_after:
        raise ValueError('Private SAPIEN Python source changed during verification.')
    if vulkan_before != vulkan_after:
        raise ValueError('System Vulkan loader changed during verification.')
sys.exit(code)
