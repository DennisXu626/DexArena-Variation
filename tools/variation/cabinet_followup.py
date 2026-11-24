"""Scoped label diagnosis and Cabinet follow-up. Static mode never imports simulation."""
import contextlib
import copy
import hashlib
import json
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

ASSET_ROOT = Path(__file__).resolve().parents[2] / 'tasks/assets/variation/cabinet_pouring/v1'
BOTTLE_NAME = 'original-3.obj'
NATIVE_LABEL = 'texture_1.jpg'
PROBE = 'variant_9'
MIN_LABEL = 240
MIN_MARKER = 24
LABEL_MARGIN = .10
LABEL_MIN_CORRELATION = .32
BOWL_VIEW = ([-.43, -.84, .37], [-.20, -.50, .045], .70)
BEAD_VIEW = ([1., .90, .60], [1., 1., .50], .65)
CLOSEOUT_CHECKS = ('unscrew-random','pour-task','pour-droplets','cap-diagnostic')


def digest(pixels):
    return hashlib.sha256(np.ascontiguousarray(pixels).tobytes()).hexdigest()


def pack_entity_ids(segmentation):
    """Store each full 32-bit entity ID losslessly in four PNG bytes."""
    return np.ascontiguousarray(segmentation,dtype='<u4').view(np.uint8).reshape(*segmentation.shape,4)


def inset(mask):
    result = np.zeros_like(mask)
    result[1:-1, 1:-1] = (mask[1:-1, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:]
                         & mask[:-2, 1:-1] & mask[2:, 1:-1])
    return result


def scaled_render_vertices(shape, part, marker):
    # Box vertices are the shared unit mesh. SAPIEN stores the render scale
    # in half_size for boxes and in scale for triangle-mesh shapes.
    geometry = shape if marker else part
    scale = shape.half_size if marker else getattr(shape, 'scale', 1.)
    return np.asarray(geometry.vertices) * np.asarray(scale)


def project_parts(size, intrinsic, extrinsic, meshes):
    """Rasterize a small object on CPU. Compare only pixels with the real entity ID."""
    height, width = size
    zbuffer = np.full(size, np.inf)
    roles = np.full(size, -1, dtype=np.int16)
    uvmap = np.zeros((*size, 2))
    for role, vertices, triangles, uv in meshes:
        camera = vertices @ extrinsic[:, :3].T + extrinsic[:, 3]
        projected = camera @ intrinsic.T
        for idx in triangles:
            depth = camera[idx, 2]
            if np.any(depth <= .01):
                continue
            xy = projected[idx, :2] / depth[:, None]
            x0, y0 = np.maximum(np.floor(xy.min(axis=0)).astype(int), 0)
            x1, y1 = np.minimum(np.ceil(xy.max(axis=0)).astype(int), [width-1, height-1])
            if x1 < x0 or y1 < y0:
                continue
            a, b = xy[1]-xy[0], xy[2]-xy[0]
            det = a[0]*b[1]-a[1]*b[0]
            if abs(det) < 1e-8:
                continue
            yy, xx = np.mgrid[y0:y1+1, x0:x1+1]
            delta_x, delta_y = xx + .5 - xy[0, 0], yy + .5 - xy[0, 1]
            beta = (delta_x*b[1] - delta_y*b[0])/det
            gamma = (a[0]*delta_y - a[1]*delta_x)/det
            weights = np.stack((1-beta-gamma, beta, gamma), axis=-1)
            visible = np.all(weights >= 0, axis=-1)
            corrected = weights/depth
            denom = corrected.sum(axis=-1)
            current = np.divide(1., denom, out=np.full_like(denom, np.inf), where=denom > 0)
            area = (slice(y0,y1+1), slice(x0,x1+1))
            hit = visible & (current < zbuffer[area])
            zbuffer[area][hit] = current[hit]
            roles[area][hit] = role
            if uv is not None:
                uvmap[area][hit] = (corrected[hit] @ uv[idx]) / denom[hit,None]
    return roles, uvmap


def image_pixels(path):
    with Image.open(path) as image:
        return np.asarray(image.convert('RGB')).copy()


def sample_texture(texture, uv, flip_v=False):
    y = 1-uv[:, 1] if flip_v else uv[:, 1]
    coord = np.column_stack((uv[:,0], y))
    coord = np.clip(coord, 0, 1) * (np.array(texture.shape[:2][::-1])-1)
    x0, y0 = np.floor(coord).astype(int).T
    x1, y1 = np.minimum(x0+1, texture.shape[1]-1), np.minimum(y0+1, texture.shape[0]-1)
    dx, dy = (coord - np.column_stack((x0,y0))).T
    return ((1-dy[:,None])*((1-dx[:,None])*texture[y0,x0]+dx[:,None]*texture[y0,x1])
            + dy[:,None]*((1-dx[:,None])*texture[y1,x0]+dx[:,None]*texture[y1,x1]))


def correlation(observed, predicted):
    # High-frequency print and broad light/dark blocks matter. An affine
    # brightness shift alone cannot make a native picture pass a candidate.
    luma = np.array([.2126,.7152,.0722])
    a, b = observed @ luma, predicted @ luma
    a, b = a-a.mean(), b-b.mean()
    denom = np.linalg.norm(a)*np.linalg.norm(b)
    return float((a @ b)/denom) if denom > 1e-8 else 0.


