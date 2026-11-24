"""Draw five independent Nut & Bolt boundary figures from measured scenes."""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation

from plot_cabinet_positions import (
    BLUE, BLUE_FILL, GREY, GREY_FILL, INK, PAPER, RED, TEAL, TEAL_FILL,
    call, canvas, disk, font_manager, label, panel, patch, plt, setup, square, table,
)


SHAFT, HEAD, NUT = "#777d83", "#62696c", "#ba9173"
NUT_EDGE = "#664832"
PNG = (
    "01_fallen_bolt_xy.png", "02_fallen_bolt_yaw.png", "03_upright_bolt_handoff.png",
    "04_free_nut_xy.png", "05_threaded_nut_yaw.png",
)


def load(path, task):
    record = json.loads(path.read_text(encoding="utf-8"))
    return record["tasks"][task], record["settings"]["backend"]


def use_measured_robot_projection(item, cpu):
    # CUDA collision components can expose stale host link poses; the chassis
    # footprint is taken from the matching native CPU layout.
    target = item["geometry"]
    source = cpu["geometry"]
    for key in ("table_lo", "table_hi", "bolt_local_vertices_m"):
        if not np.allclose(target[key], source[key], atol=1e-6, rtol=0):
            raise ValueError(f"CPU projection scene does not match measurement: {key}")
    target["base_parts_xy_m"] = source["base_parts_xy_m"]


def pieces_xy(points, p, r):
    world = (r.apply(points) + p)[:, :2] * 100
    return world[ConvexHull(world).vertices]


def draw_bolt(ax, g, center, yaw=0, fallen=False, outline=None, style="-", fill=True):
    rotation = Rotation.from_euler("z", yaw, degrees=True)
    if fallen:
        rotation *= Rotation.from_euler("y", 90, degrees=True)
        rotation *= Rotation.from_euler("z", g["candidate"]["bolt_spawn_axial_spin_deg"], degrees=True)
    loc = np.r_[np.asarray(center) / 100, 0.]
    head = pieces_xy(g["bolt_local_vertices_m"], loc, rotation)
    angles = np.arange(96) * 2 * np.pi / 96
    axes = np.column_stack([np.cos(angles), np.sin(angles)])
    cylinders = g["bolt_cylinders"] if fallen else g["bolt_cylinders"][:1]
    for cylinder in cylinders:
        pose = np.asarray(cylinder["local_pose"])
        shape_rotation = Rotation.from_quat(np.roll(pose[3:], -1))
        circle = axes * cylinder["radius_m"]
        shape = np.concatenate([
            np.column_stack([np.full(len(circle), sign * cylinder["half_length_m"]), circle])
            for sign in (-1, 1)
        ])
        points = pieces_xy(shape_rotation.apply(shape) + pose[:3], loc, rotation)
        patch(ax, points, outline or SHAFT, SHAFT if fill else "none",
              ls=style, lw=.3 if fill else .65, alpha=.80 if fill else .90, zorder=4)
    patch(ax, head, outline or HEAD, "#a5a5a0" if fill else "none", ls=style, lw=1.1, zorder=5)


def draw_nut(ax, g, center, yaw=0, threaded=False, outline=NUT_EDGE, fill=True, style="-"):
    key = "threaded_nut_local_parts_m" if threaded else "nut_local_parts_m"
    rotation = Rotation.from_euler("z", yaw, degrees=True)
    loc = np.r_[np.asarray(center) / 100, 0.]
    for part in g[key]:
        patch(ax, pieces_xy(part, loc, rotation), outline, NUT if fill else "none",
              lw=1.1 if fill else 1., ls=style, alpha=.95, zorder=6)


def cm(g, key):
    return 100 * np.array(g[key])


def scene_table(ax, g):
    table(ax, {"table_xy_cm": [cm(g, "table_lo")[:2], cm(g, "table_hi")[:2]]})


