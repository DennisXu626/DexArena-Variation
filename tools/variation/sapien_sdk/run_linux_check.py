"""Probe or validate approved task checkers with a private native Linux SAPIEN wheel."""

import argparse
import ast
import ctypes
from email import message_from_bytes
from hashlib import sha256
import importlib.metadata
import importlib.machinery
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import runpy
import shutil
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import BuiltinFunctionType
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CHECKERS = {
    'furniture': ('check_furniture_appearance.py', 'FurnitureAssembly',
                  ('LayFlatPanel', 'InsertRail', 'FastenScrew'), 'original ManiSkill RGB cameras'),
    'pipette': ('check_pipette_runtime.py', 'PipetteTransfer', ('AspirateLiquid', 'DispenseLiquid'),
                'original ManiSkill RGB cameras with explicit opt-in repaired default shaders'),
    'office': ('check_office_devices_runtime.py', 'OfficeDesk', ('OpenLaptop', 'TypeKeys', 'ClickMouse'),
               'original ManiSkill CUDA RGB cameras'),
    'nut': ('check_nut_bolt_runtime.py', 'NutBolt', ('PickBolt', 'SeatNut', 'TurnNut'),
            'standard ManiSkill CUDA RGB'),
}
NUT_CASES = {'PickBolt': (7, 'base_camera'), 'SeatNut': (1, 'wrist_camera'), 'TurnNut': (26, 'human')}
PIPETTE_OPTICAL = 'check_pipette_rendering.py'
OPTICAL_VIEWS = (-.002, -.001, 0., .001, .002, -.004, .004)
OPTICAL_CAMERAS = {'base_camera': [2, 480, 640, 3], 'human': [2, 720, 1280, 3]}
INDEXED = 'indexed_gpu_apply_patch_version'
NUT_LOCK_SYNC = 'native_gpu_lock_sync_patch_version'
COACD_LINUX_FILES = {
    'coacd/__init__.py': 'c5730c358f078af8fe2d017fa7cb374f1511c2cca3da8fb15b25171786f01044',
    'coacd/lib_coacd.so': '4c7134a59d9e96278d291703042063ecb52dd4c00a3574a5ee2c6de45fb0b487',
}
ARTIFACT_SCHEMA = 'dexarena-sapien-linux-artifact-v1'
RUNTIME_SCHEMA = 'dexarena-sapien-linux-runtime-v1'
SHARED_OBJECT = re.compile(r'\.so(?:\.[a-zA-Z0-9_-]+)*$')
NATIVE_CORE = 'sapien.libs/libsapien.so'
NATIVE_RENDERER = 'sapien.libs/libsvulkan2.so'
NUT_PATCH_DIR = 'native_lock/recipe-v6/patches'


