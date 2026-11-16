"""Verify a selected Meal environment restores the native render materials."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image
import sapien
import torch
from check_meal_parallel import CONFIG, TASKS, changed, make, materials, pixels, sample_tree


SCALARS = ("base_color", "emission", "specular", "roughness", "metallic",
           "transmission", "ior", "transmission_roughness")
TEXTURES = ("base_color_texture", "emission_texture", "metallic_texture",
            "normal_texture", "roughness_texture", "transmission_texture")


def texture_snapshot(texture):
    if texture is None:
        return None
    array = texture.download()
    # GPU-private color textures may expand an RGB source to opaque RGBA.
    if array.dtype == np.uint8 and array.ndim == 3 and array.shape[2] == 3:
        opaque = np.full((*array.shape[:2], 1), 255, dtype=array.dtype)
        array = np.concatenate((array, opaque), axis=2)
    return {"shape": list(array.shape), "dtype": str(array.dtype),
            "srgb": texture.is_srgb, "sha256": hashlib.sha256(array.tobytes()).hexdigest()}


def signature(material):
    return {"scalars": {k: getattr(material, k) for k in SCALARS},
            "textures": {k: texture_snapshot(getattr(material, k)) for k in TEXTURES}}


def snapshot(task, idx):
    result = {}
    actors = {k: getattr(task, k) for k in ("box", "plate", "spoon", "bread", "ball_food")}
    for name, actor in actors.items():
        if actor is None:
            continue
        entity = actor._objs[idx]
        if name == "box":
            bodies = [(link.name.split("link_")[-1], link.entity) for link in entity.get_links()]
        else:
            bodies = [("actor", entity)]
        for link, entity in bodies:
            rb = entity.find_component_by_type(sapien.render.RenderBodyComponent)
            if rb is None:
                continue
            for i, shape in enumerate(rb.render_shapes):
                parts = ([shape.material] if isinstance(shape, sapien.render.RenderShapePrimitive)
                         else [part.material for part in shape.parts])
                for j, material in enumerate(parts):
                    key = f"{name}/{link}/shape_{i}/slot_{j}"
                    assert key not in result, key
                    result[key] = {"shape_type": type(shape).__name__, **signature(material)}
    assert result, f"No render materials found for env {idx}"
    return result


def equal_materials(before, after, label):
    assert before.keys() == after.keys(), (label, before.keys() ^ after.keys())
    report = []
    for key, expected in before.items():
        actual = after[key]
        faults = []
        if expected["shape_type"] != actual["shape_type"]:
            faults.append("shape_type")
        faults.extend(name for name in SCALARS if not np.allclose(
            expected["scalars"][name], actual["scalars"][name], atol=1e-6, rtol=0))
        faults.extend(name for name in TEXTURES
                      if expected["textures"][name] != actual["textures"][name])
        report.append({"slot": key, "match": not faults, "mismatches": faults,
                       "native": expected, "restored": actual})
    return report


def trial(stage, enabled):
    env = make(stage, CONFIG if enabled else None)
    t = env.unwrapped
    try:
        obs, _ = env.reset(seed=7)
        before = pixels(obs, env.render())
        selected_before = snapshot(t, 1)
        other_before = snapshot(t, 0)
        state_before = sample_tree(t.get_state_dict(), 0)
        adapter = t.meal_appearance
        if enabled:
            assert [r["scheme_id"] for r in adapter.records] == ["variant_1", "variant_2"]
            other_record = dict(adapter.records[0])
            active_before = materials(adapter, 1)
        opts = {"env_idx": torch.tensor([1], device=t.device)}
        if enabled:
            opts["meal_appearance"] = {"per_env": {"1": {"scheme_id": "original"}}}
        obs, _ = env.reset(options=opts)
        after = pixels(obs, env.render())
        selected_after = snapshot(t, 1)
        other_after = snapshot(t, 0)
        state_after = t.get_state_dict()
        assert all(row["match"] for row in equal_materials(other_before, other_after, "env0 materials"))
        state_delta = changed(state_before, sample_tree(state_after, 0))
        assert all(row["max_abs_delta"] is not None and row["max_abs_delta"] <= 1e-6
                   for row in state_delta), (stage, state_delta)
        records = None
        if enabled:
            assert adapter.records[0] == other_record
            assert adapter.records[1]["scheme_id"] == "original"
            active_after = materials(adapter, 1)
            assert active_before.keys() == active_after.keys()
            assert all(a != active_after[key] for key, a in active_before.items()), stage
            records = adapter.records
        return {"before": selected_before, "after": selected_after, "before_images": before,
                "images": after, "state": sample_tree(state_after, 1),
                "other_state_delta": state_delta, "records": records}
    finally:
        env.close()


def compare_images(before, after, idx):
    result = {}
    for camera, a in before.items():
        delta = np.abs(a[idx].astype(np.int16) - after[camera][idx].astype(np.int16))
        result[camera] = {"changed_channels": int(np.count_nonzero(delta)),
                          "max_abs_channel_delta": int(delta.max())}
    return result


def check(stage, output):
    native, candidate = trial(stage, False), trial(stage, True)
    rows = equal_materials(native["after"], candidate["after"], "native to restored")
    initial_changes = equal_materials(native["after"], candidate["before"], "native to variant")
    state_delta = changed(native["state"], candidate["state"])
    visual = compare_images(native["images"], candidate["images"], 1)
    other_visual = compare_images(candidate["before_images"], candidate["images"], 0)
    for label, images in (("native", native["images"]), ("variant", candidate["before_images"]),
                          ("restored", candidate["images"])):
        Image.fromarray(images["human"][1, ..., :3]).save(output / f"{stage}_{label}.png")
    result = {"slots": rows, "changed_was_variant": [row["slot"] for row in initial_changes if not row["match"]],
              "native_vs_restored_state": state_delta, "native_vs_restored_rgb": visual,
              "env0_rgb": other_visual, "env0_state_delta": candidate["other_state_delta"],
              "records": candidate["records"]}
    (output / f"{stage}.json").write_text(json.dumps(result, indent=2) + "\n")
    assert all(row["match"] for row in rows), (stage, [row for row in rows if not row["match"]])
    assert all(row["max_abs_delta"] is not None and row["max_abs_delta"] <= 1e-6
               for row in state_delta), (stage, state_delta)
    for rgb in (visual, other_visual):
        assert all(v["max_abs_channel_delta"] <= 1 and v["changed_channels"] <= 8
                   for v in rgb.values()), (stage, rgb)
    return {"slots": len(rows), "variant_slots_changed": len(result["changed_was_variant"]),
            "native_vs_restored_rgb": visual, "env0_rgb": other_visual}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--stages", choices=TASKS, nargs="+", default=list(TASKS))
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    summary = {"job": os.environ.get("SLURM_JOB_ID"), "stages": {}}
    for stage in a.stages:
        summary["stages"][stage] = check(stage, a.output)
        (a.output / "restore_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print("PASS", stage, summary["stages"][stage], flush=True)


if __name__ == "__main__":
    main()

