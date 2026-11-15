"""Small Cabinet pilot adapter: appearance and selected tabletop poses.

It is constructed only when one feature is enabled. Native task physics,
robot reset and stage writers remain owned by the original task classes.
"""
import copy
import json
from pathlib import Path

import numpy as np
import torch

REGION = {
    "id": "cabinet_pouring.bottle_table.v1", "frame": "env_world",
    "center_xy_m": [-0.22, -0.20], "radius_m": 0.15,
    "table_top_z_m": 0.0, "fit": "entire_bottom_support_ring",
}
TABLE_XY_REGION = {
    "id": "cabinet_pouring.bottle_table.xy_v2", "frame": "env_world",
    "center_xy_m": [-0.25, -0.35], "radius_m": 0.16,
    "table_top_z_m": 0.0, "fit": "entire_bottom_support_ring",
}
ASSETS = Path(__file__).resolve().parents[1] / "assets/variation/cabinet_pouring/v1"


class PilotVariation:
    def __init__(self, env, config, num_envs):
        self.env = env
        self.config = copy.deepcopy(config)
        self.appearance = bool(config.get("appearance", {}).get("enabled", False))
        self.initial_pose = bool(config.get("initial_pose", {}).get("enabled", False))
        if type(env).__name__ not in {"CabinetPouringPickBottleEnv", "CabinetPouringUnscrewCapEnv"}:
            raise ValueError("This pilot variation supports only PickBottle and UnscrewCap")
        self.region = REGION
        if self.initial_pose:
            # One run-level selection feeds both stages, including their
            # native target marker, observation and placement predicate.
            requested = config.get("initial_pose", {}).get("region_id", REGION["id"])
            if requested == TABLE_XY_REGION["id"]:
                self.region = TABLE_XY_REGION
            elif requested != REGION["id"]:
                raise ValueError(f"Unknown tabletop bottle region: {requested}")
            env.place_center_xy = tuple(self.region["center_xy_m"])
            env.place_radius = self.region["radius_m"]
        seed = int(config.get("seed", 0))
        # Separate streams per feature and actual environment; never consume
        # the task's global Torch RNG for appearance or explicit sampling.
        self.rng = {feature: [np.random.default_rng(np.random.SeedSequence([seed, feature, i]))
                             for i in range(num_envs)] for feature in [0, 1]}
        self.schemes = ["original"] * num_envs
        self.episodes = [0] * num_envs
        self.records = []
        self._binding_key = None
        self._textures = {}
        if self.appearance:
            self.catalog = json.loads((ASSETS / "catalog.json").read_text())

    def request(self, feature, env_idx, options):
        request = dict(self.config.get(feature, {}))
        request.update(self.config.get("per_env", {}).get(str(env_idx), {}).get(feature, {}))
        override = options.get("variation", {})
        request.update(override.get(feature, {}))
        request.update(override.get("per_env", {}).get(str(env_idx), {}).get(feature, {}))
        if (feature == "initial_pose" and self.initial_pose
                and request.get("region_id", self.region["id"]) != self.region["id"]):
            error = "region_id is run-level; reset/per_env cannot switch the selected region"
            self._record(env_idx, options, status="rejected", error=error, pose=None)
            raise ValueError(f"initial_pose env {env_idx}: {error}")
        return request

    def preload_textures(self):
        """Create the finite pool before the native batched renderer freezes it."""
        import sapien.render as sr
        for scheme in self.catalog["schemes"].values():
            if "label_texture" in scheme:
                path = str(ASSETS / scheme["label_texture"])
                if path not in self._textures:
                    self._textures[path] = sr.RenderTexture2D(filename=path, mipmap_levels=4)

    @staticmethod
    def isolate_builder_materials(builder):
        """Give each native per-env build fresh mutable material instances.

        The native builder still creates the exact same shapes and physics.
        Only explicitly supplied materials (the cap's existing box markers)
        need this hook; file-loaded mesh materials are already private.
        """
        import sapien.render as sr
        original_build = builder.build_render_component
        records = [(record, record.material) for record in builder.visual_records
                   if record.material is not None]
        if not records:
            return

        def build_private_materials():
            for record, original in records:
                material = sr.RenderMaterial()
                for key in ["base_color", "base_color_texture", "roughness", "roughness_texture",
                            "metallic", "metallic_texture", "normal_texture", "emission", "emission_texture",
                            "specular", "transmission", "transmission_texture", "transmission_roughness", "ior"]:
                    setattr(material, key, getattr(original, key))
                record.material = material
            return original_build()

        builder.build_render_component = build_private_materials

    def bottle_xyz(self, env_idx, options):
        """Resolve before native cap/particle placement and the final A->B swap."""
        e = self.env
        # Delegation intentionally keeps native Torch draws for mode=native.
        requests = [self.request("initial_pose", int(i), options) for i in env_idx.tolist()]
        if all(r.get("mode", "native") == "native" for r in requests):
            return e._placed_bottle_xyz(len(env_idx))
        xyz = torch.zeros((len(env_idx), 3), dtype=torch.float32, device=e.device)
        radius = self.region["radius_m"] - e._source_bottom_support_radius
        z = -e.source_z_lo + 0.001  # Original reset clearance, not success height.
        for row, (i, request) in enumerate(zip(env_idx.tolist(), requests)):
            mode = request.get("mode", "native")
            try:
                q = np.asarray(request.get("quaternion_wxyz", [1, 0, 0, 0]), dtype=float)
                if q.shape != (4,) or not np.array_equal(q, [1, 0, 0, 0]):
                    raise ValueError("Original initialization orientation is identity wxyz only")
                if mode == "fixed":
                    xy = np.asarray(request["xy_m"], dtype=float)
                elif mode == "region":
                    theta = self.rng[1][i].uniform(0, 2 * np.pi)
                    r = radius * np.sqrt(self.rng[1][i].uniform())
                    xy = np.asarray(self.region["center_xy_m"]) + r * np.array([np.cos(theta), np.sin(theta)])
                elif mode == "native":
                    xyz[row] = e._placed_bottle_xyz(1)[0]
                    continue
                else:
                    raise ValueError(f"Unsupported initial_pose mode: {mode}")
                if xy.shape != (2,) or not np.isfinite(xy).all():
                    raise ValueError("xy_m must contain two finite meter values")
                if np.linalg.norm(xy - self.region["center_xy_m"]) > radius + 1e-9:
                    raise ValueError(f"Bottle bottom support ring exceeds selected region {self.region['id']}")
                requested_z = float(request.get("z_m", z))
                if not np.isfinite(requested_z) or abs(requested_z - z) > 1e-7:
                    raise ValueError("z_m must preserve the original 1mm reset clearance")
                xyz[row] = torch.tensor([*xy, z], device=e.device)
            except (ValueError, KeyError) as exc:
                self._record(i, options, status="rejected", error=str(exc), pose=None)
                raise ValueError(f"initial_pose env {i}: {exc}") from exc
        return xyz

    def _collect_bindings(self):
        import sapien.render as sr
        names = ["source", "source_fixed", "source_open", "cap", "cap_fixed", "cap_twin"]
        objects = tuple(raw for name in names for raw in getattr(self.env, name)._objs)
        key = tuple(id(raw) for raw in objects)
        if self._binding_key == key:
            return
        self._bindings = [[] for _ in range(self.env.num_envs)]
        owners = {}
        for name in names:
            for i, raw in enumerate(getattr(self.env, name)._objs):
                entity = getattr(raw, "entity", raw)
                body = entity.find_component_by_type(sr.RenderBodyComponent)
                for shape in body.render_shapes:
                    for part_index, part in enumerate(shape.parts):
                        material = part.material
                        # Native loaders already instantiate private materials
                        # per environment. Refuse an unexpected shared owner
                        # instead of mutating another environment's material.
                        previous = owners.setdefault(id(material), i)
                        if previous != i:
                            raise RuntimeError("Native render material is shared across environments")
                        original = {k: getattr(material, k) for k in ["base_color", "base_color_texture", "roughness", "metallic"]}
                        if name.startswith("source"):
                            role = "body_label" if original["base_color_texture"] is not None else "body_surface"
                        else:
                            role = "cap_reference" if isinstance(shape, sr.RenderShapeBox) else "cap_surface"
                        self._bindings[i].append({"name": name, "role": role, "part": part_index,
                                                  "material": material, "original": original})
        self._binding_key = key
        self._bound_objects = objects

    def apply_appearance(self, env_idx, options):
        import sapien.render as sr
        self._collect_bindings()
        for i in env_idx.tolist():
            request = self.request("appearance", i, options)
            mode = request.get("mode", "explicit")
            if mode == "explicit":
                scheme_id = request.get("scheme_id", "original")
            elif mode == "random_choice":
                choices = request.get("scheme_ids", [])
                if not choices or any(c not in self.catalog["schemes"] for c in choices):
                    raise ValueError("scheme_ids must be a nonempty set of available scheme IDs")
                scheme_id = str(self.rng[0][i].choice(choices))
            else:
                raise ValueError(f"Unknown appearance selection mode: {mode}")
            if scheme_id not in self.catalog["schemes"]:
                raise ValueError(f"Unknown appearance scheme: {scheme_id}")
            scheme = self.catalog["schemes"][scheme_id]
            for binding in self._bindings[i]:
                material = binding["material"]
                for k, value in binding["original"].items():
                    setattr(material, k, value)
                if scheme_id == "original":
                    continue
                role = binding["role"]
                if role == "body_label":
                    texture_path = str(ASSETS / scheme["label_texture"])
                    if texture_path not in self._textures:
                        self._textures[texture_path] = sr.RenderTexture2D(filename=texture_path, mipmap_levels=4)
                    material.base_color_texture = self._textures[texture_path]
                    material.base_color = [1, 1, 1, 1]
                else:
                    color_key = {"body_surface": "body_color", "cap_surface": "cap_color", "cap_reference": "reference_color"}[role]
                    material.base_color = scheme[color_key]
                material.roughness = scheme["roughness"]
                material.metallic = scheme["metallic"]
            self.schemes[i] = scheme_id

    def finish_reset(self, env_idx, options):
        if self.initial_pose:
            # PickBottle keeps its native cabinet spawn, so it does not call
            # bottle_xyz. Still reject attempts to switch its target region.
            for i in env_idx.tolist():
                self.request("initial_pose", i, options)
        if self.appearance:
            self.apply_appearance(env_idx, options)
        for i in env_idx.tolist():
            pose = self.env._source_pose().raw_pose[i].detach().cpu().tolist()
            self._record(i, options, status="ok", pose=pose)
            self.episodes[i] += 1

    def _record(self, i, options, status, pose, error=None):
        e = self.env
        record = {"manifest_ref": self.config.get("manifest_ref"),
                  "config_ref": options.get("variation", {}).get("config_ref", self.config.get("config_ref")),
                  "env_idx": i, "episode_index": self.episodes[i],
                  "appearance": self.schemes[i] if self.appearance else "native_disabled",
                  "final_pose_wxyz_m": pose, "region_id": self.region["id"], "status": status}
        if pose is not None:
            record["representation"] = int(e._active_bottle_rep[i])
            record["cap_position_m"] = e._cap_p()[i].detach().cpu().tolist()
        if error is not None:
            record["error"] = error
        self.records.append(record)
        if self.config.get("record_path"):
            with Path(self.config["record_path"]).open("a", encoding="utf-8") as file:
                file.write(json.dumps(record) + "\n")
