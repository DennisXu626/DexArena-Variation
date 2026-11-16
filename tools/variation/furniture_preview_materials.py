"""Source definitions, measured bindings and invariant reads for furniture previews.

Only material base_color/roughness/metallic may be written. The real task owns
all geometry, physics, poses and resets; this helper supports one environment
of the three declared short tasks and adds no formal appearance interface.
"""
from dataclasses import dataclass
import hashlib
import math

import numpy as np

PANEL_EDITABLE_ROLES = ("face", "cut", "edge", "routed")


_BASE = np.array([0.725, 0.541, 0.369, 1.0])


_NATIVE = {
    "face": (_BASE, 0.72),
    "cut": (np.r_[_BASE[:3] * 0.76, 1.0], 0.86),
    "edge": (np.r_[_BASE[:3] * 0.60, 1.0], 0.62),
    "routed": (np.r_[_BASE[:3] * 0.88, 1.0], 0.45),
    "label": (np.array([0.93, 0.92, 0.88, 1.0]), 0.65),
    "ink": (np.array([0.10, 0.10, 0.12, 1.0]), 0.8),
}


_MATERIAL_FIELDS = (
    "base_color", "roughness", "metallic", "specular", "emission", "ior",
    "transmission", "transmission_roughness", "base_color_texture",
    "roughness_texture", "metallic_texture", "normal_texture",
    "emission_texture", "transmission_texture",
)


def _json(value):
    if hasattr(value, "detach"):
        return _json(value.detach().cpu().tolist())
    if isinstance(value, np.ndarray):
        return _json(value.tolist())
    if isinstance(value, np.generic):
        return _json(value.item())
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _pose(pose):
    return {"p": _json(pose.p), "q_wxyz": _json(pose.q)}


def _material(material):
    result = {}
    for field in _MATERIAL_FIELDS:
        value = getattr(material, field)
        if field.endswith("_texture"):
            value = None if value is None else {
                "filename": value.filename, "width": value.width,
                "height": value.height, "format": value.format,
                "mipmap_levels": value.mipmap_levels,
            }
        result[field] = _json(value)
    return result


def _visual_specs():
    """Source builder's 20 boxes and two mouth wedges; lengths are metres."""
    specs = []

    def box(name, role, p, half, yaw=0.0):
        specs.append(dict(name=name, role=role, p=p, half=half,
                          q=[np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]))

    box("base_slab", "face", [0, 0, -0.004], [0.190, 0.095, 0.005])
    for sign in (-1, 1):
        box(f"straight_wall_{sign}", "face", [0.070, sign * 0.05475, 0.005],
            [0.120, 0.04025, 0.004])
    box("stop_wall", "cut", [0.180, 0, 0.005], [0.010, 0.0145, 0.004])
    for sign in (-1, 1):
        quad = [(-0.190, sign * 0.0595), (-0.190, sign * 0.095),
                (-0.050, sign * 0.095), (-0.050, sign * 0.0145)]
        specs.append(dict(name=f"mouth_wedge_{sign}", role="face",
                          vertices=np.array([[x, y, z] for z in (0.001, 0.009)
                                             for x, y in quad])))
    box("groove_floor_overlay", "cut", [-0.010, 0, 0.0013], [0.180, 0.014, 0.0003])
    for sign in (-1, 1):
        box(f"end_banding_{sign}", "edge", [sign * 0.1906, 0, 0], [0.0006, 0.095, 0.009])
        box(f"side_banding_{sign}", "edge", [0, sign * 0.0956, 0], [0.190, 0.0006, 0.009])
    length = np.hypot(0.140, 0.045)
    for sign in (-1, 1):
        box(f"straight_lip_{sign}", "routed", [0.070, sign * 0.0165, 0.0093],
            [0.120, 0.002, 0.0003])
        mid = np.array([-0.120, sign * 0.037]) + 0.002 * np.array([0.045, sign * 0.140]) / length
        box(f"flared_lip_{sign}", "routed", [*mid, 0.0093],
            [length / 2, 0.002, 0.0003], np.arctan2(-sign * 0.045, 0.140))
    box("part_label", "label", [-0.100, 0.045, 0.0094], [0.021, 0.012, 0.0002])
    for i in range(6):
        box(f"barcode_{i}", "ink", [-0.114 + i * 0.0056, 0.045, 0.0097],
            [0.0011, 0.008, 0.0001])
    return specs