def overview(ax, g, task):
    lo, hi = cm(g, "table_lo"), cm(g, "table_hi")
    setup(ax, (-140, hi[0] + 8, lo[1] - 8, hi[1] + 8))
    panel(ax, "整桌与操作位置")
    scene_table(ax, g)
    for points in g["base_parts_xy_m"]:
        patch(ax, np.asarray(points) * 100, "#716c60", "#a8a292", lw=.55, alpha=.85)
    label(ax, (-87, 0), "机器人底座\nCPU 实测轮廓", size=10)
    label(ax, (28, 98), "物理桌面")
    call(ax, (lo[0], -78), (-93, -92), f"实际桌边 X = {lo[0]:.2f} cm", 9)
    start, upright = cm(g, "bolt_spawn_xy_m"), cm(g, "handoff_xy_m")
    disk(ax, upright, g["handoff_radius_m"] * 100, TEAL, TEAL_FILL, alpha=.8)
    if task == "PickBolt":
        draw_bolt(ax, g, start, fallen=True)
        call(ax, start, (20, -34), "躺放螺栓", 9)
        call(ax, upright, (20, 19), "直立交接盘", 9)
    else:
        draw_bolt(ax, g, upright)
        if task == "SeatNut":
            nut = cm(g, "table_nut_xy_m")
            draw_nut(ax, g, nut)
            call(ax, nut, (20, -38), "自由螺母", 9)
        else:
            draw_nut(ax, g, upright, threaded=True)
        call(ax, upright, (20, 18), "锁定螺栓轴", 9)


def center_dot(ax, point):
    ax.scatter(*point, c=RED, edgecolors="white", zorder=12, s=42)


def mark_xy(ax, rows, prefix, field, center, short="", scale=1.23):
    for row in rows:
        name = row["label"]
        if not name.startswith(prefix) or not name[len(prefix):].isdigit():
            continue
        request = row["options"]["position_layout"][str(row["env_idx"])]
        if field not in request:
            continue
        point = np.asarray(request[field]) * 100
        if np.allclose(point, center):
            continue
        ax.scatter(*point, c="white", edgecolors=INK, zorder=12, s=31)
        label(ax, center + scale * (point - center), short + name[len(prefix):], size=7.3)
    center_dot(ax, center)


def legal(item):
    return [row for row in item["rows"] if row["kind"] == "initialization"]


def edge_measure(row):
    return row["readback"]["target_table_edge_clearance_m"]


def make_figure(title, subtitle, footer, local_title, g, task, limits, backend):
    backend_label = "原生 CUDA reset 与静置" if backend == "physx_cuda" else "原生 CPU reset 与静置"
    fig, (left, ax) = canvas(title, subtitle + "  ·  " + backend_label, footer)
    overview(left, g, task)
    setup(ax, limits)
    scene_table(ax, g)
    panel(ax, local_title)
    return fig, ax


def save(fig, path):
    fig.savefig(path, dpi=165, facecolor=PAPER)
    plt.close(fig)


def spawn_xy(item, backend, outfile):
    g = item["geometry"]
    c = cm(g, "bolt_spawn_xy_m")
    old = g["bolt_spawn_radius_m"] * 100
    radius = g["candidate"]["bolt_spawn_radius_m"] * 100
    rows = [row for row in legal(item) if row["label"].startswith("P-XY")]
    west = min(rows, key=edge_measure)
    fig, ax = make_figure(
        "躺放螺栓 / XY 平移", "PickBolt  ·  场景 XY  ·  轴线水平朝 +X，六角头平面朝下",
        f"旧域半径 {old:g} cm，候选半径 {radius:g} cm。{west['label']} 的完整碰撞投影距最近桌边 "
        f"{1000 * edge_measure(west):.2f} mm（reset 实测位姿）。",
        "中心域、真实螺栓外形与西桌边", g, "PickBolt", (-46, -11, -39, -8), backend,
    )
    disk(ax, c, radius, BLUE, BLUE_FILL, alpha=.70, zorder=2)
    disk(ax, c, old, GREY, GREY_FILL, alpha=.73, zorder=3)
    draw_bolt(ax, g, c, fallen=True)
    wx, wy = np.asarray(west["readback"]["bolt_pose"])[:2] * 100
    draw_bolt(ax, g, (wx, wy), fallen=True, outline=BLUE, fill=False)
    near_x = min(np.array(west["readback"]["target_outline_xy_m"])[:, 0]) * 100
    edge_x = cm(g, "table_lo")[0]
    ax.annotate("", (near_x, wy - 3.8), (edge_x, wy - 3.8),
                arrowprops={"arrowstyle": "<->", "color": INK}, zorder=11)
    label(ax, ((near_x + edge_x) / 2, wy - 5.3), "最小桌边余量", size=8)
    mark_xy(ax, rows, "P-XY", "bolt_spawn_xy_m", c, short="P-XY")
    call(ax, c + [3.5, .4], (-15, -13), "从杆身两侧接近", 8)
    label(ax, c + [.3, -12], "P-XY0 · 红点为根中心", size=8)
    save(fig, outfile)


