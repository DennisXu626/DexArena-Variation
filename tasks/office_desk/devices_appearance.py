"""Office laptop/keyboard material parts, prepared before scene batching."""
import copy
import hashlib
import json
from pathlib import Path
import re

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OBJECTS = ROOT / 'assets/appearance/objects/office_desk'
CATALOG = ROOT / 'tasks/assets/variation/office_desk/devices/v1/catalog.json'
FIELDS = ('base_color', 'roughness', 'metallic')
MATERIAL_FIELDS = FIELDS + (
    'specular', 'emission', 'transmission', 'ior', 'transmission_roughness',
    'base_color_texture', 'roughness_texture', 'metallic_texture',
    'normal_texture', 'emission_texture', 'transmission_texture',
)
STRIP_ROLE = 'shell_strip'
TEXTURE_DESCRIPTOR_FIELDS = ('width', 'height', 'channels', 'format', 'mipmap_levels',
                             'filter_mode', 'address_mode', 'is_srgb')


def validate_appearance_config(config, num_envs):
    if not isinstance(config, dict) or not isinstance(config.get('per_env', {}), dict):
        raise ValueError('Office appearance and per_env must be dictionaries')
    per_env = config.get('per_env', {})
    if not per_env:
        return
    valid_indices = {str(index) for index in range(num_envs)}
    for index, request in per_env.items():
        if not isinstance(index, str) or index not in valid_indices or not isinstance(request, dict):
            raise ValueError('Office per_env requires canonical environment keys and dictionary requests')
        if 'enabled' in request or 'seed' in request:
            raise ValueError('Office enabled and seed are common construction options')


def appearance_enabled(config, num_envs):
    if config is None:
        return False
    validate_appearance_config(config, num_envs)
    return config.get('enabled', False)


def validate_reset_indices(env_idx, num_envs):
    indices = env_idx.tolist() if hasattr(env_idx, 'tolist') else env_idx
    if (not isinstance(indices, (list, tuple)) or not indices
            or any(type(index) is not int or not 0 <= index < num_envs for index in indices)
            or any(left >= right for left, right in zip(indices, indices[1:]))):
        raise ValueError('Office env_idx requires strictly increasing valid environment indices')
    return indices


def validate_reset_override(override, num_envs):
    validate_appearance_config(override, num_envs)
    if 'enabled' in override or 'seed' in override:
        raise ValueError('Office enabled and seed are construction-only')


def texture_descriptor(texture):
    return {name: getattr(texture, name) for name in TEXTURE_DESCRIPTOR_FIELDS}


class OfficeStripTexture:
    """Keep one bound texture per environment and upload only its pixel contents."""

    def __init__(self, source):
        import sapien.render as sr

        self.source = source
        self.descriptor = texture_descriptor(source)
        original = source.download()
        if (source.format != 'R8G8B8A8Unorm' or not source.is_srgb or source.mipmap_levels != 1
                or original.dtype != np.uint8 or original.shape != (source.height, source.width, 4)
                or not np.all(original[..., 3] == 255)):
            raise RuntimeError('Office strip requires the reviewed opaque sRGB RGBA8 atlas')
        self.original_pixels = np.array(original, copy=True, order='C')
        self.original_pixels.flags.writeable = False
        self.texture = sr.RenderTexture2D(self.original_pixels, source.format, source.mipmap_levels,
                                          source.filter_mode, source.address_mode, source.is_srgb)
        if self.texture == source or texture_descriptor(self.texture) != self.descriptor:
            raise RuntimeError('Office private strip texture is not an exact-format independent clone')
        self.color = None

    def pixels_for(self, color):
        if color is None:
            return self.original_pixels
        linear = np.asarray(color[:3], dtype=np.float64)
        srgb = np.where(linear <= .0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - .055)
        rgba = [*np.rint(srgb * 255).astype(np.uint8), 255]
        frame = np.empty_like(self.original_pixels)
        frame[:] = rgba
        return frame

    def apply(self, color):
        color = None if color is None else tuple(color)
        if color == self.color:
            return
        pixels = self.pixels_for(color)
        if (pixels.dtype != np.uint8 or pixels.shape != self.original_pixels.shape
                or not pixels.flags.c_contiguous):
            raise RuntimeError('Office strip upload requires the exact original RGBA8 layout')
        self.texture.upload(pixels)
        self.color = color


