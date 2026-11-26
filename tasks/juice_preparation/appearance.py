"""Private render bindings for the reviewed Juice appearance recipes."""
import json
import shutil
import tempfile
from pathlib import Path
import numpy as np
import sapien

CHANNELS = ("base_color","roughness","metallic","specular","emission","transmission","ior","transmission_roughness")
TEXTURES = ("base_color_texture","normal_texture","roughness_texture","metallic_texture","emission_texture","transmission_texture")


class JuiceAppearance:
    def __init__(self, config, n):
        self.config = config
        self.catalog = json.loads((Path(__file__).resolve().parents[1]/"assets/variation/juice_preparation/v1/catalog.json").read_text())
        self.records = [None]*n

    def begin_scene(self):
        self.bindings = [{} for _ in self.records]
        self._private_files = tempfile.TemporaryDirectory(prefix="juice_visuals_")

    def bind_builder(self, builder, scene_indices):
        original = builder.build_render_component
        adapter = self
        indices = iter(scene_indices)
        def build():
            index = int(next(indices))
            previous = []
            original_filenames = []
            fridge_shapes = []
            selected = []
            for i, record in enumerate(builder.visual_records):
                name = Path(getattr(record, "filename", "")).stem.lower()
                if name in ("body_visual", "door_visual", "handle_visual"):
                    path = Path(self._private_files.name) / str(index)
                    path.mkdir(exist_ok=True)
                    destination = path / Path(record.filename).name
                    shutil.copyfile(record.filename, destination)
                    original_filenames.append((record, record.filename))
                    record.filename = str(destination)
                    fridge_shapes.append(i)
                    continue
                role = "blender" if name == "body001" else "lid" if name == "lid" else "apple" if name.startswith("model_normalized") else None
                if role is None:
                    continue
                original_material = record.material
                source = original_material
                if source is None and role == "apple":
                    shape = sapien.render.RenderShapeTriangleMesh(record.filename, scale=record.scale)
                    part, = shape.parts
                    source = part.material
                if source is None:
                    raise RuntimeError(f"No material for {name}")
                private = sapien.render.RenderMaterial(**{k: getattr(source, k) for k in CHANNELS})
                for key in TEXTURES:
                    setattr(private, key, getattr(source, key))
                texture = source.base_color_texture
                pixels = texture.download()
                if pixels.shape[2] == 3:
                    pixels = np.concatenate((pixels, np.full((*pixels.shape[:2], 1), 255, dtype=np.uint8)), axis=2)
                private.base_color_texture = sapien.render.RenderTexture2D(
                    np.ascontiguousarray(pixels), "R8G8B8A8Unorm", srgb=texture.is_srgb)
                previous.append((record, original_material))
                record.material = private
                selected.append((i, role, pixels))
            try:
                component = original()
            finally:
                for record, filename in original_filenames:
                    record.filename = filename
                for record, material in previous:
                    record.material = material
            for i in fridge_shapes:
                for part in component.render_shapes[i].parts:
                    m = part.material
                    if np.allclose(m.base_color, [.89411765,.90980392,.92156863,1], atol=.005):
                        adapter.bindings[index].setdefault("fridge", []).append(
                            (m, (list(m.base_color), m.roughness)))
            for i, role, pixels in selected:
                for part in component.render_shapes[i].parts:
                    adapter.bindings[index].setdefault(role, []).append((part.material, pixels.copy()))
            return component
        builder.build_render_component = build

    def resolve_requests(self, indices, options):
        """Resolve all selected rows before any task or rendering mutation."""
        request = options.get("juice_appearance",{})
        requests = []
        for i in indices:
            r={**self.config,**self.config.get("per_env",{}).get(str(i),{}),
               **request,**request.get("per_env",{}).get(str(i),{})}
            scheme=r.get("scheme_id","original")
            if scheme not in self.catalog["schemes"]:
                raise ValueError(scheme)
            requests.append((i, scheme))
        return requests

    def apply(self, indices, options):
        requests = self.resolve_requests(indices, options)
        for i, _ in requests:
            if not self.bindings[i]:
                raise RuntimeError(f"Incomplete bindings {i}: {list(self.bindings[i])}")
        from .appearance_colors import recolor_shell, recolor_apple
        for i, scheme in requests:
            recipe=self.catalog["schemes"][scheme]
            for role,slots in self.bindings[i].items():
                for material,source in slots:
                    if role == "fridge":
                        from .appearance_colors import linear_rgba
                        material.base_color = linear_rgba(recipe["fridge"]) if recipe else source[0]
                        material.roughness = recipe["fridge_roughness"] if recipe else source[1]
                    else:
                        transform = recolor_apple if role == "apple" else recolor_shell
                        pixels = transform(source.copy(),recipe[role]) if recipe else source
                        material.base_color_texture.upload(np.ascontiguousarray(pixels))
            old=self.records[i]
            self.records[i]={"env_idx":i,"scheme_id":scheme,"catalog_version":self.catalog["version"],
                             "episode_index":old["episode_index"]+1 if old else 1}
