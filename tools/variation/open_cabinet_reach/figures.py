"""Plot the measured handle-space and cabinet-root domains on the same world axes."""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle, Polygon as PatchPolygon
from matplotlib.lines import Line2D
from matplotlib.colors import ListedColormap
import numpy as np

import model as m

BLUE="#136cb0"
RED="#af3437"
GREEN="#18774a"
INK="#252c30"
CM=100
OUT=m.EVIDENCE


def panel(ax, data, yaw):
    ax.set_facecolor("#faf9f5")
    lo,hi=m.TABLE*CM
    ax.add_patch(Rectangle(lo,*(hi-lo),facecolor="#e7dec9",edgecolor="#565146",lw=1.5))
    for p in m.PLAN["robot_base"]:
        ax.add_patch(PatchPolygon(p["out"],facecolor="#aba296",edgecolor="#4d4943"))
    radius=json.loads((OUT/"CPU_RESULTS.json").read_bytes())["free_orientation"]["radius_m"]*CM
    ax.add_patch(Circle(m.MOUNT[:2]*CM,radius,fill=False,edgecolor=RED,lw=1.8,ls=(0,(6,3))))
    x,y=data["x"]*CM,data["y"]*CM
    ax.contourf(x,y,data["green"],levels=[.5,1.5],colors=["#95ceb0"],alpha=.55)
    ax.contour(x,y,data["green"],levels=[.5],colors=[GREEN],linewidths=.9)
    rx,ry=data["rx"]*CM,data["ry"]*CM
    ax.pcolormesh(rx,ry,np.ma.masked_equal(data["cells"],0),cmap=ListedColormap(["#78b5e1"]),shading="flat")
    ax.contour(rx[:-1]+.5,ry[:-1]+.5,data["cells"],levels=[.5],colors=[BLUE],linewidths=1)
    ax.add_patch(Rectangle((9,7),10,10,facecolor="#8b939a",edgecolor="#48545b",alpha=.58,lw=1.6,zorder=5))
    ax.add_patch(Rectangle((13,11),2,2,facecolor="#5c6267",edgecolor="none",zorder=6))
    ax.scatter(*((14,12)),s=22,c=RED,zorder=7)
    ax.plot(*(m.MOUNT[:2]*CM),marker="X",color=INK,ms=8)
    ax.set_aspect("equal")
    ax.grid(lw=.4,alpha=.3)
    ax.set_axisbelow(True)
    ax.spines[["top","right"]].set_visible(False)
    ax.set_xlabel("World X  (cm)     → farther from operator")
    ax.set_ylabel("World Y  (cm)     → operator’s left")


def cabinet(ax,origin,yaw):
    rot=m.rz(yaw)[:2,:2]
    for shape in (m.BODY,m.DOOR,m.HARDWARE):
        ax.add_patch(PatchPolygon(origin+shape@rot.T*CM,fill=False,edgecolor="#6a4a31",lw=1.25))
    pivot=origin+m.HINGE@rot.T*CM
    ax.plot(*pivot,'o',ms=3,color="#68482f")
    for a in (40,80):
        local=m.HINGE+(m.DOOR-m.HINGE)@m.rz(-a)[:2,:2].T
        ax.add_patch(PatchPolygon(origin+local@rot.T*CM,fill=False,edgecolor="#8c623e",ls=":",lw=1))
    arc=np.array([origin+m.handle_offset(yaw,a)*CM for a in np.linspace(0,80,81)])
    ax.plot(*arc.T,c="#704329",lw=1.8)
    for idx in (0,40,80):
        ax.plot(*arc[idx],"o",c="#704329",ms=3.2)
    ax.scatter(*origin,marker="+",color="#274b69",s=40,zorder=4)
    ax.annotate("80°",arc[-1],xytext=(-13,9),textcoords="offset points",fontsize=8,color="#624528")


def figures():
    presets=json.loads((m.ROOT/"tasks/cabinet_pouring/open_cabinet_cells.json").read_bytes())["presets_cm"]
    for yaw in (10,15,20):
        data=np.load(OUT/f"screen_{yaw}.npz")
        iy,ix=np.where(data["cells"])
        root=np.array([data["rx"][ix[len(ix)//2]]+.005,data["ry"][iy[len(iy)//2]]+.005])*CM
        fig,(overview,detail)=plt.subplots(1,2,figsize=(13.7,7.3),gridspec_kw={"width_ratios":[1,1.1]})
        fig.subplots_adjust(left=.07,right=.98,top=.80,bottom=.18,wspace=.19)
        for ax in (overview,detail):
            panel(ax,data,yaw)
            cabinet(ax,root,yaw)
        overview.set(xlim=(-211,88),ylim=(-125,150),title="Whole table and left arm")
        detail.set(xlim=(-105,66),ylim=(-69,68),title="Handle arc and cabinet-root positions")
        overview.text(36,106,"Table",color="#504b41",fontsize=11)
        overview.text(-110,-14,"Robot base",fontsize=9)
        overview.annotate("Arm mount",m.MOUNT[:2]*CM,xytext=(-145,48),arrowprops=dict(arrowstyle="-",lw=.8))
        detail.annotate("Cabinet",root+np.array([13,5]),xytext=(25,-32),fontsize=9,
                        color="#6a4a31",arrowprops=dict(arrowstyle="-",color="#6a4a31",lw=.8))
        detail.annotate("Table edge",(-42.45,-59),xytext=(-84,-55),arrowprops=dict(arrowstyle="->",lw=.9))
        if yaw==15:
            offsets={"near":(-12,8),"far":(6,-13),"left":(-3,9),"right":(4,-13)}
            for name,xy in presets.items():
                detail.scatter(*xy,s=34,c="white",edgecolor=INK,zorder=8)
                detail.annotate(name,xy,xytext=offsets[name],textcoords="offset points",
                                fontsize=9,weight="bold",zorder=9,
                                bbox=dict(facecolor="#faf9f5",alpha=.83,linewidth=0,pad=.8))
        fig.text(.065,.938,f"OpenCabinet   /   Cabinet yaw {yaw}°",fontsize=22,weight="bold",color=INK)
        fig.text(.066,.889,"Closed start   ·   left Sharpa arm   ·   handle height 45.21 cm   ·   CPU kinematic screen",fontsize=12,color="#47545a")
        handles=[Line2D([],[],color=RED,ls="--",lw=2,label="Free-orientation reach"),
                 Line2D([],[],color=GREEN,lw=4,label="Handle approach, 1 cm inset"),
                 Line2D([],[],color=BLUE,lw=5,label="Cabinet-root sampling"),
                 Line2D([],[],color="#727d82",lw=5,label="Prior ±5 cm box"),
                 Line2D([],[],color="#704329",lw=2,label="Handle path: 0° → 80°")]
        fig.legend(handles=handles,loc="lower center",bbox_to_anchor=(.51,.065),ncol=5,frameon=False,fontsize=10)
        width=(ix.max()-ix.min()+1); height=(iy.max()-iy.min()+1)
        fig.text(.07,.045,f"Blue extent: {width} cm near–far × {height} cm left–right.  Native jitter spans 2 × 2 cm; the prior explicit box spans 10 × 10 cm.",fontsize=10.5)
        fig.savefig(OUT/f"yaw_{yaw}.png",dpi=150,facecolor="white")
        plt.close(fig)


if __name__=="__main__":
    figures()
