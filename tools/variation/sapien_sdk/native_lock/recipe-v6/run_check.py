"""Run the repository's GPU checker with an explicit immutable Windows SDK and PhysX runtime."""
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
handles = [os.add_dll_directory(str(private / 'sapien')), os.add_dll_directory(str(physx))]
for name, expected in lock['runtime_physx']['dll_sha256'].items():
    if sha(physx / name) != expected:
        raise ValueError(f'Wrong official PhysX DLL: {name}')
    handles.append(ctypes.WinDLL(str(physx / name)))
sys.path[:0] = [str(private), str(repo)]
import sapien
import sapien.pysapien as binary

if not Path(binary.__file__).resolve().is_relative_to(private):
    raise ValueError(f'Loaded another SAPIEN binding: {binary.__file__}')
if sapien.__version__ != receipt['version'] or metadata.version('sapien') != receipt['version']:
    raise ValueError('Runtime and wheel metadata versions do not match the artifact receipt.')
capability = sapien.physx.indexed_gpu_apply_patch_version()
if capability != 1:
    raise ValueError('Native indexed GPU apply fix is required.')
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
kernel32.GetModuleFileNameW.restype = ctypes.c_uint32


def identity():
    for name, expected in receipt['native_files'].items():
        if sha(private / 'sapien' / name) != expected:
            raise ValueError(f'Runtime binary changed: {name}')
    rows = {}
    names = {'sapien.dll': private / 'sapien', 'svulkan2.dll': private / 'sapien',
             'simsense.dll': private / 'sapien', **{name: physx for name in lock['runtime_physx']['dll_sha256']}}
    for name, directory in names.items():
        module = kernel32.GetModuleHandleW(name)
        path_buffer = ctypes.create_unicode_buffer(32768)
        if not module or not kernel32.GetModuleFileNameW(module, path_buffer, len(path_buffer)):
            raise ValueError(f'Module is not loaded: {name}')
        path = Path(path_buffer.value).resolve(strict=True)
        if path != (directory / name).resolve(strict=True):
            raise ValueError(f'Loaded DLL outside requested runtime: {path}')
        rows[name] = {'path': str(path), 'sha256': sha(path)}
    path = Path(binary.__file__).resolve(strict=True)
    rows[path.name] = {'path': str(path), 'sha256': sha(path)}
    return rows


before = identity()
checker = repo / 'tools/variation/check_furniture_appearance.py'
sys.argv = [str(checker), '--physx-gpu-dir', str(physx), '--output', str(args.output), *remaining]
code = 0
try:
    runpy.run_path(str(checker), run_name='__main__')
except SystemExit as error:
    code = error.code if isinstance(error.code, int) else 1
finally:
    after = identity()
    report = {'private_sdk': True, 'artifact_sha256': sha(args.artifact),
              'indexed_gpu_apply_patch_version': capability, 'version': sapien.__version__,
              'before': before, 'after': after, 'binaries_unchanged': before == after}
    if args.output.is_dir():
        (args.output / 'private_sdk.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if before != after:
        raise ValueError('Loaded binaries changed during verification.')
sys.exit(code)
