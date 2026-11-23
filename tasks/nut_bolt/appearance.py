"""Nut & Bolt material bindings using the PR11 reset lifecycle."""
import copy
import json
from pathlib import Path

import numpy as np

from tasks.furniture_assembly.appearance import FurnitureAppearance, FIELDS, validate_parameters

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'tasks/assets/variation/nut_bolt/v1/catalog.json'


def validate_per_env(config, num_envs):
    if not isinstance(config, dict):
        raise ValueError('Nut & Bolt appearance config must be a dictionary')
    if 'per_env' in config:
        per_env = config['per_env']
        allowed = {str(index) for index in range(num_envs)}
        if not isinstance(per_env, dict) or any(
            type(key) is not str or key not in allowed or not isinstance(value, dict)
            for key, value in per_env.items()
        ):
            raise ValueError('Nut & Bolt per_env must map canonical environment keys to dictionaries')


def reset_indices(env_idx, num_envs):
    indices = env_idx.tolist() if hasattr(env_idx, 'tolist') else env_idx
    if (not isinstance(indices, (list, tuple)) or not indices
            or any(type(index) is not int or not 0 <= index < num_envs for index in indices)
            or any(previous >= current for previous, current in zip(indices, indices[1:]))):
        raise ValueError('Nut & Bolt reset requires valid, strictly increasing environment indices')
    return indices


def role_order(object_id):
    if object_id == 'bolt':
        return ['shaft'] + ['tip'] * 20 + ['thread'] * 192 + ['head']
    if object_id == 'nut':
        return ['reference_face'] + ['body'] * 5
    raise ValueError(object_id)


def check_shape(base, shape, object_id, index):
    """Reject changes in native visual type, dimensions or segment ordering."""
    import sapien.render as sr

    def close(actual, expected):
        if not np.allclose(actual, expected, rtol=0, atol=2e-7):
            raise RuntimeError(f'Unexpected {object_id} visual geometry at {index}')

    if object_id == 'nut':
        if not isinstance(shape, sr.RenderShapeBox):
            raise RuntimeError('Nut visual must be a box')
        angle = index * np.pi / 3
        apothem = base.nut_circumradius * np.cos(np.pi / 6)
        close(shape.half_size, [base.nut_circumradius * .55,
                               base.nut_wall_thickness / 2, base.nut_half_height])
        close(shape.local_pose.p, [apothem * np.cos(angle), apothem * np.sin(angle), 0])
        expected = np.array([np.cos((angle + np.pi / 2) / 2), 0, 0,
                             np.sin((angle + np.pi / 2) / 2)])
        if not (np.allclose(shape.local_pose.q, expected, rtol=0, atol=2e-7)
                or np.allclose(shape.local_pose.q, -expected, rtol=0, atol=2e-7)):
            raise RuntimeError('Nut panel order/orientation changed')
    elif index <= 20:
        if not isinstance(shape, sr.RenderShapeCylinder):
            raise RuntimeError('Bolt shaft/tip visual must be a cylinder')
        if index == 0:
            close(shape.radius, base.bolt_radius)
            close(shape.half_length, base.bolt_height / 2)
            close(shape.local_pose.p, [0, 0, 0])
    elif index <= 212:
        if not isinstance(shape, sr.RenderShapeCapsule):
            raise RuntimeError('Bolt thread visual must be a capsule')
    elif not isinstance(shape, sr.RenderShapeTriangleMesh):
        raise RuntimeError('Bolt head must be the imported triangle mesh')


class NutBoltAppearance(FurnitureAppearance):
    """Use PR11 private-material construction and atomic scheme selection."""

    def __init__(self, config, num_envs):
        validate_per_env(config, num_envs)
        self.config = copy.deepcopy(config)
        self.catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
        self.catalogs = {name: json.loads((ROOT / entry['catalog']).read_text(encoding='utf-8'))
                         for name, entry in self.catalog['objects'].items()}
        seed = int(config.get('seed', 0))
        self.rng = [np.random.default_rng(np.random.SeedSequence([seed, i])) for i in range(num_envs)]
        self.bindings = [None] * num_envs
        self.schemes = ['original'] * num_envs
        self.episodes = [0] * num_envs
        self.records = []
        for object_id, catalog in self.catalogs.items():
            if catalog['object_id'] != f'nut_bolt.{object_id}':
                raise ValueError(f'Unexpected Nut & Bolt catalog: {object_id}')
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
        params = scheme['roles']
        if set(params) & set(catalog['preserve_roles']):
            raise ValueError(f'Candidate edits protected roles: {object_id}')
        expected = {'shaft', 'head'} if object_id == 'bolt' else {'body', 'reference_face'}
        if set(params) != expected:
            raise ValueError(f'Unexpected editable roles: {object_id}')
        return {role: validate_parameters(value) for role, value in params.items()}

    def bind(self, base, env_id):
        import sapien.render as sr

        targets = [('bolt', base.bolt)]
        if base.has_nut:
            targets += [('nut', base.nut), ('nut', base.threaded_nut)]
        bindings = []
        for object_id, handle in targets:
            if len(handle._objs) != len(self.bindings):
                raise RuntimeError(f'Nut & Bolt environment count differs: {object_id}')
            raw = handle._objs[env_id]
            entity = getattr(raw, 'entity', raw)
            body = entity.find_component_by_type(sr.RenderBodyComponent)
            roles = role_order(object_id)
            if body is None or len(body.render_shapes) != len(roles):
                raise RuntimeError(f'Unexpected render shapes: {object_id}')
            for index, (shape, role) in enumerate(zip(body.render_shapes, roles)):
                check_shape(base, shape, object_id, index)
                if len(shape.parts) != 1:
                    raise RuntimeError('Expected one material part per Nut & Bolt visual')
                part = shape.parts[0]
                material = part.material
                captured = {key: copy.deepcopy(getattr(material, key)) for key in FIELDS}
                bindings.append((object_id, role, part, material, captured))
        other_materials = [row[3] for previous in self.bindings if previous is not None
                           for row in previous]
        seen = list(other_materials)
        for _, _, _, material, _ in bindings:
            if any(material == other for other in seen):
                raise RuntimeError('Nut & Bolt material aliases another role or environment')
            seen.append(material)
        self.bindings[env_id] = bindings

    def validate_selection(self, indices, override):
        """Check effective requests before scene creation or episode state changes."""
        schemes = self.catalog['schemes']
        for index in indices:
            key = str(index)
            request = {**self.config, **self.config.get('per_env', {}).get(key, {}),
                       **override, **override.get('per_env', {}).get(key, {})}
            mode = request.get('mode', 'explicit')
            if mode == 'explicit':
                name = request.get('scheme_id', 'original')
                if not isinstance(name, str) or name not in schemes:
                    raise ValueError(f'Unknown Nut & Bolt scheme for env {index}: {name!r}')
            elif mode == 'random_choice':
                choices = request.get('scheme_ids', [])
                if (not isinstance(choices, (list, tuple)) or not choices
                        or any(not isinstance(name, str) or name not in schemes for name in choices)):
                    raise ValueError(f'Nut & Bolt scheme_ids for env {index} must be nonempty catalog choices')
            else:
                raise ValueError(f'Unsupported Nut & Bolt selection mode for env {index}: {mode!r}')

    def finish_reset(self, env_idx, options):
        indices = reset_indices(env_idx, len(self.bindings))
        override = options.get('nut_bolt_appearance', {})
        validate_per_env(override, len(self.bindings))
        return super().finish_reset(np.asarray(indices), {'furniture_appearance': override})
