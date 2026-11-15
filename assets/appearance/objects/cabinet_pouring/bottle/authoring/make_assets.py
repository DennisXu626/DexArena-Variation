"""Make three small original graphic textures; no external artwork or meshes."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Font files are supplied by the user and are not redistributed.
import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=Path('appearance-authoring-output'))
parser.add_argument('--font', type=Path, required=True, help='Arial regular TTF')
parser.add_argument('--bold-font', type=Path, required=True, help='Arial Bold TTF')
args = parser.parse_args()
out = args.output
out.mkdir(parents=True, exist_ok=True)
if any((out / name).exists() for name in ['ocean.png', 'citrus.png', 'violet.png', 'catalog.json']):
    raise SystemExit('Use a fresh output directory; published files are not overwritten')
font = ImageFont.truetype(str(args.bold_font), 48)
small = ImageFont.truetype(str(args.font), 23)
styles={
 'ocean':{'bg':'#0c526b','accent':'#54e0df','ink':'#ffffff','title':'OCEAN','body_color':[.15,.65,.68,1],'cap_color':[.025,.08,.16,1],'reference_color':[1,.9,.1,1],'roughness':.38,'metallic':.05},
 'citrus':{'bg':'#ffbe32','accent':'#9d391a','ink':'#203d24','title':'CITRUS','body_color':[.95,.70,.18,1],'cap_color':[.95,.95,.83,1],'reference_color':[.04,.12,.06,1],'roughness':.65,'metallic':0},
 'violet':{'bg':'#3f205d','accent':'#eaa2ef','ink':'#ffffff','title':'VIOLET','body_color':[.48,.20,.64,1],'cap_color':[.22,.04,.40,1],'reference_color':[.05,1,.82,1],'roughness':.28,'metallic':.16}}
catalog={'version':'cabinet-appearance-v1','source':'M2 original procedural graphics, generated with Pillow; no external artwork','permission':'Project-authored graphics; no third-party artwork restrictions','schemes':{'original':{'description':'Restore captured native render properties and original texture/marker colors'}}}
for number,(key,style) in enumerate(styles.items(),start=1):
    img=Image.new('RGB',(388,490),style['bg']);draw=ImageDraw.Draw(img)
    if key=='ocean':
        for offset in [260,325,420]:
            draw.polygon([(0,offset),(388,offset-105),(388,offset-55),(0,offset+50)],fill=style['accent'])
        draw.ellipse((258,25,360,127),fill=style['ink'])
    elif key=='citrus':
        draw.ellipse((140,260,430,550),fill=style['accent'])
        draw.ellipse((181,301,389,509),fill=style['bg'])
        draw.polygon([(18,245),(100,220),(83,350)],fill=style['ink'])
    else:
        for box in [(20,260,108,350),(145,320,230,410),(265,230,360,320)]:
            draw.rounded_rectangle(box,radius=12,fill=style['accent'])
        draw.polygon([(275,35),(370,95),(280,145)],fill=style['ink'])
    draw.rectangle((0,145,388,224),fill=style['bg'])
    draw.text((16,150),style['title'],font=font,fill=style['ink'])
    draw.text((18,440),f'DEX / {number:02d}',font=small,fill=style['ink'])
    filename=f'{key}.png';img.save(out/filename)
    entry={k:v for k,v in style.items() if k in ['body_color','cap_color','reference_color','roughness','metallic']}
    entry.update(label_texture=filename,sha256=hashlib.sha256((out/filename).read_bytes()).hexdigest(),
                 description=f'{style["title"]} original graphic label; contrasting asymmetric native top stripe and side tick')
    catalog['schemes'][key]=entry
(out/'catalog.json').write_text(json.dumps(catalog,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files':[p.name for p in out.iterdir()],'bytes':sum(p.stat().st_size for p in out.iterdir())}))
