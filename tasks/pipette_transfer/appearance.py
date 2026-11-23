"""Pipette material selection, captured originals and environment-local records."""
import copy
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'tasks/assets/variation/pipette_transfer/v1/catalog.json'
FIELDS = ('base_color', 'roughness', 'metallic')
MATERIAL_FIELDS = FIELDS + (
    'specular', 'emission', 'transmission', 'ior', 'transmission_roughness',
    'base_color_texture', 'roughness_texture', 'metallic_texture',
    'normal_texture', 'emission_texture', 'transmission_texture',
)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def capture_material(material):
    return {key: (getattr(material, key) if key.endswith('_texture')
                  else copy.deepcopy(getattr(material, key)))
            for key in MATERIAL_FIELDS if hasattr(material, key)}


def validate_per_env(config, num_envs):
    if not isinstance(config, dict):
        raise ValueError('Pipette appearance configuration must be a dictionary')
    if type(num_envs) is not int or num_envs <= 0:
        raise ValueError('num_envs must be a positive integer')
    entries = config.get('per_env', {})
    if not isinstance(entries, dict):
        raise ValueError('Pipette per_env must be a dictionary')
    valid = {str(i) for i in range(num_envs)}
    if any(type(key) is not str or key not in valid or not isinstance(value, dict)
           for key, value in entries.items()):
        raise ValueError('Pipette per_env requires canonical environment string keys and dictionary values')


def validate_reset_request(seed, options, num_envs):
    if options is None:
        return
    if not isinstance(options, dict):
        raise ValueError('Pipette reset options must be a dictionary')
    if 'pipette_appearance' in options:
        validate_per_env(options['pipette_appearance'], num_envs)
        if 'reset_to_env_states' in options:
            raise ValueError('Pipette state restoration cannot include an explicit appearance override')
    if 'env_idx' not in options:
        return
    indices = options['env_idx']
    if hasattr(indices, 'tolist'):
        indices = indices.tolist()
    if (not isinstance(indices, (list, tuple)) or not indices
            or any(isinstance(i, (bool, np.bool_)) or not isinstance(i, (int, np.integer))
                   or not 0 <= int(i) < num_envs for i in indices)):
        raise ValueError('Pipette env_idx must contain valid environment integers')
    if any(int(left) >= int(right) for left, right in zip(indices, indices[1:])):
        raise ValueError('Pipette env_idx must be strictly increasing')
    if seed is not None and len(indices) != num_envs:
        raise ValueError('Partial Pipette reset must omit seed; reseed only with a full reset')
    return indices


