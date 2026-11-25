"""Render independent Furniture XY/yaw boundary plots from the runtime table."""
import argparse
import csv
import json
from itertools import product
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.patches import Polygon, Rectangle
import numpy as np

from tasks.furniture_assembly.workspace import ROLES, fixed_layout, rotate, workspace, world_layout
from tools.variation.build_furniture_workspace import panel, rail
from tools.variation.furniture_position_samples import CENTERS, XY_OFFSETS_M, rect
from tools.variation.plot_furniture_positions import check_plot_geometry, native_bounds


def rectangle(ax, xy, half, color, **kwargs):
    ax.add_patch(Rectangle(np.asarray(xy)-half, 2*half[0],2*half[1],color=color,**kwargs))


def render(kind, role, yaw_plot, geometry, measured, destination):
    _,groups,presets=workspace(kind)
    reference=presets["reference"]
    selected=ROLES[kind].index(role)
    roots=ROLES[kind]
    fixed_angles=[reference[r+"_yaw_deg"] for r in roots]
    ref=np.array(reference[roots[0]+"_xy_m"])
    if len(roots)==2:
        rel=rotate(np.array(reference["rail_xy_m"])-ref,-fixed_angles[0])
        base=np.r_[ref,rel]
    else:
        base=ref
    stages=[g for g in groups if all(a==fixed_angles[i] for i,a in enumerate(g[0]) if i!=selected)]
    if not yaw_plot:
        stages=[g for g in stages if g[0][selected]==fixed_angles[selected]]
    fig,axes=plt.subplots(1,1+len(stages),figsize=(4.1*(1+len(stages)),5.0),layout="constrained")
    table_center=np.array(geometry["table_center_xy_m"])*100
    table_half=np.array(geometry["table_half_xy_m"])*100
    half_obj={"panel":panel.PANEL_HALF[:2],"rail":rail.RAIL_HALF[:2],"rack":panel.RACK_BASE_HALF[:2]}[role]
    def background(ax):
        rectangle(ax,table_center,table_half,"#eadfc8",zorder=-5)
        ax.add_patch(Polygon(100*np.array(geometry["base_collision_hull_xy_m"]),color="#656968",alpha=.68))
        ax.set_aspect("equal")
        ax.set_xlabel("world X (cm)")
        ax.set_ylabel("world Y (cm)")
        ax.grid(alpha=.12)
    full=axes[0]
    background(full)
    full.set(xlim=(-135,82),ylim=(-124,124),title="Whole table")
    for r in roots:
        loc=np.asarray(reference[r+"_xy_m"])*100
        full.scatter(*loc,s=18,color="#345975")
        full.annotate(r,loc,fontsize=8,xytext=(3,4),textcoords="offset points")
    full.add_patch(Polygon(100*rect(panel.PLACE_CENTER,panel.PLACE_REGION_HALF_SIZE).T,
                           closed=True,fill=False,edgecolor="#407f61",lw=1.2))
    root_center=np.array(CENTERS[role])
    for ax,(angles,centers,half) in zip(axes[1:],stages):
        background(ax)
        xoff,yoff=XY_OFFSETS_M[role]
        ax.add_patch(Rectangle(100*(root_center+[xoff[0],yoff[0]]),100*(xoff[1]-xoff[0]),
                               100*(yoff[1]-yoff[0]),fill=False,edgecolor="#414a4b",lw=1.4,ls="--"))
        nx,ny,_=native_bounds(role)
        if role=="panel" and kind=="InsertRail":
            nx=ny=0.
        if nx or ny:
            rectangle(ax,root_center*100,np.array([nx,ny])*100,"#929795",alpha=.37)
        outlines=[]
        step=2*selected
        other=[n for n in range(len(base)) if n not in (step,step+1)]
        for c in centers:
            if other and np.any(np.abs(c[other]-base[other])>half[other]+1e-8):
                continue
            vertices=[]
            for signs in ((-1,-1),(1,-1),(1,1),(-1,1)):
                z=c.copy()
                z[step:step+2]+=half[step:step+2]*signs
                xy=world_layout(kind,angles,z)[role+"_xy_m"]
                vertices.append(100*np.array(xy))
            outlines.append(vertices)
        ax.add_collection(PolyCollection(outlines,facecolors="#4794c2",edgecolors="#246a93",linewidths=.3))
        ax.scatter(*(100*root_center),s=27,c="#c72c35",zorder=5)
        pivot=np.array(reference[role+"_xy_m"])
        if yaw_plot:
            ax.add_patch(Polygon(100*rect(pivot,half_obj,angles[selected]).T,closed=True,
                                 fill=False,edgecolor="#846d50",lw=1.2))
        for row in measured:
            if row["id"] not in ("near","far") or row["expected"]!="accept":continue
            layout=json.loads(row["layout"])
            if tuple(layout[r+"_yaw_deg"] for r in roots)!=angles:continue
            if kind=="InsertRail" and role=="panel":continue
            point=100*np.array(layout[role+"_xy_m"])
            ax.scatter(*point,facecolor="white",edgecolor="#1d3648",s=32,zorder=5)
            ax.annotate(row["id"],point,fontsize=8,xytext=(3,5),textcoords="offset points")
        ax.set_title(f"{role} yaw {angles[selected]:+g}°")
        extent=np.array(outlines).reshape(-1,2) if outlines else root_center[None]*100
        if yaw_plot:extent=np.vstack([extent,100*rect(pivot,half_obj,angles[selected]).T])
        lower=np.minimum(extent.min(axis=0),100*(root_center+[xoff[0],yoff[0]]))-2
        upper=np.maximum(extent.max(axis=0),100*(root_center+[xoff[1],yoff[1]]))+2
        ax.set(xlim=(lower[0],upper[0]),ylim=(lower[1],upper[1]))
    title = f"{kind}  /  {role}  /  "+("orientation" if yaw_plot else "translation")
    condition = "Other coordinates fixed at reference in the stored panel-relative frame." if len(roots)==2 else "Independent world-XY cells at the indicated yaw."
    fig.suptitle(title+"\n"+condition,fontsize=12)
    metric = {"rack":"rack_to_place_y_m","rail":"rail_to_panel_y_m","panel":"panel_inside_place_m"}[role]
    tight = min((row for row in measured if row["expected"]=="accept"),
                key=lambda row:json.loads(row["clearances_m"])[metric])
    margin = json.loads(tight["clearances_m"])[metric]
    fig.supxlabel(f"Blue  screened cells   ·   Grey  native proposals   ·   Dashed  prior explicit domain   ·   Red  nominal\n"
                  f"Measured minimum across tested layouts: {metric.removesuffix('_m').replace('_',' ')} "
                  f"{1000*margin:.2f} mm  ({tight['id']}).",fontsize=8)
    fig.savefig(destination,dpi=155)
    plt.close(fig)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--points",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    geo=check_plot_geometry()
    with args.points.open(encoding="utf-8",newline="") as f:
        data=list(csv.DictReader(f))
    for kind,roles in ROLES.items():
        measured=[row for row in data if kind in row["task"]]
        for role in roles:
            for mode in ("xy","yaw"):
                render(kind,role,mode=="yaw",geo,measured,args.output/f"{kind}-{role}-{mode}.png")