def digest(path):
    h = sha256()
    with path.open('rb') as data:
        for block in iter(lambda: data.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def need(condition, problem):
    if not condition:
        raise ValueError(problem)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def emit(path, object_):
    with path.open('x', encoding='utf-8', newline='\n') as file:
        json.dump(object_, file, indent=2)
        file.write('\n')


def identity(path):
    return {'path': str(path), 'sha256': digest(path)}


def native_elf(path):
    with path.open('rb') as binary:
        header = binary.read(20)
    return header.startswith(b'\x7fELF\x02\x01') and header[18:20] == b'\x3e\x00'


def nut_profile(repo, record, base, linux, lock_root, common):
    root = repo / 'tools/variation/sapien_sdk/native_lock'
    recipe = root / 'recipe-linux'
    lock_path = recipe / 'lock.json'
    need(lock_path.is_file() and isinstance(record.get('nut_linux'), dict),
         'Nut runtime requires the checked-in Nut recipe and its separate native-lock artifact')
    lock = read(lock_path)
    need(lock['schema'] == 'dexarena-nut-linux-recipe-lock-v1' and
         lock['sapien_commit'] == base['upstream']['commit'],
         'Nut Linux profile, source commit or lock is not compatible')
    profile = record['nut_linux']
    extra = {f'{NUT_PATCH_DIR}/{name}': sha for name, sha in lock['sapien_patches'].items()}
    need(profile['schema'] == 'dexarena-nut-linux-wheel-profile-v1' and
         profile['common_recipe_sha256'] == {name: digest(lock_root / name)
             for name in ('build_linux.py', 'prepare.py', 'lock.json', 'lock_linux.json')} and
         profile['nut_recipe_sha256'] == digest(recipe / 'build_nut_linux.py') and
         profile['nut_lock_sha256'] == digest(lock_path) and
         digest(recipe / lock['physx_patch']) == lock['physx_patch_sha256'] and
         profile['sapien_extra_patches'] == extra,
         'Nut artifact does not match the checked-in native lock and visibility recipe')
    expected_physx = {key: lock['physx'][other] for key, other in (
        ('version', 'version'), ('file', 'gpu_file'), ('sha256', 'gpu_sha256'),
        ('archive_sha256', 'gpu_archive_sha256'))}
    need(all(linux['physx_gpu'][key] == expected for key, expected in expected_physx.items()) and
         tuple(lock['sapien_patches']) == ('0300-native-lock-sync.patch', '0310-batched-render-visibility.patch') and
         all(digest(root.parent / name) == expected for name, expected in extra.items()),
         'Unrecognized Nut PhysX or additive patches')
    host_hash = profile['host_stage_sha256']
    need(record['private_host_stage_sha256'] == host_hash and
         all(re.fullmatch('[0-9a-f]{64}', value) for value in
             (host_hash, record['private_cmake_inputs_sha256'], record['native_cmake_cache_sha256'])) and
         record.get(NUT_LOCK_SYNC) == 1,
         'Nut private host link receipt or native capability is missing')
    patches = [*common, *({'file': name, 'sha256': value} for name, value in extra.items())]
    need(record['prepared_inputs']['nut_ordered_patch_sha256'] == [p['sha256'] for p in patches],
         'Nut source patch stack differs from the audited ordered profile')
    return lock['version'], patches


def verify_artifact(wheel, artifact, physx_dir, lock_root=HERE, *, checker='furniture', repo=REPO):
    linux_lock = lock_root / 'lock_linux.json'
    base_lock = lock_root / 'lock.json'
    base, linux, record = map(read, (base_lock, linux_lock, artifact))
    base_sha = digest(base_lock)
    need(linux['schema'] == 'dexarena-sapien-linux-lock-v1' and linux['base_lock_sha256'] == base_sha,
         'Linux and common source locks do not agree')
    need(record.get('schema') == ARTIFACT_SCHEMA and
         record.get('source_commit') == base['upstream']['commit'] and
         record.get('lock_sha256') == base_sha and record.get('linux_lock_sha256') == digest(linux_lock) and
         record.get('recipe_sha256') == digest(lock_root / 'build_linux.py') and
         record.get(INDEXED) == 1,
         'Build receipt does not match the Linux SDK and source locks')
    patches = [p for p in base['patches'] if p['group'] in linux['patch_groups']]
    need({p['group'] for p in patches} == {'common', 'packaging'} and
         {p['file'] for p in patches if p['group'] == 'common'} ==
         {'patches/0001-indexed-gpu-apply.patch', 'patches/0002-indexed-capability.patch'},
         'The Linux build plan does not include both native indexed writeback patches')
    need(all(digest(lock_root / p['file']) == p['sha256'] for p in patches),
         'Applied patches do not match the locked bytes')
    version = linux['version']
    native_rows = record['patches']
    if checker == 'nut':
        version, patches = nut_profile(repo, record, base, linux, lock_root, patches)
    else:
        need('nut_linux' not in record, 'Nut build only supports its separate native-lock checker')
    patch_bytes = lambda p: {'file': p['file'], 'sha256': p['sha256']}
    need([patch_bytes(p) for p in native_rows] == [patch_bytes(p) for p in patches] and
         record.get('version') == version, 'Wheel version or ordered applied patch stack differs')
    need(record.get('wheel_sha256') == digest(wheel), 'Linux wheel SHA-256 does not match its receipt')
    physics = linux['physx_gpu']
    need(record['physx_gpu'] == physics,
         'PhysX in receipt does not match the official Linux lock')
    physx_input = physx_dir / physics['file']
    physx = physx_input.resolve(strict=True)
    need(physx == physx_input and physx.is_file() and digest(physx) == physics['sha256'],
         'Use the original official Linux PhysX GPU library in a private directory')
    need(native_elf(physx), 'PhysX GPU input is not native x86-64 ELF')
    return record, linux, physx


def member_paths(package):
    seen = set()
    files = {}
    for entry in package.infolist():
        path = PurePosixPath(entry.filename)
        name = path.as_posix()
        flags = stat.S_IFMT(entry.external_attr >> 16)
        need(not path.is_absolute() and name not in ('', '.') and '..' not in path.parts and
             '\\' not in entry.filename and ':' not in entry.filename and
             name not in seen and flags in (0, stat.S_IFREG, stat.S_IFDIR),
             f'Unsafe or duplicated wheel entry: {entry.filename}')
        top = path.parts[0]
        console_script = (top.startswith('sapien-') and top.endswith('.data') and
                          path.parts[1:] in ((), ('scripts',), ('scripts', 'sapien')))
        need(top in ('sapien', 'sapien.libs') or top.endswith('.dist-info') or console_script,
             f'Unexpected top-level wheel entry: {name}')
        seen.add(name)
        if not entry.is_dir():
            files[name] = entry
    return files


def version_py(data):
    tree = ast.parse(data.decode('utf-8'))
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == '__version__' for t in node.targets)]
    need(len(assignments) == 1, 'Expected one runtime version')
    return ast.literal_eval(assignments[0].value)


