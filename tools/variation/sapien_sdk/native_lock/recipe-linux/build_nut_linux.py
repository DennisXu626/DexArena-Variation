"""Build the Nut Linux wheel using the shared Linux builder and a verified private host."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import build_host_linux as host

HERE = host.HERE
CAPABILITIES = ('indexed_gpu_apply_patch_version', 'native_gpu_lock_sync_patch_version')
NUT_PATCH_ROOT = 'native_lock/recipe-v6/patches'


def portable_nut_patches():
    return {f'{NUT_PATCH_ROOT}/{name}': sha for name, sha in host.LOCK['sapien_patches'].items()}


def load_common(path):
    path = path.resolve(strict=True)
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location('dexarena_shared_linux_builder', path)
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
    finally:
        sys.path.pop(0)
    host.require(common.HERE == path.parent, 'Shared builder loaded a different prepare module')
    return common


def verify_patch_stack(source, patches, work):
    """Reverse the stack in a scratch tree, since 0300 extends the 0002 hunks."""
    names = {name for patch in patches
             for name in re.findall(r'^\+\+\+ b/([^\r\n]+)$', patch.read_text(encoding='utf-8'), re.M)}
    with tempfile.TemporaryDirectory(prefix='nut-patch-verify-', dir=work) as temp:
        scratch = Path(temp)
        host.run('git', 'init', '--quiet', cwd=scratch)
        for name in sorted(names):
            origin = (source / name).resolve(strict=True)
            host.require(origin.is_relative_to(source), f'Patch member escapes the source: {name}')
            target = scratch / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
        for patch in reversed(patches):
            host.run('git', 'apply', '--reverse', '--check', patch, cwd=scratch)
            host.run('git', 'apply', '--reverse', patch, cwd=scratch)


def configure_common(common, stage):
    """Select the Nut profile on this process's private copy of the shared builder."""
    common.verify_locks()
    host.require(common.LOCK['upstream']['commit'] == host.LOCK['sapien_commit'], 'Shared SAPIEN commit differs')
    required = ('0001-indexed-gpu-apply.patch', '0002-indexed-capability.patch', '0200-local-build-version.patch')
    host.require(tuple(Path(row['file']).name for row in common.PATCHES) == required,
                 'Shared Linux common and packaging patch set differs')
    expected = {key: host.PHYSX[other] for key, other in (
        ('version', 'version'), ('file', 'gpu_file'), ('sha256', 'gpu_sha256'),
        ('archive_sha256', 'gpu_archive_sha256'))}
    host.require(all(common.GPU[key] == value for key, value in expected.items()), 'Shared Linux PhysX solver differs')
    patches = []
    for name, expected in host.LOCK['sapien_patches'].items():
        path = HERE.parent / 'recipe-v6/patches' / name
        host.require(host.sha(path) == expected and b'\r' not in path.read_bytes(),
                     f'Nut SAPIEN patch differs: {name}')
        patches.append({'file': str(path), 'sha256': expected})
    common.PATCHES = [*common.PATCHES, *patches]
    common.ARCHIVES = [item for item in common.ARCHIVES if item['name'] != 'physx5']
    common.LINUX = {**common.LINUX, 'version': host.LOCK['version']}
    original_inputs, original_record = common.cmake_inputs, common.input_record

    def cmake_inputs(work):
        return (original_inputs(work) + '\n'
                + f'set(SAPIEN_PHYSX5_DIR [==[{stage.as_posix()}]==] CACHE PATH "Private Nut PhysX host" FORCE)\n')

    def input_record(work):
        rows = common.PATCHES
        verify_patch_stack(work / 'source', [common.HERE / row['file'] for row in rows], work)
        try:
            # The ordered verification above supersedes the shared independent reverse checks.
            common.PATCHES = []
            record = original_record(work)
        finally:
            common.PATCHES = rows
        return {**record, 'nut_ordered_patch_sha256': [row['sha256'] for row in rows]}

    common.cmake_inputs = cmake_inputs
    common.input_record = input_record