def _matches(shape, spec):
    import sapien.render as sr

    close = lambda a, b: np.allclose(a, b, rtol=0, atol=1e-6)
    if "half" in spec:
        return (isinstance(shape, sr.RenderShapeBox)
                and close(shape.half_size, spec["half"])
                and close(shape.local_pose.p, spec["p"])
                and (close(shape.local_pose.q, spec["q"])
                     or close(shape.local_pose.q, -np.asarray(spec["q"]))))
    if not isinstance(shape, sr.RenderShapeTriangleMesh):
        return False
    if not (close(shape.scale, [1, 1, 1]) and close(shape.local_pose.p, [0, 0, 0])
            and (close(shape.local_pose.q, [1, 0, 0, 0])
                 or close(shape.local_pose.q, [-1, 0, 0, 0]))):
        return False
    vertices = np.unique(np.round(np.concatenate([p.vertices for p in shape.parts]), 7), axis=0)
    expected = spec["vertices"]
    return (vertices.shape == expected.shape
            and np.all(np.min(np.linalg.norm(vertices[:, None] - expected[None], axis=2), axis=1) < 1e-6))


def _array_digest(value):
    array = np.ascontiguousarray(value)
    return dict(shape=list(array.shape), dtype=str(array.dtype),
                sha256=hashlib.sha256(array.tobytes()).hexdigest())


def _geometry(shape):
    result = dict(type=type(shape).__name__, local_pose=_pose(shape.local_pose))
    for field in ("half_size", "scale", "radius", "half_length", "front_face"):
        if hasattr(shape, field):
            result[field] = _json(getattr(shape, field))
    if hasattr(shape, "parts"):
        result["parts"] = [
            {"vertices": _array_digest(part.vertices), "triangles": _array_digest(part.triangles),
             "vertex_normal": _array_digest(part.get_vertex_normal()),
             "vertex_uv": _array_digest(part.get_vertex_uv())}
            for part in shape.parts]
    elif hasattr(shape, "vertices"):
        result["vertices"] = _array_digest(shape.vertices)
        result["triangles"] = _array_digest(shape.triangles)
    return result


TASKS = {
    "FurnitureAssemblyLayFlatPanelEnv": "FurnitureAssemblyLayFlatPanel-Sharpa-v1",
    "FurnitureAssemblyInsertRailEnv": "FurnitureAssemblyInsertRail-Sharpa-v1",
    "FurnitureAssemblyFastenScrewEnv": "FurnitureAssemblyFastenScrew-Sharpa-v1",
}
FIELDS = ("base_color", "roughness", "metallic")


@dataclass
class ObjectBinding:
    env: object
    object_id: str
    definition: dict
    groups: dict
    rows: list


@dataclass
class FamilyBinding:
    env: object
    objects: dict


def _entity(handle):
    import sapien

    raw, = handle._objs
    entity = getattr(raw, "entity", raw)
    if not isinstance(entity, sapien.Entity):
        raise TypeError("Furniture handle must resolve to a real SAPIEN Entity")
    return entity


def _flat_definition(base):
    entity = _entity(base.panel)
    specs = _visual_specs()
    return {
        "entities": [("panel", entity)],
        "roles": {role: {
            "native": {"base_color": color.tolist(), "roughness": roughness, "metallic": 0.0},
            "editable": role not in ("label", "ink"),
            "expected_shape_count": sum(spec["role"] == role for spec in specs),
        } for role, (color, roughness) in _NATIVE.items()},
        "expected_shape_count": 22,
        "detail": {"target": [float(v) for v in entity.pose.p], "eye_offset": [0.32, -0.42, 0.28]},
    }


def _role(color, roughness, metallic, editable, count):
    return {"native": {"base_color": color, "roughness": roughness, "metallic": metallic},
            "editable": editable, "expected_shape_count": count}


