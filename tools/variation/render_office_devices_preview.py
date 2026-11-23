"""Standalone source-model previews; no task, robot, dynamics or reset integration."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from tools.variation.office_devices_assets import inspect_assets
from tools.variation.office_devices_materials import OfficeDevicesPreviewMaterials, snapshot_model, without_editable_fields, canonical_model


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--object", choices=("laptop", "keyboard"), required=True)
    parser.add_argument("--asset-root", type=Path, default=ROOT / "tasks/assets/task_object_meshes/office")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approved-render", action="store_true", help="Use only in coordinator-assigned GPU window")
    parser.add_argument('--native-off', action='store_true', help='Capture the untouched source model baseline only')
    parser.add_argument('--native-reference', type=Path, help='Fresh native-off output for exact original model/RGB comparison')
    parser.add_argument('--keycaps-only', action='store_true',
                        help='Load only visual records for the original keycaps and apply their independent catalog')
    args = parser.parse_args()
    if not args.approved_render:
        parser.error("Rendering requires a coordinator-assigned GPU window and --approved-render")
    if args.native_off and args.native_reference:
        parser.error('native-off baseline does not consume another reference')
    if (args.object == 'keyboard' or args.keycaps_only) and not args.native_off and args.native_reference is None:
        parser.error('keyboard partition or isolated keycap preview requires a matching --native-reference baseline')
    inventory = inspect_assets(args.object, args.asset_root)
    if inventory["missing"] or inventory["errors"] or not inventory["editable_count"]:
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
        return 2
    # No renderer import or scene is created before complete asset preflight.
    import numpy as np
    from PIL import Image, ImageDraw
    import sapien
    from mani_skill.utils.sapien_utils import look_at

    source_dir = ROOT / "assets/appearance/objects/office_desk" / args.object
    chassis_path = source_dir / 'bindings.json'
    chassis = json.loads(chassis_path.read_text(encoding='utf-8'))
    binding_path = source_dir / 'keycaps_bindings.json' if args.keycaps_only else chassis_path
    catalog_path = source_dir / ('keycaps_catalog.json' if args.keycaps_only else 'catalog.json')
    definition = json.loads(binding_path.read_text(encoding='utf-8')) if args.keycaps_only else chassis
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {"scope": "standalone source-model preview; NOT a task or A4/A5 result",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv,
                "physics_steps": 0, "object_id": args.object, "catalog_version": catalog["version"],
                "asset_inventory": inventory, "keycaps_only": args.keycaps_only,
                "versions": {p: metadata.version(p) for p in ("sapien", "mani_skill", "numpy", "pillow")},
                "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (Path(__file__), Path(__file__).with_name("office_devices_assets.py"),
                                            Path(__file__).with_name("office_devices_materials.py"),
                                            Path(__file__).with_name("office_devices_uv_proof.py"),
                                            Path(__file__).with_name("audit_office_devices_uv.py"),
                                            *{catalog_path, binding_path, chassis_path},
                                            ROOT / "tasks/office_desk/devices_appearance.py",
                                            ROOT / "tasks/office_desk/office_desk_open_laptop.py",
                                            ROOT / "tasks/office_desk/office_desk_type_keys.py")},
                "sapien_binary_sha256": hashlib.sha256(Path(sapien.pysapien.__file__).read_bytes()).hexdigest()}
    for row in definition['part_bindings']:
        for slot in row['editable_slots']:
            if 'partition' in slot:
                path = ROOT / slot['partition']['proof']
                manifest['source_sha256'][path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(args.output / "manifest.json", manifest)
    result = {"status": "running", "runtime_integration": "short_tasks_connected; this run model_only", "physics_steps": 0}
    try:
        scene = sapien.Scene()
        scene.set_ambient_light([0.45, 0.45, 0.45])
        scene.add_directional_light([1, 1, -1], [2, 2, 2], shadow=False)
        loader = scene.create_urdf_loader()
        loader.fix_root_link = True
        loader.scale = chassis["scale"]
        loader.load_multiple_collisions_from_file = False
        # Model-only inspection; no decomposition, physical rollout or task claim.
        # Native SAPIEN returns a tuple; formal ManiSkill task builders are untouched.
        builders, actors, cameras = loader.parse(str(Path(inventory["asset_dir"]) / "mobility.urdf"))
        if len(builders) != 1 or actors or cameras:
            raise RuntimeError("Expected one source articulation and no extra actors/cameras")
        if args.keycaps_only:
            selected = {(row['link'], row['index']): row for row in definition['part_bindings']}
            retained = set()
            for link_builder in builders[0].link_builders:
                records = []
                for index, record in enumerate(link_builder.visual_records):
                    key = (link_builder.name, index)
                    row = selected.get(key)
                    if row is None:
                        continue
                    if (index != len(records) or record.name != row['name']
                            or Path(record.filename).resolve() != Path(inventory['asset_dir']) / row['mesh']):
                        raise RuntimeError(f'Isolated keycap source does not match {key}')
                    records.append(record)
                    retained.add(key)
                link_builder.visual_records = records
            if retained != set(selected):
                raise RuntimeError('Missing source visual in isolated keycap load')
        materials = None if args.native_off else OfficeDevicesPreviewMaterials(inventory, catalog, definition)
        if materials is not None:
            materials.install(builders[0])
        model = builders[0].build()
        # CPU articulation construction leaves fixed-link poses unpropagated
        # until joint state is explicitly applied. This updates native FK; no step.
        model.set_qpos(model.get_qpos().copy())
        if args.object == "laptop":
            task_tree = ast.parse((ROOT / "tasks/office_desk/office_desk_open_laptop.py").read_text(encoding="utf-8"))
            models = next(ast.literal_eval(n.value) for n in task_tree.body
                          if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "LAPTOP_MODELS" for t in n.targets))
            # Same documented gallery opening, within the native 40–50 degree start interval.
            qpos = model.get_qpos().copy()
            qpos[0] = models["10211"]["qpos_closed"] + np.deg2rad(45)
            model.set_qpos(qpos)
        manifest["native_part_bindings"] = materials.audit if materials else []
        manifest['native_off'] = args.native_off
        original = snapshot_model(model)
        canonical = canonical_model(original, keycaps_only=args.keycaps_only)
        if args.native_reference:
            native = json.loads((args.native_reference / 'original_canonical.json').read_text(encoding='utf-8'))
            if canonical != native:
                raise RuntimeError('Enabled original model differs from native-off triangle attributes, transforms or complete PBR')
            result['native_off_model_equivalence'] = 'passed'
        protected = without_editable_fields(original, inventory, keycaps_only=args.keycaps_only)
        # Bounds follow original meshes, with one camera/light configuration for all schemes.
        points = []
        for link in model.links:
            body = link.entity.find_component_by_type(sapien.render.RenderBodyComponent)
            if body:
                for shape in body.render_shapes:
                    transform = (link.entity.pose * shape.local_pose).to_transformation_matrix()
                    for part in shape.parts:
                        points.append(np.asarray(part.vertices) * np.asarray(shape.scale) @ transform[:3, :3].T + transform[:3, 3])
        vertices = np.concatenate(points)
        center = (vertices.min(0) + vertices.max(0)) / 2
        extent = float(np.max(np.ptp(vertices, axis=0)))
        eye = center + np.array([0.85, -1.05, 1.4]) * extent
        camera = scene.add_camera("model_only", 512, 384, np.deg2rad(48), 0.001, max(10, extent * 20))
        camera.entity.pose = look_at(eye, center).sp
        manifest["camera"] = {"eye": eye.tolist(), "target": center.tolist(), "fovy_deg": 48, "resolution": [512, 384]}
        manifest["model_qpos"] = original["qpos"]
        write_json(args.output / "manifest.json", manifest)

        def capture_pixels():
            scene.update_render()
            camera.take_picture()
            raw = np.asarray(camera.get_picture("Color"))
            if raw.ndim != 3 or raw.shape[:2] != (384, 512) or raw.shape[2] < 3:
                raise RuntimeError("Invalid source-model framebuffer shape")
            if not np.isfinite(raw).all():
                raise RuntimeError("Non-finite source-model framebuffer")
            pixels = (np.clip(raw[..., :3], 0, 1) * 255).astype(np.uint8)
            if np.max(np.ptp(pixels.reshape(-1, 3), axis=0)) == 0:
                raise RuntimeError("Blank source-model frame")
            return pixels

        frames = []
        for scheme_id in (('original',) if args.native_off else catalog["schemes"]):
            if materials is not None:
                materials.apply(scheme_id)
            current = snapshot_model(model)
            if without_editable_fields(current, inventory, keycaps_only=args.keycaps_only) != protected:
                raise RuntimeError("Protected geometry, UV, material or model state changed")
            pixels = capture_pixels()
            frame = Image.fromarray(pixels)
            frame.save(args.output / f"{scheme_id}.png")
            frames.append((scheme_id, frame))
            if scheme_id == 'original' and args.native_reference:
                native_pixels = np.asarray(Image.open(args.native_reference / 'original.png').convert('RGB'))
                difference = np.abs(pixels.astype(np.int16) - native_pixels.astype(np.int16))
                result['native_off_original_rgb_difference'] = {'changed_values': int(np.count_nonzero(difference)), 'max_absolute_difference': int(difference.max())}
                if np.any(difference):
                    raise RuntimeError('Enabled original RGB differs from native-off model')
        write_json(args.output / 'original_canonical.json', canonical)
        if args.native_off:
            write_json(args.output / 'original_snapshot.json', original)
            result.update(status='passed', scope='untouched native-off model baseline; no candidate claim')
            return 0
        result["image_differences"] = {}
        for i, (name, frame) in enumerate(frames):
            for other_name, other_frame in frames[i + 1:]:
                delta = np.abs(np.asarray(frame).astype(float) - np.asarray(other_frame).astype(float))
                changed = float(np.mean(np.max(delta, axis=2) > 8))
                result["image_differences"][f"{name}/{other_name}"] = {
                    "fraction_over_8_levels": changed, "mean_absolute_difference": float(delta.mean())}
                if changed < 0.001:
                    raise RuntimeError(f"No sufficient visible pixel difference: {name}/{other_name}")
        materials.apply("original")
        if snapshot_model(model) != original:
            raise RuntimeError("Original material restoration mismatch")
        restored = capture_pixels()
        Image.fromarray(restored).save(args.output / "restored_original.png")
        delta = np.abs(restored.astype(np.int16) - np.asarray(frames[0][1]).astype(np.int16))
        Image.fromarray(delta.astype(np.uint8)).save(args.output / "restored_rgb_diff.png")
        result["restored_rgb_difference"] = {
            "changed_pixels": int(np.count_nonzero(np.any(delta != 0, axis=2))),
            "max_absolute_difference": int(delta.max()),
            "mean_absolute_difference": float(delta.mean())}
        if np.any(delta):
            raise RuntimeError("Original RGB restoration mismatch; see restored_rgb_difference")
        sheet = Image.new("RGB", (512 * len(frames), 424), (28, 28, 28))
        draw = ImageDraw.Draw(sheet)
        for index, (name, frame) in enumerate(frames):
            draw.text((index * 512 + 12, 12), name, fill="white")
            sheet.paste(frame, (index * 512, 40))
        sheet.save(args.output / "comparison.png")
        write_json(args.output / "original_snapshot.json", original)
        result.update(status="passed", protected_fields_unchanged=True, original_restored=True, original_rgb_restored=True,
                      perceptual_distinctness_and_legend_readability="pending human inspection")
    except Exception as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        result['source_hashes_unchanged'] = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
            for name, expected in manifest['source_sha256'].items())
        result['asset_hashes_unchanged'] = all(hashlib.sha256((Path(inventory['asset_dir']) / name).read_bytes()).hexdigest() == expected
            for name, expected in inventory['files'].items())
        if not result['source_hashes_unchanged'] or not result['asset_hashes_unchanged']:
            result.update(status='failed', error='Office model inputs changed during validation')
        write_json(args.output / "result.json", result)
        if not result['source_hashes_unchanged'] or not result['asset_hashes_unchanged']:
            raise RuntimeError('Office model inputs changed during validation')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
