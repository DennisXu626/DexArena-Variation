"""Negative tests for the standalone Linux Furniture evidence gate."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/variation"))
import review_furniture_linux_capture as audit


class FurnitureLinuxEvidenceTests(unittest.TestCase):
    def test_diagnostic_or_windows_receipt_cannot_claim_linux_acceptance(self):
        for invalid in ({"platform": "Windows"}, {"platform": "Linux", "test_mode": "diagnostic"}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "Linux standard capture"):
                audit.checker_scope(invalid, {}, {"version": "fixture"}, "fixture", set())

    def test_catalog_material_readback_rejects_different_scheme_or_protected_color(self):
        module = audit.load_appearance()
        catalog = module.FurnitureAppearance({}, 2)
        task, scheme = "LayFlatPanel", "variant_4"
        original, current = [], []
        protected = None
        for entity, obj in (("scene-0_drawer_panel", "flat_panel"), ("scene-0_panel_rack", "panel_rack")):
            params = catalog.scheme_parameters(obj, scheme)
            for role, count in catalog._expected_counts(obj, task, detail=True).items():
                rough, metal = module.ROLES[obj][role]
                for _ in range(count):
                    shape = len(original)
                    material = {"base_color": [0.12, 0.24, 0.36, 1.0], "roughness": rough,
                                "metallic": metal, "base_color_texture": None}
                    slot = {"entity": entity, "shape": shape, "part": 0, "material": material}
                    original.append(slot)
                    current.append({**slot, "material": {**material, **params.get(role, {})}})
                    if role == "ink":
                        protected = shape
        checked = audit.material_readback(module, catalog, task, scheme, original, current)
        self.assertEqual(checked["flat_panel"]["editable_roles"]["face"]["actual"]["base_color"],
                         [0.94, 0.29, 0.022, 1.0])
        with self.assertRaisesRegex(ValueError, "wrong actual"):
            audit.material_readback(module, catalog, task, "variant_8", original, current)
        current[protected]["material"]["base_color"] = [1.0, 0.0, 0.0, 1.0]
        with self.assertRaisesRegex(ValueError, "wrong actual"):
            audit.material_readback(module, catalog, task, scheme, original, current)

    def test_run_receipt_is_bound_to_outputs_and_required_loaded_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            version, physx = "3.0.3+dexarena.gpu1.linux1", "105.1-physx-5.3.1.patch0"
            binding = "sapien/pysapien.cpython-310-x86_64-linux-gnu.so"
            core, renderer = "sapien.libs/libsapien.so", "sapien.libs/libsvulkan2.so"
            inventory = {binding: "c" * 64, core: "2" * 64, renderer: "3" * 64}
            artifact = {"version": version, "wheel_sha256": "a" * 64,
                        "native_files": inventory, "native_binding": binding}
            artifact_path = run / "artifact.json"
            audit.evidence.write(artifact_path, artifact)
            manifest = {"versions": {"sapien": version}, "physx_version": physx}
            audit.evidence.write(run / "manifest.json", manifest)
            audit.evidence.write(run / "results.json", {"status": "fixture"})
            lock = {"version": version, "physx_gpu": {
                "file": "libPhysXGpu_64.so", "version": physx, "sha256": "b" * 64}}
            physx_file = f"physx/{lock['physx_gpu']['file']}"
            mapped = {f"wheel/{path}": {"path": f"/private/{path}", "sha256": sha}
                      for path, sha in inventory.items()}
            rows = {
                **mapped,
                physx_file: {"path": "/private/libPhysXGpu_64.so", "sha256": "b" * 64},
                "driver/libcuda.so.1": {"path": "/nvidia/libcuda.so.1", "sha256": "d" * 64},
            }
            receipt = {
                "schema": "dexarena-sapien-linux-runtime-v1", "platform": "Linux",
                "status": "passed", "private_sdk": True, "execution": "standard_cuda", "returncode": 0,
                "indexed_gpu_apply_patch_version": 1,
                "artifact_sha256": audit.evidence.sha(artifact_path), "wheel_sha256": "a" * 64,
                "version": version, "physx_version": physx, "binaries_unchanged": True,
                "wheel_native_files": inventory,
                "loaded_wheel_before": mapped, "loaded_wheel_after": mapped,
                "vulkan_loader": {"path": "/usr/lib/libvulkan.so.1.3.239", "sha256": "f" * 64},
                "vulkan_observation": {"phase": "validated_rgb", "samples": 1},
                "launcher_sha256": audit.evidence.sha(audit.ROOT / "tools/variation/sapien_sdk/run_linux_check.py"),
                "render_observer_sha256": audit.evidence.sha(audit.ROOT / "tools/variation/sapien_sdk/linux_render_receipt.py"),
                "before": rows, "after": rows, "python_source_unchanged": True,
                "python_before": {"sapien/__init__.py": "e" * 64},
                "python_after": {"sapien/__init__.py": "e" * 64},
                "wheel_assets_before": {"sapien/shaders/example.spv": "9" * 64},
                "wheel_assets_after": {"sapien/shaders/example.spv": "9" * 64},
                "wheel_assets_unchanged": True,
                "manifest_sha256": audit.evidence.sha(run / "manifest.json"),
                "results_sha256": audit.evidence.sha(run / "results.json"),
            }
            audit.evidence.write(run / "private_sdk.json", receipt)
            self.assertEqual(audit.linux_sdk_identity(run, manifest, artifact_path, artifact,
                                                      lock)["identity"]["version"], version)
            with self.subTest("capability only"), self.assertRaisesRegex(ValueError, "successful Linux"):
                audit.evidence.write(run / "private_sdk.json", {**receipt, "execution": "capability_probe"})
                audit.linux_sdk_identity(run, manifest, artifact_path, artifact, lock)
            with self.subTest("teardown mapping alone"), self.assertRaisesRegex(ValueError, "live Vulkan"):
                audit.evidence.write(run / "private_sdk.json", {**receipt, "vulkan_observation": None})
                audit.linux_sdk_identity(run, manifest, artifact_path, artifact, lock)
            with self.subTest("wrong physically loaded runtime"), self.assertRaisesRegex(ValueError, "pinned PhysX"):
                mismatch = copy.deepcopy(rows)
                mismatch[physx_file]["sha256"] = "f" * 64
                audit.evidence.write(run / "private_sdk.json", {**receipt, "before": mismatch, "after": mismatch})
                audit.linux_sdk_identity(run, manifest, artifact_path, artifact, lock)
            with self.subTest("staged core absent"), self.assertRaisesRegex(ValueError, "staged wheel must"):
                short = {name: sha for name, sha in inventory.items() if name != core}
                changed_artifact = {**artifact, "native_files": short}
                audit.evidence.write(artifact_path, changed_artifact)
                changed_receipt = {**receipt, "wheel_native_files": short,
                                   "artifact_sha256": audit.evidence.sha(artifact_path)}
                audit.evidence.write(run / "private_sdk.json", changed_receipt)
                audit.linux_sdk_identity(run, manifest, artifact_path, changed_artifact, lock)
            audit.evidence.write(artifact_path, artifact)
            with self.subTest("mapped renderer absent at end"), self.assertRaisesRegex(ValueError, "loaded.*renderer"):
                short = {name: row for name, row in mapped.items() if name != f"wheel/{renderer}"}
                audit.evidence.write(run / "private_sdk.json", {**receipt, "loaded_wheel_after": short})
                audit.linux_sdk_identity(run, manifest, artifact_path, artifact, lock)
            with self.subTest("changed packaged assets"), self.assertRaisesRegex(ValueError, "wheel assets changed"):
                audit.evidence.write(run / "private_sdk.json", {**receipt, "wheel_assets_after": {}})
                audit.linux_sdk_identity(run, manifest, artifact_path, artifact, lock)
            with self.subTest("transplanted results"), self.assertRaisesRegex(ValueError, "captured results"):
                audit.evidence.write(run / "results.json", {"status": "other run"})
                audit.evidence.write(run / "private_sdk.json", receipt)
                audit.linux_sdk_identity(run, manifest, artifact_path, artifact, lock)


if __name__ == "__main__":
    unittest.main()
