"""Flat material design swatches only. Never imports tasks or renders a scene."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
catalog = json.loads((ROOT / 'tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json').read_text())
image = Image.new('RGB', (1000, 480), '#f1efea')
draw = ImageDraw.Draw(image)
draw.text((24, 20), 'DRAWER / SOCKET - FLAT DESIGN SWATCHES, NOT SIMULATION IMAGES', fill='#212121')
draw.text((24, 44), 'PBR values are estimates. Gloss, holes, seams and realism require actual task RGB review.', fill='#444444')
for col, name in enumerate(['warm_white', 'neutral_grey']):
    x = 24 + col * 490
    draw.text((x, 90), name, fill='#212121')
    for row, (obj, role, label) in enumerate([('drawer','panel','Painted board / matt laminate'), ('socket','shell','Warm white PC / anthracite PC')]):
        p = catalog['schemes'][name][obj][role]
        rgb = [round((12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055)*255) for v in p['base_color'][:3]]
        y = 120 + row * 170
        draw.rectangle((x,y,x+440,y+95),fill=tuple(rgb),outline='#666666',width=1)
        draw.text((x,y+104),obj+' | '+label,fill='#212121')
        draw.text((x,y+123),f"roughness={p['roughness']} metallic=0 | native hardware/hole liners preserved",fill='#444444')
image.save(ROOT/'assets/appearance/objects/drawer_plug/drawer/material_board.png')
