"""Draw six annotated static plans from GEOMETRY.json. No simulator imports."""
import argparse
import json
from pathlib import Path

import numpy as np
from matplotlib import font_manager
from matplotlib import pyplot as plt
from matplotlib.patches import Patch
from shapely.affinity import translate
from shapely.geometry import Polygon
from shapely.ops import unary_union

from plot_cabinet_positions import (
    BLUE, BLUE_FILL, BROWN, COPPER, EDGE, GREY, GREY_FILL, INK, PAPER,
    SWEEP, TEAL, TEAL_FILL, WOOD, call, canvas, disk, label,
    panel, patch, region, ring, rotation, samples, setup, square, table,
)

FILES = ("01_drawer_xy.png", "02_drawer_yaw.png", "03_charger_in_drawer.png",
         "04_charger_table_handoff.png", "05_socket_xy.png", "06_socket_yaw.png")
PULL = np.array([-22, 0])
SOCKET_FILL = "#d1c6ae"
PRONG = "#e3be75"
STEEL = "#48443e"


def moved(rings, offset, yaw=0):
    def transform(points):
        return np.asarray(points) @ rotation(yaw).T + offset
    return [dict(out=transform(p["out"]), holes=[transform(h) for h in p["holes"]]) for p in rings]


def draw(ax, shape, offset, edge, fill="none", yaw=0, **kwargs):
    region(ax, moved(shape,offset,yaw), edge, fill, **kwargs)


def arrow(ax, start, end, color=INK, **kwargs):
    ax.annotate("", xy=end, xytext=start, arrowprops={"arrowstyle":"->","color":color,
                "lw":kwargs.get("lw",1.4),"linestyle":kwargs.get("ls","-")}, zorder=11)


def dimension(ax, pair, note, at):
    a,b=np.array(pair)
    ax.plot(*np.array([a,b]).T,color=INK,lw=1.35,zorder=11)
    ax.scatter(*np.array([a,b]).T,c=INK,s=10,zorder=11)
    call(ax,(a+b)/2,at,note,9)


def charger(ax,g,center,zorder=6):
    for shape in g["charger_shapes"][1:]:
        draw(ax,shape,center,STEEL,PRONG,zorder=zorder)
    draw(ax,g["charger_shapes"][0],center,TEAL,"#8cae9e",zorder=zorder)


def socket(ax,g,center,yaw=90,edge=STEEL,fill=SOCKET_FILL,show_pins=False,ls="-",zorder=5):
    r=rotation(yaw)
    patch(ax,square(np.zeros(2),g["socket_half"]) @ r.T + center,edge,fill,zorder=zorder,ls=ls)
    for x in (-g["slot_offset"],g["slot_offset"]):
        hx,hy=g["slot_half_xy"]
        outline=np.array([[x-hx,-hy],[x+hx,-hy],[x+hx,hy],[x-hx,hy]])
        hole_color=STEEL if fill!="none" else "none"
        patch(ax,outline@r.T+center,edge,hole_color,zorder=zorder+1,ls=ls,lw=1)
        if show_pins:
            px,py=g["blade_half_xy"]
            pins=np.array([[x-px,-py],[x+px,-py],[x+px,py],[x-px,py]])
            patch(ax,pins@r.T+center,"#61491c",PRONG,zorder=zorder+2,lw=.8)


def drawer(ax,g,center,angle=0,show_open=True):
    draw(ax,g["cabinet"],center,BROWN,WOOD,angle,zorder=3)
    draw(ax,g["handle"],center,STEEL,STEEL,angle,zorder=6)
    if show_open:
        opened=center+PULL@rotation(angle).T
        draw(ax,g["middle"],opened,BROWN,SWEEP,angle,zorder=2)
        draw(ax,g["handle"],opened,STEEL,STEEL,angle,zorder=6)


def handoff(ax,g,h,annotate=False):
    disk(ax,h,g["handoff_r"],TEAL,TEAL_FILL,zorder=2,alpha=.73)
    disk(ax,h,g["handoff_insert_r"],TEAL,ls="--",zorder=4)
    if annotate:
        label(ax,h+[0,-2],"Charger  交接区",10)


