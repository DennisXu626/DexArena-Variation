"""Validate native-lock build provenance without importing SAPIEN or any native SDK."""
from __future__ import annotations

import argparse
import ast
import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PureWindowsPath
import re
import zipfile


class IdentityError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise IdentityError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def at(root, relative):
    root = Path(root).resolve()
    path = (root / Path(str(relative).replace('\\', '/'))).resolve()
    require(path.is_relative_to(root), f'Path escaped its provenance root: {relative}')
    return path


def check(path, expected, label=None):
    require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected),
            f'Invalid SHA-256: {label or path}')
    require(Path(path).is_file(), f'Missing identity input: {label or path}')
    require(sha(path) == expected, f'Identity mismatch: {label or path}')


def remap(recorded, original, actual):
    """Remap a recorded Windows build root without editing its historical receipt."""
    try:
        relative = PureWindowsPath(recorded).relative_to(PureWindowsPath(original))
    except ValueError:
        return Path(recorded)
    return Path(actual).joinpath(*relative.parts)


def _version(runtime):
    module = ast.parse((runtime / 'sapien/version.py').read_text(encoding='utf-8'))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__'
                                              for t in node.targets):
            return ast.literal_eval(node.value)
    raise IdentityError('Runtime has no literal __version__')


def _wheel_runtime(wheel, runtime, receipt):
    check(wheel, receipt['wheel_sha256'], 'wheel')
    with zipfile.ZipFile(wheel) as package:
        names = package.namelist()
        require(len(names) == len(set(names)), 'Duplicate wheel member')
        require(package.testzip() is None, 'Corrupt wheel member')
        records = [name for name in names if name.endswith('.dist-info/RECORD')]
        require(len(records) == 1, 'Expected exactly one wheel RECORD')
        rows = list(csv.reader(io.StringIO(package.read(records[0]).decode('utf-8'))))
        require({row[0] for row in rows} == set(names), 'Wheel RECORD closure differs')
        for name, digest, size in rows:
            target = at(runtime, name)
            require(target.is_file(), f'Missing runtime wheel member: {name}')
            data = package.read(name)
            require(hashlib.sha256(data).hexdigest() == sha(target), f'Runtime differs from wheel: {name}')
            if name == records[0]:
                require(not digest and not size, 'RECORD must not hash itself')
            else:
                expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
                require(digest == expected and int(size) == len(data), f'Invalid wheel RECORD: {name}')
        metadata_names = [name for name in names if name.endswith('.dist-info/METADATA')]
        require(len(metadata_names) == 1, 'Expected one wheel METADATA')
        require(('Version: ' + receipt['version']) in package.read(metadata_names[0]).decode().splitlines(),
                'Wheel metadata version differs')
    require(_version(runtime) == receipt['version'], 'Runtime version differs')
    return len(rows)


def _base_v5(base, receipt, expected_receipt_sha, base_recipe_root=None):
    check(base / 'artifact.json', expected_receipt_sha, 'base v5 artifact')
    require(receipt['version'] == '3.0.3+dexarena.gpu1.wininterop5', 'Expected actual v5 base receipt')
    if base_recipe_root:
        lock_path = Path(base_recipe_root).resolve() / 'lock.json'
    else:
        candidates = [base / 'recipe/lock.json', base / 'lock.json']
        # The original public recipe lives in the enclosing source checkout;
        # relocated work roots can supply --base-recipe-root explicitly.
        if len(base.parents) > 2:
            candidates.append(base.parents[2] / 'tools/variation/sapien_sdk/lock.json')
        lock_path = next((p for p in candidates if p.is_file()), candidates[0])
    require(lock_path.is_file(), 'Supply the original v5 recipe with --base-recipe-root')
    check(lock_path, receipt['lock_sha256'], 'base v5 lock')
    lock = read(lock_path)
    actual, source = receipt['actual_toolchain'], receipt['actual_source']
    require(actual['lock_sha256'] == source['lock_sha256'] == receipt['lock_sha256'], 'Base v5 lock chain differs')
    require(receipt['source_commit'] == lock['upstream']['commit']
            and receipt['patches'] == lock['patches'] and receipt['physx_gpu'] == lock['runtime_physx'],
            'Base v5 receipt differs from published lock')
    check(base / 'prepared_inputs.json', actual['prepared_inputs_sha256'], 'base v5 prepared inputs')
    require(read(base / 'prepared_inputs.json') == source, 'Base v5 prepared input record differs')
    require(read(base / 'build_identity.json') == actual, 'Base v5 actual build identity differs')
    for name, expected in actual['recipe_sha256'].items():
        check(at(lock_path.parent, name), expected, 'base v5 recipe ' + name)
    for patch in lock['patches']:
        check(at(lock_path.parent, patch['file']), patch['sha256'], 'base v5 patch ' + patch['file'])
    count = 0
    for relative, record in source['source'].items():
        tree = at(base / 'source', relative)
        for name, expected in record['tracked_sha256'].items():
            check(at(tree, name), expected, 'base v5 source ' + relative + '/' + name)
            count += 1
    return {'artifact_sha256': expected_receipt_sha, 'lock_sha256': receipt['lock_sha256'],
            'source_commit': receipt['source_commit'], 'verified_source_files': count}