def check_staged_files(runtime, expected):
    actual = {}
    for path in runtime.rglob('*'):
        need(not path.is_symlink(), f'Symlink in private wheel staging: {path}')
        if path.is_file():
            name = path.relative_to(runtime).as_posix()
            need(name in expected, f'Unidentified file in private wheel staging: {name}')
            actual[name] = digest(path)
            need(actual[name] == expected[name], f'Private wheel file differs: {name}')
    need(set(actual) == set(expected), 'Private wheel staging lost one or more files')
    return actual


def wheel_inventory(wheel, record, linux, runtime, *, stage=False):
    """Check wheel ABI and record code, native binaries and render-package files."""
    abi = f'cp{sys.version_info.major}{sys.version_info.minor}'
    with ZipFile(wheel) as package:
        files = member_paths(package)
        metadata = [name for name in files if name.endswith('.dist-info/METADATA')]
        need(len(metadata) == 1, 'Expected one SAPIEN metadata file')
        info = message_from_bytes(package.read(metadata[0]))
        tags = message_from_bytes(package.read(metadata[0].rsplit('/', 1)[0] + '/WHEEL'))
        need(info['Name'].lower() == 'sapien' and info['Version'] == record['version'] ==
             version_py(package.read('sapien/version.py')) and
             tags['Root-Is-Purelib'].strip().lower() == 'false' and
             f'{abi}-{abi}-{linux["wheel_platform"]}' in tags.get_all('Tag', []),
             'Wheel is not the verified native Linux build for this interpreter')
        extensions = [p for p in files if p.startswith('sapien/pysapien') and p.endswith('.so')
                      and '/' not in p.removeprefix('sapien/') and
                      any(p == 'sapien/pysapien' + suffix for suffix in importlib.machinery.EXTENSION_SUFFIXES)]
        need(extensions == [record['native_binding']] and NATIVE_CORE in files and NATIVE_RENDERER in files,
             'Expected one matching native SAPIEN binding, core and renderer')
        expected = {}
        if stage:
            runtime.mkdir(parents=True, exist_ok=False)
        for name, entry in files.items():
            target = runtime / name
            if stage:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as src, target.open('xb') as out:
                    shutil.copyfileobj(src, out)
            with package.open(entry) as src:
                h = sha256()
                for block in iter(lambda: src.read(1 << 20), b''):
                    h.update(block)
            expected[name] = h.hexdigest()
    check_staged_files(runtime, expected)
    native = {name: sha for name, sha in expected.items() if SHARED_OBJECT.search(name)}
    python = {name: sha for name, sha in expected.items() if name.endswith('.py')}
    assets = {name: sha for name, sha in expected.items() if name not in native and name not in python}
    need(native == record['native_files'], 'Wheel ELF inventory does not match the build receipt')
    need(all(native_elf(runtime / name) for name in native), 'Non-x86-64 ELF native wheel member')
    return extensions[0], native, python, assets


def mapped_files(path=Path('/proc/self/maps')):
    """Read actual mappings (not just the planned search path)."""
    files = {}
    for line in path.read_text(encoding='utf-8', errors='surrogateescape').splitlines():
        cols = line.split(maxsplit=5)
        if len(cols) != 6 or not cols[5].startswith('/'):
            continue
        name = cols[5]
        path_name = Path(name.removesuffix(' (deleted)'))
        files[path_name] = files.get(path_name, False) or name.endswith(' (deleted)')
    return files


def is_driver_name(name):
    return name == 'libcuda.so' or name.startswith('libcuda.so.')


