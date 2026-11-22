"""CPU-only, read-only asset evidence for the office-device foundation.

No simulator or rendering library is imported. ``asset_root`` is the office
directory containing model-ID subdirectories. Unknown material evidence always
protects a visual; this inspector never changes meshes, UVs, or materials.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shlex
import struct
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CATALOG_ROOT = ROOT / "assets" / "appearance" / "objects" / "office_desk"
DEFAULT_ASSET_ROOT = ROOT / "tasks" / "assets" / "task_object_meshes" / "office"
OBJECT_IDS = ("laptop", "keyboard")
_TEXTURE_COMMANDS = {"bump", "disp", "decal", "refl", "norm", "normal"}


def load_definition(object_id: str) -> dict:
    """Read the object's sole binding definition (not an inferred asset map)."""
    if object_id not in OBJECT_IDS:
        raise ValueError(f"Unknown office device: {object_id!r}")
    with (CATALOG_ROOT / object_id / "bindings.json").open(encoding="utf-8-sig") as stream:
        definition = json.load(stream)
    if definition.get("object_id") != object_id:
        raise ValueError(f"Binding object_id mismatch for {object_id}")
    model_id = str(definition["model_id"])
    if not model_id.isdigit():
        raise ValueError(f"Unsafe model ID: {model_id!r}")
    return definition


def _tokens(line: str) -> list[str]:
    return shlex.split(line, comments=True, posix=True)


def _texture_filename(tokens: list[str]) -> str:
    """Consume standard Wavefront map options without treating them as paths."""
    index = 0
    single = {"-blendu", "-blendv", "-boost", "-texres", "-clamp", "-bm", "-imfchan", "-type", "-cc", "-colorspace"}
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index].lower()
        index += 1
        if option in {"-o", "-s", "-t"}:
            count = 0
            while index < len(tokens) and count < 3:
                try:
                    float(tokens[index])
                except ValueError:
                    break
                count += 1
                index += 1
            if not count:
                raise ValueError(f"Texture option {option} has no numeric arguments")
        elif option == "-mm":
            if index + 2 > len(tokens):
                raise ValueError("Texture option -mm has fewer than two arguments")
            index += 2
        elif option in single:
            if index >= len(tokens):
                raise ValueError(f"Texture option {option} has no argument")
            index += 1
        else:
            raise ValueError(f"Unknown texture option: {option}")
    filename = " ".join(tokens[index:])
    if not filename:
        raise ValueError("Texture reference has no filename")
    return filename


