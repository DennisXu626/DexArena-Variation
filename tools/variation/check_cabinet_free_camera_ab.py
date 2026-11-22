"""One production free-cap transition per group, with default task cameras."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

import numpy as np
from PIL import Image

TASK = 'CabinetPouringUnscrewCap-Sharpa-v1'
FORMAL_CAMERAS = ('base_camera', 'task_wrist_camera')
REVIEW_CAMERA = 'render_camera'
GROUPS = ('appearance_off', 'variant_9')
ACTORS = ('source_fixed', 'cap_fixed', 'cap_twin', 'mobile_base_link_6',
          'bottle_placement_region', 'cap_placement_region')
SEED = 7


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def array(tensor):
    return tensor.detach().cpu().numpy().copy()


def counts(pixels, names):
    ids, pixels_per_id = np.unique(pixels, return_counts=True)
    return [dict(entity_id=int(i), name=names.get(int(i), 'background' if i == 0 else 'unmapped'), pixels=int(n))
            for i, n in sorted(zip(ids, pixels_per_id), key=lambda pair: (-int(pair[1]), int(pair[0])))]


def compare_camera(before, after, actors_before, actors_after, camera_unchanged, bottle_pose_unchanged, names):
    before_body = before == actors_before['source_fixed']
    before_cap = before == actors_before['cap_fixed']
    after_body = after == actors_after['source_fixed']
    after_cap = after == actors_after['cap_twin']
    replacements = counts(after[before_body], names)
    excluded = {0, actors_after['source_fixed'], actors_after['cap_fixed'], actors_after['cap_twin']}
    other_foreground = sum(row['pixels'] for row in replacements if row['entity_id'] not in excluded)
    body_before, cap_before = int(before_body.sum()), int(before_cap.sum())
    body_after, cap_after = int(after_body.sum()), int(after_cap.sum())
    if not body_before or not cap_before:
        status, reasons = '不可判定', ['附着帧未同时看见固定瓶和附着盖']
    elif not camera_unchanged or not bottle_pose_unchanged:
        status, reasons = '不可判定', ['相机参数或固定瓶物理位姿改变']
    else:
        reasons = [message for condition, message in (
            (not body_after, '原可见固定瓶变为零像素'),
            (not cap_after, '附着盖原可见，预期自由盖为零像素'),
            (other_foreground * 2 > body_before, '其他前景占据原固定瓶区域的过半像素'),
        ) if condition]
        status = '复现' if reasons else '未复现'
        if not reasons:
            reasons = ['固定瓶和自由盖仍可见，原固定瓶区域未被其他前景占据过半']
    return dict(status=status, reasons=reasons, source_fixed_pixels=[body_before, body_after],
                cap_pixels=[cap_before, cap_after], before_cap='cap_fixed', after_cap='cap_twin',
                old_bottle_region_after=replacements, other_foreground_pixels=other_foreground,
                camera_unchanged=camera_unchanged, bottle_pose_unchanged=bottle_pose_unchanged)


def tensor_state(value):
    if isinstance(value, dict):
        return {name: tensor_state(item) for name, item in value.items()}
    values = np.ascontiguousarray(array(value))
    return dict(shape=list(values.shape), dtype=str(values.dtype),
                sha256=hashlib.sha256(values.tobytes()).hexdigest())


def actor_snapshot(task, body_type):
    markers = task.placement_region_markers
    selected = dict(source_fixed=task.source_fixed, cap_fixed=task.cap_fixed, cap_twin=task.cap_twin,
                    mobile_base_link_6=task.agent.robot.links_map['mobile_base_link_6'],
                    bottle_placement_region=markers['bottle'], cap_placement_region=markers['cap'])
    result = []
    for i, scene in enumerate(task.scene.sub_scenes):
        actors = {}
        for name in ACTORS:
            actor = selected[name]
            raw = actor._objs[i]
            entity = getattr(raw, 'entity', raw)
            render = entity.find_component_by_type(body_type)
            actors[name] = dict(id=int(entity.per_scene_id), name=entity.name,
                                pose_m_wxyz=array(actor.pose.raw_pose[i]).tolist(),
                                visibility=float(render.visibility) if render is not None else None)
        result.append(dict(actors=actors, names={int(entity.per_scene_id): entity.name for entity in scene.entities},
            flags={name: getattr(task, f'_{name}')[i].item() for name in (
                'active_bottle_rep', 'cap_detached', 'cap_free', 'stage_cap_turned', 'stage_cap_placed')}))
    return result


def camera_setup(sensor):
    config = sensor.config
    return dict(width=int(config.width), height=int(config.height), fov=config.fov,
                near=config.near, far=config.far, mounted=config.mount is not None,
                mount_name=getattr(config.mount, 'name', None),
                local_poses=[dict(p=c.local_pose.p.tolist(), q=c.local_pose.q.tolist())
                             for c in sensor.camera._render_cameras])


def capture_formal(task, info, mark_call):
    mark_call('task.get_obs(info=existing_info, unflattened=True)')
    observation = task.get_obs(info=info, unflattened=True)['sensor_data']
    missing = [name for name in FORMAL_CAMERAS if name not in observation]
    if missing:
        raise AssertionError(f"Missing formal cameras: {', '.join(missing)}")
    return {name: (observation[name], task.scene.sensors[name].get_params()) for name in FORMAL_CAMERAS}


def capture_supplement(task, mark_call):
    mark_call('scene.update_render(sensors=False, human=True); render_camera.capture()')
    task.scene.update_render(update_sensors=False, update_human_render_cameras=True)
    camera = task.scene.human_render_cameras[REVIEW_CAMERA]
    camera.capture()
    return camera.get_obs(rgb=True, depth=False, segmentation=True, position=False), camera.get_params()


def save_captures(folder, stage, captures, entities, records, pack_entity_ids):
    frames = {}
    for name, (data, params) in captures.items():
        rgb, seg = array(data['rgb'])[..., :3], array(data['segmentation'])[..., 0]
        assert rgb.dtype == np.uint8 and seg.dtype.kind in 'iu'
        assert rgb.shape[:3] == seg.shape and len(rgb) == len(seg) == 2
        if name in FORMAL_CAMERAS:
            assert seg.shape[1:] == (256, 256), (name, seg.shape)
        camera = {key: array(value) for key, value in params.items()}
        frames[name] = (rgb, seg, camera)
        destination = records[name] = []
        for i, scene in enumerate(entities):
            stem = f'{stage}_{name}_env{i}'
            rgb_path, seg_path = (folder/f'{stem}_{kind}.png' for kind in ('rgb', 'entity_ids'))
            Image.fromarray(rgb[i]).save(rgb_path)
            Image.fromarray(pack_entity_ids(seg[i])).save(seg_path)
            destination.append(dict(rgb=dict(file=rgb_path.name, sha256=sha256(rgb_path)),
                entity_ids=dict(file=seg_path.name, sha256=sha256(seg_path)), resolution=list(rgb[i].shape[1::-1]),
                camera={key: value[i].tolist() for key, value in camera.items()},
                foreground=counts(seg[i], scene['names'])[:12],
                visible_pixels={key: int(np.count_nonzero(seg[i] == actor['id']))
                                for key, actor in scene['actors'].items()}))
    return frames


def render_buffers(task, folder, stage):
    # The getter can prepare the buffer; read after both cameras have captured.
    result = []
    for i, scene in enumerate(task.scene.sub_scenes):
        row = dict(env_idx=i, source='RenderSystem.cuda_object_transforms',
                   mapping='Raw renderer order; no public per-shape transform row index in SAPIEN 3.0.3')
        try:
            tensor = scene.render_system.cuda_object_transforms.torch()
            if tensor.numel() * tensor.element_size() > 512 << 10:
                row['unavailable'] = 'buffer exceeds the diagnostic 512 KiB per-environment limit'
            else:
                data = array(tensor)
                path = folder/f'{stage}_env{i}_renderer_transforms.npy'
                np.save(path, data, allow_pickle=False)
                row.update(file=path.name, sha256=sha256(path), shape=list(data.shape), dtype=str(data.dtype))
        except (AttributeError, RuntimeError, TypeError, ValueError, BufferError) as exc:
            row['unavailable'] = f'{type(exc).__name__}: {str(exc)[:300]}'
        result.append(row)
    return result


def same_arrays(before, after):
    return set(before) == set(after) and all(np.allclose(before[k], after[k], atol=1e-6, rtol=0) for k in before)


def stage_frames(task, info, folder, label, record, flush, body_type, pack_entity_ids):
    record.update(calls=[], cameras={})

    def mark_call(call):
        record['calls'].append(call)
        flush()

    # No rendering in actor_snapshot; the formal observation is the first draw.
    entities = actor_snapshot(task, body_type)
    record['environments'] = entities
    formal = capture_formal(task, info, mark_call)
    frames = save_captures(folder, label, formal, entities, record['cameras'], pack_entity_ids)
    flush()
    extra = capture_supplement(task, mark_call)
    frames.update(save_captures(folder, label, {REVIEW_CAMERA: extra}, entities, record['cameras'], pack_entity_ids))
    flush()
    record['renderer_transform_readback_after_both_captures'] = render_buffers(task, folder, label)
    flush()
    return frames


def stage_flags(task):
    return {name: array(getattr(task, f'_{name}')).tolist() for name in (
        'active_bottle_rep', 'cap_detached', 'cap_free', 'stage_cap_turned', 'stage_cap_placed')}


def comparison(attached, free, before, after):
    result = {}
    prev, now = before['environments'][0], after['environments'][0]
    prev_ids = {name: value['id'] for name, value in prev['actors'].items()}
    now_ids = {name: value['id'] for name, value in now['actors'].items()}
    bottle_unchanged = np.allclose(prev['actors']['source_fixed']['pose_m_wxyz'],
                                   now['actors']['source_fixed']['pose_m_wxyz'], atol=1e-6, rtol=0)
    for name in (*FORMAL_CAMERAS, REVIEW_CAMERA):
        rgb_before, seg_before, params_before = attached[name]
        rgb_after, seg_after, params_after = free[name]
        camera_unchanged = [same_arrays({k:v[i] for k,v in params_before.items()},
                                       {k:v[i] for k,v in params_after.items()}) for i in (0, 1)]
        check = compare_camera(seg_before[0], seg_after[0], prev_ids, now_ids,
                               camera_unchanged[0], bool(bottle_unchanged), now['names'])
        check['env1_control'] = dict(rgb_equal=np.array_equal(rgb_before[1], rgb_after[1]),
                                    entity_ids_equal=np.array_equal(seg_before[1], seg_after[1]),
                                    camera_unchanged=camera_unchanged[1])
        result[name] = check
    return result


def approved_inputs(args):
    approval = json.loads(args.approval.read_text(encoding='utf-8'))
    assert approval['approved'] is True and approval['blockers_resolved'] is True
    assert approval['scope'] == 'cabinet_free_camera_ab'
    assert os.environ.get('SLURM_JOB_ID', '').isdigit() and os.environ.get('SLURM_JOB_GPUS', '').isdigit()
    root = Path(approval['storage_root']).resolve(strict=True)
    source = args.source.resolve(strict=True)
    assert source == Path(approval['production_source']) and source.is_relative_to(root)
    output = args.output.resolve()
    assert output == Path(approval['output']) and output != root and output.is_relative_to(root)
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                                   text=True, timeout=8).strip()
    assert head == approval['production_head']
    assert sha256(Path(__file__)) == approval['checker_sha256']
    for rel, expected in approval['production_hashes'].items():
        assert sha256(source/rel) == expected, rel
    return approval, source, output


def run(args):
    approval, source, output = approved_inputs(args)
    sys.path[:0] = [str(source), str(source/'tools/variation')]
    import gymnasium as gym
    import torch
    import tasks
    from mani_skill.utils import sapien_utils
    from sapien.render import RenderBodyComponent
    from cabinet_followup import pack_entity_ids
    from tasks.cabinet_pouring.cabinet_pouring_long import BOTTLE_REP_FIXED, CAP_TURN_SWITCH_HOLD_STEPS

    output.mkdir(exist_ok=False)
    report = dict(status='running', task=TASK, seed=SEED, job=os.environ['SLURM_JOB_ID'],
                  production_head=approval['production_head'], checker_head=approval['checker_head'],
                  full_entity_ids='RGBA packed little-endian uint32', groups={})
    flush = lambda: write_json(output/'results.json', report)
    write_json(output/'manifest.json', {**approval, 'job': report['job']})
    view = approval['supplement_view']
    torch.manual_seed(SEED)
    cpu_rng, cuda_rng = torch.random.get_rng_state(), torch.cuda.get_rng_state()
    group = GROUPS[0]
    try:
        for group in GROUPS:
            eye, target, fov = view
            common = dict(num_envs=2, sim_backend='physx_cuda', obs_mode='rgb+segmentation',
                          render_mode='rgb_array', reconfiguration_freq=0,
                          human_render_camera_configs=dict(width=960, height=720, fov=fov,
                                pose=sapien_utils.look_at(eye, target)))
            appearance = {} if group == 'appearance_off' else {
                'family_appearance': dict(enabled=True, mode='explicit', scheme_id='variant_9', seed=109)}
            row = report['groups'][group] = dict(status='running', appearance_kwargs=appearance,
                formal_camera_source='task defaults; sensor_configs omitted', config={k:v for k,v in common.items()
                    if k != 'human_render_camera_configs'}, supplemental_view=view, stages={})
            folder = output/group
            folder.mkdir()
            flush()
            torch.random.set_rng_state(cpu_rng)
            torch.cuda.set_rng_state(cuda_rng)
            with closing(gym.make(TASK, **common, **appearance)) as env:
                task = env.unwrapped
                # Reset itself may return task observations in the usual way.
                # There are no extra captures after the switch before get_obs.
                _, info = env.reset(seed=SEED)
                assert task.num_envs == 2 and task.gpu_sim_enabled
                row['actual_appearance_records'] = task.family_appearance_records
                if group == 'appearance_off':
                    assert task._family_appearance is None and task._variation is None
                    assert not row['actual_appearance_records']
                else:
                    assert task._family_appearance.schemes == ['variant_9', 'variant_9']
                row['actual_formal_cameras'] = {name: camera_setup(task.scene.sensors[name]) for name in FORMAL_CAMERAS}
                for name, cfg in row['actual_formal_cameras'].items():
                    assert cfg['width'] == cfg['height'] == 256
                    assert cfg['mounted'] == (name == 'task_wrist_camera')
                row['reset_state'] = tensor_state(task.get_state_dict())
                if group == 'variant_9':
                    native = report['groups']['appearance_off']
                    row['matched_native_reset_state'] = row['reset_state'] == native['reset_state']
                    row['matched_native_camera_setup'] = row['actual_formal_cameras'] == native['actual_formal_cameras']
                    assert row['matched_native_reset_state'] and row['matched_native_camera_setup']
                row['before_flags'] = stage_flags(task)
                assert row['before_flags']['active_bottle_rep'] == [BOTTLE_REP_FIXED] * 2
                assert row['before_flags']['cap_detached'] == row['before_flags']['cap_free'] == [False, False]
                attached = row['stages']['attached'] = {}
                before = stage_frames(task, info, folder, 'attached', attached, flush, RenderBodyComponent, pack_entity_ids)
                if group == 'variant_9':
                    first = native['stages']['attached']['cameras']
                    row['matched_native_attached_camera_parameters'] = all(
                        same_arrays(first[name][i]['camera'], current[i]['camera'])
                        for name, current in attached['cameras'].items() for i in (0, 1))
                    flush()
                    assert row['matched_native_attached_camera_parameters']

                row['trigger'] = dict(call='UnscrewCap.evaluate()', env_idx=0, twist=float(task.cap_success_rotation),
                                      hold_count=CAP_TURN_SWITCH_HOLD_STEPS-1, physics_steps=0)
                task._cap_twist[0] = task.cap_success_rotation
                task._cap_turn_hold_count[0] = CAP_TURN_SWITCH_HOLD_STEPS-1
                task._cap_turn_last_eval_step[0] = task._elapsed_steps[0]-1
                flush()
                info = task.evaluate()
                flags = row['after_flags'] = stage_flags(task)
                flush()
                assert flags['active_bottle_rep'] == [BOTTLE_REP_FIXED] * 2
                assert flags['cap_detached'] == flags['cap_free'] == flags['stage_cap_turned'] == [True, False]
                assert flags['stage_cap_placed'] == [False, False]
                free = row['stages']['free'] = {}
                after = stage_frames(task, info, folder, 'free', free, flush, RenderBodyComponent, pack_entity_ids)
                row['comparison'] = comparison(before, after, attached, free)
                row['status'] = 'captured_and_compared'
                flush()
        report['status'] = 'completed'
    except Exception:
        report.update(status='stopped', failed_group=group, traceback=traceback.format_exc()[-8000:])
        raise
    finally:
        flush()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
