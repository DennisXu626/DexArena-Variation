"""Draw the six Office Desk boundary diagrams from native reset readbacks."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, patheffects
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon, Rectangle
import numpy as np
from scipy.spatial import ConvexHull

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tasks.office_desk.position_layout import XY_BOUNDS_M, YAW_OFFSETS_DEG

STYLE = {
    "canvas": "#f3efe5", "outside": "#f8f5ee", "table": "#e5decb",
    "text": "#26302d", "edge": "#574e42", "grid": "#796b59",
    "old": "#737d84", "new": "#1768a2", "blue_fill": "#b0d5eb",
    "center": "#b83137", "body": "#b68d71", "attachment": "#658578",
    "robot": "#a39c87", "sweep": "#dfae89",
}
TASKS = {
    "OpenLaptop": ("laptop", "笔记本", "掀屏", "Laptop", "lid edge"),
    "TypeKeys": ("keyboard", "外置键盘", "依次按 P / A / I / R / Enter", "Keyboard", "P"),
    "ClickMouse": ("mouse", "鼠标", "左键点击", "Mouse", "left button"),
}


def configure_font():
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            font_manager.fontManager.addfont(candidate)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=candidate).get_name()
            break
    else:
        if not any(font.name in ("Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei",
                                 "PingFang SC") for font in font_manager.fontManager.ttflist):
            raise RuntimeError("Install Microsoft YaHei or Noto Sans CJK to draw Chinese labels")
        plt.rcParams["font.family"] = ["Microsoft YaHei", "Noto Sans CJK SC",
                                      "WenQuanYi Micro Hei", "PingFang SC"]
    plt.rcParams["axes.unicode_minus"] = False


def draw_polygon(ax, vertices, **kwargs):
    xy = np.asarray(vertices)[:, :2] * 100
    ax.add_patch(Polygon(xy, closed=True, **kwargs))


def setup_ax(ax, title, axes_widths=None):
    ax.set_title(title, loc="left", fontsize=15, fontweight="bold", pad=9)
    ax.set_xlabel("场景 X (cm)")
    ax.set_ylabel("场景 Y (cm)")
    ax.set_aspect("equal", adjustable="box")
    ax.set_facecolor(STYLE["outside"])
    ax.grid(alpha=.13, color=STYLE["grid"])
    for spine in ax.spines.values():
        spine.set_color("#a59882")
    if axes_widths is not None:
        ax.set_xlim(*axes_widths[0])
        ax.set_ylim(*axes_widths[1])


def outlined_label(ax, name, xy, size=9, **kwargs):
    return ax.text(*xy, name, fontsize=size, color=STYLE["text"], **kwargs,
                   path_effects=[patheffects.withStroke(linewidth=2.5, foreground=STYLE["canvas"])])


def workspace(ax, point, name):
    table = np.asarray(point["table_outline"]) * 100
    parts = [np.asarray(item) * 100 for item in point["robot_outlines"].values()]
    outline = np.concatenate([table, *parts])
    lower, upper = outline.min(0) - 10, outline.max(0) + 10
    setup_ax(ax, "整桌与机器人", axes_widths=list(zip(lower, upper)))
    draw_polygon(ax, point["table_outline"], facecolor=STYLE["table"],
                 edgecolor=STYLE["edge"], lw=1.8)
    top = (table.min(0)[0] + 8, table.max(0)[1] - 15)
    outlined_label(ax, "Table 桌面", top, size=11)
    for polygon in point["robot_outlines"].values():
        draw_polygon(ax, polygon, facecolor=STYLE["robot"], edgecolor=STYLE["edge"], lw=1.1)
    if parts:
        label = np.concatenate(parts).mean(0)
        outlined_label(ax, "机器人底座", label, ha="center", va="center")
    draw_polygon(ax, point["device_outline"], facecolor=STYLE["body"], edgecolor=STYLE["edge"], lw=1)
    center = np.asarray(point["pose"][:2]) * 100
    ax.scatter(*center, s=22, color=STYLE["center"], edgecolor="white", zorder=5)
    ax.annotate(name, center, xytext=(15, 12), textcoords="offset points",
                arrowprops={"arrowstyle": "->", "color": STYLE["text"]}, fontsize=10)
    edge = table.min(0)[0]
    ax.annotate(f"物理桌边 X = {edge:.2f} cm", (edge, -78), xytext=(-45, -22),
                textcoords="offset points", arrowprops={"arrowstyle": "->", "color": STYLE["text"]},
                fontsize=9)


def bounds(ax, lower, upper, *, color, fill, zorder):
    ax.add_patch(Rectangle(lower, *(upper - lower), facecolor=fill, edgecolor=color,
                           alpha=.85, lw=1.3, zorder=zorder))


def mark_centers(ax, selected, nominal, candidate_center):
    samples = (row for row in selected if row["id"].startswith("XY"))
    for number, row in enumerate(samples, start=1):
        p = np.asarray(row["pose"][:2]) * 100
        ax.scatter(*p, s=32, color="white", edgecolor=STYLE["text"], lw=1.2, zorder=8)
        direction = np.sign(np.round(p - candidate_center, 4))
        offset = [11 * direction[0], 8 * direction[1]]
        annotation = ax.annotate(str(number), p, xytext=offset, textcoords="offset points", zorder=9,
                                 ha={-1: "right", 0: "center", 1: "left"}[direction[0]],
                                 va={-1: "top", 0: "center", 1: "bottom"}[direction[1]], fontsize=8)
        annotation.set_path_effects([patheffects.withStroke(linewidth=2.5, foreground=STYLE["canvas"])])
    center = np.asarray(nominal["pose"][:2]) * 100
    ax.scatter(*center, s=27, color=STYLE["center"], edgecolor="white", zorder=10)
    if not np.allclose(center, candidate_center):
        ax.scatter(*candidate_center, s=24, color=STYLE["center"], marker="D",
                   edgecolor="white", linewidth=.6, zorder=11)
        ax.annotate("M 候选域中心", candidate_center, xytext=(28, -25),
                    textcoords="offset points", fontsize=8, zorder=11,
                    bbox={"facecolor": STYLE["canvas"], "edgecolor": "none", "pad": 1},
                    arrowprops={"arrowstyle": "-", "color": STYLE["text"]})


def draw_live_geometry(ax, nominal, kind, mode):
    controls = nominal["controls"]
    if kind == "OpenLaptop":
        lid = controls["lid"]
        draw_polygon(ax, lid["collision_sweep_outline"], facecolor=STYLE["sweep"],
                     edgecolor=STYLE["edge"], alpha=.32, linestyle="--", lw=1.2, zorder=4)
        sweep = np.asarray(lid["edge_sweep_xyz_m"]) * 100
        ax.plot(sweep[:, 0], sweep[:, 1], color=STYLE["edge"], lw=1.5, zorder=6)
        ax.annotate("", sweep[-1, :2], sweep[-4, :2], zorder=7,
                    arrowprops={"arrowstyle": "->", "color": STYLE["edge"]})
        hinge = np.asarray(lid["hinge_xyz_m"]) * 100
        ax.scatter(*hinge[:2], marker="s", color=STYLE["edge"], s=26, zorder=8)
        outlined_label(ax, "屏轴", hinge[:2] + [1, 1.5], zorder=9)
        outlined_label(ax, "翻盖扫掠", sweep[-1, :2] + [1, -4], zorder=9)
    for name, shape in nominal["attachment_outlines"].items():
        draw_polygon(ax, shape, facecolor=STYLE["attachment"], edgecolor=STYLE["edge"],
                     lw=.7, alpha=.56, zorder=5)
    for label, xyz in controls["targets_xyz_m"].items():
        if mode == "yaw" and label == TASKS[kind][-1]:
            continue
        if kind == "OpenLaptop":
            label = "掀屏接触边"
        elif kind == "ClickMouse":
            label = "左键按压点"
        point = np.asarray(xyz[:2]) * 100
        ax.scatter(*point, s=14, color=STYLE["attachment"], edgecolor=STYLE["edge"], zorder=8)
        offset = [-2.2, .6] if kind == "TypeKeys" and label == "I" and mode == "xy" else [.2, .6]
        outlined_label(ax, label, point + offset, size=8, zorder=9)
    if kind == "ClickMouse":
        right_button = controls["button_links"]["right button"]
        shape = np.asarray(nominal["attachment_outlines"][right_button]) * 100
        target = shape.mean(0)
        ax.annotate("右键", target, xytext=(7, -23), textcoords="offset points", fontsize=8,
                    arrowprops={"arrowstyle": "->", "color": STYLE["text"]}, zorder=9)


def local(ax, selected, nominal, kind, mode, data):
    center = np.asarray(nominal["pose"][:2]) * 100
    table = np.asarray(nominal["table_outline"]) * 100
    points = np.concatenate([np.asarray(row["device_outline"]) for row in selected]) * 100
    hull = points[ConvexHull(points).vertices]
    low, high = points.min(0) - 6, points.max(0) + 6
    table_edge = table[:, 0].min()
    if low[0] - table_edge < 24:
        low[0] = min(table_edge - 3, low[0])
    yaw_target = {"OpenLaptop": "掀屏接触边", "TypeKeys": "P 键", "ClickMouse": "左键按压点"}[kind]
    setup_ax(ax, "可采样中心和实际占地" if mode == "xy" else f"同一根位置与{yaw_target}",
             axes_widths=list(zip(low, high)))
    draw_polygon(ax, nominal["table_outline"], facecolor=STYLE["table"],
                 edgecolor=STYLE["edge"], lw=1.8)
    draw_polygon(ax, nominal["device_outline"], facecolor=STYLE["body"],
                 edgecolor=STYLE["edge"], alpha=.65, lw=1.3, zorder=2)
    draw_polygon(ax, nominal["support_outline"], facecolor="none",
                 edgecolor=STYLE["edge"], linestyle=":", lw=1, zorder=3)
    draw_live_geometry(ax, nominal, kind, mode)
    if mode == "xy":
        draw_polygon(ax, hull / 100, facecolor="none", edgecolor=STYLE["edge"],
                     lw=1.1, linestyle="--", zorder=3)
        device = TASKS[kind][0]
        native_extent = np.asarray(data["native_xy_half_range_m"]) * 100
        bounds(ax, center - native_extent, center + native_extent,
               color=STYLE["old"], fill="#b8bec0", zorder=6)
        lower, upper = center + np.asarray(XY_BOUNDS_M[device]) * 100
        bounds(ax, lower, upper,
               color=STYLE["new"], fill=(*matplotlib.colors.to_rgb(STYLE["blue_fill"]), .32),
               zorder=7)
        mark_centers(ax, selected, nominal, (lower + upper) / 2)
        nearest = min(selected, key=lambda row: row["tightest_table_edge_m"])
        limiting = np.asarray(nearest["device_outline"]) * 100
        corner = limiting[limiting[:, 0].argmin()]
        if table_edge >= low[0]:
            ax.annotate("", xy=(table_edge, corner[1]), xytext=corner,
                        arrowprops={"arrowstyle": "<->", "color": STYLE["text"]}, zorder=9)
            outlined_label(ax, f"{nearest['tightest_table_edge_m'] * 100:.2f} cm",
                           [(table_edge + corner[0]) / 2, corner[1] + 1], ha="center", zorder=9)
    else:
        # Derive native ±5° silhouettes around the same measured root, using
        # only the baked collision geometry from the nominal native reset.
        neutral = np.asarray(nominal["device_outline"]) * 100
        extent = data["native_yaw_half_range_deg"]
        for angle in (-extent, extent):
            a = math.radians(angle)
            matrix = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
            draw_polygon(ax, ((neutral - center) @ matrix.T + center) / 100,
                         facecolor="none", edgecolor=STYLE["old"], linestyle="--", lw=1.0, zorder=6)
        name = TASKS[kind][-1]
        for row, linestyle in zip(selected, ("-", "--", ":")):
            angle = row["request"][f"{TASKS[kind][0]}_yaw_offset_deg"]
            draw_polygon(ax, row["device_outline"], facecolor="none", edgecolor=STYLE["new"],
                         linestyle=linestyle, lw=1.5, zorder=7)
            p = np.asarray(row["controls"]["targets_xyz_m"][name][:2]) * 100
            ax.scatter(*p, s=27, color="white", edgecolor=STYLE["text"], lw=1.0, zorder=9)
            labels = ((-36, 20), (-30, 1), (-36, -23)) if kind == "OpenLaptop" else (
                (-34, 20), (0, 27), (30, 17))
            offset = labels[YAW_OFFSETS_DEG.index(angle)]
            ax.annotate(f"{angle:+d}°" if angle else "0°", p, xytext=offset,
                        textcoords="offset points", ha="center", fontsize=8,
                        bbox={"facecolor": STYLE["canvas"], "edgecolor": "none", "pad": 1},
                        arrowprops={"arrowstyle": "->", "color": STYLE["text"]}, zorder=10)
        ax.scatter(*center, s=32, color=STYLE["center"], edgecolor="white", zorder=10)
        nearest = min(selected, key=lambda row: row["tightest_table_edge_m"])
    return nearest


def plot(data, kind, mode, path):
    nominal = next(row for row in data["points"] if row["id"] == "N")
    if mode == "xy":
        selected = [row for row in data["points"] if row["id"] in ("N", "M") or row["id"].startswith("XY")]
    else:
        selected = [next(row for row in data["points"] if row["id"] == name)
                    for name in (f"R{YAW_OFFSETS_DEG[0]:+d}", "N", f"R{YAW_OFFSETS_DEG[-1]:+d}")]
    _, title, action, label, _ = TASKS[kind]
    fig, axes = plt.subplots(1, 2, figsize=(15.4, 8), facecolor=STYLE["canvas"],
                             gridspec_kw={"width_ratios": [1, 1.15]})
    fig.subplots_adjust(left=.055, right=.962, top=.79, bottom=.16, wspace=.12)
    fig.text(.055, .93, f"{title}  /  {'XY 平移' if mode == 'xy' else '物体朝向'}",
             fontsize=28, fontweight="bold", color=STYLE["text"])
    center = np.asarray(nominal["pose"][:2]) * 100
    context = "相对模型朝向固定 0°" if mode == "xy" else f"设备根固定 ({center[0]:g}, {center[1]:g}) cm"
    z = f"俯视 · {data['make_kwargs']['sim_backend']} 实测"
    fig.text(.057, .862, f"{kind} · {action} · {context} · {z}", fontsize=12, color=STYLE["edge"])
    fig.legend(handles=[
        Patch(facecolor="#b8bec0", edgecolor=STYLE["old"], label="旧域"),
        Patch(facecolor=STYLE["blue_fill"], edgecolor=STYLE["new"], label="新域"),
        Line2D([], [], marker="o", color="none", markerfacecolor=STYLE["center"], markeredgecolor="white", label="标称中心"),
        Line2D([], [], marker="o", color="none", markerfacecolor="white", markeredgecolor=STYLE["text"], label="样点"),
    ], loc="upper right", bbox_to_anchor=(.964, .954), ncol=4, frameon=False, fontsize=10)
    workspace(axes[0], nominal, label)
    nearest = local(axes[1], selected, nominal, kind, mode, data)
    all_valid = sum(bool(row["initialization_passed"]) for row in selected)
    foot = (f"{all_valid}/{len(selected)} 个样点通过真实后端初态检查 · 最小完整占地桌边余量 "
            f"{nearest['tightest_table_edge_m'] * 100:.2f} cm（{nearest['id']}，reset 位姿及碰撞几何）")
    if kind == "OpenLaptop":
        lid = nominal["controls"]["lid"]
        low, high = 100 * np.asarray(lid["collision_sweep_height_range_m"])
        foot += f" · 标称翻盖扫掠高度 {low:.1f}～{high:.1f} cm"
    else:
        foot += " · 点线为近底支撑外廓，绿色为关节部件"
    if kind == "TypeKeys":
        combinations = [row for row in data["points"] if row["id"].startswith("C")]
        limiting = min(combinations, key=lambda row: row["tightest_table_edge_m"])
        foot += f" · 叠加转角的 {limiting['id']} 余量 {limiting['tightest_table_edge_m'] * 100:.2f} cm"
    fig.add_artist(Line2D([.056, .961], [.105, .105], transform=fig.transFigure,
                          color="#ab9d83", lw=.7))
    fig.text(.057, .057, foot, fontsize=11, color=STYLE["text"])
    fig.savefig(path, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    sample_labels = {
        str(number): row["id"] for number, row in
        enumerate((row for row in selected if row["id"].startswith("XY")), start=1)
    }
    return {"image": path.name, "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "plot_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "backend": data["make_kwargs"]["sim_backend"],
            "source_commit": data["source_commit"], "point_ids": [row["id"] for row in selected],
            "xy_marker_to_sample_id": sample_labels,
            "limiting_point": nearest["id"], "table_edge_margin_m": nearest["tightest_table_edge_m"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="parent containing OpenLaptop, TypeKeys and ClickMouse result directories")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    configure_font()
    args.output.mkdir(parents=True, exist_ok=True)
    figures = []
    for index, kind in enumerate(TASKS):
        data = json.loads((args.input / kind / "results.json").read_text(encoding="utf-8"))
        device = TASKS[kind][0]
        for offset, mode in enumerate(("xy", "yaw"), start=1):
            output = args.output / f"{2 * index + offset:02d}_{device}_{mode}.png"
            figures.append(plot(data, kind, mode, output))
    (args.output / "FIGURES.json").write_text(json.dumps(figures, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
