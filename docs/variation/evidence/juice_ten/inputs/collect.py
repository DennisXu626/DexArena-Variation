import gzip,hashlib,json,shutil
from pathlib import Path
from PIL import Image
root=Path('/data/home/pb/juice-ten-20261124')
out=root/'handoff';out.mkdir(exist_ok=True)
summary={"base":"58de243 + PR19 b611faf + source snapshot","jobs":[137880,137890,137918],"stages":{},"limits":"Sharpa,2env,seed7,noise0,fixed schemes; no complete robot trajectory"}
for job,stages in [(137890,['OpenFridge']),(137918,['AppleToBlender','CloseFridge','PlaceLid','PressButton','Long'])]:
 for stage in stages:
  source=root/f'results-{job}'/stage;dest=out/stage;dest.mkdir(exist_ok=True)
  report=json.loads((source/'report.json').read_text())
  summary['stages'][stage]={'status':report['status'],'A4':len(report['rows']),'A5':len(report['A5']),'actual_ids':[r['request'] for r in report['rows']]}
  for name in ('report.json','identity.json','signatures.json'):
   data=(source/name).read_bytes()
   with gzip.open(dest/(name+'.gz'),'wb') as f:f.write(data)
  (dest/'image_hashes.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.png')},indent=2))
for name in ('short_trace/trace.json','critical/report.json','preview/manifest.json'):
 p=root/'results-137918'/name
 if p.exists():
  with gzip.open(out/(name.replace('/','_')+'.gz'),'wb') as f:f.write(p.read_bytes())
trace=json.loads((root/'results-137918/short_trace/trace.json').read_text())
summary['short_trace']={k:{'status':v['status'],'pairs':len(v['schemes'])} for k,v in trace['stages'].items()}
summary['critical']=json.loads((root/'results-137918/critical/report.json').read_text())['status']
for p in (root/'results-137918/preview').glob('*comparison.png'):
 im=Image.open(p);im.thumbnail((1440,1800));im.save(out/p.name)
for p in root.glob('*sha256.txt'):shutil.copyfile(p,out/p.name)
for p in root.glob('receipt-*.txt'):shutil.copyfile(p,out/p.name)
(out/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
