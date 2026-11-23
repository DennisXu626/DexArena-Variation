import ctypes
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.variation import check_office_devices_runtime as runtime


class OfficeCheckerPlatforms(unittest.TestCase):
    def test_linux_requires_native_gpu_and_indexed_capability(self):
        args = SimpleNamespace(experimental_windows_cuda=False, physx_gpu_dir=None)
        enable = Mock()
        physx = SimpleNamespace(is_gpu_enabled=lambda: True, _enable_gpu=enable)
        with patch.object(runtime.platform, 'system', return_value='Linux'), patch.object(
            runtime, 'sapien', SimpleNamespace(physx=physx), create=True
        ):
            with self.assertRaisesRegex(RuntimeError, 'indexed_gpu_apply_patch_version'):
                runtime.require_cuda_runtime(args)
            physx.indexed_gpu_apply_patch_version = lambda: 2
            with self.assertRaisesRegex(RuntimeError, 'indexed_gpu_apply_patch_version'):
                runtime.require_cuda_runtime(args)
            physx.indexed_gpu_apply_patch_version = lambda: 1
            physx.is_gpu_enabled = lambda: False
            with self.assertRaisesRegex(RuntimeError, 'verified SDK launcher'):
                runtime.require_cuda_runtime(args)
            physx.is_gpu_enabled = lambda: True
            self.assertEqual(runtime.require_cuda_runtime(args), [])
        enable.assert_not_called()

    def test_windows_keeps_original_dll_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(experimental_windows_cuda=True, physx_gpu_dir=Path(directory))
            physx = SimpleNamespace(is_gpu_enabled=Mock(side_effect=[False, True]), _enable_gpu=Mock(),
                                    indexed_gpu_apply_patch_version=lambda: 1)
            with patch.object(runtime.platform, 'system', return_value='Windows'), patch.object(
                runtime, 'sapien', SimpleNamespace(physx=physx), create=True
            ), patch.object(runtime.os, 'add_dll_directory', create=True) as add_dir, patch.object(
                ctypes, 'WinDLL', create=True
            ) as load:
                handles = runtime.require_cuda_runtime(args)
            add_dir.assert_called_once_with(str(Path(directory).resolve()))
            self.assertEqual([Path(call.args[0]).name for call in load.call_args_list],
                             ['PhysXDevice64.dll', 'PhysXGpu_64.dll'])
            self.assertEqual(handles, [add_dir.return_value, load.return_value, load.return_value])
            physx._enable_gpu.assert_called_once_with()

    def test_linux_rejects_missing_capability_before_starting_any_task(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'results'
            argv = ['check_office_devices_runtime.py', '--approved-runtime',
                    '--sim-backend', 'physx_cuda', '--output', str(output)]
            with patch.object(runtime.platform, 'system', return_value='Linux'), patch.object(
                runtime, 'configure_runtime'
            ), patch.object(runtime, 'sapien', SimpleNamespace(physx=SimpleNamespace()), create=True), patch.object(
                runtime, 'source_hashes', return_value={}
            ), patch.object(runtime, 'asset_hashes', return_value={}), patch.object(
                runtime, 'run_task'
            ) as run_task, patch.object(sys, 'argv', argv), patch.object(
                sys, 'path', sys.path.copy()
            ), patch('builtins.print'):
                self.assertEqual(runtime.main(), 1)
            run_task.assert_not_called()
            report = json.loads((output / 'results.json').read_bytes())
            self.assertEqual((report['status'], report['formal_acceptance'], report['tasks']),
                             ('failed', 'failed', []))
            self.assertIn('indexed_gpu_apply_patch_version', report['error'])
