"""Static checks and runtime entry for Nut & Bolt appearance.

This script never imports task modules or starts a renderer/simulator. Missing
source assets and all runtime observations remain explicitly pending.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
FAMILY = ROOT / "assets/appearance/objects/nut_bolt"
SOURCE = ROOT / "tasks/nut_bolt/nut_bolt_long.py"
OUTPUT_ROOTS = (ROOT / "outputs/variation/nut_bolt", ROOT / ".local/nut_bolt")
ROLES = {"bolt": {"shaft", "head"}, "nut": {"body", "reference_face"}}
PRESERVED = {"bolt": ["tip", "thread"], "nut": []}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def call_name(node: ast.AST) -> str:
    return ast.unparse(node.func) if isinstance(node, ast.Call) else ""


def calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [item for item in ast.walk(node) if isinstance(item, ast.Call)
            and call_name(item).endswith(name)]


def literal_keyword(call: ast.Call, name: str):
    for keyword in call.keywords:
        if keyword.arg == name:
            return ast.literal_eval(keyword.value)
    raise ValueError(f"Missing literal keyword {name}")


def class_assignments(node: ast.ClassDef) -> dict:
    result = {}
    for item in node.body:
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    try:
                        result[target.id] = ast.literal_eval(item.value)
                    except (ValueError, TypeError):
                        pass
    return result


def numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def material_valid(material: dict) -> bool:
    if not isinstance(material, dict) or set(material) != {"base_color", "roughness", "metallic"}:
        return False
    color = material["base_color"]
    return (isinstance(color, list) and len(color) == 4
            and all(numeric(v) and 0 <= v <= 1 for v in color)
            and color[3] == 1
            and all(numeric(material[k]) and 0 <= material[k] <= 1
                    for k in ("roughness", "metallic")))


def inspect_catalog(obj: str, check, source_audit: dict) -> dict:
    path = FAMILY / obj / "variants/v1/catalog.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    check(f"{obj}.catalog_version", data.get("version") == f"nut-bolt-{obj}-appearance-v1")
    check(f"{obj}.object_id", data.get("object_id") == f"nut_bolt.{obj}")
    check(f"{obj}.preserve_roles", data.get("preserve_roles") == PRESERVED[obj])
    check(f"{obj}.preview_scope", data.get("scope") == "material_appearance")
    check(f"{obj}.no_new_uv_or_textures", data.get("new_uv") is False and data.get("new_textures") == [])
    check(f"{obj}.material_fields", data.get("fields") == ["base_color", "roughness", "metallic"])
    schemes = data.get("schemes", {})
    check(f"{obj}.scheme_ids", set(schemes) == {"original", "variant_1", "variant_2"})
    check(f"{obj}.original_restores_native", schemes.get("original") == {"mode": "restore_native"})
    for scheme_id in ("variant_1", "variant_2"):
        scheme = schemes.get(scheme_id, {})
        roles = scheme.get("roles", {})
        check(f"{obj}.{scheme_id}.mode", scheme.get("mode") == "material_override")
        check(f"{obj}.{scheme_id}.roles", set(roles) == ROLES[obj])
        for role in ROLES[obj]:
            check(f"{obj}.{scheme_id}.{role}.ranges", material_valid(roles.get(role)))
        if obj == "nut" and set(roles) == ROLES[obj]:
            check(f"{obj}.{scheme_id}.rotation_reference_contrast",
                  max(abs(a-b) for a, b in zip(roles["body"]["base_color"][:3],
                                               roles["reference_face"]["base_color"][:3])) >= 0.25)
    first = schemes.get("variant_1", {}).get("roles", {})
    second = schemes.get("variant_2", {}).get("roles", {})
    check(f"{obj}.candidate_color_difference", any(
        role in first and role in second and material_valid(first[role]) and material_valid(second[role])
        and max(abs(a-b) for a, b in zip(first[role]["base_color"][:3],
                                       second[role]["base_color"][:3])) >= 0.25
        for role in ROLES[obj]))
    bindings_path = FAMILY / obj / "bindings.json"
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    reference = bindings.get("catalog", "")
    resolved = (bindings_path.parent / reference).resolve()
    check(f"{obj}.binding_catalog_reference", resolved == path.resolve())
    check(f"{obj}.binding_roles", set(bindings.get("roles", {})) == ROLES[obj] | set(PRESERVED[obj]))
    check(f"{obj}.formal_integration_declared", bindings.get("stage") == "formal_integration_runtime_pending"
          and bindings.get("formal_task_integration") is True)
    check(f"{obj}.binding_identity", bindings.get("logical_object") == f"nut_bolt.{obj}"
          and bindings.get("source") == relative(SOURCE))
    roles = bindings.get("roles", {})
    if obj == "nut":
        check("nut.reference_segment", roles.get("reference_face", {}).get("segment_indices") == [0])
        check("nut.body_segments", roles.get("body", {}).get("segment_indices") == [1, 2, 3, 4, 5])
        expected_tasks = {"SeatNut", "TurnNut", "Long"}
        for task, representation in bindings.get("representations", {}).items():
            for kind in ("free", "threaded"):
                count = source_audit.get("nut_visual_counts", {}).get(kind)
                check(f"nut.{task}.{kind}.record_count", count is not None
                      and representation.get(kind, {}).get("expected_visual_records") == count)
    else:
        expected_tasks = {"PickBolt", "SeatNut", "TurnNut", "Long"}
        source_indices = source_audit.get("bolt_visual_records", {}).get("indices_by_role", {})
        for role in ROLES[obj] | set(PRESERVED[obj]):
            entry = roles.get(role, {})
            indices = entry.get("record_indices")
            if indices is None:
                interval = entry.get("record_range_inclusive", [])
                indices = list(range(interval[0], interval[1] + 1)) if len(interval) == 2 else None
            check(f"bolt.{role}.source_record_indices", indices is not None and indices == source_indices.get(role))
            check(f"bolt.{role}.editable", entry.get("editable") is (role in ROLES[obj]))
        for task, representation in bindings.get("representations", {}).items():
            check(f"bolt.{task}.record_count", representation.get("expected_visual_records")
                  == source_audit.get("bolt_visual_records", {}).get("total"))
    check(f"{obj}.binding_task_coverage", set(bindings.get("representations", {})) == expected_tasks)
    return {"catalog": relative(path), "sha256": sha256(path), "bindings": relative(bindings_path)}


class MemoryPath:
    """The extracted generator can only write its derived XML to memory."""
    def __init__(self):
        self.text = None

    def exists(self):
        return self.text is not None

    def read_text(self, *args, **kwargs):
        return self.text

    def write_text(self, text, *args, **kwargs):
        self.text = text
        return len(text)


def scalar_expression(node: ast.AST, variables: dict, constants: dict):
    """Evaluate only arithmetic needed by source loop bounds, never task code."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return variables[node.id]
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            return constants[node.attr]
        if ast.unparse(node) == "np.pi":
            return math.pi
    if isinstance(node, (ast.List, ast.Tuple)):
        return [scalar_expression(item, variables, constants) for item in node.elts]
    if isinstance(node, ast.UnaryOp):
        value = scalar_expression(node.operand, variables, constants)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
    if isinstance(node, ast.BinOp):
        left = scalar_expression(node.left, variables, constants)
        right = scalar_expression(node.right, variables, constants)
        operations = {ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
                      ast.Mult: lambda: left * right, ast.Div: lambda: left / right,
                      ast.Pow: lambda: left ** right}
        if type(node.op) in operations:
            return operations[type(node.op)]()
    if isinstance(node, ast.Call):
        allowed = {"range": range, "int": int, "round": round, "np.sqrt": math.sqrt,
                   "np.cos": math.cos, "np.sin": math.sin}
        function = allowed.get(call_name(node))
        if function is not None and not node.keywords:
            return function(*(scalar_expression(arg, variables, constants) for arg in node.args))
    raise ValueError(f"Unsupported source count expression: {ast.unparse(node)}")