def overview(ax,g,task,mark=None):
    c,h,s=[np.asarray(g[k]) for k in ("cabinet_xy","handoff_xy","socket_xy")]
    setup(ax,(-143,89,-132,132))
    table(ax,g)
    region(ax,g["robot_base"],EDGE,"#aaa493",zorder=1)
    label(ax,(-87,4),"机器人底座",9)
    label(ax,(16,102),"Table  桌面",11)
    call(ax,(g["table_xy_cm"][0][0],-87),(-93,-101),"物理桌边 X = −42.45",8)
    if task=="socket":
        disk(ax,h,g["handoff_insert_r"],TEAL,TEAL_FILL,ls="--",zorder=2)
    else:
        handoff(ax,g,h)
    label(ax,h,"Charger",8.6)
    if task in ("drawer","both"):
        drawer(ax,g,c)
        label(ax,c,"Drawer  柜体",9)
        if mark is not None:
            point=c+PULL+g["drawer_charger_xy"]
            charger(ax,g,point)
            call(ax,point,(-68,66),"中层抽屉",8.7)
    if task in ("socket","both"):
        socket(ax,g,s)
        label(ax,s+[20,0],"Socket  插座",8.4)
    if task=="both":
        label(ax,(-13,54),"PickCharger",8.4)
        label(ax,(-8,-16),"InsertPlug",8.4)
    panel(ax,"整桌定位" if task!="both" else "整桌叠图 · 两任务参照")


def grid(offsets_x,offsets_y):
    return np.array([(x,y) for x in offsets_x for y in offsets_y])


