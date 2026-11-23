"""Exercise exact SDK shader inputs without importing SAPIEN or the simulator."""
import hashlib
from importlib.util import find_spec
from pathlib import Path
from runpy import run_path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FRAGMENTS = ('gbuffer.frag', 'gbuffer1.frag')
WINDOWS_GENERATED = {
    'default/gbuffer.frag': '632faefff4c67a14516e7ef2027b6bd8f25391690e949f606d0de962a4dbf56b',
    'default/gbuffer1.frag': 'fb4962010f83ac27b912ac0fb4c2425c35067b00fee60b72d214f226fd263927',
}
PATCH_SHA256 = 'd993ee637e4e09fd482d8bf1949ab1138b129d820f7eb5d752be612fb088e488'


class PipetteShaderSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sdk = find_spec('sapien')
        if sdk is None:
            raise unittest.SkipTest('The reviewed SAPIEN 3.0.3 shader files are required')
        folder = Path(sdk.origin).parent / 'vulkan_shader/default'
        cls.lf = {name: (folder / name).read_bytes().replace(b'\r\n', b'\n') for name in FRAGMENTS}
        cls.crlf = {name: data.replace(b'\n', b'\r\n') for name, data in cls.lf.items()}

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.runtime = run_path(str(ROOT / 'tasks/pipette_transfer/rendering.py'))
        self.preview = run_path(str(ROOT / 'tools/variation/pipette_render_fixes.py'))

    def tearDown(self):
        for directory, _, _ in self.runtime['_SHADER_PACKS'].values():
            directory.cleanup()

    def package(self, name, fragments):
        root = self.tmp / name / 'sapien'
        shaders = root / 'vulkan_shader'
        (shaders / 'default').mkdir(parents=True)
        (shaders / 'common').mkdir()
        for filename, data in fragments.items():
            (shaders / 'default' / filename).write_bytes(data)
        return SimpleNamespace(__file__=str(root / '__init__.py'))

    def render_repair(self, sdk):
        shaders = SimpleNamespace(PREBUILT_SHADER_CONFIGS={'default': SimpleNamespace(shader_pack='default')})
        with patch.dict(sys.modules, {'sapien': sdk, 'mani_skill.render.shaders': shaders}):
            return self.runtime['PipetteRendering']({'enabled': True})

    def test_runtime_and_preview_accept_the_lf_and_crlf_pairs(self):
        lf_generated = None
        for name, fragments in (('lf', self.lf), ('crlf', self.crlf)):
            with self.subTest(newlines=name):
                sdk = self.package(name, fragments)
                runtime = self.render_repair(sdk)
                target, preview = self.preview['depth_shader'](sdk, self.tmp / f'{name}-preview')
                source = {f'default/{file}': hashlib.sha256(data).hexdigest()
                          for file, data in fragments.items()}
                self.assertEqual(runtime.identity['source_shader_sha256'], source)
                self.assertEqual(preview['source_shader_sha256'], source)
                self.assertEqual(runtime.identity['patch_sha256'], PATCH_SHA256)
                self.assertEqual(preview['patch_sha256'], PATCH_SHA256)
                self.assertEqual(runtime.identity['generated_shader_sha256'], preview['generated_shader_sha256'])
                if sys.platform == 'win32':
                    self.assertEqual(preview['generated_shader_sha256'], WINDOWS_GENERATED)
                generated = {name: (target / name).read_bytes() for name in FRAGMENTS}
                if name == 'lf':
                    lf_generated = generated
                else:
                    self.assertEqual(generated, lf_generated)
                original = Path(sdk.__file__).parent / 'vulkan_shader/default'
                self.assertEqual({name: (original / name).read_bytes() for name in FRAGMENTS}, fragments)

    def test_runtime_and_preview_reject_mixed_and_unreviewed_bytes(self):
        mixed = {FRAGMENTS[0]: self.lf[FRAGMENTS[0]], FRAGMENTS[1]: self.crlf[FRAGMENTS[1]]}
        changed = {**self.lf, FRAGMENTS[0]: self.lf[FRAGMENTS[0]] + b'\n// unexpected content\n'}
        bare_cr = {**self.lf, FRAGMENTS[1]: self.lf[FRAGMENTS[1]].replace(b'\n', b'\r', 1)}
        for name, fragments in (('mixed', mixed), ('changed', changed), ('bare-cr', bare_cr)):
            with self.subTest(source=name):
                sdk = self.package(name, fragments)
                with self.assertRaisesRegex(ValueError, 'Unreviewed SAPIEN default shader pair'):
                    self.render_repair(sdk)
                output = self.tmp / f'{name}-preview'
                with self.assertRaisesRegex(ValueError, 'Unreviewed SAPIEN default shader pair'):
                    self.preview['depth_shader'](sdk, output)
                self.assertFalse(output.exists())
        self.assertFalse(self.runtime['_SHADER_PACKS'])


if __name__ == '__main__':
    unittest.main()
