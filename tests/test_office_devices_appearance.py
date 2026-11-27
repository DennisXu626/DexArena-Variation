"""CPU contracts for Office selections and lossless multi-material preparation."""
import copy
import ast
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('office_devices_under_test', ROOT / 'tasks/office_desk/devices_appearance.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Material:
    def __init__(self, color=(.4, .5, .6, 1.)):
        for key in M.MATERIAL_FIELDS:
            setattr(self, key, None if key.endswith('_texture') else .0)
        self.base_color = list(color)
        self.roughness, self.metallic, self.specular, self.ior = .63, .17, .28, 1.5
        self.emission = [0., 0., 0., 0.]


class Part:
    def __init__(self, material, vertices=None, triangles=None, normals=None, uv=None):
        self.material = material
        self.vertices = np.asarray(vertices if vertices is not None else [[0,0,0],[1,0,0],[0,1,0]], dtype=np.float32)
        self.triangles = np.asarray(triangles if triangles is not None else [[0,1,2]], dtype=np.uint32)
        self.normals = np.asarray(normals if normals is not None else [[0,0,1]]*3, dtype=np.float32)
        self.uv = np.asarray(uv if uv is not None else [[0,0],[1,0],[0,1]], dtype=np.float32)

    def get_vertex_normal(self):
        return self.normals.copy()

    def get_vertex_uv(self):
        return self.uv.copy()


class Texture:
    def __init__(self, pixels, format='R8G8B8A8Unorm', mipmap_levels=1,
                 filter_mode='linear', address_mode='repeat', is_srgb=True):
        self.filename = ''
        self.format, self.mipmap_levels, self.is_srgb = format, mipmap_levels, is_srgb
        self.filter_mode, self.address_mode = filter_mode, address_mode
        self.height, self.width, self.channels = pixels.shape
        self.pixels = pixels.copy()

    def download(self):
        return self.pixels.copy()

    def upload(self, pixels):
        assert pixels.shape == self.pixels.shape and pixels.dtype == self.pixels.dtype
        self.pixels = pixels.copy()


class Shape:
    def __init__(self, vertices=None, triangles=None, normals=None, uv=None, material=None, parts=None):
        self.parts = parts if parts is not None else [Part(material, vertices, triangles, normals, uv)]
        self.scale = [1., 2., 3.]
        self.local_pose = 'source_pose'
        self.front_face = 'clockwise'
        self.name = 'screen_frame'

    def clone(self):
        return copy.copy(self)


class Body:
    def __init__(self):
        self.render_shapes = []
        self.name, self.visibility, self.shading_mode = 'source_body', .8, 0
        self.is_render_id_disabled = False

    def attach(self, shape):
        self.render_shapes.append(shape)


def adapter(config=None, oid='laptop'):
    result = M.OfficeDevicesAppearance({'enabled': True, **(config or {})}, 2, oid, Path('unused'))
    role = result.definition['editable_role']
    for i in range(2):
        mat = Material((.2 + .1*i, .3, .4, 1.))
        native = {key: copy.deepcopy(getattr(mat, key)) for key in M.FIELDS}
        result.bindings[i] = [(role, Part(mat), mat, native)]
    return result


def state(value):
    return [[{key: copy.deepcopy(getattr(mat, key)) for key in M.MATERIAL_FIELDS}
             for _, _, mat, _ in rows] if rows is not None else None for rows in value.bindings]


def reset(value, selected, request=None):
    value.finish_reset(np.asarray(selected), {} if request is None else {'office_devices_appearance': request})


class OfficeSelections(unittest.TestCase):
    def test_override_precedence_and_records(self):
        a = adapter({'scheme_id':'original','per_env':{'1':{'scheme_id':'variant_1'}}})
        reset(a,[0,1]);self.assertEqual(a.schemes,['original','variant_1'])
        reset(a,[1],{'scheme_id':'variant_2'});self.assertEqual(a.schemes,['original','variant_2'])
        reset(a,[1],{'scheme_id':'variant_2','per_env':{'1':{'scheme_id':'original'}}})
        self.assertEqual(a.schemes,['original','original']);self.assertEqual(a.episodes,[1,3])
        self.assertEqual([r['episode_index'] for r in a.records if r['env_idx']==1],[1,2,3])

    def test_explicit_and_render_read_do_not_draw_rng(self):
        a=adapter({'scheme_id':'variant_2'});before=[copy.deepcopy(r.bit_generator.state) for r in a.rng]
        reset(a,[0,1]);state(a)
        self.assertEqual(before,[r.bit_generator.state for r in a.rng])

    def test_original_restores_actual_native_and_other_pbr(self):
        for oid in ('laptop','keyboard'):
            a=adapter({'scheme_id':'variant_1'},oid);native=state(a)
            reset(a,[0,1]);self.assertNotEqual(state(a),native)
            reset(a,[0,1],{'scheme_id':'original'});self.assertEqual(state(a),native)

    def test_two_private_strips_upload_pixels_without_rebinding_or_changing_source(self):
        a=adapter({'scheme_id':'variant_1'},'keyboard')
        original=np.full((3,4,4),75,dtype=np.uint8);original[...,3]=255
        source=Texture(original);source.filename='unchanged_native_atlas.jpg'
        render=SimpleNamespace(RenderTexture2D=Texture)
        with patch.dict(sys.modules,{'sapien':SimpleNamespace(render=render),'sapien.render':render}):
            strips=[M.OfficeStripTexture(source),M.OfficeStripTexture(source)]
        for i in range(2):
            material=Material((1.,1.,1.,1.));material.base_color_texture=strips[i].texture
            captured={field:copy.deepcopy(getattr(material,field)) for field in M.FIELDS}
            a.bindings[i].append((M.STRIP_ROLE,Part(material),material,captured))
            a.prepared[i]=M.OfficePartMaterials({'runtime_source_sha256': {}}, Path('.'))
            a.prepared[i].strip_texture=strips[i]
        self.assertIsNot(strips[0].texture,strips[1].texture)
        reset(a,[1])
        np.testing.assert_array_equal(strips[0].texture.download(),original)
        self.assertFalse(np.array_equal(strips[1].texture.download(),original))
        reset(a,[0],{'scheme_id':'variant_2'})
        self.assertFalse(np.array_equal(strips[0].texture.download(),strips[1].texture.download()))
        np.testing.assert_array_equal(source.download(),original)
        reset(a,[0,1],{'scheme_id':'original'})
        for i in range(2):
            self.assertIs(a.bindings[i][-1][2].base_color_texture,strips[i].texture)
            np.testing.assert_array_equal(strips[i].texture.download(),original)

    def test_later_invalid_request_is_atomic_for_rng_materials_records(self):
        for bad in ({'mode':'explicit','scheme_id':'unknown'},{'mode':'random_choice','scheme_ids':[]},{'mode':'unknown'}):
            a=adapter({'mode':'random_choice','scheme_ids':['original','variant_1'],'per_env':{'1':bad}})
            original=state(a);rng=[copy.deepcopy(r.bit_generator.state) for r in a.rng]
            with self.assertRaises(ValueError):reset(a,[0,1])
            self.assertEqual(state(a),original);self.assertEqual([r.bit_generator.state for r in a.rng],rng)
            self.assertEqual(a.records,[]);self.assertEqual(a.episodes,[0,0])

    def test_later_unbound_request_is_atomic(self):
        a=adapter({'mode':'random_choice','scheme_ids':['original','variant_1']});a.bindings[1]=None
        original=state(a);rng=copy.deepcopy(a.rng[0].bit_generator.state)
        with self.assertRaises(RuntimeError):reset(a,[0,1])
        self.assertEqual(state(a),original);self.assertEqual(a.rng[0].bit_generator.state,rng)

    def test_invalid_indices_and_reset_only_fields(self):
        for selected in ([],[-1],[2],[0,0],[True],[1,0]):
            a=adapter()
            with self.assertRaises(ValueError):reset(a,selected)
            self.assertEqual(a.records,[])
        for request in ({'seed':8},{'enabled':False},{'per_env':{'-1':{}}},{'per_env':{'2':{}}},{'per_env':{'01':{}}}):
            a=adapter()
            with self.assertRaises(ValueError):reset(a,[0,1],request)
            self.assertEqual(a.records,[])

    def test_per_env_requires_canonical_keys_and_dictionary_requests(self):
        invalid = (None, [], {'-1': {}}, {'2': {}}, {'01': {}}, {'env1': {}},
                   {1: {}}, {'1': None}, {'1': []}, {'1': {'seed': 7}})
        for per_env in invalid:
            with self.subTest(per_env=per_env):
                with self.assertRaisesRegex(ValueError, 'per_env|common construction'):
                    adapter({'per_env': per_env})
                with self.assertRaises(ValueError):
                    M.appearance_enabled({'enabled': False, 'per_env': per_env}, 2)
                a=adapter({'mode':'random_choice','scheme_ids':['original','variant_1']})
                before=(state(a),[copy.deepcopy(r.bit_generator.state) for r in a.rng])
                with self.assertRaises(ValueError):reset(a,[0],{'per_env':per_env})
                self.assertEqual((state(a),[r.bit_generator.state for r in a.rng]),before)
                self.assertEqual((a.records,a.episodes),([],[0,0]))

    def test_independent_reproducible_per_environment_streams(self):
        config={'mode':'random_choice','scheme_ids':['original','variant_1','variant_2'],'seed':71}
        a,b=adapter(config),adapter(config);reset(a,[0,1]);reset(b,[0,1])
        original=state(a)[0];rng=copy.deepcopy(a.rng[0].bit_generator.state);records=copy.deepcopy(a.records)
        for _ in range(24):reset(a,[1])
        self.assertEqual(state(a)[0],original);self.assertEqual(a.rng[0].bit_generator.state,rng)
        self.assertEqual([r for r in a.records if r['env_idx']==0],[r for r in records if r['env_idx']==0])
        reset(a,[0]);reset(b,[0]);self.assertEqual(a.schemes[0],b.schemes[0])


class OfficePartPreparation(unittest.TestCase):
    def test_keycap_material_keeps_atlas_sampler_uv_and_restores_original_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            mesh = root / 'key.obj'
            mesh.write_bytes(b'original key')
            atlas = root / 'atlas.jpg'
            atlas.write_bytes(b'original key atlas')
            pixels = np.array([[[235, 235, 235, 255], [150, 150, 150, 255]],
                               [[18, 18, 18, 255], [220, 220, 220, 255]]], dtype=np.uint8)
            texture = Texture(pixels)
            texture.filename = str(atlas)
            pixels = texture.download()
            material = Material((1., 1., 1., 1.))
            material.base_color_texture = texture
            part = Part(material)
            native_body = Body()
            native_body.attach(Shape(parts=[part]))
            digest = M.triangle_positions_hash(part.vertices, part.triangles)
            definition = {'editable_role': 'keycap', 'base_color_texture': atlas.name,
                          'runtime_source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                    for p in (mesh, atlas)},
                          'part_bindings': [{'link': 'link_1', 'index': 0, 'name': 'key',
                                             'mesh': mesh.name, 'native_part_count': 1,
                                             'editable_slots': [{'material': 'cap', 'triangles': 1,
                                                                 'diffuse': [1., 1., 1.],
                                                                 'position_triangles_sha256': digest}]}]}
            render = SimpleNamespace(RenderBodyComponent=Body, RenderMaterial=Material, RenderShapeTriangleMesh=Shape,
                                     RenderTexture2D=Texture)
            record = SimpleNamespace(type='file', name='key', filename=str(mesh), material=None)
            link = SimpleNamespace(name='link_1', visual_records=[record], build_render_component=lambda: native_body)
            with patch.dict(sys.modules, {'sapien': SimpleNamespace(render=render), 'sapien.render': render}):
                prepared = M.OfficePartMaterials(definition, root)
                prepared.install(SimpleNamespace(link_builders=[link]))
                link.build_render_component()
            _, rebuilt, mutable, _ = prepared.bindings[0]
            chromatic = [.63, .58, .55, 1.]
            private = prepared.keycap_textures['keycap']
            prepared.apply_texture('keycap', mutable, chromatic)
            self.assertIsNot(mutable, material)
            self.assertIs(mutable.base_color_texture, private.texture)
            self.assertIsNot(mutable.base_color_texture, texture)
            self.assertEqual(M.texture_descriptor(private.texture), M.texture_descriptor(texture))
            self.assertIsNone(prepared.strip_texture)
            changed = private.texture.download()
            self.assertFalse(np.array_equal(changed, pixels))
            np.testing.assert_array_equal(changed[..., 3], pixels[..., 3])
            self.assertEqual(int(changed[0, 0, 0]) - int(changed[0, 1, 0]), 85)
            np.testing.assert_array_equal(changed[1, 0], pixels[1, 0])
            np.testing.assert_array_equal(texture.download(), pixels)
            prepared.apply_texture('keycap', mutable, None)
            np.testing.assert_array_equal(private.texture.download(), pixels)
            np.testing.assert_array_equal(rebuilt.get_vertex_uv(), part.get_vertex_uv())
            self.assertEqual(material.base_color, [1., 1., 1., 1.])

    def test_triangle_partition_preserves_indices_attributes_and_texture_handle(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as folder, patch.object(M, 'ROOT', Path(folder).resolve()):
            root=M.ROOT;source=root/'mesh.obj';source.write_bytes(b'partition source')
            texture_path=root/'texture.jpg';texture_path.write_bytes(b'unchanged texture bytes')
            vertices=np.asarray([[0,0,0],[1,0,0],[0,1,0],[2,0,0],[3,0,0],[2,1,0]],dtype=np.float32)
            triangles=np.asarray([[0,1,2],[3,4,5]],dtype=np.uint32)
            uv=np.asarray([[.1,.8],[.2,.8],[.1,.9],[.7,.1],[.8,.1],[.7,.2]],dtype=np.float32)
            material=Material((1.,1.,1.,1.))
            texture=Texture(np.full((16,16,4),255,dtype=np.uint8));texture.filename=str(texture_path)
            material.base_color_texture=texture
            part=Part(material,vertices,triangles,np.asarray([[0,0,1]]*6,dtype=np.float32),uv)
            native=Body();native.attach(Shape(parts=[part]))
            mask=np.zeros((16,16),dtype=np.uint8);mask[10:15,10:15]=255
            rows=[[[10,15]] if 10<=y<15 else [] for y in range(16)]
            proof=root/'proof.json';proof.write_text(__import__('json').dumps({'size':[16,16],'key_mask_rows':rows}),encoding='utf-8')
            partition={'proof':proof.name,'proof_sha256':hashlib.sha256(proof.read_bytes()).hexdigest(),
                'texture':'texture.jpg','texture_sha256':hashlib.sha256(texture_path.read_bytes()).hexdigest(),
                'key_uv_mask_sha256':hashlib.sha256(mask.tobytes()).hexdigest(),'protected_mask_sha256':hashlib.sha256(mask.tobytes()).hexdigest(),
                'margin_texels':0,'mipmap_levels':1,'safe_triangles':1,
                'coverage_method':'exact_integer_sat_closed_bilinear_support',
                'expected_sampler':{'address_mode':'repeat','filter_mode':'linear','is_srgb':True},
                'source_uv_to_native':'assimp_flip_v_float32','native_uv_to_image':'direct_uv_top_left',
                'safe_native_triangle_position_uv_sha256':M.triangle_position_uv_ids(vertices,uv,triangles[:1])}
            definition={'editable_role':'shell','runtime_source_sha256':{'mesh.obj':hashlib.sha256(source.read_bytes()).hexdigest()},
                'part_bindings':[{'link':'link_0','index':0,'name':'frame','mesh':'mesh.obj','native_part_count':1,
                    'editable_slots':[{'material':'shell','triangles':2,'diffuse':[1.,1.,1.],
                        'position_triangles_sha256':M.triangle_positions_hash(vertices,triangles),'role':'shell_strip','partition':partition}]}]}
            render=SimpleNamespace(RenderBodyComponent=Body,RenderMaterial=Material,RenderShapeTriangleMesh=Shape,RenderTexture2D=Texture)
            with patch.dict(sys.modules,{'sapien':SimpleNamespace(render=render),'sapien.render':render}):
                record=SimpleNamespace(type='file',name='frame',filename=str(source),material=None)
                link=SimpleNamespace(name='link_0',visual_records=[record],build_render_component=lambda:native)
                prepared=M.OfficePartMaterials(definition,root);prepared.install(SimpleNamespace(link_builders=[link]));body=link.build_render_component()
            self.assertEqual(len(body.render_shapes),2)
            rebuilt=[shape.parts[0] for shape in body.render_shapes]
            np.testing.assert_array_equal(np.concatenate([p.triangles for p in rebuilt]),triangles)
            for p in rebuilt:
                np.testing.assert_array_equal(p.vertices,vertices);np.testing.assert_array_equal(p.get_vertex_uv(),uv)
            self.assertIs(rebuilt[0].material.base_color_texture,prepared.strip_texture.texture)
            self.assertIsNot(prepared.strip_texture.texture,texture)
            np.testing.assert_array_equal(prepared.strip_texture.texture.download(),texture.download())
            self.assertIs(rebuilt[1].material.base_color_texture,texture)
            self.assertIsNot(rebuilt[0].material,material);self.assertIs(rebuilt[1].material,material)
            rebuilt[0].material.base_color=[.1,.2,.3,1.]
            self.assertEqual(material.base_color,[1.,1.,1.,1.]);self.assertEqual(texture_path.read_bytes(),b'unchanged texture bytes')
            np.testing.assert_array_equal(np.concatenate([M.triangle_attribute_rows(p) for p in rebuilt]),M.triangle_attribute_rows(part))
            proof.write_text('{}',encoding='utf-8')
            with self.assertRaises(RuntimeError):prepared._partition_mask(part,partition)

    def test_only_proven_part_is_private_and_all_arrays_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'mesh.obj';source.write_bytes(b'source identity')
            editable=Material((.4,.5,.6,1.));protected=Material((.1,.1,.1,1.));protected.base_color_texture=SimpleNamespace(address_mode="repeat", filter_mode="linear", mipmap_levels=1)
            source_shape=Shape(parts=[Part(editable),Part(protected)])
            native=Body();native.attach(source_shape)
            definition={'editable_role':'shell','runtime_source_sha256':{'mesh.obj':hashlib.sha256(source.read_bytes()).hexdigest()},'part_bindings':[{'link':'link_0','index':0,'name':'frame','mesh':'mesh.obj','native_part_count':2,'editable_slots':[{'material':'body','triangles':1,'diffuse':[.4,.5,.6], 'position_triangles_sha256':M.triangle_positions_hash(source_shape.parts[0].vertices,source_shape.parts[0].triangles)}]}]}
            record=SimpleNamespace(type='file',name='frame',filename=str(source),material=None)
            render=SimpleNamespace(RenderBodyComponent=Body,RenderMaterial=Material,RenderShapeTriangleMesh=Shape)
            package=SimpleNamespace(render=render)
            with patch.dict(sys.modules,{'sapien':package,'sapien.render':render}):
                prepared=[]
                for _ in range(2):
                    lb=SimpleNamespace(name='link_0',visual_records=[record],build_render_component=lambda:native)
                    p=M.OfficePartMaterials(definition,root);p.install(SimpleNamespace(link_builders=[lb]));body=lb.build_render_component();prepared.append(p)
                    self.assertEqual(len(body.render_shapes),2)
                    self.assertIs(body.render_shapes[1].parts[0].material,protected)
                    self.assertIsNone(record.material)
                    for rebuilt,part in zip(body.render_shapes,source_shape.parts):
                        np.testing.assert_array_equal(rebuilt.parts[0].vertices,part.vertices)
                        np.testing.assert_array_equal(rebuilt.parts[0].get_vertex_uv(),part.get_vertex_uv())
                        self.assertEqual(rebuilt.scale,source_shape.scale)
                        self.assertEqual(rebuilt.local_pose,source_shape.local_pose)
                first,second=prepared
                self.assertIsNot(first.bindings[0][2],editable)
                self.assertIsNot(first.bindings[0][2],second.bindings[0][2])
                first.bindings[0][2].base_color=[1.,0.,0.,1.]
                self.assertEqual(editable.base_color,[.4,.5,.6,1.])
                self.assertEqual(second.bindings[0][2].base_color,[.4,.5,.6,1.])
                editable.base_color_texture=object()
                lb=SimpleNamespace(name='link_0',visual_records=[record],build_render_component=lambda:native)
                p=M.OfficePartMaterials(definition,root);p.install(SimpleNamespace(link_builders=[lb]))
                with self.assertRaises(RuntimeError):lb.build_render_component()
            source.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):M.OfficePartMaterials(definition,root)


class PublicOfficeReset(unittest.TestCase):
    CASES = (
        ('TypeKeys', 'type_keys', 'office_devices_appearance', 'keyboard', ('variant_1', 'variant_2'),
         ('ochre_matte', 'indigo_satin')),
        ('OpenLaptop', 'open_laptop', 'office_devices_appearance', 'laptop', ('variant_1', 'variant_2'),
         ('terracotta_matte', 'petrol_satin')),
        ('ClickMouse', 'click_mouse', 'mouse_appearance', 'mouse', ('ivory_matte', 'navy_satin'),
         ('ivory_matte', 'navy_satin')),
    )

    @classmethod
    def setUpClass(cls):
        class Native:
            def reset(self, seed=None, options=None):
                self.calls.append((seed, options))
                self.task_draws += 1
                self.state_writes += 1
                if options is None:
                    options = {}
                if 'reset_to_env_states' not in options:
                    indices = options.get('env_idx', range(self.num_envs))
                    ids = list(map(int, indices))
                    for appearance in (self.appearance, getattr(self, '_office_keyboard_appearance', None)):
                        if appearance is not None:
                            for index in ids:
                                if appearance.bindings[index] is None:
                                    appearance.bindings[index] = []
                            appearance.finish_reset(ids, options)
                return 'observations', 'info'

            def __setattr__(self, name, value):
                if name in ('_furniture_reset_env_idx', '_furniture_reset_scope_masks'):
                    self.scope_writes += 1
                super().__setattr__(name, value)

        def source(path):
            return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))

        furniture = ROOT / 'tasks/furniture_assembly/reset_scope.py'
        furniture_nodes = [
            node for node in source(furniture).body
            if getattr(node, 'name', None) in ('FurnitureResetScopeMixin', 'is_full_reset')
        ]
        namespace = {'BaseEnv': Native, 'torch': torch, 'np': np, '_MISSING': object()}
        exec(compile(ast.Module(body=furniture_nodes, type_ignores=[]), str(furniture), 'exec'), namespace)

        office = ROOT / 'tasks/office_desk'
        scope_path = office / 'reset_scope.py'
        scope = next(node for node in source(scope_path).body if isinstance(node, ast.ClassDef))
        namespace.update(resolve_reset_requests=M.resolve_reset_requests,
                         validate_reset_indices=M.validate_reset_indices,
                         validate_reset_override=M.validate_reset_override)
        exec(compile(ast.Module(body=[scope], type_ignores=[]), str(scope_path), 'exec'), namespace)

        mouse_spec = importlib.util.spec_from_file_location('office_mouse_under_test', office / 'mouse_appearance.py')
        mouse = importlib.util.module_from_spec(mouse_spec)
        with patch.dict(sys.modules, {'tasks.office_desk.devices_appearance': M}):
            mouse_spec.loader.exec_module(mouse)
        namespace.update(OfficeDevicesAppearance=M.OfficeDevicesAppearance, MouseAppearance=mouse.MouseAppearance,
                         appearance_enabled=M.appearance_enabled, DEFAULT_ROBOT_UID='mock',
                         KEYBOARD_ASSET_DIR=office, LAPTOP_ASSET_DIR=office)
        cls.env_classes = {}
        for task, stem, key, *_ in cls.CASES:
            task_path = office / f'office_desk_{stem}.py'
            actual = next(node for node in source(task_path).body
                          if isinstance(node, ast.ClassDef) and node.name == f'OfficeDesk{task}Env')
            # Preserve the task's inheritance, constructor key and adapter initialization.
            assert any(isinstance(dec, ast.Call) and ast.unparse(dec.func) == 'register_task'
                       and ast.literal_eval(dec.args[0]) == f'OfficeDesk{task}' for dec in actual.decorator_list)
            actual.decorator_list = []
            constructor = next(node for node in actual.body if isinstance(node, ast.FunctionDef)
                               and node.name == '__init__')
            appearance_fields = {f'self._{key}', 'self._office_keyboard_appearance'}
            constructor.body = [
                node for node in constructor.body if isinstance(node, ast.Assign)
                and any(ast.unparse(target) in appearance_fields for target in node.targets)
            ]
            assert len(constructor.body) == (1 if task == 'ClickMouse' else 2)
            actual.body = [constructor] + [node for node in actual.body
                                           if isinstance(node, ast.FunctionDef) and node.name == 'reset']
            exec(compile(ast.Module(body=[actual], type_ignores=[]), str(task_path), 'exec'), namespace)
            cls.env_classes[task] = namespace[actual.name]

    def env(self, task, key, config=None, *, keycaps=None):
        kwargs = {} if config is None else {key: config}
        if keycaps is not None:
            kwargs['office_keyboard_appearance'] = keycaps
        instance = self.env_classes[task](num_envs=2, **kwargs)
        instance.appearance = getattr(instance, f'_{key}')
        instance.num_envs = 2
        instance._elapsed_steps = torch.zeros(2, dtype=torch.int32)
        instance._reconfig_counter = 1
        instance.reconfiguration_freq = 0
        instance.scene = object()
        instance.gpu_sim_enabled = False
        instance.calls = []
        instance.task_draws = instance.state_writes = instance.scope_writes = 0
        return instance

    def reject(self, env, message, options=None):
        adapter = env.appearance
        before = None if adapter is None else (
            copy.deepcopy([rng.bit_generator.state for rng in adapter.rng]),
            tuple(adapter.bindings), adapter.schemes.copy(), adapter.episodes.copy(), adapter.records.copy())
        with self.assertRaisesRegex(ValueError, message):
            env.reset(options=options)
        self.assertEqual((env.calls, env.task_draws, env.state_writes, env.scope_writes), ([], 0, 0, 0))
        if adapter is not None:
            self.assertEqual(before, ([rng.bit_generator.state for rng in adapter.rng], tuple(adapter.bindings),
                                      adapter.schemes, adapter.episodes, adapter.records))

    def test_later_explicit_and_random_errors_do_not_enter_native_reset(self):
        for task, _, key, _, (first, second), _ in self.CASES:
            for later, message in (
                ({'mode': 'explicit', 'scheme_id': second + '_typo'}, 'env 1.*_typo'),
                ({'scheme_ids': [first, second, 'typo']}, 'env 1.*typo'),
                ({'scheme_ids': [first, {}]}, 'env 1.*scheme|scheme.*env 1'),
                ({'scheme_ids': []}, 'env 1.*nonempty list'),
                ({'mode': 'typo_mode'}, 'env 1.*typo_mode'),
            ):
                with self.subTest(task=task, later=later):
                    env = self.env(task, key, {'enabled': True})
                    self.reject(env, message, {key: {'mode': 'random_choice', 'scheme_ids': [first, second],
                                                    'per_env': {'1': later}}})

    def test_constructor_selection_with_unbound_adapter_and_state_restoration(self):
        for task, _, key, _, (first, second), _ in self.CASES:
            with self.subTest(task=task):
                env = self.env(task, key, {'enabled': True, 'scheme_id': first,
                                           'per_env': {'1': {'scheme_id': 'ctor_typo'}}})
                self.assertEqual(env.appearance.bindings, [None, None])
                self.reject(env, 'env 1.*ctor_typo')
                restore = {'reset_to_env_states': {'env_states': object()}}
                self.reject(env, 'state restoration', {**restore, key: {'scheme_id': second}})
                self.assertEqual(env.reset(options=restore), ('observations', 'info'))
                self.assertIs(env.calls[0][1], restore)
                self.assertEqual(env.appearance.bindings, [None, None])
                self.assertEqual(env.appearance.episodes, [0, 0])

    def test_actual_public_ids_forward_with_all_four_precedence_levels(self):
        for task, _, key, model, (first, second), mapped in self.CASES:
            with self.subTest(task=task):
                env = self.env(task, key, {'enabled': True, 'scheme_id': first,
                                           'per_env': {'1': {'scheme_id': second}}})
                adapter = env.appearance
                if model == 'mouse':
                    self.assertTrue(all(name in adapter.catalog['schemes'] for name in mapped))
                    self.assertNotIn('variant_1', adapter.catalog['schemes'])
                else:
                    self.assertEqual(adapter.object_id, model)
                    mapping = adapter.catalog['objects'][model]['scheme_map']
                    self.assertEqual((mapping[first], mapping[second]), mapped)
                before_rng = copy.deepcopy([rng.bit_generator.state for rng in adapter.rng])
                self.assertEqual(env.reset(seed=7), ('observations', 'info'))
                self.assertEqual(env.calls, [(7, None)])
                self.assertEqual(adapter.schemes, [first, second])
                options = {key: {'scheme_id': 'original', 'per_env': {'1': {'scheme_id': first}}}}
                env.reset(options=options)
                self.assertIs(env.calls[-1][1], options)
                self.assertEqual(adapter.schemes, ['original', first])
                self.assertEqual(before_rng, [rng.bit_generator.state for rng in adapter.rng])
                env.reset(options={'env_idx': [0], key: {'mode': 'random_choice', 'scheme_ids': [first, second],
                                                         'per_env': {'1': {'scheme_ids': ['unselected_typo']}}}})
                self.assertEqual(env.calls[-1][1]['env_idx'].tolist(), [0])
                self.assertIn(adapter.schemes[0], (first, second))
                self.assertEqual(adapter.schemes[1], first)
                self.assertEqual(adapter.episodes, [3, 2])
                self.assertNotEqual(before_rng[0], adapter.rng[0].bit_generator.state)
                self.assertEqual(before_rng[1], adapter.rng[1].bit_generator.state)

    def test_disabled_defaults_ignore_selection_and_keep_constructor_only_controls(self):
        for task, _, key, *_ in self.CASES:
            for config in (None, {'enabled': False}):
                with self.subTest(task=task, config=config):
                    env = self.env(task, key, config)
                    self.assertIsNone(env.appearance)
                    self.reject(env, 'construction-only', {key: {'enabled': True}})
                    self.reject(env, 'construction-only', {key: {'seed': 9}})
                    options = {key: {'mode': 'random_choice', 'scheme_ids': ['inactive_typo']}}
                    self.assertEqual(env.reset(options=options), ('observations', 'info'))
                    self.assertIs(env.calls[0][1], options)

    def test_keycaps_and_device_channels_select_independently_before_native_reset(self):
        key = 'office_devices_appearance'
        keycaps_key = 'office_keyboard_appearance'
        for task in ('OpenLaptop', 'TypeKeys'):
            with self.subTest(task=task):
                caps_only = self.env(task, key, {'enabled': False},
                                     keycaps={'enabled': True, 'scheme_id': 'variant_3'})
                caps_only.reset()
                self.assertIsNone(caps_only.appearance)
                self.assertEqual(caps_only._office_keyboard_appearance.schemes, ['variant_3'] * 2)
                device_only = self.env(task, key, {'enabled': True, 'scheme_id': 'variant_1'},
                                       keycaps={'enabled': False})
                device_only.reset()
                self.assertEqual(device_only.appearance.schemes, ['variant_1'] * 2)
                self.assertIsNone(device_only._office_keyboard_appearance)

                env = self.env(task, key, {'enabled': True, 'scheme_id': 'variant_1'},
                               keycaps={'enabled': True, 'scheme_id': 'variant_8'})
                caps = env._office_keyboard_appearance
                self.reject(env, 'env 1.*invalid', {key: {'scheme_id': 'variant_2'}, keycaps_key: {
                    'per_env': {'1': {'scheme_id': 'invalid'}}}})
                self.assertEqual(caps.records, [])
                env.reset()
                env.reset(options={'env_idx': [1], keycaps_key: {'scheme_id': 'original'}})
                self.assertEqual(env.appearance.schemes, ['variant_1', 'variant_1'])
                self.assertEqual(caps.schemes, ['variant_8', 'original'])
                self.assertEqual(caps.episodes, [1, 2])

    def test_all_expansion_ids_forward_and_reject_late_typo(self):
        for task, _, key, _, original_candidates, _ in self.CASES:
            probe = self.env(task, key, {'enabled': True})
            ids = list(probe.appearance.catalog['schemes'])
            self.assertEqual(ids[:3], ['original', *original_candidates])
            expanded = ids[3:]
            if len(ids) == 3:
                continue
            self.assertEqual(expanded, [f'variant_{index}' for index in range(3, 11)])
            for name in expanded:
                with self.subTest(task=task, scheme=name):
                    env = self.env(task, key, {'enabled': True})
                    self.reject(env, 'env 1.*_typo', {key: {'scheme_id': name,
                                                            'per_env': {'1': {'scheme_id': name + '_typo'}}}})
                    self.reject(env, 'env 1.*_typo', {key: {'mode': 'random_choice', 'scheme_ids': [name, 'original'],
                                                            'per_env': {'1': {'scheme_ids': [name, name + '_typo']}}}})
                    env.reset(options={key: {'scheme_id': name}})
                    self.assertEqual(env.appearance.schemes, [name, name])


