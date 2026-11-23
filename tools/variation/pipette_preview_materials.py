"""CPU source inspection and render-only materials for Pipette foundation previews."""
from __future__ import annotations

import ast
import copy
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / 'assets/appearance/objects/pipette_transfer'
CATALOG = ARCHIVE / 'catalog.json'
SOURCE = ROOT / 'tasks/pipette_transfer/pipette_transfer_long.py'
FUNCTIONS = (
    '_mat', '_glass_mat', '_box', '_cyl', '_open_glass_wall', '_ring',
    '_build_glass_beaker', '_build_test_tube', '_build_test_tube_rack',
    '_build_pipette_stand', '_lengthen_pipette_grip',
)
CONSTANTS = (
    'TUBE_COLLISION_BAND', 'DISH_COLLISION_WALL', 'PIPETTE_GRIP_ORIGINAL_LENGTH',
    'PIPETTE_GRIP_LENGTH', 'PIPETTE_GRIP_EXTENSION',
)
BUILDERS = {
    'sample_cup': '_build_glass_beaker', 'test_tube': '_build_test_tube',
    'tube_rack': '_build_test_tube_rack', 'pipette_stand': '_build_pipette_stand',
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def input_file_sha256():
    tools = ROOT/'tools/variation'
    tasks = ROOT/'tasks/pipette_transfer'
    files = [tools/name for name in ('render_pipette_preview.py', 'pipette_preview_materials.py',
                                     'check_pipette_appearance.py', 'pipette_render_fixes.py',
                                     'sapien_sdk/run_task_check.py')]
    files += [CATALOG]
    files += [ROOT / path for path in read_json(CATALOG)['new_textures']]
    files += [ARCHIVE/key/'bindings.json' for key in
              ('pipette', 'sample_cup', 'test_tube', 'tube_rack', 'pipette_stand', 'tip_cup')]
    files += [tasks/name for name in ('pipette_transfer_long.py', 'pipette_transfer_aspirate_liquid.py',
                                     'pipette_transfer_dispense_liquid.py', 'rendering.py')]
    asset = ROOT/'tasks/assets/task_object_meshes/pipette'
    files += [asset/name for name in ('mobility.urdf', 'README.md') if (asset/name).is_file()]
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}


def fresh_output(path, *, file=False):
    target = Path(path).resolve()
    roots = (ROOT/'outputs/variation/pipette_transfer', ROOT/'.local/pipette_transfer')
    if not any(target != root.resolve() and target.is_relative_to(root.resolve()) for root in roots):
        raise ValueError('Output must be inside this family outputs or .local directory')
    if target.exists():
        raise FileExistsError(f'Output already exists: {target}')
    if file:
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target.mkdir(parents=True)
    return target


def source_nodes():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in CONSTANTS for t in node.targets
        ):
            selected.append(node)
    names = {n.name for n in selected if isinstance(n, ast.FunctionDef)}
    if names != set(FUNCTIONS):
        raise ValueError('Incomplete Pipette source functions')
    cfg = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PipetteConfig')
    dimensions = [n for n in cfg.body if isinstance(n, ast.AnnAssign)
                  and n.target.id in ('cup_h', 'tube_h', 'tube_r')]
    if len(dimensions) != 3:
        raise ValueError('Incomplete Pipette vessel dimensions')
    selected.extend(dimensions)
    return selected


def source_digest():
    tree = ast.Module(body=source_nodes(), type_ignores=[])
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def source_namespace(sapien):
    """Load only reviewed geometry helpers; never import the task or its robots."""
    numpy_scalars = SimpleNamespace(
        pi=math.pi, sin=math.sin, cos=math.cos,
        linspace=lambda start, stop, count, endpoint=True: [
            start + (stop-start)*i/(count-1 if endpoint else count) for i in range(count)
        ],
    )
    namespace = {'sapien': sapien, 'np': numpy_scalars}
    tree = ast.Module(body=source_nodes(), type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), str(SOURCE), 'exec'), namespace)
    dimensions = {name: namespace[name] for name in ('cup_h', 'tube_h', 'tube_r')}
    namespace['cfg'] = SimpleNamespace(**dimensions)
    return namespace