def print_score(rgb, coords, native, wanted, flip_v):
    return {name:correlation(rgb, sample_texture(image, coords, flip_v))
            for name,image in [('native',native),('wanted',wanted)]}


def preferred(score, role):
    other = 'wanted' if role=='native' else 'native'
    return score[role]>=LABEL_MIN_CORRELATION and score[role]-score[other]>=LABEL_MARGIN


def static(directory):
    catalog=json.loads((directory/'v1/catalog.json').read_text('utf-8'))['schemes']
    probe=image_pixels(directory/'v1'/catalog['berry_soda']['label_texture'])
    assert probe.shape==(490,388,3)
    K=np.array([[70,0,52],[0,70,46],[0,0,1.]])
    E=np.eye(4)[:3]
    xyz=np.array([[-1,-1,2],[1,-1,2],[1,1,2],[-1,1,2]],dtype=float)
    uv=np.array([[0,0],[1,0],[1,1],[0,1]],dtype=float)
    role, plane=project_parts((92,104),K,E,[(1,xyz,np.array([[0,1,2],[0,2,3]]),uv)])
    mask=inset(role==1)
    assert mask.sum()>MIN_LABEL and np.allclose(plane[45,51],[.492857,.492857],atol=1e-5)
    native=np.zeros((28,40,3),np.uint8)
    native[:,20:]=200
    wanted=native.transpose(1,0,2).copy()
    observed=sample_texture(wanted,plane[mask])
    score=print_score(observed,plane[mask],native,wanted,False)
    assert preferred(score,'wanted') and not preferred(score,'native')
    native_obs=sample_texture(native,plane[mask])
    for original_pixels in (native_obs, .76*native_obs+25):
        assert preferred(print_score(original_pixels,plane[mask],native,wanted,False),'native')
    box=SimpleNamespace(vertices=np.array([[-1.,-1.,-1.],[1.,1.,1.]]),
                        half_size=(.0128,.002,.0012))
    assert np.allclose(np.ptp(scaled_render_vertices(box,None,True),axis=0),[.0256,.004,.0024])
    return dict(cpu_only=True,projected_test_pixels=int(mask.sum()),wanted_control=score,
                wrong_print_rejected=True,probe_art_shape=list(probe.shape),box_half_size_applied=True)


def texture_pixels(source, native):
    """Match the native texture format and size for the diagnostic upload."""
    with Image.fromarray(source) as image:
        mode='RGBA' if native.shape[2]==4 else 'RGB'
        return np.asarray(image.convert(mode).resize(native.shape[1::-1],Image.Resampling.LANCZOS)).copy()


@contextlib.contextmanager
def private_texture_experiment():
    """Checker-only intervention. No production file or shared texture is edited."""
    from sapien.render import RenderTexture2D
    from tasks.cabinet_pouring.variation import PilotVariation

    original_collect=PilotVariation._collect_bindings
    original_apply=PilotVariation.apply_appearance

    def collect(adapter):
        original_collect(adapter)
        materials=[]
        for group in adapter._bindings:
            for binding in group:
                if binding['role']!='body_label':
                    continue
                material=binding['material']
                assert not any(material==m for m in materials), 'label material is shared'
                materials.append(material)
                if 'diagnostic_private_label' in binding:
                    continue
                old=binding['original']['base_color_texture']
                pixels=old.download().copy()
                live=RenderTexture2D(array=pixels, format=old.format, mipmap_levels=old.mipmap_levels,
                                     filter_mode=old.filter_mode,address_mode=old.address_mode,srgb=old.is_srgb)
                binding['diagnostic_private_label']=(live,pixels)
                material.base_color_texture=live

    def apply(adapter, env_idx, options):
        original_apply(adapter,env_idx,options)
        for i in env_idx.tolist():
            scheme=adapter.schemes[i]
            for binding in adapter._bindings[i]:
                if 'diagnostic_private_label' not in binding:
                    continue
                live,native=binding['diagnostic_private_label']
                data=native if scheme=='original' else texture_pixels(
                    binding['material'].base_color_texture.download(),native)
                live.upload(data)
                binding['material'].base_color_texture=live

    with patch.object(PilotVariation,'_collect_bindings',collect), patch.object(PilotVariation,'apply_appearance',apply):
        yield