def system_driver(mapped, runtime, physx_dir):
    candidates = set()
    for path, deleted in mapped.items():
        if is_driver_name(path.name):
            need(not deleted, f'Deleted system CUDA driver: {path}')
            path = path.resolve(strict=True)
            need(not path.is_relative_to(runtime) and not path.is_relative_to(physx_dir)
                 and 'stubs' not in path.parts,
                 f'Expected the actual system CUDA driver, not a private library or toolkit stubs: {path}')
            candidates.add(path)
    need(len(candidates) == 1, f'Expected one actual mapped system CUDA driver: {sorted(candidates)}')
    return candidates.pop()


def vulkan_identity(mapped, *, required=True):
    loaders = set()
    for path, deleted in mapped.items():
        if path.name == 'libvulkan.so' or path.name.startswith('libvulkan.so.'):
            need(not deleted, f'Deleted Vulkan loader: {path}')
            loaders.add(path.resolve(strict=True))
    if not loaders and not required:
        return None
    need(len(loaders) == 1, f'Expected a single loaded Vulkan library: {sorted(loaders)}')
    return identity(loaders.pop())


def runtime_identity(runtime, binding, physx, expected, *, gpu, include_vulkan=False):
    mapped = mapped_files()
    native_paths = {}
    candidates = []
    for path, deleted in mapped.items():
        name = path.name
        is_wheel_file = path.is_relative_to(runtime)
        if name == physx.name or name.startswith('libPhysXGpu_64.so.'):
            need(not deleted, f'Deleted PhysX GPU mapping: {path}')
            candidates.append(path.resolve(strict=True))
        elif is_driver_name(name):
            continue
        elif name == 'libvulkan.so' or name.startswith('libvulkan.so.'):
            need(not deleted, f'Deleted Vulkan loader: {path}')
        elif is_wheel_file and SHARED_OBJECT.search(name):
            need(not deleted, f'Deleted wheel mapping: {path}')
            relative = path.relative_to(runtime).as_posix()
            need(relative in expected and digest(path) == expected[relative],
                 f'Unexpected mapped wheel library: {path}')
            native_paths['wheel/' + relative] = {'path': str(path), 'sha256': expected[relative]}
        elif name.startswith(('pysapien.', 'pysapien_pinocchio.', 'libsapien.', 'libsapien-',
                              'libsvulkan2.', 'libsvulkan2-', 'libsimsense.', 'libsimsense-',
                              'libpinocchio.', 'libpinocchio-', 'libOpenImageDenoise')):
            raise ValueError(f'Mapped SAPIEN native library outside the private wheel: {path}')
    required = ('wheel/' + binding, 'wheel/' + NATIVE_CORE, 'wheel/' + NATIVE_RENDERER)
    need(all(key in native_paths for key in required), 'Native binding, core or renderer is not mapped')
    result = {key: native_paths[key] for key in required}
    if gpu:
        need(set(candidates) == {physx}, f'Unexpected mapped PhysX GPU runtime: {candidates}')
        result['physx/' + physx.name] = identity(physx)
        result['driver/libcuda.so.1'] = identity(system_driver(mapped, runtime, physx.parent))
    if include_vulkan:
        result['vulkan/libvulkan.so.1'] = vulkan_identity(mapped)
    return result, native_paths


def capability(sapien, binary, name=INDEXED):
    marker = getattr(binary.physx, name, None)
    need(isinstance(marker, BuiltinFunctionType) and
         getattr(sapien.physx, name, None) is marker,
         'Native indexed GPU apply or lock capability is missing; '
         f'a stock binding or Python replacement cannot pass: {name}')
    version = marker()
    need(type(version) is int and version == 1, f'Native capability must equal 1: {name}')
    return version


