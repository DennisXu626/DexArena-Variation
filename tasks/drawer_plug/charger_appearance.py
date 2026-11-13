"""Charger-only appearance binding; no pose, geometry or physics writes."""
import copy
import json
from pathlib import Path

import numpy as np

CATALOG = Path(__file__).resolve().parents[1] / 'assets/variation/drawer_plug/v1/catalog.json'


class ChargerAppearance:
    def __init__(self, config, num_envs):
        self.config = copy.deepcopy(config)
        self.catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
        seed = int(config.get('seed', 0))
        self.rng = [np.random.default_rng(np.random.SeedSequence([seed, i])) for i in range(num_envs)]
        self.schemes = ['original'] * num_envs
        self.episodes = [0] * num_envs
        self.records = []

    @staticmethod
    def isolate_builder_materials(builder):
        """Reuse the accepted Cabinet per-env builder binding approach.

        Native build still owns the exact same three visual/collision boxes.
        Each render build gets fresh materials instead of sharing the explicit
        body/prong material objects across environments.
        """
        import sapien.render as sr
        original_build = builder.build_render_component
        records = [(r, r.material) for r in builder.visual_records]

        def build_private_materials():
            for record, original in records:
                material = sr.RenderMaterial()
                for key in ['base_color', 'base_color_texture', 'roughness', 'metallic']:
                    setattr(material, key, getattr(original, key))
                record.material = material
            return original_build()

        builder.build_render_component = build_private_materials

    def finish_reset(self, env, env_idx, options):
        import sapien.render as sr
        owners = {}
        bindings = []
        for i, entity in enumerate(env.charger._objs):
            body = entity.find_component_by_type(sr.RenderBodyComponent)
            groups = {'body': [], 'prongs': []}
            for shape in body.render_shapes:
                if np.allclose(shape.half_size, env.charger_half):
                    role = 'body'
                elif np.allclose(shape.half_size, env.charger_prong_half):
                    role = 'prongs'
                else:
                    raise ValueError(f'Unexpected Charger box size: {shape.half_size}')
                groups[role].append(shape)
                for part in shape.parts:
                    material = part.material
                    owner, _ = owners.setdefault(id(material), (i, material))
                    if owner != i:
                        raise RuntimeError('Charger material shared across environments')
            if [len(groups['body']), len(groups['prongs'])] != [1, 2]:
                raise ValueError('Expected one Charger body and two prongs')
            bindings.append(groups)
        override = options.get('charger_appearance', {})
        for i in env_idx.tolist():
            request = {**self.config, **self.config.get('per_env', {}).get(str(i), {}),
                       **override, **override.get('per_env', {}).get(str(i), {})}
            mode = request.get('mode', 'explicit')
            if mode == 'explicit':
                scheme_id = request.get('scheme_id', 'original')
            elif mode == 'random_choice':
                choices = request.get('scheme_ids', [])
                if not choices or any(x not in self.catalog['schemes'] for x in choices):
                    raise ValueError('scheme_ids must be a nonempty set from the Charger catalog')
                scheme_id = str(self.rng[i].choice(choices))
            else:
                raise ValueError(f'Unsupported Charger selection mode: {mode}')
            if scheme_id not in self.catalog['schemes']:
                raise ValueError(f'Unknown Charger scheme: {scheme_id}')
            for role, shapes in bindings[i].items():
                params = self.catalog['schemes'][scheme_id]['body'] if role == 'body' else self.catalog['prongs']
                for shape in shapes:
                    for part in shape.parts:
                        for key in ['base_color', 'roughness', 'metallic']:
                            setattr(part.material, key, params[key])
            self.schemes[i] = scheme_id
            self.episodes[i] += 1
            self.records.append({'env_idx': i, 'episode_index': self.episodes[i],
                                 'scheme_id': scheme_id, 'catalog_version': self.catalog['version']})
