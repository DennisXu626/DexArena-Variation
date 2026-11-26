"""Independent acceptance expectations, never used to choose runtime materials.

These reviewed ID-to-role expectations deliberately do not come from the catalog:
otherwise swapping two complete recipes could pass the regression check.
"""
import copy
import hashlib

import numpy as np

EXPECTED = {
    "variant_1": {"pan": "#2D746E", "pan_roughness": .84, "bin_frame": "#B0A79B",
                  "sugar_rgb_multipliers": [1.05, .82, .88]},
    "variant_2": {"pan": "#A64D3C", "pan_roughness": .51, "bin_frame": "#384F6A",
                  "sugar_rgb_multipliers": [.76, .92, 1.08]},
}


def check_catalog(catalog):
    assert catalog["schemes"]["original"] == {}
    for scheme, expected in EXPECTED.items():
        assert catalog["schemes"][scheme] == expected, ("ID/recipe mismatch", scheme)


def linear_color(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels] + [1.]


def expected_pixels(original, scheme):
    pixels = original.copy()
    if scheme != "original":
        # Compute from the independently frozen ID contract and original pixels.
        pixels[..., :3] = np.clip(np.rint(
            original[..., :3] * np.asarray(EXPECTED[scheme]["sugar_rgb_multipliers"])), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(pixels)


def check_materials(native, actual, scheme, original_rgba):
    expected = copy.deepcopy(native)
    pan, = [k for k, m in native.items() if k.startswith("pan/")
            and m["color"][2] > .8 and m["color"][0] < .1]
    frame, = [k for k, m in native.items() if k.startswith("bin/") and m["base_color_texture"] is None]
    debris = []
    original = np.ascontiguousarray(original_rgba)
    original_id = [list(original.shape), str(original.dtype), hashlib.sha256(original.tobytes()).hexdigest()]
    actors = {k.split("/")[0] for k in native if k.startswith("debris_")}
    assert len(actors) == 3, ("expected three sugar actors", actors)
    for actor in sorted(actors):
        slots = [k for k, material in native.items()
                 if k.startswith(actor + "/") and material["base_color_texture"] is not None]
        assert len(slots) == 1, ("expected one sugar texture slot", actor, slots)
        slot, = slots
        assert native[slot]["base_color_texture"][1] == original_id, ("native sugar texture mismatch", slot)
        debris.append(slot)
    pixels = expected_pixels(original_rgba, scheme)
    texture_id = [list(pixels.shape), str(pixels.dtype), hashlib.sha256(pixels.tobytes()).hexdigest()]
    if scheme != "original":
        recipe = EXPECTED[scheme]
        expected[pan]["color"] = linear_color(recipe["pan"])
        expected[pan]["roughness"] = recipe["pan_roughness"]
        expected[frame]["color"] = linear_color(recipe["bin_frame"])
    for slot in debris:
        expected[slot]["base_color_texture"][1] = texture_id
    assert expected.keys() == actual.keys()
    for slot, material in expected.items():
        for field, value in material.items():
            found = actual[slot][field]
            if field in ("color", "roughness", "metallic"):
                assert np.allclose(value, found, atol=1e-6, rtol=0), (scheme, slot, field, value, found)
            else:
                assert value == found, (scheme, slot, field, value, found)
    return {"scheme_id": scheme, "pan_slot": pan, "bin_frame_slot": frame,
            "sugar_slots": debris, "expected_sugar_rgba_sha256": texture_id[-1]}
