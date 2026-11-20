"""Validate Pipette material bindings and assets without simulation imports or GPU use."""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipette_preview_materials import (
    CATALOG, ROOT, SOURCE, Material, apply_material, apply_records, bindings, build_pipette_model, digest, fresh_output,
    input_file_sha256, inspect_pipette_asset, load_catalog, procedural_records, restore_records, snapshot_records, source_digest,
)


def check_loader_contract():
    shared = Material(base_color=[.2, .3, .4, 1.])
    body = SimpleNamespace(type='cylinder', material=shared)
    rear = SimpleNamespace(type='cylinder', material=shared)
    plunger = SimpleNamespace(type='cylinder', material=shared)
    shoulder = SimpleNamespace(type='cylinder', material=shared)
    nozzle = SimpleNamespace(type='cylinder', material=shared)
    tip = SimpleNamespace(type='cylinder', material=shared)
    calls = []
    builder = SimpleNamespace(
        link_builders=[SimpleNamespace(name='base', visual_records=[body, rear, shoulder, nozzle], collision_records=[None]*4),
                       SimpleNamespace(name='tip', visual_records=[tip], collision_records=[None]),
                       SimpleNamespace(name='plunger', visual_records=[plunger], collision_records=[None])],
        build=lambda **kwargs: calls.append(kwargs),
    )
    # SAPIEN's native loader returns three lists; ManiSkill's dict is a different API.
    scene = SimpleNamespace(create_urdf_loader=lambda: SimpleNamespace(
        parse=lambda path: ([builder], [], [])))
    fake_sapien = SimpleNamespace(render=SimpleNamespace(RenderMaterial=Material))
    ns = {'_lengthen_pipette_grip': lambda b: calls.append('lengthen')}
    selected = build_pipette_model(scene, 'mock.urdf', fake_sapien, ns).selected
    apply_material(selected[0].material, {'base_color_rgb': [.1, .8, .2]})
    if shared.base_color != [.2, .3, .4, 1.] or body.material is shared or rear.material is not shared or plunger.material is not shared:
        raise ValueError('Pipette body mutation reached protected shared materials')
    if calls != ['lengthen', {'fix_root_link': False}]:
        raise ValueError('Pipette source extension/build contract mismatch')
    for invalid in (Material(base_color=[1., 1., 1., .5]), Material(transmission=.3),
                    Material(base_color_texture='marked.png')):
        body.material = invalid
        try:
            build_pipette_model(scene, 'mock.urdf', fake_sapien, ns)
        except ValueError:
            continue
        raise ValueError('Unsafe Pipette body was accepted')


def task_actor_sets():
    folder = SOURCE.parent
    classes = (
        ('PipetteTransferLong-Sharpa-v1', SOURCE, 'PipetteTransferLongEnv'),
        ('PipetteTransferAspirateLiquid-Sharpa-v1', folder/'pipette_transfer_aspirate_liquid.py',
         'PipetteTransferAspirateLiquidEnv'),
        ('PipetteTransferDispenseLiquid-Sharpa-v1', folder/'pipette_transfer_dispense_liquid.py',
         'PipetteTransferDispenseLiquidEnv'),
    )
    names = {'LOAD_CUP': 'sample_cup', 'LOAD_TUBE': 'test_tube', 'LOAD_RACK': 'tube_rack',
             'LOAD_PIPETTE_STAND': 'pipette_stand', 'LOAD_PIPETTE': 'pipette'}
    result = {}
    defaults = {}
    for task, path, class_name in classes:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
        flags = defaults.copy()
        for node in cls.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in names:
                        flags[target.id] = ast.literal_eval(node.value)
        if not defaults:
            defaults = flags.copy()
        result[task] = {names[name] for name, enabled in flags.items() if enabled}
    return result