class PipetteAppearance:
    def __init__(self, config, num_envs, *, rendering_enabled=False):
        validate_per_env(config, num_envs)
        self.config = copy.deepcopy(config)
        self.rendering_enabled = bool(rendering_enabled)
        self.catalog = read(CATALOG)
        self.parameters = read(ROOT / self.catalog['parameters'])
        self.definitions = {name: read(ROOT / path)
                            for name, path in self.catalog['bindings'].items()}
        plate_label = self.definitions['pipette_stand']['roles']['base_plate']['candidate_color_texture']
        self._plate_label_path = (ROOT / plate_label['path']).resolve()
        self._plate_label_levels = plate_label['mipmap_levels']
        self._plate_label = None
        if (self.parameters['new_textures'] != [plate_label['path']]
                or not self._plate_label_path.is_relative_to((ROOT / 'assets/appearance').resolve())
                or not self._plate_label_path.is_file()
                or type(self._plate_label_levels) is not int or self._plate_label_levels < 1):
            raise ValueError('Invalid Pipette stand base-plate label asset')
        seed = int(config.get('seed', 0))
        self.rng = [np.random.default_rng(np.random.SeedSequence([seed, i]))
                    for i in range(num_envs)]
        self.bindings = [None] * num_envs
        self.schemes = ['original'] * num_envs
        self.episodes = [0] * num_envs
        self.records = []
        for name in self.catalog['schemes']:
            for object_id in self.parameters['objects']:
                self.scheme_parameters(object_id, name)

    def scheme_parameters(self, object_id, scheme_id):
        if scheme_id not in self.catalog['schemes']:
            raise ValueError(f'Unknown Pipette scheme: {scheme_id}')
        values = self.parameters['objects'][object_id]['schemes'][scheme_id]
        if scheme_id == 'original' and values != {}:
            raise ValueError('Original must restore captured native materials')
        result = copy.deepcopy(values)
        for role, params in result.items():
            definition = self.definitions[object_id]['roles'][role]
            if not definition['editable']:
                raise ValueError(f'Protected Pipette role: {object_id}/{role}')
            allowed = {'base_color_rgb', 'base_color_alpha'} if object_id in (
                'sample_cup', 'test_tube') else {'base_color_rgb', 'roughness', 'metallic'}
            if not set(params) <= allowed:
                raise ValueError(f'Unsupported Pipette material fields: {object_id}/{role}')
            for field, value in params.items():
                array = np.asarray(value, dtype=float)
                if not np.isfinite(array).all() or np.any(array < 0) or np.any(array > 1):
                    raise ValueError('Pipette material values must be finite in [0,1]')
                if field == 'base_color_rgb' and array.shape != (3,):
                    raise ValueError('Pipette RGB must have three components')
                if field != 'base_color_rgb' and array.shape != ():
                    raise ValueError('Pipette material scalar expected')
        return result

    @staticmethod
    def isolate_builder_materials(builder):
        import sapien.render as sr
        for link_builder in getattr(builder, 'link_builders', [builder]):
            original_build = link_builder.build_render_component
            records = list(link_builder.visual_records)
            def build_private(original_build=original_build, records=records):
                native_body = original_build()
                if not records:
                    return native_body
                if len(native_body.render_shapes) != len(records):
                    raise RuntimeError('Pipette visual record/shape count mismatch')
                # This cache belongs to one render-component construction, never a
                # persistent builder or environment. Preserve native wall aliases.
                materials = []
                for record, shape in zip(records, native_body.render_shapes):
                    if len(shape.parts) != 1:
                        raise RuntimeError('Expected one Pipette material per visual')
                    source = shape.parts[0].material
                    matches = [private for native, private in materials if native == source]
                    if matches:
                        private, = matches
                    else:
                        private = sr.RenderMaterial()
                        for key, value in capture_material(source).items():
                            setattr(private, key, value)
                        materials.append((source, private))
                    record.material = private
                return original_build()
            link_builder.build_render_component = build_private

    @staticmethod
    def resolved_parameters(native, params):
        result = copy.copy(native)
        color = list(native['base_color'])
        if 'base_color_rgb' in params:
            color[:3] = params['base_color_rgb']
        if 'base_color_alpha' in params:
            color[3] = params['base_color_alpha']
        result['base_color'] = color
        for field in ('roughness', 'metallic'):
            if field in params:
                result[field] = params[field]
        return result

    def bind(self, base, env_id):
        import sapien.render as sr

        rows = []

        def append(object_id, role, shape):
            if len(shape.parts) != 1:
                raise RuntimeError(f'Expected one Pipette material per visual: {object_id}/{role}')
            part, = shape.parts
            rows.append((object_id, role, part, part.material, capture_material(part.material)))

        for object_id in ('sample_cup', 'test_tube', 'tube_rack', 'pipette_stand'):
            handle = getattr(base, object_id)
            if handle is None:
                continue
            if len(handle._objs) != len(self.bindings):
                raise RuntimeError(f'Pipette environment count differs: {object_id}')
            body = handle._objs[env_id].find_component_by_type(sr.RenderBodyComponent)
            definition = self.definitions[object_id]
            if body is None or len(body.render_shapes) != definition['expected_visual_count']:
                raise RuntimeError(f'Pipette visual count differs: {object_id}')
            indices = []
            for role, entry in definition['roles'].items():
                owner = entry.get('parameters_from', object_id)
                for index in entry['visual_indices']:
                    append(owner, role, body.render_shapes[index])
                    indices.append(index)
            if sorted(indices) != list(range(len(body.render_shapes))):
                raise RuntimeError(f'Incomplete Pipette visual roles: {object_id}')
        if base.pipette is not None:
            raw = base.pipette._objs[env_id]
            links = {link.name.rsplit('_', 1)[-1]: link for link in raw.get_links()}
            definition = self.definitions['pipette']
            if set(links) != set(definition['link_visual_counts']):
                raise RuntimeError('Pipette native link names differ')
            bodies = {name: link.entity.find_component_by_type(sr.RenderBodyComponent)
                      for name, link in links.items()}
            for name, count in definition['link_visual_counts'].items():
                if bodies[name] is None or len(bodies[name].render_shapes) != count:
                    raise RuntimeError(f'Pipette native link visual count differs: {name}')
            for role, entry in definition['roles'].items():
                append('pipette', role, bodies[entry['link']].render_shapes[entry['visual_index']])
        for i, previous in enumerate(self.bindings):
            if previous is not None and i != env_id and any(
                material == other for _, _, _, material, _ in rows
                for _, _, _, other, _ in previous
            ):
                raise RuntimeError('Pipette mutable material shared across environments')
        for object_id, role, _, material, _ in rows:
            if any(material == other and (object_id, role) != (oid, other_role)
                   for oid, other_role, _, other, _ in rows):
                raise RuntimeError('Pipette material shared across distinct original roles')
        self.bindings[env_id] = rows

    def resolve_requests(self, indices, override):
        """Validate effective choices without touching bindings, RNG or records."""
        validate_per_env(self.config, len(self.bindings))
        validate_per_env(override, len(self.bindings))
        if {'enabled', 'seed'} & set(override):
            raise ValueError('Pipette enabled/seed may change only at construction')
        if any({'enabled', 'seed'} & set(value) for value in override.get('per_env', {}).values()):
            raise ValueError('Pipette enabled/seed may change only at construction')
        requests = []
        for i in indices:
            request = {**self.config, **self.config.get('per_env', {}).get(str(i), {}),
                       **override, **override.get('per_env', {}).get(str(i), {})}
            mode = request.get('mode', 'explicit')
            if mode == 'explicit':
                choices = [request.get('scheme_id', 'original')]
            elif mode == 'random_choice':
                choices = request.get('scheme_ids', [])
                if not isinstance(choices, (list, tuple)) or not choices:
                    raise ValueError('Pipette scheme_ids must be nonempty catalog choices')
            else:
                raise ValueError(f'Unsupported Pipette selection mode: {mode}')
            if any(not isinstance(name, str) or name not in self.catalog['schemes'] for name in choices):
                raise ValueError(f'Unknown Pipette scheme: {choices}')
            if not self.rendering_enabled and any(name != 'original' for name in choices):
                raise ValueError('Pipette candidates require pipette_rendering={"enabled": True}')
            requests.append((i, mode, choices))
        return requests

    def finish_reset(self, env_idx, options):
        indices = env_idx.tolist()
        if (not indices or any(type(i) is not int or not 0 <= i < len(self.bindings) for i in indices)
                or len(indices) != len(set(indices))):
            raise ValueError('Pipette env_idx must be nonempty, unique valid environment indices')
        requests = []
        for i, mode, choices in self.resolve_requests(indices, options.get('pipette_appearance', {})):
            if self.bindings[i] is None:
                raise RuntimeError(f'Pipette environment is not bound: {i}')
            if any(part.material != material for _, _, part, material, _ in self.bindings[i]):
                raise RuntimeError('Pipette bound material was replaced')
            parameters = {name: {oid: self.scheme_parameters(oid, name)
                                for oid in {row[0] for row in self.bindings[i]}}
                          for name in choices}
            requests.append((i, mode, choices, parameters))
        # A single immutable texture can be shared. Load it before RNG or
        # material writes, and only if a requested candidate uses the plate.
        if self._plate_label is None and any(
            any(name != 'original' and 'pipette_stand' in parameters[name] for name in choices)
            for _, _, choices, parameters in requests
        ):
            from sapien.render import RenderTexture2D
            self._plate_label = RenderTexture2D(
                str(self._plate_label_path), mipmap_levels=self._plate_label_levels)
        # Validate every selected environment before any sampling or material mutation.
        selections = [(i, str(self.rng[i].choice(choices)) if mode == 'random_choice' else choices[0], params)
                      for i, mode, choices, params in requests]
        for i, name, parameters in selections:
            for object_id, role, part, material, native in self.bindings[i]:
                values = self.resolved_parameters(native, parameters[name][object_id].get(role, {}))
                if object_id == 'pipette_stand' and role == 'base_plate':
                    native_texture = values.pop('base_color_texture')
                    # SAPIEN 3.0.3 uploads the changed texture mask on the next
                    # uniform write. Set the texture before writing base_color.
                    material.base_color_texture = native_texture if name == 'original' else self._plate_label
                for key, value in values.items():
                    setattr(material, key, value)
            self.schemes[i] = name
            self.episodes[i] += 1
            self.records.append({'env_idx': i, 'episode_index': self.episodes[i],
                                 'scheme_id': name, 'catalog_version': self.catalog['version']})