def selected_result(directory, tasks, family='furniture'):
    result, manifest = (read(directory / name) for name in ('results.json', 'manifest.json'))
    _, prefix, _, capture_path = CHECKERS[family]
    ids = [f'{prefix}{task}-Sharpa-v1' for task in tasks]
    recorded_platform = manifest.get('platform', '')
    captures_match = (all(row.get('capture_path') == capture_path for row in result['tasks'])
                      if family == 'nut' else manifest.get('capture_path') == capture_path)
    need((recorded_platform == 'Linux' or
          (family in ('office', 'nut') and recorded_platform.startswith('Linux-'))) and
         manifest.get('sim_backend') == 'physx_cuda' and captures_match and
         manifest.get('num_envs') == 2 and manifest.get('task_ids') == ids and
         result.get('status') == result.get('formal_acceptance') == 'passed' and
         result.get('test_mode') == 'standard' and result.get('source_hashes_unchanged') is True and
         [(row['task'], row['status']) for row in result['tasks']] == [(t, 'passed') for t in tasks],
         f'Standard native Linux CUDA {family} checks did not pass')
    if family == 'pipette':
        need(manifest.get('rendering_probe_only') is False and
             manifest.get('pipette_rendering') == {'enabled': True},
             'Pipette must use its standard checker with explicit rendering options')
    if family == 'office' and 'ClickMouse' in tasks:
        mouse = next(row for row in result['tasks'] if row['task'] == 'ClickMouse')
        collision = mouse.get('mouse_collision_identity', {})
        need(mouse.get('mouse_collision_inputs_unchanged') is True
             and collision.get('coacd_version') == '1.0.14'
             and collision.get('coacd_files') == COACD_LINUX_FILES
             and len(collision.get('caches', {})) == 5,
             'ClickMouse requires the locked Linux CoACD release and all five unchanged collision caches')
    if family == 'nut':
        seed, camera = NUT_CASES[tasks[0]]
        need(len(tasks) == 1 and manifest.get('reset_seed') == seed and
             manifest.get('candidate_visibility_camera') == camera and
             manifest.get('native_capabilities') == {INDEXED: 1, NUT_LOCK_SYNC: 1} and
             result.get('sdk_native_files_unchanged') is True,
             'Nut must preserve both native capabilities and use the frozen task seed/camera')


def pipette_optical_result(directory, task):
    """Check run scope and coverage; raw attachments are audited separately."""
    result, manifest = (read(directory / name) for name in ('results.json', 'manifest.json'))
    need(task in CHECKERS['pipette'][2], 'Unknown Pipette optical task')
    need(manifest.get('task_id') == f'PipetteTransfer{task}-Sharpa-v1' and
         manifest.get('sim_backend') == 'physx_cuda' and manifest.get('num_envs') == 2 and
         manifest.get('gpu_memory_profile') == 'two_env' and
         manifest.get('control_steps') == manifest.get('physics_steps') == 0 and
         all(isinstance(manifest.get(key), dict) and manifest[key]
             for key in ('files', 'external_files')) and
         'tools/variation/' + PIPETTE_OPTICAL in manifest['files'],
         'Pipette optical manifest differs from the standalone two-environment CUDA probe')
    need(result.get('status') == 'passed' and result.get('task') == task and
         result.get('formal_acceptance') == 'NOT TESTED: supplementary rendering only' and
         result.get('completed_constructions') == 28 and
         result.get('control_steps') == result.get('physics_steps') == 0 and
         all(result.get(key) is True for key in (
             'source_hashes_unchanged', 'external_hashes_unchanged', 'asset_hashes_unchanged')),
         'Pipette optical run did not complete exactly 28 fresh constructions and zero control/physics steps')
    views = [(seed, view, dx) for seed in (7, 19) for view, dx in enumerate(OPTICAL_VIEWS)]
    cases = result.get('cases', [])
    need(isinstance(cases, list) and len(cases) == 28 and
         [(row.get('seed'), row.get('view'), row.get('translation_x_m'), row.get('label'))
          for row in cases] == [(seed, view, dx, label) for seed, view, dx in views
                                for label in ('native_depth', 'fixed_depth')],
         'Pipette optical construction coverage differs from the seed/view/bias matrix')
    for case in cases:
        rendering = case.get('rendering', {})
        bias = rendering.get('bias_ndc')
        rgb = case.get('standard_rgb', {})
        need(case.get('status') == 'passed' and case.get('native_buffer_errors') == [] and
             case.get('control_steps') == case.get('physics_steps') == 0 and
             rendering.get('shader_pack') == 'default' and
             'sample_cup_fixed_shading_modes' in rendering and
             rendering['sample_cup_fixed_shading_modes'] == ([1, 1] if task == 'AspirateLiquid' else []) and
             type(bias) in (int, float) and 0 < bias <= 2e-6 and
             case.get('bias_ndc') == (0. if case['label'] == 'native_depth' else bias) and
             all(rgb.get(cam, {}).get('dtype') == 'torch.uint8' and
                 rgb.get(cam, {}).get('device', '').startswith('cuda:') and
                 rgb.get(cam, {}).get('shape') == shape for cam, shape in OPTICAL_CAMERAS.items()),
             'Pipette optical case lacks clean standard CUDA RGB or reviewed rendering metadata')
    comparisons = result.get('comparisons', [])
    need(isinstance(comparisons, list) and len(comparisons) == 56 and
         [(row.get('seed'), row.get('view'), row.get('translation_x_m'),
           row.get('camera'), row.get('env_idx')) for row in comparisons] ==
         [(seed, view, dx, camera, env) for seed, view, dx in views
          for camera in OPTICAL_CAMERAS for env in (0, 1)],
         'Pipette optical comparison coverage differs from the original camera/environment matrix')
    measured = set()
    for row in comparisons:
        count = row.get('common_tip_pixels')
        need(type(count) is int and count >= 0 and
             row.get('rgb_changed_values_outside_tip_union') == 0 and
             row.get('depth_changed_values_outside_tip_union') == 0 and
             row.get('fixed_cap_interior_missing_pixels') == 0,
             'Pipette optical report changes a protected region')
        if count:
            need(row.get('position_xyz_max_abs_delta_common_tip') == 0 and
                 row.get('position_raw_max_abs_delta_common_tip') == 0,
                 'Pipette optical report changes common target positions')
            measured.add((row['camera'], row['env_idx']))
        else:
            need(isinstance(row.get('visibility_limit'), str) and row['visibility_limit'],
                 'Pipette optical report omits the no-common-pixel visibility limit')
    need(measured == {(cam, env) for cam in OPTICAL_CAMERAS for env in (0, 1)},
         'Pipette optical report is missing measured common pixels for one camera/environment')


