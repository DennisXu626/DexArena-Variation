"""Appearance-only bindings for the five approved Meal Preparation objects."""
import json
from pathlib import Path

import numpy as np
import sapien
from PIL import Image

from .appearance_textures import bake_texture

CATALOG = Path(__file__).resolve().parents[1] / "assets/variation/meal_preparation/v1/catalog.json"
CHANNELS = ("emission", "base_color", "specular", "roughness", "metallic",
            "transmission", "ior", "transmission_roughness")
TEXTURES = ("base_color_texture", "emission_texture", "metallic_texture",
            "normal_texture", "roughness_texture", "transmission_texture")
TEXTURED_ROLES = {"plate_top", "plate_bottom", "wire_140088225", "Material.052"}
MODELS = {
    "pizza_plate": ("plate_0", {"model_normalized_0.obj": "plate_top",
                               "model_normalized_1.obj": "plate_bottom"}),
    "spoon": ("spoon_16", {"model_normalized_0.obj": "wire_140088225"}),
    "bread": ("bagel_5", {"model_normalized_0.obj": "Material.052"}),
    "round_ball_food": ("tomato_2", {"model_normalized_3.obj": "default.012"}),
}


def linear_rgba(color):
    values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055)**2.4 for v in values] + [1.]


class MealAppearance:
    def __init__(self, config, num_envs):
        self.config = dict(config)
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.num_envs = num_envs
        seed = int(config.get("seed", 0))
        self.rng = [np.random.default_rng(np.random.SeedSequence([seed, idx]))
                    for idx in range(num_envs)]
        self.records = [None] * num_envs
        self.texture_pixels = {}
        self.begin_scene()

    def begin_scene(self):
        self.bindings = [{} for _ in range(self.num_envs)]
        self.applied = [None] * self.num_envs

    def bind_box(self, base, lid, scene_idx, materials):
        roles = {id(material): role for role, material in materials.items()}
        for builder in (base, lid):
            slots = [(i, roles[id(r.material)], None)
                     for i, r in enumerate(builder.visual_records) if id(r.material) in roles]
            self._bind_builder(builder, "box", slots, [scene_idx])

    def bind_mjcf(self, builder, name, asset_info):
        model, mapping = MODELS[name]
        asset_dir = Path(asset_info["asset_dir"])
        if asset_dir.name != model or "mjcf_path" not in asset_info:
            raise ValueError(f"Meal appearance requires the approved MJCF model {model}")
        slots = []
        for i, record in enumerate(builder.visual_records):
            if record.type == "file":
                role = mapping.get(Path(record.filename).name)
                if role is not None:
                    slots.append((i, role, asset_dir))
            elif name == "spoon" and record.type == "capsule":
                slots.append((i, "grip", asset_dir))
        expected = set(mapping.values()) | ({"grip"} if name == "spoon" else set())
        if {role for _, role, _ in slots} != expected:
            raise ValueError(f"Unexpected visual bindings for {model}")
        self._bind_builder(builder, name, slots, range(self.num_envs))

    def _bind_builder(self, builder, name, slots, scene_indices):
        original_build = builder.build_render_component
        originals = [(i, role, root, builder.visual_records[i].material) for i, role, root in slots]
        indices = iter(scene_indices)

        def build_private():
            env_idx = int(next(indices))
            try:
                for i, role, _, material in originals:
                    private = sapien.render.RenderMaterial(
                        **{key: getattr(material, key) for key in CHANNELS}
                    )
                    for key in TEXTURES:
                        setattr(private, key, getattr(material, key))
                    source = material.base_color_texture
                    if role in TEXTURED_ROLES and source is not None:
                        pixels = self._original_pixels(source)
                        private.base_color_texture = sapien.render.RenderTexture2D(
                            pixels, "R8G8B8A8Unorm", srgb=source.is_srgb
                        )
                    builder.visual_records[i].material = private
                component = original_build()
            finally:
                for i, role, _, material in originals:
                    builder.visual_records[i].material = material
            group = self.bindings[env_idx].setdefault(name, {})
            for i, role, root, original in originals:
                targets = group.setdefault(role, [])
                shape = component.render_shapes[i]
                if role == "grip" and not isinstance(shape, sapien.render.RenderShapeCapsule):
                    raise TypeError(f"Spoon grip bound to {type(shape).__name__}")
                materials = ([shape.material] if isinstance(shape, sapien.render.RenderShapePrimitive)
                             else [part.material for part in shape.parts])
                for material in materials:
                    baseline = {key: getattr(material, key)
                                for key in ("base_color", "roughness", "metallic")}
                    source = original.base_color_texture if role in TEXTURED_ROLES else None
                    if source is not None:
                        baseline["pixels"] = self._original_pixels(source)
                        baseline["texture"] = material.base_color_texture
                        baseline["texture_name"] = "original"
                    targets.append((material, baseline, root))
            return component

        builder.build_render_component = build_private

    def _original_pixels(self, texture):
        key = ("original", texture.filename)
        if key not in self.texture_pixels:
            pixels = texture.download()
            if pixels.shape[-1] == 3:
                alpha = np.full((*pixels.shape[:2], 1), 255, dtype=np.uint8)
                pixels = np.concatenate((pixels, alpha), axis=-1)
            if pixels.dtype != np.uint8 or pixels.shape[-1] != 4:
                raise ValueError(f"Expected an 8-bit Meal color texture: {texture.filename}")
            self.texture_pixels[key] = np.ascontiguousarray(pixels)
        return self.texture_pixels[key]

    def _update_texture(self, baseline, root, name):
        if name == baseline["texture_name"]:
            return
        original = baseline["pixels"]
        height, width = original.shape[:2]
        if name == "original":
            pixels = original
        else:
            key = (root, name, (height, width))
            if key not in self.texture_pixels:
                if name.startswith("solid:"):
                    color = name.split(":", 1)[1]
                    rgba = [int(color[i:i + 2], 16) for i in (1, 3, 5)] + [255]
                    pixels = np.empty_like(original)
                    pixels[:] = rgba
                else:
                    baked = Image.fromarray(bake_texture(root, name), "RGBA")
                    pixels = np.asarray(baked.resize((width, height), Image.Resampling.LANCZOS))
                self.texture_pixels[key] = np.ascontiguousarray(pixels)
            pixels = self.texture_pixels[key]
        # Keep the descriptor bound to the same private texture in SAPIEN 3.0.
        baseline["texture"].upload(pixels)
        baseline["texture_name"] = name

    def _choose(self, env_idx, override):
        per_env = str(env_idx)
        request = {**self.config, **self.config.get("per_env", {}).get(per_env, {}),
                   **override, **override.get("per_env", {}).get(per_env, {})}
        mode = request.get("mode", "explicit")
        if mode == "explicit":
            return request.get("scheme_id", "original")
        if mode != "random_choice":
            raise ValueError(f"Unsupported Meal appearance mode: {mode}")
        choices = request.get("scheme_ids", ())
        if not choices or any(x not in self.catalog["schemes"] for x in choices):
            raise ValueError("scheme_ids must list known Meal appearance schemes")
        return str(self.rng[env_idx].choice(choices))

    def finish_reset(self, env_idx, options):
        override = options.get("meal_appearance", {})
        requests = [(idx, self._choose(idx, override)) for idx in env_idx.tolist()]
        for _, scheme in requests:
            if scheme not in self.catalog["schemes"]:
                raise ValueError(f"Unknown Meal appearance scheme: {scheme}")
        for idx, scheme in requests:
            if self.applied[idx] != scheme:
                definition = self.catalog["schemes"][scheme]
                for actor_name, group in self.bindings[idx].items():
                    for role, targets in group.items():
                        config = definition.get(actor_name, {}).get(role)
                        for material, baseline, root in targets:
                            params = {key: baseline[key] for key in ("base_color", "roughness", "metallic")}
                            if config is not None:
                                params.update(base_color=linear_rgba(config["color"]),
                                              roughness=config["roughness"], metallic=config["metallic"])
                            if "texture" in baseline:
                                texture_name = ("original" if config is None else
                                        config.get("texture", "solid:" + config["color"]))
                                if config is not None:
                                    params["base_color"] = [1.0, 1.0, 1.0, 1.0]
                                self._update_texture(baseline, root, texture_name)
                            elif config is not None:
                                # Clear the renderer's fallback texture on pure-color parts.
                                material.base_color_texture = None
                            for key, value in params.items():
                                setattr(material, key, value)
                self.applied[idx] = scheme
            previous = self.records[idx]
            self.records[idx] = {"env_idx": idx, "scheme_id": scheme,
                                 "episode_index": 1 if previous is None else previous["episode_index"] + 1,
                                 "catalog_version": self.catalog["version"]}

