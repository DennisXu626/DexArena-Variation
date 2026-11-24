"""GPU probe for the standard SAPIEN raster batch, run through the private SDK launcher."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import traceback


def require(condition, reason):
    if not condition:
        raise AssertionError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    sdk = os.environ.get('DEXARENA_NATIVE_LOCK_SDK_ROOT')
    artifact = os.environ.get('DEXARENA_NATIVE_LOCK_SDK_ARTIFACT')
    artifact_sha = os.environ.get('DEXARENA_NATIVE_LOCK_SDK_ARTIFACT_SHA256')
    loaded = json.loads(os.environ.get('DEXARENA_NATIVE_LOCK_SDK_LOADED_IDENTITY', '{}'))
    require(sdk and artifact and artifact_sha and loaded, 'Use launch_native_lock.py with the reviewed SDK receipt')
    require(sha(artifact) == artifact_sha, 'Launcher receipt SHA differs')
    free, utilization = map(int, subprocess.check_output(['nvidia-smi',
        '--query-gpu=memory.free,utilization.gpu', '--format=csv,noheader,nounits'], text=True).strip().split(','))
    require(free >= 2048 and utilization < 70, 'GPU start resource gate')
    out.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve()
    (out / 'probe_source.py').write_bytes(source.read_bytes())
    result = {'status': 'running', 'artifact_sha256': artifact_sha, 'probe_source_sha256': sha(source),
              'loaded_modules': loaded, 'resource_before': {'free_mib': free, 'utilization_percent': utilization},
              'scope': 'Standard Color/PositionSegmentation CUDA readback from two raster scenes, no task or physics simulation',
              'captures': {}, 'structure_negative': []}
    captures = {}

    import faulthandler
    import torch
    import sapien

    faulthandler.dump_traceback_later(90, exit=True)
    try:
        render = sapien.render
        render.set_camera_shader_dir('minimal')
        stream = torch.cuda.current_stream().cuda_stream
        scenes, systems, bodies, entities, cameras = [], [], [], [], []
        positions = []

        def add_box(scene, index, rgba, visible):
            material = render.RenderMaterial(base_color=rgba)
            shape = render.RenderShapeBox([.19, .19, .19], material)
            shape.set_gpu_pose_batch_index(index)
            body = render.RenderBodyComponent().attach(shape)
            body.visibility = float(visible)
            entity = sapien.Entity()
            entity.add_component(body)
            entity.pose = sapien.Pose([2., 8., 0.])
            scene.add_entity(entity)
            return entity, body

        def add_camera(scene, index):
            camera = render.RenderCameraComponent(80, 64)
            camera.set_gpu_pose_batch_index(index)
            entity = sapien.Entity()
            entity.add_component(camera)
            entity.pose = sapien.Pose([0., -8., 0.])
            scene.add_entity(entity)
            return entity, camera

        camera_entities = []
        for i in range(2):
            system = render.RenderSystem()
            scene = sapien.Scene([system])
            system.ambient_light = [.8, .8, .8]
            camera_y = .125 * i
            positions.extend([(2., camera_y - .375, 0.), (2., camera_y + .375, 0.),
                              (0., camera_y, 0.)])
            pairs = [add_box(scene, i * 3, [.85, .08, .03, 1.], True),
                     add_box(scene, i * 3 + 1, [.05, .6, .85, 1.], False)]
            camera_entity, camera = add_camera(scene, i * 3 + 2)
            scenes.append(scene)
            systems.append(system)
            entities.append([pair[0] for pair in pairs])
            bodies.append([pair[1] for pair in pairs])
            cameras.append(camera)
            camera_entities.append(camera_entity)

        raw_poses = torch.tensor([(*position, 1., 0., 0., 0.) for position in positions],
                                 device='cuda', dtype=torch.float32)
        handle = sapien.CudaArray(raw_poses)

        def make_render_group():
            group = render.RenderSystemGroup(systems)
            group.set_cuda_stream(stream)
            group.set_cuda_poses(handle)
            return group

        group = make_render_group()
        batch = group.create_camera_group(cameras, ['Color', 'PositionSegmentation'])
        object_arrays = [system.cuda_object_transforms for system in systems]
        camera_arrays = [camera._cuda_buffer for camera in cameras]

        def gpu_snapshot():
            return (
                [array.torch().detach().cpu().clone() for array in object_arrays],
                [array.torch().detach().cpu().clone() for array in camera_arrays],
            )

        cpu_warmup = gpu_snapshot()
        captures['cpu_warmup'] = {'actor_and_camera_buffers': cpu_warmup}
        ids = [[entity.per_scene_id for entity in scene_entities] for scene_entities in entities]
        expected = [0, 0]

        def capture(label):
            result['captures'][label] = {'phase': 'update_render', 'visible_representation': list(expected)}
            group.update_render()
            torch.cuda.synchronize()
            before = gpu_snapshot()
            input_poses = raw_poses.cpu().clone()
            captures[label] = {'before': before, 'cuda_poses': input_poses}
            result['captures'][label]['phase'] = 'take_picture'
            batch.take_picture()
            torch.cuda.synchronize()
            color = batch.get_picture_cuda('Color').torch().detach().cpu().clone()[..., :3]
            seg = batch.get_picture_cuda('PositionSegmentation').torch().detach().cpu().clone()[..., 3]
            after = gpu_snapshot()
            counts = [[int((seg[i] == entity_id).sum()) for entity_id in ids[i]] for i in range(2)]
            captures[label].update(after=after, rgb=color, segmentation=seg)
            result['captures'][label] = {'phase': 'validate', 'object_pixel_counts': counts,
                'visible_representation': list(expected),
                'object_buffers': [array.ptr for array in object_arrays],
                'camera_buffers': [array.ptr for array in camera_arrays]}
            for i in range(2):
                torch.testing.assert_close(before[0][i][:2, 3, :3], input_poses[i * 3:i * 3 + 2, :3],
                                           rtol=0, atol=0, msg=f'{label}: actor GPU translation')
                torch.testing.assert_close(before[1][i][44:47], input_poses[i * 3 + 2, :3],
                                           rtol=0, atol=0, msg=f'{label}: camera GPU translation')
                require(torch.equal(before[0][i], after[0][i]), f'{label}: env{i} actor buffer overwritten')
                require(torch.equal(before[1][i], after[1][i]), f'{label}: env{i} camera buffer overwritten')
                require(systems[i].cuda_object_transforms.ptr == object_arrays[i].ptr,
                        f'{label}: env{i} actor buffer was reallocated')
                require(cameras[i]._cuda_buffer.ptr == camera_arrays[i].ptr,
                        f'{label}: env{i} camera buffer was reallocated')
                require(counts[i][expected[i]] > 0 and counts[i][1 - expected[i]] == 0,
                        f'{label}: env{i} wrong visible representation {counts[i]}')
            result['captures'][label]['phase'] = 'passed'
            return color

        first = capture('first_gpu_frame')
        for i in range(2):
            require(not torch.equal(cpu_warmup[0][i], captures['first_gpu_frame']['before'][0][i]),
                    f'env{i} actor shadow must differ from GPU pose')
            require(not torch.equal(cpu_warmup[1][i][:16], captures['first_gpu_frame']['before'][1][i][:16]),
                    f'env{i} camera shadow must differ from GPU pose')

        for i in range(2):
            other = 1 - i
            saved = raw_poses[i * 3:i * 3 + 3].clone()
            raw_poses[i * 3, 1] += .125
            raw_poses[i * 3 + 1, 1] -= .125
            raw_poses[i * 3 + 2, 1] += .125
            bodies[i][0].visibility, bodies[i][1].visibility = 0., 1.
            expected[i] = 1
            changed = capture(f'env{i}_threaded')
            require(not torch.equal(first[i], changed[i]), f'env{i}: selected RGB did not change')
            require(torch.equal(first[other], changed[other]), f'env{other}: unselected RGB changed')
            bodies[i][0].visibility, bodies[i][1].visibility = 1., 0.
            raw_poses[i * 3:i * 3 + 3].copy_(saved)
            expected[i] = 0
            restored = capture(f'env{i}_free_restored')
            require(torch.equal(first, restored), f'env{i}: restored pair of RGB frames differs')

        def require_guard(changed_group, label):
            try:
                changed_group.update_render()
            except RuntimeError as error:
                require('Modifying a scene (add/remove object/camera) is not allowed' in str(error), str(error))
                result['structure_negative'].append({'case': label, 'error': str(error)})
            else:
                raise AssertionError(f'{label}: structural change was accepted')

        extra, _ = add_box(scenes[0], -1, [.3, .3, .3, 1.], True)
        require_guard(group, 'add_object_env0')
        replacement_group = make_render_group()
        scenes[1].remove_entity(camera_entities[1])
        require_guard(replacement_group, 'remove_camera_env1')
        require(extra.per_scene_id != 0, 'Negative test object was not attached')
        result['status'] = 'passed'
    except Exception:
        result['status'] = 'failed'
        result['error'] = traceback.format_exc()
    finally:
        faulthandler.cancel_dump_traceback_later()
        if captures:
            torch.save(captures, out / 'captures.pt')
            result['captures_sha256'] = sha(out / 'captures.pt')
        result['artifact_and_loaded_files_unchanged'] = sha(artifact) == artifact_sha and all(
            sha(item['path']) == item['sha256'] for item in loaded.values())
        if not result['artifact_and_loaded_files_unchanged']:
            result['status'] = 'failed'
        (out / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'report': str(out / 'results.json')}))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