class Followup:
    def __init__(self, report, output, hooks):
        self.report=report
        self.output=output
        self.h=SimpleNamespace(**hooks)
        self.bottle_catalog=json.loads((ASSET_ROOT/'catalog.json').read_text('utf-8'))['schemes']
        self.first=None

    def save(self):
        (self.output/'results.json').write_text(json.dumps(self.report,indent=2)+'\n',encoding='utf-8')

    def image(self,name,pixels):
        path=self.output/f'{name}.png'
        Image.fromarray(pixels).save(path)
        return dict(file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    size_wh=list(pixels.shape[1::-1]))

    @staticmethod
    def review(env,i=0):
        task=env.unwrapped
        # Use the same membership refresh as the production RGB and sensor paths.
        task._refresh_bottle_render_group()
        scene=task.scene
        scene.update_render(update_sensors=False,update_human_render_cameras=True)
        camera=scene.human_render_cameras['render_camera']
        camera.capture()
        frame=camera.get_obs(rgb=True,depth=False,segmentation=True,position=False)
        params=camera.get_params()
        cpu=lambda x:(x if i is None else x[i]).detach().cpu().numpy().copy()
        return SimpleNamespace(rgb=cpu(frame['rgb'])[...,:3],seg=cpu(frame['segmentation'])[...,0],
                               K=cpu(params['intrinsic_cv']),E=cpu(params['extrinsic_cv']))

    @staticmethod
    def actor(e,i,cap=False):
        from tasks.cabinet_pouring.cabinet_pouring_long import BOTTLE_REP_FIXED,BOTTLE_REP_OPEN
        rep=int(e._active_bottle_rep[i]) if e.bottle_stage_twins else None
        if cap:
            name='cap_twin' if bool(e._cap_free[i]) else ('cap_fixed' if rep==BOTTLE_REP_FIXED else 'cap')
        else:
            name={BOTTLE_REP_FIXED:'source_fixed',BOTTLE_REP_OPEN:'source_open'}.get(rep,'source')
        return name,getattr(e,name)

    @staticmethod
    def entity(actor,i):
        raw=actor._objs[i]
        return getattr(raw,'entity',raw)

    def geometry(self,e,i,frame,cap=False):
        from sapien.render import RenderBodyComponent, RenderShapeBox
        name,actor=self.actor(e,i,cap)
        entity=self.entity(actor,i)
        pose=actor.pose.to_transformation_matrix()[i].detach().cpu().numpy()
        body=entity.find_component_by_type(RenderBodyComponent)
        meshes=[]
        label_slots=[]
        for shape in body.render_shapes:
            T=pose @ shape.local_pose.to_transformation_matrix()
            parts=shape.parts
            for part in parts:
                m=part.material
                tex=m.base_color_texture
                label=not cap and tex is not None
                marker=cap and isinstance(shape,RenderShapeBox)
                role=2 if marker else (1 if label else 0)
                geom=shape if marker else part
                vertices=scaled_render_vertices(shape,part,marker)
                vertices=vertices @ T[:3,:3].T + T[:3,3]
                meshes.append((role,vertices,np.asarray(geom.triangles),part.get_vertex_uv() if label else None))
                if label:
                    assert Path(shape.filename).name==BOTTLE_NAME,shape.filename
                    label_slots.append((m,tex,shape.filename))
        roles,uv=project_parts(frame.seg.shape,frame.K,frame.E,meshes)
        obj=frame.seg==entity.per_scene_id
        projected=roles==(2 if cap else 1)
        overlap=projected&obj
        mask=inset(overlap)
        assert mask.sum()>=(MIN_MARKER if cap else MIN_LABEL),(
            name,int(mask.sum()),int(obj.sum()),int(projected.sum()),int(overlap.sum()))
        assert int(obj.sum())>=(80 if cap else MIN_LABEL)
        if cap:
            return name,obj,mask
        m,tex,mesh=label_slots[0]
        assert len(label_slots)==1
        return name,obj,mask,uv[mask],(m,tex,mesh)

    def calibrated_view(self,task,which=0):
        if task=='PourBeads':
            return BOWL_VIEW
        if task=='beads':
            return BEAD_VIEW
        if self.first is None:
            self.first={}
        if task not in self.first:
            with contextlib.closing(self.h.make(task)) as env:
                self.h.full_reset(env)
                e=env.unwrapped
                p=e._source_pose().p[0].detach().cpu().numpy().copy()
                p[2]+=(float(e.source_z_lo)+float(e.source_z_hi))*.5
                self.first[task]=p
        target=self.first[task]
        if task=='PickBottle':
            offsets=([-.36,-.055,.045],[-.40,.025,.072])
            fov=.53
        else:
            offsets=([.26,.14,.25],[.23,-.28,.31])
            fov=.83
            if which==0:
                offsets=([.43,.13,.34],offsets[1])
        return ((target+offsets[which]).tolist(),target.tolist(),fov)

    def expected(self,sid):
        code=self.h.catalog[sid]['bottle']
        path=ASSET_ROOT/self.bottle_catalog[code]['label_texture']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==self.bottle_catalog[code]['sha256']
        return image_pixels(path),dict(scheme=code,file=path.name,sha256=self.bottle_catalog[code]['sha256'])

    def label_frame(self,env,sid,native,flip,stem,i=0,*,frame=None,meta=None):
        if frame is None:
            frame=self.review(env,i)
        if meta is None:
            meta=self.save_review(stem,frame)
        name,obj,mask,uv,(_,tex,mesh)=self.geometry(env.unwrapped,i,frame)
        meta.update(mask=self.image(stem+'_label_mask',mask.astype(np.uint8)*255),
                  representation=name,mesh=Path(mesh).name,label_pixels=int(mask.sum()),
                  bound_filename=Path(tex.filename or '').name,bound_texels=digest(tex.download()))
        if sid!='original':
            wanted,meta['wanted_asset']=self.expected(sid)
            actual=tex.download()
            expected=texture_pixels(wanted,actual)[...,:3]
            meta['bound_matches_catalog_pixels']=np.array_equal(actual[...,:3],expected)
            assert meta['bound_matches_catalog_pixels'], (name,sid,'actual label slot pixels')
            meta['image_score']=print_score(frame.rgb[mask],uv,native,wanted,flip)
        else:
            meta['template_orientation_scores']=[
                correlation(frame.rgb[mask],sample_texture(native,uv,flip_v)) for flip_v in (False,True)]
        return frame,meta,mask

    def probe(self):
        task='PickBottle'
        row=self.report['tasks'][task]=dict(phase='label probe',previous_job=128861,scheme=PROBE,attempts=[])
        wanted,art=self.expected(PROBE)
        row['wanted_asset']=art
        baseline_state=None
        selected=None
        for attempt in (0,1):
            view=self.calibrated_view(task,attempt)
            with contextlib.closing(self.h.make(task,{'enabled':True,'seed':109},review_view=view)) as env:
                self.h.full_reset(env,self.h.opts('original'))
                frame=self.review(env)
                candidate=dict(view=view,original=self.image(f'PickBottle_probe_native_view{attempt}',frame.rgb))
                row['attempts'].append(candidate)
                self.save()
                try:
                    _,_,mask,uv,(_,tex,_)=self.geometry(env.unwrapped,0,frame)
                except AssertionError as exc:
                    candidate['visibility_issue']=str(exc)
                    continue
                native=tex.download()[...,:3].copy()
                assert Path(tex.filename).name==NATIVE_LABEL
                tests=[print_score(frame.rgb[mask],uv,native,wanted,flip) for flip in (False,True)]
                flip=max((False,True),key=lambda k:tests[k]['native'])
                candidate['native_scores']=tests
                candidate['flip_v']=flip
                if not preferred(tests[flip],'native'):
                    continue
                row['original_mask']=self.image('PickBottle_probe_native_label_mask',mask.astype(np.uint8)*255)
                baseline_state=self.h.task_state(env.unwrapped,0)
                self.h.full_reset(env,self.h.opts(PROBE))
                hot,row['hot'],_=self.label_frame(env,PROBE,native,flip,'PickBottle_probe_hot')
                assert self.h.task_state(env.unwrapped,0)==baseline_state
                row['same_geometry_camera']=np.array_equal(hot.seg,frame.seg) and np.array_equal(hot.E,frame.E)
                assert row['same_geometry_camera']
                selected=view
                break
        assert selected is not None,'native label not identified in either review view'
        row['camera']=selected
        row['native_texels_sha256']=digest(native)
        self.save()
        if preferred(row['hot']['image_score'],'wanted'):
            row.update(status='current_binding_visible',recommended_binding='current')
            return
        with contextlib.closing(self.h.make(task,{'enabled':True,'seed':109,'scheme_id':PROBE},review_view=selected)) as env:
            self.h.full_reset(env,self.h.opts(PROBE))
            _,row['cold'],_=self.label_frame(env,PROBE,native,flip,'PickBottle_probe_cold')
            assert self.h.task_state(env.unwrapped,0)==baseline_state
        with private_texture_experiment(), contextlib.closing(
                self.h.make(task,{'enabled':True,'seed':109},review_view=selected)) as env:
            self.h.full_reset(env,self.h.opts('original'))
            before=self.review(env)
            self.h.full_reset(env,self.h.opts(PROBE))
            private,row['private_upload'],_=self.label_frame(env,PROBE,native,flip,'PickBottle_probe_private_upload')
            assert self.h.task_state(env.unwrapped,0)==baseline_state
            assert np.array_equal(before.seg,private.seg) and np.array_equal(before.E,private.E)
        # A proposal to change production needs a visible candidate in the
        # private-texture control and a native-looking warmed frame.
        switch_stale=preferred(row['hot']['image_score'],'native')
        upload_works=preferred(row['private_upload']['image_score'],'wanted')
        if switch_stale and upload_works:
            row.update(status='reference_switch_stale_private_upload_visible',recommended_binding='private_upload')
        else:
            row['status']='inconclusive'
            raise AssertionError('No supported label-binding remedy from the probe')


    @staticmethod
    def crop(mask, padding=14):
        y,x=np.where(mask)
        h,w=mask.shape
        assert x.size
        return [max(0,int(x.min())-padding),max(0,int(y.min())-padding),
                min(w,int(x.max())+padding+1),min(h,int(y.max())+padding+1)]

    def save_review(self,stem,frame,mask=None):
        row={'files':{'review':self.image(stem,frame.rgb)}}
        if mask is not None:
            row['object_mask']=self.image(stem+'_mask',mask.astype(np.uint8)*255)
        return row

    def bowl_masks(self,e,frame,i):
        entity=self.entity(e.target,i)
        mask=frame.seg==entity.per_scene_id
        interior=mask
        for _ in range(6):
            interior=inset(interior)
        rim=inset(mask)&~interior
        assert int(interior.sum())>=180 and int(rim.sum())>=80, 'bowl not in view'
        return mask,interior,rim

    def baseline_view(self,task,row):
        # Check original visibility before enabling any scheme. Record each
        # bounded view attempt, keeping the successful camera fixed thereafter.
        row['native_view_trials']=[]
        for which in ((0,) if task=='PourBeads' else (0,1)):
            view=self.calibrated_view(task,which)
            with contextlib.closing(self.h.make(task,review_view=view)) as native_env:
                _,info=self.h.full_reset(native_env)
                frame=self.review(native_env)
                attempt=dict(view=view,**self.save_review(f'{task}_native_view{which}',frame))
                row['native_view_trials'].append(attempt)
                self.save()
                e=native_env.unwrapped
                try:
                    if task=='PourBeads':
                        masks=self.bowl_masks(e,frame,0)
                        row['same_coordinate_crops']={'bowl':self.crop(masks[0])}
                        native=None
                        flip=None
                    else:
                        _,obj,mask,uv,(_,tex,_)=self.geometry(e,0,frame)
                        assert Path(tex.filename).name==NATIVE_LABEL
                        native=tex.download()[...,:3].copy()
                        probe,_=self.expected(PROBE)
                        scores=[print_score(frame.rgb[mask],uv,native,probe,k) for k in (False,True)]
                        flip=max((False,True),key=lambda k:scores[k]['native'])
                        attempt['native_scores']=scores
                        assert preferred(scores[flip],'native'),'native print was not identified'
                        row['same_coordinate_crops']={'label':self.crop(mask)}
                        if task=='UnscrewCap':
                            _,cap,marker=self.geometry(e,0,frame,cap=True)
                            row['same_coordinate_crops']['bottle_cap']=self.crop(obj|cap)
                            row['same_coordinate_crops']['cap_marker']=self.crop(cap|marker)
                except AssertionError as exc:
                    attempt['visibility_issue']=str(exc)
                    continue
                row['camera']=dict(view=view,intrinsic=frame.K.tolist(),extrinsic=frame.E.tolist())
                row['flip_v']=flip
                return view,frame,native,flip,self.h.snap(native_env,info)
        raise AssertionError(f'{task}: no proved native review view')

    def custody(self,e,i):
        family=e._family_appearance
        return dict(state=self.h.task_state(e,i),materials=self.h.materials(e,i),
                    rng=copy.deepcopy(family.rng[i].bit_generator.state),
                    records=[x for x in e.family_appearance_records if x['env_idx']==i])

    def isolation(self,env,task,row,baseline,native,flip):
        e=env.unwrapped
        self.h.full_reset(env,{'family_appearance':{'per_env':{
            '0':{'scheme_id':'variant_4'},'1':{'scheme_id':'variant_9'}}}})
        row['isolation']=[]
        for selected in (1,0):
            still=1-selected
            before=self.h.capture(env)
            before_review=self.review(env,still)
            selected_before=self.review(env,selected)
            custody=self.custody(e,still)
            env.reset(options=self.h.opts('original',selected))
            after=self.h.capture(env)
            after_review=self.review(env,still)
            selected_after=self.review(env,selected)
            now=self.custody(e,still)
            phase=dict(selected=selected,passive={k:custody[k]==now[k] for k in custody},
                       before=self.save_review(f'{task}_reset{selected}_before',selected_before),
                       after=self.save_review(f'{task}_reset{selected}_after',selected_after))
            row['isolation'].append(phase)
            phase['passive']['all_camera_rgb']=self.h.rgb_equal(before,after,still)
            phase['passive']['review_rgb']=np.array_equal(before_review.rgb,after_review.rgb)
            self.save()
            assert all(phase['passive'].values()),(task,selected,phase['passive'])
            assert self.h.materials(e,selected)==baseline['materials'][selected]
            assert e.family_appearance_records[-1]['env_idx']==selected
            assert e.family_appearance_records[-1]['family_id']=='original'
            if task=='PourBeads':
                # The bowl can move slightly on reset. Compare the old and
                # new entity pixels, after native material restoration.
                mask,bottom,rim=self.bowl_masks(e,selected_after,selected)
                id_=self.entity(e.target,selected).per_scene_id
                common=(selected_before.seg==id_)&mask
                assert common.sum()>=180
                assert np.any(selected_before.rgb[common]!=selected_after.rgb[common])
                phase['bowl_common_pixels']=int(common.sum())
            else:
                name,_,mask,uv,_=self.geometry(e,selected,selected_after)
                probe,_=self.expected(PROBE)
                scores=print_score(selected_after.rgb[mask],uv,native,probe,flip)
                phase['restored_label']={'representation':name,'pixels':int(mask.sum()),'scores':scores}
                assert preferred(scores,'native'),(task,selected,scores)
                if task=='UnscrewCap':
                    cap_name,_,marker=self.geometry(e,selected,selected_after,cap=True)
                    phase['restored_cap']={'representation':cap_name,'marker_pixels':int(marker.sum())}
            phase['status']='passed'
            self.save()

    def cap_switch(self,env,row,native,flip):
        import torch
        from tasks.cabinet_pouring.cabinet_pouring_long import BOTTLE_REP_OPEN, CAP_TURN_SWITCH_HOLD_STEPS
        e=env.unwrapped
        self.h.full_reset(env,self.h.opts(PROBE))
        stage=row['engineered_stage_switch']={
            'scope':'checker-only trigger, no robot action','scheme':PROBE,'frames':{}}
        if native is None:
            slots=[slot for slot in e._variation._bindings[0]
                   if slot['name']=='source_fixed' and slot['role']=='body_label']
            assert len(slots)==1
            native=slots[0]['label_native'][...,:3]
        previous=self.h.materials(e,0)
        passive=self.custody(e,1)
        stages=(('attached','source_fixed','cap_fixed'),('free','source_fixed','cap_twin'),
                ('open','source_open','cap_twin'))
        for kind,bottle_expected,cap_expected in stages:
            stage['attempted_stage']=kind
            self.save()
            if kind=='free':
                # Seed only env 0 at the qualification boundary. evaluate() owns
                # detachment, friction, rigid-data sync and the placement marker.
                e._cap_twist[0]=e.cap_success_rotation
                e._cap_turn_hold_count[0]=CAP_TURN_SWITCH_HOLD_STEPS-1
                e._cap_turn_last_eval_step[0]=e._elapsed_steps[0]-1
                stage['free_trigger']=dict(path='UnscrewCap.evaluate -> _cap_status',env_idx=0,
                                           twist=float(e.cap_success_rotation),
                                           seeded_hold_count=CAP_TURN_SWITCH_HOLD_STEPS-1)
                self.save()
                e.evaluate()
            elif kind=='open':
                e._swap_to_open_bottle(torch.tensor([True,False],device=e.device))
            batch=self.review(env,i=None)
            frame=SimpleNamespace(**{key:value[0] for key,value in vars(batch).items()})
            other={key:value[1] for key,value in vars(batch).items()}
            if kind=='attached':
                other_baseline=other
            stem=f'UnscrewCap_engineered_{kind}'
            meta=stage['frames'][kind]=self.save_review(stem,frame)
            if kind=='attached' and row.get('archived_attached_sha256'):
                meta['matches_128997_attached']=meta['files']['review']['sha256']==row['archived_attached_sha256']
            self.save_stage_evidence(e,batch,stem,meta)
            if kind=='free':
                assert bool(e._cap_detached[0]) and bool(e._cap_free[0])
                assert bool(e._stage_cap_turned[0]) and not bool(e._stage_cap_placed[0])
            elif kind=='open':
                assert int(e._active_bottle_rep[0])==BOTTLE_REP_OPEN
            self.save()
            assert np.array_equal(frame.K,row['camera']['intrinsic'])
            assert np.array_equal(frame.E,row['camera']['extrinsic'])
            self.label_frame(env,PROBE,native,flip,stem,frame=frame,meta=meta)
            self.save()
            cap_name,cap,mark=self.geometry(e,0,frame,cap=True)
            meta.update(cap_representation=cap_name,cap_pixels=int(cap.sum()),marker_pixels=int(mark.sum()),
                        marker_median_rgb=np.median(frame.rgb[mark],axis=0).tolist(),
                        marker_mask=self.image(f'UnscrewCap_engineered_{kind}_marker',mark.astype(np.uint8)*255))
            current=self.custody(e,1)
            meta['passive_env']={key:passive[key]==current[key] for key in passive}
            meta['passive_env'].update({key:np.array_equal(other[key],other_baseline[key]) for key in other})
            self.save()
            assert meta['representation']==bottle_expected and cap_name==cap_expected,(kind,meta)
            assert preferred(meta['image_score'],'wanted'),(kind,meta['image_score'])
            assert all(meta['passive_env'].values()),(kind,meta['passive_env'])
            assert self.h.materials(e,0)==previous,(kind,'selected materials changed')
            meta['verified_slots']=self.h.verify_bindings(e,0,PROBE)
            meta['status']='passed'
        stage['status']='passed'
        self.save()

    def save_stage_evidence(self,e,batch,stem,meta):
        from sapien.render import RenderBodyComponent

        environments=meta['environments']={}
        for i in (0,1):
            prefix=f'{stem}_env{i}'
            rgb=meta['files']['review'] if i==0 else self.image(prefix,batch.rgb[i])
            seg=batch.seg[i]
            environments[str(i)]=dict(rgb=rgb,entity_segmentation=self.image(prefix+'_entity_ids',pack_entity_ids(seg)),
                segmentation_format='RGBA bytes least-significant first, decode as little-endian uint32')
        self.save()
        for i in (0,1):
            seg=batch.seg[i]
            names={int(entity.per_scene_id):entity.name for entity in e.scene.sub_scenes[i].entities}
            ids,counts=np.unique(seg,return_counts=True)
            count_by_id={int(entity_id):int(count) for entity_id,count in zip(ids,counts)}
            foreground=[dict(entity_id=entity_id,name=names.get(entity_id,'unmapped'),pixels=count)
                        for entity_id,count in sorted(count_by_id.items(),key=lambda item:(-item[1],item[0]))
                        if entity_id!=0][:12]
            actors={}
            for name in ('source','source_fixed','source_open','cap_fixed','cap_twin'):
                actor=getattr(e,name)
                entity=self.entity(actor,i)
                entity_id=int(entity.per_scene_id)
                render=entity.find_component_by_type(RenderBodyComponent)
                actors[name]=dict(entity_id=entity_id,name=entity.name,pixels=count_by_id.get(entity_id,0),
                                  pose_m_wxyz=actor.pose.raw_pose[i].detach().cpu().tolist(),
                                  visibility=float(render.visibility) if render is not None else None)
            world_to_cv=batch.E[i]
            cv_to_world=world_to_cv[:,:3].T
            environments[str(i)].update(foreground=foreground,actors=actors,
                flags={name: getattr(e,name)[i].item() for name in ('_active_bottle_rep','_cap_detached',
                    '_cap_free','_stage_cap_turned','_stage_cap_placed')},
                camera=dict(intrinsic=batch.K[i].tolist(),extrinsic=world_to_cv.tolist(),
                            position_world_m=(-cv_to_world@world_to_cv[:,3]).tolist(),
                            cv_to_world_rotation=cv_to_world.tolist()))
        self.save()

    def cap_finish(self,reused,*,with_random=True,attached_reference=None):
        row=self.report['tasks']['UnscrewCap']=dict(status='running',reused_fixed_job=128943,
                                                   camera=reused['camera'],archived_attached_sha256=attached_reference)
        self.save()
        with contextlib.closing(self.h.make('UnscrewCap',{'enabled':True,'seed':109},
                                             review_view=row['camera']['view'])) as env:
            self.cap_switch(env,row,None,reused['flip_v'])
        if with_random:
            self.random('UnscrewCap',row)
        row['status']='passed'
        self.save()

    def random(self,task,row):
        traces=[]
        for _ in range(2):
            with contextlib.closing(self.h.make(task,{'enabled':True,'seed':109})) as env:
                for idx in (None,1,0,1):
                    env.reset(seed=7,options=self.h.opts(None,idx,mode='random_choice'))
                traces.append(env.unwrapped.family_appearance_records)
        row['random_reproducibility']=traces
        self.save()
        assert traces[0]==traces[1] and [x['env_idx'] for x in traces[0]]==[0,1,0,1,1,0,1]

    def task_matrix(self,task,auth):
        row=self.report['tasks'][task]=dict(status='running',captures={},gallery_camera='review')
        self.save()
        view,original,native,flip,baseline=self.baseline_view(task,row)
        with contextlib.closing(self.h.make(task,{'enabled':True,'seed':109},review_view=view)) as env:
            e=env.unwrapped
            for sid in self.h.variants:
                row['attempted_scheme']=sid
                _,info=self.h.full_reset(env,self.h.opts(sid))
                # Recheck only task baselines needed by this evidence; never recapture the cabinets.
                if task!='PickBottle':
                    now=self.h.snap(env,info)
                    assert all(now[k]==baseline[k] for k in ('state','physics','info')),(task,sid,'physical drift')
                frame=self.review(env)
                if sid=='original':
                    assert np.array_equal(frame.rgb,original.rgb)
                    assert [self.h.materials(e,i) for i in (0,1)]==baseline['materials']
                else:
                    row['last_verified_slots']=[self.h.verify_bindings(e,i,sid,bottle_only=task=='PickBottle')
                                                for i in (0,1)]
                if task=='PourBeads':
                    stem=f'{task}_{sid}_review'
                    row['captures'][sid]=self.save_review(stem,frame)
                    if sid!='original':
                        row['captures'][sid]['verified_slots']=row['last_verified_slots']
                    self.save()
                    mask,inner,rim=self.bowl_masks(e,frame,0)
                    row['captures'][sid]['object_mask']=self.image(stem+'_mask',mask.astype(np.uint8)*255)
                    row['captures'][sid]['native_particles_in_source']=info['num_in_source'].detach().cpu().tolist()
                    for name,zone in [('surface',inner),('inner_silhouette_band',rim)]:
                        changed=int(np.any(frame.rgb[zone]!=original.rgb[zone],axis=-1).sum())
                        row['captures'][sid][name]=dict(pixels=int(zone.sum()),changed=changed,
                            mask=self.image(f'{stem}_{name}_mask',zone.astype(np.uint8)*255))
                        self.save()
                        assert changed>0 if sid!='original' else changed==0
                    assert len(e.particles)==16 and e.particle_radius==.004
                else:
                    _,meta,_=self.label_frame(env,sid,native,flip,f'{task}_{sid}_review')
                    row['captures'][sid]=meta
                    self.save()
                    if sid!='original':
                        assert preferred(meta['image_score'],'wanted'),(task,sid,meta['image_score'])
                    if task=='UnscrewCap':
                        _,_,marker=self.geometry(e,0,frame,cap=True)
                        marker_pixels=frame.rgb[marker]
                        mask_name=f'{task}_{sid}_marker_mask'
                        meta['marker_mask']=self.image(mask_name,marker.astype(np.uint8)*255)
                        meta['marker_pixels']=int(marker.sum())
                        meta['marker_median_rgb']=np.median(marker_pixels,axis=0).tolist()
                        if sid!='original':
                            assert np.any(marker_pixels!=original.rgb[marker])
                row['captures'][sid]['records']=e.family_appearance_records[-2:]
                assert all(x['family_id']==sid for x in e.family_appearance_records[-2:])
                assert np.array_equal(frame.E,original.E) and np.array_equal(frame.K,original.K)
                if sid!='original':
                    self.h.full_reset(env,self.h.opts('original'))
                    restored=self.review(env)
                    assert np.array_equal(restored.rgb,original.rgb)
                    assert [self.h.materials(e,i) for i in (0,1)]==baseline['materials']
                    row['captures'][sid]['restored']=True
                self.save()
            if task!='PickBottle' or auth['label_probe']['binding_path']=='private_upload':
                self.isolation(env,task,row,baseline,native,flip)
            if task=='UnscrewCap':
                self.cap_switch(env,row,native,flip)
        if task!='PickBottle':
            self.random(task,row)
        row['status']='passed'
        self.save()

    def beads(self):
        row=self.report['tasks']['PourBeads_diagnostic']=dict(status='running',gallery_camera='review',
            diagnostic='Independent instance; 16 native 4 mm spheres outside the bottle.',
            view=BEAD_VIEW,captures={})
        with contextlib.closing(self.h.make('PourBeads',{'enabled':True,'seed':109},review_view=BEAD_VIEW)) as env:
            e=env.unwrapped
            baseline=None
            for sid in self.h.variants:
                self.h.full_reset(env,self.h.opts(sid))
                if sid!='original':
                    self.h.verify_bindings(e,0,sid)
                self.h.bead_display(e)
                frame=self.review(env)
                stem=f'PourBeads_diagnostic_{sid}'
                event=row['captures'][sid]=dict(**self.save_review(stem,frame),spheres=[])
                self.save()
                if baseline is None:
                    baseline=frame
                    baseline_state=self.h.task_state(e,0)
                    row['camera']=dict(view=BEAD_VIEW,intrinsic=frame.K.tolist(),extrinsic=frame.E.tolist())
                else:
                    assert self.h.task_state(e,0)==baseline_state
                    assert np.array_equal(frame.K,baseline.K) and np.array_equal(frame.E,baseline.E)
                sphere_ids=np.zeros_like(frame.seg,dtype=np.uint8)
                for ordinal,particle in enumerate(e.particles,1):
                    current=frame.seg==self.entity(particle,0).per_scene_id
                    changed=int(np.any(frame.rgb[current]!=baseline.rgb[current],axis=-1).sum())
                    event['spheres'].append(dict(ordinal=ordinal,pixels=int(current.sum()),changed=changed))
                    assert current.sum()>=8,'individual bead not visible'
                    assert np.array_equal(current,baseline.seg==self.entity(particle,0).per_scene_id)
                    assert changed>0 if sid!='original' else changed==0
                    sphere_ids[current]=ordinal
                    event['spheres'][-1].update(median_rgb=np.median(frame.rgb[current],axis=0).tolist(),
                                                mask_sha256=digest(current))
                event['sphere_id_mask']=self.image(stem+'_sphere_ids',sphere_ids)
                union=sphere_ids!=0
                event['object_mask']=self.image(stem+'_mask',union.astype(np.uint8)*255)
                row['same_coordinate_crops']={'beads':self.crop(union)}
                self.save()
        row['status']='passed'