def _world_center(entity, local_height):
    pose = entity.pose
    p = [float(value) for value in pose.p]
    w, x, y, z = [float(value) for value in pose.q]
    normal = (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))
    return [p[i] + local_height * normal[i] for i in range(3)]


def _definitions(base, task_id):
    """Keep task-specific source roles/counts; never add absent objects."""
    result = {"flat_panel": _flat_definition(base)}
    if task_id == TASKS["FurnitureAssemblyLayFlatPanelEnv"]:
        if not hasattr(base, "rack"):
            raise ValueError("The selected task has no panel-rack actor")
        rack = _entity(base.rack)
        matrix = rack.pose.to_transformation_matrix()
        result["panel_rack"] = {
            "entities": [("rack", rack)],
            "roles": {
                "body": _role([0.29, 0.31, 0.34, 1.0], 0.55, 0.35, True, 8),
                "plate": _role([0.21, 0.23, 0.26, 1.0], 0.70, 0.30, True, 1),
                "pad": _role([0.12, 0.14, 0.16, 1.0], 0.9, 0.0, False, 6),
                "bolt": _role([0.62, 0.64, 0.67, 1.0], 0.30, 0.90, False, 8),
                "decal": _role([0.85, 0.68, 0.15, 1.0], 0.55, 0.0, False, 9),
            },
            "expected_shape_count": 32,
            "detail": {"target": [float(matrix[i, 3] + 0.045 * matrix[i, 2]) for i in range(3)],
                       "eye_offset": [0.48, -0.48, 0.34]},
        }
        return result
    rail = _entity(base.rail_body)
    if rail != _entity(base.rail.links_map["rail_body"]):
        raise ValueError("rail_body does not belong to the task rail articulation")
    insert = task_id == TASKS["FurnitureAssemblyInsertRailEnv"]
    # InsertRail nests its two-lip/nine-slot details in the two-flange loop;
    # FastenScrew adds them once. Preserve this source geometry difference.
    detail_count = 22 if insert else 11
    result["rail"] = {
        "entities": [("rail_body", rail)],
        "roles": {
            "metal_body": _role([0.66, 0.68, 0.72, 1.0], 0.28, 0.92, True, 3),
            "channel_details": _role([0.42, 0.44, 0.48, 1.0], 0.42, 0.85, True, detail_count),
        },
        "expected_shape_count": 3 + detail_count,
        "detail": {"target": [float(value) for value in rail.pose.p], "eye_offset": [0.22, -0.32, 0.25]},
    }
    head = _entity(base.screw_head)
    if insert:
        roles = {"grip": _role([0.08, 0.09, 0.10, 1.0], 0.55, 0.55, True, 17),
                 "reference": _role([0.96, 0.82, 0.30, 1.0], 0.55, 0.25, False, 4)}
        total, height, offset = 21, 0.004, [0.055, -0.075, 0.085]
    else:
        roles = {"grip": _role([0.10, 0.10, 0.11, 1.0], 0.60, 0.10, True, 2),
                 "reference": _role([0.92, 0.78, 0.26, 1.0], 0.50, 0.30, False, 2)}
        total, height, offset = 4, 0.026, [0.10, -0.15, 0.13]
    result["screw"] = {"entities": [("screw_head", head)], "roles": roles,
                       "expected_shape_count": total,
                       "detail": {"target": _world_center(head, height), "eye_offset": offset}}
    return result


def _signature_matches(material, params):
    return (np.allclose(material.base_color, params["base_color"], rtol=0, atol=2e-6)
            and abs(material.roughness - params["roughness"]) < 2e-6
            and abs(material.metallic - params["metallic"]) < 2e-6)


