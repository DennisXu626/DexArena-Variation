"""Material-only, single-model authoring helper. No formal task/reset adapter."""
import copy
import hashlib
from pathlib import Path

FIELDS = ("base_color", "roughness", "metallic")
MATERIAL_FIELDS = FIELDS + (
    "specular", "emission", "transmission", "ior", "transmission_roughness",
    "base_color_texture", "roughness_texture", "metallic_texture", "normal_texture",
    "emission_texture", "transmission_texture",
)


def plain(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (tuple, list)):
        return [plain(x) for x in value]
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def material_state(material, texture_pixels=None):
    result = {}
    for field in MATERIAL_FIELDS:
        if not hasattr(material, field):
            continue
        value = getattr(material, field)
        if field.endswith("_texture"):
            metadata = None if value is None else {
                key: plain(getattr(value, key))
                for key in ("filename", *_RUNTIME.TEXTURE_DESCRIPTOR_FIELDS)
                if hasattr(value, key)
            }
            if value is not None and field == 'base_color_texture' and texture_pixels is not None:
                state = next((state for existing, state in texture_pixels if existing == value), None)
                if state is None:
                    data = value.download()
                    state = {'data_sha256': hashlib.sha256(data.tobytes()).hexdigest(),
                             'data_shape': list(data.shape), 'data_dtype': str(data.dtype)}
                    texture_pixels.append((value, state))
                metadata.update(state)
            value = metadata
        result[field] = plain(value)
    return result


def opaque_untextured(material):
    state = material_state(material)
    return (len(state["base_color"]) == 4 and state["base_color"][3] == 1
            and state.get("transmission", 0) == 0
            and all(v is None for k, v in state.items() if k.endswith("_texture")))


# Load this standalone module directly so CPU checks never import tasks/__init__.
import importlib.util
_RUNTIME_PATH = Path(__file__).resolve().parents[2] / "tasks/office_desk/devices_appearance.py"
_SPEC = importlib.util.spec_from_file_location("office_device_part_materials", _RUNTIME_PATH)
_RUNTIME = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNTIME)


class OfficeDevicesPreviewMaterials(_RUNTIME.OfficePartMaterials):
    """Use the same explicit per-part preparation as the formal short tasks."""

    def __init__(self, inventory, catalog, definition=None):
        if inventory["missing"] or inventory["errors"] or not inventory["editable_count"]:
            raise ValueError("Complete, unambiguous authorized assets are required")
        if definition is None:
            definition_path = Path(__file__).resolve().parents[2] / "assets/appearance/objects/office_desk" / inventory["object_id"] / "bindings.json"
            import json
            definition = json.loads(definition_path.read_text(encoding="utf-8"))
        super().__init__(definition, inventory["asset_dir"])
        self.catalog = catalog

    def apply(self, scheme_id):
        scheme = self.catalog["schemes"][scheme_id]
        for role, part, material, original in self.bindings:
            source_role = self.catalog.get('role_aliases', {}).get(role, role)
            parameters = original if scheme_id == "original" else {**scheme[source_role]}
            if role == _RUNTIME.STRIP_ROLE:
                assert material.base_color_texture == self.strip_texture.texture
                self.strip_texture.apply(None if scheme_id == 'original' else parameters['base_color'])
            for field in FIELDS:
                setattr(material, field, parameters[field])


def snapshot_model(articulation):
    """Read model transforms, mesh/UV hashes and all native material fields."""
    import numpy as np
    import sapien.render as sr

    def digest(value):
        data = np.ascontiguousarray(value)
        return {"shape": list(data.shape), "sha256": hashlib.sha256(data.tobytes()).hexdigest()}

    result = {"qpos": plain(articulation.get_qpos()), "qvel": plain(articulation.get_qvel()), "links": []}
    texture_pixels = []
    for link in articulation.links:
        body = link.entity.find_component_by_type(sr.RenderBodyComponent)
        row = {"name": link.name, "pose": {"p": plain(link.entity.pose.p), "q": plain(link.entity.pose.q)},
               "mass": float(link.mass), "inertia": plain(link.inertia), "shapes": [],
               "visual_geometry": _RUNTIME.render_geometry(body) if body else []}
        if body:
            for shape in body.render_shapes:
                row["shapes"].append({"name": shape.name, "scale": plain(shape.scale),
                    "pose": {"p": plain(shape.local_pose.p), "q": plain(shape.local_pose.q)},
                    "parts": [{"vertices": digest(part.vertices), "triangles": digest(part.triangles),
                               "uv": digest(part.get_vertex_uv()), "normals": digest(part.get_vertex_normal()),
                               "material": material_state(part.material, texture_pixels)} for part in shape.parts]})
        result["links"].append(row)
    return result


def canonical_model(snapshot):
    """Exact triangle attributes and native source-slot PBR across partitions."""
    from types import SimpleNamespace
    result = copy.deepcopy(snapshot)
    for link in result['links']:
        materials = {}
        strip_materials = {}
        for visual_index, shape in enumerate(link.pop('shapes')):
            for part_index, part in enumerate(shape['parts']):
                visual, source_part = _RUNTIME.source_slot(SimpleNamespace(name=shape['name']), visual_index, part_index)
                key = f'{visual}:{source_part}'
                if '::office_role:shell_strip' in shape['name']:
                    assert key not in strip_materials
                    strip_materials[key] = part['material']
                    continue
                if key in materials and materials[key] != part['material']:
                    raise RuntimeError('Partition original does not preserve its source-slot PBR')
                materials[key] = part['material']
        for key, private in strip_materials.items():
            source = copy.deepcopy(materials[key])
            texture = private['base_color_texture']
            assert texture['filename'] == '' and source['base_color_texture']['filename']
            source['base_color_texture']['filename'] = ''
            if source != private:
                raise RuntimeError('Private strip does not preserve native original sampler, pixels and PBR')
        link['materials'] = materials
    return result


def without_editable_fields(snapshot, inventory):
    result = copy.deepcopy(snapshot)
    for link in result["links"]:
        for index, shape in enumerate(link["shapes"]):
            if "::office_edit:" in shape["name"]:
                for part in shape["parts"]:
                    for field in FIELDS:
                        part["material"].pop(field, None)
                    if '::office_role:shell_strip' in shape['name']:
                        part['material'].pop('base_color_texture', None)
    return result