def _host(provenance, receipt, expected_stage_sha, dependency=None):
    source_path = provenance / 'source-manifest.json'
    build_path = provenance / 'build-status.json'
    stage_path = provenance / 'host-stage-manifest.json'
    if dependency:
        for key in ('source_manifest', 'build_status', 'stage_manifest'):
            check(remap(dependency[key]['path'], dependency['provenance_root'], provenance),
                  dependency[key]['sha256'], 'host dependency ' + key)
        source_path = remap(dependency['source_manifest']['path'], dependency['provenance_root'], provenance)
        build_path = remap(dependency['build_status']['path'], dependency['provenance_root'], provenance)
        stage_path = remap(dependency['stage_manifest']['path'], dependency['provenance_root'], provenance)
    source, build, stage = read(source_path), read(build_path), read(stage_path)
    check(stage_path, expected_stage_sha, 'PhysX host stage manifest')
    require(source == receipt['host_physx']['source'] and build == receipt['host_physx']['build'],
            'PhysX inline provenance differs from actual manifests')
    check(source_path, stage['source_manifest_sha256'], 'PhysX source-to-stage chain')
    check(build_path, stage['build_status_sha256'], 'PhysX build-to-stage chain')
    require(build['source_manifest_sha256'] == sha(source_path), 'PhysX source-to-build chain differs')
    require(source['commit'] == '85befb639eb736bc8ec7d4a2e9726ec2ab1d0434'
            and source['patch0_commit'] == '8026efddef81130fb97ec3b4a51da66fab39f09d',
            'PhysX source or preserved patch0 revision differs')
    require(build['status'] == 'host_libraries_built_runtime_untested' and len(build['libraries']) == 9,
            'Expected the completed nine-library PhysX host dependency')
    stage_root = remap(dependency['physx_stage']['path'], dependency['provenance_root'], provenance) if dependency else provenance / 'physx-stage-native-lock-v1'
    for name, item in stage['files'].items():
        check(at(stage_root, name), item['sha256'], 'PhysX stage ' + name)
    for name, item in build['libraries'].items():
        require(stage['files'][name] == item, 'PhysX stage library differs from build: ' + name)
    require(stage['locked_gpu_dlls_unchanged'] == receipt['physx_gpu']['dll_sha256'], 'PhysX GPU identity differs')
    require(stage['capability_symbol'] == 'dexarena_physx_native_lock_sync_patch_version'
            and stage['capability_in_linker_index'] is True and stage['out_of_line_lock_setter_in_linker_index'] is True,
            'PhysX native lock symbol evidence is incomplete')
    # Verify actual source bytes, including the patched setter and preserved
    # cooking workaround; source manifests alone are not a source-byte check.
    for name, item in source['selected_files'].items():
        check(at(provenance / 'source-upstream', name), item['sha256'], 'PhysX upstream source ' + name)
    patched = provenance / 'source-patched'
    changed = {name: item['patched_sha256'] for name, item in source['patch'].items()}
    changed['physx/source/simulationcontroller/src/ScBodyCore.cpp'] = source['final_runtime_cpp_sha256']
    changed.update({name: item['sha256'] for name, item in source['preserved_patch0_files'].items()})
    cmake_name = 'physx/source/compiler/cmake/windows/CMakeLists.txt'
    original_cmake = at(provenance / 'source-upstream', cmake_name).read_bytes()
    changed[cmake_name] = hashlib.sha256(original_cmake.replace(b'IF(PX_COPY_EXTERNAL_DLL OR PUBLIC_RELEASE)',
                                                              b'IF(PX_COPY_EXTERNAL_DLL)', 1)).hexdigest()
    for name, item in source['selected_files'].items():
        check(at(patched, name), changed.get(name, item['sha256']), 'PhysX patched source ' + name)
    return {'source_manifest_sha256': sha(source_path), 'build_status_sha256': sha(build_path),
            'stage_manifest_sha256': sha(stage_path), 'stage_files_verified': len(stage['files']),
            'host_libraries': 9,
            'dependency_reused': dependency['reused'] if dependency is not None else None}