def checker_argv(args, output):
    if args.pipette_optical:
        name = PIPETTE_OPTICAL
        options = ['--task', args.task[0], '--gpu-memory-profile', 'two_env']
    else:
        name, _, default_tasks, _ = CHECKERS[args.checker]
        tasks = args.task or default_tasks
        options = [part for task in tasks for part in ('--task', task)]
        if args.checker == 'nut':
            seed, camera = NUT_CASES[tasks[0]]
            options.extend(('--seed', str(seed), '--visibility-camera', camera))
        if args.two_env_memory:
            options.extend(('--gpu-memory-profile', 'two_env'))
    checker = (args.repo_root / 'tools/variation' / name).resolve(strict=True)
    need(checker.is_relative_to(args.repo_root), 'The selected checker is outside the repository')
    return checker, [str(checker), '--approved-runtime', '--sim-backend', 'physx_cuda',
                     '--output', str(output), *options]


def run_child(args, wheel, artifact, output, runtime, physx_dir):
    record, linux, physx = verify_artifact(wheel, artifact, physx_dir,
                                           checker=args.checker, repo=args.repo_root)
    artifact_sha = digest(artifact)
    binding, native, python, assets = wheel_inventory(wheel, record, linux, runtime)
    need(not any(name == 'sapien' or name.startswith('sapien.') for name in sys.modules),
         'SAPIEN was already imported before activating the private wheel')
    sys.path[:0] = [str(runtime), str(args.repo_root)]
    import sapien
    import sapien.pysapien as binary
    from tools.variation.sapien_sdk import linux_render_receipt

    need(Path(sapien.__file__).resolve() == runtime / 'sapien/__init__.py' and
         Path(binary.__file__).resolve() == runtime / binding and
         sapien.__version__ == importlib.metadata.version('sapien') == record['version'],
         'Actual import does not match the private wheel path or version')
    names = (INDEXED, NUT_LOCK_SYNC) if args.checker == 'nut' else (INDEXED,)
    capabilities = {name: capability(sapien, binary, name) for name in names}
    need(sapien.physx.version() == record['physx_gpu']['version'],
         'The actual PhysX SDK version does not match the Linux lock')
    checker_runs = args.approved_runtime
    execution = 'capability_probe'
    if checker_runs:
        execution = 'supplementary_optical' if args.pipette_optical else 'standard_cuda'
    loader_handles = []
    if checker_runs:
        need(not sapien.physx.is_gpu_enabled(), 'GPU PhysX was already enabled before identity checks')
        # Do not call SAPIEN's cache/downloader. The process is exec'ed with the
        # pinned PhysX and the private driver alias ahead of inherited paths.
        driver = ctypes.CDLL('libcuda.so.1', ctypes.RTLD_GLOBAL)
        driver_alias = ctypes.CDLL('libcuda.so', ctypes.RTLD_GLOBAL)
        need(driver._handle == driver_alias._handle and
             system_driver(mapped_files(), runtime, physx_dir) == args._driver,
             'SAPIEN unversioned CUDA lookup would not load the same verified system driver')
        loader_handles.extend((driver, driver_alias))
        loader_handles.append(ctypes.CDLL(str(physx), ctypes.RTLD_LOCAL))
        binary.physx._enable_gpu()
        need(sapien.physx.is_gpu_enabled(), 'SAPIEN failed to enable native PhysX GPU')
    before, loaded_before = runtime_identity(runtime, binding, physx, native, gpu=checker_runs)
    code = 1
    after = loaded_after = {}
    python_after = assets_after = {}
    manifest_sha = results_sha = None
    vulkan = None
    vulkan_samples = 0
    succeeded = False

    def observe_vulkan():
        nonlocal vulkan, vulkan_samples
        observed = vulkan_identity(mapped_files())
        need(vulkan is None or observed == vulkan, 'Mapped Vulkan loader changed between RGB readbacks')
        vulkan = observed
        vulkan_samples += 1

    try:
        if checker_runs:
            checker, sys.argv = checker_argv(args, output)
            sys.path.insert(0, str(checker.parent))
            try:
                with linux_render_receipt.observe_render_readbacks(observe_vulkan):
                    runpy.run_path(str(checker), run_name='__main__')
            except SystemExit as e:
                code = 0 if e.code is None else (e.code if isinstance(e.code, int) else 1)
            else:
                code = 0
            if code:
                return code
            if args.pipette_optical:
                pipette_optical_result(output, args.task[0])
            else:
                selected_result(output, args.task or CHECKERS[args.checker][2], args.checker)
            manifest_sha, results_sha = [digest(output / name) for name in ('manifest.json', 'results.json')]
        else:
            output.mkdir(parents=True)
            code = 0
        need(capabilities == {name: capability(sapien, binary, name) for name in names} and
             digest(artifact) == artifact_sha and
             digest(wheel) == record['wheel_sha256'], 'SDK capability, artifact or wheel changed during the run')
        after, loaded_after = runtime_identity(runtime, binding, physx, native, gpu=checker_runs)
        if checker_runs:
            need(vulkan_samples > 0, 'No mapped Vulkan loader observed at a validated RGB readback')
            remaining = vulkan_identity(mapped_files(), required=False)
            need(remaining is None or remaining == vulkan, 'Mapped Vulkan loader changed after RGB capture')
        files = check_staged_files(runtime, {**native, **python, **assets})
        python_after = {relative: files[relative] for relative in python}
        assets_after = {relative: files[relative] for relative in assets}
        need(before == after, 'Mapped native runtime changed during the run')
        succeeded = True
        print(json.dumps({'status': 'passed', 'execution': execution, 'version': sapien.__version__,
                          **capabilities}), flush=True)
        return 0
    finally:
        if output.is_dir():
            emit(output / 'private_sdk.json', {
                'schema': RUNTIME_SCHEMA, 'status': 'passed' if succeeded else 'failed',
                'platform': 'Linux', 'execution': execution, 'private_sdk': True,
                'checker': args.checker if checker_runs else None,
                'returncode': 0 if succeeded else (code or 1),
                'artifact_sha256': artifact_sha, 'wheel_sha256': record['wheel_sha256'],
                'version': sapien.__version__, 'physx_version': sapien.physx.version(),
                **capabilities, 'wheel_native_files': native,
                'before': before, 'after': after, 'binaries_unchanged': succeeded and before == after,
                'python_before': python, 'python_after': python_after,
                'python_source_unchanged': succeeded and python == python_after,
                'wheel_assets_before': assets, 'wheel_assets_after': assets_after,
                'wheel_assets_unchanged': succeeded and assets == assets_after,
                'manifest_sha256': manifest_sha, 'results_sha256': results_sha,
                'loaded_wheel_before': loaded_before, 'loaded_wheel_after': loaded_after,
                'vulkan_loader': vulkan,
                'vulkan_observation': {'phase': 'validated_rgb', 'samples': vulkan_samples} if vulkan_samples else None,
                'launcher_sha256': digest(Path(__file__)),
                'render_observer_sha256': digest(Path(linux_render_receipt.__file__)),
            })


