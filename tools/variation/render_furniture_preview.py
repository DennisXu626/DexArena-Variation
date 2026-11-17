"""Export fixed-camera previews of the three furniture material schemes."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.variation.furniture_preview_materials import (
    FIELDS, PANEL_EDITABLE_ROLES, apply_object, describe_furniture, inspect_furniture, restore_furniture, snapshot_furniture,
    _validate_params,
)

INDEX = ROOT / "tasks/assets/variation/furniture_assembly/v1/catalog.json"
SCHEMES = ("original", "variant_1", "variant_2")
TASK_IDS = {name: f"FurnitureAssembly{name}-Sharpa-v1"
            for name in ("LayFlatPanel", "InsertRail", "FastenScrew")}
SCOPE = "Real single-environment initial-state authoring preview; no dynamics, task success, parallel reset or A4/A5 acceptance"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def flat_role_parameters(catalog, name):
    candidate = catalog['schemes'][name]
    color = candidate['base_color']
    return {role: {
        'base_color': [float(c) * catalog['color_factors'][role] for c in color[:3]] + [color[3]],
        'roughness': candidate['roughness'][role], 'metallic': candidate['metallic'],
    } for role in PANEL_EDITABLE_ROLES}


def capture(viewer, pose):
    """Read the viewer framebuffer without advancing simulation."""
    from PIL import Image
    viewer.set_camera_pose(pose)
    # Draw no UI into exported frames. No physics or task reset is performed.
    for _ in range(2):
        viewer.window.update_render()
        viewer.window.render('Color', [])
    pixels = np.asarray(viewer.window.get_picture('Color'))[..., :3].copy()
    if np.issubdtype(pixels.dtype, np.floating):
        pixels = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    elif pixels.dtype != np.uint8:
        raise ValueError(f'Unexpected framebuffer dtype {pixels.dtype}')
    if pixels.ndim != 3 or pixels.shape[-1] != 3 or np.ptp(pixels) == 0:
        raise RuntimeError('Invalid or blank native task framebuffer')
    return Image.fromarray(pixels)


def compare_images(frames, path):
    from PIL import Image, ImageDraw
    width, height = frames[0][1].size
    sheet = Image.new('RGB', (width * len(frames), height + 36), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    for i, (name, frame) in enumerate(frames):
        draw.text((i * width + 12, 10), name, fill=(245, 245, 245))
        sheet.paste(frame, (i * width, 36))
    sheet.save(path)


def prepare_viewer(env):
    from sapien.utils.viewer.path_window import PathWindow
    from sapien.utils.viewer.transform_window import TransformWindow

    viewer = env.unwrapped._viewer
    # Optional editing panels require Pinocchio on robot selection. Keep the
    # native task and other viewer plugins; material inspection needs no IK.
    kept = []
    for plugin in viewer.plugins:
        if isinstance(plugin, (TransformWindow, PathWindow)):
            plugin.close()
        else:
            kept.append(plugin)
    viewer.plugins = kept
    viewer.selected_entity_visibility = 1.0
    camera = env.unwrapped.scene.human_render_cameras['render_camera'].camera._render_cameras[0]
    task_pose = camera.get_global_pose()
    config = {'width': int(camera.width), 'height': int(camera.height),
              'near': float(camera.near), 'far': float(camera.far), 'fovy': float(camera.fovy),
              'task_view': 'Native task render_camera extrinsics and projection; viewer shader',
              'capture_path': 'SAPIEN RenderWindow Color -> CPU NumPy (not CUDA image tensor)'}
    viewer.resolution = (config['width'], config['height'])
    viewer.window.set_camera_parameters(config['near'], config['far'], config['fovy'])
    viewer.set_camera_pose(task_pose)
    return viewer, task_pose, config



def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_pixels(original, restored):
    """Exact RGB-array comparison; retain any nonzero drift as measured data."""
    expected = np.ascontiguousarray(np.asarray(original, dtype=np.uint8))
    actual = np.ascontiguousarray(np.asarray(restored, dtype=np.uint8))
    same_shape = expected.shape == actual.shape
    difference = np.abs(actual.astype(np.int16) - expected.astype(np.int16)) if same_shape else None
    return dict(
        identical=bool(same_shape and np.array_equal(actual, expected)),
        max_abs_diff=int(difference.max()) if same_shape else None,
        changed_channel_values=int(np.count_nonzero(difference)) if same_shape else None,
        original_shape=list(expected.shape), restored_shape=list(actual.shape),
        original_pixels_sha256=hashlib.sha256(expected.tobytes()).hexdigest(),
        restored_pixels_sha256=hashlib.sha256(actual.tobytes()).hexdigest(),
    )


def load_set():
    """Validate the unique catalogs and family mapping without simulator imports."""
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    if (index["version"] != "furniture-appearance-v1"
            or index["scope"] != "material_appearance"
            or tuple(index["schemes"]) != SCHEMES or set(index["tasks"]) != set(TASK_IDS)
            or set(index["objects"]) != {"flat_panel", "panel_rack", "rail", "screw"}):
        raise ValueError("Unexpected furniture preview-set contract")
    catalogs = {}
    for object_id, entry in index["objects"].items():
        path = (ROOT / entry["catalog"]).resolve()
        if not path.is_relative_to(ROOT) or set(entry["scheme_map"]) != set(SCHEMES):
            raise ValueError(f"Invalid unique catalog path or scheme map: {object_id}")
        catalog = json.loads(path.read_text(encoding="utf-8"))
        if (catalog["object_id"] != f"furniture_assembly.{object_id}"
                or catalog["scope"] != "furniture_appearance"
                or entry["scheme_map"]["original"] != "original"
                or catalog["schemes"]["original"] != {"mode": "restore_native"}):
            raise ValueError(f"Catalog identity/original mismatch: {object_id}")
        mapped = [entry["scheme_map"][scheme] for scheme in SCHEMES]
        if len(set(mapped)) != 3 or set(mapped) != set(catalog["schemes"]):
            raise ValueError(f"Each family scheme must map to one of exactly three object schemes: {object_id}")
        for local_id in mapped[1:]:
            scheme = catalog["schemes"][local_id]
            if scheme["mode"] != "material_override":
                raise ValueError(f"Candidate is not material_override: {object_id}/{local_id}")
            params = scheme.get("roles")
            if params is None:
                if object_id != "flat_panel" or set(catalog["color_factors"]) != {"face", "cut", "edge", "routed"}:
                    raise ValueError("Only flat_panel uses palette/factor parameters")
                _validate_params({"base_color": scheme["base_color"], "roughness": 0.5,
                                  "metallic": scheme["metallic"]}, "flat_panel palette")
                if any(not 0 < float(factor) <= 1 for factor in catalog["color_factors"].values()):
                    raise ValueError("Invalid flat-panel color factor")
                params = flat_role_parameters(catalog, local_id)
            if not params or set(params) & set(catalog["preserve_roles"]):
                raise ValueError(f"Candidate edits a preserved role or has no roles: {object_id}/{local_id}")
            for role, values in params.items():
                _validate_params(values, f"{object_id}/{local_id}/{role}")
        catalogs[object_id] = catalog
    for task, objects in index["tasks"].items():
        if len(set(objects)) != len(objects) or not set(objects) <= set(catalogs) or "flat_panel" not in objects:
            raise ValueError(f"Invalid object coverage for {task}")
    expected = {"LayFlatPanel": {"flat_panel", "panel_rack"},
                "InsertRail": {"flat_panel", "rail", "screw"},
                "FastenScrew": {"flat_panel", "rail", "screw"}}
    if any(set(index["tasks"][task]) != objects for task, objects in expected.items()):
        raise ValueError("Preview-set task presence does not match the three source loaders")
    return index, catalogs


def make_task(task, seed):
    import gymnasium as gym
    import tasks  # Register the actual repository task classes.

    kwargs = dict(num_envs=1, sim_backend="physx_cpu", obs_mode="state",
                  control_mode="pd_joint_pos", render_mode="human", visual_detail=True)
    if task != "FastenScrew":
        kwargs["panel_color_jitter"] = False
    env = gym.make(TASK_IDS[task], **kwargs)
    try:
        env.reset(seed=seed)
        return env
    except BaseException:
        env.close()
        raise


def fixed_views(env, binding, order):
    """Native task view plus object detail poses; no task entity is moved."""
    import sapien
    from mani_skill.utils import sapien_utils

    viewer, task_pose, config = prepare_viewer(env)
    viewer.select_entity(None)
    views = {"task": task_pose}
    for object_id in order:
        definition = binding.objects[object_id].definition
        if object_id == "flat_panel":
            _, entity = definition["entities"][0]
            matrix = entity.pose.to_transformation_matrix()
            target = matrix[:3, 3]
            eye = target + matrix[:3, :3] @ np.array([0.16, 0.12, 0.55])
        else:
            target = np.asarray(definition["detail"]["target"], dtype=float)
            eye = target + np.asarray(definition["detail"]["eye_offset"], dtype=float)
        pose = sapien_utils.look_at(eye, target)
        views[object_id] = sapien.Pose(pose.p[0].tolist(), pose.q[0].tolist())
    config["poses"] = {name: {"p_m": pose.p.tolist(), "q_wxyz": pose.q.tolist()}
                       for name, pose in views.items()}
    config["projection_matrix"] = np.asarray(viewer.window.get_camera_projection_matrix()).tolist()
    config["detail_view"] = "Additional fixed object cameras of the same unchanged real task initial state"
    config["flat_panel_detail_rule"] = "Eye = center + localX*0.16m + localY*0.12m + localZ*0.55m; aim at actual panel center"
    config["view_order"] = list(views)
    return viewer, views, config


def select_family(binding, index, catalogs, scheme_id):
    """Apply all present objects and read back every actual part's PBR fields."""
    observed = {}
    for object_id, obj in binding.objects.items():
        catalog = catalogs[object_id]
        local_id = index["objects"][object_id]["scheme_map"][scheme_id]
        apply_object(obj, catalog, local_id)
        candidate = catalog["schemes"][local_id]
        expected = ({} if local_id == "original" else candidate.get("roles"))
        if expected is None:
            expected = flat_role_parameters(catalog, local_id)
        role_results = {}
        for role, records in obj.groups.items():
            parts = []
            for record in records:
                material = record["material"]
                actual = dict(base_color=np.asarray(material.base_color, dtype=float).tolist(),
                              roughness=float(material.roughness), metallic=float(material.metallic))
                target = expected.get(role, record["native"])
                for field in FIELDS:
                    np.testing.assert_allclose(actual[field], target[field], rtol=0, atol=2e-6)
                parts.append(dict(entity=record["semantic_entity"], shape_index=record["shape_index"],
                                  part_index=record["part_index"], actual=actual,
                                  expected={field: target[field] for field in FIELDS}))
            role_results[role] = {"parts_checked": len(parts), "parts": parts}
        observed[object_id] = {"object_scheme_id": local_id, "roles": role_results}
    return observed