def _incremental(sdk, provenance, receipt, base_root, base_recipe_root):
    lock_path = sdk / 'lock.json'
    check(lock_path, receipt['lock_sha256'], 'native-lock build lock')
    lock = read(lock_path)
    require(lock['schema'] == 'dexarena-sapien-native-lock-build-lock-v1', 'Unsupported native-lock lock schema')
    require(lock['version'] == receipt['version'] and lock['build_mode'] == receipt['actual_toolchain']['build_mode'],
            'Native-lock build mode/version differs')
    require(lock['clean_full_build_executed'] is False and receipt['incremental_link']['clean_full_build_executed'] is False,
            'Incremental build must not claim full clean compilation')
    base = Path(base_root or receipt['incremental_link']['source_build_origin']).resolve()
    prior = read(base / 'artifact.json')
    base_summary = _base_v5(base, prior, lock['base_artifact_sha256'], base_recipe_root)
    require(receipt['incremental_link']['origin_artifact_sha256'] == lock['base_artifact_sha256']
            == receipt['actual_source']['base_artifact_sha256'], 'Base artifact chain differs')
    require(lock['base_lock_sha256'] == prior['lock_sha256'], 'Base lock chain differs')
    inputs_path = provenance / 'relink-notes/v5-ninja-relink-inputs.json'
    check(inputs_path, lock['relink_inputs_sha256'], 'v5 Ninja input manifest')
    inputs = read(inputs_path)
    status_path = sdk / 'relink-status.json'
    check(status_path, lock['relink_status_sha256'], 'native relink status')
    status, relink = read(status_path), read(sdk / 'relink-lock.json')
    require(status['status'] == 'native_sdk_linked_loading_and_runtime_untested', 'Expected completed relink status')
    require(all(status[key] == value for key, value in relink.items() if key != 'status'),
            'Relink lock differs from completed status')
    require(inputs['groups'] == receipt['actual_source']['unchanged_objects_and_source_identities'],
            'Cached input provenance differs from embedded receipt')
    require(status['source_files'] == receipt['actual_source']['new_source_snapshot'], 'New source snapshot differs')
    for name, row in status['source_files'].items():
        check(at(sdk / 'source', name), row['final_sha256'], 'new SAPIEN source ' + name)
        check(at(base / 'source', name), row['base_sha256'], 'base SAPIEN source ' + name)
    for name, digest in status['artifacts'].items():
        check(at(sdk, name), digest, 'relink output ' + name)
    counts = {}
    for kind, group in inputs['groups'].items():
        reused = [item for item in group['objects'] if item['reuse']]
        counts[kind] = len(reused)
        for item in reused:
            check(remap(item['path'], inputs['base_root'], base), item['sha256'], 'cached ' + kind + ' object')
            check(remap(item['source_path'], inputs['base_root'], base), item['source_sha256'], 'cached object source')
    require(counts == {'native': receipt['incremental_link']['native_objects_reused'],
                       'pybind': receipt['incremental_link']['pybind_objects_reused']}, 'Reused object counts differ')
    for name, digest in lock['recipes'].items():
        check(at(provenance / 'public-sdk', name), digest, 'incremental recipe ' + name)
    for name, digest in lock['new_patches'].items():
        check(at(provenance, name), digest, 'native-lock patch ' + name)
    overlay_path = provenance / 'sapien-overlay-manifest.json'
    check(overlay_path, relink['sapien_overlay_manifest_sha256'], 'SAPIEN overlay manifest')
    overlay = read(overlay_path)
    require(overlay['base_artifact_sha256'] == lock['base_artifact_sha256'], 'Overlay base identity differs')
    check(at(provenance, overlay['patch']), overlay['patch_sha256'], 'SAPIEN overlay patch')
    for item in overlay['files']:
        check(at(provenance / 'sapien-overlay', item['path']), item['overlay_sha256'], 'SAPIEN overlay source')
        require(status['source_files'][item['path']]['final_sha256'] == item['overlay_sha256'], 'Overlay not applied to relink source')
    host = _host(provenance, receipt, lock['host_stage_manifest_sha256'])
    require(host['source_manifest_sha256'] == lock['physx_source_manifest_sha256'], 'Host source lock differs')
    return {'build_mode': lock['build_mode'], 'clean_full_build_executed': False,
            'base': base_summary, 'source_files_verified': len(status['source_files']),
            'source_snapshot_canonical_sha256': canonical_sha(status['source_files']),
            'reused_objects_verified': counts, 'host_physx': host,
            'relink_lock_sha256': sha(sdk / 'relink-lock.json'), 'relink_status_sha256': sha(status_path)}


