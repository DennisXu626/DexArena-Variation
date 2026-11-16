"""Strict material bindings for the one-environment LayFlatPanel preview.

This inspects an already reset real task. It never builds shapes, resets or
steps the task, writes poses/physics, or installs a task-level appearance API.
"""
from dataclasses import dataclass
import hashlib
import math

import numpy as np


ROLES = ("face", "cut", "edge", "routed", "label", "ink")
EDITABLE_ROLES = ROLES[:4]
SOURCE = "tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py:413-514"
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


@dataclass
class PanelBinding:
    env: object
    entity: object
    groups: dict
    shapes: list


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


def _panel_entity(env):
    base = env.unwrapped
    if type(base).__name__ != "FurnitureAssemblyLayFlatPanelEnv" or base.num_envs != 1:
        raise ValueError("This preview requires the real single-environment LayFlatPanel task")
    if not base.visual_detail or base.panel_color_jitter:
        raise ValueError("Use visual_detail=True and panel_color_jitter=False")
    entity, = base.panel._objs
    return base, entity


def inspect_panel(env):
    """Capture native bindings after reset; fail on unexpected geometry/materials.

    ``groups[role]`` contains one record per actual render part. ``shapes``
    contains one source-to-runtime record per visual shape (22 in this pilot).
    """
    import sapien.render as sr

    base, entity = _panel_entity(env)
    body = entity.find_component_by_type(sr.RenderBodyComponent)
    if body is None or len(body.render_shapes) != 22:
        raise ValueError("Expected 22 real panel visual shapes with visual_detail=True")
    groups, rows, remaining = {role: [] for role in ROLES}, [], _visual_specs()
    for shape_index, shape in enumerate(body.render_shapes):
        matches = [spec for spec in remaining if _matches(shape, spec)]
        if len(matches) != 1:
            raise ValueError(f"Panel shape {shape_index} has {len(matches)} source geometry matches")
        spec = matches[0]
        remaining = [other for other in remaining if other is not spec]
        role = spec["role"]
        if not shape.parts:
            raise ValueError(f"Panel {spec['name']} has no actual render parts")
        rows.append(dict(shape_index=shape_index, source_part=spec["name"], role=role,
                         shape_type=type(shape).__name__, local_pose=_pose(shape.local_pose),
                         part_count=len(shape.parts)))
        for part_index, part in enumerate(shape.parts):
            material = part.material
            color, roughness = _NATIVE[role]
            if not (np.allclose(material.base_color, color, rtol=0, atol=2e-6)
                    and abs(material.roughness - roughness) < 2e-6
                    and abs(material.metallic) < 2e-6
                    and abs(material.specular - 0.3) < 2e-6):
                raise ValueError(f"Panel {spec['name']} part {part_index} native material mismatch")
            groups[role].append(dict(shape_index=shape_index, part_index=part_index,
                                     material=material, native=_material(material)))
    if remaining:
        raise ValueError(f"Missing source visuals: {[spec['name'] for spec in remaining]}")
    for other in base.scene.sub_scenes[0].entities:
        if other == entity:
            continue
        render = other.find_component_by_type(sr.RenderBodyComponent)
        if render is not None:
            for shape in render.render_shapes:
                for part in shape.parts:
                    if any(part.material == row["material"]
                           for role in EDITABLE_ROLES for row in groups[role]):
                        raise ValueError(f"Panel material unexpectedly shared with {other.name}")
    return PanelBinding(base, entity, groups, rows)


def describe_serializable(binding):
    """Return the measured source/shape/part map and native/current parameters."""
    return dict(source=SOURCE, entity_name=binding.entity.name, shapes=binding.shapes,
                roles={role: {"shape_count": len({r["shape_index"] for r in rows}),
                              "part_count": len(rows), "parts": [
                                  {"shape_index": r["shape_index"], "part_index": r["part_index"],
                                   "native": r["native"], "current": _material(r["material"])}
                                  for r in rows]}
                       for role, rows in binding.groups.items()})


