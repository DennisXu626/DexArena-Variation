"""Bake existing catalog colors into native texture luminance; CPU authoring only.

Native SAPIEN 3.0.3 raster shaders select texture OR baseColor, not their product.
No UV, geometry, alpha or simulation assets are modified by this authoring step.
"""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image


def make(assets, output, catalog):
    output.mkdir(parents=True, exist_ok=False)
    report = {'method': 'native luminance multiplied by existing catalog RGB; native alpha retained',
              'license': 'Derived from existing PartNet/RoboCasa task assets; original asset terms remain applicable',
              'files': {}}
    for role, folder in [('cabinet', assets / 'cabinet/images'), ('bowl', assets / 'bowl/visual')]:
        sources = sorted(p for p in folder.iterdir() if p.suffix.lower() in {'.jpg', '.jpeg', '.png'})
        for source in sources:
            with Image.open(source) as image:
                rgba = image.convert('RGBA')
                luminance = image.convert('RGB').convert('L')
                for scheme in ['ocean', 'citrus']:
                    color = catalog['schemes'][scheme]['objects'][role]['base_color']
                    channels = [luminance.point([round(v * c) for v in range(256)]) for c in color[:3]]
                    tinted = Image.merge('RGBA', (*channels, rgba.getchannel('A')))
                    name = f'{role}_{scheme}_{source.stem}.png'
                    target = output / name
                    tinted.save(target)
                    report['files'][name] = {'role': role, 'scheme': scheme, 'source': str(source.relative_to(assets)),
                        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'size': target.stat().st_size,
                        'dimensions': list(tinted.size), 'source_basename': source.name}
    (output / 'provenance.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    a = parser.parse_args()
    print(json.dumps(make(a.assets, a.output, json.loads(a.catalog.read_text())), indent=2))