def count_visual_records(method: ast.FunctionDef, constants: dict) -> list[dict]:
    """Count source visual calls with statically evaluated native for loops."""
    records = []
    def contains_visual(node):
        return any(isinstance(item, ast.Call) and call_name(item).startswith("builder.add_")
                   and "visual" in call_name(item) for item in ast.walk(node))
    def visit(statements, variables, multiplier=1, loop_bounds=()):
        for statement in statements:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
                try:
                    variables[statement.targets[0].id] = scalar_expression(statement.value, variables, constants)
                except (ValueError, KeyError, TypeError):
                    pass
            elif isinstance(statement, ast.For) and contains_visual(statement):
                values = scalar_expression(statement.iter, variables, constants)
                if not isinstance(values, range) or not isinstance(statement.target, ast.Name):
                    raise ValueError("Visual loop must use a statically resolved range and simple target")
                inner = dict(variables)
                if values:
                    inner[statement.target.id] = values[0]
                visit(statement.body, inner, multiplier * len(values), loop_bounds + (ast.unparse(statement.iter),))
                if statement.orelse:
                    visit(statement.orelse, dict(variables), multiplier, loop_bounds)
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and contains_visual(statement):
                records.append({"call": call_name(statement.value), "count": multiplier,
                                "line": statement.lineno, "loop_bounds": list(loop_bounds)})
            elif contains_visual(statement):
                raise ValueError(f"Unexpected visual control structure at line {statement.lineno}")
    visit(method.body, {})
    return records


