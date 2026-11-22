"""Create an immutable private runtime and an identity receipt; does not initialize GPU."""
import argparse
import ast
import email
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from prepare import source_identity, verify_applied_patches_in_scratch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--wheel', type=Path, required=True)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--receipt', type=Path, required=True)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--build-info', type=Path, required=True, help='Actual build_identity.json from the build recipe')
args = parser.parse_args()
here = Path(__file__).resolve().parent
lock = json.loads((here / 'lock.json').read_text(encoding='utf-8'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
wheel = args.wheel.resolve(strict=True)
runtime = args.runtime.resolve()
if runtime.exists() or args.receipt.exists():
    raise ValueError('Use new runtime/receipt paths; never overwrite earlier evidence.')
with zipfile.ZipFile(wheel) as package:
    for name in package.namelist():
        if not (runtime / name).resolve().is_relative_to(runtime):
            raise ValueError(f'Unsafe wheel member: {name}')
    metadata_names = [n for n in package.namelist() if n.endswith('.dist-info/METADATA')]
    if len(metadata_names) != 1:
        raise ValueError('Expected one wheel metadata record.')
    version = email.message_from_bytes(package.read(metadata_names[0]))['Version']
    parsed = ast.parse(package.read('sapien/version.py').decode('utf-8'))
    package_version = next(ast.literal_eval(n.value) for n in parsed.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets))
    if version != lock['local_version'] or package_version != version:
        raise ValueError('Wheel metadata, runtime version and lock must agree.')
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=args.source, text=True).strip()
if commit != lock['upstream']['commit']:
    raise ValueError('Source commit does not match lock.')
for patch in lock['patches']:
    if sha(here / patch['file']) != patch['sha256']:
        raise ValueError(f'Changed patch: {patch["file"]}')
verify_applied_patches_in_scratch(args.source.parent)
receipt = {
    'version': version, 'wheel_sha256': sha(wheel),
    'source_commit': commit, 'lock_sha256': sha(here / 'lock.json'),
    'patches': lock['patches'], 'reference_toolchain': lock['tested_toolchain'],
    'actual_toolchain': json.loads(args.build_info.read_text(encoding='utf-8-sig')),
    'actual_source': json.loads((args.source.parent / 'prepared_inputs.json').read_text(encoding='utf-8')),
    'physx_gpu': lock['runtime_physx'],
    'acceptance': 'Build identity only. Verify loaded native DLL paths/SHA, capability, actual CUDA physics/RGB, and formal multi-env reset separately.'
}
if receipt['actual_toolchain']['lock_sha256'] != sha(here / 'lock.json') or receipt['actual_toolchain']['prepared_inputs_sha256'] != sha(args.source.parent / 'prepared_inputs.json'):
    raise ValueError('Build identity and source preparation do not match this lock.')
if source_identity(args.source.parent) != receipt['actual_source']['source']:
    raise ValueError('Tracked SDK source changed after preparation.')
for name, expected in receipt['actual_toolchain']['recipe_sha256'].items():
    if sha(here / name) != expected:
        raise ValueError(f'Build recipe changed since compilation: {name}')
# All source/patch/build identity checks above complete before runtime writes.
if sha(wheel) != receipt['wheel_sha256']:
    raise ValueError('Wheel changed during identity verification.')
with zipfile.ZipFile(wheel) as package:
    runtime.mkdir(parents=True)
    package.extractall(runtime)
receipt['native_files'] = {p.name: sha(p) for p in (runtime / 'sapien').iterdir() if p.suffix in ('.pyd', '.dll')}
args.receipt.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(json.dumps(receipt, indent=2))
