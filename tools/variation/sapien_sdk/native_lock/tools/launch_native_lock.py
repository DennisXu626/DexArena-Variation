"""Validate an immutable native-lock SDK, then launch a script in a fresh Python process."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from native_lock_identity import IdentityError, require, validate_sdk


BOOTSTRAP = r'''
import ctypes, hashlib, json, os
from importlib import metadata
from pathlib import Path
import runpy, sys

identity = json.loads(sys.argv[1])
def need(value, detail):
    if not value:
        raise RuntimeError(detail)
repo, script = Path(sys.argv[2]), Path(sys.argv[3])
runtime, gpu = Path(identity['runtime']), Path(identity['physx_runtime'])
handles = [os.add_dll_directory(str(runtime / 'sapien')), os.add_dll_directory(str(gpu))]
handles += [ctypes.WinDLL(str(gpu / name)) for name in identity['physx_gpu']['dll_sha256']]
sys.path[:0] = [str(runtime), str(repo)]
import sapien
import sapien.pysapien as binding
import sapien.physx as px
need(Path(binding.__file__).resolve().is_relative_to(runtime), binding.__file__)
need(sapien.__version__ == metadata.version('sapien') == identity['version'], 'Runtime version differs')
for name, expected in identity['capabilities_expected'].items():
    need(getattr(px, name)() == expected, name)
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel.GetModuleHandleW.restype = ctypes.c_void_p
kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
kernel.GetModuleFileNameW.restype = ctypes.c_uint32
loaded = {}
for name in identity['required_loaded']:
    module = kernel.GetModuleHandleW(name)
    buffer = ctypes.create_unicode_buffer(32768)
    need(module and kernel.GetModuleFileNameW(module, buffer, len(buffer)), name)
    path = Path(buffer.value).resolve(strict=True)
    directory = gpu if name in identity['physx_gpu']['dll_sha256'] else runtime / 'sapien'
    need(path == (directory / name).resolve(strict=True), (name, str(path)))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    need(digest == identity['expected_loaded'][name], name)
    loaded[name] = {'path': str(path), 'sha256': digest}
os.environ['DEXARENA_NATIVE_LOCK_SDK_ROOT'] = identity['sdk_root']
os.environ['DEXARENA_NATIVE_LOCK_SDK_ARTIFACT'] = identity['artifact']
os.environ['DEXARENA_NATIVE_LOCK_SDK_ARTIFACT_SHA256'] = identity['artifact_sha256']
os.environ['DEXARENA_NATIVE_LOCK_SDK_LOADED_IDENTITY'] = json.dumps(loaded, sort_keys=True)
sys.argv = [str(script), *sys.argv[4:]]
# Keep DLL-directory and explicitly loaded GPU-library handles alive throughout
# the target script; metadata checks above do not initialize or step a scene.
runpy.run_path(str(script), run_name='__main__')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-root', type=Path, required=True)
    parser.add_argument('--base-root', type=Path)
    parser.add_argument('--provenance-root', type=Path)
    parser.add_argument('--base-recipe-root', type=Path)
    parser.add_argument('--artifact-sha256')
    parser.add_argument('--python', type=Path, required=True, help='Locked CPython 3.10.22 x64 interpreter')
    parser.add_argument('--repo-root', type=Path, help='Project root added after the private SDK on sys.path')
    parser.add_argument('--cwd', type=Path, help='Working directory for the target; defaults to the current directory')
    parser.add_argument('--validate-only', action='store_true', help='Only file/provenance and standard-library Python identity checks; no native import')
    parser.add_argument('script', nargs='?', type=Path)
    parser.add_argument('script_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    python = args.python.resolve(strict=True)
    probe = subprocess.check_output([str(python), '-I', '-S', '-B', '-c',
        'import json,platform,struct; print(json.dumps(dict(version=platform.python_version(),bits=8*struct.calcsize("P"),implementation=platform.python_implementation())))'],
        text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    python_identity = json.loads(probe)
    require(python_identity == {'version': '3.10.22', 'bits': 64, 'implementation': 'CPython'},
            'Use the locked CPython 3.10.22 x64 interpreter')
    identity = validate_sdk(args.sdk_root, args.base_root, args.provenance_root,
                            args.artifact_sha256, args.base_recipe_root)
    identity['launcher_python'] = {'path': str(python), **python_identity}
    if args.validate_only:
        print(json.dumps(identity, indent=2))
        return
    require(os.name == 'nt', 'The native Windows SDK launcher is Windows-only')
    require(args.script is not None, 'Specify a target script or --validate-only')
    script = args.script.resolve(strict=True)
    cwd = args.cwd.resolve(strict=True) if args.cwd else Path.cwd()
    repo = args.repo_root.resolve(strict=True) if args.repo_root else cwd
    environment = os.environ.copy()
    environment['PYTHONPATH'] = os.pathsep.join([identity['runtime'], str(repo), environment.get('PYTHONPATH', '')])
    environment['PATH'] = os.pathsep.join([str(Path(identity['runtime']) / 'sapien'), identity['physx_runtime'], environment.get('PATH', '')])
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    remaining = args.script_args[1:] if args.script_args[:1] == ['--'] else args.script_args
    command = [str(python), '-B', '-c', BOOTSTRAP, json.dumps(identity), str(repo), str(script), *remaining]
    result = subprocess.run(command, cwd=cwd, env=environment,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    try:
        main()
    except IdentityError as error:
        raise SystemExit(str(error)) from error
