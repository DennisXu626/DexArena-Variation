"""Compare the public reset frame with fixed-construction Pipette plate controls."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

from check_pipette_runtime import GPU_MEMORY_PROFILES, ROOT, TASKS


COLORS = ('jade', 'coral')
VIEWS = ('reset', 'next', 'human')
LAYOUTS = tuple((a, b) for a in COLORS for b in COLORS)


def digest(array):
    return hashlib.sha256(array.tobytes()).hexdigest()


def config(layout):
    return {'mode': 'explicit', 'per_env': {
        str(i): {'scheme_id': name} for i, name in enumerate(layout)}}


def stand_plate(base, row):
    import sapien

    adapter = base._pipette_appearance
    part, = [part for oid, role, part, _, _ in adapter.bindings[row]
             if (oid, role) == ('pipette_stand', 'base_plate')]
    actor = base.pipette_stand._objs[row]
    body = actor.find_component_by_type(sapien.render.RenderBodyComponent)
    shape, = [shape for shape in body.render_shapes if part in shape.parts]
    return part, int(shape.per_scene_id)


def plate_identity(adapter, row, plate, scheme):
    part, shape_id = plate
    assert adapter.schemes[row] == scheme
    texture = part.material.base_color_texture
    result = {'scheme': scheme, 'shape_id': shape_id, 'texture': None}
    if texture is None:
        assert scheme == 'original'
        return result
    pixels = np.asarray(texture.download())
    result['texture'] = {'sha256': digest(pixels), 'shape': list(pixels.shape),
                         'dtype': str(pixels.dtype)}
    if scheme != 'original':
        path = (ROOT / adapter.definitions['pipette_stand']['roles']['base_plate']
                ['candidate_color_texture']['directory'] / (scheme + '.png'))
        source = np.asarray(Image.open(path).convert('RGBA'))
        if pixels.dtype == np.float32:
            rgba = source.astype(np.float32) / 255
            rgb = rgba[..., :3]
            rgba[..., :3] = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
            np.testing.assert_allclose(pixels, rgba, rtol=0, atol=2e-7)
        else:
            np.testing.assert_array_equal(pixels, source[..., :pixels.shape[2]])
        result['texture']['source_png_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def save_view(folder, view, rgb, sensor, ids):
    import torch

    assert rgb.is_cuda and rgb.dtype == torch.uint8 and rgb.shape[0] == len(ids) == 2
    frames = rgb.detach().cpu().numpy().copy()
    for i, camera in enumerate(sensor.camera._render_cameras):
        seg = camera.get_picture_cuda('Segmentation').torch()
        assert seg.is_cuda
        shape_ids = seg[..., 0].detach().cpu().numpy().copy()
        assert np.any(shape_ids == ids[i]) and shape_ids.shape == frames[i].shape[:2]
        Image.fromarray(frames[i]).save(folder / f'{view}-{i}.png')
        np.savez_compressed(folder / f'{view}-{i}.npz', shape_ids=shape_ids)


def capture(task, initial, requested, output, seed):
    import gymnasium as gym
    import torch

    env = gym.make(f'PipetteTransfer{task}-Sharpa-v1', num_envs=2, sim_backend='physx_cuda',
                   obs_mode='rgb', render_mode='rgb_array', reconfiguration_freq=0,
                   sim_config={'gpu_memory_config': GPU_MEMORY_PROFILES['two_env'].copy()},
                   pipette_rendering={'enabled': True}, pipette_appearance={'enabled': True, **config(initial)})
    try:
        base = env.unwrapped
        assert base.scene.gpu_sim_enabled and base.scene._gpu_sim_initialized
        sensor = base._sensors['base_camera']
        human = base.scene.human_render_cameras['render_camera']
        for phase, layout, options in [('initial', initial, {}), ('switched', requested, {
                'pipette_appearance': config(requested)})]:
            folder = output / phase
            folder.mkdir(parents=True)
            obs, info = env.reset(seed=seed, options=options)
            # Copy reset-returned RGB before any other capture can reuse its buffer.
            first = obs['sensor_data']['base_camera']['rgb'].clone()
            plates = [stand_plate(base, i) for i in range(2)]
            ids = [shape_id for _, shape_id in plates]
            save_view(folder, 'reset', first, sensor, ids)
            following = base.get_obs(info=info)['sensor_data']['base_camera']['rgb']
            save_view(folder, 'next', following, sensor, ids)
            save_view(folder, 'human', env.render(), human, ids)
            # A GPU texture download may synchronize rendering. Inspect it only
            # after recording all three camera outputs for this reset.
            identity = [plate_identity(base._pipette_appearance, i, plates[i], scheme)
                        for i, scheme in enumerate(layout)]
            assert base.elapsed_steps.count_nonzero().item() == 0
            (folder / 'identity.json').write_text(json.dumps(identity, indent=2), encoding='utf-8')
    finally:
        env.close()
    del env, base, sensor, human, obs, first, following
    gc.collect()
    torch.cuda.empty_cache()


def masked_frame(folder, view, row):
    identity = json.loads((folder / 'identity.json').read_text())[row]
    with np.load(folder / f'{view}-{row}.npz') as image:
        mask = image['shape_ids'] == identity['shape_id']
    return mask, np.asarray(Image.open(folder / f'{view}-{row}.png'))[mask], identity['texture']


def check_frames(output):
    comparisons = []
    for view in VIEWS:
        for row in range(2):
            controls = {}
            for scheme in COLORS:
                name = scheme + '-' + scheme
                controls[scheme] = masked_frame(output / name / 'switched', view, row)
            mask, jade, first_texture = controls['jade']
            other_mask, coral, second_texture = controls['coral']
            np.testing.assert_array_equal(other_mask, mask)
            delta = np.abs(jade.astype(np.int16) - coral).max(axis=1)
            changed = int(np.count_nonzero(delta >= 8))
            assert first_texture['sha256'] != second_texture['sha256']
            metrics = {'view': view, 'environment': row, 'plate_pixels': len(delta),
                       'different_pixels': int(np.count_nonzero(delta)), 'delta_ge_8': changed,
                       'max_channel_delta': int(delta.max()), 'mean_max_channel_delta': float(delta.mean())}
            assert changed >= max(8, len(delta) // 2) and int(delta.max()) >= 16, metrics
            original_mask, original, _ = masked_frame(output / 'jade-jade' / 'initial', view, row)
            for layout in LAYOUTS:
                folder = output / '-'.join(layout)
                start_mask, start, _ = masked_frame(folder / 'initial', view, row)
                np.testing.assert_array_equal(start_mask, original_mask)
                np.testing.assert_array_equal(start, original)
                scheme = layout[row]
                ref_mask, ref, ref_texture = masked_frame(output / ('fixed-' + scheme) / 'switched', view, row)
                actual_mask, actual, actual_texture = masked_frame(folder / 'switched', view, row)
                np.testing.assert_array_equal(actual_mask, ref_mask)
                np.testing.assert_array_equal(actual, ref, err_msg=f'{view} row {row} {layout} vs fixed {scheme}')
                assert actual_texture == ref_texture
            comparisons.append(metrics)
    return comparisons


def run(task, output):
    output.mkdir(parents=True, exist_ok=False)
    for name in COLORS:
        capture(task, (name, name), (name, name), output / ('fixed-' + name), 7)
    for layout in LAYOUTS:
        capture(task, ('original', 'original'), layout, output / '-'.join(layout), 7)
    report = {'task': task, 'seed': 7, 'steps_between_resets': 0,
              'layouts': LAYOUTS, 'exact_fixed_candidate_match': True, 'comparisons': check_frames(output)}
    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', choices=TASKS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    import tasks  # Register the task environments.
    print(json.dumps(run(args.task, args.output)))