def _clean(sdk, provenance, receipt, provenance_override=False):
    recipe, work = sdk / 'recipe-v6', sdk / 'sapien-clean'
    check(recipe / 'lock.json', receipt['lock_sha256'], 'clean recipe lock')
    lock = read(recipe / 'lock.json')
    actual, source = receipt['actual_toolchain'], receipt['actual_source']
    require(lock['local_version'] == receipt['version'] and lock['upstream']['commit'] == receipt['source_commit'],
            'Clean receipt version/source differs from lock')
    require(actual['lock_sha256'] == source['lock_sha256'] == receipt['lock_sha256'], 'Clean lock chain differs')
    require(read(work / 'build_identity.json') == actual and read(work / 'prepared_inputs.json') == source,
            'Clean build or prepared source identity differs')
    check(work / 'prepared_inputs.json', actual['prepared_inputs_sha256'], 'clean prepared inputs')
    require(receipt['patches'] == lock['patches'] and receipt['physx_gpu'] == lock['runtime_physx'],
            'Clean patches or GPU runtime differs from lock')
    for patch in lock['patches']:
        check(at(recipe, patch['file']), patch['sha256'], 'clean patch')
    for name, expected in actual['recipe_sha256'].items():
        check(at(recipe, name), expected, 'clean recipe ' + name)
    count = 0
    for name, record in source['source'].items():
        for relative, digest in record['tracked_sha256'].items():
            check(at(at(work / 'source', name), relative), digest, 'clean source ' + name + '/' + relative)
            count += 1
    mode = receipt['incremental_link']
    require(mode['clean_full_build_executed'] is True, 'Clean build completion is not recorded')
    for key in ('native_objects_reused_from_v5', 'pybind_objects_reused_from_v5'):
        require(mode[key] == 0, 'Clean SAPIEN must not reuse v5 objects')
    dependency_record = receipt['host_dependency']
    dependency_path = sdk / 'host-dependency.json'
    require(Path(dependency_record['path']).resolve() == dependency_path.resolve(),
            'Clean receipt host dependency path differs from the selected SDK root')
    check(dependency_path, dependency_record['sha256'], 'clean receipt host dependency')
    dependency = read(dependency_path)
    require(dependency['schema'] == 'dexarena-clean-host-dependency-v1', 'Unsupported clean host dependency schema')
    reused = dependency['reused']
    require(type(reused) is bool and type(dependency['dependency_reused']) is bool
            and dependency['dependency_reused'] == reused,
            'Host dependency reuse fields differ')
    require(type(receipt['host_physx']['dependency_reused']) is bool
            and receipt['host_physx']['dependency_reused'] == reused
            and type(mode['physx_host_dependency_reused']) is bool
            and mode['physx_host_dependency_reused'] == reused,
            'Clean receipt and host dependency reuse flags differ')
    require(receipt['host_physx']['provenance'] == dependency,
            'Clean receipt embedded host provenance differs from the dependency record')
    for key, receipt_key in (('source_manifest', 'source_manifest_sha256'),
                             ('build_status', 'build_status_sha256'),
                             ('stage_manifest', 'stage_manifest_sha256')):
        require(receipt['host_physx'][receipt_key] == dependency[key]['sha256'],
                'Clean receipt host manifest identity differs: ' + key)
    require(receipt['host_physx']['provenance_root'] == dependency['provenance_root']
            and Path(receipt['host_physx']['stage']).resolve() == Path(dependency['physx_stage']['path']).resolve(),
            'Clean receipt host provenance paths differ')
    expected_mode = ('clean_sapien_full_source_with_verified_prebuilt_physx_host'
                     if reused else 'clean_full_source')
    require(mode['mode'] == receipt['build_mode'] == expected_mode,
            'Clean receipt build mode disagrees with host dependency reuse')
    require(isinstance(mode['clean_full_build_scope'], str) and bool(mode['clean_full_build_scope']),
            'Clean build scope is missing')
    host_root = provenance if provenance_override else Path(dependency['provenance_root'])
    host = _host(host_root, receipt, receipt['host_physx']['stage_manifest_sha256'], dependency)
    return {'build_mode': receipt['build_mode'], 'clean_full_build_executed': True,
            'clean_full_build_scope': mode['clean_full_build_scope'],
            'host_dependency_sha256': dependency_record['sha256'],
            'physx_host_dependency_reused': reused,
            'source_files_verified': count, 'reused_objects_verified': {'native': 0, 'pybind': 0},
            'prepared_source_canonical_sha256': canonical_sha(source), 'host_physx': host}