def inspect_furniture(env):
    """Bind all present furniture objects after a native reset; fail on mismatch.

    Source roles are semantic names, not alleged engine material names. Flat
    panel geometry is matched precisely; the other objects use their complete
    native PBR signatures within the definition's explicitly selected entities.
    """
    import sapien.render as sr

    base = env.unwrapped
    task_id = TASKS.get(type(base).__name__)
    declared_id = getattr(getattr(env, "spec", None), "id", None)
    if (task_id is None or base.num_envs != 1 or not base.visual_detail
            or (declared_id is not None and declared_id != task_id)):
        raise ValueError("Furniture preview requires one supported Sharpa task with visual_detail=True")
    if getattr(base, "panel_color_jitter", False):
        raise ValueError("Disable panel_color_jitter for native source-signature binding")
    definitions = _definitions(base, task_id)
    objects, all_entities, owners = {}, [], []
    for object_id, definition in definitions.items():
        groups = {role: [] for role in definition["roles"]}
        rows, counts = [], {role: set() for role in groups}
        specs = _visual_specs() if object_id == "flat_panel" else None
        for semantic, entity in definition["entities"]:
            if any(entity == previous for previous in all_entities):
                raise ValueError(f"{object_id}: target entity already belongs to another furniture object")
            all_entities.append(entity)
            body = entity.find_component_by_type(sr.RenderBodyComponent)
            if body is None:
                raise ValueError(f"{object_id}/{semantic}: no actual RenderBodyComponent")
            for si, shape in enumerate(body.render_shapes):
                source_part, source_role = None, None
                if specs is not None:
                    matched = [spec for spec in specs if _matches(shape, spec)]
                    if len(matched) != 1:
                        raise ValueError(f"{object_id}/{semantic} shape {si}: source geometry mismatch")
                    source_part, source_role = matched[0]["name"], matched[0]["role"]
                    specs = [spec for spec in specs if spec is not matched[0]]
                if not shape.parts:
                    raise ValueError(f"{object_id}/{semantic} shape {si}: no actual render parts")
                part_roles = []
                for pi, part in enumerate(shape.parts):
                    material = part.material
                    roles = [role for role, spec in definition["roles"].items()
                             if _signature_matches(material, spec["native"])]
                    if len(roles) != 1 or (source_role is not None and roles[0] != source_role):
                        raise ValueError(f"{object_id}/{semantic} shape {si} part {pi}: native PBR role mismatch")
                    role = roles[0]
                    counts[role].add((semantic, si))
                    groups[role].append(dict(entity=entity, semantic_entity=semantic,
                                             shape_index=si, part_index=pi, material=material,
                                             native=_material(material)))
                    part_roles.append(role)
                    owners.append((object_id, role, definition["roles"][role]["editable"], material))
                rows.append(dict(entity=semantic, entity_name=entity.name, entity_id=entity.per_scene_id,
                                 shape_index=si, source_part=source_part, part_count=len(shape.parts),
                                 part_roles=part_roles, geometry=_geometry(shape)))
        if specs:
            raise ValueError("Flat panel is missing expected source geometry")
        if len(rows) != definition["expected_shape_count"]:
            raise ValueError(f"{object_id}: expected {definition['expected_shape_count']} visual shapes, got {len(rows)}")
        for role, spec in definition["roles"].items():
            if len(counts[role]) != spec["expected_shape_count"]:
                raise ValueError(f"{object_id}/{role}: expected {spec['expected_shape_count']} shapes, got {len(counts[role])}")
        objects[object_id] = ObjectBinding(base, object_id, definition, groups, rows)
    editable = [(oid, role, mat) for oid, role, can_edit, mat in owners if can_edit]
    for oid, role, material in editable:
        if any(material == other and (oid != other_id or role != other_role)
               for other_id, other_role, _, other in owners):
            raise ValueError(f"{oid}/{role}: editable material aliases a different target role/object")
    for entity in base.scene.sub_scenes[0].entities:
        if any(entity == target for target in all_entities):
            continue
        body = entity.find_component_by_type(sr.RenderBodyComponent)
        if body is not None:
            for shape in body.render_shapes:
                for part in shape.parts:
                    if any(part.material == material for _, _, material in editable):
                        raise ValueError(f"Editable furniture material aliases non-target entity {entity.name}")
    return FamilyBinding(base, objects)


