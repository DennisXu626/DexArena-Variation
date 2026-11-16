"""Measured bindings for three real single-environment furniture previews.

Reuses the panel preview's read-only material/geometry serialization. Only
captured material base_color/roughness/metallic may be written; no task loader,
state, geometry, physics, randomization or reset interface is modified here.
"""
from dataclasses import dataclass

import numpy as np

from tools.variation.panel_preview_materials import (
    _NATIVE, _geometry, _json, _material, _matches, _pose, _visual_specs,
)
from tools.variation import (
    furniture_rack_definition, furniture_rail_definition, furniture_screw_definition,
)


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
    raw, = handle._objs
    return getattr(raw, "entity", raw)


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
    definitions = {"flat_panel": _flat_definition(base)}
    modules = ((furniture_rack_definition,) if task_id == TASKS["FurnitureAssemblyLayFlatPanelEnv"]
               else (furniture_rail_definition, furniture_screw_definition))
    definitions.update({module.OBJECT_ID: module.get_definition(env) for module in modules})
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
