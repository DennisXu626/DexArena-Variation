"""CPU-only evidence integrity check; does not rerun simulation or certify acceptance."""
import argparse,gzip,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--frames',type=Path);args=p.parse_args();root=Path(__file__).resolve().parent;results={}
for stage in sorted(root.glob('*/report.json')):
 d=json.loads(stage.read_text());signatures=json.loads(gzip.decompress((stage.parent/'signatures.json.gz').read_bytes()))
 for h,v in signatures.items():
  assert hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()==h,h
 refs=[]
 def visit(v):
  if isinstance(v,dict):
   for k,x in v.items():
    if k in ('state','info','counters','materials','physics','rng','records') and isinstance(x,str) and len(x)==64:refs.append(x);assert x in signatures,x
    visit(x)
  elif isinstance(v,list):
   for x in v:visit(x)
 visit(d)
 table=json.loads((stage.parent/'scheme_table.json').read_text());assert [x['request'] for x in table]==['original',*[f'variant_{i}' for i in range(1,11)]]
 assert all(x['actual']==[x['request']]*2 for x in table)
 frames=0
 if args.frames:
  hashes=json.loads((stage.parent/'image_hashes.json').read_text())
  for raw in (args.frames/stage.parent.name).glob('*.png'):
   if raw.name in hashes:assert hashlib.sha256(raw.read_bytes()).hexdigest()==hashes[raw.name],raw;frames+=1
 results[stage.parent.name]={'status':d['status'],'signature_blocks':len(signatures),'references':len(refs),'scheme_rows':len(table),'original_pngs_verified':frames}
print(json.dumps({'integrity':'passed','simulation_rerun':False,'stages':results},indent=2))
