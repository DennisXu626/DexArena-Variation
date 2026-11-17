"""Table Cleaning appearance bindings, scoped to the selected environment."""
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from PIL import Image
import sapien

CATALOG = Path(__file__).resolve().parents[1] / "assets/variation/table_cleaning/v1/catalog.json"


class CleaningAppearance:
    def __init__(self, config, num_envs):
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.config = config
        self.records = [None] * num_envs
        self.bindings = [None] * num_envs
        self.applied = [None] * num_envs

    def begin_scene(self):
        self._files = tempfile.TemporaryDirectory(prefix="table_cleaning_visuals_")
        self.applied = [None] * len(self.bindings)
        self.pixels = {}

    def private_glb(self, root, uid, env):
        source = root / f"{uid}.glb"
        destination = Path(self._files.name) / str(env) / source.name
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, destination)
        return str(destination)

    def prepare_debris(self, builder):
        records = [r for r in builder.visual_records if r.type == "file"]
        record, = records
        original = record.material
        source = original.base_color_texture
        if "original" not in self.pixels:
            pixels = source.download()
            if pixels.shape[2] == 3:
                pixels = np.asarray(Image.fromarray(pixels).convert("RGBA"))
            self.pixels["original"] = np.ascontiguousarray(pixels)
        fields = ("base_color", "roughness", "metallic", "specular", "emission",
                  "transmission", "ior", "transmission_roughness")
        private = sapien.render.RenderMaterial(**{k: getattr(original, k) for k in fields})
        for field in ("normal_texture", "roughness_texture", "metallic_texture",
                      "emission_texture", "transmission_texture"):
            setattr(private, field, getattr(original, field))
        private.base_color_texture = sapien.render.RenderTexture2D(
            self.pixels["original"], "R8G8B8A8Unorm", srgb=source.is_srgb)
        record.material = private

    @staticmethod
    def mesh_materials(actor):
        entity, = actor._objs
        render = entity.find_component_by_type(sapien.render.RenderBodyComponent)
        return [part.material for shape in render.render_shapes
                if not isinstance(shape, sapien.render.RenderShapePrimitive)
                for part in shape.parts]

    def bind(self, index, pan, bin_actor, debris):
        body, = [m for m in self.mesh_materials(pan) if m.base_color[2] > .8 and m.base_color[0] < .1]
        frame, = [m for m in self.mesh_materials(bin_actor) if m.base_color_texture is None]
        self.bindings[index] = (
            body, frame, [self.mesh_materials(actor)[0].base_color_texture for actor in debris],
            list(body.base_color), body.roughness, list(frame.base_color))

    @staticmethod
    def linear_hex(color):
        srgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        return [c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4 for c in srgb] + [1.]

    def reset(self, indices, options):
        overrides = options.get("table_cleaning_appearance", {})
        requests = []
        for index in indices:
            key = str(index)
            effective = {**self.config, **self.config.get("per_env", {}).get(key, {}),
                         **overrides, **overrides.get("per_env", {}).get(key, {})}
            scheme = effective.get("scheme_id", "original")
            if scheme not in self.catalog["schemes"]:
                raise ValueError(f"Unknown Table Cleaning appearance: {scheme}")
            requests.append((index, scheme))
        for index, scheme in requests:
            if self.applied[index] != scheme:
                body, frame, textures, base, roughness, frame_base = self.bindings[index]
                recipe = self.catalog["schemes"][scheme]
                if scheme not in self.pixels:
                    pixels = self.pixels["original"].copy()
                    factors = np.asarray(recipe["sugar_rgb_multipliers"])
                    pixels[..., :3] = np.rint(pixels[..., :3] * factors).clip(0, 255).astype(np.uint8)
                    self.pixels[scheme] = pixels
                body.base_color = self.linear_hex(recipe["pan"]) if recipe else base
                body.roughness = recipe.get("pan_roughness", roughness)
                frame.base_color = self.linear_hex(recipe["bin_frame"]) if recipe else frame_base
                if scheme != "original" or self.applied[index] is not None:
                    for texture in textures:
                        texture.upload(self.pixels[scheme])
                self.applied[index] = scheme
            previous = self.records[index]
            self.records[index] = {
                "env_idx": index, "scheme_id": scheme, "catalog_version": self.catalog["version"],
                "episode_index": 1 if previous is None else previous["episode_index"] + 1,
            }