def describe_furniture(binding):
    """JSON-ready source-to-actual entity/shape/part mappings and PBR values."""
    return {
        "task_id": TASKS[type(binding.env).__name__],
        "scope": "authoring_and_single_environment_preview_only",
        "objects": {oid: {
            "entities": [{"semantic": name, "name": entity.name, "id": entity.per_scene_id}
                         for name, entity in obj.definition["entities"]],
            "detail": obj.definition["detail"], "shapes": obj.rows,
            "roles": {role: {
                **obj.definition["roles"][role],
                "shape_count": len({(r["semantic_entity"], r["shape_index"]) for r in records}),
                "part_count": len(records), "parts": [{
                    "entity": r["semantic_entity"], "entity_name": r["entity"].name,
                    "shape_index": r["shape_index"], "part_index": r["part_index"],
                    "native": r["native"], "current": _material(r["material"]),
                } for r in records],
            } for role, records in obj.groups.items()},
        } for oid, obj in binding.objects.items()},
    }


def _check_live(obj):
    entities = obj.env.scene.sub_scenes[0].entities
    if any(not any(target == entity for entity in entities)
           for _, target in obj.definition["entities"]):
        raise RuntimeError("The task was rebuilt; inspect native furniture again")


def _validate_params(params, role):
    if set(params) != set(FIELDS):
        raise ValueError(f"{role}: expected exactly {FIELDS}")
    color = np.asarray(params["base_color"], dtype=float)
    roughness, metallic = float(params["roughness"]), float(params["metallic"])
    if (color.shape != (4,) or not np.isfinite(color).all() or np.any(color < 0)
            or np.any(color > 1) or color[3] != 1
            or not 0 <= roughness <= 1 or not 0 <= metallic <= 1):
        raise ValueError(f"{role}: invalid opaque PBR parameters")
    return dict(base_color=color.tolist(), roughness=roughness, metallic=metallic)


def _restore_object(obj):
    _check_live(obj)
    for role, records in obj.groups.items():
        if obj.definition["roles"][role]["editable"]:
            for record in records:
                for field in FIELDS:
                    setattr(record["material"], field, record["native"][field])


def apply_object(obj, catalog, scheme_id):
    """Validate a complete object scheme before writing only its editable PBR.

    Supports the prior flat-panel palette/factor schema and the other three
    catalogs' explicit role parameters. Original restores measured native data.
    """
    _check_live(obj)
    if (catalog["object_id"] != f"furniture_assembly.{obj.object_id}"
            or catalog["scope"] != "authoring_and_single_environment_preview_only"):
        raise ValueError("Object catalog identity/scope mismatch")
    scheme = catalog["schemes"][scheme_id]
    if scheme_id == "original":
        if scheme != {"mode": "restore_native"}:
            raise ValueError("Original must restore captured native materials")
        _restore_object(obj)
        return
    editable = {role for role, spec in obj.definition["roles"].items() if spec["editable"]}
    preserved = set(obj.groups) - editable
    declared_preserved = set(catalog["preserve_roles"])
    if not preserved <= declared_preserved or editable & declared_preserved:
        raise ValueError("Catalog does not preserve this representation's protected roles")
    if scheme["mode"] != "material_override":
        raise ValueError("Candidate must be a material_override")
    if "roles" in scheme:
        parameters = scheme["roles"]
    elif obj.object_id == "flat_panel":
        if set(catalog["color_factors"]) != editable or set(scheme["roughness"]) != editable:
            raise ValueError("Flat-panel palette must describe every editable role")
        color = _validate_params({"base_color": scheme["base_color"], "roughness": 0.5,
                                  "metallic": scheme["metallic"]}, "flat_panel palette")["base_color"]
        parameters = {role: {
            "base_color": [float(v) * float(catalog["color_factors"][role]) for v in color[:3]] + [color[3]],
            "roughness": scheme["roughness"][role], "metallic": scheme["metallic"],
        } for role in editable}
    else:
        raise ValueError("Object candidate is missing role parameters")
    if set(parameters) != editable:
        raise ValueError(f"Candidate must describe exactly the editable roles: {sorted(editable)}")
    checked = {role: _validate_params(params, role) for role, params in parameters.items()}
    for role, params in checked.items():
        for record in obj.groups[role]:
            for field, value in params.items():
                setattr(record["material"], field, value)