def spawn_yaw(item, backend, outfile):
    g = item["geometry"]
    c = cm(g, "bolt_spawn_xy_m")
    angles = g["candidate"]["bolt_spawn_yaw_deg"]
    tip_z = max(cyl["local_pose"][2] + cyl["half_length_m"] for cyl in g["bolt_cylinders"]) * 100
    chosen = [row for row in legal(item) if row["label"] in {"P-XY0", "P-Y-90", "P-Y+90"}]
    worst = min(chosen, key=edge_measure)
    fig, ax = make_figure(
        "躺放螺栓 / 朝向", f"PickBolt  ·  根固定 ({c[0]:g}, {c[1]:g}) cm  ·  轴线水平",
        f"灰虚线表示固定水平姿态下的原生全周方向，白点追踪同一物理尖端。"
        f"{worst['label']} 桌边余量 {1000 * edge_measure(worst):.2f} mm（reset 实测位姿）。",
        "固定根中心、同一尖端的三个方向", g, "PickBolt", (-37, -11, -34, -10), backend,
    )
    disk(ax, c, tip_z, GREY, GREY_FILL, ls="--", alpha=.55, zorder=2)
    draw_bolt(ax, g, c, fallen=True)
    for yaw, style in zip(angles, ["--", "-", ":"]):
        if yaw:
            draw_bolt(ax, g, c, yaw=yaw, fallen=True, outline=BLUE, style=style, fill=False)
        angle = np.deg2rad(yaw)
        direction = np.array([np.cos(angle), np.sin(angle)])
        tip = c + tip_z * direction
        ax.plot([c[0], tip[0]], [c[1], tip[1]], color=BLUE, lw=1.1, ls=style, zorder=9)
        ax.scatter(*tip, c="white", edgecolors=INK, zorder=12, s=35)
        name = f"P-Y{yaw:+d}" if yaw else "P-XY0"
        call(ax, tip, tip + direction * 3.6, f"{yaw}°  {name}", 8.6)
    center_dot(ax, c)
    call(ax, c + [-3.7, .8], (-33.5, -15), "六角头", 9)
    save(fig, outfile)


def handoff(seat, turn, backend, outfile):
    g = seat["geometry"]
    c = cm(g, "handoff_xy_m")
    radius = g["candidate"]["upright_bolt_radius_m"] * 100
    worst = min(legal(seat) + legal(turn), key=lambda row: row["readback"]["bolt_head_disc_clearance_m"])
    fig, ax = make_figure(
        "直立螺栓 / 桌面交接", "PickBolt 放置 → SeatNut 装入 → TurnNut 旋转  ·  候选直立朝向 0°",
        f"绿线是原生六角头成功盘，蓝区是螺栓根请求域。{worst['label']} 的完整六角头离盘沿"
        f"至少余 {1000 * worst['readback']['bolt_head_disc_clearance_m']:.2f} mm（reset 实测位姿）。",
        "成功盘、六角头与两个任务共用的轴位", g, "SeatNut", (-43, 10, -29, 21), backend,
    )
    outer = g["handoff_radius_m"] * 100
    head_radius = g["bolt_head_circumradius_m"] * 100
    disk(ax, c, outer, TEAL, TEAL_FILL, alpha=.85, zorder=1)
    head_angles = np.deg2rad(np.arange(0, 360, 60))
    angles = np.linspace(0, 2 * np.pi, 361)
    direction = np.column_stack([np.cos(angles), np.sin(angles)])
    projection = np.cos(angles[:, None] - head_angles).max(axis=1)
    old_outer = -head_radius * np.sqrt(3) / 2 + np.sqrt(outer**2 - head_radius**2 / 4)
    patch(ax, c + old_outer * direction, GREY, GREY_FILL, ls="--", alpha=.75, zorder=2)
    disk(ax, c, radius, BLUE, BLUE_FILL, alpha=.70, zorder=3)
    at_yaw0 = -head_radius * projection + np.sqrt(outer**2 - head_radius**2 * (1 - projection**2))
    patch(ax, c + direction * at_yaw0[:, None], GREY, ls=":", lw=1.1, zorder=5)
    draw_bolt(ax, g, c)
    boundary = c + [radius, 0.]
    draw_bolt(ax, g, boundary, outline=BLUE, fill=False)
    mark_xy(ax, legal(seat), "S-B", "upright_bolt_xy_m", c, short="B", scale=1.16)
    start = cm(g, "table_nut_xy_m")
    draw_nut(ax, g, start)
    call(ax, start, (-30, -22), "自由螺母名义起点", 8.5)
    call(ax, boundary + [head_radius, 0.], (.5, 9), "东端六角底面", 8.5)
    label(ax, (-12, -15.0), f"灰虚线为原生中心最外沿 {old_outer:.2f} cm\n灰点线为固定 0° 朝向时的边界", size=8.2)
    label(ax, (-21, 13.5), "B0—B8 同时对应 S- 与 T- 行", size=8.6)
    save(fig, outfile)


