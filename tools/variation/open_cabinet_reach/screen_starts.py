"""Intersect the PR #46 cells with neutral-start and approach tests; runtime rechecks actual noise."""
import json
from pathlib import Path
import sys
import numpy as np
from scipy.ndimage import label
import model as m
from measure import target_frames
from start_mesh import DATA, OUT, cabinet, enclosures

sys.path.insert(0,str(m.ROOT/"tasks/cabinet_pouring"))
import start_clearance as sc


def measured_rows(cells,rx,ry):
    rows=[]
    for j in np.flatnonzero(cells.any(axis=1)):
        edges=np.flatnonzero(np.diff(np.r_[False,cells[j],False])).reshape(-1,2)
        rows.extend([[int(ry[j]),int(rx[a]),int(rx[b])] for a,b in edges])
    return rows


def main(export):
    data=enclosures(cabinet(export))
    axes=[10,15,20]
    raw=[np.load(m.EVIDENCE/f"screen_{yaw}.npz") for yaw in axes]
    rx=np.rint(raw[0]["rx"]*100).astype(int);ry=np.rint(raw[0]["ry"]*100).astype(int)
    union=np.logical_or.reduce([d["cells"] for d in raw])
    j,i=np.where(union)
    xx=rx[i.min():i.max()+2];yy=ry[j.min():j.max()+2]
    nodes=np.full((3,len(yy),len(xx),7),np.nan)
    targets=[];rotations=[]
    for k,yaw in enumerate(axes):
        offs,rots,_=target_frames(yaw)
        targets.append(np.r_[offs[0],m.Z]);rotations.append(rots[0])
        for j,i in zip(*np.where(raw[k]["cells"])):
            for u,v in [(0,0),(0,1),(1,0),(1,1)]:
                x,y=rx[i+u],ry[j+v];node=nodes[k,y-yy[0],x-xx[0]]
                if np.isfinite(node).all():continue
                ok,q=m.solve(np.r_[[x/100,y/100]+offs[0],m.Z],rots[0],m.HOME)
                assert ok,(yaw,x,y)
                node[:]=q
    np.savez_compressed(DATA,**data,pre_q=nodes,grid_min=[xx[0],yy[0]],target=targets,rotation=rotations)
    sc.geometry.cache_clear()
    rows={};candidates={}
    for k,yaw in enumerate(axes):
        old=raw[k]["cells"]
        cells=np.zeros_like(old)
        cache={};minimum={}
        def check(x,y):
            key=(x,y)
            if key not in cache:
                xy=np.array(key)/100
                end=sc.pregrasp(sc.geometry(),xy,yaw)
                if end is None: cache[key]=(0.,0.)
                else:
                    a,b=sc.clearance(xy,yaw,m.HOME,end);cache[key]=(a[0],b[0])
            return cache[key]
        for j,i in zip(*np.where(old)):
            x,y=rx[i],ry[j]
            vals=[check(x+u,y+v) for u,v in [(0,0),(1,0),(0,1),(1,1),(.5,.5)]]
            start,path=np.min(vals,axis=0)
            cells[j,i]=start>=sc.MIN_START_CLEARANCE_MM and path>=sc.MIN_APPROACH_CLEARANCE_MM
            minimum[(j,i)]=min(start-sc.MIN_START_CLEARANCE_MM,path-sc.MIN_APPROACH_CLEARANCE_MM)
        labels,n=label(cells);assert n,(yaw,np.max(list(cache.values()),axis=0))
        cells=labels==np.bincount(labels.ravel())[1:].argmax()+1
        rows[str(yaw)]=measured_rows(cells,rx,ry)
        np.savez_compressed(OUT/f"roots_{yaw}.npz",cells=cells)
        print(yaw,int(cells.sum()),flush=True)
        if yaw==15:
            for j,i in zip(*np.where(cells)):
                x,y=rx[i]+.5,ry[j]+.5
                start,path=check(x,y)
                if start>=sc.MIN_START_CLEARANCE_MM+18 and path>=sc.MIN_APPROACH_CLEARANCE_MM+2:
                    candidates[x,y]=[start,path]
    def pair(axis):
        options=[]
        for other in sorted({p[1-axis] for p in candidates}):
            line=sorted([p for p in candidates if p[1-axis]==other],key=lambda p:p[axis])
            a,b=line[0],line[-1]
            options.append((b[axis]-a[axis],min(candidates[a][0],candidates[b][0]),a,b))
        return max(options)[2:]
    near,far=pair(0);right,left=pair(1)
    presets=dict(near=near,far=far,left=left,right=right)
    assert len(set(presets.values()))==4,presets
    path=m.ROOT/"tasks/cabinet_pouring/open_cabinet_clear_cells.json"
    path.write_text(json.dumps(dict(rows_cm=rows,presets_cm=presets),separators=(",",":"))+"\n",encoding="utf8",newline="\n")
    print(presets)


if __name__=="__main__":main(Path(sys.argv[1]))