def validate_sdk(sdk_root, base_root=None, provenance_root=None, expected_artifact_sha256=None, base_recipe_root=None):
    """Return a separate native-lock identity; never retrofit the portable-v5 schema."""
    sdk = Path(sdk_root).resolve(strict=True)
    provenance = Path(provenance_root).resolve(strict=True) if provenance_root else sdk.parent
    artifact_path = sdk / 'artifact.json'
    receipt = read(artifact_path)
    if expected_artifact_sha256:
        check(artifact_path, expected_artifact_sha256, 'expected SDK artifact')
    require(receipt['capabilities']['native_gpu_lock_sync_patch_version']['expected'] == 1
            and receipt['capabilities']['indexed_gpu_apply_patch_version']['expected'] == 1,
            'Both native capability contracts are required')
    require(receipt['source_commit'] == '731622eac5b140b320076c8a1b6eb4b553c3ccd4', 'Unexpected SAPIEN revision')
    mode = receipt['incremental_link']
    if mode.get('clean_full_build_executed') is False and 'source_build_origin' in mode:
        build = _incremental(sdk, provenance, receipt, base_root, base_recipe_root)
        wheel = sdk / 'wheels' / Path(receipt['wheel']).name
    elif mode.get('clean_full_build_executed') is True:
        build = _clean(sdk, provenance, receipt, provenance_root is not None)
        wheels = list((sdk / 'sapien-clean/wheels').glob('*.whl'))
        require(len(wheels) == 1, 'Expected one clean build wheel')
        wheel = wheels[0]
    else:
        raise IdentityError('Unsupported native-lock provenance schema')
    runtime, gpu = sdk / 'runtime', sdk / 'physx-runtime'
    for name, digest in receipt['native_files'].items():
        require(Path(name).name == name, 'Native binary name contains a path')
        check(runtime / 'sapien' / name, digest, 'SDK native binary ' + name)
    for name, digest in receipt['physx_gpu']['dll_sha256'].items():
        require(Path(name).name == name, 'GPU binary name contains a path')
        check(gpu / name, digest, 'PhysX GPU binary ' + name)
    entries = _wheel_runtime(wheel, runtime, receipt)
    expected_loaded = dict(receipt['native_files'])
    expected_loaded.update(receipt['physx_gpu']['dll_sha256'])
    required_loaded = {'sapien.dll', 'svulkan2.dll', 'simsense.dll'}
    required_loaded.update(name for name in receipt['native_files'] if name.endswith('.pyd'))
    required_loaded.update(receipt['physx_gpu']['dll_sha256'])
    require(len([name for name in required_loaded if name.endswith('.pyd')]) == 1, 'Expected exactly one CPython extension')
    return {'schema': 'dexarena-native-lock-sdk-identity-v1', 'version': receipt['version'],
            'artifact_sha256': sha(artifact_path), 'lock_sha256': receipt['lock_sha256'],
            'source_commit': receipt['source_commit'], 'wheel_sha256': receipt['wheel_sha256'],
            'sdk_root': str(sdk), 'artifact': str(artifact_path), 'runtime': str(runtime),
            'physx_runtime': str(gpu), 'native_files': receipt['native_files'],
            'physx_gpu': receipt['physx_gpu'], 'wheel_record_entries_verified': entries,
            'expected_loaded': expected_loaded, 'required_loaded': sorted(required_loaded),
            'build': build, 'capabilities_expected': {key: value['expected'] for key, value in receipt['capabilities'].items()},
            'build_acceptance': receipt['acceptance'], 'native_modules_imported': False,
            'runtime_acceptance': 'Separate actual loaded-path/SHA, native capability and GPU/task evidence required'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-root', required=True, type=Path)
    parser.add_argument('--base-root', type=Path)
    parser.add_argument('--provenance-root', type=Path)
    parser.add_argument('--base-recipe-root', type=Path)
    parser.add_argument('--artifact-sha256')
    args = parser.parse_args()
    print(json.dumps(validate_sdk(args.sdk_root, args.base_root, args.provenance_root,
                                  args.artifact_sha256, args.base_recipe_root), indent=2))


if __name__ == '__main__':
    main()
