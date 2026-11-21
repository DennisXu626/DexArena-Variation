"""Render-only bindings for the approved Package Opening appearances."""
import colorsys
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from PIL import Image
import sapien


CATALOG = Path(__file__).resolve().parents[1] / "assets/variation/package_opening/v1/catalog.json"
PARAMS = ("base_color", "roughness", "metallic")


def srgb_hex(color):
    return [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]


def linear_rgba(color):
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055)**2.4
            for v in srgb_hex(color)] + [1.0]


def recolor_apple(source, target, include_yellow_skin=False, match_target_value=False):
    rgb = source.convert("RGB")
    rgba = source.convert("RGBA")
    hsv = np.asarray(rgb.convert("HSV"), dtype=np.float32) / 255
    hue, sat, value = np.moveaxis(hsv, -1, 0)
    target_h, target_s, target_v = colorsys.rgb_to_hsv(*srgb_hex(target))
    hue_delta = (hue + .5) % 1 - .5
    # Red, saturated fruit skin only. Fade the mask over hue, saturation and
    # near-black pixels so highlights, stem recess and neutral detail survive.
    hue_weight = np.clip((.115 - np.abs(hue_delta)) / .055, 0, 1)
    sat_weight = np.clip((sat - .20) / .24, 0, 1)
    dark_weight = np.clip((value - .23) / .25, 0, 1)
    hue_spread = .50
    if include_yellow_skin:
        # Include the sunlit yellow shoulder around the stem. The masks
        # fade out on the near-black woody stem and neutral specular detail.
        yellow_hue = np.clip((hue_delta - .045) / .045, 0, 1)
        yellow_hue *= np.clip((.21 - hue_delta) / .052, 0, 1)
        bright_skin = np.clip((value - .36) / .19, 0, 1)
        hue_weight = np.maximum(hue_weight, yellow_hue * bright_skin)
        sat_weight = np.clip((sat - .095) / .265, 0, 1)
        hue_spread = .16
    weight = (hue_weight * sat_weight * dark_weight)[..., None]
    mapped_value = (target_v * np.clip(value / .85, 0, 1) if match_target_value
                    else np.clip(value * .96 + .02, 0, 1))
    mapped = np.stack(((target_h + hue_spread * hue_delta) % 1,
                       np.clip(sat * target_s / .82, 0, 1),
                       mapped_value), axis=-1)
    recolored = np.asarray(Image.fromarray(np.rint(mapped * 255).astype(np.uint8), "HSV").convert("RGB"),
                           dtype=np.float32)
    result = np.asarray(rgba).copy()
    result[..., :3] = np.rint((1 - weight) * np.asarray(rgb) + weight * recolored).astype(np.uint8)
    return result, float(np.mean(weight > .5))