def restore_furniture(binding):
    for obj in binding.objects.values():
        _restore_object(obj)


def _rail_joints(base):
    """Read documented SAPIEN 3.0.3 joint properties, not Pinocchio/IK."""
    if not hasattr(base, "rail"):
        return []
    articulation, = base.rail._objs
    rows = []
    for joint in articulation.joints:
        row = dict(name=joint.name, type=joint.type, dof=joint.dof)
        if joint.parent_link is not None:
            row.update(pose_in_parent=_pose(joint.pose_in_parent), pose_in_child=_pose(joint.pose_in_child))
        if joint.dof:
            for field in ("limits", "friction", "max_velocity", "armature", "stiffness", "damping",
                          "force_limit", "drive_mode", "drive_target", "drive_velocity_target"):
                row[field] = _json(getattr(joint, field))
        rows.append(row)
    return rows


def snapshot_furniture(binding):
    """Initial-state invariants including all non-editable material properties.

    No step, reset, evaluate, pose or physics setters. This cannot establish
    dynamics, complete task success, parallel isolation or A4/A5 acceptance.
    """
    import sapien.physx as px
    import sapien.render as sr

    base = binding.env
    owned = {}
    for oid, obj in binding.objects.items():
        _check_live(obj)
        for role, records in obj.groups.items():
            for record in records:
                key = (record["entity"].per_scene_id, record["shape_index"], record["part_index"])
                owned[key] = (oid, role, obj.definition["roles"][role]["editable"])
    entities, protected, non_furniture = [], [], []
    for entity in sorted(base.scene.sub_scenes[0].entities, key=lambda e: e.per_scene_id):
        row = dict(name=entity.name, id=entity.per_scene_id, pose=_pose(entity.pose), visual=[], physics=[])
        for component in entity.components:
            if isinstance(component, sr.RenderBodyComponent):
                row["visual"].append(dict(visibility=float(component.visibility),
                                          shapes=[_geometry(shape) for shape in component.render_shapes]))
                for si, shape in enumerate(component.render_shapes):
                    for pi, part in enumerate(shape.parts):
                        material = _material(part.material)
                        owner = owned.get((entity.per_scene_id, si, pi))
                        record = dict(entity_id=entity.per_scene_id, shape_index=si, part_index=pi)
                        if owner is None:
                            non_furniture.append({**record, "material": material})
                        else:
                            oid, role, editable = owner
                            if editable:
                                material = {key: value for key, value in material.items() if key not in FIELDS}
                            protected.append({**record, "object_id": oid, "role": role, "material": material})
            elif isinstance(component, px.PhysxRigidBaseComponent):
                physics = dict(type=type(component).__name__, collisions=[])
                for field in ("mass", "inertia", "linear_damping", "angular_damping", "disable_gravity",
                              "max_linear_velocity", "max_angular_velocity", "max_depenetration_velocity",
                              "kinematic", "locked_motion_axes"):
                    if hasattr(component, field):
                        physics[field] = _json(getattr(component, field))
                if hasattr(component, "cmass_local_pose"):
                    physics["cmass_local_pose"] = _pose(component.cmass_local_pose)
                for shape in component.collision_shapes:
                    collision = _geometry(shape)
                    for field in ("density", "contact_offset", "rest_offset", "patch_radius",
                                  "min_patch_radius", "collision_groups"):
                        collision[field] = _json(getattr(shape, field))
                    collision["material"] = {
                        field: _json(getattr(shape.physical_material, field))
                        for field in ("static_friction", "dynamic_friction", "restitution")}
                    physics["collisions"].append(collision)
                row["physics"].append(physics)
        entities.append(row)
    return dict(state=_json(base.get_state_dict()), elapsed_steps=_json(base._elapsed_steps),
                geometry_and_physics=entities, rail_joints=_rail_joints(base),
                non_furniture_materials=non_furniture, protected_furniture_materials=protected)
