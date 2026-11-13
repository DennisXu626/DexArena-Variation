"""Small stdlib-only repository check. Never imports tasks or a simulator."""
import ast
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
sources = list((root / 'tools/variation').glob('*.py'))
sources += [root / 'tasks/cabinet_pouring' / name for name in
            ['cabinet_pouring_long.py', 'cabinet_pouring_pick_bottle.py',
             'cabinet_pouring_unscrew_cap.py', 'variation.py']]
for source in sources:
    ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
catalog = json.loads((root / 'tasks/assets/variation/cabinet_pouring/v1/catalog.json').read_text(encoding='utf-8'))
configs = list((root / 'examples/variation/cabinet_pouring').glob('*.json'))
for path in configs:
    config = json.loads(path.read_text(encoding='utf-8'))
    assert config['version'] == 'cabinet-pilot-v1', path
    for feature in ['appearance', 'initial_pose']:
        assert isinstance(config[feature]['enabled'], bool), path
    requests = [config.get('appearance', {})]
    requests += [v.get('appearance', {}) for v in config.get('per_env', {}).values()]
    for request in requests:
        ids = request.get('scheme_ids', []) + ([request['scheme_id']] if 'scheme_id' in request else [])
        assert all(i in catalog['schemes'] for i in ids), path
for scheme in catalog['schemes'].values():
    if 'label_texture' in scheme:
        assert (root / 'tasks/assets/variation/cabinet_pouring/v1' / scheme['label_texture']).is_file()
docs = [root / 'README.md', root / 'CONTRIBUTING.md', root / '.github/PULL_REQUEST_TEMPLATE.md']
docs += list((root / 'docs/variation').glob('*.md'))
links = 0
for path in docs:
    for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', path.read_text(encoding='utf-8')):
        if target.startswith(('https://', 'http://', '#', 'mailto:')):
            continue
        target = target.split('#', 1)[0]
        assert (path.parent / target).exists(), f'{path}: broken link {target}'
        links += 1
print(json.dumps({'status': 'passed', 'python_syntax_files': len(sources),
                  'json_configs': len(configs), 'relative_links': links,
                  'scope': 'CPU static only; no environment import or physical verification'}))
