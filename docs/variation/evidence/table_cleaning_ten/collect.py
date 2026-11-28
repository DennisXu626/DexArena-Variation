import gzip,hashlib,json,tarfile,shutil,subprocess
from pathlib import Path
root=Path('/data/home/pb/table-cleaning-ten-20261124')
source=root/'full-138555'
out=root/'handoff-138555';out.mkdir(exist_ok=True)
def save(name,data):
 path=out/name;path.parent.mkdir(parents=True,exist_ok=True)
 with gzip.open(str(path)+'.gz','wt') as f:json.dump(data,f,indent=2)
def read(p):return json.loads(p.read_text())
summary={'job':138555,'gpu':6,'stages':{},'source_snapshot':'final-overlay.tar.gz'}
for stage in ('PickDebris','DumpDustpan','Long'):
 folder=source/stage
 report=read(folder/'report.json');signatures=read(folder/'signatures.json')
 for digest,value in signatures.items():
  text=json.dumps(value,sort_keys=True,separators=(',',':'))
  assert hashlib.sha256(text.encode()).hexdigest()==digest
 summary['stages'][stage]={'status':report['status'],'A4':len(report['rows']),'A5':len(report['A5']),'signature_blocks':len(signatures),'replay':report.get('replay') is not None}
 for name in ('report.json','signatures.json','identity.json'):save(stage+'/'+name,read(folder/name))
 hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.png')}
 save(stage+'/image_hashes.json',hashes)
 from PIL import Image,ImageDraw
 images=[folder/f"{scheme}_human_env0.png" for scheme in ('original',*[f'variant_{i}' for i in range(1,11)])]
 canvas=Image.new('RGB',(1500,4*407),'#20252b');draw=ImageDraw.Draw(canvas)
 for i,path in enumerate(images):
  x,y=(i%3)*500,(i//3)*407
  with Image.open(path) as image:canvas.paste(image.convert('RGB').resize((500,375)),(x,y+32))
  draw.text((x+10,y+8),path.name.removesuffix('_human_env0.png'),fill='white')
 canvas.save(out/f'{stage}_A4.png')
 if stage=='Long':
  for selected in (0,1):
   canvas=Image.new('RGB',(1000,814),'#20252b');draw=ImageDraw.Draw(canvas)
   for i,(moment,env) in enumerate((('before',selected),('after',selected),('before',1-selected),('after',1-selected))):
    path=folder/f'a5_variant_10_selected{selected}_{moment}_human_env{env}.png'
    x,y=(i%2)*500,(i//2)*407
    with Image.open(path) as image:canvas.paste(image.convert('RGB').resize((500,375)),(x,y+32))
    draw.text((x+10,y+8),f'env{env} {moment} / reset env{selected}',fill='white')
   canvas.save(out/f'Long_A5_reset_env{selected}.png')
trace=read(source/'short_trace/trace.json')
maximum=0.
def equal(a,b):
 global maximum
 if isinstance(a,dict):
  assert a.keys()==b.keys()
  for key in a:equal(a[key],b[key])
 elif isinstance(a,list):
  assert len(a)==len(b)
  for x,y in zip(a,b):equal(x,y)
 elif a!=b:
  assert isinstance(a,(int,float)) and isinstance(b,(int,float))
  difference=abs(a-b);maximum=max(maximum,difference);assert difference<=1e-6
for stage,data in trace['stages'].items():
 assert data['status']=='passed' and len(data['schemes'])==11
 for row in data['schemes']:
  equal(row['native_initial'],row['initial']);equal(row['native_trace'],row['trace'])
summary['trace_max_delta']=maximum
summary['short_trace']={k:{'status':v['status'],'pairs':len(v['schemes'])} for k,v in trace['stages'].items()}
save('short_trace.json',trace)
critical=read(root/'recheck-138600/critical/report.json');save('critical.json',critical)
summary['critical']={'status':critical.get('status'),'cases':len(critical['cases'])}
for name in ('hold-cpu.txt','reset-cpu.txt','state-restore-cpu.json','state-restore-cpu.txt','source-sha256.txt','asset-sha256.txt'):
 shutil.copy2(source/name,out/name)
for job in (138536,138555,138556,138598,138600):
 result=subprocess.run(['/opt/slurm/bin/scontrol','show','job',str(job)],capture_output=True,text=True)
 receipt=result.stdout if result.returncode==0 else 'Receipt no longer retained by scontrol at collection time: '+result.stderr
 (out/f'receipt-{job}.txt').write_text(receipt)
 log=root/(('smoke-' if job==138536 else 'full-' if job==138555 else 'pixel-' if job==138556 else 'recheck-')+str(job)+'.out')
 if log.exists():
  with gzip.open(out/(str(job)+'.out.gz'),'wb') as f:f.write(log.read_bytes())
preview=source/'preview'
if (preview/'manifest.json').exists():
 save('preview_manifest.json',read(preview/'manifest.json'))
 for p in preview.glob('*comparison.png'):shutil.copy2(p,out/p.name)
pixel=root/'recheck-138600/pixel/report.json'
if pixel.exists():save('pixel.json',read(pixel));summary['pixel']=read(pixel)
assert all(v['status']=='passed' and v['A4']==11 and v['A5']==20 and v['replay'] for v in summary['stages'].values())
assert summary['critical']=={'status':'passed','cases':8}
assert summary.get('pixel',{}).get('status')=='passed'
assert len(summary['pixel']['cases'])==6
(out/'summary.json').write_text(json.dumps(summary,indent=2))
shutil.copy2(root/'final-overlay.tar.gz',out/'source_snapshot.tar.gz')
shutil.copy2(root/'supplement.tar.gz',out/'pixel_initial_source_snapshot.tar.gz')
shutil.copy2(root/'recheck-source.tar.gz',out/'recheck_initial_source_snapshot.tar.gz')
shutil.copy2(root/'recheck-v3-source.tar.gz',out/'recheck_source_snapshot.tar.gz')
for name in ('full.sh','supplement.sh','smoke.sh','recheck.sh','recheck-v3.sh','source_manifest.json'):shutil.copy2(root/name,out/name)
with tarfile.open(root/'handoff-138555.tar.gz','w:gz') as t:t.add(out,arcname=out.name)
print(json.dumps(summary,indent=2))
