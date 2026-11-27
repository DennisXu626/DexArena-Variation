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

EXPECTED.update({'variant_3': {'pan': '#315DA8', 'pan_roughness': 0.7, 'bin_frame': '#E5DCC8', 'sugar_color': '#E8A35A'}, 'variant_4': {'pan': '#8C9E7A', 'pan_roughness': 0.82, 'bin_frame': '#733B4B', 'sugar_color': '#C7B2DB'}, 'variant_5': {'pan': '#D5A72C', 'pan_roughness': 0.64, 'bin_frame': '#454951', 'sugar_color': '#60B8CD'}, 'variant_6': {'pan': '#A38CC6', 'pan_roughness': 0.76, 'bin_frame': '#286A70', 'sugar_color': '#E3D77E'}, 'variant_7': {'pan': '#D57B65', 'pan_roughness': 0.6, 'bin_frame': '#304869', 'sugar_color': '#97CDB2'}, 'variant_8': {'pan': '#8FBFD0', 'pan_roughness': 0.8, 'bin_frame': '#765448', 'sugar_color': '#D991AD'}, 'variant_9': {'pan': '#E5DDC9', 'pan_roughness': 0.72, 'bin_frame': '#35584C', 'sugar_color': '#825184'}, 'variant_10': {'pan': '#535A66', 'pan_roughness': 0.66, 'bin_frame': '#B97846', 'sugar_color': '#E8E4DC'}})


# Approved handle/body additions, independently frozen from the runtime catalog.
for scheme, handle, body in [
    ('variant_1', '#D8C7A5', '#A9B8AC'), ('variant_2', '#D6BA98', '#91A5BA'),
    ('variant_3', '#D7A469', '#B5C5D8'), ('variant_4', '#B47D8B', '#CAB7BF'),
    ('variant_5', '#607D8B', '#A6B4BE'), ('variant_6', '#68A89E', '#A9C8C0'),
    ('variant_7', '#7893B2', '#A5B8CB'), ('variant_8', '#B48E76', '#C9B6A3'),
    ('variant_9', '#789B82', '#A9BCA5'), ('variant_10', '#D0A078', '#C6AD95')]:
    EXPECTED[scheme].update(pan_handle=handle, bin_body=body, bin_body_metallic=.05, bin_body_roughness=.65)


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
        recipe = EXPECTED[scheme]
        if "sugar_color" in recipe:
            color = np.asarray([int(recipe["sugar_color"][i:i+2],16) for i in (1,3,5)])
            luminance = np.mean(original[..., :3].astype(float), axis=2)
            reference = max(1., float(np.percentile(luminance,95)))
            pixels[..., :3] = np.rint(np.minimum(luminance/reference,1)[...,None]*color).astype(np.uint8)
        else:
            pixels[..., :3] = np.clip(np.rint(
                original[..., :3] * np.asarray(recipe["sugar_rgb_multipliers"])), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(pixels)


def check_materials(native, actual, scheme, original_rgba, bin_original=None):
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
        for slot in native:
            if slot.startswith("pan/") and slot != pan:
                expected[slot]["color"] = linear_color(recipe["pan_handle"])
            if slot.startswith("bin/") and native[slot]["base_color_texture"] is not None:
                assert bin_original is not None, "original bin pixels required"
                rgba = np.asarray(bin_original).copy()
                rgb = np.asarray([int(recipe["bin_body"][i:i+2], 16) for i in (1,3,5)])
                rgba[..., :3] = rgb
                expected[slot]["base_color_texture"][1] = [list(rgba.shape), str(rgba.dtype), hashlib.sha256(rgba.tobytes()).hexdigest()]
                expected[slot]["metallic"] = recipe["bin_body_metallic"]
                expected[slot]["roughness"] = recipe["bin_body_roughness"]
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
