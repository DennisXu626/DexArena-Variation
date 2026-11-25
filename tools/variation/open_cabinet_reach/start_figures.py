"""Same axes as PR #46. Shaded roots are distinct from the reach maps and physical parts."""
import argparse
import json
from pathlib import Path
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon
from scipy.spatial import ConvexHull
from figures import plt, panel, cabinet as draw_cabinet, BLUE, GREEN, RED
import model as m
from start_mesh import OUT, cabinet, hand, arm_pose


def maps():
    spec=json.loads((m.ROOT/"tasks/cabinet_pouring/open_cabinet_clear_cells.json").read_bytes())
    for yaw in (10,15,20):
        old=dict(np.load(m.EVIDENCE/f"screen_{yaw}.npz"))
        cells=np.load(OUT/f"roots_{yaw}.npz")["cells"]
        rx,ry=old["rx"]*100,old["ry"]*100
        j,i=np.where(cells);k=len(j)//2;root=np.array([rx[i[k]]+.5,ry[j[k]]+.5])
        fig,axes=plt.subplots(1,2,figsize=(13.7,7.3),gridspec_kw={"width_ratios":[1,1.1]})
        fig.subplots_adjust(left=.07,right=.98,top=.80,bottom=.18,wspace=.19)
        for ax in axes:
            panel(ax,old,yaw)
            ax.pcolor(rx,ry,np.ma.masked_equal(old["cells"] & ~cells,False),cmap=plt.matplotlib.colors.ListedColormap(["#d9e4eb"]),shading="flat",zorder=3)
            ax.contour(rx[:-1]+.5,ry[:-1]+.5,old["cells"],levels=[.5],colors=["#27628b"],linestyles="--",linewidths=1.1,zorder=4)
            ax.pcolor(rx,ry,np.ma.masked_equal(cells,False),cmap=plt.matplotlib.colors.ListedColormap(["#1973b3"]),shading="flat",zorder=4)
            draw_cabinet(ax,root,yaw)
        overview,detail=axes
        overview.set(xlim=(-211,88),ylim=(-125,150),title="Whole table and left arm")
        detail.set(xlim=(-105,66),ylim=(-69,68),title="Cabinet roots and handle arc")
        overview.text(36,106,"Table");overview.text(-110,-14,"Robot base",fontsize=9)
        overview.annotate("Arm mount",m.MOUNT[:2]*100,(-145,48),arrowprops=dict(arrowstyle="-",lw=.8))
        detail.annotate("Table edge",(-42.45,-59),(-84,-55),arrowprops=dict(arrowstyle="->",lw=.9))
        detail.text(23,39,"Cabinet",color="#633f26")
        if yaw==15:
            for name,xy in spec["presets_cm"].items():
                dx,dy={"near":(-24,9),"far":(10,2),"left":(-15,15),"right":(7,-16)}[name]
                detail.scatter(*xy,color="white",edgecolor="#16384b",s=23,zorder=9)
                detail.annotate(name,xy,(dx,dy),textcoords="offset points",fontsize=9,zorder=10,
                                bbox=dict(facecolor="#faf8ef",edgecolor="none",pad=.7))
        fig.text(.065,.936,f"OpenCabinet   /   {yaw}° cabinet yaw",fontsize=23,weight="bold")
        fig.text(.065,.883,"Closed-door starts   ·   neutral arm map   ·   noisy arm pose checked again on each reset",fontsize=12)
        handles=[Line2D([],[],color=RED,ls="--",label="Arm reach"),Patch(color="#95ceb0",label="Handle reach, 1 cm inset"),
                 Line2D([],[],color="#27628b",ls="--",label="Previous roots (#46)"),
                 Patch(color="#d9e4eb",label="Removed"),Patch(color="#1973b3",label="Retained"),
                 Line2D([],[],color="#704329",label="Handle arc to 80°")]
        fig.legend(handles=handles,ncol=6,loc="lower center",bbox_to_anchor=(.51,.068),frameon=False)
        fig.text(.07,.046,f"{cells.sum()} of {old['cells'].sum()} one-cm² cells retained. Start ≥60 mm; approach ≥12 mm. No cells added outside the previous pull screen.",fontsize=10.5)
        fig.savefig(OUT/f"yaw_{yaw}.png",dpi=150);plt.close(fig)


def near_figure(export):
    c=cabinet(export);d=json.loads((OUT/"cpu_audit.json").read_bytes());pose=arm_pose(np.array(d["sampled_arm_q"]))
    fig,axes=plt.subplots(1,2,figsize=(12.9,6.3),sharex=True,sharey=True)
    fig.subplots_adjust(left=.077,right=.97,top=.80,bottom=.16,wspace=.12)
    for ax,key in zip(axes,("near","new_near")):
        rec=d["seed7"][key];xy=rec["root_xy_m"];closest=rec["mesh"]
        def shape(pts,fc,ec,order):
            points=np.unique(pts.reshape(-1,3)[:,:2]*100,axis=0)
            if len(points)>2:
                poly=points[ConvexHull(points).vertices]
                ax.add_patch(Polygon(poly,facecolor=fc,edgecolor=ec,linewidth=.5,zorder=order))
        for n,(tri,_) in c.items():
            col={"door":"#c3895f","body":"#ddd0b6","handle":"#584635"}[n.split(":")[0]]
            shape(tri@m.rz(15).T+np.r_[xy,0.],col,"#886c51",{"body":1,"door":2,"handle":3}[n.split(":")[0]])
        for n,(tri,_) in hand().items():
            shape(tri@pose[:3,:3].T+pose[:3,3],"#a9bbc5" if "hand_" in n else "#45798e","#243c48",4)
        a,b=np.array([closest["hand_xyz_m"],closest["cabinet_xyz_m"]])[:,:2]*100
        ax.plot(*np.stack([a,b]).T,color="#ab2424",lw=2.5,zorder=7)
        ax.scatter(*a,s=28,facecolor="white",edgecolor="#ab2424",zorder=8)
        ax.scatter(*b,s=22,marker="x",color="#ab2424",zorder=8)
        ax.annotate("Closest pair",(a+b)/2,(-40,0),fontsize=9,color="#8b1d1b",arrowprops=dict(arrowstyle="-",color="#8b1d1b"),zorder=9)
        ax.set(aspect="equal",xlim=(-45,1),ylim=(-32,8),xlabel="World X  (cm)",facecolor="#ece5d7")
        label=(f'{closest["inside_witness_mm"]:.1f} mm inside door' if key=="near" else f'{closest["mesh_gap_mm"]:.1f} mm clear')
        ax.set_title(("Old near" if key=="near" else "Proposed near")+"   /   "+label,fontsize=14,loc="left",weight="bold")
        ax.grid(alpha=.15);ax.set_axisbelow(True)
    axes[0].set_ylabel("World Y  (cm)")
    fig.suptitle("What changed at the near start?",fontsize=22,x=.08,ha="left",weight="bold")
    fig.text(.08,.891,"Same native arm draw (CPU seed 7), closed door, 15° yaw. World top view; dimensions use full 3D meshes.",fontsize=11.2)
    fig.legend(handles=[Patch(color=c,label=n) for c,n in [("#ddd0b6","Cabinet body"),("#c3895f","Closed door"),("#584635","Handle"),("#a9bbc5","Wrist and palm"),("#45798e","Fingers")]],
               loc="lower center",ncol=5,frameon=False,bbox_to_anchor=(.5,.04))
    fig.savefig(OUT/"near_start.png",dpi=150);plt.close(fig)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("export",type=Path)
    maps();near_figure(p.parse_args().export)
