"""CPU-only archive consistency checks; never loads simulation or publishes assets."""
import ast
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[2]
archive = root / 'assets/appearance'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


rows = list(csv.DictReader((archive / 'objects.csv').open(encoding='utf-8')))
assert len(rows) == 42 and len({(r['family'], r['object_id']) for r in rows}) == 42
assert len({r['family'] for r in rows}) == 10
assert Counter(r['status'] for r in rows) == {
    'accepted_pilot': 2, 'pending_adaptation': 35, 'no_visual': 3,
    'not_loaded': 1, 'external_pending': 1,
}
for row in rows:
    directory = archive / row['directory']
    assert (directory / 'README.md').is_file(), row
    if row['status'] != 'accepted_pilot':
        assert not (directory / 'variants').exists(), row
mapping = read(archive / 'runtime_mapping.json')
catalog_path = root / mapping['runtime_catalog']
catalog = read(catalog_path)
assert sha(catalog_path) == mapping['runtime_catalog_sha256']
for name, item in mapping['schemes'].items():
    scheme = catalog['schemes'][name]
    body = read(archive / item['bottle_materials'])
    cap = read(archive / item['cap_materials'])
    assert body['scheme_id'] == cap['scheme_id'] == name
    assert body['paired_cap_scheme_id'] == cap['paired_bottle_scheme_id'] == name
    for role, material in body['roles'].items():
        expected = scheme['body_color'] if role == 'body_surface' else [1, 1, 1, 1]
        assert material['base_color'] == expected
        assert material['roughness'] == scheme['roughness']
        assert material['metallic'] == scheme['metallic']
    for role, key in [('cap_surface', 'cap_color'), ('cap_reference', 'reference_color')]:
        assert cap['roles'][role] == {
            'base_color': scheme[key], 'roughness': scheme['roughness'],
            'metallic': scheme['metallic'],
        }
    texture = archive / item['texture']['archive']
    runtime = root / item['texture']['runtime']
    assert texture.read_bytes() == runtime.read_bytes()
    assert sha(texture) == item['texture']['sha256'] == scheme['sha256'] == body['label_sha256']
    assert runtime.name == scheme['label_texture']
    assert (archive / item['bottle_materials']).parent / body['roles']['body_label']['base_color_texture'] == texture
    assert cap['texture'] is None

bottle = archive / 'objects/cabinet_pouring/bottle'
cap = bottle.parent / 'bottle_cap'
for folder, handles, uv in [(bottle, ['source', 'source_fixed', 'source_open'], 38),
                            (cap, ['cap', 'cap_fixed', 'cap_twin'], 0)]:
    binding = read(folder / 'bindings.json')
    assert binding['runtime_handles'] == handles and binding['uv_vertices'] == uv
    assert set(binding['representations']) == set(handles)
assert not list(cap.rglob('textures'))
native_tree = ast.parse((root / 'tasks/cabinet_pouring/cabinet_pouring_long.py').read_text(encoding='utf-8'))
markers = next(n.value
               for n in native_tree.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'CAP_MARKER_BOXES' for t in n.targets))
assert isinstance(markers, ast.List) and len(markers.elts) == 2
adapter = (root / 'tasks/cabinet_pouring/variation.py').read_text(encoding='utf-8')
assert all(token in adapter for token in ['body_surface', 'body_label', 'cap_surface', 'cap_reference', 'RenderShapeBox'])
ast.parse((bottle / 'authoring/make_assets.py').read_text(encoding='utf-8'))
authoring = read(bottle / 'authoring/check_result.json')
assert all(x['byte_match'] and x['size'] == [388, 490] for x in authoring['images'])
for image in read(archive / 'preview_sources.json')['images']:
    assert sha(archive / image['archive']) == image['sha256']
images = list(archive.rglob('*.png'))
for path in images:
    with Image.open(path) as image:
        image.load()
links = 0
for path in [root / 'README.md', *archive.rglob('*.md')]:
    for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', path.read_text(encoding='utf-8')):
        if target.startswith(('https://', 'http://', '#', 'mailto:')):
            continue
        assert (path.parent / target.split('#')[0]).exists(), f'{path}: {target}'
        links += 1
print(json.dumps({'status': 'passed', 'objects': len(rows), 'families': 10,
                  'decoded_pngs': len(images), 'archive_runtime_png_matches': 3,
                  'paired_schemes': 3, 'relative_links': links,
                  'scope': 'CPU archive only; no runtime capability or simulation claim'}))