def child_command(args, wheel, artifact, output, physx_dir, driver=None):
    # Resolve all user paths in the parent before changing cwd to the repository.
    cmd = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--_child',
           '--repo-root', str(args.repo_root), '--wheel', str(wheel), '--artifact', str(artifact),
           '--physx-gpu-dir', str(physx_dir), '--output', str(output),
           '--checker', args.checker, '--probe-only' if args.probe_only else '--approved-runtime']
    for task in args.task or ():
        cmd.extend(('--task', task))
    if args.two_env_memory:
        cmd.append('--two-env-memory')
    if args.pipette_optical:
        cmd.append('--pipette-optical')
    if driver is not None:
        cmd.extend(('--_driver', str(driver)))
    return cmd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=REPO)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--physx-gpu-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checker', choices=tuple(CHECKERS), default='furniture',
                        help='The selected checker and task sources must be present in the checkout')
    parser.add_argument('--task', action='append', help='Repeat for a subset of the selected checker tasks')
    parser.add_argument('--two-env-memory', action='store_true',
                        help='Use the existing two_env capacity profile for Pipette or Office')
    parser.add_argument('--pipette-optical', action='store_true',
                        help='Run the supplementary Pipette optical probe for one task with two_env capacity')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--probe-only', action='store_true', help='Import private Linux wheel and call native capability; no GPU work')
    mode.add_argument('--approved-runtime', action='store_true', help='Run standard GPU CUDA/RGB; obey project resource authorization')
    parser.add_argument('--_child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--_driver', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'AMD64'):
        parser.error('This launcher requires x86-64 Linux; Windows resources require run_check.py')
    if args.task is not None and (args.probe_only or len(set(args.task)) != len(args.task)
                                 or not set(args.task) <= set(CHECKERS[args.checker][2])):
        parser.error('--task requires --approved-runtime and unique IDs of the selected checker')
    if args.checker == 'nut' and args.approved_runtime and len(args.task or ()) != 1:
        parser.error('Nut standard CUDA requires exactly one --task per run (fixed task seed/camera)')
    if args.pipette_optical and (args.checker != 'pipette' or not args.approved_runtime or len(args.task or ()) != 1):
        parser.error('--pipette-optical requires --checker pipette --approved-runtime and exactly one --task')
    if args.two_env_memory and (args.probe_only or args.checker == 'furniture'):
        parser.error('--two-env-memory requires a standard Pipette, Office or Nut GPU run')
    args.repo_root = args.repo_root.resolve(strict=True)
    wheel, artifact, physx_dir = (p.resolve(strict=True) for p in (args.wheel, args.artifact, args.physx_gpu_dir))
    output = args.output.resolve()
    need(not output.exists(), 'Choose a new output directory')
    runtime = output.with_name(output.name + '-private-runtime')
    if bool(args._driver) != bool(args._child and args.approved_runtime):
        parser.error('Unexpected driver identity option')
    if args._child:
        return run_child(args, wheel, artifact, output, runtime, physx_dir)
    need(not runtime.exists(), 'Choose a new output prefix; it also owns its private runtime directory')
    record, linux, _ = verify_artifact(wheel, artifact, physx_dir, checker=args.checker, repo=args.repo_root)
    wheel_inventory(wheel, record, linux, runtime, stage=True)
    env = dict(os.environ)
    env.pop('LD_PRELOAD', None)
    library_paths = [str(physx_dir), *filter(None, env.get('LD_LIBRARY_PATH', '').split(os.pathsep))]
    if args.probe_only:
        env['LD_LIBRARY_PATH'] = os.pathsep.join(library_paths)
        return subprocess.run(child_command(args, wheel, artifact, output, physx_dir),
                              cwd=args.repo_root, env=env, check=False).returncode
    # Keep this parent handle alive while the verified alias is in use.
    loader_handle = ctypes.CDLL('libcuda.so.1', ctypes.RTLD_LOCAL)
    driver = system_driver(mapped_files(), runtime, physx_dir)
    with TemporaryDirectory(prefix='.dexarena-cuda-', dir=output.parent) as alias_dir:
        # Locked SAPIEN calls dlopen("libcuda.so"); some hosts only ship the
        # .so.1 soname. Supply the alias in this child process, never the host.
        (Path(alias_dir) / 'libcuda.so').symlink_to(driver)
        env['LD_LIBRARY_PATH'] = os.pathsep.join([alias_dir, *library_paths])
        return subprocess.run(child_command(args, wheel, artifact, output, physx_dir, driver),
                              cwd=args.repo_root, env=env, check=False).returncode


if __name__ == '__main__':
    sys.exit(main())