class PackageAppearance:
    def __init__(self, config, num_envs):
        self.config = dict(config)
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.rng = [np.random.default_rng(np.random.SeedSequence([config.get("seed", 0), i]))
                    for i in range(num_envs)]
        self.records = [None] * num_envs
        self.begin_scene()

    def begin_scene(self):
        self.bindings = [{} for _ in self.rng]
        self.applied = [None] * len(self.rng)
        self.apple_pixels = {}
        self._mesh_cache = tempfile.TemporaryDirectory(prefix="package_visuals_")

    def prepare_box(self, builder, index):
        # SAPIEN caches OBJ parts and their imported materials by path. Give
        # each environment a private source for the exact same visual bytes.
        root = Path(self._mesh_cache.name) / str(index)
        root.mkdir()
        for link in builder.link_builders:
            for record in link.visual_records:
                if record.type == "file":
                    source = Path(record.filename)
                    if source.suffix != ".obj":
                        raise ValueError(f"Unexpected carton visual: {source}")
                    shutil.copyfile(source, root / source.name)
                    mtl = source.with_suffix(".mtl")
                    shutil.copyfile(mtl, root / mtl.name)
                    record.filename = str(root / source.name)

    def prepare_apple(self, builder):
        record, = builder.visual_records
        source = record.material
        original_texture = source.base_color_texture
        if not self.apple_pixels:
            pixels = original_texture.download()
            if pixels.dtype != np.uint8 or pixels.shape[-1] not in (3, 4):
                raise ValueError("Expected an 8-bit apple color map")
            if pixels.shape[-1] == 3:
                pixels = np.concatenate(
                    (pixels, np.full((*pixels.shape[:2], 1), 255, dtype=np.uint8)), axis=-1
                )
            self.apple_pixels["original"] = np.ascontiguousarray(pixels)
        channels = ("emission", "specular", "transmission", "ior", "transmission_roughness")
        textures = ("emission_texture", "metallic_texture", "normal_texture",
                    "roughness_texture", "transmission_texture")
        material = sapien.render.RenderMaterial(
            **{key: getattr(source, key) for key in (*PARAMS, *channels)}
        )
        for key in textures:
            setattr(material, key, getattr(source, key))
        material.base_color_texture = sapien.render.RenderTexture2D(
            self.apple_pixels["original"], "R8G8B8A8Unorm", srgb=original_texture.is_srgb
        )
        record.material = material

    def bind(self, name, actor, index):
        raw, = actor._objs
        entities = ([link.entity for link in raw.get_links()] if name == "box" else [raw])
        group = {}
        for entity in entities:
            render = entity.find_component_by_type(sapien.render.RenderBodyComponent)
            if render is None:
                continue
            for shape in render.render_shapes:
                primitive = isinstance(shape, sapien.render.RenderShapePrimitive)
                materials = [shape.material] if primitive else [part.material for part in shape.parts]
                for material in materials:
                    role = name
                    if name == "box":
                        flap = entity.name.endswith(("_0", "_1"))
                        r, g, b, _ = material.base_color
                        if primitive:
                            role = "tab" if flap else "floor"
                        elif flap:
                            role = "flap"
                        else:
                            role = "accent" if r > .7 and g < .25 and b > .3 else "body"
                    group.setdefault(role, []).append(
                        (material, {key: getattr(material, key) for key in PARAMS})
                    )
        expected = ({"body": 15, "flap": 2, "tab": 2, "floor": 1, "accent": 1}
                    if name == "box" else {name: 1})
        counts = {role: len(slots) for role, slots in group.items()}
        if counts != expected:
            raise RuntimeError(f"Unexpected {name} visual bindings: {counts}")
        self.bindings[index][name] = group

    def _choose(self, index, override):
        key = str(index)
        request = {**self.config, **self.config.get("per_env", {}).get(key, {}),
                   **override, **override.get("per_env", {}).get(key, {})}
        schemes = self.catalog["schemes"]
        mode = request.get("mode", "explicit")
        if mode == "explicit":
            scheme = request.get("scheme_id", "original")
            if scheme not in schemes:
                raise ValueError(f"Unknown Package Opening appearance scheme: {scheme}")
            return scheme
        if mode != "random_choice":
            raise ValueError(f"Unknown Package Opening appearance mode: {mode}")
        choices = request.get("scheme_ids", ())
        if not choices or any(scheme not in schemes for scheme in choices):
            raise ValueError("scheme_ids must list known Package Opening appearance schemes")
        return str(self.rng[index].choice(choices))

    def finish_reset(self, env_idx, options):
        override = options.get("package_appearance", {})
        requests = [(idx, self._choose(idx, override)) for idx in env_idx.tolist()]
        for idx, scheme in requests:
            if self.applied[idx] != scheme:
                for name, group in self.bindings[idx].items():
                    choice = self.catalog["schemes"][scheme][name]
                    recipe = self.catalog["objects"][name][choice]
                    for role, targets in group.items():
                        if role == "accent":
                            continue
                        for material, baseline in targets:
                            values = baseline
                            if choice != "original":
                                values = dict(baseline, roughness=recipe["roughness"],
                                              metallic=recipe["metallic"])
                                if name != "apple":
                                    color = recipe["colors"][role] if name == "box" else recipe["color"]
                                    values["base_color"] = linear_rgba(color)
                            if name == "apple" and (self.applied[idx] is not None or choice != "original"):
                                if choice not in self.apple_pixels:
                                    self.apple_pixels[choice], _ = recolor_apple(
                                        Image.fromarray(self.apple_pixels["original"]),
                                        recipe["color"], recipe.get("include_yellow_skin", False),
                                        recipe.get("match_target_value", False)
                                    )
                                # Keep the bound Vulkan texture descriptor stable across partial resets.
                                material.base_color_texture.upload(self.apple_pixels[choice])
                            for key, value in values.items():
                                setattr(material, key, value)
                self.applied[idx] = scheme
            previous = self.records[idx]
            self.records[idx] = {
                "env_idx": idx, "scheme_id": scheme, "catalog_version": self.catalog["version"],
                "episode_index": 1 if previous is None else previous["episode_index"] + 1,
            }