class Material:
    def __init__(self, **values):
        self.base_color = [1., 1., 1., 1.]
        self.roughness = .5
        self.metallic = 0.
        self.transmission = 0.
        self.ior = 1.5
        self.specular = .5
        self.base_color_texture = None
        self.__dict__.update(values)


class Pose:
    def __init__(self, p=None, q=None):
        self.p = list(p if p is not None else [0., 0., 0.])
        self.q = list(q if q is not None else [1., 0., 0., 0.])


class Recorder:
    def __init__(self):
        self.visual_records = []
        self.collision_records = []

    def __getattr__(self, name):
        if not name.startswith('add_') or name.rsplit('_', 1)[-1] not in ('visual', 'collision'):
            raise AttributeError(name)

        def record(**kwargs):
            kind = name.rsplit('_', 1)[-1]
            item = SimpleNamespace(type=name[4:].rsplit('_', 1)[0], **kwargs)
            getattr(self, kind+'_records').append(item)
        return record


def procedural_records():
    fake = SimpleNamespace(Pose=Pose, render=SimpleNamespace(RenderMaterial=Material))
    ns = source_namespace(fake)
    result = {}
    for key, function in BUILDERS.items():
        builder = Recorder()
        if key in ('sample_cup', 'test_tube'):
            ns[function](builder, ns['cfg'])
        else:
            ns[function](builder)
        result[key] = builder
    return result


def bindings(object_id):
    return read_json(ARCHIVE / object_id / 'bindings.json')


def role_indices(binding):
    for role, definition in binding['roles'].items():
        if 'visual_indices' in definition:
            yield role, definition['visual_indices']


def parameters(catalog, object_id, role, scheme):
    if scheme == 'original':
        return {}
    owner = 'tip_cup' if object_id == 'pipette_stand' and role == 'tip_cup' else object_id
    return catalog['objects'][owner]['schemes'][scheme][role]


def apply_material(material, params):
    for key, value in params.items():
        if key == 'base_color_rgb':
            material.base_color = [*value, float(material.base_color[3])]
        elif key == 'base_color_alpha':
            material.base_color = [*material.base_color[:3], value]
        elif key in ('roughness', 'metallic'):
            setattr(material, key, value)
        else:
            raise ValueError(f'Unsupported appearance field: {key}')


def apply_records(records, object_id, scheme, catalog, *, load_texture=None):
    binding = bindings(object_id)
    if len(records) != binding['expected_visual_count']:
        raise ValueError(f'{object_id}: unexpected visual count {len(records)}')
    for role, indices in role_indices(binding):
        params = parameters(catalog, object_id, role, scheme)
        label = binding['roles'][role].get('candidate_color_texture') if params else None
        texture = (load_texture(ROOT / label['path'], label['mipmap_levels'])
                   if label and load_texture else label and label['path'])
        for index in indices:
            material = records[index].material
            if label:
                material.base_color_texture = texture
            apply_material(material, params)


def snapshot_records(records):
    # Restore the texture before the uniform update that uploads its mask.
    return [(record.material, {key: (getattr(record.material, key) if key == 'base_color_texture'
                                    else copy.deepcopy(getattr(record.material, key)))
                              for key in ('base_color_texture', 'base_color', 'roughness', 'metallic')})
            for record in records]


def restore_records(snapshot):
    for material, fields in snapshot:
        for key, value in fields.items():
            setattr(material, key, value if key == 'base_color_texture' else copy.deepcopy(value))


def private_material(sapien, source):
    material = sapien.render.RenderMaterial()
    for field in ('base_color', 'roughness', 'metallic', 'specular', 'transmission',
                  'ior', 'emission', 'transmission_roughness', 'base_color_texture',
                  'roughness_texture', 'metallic_texture', 'normal_texture',
                  'emission_texture', 'transmission_texture'):
        if hasattr(source, field):
            setattr(material, field, getattr(source, field))
    return material