def validate_parameters(params):
    if set(params) != set(FIELDS):
        raise ValueError('Expected only base_color, roughness and metallic')
    color = np.asarray(params['base_color'], dtype=float)
    values = np.asarray([params['roughness'], params['metallic']], dtype=float)
    if (color.shape != (4,) or not np.isfinite(color).all()
            or np.any(color < 0) or np.any(color > 1) or color[3] != 1
            or not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 1)):
        raise ValueError('Invalid opaque material parameters')
    return copy.deepcopy(params)


def opaque_untextured(material):
    color = np.asarray(material.base_color)
    return (color.shape == (4,) and color[3] == 1
            and getattr(material, 'transmission', 0) == 0
            and all(getattr(material, key, None) is None
                    for key in MATERIAL_FIELDS if key.endswith('_texture')))


def triangle_positions_hash(vertices, triangles):
    """Identify a source material group despite importer vertex/index ordering."""
    values = np.asarray(vertices, dtype=np.float32)[np.asarray(triangles)]
    rows = [b''.join(sorted(np.ascontiguousarray(point).tobytes() for point in triangle))
            for triangle in values]
    return hashlib.sha256(b''.join(sorted(rows))).hexdigest()


def triangle_position_ids(vertices, triangles):
    return [triangle_positions_hash(vertices, [triangle]) for triangle in triangles]


def triangle_position_uv_ids(vertices, uv, triangles):
    values = np.concatenate([np.asarray(vertices, dtype=np.float32), np.asarray(uv, dtype=np.float32)], axis=1)
    return [hashlib.sha256(b''.join(sorted(np.ascontiguousarray(values[index]).tobytes()
                                         for index in triangle))).hexdigest()
            for triangle in triangles]


def triangle_attribute_rows(part):
    """Exact rendered triangle attributes; invariant to material partitioning."""
    arrays = [np.asarray(part.vertices, dtype=np.float32)]
    for values in (part.get_vertex_normal(), part.get_vertex_uv()):
        values = np.asarray(values, dtype=np.float32)
        if values.size:
            if len(values) != len(arrays[0]):
                raise RuntimeError('Office vertex attribute count differs')
            arrays.append(values)
    vertices = np.concatenate(arrays, axis=1)
    triangles = np.ascontiguousarray(vertices[np.asarray(part.triangles)], dtype=np.float32)
    # Array reconstruction preserves triangle winding and corner order exactly.
    return triangles.reshape(len(triangles), -1)


def render_geometry(body):
    groups = {}
    for shape in body.render_shapes:
        transform = {'type': type(shape).__name__,
                     'p': np.asarray(shape.local_pose.p).tolist(),
                     'q': np.asarray(shape.local_pose.q).tolist(), 'front_face': shape.front_face}
        for field in ('scale', 'half_size', 'radius', 'half_length'):
            if hasattr(shape, field):
                value = getattr(shape, field)
                transform[field] = np.asarray(value).tolist()
        key = json.dumps(transform, sort_keys=True)
        for part in shape.parts:
            rows = triangle_attribute_rows(part)
            row_bytes = [np.ascontiguousarray(row).tobytes() for row in rows]
            groups.setdefault(key, []).extend(row_bytes)
    return [{'transform': json.loads(key), 'triangles': len(rows),
             'attributes_sha256': hashlib.sha256(b''.join(sorted(rows))).hexdigest()}
            for key, rows in sorted(groups.items())]


def source_slot(shape, visual_index, part_index):
    visual = re.search(r'::office_source:(\d+)', shape.name)
    part = re.search(r'::office_(?:edit|keep):(\d+)', shape.name)
    return (int(visual[1]) if visual else visual_index,
            int(part[1]) if part else part_index)