class OfficeCapacityConfig(unittest.TestCase):
    def test_reset_preflight_rejects_before_any_native_write(self):
        source=ast.parse((ROOT/'tasks/office_desk/reset_scope.py').read_text(encoding='utf-8'))
        cls=next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='OfficeResetScopeMixin')
        class Parent:
            def reset(self,seed=None,options=None):
                self.calls.append((seed,options));return 'delegated'
        namespace={'FurnitureResetScopeMixin':Parent,'is_full_reset':lambda idx,n:idx is None or {int(i) for i in idx}==set(range(n)),
                   'validate_reset_indices':M.validate_reset_indices,'validate_reset_override':M.validate_reset_override,
                   'resolve_reset_requests':M.resolve_reset_requests,
                   'torch':torch}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'<office-reset-scope>','exec'),namespace)
        instance=namespace['OfficeResetScopeMixin']();instance.num_envs=2;instance.calls=[]
        instance._elapsed_steps=torch.zeros(instance.num_envs,dtype=torch.int32)
        instance.state=np.arange(8);instance.rng=np.random.default_rng(71);instance.records=[{'env_idx':0,'episode_index':1}]
        before=(instance.state.copy(),copy.deepcopy(instance.rng.bit_generator.state),copy.deepcopy(instance.records))
        restore={'env_states':{'actor':instance.state}}
        for args,message in (({'seed':7,'options':{'env_idx':[1]}},'omit seed'),
                             ({'options':{'env_idx':[1,0]}},'strictly increasing'),
                             ({'options':{'env_idx':[True]}},'strictly increasing'),
                             ({'options':{'reset_to_env_states':restore,'office_devices_appearance':{}}},'state restoration'),
                             ({'options':{'env_idx':[0],'office_devices_appearance':{'per_env':{'2':{}}}}},'per_env')):
            with self.assertRaisesRegex(ValueError,message):instance.reset(**args)
            np.testing.assert_array_equal(instance.state,before[0])
            self.assertEqual(instance.rng.bit_generator.state,before[1]);self.assertEqual(instance.records,before[2]);self.assertEqual(instance.calls,[])
        instance._mouse_appearance=None
        with self.assertRaisesRegex(ValueError,'state restoration'):
            instance.reset(options={'reset_to_env_states':restore,'mouse_appearance':{}})
        with self.assertRaisesRegex(ValueError,'per_env'):
            instance.reset(options={'mouse_appearance':{'per_env':{'1':None}}})
        self.assertEqual(instance.calls,[])
        for selected in ([0,1],(0,1),torch.tensor([0,1],dtype=torch.uint8)):
            options={'env_idx':selected}
            self.assertEqual(instance.reset(seed=7,options=options),'delegated')
            delegated=instance.calls[-1][1]
            self.assertIs(options['env_idx'],selected)
            self.assertIsNot(options,delegated)
            indices=delegated['env_idx']
            self.assertEqual((indices.tolist(),indices.dtype,indices.device),([0,1],torch.long,instance._elapsed_steps.device))
        canonical={'env_idx':torch.tensor([1],dtype=torch.long),'reset_to_env_states':restore}
        self.assertEqual(instance.reset(options=canonical),'delegated')
        self.assertIs(instance.calls[-1][1],canonical)
        restore_options={'reset_to_env_states':restore}
        self.assertEqual(instance.reset(options=restore_options),'delegated')
        self.assertIs(instance.calls[-1][1],restore_options)
        self.assertEqual(instance.reset(seed=7,options={'env_idx':None}),'delegated')
        self.assertEqual(instance.calls[-1],(7,{}))

    def test_only_integer_capacity_keys_pass_through_and_physics_stays_locked(self):
        tree=ast.parse((ROOT/'tasks/office_desk/reset_scope.py').read_text(encoding='utf-8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='office_capacity_config')
        namespace={'copy':copy};exec(compile(ast.Module(body=[function],type_ignores=[]),'<capacity-validator>','exec'),namespace)
        validate=namespace['office_capacity_config']
        capacities={'max_rigid_contact_count':2**17,'max_rigid_patch_count':2**16,'found_lost_pairs_capacity':2**20}
        kwargs={};self.assertIsNone(validate({'gpu_memory_config':capacities},kwargs));self.assertEqual(kwargs['sim_config'],{'gpu_memory_config':capacities})
        for bad in (True,1.5,0,-1):
            values={**capacities,'max_rigid_contact_count':bad}
            with self.assertRaises(ValueError):validate({'gpu_memory_config':values},{})
        with self.assertRaises(ValueError):validate({'gpu_memory_config':{**capacities,'physics_freq':400}},{})
        physics={'physics_freq':200};kwargs={};self.assertIs(validate(physics,kwargs),physics);self.assertEqual(kwargs,{})
        self.assertIsNone(validate(None,{}));self.assertEqual(validate({'control_freq':20},{}),{'control_freq':20})


class OfficeExactUvSafety(unittest.TestCase):
    def test_closed_triangle_support_includes_interior_touch_and_degenerate_faces(self):
        sys.path.insert(0,str(ROOT))
        from tools.variation.office_devices_uv_proof import intersects,periodic_witness
        self.assertTrue(intersects([[-100,-100],[100,-100],[0,100]],[0,0,1,1]))
        self.assertTrue(intersects([[10,10],[10,10],[10,10]],[10,10,20,20]))
        self.assertTrue(intersects([[0,0],[10,0],[0,10]],[10,0,20,10]))
        self.assertFalse(intersects([[0,0],[9,0],[0,9]],[10,10,20,20]))
        witness=periodic_witness([[110,110],[110,110],[110,110]],
            [{'scaled_closed_rect':[10,10,20,20]}],100)
        self.assertIsNotNone(witness);self.assertEqual(witness['integer_tile'],[1,1])


class OfficeKeyMarkerScope(unittest.TestCase):
    def test_batched_marker_uses_own_actual_key_pose_and_native_reset_mask(self):
        class NativePose:
            def __init__(self, p=(0.,0.,0.)):
                self.p = np.asarray(p, dtype=float)

            def to_transformation_matrix(self):
                matrix = np.eye(4)
                matrix[:3, 3] = self.p
                return matrix

        class Marker:
            def __init__(self, scene):
                self.scene = scene
                self._scene_idxs = torch.tensor([1,0])
                self._body_data_index = torch.tensor([2, 4])
                self._bodies = [SimpleNamespace(gpu_index=17), SimpleNamespace(gpu_index=8)]
                self.device = torch.device('cpu')
                self.positions = {}

            def set_pose(self, poses):
                selected = self._scene_idxs[self.scene._reset_mask[self._scene_idxs]]
                for env_id, pose in zip(selected.tolist(), poses, strict=True):
                    self.positions[env_id] = pose.p.tolist()
                    row = int((self._scene_idxs == env_id).nonzero().item())
                    buffer[self._body_data_index[row], :3] = torch.tensor(pose.p)

        def key(x, y, z):
            shape=SimpleNamespace(vertices=[[-1.,-2.,0.],[1.,2.,.4]],
                                  get_local_pose=lambda: NativePose())
            raw=SimpleNamespace(entity=SimpleNamespace(pose=NativePose((1000.,1000.,0.))),
                                get_collision_shapes=lambda:[shape])
            return SimpleNamespace(_objs=[raw],pose=SimpleNamespace(sp=NativePose((x,y,z))))

        path=ROOT/'tasks/office_desk/office_desk_type_keys.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        methods=[node for node in tree.body if isinstance(node,ast.FunctionDef)
                 and node.name in {'_key_target_marker_pose','move_key_target_marker'}]
        cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='OfficeDeskTypeKeysEnv')
        methods.append(next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='_update_key_target_marker'))
        namespace={'np':np,'sapien':SimpleNamespace(Pose=NativePose,CudaArray=lambda t:t),
                   'torch':SimpleNamespace(tensor=torch.tensor,int32=torch.int32,
                                           cuda=SimpleNamespace(synchronize=lambda device:None)),
                   'KEY_MARKER_HEIGHT':.05,
                   'KEY_MARKER_PARKED_Z':-3.,'Pose':SimpleNamespace(create=lambda poses,device:poses)}
        exec(compile(ast.Module(body=methods,type_ignores=[]),str(path),'exec'),namespace)
        update=namespace['_update_key_target_marker']
        buffer=torch.zeros((6, 13), dtype=torch.float32)
        persisted={}
        applied=[]
        def apply(ids):
            applied.append(ids.tolist())
            for body_id in ids.tolist():
                persisted[body_id]=buffer[{17:2,8:4}[body_id],:3].clone()
        scene=SimpleNamespace(gpu_sim_enabled=True,_reset_mask=torch.tensor([True,True]),
                              parallel_in_single_scene=False,scene_offsets=torch.tensor([[-2.,-2.,0.],[0.,-2.,0.]]),
                              px=SimpleNamespace(cuda_rigid_body_data=SimpleNamespace(torch=lambda:buffer),
                                                 gpu_apply_rigid_dynamic_data=apply))
        marker=Marker(scene)
        env=SimpleNamespace(num_envs=2,scene=scene,key_target_marker=marker,_target_links=[],sequence_index=torch.tensor([0,0]))
        update(env)
        self.assertEqual(marker.positions,{})
        env._target_links=[[key(1,2,1),key(3,4,1)],[key(10,20,2),key(30,40,2)]]
        update(env)
        self.assertEqual([marker.positions[i][:2] for i in range(2)],[[1.,2.],[10.,20.]])
        np.testing.assert_allclose([marker.positions[i][2] for i in range(2)],[1.45,2.45])
        env.sequence_index[:]=torch.tensor([1,0])
        scene._reset_mask[:]=torch.tensor([True,False])
        update(env)
        self.assertEqual([marker.positions[i][:2] for i in range(2)],[[3.,4.],[10.,20.]])
        env.sequence_index[1]=1
        scene._reset_mask[:]=torch.tensor([False,True])
        update(env)
        self.assertEqual([marker.positions[i][:2] for i in range(2)],[[3.,4.],[30.,40.]])
        env._target_links[1][1].pose.sp=NativePose((31.,42.,3.))
        update(env)
        self.assertEqual([marker.positions[i][:2] for i in range(2)],[[3.,4.],[31.,42.]])
        env.sequence_index[:]=2
        scene._reset_mask[:]=True
        update(env)
        self.assertEqual(marker.positions,{0:[0.,0.,-3.],1:[0.,0.,-3.]})
        self.assertEqual(applied, [[17,8],[8],[17],[17],[17,8]])
        # Change both targets with a full reset, then emulate the SDK overwriting
        # the staging buffer on the next partial reset with persistent body poses.
        env.sequence_index[:]=0
        env._target_links[0][0].pose.sp=NativePose((.1234567,.2345678,.3))
        update(env)
        held=buffer[4,:3].clone()
        for body_id,idx in [(17,2),(8,4)]:
            buffer[idx,:3]=persisted[body_id]
        env._furniture_reset_env_idx=[1]
        env._furniture_reset_mask=lambda mask:torch.tensor([False,True])
        update(env)
        self.assertEqual(applied[-1],[17])
        self.assertTrue(torch.equal(held,buffer[4,:3]))
        self.assertTrue(torch.equal(scene._reset_mask,torch.tensor([True,True])))
        self.assertTrue(torch.count_nonzero(buffer[[0,1,3,5]]) == 0)


if __name__=='__main__':
    unittest.main()
