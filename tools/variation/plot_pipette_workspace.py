"""Plot conditional workspace slices and full-table reference views from the shipped sampler."""
from pathlib import Path
import csv
import sys
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Rectangle, Polygon
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tasks.pipette_transfer.position_layout import XY_OFFSETS_M
from tasks.pipette_transfer.position_workspace import workspace
from tasks.pipette_transfer.pipette_transfer_long import PipetteConfig, PIPETTE_STAND_RANDOM_YAW_DEG
from tasks.pipette_transfer.position_layout import position_centers


def rect(ax, center, low, high, color, **kwargs):
    p = 100 * (np.asarray(center) + low)
    d = 100 * (np.asarray(high) - low)
    return ax.add_patch(Rectangle(p, *d, fill=False, edgecolor=color, **kwargs))


def make(directory, dof):
    source = directory.parent/'pipette_position_boundaries'
    tasks = [k for k in ('AspirateLiquid','DispenseLiquid','Long')
             if (dof.split('-')[0] in workspace(k)[0])]
    fig, axes = plt.subplots(len(tasks),2,figsize=(12,3.75*len(tasks)),squeeze=False)
    nominal=position_centers(PipetteConfig())
    report=json.loads((directory/'BUILD.json').read_text())
    backend='cuda' if (directory/'cuda/POINTS.csv').exists() else 'cpu'
    with (directory/backend/'POINTS.csv').open(encoding='utf-8') as stream:
        evidence=list(csv.DictReader(stream))
    for (wide, close),task in zip(axes,tasks):
        objects,slices,presets,half,_=workspace(task)
        center=np.array(presets['center']).reshape(-1,2)/1000
        geo=json.loads((source/f'GEOMETRY-{task}.json').read_text(encoding='utf-8'))
        lo,hi=np.array(report[task]['bounds'])*100
        wide.add_patch(Rectangle(lo,*(hi-lo),fc='#eee8d9',ec='#563e32',lw=1.4,zorder=0))
        wide.add_patch(Polygon(np.array(geo['robot_base_world_hull_xy'])*100,fc='#9eaaa5',alpha=.65))
        obj=dof.split('-')[0]
        idx=objects.index(obj)
        colors={'cup':'#b5824b','rack':'#527e64','stand':'#564e77'}
        for j,name in enumerate(objects):
            hull=np.array(geo['local_hulls_xy'][name])
            if name=='stand':
                hull=np.column_stack((-hull[:,1],hull[:,0]))
            hull=(hull+center[j])*100
            for ax in (wide,close):
                ax.add_patch(Polygon(hull,closed=True,fill=False,ec=colors[name],lw=1.25))
                if ax is wide:
                    ax.annotate(name,center[j]*100,xytext=(4,5),textcoords='offset points',fontsize=8)
        wide.set(xlim=(-125,83),ylim=(-126,126),title=task+'   |   table and robot')
        if dof.endswith('-xy'):
            all_rows=slices[90].reshape(-1,len(objects),2)
            other=[i for i in range(len(objects)) if i!=idx]
            mask=np.all(np.abs(all_rows[:,other]-center[other]*1000)<=half+1e-8,axis=(1,2))
            centers=np.unique(all_rows[mask,idx],axis=0)/10
            for ax in (wide,close):
                projected=np.unique(all_rows[:,idx],axis=0)/10
                marginals=[Rectangle(x-half/10,half/5,half/5) for x in projected]
                ax.add_collection(PatchCollection(marginals,facecolor='#d6e9f1',edgecolor='none',zorder=.8))
                boxes=[Rectangle(x-half/10,half/5,half/5) for x in centers]
                ax.add_collection(PatchCollection(boxes,facecolor='#60a9cc',edgecolor='none',alpha=.75,zorder=0.9))
                rect(ax,nominal[obj],-np.asarray(geo['native_xy_half_ranges_m'][obj]),
                     geo['native_xy_half_ranges_m'][obj],'#656865',linestyle=':')
                rect(ax,nominal[obj],*XY_OFFSETS_M[obj], '#646464',linestyle='--')
                ax.plot(*(np.array(nominal[obj])*100),'o',color='#af433b',ms=4)
                ax.plot(*(center[idx]*100),'x',color='#14597c',ms=6)
            for label,align in [('near',(2,-14)),('far',(2,5))]:
                point=np.asarray(presets[label]).reshape(-1,2)[idx]/10
                close.plot(*point,'o',mfc='white',mec='#355664',ms=4)
                close.annotate(label,point,xytext=align,textcoords='offset points',fontsize=8)
            c=center[idx]*100
            close.set(xlim=(c[0]-17,c[0]+17),ylim=(c[1]-14,c[1]+14),
                      title=f'{obj} XY at 90° | other objects at center preset')
        else:
            post=np.array(geo['dimensions']['stand']['shapes'][1]['pose'][:2])*100
            ctr=center[idx]*100
            axis=close
            for yaw,rows in slices.items():
                matches=np.all(np.abs(rows-center.flatten()*1000)<=half+1e-8,axis=1).any()
                rad=np.deg2rad(yaw)
                offset=np.array([[np.cos(rad),-np.sin(rad)],[np.sin(rad),np.cos(rad)]]) @ post
                end=ctr+offset
                axis.plot([ctr[0],end[0]],[ctr[1],end[1]],color='#206881' if matches else '#9c9c9c')
                axis.annotate(str(yaw)+'°'+('' if matches else ' excluded'),end,
                    xytext=(2,{78:-12,90:0,102:9}[yaw]),textcoords='offset points',fontsize=8)
            angles=np.deg2rad(np.linspace(90-PIPETTE_STAND_RANDOM_YAW_DEG,90+PIPETTE_STAND_RANDOM_YAW_DEG,40))
            axis.plot(ctr[0]+np.cos(angles)*post[0]-np.sin(angles)*post[1],
                      ctr[1]+np.sin(angles)*post[0]+np.cos(angles)*post[1],':',color='gray')
            axis.scatter(*ctr,color='#af433b',s=14)
            close.set(xlim=(ctr[0]-7,ctr[0]+11),ylim=(ctr[1]-8,ctr[1]+8),
                      title='Stand yaw | same rear post, fixed center-preset XY')
        rows=[r for r in evidence if r['task']=='PipetteTransfer'+task+'-Sharpa-v1' and
              r['outcome']=='initial_passed' and (r['id'] in presets or r['id'].startswith('edge-'))]
        margin,label=min((json.loads(r['initial'])['table_margin_m'][obj]*1000,r['id']) for r in rows)
        wide.set_xlabel(f'world X (cm)  |  tightest measured edge {margin:.1f} mm ({label})')
        for ax in (wide,close):
            ax.set_aspect('equal')
            ax.grid(alpha=.17)
            ax.set_ylabel('world Y (cm)')
        close.set_xlabel('world X (cm)')
    title='Pipette workspace   /   '+dof.replace('-', ' ')
    fig.suptitle(title,fontsize=17,ha='left',x=.06)
    legend=('Light blue: all target combinations   ·   dark blue: fixed-target slice   ·   dotted: native jitter'
            '   ·   dashed: old XY proposal   ·   red dot: nominal   ·   cross: center preset')
    if dof.endswith('yaw'):
        legend='Angle labels track the same post   ·   blue: fixed layout accepted   ·   gray: outside joint domain   ·   dotted arc: native yaw'
    fig.text(.055,.012,legend,fontsize=9)
    fig.tight_layout(rect=(0,.035,1,.965))
    fig.savefig(directory/(dof+'.png'),dpi=140)
    plt.close(fig)


if __name__=='__main__':
    path=ROOT/'docs/variation/evidence/pipette_workspace'
    for dof in ('stand-xy','stand-yaw','cup-xy','rack-xy'):
        make(path,dof)