def invariant_check(baseline, binding):
    actual = snapshot_furniture(binding)
    if actual != baseline:
        changed = [key for key in baseline if actual[key] != baseline[key]]
        raise RuntimeError(f"Task/protected-scene invariants changed: {changed}")
    return {key: digest(value) for key, value in actual.items()}


def _baseline_path(output, task):
    resolved = output.resolve()
    if any(resolved.is_relative_to(ROOT / directory) for directory in ("outputs", ".local")):
        return output / "baseline_scene.json"
    # Full native snapshots are local diagnostic outputs, never object assets.
    folder = ROOT / "outputs/variation/furniture_baselines"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return folder / f"{task}_{stamp}.json"


def implementation_files(index):
    files = {
        "tools/variation/render_furniture_preview.py", "tools/variation/furniture_preview_materials.py",
        INDEX.relative_to(ROOT).as_posix(),
        "tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py",
        "tasks/furniture_assembly/furniture_assembly_insert_rail.py",
        "tasks/furniture_assembly/furniture_assembly_fasten_screw.py",
    }
    files.update(entry["catalog"] for entry in index["objects"].values())
    return sorted(files)


def export(env, binding, index, catalogs, viewer, views, camera_config, output, task, seed):
    output.mkdir(parents=True, exist_ok=False)
    viewer.select_entity(None)
    baseline = snapshot_furniture(binding)
    native = describe_furniture(binding)
    evidence = dict(task_id=TASK_IDS[task], num_envs=1, seed=seed, scope=SCOPE,
                    env_step_calls_after_reset=0, native_bindings=native, schemes={}, checks={},
                    screenshots_review="pending_human_review")
    frames = {view: [] for view in views}
    try:
        for scheme in SCHEMES:
            actual = select_family(binding, index, catalogs, scheme)
            result = {"actual_objects": actual, "images": {}}
            for view, pose in views.items():
                frame = capture(viewer, pose)
                filename = f"{scheme}_{view}.png"
                frame.save(output / filename)
                result["images"][view] = dict(file=filename, sha256=sha(output / filename), size=list(frame.size))
                frames[view].append((scheme, frame))
            result["invariant_digests"] = invariant_check(baseline, binding)
            evidence["schemes"][scheme] = result
        restore_furniture(binding)
        restored = describe_furniture(binding)
        if restored != native:
            raise RuntimeError("Full actual material/binding description did not restore exactly")
        invariant_check(baseline, binding)
        evidence["restoration"] = dict(native_description_sha256=digest(native),
                                        restored_description_sha256=digest(restored), exact_equal=True)
        evidence["restoration"]["per_view_pixels"] = {
            view: compare_pixels(frames[view][0][1], capture(viewer, pose))
            for view, pose in views.items()
        }
        invariant_check(baseline, binding)
        evidence["comparisons"] = {}
        for view, images in frames.items():
            filename = f"comparison_{view}.png"
            compare_images(images, output / filename)
            evidence["comparisons"][view] = dict(file=filename, sha256=sha(output / filename))
        evidence["checks"] = {
            "all_present_objects_and_actual_shape_part_bindings": True,
            "all_requested_pbr_fields_read_back_for_every_part": True,
            "same_reset_state_geometry_physics_uv_and_rail_joints": True,
            "non_furniture_and_all_protected_material_fields_unchanged": True,
            "full_original_material_description_restored_exactly": True,
            "restored_original_pixels_identical": all(
                result["identical"] for result in evidence["restoration"]["per_view_pixels"].values()),
        }
        baseline_path = _baseline_path(output, task)
        write_json(baseline_path, baseline)
        evidence["baseline_invariant_digests"] = {key: digest(value) for key, value in baseline.items()}
        write_json(output / "evidence.json", evidence)
        revision = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True).stdout.strip()
        manifest = dict(
            created_utc=datetime.now(timezone.utc).isoformat(), task_id=TASK_IDS[task],
            git_base_commit=revision, source_identity="Exact source and parameter file hashes identify the capture inputs",
            implementation_files_sha256={file: sha(ROOT / file) for file in implementation_files(index)},
            index_version=index["version"], object_catalog_versions={oid: catalogs[oid]["version"] for oid in binding.objects},
            object_scheme_maps={oid: index["objects"][oid]["scheme_map"] for oid in binding.objects},
            num_envs=1, seed=seed, visual_detail=True,
            panel_color_jitter=False if task != "FastenScrew" else "not_a_task_parameter",
            backend=str(env.unwrapped.backend), sim_backend=env.unwrapped.backend.sim_backend,
            render_backend=env.unwrapped.backend.render_backend, platform=platform.system(),
            python=platform.python_version(), architecture=platform.machine(),
            versions={name: metadata.version(name) for name in ("torch", "sapien", "mani_skill", "numpy", "gymnasium", "trimesh", "Pillow")},
            camera=camera_config, env_step_calls_after_reset=0,
            evidence={"file": "evidence.json", "sha256": sha(output / "evidence.json")},
            baseline_scene={"storage": "ignored_local_output_only", "file_sha256": sha(baseline_path),
                            "included_in_object_delivery": False},
            scope=SCOPE, human_review="pending_human_review",
        )
        write_json(output / "manifest.json", manifest)
        print(f"Exported {TASK_IDS[task]}: three family schemes, {len(views)} fixed views to {output}", flush=True)
    except BaseException as error:
        write_json(output / "failure.json", dict(task_id=TASK_IDS[task], error_type=type(error).__name__,
                                               error=str(error), scope=SCOPE, status="failed"))
        raise
    finally:
        restore_furniture(binding)


