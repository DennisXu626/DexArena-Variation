"""CPU contract checks for the Linux launcher, without loading SAPIEN or CUDA."""

from contextlib import redirect_stderr
import importlib.machinery
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import stat
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo


RUNNER = Path(__file__).resolve().parents[1] / 'tools/variation/sapien_sdk/run_linux_check.py'
spec = importlib.util.spec_from_file_location('furniture_linux_runner', RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def elf(text):
    # Only the x86-64 ELF header contract is modeled; these bytes cannot be loaded.
    return b'\x7fELF\x02\x01' + bytes(12) + b'\x3e\x00' + text


class PrivateWheelContracts(TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.wheel = self.root / 'sapien.whl'
        self.artifact = self.root / 'artifact.json'
        self.physx = self.root / 'physx/libPhysXGpu_64.so'
        self.physx.parent.mkdir()
        self.physx.write_bytes(elf(b'synthetic placeholder, not a library'))
        self.runtime = self.root / 'runtime'
        self.version = '3.0.3+dexarena.gpu1.linux1'
        self.binding = 'sapien/pysapien' + next(s for s in importlib.machinery.EXTENSION_SUFFIXES
                                                if s.endswith('.so')) if os.name != 'nt' else 'sapien/pysapien.so'
        self.platform_tag = 'manylinux_2_28_x86_64'
        self.abi = f'cp{sys.version_info.major}{sys.version_info.minor}'
        self.patches = []
        for relative, group in (
            ('patches/0001-indexed-gpu-apply.patch', 'common'),
            ('patches/0002-indexed-capability.patch', 'common'),
            ('patches/0200-local-build-version.patch', 'packaging'),
        ):
            p = self.root / relative
            p.parent.mkdir(exist_ok=True)
            p.write_bytes(relative.encode())
            self.patches.append({'file': relative, 'sha256': runner.digest(p), 'group': group})
        self.base = {'upstream': {'commit': '0' * 40}, 'patches': self.patches}
        self.write_json('lock.json', self.base)
        self.base_sha = runner.digest(self.root / 'lock.json')
        (self.root / 'build_linux.py').write_bytes(b'# fixture')
        self.linux = {'schema': 'dexarena-sapien-linux-lock-v1', 'base_lock_sha256': self.base_sha,
                      'version': self.version, 'wheel_platform': self.platform_tag,
                      'patch_groups': ['common', 'packaging'],
                      'physx_gpu': {'version': '105.1-test', 'file': self.physx.name,
                                    'sha256': runner.digest(self.physx)}}
        self.write_json('lock_linux.json', self.linux)
        self.write_wheel()
        self.record = {'schema': runner.ARTIFACT_SCHEMA, 'version': self.version, 'lock_sha256': self.base_sha,
                       'linux_lock_sha256': runner.digest(self.root / 'lock_linux.json'),
                       'source_commit': self.base['upstream']['commit'], 'patches': self.patches,
                       'wheel_sha256': runner.digest(self.wheel), 'physx_gpu': self.linux['physx_gpu'],
                       'native_binding': self.binding, 'recipe_sha256': runner.digest(self.root / 'build_linux.py'),
                       'indexed_gpu_apply_patch_version': 1,
                       'native_files': {name: runner.sha256(data).hexdigest()
                                        for name, data in self.native_files().items()}}
        self.write_json('artifact.json', self.record)

    def write_json(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding='utf-8')

    def write_wheel(self, *, tag=None, package_version=None, extra=None):
        name = 'sapien-' + self.version + '.dist-info'
        tag = tag or f'{self.abi}-{self.abi}-{self.platform_tag}'
        with ZipFile(self.wheel, 'w') as out:
            out.writestr(name + '/METADATA', f'Name: sapien\nVersion: {self.version}\n')
            out.writestr(name + '/WHEEL', f'Root-Is-Purelib: false\nTag: {tag}\n')
            out.writestr('sapien/__init__.py', '')
            out.writestr('sapien/version.py', f'__version__ = {package_version or self.version!r}\n')
            for filename, data in self.native_files().items():
                out.writestr(filename, data)
            out.writestr('sapien/vulkan_shader/default/shadow.frag', 'shader fixture')
            out.writestr('sapien/vulkan_library/nvidia_icd.json', '{}')
            out.writestr('sapien-' + self.version + '.data/scripts/sapien', 'console script fixture')
            if extra:
                out.writestr(extra, 'unexpected')

    def native_files(self):
        return {name: elf(name.encode()) for name in (self.binding, runner.NATIVE_CORE, runner.NATIVE_RENDERER)}

    def inventory(self, *, stage=False):
        # Windows lacks an ELF extension suffix; only the file/ABI contract is under test.
        with patch.object(runner.importlib.machinery, 'EXTENSION_SUFFIXES',
                          [self.binding.removeprefix('sapien/pysapien')]):
            return runner.wheel_inventory(self.wheel, self.record, self.linux, self.runtime, stage=stage)

    def verify(self):
        return runner.verify_artifact(self.wheel, self.artifact, self.physx.parent, lock_root=self.root)

    def test_exact_artifact_only_with_applied_common_patch_identities(self):
        self.assertEqual(self.verify()[2], self.physx)
        self.write_json('artifact.json', {**self.record, 'patches': self.patches[1:]})
        with self.assertRaisesRegex(ValueError, 'patch'):
            self.verify()
        self.write_json('artifact.json', self.record)
        (self.root / self.patches[0]['file']).write_bytes(b'changed C++ patch')
        with self.assertRaisesRegex(ValueError, 'patches'):
            self.verify()

    def test_wheel_and_physx_bytes_are_checked(self):
        self.physx.write_bytes(elf(b'wrong release'))
        with self.assertRaisesRegex(ValueError, 'official Linux PhysX'):
            self.verify()
        self.wheel.write_bytes(b'replaced')
        with self.assertRaisesRegex(ValueError, 'Wheel SHA|wheel SHA'):
            self.verify()

    def test_wheel_stage_checks_exact_python_and_elf_inventory(self):
        binding, native, python, assets = self.inventory(stage=True)
        self.assertEqual(binding, self.binding)
        self.assertEqual(native, self.record['native_files'])
        self.assertEqual(set(python), {'sapien/__init__.py', 'sapien/version.py'})
        self.assertIn('sapien/vulkan_shader/default/shadow.frag', assets)
        (self.runtime / 'sapien/version.py').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'wheel file differs'):
            self.inventory()

    def test_unidentified_staged_code_rejected(self):
        self.inventory(stage=True)
        (self.runtime / 'sapien/injected.py').write_text('1', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unidentified file'):
            self.inventory()

    def test_changed_shaders_and_vulkan_loader_descriptors_rejected(self):
        _, native, python, assets = self.inventory(stage=True)
        frozen = {**native, **python, **assets}
        for relative in ('sapien/vulkan_shader/default/shadow.frag', 'sapien/vulkan_library/nvidia_icd.json'):
            with self.subTest(entry=relative):
                file = self.runtime / relative
                data = file.read_bytes()
                file.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'wheel file differs'):
                    runner.check_staged_files(self.runtime, frozen)
                file.write_bytes(data)
        self.assertEqual(runner.check_staged_files(self.runtime, frozen), frozen)

    def test_incompatible_or_pure_wheel_rejected(self):
        self.write_wheel(tag='cp99-cp99-manylinux_2_28_x86_64')
        with self.assertRaisesRegex(ValueError, 'native Linux build'):
            self.inventory(stage=True)
        self.write_wheel(package_version='3.0.3')
        with self.assertRaisesRegex(ValueError, 'native Linux build'):
            self.inventory(stage=True)

    def test_unsafe_zip_member_rejected_before_private_root_creation(self):
        self.write_wheel(extra='../bad.py')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.inventory(stage=True)
        self.assertFalse(self.runtime.exists())
        self.write_wheel()
        with ZipFile(self.wheel, 'a') as out:
            entry = ZipInfo('sapien/link.py')
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            out.writestr(entry, 'target.py')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.inventory(stage=True)

    def test_only_mapped_native_binding_official_physx_and_system_driver(self):
        binding, native, _, _ = self.inventory(stage=True)
        libcuda = self.root / 'libcuda.so.1234'
        libcuda.write_bytes(b'synthetic')
        wheel = {self.runtime / name: False for name in native}
        loaded = {**wheel, self.physx: False, libcuda: False}
        with patch.object(runner, 'mapped_files', return_value=loaded):
            seen, _ = runner.runtime_identity(self.runtime, binding, self.physx, native, gpu=True)
            self.assertEqual(seen['physx/' + self.physx.name]['sha256'], runner.digest(self.physx))
            self.assertEqual(seen['driver/libcuda.so.1']['path'], str(libcuda))
        other = self.root / 'alternate' / self.physx.name
        other.parent.mkdir()
        other.write_bytes(self.physx.read_bytes())
        with patch.object(runner, 'mapped_files', return_value={**loaded, other: False}):
            with self.assertRaisesRegex(ValueError, 'mapped PhysX'):
                runner.runtime_identity(self.runtime, binding, self.physx, native, gpu=True)
        stubs = self.root / 'stubs' / libcuda.name
        stubs.parent.mkdir()
        stubs.write_bytes(b'wrong')
        with patch.object(runner, 'mapped_files',
                          return_value={**wheel, self.physx: False, stubs: False}):
            with self.assertRaisesRegex(ValueError, 'stubs'):
                runner.runtime_identity(self.runtime, binding, self.physx, native, gpu=True)
        for filename in ('libOpenImageDenoise.so.2.0.1', 'libsimsense-replaced.so', 'pysapien_pinocchio.so'):
            impostor = self.root / filename
            with patch.object(runner, 'mapped_files', return_value={**loaded, impostor: False}):
                with self.assertRaisesRegex(ValueError, 'outside the private wheel'):
                    runner.runtime_identity(self.runtime, binding, self.physx, native, gpu=True)

    def test_build_receipt_cannot_omit_core_identity(self):
        self.record['native_files'].pop(runner.NATIVE_CORE)
        with self.assertRaisesRegex(ValueError, 'ELF inventory'):
            self.inventory(stage=True)

    def test_nut_requires_recipe_link_provenance_and_ordered_two_additive_patches(self):
        root = self.root / 'tools/variation/sapien_sdk/native_lock'
        recipe = root / 'recipe-linux'
        recipe.mkdir(parents=True)
        patches = root / 'recipe-v6/patches'
        patches.mkdir(parents=True)
        extras = {}
        for name in ('0300-native-lock-sync.patch', '0310-batched-render-visibility.patch'):
            p = patches / name
            p.write_bytes(name.encode())
            extras[name] = runner.digest(p)
        for name in ('nut-host.patch', 'build_nut_linux.py'):
            (recipe / name).write_bytes(name.encode())
        (self.root / 'prepare.py').write_bytes(b'# fixture')
        self.linux['physx_gpu']['archive_sha256'] = 'b' * 64
        self.write_json('lock_linux.json', self.linux)
        physics = self.linux['physx_gpu']
        lock = {'schema': 'dexarena-nut-linux-recipe-lock-v1', 'version': '3.0.3+dexarena.gpu1.linuxnut1',
                'sapien_commit': self.base['upstream']['commit'], 'physx_patch': 'nut-host.patch',
                'physx_patch_sha256': runner.digest(recipe / 'nut-host.patch'), 'sapien_patches': extras,
                'physx': {k: physics[v] for k, v in (('version','version'), ('gpu_file','file'),
                                                    ('gpu_sha256','sha256'), ('gpu_archive_sha256','archive_sha256'))}}
        (recipe / 'lock.json').write_text(json.dumps(lock), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'separate native-lock artifact'):
            runner.nut_profile(self.root, self.record, self.base, self.linux, self.root, self.patches)
        stage_hash = 'c' * 64
        portable = {f'{runner.NUT_PATCH_DIR}/{name}': value for name, value in extras.items()}
        extra_rows = [{'file': name, 'sha256': value} for name, value in portable.items()]
        self.record.update({
            'version': lock['version'], 'linux_lock_sha256': runner.digest(self.root / 'lock_linux.json'),
            'patches': [*self.patches, *extra_rows],
            runner.NUT_LOCK_SYNC: 1, 'private_host_stage_sha256': stage_hash,
            'private_cmake_inputs_sha256': 'd' * 64, 'native_cmake_cache_sha256': 'e' * 64,
            'prepared_inputs': {'nut_ordered_patch_sha256': [p['sha256'] for p in [*self.patches, *extra_rows]]},
            'nut_linux': {'schema': 'dexarena-nut-linux-wheel-profile-v1', 'host_stage_sha256': stage_hash,
                          'common_recipe_sha256': {name: runner.digest(self.root / name)
                              for name in ('build_linux.py', 'prepare.py', 'lock.json', 'lock_linux.json')},
                          'nut_lock_sha256': runner.digest(recipe / 'lock.json'),
                          'nut_recipe_sha256': runner.digest(recipe / 'build_nut_linux.py'),
                          'sapien_extra_patches': portable},
        })
        self.write_json('artifact.json', self.record)
        runner.verify_artifact(self.wheel, self.artifact, self.physx.parent, self.root,
                               checker='nut', repo=self.root)
        with self.assertRaisesRegex(ValueError, 'only supports'):
            self.verify()
        self.record['prepared_inputs']['nut_ordered_patch_sha256'].reverse()
        self.write_json('artifact.json', self.record)
        with self.assertRaisesRegex(ValueError, 'ordered profile'):
            runner.verify_artifact(self.wheel, self.artifact, self.physx.parent, self.root,
                                   checker='nut', repo=self.root)


class ProbeContracts(TestCase):
    def test_vulkan_mapping_requires_one_live_loader_and_allows_teardown(self):
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            first = root / 'libvulkan.so.1'
            second = root / 'libvulkan.so.2'
            first.write_bytes(elf(b'live loader'))
            second.write_bytes(elf(b'other loader'))
            observed = runner.vulkan_identity({first: False})
            self.assertEqual(observed, {'path': str(first), 'sha256': runner.digest(first)})
            self.assertIsNone(runner.vulkan_identity({}, required=False))
            with self.assertRaisesRegex(ValueError, 'single loaded Vulkan'):
                runner.vulkan_identity({})
            with self.assertRaisesRegex(ValueError, 'single loaded Vulkan'):
                runner.vulkan_identity({first: False, second: False}, required=False)
            with self.assertRaisesRegex(ValueError, 'Deleted Vulkan loader'):
                runner.vulkan_identity({first: True}, required=False)

    def test_render_observer_is_scoped_to_the_checker_even_when_it_exits(self):
        spec = importlib.util.spec_from_file_location('render_receipt', runner.HERE / 'linux_render_receipt.py')
        observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(observer)
        calls = []
        observer.record_render_readback()
        with self.assertRaises(SystemExit):
            with observer.observe_render_readbacks(lambda: calls.append('live')):
                observer.record_render_readback()
                raise SystemExit(0)
        observer.record_render_readback()
        self.assertEqual(calls, ['live'])

    def test_child_arguments_survive_repository_cwd_change(self):
        root = Path.cwd() / 'input'
        args = SimpleNamespace(repo_root=root / 'other' / 'repo', checker='office',
                               probe_only=False, task=['TypeKeys'], two_env_memory=True,
                               pipette_optical=False)
        paths = {'--wheel': root / 'wheel.whl', '--artifact': root / 'artifact.json',
                 '--output': root / 'fresh directory', '--physx-gpu-dir': root / 'physics',
                 '--_driver': root / 'real-libcuda.so.123'}
        argv = runner.child_command(args, paths['--wheel'], paths['--artifact'], paths['--output'],
                                    paths['--physx-gpu-dir'], paths['--_driver'])
        self.assertEqual(argv[argv.index('--repo-root') + 1], str(args.repo_root))
        self.assertEqual(argv[argv.index('--task') + 1], 'TypeKeys')
        self.assertIn('--approved-runtime', argv)
        self.assertIn('--two-env-memory', argv)
        for flag, value in paths.items():
            self.assertEqual(Path(argv[argv.index(flag) + 1]), value)

    def test_python_marker_and_non_native_alias_are_rejected(self):
        for marker, alias in ((lambda: 1, lambda: 1), (sys.getrecursionlimit, lambda: 1)):
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, 'Native indexed'):
                runner.capability(
                    SimpleNamespace(physx=SimpleNamespace(indexed_gpu_apply_patch_version=alias)),
                    SimpleNamespace(physx=SimpleNamespace(indexed_gpu_apply_patch_version=marker)),
                )
        native = SimpleNamespace(physx=SimpleNamespace(indexed_gpu_apply_patch_version=sys.getrecursionlimit))
        with self.assertRaisesRegex(ValueError, 'must equal 1'):
            runner.capability(native, native)

    def test_only_standard_native_linux_cuda_is_accepted(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            tasks = ('LayFlatPanel',)
            manifest = {'platform': 'Linux', 'sim_backend': 'physx_cuda', 'num_envs': 2,
                        'task_ids': ['FurnitureAssemblyLayFlatPanel-Sharpa-v1'],
                        'capture_path': 'original ManiSkill RGB cameras'}
            result = {'status': 'passed', 'formal_acceptance': 'passed', 'test_mode': 'standard',
                      'source_hashes_unchanged': True, 'tasks': [{'task': 'LayFlatPanel', 'status': 'passed'}]}
            (directory / 'results.json').write_text(json.dumps(result), encoding='utf-8')
            for change in ({}, {'platform': 'Windows'}, {'sim_backend': 'physx_cpu'},
                           {'capture_path': 'diagnostic readback'}, {'num_envs': 1}):
                (directory / 'manifest.json').write_text(json.dumps({**manifest, **change}), encoding='utf-8')
                if change:
                    with self.assertRaisesRegex(ValueError, 'Standard native Linux'):
                        runner.selected_result(directory, tasks)
                else:
                    runner.selected_result(directory, tasks)

    def test_pipette_opt_in_and_office_native_appearances_are_checked(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            for family, task, platform in (
                ('pipette', 'AspirateLiquid', 'Linux'), ('office', 'TypeKeys', 'Linux-6.1.0-x86_64'),
            ):
                _, prefix, _, capture = runner.CHECKERS[family]
                result = {'status': 'passed', 'formal_acceptance': 'passed', 'test_mode': 'standard',
                          'source_hashes_unchanged': True, 'tasks': [{'task': task, 'status': 'passed'}]}
                manifest = {'platform': platform, 'sim_backend': 'physx_cuda', 'num_envs': 2,
                            'task_ids': [prefix + task + '-Sharpa-v1'], 'capture_path': capture,
                            'rendering_probe_only': False, 'pipette_rendering': {'enabled': True}}
                (directory / 'results.json').write_text(json.dumps(result), encoding='utf-8')
                (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
                runner.selected_result(directory, (task,), family)
                if family == 'pipette':
                    manifest['rendering_probe_only'] = True
                    (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'Pipette must use its standard checker'):
                        runner.selected_result(directory, (task,), family)

    def test_pipette_optical_mode_runs_the_standalone_tool_only(self):
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            checker = root / 'tools/variation/check_pipette_rendering.py'
            checker.parent.mkdir(parents=True)
            checker.touch()
            output = root / 'fresh optical output'
            args = SimpleNamespace(repo_root=root, checker='pipette', probe_only=False,
                                   task=['AspirateLiquid'], two_env_memory=False, pipette_optical=True)
            expected_opts = ['--approved-runtime', '--sim-backend', 'physx_cuda',
                             '--output', str(output), '--task', 'AspirateLiquid',
                             '--gpu-memory-profile', 'two_env']
            self.assertEqual(runner.checker_argv(args, output), (checker, [str(checker), *expected_opts]))
            child = runner.child_command(args, root / 'private.whl', root / 'artifact.json',
                                         output, root / 'physx', root / 'libcuda.so.1')
            self.assertIn('--pipette-optical', child)
            self.assertNotIn('--probe-only', child)
            self.assertNotIn('--experimental-windows-cuda', child)

    def test_pipette_optical_cli_rejects_other_tasks_and_preflight(self):
        required = ['--wheel', 'wheel', '--artifact', 'artifact', '--physx-gpu-dir', 'physx',
                    '--output', 'output', '--pipette-optical']
        for bad in (['--checker', 'pipette', '--probe-only'],
                    ['--checker', 'pipette', '--approved-runtime'],
                    ['--checker', 'pipette', '--approved-runtime', '--task', 'AspirateLiquid',
                     '--task', 'DispenseLiquid'],
                    ['--checker', 'office', '--approved-runtime', '--task', 'ClickMouse']):
            with self.subTest(args=bad), patch.object(sys, 'argv', ['runner', *required, *bad]), \
                    patch.object(runner.platform, 'system', return_value='Linux'), \
                    patch.object(runner.platform, 'machine', return_value='x86_64'), \
                    redirect_stderr(StringIO()) as errors, self.assertRaises(SystemExit) as exit_:
                runner.main()
            self.assertEqual(exit_.exception.code, 2)
            self.assertIn('--pipette-optical requires', errors.getvalue())

    def test_pipette_optical_requires_full_clean_cuda_matrix(self):
        # A complete synthetic receipt exercises only the launcher gate, not the optics.
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            task = 'DispenseLiquid'
            cases = []
            rows = []
            for seed in (7, 19):
                for view, offset in enumerate((-.002, -.001, 0., .001, .002, -.004, .004)):
                    keys = {'seed': seed, 'view': view, 'translation_x_m': offset}
                    for label, bias in (('native_depth', 0.), ('fixed_depth', 2e-6)):
                        cases.append({**keys, 'label': label, 'bias_ndc': bias, 'status': 'passed',
                                      'native_buffer_errors': [], 'control_steps': 0, 'physics_steps': 0,
                                      'standard_rgb': {
                                          name: {'dtype': 'torch.uint8', 'device': 'cuda:0', 'shape': shape}
                                          for name, shape in (('base_camera', [2, 480, 640, 3]),
                                                              ('human', [2, 720, 1280, 3]))},
                                      'rendering': {'shader_pack': 'default', 'bias_ndc': 2e-6,
                                                    'sample_cup_fixed_shading_modes': []}})
                    for camera in ('base_camera', 'human'):
                        for env in (0, 1):
                            rows.append({**keys, 'camera': camera, 'env_idx': env,
                                         'common_tip_pixels': 20, 'rgb_changed_values_outside_tip_union': 0,
                                         'depth_changed_values_outside_tip_union': 0,
                                         'fixed_cap_interior_missing_pixels': 0,
                                         'position_xyz_max_abs_delta_common_tip': 0,
                                         'position_raw_max_abs_delta_common_tip': 0})
            manifest = {'task_id': 'PipetteTransferDispenseLiquid-Sharpa-v1', 'sim_backend': 'physx_cuda',
                        'num_envs': 2, 'gpu_memory_profile': 'two_env', 'control_steps': 0, 'physics_steps': 0,
                        'files': {'tools/variation/check_pipette_rendering.py': 'hash'},
                        'external_files': {'mani_skill/__init__.py': 'hash'}}
            result = {'task': task, 'status': 'passed', 'formal_acceptance': 'NOT TESTED: supplementary rendering only',
                      'completed_constructions': 28, 'control_steps': 0, 'physics_steps': 0,
                      'cases': cases, 'comparisons': rows, 'source_hashes_unchanged': True,
                      'external_hashes_unchanged': True, 'asset_hashes_unchanged': True}

            def check_run(checked_manifest, checked_result):
                for filename, value in (('manifest.json', checked_manifest), ('results.json', checked_result)):
                    (directory / filename).write_text(json.dumps(value), encoding='utf-8')
                runner.pipette_optical_result(directory, task)

            check_run(manifest, result)
            first_masked = {**rows[0], 'common_tip_pixels': 0, 'visibility_limit': 'occluded'}
            check_run(manifest, {**result, 'comparisons': [first_masked, *rows[1:]]})
            for change, message in (
                ({'formal_acceptance': 'passed'}, 'zero control/physics'),
                ({'physics_steps': 1}, 'zero control/physics'),
                ({'cases': [cases[1], *cases[1:]]}, 'construction coverage'),
                ({'cases': [{**cases[0], 'native_buffer_errors': ['contact overflow']}, *cases[1:]]}, 'clean standard CUDA'),
                ({'comparisons': [rows[1], *rows[1:]]}, 'comparison coverage'),
                ({'comparisons': [{**first_masked, 'visibility_limit': ''}, *rows[1:]]}, 'visibility limit'),
                ({'comparisons': [{**rows[0], 'depth_changed_values_outside_tip_union': 1}, *rows[1:]]}, 'protected region'),
            ):
                with self.subTest(change=tuple(change), message=message), self.assertRaisesRegex(ValueError, message):
                    check_run(manifest, {**result, **change})
            with self.assertRaisesRegex(ValueError, 'standalone two-environment CUDA probe'):
                check_run({**manifest, 'sim_backend': 'physx_cpu'}, result)

    def test_office_mouse_requires_pinned_linux_collision_package_and_caches(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            task = 'ClickMouse'
            manifest = {'platform': 'Linux-6.1.0-x86_64', 'sim_backend': 'physx_cuda', 'num_envs': 2,
                        'task_ids': ['OfficeDeskClickMouse-Sharpa-v1'],
                        'capture_path': 'original ManiSkill CUDA RGB cameras'}
            collision = {'coacd_version': '1.0.14', 'coacd_files': runner.COACD_LINUX_FILES,
                         'caches': {str(index): {} for index in range(5)}}
            row = {'task': task, 'status': 'passed', 'mouse_collision_inputs_unchanged': True,
                   'mouse_collision_identity': collision}
            result = {'status': 'passed', 'formal_acceptance': 'passed', 'test_mode': 'standard',
                      'source_hashes_unchanged': True, 'tasks': [row]}
            (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (directory / 'results.json').write_text(json.dumps(result), encoding='utf-8')
            runner.selected_result(directory, (task,), 'office')
            for change in ({'coacd_files': {}}, {'caches': {'one': {}}}):
                row['mouse_collision_identity'] = {**collision, **change}
                (directory / 'results.json').write_text(json.dumps(result), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'locked Linux CoACD release'):
                    runner.selected_result(directory, (task,), 'office')

    def test_nut_standard_requires_both_native_capabilities_and_fixed_camera(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            manifest = {'platform': 'Linux-6.1.0-x86_64', 'sim_backend': 'physx_cuda', 'num_envs': 2,
                        'task_ids': ['NutBoltSeatNut-Sharpa-v1'], 'reset_seed': 1,
                        'candidate_visibility_camera': 'wrist_camera',
                        'native_capabilities': {runner.INDEXED: 1, runner.NUT_LOCK_SYNC: 1}}
            result = {'status': 'passed', 'formal_acceptance': 'passed', 'test_mode': 'standard',
                      'source_hashes_unchanged': True, 'sdk_native_files_unchanged': True,
                      'tasks': [{'task': 'SeatNut', 'status': 'passed', 'capture_path': 'standard ManiSkill CUDA RGB'}]}
            (directory / 'results.json').write_text(json.dumps(result), encoding='utf-8')
            (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            runner.selected_result(directory, ('SeatNut',), 'nut')
            for change in ({'reset_seed': 7}, {'native_capabilities': {runner.INDEXED: 1}}):
                (directory / 'manifest.json').write_text(json.dumps({**manifest, **change}), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Nut must preserve both'):
                    runner.selected_result(directory, ('SeatNut',), 'nut')


if __name__ == '__main__':
    main()
