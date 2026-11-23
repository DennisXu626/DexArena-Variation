"""Furniture material selection and per-environment reset bindings."""
import copy
import json
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'tasks/assets/variation/furniture_assembly/v1/catalog.json'
FIELDS = ('base_color', 'roughness', 'metallic')
MATERIAL_FIELDS = FIELDS + (
    'specular', 'emission', 'transmission', 'ior', 'transmission_roughness',
    'base_color_texture', 'roughness_texture', 'metallic_texture',
    'normal_texture', 'emission_texture', 'transmission_texture',
)
TASKS = {
    'FurnitureAssemblyLayFlatPanelEnv': 'LayFlatPanel',
    'FurnitureAssemblyInsertRailEnv': 'InsertRail',
    'FurnitureAssemblyFastenScrewEnv': 'FastenScrew',
}
ROLES = {
    'flat_panel': {'face': (.72, 0), 'cut': (.86, 0), 'edge': (.62, 0),
                   'routed': (.45, 0), 'label': (.65, 0), 'ink': (.8, 0)},
    'panel_rack': {'body': (.55, .35), 'plate': (.70, .30), 'pad': (.9, 0),
                   'bolt': (.30, .90), 'decal': (.55, 0)},
    'rail': {'metal_body': (.28, .92), 'channel_details': (.42, .85)},
    'insert_screw': {'grip': (.55, .55), 'reference': (.55, .25)},
    'wing_screw': {'grip': (.60, .10), 'reference': (.50, .30)},
}


def validate_parameters(params):
    if set(params) != set(FIELDS):
        raise ValueError(f'Expected material fields {FIELDS}')
    color = np.asarray(params['base_color'], dtype=float)
    if (color.shape != (4,) or not np.isfinite(color).all()
            or np.any(color < 0) or np.any(color > 1) or color[3] != 1
            or not 0 <= float(params['roughness']) <= 1
            or not 0 <= float(params['metallic']) <= 1):
        raise ValueError('Invalid opaque material parameters')
    return copy.deepcopy(params)