def inspect_assets(object_id: str, asset_root: Path) -> dict:
    """Inventory one real model and identify only proven-safe candidate visuals.

    ``files`` maps model-relative paths to SHA-256. Visual rows use ``link``,
    ``name``, ``index`` (within the link), ``mesh``, ``role`` and
    ``protection_reason``; OBJ/MTL evidence is included on each row. Missing
    files and unsafe/unsupported references are reported, never substituted.
    A missing URDF returns an ordinary result with ``missing`` populated.
    """
    definition = load_definition(object_id)
    model_id = str(definition["model_id"])
    model_dir = (Path(asset_root) / model_id).resolve()
    result = {
        "object_id": object_id, "model_id": model_id,
        "asset_dir": str(model_dir), "urdf": "mobility.urdf",
        "files": {}, "visuals": [], "collisions": [],
        "missing": [], "errors": [], "editable_count": 0,
    }
    cache: dict[Path, bytes | None] = {}
    obj_cache: dict[Path, dict] = {}
    mtl_cache: dict[Path, dict] = {}

    def issue(message: str) -> None:
        if message not in result["errors"]:
            result["errors"].append(message)

    def locate(base: Path, filename: str, context: str) -> Path | None:
        if not filename or "://" in filename:
            issue(f"{context}: unsupported or empty path {filename!r}")
            return None
        path = (base / filename).resolve()
        if not path.is_relative_to(model_dir):
            issue(f"{context}: path escapes model directory: {filename!r}")
            return None
        return path

    def relative(path: Path) -> str:
        return path.relative_to(model_dir).as_posix()

    def read(path: Path) -> bytes | None:
        if path in cache:
            return cache[path]
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            filename = relative(path)
            if filename not in result["missing"]:
                result["missing"].append(filename)
            payload = None
        except OSError as exc:
            issue(f"{relative(path)}: cannot read: {exc}")
            payload = None
        if payload is not None:
            result["files"][relative(path)] = hashlib.sha256(payload).hexdigest()
        cache[path] = payload
        return payload

    def lines(path: Path) -> list[str] | None:
        payload = read(path)
        if payload is None:
            return None
        try:
            return payload.decode("utf-8-sig").splitlines()
        except UnicodeDecodeError:
            issue(f"{relative(path)}: unsupported text encoding")
            return None

    def scan_mtl(path: Path) -> dict:
        if path in mtl_cache:
            return mtl_cache[path]
        materials: dict[str, dict] = {}
        data = {"materials": materials, "issues": []}
        mtl_cache[path] = data
        source = lines(path)
        if source is None:
            data["issues"].append("missing_or_unreadable_mtl")
            return data
        current = None
        for number, line in enumerate(source, 1):
            try:
                parts = _tokens(line)
                if not parts:
                    continue
                command, values = parts[0].lower(), parts[1:]
                if command == "newmtl":
                    name = " ".join(values)
                    if not name or name in materials:
                        raise ValueError("empty or duplicate newmtl name")
                    current = {"name": name, "mtl": relative(path), "diffuse": None,
                               "opacity": 1.0, "textures": [], "issues": [],
                               "transmission": False}
                    materials[name] = current
                elif command.startswith("map_") or command in _TEXTURE_COMMANDS:
                    texture = locate(path.parent, _texture_filename(values), relative(path))
                    if texture is not None:
                        read(texture)
                    if current is None:
                        raise ValueError("texture outside a newmtl block")
                    current["textures"].append(relative(texture) if texture else None)
                elif current is not None and command == "kd":
                    values_f = [float(value) for value in values]
                    if len(values_f) != 3 or not all(math.isfinite(v) for v in values_f):
                        raise ValueError("invalid Kd")
                    current["diffuse"] = values_f
                elif current is not None and command in {"d", "tr"}:
                    if values and values[0].lower() == "-halo":
                        values = values[1:]
                    if len(values) != 1:
                        raise ValueError(f"invalid {command}")
                    value = float(values[0])
                    if not math.isfinite(value) or not 0 <= value <= 1:
                        raise ValueError(f"invalid {command} opacity")
                    alpha = value if command == "d" else 1.0 - value
                    current["opacity"] = min(current["opacity"], alpha)
                elif current is not None and command == "tf":
                    # Transmission can be expressed separately from d/Tr.
                    current["transmission"] = True
                elif current is not None and command == "illum":
                    if len(values) != 1:
                        raise ValueError("invalid illum")
                    current["transmission"] |= int(values[0]) in {4, 6, 7, 9}
            except ValueError as exc:
                message = f"{relative(path)}:{number}: {exc}"
                issue(message)
                data["issues"].append(message)
                if current is not None:
                    current["issues"].append(message)
        return data

    def scan_obj(path: Path) -> dict:
        if path in obj_cache:
            return obj_cache[path]
        data = {"vertex_count": 0, "uv_count": 0, "face_count": 0, "material_triangles": {}, "material_geometry_sha256": {},
                "used_materials": [], "material_slots": [], "materials": {},
                "mtllib": [], "issues": [], "unassigned_faces": False}
        obj_cache[path] = data
        if path.suffix.lower() != ".obj":
            read(path)
            message = f"{relative(path)}: unsupported mesh extension; OBJ required"
            issue(message)
            data["issues"].append(message)
            return data
        source = lines(path)
        if source is None:
            data["issues"].append("missing_or_unreadable_obj")
            return data
        current_material = None
        vertices, material_faces = [], {}
        for number, line in enumerate(source, 1):
            try:
                parts = _tokens(line)
                if not parts:
                    continue
                command, values = parts[0].lower(), parts[1:]
                if command == "v":
                    data["vertex_count"] += 1
                    vertices.append(tuple(float(value) for value in values[:3]))
                elif command == "vt":
                    data["uv_count"] += 1
                elif command == "f":
                    data["face_count"] += 1
                    data["unassigned_faces"] |= current_material is None
                    counts = data["material_triangles"]
                    counts[current_material] = counts.get(current_material, 0) + max(0, len(values) - 2)
                    indices = [int(value.split('/')[0]) for value in values]
                    points = [vertices[value - 1 if value > 0 else value] for value in indices]
                    for index in range(1, len(points) - 1):
                        material_faces.setdefault(current_material, []).append((points[0], points[index], points[index + 1]))
                elif command == "usemtl":
                    current_material = " ".join(values)
                    if not current_material:
                        raise ValueError("empty usemtl")
                    if current_material not in data["used_materials"]:
                        data["used_materials"].append(current_material)
                elif command == "mtllib":
                    if not values:
                        raise ValueError("empty mtllib")
                    for filename in values:
                        mtl = locate(path.parent, filename, relative(path))
                        if mtl is None:
                            data["issues"].append("unsafe_mtllib")
                            continue
                        data["mtllib"].append(relative(mtl))
                        inventory = scan_mtl(mtl)
                        data["issues"].extend(inventory["issues"])
                        for name, material in inventory["materials"].items():
                            data["material_slots"].append({"name": name, "mtl": relative(mtl)})
                            if name in data["materials"]:
                                data["issues"].append(f"ambiguous_material:{name}")
                            data["materials"][name] = material
            except ValueError as exc:
                message = f"{relative(path)}:{number}: {exc}"
                issue(message)
                data["issues"].append(message)
        data["material_geometry_sha256"] = {
            name: hashlib.sha256(b''.join(sorted(
                b''.join(sorted(struct.pack('<3f', *point) for point in triangle))
                for triangle in triangles))).hexdigest()
            for name, triangles in material_faces.items()
        }
        return data

    urdf_path = locate(model_dir, "mobility.urdf", "URDF")
    payload = read(urdf_path)
    if payload is None:
        issue("No URDF evidence; asset binding remains pending")
        return result
    # Native SAPIEN automatically reads this optional sibling during parse().
    srdf_path = model_dir / "mobility.srdf"
    if srdf_path.exists():
        srdf_data = read(srdf_path)
        if srdf_data is not None:
            try:
                ET.fromstring(srdf_data)
            except ET.ParseError as exc:
                issue(f"mobility.srdf: invalid XML: {exc}")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        issue(f"mobility.urdf: invalid XML: {exc}")
        return result

    named_materials = {node.get("name"): node for node in root.findall("material")}

    def urdf_material_reasons(node: ET.Element | None) -> list[str]:
        if node is None:
            return []
        reasons = []
        for texture in node.findall("texture"):
            path = locate(model_dir, texture.get("filename", ""), "URDF texture")
            if path is not None:
                read(path)
            reasons.append("urdf_texture")
        color = node.find("color")
        if color is not None:
            try:
                rgba = [float(value) for value in color.get("rgba", "").split()]
                if len(rgba) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in rgba):
                    raise ValueError()
                if rgba[3] < 1:
                    reasons.append("urdf_transparency")
            except ValueError:
                reasons.append("unknown_urdf_alpha")
        if not list(node):
            referenced = named_materials.get(node.get("name"))
            if referenced is None or referenced is node:
                reasons.append("unresolved_urdf_material")
            else:
                reasons.extend(urdf_material_reasons(referenced))
        return reasons

    # Inventory even top-level materials that no visual happens to use.
    for material in root.findall("material"):
        urdf_material_reasons(material)

    links = {node.get("name"): node for node in root.findall("link")}
    children: dict[str, list[str]] = {}
    moving_children = set()
    joint_by_name = {}
    child_links = set()
    for joint in root.findall("joint"):
        parent, child = joint.find("parent"), joint.find("child")
        if parent is None or child is None:
            issue(f"Joint {joint.get('name')!r} has no parent/child")
            continue
        parent_name, child_name = parent.get("link"), child.get("link")
        children.setdefault(parent_name, []).append(child_name)
        child_links.add(child_name)
        joint_by_name[joint.get("name")] = joint
        if joint.get("type") != "fixed":
            moving_children.add(child_name)
        if parent_name not in links or child_name not in links:
            issue(f"Joint {joint.get('name')!r} references an unknown link")

    protected_links = set(moving_children)
    pending = list(moving_children)
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in protected_links:
                protected_links.add(child)
                pending.append(child)
    roots = set(links) - child_links
    fixed_chassis = set()
    if len(roots) == 1:
        pending = list(roots)
        while pending:
            link_name = pending.pop()
            if link_name in fixed_chassis or link_name in protected_links:
                continue
            fixed_chassis.add(link_name)
            pending.extend(children.get(link_name, []))
    else:
        issue(f"Expected one URDF root link; found {len(roots)}")

    if object_id == "keyboard":
        result["key_count"] = len(moving_children)
        expected = definition.get("expected_key_count")
        if expected is not None and len(moving_children) != expected:
            issue(f"Expected {expected} movable keys, found {len(moving_children)}")
        result["target_key_sequence"] = definition.get("target_key_sequence", [])
        for label, joint_name, link_name in result["target_key_sequence"]:
            joint = joint_by_name.get(joint_name)
            child = None if joint is None else joint.find("child")
            if child is None or child.get("link") != link_name or link_name not in protected_links:
                issue(f"Target {label}: expected movable {joint_name} -> {link_name}")

    selector = definition.get("selector", {}).get("kind")
    for link_name, link in links.items():
        for tag in ("visual", "collision"):
            for index, element in enumerate(link.findall(tag)):
                mesh = element.find("geometry/mesh")
                row = {"link": link_name, "name": element.get("name", ""),
                       "index": index, "mesh": None, "role": None,
                       "protection_reason": None}
                reasons = []
                if mesh is None:
                    issue(f"{link_name}/{tag}[{index}]: expected OBJ mesh geometry")
                    reasons.append("non_mesh_geometry")
                else:
                    path = locate(model_dir, mesh.get("filename", ""), f"{link_name}/{tag}[{index}]")
                    if path is None:
                        reasons.append("unsafe_mesh_reference")
                    else:
                        row["mesh"] = relative(path)
                        evidence = scan_obj(path)
                        row.update(evidence)
                        if evidence["issues"]:
                            reasons.append("unresolved_obj_or_mtl")
                        if not evidence["vertex_count"] or not evidence["face_count"]:
                            reasons.append("empty_mesh")
                        used = evidence["used_materials"]
                        if len(used) != 1 or evidence["unassigned_faces"]:
                            reasons.append("unknown_or_multiple_used_materials")
                        else:
                            material = evidence["materials"].get(used[0])
                            if material is None or material["diffuse"] is None:
                                reasons.append("unknown_original_material")
                            else:
                                if material["textures"]:
                                    reasons.append("original_mtl_texture")
                                if material["opacity"] < 1:
                                    reasons.append("original_mtl_transparency")
                                if material["transmission"]:
                                    reasons.append("original_mtl_transmission")
                                if material["issues"]:
                                    reasons.append("unresolved_original_material")
                reasons.extend(urdf_material_reasons(element.find("material")))
                if tag == "collision":
                    row["protection_reason"] = "collision_geometry_is_immutable"
                    result["collisions"].append(row)
                    continue
                if selector == "laptop_screen_frame":
                    selected = row["name"].startswith("screen_frame")
                    if not selected:
                        reasons.insert(0, "screen_or_other_non_frame_visual")
                elif selector == "keyboard_fixed_chassis":
                    selected = link_name in fixed_chassis
                    if not selected:
                        reasons.insert(0, "moving_key_or_descendant")
                else:
                    selected = False
                    reasons.insert(0, "unknown_selector")
                    issue(f"Unknown selector: {selector!r}")
                explicit = next((value for value in definition.get("part_bindings", [])
                                 if (value["link"], value["index"]) == (link_name, index)), None)
                if selected and explicit is not None:
                    # A multi-material visual is never overridden as a whole.
                    # Prove only the explicitly named native parts editable.
                    retained = [reason for reason in reasons if reason != "unknown_or_multiple_used_materials"]
                    if (row["mesh"] != explicit["mesh"] or row["name"] != explicit["name"]
                            or len(row.get("used_materials", [])) != explicit["native_part_count"]):
                        retained.append("explicit_visual_identity_mismatch")
                    for slot in explicit["editable_slots"]:
                        material = row.get("materials", {}).get(slot["material"])
                        if (slot["material"] not in row.get("used_materials", []) or material is None
                                or material["diffuse"] != slot["diffuse"]
                                or material["textures"] != ([slot['partition']['texture']] if 'partition' in slot else [])
                                or material["opacity"] != 1
                                or material["transmission"] or material["issues"]
                                or row.get("material_triangles", {}).get(slot["material"]) != slot["triangles"]
                                or row.get("material_geometry_sha256", {}).get(slot["material"]) != slot["position_triangles_sha256"]):
                            retained.append("unsafe_or_unresolved_explicit_part")
                    if not retained:
                        row["role"] = definition["editable_role"]
                        row["editable_slots"] = explicit["editable_slots"]
                        result["editable_count"] += len(explicit["editable_slots"])
                    else:
                        row["protection_reason"] = ";".join(dict.fromkeys(retained))
                elif selected and not reasons:
                    row["role"] = definition["editable_role"]
                    result["editable_count"] += 1
                else:
                    row["protection_reason"] = ";".join(dict.fromkeys(reasons))
                result["visuals"].append(row)
    if not result["editable_count"]:
        issue("No proven-safe editable visuals found; asset binding remains pending")
    result["files"] = dict(sorted(result["files"].items()))
    result["missing"].sort()
    return result
