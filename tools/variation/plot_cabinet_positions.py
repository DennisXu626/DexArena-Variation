"""Plot physical neighbours and measured position requests for Cabinet & Pouring."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager, patheffects, pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Patch, Polygon, Rectangle
from matplotlib.ticker import MaxNLocator
import numpy as np

BLUE, BLUE_FILL, GREY, GREY_FILL = "#186db1", "#9ac8e7", "#697179", "#bec2c4"
RED, INK = "#bf3236", "#252a28"
PAPER, FLOOR, TABLE, EDGE = "#f6f2e9", "#f6f3ec", "#e5decd", "#5b574b"
WOOD, BROWN, SWEEP, COPPER = "#ba967a", "#664533", "#e5b998", "#a26947"
TEAL, TEAL_FILL = "#426859", "#c1d1be"
C, SHELF, OLD, HANDOFF, BOWL = map(np.array, ([14,12],[-21,-.5],[-22,-20],[-25,-35],[-20,-50]))
FILES = ["01_cabinet_xy.png","02_cabinet_yaw.png","03_shelf_bottle.png","04_table_handoff.png","05_bowl_xy.png"]


def rotation(angle):
    a = np.deg2rad(angle)
    return np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]])


def world(points, yaw=15, center=C):
    return np.asarray(points) @ rotation(yaw).T + center


def square(center, half):
    return center + np.array([[-half,-half],[half,-half],[half,half],[-half,half]])


def patch(ax, points, ec, fc="none", **kw):
    ax.add_patch(Polygon(points, closed=True, ec=ec, fc=fc, lw=kw.pop("lw",1.3), **kw))


def disk(ax, center, radius, ec, fc="none", **kw):
    ax.add_patch(Circle(center, radius, ec=ec, fc=fc, lw=kw.pop("lw",1.3), **kw))


def region(ax, rings, ec, fc, **kw):
    # Compound paths preserve holes in the projected collision footprint.
    from matplotlib.path import Path as DrawPath
    from matplotlib.patches import PathPatch
    for piece in rings:
        paths = [DrawPath(np.asarray(vertices), closed=True) for vertices in [piece["out"],*piece["holes"]]]
        ax.add_patch(PathPatch(DrawPath.make_compound_path(*paths),ec=ec,fc=fc,lw=kw.get("lw",1.1),
                               ls=kw.get("ls","-"),alpha=kw.get("alpha",1),zorder=kw.get("zorder",1.4)))


def label(ax, at, s, size=10, color=INK, **kw):
    t = ax.text(*at,s,ha=kw.pop("ha","center"),va="center",fontsize=size,color=color,
                zorder=12,linespacing=1.12,clip_on=True,**kw)
    t.set_path_effects([patheffects.withStroke(linewidth=2.25,foreground=PAPER,alpha=.85)])
    return t


def call(ax, to, at, s, size=9):
    ax.annotate(s,xy=to,xytext=at,ha="center",va="center",color=INK,fontsize=size,
                bbox=dict(boxstyle="round,pad=.16",fc=PAPER,ec="none",alpha=.91),
                arrowprops=dict(arrowstyle="->",lw=1,color=INK,shrinkA=2,shrinkB=1),
                annotation_clip=True,zorder=13)


def samples(ax, pts, centers):
    p = np.atleast_2d(pts)
    ax.scatter(*p.T, s=40, c="white", edgecolors=INK, lw=1.15, zorder=9)
    for c in centers:
        ax.scatter(*c,s=24,facecolors=RED,edgecolors="white",lw=.55,zorder=10)


def ring(c, r):
    a=np.arange(8)*np.pi/4
    return np.vstack([c,c+r*np.column_stack([np.cos(a),np.sin(a)])])


def table(ax,g):
    lo,hi=np.array(g["table_xy_cm"])
    ax.add_patch(Rectangle(lo,*(hi-lo),fc=TABLE,ec=EDGE,lw=1.7,zorder=0))


def setup(ax, limits, xlabel="场景 X  (cm)", ylabel="Y  (cm)"):
    ax.set(xlim=limits[:2],ylim=limits[2:],aspect="equal",xlabel=xlabel,ylabel=ylabel,facecolor=FLOOR)
    ax.set_axisbelow(False)
    ax.grid(color="#897c65",alpha=.16,lw=.6,zorder=.4)
    for s in ax.spines.values():
        s.set_color("#a59a87")
    ax.tick_params(labelsize=9,color=EDGE)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=6,integer=True))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=7,integer=True))


def panel(ax, title):
    ax.set_title(title,loc="left",pad=10,fontsize=13,fontweight="bold",color=INK)


def canvas(title, subtitle, footer, layout="pair"):
    fig=plt.figure(figsize=(13.8,7.6),facecolor=PAPER)
    fig.text(.05,.926,title,size=23,weight="bold",color=INK)
    fig.text(.052,.876,subtitle,size=11,color=EDGE)
    fig.legend(handles=[
        Patch(fc=GREY_FILL,ec=GREY,label="旧范围"),Patch(fc=BLUE_FILL,ec=BLUE,label="新范围"),
        Line2D([],[],marker="o",ls="",mec="white",mfc=RED,label="范围中心",ms=7.5),
        Line2D([],[],marker="o",ls="",mec=INK,mfc="white",label="采样点",ms=7.5)],
        loc="upper right",bbox_to_anchor=(.964,.963),ncol=4,frameon=False,
        fontsize=10,handlelength=1.4,columnspacing=1.0,handletextpad=.45)
    if layout=="three":
        gs=fig.add_gridspec(1,3,left=.055,right=.978,bottom=.185,top=.795,width_ratios=[.85,1,1],wspace=.26)
    else:
        gs=fig.add_gridspec(1,2,left=.065,right=.96,bottom=.18,top=.80,width_ratios=[.9,1.45],wspace=.17)
    fig.add_artist(Line2D([.052,.951],[.112,.112],color="#bdb19d",lw=.85))
    fig.text(.052,.065,footer,size=10.3,color=INK)
    return fig,[fig.add_subplot(cell) for cell in gs]


def cabinet(ax,g,yaw=15,center=C,body=True,angles=(0,90),body_fill=WOOD,body_edge=BROWN):
    hinge=np.array(g["hinge"])
    if body:
        patch(ax,world(g["body"],yaw,center),body_edge,body_fill,zorder=2.6)
    for q in angles:
        for key,col in (("door","#916448"),("handle","#433c35")):
            p=(np.asarray(g[key])-hinge) @ rotation(-q).T + hinge
            patch(ax,world(p,yaw,center),BROWN,col,lw=.9,zorder=4)
    pivot=world(hinge,yaw,center)
    ax.scatter(*pivot,s=17,c=INK,marker="s",zorder=7)


def bottle_on_shelf(ax,g):
    patch(ax,world(np.asarray(g["bottle_collision"])+SHELF),TEAL,TEAL_FILL,zorder=6)


def handoff(ax,g,both=False,points=False):
    if both:
        disk(ax,OLD,15,GREY,GREY_FILL,alpha=.82,zorder=2.35)
        disk(ax,OLD,15-g["base_radius_cm"],GREY,ls="--",zorder=4)
    ec,fc=(BLUE,BLUE_FILL) if both else (TEAL,TEAL_FILL)
    disk(ax,HANDOFF,16,ec,fc,alpha=.74,zorder=2.4)
    disk(ax,HANDOFF,16-g["base_radius_cm"],ec,ls="--",zorder=4)
    if points:
        samples(ax,ring(HANDOFF,16-g["base_radius_cm"]),[HANDOFF,OLD])


def overview(ax,g,kind):
    setup(ax,(-143,88,-131,131))
    table(ax,g)
    region(ax,g["robot_base"],"#615c52","#aaa493",zorder=1)
    label(ax,(-83,1),"机器人底座",8.8)
    label(ax,(19,100),"Table  桌面",12)
    label(ax,(16,-103),"物理桌面范围",8.5,EDGE)
    if kind=="bowl":
        disk(ax,OLD,15.402,TEAL,TEAL_FILL,zorder=2)
        disk(ax,BOWL,12,BLUE,BLUE_FILL,zorder=2)
        label(ax,OLD,"Bottle",8);label(ax,BOWL,"Bowl",8)
    else:
        if kind!="shelf":
            key={"move":"sweep_xy","yaw":"sweep_yaw","transfer":"sweep_new_low"}[kind]
            region(ax,g[key],COPPER,SWEEP)
        cabinet(ax,g,angles=(90,) if kind in ("shelf","transfer") else (0,90))
        bottle_on_shelf(ax,g)
        handoff(ax,g,both=kind=="transfer")
        label(ax,(16,16),"Cabinet",8.5)
        label(ax,HANDOFF,"Bottle" if kind=="transfer" else "放瓶区",8)
    call(ax,(-42.45,-72),(-91,-88),"桌边 X = −42.45",8.2)
    panel(ax,"整桌与周边物体")


def shelf_window(ax,g):
    setup(ax,(-38,29,-23,24),"柜体局部 X  (cm)")
    lo,hi=np.array(g["table_xy_cm"])
    corners=np.array([[lo[0],lo[1]],[hi[0],lo[1]],hi,[lo[0],hi[1]]])
    ax.set_facecolor(FLOOR)
    patch(ax,(corners-C)@rotation(15),EDGE,TABLE,zorder=0)
    patch(ax,g["shelf"],BROWN,"#d9bf9e",zorder=1.3)
    for wall in g["walls"]:
        patch(ax,wall,BROWN,WOOD,lw=.9,zorder=2.7)
    cabinet(ax,g,yaw=0,center=np.zeros(2),body=False,angles=(90,))
    label(ax,(4,10),"Cabinet · 层板",10)
    label(ax,(22,0),"后壁",8.8,rotation=90)
    label(ax,(-27.6,-11),"柜口",8.7,rotation=90)
    disk(ax,SHELF,g["base_radius_cm"],TEAL,TEAL_FILL,zorder=3)
    label(ax,(-21,-.5),"Bottle",8.3)
    call(ax,(-34,-4),(-15,-9),"取出",8.5)
    panel(ax,"层板、侧壁与柜口")


def render(root):
    g=json.loads((root/"plan_geometry.json").read_text(encoding="utf-8"))
    radius=g["base_radius_cm"]
    def save(n,fig):
        fig.savefig(root/FILES[n-1],dpi=165,facecolor=PAPER)
        plt.close(fig)

    fig,(ov,ax)=canvas("单门柜  /  XY 平移","OpenCabinet 关门、PickBottle 开门 90°　·　柜体朝向固定 15°",
        "柜根 (14, 12) cm，原生各轴 ±1 cm，候选各轴 ±5 cm。两任务平移样点初态各 9/9 通过；把手操作与抓瓶退出仍待遥操作复核。")
    overview(ov,g,"move");setup(ax,(-63,58,-54,53));table(ax,g)
    region(ax,g["sweep_xy"],COPPER,SWEEP)
    patch(ax,g["body_move15"],BROWN,"#d7b99b",ls="--",zorder=2)
    cabinet(ax,g);bottle_on_shelf(ax,g);handoff(ax,g)
    patch(ax,square(C,5),BLUE,BLUE_FILL,zorder=5)
    patch(ax,square(C,1),GREY,GREY_FILL,zorder=6)
    samples(ax,[(x,y) for x in (9,14,19) for y in (7,12,17)],[C])
    label(ax,(22,25),"Cabinet",11,rotation=15)
    label(ax,(-32,2),"门扫掠",9.5)
    label(ax,HANDOFF,"Bottle · 交接区",10)
    call(ax,world(g["hp"]),(-29,-14),"接近把手")
    call(ax,world(SHELF),(1,39),"层板 Bottle")
    call(ax,(19,12),(41,9),"柜根范围")
    panel(ax,"柜体移动、门扫掠与放瓶区")
    save(1,fig)

    fig,(ov,ax)=canvas("单门柜  /  柜体朝向","OpenCabinet、PickBottle　·　柜根固定 (14, 12) cm　·　门关节从 0° 开至 90°",
        "三种柜体朝向的初态在两个任务各 3/3 通过。白点取在同一个后角，显示整体旋转；红点是固定柜根，方点是门轴。")
    overview(ov,g,"yaw");setup(ax,(-62,62,-54,57));table(ax,g)
    region(ax,g["sweep_yaw"],COPPER,SWEEP)
    cabinet(ax,g);bottle_on_shelf(ax,g);handoff(ax,g)
    corner=np.array([26.36,18.42])
    for yaw,ls,offset in [(10,"-",[13,-5]),(15,"--",[14,4]),(20,":",[6,12])]:
        col=GREY if yaw==15 else BLUE
        patch(ax,world(g["body"],yaw),col,ls=ls,lw=1.5,zorder=5)
        hinge=np.asarray(g["hinge"])
        for angle in (0,90):
            d=(np.asarray(g["door"])-hinge)@rotation(-angle).T+hinge
            patch(ax,world(d,yaw),col,ls=ls,lw=.85,zorder=4.5)
        point=world(corner,yaw)
        samples(ax,[point],[C])
        call(ax,point,point+offset,f"{yaw}°",9)
    label(ax,(18,17),"Cabinet",10,rotation=15)
    label(ax,(-33,1),"门扫掠",10)
    label(ax,HANDOFF,"Bottle · 交接区",10)
    call(ax,world(g["hinge"]),(-23,35),"门轴")
    call(ax,world(g["hp"]),(-22,-17),"关门把手")
    panel(ax,"同一柜根的三个朝向")
    save(2,fig)

    fig,(ov,context,ax)=canvas("层板  /  瓶中心范围","PickBottle　·　开门 90°，柜体 15°　·　柜内名义瓶心 (−21, −0.5) cm　·　局部 +X 向柜内",
        "九个候选点均获得真实层板支撑。叉号为 X = −24 cm 的三个越界请求，均被拒绝；最浅合法点的完整瓶底余量约 0.025 mm。","three")
    overview(ov,g,"shelf");shelf_window(context,g)
    setup(ax,(-29,-12,-8,8),"柜体局部 X  (cm)")
    ax.set_facecolor(TABLE)
    patch(ax,g["shelf"],BROWN,"#d9bf9e",zorder=1)
    ax.axvline(g["front_cm"],color=BROWN,lw=1.8)
    rect=np.array([[-22.04,-3.5],[-18,-3.5],[-18,2.5],[-22.04,2.5]])
    patch(ax,rect,BLUE,BLUE_FILL,zorder=3)
    patch(ax,square(np.zeros(2),1)@rotation(-15).T+SHELF,GREY,GREY_FILL,zorder=4)
    disk(ax,[-22.04,-.5],radius,TEAL,ls="--",zorder=6)
    disk(ax,[-18,2.5],radius,TEAL,ls=":",zorder=6)
    samples(ax,[(x,y) for x in (-22.04,-20.02,-18) for y in (-3.5,-.5,2.5)],[SHELF,[-20.02,-.5]])
    samples(ax,[(-24,y) for y in (-3.5,-.5,2.5)],[])
    ax.scatter([-24]*3,[-3.5,-.5,2.5],s=18,c=INK,marker="x",zorder=10)
    label(ax,(-25.6,4.7),"柜口",9)
    label(ax,(-19.6,-5.7),"Bottle · 瓶心范围",9)
    call(ax,(-17.8,5.02),(-15.7,6.4),"深角瓶底",8.1)
    ax.annotate("手指接近",xy=(-18,-7),xytext=(-24,-7),fontsize=8,va="center",
                arrowprops=dict(arrowstyle="->",color=INK,lw=1),zorder=9)
    panel(ax,"瓶底与层板前缘")
    save(3,fig)

    fig,(ov,ax)=canvas("桌面  /  瓶位交接区","PickBottle 放置目标 → UnscrewCap 起点　·　实线为瓶底支撑盘，虚线为允许瓶中心　·　新盘中心 (−25, −35) cm，支撑盘 16 cm，瓶心半径 13.37 cm",
        "原生开门 90° 时，离新交接区最近的柜身余 4.30 cm、门余 25.85 cm。若同时扫门，最不利中间角的平面包络重叠 4.38 cm。")
    overview(ov,g,"transfer");setup(ax,(-57,53,-58,51));table(ax,g)
    region(ax,g["sweep_new_low"],COPPER,SWEEP)
    region(ax,g["sweep_legacy_low"],COPPER,"none",ls="--",lw=1.2,zorder=2)
    handoff(ax,g,both=True,points=True)
    cabinet(ax,g,angles=(90,));bottle_on_shelf(ax,g)
    from shapely.geometry import Point, Polygon as Shape
    from shapely.ops import unary_union
    sweep=unary_union([Shape(p["out"],p["holes"]) for p in g["sweep_new_low"]])
    overlap=sweep.intersection(Point(HANDOFF).buffer(16-radius+g["bottle_radius_cm"],resolution=128))
    if not overlap.is_empty:
        patch(ax,overlap.exterior.coords,"#854b35","none",hatch="////",zorder=6,lw=1)
        where=overlap.representative_point()
        call(ax,[where.x,where.y],[14,-20],"扫门与瓶包络相交")
    label(ax,(15,14),"Cabinet",12,rotation=15)
    label(ax,(-33,2),"Door · 扫掠",9.2)
    label(ax,(-18,-12),"旧 Bottle",9.2)
    label(ax,(-25,-38.4),"新 Bottle",10)
    call(ax,(-42.45,-35),(-46,-54),"桌边",8.6)
    call(ax,world(SHELF),[24,38],"层板出瓶")
    call(ax,ring(HANDOFF,16-radius)[6],(-16,-51.5),"西南精确边界",8.2)
    panel(ax,"柜门全程扫掠与新、旧瓶区")
    save(4,fig)

    fig,(ov,ax)=canvas("桌面  /  倾倒时的碗位","PourBeads　·　开口瓶沿用原生桌面采样，16 颗液滴随瓶初始化　·　碗中心 (−20, −50) cm",
        "九个碗位初态 9/9 通过，标 × 的东、东北、西三点指尖 IK 超过 15 mm。17 个请求中，真实初态最小瓶碗包络间隙为 6.94 cm（seed 774）。")
    overview(ov,g,"bowl");setup(ax,(-53,12,-67,2));table(ax,g)
    disk(ax,OLD,15.402,TEAL,TEAL_FILL,zorder=1.5)
    disk(ax,OLD,12.374,TEAL,ls="--",zorder=3)
    nb=np.asarray(g["nearest_bowl"]);nf=np.asarray(g["nearest_bottle"])
    patch(ax,np.asarray(g["bowl_collision"])+nb,"#715639","#d5ba92",zorder=2.2)
    patch(ax,np.asarray(g["bottle_collision"])+nf,TEAL,"#8ba589",zorder=3.8)
    disk(ax,BOWL,3,BLUE,BLUE_FILL,zorder=4);patch(ax,square(BOWL,1),GREY,GREY_FILL,zorder=5)
    samples(ax,ring(BOWL,3),[BOWL])
    for i in (1,2,5):
        ax.scatter(*ring(BOWL,3)[i],marker="x",color=INK,s=10,zorder=10)
    ax.annotate("送瓶口到碗沿", xy=(-12,-41),xytext=(-9,-25), ha="center",fontsize=8.4,
                arrowprops=dict(arrowstyle="->",lw=1,color=INK),zorder=8)
    label(ax,(-22,-17),"Bottle · 开口瓶",10)
    label(ax,(-21,-22),"虚线内采瓶心",8.7)
    label(ax,(-20,-43.7),"Bowl · 碗",9.8)
    # The closest allowed centres lie on this common radius of their two regions.
    d=(nf-nb)/np.linalg.norm(nf-nb)
    near_bowl=nb+d*np.max(np.linalg.norm(g["bowl_collision"],axis=1))
    near_bottle=nf-d*g["bottle_radius_cm"]
    ax.annotate("",near_bottle,near_bowl,arrowprops=dict(arrowstyle="|-|",color=INK,lw=1.15),zorder=8)
    call(ax,(near_bowl+near_bottle)/2,(-3,-35.5),"最近可选 2.66 cm",9)
    call(ax,BOWL+[2.1,-2.1],(-7,-60),"碗中心盘 r = 3 cm")
    call(ax,(-42.45,-40),(-46,-58),"桌边",9)
    panel(ax,"碗的真实占地与原生瓶位")
    save(5,fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("evidence",type=Path,help="Directory containing plan_geometry.json")
    for path in ["C:/Windows/Fonts/msyh.ttc","C:/Windows/Fonts/msyhbd.ttc"]:
        if Path(path).is_file():
            font_manager.fontManager.addfont(path)
    available={f.name for f in font_manager.fontManager.ttflist}
    family=next((name for name in ("Microsoft YaHei","Noto Sans CJK SC") if name in available),"DejaVu Sans")
    plt.rcParams.update({"font.family":[family,"DejaVu Sans"],
                         "axes.unicode_minus":False,"axes.labelcolor":INK,"text.color":INK})
    render(parser.parse_args().evidence)