def build_pipette_model(scene, urdf, sapien, namespace):
    loader = scene.create_urdf_loader()
    loader.fix_root_link, loader.scale = False, 1.
    articulations, actors, cameras = loader.parse(str(urdf))
    if len(articulations) != 1 or actors or cameras:
        raise ValueError('Expected one Pipette articulation and no extra actors/cameras')
    builder = articulations[0]
    links = {link.name: link for link in builder.link_builders}
    if len(links) != len(builder.link_builders) or set(links) != {'base', 'tip', 'plunger'}:
        raise ValueError('Unexpected or duplicate Pipette links')
    if any(len(links[name].visual_records) != count or len(links[name].collision_records) != count
           for name, count in {'base': 4, 'tip': 1, 'plunger': 1}.items()):
        raise ValueError('Unexpected Pipette visual/collision layout')
    records = links['base'].visual_records
    if len(records) < 2 or any(r.type != 'cylinder' for r in records[:2]):
        raise ValueError('Unexpected Pipette grip records')
    source = records[0].material
    if source is None or float(source.base_color[3]) != 1. or float(source.transmission) != 0.:
        raise ValueError('Pipette editable body must be opaque and nontransmissive')
    for field in ('base_color_texture', 'normal_texture', 'emission_texture', 'roughness_texture',
                  'metallic_texture', 'transmission_texture'):
        if getattr(source, field, None) is not None:
            raise ValueError('Textured Pipette body requires a separate marking audit')
    namespace['_lengthen_pipette_grip'](builder)
    records[0].material = private_material(sapien, source)
    actor = builder.build(fix_root_link=False)
    return SimpleNamespace(actor=actor, selected=[records[0]], builder=builder, links=links,
                           visual_records=[record for link in builder.link_builders for record in link.visual_records],
                           collision_records=[record for link in builder.link_builders for record in link.collision_records])


def inspect_pipette_asset(path):
    path = Path(path)
    if not path.is_file():
        return {'status': 'missing', 'path': str(path)}
    root = ET.parse(path).getroot()
    materials = {node.get('name'): node for node in root.findall('material')}
    links = []
    for link in root.findall('link'):
        visuals = []
        for index, visual in enumerate(link.findall('visual')):
            geometry = visual.find('geometry')
            material = visual.find('material')
            if material is not None and len(material) == 0:
                material = materials.get(material.get('name'), material)
            visuals.append({
                'index': index,
                'geometry': ET.tostring(geometry, encoding='unicode') if geometry is not None else None,
                'material': ET.tostring(material, encoding='unicode') if material is not None else None,
            })
        links.append({'name': link.get('name'), 'visuals': visuals})
    binding = bindings('pipette')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    readme_sha = hashlib.sha256(path.with_name('README.md').read_bytes()).hexdigest() if path.with_name('README.md').is_file() else None
    reviewed = (binding.get('binding_status') == 'verified' and binding.get('asset_sha256') == sha
                and binding.get('readme_sha256') == readme_sha and readme_sha is not None)
    return {'status': 'reviewed' if reviewed else 'available_unreviewed', 'path': str(path),
            'sha256': sha, 'links': links,
            'joints': [{'name': n.get('name'), 'type': n.get('type'),
                        'parent': n.find('parent').get('link'), 'child': n.find('child').get('link'),
                        'axis': n.find('axis').get('xyz') if n.find('axis') is not None else None,
                        'limit': dict(n.find('limit').attrib) if n.find('limit') is not None else None}
                       for n in root.findall('joint')],
            'link_count': len(links), 'visual_count': sum(len(link['visuals']) for link in links),
            'collision_count': len(root.findall('.//collision')),
            'external_mesh_or_texture_count': len(root.findall('.//mesh'))+len(root.findall('.//texture')),
            'mass_kg': {link.get('name'): float(link.find('inertial/mass').get('value')) for link in root.findall('link')},
            'readme_sha256': readme_sha}