class FurnitureAppearance:
    def __init__(self, config, num_envs):
        self.config = copy.deepcopy(config)
        self.catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
        self.catalogs = {
            name: json.loads((ROOT / entry['catalog']).read_text(encoding='utf-8'))
            for name, entry in self.catalog['objects'].items()
        }
        seed = int(config.get('seed', 0))
        self.rng = [np.random.default_rng(np.random.SeedSequence([seed, i])) for i in range(num_envs)]
        self.bindings = [None] * num_envs
        self.panel_surfaces = [()] * num_envs
        self.schemes = ['original'] * num_envs
        self.episodes = [0] * num_envs
        self.records = []
        for object_id, catalog in self.catalogs.items():
            if catalog['object_id'] != f'furniture_assembly.{object_id}':
                raise ValueError(f'Unexpected furniture catalog: {object_id}')
            for name in self.catalog['schemes']:
                self.scheme_parameters(object_id, name)

    def scheme_parameters(self, object_id, scheme_id):
        entry = self.catalog['objects'][object_id]
        catalog = self.catalogs[object_id]
        scheme = catalog['schemes'][entry['scheme_map'][scheme_id]]
        if scheme_id == 'original':
            if scheme != {'mode': 'restore_native'}:
                raise ValueError('Original must restore native materials')
            return {}
        if scheme['mode'] != 'material_override':
            raise ValueError('Candidate must use material_override')
        if 'roles' in scheme:
            params = scheme['roles']
        elif object_id == 'flat_panel':
            params = {role: {
                'base_color': [float(v) * factor for v in scheme['base_color'][:3]] + [scheme['base_color'][3]],
                'roughness': scheme['roughness'][role], 'metallic': scheme['metallic'],
            } for role, factor in catalog['color_factors'].items()}
        else:
            raise ValueError(f'Missing furniture roles: {object_id}')
        if set(params) & set(catalog['preserve_roles']):
            raise ValueError(f'Candidate edits protected roles: {object_id}')
        return {role: validate_parameters(value) for role, value in params.items()}

    def panel_finish(self, scheme_id):
        local_id = self.catalog['objects']['flat_panel']['scheme_map'][scheme_id]
        return self.catalogs['flat_panel']['schemes'][local_id].get('surface')

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
                    raise RuntimeError('Furniture visual record/shape count mismatch')
                for record, shape in zip(records, native_body.render_shapes):
                    if len(shape.parts) != 1:
                        raise RuntimeError('Expected one furniture material per visual record')
                    source = shape.parts[0].material
                    material = sr.RenderMaterial()
                    for key in MATERIAL_FIELDS:
                        if hasattr(source, key):
                            setattr(material, key, getattr(source, key))
                    record.material = material
                return original_build()

            link_builder.build_render_component = build_private

    def bind(self, base, env_id):
        import sapien.render as sr
        from .finishes import PanelSurface, WOOD_FINISHES

        known_finishes = {'plain', *WOOD_FINISHES}
        if any(self.panel_finish(name) not in known_finishes for name in self.catalog['schemes'] if name != 'original'):
            raise ValueError('Unknown panel finish in furniture catalog')

        task = TASKS[type(base).__name__]
        handles = {'flat_panel': base.panel}
        if task == 'LayFlatPanel':
            handles['panel_rack'] = base.rack
        else:
            handles.update(rail=base.rail_body, screw=base.screw_head)
        bindings = []
        face_boxes = []
        for object_id, handle in handles.items():
            if len(handle._objs) != len(self.bindings):
                raise RuntimeError(f'Furniture environment count mismatch: {object_id}')
            raw = handle._objs[env_id]
            entity = getattr(raw, 'entity', raw)
            body = entity.find_component_by_type(sr.RenderBodyComponent)
            if body is None:
                raise RuntimeError(f'Missing furniture visual: {object_id}')
            kind = ('insert_screw' if task == 'InsertRail' else 'wing_screw') if object_id == 'screw' else object_id
            signatures = ROLES[kind]
            counts = Counter()
            for shape in body.render_shapes:
                shape_roles = set()
                for part in shape.parts:
                    material = part.material
                    matches = [role for role, signature in signatures.items()
                               if np.allclose([material.roughness, material.metallic], signature, rtol=0, atol=2e-6)]
                    if len(matches) != 1:
                        raise RuntimeError(f'Unexpected furniture material: {object_id}')
                    role = matches[0]
                    native = {key: copy.deepcopy(getattr(material, key)) for key in FIELDS}
                    bindings.append((object_id, role, part, material, native))
                    if object_id == 'flat_panel' and role == 'face' and isinstance(shape, sr.RenderShapeBox):
                        face_boxes.append((material, shape))
                    shape_roles.add(role)
                counts.update(shape_roles)
            expected = self._expected_counts(object_id, task, base.visual_detail)
            if dict(counts) != expected:
                raise RuntimeError(f'Furniture role counts differ: {object_id}: {dict(counts)} != {expected}')
        for i, previous in enumerate(self.bindings):
            if previous is not None and i != env_id:
                if any(material == other for _, _, _, material, _ in bindings
                       for _, _, _, other, _ in previous):
                    raise RuntimeError('Furniture material shared across environments')
        if len(face_boxes) != 3:
            raise RuntimeError('Expected three UV-mapped furniture panel face boxes')
        self.panel_surfaces[env_id] = tuple(PanelSurface(material, shape, sr.RenderTexture2D)
                                            for material, shape in face_boxes)
        self.bindings[env_id] = bindings

    @staticmethod
    def _expected_counts(object_id, task, detail):
        if object_id == 'flat_panel':
            counts = dict(face=5, cut=2, edge=4)
            if detail:
                counts.update(routed=4, label=1, ink=6)
            return counts
        if object_id == 'panel_rack':
            return dict(body=8, plate=1, pad=6, bolt=8, decal=9) if detail else dict(body=4, plate=1, pad=2)
        if object_id == 'rail':
            return dict(metal_body=3, channel_details=22 if task == 'InsertRail' else 11)
        return dict(grip=17, reference=4) if task == 'InsertRail' else dict(grip=2, reference=2)

    def finish_reset(self, env_idx, options):
        override = options.get('furniture_appearance', {})
        requests = []
        for i in env_idx.tolist():
            request = {**self.config, **self.config.get('per_env', {}).get(str(i), {}),
                       **override, **override.get('per_env', {}).get(str(i), {})}
            mode = request.get('mode', 'explicit')
            if mode == 'explicit':
                choices = [request.get('scheme_id', 'original')]
            elif mode == 'random_choice':
                choices = request.get('scheme_ids', [])
                if not choices or any(value not in self.catalog['schemes'] for value in choices):
                    raise ValueError('Furniture scheme_ids must be nonempty catalog choices')
            else:
                raise ValueError(f'Unsupported furniture selection mode: {mode}')
            if any(name not in self.catalog['schemes'] for name in choices):
                raise ValueError(f'Unknown furniture scheme: {choices}')
            if self.bindings[i] is None:
                raise RuntimeError(f'Furniture environment is not bound: {i}')
            parameters = {name: {oid: self.scheme_parameters(oid, name)
                                for oid in {row[0] for row in self.bindings[i]}}
                          for name in choices}
            requests.append((i, mode, choices, parameters))
        selections = [(i, str(self.rng[i].choice(choices)) if mode == 'random_choice' else choices[0], params)
                      for i, mode, choices, params in requests]
        # Other families reuse scalar reset selection without panel bindings.
        panel_surfaces = getattr(self, 'panel_surfaces', None)
        for i, name, parameters in selections:
            if panel_surfaces is not None and panel_surfaces[i]:
                face = parameters[name]['flat_panel'].get('face', {})
                finish = self.panel_finish(name)
                for surface in panel_surfaces[i]:
                    surface.apply(name, finish, face.get('base_color'))
            for object_id, role, part, material, native in self.bindings[i]:
                params = parameters[name][object_id].get(role, native)
                for key in FIELDS:
                    setattr(material, key, params[key])
            self.schemes[i] = name
            self.episodes[i] += 1
            self.records.append({'env_idx': i, 'episode_index': self.episodes[i],
                                 'scheme_id': name, 'catalog_version': self.catalog['version']})