def check(historical_preview_root=None):
    catalog = load_catalog()
    check_loader_contract()
    native = procedural_records()
    checks = []
    summary = {}
    for key, builder in native.items():
        binding = bindings(key)
        records = builder.visual_records
        if len(records) != binding['expected_visual_count']:
            raise ValueError(f'{key}: visual count mismatch')
        indices = [i for role in binding['roles'].values() for i in role['visual_indices']]
        if sorted(indices) != list(range(len(records))):
            raise ValueError(f'{key}: visual roles must be complete and disjoint')
        collisions = digest(builder.collision_records)
        geometry = digest([{k: v for k, v in vars(r).items() if k != 'material'} for r in records])
        colors = [list(r.material.base_color) for r in records]
        original_hash = digest(records)
        snapshot = snapshot_records(records)
        for scheme in catalog['candidate_ids']:
            apply_records(records, key, scheme, catalog)
            restore_records(snapshot)
            if digest(records) != original_hash:
                raise ValueError(f'{key}: native material restoration failed')
        for scheme in ['original', *catalog['candidate_ids']]:
            candidate = copy.deepcopy(builder)
            apply_records(candidate.visual_records, key, scheme, catalog)
            if digest(candidate.collision_records) != collisions:
                raise ValueError(f'{key}: collisions changed')
            if digest([{k: v for k, v in vars(r).items() if k != 'material'}
                       for r in candidate.visual_records]) != geometry:
                raise ValueError(f'{key}: visual geometry changed')
            for before, after in zip(records, candidate.visual_records):
                if (key not in ('sample_cup', 'test_tube') or scheme == 'original') and float(before.material.base_color[3]) != float(after.material.base_color[3]):
                    raise ValueError(f'{key}: alpha changed')
                if key in ('sample_cup', 'test_tube'):
                    for field in ('roughness', 'metallic', 'transmission', 'ior', 'specular'):
                        if getattr(before.material, field) != getattr(after.material, field):
                            raise ValueError(f'{key}: protected glass field changed: {field}')
            if scheme == 'original' and digest(candidate.visual_records) != digest(records):
                raise ValueError(f'{key}: original is not an exact material no-op')
            if scheme != 'original' and colors == [list(r.material.base_color) for r in candidate.visual_records]:
                raise ValueError(f'{key}: candidate did not change any RGB')
        summary[key] = {'visuals': len(records), 'collisions': len(builder.collision_records),
                        'visual_geometry_sha256': geometry, 'collision_sha256': collisions}
    stand = bindings('pipette_stand')
    tip = bindings('tip_cup')
    if stand['roles']['tip_cup']['visual_indices'] != tip['roles']['tip_cup']['visual_indices'] or tip['parent_object'] != 'pipette_stand':
        raise ValueError('tip_cup must reference the parent visual once')
    actual_task_sets = task_actor_sets()
    if set(catalog['task_objects']) != set(actual_task_sets):
        raise ValueError('Unexpected task mapping')
    for task, objects in catalog['task_objects'].items():
        if len(objects) != len(set(objects)) or 'tip_cup' in objects or 'liquid_state' in objects:
            raise ValueError(f'{task}: duplicated or non-actor object')
        if set(objects) != actual_task_sets[task]:
            raise ValueError(f'{task}: task source load flags differ from catalog')
    # Transmission is unused by the raster path; only controlled glass alpha is allowed.
    from pipette_preview_materials import validate_catalog
    invalid = copy.deepcopy(catalog)
    invalid['objects']['sample_cup']['schemes'][catalog['candidate_ids'][0]]['wall']['transmission'] = .9
    try:
        validate_catalog(invalid)
    except ValueError:
        checks.append('glass_field_rejection')
    else:
        raise ValueError('Invalid glass parameter was accepted')
    for path in Path(__file__).resolve().parent.glob('*pipette*.py'):
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    model_evidence = {}
    if historical_preview_root is not None:
        archived = sorted(historical_preview_root.glob('*/previews/native_assets_*/evidence.json'))
        if not archived:
            raise ValueError('No archived native model evidence found')
        current_sources = input_file_sha256()
        catalog_sha = hashlib.sha256(CATALOG.read_bytes()).hexdigest()
        for receipt_path in archived:
            key = receipt_path.parents[2].name
            if key not in catalog['objects'] or key in model_evidence:
                raise ValueError(f'Ambiguous archived object: {key}')
            evidence = json.loads(receipt_path.read_text(encoding='utf-8'))
            manifest = evidence['source_manifest']
            current_identity = (manifest.get('input_file_sha256') == current_sources
                                and manifest['catalog_sha256'] == catalog_sha
                                and manifest['source_geometry_ast_sha256'] == source_digest())
            if (manifest['objects'][0]['object_id'] != key
                    or manifest['objects'][0]['restored_rgb_max_abs_difference'] != 0
                    or evidence['comparison_sha256'] != hashlib.sha256(receipt_path.with_name('comparison.png').read_bytes()).hexdigest()):
                raise ValueError(f'{key}: archived model artifact failed integrity verification')
            model_evidence[key] = {'render_checks': evidence['render_checks'],
                                   'visual_review': evidence['visual_review'],
                                   'identity_scope': f'{len(current_sources)}_actual_files_sha256' if current_identity
                                   else 'historical_not_current_inputs'}
    if model_evidence:
        checks.append('archived_model_evidence_identity')
    checks += ['catalog_roles', 'source_geometry_guard', 'complete_disjoint_procedural_bindings',
               'original_noop', 'native_material_restoration', 'visual_geometry_unchanged', 'collision_records_unchanged',
               'original_glass_alpha_restored_candidate_alpha_controlled', 'glass_other_optics_unchanged',
               'candidate_rgb_separation', 'tip_cup_parent_reference',
               'task_actor_sets', 'native_loader_tuple_mock', 'pipette_private_material_mock',
               'pipette_transparency_texture_rejection_mock', 'python_syntax']
    asset = ROOT / 'tasks/assets/task_object_meshes/pipette/mobility.urdf'
    asset_audit = inspect_pipette_asset(asset)
    if asset_audit['status'] == 'reviewed':
        if (asset_audit['link_count'], asset_audit['visual_count'], asset_audit['collision_count'],
                asset_audit['external_mesh_or_texture_count']) != (3, 6, 6, 0):
            raise ValueError('Audited Pipette source structure changed')
        checks.append('original_pipette_asset_identity_and_structure')
    return {
        'status': 'passed', 'scope': 'CPU material, binding and asset checks only',
        'catalog': str(CATALOG.relative_to(ROOT)), 'geometry_ast_sha256': source_digest(),
        'checks': checks, 'procedural_objects': summary,
        'archived_model_previews': model_evidence,
        'pipette_asset_present': asset.is_file(),
        'pipette_asset_status': asset_audit['status'],
        'not_checked': ['native rendering', 'task dynamics', 'CUDA isolation'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--historical-preview-root', type=Path)
    args = parser.parse_args()
    result = check(args.historical_preview_root)
    raw = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)+'\n'
    if args.output:
        fresh_output(args.output, file=True).write_text(raw, encoding='utf-8')
    print(raw, end='')


if __name__ == '__main__':
    main()