class OfficePartMaterials:
    """Keep source arrays and protected slots; give selected parts private PBR.

    SAPIEN imported part.material has no setter. A selected multi-part visual is
    repackaged as one shape per existing native part, with identical vertices,
    triangles, normals, UV, scale, pose and winding. Only designated parts
    receive private materials. No record.material override is used.
    """

    def __init__(self, definition, asset_dir):
        self.definition = definition
        self.asset_dir = Path(asset_dir).resolve()
        self.bindings = []
        self.audit = []
        self.strip_texture = None
        for name, expected in definition['runtime_source_sha256'].items():
            path = (self.asset_dir / name).resolve()
            if not path.is_relative_to(self.asset_dir):
                raise ValueError('Office source path escapes model directory')
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f'Office source identity changed: {name}')

    def install(self, builder):
        import sapien.render as sr

        selected = {(row['link'], row['index']): row
                    for row in self.definition['part_bindings']}
        found = set()
        for link in builder.link_builders:
            records = list(link.visual_records)
            rows = []
            for index, record in enumerate(records):
                row = selected.get((link.name, index))
                if row is not None:
                    if (record.type != 'file' or record.name != row['name']
                            or Path(record.filename).resolve() != self.asset_dir / row['mesh']
                            or record.material is not None):
                        raise RuntimeError(f'Office visual binding mismatch: {link.name}/{index}')
                    found.add((link.name, index))
                rows.append(row)
            if not any(rows):
                continue
            original_build = link.build_render_component

            def private_build(original_build=original_build, rows=rows, records=records, link_name=link.name):
                source = original_build()
                if len(source.render_shapes) != len(records):
                    raise RuntimeError('Office visual record/shape count mismatch')
                body = sr.RenderBodyComponent()
                body.name, body.visibility, body.shading_mode = source.name, source.visibility, source.shading_mode
                if source.is_render_id_disabled:
                    body.disable_render_id()
                for visual_index, (shape, row) in enumerate(zip(source.render_shapes, rows)):
                    if row is None:
                        clone = shape.clone()
                        clone.name = shape.name + '::office_source:' + str(visual_index)
                        body.attach(clone)
                        continue
                    parts = list(shape.parts)
                    if len(parts) != row['native_part_count']:
                        raise RuntimeError(f'Office native part count mismatch: {row["mesh"]}')
                    matched = []
                    for part_index, part in enumerate(parts):
                        material = part.material
                        matches = [slot for slot in row['editable_slots']
                                   if len(part.triangles) == slot['triangles']
                                   and np.allclose(material.base_color,
                                       slot['diffuse'] + [1.0], rtol=0, atol=2e-6)]
                        if len(matches) > 1:
                            raise RuntimeError('Ambiguous Office part identity')
                        groups = [(False, np.asarray(part.triangles))]
                        if matches:
                            slot = matches[0]
                            if triangle_positions_hash(part.vertices, part.triangles) != slot['position_triangles_sha256']:
                                raise RuntimeError('Office part differs from its source material geometry')
                            if 'partition' in slot:
                                mask = self._partition_mask(part, slot['partition'])
                                texture = material.base_color_texture
                                if (texture is None or np.asarray(material.base_color)[3] != 1
                                        or material.transmission != 0
                                        or texture.mipmap_levels != slot['partition']['mipmap_levels']
                                        or texture.address_mode != slot['partition']['expected_sampler']['address_mode']
                                        or texture.filter_mode != slot['partition']['expected_sampler']['filter_mode']
                                        or texture.is_srgb != slot['partition']['expected_sampler']['is_srgb']
                                        or Path(texture.filename).resolve() != self.asset_dir / slot['partition']['texture']
                                        or any(getattr(material, key, None) is not None
                                               for key in MATERIAL_FIELDS if key.endswith('_texture') and key != 'base_color_texture')):
                                    raise RuntimeError('Unexpected Office partition texture or transparency')
                                groups = [(True, np.asarray(part.triangles)[mask]),
                                          (False, np.asarray(part.triangles)[~mask])]
                            else:
                                if not opaque_untextured(material):
                                    raise RuntimeError('Office editable part is textured or transparent')
                                groups = [(True, np.asarray(part.triangles))]
                            matched.append(slot['material'])
                        joined = np.concatenate([triangles for _, triangles in groups])
                        if sorted(map(tuple, joined.tolist())) != sorted(map(tuple, np.asarray(part.triangles).tolist())):
                            raise RuntimeError('Office partition changed the joint triangle/index set')
                        for editable, triangles in groups:
                            target = material
                            role = matches[0].get('role', self.definition['editable_role']) if editable else None
                            if editable and (role == STRIP_ROLE) != ('partition' in matches[0]):
                                raise RuntimeError('Office texture upload is limited to the approved strip partition')
                            if editable:
                                target = sr.RenderMaterial()
                                for key in MATERIAL_FIELDS:
                                    if hasattr(material, key):
                                        setattr(target, key, getattr(material, key))
                                if target.base_color_texture != material.base_color_texture:
                                    raise RuntimeError('Office partition replaced the source texture handle')
                                if role == STRIP_ROLE:
                                    if self.strip_texture is not None:
                                        raise RuntimeError('Expected one private strip texture per environment')
                                    self.strip_texture = OfficeStripTexture(material.base_color_texture)
                                    target.base_color_texture = self.strip_texture.texture
                            rebuilt = sr.RenderShapeTriangleMesh(
                                part.vertices, triangles, part.get_vertex_normal(), part.get_vertex_uv(), target)
                            rebuilt.scale, rebuilt.local_pose, rebuilt.front_face = shape.scale, shape.local_pose, shape.front_face
                            rebuilt.name = (shape.name + '::office_source:' + str(row['index'])
                                            + ('::office_edit:' if editable else '::office_keep:') + str(part_index)
                                            + ('::office_role:' + role if role else '')
                                            + ('::office_group:' + ('safe' if editable else 'protected')
                                               if matches and 'partition' in matches[0] else ''))
                            body.attach(rebuilt)
                            for field, value in (
                                ('vertices', part.vertices), ('triangles', triangles),
                                ('get_vertex_normal', part.get_vertex_normal()), ('get_vertex_uv', part.get_vertex_uv()),
                            ):
                                actual = getattr(rebuilt.parts[0], field)
                                actual = actual() if callable(actual) else actual
                                if np.asarray(actual).dtype != np.asarray(value).dtype or not np.array_equal(actual, value):
                                    raise RuntimeError(f'Office rebuilt geometry changed: {field}')
                            if editable:
                                native = {key: copy.deepcopy(getattr(target, key)) for key in FIELDS}
                                self.bindings.append((role, rebuilt.parts[0], target, native))
                            self.audit.append({'link': link_name, 'visual': row['index'],
                                'mesh': row['mesh'], 'native_part': part_index,
                                'triangles': len(triangles), 'editable': editable,
                                'material': matches[0]['material'] if matches else None,
                                'texture': ({'address_mode': material.base_color_texture.address_mode,
                                             'filter_mode': material.base_color_texture.filter_mode,
                                             'mipmap_levels': material.base_color_texture.mipmap_levels,
                                    'same_handle': target.base_color_texture == material.base_color_texture,
                                    'private_strip_clone': role == STRIP_ROLE}
                                            if material.base_color_texture is not None else None)})
                    if sorted(matched) != sorted(slot['material'] for slot in row['editable_slots']):
                        raise RuntimeError(f'Office safe slots not uniquely bound: {row["mesh"]}')
                return body

            link.build_render_component = private_build
        if found != set(selected):
            raise RuntimeError('Incomplete Office visual binding')

    def _partition_mask(self, part, partition):
        """Recheck approved existing triangles against all key UVs in native data."""
        from PIL import Image
        from tools.variation import office_devices_uv_proof as U

        proof_path = (ROOT / partition['proof']).resolve()
        if (not proof_path.is_relative_to(ROOT)
                or hashlib.sha256(proof_path.read_bytes()).hexdigest() != partition['proof_sha256']):
            raise RuntimeError('Office UV protection proof identity changed')
        proof = json.loads(proof_path.read_text(encoding='utf-8'))
        width, height = proof['size']
        mask = np.zeros((height, width), dtype=np.uint8)
        for y, runs in enumerate(proof['key_mask_rows']):
            for start, end in runs:
                mask[y, start:end] = 255
        if hashlib.sha256(mask.tobytes()).hexdigest() != partition['key_uv_mask_sha256']:
            raise RuntimeError('Office key UV mask changed')
        margin = partition['margin_texels']
        if type(margin) is not int or margin < 0:
            raise ValueError('Office UV margin must be a nonnegative integer')
        if partition['coverage_method'] != 'exact_integer_sat_closed_bilinear_support':
            raise RuntimeError('Unknown Office UV coverage proof')
        if (partition['source_uv_to_native'] != 'assimp_flip_v_float32'
                or partition['native_uv_to_image'] != 'direct_uv_top_left'):
            raise RuntimeError('Unknown Office native UV mapping')
        ids = triangle_position_uv_ids(part.vertices, part.get_vertex_uv(), part.triangles)
        safe_ids = set(partition['safe_native_triangle_position_uv_sha256'])
        if len(ids) != len(set(ids)) or len(safe_ids) != partition['safe_triangles']:
            raise RuntimeError('Office partition triangle identity is ambiguous')
        selected = np.asarray([value in safe_ids for value in ids])
        if int(selected.sum()) != partition['safe_triangles']:
            raise RuntimeError('Office safe triangles are absent from native data')
        uv = np.asarray(part.get_vertex_uv())
        scale = U.integer_scale(uv[np.asarray(part.triangles)].reshape(-1,2).tolist(),width,height)
        rectangles,protected_sha = U.protected_rectangles(Image.fromarray(mask),margin,scale)
        if protected_sha != partition['protected_mask_sha256']:
            raise RuntimeError('Office protected UV margin changed')
        for triangle in np.asarray(part.triangles)[selected]:
            coords = uv[triangle]
            if not np.isfinite(coords).all() or np.any(coords < 0) or np.any(coords > 1):
                raise RuntimeError('Office safe triangle has unknown UV sampling')
            if U.periodic_witness(U.scaled_triangle(coords.tolist(),scale),rectangles,scale) is not None:
                raise RuntimeError('Office safe triangle samples protected key UVs')
        texture_path = self.asset_dir / partition['texture']
        if hashlib.sha256(texture_path.read_bytes()).hexdigest() != partition['texture_sha256']:
            raise RuntimeError('Office partition source texture changed')
        return selected


