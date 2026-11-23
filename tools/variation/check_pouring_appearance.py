"""Check object-only colour, native restoration and per-environment isolation."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

import numpy as np
from PIL import Image

from cabinet_color_oracle import require_color

ROOT = Path(__file__).resolve().parents[2]
SCHEMES = ("original", "ocean", "citrus", "violet")
VIEWS = {
    "bowl": ([-.43, -.84, .37], [-.20, -.50, .045], .70),
    "beads": ([1., .90, .60], [1., 1., .50], .65),
}


def mask_for(rgb, segmentation, ids):
    if rgb.shape[:2] != segmentation.shape or not ids or min(ids) <= 0:
        raise ValueError("Expected aligned RGB, entity segmentation and positive object IDs")
    mask = np.isin(segmentation, ids)
    if any(not np.any(segmentation == entity) for entity in ids):
        raise ValueError("Target entity missing in the capture")
    return mask


def static(asset):
    spec = importlib.util.spec_from_file_location("pouring_appearance",
        ROOT / "tasks/cabinet_pouring/pouring_appearance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert 'map_Kd material_0.jpeg' in (asset / "material.mtl").read_text()
    assert 'usemtl material_0' in (asset / "model_normalized_0.obj").read_text()
    with Image.open(asset / "material_0.jpeg") as image:
        native = np.asarray(image.convert("RGBA"))
    report = {}
    seg = np.zeros((96, 96), np.int32)
    seg[34:57, 34:57] = 19
    patch = np.s_[34:57, 34:57]
    for scheme, (color, _, _) in module.PALETTE.items():
        pixels = module.tint_bowl(native, color)
        assert np.array_equal(native[..., 3], pixels[..., 3])
        texture = require_color(pixels, scheme, 20)
        counts = []
        for background in ((46, 173, 199), (255, 173, 63), (166, 71, 230)):
            rgb = np.full((96, 96, 3), background, dtype=np.uint8)
            rgb[patch] = np.asarray(color) * 255
            mask = mask_for(rgb, seg, [19])
            counts.append(require_color(rgb, scheme, 20, mask)["matched_pixels"])
            wrong = next(k for k in module.PALETTE if k != scheme)
            rgb[patch] = np.asarray(module.PALETTE[wrong][0]) * 255
            try:
                require_color(rgb, scheme, 20, mask)
            except AssertionError:
                continue
            raise AssertionError("Background incorrectly passed the wrong bowl colour")
        assert counts == [23 * 23] * 3
        report[scheme] = dict(texture=texture, masked_positive=counts, rejected_wrong_colours=3)
    return report


def digest(array):
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def state_at(value, idx):
    if isinstance(value, dict):
        return {k: state_at(v, idx) for k, v in value.items()}
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    if isinstance(value, np.ndarray):
        return digest(value[idx] if value.ndim and value.shape[0] == 2 else value)
    return value


def run(approval, output):
    auth = json.loads(approval.read_text())
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    assert auth["approved"] and auth["blockers_resolved"] and auth["scope"] == "pouring_bowl_beads_rgb"
    assert auth["frozen_head"] == head and os.environ["SLURM_JOB_GPUS"].isdigit()
    assert output.resolve().is_relative_to(Path(auth["storage_root"]).resolve(strict=True))
    output.mkdir(exist_ok=False)
    sys.path.insert(0, str(ROOT))
    import gymnasium as gym
    import torch
    from mani_skill.utils import sapien_utils
    from mani_skill.utils.structs import Pose
    from sapien.render import RenderBodyComponent
    import tasks  # register the production task
    from tasks.cabinet_pouring.pouring_appearance import PALETTE

    report = dict(head=head, job=os.environ["SLURM_JOB_ID"], seed=71, builds=0, views={})
    issues = []

    def save():
        (output / "RESULTS.json").write_text(json.dumps(report, indent=2))

    def capture(e):
        obs = e.get_obs()["sensor_data"]
        return {k: (v["rgb"].detach().cpu().numpy()[..., :3].copy(),
                    v["segmentation"].detach().cpu().numpy()[..., 0].copy()) for k, v in obs.items()}

    def place(e, indices):
        assert len(e.particles) == 16 and e.particle_radius == .004
        for j, particle in enumerate(e.particles):
            p = particle.pose.p.clone()
            p[indices] = torch.tensor([1+(j%4-1.5)*.018, 1+(j//4-1.5)*.018, .50], device=e.device)
            particle.set_pose(Pose.create_from_pq(p=p, q=particle.pose.q))
        e.scene.px.gpu_apply_rigid_dynamic_data()
        e.scene._gpu_fetch_all()

    def materials(e, idx):
        result = []
        for actor in [e.target, *e.particles]:
            body = actor._objs[idx].find_component_by_type(RenderBodyComponent)
            part, = [p for s in body.render_shapes for p in s.parts]
            m = part.material
            tex = m.base_color_texture
            result.append((np.asarray(m.base_color).tolist(), m.roughness, m.metallic,
                           None if tex is None else digest(tex.download())))
        return result

    def validate_slots(current, native, scheme):
        assert len(current) == len(native) == 17
        if scheme == "original":
            assert current == native, "Native material restoration failed"
            return
        rgb, bowl_rough, bead_rough = PALETTE[scheme]
        for i, (row, original) in enumerate(zip(current, native)):
            rough = bead_rough if i else bowl_rough
            np.testing.assert_allclose(row[0], [*rgb, original[0][3]], rtol=0, atol=1e-6)
            assert abs(row[1] - (original[1] if rough is None else rough)) < 1e-6
            assert row[2] == (original[2] if rough is None else 0.)
            assert (row[3] is None and original[3] is None) if i else (row[3] != original[3])

    rng = torch.random.get_rng_state(), torch.cuda.get_rng_state()
    for view, (eye, target, fov) in VIEWS.items():
        row = report["views"][view] = dict(frames={}, colours={}, camera=VIEWS[view],
            diagnostic=view == "beads", radius_m=.004, bead_count=16)
        for enabled in (False, True):
            torch.random.set_rng_state(rng[0])
            torch.cuda.set_rng_state(rng[1])
            frame_label = "construct"
            env = None
            try:
                env = gym.make("CabinetPouringPourBeads-Sharpa-v1", num_envs=2, sim_backend="physx_cuda",
                    obs_mode="rgb+segmentation", render_mode="rgb_array", reconfiguration_freq=0,
                    sensor_configs={"base_camera": dict(width=512, height=512, fov=fov,
                        pose=sapien_utils.look_at(eye, target))}, pouring_appearance={"enabled": enabled})
                e = env.unwrapped
                report["builds"] += 1
                ids = [[(e.target._objs[i]).per_scene_id] if view == "bowl" else
                       [p._objs[i].per_scene_id for p in e.particles] for i in range(2)]
                for frame_label in ((*SCHEMES, "restored") if enabled else ("native",)):
                    scheme = frame_label if frame_label in SCHEMES else "original"
                    env.reset(seed=71, options={"pouring_appearance": {"scheme_id": scheme}})
                    if view == "beads":
                        place(e, [0, 1])
                    frames = capture(e)
                    rgb, seg = frames["base_camera"]
                    if enabled and frame_label in SCHEMES:
                        path = output / f"{view}_{scheme}.png"
                        Image.fromarray(rgb[0]).save(path)
                        row["frames"][scheme] = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                    states = [state_at(e.get_state_dict(), i) for i in range(2)]
                    mats = [materials(e, i) for i in range(2)]
                    if not enabled:
                        baseline, base_state, base_mat = frames, states, mats
                        continue
                    try:
                        assert states == base_state, "Physical initial state drift"
                        for i in range(2):
                            validate_slots(mats[i], base_mat[i], scheme)
                            mask = mask_for(rgb[i], seg[i], ids[i])
                            if scheme == "original":
                                assert all(np.array_equal(frames[k][0][i], baseline[k][0][i]) for k in frames), "Native RGB mismatch"
                            else:
                                metrics = require_color(rgb[i], scheme, 20 if view == "bowl" else 100, mask)
                                row["colours"][f"{scheme}_env{i}"] = dict(**metrics, object_pixels=int(mask.sum()))
                    except (AssertionError, ValueError) as exc:
                        issues.append(f"{view}/{frame_label}: {exc}")
                    save()
                if enabled:
                    before = capture(e)
                    state0, mat0 = state_at(e.get_state_dict(), 0), materials(e, 0)
                    env.reset(options={"env_idx": torch.tensor([1], device=e.device),
                                       "pouring_appearance": {"scheme_id": "violet"}})
                    if view == "beads":
                        place(e, [1])
                    after = capture(e)
                    assert all(np.array_equal(before[k][0][0], after[k][0][0]) for k in before), "env0 RGB drift"
                    assert state_at(e.get_state_dict(), 0) == state0 and materials(e, 0) == mat0, "env0 state/material drift"
                    assert e._pouring_appearance.schemes == ["original", "violet"]
                    validate_slots(materials(e, 1), base_mat[1], "violet")
                    rgb, seg = after["base_camera"]
                    m = mask_for(rgb[1], seg[1], ids[1])
                    row["selected_env"] = require_color(rgb[1], "violet", 20 if view == "bowl" else 100, m)
                    assert not np.array_equal(before["base_camera"][0][1], rgb[1])
                    row["local_reset"] = "passed"
            except Exception:
                issues.append(f"{view}/{enabled}/{frame_label}: {traceback.format_exc()}")
            finally:
                if env is not None:
                    env.close()
                save()
    report["issues"] = issues
    report["status"] = "failed" if issues else "passed"
    save()
    if issues:
        raise RuntimeError("\n".join(issues))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-asset", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.static_asset:
        print(json.dumps(static(args.static_asset)))
    elif args.approval and args.output:
        run(args.approval, args.output)
    else:
        parser.error("supply --static-asset or --approval and --output")
