"""Drawer/socket render-only adapter; Charger keeps its independent catalog.

URDF semantics identify panels, handles and sliders. Texture presence is never
a role classifier. The native geometry, UVs and physical builders are untouched.
"""
import copy
import json
from pathlib import Path

import numpy as np

CATALOG = Path(__file__).resolve().parents[1] / 'assets/variation/drawer_plug/fixtures_v1/catalog.json'
FIELDS = ('base_color', 'roughness', 'metallic')


class FixtureAppearance:
    def __init__(self, config, num_envs):
        self.config = copy.deepcopy(config)
        self.catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
        self.rng = [np.random.default_rng(np.random.SeedSequence([int(config.get('seed', 0)), i]))
                    for i in range(num_envs)]
        self.schemes = ['original'] * num_envs
        self.episodes = [0] * num_envs
        self.records = []
        self.bindings = [[] for _ in range(num_envs)]
        self._objects = None

    def _bind(self, env):
        import sapien.render as sr
        entries = []
        if env.has_drawer:
            for i, drawer in enumerate(env._drawers):
                for link in drawer.get_links():
                    entries.extend(('drawer', link.name, i, raw) for raw in link._objs)
        if env.has_socket:
            entries.extend(('socket', '', i, raw) for i, raw in enumerate(env.socket._objs))
        objects = tuple(raw for _, _, _, raw in entries)
        if self._objects is not None and len(objects) == len(self._objects) and all(
                a is b for a, b in zip(objects, self._objects)):
            return
        self.bindings = [[] for _ in range(env.num_envs)]
        owners = []  # Hold wrappers: comparing Python ids alone misses native aliases.
        for obj, link, i, raw in entries:
            entity = getattr(raw, 'entity', raw)
            body = entity.find_component_by_type(sr.RenderBodyComponent)
            if body is None:
                continue  # URDF base has no visual.
            if obj == 'socket' and len(body.render_shapes) != 8:
                raise ValueError('Socket must contain six shell boxes and two dark liners')
            for shape_index, shape in enumerate(body.render_shapes):
                if obj == 'drawer':
                    filename = Path(shape.filename).name
                    mapping = self.catalog['drawer_mesh_roles'].get(filename)
                    if mapping is None or mapping['link'] != link:
                        raise ValueError(f'Unknown Drawer semantic binding: {link}/{filename}')
                    role = mapping['role']
                else:
                    filename = f'box_{shape_index}'
                    role = 'shell' if shape_index < 6 else 'hole'
                for part_index, part in enumerate(shape.parts):
                    material = part.material
                    for previous, owner, previous_role in owners:
                        if material == previous and (owner != i or previous_role != (obj, role)):
                            raise RuntimeError('Material aliases another environment or semantic role')
                    owners.append((material, i, (obj, role)))
                    native = {key: copy.deepcopy(getattr(material, key)) for key in FIELDS}
                    native['base_color_texture'] = material.base_color_texture
                    binding = dict(object=obj, link=link, mesh=filename, part=part_index,
                                   role=role, material=material, native=native)
                    # The inspected Drawer source has map_Kd only. Do not silently
                    # retain wood bump/roughness maps if a different asset is used.
                    if (obj == 'drawer' and role != 'slider') or role == 'shell':
                        for channel in ('normal_texture', 'roughness_texture', 'metallic_texture'):
                            if getattr(material, channel) is not None:
                                raise ValueError(f'Unreviewed {channel} on {obj}/{filename}')
                    self.bindings[i].append(binding)
        for row in self.bindings:
            if env.has_drawer:
                actual = {b['mesh'] for b in row if b['object'] == 'drawer'}
                if actual != set(self.catalog['drawer_mesh_roles']):
                    raise ValueError('Incomplete Drawer visual mesh coverage')
            if env.has_socket and {b['role'] for b in row if b['object'] == 'socket'} != {'shell', 'hole'}:
                raise ValueError('Incomplete Socket visual coverage')
            # One stable private texture per environment, source image and role:
            # the shared wood map is retained on fronts but masked on the shell.
            pool = {}
            for binding in row:
                texture = binding['native']['base_color_texture']
                if binding['object'] != 'drawer' or binding['role'] == 'slider' or texture is None:
                    continue
                source = (texture.filename, binding['role'])
                if source not in pool:
                    pixels = texture.download().copy()
                    live = sr.RenderTexture2D(array=pixels, format=texture.format,
                                             mipmap_levels=texture.mipmap_levels,
                                             filter_mode=texture.filter_mode,
                                             address_mode=texture.address_mode, srgb=texture.is_srgb)
                    pool[source] = dict(texture=live, pixels=pixels, srgb=texture.is_srgb)
                binding['live'] = pool[source]
                binding['material'].base_color_texture = pool[source]['texture']
        self._objects = objects

    @staticmethod
    def _solid_pixels(live, linear_rgb):
        """Opaque paint/laminate replaces wood colour, preserving native alpha.

        No grain, random noise, normals or scratches are synthesized. Colour
        texture bytes are encoded to match the native texture's colour space.
        """
        pixels = live['pixels'].copy()
        rgb = np.asarray(linear_rgb)
        if live['srgb']:
            rgb = np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - 0.055)
        if np.issubdtype(pixels.dtype, np.integer):
            rgb = np.rint(rgb * np.iinfo(pixels.dtype).max)
        if pixels.ndim != 3 or pixels.shape[-1] not in (3, 4):
            raise ValueError('Expected RGB/RGBA colour texture')
        pixels[..., :3] = rgb.astype(pixels.dtype)
        return pixels

    @staticmethod
    def _surface_color(binding, params):
        if params is None:
            return binding['native']['base_color']
        # The colour texture already contains the drawer finish. Apply the
        # chosen colour only once; untextured pieces and sockets use base color.
        rgb = [1.0, 1.0, 1.0] if 'live' in binding else params['base_color'][:3]
        return [*rgb, float(binding['native']['base_color'][3])]

    @staticmethod
    def _texture_pixels(live, params):
        if params is None:
            return live['pixels']
        mode = params.get('texture_mode', 'solid')
        if mode == 'solid':
            return FixtureAppearance._solid_pixels(live, params['base_color'][:3])
        if mode != 'oak_tone':
            raise ValueError(f'Unknown drawer texture mode: {mode}')
        # Transform the existing texels in place in UV space; keep the native
        # grain orientation and layout, including edge faces and alpha.
        pixels = live['pixels'].copy()
        scale = np.iinfo(pixels.dtype).max if np.issubdtype(pixels.dtype, np.integer) else 1.0
        rgb = pixels[..., :3].astype(np.float32) / scale
        if live['srgb']:
            rgb = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
        luma = (rgb @ np.array([.2126, .7152, .0722], dtype=np.float32))[..., None]
        sat = params['source_saturation']
        rgb = np.clip((sat * rgb + (1 - sat) * luma) * params['source_gain'], 0, 1)
        if live['srgb']:
            rgb = np.where(rgb <= .0031308, 12.92 * rgb, 1.055 * rgb ** (1 / 2.4) - .055)
        pixels[..., :3] = (np.rint(rgb * scale) if scale != 1 else rgb).astype(pixels.dtype)
        return pixels

    def finish_reset(self, env, env_idx, options):
        self._bind(env)
        override = options.get('drawer_plug_appearance', {})
        for i in env_idx.tolist():
            request = {**self.config, **self.config.get('per_env', {}).get(str(i), {}),
                       **override, **override.get('per_env', {}).get(str(i), {})}
            mode = request.get('mode', 'explicit')
            if mode == 'explicit':
                name = request.get('scheme_id', 'original')
            elif mode == 'random_choice':
                choices = request.get('scheme_ids', [])
                if not choices or any(s not in self.catalog['schemes'] for s in choices):
                    raise ValueError('scheme_ids must be a nonempty catalog selection')
                name = str(self.rng[i].choice(choices))
            else:
                raise ValueError(f'Unknown fixture selection mode: {mode}')
            if name not in self.catalog['schemes']:
                raise ValueError(f'Unknown fixture scheme: {name}')
            scheme = self.catalog['schemes'][name]
            uploaded = set()
            for binding in self.bindings[i]:
                material, native = binding['material'], binding['native']
                params = scheme.get(binding['object'], {}).get(binding['role'])
                for key in FIELDS:
                    setattr(material, key, native[key])
                if params is not None:
                    material.base_color = self._surface_color(binding, params)
                    material.roughness = params['roughness']
                    material.metallic = params['metallic']
                if 'live' in binding:
                    live = binding['live']
                    if id(live) not in uploaded:
                        pixels = self._texture_pixels(live, params)
                        live['texture'].upload(pixels)
                        uploaded.add(id(live))
            self.schemes[i] = name
            self.episodes[i] += 1
            objects = sorted({b['object'] for b in self.bindings[i]})
            record = dict(env_idx=i, episode_index=self.episodes[i], scheme_id=name,
                          catalog_version=self.catalog['version'], objects=objects)
            if 'drawer' in objects:
                record['drawer_revision'] = self.catalog['drawer_revision']
            self.records.append(record)