def bolt_record_mapping(method: ast.FunctionDef, constants: dict, check) -> dict:
    records = count_visual_records(method, constants)
    index = 0
    mapping = {}
    for record in records:
        name = record["call"].rsplit(".", 1)[-1]
        if name == "add_cylinder_visual":
            role = "tip" if record["loop_bounds"] else "shaft"
        elif name == "add_capsule_visual":
            role = "thread"
        elif name == "add_visual_from_file":
            role = "head"
        else:
            raise ValueError(f"Unknown bolt visual type: {name}")
        if role in mapping:
            raise ValueError(f"More than one source record site for role {role}")
        mapping[role] = list(range(index, index + record["count"]))
        index += record["count"]
    check("source.bolt_record_roles", set(mapping) == {"shaft", "tip", "thread", "head"})
    return {"total": index, "counts_by_role": {role: len(indices) for role, indices in mapping.items()},
            "indices_by_role": mapping, "source_sites": records,
            "note": "Counts derived from native AST loop bounds; head render-shape count remains asset dependent"}


def inspect_generated_urdf(method: ast.FunctionDef, constants: dict, check) -> dict:
    memory = MemoryPath()
    namespace = {"np": math, "Path": MemoryPath, "THREADED_NUT_URDF_PATH": memory}
    code = ast.Module(body=[method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(code), "<extracted_nut_urdf_generator>", "exec"), namespace)
    namespace[method.name](SimpleNamespace(**constants))
    tree = ET.fromstring(memory.text)
    links = tree.findall("link")
    joint = tree.find("joint")
    check("urdf.link_names", {link.attrib["name"] for link in links} == {"nut_mount", "threaded_nut"})
    check("urdf.single_continuous_joint", len(tree.findall("joint")) == 1 and joint is not None
          and joint.attrib == {"name": "nut_turn_joint", "type": "continuous"})
    if joint is not None:
        check("urdf.joint_parent_child", joint.find("parent").get("link") == "nut_mount"
              and joint.find("child").get("link") == "threaded_nut")
        check("urdf.joint_axis", joint.find("axis").get("xyz") == "0 0 1")
    nut = tree.find("link[@name='threaded_nut']")
    visuals = nut.findall("visual")
    collisions = nut.findall("collision")
    check("urdf.six_visuals_and_collisions", len(visuals) == len(collisions) == 6)
    origins = []
    for i, (visual, collision) in enumerate(zip(visuals, collisions)):
        check(f"urdf.segment_{i}.matching_geometry",
              visual.find("origin").attrib == collision.find("origin").attrib
              and visual.find("geometry/box").attrib == collision.find("geometry/box").attrib)
        check(f"urdf.segment_{i}.native_material", visual.find("material").get("name") == "nut_orange")
        origins.append(visual.find("origin").attrib)
    return {"execution": "AST-extracted method; math substitutes numpy; in-memory output only",
            "links": [link.attrib["name"] for link in links], "visual_count": len(visuals),
            "collision_count": len(collisions), "segment_origins": origins,
            "native_urdf_material": "RGBA only; roughness/metallic remain loader defaults",
            "sha256": hashlib.sha256(memory.text.encode()).hexdigest()}


