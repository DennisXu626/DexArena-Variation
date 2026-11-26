"""Recheck archived job 90644 against independent scheme/role expectations.

Numeric manifest checks only; image hue/visibility review is recorded separately.
No GPU, simulator, assets or new rendering are needed.
"""
import json
from pathlib import Path

import numpy as np
from table_cleaning_contract import EXPECTED, linear_color


def main():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "docs/variation/evidence/table_cleaning/preview_90644_manifest.json").read_text(encoding="utf-8"))
    assert manifest["job_id"] == "90644"
    count = 0
    for view, schemes in manifest["views"].items():
        original = schemes["original"]
        for scheme, expected in EXPECTED.items():
            actual = schemes[scheme]
            material = actual["binding"]
            assert all(actual[k] == v for k, v in original.items() if k != "binding"), (view, scheme, "initial state/camera")
            assert np.allclose(material["pan_body_color"], linear_color(expected["pan"]), atol=1e-6, rtol=0), (view, scheme, "pan")
            assert abs(material["pan_roughness"] - expected["pan_roughness"]) <= 1e-6
            assert np.allclose(material["bin_frame_color"], linear_color(expected["bin_frame"]), atol=1e-6, rtol=0), (view, scheme, "frame")
            for key in ("bin_wall_color", "bin_wall_texture", "grip_color", "grip_roughness"):
                assert material[key] == original["binding"][key], (view, scheme, key)
            textures = material["sugar_textures"]
            assert len({v["sha256"] for v in textures}) == 1
            assert textures[0] != original["binding"]["sugar_textures"][0]
            other = "variant_2" if scheme == "variant_1" else "variant_1"
            assert textures[0] != schemes[other]["binding"]["sugar_textures"][0]
            count += 1
    print(json.dumps({"status": "passed", "job": "90644", "view_scheme_pairs": count,
                      "scope": "CPU archived manifest checks; sugar hues require recorded original-image review"}))


if __name__ == "__main__":
    main()
