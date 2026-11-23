"""CPU-only tests for the private Nut Linux recipe and solver binding gate."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

RECIPE = (Path(__file__).resolve().parents[1] / 'tools/variation/sapien_sdk/native_lock/recipe-linux')


def load(name):
    spec = importlib.util.spec_from_file_location(name, RECIPE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOST = load('build_host_linux')
with patch.dict(sys.modules, {'build_host_linux': HOST}):
    WHEEL = load('build_nut_linux')
with patch.dict(sys.modules, {'build_host_linux': HOST, 'build_nut_linux': WHEEL}), patch.object(sys, 'path', sys.path.copy()):
    PROBES = load('run_probes_linux')


class NutLinuxRecipeTests(unittest.TestCase):
    def test_wheel_cli_help_and_invalid_jobs_preserve_the_original_exit(self):
        cli = [sys.executable, '-B', str(RECIPE / 'build_nut_linux.py')]
        help_result = subprocess.run([*cli, '--help'], capture_output=True, text=True, check=True)
        self.assertIn('--common-recipe', help_result.stdout)
        bad_jobs = subprocess.run(
            [*cli, 'build', '--common-recipe', 'common', '--work-dir', 'wheel',
             '--host-work', 'host', '--jobs', '0'], capture_output=True, text=True, check=False)
        self.assertEqual(bad_jobs.returncode, 1)
        self.assertEqual(bad_jobs.stderr.strip(), 'Nut Linux wheel: --jobs must be positive')

    def test_patch_is_locked_to_real_setter(self):
        patch_path = RECIPE / HOST.LOCK['physx_patch']
        self.assertEqual(HOST.sha(patch_path), HOST.LOCK['physx_patch_sha256'])
        patch_text = patch_path.read_text(encoding='utf-8')
        self.assertIn('+\tupdateBodySim(*this);', patch_text)
        self.assertIn('+extern "C" unsigned ' + HOST.MARKER, patch_text)
        self.assertNotIn('RigidDynamicLockFlags(PxRigidDynamicLockFlags flags) {', '\n'.join(
            line for line in patch_text.splitlines() if line.startswith('+')))

    def test_wrong_archive_does_not_create_work_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'bad.zip'
            path.write_bytes(b'not a locked vendor archive')
            work = root / 'work'
            with self.assertRaisesRegex(ValueError, 'input archive SHA'):
                HOST.prepare(work, path, path, path)
            self.assertFalse(work.exists())

    def test_release_headers_check_bytes_and_generated_config_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'reference.zip'
            includes = root / 'include'
            includes.mkdir()
            (includes / 'PxPhysicsAPI.h').write_bytes(b'expected contents')
            with ZipFile(archive, 'w') as bundle:
                bundle.writestr('include/PxPhysicsAPI.h', b'expected contents')
                bundle.writestr('include/PxConfig.h', b'generated config')
            with patch.dict(HOST.PHYSX, {'header_count': 2, 'generated_header_sha256': HOST.digest(b'generated config')}):
                self.assertEqual(set(HOST.reference_headers(archive, includes)), {'PxPhysicsAPI.h'})
                (includes / 'PxPhysicsAPI.h').write_bytes(b'wrong contents')
                with self.assertRaisesRegex(ValueError, 'Public headers differ'):
                    HOST.reference_headers(archive, includes)

    def test_solver_gate_rejects_wrong_architecture_or_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            solver = Path(directory) / HOST.PHYSX['gpu_file']
            prefix = b'\x7fELF\x02\x01\x01' + bytes(9)
            solver.write_bytes(prefix + struct.pack('<HH', 3, 183))
            with self.assertRaisesRegex(ValueError, 'x86-64'):
                HOST.check_gpu_abi(solver)
            solver.write_bytes(prefix + struct.pack('<HH', 3, 62))
            with self.assertRaisesRegex(ValueError, 'solver SHA'):
                HOST.check_gpu_abi(solver)

    def test_marker_in_separate_object_is_rejected(self):
        marker = f'libPhysX_static_64.a:ScBodyCore.cpp.o:000010 T {HOST.MARKER}'
        setter = f'libPhysX_static_64.a:ScBodyCore.cpp.o:000020 T {HOST.SETTER}...)'
        self.assertEqual(HOST.require_host_symbols(marker + '\n' + setter), 'ScBodyCore.cpp.o')
        with self.assertRaisesRegex(ValueError, 'share the ScBodyCore object'):
            HOST.require_host_symbols(marker.replace('ScBodyCore.cpp.o', 'stub.o') + '\n' + setter)

    def test_common_profile_uses_only_the_private_host_and_pinned_patch_order(self):
        names = ('0001-indexed-gpu-apply.patch', '0002-indexed-capability.patch', '0200-local-build-version.patch')
        physx = HOST.PHYSX
        common = SimpleNamespace(
            LOCK={'upstream': {'commit': HOST.LOCK['sapien_commit']}},
            PATCHES=[{'file': f'patches/{name}'} for name in names],
            GPU={'version': physx['version'], 'file': physx['gpu_file'],
                 'sha256': physx['gpu_sha256'], 'archive_sha256': physx['gpu_archive_sha256']},
            ARCHIVES=[{'name': 'physx5'}, {'name': 'oidn'}],
            LINUX={'version': 'shared'}, verify_locks=lambda: None,
            cmake_inputs=lambda work: 'set(FETCHCONTENT_FULLY_DISCONNECTED ON)',
            input_record=lambda work: {})
        stage = Path('private stage').resolve()
        WHEEL.configure_common(common, stage)
        self.assertEqual(tuple(Path(p['file']).name for p in common.PATCHES), names + tuple(HOST.LOCK['sapien_patches']))
        self.assertEqual(common.ARCHIVES, [{'name': 'oidn'}])
        self.assertEqual(common.LINUX['version'], HOST.LOCK['version'])
        self.assertIn(f'SAPIEN_PHYSX5_DIR [==[{stage.as_posix()}]==]', common.cmake_inputs(None))

    def test_non_linux_build_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'host'
            with patch.object(HOST.sys, 'platform', 'win32'), self.assertRaisesRegex(ValueError, 'native Linux'):
                HOST.build(work, 'cc', 'c++', 1)
            self.assertFalse(work.exists())

    def test_wheel_build_requires_both_markers_before_writing_receipt(self):
        work = Path('wheel-stage')
        compiler = {'version': 'verified compiler'}
        stage_record = {'compiler': {'cc': compiler, 'cxx': compiler}}

        def incomplete_build(build_root, jobs, *, capabilities):
            self.assertEqual((build_root, jobs), (work, 2))
            self.assertEqual(capabilities, WHEEL.CAPABILITIES)
            common.write_json(work / 'artifact.json', {capabilities[0]: 1})

        common = SimpleNamespace(build=incomplete_build, write_json=self.fail)
        with patch.object(HOST, 'compiler', return_value=compiler), patch.dict(WHEEL.os.environ):
            with self.assertRaisesRegex(ValueError, 'Native Nut probe receipt missing'):
                WHEEL.build(common, work, Path('host-stage'), stage_record, 2, {})

    def test_linux_fixtures_preserve_native_physics_and_raster_cases(self):
        original, lock = PROBES.fixture_source('lock')
        lock_body = 'snapshots, indices, axis_indices = '
        self.assertEqual(lock.split(lock_body, 1)[1], original.decode().split(lock_body, 1)[1])
        self.assertNotIn('ctypes.WinDLL', lock)
        self.assertIn('private = linux_runtime_path', lock)
        self.assertIn('return linux_native_identity()', lock)
        compile(lock, '<native fixture>', 'exec')
        original, raster = PROBES.fixture_source('raster')
        raster_body = '    captures = {}'
        observer = '        linux_observe_vulkan()\n'
        anchor = "        require(extra.per_scene_id != 0, 'Negative test object was not attached')\n"
        self.assertEqual(raster.count(observer), 1)
        self.assertIn(anchor + observer + "        result['status'] = 'passed'\n", raster)
        self.assertEqual(raster.replace(observer, '').split(raster_body, 1)[1],
                         original.decode().split(raster_body, 1)[1])
        self.assertIn('free, utilization = linux_gpu_resource()', raster)
        compile(raster, '<raster fixture>', 'exec')

    def test_raster_loader_records_live_vulkan_and_actual_teardown(self):
        live = {'path': '/system/libvulkan.so.1', 'sha256': 'a' * 64}
        changed = {**live, 'sha256': 'b' * 64}
        cases = (
            ('released', 'raster', True, None, None),
            ('still mapped', 'raster', True, live, None),
            ('changed', 'raster', True, changed, 'loader changed'),
            ('no live observation', 'raster', False, live, 'did not observe Vulkan'),
            ('lock', 'lock', False, None, None),
        )
        for label, kind, observe, teardown, error in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                artifact, wheel = root / 'artifact.json', root / 'fixture.whl'
                artifact.write_bytes(b'CPU contract artifact')
                wheel.write_bytes(b'CPU contract wheel')
                record = {'version': 'fixture', 'wheel_sha256': HOST.sha(wheel)}
                args = SimpleNamespace(kind=kind, output=root / 'run', common_runner=None, gpu_uuid='test',
                                       artifact=artifact, artifact_sha256=HOST.sha(artifact), _driver=None)
                binding = 'sapien/pysapien.so'
                marker = (1).bit_count
                physx = SimpleNamespace(version=lambda: HOST.PHYSX['version'], is_gpu_enabled=lambda: False,
                                        **dict.fromkeys(PROBES.CAPABILITIES, marker))
                sapien = ModuleType('sapien')
                binary = ModuleType('sapien.pysapien')
                sapien.__version__, sapien.physx, sapien.pysapien = 'fixture', physx, binary
                binary.__file__, binary.physx = str(args.output / 'private-runtime' / binding), physx
                phase = SimpleNamespace(name='before', mapping=None)
                events = []

                def transition(name, mapping):
                    phase.name, phase.mapping = name, mapping

                def vulkan_identity(mapping, *, required):
                    events.append((phase.name, required))
                    if required and mapping is None:
                        raise ValueError('Missing live Vulkan loader')
                    return mapping

                core = {'wheel/core': {'path': '/private/libsapien.so', 'sha256': 'c' * 64}}

                def runtime_identity(*args, gpu, include_vulkan=False):
                    self.assertTrue(gpu)
                    mapped = dict(core)
                    if include_vulkan:
                        mapped['vulkan/libvulkan.so.1'] = vulkan_identity(phase.mapping, required=True)
                    return mapped, {}

                common = SimpleNamespace(
                    wheel_inventory=lambda *args, **kwargs: (binding, {}, {}, {}),
                    runtime_identity=runtime_identity,
                    mapped_files=lambda: phase.mapping,
                    vulkan_identity=vulkan_identity,
                    check_staged_files=lambda *args: None,
                )
                lifecycle = ModuleType('test_raster_lifecycle')
                lifecycle.capture = lambda: transition('live', live)
                lifecycle.release = lambda: transition('teardown', teardown)
                fixture = ("import json, sys\nfrom pathlib import Path\nimport test_raster_lifecycle as scene\n"
                           "scene.capture()\n" + ("linux_observe_vulkan()\n" if observe else "") +
                           "scene.release()\noutput = Path(sys.argv[-1])\noutput.mkdir()\n"
                           "(output / 'results.json').write_text(json.dumps({'status': 'passed'}))\n"
                           "raise SystemExit(0)\n")
                modules = {'sapien': sapien, 'sapien.pysapien': binary, 'test_raster_lifecycle': lifecycle}
                with patch.dict(sys.modules, modules), patch.dict(PROBES.os.environ), \
                        patch.object(sys, 'path', sys.path.copy()), patch.object(sys, 'argv', []), \
                        patch.object(PROBES, 'gpu_resource', return_value=(4096, 0)), \
                        patch.object(PROBES, 'fixture_source', return_value=(b'fixture source', fixture)), \
                        patch.object(PROBES, 'load_common', return_value=common), \
                        patch.object(PROBES, 'load_cuda_driver'), patch.object(PROBES.ctypes, 'CDLL'), \
                        patch.object(PROBES.metadata, 'version', return_value='fixture'):
                    path = args.output / 'linux-loader-receipt.json'
                    if error:
                        with self.assertRaisesRegex(ValueError, error):
                            PROBES.run_fixture(args, record, {}, wheel, root / 'solver.so')
                        self.assertFalse(path.exists())
                        continue
                    PROBES.run_fixture(args, record, {}, wheel, root / 'solver.so')
                    receipt = json.loads(path.read_bytes())
                    self.assertEqual(receipt['mapped_before'], core)
                    self.assertEqual(receipt['mapped_after'],
                                     {**core, 'vulkan/libvulkan.so.1': teardown} if teardown else core)
                    if kind == 'raster':
                        self.assertEqual(receipt['vulkan_live'], live)
                        self.assertEqual(events, [('live', True), ('teardown', False)])
                    else:
                        self.assertNotIn('vulkan_live', receipt)
                        self.assertEqual(events, [])

    def test_cuda_alias_requires_the_same_mapped_driver_and_handle(self):
        expected = Path('/system/libcuda.so.1')
        common = SimpleNamespace(mapped_files=lambda: {}, system_driver=lambda *args: expected)
        shared = SimpleNamespace(_handle=7)
        with patch.object(PROBES.ctypes, 'CDLL', side_effect=(shared, shared)) as loader:
            self.assertEqual(PROBES.load_cuda_driver(common, Path('/wheel'), Path('/physx'), expected), (shared, shared))
            self.assertEqual([call.args[0] for call in loader.call_args_list], ['libcuda.so.1', 'libcuda.so'])
        with patch.object(PROBES.ctypes, 'CDLL', side_effect=(shared, SimpleNamespace(_handle=8))):
            with self.assertRaisesRegex(ValueError, 'same verified system driver'):
                PROBES.load_cuda_driver(common, Path('/wheel'), Path('/physx'), expected)
        with patch.object(PROBES.ctypes, 'CDLL', side_effect=(shared, shared)):
            with self.assertRaisesRegex(ValueError, 'same verified system driver'):
                PROBES.load_cuda_driver(common, Path('/wheel'), Path('/physx'), Path('/unverified/libcuda.so.1'))


if __name__ == '__main__':
    unittest.main()