def build(common, work, host_work, stage_record, jobs, provenance):
    for lang, default in (('cc', 'cc'), ('cxx', 'c++')):
        tool = host.compiler(os.environ.get(lang.upper(), default))
        host.require(tool == stage_record['compiler'][lang], f'{lang} differs from the private host build')
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    write_json = common.write_json

    def write_receipt(path, data):
        if path == work / 'artifact.json':
            host.require(all(type(data.get(name)) is int and data[name] == 1 for name in CAPABILITIES),
                         'Native Nut probe receipt missing')
            host.require(host.verify_stage(host_work) == stage_record, 'Host stage changed during wheel build')
            host.check_gpu_abi(work / 'physx-runtime' / host.PHYSX['gpu_file'])
            cmake_input = work / 'build/inputs.cmake'
            private_dir = host_work / 'physx-host'
            host.require(f'[==[{private_dir.as_posix()}]==]' in
                         cmake_input.read_text(encoding='utf-8'), 'SAPIEN private host CMake input missing')
            native_cache = work / 'build/_sapien_build/CMakeCache.txt'
            cache = native_cache.read_text(encoding='utf-8').splitlines()
            host.require(f'SAPIEN_PHYSX5_DIR:PATH={private_dir.as_posix()}' in cache,
                         'SAPIEN did not configure against the verified host stage')
            scoped = portable_nut_patches()
            shared = [row for row in data['patches'] if not Path(row['file']).is_absolute()]
            applied = [*shared, *({'file': name, 'sha256': value} for name, value in scoped.items())]
            data = {**data, 'patches': applied, 'nut_linux': provenance,
                    'private_host_stage_sha256': host.sha(host_work / 'host-stage.json'),
                    'private_cmake_inputs_sha256': host.sha(cmake_input),
                    'native_cmake_cache_sha256': host.sha(native_cache),
                    'gpu_runtime_executed': False}
        write_json(path, data)

    common.write_json = write_receipt
    common.build(work, jobs, capabilities=CAPABILITIES)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'build'))
    parser.add_argument('--common-recipe', type=Path, required=True, help='Shared build_linux.py')
    parser.add_argument('--work-dir', type=Path, required=True, help='Exclusive Nut wheel work directory')
    parser.add_argument('--host-work', type=Path, required=True, help='Completed Nut PhysX host build')
    parser.add_argument('--download-cache', type=Path)
    parser.add_argument('--source-reference', type=Path)
    parser.add_argument('--dependency-reference', type=Path)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    host.require(args.jobs > 0, '--jobs must be positive')
    work = args.work_dir.resolve()
    host_work = args.host_work.resolve(strict=True)
    host.require(not work.is_relative_to(host_work) and not host_work.is_relative_to(work),
                 'Use separate wheel and private host work directories')
    stage_record = host.verify_stage(host_work)
    common = load_common(args.common_recipe)
    configure_common(common, host_work / 'physx-host')
    common_path = args.common_recipe.resolve()
    recipe_files = [common_path, *(common_path.parent / name for name in ('prepare.py', 'lock.json', 'lock_linux.json'))]
    provenance = {
        'schema': 'dexarena-nut-linux-wheel-profile-v1',
        'common_recipe_sha256': {path.name: host.sha(path) for path in recipe_files},
        'nut_lock_sha256': host.sha(host.LOCK_PATH), 'nut_recipe_sha256': host.sha(Path(__file__)),
        'host_stage_sha256': host.sha(host_work / 'host-stage.json'),
        'sapien_extra_patches': portable_nut_patches(),
    }
    record = work / 'prepared_nut_linux.json'
    if args.action == 'prepare':
        cache = args.download_cache.resolve() if args.download_cache else work / 'downloads'
        common.prepare(work, cache, args.source_reference, args.dependency_reference)
        host.write_json(record, provenance)
    else:
        host.require(json.loads(record.read_text(encoding='utf-8')) == provenance, 'Prepared Nut wheel inputs differ')
        build(common, work, host_work, stage_record, args.jobs, provenance)


if __name__ == '__main__':
    try:
        main()
    except (AttributeError, KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f'Nut Linux wheel: {error}')
