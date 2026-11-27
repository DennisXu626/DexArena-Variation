"""Bake the stand mark with each catalog paint color for the default G-buffer."""
import argparse
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'assets/appearance/objects/pipette_transfer'


def stand_textures(catalog):
    binding = json.loads((ASSETS / 'pipette_stand/bindings.json').read_text(encoding='utf-8'))
    definition = binding['roles']['base_plate']['candidate_color_texture']
    with Image.open(ROOT / definition['source_mask']) as source:
        mark = source.convert('L')
    factors = [(v / 12.92 if v <= .04045 else ((v + .055) / 1.055)**2.4)
               for v in (index / 255 for index in range(256))]

    def srgb(value):
        encoded = 12.92 * value if value <= .0031308 else 1.055 * value**(1 / 2.4) - .055
        return round(255 * encoded)

    materials = catalog['objects']['pipette_stand']['schemes']
    for scheme in catalog['candidate_ids']:
        paint = materials[scheme]['base_plate']['base_color_rgb']
        channels = [mark.point([srgb(level * factor) for factor in factors]) for level in paint]
        yield ROOT / definition['directory'] / f'{scheme}.png', Image.merge('RGB', channels)


def check_stand_textures(catalog):
    for path, expected in stand_textures(catalog):
        with Image.open(path) as actual:
            if actual.mode != 'RGB' or actual.size != expected.size or actual.tobytes() != expected.tobytes():
                raise ValueError(f'Pipette stand paint bake differs from catalog and mark: {path.name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Regenerate the checked-in paint textures')
    args = parser.parse_args()
    catalog = json.loads((ASSETS / 'catalog.json').read_text(encoding='utf-8'))
    if args.write:
        for path, texture in stand_textures(catalog):
            path.parent.mkdir(parents=True, exist_ok=True)
            texture.save(path, optimize=True)
    check_stand_textures(catalog)
    print(f'Checked {len(catalog["candidate_ids"])} opaque RGB stand paint textures.')


if __name__ == '__main__':
    main()