def _check_live(binding):
    _, entity = _panel_entity(binding.env)
    if entity != binding.entity:
        raise RuntimeError("The task was rebuilt; inspect its native panel again before applying")


def apply_roles(binding, role_params):
    """Apply all four editable roles; label/ink, textures and other fields stay native.

    Each role must provide ``base_color`` (opaque RGBA), ``roughness`` and
    ``metallic``. All parameters are validated before any material is changed.
    """
    _check_live(binding)
    if set(role_params) != set(EDITABLE_ROLES):
        raise ValueError(f"Provide exactly these material roles: {EDITABLE_ROLES}")
    checked = {}
    for role, params in role_params.items():
        if set(params) != {"base_color", "roughness", "metallic"}:
            raise ValueError(f"{role}: expected base_color, roughness, metallic")
        color = np.asarray(params["base_color"], dtype=float)
        roughness, metallic = float(params["roughness"]), float(params["metallic"])
        if (color.shape != (4,) or not np.isfinite(color).all()
                or np.any(color < 0) or np.any(color > 1) or color[3] != 1
                or not 0 <= roughness <= 1 or not 0 <= metallic <= 1):
            raise ValueError(f"{role}: invalid opaque PBR parameters")
        checked[role] = dict(base_color=color.tolist(), roughness=roughness, metallic=metallic)
    for role, params in checked.items():
        for row in binding.groups[role]:
            for field, value in params.items():
                setattr(row["material"], field, value)


def restore_native(binding):
    """Restore the exact captured editable values; do not substitute a palette."""
    _check_live(binding)
    for role in EDITABLE_ROLES:
        for row in binding.groups[role]:
            for field in ("base_color", "roughness", "metallic"):
                setattr(row["material"], field, row["native"][field])


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


def snapshot_scene(env):
    """Read invariants for before/after comparison without stepping/evaluating.

    Editable panel material values are intentionally excluded. Protected label/
    ink and every other entity's materials remain part of the comparison.
    Mesh/UV arrays are hashed from actual loaded geometry, not source paths.
    This is an initial-state preview check, not a dynamics or A4/A5 result.
    """
    import sapien.physx as px
    import sapien.render as sr

    base, panel = _panel_entity(env)
    entities, non_panel_materials, protected = [], [], []
    specs = _visual_specs()
    for entity in sorted(base.scene.sub_scenes[0].entities, key=lambda e: e.per_scene_id):
        row = dict(name=entity.name, id=entity.per_scene_id, pose=_pose(entity.pose),
                   visual=[], physics=[])
        for component in entity.components:
            if isinstance(component, sr.RenderBodyComponent):
                for si, shape in enumerate(component.render_shapes):
                    row["visual"].append(_geometry(shape))
                    materials = [_material(part.material) for part in shape.parts]
                    if entity != panel:
                        non_panel_materials.append(dict(entity_id=entity.per_scene_id,
                                                        shape_index=si, materials=materials))
                    else:
                        matches = [spec for spec in specs if _matches(shape, spec)]
                        if len(matches) != 1:
                            raise ValueError(f"Panel shape {si} no longer matches the source geometry")
                        role = matches[0]["role"]
                        if role in EDITABLE_ROLES:
                            materials = [{key: value for key, value in material.items()
                                          if key not in ("base_color", "roughness", "metallic")}
                                         for material in materials]
                        protected.append(dict(shape_index=si, role=role, materials=materials))
            elif isinstance(component, px.PhysxRigidBaseComponent):
                physics = dict(type=type(component).__name__, collisions=[])
                for field in ("mass", "inertia", "linear_damping", "angular_damping",
                              "disable_gravity", "max_linear_velocity", "max_angular_velocity",
                              "max_depenetration_velocity", "kinematic", "locked_motion_axes"):
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
                geometry_and_physics=entities, non_panel_materials=non_panel_materials,
                protected_panel_materials=protected)
