"""CPU audit of the original keyboard UVs and existing safe shell triangles.

The mask protects in-bounds key atlas footprints. It does not claim to model
out-of-bounds wrapping. All moving keys and all out-of-bounds shell triangles
keep their complete original material and texture object.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.variation.office_devices_assets import inspect_assets,DEFAULT_ASSET_ROOT
from tools.variation.office_devices_materials import _RUNTIME as M
from tools.variation import office_devices_uv_proof as U


def parse(path,materials):
    import numpy as np
    vertices=[];uv=[];current=None;triangles=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        parts=line.split()
        if not parts:continue
        if parts[0]=='v':vertices.append([float(v) for v in parts[1:4]])
        elif parts[0]=='vt':uv.append([float(v) for v in parts[1:3]])
        elif parts[0]=='usemtl':current=parts[1]
        elif parts[0]=='f' and current in materials:
            if len(parts)!=4:raise ValueError('Keyboard proof requires original triangles')
            refs=[value.split('/') for value in parts[1:]]
            if any(len(value)<2 or not value[1] for value in refs):raise ValueError('Keyboard proof requires source UV indices')
            triangles.append((np.asarray([vertices[int(value[0])-1] for value in refs],dtype=np.float32),
                              np.asarray([uv[int(value[1])-1] for value in refs],dtype=np.float32)))
    return triangles


def inspect_uv(asset_dir,margin=8):
    from PIL import Image,ImageDraw,ImageFilter
    import numpy as np
    asset_dir=Path(asset_dir);inventory=inspect_assets('keyboard',asset_dir.parent)
    texture=asset_dir/'images/texture_0.jpg';width,height=Image.open(texture).size
    mask=Image.new('L',(width,height));draw=ImageDraw.Draw(mask);keys=0;source_key_triangles=0
    for row in inventory['visuals']:
        if row['link']=='link_0':continue
        keys+=1
        names={name for name,value in row['materials'].items() if value['textures']}
        for positions,uv in parse(asset_dir/row['mesh'],names):
            if np.any(uv<0) or np.any(uv>1):continue
            source_key_triangles+=1
            draw.polygon([(float(u)*(width-1),(1-float(v))*(height-1)) for u,v in uv],fill=255)
    if keys!=77:raise ValueError('The keyboard proof requires all 77 moving key visuals')
    array=np.asarray(mask);rows=[]
    for row in array:
        flags=np.r_[False,row>0,False]
        starts=np.flatnonzero((~flags[:-1])&flags[1:]);ends=np.flatnonzero(flags[:-1]&(~flags[1:]))
        rows.append([[int(a),int(b)] for a,b in zip(starts,ends)])
    proof={'schema_version':2,'scope':'in-bounds original key atlas footprints; never a render texture',
        'size':[width,height],'key_mask_rows':rows,'all_moving_keys_complete_pbr_protected':True,
        'out_of_bounds_key_uv':'preserved with original complete material and texture handle; this mask does not model wrap coverage',
        'coverage_contract':{'method':'exact_integer_sat_closed_bilinear_support','coordinates':'native float32 exact dyadic rationals',
            'address_mode':'repeat','filter_mode':'linear','mipmap_levels':1,'is_srgb':True,'margin_texels':margin,
            'support':'[(s-.5)/W,(e+.5)/W] for texel run [s,e); touching rejects'}}
    triangles=parse(asset_dir/'textured_objs/original-80.obj',{'material_0_0'})
    native_values=[]
    for positions,uv in triangles:
        native_uv=uv.copy();native_uv[:,1]=np.float32(1)-native_uv[:,1];native_values.extend(native_uv.tolist())
    scale=U.integer_scale(native_values,width,height)
    rectangles,protected_sha=U.protected_rectangles(mask,margin,scale)
    protected=mask.filter(ImageFilter.MaxFilter(margin*2+1)) if margin else mask
    protected_array=np.asarray(protected)>0
    safe=[];native_safe=[];out_of_bounds=0;touches=0;safe_area=0.;all_area=0.;safe_uv=[];safe_coverage=Image.new('L',(width,height));safe_draw=ImageDraw.Draw(safe_coverage)
    witnesses=[]
    for face_index,(positions,uv) in enumerate(triangles,1):
        area=float(np.linalg.norm(np.cross(positions[1]-positions[0],positions[2]-positions[0]))/2);all_area+=area
        if np.any(uv<0) or np.any(uv>1):out_of_bounds+=1;continue
        points=[(float(u)*(width-1),(1-float(v))*(height-1)) for u,v in uv]
        native_uv=uv.copy();native_uv[:,1]=np.float32(1)-native_uv[:,1]
        witness=U.periodic_witness(U.scaled_triangle(native_uv.tolist(),scale),rectangles,scale)
        if witness is not None:
            touches+=1;witnesses.append({'material_face_1_based':face_index,'witness':witness});continue
        safe.extend(M.triangle_position_uv_ids(positions,uv,[[0,1,2]]))
        native_uv=uv.copy();native_uv[:,1]=np.float32(1)-native_uv[:,1]
        native_safe.extend(M.triangle_position_uv_ids(positions,native_uv,[[0,1,2]]))
        safe_area+=area;safe_uv.extend(uv.tolist());safe_draw.polygon(points,fill=255)
    report={'scope':'CPU source UV audit; no rendering or task success claim','source_triangles':len(triangles),
        'safe_triangles':len(safe),'safe_source_triangle_position_uv_sha256':safe,
        'safe_native_triangle_position_uv_sha256':native_safe,
        'source_uv_to_native':'assimp_flip_v_float32','native_uv_to_image':'direct_uv_top_left',
        'coverage_method':'exact_integer_sat_closed_bilinear_support','integer_scale':scale,
        'protected_rectangle_count':len(rectangles),'rejected_in_bounds_witnesses':witnesses,
        'out_of_bounds_triangles_protected':out_of_bounds,'touching_key_region_triangles_protected':touches,
        'key_uv_mask_sha256':hashlib.sha256(array.tobytes()).hexdigest(),
        'protected_mask_sha256':protected_sha,
        'texture_sha256':hashlib.sha256(texture.read_bytes()).hexdigest(),
        'source_key_in_bounds_triangles':source_key_triangles,'moving_key_visuals':keys,
        'safe_uv_range':[np.min(safe_uv,axis=0).tolist(),np.max(safe_uv,axis=0).tolist()],
        'safe_source_area':safe_area,'source_area':all_area,'margin_texels':margin,
        'source_sha256':inventory['files']}
    return proof,report,mask,protected,safe_coverage


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--asset-dir',type=Path,default=DEFAULT_ASSET_ROOT/'13106');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    proof,report,mask,protected,safe=inspect_uv(args.asset_dir);args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'key_uv_protection.json').write_text(json.dumps(proof,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')
    (args.output/'audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    mask.save(args.output/'key_in_bounds_atlas_mask.png');protected.save(args.output/'key_protected_8_texel_mask.png');safe.save(args.output/'safe_shell_mask.png')
    from PIL import Image
    source=Image.open(args.asset_dir/'images/texture_0.jpg').convert('RGB')
    Image.composite(Image.blend(source,Image.new('RGB',source.size,(0,170,60)),.5),source,safe).save(args.output/'safe_shell_atlas_overlay.png')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','safe_source_triangle_position_uv_sha256','safe_native_triangle_position_uv_sha256')},indent=2))


if __name__=='__main__':main()