def inspect_sources(check) -> dict:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "NutBoltLongEnv")
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    constants = class_assignments(cls)
    check('source.family_reseed_guard', any(ast.unparse(base) == 'NutBoltResetScopeMixin' for base in cls.bases))
    check("source.shared_scene_builders", all(calls(methods["_load_scene"], name) for name in
          ("self._load_bolt", "self._load_platform", "self._load_nut", "self._load_threaded_nut")))
    bolt = methods["_load_bolt"]
    bolt_material = calls(bolt, "sapien.render.RenderMaterial")[0]
    check("source.bolt_native_material", all(literal_keyword(bolt_material, key) == value for key, value in {
          "base_color": [0.55, 0.55, 0.60, 1.0], "roughness": 0.4, "metallic": 0.8}.items()))
    check("source.bolt_dynamic_actor", any(literal_keyword(c, "name") == "bolt" for c in calls(bolt, "builder.build")))
    check("source.bolt_head_file", len(calls(bolt, "builder.add_visual_from_file")) == 1
          and any(isinstance(n, ast.Name) and n.id == "BOLT_HEX_HEAD_PATH" for n in ast.walk(bolt)))
    head_calls = calls(bolt, "builder.add_visual_from_file")
    check("source.head_explicit_native_render_material_override", len(head_calls) == 1 and any(
          keyword.arg == "material" and isinstance(keyword.value, ast.Name)
          and keyword.value.id == "render_material" for keyword in head_calls[0].keywords))
    check("source.bolt_visual_families", len(calls(bolt, "builder.add_cylinder_visual")) == 2
          and len(calls(bolt, "builder.add_capsule_visual")) == 1)
    platform_calls = [call_name(c).rsplit(".", 1)[-1] for c in ast.walk(methods["_load_platform"])
                      if isinstance(c, ast.Call)]
    check("source.platform_has_no_visual", "add_cylinder_collision" in platform_calls
          and not any("visual" in name for name in platform_calls))
    check("source.nut_six_segments", any(isinstance(n, ast.For) and ast.unparse(n.iter) == "range(6)"
          for n in ast.walk(methods["_load_nut"])))
    nut_material = calls(methods["_load_nut"], "sapien.render.RenderMaterial")[0]
    check("source.nut_native_material", all(literal_keyword(nut_material, key) == value for key, value in {
          "base_color": [0.90, 0.50, 0.10, 1.0], "roughness": 0.6, "metallic": 0.3}.items()))
    check("source.nut_dynamic_actor", any(literal_keyword(c, "name") == "nut"
          for c in calls(methods["_load_nut"], "builder.build")))
    threaded = methods["_load_threaded_nut"]
    check("source.threaded_fixed_root", any(isinstance(n, ast.Assign)
          and any(ast.unparse(t) == "loader.fix_root_link" for t in n.targets)
          and isinstance(n.value, ast.Constant) and n.value.value is True for n in ast.walk(threaded)))
    check("source.visibility_preserved_in_native_task", len(calls(methods["_sync_nut_visibility"], "self._set_body_visibility")) == 2)
    hold = methods["_refresh_hold_state"]
    gpu_hold = SOURCE.with_name('gpu_hold.py').read_text(encoding='utf-8')
    check('source.native_gpu_hold_capability_gate', bool(calls(hold, 'refresh_gpu_hold_state'))
          and 'native_gpu_lock_sync_patch_version' in gpu_hold
          and 'indexed_gpu_apply_patch_version' in gpu_hold)
    task_map = {}
    expected = {
        "pick_bolt": ("NutBoltPickBoltEnv", {"has_platform": False, "has_nut": False}, "_place_bolt"),
        "seat_nut": ("NutBoltSeatNutEnv", {}, "_place_nut_on_table"),
        "turn_nut": ("NutBoltTurnNutEnv", {}, "_place_nut_on_platform"),
    }
    for short, (class_name, flags, place) in expected.items():
        path = SOURCE.with_name(f"nut_bolt_{short}.py")
        short_tree = ast.parse(path.read_text(encoding="utf-8"))
        short_cls = next(n for n in short_tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
        values = class_assignments(short_cls)
        check(f"source.{short}.inherits_shared_builders", any(ast.unparse(b) == "NutBoltLongEnv" for b in short_cls.bases)
              and not any(isinstance(n, ast.FunctionDef) and n.name.startswith("_load_") for n in short_cls.body))
        check(f"source.{short}.native_flags", all(values.get(k) == v for k, v in flags.items()))
        check(f"source.{short}.native_initialization", bool(calls(short_cls, "self." + place)))
        task_map[short] = {"source": relative(path), "sha256": sha256(path), "flags": values, "initialization": place}
    native_urdf = inspect_generated_urdf(methods["_generate_threaded_nut_urdf"], constants, check)
    free_records = count_visual_records(methods["_load_nut"], constants)
    free_count = sum(record["count"] for record in free_records)
    check("source.nut_twin_record_counts", free_count == native_urdf["visual_count"])
    return {"source": relative(SOURCE), "sha256": sha256(SOURCE), "tasks": task_map,
            "native_urdf": native_urdf, "bolt_visual_records": bolt_record_mapping(bolt, constants, check),
            "nut_visual_counts": {"free": free_count, "threaded": native_urdf["visual_count"]},
            "nut_source_sites": free_records}


def inspect_obj(pending: list, check) -> dict:
    path = ROOT / "tasks/assets/task_object_meshes/screwing/bolt_hex_head.obj"
    if not path.is_file():
        pending.append("bolt_hex_head.obj absent: OBJ UV/material/topology and true task render remain unverified")
        return {"path": relative(path), "status": "missing"}
    raw = path.read_bytes()
    identity = json.loads((FAMILY / "bolt/bindings.json").read_text(encoding="utf-8"))["asset"]
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    check("asset.size_identity", len(raw) == identity["size_bytes"])
    check("asset.sha256_identity", sha256(path) == identity["sha256"])
    check("asset.git_blob_identity", blob == identity["git_blob_sha1"])
    counts = {"v": 0, "vt": 0, "vn": 0, "f": 0}
    refs = {"mtllib": set(), "usemtl": set(), "o": set(), "g": set()}
    vertices, faces = [], []
    textured_faces = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] in counts:
            counts[fields[0]] += 1
        if fields[0] in refs:
            refs[fields[0]].add(" ".join(fields[1:]))
        if fields[0] == "v":
            vertices.append(tuple(float(value) for value in fields[1:4]))
        if fields[0] == "f":
            faces.append([int(value.split("/")[0]) for value in fields[1:]])
        if fields[0] == "f" and any(len(v.split("/")) > 1 and v.split("/")[1] for v in fields[1:]):
            textured_faces += 1
    valid_indices = bool(vertices and faces) and all(1 <= index <= len(vertices) for face in faces for index in face)
    triangles = all(len(face) == 3 for face in faces)
    check("asset.positive_vertex_indices", valid_indices)
    check("asset.triangle_faces", triangles)
    check("asset.finite_vertices", all(len(v) == 3 and all(math.isfinite(c) for c in v) for v in vertices))
    check("asset.no_uv_or_material_dependencies", counts["vt"] == 0 and not textured_faces
          and not refs["mtllib"] and not refs["usemtl"])
    check("asset.no_object_or_group_split", not refs["o"] and not refs["g"])
    if not valid_indices or not triangles:
        raise ValueError("Expected original triangle mesh with positive valid vertex indices")
    edges, directed, adjacency = {}, {}, {i: set() for i in range(1, len(vertices) + 1)}
    degenerates, volume = 0, 0.0
    for face in faces:
        a, b, c = (vertices[index - 1] for index in face)
        ab, ac = ([b[k] - a[k] for k in range(3)], [c[k] - a[k] for k in range(3)])
        cross = [ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0]]
        degenerates += sum(value*value for value in cross) <= 1e-24
        volume += (a[0]*(b[1]*c[2]-b[2]*c[1]) + a[1]*(b[2]*c[0]-b[0]*c[2])
                   + a[2]*(b[0]*c[1]-b[1]*c[0])) / 6
        for u, v in zip(face, face[1:] + face[:1]):
            edge = tuple(sorted((u, v)))
            edges[edge] = edges.get(edge, 0) + 1
            directed[(u, v)] = directed.get((u, v), 0) + 1
            adjacency[u].add(v)
            adjacency[v].add(u)
    remaining, components = set(adjacency), 0
    while remaining:
        stack = [remaining.pop()]
        components += 1
        while stack:
            for neighbor in adjacency[stack.pop()] & remaining:
                remaining.remove(neighbor)
                stack.append(neighbor)
    boundary = sum(count == 1 for count in edges.values())
    nonmanifold = sum(count != 2 for count in edges.values())
    winding = all(directed.get((u, v), 0) == directed.get((v, u), 0) == 1 for u, v in edges)
    check("asset.single_connected_component", components == 1)
    check("asset.closed_oriented_manifold", not boundary and not nonmanifold and winding)
    check("asset.no_degenerate_triangles", degenerates == 0)
    check("asset.positive_signed_volume", volume > 0)
    bounds = {"min": [min(v[k] for v in vertices) for k in range(3)],
              "max": [max(v[k] for v in vertices) for k in range(3)]}
    pending.append("Actual SAPIEN head render-shape/material-part splitting and task loading have not been run")
    return {"path": relative(path), "status": "verified_source_structure_runtime_pending",
            "size_bytes": len(raw), "sha256": sha256(path), "git_blob_sha1": blob,
            "counts": counts, "faces_with_uv_reference": textured_faces,
            "references": {key: sorted(value) for key, value in refs.items()},
            "bounds_m": bounds, "topology": {"connected_components": components, "edges": len(edges),
                "boundary_edges": boundary, "nonmanifold_edges": nonmanifold, "consistent_winding": winding,
                "degenerate_triangles": degenerates, "euler_characteristic": len(vertices)-len(edges)+len(faces),
                "signed_volume_m3": volume},
            "runtime_material": "Native task explicitly overrides imported head material"}


