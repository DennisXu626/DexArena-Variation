"""Opt-in finishes for the two short tasks that show the real cabinet."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np


CATALOG = Path(__file__).resolve().parents[1] / 'assets/variation/cabinet_pouring/cabinet_v1/catalog.json'
FIELDS = ('base_color', 'roughness', 'metallic')


def finish_pixels(native, srgb, finish, grain_axis):
    """Colour only, independent of the original image's RGB values.

    A periodic, directional grain is evaluated on the existing UV layout.
    Preserve the native dimensions, channel type and alpha for in-place upload.
    """
    if native.ndim != 3 or native.shape[-1] not in (3, 4):
        raise ValueError('Expected RGB or RGBA cabinet colour texture')
    rgb = np.array(finish['color'], dtype=np.float32)
    pixels = native.copy()
    if finish['wood'] is not None:
        h, w = native.shape[:2]
        u = (np.arange(w, dtype=np.float32)[None, :] + .5) / w
        v = (np.arange(h, dtype=np.float32)[:, None] + .5) / h
        if grain_axis not in ('U', 'V'):
            raise ValueError('A textured veneer requires a measured UV grain axis')
        along, across = (u, v) if grain_axis == 'U' else (v, u)
        phase = 2 * np.pi * (across + .007*np.sin(2*np.pi*along)
                            + .003*np.sin(4*np.pi*along + 1.7))
        fine = .28*np.sin(18*phase + .9) + .12*np.cos(31*phase + .7)
        sweep = .34*np.sin(3*phase + .5) + .15*np.sin(7*phase + 1.4)
        pores = .11*np.sin(53*phase + .3*np.cos(2*np.pi*along))
        variation = (fine + sweep + pores) * (.25 if finish['wood'] == 'oak' else .38)
        rgb = rgb * (1 + variation[..., None] * np.array([.88, 1, 1.14], dtype=np.float32))
    rgb = np.clip(rgb, 0, 1)
    if srgb:
        rgb = np.where(rgb <= .0031308, rgb * 12.92, 1.055 * rgb**(1/2.4) - .055)
    if np.issubdtype(pixels.dtype, np.integer):
        rgb = np.rint(rgb * np.iinfo(pixels.dtype).max)
    pixels[..., :3] = rgb.astype(pixels.dtype)
    return pixels


class CabinetAppearance:
    def __init__(self, config, num_envs):
        self.config = copy.deepcopy(config)
        self.catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
        self.bindings = [[] for _ in range(num_envs)]
        self.schemes = ['original'] * num_envs

    def bind(self, cabinets, urdf_path):
        """Bind isolated stable textures before cameras/rendering are built."""
        import sapien.render as render

        if hashlib.sha256(urdf_path.read_bytes()).hexdigest() != self.catalog['urdf_sha256']:
            raise ValueError('Unreviewed cabinet URDF; cabinet appearance mapping is asset-specific')
        mapping = self.catalog['meshes']
        self.bindings = [[] for _ in cabinets]
        owners = []
        for env_idx, cabinet in enumerate(cabinets):
            seen = {}
            pool = {}
            for link in cabinet.get_links():
                for raw in link._objs:
                    body = raw.entity.find_component_by_type(render.RenderBodyComponent)
                    if body is None:
                        continue
                    for shape in body.render_shapes:
                        name = Path(shape.filename).name
                        if name not in mapping or mapping[name]['link'] != link.name or name in seen:
                            raise ValueError(f'Unreviewed cabinet mesh: {link.name}/{name}')
                        slots = mapping[name]['slots']
                        matched = set()
                        for part in shape.parts:
                            material = part.material
                            texture = material.base_color_texture
                            source = Path(texture.filename).name if texture is not None else 'untextured'
                            if source not in slots or source in matched:
                                raise ValueError(f'Unreviewed cabinet material slot: {name}/{source}')
                            matched.add(source)
                            role = slots[source]['role']
                            key = (source, role, slots[source]['grain_axis'])
                            if any(material == m and (env_idx != owner or key != old_key)
                                   for m, owner, old_key in owners):
                                raise RuntimeError(f'Cabinet material aliases another environment or role: {name}/{source}')
                            owners.append((material, env_idx, key))
                            if role == 'native_detail':
                                continue
                            native = {k: copy.deepcopy(getattr(material, k)) for k in FIELDS}
                            row = dict(mesh=name, role=role, source=source, material=material, native=native)
                            if texture is not None:
                                if key not in pool:
                                    pixels = texture.download().copy()
                                    private = render.RenderTexture2D(
                                        array=pixels, format=texture.format, mipmap_levels=texture.mipmap_levels,
                                        filter_mode=texture.filter_mode, address_mode=texture.address_mode,
                                        srgb=texture.is_srgb)
                                    candidates = {'original': pixels}
                                    for sid, scheme in self.catalog['schemes'].items():
                                        if sid != 'original':
                                            candidates[sid] = finish_pixels(pixels, texture.is_srgb, scheme[role], key[2])
                                    pool[key] = dict(texture=private, pixels=candidates)
                                row['live'] = pool[key]
                                material.base_color_texture = row['live']['texture']
                            self.bindings[env_idx].append(row)
                        if matched != set(slots):
                            raise ValueError(f'Missing cabinet material slots: {name}/{set(slots)-matched}')
                        seen[name] = True
            if set(seen) != set(mapping):
                raise ValueError(f'Missing cabinet meshes: {set(mapping)-set(seen)}')

    def finish_reset(self, env_idx, options):
        override = options.get('cabinet_appearance', {})
        for i in env_idx.tolist():
            request = {**self.config, **self.config.get('per_env', {}).get(str(i), {}),
                       **override, **override.get('per_env', {}).get(str(i), {})}
            sid = request.get('scheme_id', 'original')
            if sid not in self.catalog['schemes']:
                raise ValueError(f'Unknown cabinet scheme: {sid}')
            scheme = self.catalog['schemes'][sid]
            uploaded = set()
            for row in self.bindings[i]:
                material, native = row['material'], row['native']
                if sid == 'original':
                    for k in FIELDS:
                        setattr(material, k, native[k])
                else:
                    finish = scheme[row['role']]
                    rgb = [1., 1., 1.] if 'live' in row else finish['color']
                    material.base_color = [*rgb, float(native['base_color'][3])]
                    material.roughness = finish['roughness']
                    material.metallic = finish['metallic']
                if 'live' in row:
                    live = row['live']
                    if id(live) not in uploaded:
                        live['texture'].upload(live['pixels'][sid])
                        uploaded.add(id(live))
            self.schemes[i] = sid
