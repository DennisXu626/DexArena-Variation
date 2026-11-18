"""101408 ClickMouse render-only adapter; no Long or physical state writes."""
import copy
import json
from pathlib import Path

import numpy as np

from tasks.office_desk.devices_appearance import validate_appearance_config, validate_reset_indices, validate_reset_override

CATALOG = Path(__file__).resolve().parents[1] / 'assets/variation/office_desk/mouse_101408/v1/catalog.json'
ROLES = {'link_0': 'buttons', 'link_1': 'buttons', 'link_2': 'wheel', 'link_3': 'shell'}
FIELDS = ('base_color', 'roughness', 'metallic')


class MouseAppearance:
    def __init__(self, config, num_envs):
        validate_appearance_config(config, num_envs)
        self.config = copy.deepcopy(config)
        self.catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
        seed = int(config.get('seed', 0))
        self.rng = [np.random.default_rng(np.random.SeedSequence([seed, i])) for i in range(num_envs)]
        self.bindings = [None] * num_envs
        self.schemes = ['original'] * num_envs
        self.episodes = [0] * num_envs
        self.records = []

    @staticmethod
    def isolate_builder_materials(builder):
        """Use task-owned LinkBuilders before any scene/render batching.

        Imported mesh-part materials are read-only. Inspect the unattached native
        render component, then pass independent copies through visual_records.
        Mesh files, scales, poses and all collision builders remain unchanged.
        101408 has exactly one native material part per OBJ visual record.
        """
        import sapien.render as sr
        for link_builder in builder.link_builders:
            original_build = link_builder.build_render_component
            records = list(link_builder.visual_records)

            def build_private(original_build=original_build, records=records):
                native_body = original_build()
                if not records:
                    return native_body
                if len(native_body.render_shapes) != len(records):
                    raise RuntimeError('Mouse visual record/shape count mismatch')
                for record, shape in zip(records, native_body.render_shapes):
                    if len(shape.parts) != 1:
                        raise RuntimeError('Expected one Mouse material per source OBJ')
                    source = shape.parts[0].material
                    material = sr.RenderMaterial()
                    for key in ('base_color', 'roughness', 'metallic', 'specular',
                                'emission', 'transmission', 'ior', 'transmission_roughness',
                                'base_color_texture', 'roughness_texture',
                                'metallic_texture', 'normal_texture', 'emission_texture',
                                'transmission_texture'):
                        if hasattr(source, key):
                            setattr(material, key, getattr(source, key))
                    record.material = material
                return original_build()

            link_builder.build_render_component = build_private

    def bind(self, mouse, env_id):
        """Bind by URDF link; repeated material_0_0 names are not role IDs."""
        import sapien.render as sr
        bindings = []
        for link_name, role in ROLES.items():
            for entity in mouse.links_map[link_name]._objs:
                body = entity.entity.find_component_by_type(sr.RenderBodyComponent)
                if body is None:
                    raise RuntimeError(f'Missing Mouse visual: {link_name}')
                for shape in body.render_shapes:
                    for part in shape.parts:
                        material = part.material
                        native = {key: copy.deepcopy(getattr(material, key)) for key in FIELDS}
                        bindings.append((role, part, material, native))
        if {r for r, *_ in bindings} != set(ROLES.values()):
            raise RuntimeError('Incomplete Mouse role binding')
        # Hold references and reject cross-environment aliases before any mutation.
        for previous in self.bindings:
            if previous is not None:
                if any(m == other for _, _, m, _ in bindings for _, _, other, _ in previous):
                    raise RuntimeError('Mouse material shared across environments')
        self.bindings[env_id] = bindings

    def finish_reset(self, env_idx, options):
        indices = validate_reset_indices(env_idx, len(self.bindings))
        override = options.get('mouse_appearance', {})
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
                    raise ValueError('Mouse scheme_ids must be nonempty catalog choices')
            else:
                raise ValueError(f'Unsupported Mouse selection mode: {mode}')
            if any(name not in self.catalog['schemes'] for name in choices):
                raise ValueError(f'Unknown Mouse scheme: {choices}')
            if self.bindings[i] is None:
                raise RuntimeError(f'Mouse environment is not bound: {i}')
            requests.append((i, mode, choices))
        selections = [(i, str(self.rng[i].choice(choices)) if mode == 'random_choice' else choices[0])
                      for i, mode, choices in requests]
        for i, name in selections:
            for role, part, material, native in self.bindings[i]:
                params = native if name == 'original' else self.catalog['schemes'][name][role]
                for key in FIELDS:
                    setattr(material, key, params[key])
            self.schemes[i] = name
            self.episodes[i] += 1
            self.records.append({'env_idx': i, 'episode_index': self.episodes[i],
                                 'scheme_id': name, 'catalog_version': self.catalog['version']})