def output_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not any(path.is_relative_to(base.resolve()) for base in OUTPUT_ROOTS):
        raise ValueError("--output must be under outputs/variation/nut_bolt or .local/nut_bolt")
    return path


def inspect_runtime_index(check):
    path = ROOT / 'tasks/assets/variation/nut_bolt/v1/catalog.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    check('runtime.catalog_version', data.get('version') == 'nut-bolt-appearance-v1')
    check('runtime.material_scope', data.get('scope') == 'material_appearance')
    check('runtime.scheme_ids', data.get('schemes') == ['original', 'variant_1', 'variant_2'])
    check('runtime.objects', set(data.get('objects', {})) == {'bolt', 'nut'})
    check('runtime.short_tasks', data.get('tasks') == {
        'PickBolt': ['bolt'], 'SeatNut': ['bolt', 'nut'], 'TurnNut': ['bolt', 'nut']})
    for object_id, entry in data.get('objects', {}).items():
        check(f'runtime.{object_id}.single_parameter_source',
              (ROOT / entry.get('catalog', '')).resolve() ==
              (FAMILY / object_id / 'variants/v1/catalog.json').resolve())
        check(f'runtime.{object_id}.scheme_map', entry.get('scheme_map') == {
            name: name for name in ('original', 'variant_1', 'variant_2')})
    for name in ('default', 'fixed', 'random'):
        example = json.loads((ROOT / f'examples/variation/nut_bolt/{name}.json').read_text())
        check(f'example.{name}.task', example.get('task_id') in {
            f'NutBolt{task}-Sharpa-v1' for task in data['tasks']})
        check(f'example.{name}.enabled', type(example.get('nut_bolt_appearance', {}).get('enabled')) is bool)
    return {'path': relative(path), 'sha256': sha256(path)}