def nut_xy(item, backend, outfile):
    g = item["geometry"]
    c, bolt = cm(g, "table_nut_xy_m"), cm(g, "handoff_xy_m")
    old = g["table_nut_native_half_range_m"] * 100
    half = 100 * np.array(g["candidate"]["table_nut_half_range_m"])
    nearest = min(legal(item), key=lambda row: row["readback"]["nut_bolt_plan_clearance_lower_bound_m"])
    detail = nearest["readback"]
    fig, ax = make_figure(
        "自由螺母 / 桌面 XY", "SeatNut  ·  螺母平放，明确请求时朝向为 0°",
        f"原生两轴各 ±{old:g} cm，候选各 ±{half[0]:g} cm。{nearest['label']} 的自由螺母与螺栓/承托台"
        f"俯视净距下界 {1000 * detail['nut_bolt_plan_clearance_lower_bound_m']:.1f} mm（实测位姿）。",
        "自由螺母、同场螺栓与最近组合", g, "SeatNut", (-35, 5, -34, 8), backend,
    )
    patch(ax, c + square(np.zeros(2), 1) * half, BLUE, BLUE_FILL, alpha=.70, zorder=2)
    patch(ax, square(c, old), GREY, GREY_FILL, alpha=.74, zorder=3)
    draw_nut(ax, g, c)
    draw_bolt(ax, g, bolt)
    patch(ax, square(c, old), GREY, ls="--", lw=1.05, zorder=8)
    mark_xy(ax, legal(item), "S-N", "table_nut_xy_m", c, short="S-N", scale=1.39)
    a = np.asarray(detail["target_pose"])[:2] * 100
    b = np.asarray(detail["bolt_pose"])[:2] * 100
    draw_nut(ax, g, a, outline=BLUE, fill=False, style="--")
    draw_bolt(ax, g, b, outline=BLUE, fill=False, style="--")
    ax.plot([a[0], b[0]], [a[1], b[1]], ls="--", lw=1.05, color=BLUE, zorder=8)
    call(ax, b, (.0, -4.), f"{nearest['label']} 叠加后的轴位", 8.1)
    call(ax, c, (-25, -29), "S-B0 · 名义螺母起点", 8.1)
    call(ax, bolt, (-23., 3.), "锁定螺栓 · 名义轴位", 8.1)
    save(fig, outfile)


