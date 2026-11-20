"""Opt-in appearances of the receiving bowl and simulated liquid in PourBeads."""
import copy

import numpy as np
from PIL import Image


# Linear base colours for spheres; the bowl uses the same reviewed tint
# coefficients on the source diffuse map's 8-bit luminance.
PALETTE = {
    "ocean":  ((.18, .68, .78), .45, .25),
    "citrus": ((1., .68, .25), .55, .35),
    "violet": ((.65, .28, .90), None, None),
}


def tint_bowl(native, color):
    if native.dtype != np.uint8 or native.ndim != 3 or native.shape[-1] not in (3, 4):
        raise ValueError("Expected the native 8-bit RGB(A) bowl diffuse texture")
    luminance = np.asarray(Image.fromarray(native[..., :3]).convert("L"))
    tinted = native.copy()
    tinted[..., :3] = (luminance[..., None] * np.asarray(color)).astype(np.uint8)
    return tinted


class PouringAppearance:
    def __init__(self, config):
        self.default = config.get("scheme_id", "original")

    def bind(self, bowl, particles):
        import sapien.render as render

        self.bindings = []
        self.schemes = []
        owners = []
        for idx, raw in enumerate(bowl._objs):
            body = raw.find_component_by_type(render.RenderBodyComponent)
            parts = [p for shape in body.render_shapes for p in shape.parts]
            if len(parts) != 1:
                raise ValueError("Expected one native bowl material")
            bowl_mat = parts[0].material
            if bowl_mat in owners:
                raise RuntimeError("Shared bowl material across environments")
            owners.append(bowl_mat)
            texture = bowl_mat.base_color_texture
            native = texture.download().copy()
            live = render.RenderTexture2D(array=native, format=texture.format,
                mipmap_levels=texture.mipmap_levels, filter_mode=texture.filter_mode,
                address_mode=texture.address_mode, srgb=texture.is_srgb)
            bowl_mat.base_color_texture = live
            pixels = {"original": native, **{s: tint_bowl(native, p[0]) for s, p in PALETTE.items()}}

            # ManiSkill's build_sphere shares an explicit RenderMaterial between
            # environments. Isolate its visual before cameras are constructed.
            # The native entities, PhysX components, and state registry stay intact.
            materials = [(bowl_mat, "bowl")]
            for particle in particles:
                ent = particle._objs[idx]
                old = ent.find_component_by_type(render.RenderBodyComponent)
                shape, = old.render_shapes
                if not isinstance(shape, render.RenderShapeSphere):
                    raise ValueError("Expected the native spherical liquid proxy")
                mat = render.RenderMaterial(base_color=shape.material.base_color)
                sphere = render.RenderShapeSphere(shape.radius, mat)
                sphere.name, sphere.local_pose, sphere.front_face = shape.name, shape.local_pose, shape.front_face
                private = render.RenderBodyComponent()
                private.name, private.visibility, private.shading_mode = old.name, old.visibility, old.shading_mode
                if old.is_render_id_disabled:
                    private.disable_render_id()
                private.attach(sphere)
                ent.remove_component(old)
                ent.add_component(private)
                materials.append((mat, "beads"))
            slots = [(m, role, copy.deepcopy(m.base_color), m.roughness, m.metallic) for m, role in materials]
            self.bindings.append((live, pixels, slots))
            self.schemes.append("original")

    def finish_reset(self, env_idx, options):
        scheme = options.get("pouring_appearance", {}).get("scheme_id", self.default)
        if scheme != "original" and scheme not in PALETTE:
            raise ValueError(f"Unknown PourBeads appearance: {scheme}")
        for idx in env_idx.tolist():
            texture, pixels, slots = self.bindings[idx]
            texture.upload(pixels[scheme])
            for mat, role, native_color, roughness, metallic in slots:
                if scheme == "original":
                    mat.base_color, mat.roughness, mat.metallic = native_color, roughness, metallic
                else:
                    rgb, bowl_rough, bead_rough = PALETTE[scheme]
                    mat.base_color = [*rgb, float(native_color[3])]
                    rough = bowl_rough if role == "bowl" else bead_rough
                    mat.roughness = roughness if rough is None else rough
                    mat.metallic = metallic if rough is None else 0.
            self.schemes[idx] = scheme