def main() -> int:
    import sys
    if "--approved-runtime" in sys.argv:
        sys.path.insert(0, str(ROOT))
        from tools.variation.check_nut_bolt_runtime import main as runtime_main
        return runtime_main()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static", action="store_true", help="No simulator or renderer")
    parser.add_argument("--output", help="Optional JSON report in a family-owned output directory")
    args = parser.parse_args()
    checks, errors = [], []
    pending = ["No simulator, renderer, task reset, physical invariance, or parallel-environment checks were run",
               "GPU holds require both native lock-sync and indexed-apply capabilities; family runtime acceptance is separate"]
    def check(name, passed):
        checks.append({"check": name, "passed": bool(passed)})
        if not passed:
            errors.append(name)
    report = {"scope": "nut_bolt_cpu_static_only", "checks": checks, "errors": errors, "pending": pending}
    try:
        report['runtime_index'] = inspect_runtime_index(check)
    except Exception as exc:
        errors.append(f'runtime_index: {type(exc).__name__}: {exc}')
    try:
        report["source_audit"] = inspect_sources(check)
    except Exception as exc:
        errors.append(f"source_audit: {type(exc).__name__}: {exc}")
    for obj in ROLES:
        try:
            report[obj] = inspect_catalog(obj, check, report.get("source_audit", {}))
        except Exception as exc:
            errors.append(f"{obj}: {type(exc).__name__}: {exc}")
    try:
        report["head_asset"] = inspect_obj(pending, check)
    except Exception as exc:
        errors.append(f"head_asset: {type(exc).__name__}: {exc}")
    syntax = []
    sources = list((ROOT / 'tools/variation').glob('*nut_bolt*.py')) + list((ROOT / 'tasks/nut_bolt').glob('*.py'))
    for path in sorted(sources):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            syntax.append(relative(path))
        except SyntaxError as exc:
            errors.append(f"syntax: {relative(path)}: {exc}")
    report["syntax_checked"] = syntax
    report["status"] = "failed" if errors else "static_checks_passed_runtime_pending"
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        try:
            destination = output_path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(encoded + "\n", encoding="utf-8")
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
    print(encoded)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