def interactive(env, binding, index, catalogs, viewer, views, scheme, focus):
    viewer.select_entity(None)
    baseline = snapshot_furniture(binding)
    select_family(binding, index, catalogs, scheme)
    invariant_check(baseline, binding)
    viewer.set_camera_pose(views[focus])
    print("Keys: 1 original | 2 variant_1 | 3 variant_2 (all present objects); V cycles fixed views", flush=True)
    print("Camera: right-drag rotates, middle-drag pans, wheel zooms. Close window to exit.", flush=True)
    print(f"Scheme: {scheme}; view: {focus}", flush=True)
    try:
        while not viewer.closed:
            env.render()
            if viewer.closed:
                break
            for key, candidate in zip(("1", "2", "3"), SCHEMES):
                if viewer.window.key_press(key):
                    viewer.select_entity(None)
                    select_family(binding, index, catalogs, candidate)
                    invariant_check(baseline, binding)
                    scheme = candidate
                    print(f"Scheme: {scheme}; view: {focus}", flush=True)
            if viewer.window.key_press("v"):
                order = list(views)
                focus = order[(order.index(focus) + 1) % len(order)]
                viewer.select_entity(None)
                viewer.set_camera_pose(views[focus])
                print(f"Scheme: {scheme}; view: {focus}", flush=True)
            time.sleep(1 / 60)
    finally:
        restore_furniture(binding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=tuple(TASK_IDS), default="LayFlatPanel")
    parser.add_argument("--view", action="store_true")
    parser.add_argument("--scheme", choices=SCHEMES, default="original", help="Starting family scheme for --view")
    parser.add_argument("--focus", choices=("task", "flat_panel", "panel_rack", "rail", "screw"), default="task")
    parser.add_argument("--output", type=Path, help="New directory for all schemes/views and structured evidence")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--static", action="store_true", help="Catalog/index checks only; no simulator import")
    args = parser.parse_args()
    index, catalogs = load_set()
    if args.focus != "task" and args.focus not in index["tasks"][args.task]:
        parser.error(f"{args.focus} is absent from {args.task}")
    if args.static:
        print(json.dumps(dict(status="passed", scope="CPU index/catalog checks only; no simulation",
                              schemes=list(SCHEMES), tasks=index["tasks"],
                              catalog_versions={oid: catalog["version"] for oid, catalog in catalogs.items()})))
        return
    if not args.view and args.output is None:
        parser.error("Choose --view or --output DIRECTORY")
    if args.output is not None and args.output.exists():
        parser.error("Output directory must be new; previous evidence is never overwritten")
    env = None
    try:
        env = make_task(args.task, args.seed)
        binding = inspect_furniture(env)
        if set(binding.objects) != set(index["tasks"][args.task]):
            raise ValueError("Actual furniture object coverage differs from the preview-set index")
        viewer, views, camera_config = fixed_views(env, binding, index["tasks"][args.task])
        if args.output is not None:
            export(env, binding, index, catalogs, viewer, views, camera_config, args.output, args.task, args.seed)
        if args.view:
            interactive(env, binding, index, catalogs, viewer, views, args.scheme, args.focus)
    except KeyboardInterrupt:
        pass
    finally:
        if env is not None:
            env.close()


if __name__ == "__main__":
    main()