def run(phase,auth,*,report,output,**hooks):
    check=Followup(report,output,hooks)
    report['phase']=phase
    report['reused_job']=128861
    task='PickBottle'
    try:
        if phase=='label-probe':
            check.probe()
            report['status']='probe_ready_for_frame_review'
        elif phase in CLOSEOUT_CHECKS:
            report['reused_jobs']=[128861,128933,128943,128997]
            if phase=='unscrew-random':
                task='UnscrewCap'
                row=report['tasks'][task]=dict(status='running')
                check.random(task,row)
                row['status']='passed'
            elif phase=='pour-task':
                task='PourBeads'
                check.task_matrix(task,auth)
            elif phase=='pour-droplets':
                task='PourBeads_diagnostic'
                check.beads()
            else:
                task='UnscrewCap'
                check.cap_finish(auth['reused_evidence']['128943'],with_random=False,
                                 attached_reference=auth['reused_evidence']['128997']['attached_frame_sha256'])
            report['status']='engineering_passed_pending_visual_review' if phase!='unscrew-random' else 'passed'
        else:
            tasks=('PickBottle','UnscrewCap','PourBeads')
            if phase=='finish':
                report['reused_pick_bottle_job']=128933
                report['reused_unscrew_cap_fixed_job']=128943
                task='UnscrewCap'
                check.cap_finish(auth['reused_evidence']['128943'])
                tasks=('PourBeads',)
            elif phase=='remaining':
                report['reused_pick_bottle_job']=128933
                tasks=tasks[1:]
            for task in tasks:
                check.task_matrix(task,auth)
            task='PourBeads_diagnostic'
            check.beads()
            report['status']='engineering_passed_pending_visual_review'
    except Exception:
        report.update(status='failed',failed_task=task,traceback=traceback.format_exc()[-8000:])
        raise
    finally:
        check.save()