def serialize(value):
    if isinstance(value, SimpleNamespace) or isinstance(value, (Pose, Material)):
        return {k: serialize(v) for k, v in vars(value).items()}
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serialize(v) for v in value]
    return value


def digest(value):
    raw = json.dumps(serialize(value), sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_catalog(catalog):
    rendering = catalog.get('rendering', {})
    bias = rendering.get('tip_depth_bias_ndc')
    if (rendering.get('shader_pack') != 'default' or isinstance(bias, bool)
            or not isinstance(bias, (float, int)) or not math.isfinite(bias) or not 0 < bias <= 2e-6):
        raise ValueError('Expected default raster shader and tip depth bias within (0, 2e-6]')
    if catalog['source_guard']['geometry_ast_sha256'] != source_digest():
        raise ValueError('Pipette source geometry changed; review bindings before use')
    expected = {'pipette', 'sample_cup', 'test_tube', 'tube_rack', 'pipette_stand', 'tip_cup'}
    if set(catalog['objects']) != expected:
        raise ValueError('Expected exactly six visible logical objects')
    candidates = catalog['candidate_ids']
    if len(candidates) < 2 or len(set(candidates)) != len(candidates) or 'original' in candidates:
        raise ValueError('Expected at least two distinct candidate IDs')
    textures = []
    for key, obj in catalog['objects'].items():
        if set(obj['schemes']) != {'original', *candidates} or obj['schemes']['original'] != {}:
            raise ValueError(f'{key}: original must use captured native materials')
        definition = bindings(key)
        editable = {role for role, entry in definition['roles'].items() if entry['editable']}
        for role, entry in definition['roles'].items():
            texture = entry.get('candidate_color_texture')
            if texture:
                path = (ROOT / texture['path']).resolve()
                if ((key, role) != ('pipette_stand', 'base_plate') or entry['visual_indices'] != [0]
                        or role not in editable or not path.is_relative_to(ARCHIVE.resolve())
                        or not path.is_file() or type(texture['mipmap_levels']) is not int
                        or texture['mipmap_levels'] < 1):
                    raise ValueError('Expected a single stand base-plate texture on its native box UVs')
                textures.append(texture['path'])
        for scheme in candidates:
            if set(obj['schemes'][scheme]) != editable:
                raise ValueError(f'{key}/{scheme}: incomplete role parameters')
            for params in obj['schemes'][scheme].values():
                if not set(params) <= {'base_color_rgb', 'base_color_alpha', 'roughness', 'metallic'}:
                    raise ValueError(f'{key}: unsupported material field')
                if 'base_color_rgb' not in params or len(params['base_color_rgb']) != 3:
                    raise ValueError(f'{key}: expected RGB')
                for field, value in params.items():
                    values = value if isinstance(value, list) else [value]
                    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or
                           not math.isfinite(v) or not 0 <= v <= 1 for v in values):
                        raise ValueError(f'{key}/{field}: values must be finite within [0, 1]')
                if key in ('sample_cup', 'test_tube'):
                    if set(params) != {'base_color_rgb', 'base_color_alpha'} or not .15 <= params['base_color_alpha'] <= .4:
                        raise ValueError('Glass candidates require RGB and controlled alpha within [.15, .4]')
                elif 'base_color_alpha' in params:
                    raise ValueError('Only glass roles may change alpha')
        for left, right in combinations(candidates, 2):
            difference = max(
                abs(a - b) for role in editable for a, b in zip(
                    obj['schemes'][left][role]['base_color_rgb'],
                    obj['schemes'][right][role]['base_color_rgb'], strict=True)
            )
            # Coordinated accents can overlap. Check for near-duplicate palettes
            # per object, then use actual camera pixels for formal acceptance.
            if difference < (.16 if key in ('sample_cup', 'test_tube') else .075):
                raise ValueError(f'{key}: palette separation too small for {left} and {right}')
    if len(textures) != 1 or catalog['new_textures'] != textures or catalog['new_uv']:
        raise ValueError('Unexpected texture inventory or UV change')
    return catalog


def load_catalog():
    return validate_catalog(read_json(CATALOG))