def turn_yaw(item, backend, outfile):
    g = item["geometry"]
    c = cm(g, "handoff_xy_m")
    angles = g["candidate"]["threaded_nut_relative_yaw_deg"]
    local = np.asarray(g["threaded_nut_local_parts_m"]).reshape(-1, 3)
    point = local[np.argmax(local[:, 0] + .30 * local[:, 1])]
    radius = np.linalg.norm(point[:2]) * 100
    chosen = [row for row in legal(item) if row["label"] in {"T-B0", "T-Y-20", "T-Y+20"}]
    worst = max(chosen, key=lambda row: max(row["ik"]["fingertip_max_errors_m"]))
    protrusion = (radius - g["platform_radius_m"] * 100) * 10
    fig, ax = make_figure(
        "已就位螺母 / 相对朝向",
        f"TurnNut  ·  轴固定 ({c[0]:g}, {c[1]:g}) cm  ·  支承平面 Z = {100 * g['platform_support_height_m']:g} cm",
        f"{worst['label']} 的两指路径最大误差 {1000 * max(worst['ik']['fingertip_max_errors_m']):.1f} mm。"
        f"同一外角超出承托台半径 {protrusion:.2f} mm。原生固定轴，实际静置位移见逐点表。",
        "同一外角、真实六块碰撞外形与固定轴", g, "TurnNut",
        (c[0] - 5.7, c[0] + 6.5, c[1] - 5.4, c[1] + 5.4), backend,
    )
    disk(ax, c, radius, GREY, GREY_FILL, ls="--", alpha=.67, zorder=2)
    disk(ax, c, g["platform_radius_m"] * 100, TEAL, TEAL_FILL, ls=":", alpha=.9, zorder=3)
    disk(ax, c, g["bolt_cylinders"][0]["radius_m"] * 100, SHAFT, "#a9aba7", zorder=4)
    draw_nut(ax, g, c, threaded=True)
    for yaw, style, at in zip(angles, ["--", "-", ":"], [(4.6, -3), (5.1, .7), (4.5, 3.5)]):
        if yaw:
            draw_nut(ax, g, c, yaw=yaw, threaded=True, outline=BLUE, fill=False, style=style)
        witness = c + Rotation.from_euler("z", yaw, degrees=True).apply(point)[:2] * 100
        ax.scatter(*witness, c="white", edgecolors=INK, zorder=12, s=35)
        name = f"T-Y{yaw:+d}" if yaw else "T-B0"
        call(ax, witness, c + at, f"{yaw}°  {name}", 8.1)
    center_dot(ax, c)
    call(ax, c + [-1.35, .5], c + [-4.6, 3.75], "螺栓杆", 8.6)
    call(ax, c + [-2.1, .95], c + [-4.4, -3.9], "无视觉承托台", 8.2)
    theta = np.deg2rad([143, 189])
    vector = 3.55 * np.column_stack([np.cos(theta), np.sin(theta)]) + c
    ax.annotate("", vector[1], vector[0], arrowprops={"arrowstyle": "->", "color": INK,
                "connectionstyle": "arc3,rad=.17"}, zorder=10)
    label(ax, c + [-4.15, 1.35], "逆时针", size=7.6)
    save(fig, outfile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pick", "seat", "turn", "robot-geometry-cpu", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    win_cjk = Path("C:/Windows/Fonts/msyh.ttc")
    if win_cjk.exists():
        font_manager.fontManager.addfont(win_cjk)
    names = {font.name for font in font_manager.fontManager.ttflist}
    choices = ("Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Zen Hei")
    chosen = next((name for name in choices if name in names), None)
    if chosen is None:
        raise RuntimeError("Install a CJK font to generate the Chinese boundary figures")
    plt.rcParams.update({"font.family": [chosen, "DejaVu Sans"], "axes.unicode_minus": False})
    pick, pb = load(args.pick, "PickBolt")
    seat, sb = load(args.seat, "SeatNut")
    turn, tb = load(args.turn, "TurnNut")
    if not pb == sb == tb:
        raise ValueError("Choose measurements from the same simulation backend")
    for name, item in (("PickBolt", pick), ("SeatNut", seat), ("TurnNut", turn)):
        cpu, backend = load(args.robot_geometry_cpu, name)
        if backend != "physx_cpu":
            raise ValueError("Robot projection requires native CPU measurements")
        use_measured_robot_projection(item, cpu)
    args.output.mkdir(parents=True, exist_ok=True)
    spawn_xy(pick, pb, args.output / PNG[0])
    spawn_yaw(pick, pb, args.output / PNG[1])
    handoff(seat, turn, sb, args.output / PNG[2])
    nut_xy(seat, sb, args.output / PNG[3])
    turn_yaw(turn, tb, args.output / PNG[4])


if __name__ == "__main__":
    main()
