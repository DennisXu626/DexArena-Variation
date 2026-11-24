"""Index new Furniture scheme readbacks and images from real Linux CUDA captures."""

import argparse
import importlib.util
from pathlib import Path, PurePosixPath
import shutil
import subprocess

import compact_furniture_runtime as evidence


ROOT = evidence.ROOT
CAMERA = "base_camera"
CAPTURE_PATH = "original ManiSkill RGB cameras"
OBJECT_NAMES = {
    "drawer_panel": "flat_panel", "panel_rack": "panel_rack",
    "rail_body": "rail", "screw_head": "screw",
}


def load_appearance():
    # Import the material contract directly; do not register tasks or load SAPIEN.
    spec = importlib.util.spec_from_file_location(
        "furniture_material_contract", ROOT / "tasks/furniture_assembly/appearance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def slot_map(rows):
    slots = {(r["entity"], r["shape"], r["part"]): r["material"] for r in rows}
    evidence.require(len(slots) == len(rows), "Duplicate measured material slot")
    return slots


def material_readback(module, catalog, task, scheme, original, candidate):
    import numpy as np

    baseline, actual = slot_map(original), slot_map(candidate)
    evidence.require(baseline.keys() == actual.keys(), f"{task}/{scheme}: render slots differ")
    targets = catalog.catalog["tasks"][task]
    expected = {obj: catalog.scheme_parameters(obj, scheme) for obj in targets}
    readback = {obj: {role: [] for role in roles} for obj, roles in expected.items()}
    for slot, native in baseline.items():
        observed = actual[slot]
        evidence.require(native.keys() == observed.keys(), f"{slot}: render material fields differ")
        name = slot[0].split("_", 1)[1] if slot[0].startswith("scene-") else slot[0]
        obj = OBJECT_NAMES.get(name)
        params = native
        if obj in targets:
            kind = obj
            if kind == "screw":
                kind = "insert_screw" if task == "InsertRail" else "wing_screw"
            # Match the native material signature used by FurnitureAppearance.bind.
            signature = [native["roughness"], native["metallic"]]
            roles = [role for role, values in module.ROLES[kind].items()
                     if np.allclose(signature, values, rtol=0, atol=2e-6)]
            evidence.require(len(roles) == 1, f"{slot}: no unique native role")
            role = roles[0]
            if role in expected[obj]:
                params = {**native, **expected[obj][role]}
                readback[obj][role].append({key: observed[key] for key in module.FIELDS})
        for key in module.FIELDS:
            evidence.require(np.allclose(observed[key], params[key], rtol=0, atol=1e-7),
                             f"{task}/{scheme}/{slot}: wrong actual {key}")
        evidence.require(all(observed[key] == value for key, value in native.items()
                             if key not in module.FIELDS), f"{slot}: protected material field differed")
    for obj, roles in readback.items():
        expected_counts = catalog._expected_counts(obj, task, detail=True)
        for role, values in roles.items():
            evidence.require(len(values) == expected_counts[role], f"{obj}/{role}: incomplete slot readback")
            roles[role] = {"slots": len(values), "actual": values[0],
                           "catalog": expected[obj][role]}
    return {obj: {"scheme_id": catalog.catalog["objects"][obj]["scheme_map"][scheme],
                  "editable_roles": roles} for obj, roles in readback.items()}


def image_row(task, scheme, env, directory, checks, module, catalog):
    import numpy as np
    from PIL import Image

    measured = checks[scheme]
    records = [record for record in measured["records"] if record["env_idx"] == env]
    evidence.require(bool(records) and all(
        rec["scheme_id"] == scheme and rec["catalog_version"] == catalog.catalog["version"]
        and rec["episode_index"] == index for index, rec in enumerate(records, 1)
    ), f"{task}/{scheme}/env{env}: recorded scheme or catalog differs")
    objects = material_readback(module, catalog, task, scheme, checks["original"]["materials"][env],
                                measured["materials"][env])
    original = directory / f"original_{CAMERA}_env{env}.png"
    source = directory / f"{scheme}_{CAMERA}_env{env}.png"
    with Image.open(source) as image, Image.open(original) as reference:
        evidence.require(image.mode == reference.mode == "RGB" and image.size == reference.size,
                         f"{task}/{scheme}/env{env}: expected original camera RGB and resolution")
        frame, native = np.asarray(image).astype(np.int16), np.asarray(reference).astype(np.int16)
    difference = np.abs(frame - native)
    changed = int(np.count_nonzero(np.any(difference, axis=2)))
    evidence.require(changed > 0, f"{task}/{scheme}/env{env}: {CAMERA} did not show candidate")
    color_meta = catalog.catalogs["screw"]["schemes"][
        catalog.catalog["objects"]["screw"]["scheme_map"][scheme]]
    return {"task": task, "env_idx": env, "requested_id": scheme,
            "recorded_id": records[-1]["scheme_id"], "episode_record": records[-1], "objects": objects,
            "palette_reference": color_meta["label"].removesuffix("_head"),
            "camera": CAMERA, "png": f"{task}/{source.name}", "sha256": evidence.sha(source),
            "original_png": f"{task}/{original.name}", "original_sha256": evidence.sha(original),
            "changed_pixels": changed,
            "max_absolute_rgb_error": int(difference.max())}, source


def checker_scope(manifest, results, catalog, commit, source_hashes):
    expected = {
        "platform": "Linux", "sim_backend": "physx_cuda", "num_envs": 2,
        "capture_path": CAPTURE_PATH, "test_mode": "standard",
        "experimental_windows_cuda": False, "gpu_bootstrap": "native default",
        "git_commit": commit, "catalog_version": catalog["version"],
        "schemes": list(evidence.SCHEMES),
    }
    for key, value in expected.items():
        evidence.require(manifest.get(key) == value, f"Not a frozen Linux standard capture: {key}")
    evidence.require("--diagnostic-native-readback" not in manifest["command"]
                     and "--experimental-windows-cuda" not in manifest["command"],
                     "Diagnostic or Windows command is not Linux acceptance")
    evidence.require(results["status"] == results["formal_acceptance"] == "passed"
                     and results["test_mode"] == "standard" and results["source_hashes_unchanged"]
                     and results["control_steps"] == 2 * len(results["tasks"])
                     and results["physics_steps"] == 40 * len(results["tasks"]),
                     "Incomplete CUDA capture or original control/physics coverage differs")
    evidence.require(set(manifest["files"]) == source_hashes, "Capture source closure differs")
    evidence.files_lf_identity(manifest["files"])


def linux_sdk_identity(run, manifest, artifact_path, artifact, lock):
    sdk = evidence.read(run / "private_sdk.json")
    evidence.require(sdk["schema"] == "dexarena-sapien-linux-runtime-v1" and sdk["status"] == "passed"
                     and sdk["platform"] == "Linux" and sdk["private_sdk"] is True
                     and sdk["execution"] == "standard_cuda" and sdk["returncode"] == 0
                     and sdk["indexed_gpu_apply_patch_version"] == 1,
                     "Missing successful Linux native-capability run receipt")
    for name in ("manifest", "results"):
        evidence.require(sdk.get(name + "_sha256") == evidence.sha(run / (name + ".json")),
                         f"Launcher receipt does not match the captured {name}")
    evidence.require(sdk["artifact_sha256"] == evidence.sha(artifact_path)
                     and sdk["wheel_sha256"] == artifact["wheel_sha256"]
                     and sdk["version"] == artifact["version"] == lock["version"] == manifest["versions"]["sapien"]
                     and sdk["physx_version"] == lock["physx_gpu"]["version"] == manifest["physx_version"],
                     "SDK receipt differs from the locked, staged artifact")
    evidence.digest_map({"artifact": sdk["artifact_sha256"], "wheel": sdk["wheel_sha256"]},
                        "Linux SDK artifact identity")
    evidence.require(sdk["binaries_unchanged"] is True and sdk["before"] == sdk["after"]
                     and sdk["python_source_unchanged"] is True and sdk["python_before"] == sdk["python_after"],
                     "Linux SDK changed during task capture")
    inventory = sdk["wheel_native_files"]
    evidence.digest_map(inventory, "staged wheel ELF files")
    binding = artifact["native_binding"]
    required = {binding, "sapien.libs/libsapien.so", "sapien.libs/libsvulkan2.so"}
    evidence.require(inventory == artifact["native_files"] and required <= inventory.keys(),
                     "The staged wheel must contain the locked binding, core and renderer")
    required_keys = {"wheel/" + name for name in required}
    loaded = sdk["before"]
    evidence.require(required_keys <= loaded.keys(), "Native binding, core or renderer is not mapped")
    runtime = PurePosixPath(loaded["wheel/" + binding]["path"])
    for _ in PurePosixPath(binding).parts:
        runtime = runtime.parent

    def verify_wheel_row(name, row):
        relative = name.removeprefix("wheel/")
        path = PurePosixPath(row["path"])
        evidence.require(name.startswith("wheel/") and path.is_absolute()
                         and path == runtime / relative and inventory.get(relative) == row["sha256"],
                         f"Loaded SDK ELF file does not match the staged wheel: {relative}")

    native = {}
    for name, row in loaded.items():
        path = PurePosixPath(row["path"])
        evidence.require(path.is_absolute(), "Loaded ELF path is not absolute")
        if name.startswith("wheel/"):
            verify_wheel_row(name, row)
        native[name] = row["sha256"]
    for phase in ("loaded_wheel_before", "loaded_wheel_after"):
        rows = sdk[phase]
        evidence.require(required_keys <= rows.keys() and all(rows[name] == loaded[name] for name in required_keys),
                         f"Actual loaded binding, core or renderer identity differs: {phase}")
        for name, row in rows.items():
            verify_wheel_row(name, row)
    loader = sdk["vulkan_loader"]
    path = PurePosixPath(loader["path"])
    evidence.require(path.is_absolute() and (path.name == "libvulkan.so" or path.name.startswith("libvulkan.so.")),
                     "No loaded Linux Vulkan renderer identified")
    observation = sdk.get("vulkan_observation") or {}
    evidence.require(observation.get("phase") == "validated_rgb"
                     and type(observation.get("samples")) is int and observation["samples"] > 0,
                     "No live Vulkan observation at a validated RGB readback")
    sdk_dir = ROOT / "tools/variation/sapien_sdk"
    observer_sources = {"launcher_sha256": sdk_dir / "run_linux_check.py",
                        "render_observer_sha256": sdk_dir / "linux_render_receipt.py"}
    evidence.require(all(sdk.get(key) == evidence.sha(file) for key, file in observer_sources.items()),
                     "Vulkan observation source does not match the checkout")
    native["vulkan/libvulkan.so.1"] = loader["sha256"]
    evidence.digest_map(native, "loaded Linux SDK binaries")
    candidates = [name for name in native if name.startswith("wheel/sapien/pysapien")
                  and name.endswith(".so")]
    evidence.require(candidates == ["wheel/" + artifact["native_binding"]]
                     and "driver/libcuda.so.1" in native
                     and native.get("physx/" + lock["physx_gpu"]["file"]) == lock["physx_gpu"]["sha256"],
                     "Missing loaded Python binding, NVIDIA driver, or pinned PhysX GPU library")
    python = {name: row["sha256"] if isinstance(row, dict) else row
              for name, row in sdk["python_before"].items()}
    evidence.digest_map(python, "Linux SDK Python files")
    assets = sdk["wheel_assets_before"]
    evidence.require(sdk["wheel_assets_unchanged"] is True and assets == sdk["wheel_assets_after"],
                     "Packaged wheel assets changed during task capture")
    evidence.digest_map(assets, "packaged wheel assets")
    identity = {key: sdk[key] for key in ("version", "physx_version", "artifact_sha256", "wheel_sha256",
                                         "indexed_gpu_apply_patch_version")}
    identity.update({"native_sha256": native, "python_sha256": python,
                     "wheel_assets_sha256": evidence.canonical_sha(assets)})
    return {"identity": identity, "receipt": {"private_sdk_sha256": evidence.sha(run / "private_sdk.json"),
                                              "vulkan_observation": observation,
                                              **{key: sdk[key] for key in observer_sources}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True,
                        help="Raw Linux launcher output; repeat for one job per task")
    parser.add_argument("--artifact", type=Path, required=True, help="Exact staged Linux SDK receipt")
    parser.add_argument("--output", type=Path, required=True, help="Fresh directory for verified evidence")
    args = parser.parse_args()
    evidence.require(not args.output.exists(), "Choose a new output directory")

    artifact = evidence.read(args.artifact)
    lock_path = ROOT / "tools/variation/sapien_sdk/lock_linux.json"
    lock = evidence.read(lock_path)
    base_lock_path = lock_path.with_name("lock.json")
    base_lock = evidence.read(base_lock_path)
    locked_patches = [{key: row[key] for key in ("file", "sha256")}
                      for row in base_lock["patches"] if row["group"] in lock["patch_groups"]]
    evidence.require(artifact["schema"] == "dexarena-sapien-linux-artifact-v1"
                     and artifact["source_commit"] == base_lock["upstream"]["commit"]
                     and artifact["lock_sha256"] == lock["base_lock_sha256"] == evidence.sha(base_lock_path)
                     and artifact["linux_lock_sha256"] == evidence.sha(lock_path)
                     and artifact["recipe_sha256"] == evidence.sha(lock_path.with_name("build_linux.py"))
                     and artifact["patches"] == locked_patches
                     and artifact["indexed_gpu_apply_patch_version"] == 1
                     and artifact["physx_gpu"] == lock["physx_gpu"],
                     "Artifact is not tied to the current locked Linux build inputs")
    for patch in locked_patches:
        evidence.require(evidence.sha(lock_path.parent / patch["file"]) == patch["sha256"],
                         f"Current source patch bytes differ from lock: {patch['file']}")
    module = load_appearance()
    catalog = module.FurnitureAppearance({}, 2)
    schemes = tuple(f"variant_{i}" for i in range(3, 11))
    evidence.require(evidence.SCHEMES[3:] == schemes, "Unexpected added schemes")
    from check_furniture_appearance import ADAPTER, IMPEDANCE, RESET_SCOPE, TASKS
    published_sources = {ADAPTER, IMPEDANCE, RESET_SCOPE, "tools/variation/check_furniture_appearance.py",
                         evidence.CATALOG.relative_to(ROOT).as_posix(), *TASKS.values(),
                         *(v["catalog"] for v in catalog.catalog["objects"].values())}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "diff", "--name-only", commit, "--",
                                     *sorted(published_sources)], cwd=ROOT, text=True)
    evidence.require(not dirty.strip(), "Capture sources do not match the frozen commit")
    output_images, captures, tasks, images = [], [], {}, []
    runtime_identity, source_identity = None, None
    for run in args.run:
        manifest = evidence.read(run / "manifest.json")
        results = evidence.read(run / "results.json")
        checker_scope(manifest, results, catalog.catalog, commit, published_sources)
        sdk = linux_sdk_identity(run, manifest, args.artifact, artifact, lock)
        evidence.require(runtime_identity is None or runtime_identity == sdk["identity"],
                         "Runs use different native SDKs")
        runtime_identity = sdk["identity"]
        evidence.require(source_identity is None or source_identity == manifest["files"],
                         "Runs use different source bytes")
        source_identity = manifest["files"]
        found = []
        for task in results["tasks"]:
            name = task["task"]
            evidence.require(name in TASKS and name not in tasks, f"Unexpected/duplicate task {name}")
            directory = run / name
            tasks[name] = evidence.task_check(directory, task)
            for env in (0, 1):
                original = directory / f"original_{CAMERA}_env{env}.png"
                output_images.append((f"{name}/{original.name}", original, evidence.sha(original)))
            for scheme in schemes:
                for env in (0, 1):
                    row, png = image_row(name, scheme, env, directory, task["checks"], module, catalog)
                    images.append(row)
                    output_images.append((row["png"], png, row["sha256"]))
            found.append(tasks[name]["task_id"])
        evidence.require(manifest["task_ids"] == found, "Requested tasks differ from actual capture")
        captures.append({"tasks": found, "manifest_sha256": evidence.sha(run / "manifest.json"),
                         "results_sha256": evidence.sha(run / "results.json"), **sdk["receipt"]})
    evidence.require(set(tasks) == set(TASKS) and len(images) == 48,
                     "Three tasks and all 48 added-scheme cells are required")

    # The existing raw acceptance verifier also checked the native-only directions.
    # Keep six appearance directions in this index, with original before/after PNGs.
    local_evidence = []
    for run in args.run:
        for task in evidence.read(run / "results.json")["tasks"]:
            name = task["task"]
            for i, row in enumerate(tasks[name]["appearance_local_reset"]):
                checks = task["checks"]
                measured = checks[f"local_reset_{i}"]
                selected, = row["selected"]
                evidence.require(measured["scheme_id"] == "original"
                                 and measured["after_records"][-1]["scheme_id"] == "original"
                                 and measured["after_materials"][selected] ==
                                 checks["original"]["materials"][selected],
                                 f"{name}/{i}: selected environment did not restore native materials")
                frames = {}
                for env in (0, 1):
                    filename = f"local_{i}_{CAMERA}_env{env}.png"
                    path = run / name / filename
                    digest = evidence.sha(path)
                    frames[str(env)] = {"png": f"{name}/{filename}", "sha256": digest}
                    output_images.append((f"{name}/{filename}", path, digest))
                local_evidence.append({"task": name, "selected": row["selected"], "camera": CAMERA,
                                       "frames_before_and_after": frames, "checks": row})
    evidence.require(len(local_evidence) == 6, "Expected six appearance reset directions")

    args.output.mkdir(parents=True, exist_ok=False)
    for relative, source, digest in output_images:
        target = args.output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        evidence.require(evidence.sha(target) == digest, f"PNG changed during export: {relative}")
    evidence.write(args.output / "review.json", {
        "status": "passed", "scope": "Linux standard CUDA, two environments, three Furniture short tasks",
        "head": commit, "sdk": runtime_identity, "captures": captures,
        "linux_lock_sha256": evidence.sha(lock_path),
        "source_sha256": source_identity, "verifier_sha256": evidence.sha(Path(__file__)),
        "shared_verifier_sha256": evidence.sha(Path(evidence.__file__)),
        "added_scheme_cells": images, "appearance_local_resets": local_evidence, "task_checks": tasks,
        "notes": "Role colors are measured material parameters; PNGs are original camera output. "
                 "No task success or policy evaluation was performed.",
    })
    lines = ["# Furniture Assembly: Linux CUDA evidence", "",
             "Original task base-camera images. The role-by-role material readbacks, source identity,",
             "and local reset checks are in [review.json](review.json).", "",
             "| Task | Env | Scheme and recorded ID | Catalog palette reference | Original |",
             "|---|---:|---|---|---|"]
    for row in images:
        lines.append(f"| {row['task']} | {row['env_idx']} | [{row['requested_id']} → "
                     f"{row['recorded_id']}]({row['png']}) | {row['palette_reference']} | "
                     f"[Original]({row['original_png']}) |")
    (args.output / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Verified {len(images)} added-scheme RGB frames and {len(local_evidence)} local reset directions.")


if __name__ == "__main__":
    main()