def render(g,out):
    c,h,s=[np.asarray(g[k]) for k in ("cabinet_xy","handoff_xy","socket_xy")]
    handle=np.array(g["handle_xy"])
    inside=np.array(g["drawer_charger_xy"])
    front_limit=g["table_xy_cm"][0][0]
    def create(title,sub,foot):
        return canvas(title,sub+"     ·     静态推算／待实测",foot)
    def save(fig,n):
        fig.savefig(out/FILES[n-1],dpi=170,facecolor=PAPER)
        plt.close(fig)

    fig,(ov,ax)=create("抽屉柜  /  XY 平移","OpenDrawer、PickCharger   ·   世界 XY   ·   朝向 0°",
        "柜根标称 (18, 18) cm。原生各轴 ±1 cm，候选各轴 ±5 cm。橙色为标称柜根下中屉 0–22 cm 的滑动投影。")
    overview(ov,g,"drawer");setup(ax,(-57,59,-79,58));table(ax,g)
    pieces=[Polygon(p["out"],p["holes"]) for p in g["middle"]]
    swept=unary_union([unary_union([p,translate(p,xoff=-22)]).convex_hull for p in pieces])
    patch(ax,translate(swept,xoff=c[0],yoff=c[1]).exterior.coords,COPPER,SWEEP,zorder=1.4,alpha=.7)
    drawer(ax,g,c)
    handoff(ax,g,h,annotate=True)
    patch(ax,square(c,5),BLUE,BLUE_FILL,zorder=5)
    patch(ax,square(c,1),GREY,GREY_FILL,zorder=6)
    samples(ax,c+grid((-5,0,5),(-5,0,5)),[c])
    label(ax,c+[13,17],"Drawer  柜体",10)
    call(ax,c+handle,(2,-23),"OpenDrawer 把手 · 0 cm",8.5)
    call(ax,c+handle+PULL,(-29,51),"PickCharger 把手 · 22 cm",8.5)
    arrow(ax,(-13,41),(-35,41))
    label(ax,(-23,46),"拉出方向",8.6)
    label(ax,(-24,-4),"中屉扫掠",8.6)
    panel(ax,"关闭初态、开屉初态与操作侧")
    save(fig,1)

    fig,(ov,ax)=create("抽屉柜  /  柜体朝向","OpenDrawer、PickCharger   ·   世界 XY   ·   柜根固定 (18, 18) cm",
        "三条线均追踪同一个中层把手点。入口侧在左，手沿滑轨接近后向外拉。白点为关闭位置，箭头止于 22 cm 开度。")
    overview(ov,g,"drawer");setup(ax,(-55,57,-37,63));table(ax,g)
    drawer(ax,g,c)
    for yaw,ls in [(-5,"-"),(0,"--"),(5,":")]:
        col=GREY if yaw==0 else BLUE
        draw(ax,g["cabinet"],c,col,yaw=yaw,ls=ls,zorder=4,lw=1.4)
        start=c+handle@rotation(yaw).T
        end=c+(handle+PULL)@rotation(yaw).T
        arrow(ax,start,end,col,ls=ls,lw=2.0)
        samples(ax,[start],[c])
        call(ax,end,end+[-11,{-5:15,0:0,5:-15}[yaw]],f"{yaw:+d}°" if yaw else "0°",9)
    label(ax,c+[12,14],"Drawer",11)
    call(ax,c+handle,(1,44),"同一个把手点",9)
    arrow(ax,(-43,-16),(-20,-16))
    label(ax,(-31,-24),"手从柜前接近",9)
    panel(ax,"同一把手和三条滑轨方向")
    save(fig,2)

    fig,(ov,ax)=create("中层抽屉  /  充电器中心","PickCharger   ·   开屉 22 cm   ·   右图为随屉移动的局部 XY，+X 向深处",
        "蓝域为中心偏移 X ±1、Y ±2 cm。最深点的内侧插脚几乎到达柜顶前沿的俯视投影；抬升路线和手指间隙待实测。")
    overview(ov,g,"drawer",mark=True);setup(ax,(-38,29,-30,30),"抽屉局部 X  (cm)")
    # Express the same physical table in the moving drawer's q=0 reference coordinates.
    lo,hi=np.asarray(g["table_xy_cm"])-(c+PULL)
    table(ax,{"table_xy_cm":[lo,hi]})
    draw(ax,g["floor"],[0,0],BROWN,"#d9bf9e",zorder=2)
    for name,parts in g["middle_parts"].items():
        if name.startswith(("drawer_front/","drawer_back/","drawer_side/","handle/")):
            draw(ax,parts,[0,0],BROWN,WOOD if not name.startswith("handle") else STEEL,zorder=3)
    frame_front=g["roof_front_drawer_x_cm"]
    ax.axvline(frame_front,color=BROWN,ls=":",lw=1.2,zorder=4)
    deep=np.asarray(g["deep_positive_y"]["charger_xy"])
    charger(ax,g,deep)
    rect=inside+np.array([[-1,-2],[1,-2],[1,2],[-1,2]])
    patch(ax,rect,BLUE,BLUE_FILL,zorder=8)
    patch(ax,square(inside,1),GREY,GREY_FILL,zorder=8.5)
    samples(ax,inside+grid((-1,0,1),(-2,0,2)),[inside])
    call(ax,deep,(-5,16),"深侧抓取点 A",9)
    call(ax,deep+[4.75,2.2],(5,8),"双插脚朝屉内",8.6)
    call(ax,deep+[-1,0],(-22,12),"侧躺壳体",8.6)
    label(ax,(3,-16),"内底板",10)
    label(ax,(17,25.7),"侧壁",9)
    label(ax,(25.5,13),"后壁",8.5,rotation=90)
    label(ax,(-28.5,9),"前沿",8.8,rotation=90)
    call(ax,(frame_front,-4),(5,-23),"上方柜顶前沿",8)
    arrow(ax,(-31,-10),(-15,-5))
    label(ax,(-26,-15),"手指接近",8.8)
    arrow(ax,(-11,-10),(-31,-10))
    label(ax,(-26,-20),"抬过前沿后取出",8.8)
    panel(ax,"真实屉底、四周边界与最深姿态")
    save(fig,3)

    fig,(ov,ax)=create("桌面  /  充电器交接区","PickCharger 放置判定、InsertPlug 初始化   ·   世界 XY   ·   两圆沿用",
        "西缘支撑：10.5 cm 采样盘余 0.15 cm，14 cm 判定圆极限悬出 3.35 cm。开屉与侧躺 Charger 高度分离，图示为投影净距。")
    overview(ov,g,"both");setup(ax,(-52,19,-82,30));table(ax,g)
    drawer(ax,g,c)
    socket(ax,g,s)
    label(ax,(3,-31),"Socket · InsertPlug",8.6)
    label(ax,(-13,1),"开屉 · PickCharger",8.4)
    handoff(ax,g,h)
    samples(ax,np.vstack([ring(h,g["handoff_r"]),ring(h,g["handoff_insert_r"])]),[h])
    nearest=g["nearest_socket_nominal"]
    upper=g["handoff_drawer_limit"]
    for shape in g["charger_shapes"]:
        draw(ax,shape,upper["charger_xy"],TEAL,ls=":",zorder=5)
    dimension(ax,upper["witness"],"距开屉投影 31.11 cm",(-11,-23))
    charger(ax,g,nearest["charger_xy"])
    dimension(ax,nearest["witness"],"距标称插座 3.24 cm",(-1,-55))
    charger(ax,g,h+[-g["handoff_insert_r"],0])
    west=h+[-g["handoff_r"],0]
    for shape in g["charger_shapes"]:
        draw(ax,shape,west,TEAL,yaw=0,ls="--",zorder=6)
    geom=Polygon(moved(g["charger_shapes"][0],west)[0]["out"])
    from shapely.geometry import box
    overhang=geom.intersection(box(-100,-100,front_limit,100))
    patch(ax,overhang.exterior.coords,"#885239","none",hatch="////",zorder=7)
    call(ax,(front_limit,-63),(-45,-78),"斜线 · 壳体悬出桌边",8)
    call(ax,h+[11,-8.65],(-1,-77),"实线 14 cm · 放置判定",8.6)
    call(ax,h+[9,-5.4],(3,-68),"虚线 10.5 cm · 初始化",8.6)
    label(ax,h+[1,2],"Charger",9)
    panel(ax,"分任务参照与完整侧躺外廓")
    save(fig,4)

    fig,(ov,ax)=create("插座  /  XY 平移","InsertPlug   ·   世界 XY   ·   朝向固定 90°   ·   中心 (−12.5, −38) cm",
        "原生中心域为各轴 ±1 cm，候选半径为 2 cm。两侧同时取最靠近的允许位置，真实外廓静态间隙 1.24 cm。")
    overview(ov,g,"socket");setup(ax,(-46,7,-76,-24));table(ax,g)
    disk(ax,h,g["handoff_insert_r"],TEAL,TEAL_FILL,ls="--",zorder=2)
    label(ax,h,"Charger · 原生中心域",8.8)
    nearest=g["nearest_socket_new"]
    sc=np.asarray(nearest["socket_xy"])
    socket(ax,g,s,edge=GREY,fill="none",ls="--",zorder=4)
    socket(ax,g,sc,zorder=5)
    disk(ax,s,2,BLUE,BLUE_FILL,zorder=7)
    patch(ax,square(s,1),GREY,GREY_FILL,zorder=8)
    samples(ax,ring(s,2),[s])
    ax.scatter(*sc,facecolors="none",edgecolors=INK,s=75,zorder=11,lw=1.3)
    charger(ax,g,nearest["charger_xy"])
    dimension(ax,nearest["witness"],"外廓间隙 1.24 cm",(-3,-50))
    # Keep both real holes legible when the centre samples cross them.
    for y in (-g["slot_offset"],g["slot_offset"]):
        hole_center=sc+[0,y]
        hx,hy=g["slot_half_xy"]
        ax.plot([hole_center[0]-hy,hole_center[0]+hy,hole_center[0]+hy,hole_center[0]-hy,hole_center[0]-hy],
                [hole_center[1]-hx,hole_center[1]-hx,hole_center[1]+hx,hole_center[1]+hx,hole_center[1]-hx],
                color=STEEL,lw=1.05,zorder=8.7)
    call(ax,sc+[1.55,2.2],(-.4,-32),"Socket · 双孔",8.2)
    call(ax,nearest["charger_xy"],(-34,-51),"最近 Charger",8.2)
    panel(ax,"最靠近的合法位置")
    save(fig,5)

    fig,(ov,ax)=create("插座  /  壳体朝向","InsertPlug   ·   世界 XY   ·   插座中心固定 (−12.5, −38) cm",
        "两个孔刚性随壳体旋转，孔距 4.4 cm。金色为 90° 双插脚预对准投影，孔深 2.8 cm。85°、95° 时双脚须随插座一同转向。")
    overview(ov,g,"socket");setup(ax,(-25,.4,-50,-25.5));table(ax,g)
    socket(ax,g,s,edge=GREY,fill=SOCKET_FILL,show_pins=True,zorder=3)
    for yaw,ls in [(85,"-"),(95,":")]:
        socket(ax,g,s,yaw,edge=BLUE,fill="none",ls=ls,zorder=4)
    # Use the same identified corner on the shell in all three poses.
    corner=np.array([g["socket_half"],-g["socket_half"]])
    for yaw,at in [(85,(-3,-26.9)),(90,(-.8,-29.5)),(95,(-.7,-33))]:
        pos=s+corner@rotation(yaw).T
        samples(ax,[pos],[s])
        call(ax,pos,at,f"{yaw}°",8.7)
    hw,hh=g["upright_half_xy"]
    silhouette=np.array([[-hw,-hh],[hw,-hh],[hw,hh],[-hw,hh]])
    patch(ax,silhouette@rotation(90).T+s,TEAL,ls="--",zorder=5,lw=1.15)
    call(ax,s+[-2,2.2],(-20.5,-34),"孔口",9)
    call(ax,s+[0,-2.2],(-3,-43),"双脚垂直入孔",8.7)
    label(ax,s+[4,0],"Socket",10)
    label(ax,s+[0,-9.2],"细虚线 · 充电器预对准壳体",8.7)
    panel(ax,"三角度叠图与双脚预对准")
    save(fig,6)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory",type=Path)
    args=parser.parse_args()
    for name in ("msyh.ttc","msyhbd.ttc"):
        path=Path("C:/Windows/Fonts")/name
        if path.is_file():
            font_manager.fontManager.addfont(path)
    fonts={font.name for font in font_manager.fontManager.ttflist}
    family=next((name for name in ("Microsoft YaHei","Noto Sans CJK SC") if name in fonts),"DejaVu Sans")
    plt.rcParams.update({"font.family":[family,"DejaVu Sans"],"axes.unicode_minus":False,
                         "axes.labelcolor":INK,"text.color":INK})
    render(json.loads((args.directory/"GEOMETRY.json").read_bytes()),args.directory)
