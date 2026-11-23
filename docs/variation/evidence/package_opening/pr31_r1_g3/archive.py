"""Audit and package the actual PR31 GPU outputs without rerunning simulation."""
from pathlib import Path
import gzip
import hashlib
import json
import shutil
from PIL import Image, ImageDraw

root = Path('/data/home/pb/pr31-r1-fix-20261123')
results = root / 'results-135140'
out = root / 'evidence'
out.mkdir(exist_ok=False)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
dump = lambda p, x: p.write_text(json.dumps(x, indent=2) + '\n')
matrix = json.loads((root / 'review-matrix.json').read_text())
summary = {'tested_commit': '425a54a510b1a4b843279e30d41f8f6c69f428be', 'job': 135140, 'preview_job': 135189, 'node': 'lyg0295', 'physical_gpu': 3,
           'scope': 'Package Sharpa; 2 env; seed7; noise0; full checker A4/A5/random; review original task-camera frames',
           'stages': {}, 'review_cells': matrix}
for stage in ('open', 'extract', 'long'):
    src = results / stage
    report = json.loads((src / 'report.json').read_text())
    signatures = json.loads((src / 'signatures.json').read_text())
    assert report['status'] == 'passed'
    assert len(report['rows']) == 11 and len(report['A5']) == 20
    for key, value in signatures.items():
        assert hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == key
    maxima = {'unselected': 0., 'selected_vs_native': 0.}
    def compare(a, b):
        if isinstance(a, dict):
            assert a.keys() == b.keys()
            return max((compare(a[k], b[k]) for k in a), default=0.)
        if isinstance(a, list):
            assert len(a) == len(b)
            return max((compare(x, y) for x, y in zip(a, b)), default=0.)
        return abs(a - b)
    for case in report['A5']:
        selected = case['selected']; other = 1 - selected
        before = signatures[case['before']['control_targets']]
        after = signatures[case['after']['control_targets']]
        native = signatures[case['matched_native_after']['control_targets']]
        assert all(row['arm_impedance_qpos'] and row['drive_targets'] and row['drive_velocities'] for row in before + after)
        maxima['unselected'] = max(maxima['unselected'], compare(before[other], after[other]))
        maxima['selected_vs_native'] = max(maxima['selected_vs_native'], compare(native[selected], after[selected]))
    assert max(maxima.values()) <= 1e-6
    dest = out / stage; dest.mkdir()
    for name in ('report.json', 'signatures.json'):
        with gzip.open(dest / (name + '.gz'), 'wb') as f:
            f.write((src / name).read_bytes())
    shutil.copy2(src / 'identity.json', dest)
    shutil.copy2(results / (stage + '.log'), dest)
    rows = {row['request']: row for row in report['rows']}
    for cell in matrix:
        if cell['task'] != stage:
            continue
        scheme, idx = cell['request'], cell['environment']
        row = rows[scheme]
        assert row['actual'][idx]['scheme_id'] == scheme
        frames = []
        for label, name in row['images'].items():
            if not label.endswith('/env' + str(idx)):
                continue
            shutil.copy2(src / name, dest / name)
            frames.append({'camera': label, 'path': stage + '/' + name, 'sha256': sha(dest / name)})
        assert frames
        cell.update(actual_record_ids=[record['scheme_id'] for record in row['actual']],
                    proof=frames, status='rendered; actual ID and semantic checks passed; visual review pending')
    cameras = sorted({label.split('/')[0] for row in report['rows'] for label in row['images']})
    for camera in cameras:
        sheet = Image.new('RGB', (4 * 360, 4 * 300), '#181b20')
        draw = ImageDraw.Draw(sheet)
        for k in range(16):
            scheme = 'variant_' + str(3 + k // 2); idx = k % 2
            name = rows[scheme]['images'][camera + '/env' + str(idx)]
            im = Image.open(src / name).convert('RGB'); im.thumbnail((360, 272))
            x, y = (k % 4) * 360, (k // 4) * 300
            draw.text((x + 8, y + 6), f'{stage} {scheme} env{idx} {camera}', fill='white')
            sheet.paste(im, (x, y + 25))
        sheet.save(out / f'{stage}_{camera}_contact.jpg', quality=92)
    summary['stages'][stage] = {'status': report['status'], 'A4': len(report['rows']), 'A5': len(report['A5']),
                                'control_target_max_delta': maxima, 'signature_blocks_verified': len(signatures),
                                'random_reproduced': report['random']['repeats'] == 2}
dump(out / 'summary.json', summary)
dump(out / 'source_hashes.json', {str(p.relative_to(root / 'source')): sha(p) for folder in ('tasks', 'tools', 'utils', 'tests') for p in (root / 'source' / folder).rglob('*.py')})
dump(out / 'raw_image_hashes.json', {str(p.relative_to(results)): sha(p) for p in results.rglob('*.png')})
shutil.copy2(root / 'run.sh', out / 'run.sh')
shutil.copy2(results / 'cpu-tests.log', out)
shutil.copy2(root / 'receipt.txt', out)
shutil.copy2(root / 'run-preview.sh', out)
shutil.copy2(root / 'archive.py', out / 'archive.py')
preview = root / 'preview-135189'
assert len(list(preview.glob('*.png'))) == 55
shutil.copytree(preview, out / 'supplemental_preview')
dump(out / 'file_hashes.json', {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file()})
shutil.make_archive(str(root / 'evidence'), 'gztar', out)
print(json.dumps(summary['stages'], indent=2))