class OfficeDevicesAppearance:
    def __init__(self, config, num_envs, object_id, asset_root):
        validate_appearance_config(config, num_envs)
        self.config = copy.deepcopy(config)
        self.object_id = object_id
        self.catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
        entry = self.catalog['objects'][object_id]
        self.object_catalog = json.loads((ROOT / entry['catalog']).read_text(encoding='utf-8'))
        self.definition = json.loads((OBJECTS / object_id / 'bindings.json').read_text(encoding='utf-8'))
        self.asset_dir = Path(asset_root) / self.definition['model_id']
        self.bindings = [None] * num_envs
        self.prepared = [None] * num_envs
        self.schemes, self.episodes, self.records = ['original'] * num_envs, [0] * num_envs, []
        seed = int(config.get('seed', 0))
        self.rng = [np.random.default_rng(np.random.SeedSequence([seed, i])) for i in range(num_envs)]
        for name in self.catalog['schemes']:
            self.scheme_parameters(name)

    def scheme_parameters(self, scheme_id):
        mapped = self.catalog['objects'][self.object_id]['scheme_map'][scheme_id]
        scheme = self.object_catalog['schemes'][mapped]
        if scheme_id == 'original':
            if scheme != {'restore': 'captured_native'}:
                raise ValueError('Office original must restore captured native PBR')
            return {}
        if set(scheme) != {self.definition['editable_role']}:
            raise ValueError('Office candidate edits an unknown role')
        result = {role: validate_parameters(params) for role, params in scheme.items()}
        for role, source in self.object_catalog.get('role_aliases', {}).items():
            if role != STRIP_ROLE or source != 'shell' or self.object_id != 'keyboard':
                raise ValueError('Unknown Office role alias')
            result[role] = result[source]
        return result

    def isolate_builder_materials(self, builder, env_id):
        materials = OfficePartMaterials(self.definition, self.asset_dir)
        materials.install(builder)
        self.prepared[env_id] = materials

    def bind(self, handle, env_id):
        import sapien.render as sr

        prepared = self.prepared[env_id]
        bindings = prepared.bindings
        if len(bindings) != sum(len(row['editable_slots']) for row in self.definition['part_bindings']):
            raise RuntimeError('Incomplete Office private material construction')
        actual = [part for link in handle.get_links() for raw in link._objs
                  for body in [raw.entity.find_component_by_type(sr.RenderBodyComponent)] if body
                  for shape in body.render_shapes for part in shape.parts]
        if any(sum(part == candidate for candidate in actual) != 1 for _, part, _, _ in bindings):
            raise RuntimeError('Office material was not attached to its environment')
        for index, previous in enumerate(self.bindings):
            if previous is not None and index != env_id and any(
                    material == other for _, _, material, _ in bindings for _, _, other, _ in previous):
                raise RuntimeError('Office mutable material shared across environments')
            if (previous is not None and index != env_id and prepared.strip_texture is not None
                    and prepared.strip_texture.texture == self.prepared[index].strip_texture.texture):
                raise RuntimeError('Office mutable strip texture shared across environments')
        self.bindings[env_id] = bindings

    def finish_reset(self, env_idx, options):
        indices = validate_reset_indices(env_idx, len(self.bindings))
        override = options.get('office_devices_appearance', {})
        validate_reset_override(override, len(self.bindings))
        requests = []
        for i in indices:
            request = {**self.config, **self.config.get('per_env', {}).get(str(i), {}),
                       **override, **override.get('per_env', {}).get(str(i), {})}
            mode = request.get('mode', 'explicit')
            if mode == 'explicit':
                choices = [request.get('scheme_id', 'original')]
            elif mode == 'random_choice':
                choices = request.get('scheme_ids', [])
                if not isinstance(choices, list) or not choices:
                    raise ValueError('Office scheme_ids must be a nonempty list')
            else:
                raise ValueError(f'Unsupported Office selection mode: {mode}')
            if any(name not in self.catalog['schemes'] for name in choices):
                raise ValueError(f'Unknown Office appearance scheme: {choices}')
            if self.bindings[i] is None:
                raise RuntimeError(f'Office environment is not bound: {i}')
            requests.append((i, mode, choices, {name: self.scheme_parameters(name) for name in choices}))
        selections = [(i, str(self.rng[i].choice(choices)) if mode == 'random_choice' else choices[0], params)
                      for i, mode, choices, params in requests]
        for i, name, parameters in selections:
            for role, part, material, captured in self.bindings[i]:
                params = parameters[name].get(role, captured)
                if role == STRIP_ROLE:
                    strip = self.prepared[i].strip_texture
                    if material.base_color_texture != strip.texture:
                        raise RuntimeError('Office private strip texture was rebound')
                    strip.apply(None if name == 'original' else params['base_color'])
                for key in FIELDS:
                    setattr(material, key, params[key])
            self.schemes[i] = name
            self.episodes[i] += 1
            self.records.append({'env_idx': i, 'episode_index': self.episodes[i],
                                 'scheme_id': name, 'catalog_version': self.catalog['version']})
