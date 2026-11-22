"""Opt-in repaired default raster shaders and a stable sample-cup pass policy."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

_SHADER_PACKS = {}

# SAPIEN 3.0.3, commit 731622eac5b140b320076c8a1b6eb4b553c3ccd4,
# and the identical sources checked out with CRLF for the Windows wheel.
_SOURCE_FRAGMENT_SHA256 = (
    {
        'gbuffer.frag': '5fafc347dd9244be3ee5238f7e1fd04b2beaf90cab645a5f447c7b48ab55f7cf',
        'gbuffer1.frag': '05e9c8ba41019ce89c793c51b514d8d9ffc9701c8de8f7020554afe648233c33',
    },
    {
        'gbuffer.frag': '96bf1cd4330f90e29d7456b90dfea9bc8c8a839458a32e31ae525863072028fb',
        'gbuffer1.frag': '574745cffd6dd6b86ed9ecd2d94c7533fbe5b0cc0fdf36606efa5e1c5c5ab982',
    },
)


def reviewed_source_fragments(folder):
    """Return exact reviewed bytes for one complete default shader pair."""
    fragments = {name: (folder / name).read_bytes() for name in _SOURCE_FRAGMENT_SHA256[0]}
    observed = {name: hashlib.sha256(data).hexdigest() for name, data in fragments.items()}
    if observed not in _SOURCE_FRAGMENT_SHA256:
        files = ', '.join(f'{name}={digest}' for name, digest in observed.items())
        raise ValueError(f'Unreviewed SAPIEN default shader pair: {files}')
    return fragments


def hashes(folder):
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob('*')) if path.is_file()}


class PipetteRendering:
    def __init__(self, config):
        import sapien
        from mani_skill.render.shaders import PREBUILT_SHADER_CONFIGS

        if set(config) - {'enabled'}:
            raise ValueError('pipette_rendering supports only the enabled option')
        root = Path(__file__).resolve().parents[2]
        catalog = json.loads((root / 'assets/appearance/objects/pipette_transfer/catalog.json').read_text(encoding='utf-8'))
        self.bias = float(catalog['rendering']['tip_depth_bias_ndc'])
        source = Path(sapien.__file__).parent / 'vulkan_shader'
        fragments = reviewed_source_fragments(source / 'default')
        source_hashes = {f'{name}/{key}': value for name in ('default', 'common')
                         for key, value in hashes(source / name).items()}
        constants = ('layout(constant_id=20) const int pipetteTipRenderId=-1;\n'
                     'layout(constant_id=21) const float pipetteDepthBias=0.0;\n\n')
        patch = ('\n  gl_FragDepth = gl_FragCoord.z;\n'
                 '  if (int(inSegmentation.x) == pipetteTipRenderId)\n'
                 '    gl_FragDepth = clamp(gl_FragCoord.z-pipetteDepthBias, 0.0, 1.0);')
        patch_sha = hashlib.sha256((constants + patch).encode()).hexdigest()
        tree_sha = hashlib.sha256(json.dumps(source_hashes, sort_keys=True).encode()).hexdigest()
        key = (tree_sha, patch_sha)
        if key not in _SHADER_PACKS:
            directory = tempfile.TemporaryDirectory(prefix='dexarena-pipette-render-')
            output = Path(directory.name)
            for name in ('default', 'common'):
                shutil.copytree(source / name, output / name)
            for name, data in fragments.items():
                path = output / 'default' / name
                text = data.decode('utf-8').replace('\r\n', '\n')
                if text.count('#define SET_NUM 0') != 1 or text.count('void main() {') != 1:
                    raise ValueError(f'Unexpected shader patch anchors: {name}')
                text = text.replace('#define SET_NUM 0', constants + '#define SET_NUM 0', 1)
                text = text.replace('void main() {', 'void main() {' + patch, 1)
                path.write_text(text, encoding='utf-8')
            _SHADER_PACKS[key] = (directory, output, hashes(output))
        self.directory, output, generated_hashes = _SHADER_PACKS[key]
        if hashes(output) != generated_hashes:
            raise RuntimeError('The cached Pipette shader package was modified')
        self.shader_config = copy.deepcopy(PREBUILT_SHADER_CONFIGS['default'])
        self.shader_config.shader_pack = str(output / 'default')
        self.identity = {'shader_pack': 'default', 'bias_ndc': self.bias,
                         'source_shader_sha256': source_hashes,
                         'source_shader_tree_sha256': tree_sha,
                         'generated_shader_sha256': copy.deepcopy(generated_hashes),
                         'patch_sha256': patch_sha,
                         'glass_pass_policy': 'Sample cup uses fixed transparent gbuffer pass before rendering batches',
                         'scope': 'Repaired default shaders plus sample-cup fixed transparent pass; unchanged PBR/geometry/physics'}

    def prepare_objects(self, base):
        import sapien.render as sr
        modes = []
        if base.sample_cup is not None:
            for raw in base.sample_cup._objs:
                body = raw.find_component_by_type(sr.RenderBodyComponent)
                if body is None or len(body.render_shapes) != 57:
                    raise RuntimeError('Pipette render repair sample-cup layout differs')
                modes.append(int(body.shading_mode))
                body.shading_mode = 1
        self.identity['sample_cup_original_shading_modes'] = modes
        self.identity['sample_cup_fixed_shading_modes'] = [1] * len(modes)

    def camera_overrides(self, overrides):
        result = copy.deepcopy(overrides or {})
        if result.get('shader_pack', 'default') != 'default' or 'shader_config' in result:
            raise ValueError('Pipette render repair requires its reviewed default shader configuration')
        result.pop('shader_pack', None)
        for value in result.values():
            if isinstance(value, dict):
                if value.get('shader_pack', 'default') != 'default' or 'shader_config' in value:
                    raise ValueError('Pipette render repair requires default camera shaders')
                value.pop('shader_pack', None)
                value['shader_config'] = self.shader_config
        result['shader_config'] = self.shader_config
        return result

    def prepare_formats(self):
        import sapien
        # Custom shader paths bypass ManiSkill's named-default format setup.
        for name in ('Color', 'ColorRaw', 'PositionSegmentation'):
            sapien.render.set_picture_format(name, 'r32g32b32a32sfloat')

    def bind_cameras(self, base):
        import sapien.render as sr

        if base.pipette_stand is None:
            raise RuntimeError('Pipette render repair needs the native stand')
        ids = []
        for raw in base.pipette_stand._objs:
            body = raw.find_component_by_type(sr.RenderBodyComponent)
            if body is None or len(body.render_shapes) != 47:
                raise RuntimeError('Pipette render repair stand layout differs')
            ids.append(int(body.render_shapes[4].per_scene_id))
        for sensor in (*base._sensors.values(), *base.scene.human_render_cameras.values()):
            cameras = sensor.camera._render_cameras
            if len(cameras) != len(ids):
                raise RuntimeError('Pipette render repair camera environment count differs')
            for camera, render_id in zip(cameras, ids):
                camera.set_property('pipetteTipRenderId', render_id)
                camera.set_property('pipetteDepthBias', self.bias)
        self.identity['tip_render_ids'] = ids

    def close(self):
        # Shared immutable packages remain valid for every scene until process exit.
        # TemporaryDirectory finalizers remove them when the process exits.
        pass
