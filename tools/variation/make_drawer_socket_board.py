"""Flat swatches of the drawer redesign, not task renderings."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
catalog = json.loads((ROOT / 'tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json').read_text())
image = Image.new('RGB', (1000, 465), '#f1efea')
draw = ImageDraw.Draw(image)
draw.text((24, 20), 'DRAWER COMPONENT COLOURS - FLAT SWATCHES, NOT TASK RGB', fill='#212121')
draw.text((24, 43), 'Wood swatch shows base colour only. Grain and gloss require actual task RGB.', fill='#444444')
for col, (name,label) in enumerate([('warm_white','A | Oak and warm white'),('neutral_grey','B | Light grey and graphite')]):
    x = 24 + col * 490
    draw.text((x, 75), label, fill='#212121')
    for row, (role, label) in enumerate([('top','Top and front trim'),('cabinet_side','Cabinet sides and frame'),
                                         ('front','Drawer fronts'),('inner_bottom','Inner walls, liners and floor'),
                                         ('handle','Handles')]):
        mat = catalog['schemes'][name]['drawer'][role]
        rgb = [round((12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055)*255) for v in mat['base_color'][:3]]
        y = 101 + row * 63
        draw.rectangle((x,y,x+170,y+42),fill=tuple(rgb),outline='#666666',width=1)
        draw.text((x+182,y+4),label,fill='#212121')
        draw.text((x+182,y+22),f"roughness={mat['roughness']} metallic={mat['metallic']}",fill='#444444')
draw.text((24, 432), 'Drawer sliders retain original hardware in both options.', fill='#444444')
with args.output.open('xb') as file:
    image.save(file,format='PNG')
