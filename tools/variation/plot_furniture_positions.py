"""Plot the six Furniture position boundaries from native geometry and reset evidence."""

import argparse
import inspect
import json
from pathlib import Path

import gymnasium as gym
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon
import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation

from tasks.furniture_assembly.furniture_assembly_fasten_screw import (
    FurnitureAssemblyFastenScrewEnv, SCREW_TARGET_ROTATION, WING_HALF, WING_SCREW_HUB_RADIUS,
    WING_SCREW_STEM_HEIGHT,
)
from tasks.furniture_assembly.furniture_assembly_insert_rail import (
    FurnitureAssemblyInsertRailEnv, RAIL_HALF, RAIL_SCREW_LOCAL_POSITIONS, RAIL_SEATED_X_LOCAL,
)
from tasks.furniture_assembly.furniture_assembly_lay_flat_panel import (
    FurnitureAssemblyLayFlatPanelEnv, GROOVE_HALF_W, GROOVE_MOUTH_FLARE, GROOVE_MOUTH_LENGTH,
    GROOVE_STOP_X, PANEL_HALF, PANEL_IN_SLOT_Z, PLACE_CENTER, PLACE_REGION_HALF_SIZE,
    RACK_BASE_HALF, RACK_SLOT_FLOOR_Z, RACK_SLOT_HALF_W, RACK_TOP_Z, RACK_WALL_HALF_T,
)
from tasks.furniture_assembly.position_layout import XY_OFFSETS_M, YAW_DEGREES
from tools.variation.check_furniture_positions import pose, rotation, table_geometry
from tools.variation.furniture_position_samples import CENTERS, FIGURE_PREFIX, rect


FIGURES = (
    ("01_rack_xy", "rack", "xy", "LayFlatPanel", "导向架 / XY 平移"),
    ("02_rack_yaw", "rack", "yaw", "LayFlatPanel", "导向架 / 朝向"),
    ("03_rail_xy", "rail", "xy", "InsertRail", "待拾导轨 / XY 平移"),
    ("04_rail_yaw", "rail", "yaw", "InsertRail", "待拾导轨 / 朝向"),
    ("05_panel_xy", "panel", "xy", "FastenScrew", "交接板件 / XY 平移"),
    ("06_panel_yaw", "panel", "yaw", "FastenScrew", "交接板件 / 朝向"),
)
ENV_CLASSES = {"rack": FurnitureAssemblyLayFlatPanelEnv, "rail": FurnitureAssemblyInsertRailEnv,
               "panel": FurnitureAssemblyFastenScrewEnv}
HALF = {"rack": RACK_BASE_HALF, "rail": RAIL_HALF, "panel": PANEL_HALF}
ROLE_CN = {"rack": "导向架", "rail": "待拾导轨", "panel": "板件"}
TINT = {"rack": "#b87748", "rail": "#4e827b", "panel": "#ad7952"}
BACKGROUND, AXES, TABLE, INK = "#f5f1e8", "#f8f5ee", "#e6dec9", "#282b2a"
BLUE, GREY, RED = "#176aab", "#677483", "#b92c32"


def xy_transform(vertices, center, yaw):
    transform = Rotation.from_euler("z", yaw, degrees=True).as_matrix()[:2, :2]
    return transform @ np.asarray(vertices).T + np.asarray(center)[:, None]


def patch(ax, vertices, **kwargs):
    ax.add_patch(Polygon(100 * vertices.T, closed=True, **kwargs))


def outline(ax, center, half, yaw=0., **kwargs):
    patch(ax, rect(center, half, yaw), **kwargs)


def check_plot_geometry():
    """Read the actual table collision and the projected robot base collision shape."""
    task = "FurnitureAssemblyLayFlatPanel-Sharpa-v1"
    kwargs = dict(num_envs=1, sim_backend="physx_cpu", obs_mode="state", render_mode=None, reconfiguration_freq=0)
    with gym.make(task, **kwargs) as env:
        e = env.unwrapped
        env.reset(seed=701, options={"position_layout": {"0": {}}})
        center, half, table_z = table_geometry(e)
        vertices = []
        for name, link in e.agent.robot.links_map.items():
            if not name.startswith("mobile_base_link"):
                continue
            link_pose = pose(link, 0)
            for shape in link._bodies[0].collision_shapes:
                local = shape.local_pose
                orient = Rotation.from_quat(local.q[[1, 2, 3, 0]])
                link_vertices = local.p + orient.apply(shape.vertices * shape.scale)
                vertices.extend(link_pose[:3] + rotation(link_pose).apply(link_vertices))
        vertices = np.asarray(vertices)[:, :2]
        boundary = vertices[ConvexHull(vertices).vertices]
        return dict(table_center_xy_m=center.tolist(), table_half_xy_m=half.tolist(), table_top_z_m=table_z,
                    base_collision_hull_xy_m=boundary.tolist(), source_task=task, make=kwargs)


def native_bounds(role):
    params = inspect.signature(ENV_CLASSES[role].__init__).parameters
    x, y = (params[f"{role}_random_{axis}"].default for axis in ("x", "y"))
    yaw = params[f"{role}_random_yaw" + ("_deg" if role == "panel" else "")].default
    return x, y, yaw if role == "panel" else np.rad2deg(yaw)


def rack(ax, center, yaw, detail):
    outline(ax, center, RACK_BASE_HALF, yaw, facecolor=TINT["rack"], edgecolor="#674b37", lw=1.4, alpha=.8)
    for sign in (-1., 1.):
        xy = xy_transform([[0., sign * (RACK_SLOT_HALF_W + RACK_WALL_HALF_T)]], center, yaw)[:, 0]
        outline(ax, xy, [RACK_BASE_HALF[0], RACK_WALL_HALF_T], yaw, color="#79482c", alpha=.95)
    outline(ax, center, [PANEL_HALF[0], PANEL_HALF[2]], yaw, facecolor="#eed9a9", edgecolor="#593c27", lw=1.)
    if detail:
        board_edge = xy_transform([[.12, 0.]], center, yaw)[:, 0]
        ax.annotate("槽内立板 · 向上取出", 100 * board_edge, xytext=(16, 14), textcoords="offset points",
                    arrowprops={"arrowstyle": "->", "color": INK}, fontsize=9)


def flat_panel(ax, center, yaw, detail, show_wing):
    outline(ax, center, PANEL_HALF, yaw, facecolor=TINT["panel"], edgecolor="#6e4c33", lw=1.4, alpha=.72)
    mouth_x = -PANEL_HALF[0]
    wide = GROOVE_HALF_W + GROOVE_MOUTH_FLARE
    narrow_x = mouth_x + GROOVE_MOUTH_LENGTH
    groove = [(mouth_x, -wide), (narrow_x, -GROOVE_HALF_W), (GROOVE_STOP_X, -GROOVE_HALF_W),
              (GROOVE_STOP_X, GROOVE_HALF_W), (narrow_x, GROOVE_HALF_W), (mouth_x, wide)]
    patch(ax, xy_transform(groove, center, yaw), facecolor="#edcfa2", edgecolor="#734d32", lw=.8)
    seated = xy_transform([[RAIL_SEATED_X_LOCAL, 0.]], center, yaw)[:, 0]
    outline(ax, seated, RAIL_HALF, yaw, facecolor="#728b89" if show_wing else "none",
            edgecolor="#375c58", ls="-" if show_wing else "--", lw=1.4, alpha=.8)
    if show_wing:
        screw(ax, center, yaw, detail)
    if detail:
        points = xy_transform([[mouth_x - .045, 0.], [mouth_x + .04, 0.]], center, yaw)
        ax.annotate("插入", xy=100 * points[:, 1], xytext=100 * points[:, 0],
                    arrowprops={"arrowstyle": "->", "color": INK}, fontsize=9, va="bottom")
        xy = xy_transform([[GROOVE_STOP_X, 0.]], center, yaw)[:, 0]
        ax.annotate("止挡", 100 * xy, xytext=(5, 25), textcoords="offset points",
                    arrowprops={"arrowstyle": "->", "color": INK}, fontsize=9)


def screw(ax, panel_center, yaw, detail):
    sx, sy, _ = RAIL_SCREW_LOCAL_POSITIONS[0]
    pivot = xy_transform([[RAIL_SEATED_X_LOCAL + sx, sy]], panel_center, yaw)[:, 0]
    hub = plt.Circle(100 * pivot, 100 * WING_SCREW_HUB_RADIUS, color="#454b46", zorder=6)
    ax.add_patch(hub)
    outline(ax, pivot, WING_HALF, yaw, color="#3a403b", zorder=6)
    if detail:
        end_yaw = yaw - np.rad2deg(SCREW_TARGET_ROTATION)
        outline(ax, pivot, WING_HALF, end_yaw, facecolor="none", edgecolor="#39433e", ls="--", lw=.9)
        theta = np.deg2rad(np.linspace(yaw, end_yaw, 25))
        sweep = 100 * (pivot[:, None] + WING_HALF[0] * np.stack([np.cos(theta), np.sin(theta)]))
        ax.plot(*sweep, color="#39433e", ls=":", lw=1.)
        ax.annotate("翼部顺时针扫掠", 100 * pivot, xytext=(-4, 28), textcoords="offset points",
                    arrowprops={"arrowstyle": "->", "color": INK}, fontsize=9, zorder=9)


def background(ax, geometry, full):
    ax.set_facecolor(AXES)
    outline(ax, geometry["table_center_xy_m"], geometry["table_half_xy_m"], facecolor=TABLE,
            edgecolor="#544e41", linewidth=1.8, zorder=0)
    if full:
        patch(ax, np.asarray(geometry["base_collision_hull_xy_m"]).T,
              facecolor="#a6a28f", edgecolor="#666052", lw=1.2, zorder=1)
        ax.text(10, 99, "真实桌面", fontsize=11, color=INK)
        ax.text(-86, 2, "机器人底座轮廓", fontsize=9, ha="center", color=INK)
        near_edge = 100 * (geometry["table_center_xy_m"][0] - geometry["table_half_xy_m"][0])
        ax.annotate(f"物理桌边 X = {near_edge:.2f} cm", (near_edge, -92), xytext=(-123, -103),
                    arrowprops={"arrowstyle": "->", "color": INK}, fontsize=8)
    ax.set_axisbelow(True)
    ax.grid(color="#867d69", alpha=.18)
    ax.set_aspect("equal", adjustable="box")
    ax.set_anchor("N")
    ax.set_xlabel("世界 X (cm)")
    ax.set_ylabel("世界 Y (cm)")
    for spine in ax.spines.values():
        spine.set_color("#a39783")


def scene(ax, role, detail):
    outline(ax, PLACE_CENTER, PLACE_REGION_HALF_SIZE, facecolor="none", edgecolor="#856340", ls="--", lw=1.5)
    if detail:
        ax.text(-6, -.5 if role == "rack" else 8.1, "固定放置成功区", fontsize=8, color="#694f33")
    if role == "rack":
        rack(ax, CENTERS[role], 0., detail)
    else:
        flat_panel(ax, CENTERS["panel"], 0., detail, role == "panel")
        label = "待拾导轨" if role == "rail" else "InsertRail 的待拾导轨"
        outline(ax, CENTERS["rail"], RAIL_HALF, facecolor=TINT["rail"], edgecolor="#375c58", lw=1.1, alpha=.75)
        ax.text(-25, -32, label, fontsize=9 if detail else 7, color="#274e47")
        head_xy = np.asarray(CENTERS["rail"]) + RAIL_SCREW_LOCAL_POSITIONS[0][:2]
        ax.scatter(*(100 * head_xy), facecolor="#3a403b", s=9, zorder=4)
        if detail and role == "rail":
            ax.annotate("螺钉随导轨", 100 * head_xy, xytext=(-28, 15), textcoords="offset points",
                        arrowprops={"arrowstyle": "->", "color": INK}, fontsize=8)


def collect_samples(points, role, mode):
    for row in points:
        if row["point"] == "N" or row["figure"] in (f"{role}_{mode}", f"{role}_{mode}_midpoints"):
            yield row["point"], row["measured_poses"][role][:2], row["measured_yaw_deg"][role]


def domain_xy(ax, role, samples):
    center = np.asarray(CENTERS[role])
    old_x, old_y, _ = native_bounds(role)
    outline(ax, center, [old_x, old_y], facecolor=GREY, edgecolor=GREY, lw=1., alpha=.33, zorder=3)
    bounds = np.array(XY_OFFSETS_M[role])
    midpoint = center + bounds.mean(axis=1)
    half = np.ptp(bounds, axis=1) / 2
    outlines = np.concatenate([rect(xy, HALF[role]).T for _, xy, _ in samples])
    outline_union = outlines[ConvexHull(outlines).vertices]
    patch(ax, outline_union.T, edgecolor="#724c37", facecolor="none", ls="--", lw=1.15, zorder=3)
    outline(ax, midpoint, half, facecolor="#79b8e5", edgecolor=BLUE, lw=1.4, alpha=.55, zorder=4)
    columns = {-1: [], 0: [], 1: []}
    for point, xy, _ in samples:
        x, y = 100 * np.asarray(xy)
        nominal = point == "N"
        ax.scatter(x, y, c=RED if nominal else "white", edgecolor="white" if nominal else INK,
                   lw=.9, s=22, zorder=8)
        if not nominal:
            column = 0 if abs(x - center[0] * 100) < .001 else int(np.sign(x - center[0] * 100))
            columns[column].append((point.split("-")[-1], x, y))
    for column, labels in columns.items():
        labels.sort(key=lambda row: row[2])
        mean_y = np.mean([row[2] for row in labels])
        spacing = max((labels[-1][2] - labels[0][2]) / (len(labels) - 1), 1.75)
        for index, (label, x, y) in enumerate(labels):
            label_y = mean_y + spacing * (index - (len(labels) - 1) / 2)
            dx = .7 * column + (.3 if column == 0 else 0.)
            side = {-1: "right", 0: "left", 1: "left"}[column]
            ax.annotate(label, xy=(x, y), xytext=(x + dx, label_y), ha=side, va="center",
                        arrowprops={"arrowstyle": "-", "color": INK, "lw": .6, "shrinkB": 3},
                        fontsize=7.5, zorder=9, color=INK)
    if np.linalg.norm(midpoint - center) > .000001:
        ax.scatter(*(100 * midpoint), marker="x", color=BLUE, s=22, zorder=9)


def domain_yaw(ax, role, samples):
    center = CENTERS[role]
    half = HALF[role]
    old_yaw = native_bounds(role)[2]
    old_points = np.concatenate([rect(center, half, yaw).T for yaw in np.linspace(-old_yaw, old_yaw, 31)])
    old_outline = old_points[ConvexHull(old_points).vertices]
    patch(ax, old_outline.T, facecolor=GREY, edgecolor=GREY, alpha=.23, lw=1., zorder=3)
    styles = ("-", "--", ":")
    for index, (point, xy, yaw) in enumerate(sorted(samples, key=lambda row: row[2])):
        outline(ax, xy, half, yaw, edgecolor=BLUE, facecolor="none", ls=styles[index], lw=1.5, zorder=5)
        # Track the same +X, +Y collision corner in all three orientations.
        corner = rect(xy, half, yaw)[:, 2] * 100
        ax.scatter(*corner, facecolor="white", edgecolor=INK, s=26, zorder=8)
        ax.annotate(f"{point} {yaw:+.0f}°", corner, xytext=(11, (-8, 4, 16)[index]),
                    textcoords="offset points", fontsize=8, arrowprops={"arrowstyle": "-", "color": INK}, zorder=9)
        if role == "panel" and point != "N":
            screw(ax, xy, yaw, False)
    ax.scatter(*(100 * np.asarray(center)), c=RED, edgecolor="white", lw=1., s=42, zorder=8)


def tight_caption(role, mode, tasks):
    task = {"rack": "LayFlatPanel", "rail": "InsertRail", "panel": "FastenScrew"}[role]
    selected = cases_of(tasks[task], role, mode)
    metric = {"rack": "rack_table_edge_m", "rail": "rail_to_panel_y_m", "panel": "panel_inside_place_m"}[role]
    minimum = min(selected, key=lambda row: row["clearances_m"][metric])
    combined = min((row for row in tasks[task]["points"] if row["figure"] == "combined"),
                   key=lambda row: row["clearances_m"][metric])
    distance = 1000 * minimum["clearances_m"][metric]
    combined_distance = 1000 * combined["clearances_m"][metric]
    metric_cn = {"rack": "架底最小桌边余量", "rail": "导轨与平板最小 Y 向投影净距", "panel": "板件完整轮廓至成功区边界"}[role]
    first = f"按 reset 后的位姿投影，{minimum['point']} 的{metric_cn}为 {distance:.2f} mm。"
    first += f"　叠加 {combined['point']} 为 {combined_distance:.2f} mm。"
    if mode == "xy":
        first += f"　图中数字对应逐点表 {FIGURE_PREFIX[role]}XY-编号。"
    if role == "rack":
        rest = f"架底贴桌，槽底 Z={RACK_SLOT_FLOOR_Z * 100:.1f} cm，槽顶 Z={RACK_TOP_Z * 100:.1f} cm，立板中心 Z={PANEL_IN_SLOT_Z * 100:.2f} cm。"
    elif role == "rail":
        rest = "待拾导轨的底面在桌面，螺钉随导轨移动。虚线导轨表示沟槽内的就位轮廓。"
    else:
        rest = f"InsertRail 板槽朝上。FastenScrew 导轨随板件就位，翼部中心相对螺钉根高 {(WING_SCREW_STEM_HEIGHT + WING_HALF[2]) * 100:.1f} cm。灰域为 FastenScrew 原生范围，InsertRail 原生定点。"
    return first, rest


def cases_of(task, role, mode):
    matching = {f"{role}_{mode}", f"{role}_{mode}_midpoints"}
    return [row for row in task["points"] if row["point"] == "N" or row["figure"] in matching]


def plot_one(target, specification, geometry, runtime):
    filename, role, mode, task, title = specification
    fig = plt.figure(figsize=(14.2, 8.1), facecolor=BACKGROUND)
    gs = fig.add_gridspec(1, 2, left=.08, right=.957, bottom=.20, top=.794, wspace=.28)
    full, detail = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    for ax, is_full in ((full, True), (detail, False)):
        background(ax, geometry, is_full)
        scene(ax, role, not is_full)
    full.set(xlim=(-135, 84), ylim=(-126, 126))
    if role == "rack":
        detail.set(xlim=(-47, 22), ylim=(-2, 42))
    else:
        detail.set(xlim=(-47, 22), ylim=(-39, 11))
    full.set_title("整桌与周边物体", loc="left", color=INK, fontweight="bold", pad=11)
    detail.set_title("旋转中心、同一碰撞角与障碍" if mode == "yaw" else "中心采样域、完整占地与操作方向",
                     loc="left", color=INK, fontweight="bold", pad=11)
    samples = list(collect_samples(runtime["tasks"][task]["points"], role, mode))
    (domain_xy if mode == "xy" else domain_yaw)(detail, role, samples)
    full.scatter(*(100 * np.asarray(CENTERS[role])), c=RED, edgecolor="white", lw=.9, s=24, zorder=8)
    fig.text(.07, .932, title, fontsize=27, weight="bold", color=INK)
    x, y = np.asarray(CENTERS[role]) * 100
    stage = "InsertRail、FastenScrew" if role == "panel" else task
    setting = "中心固定，转轴为世界 +Z" if mode == "yaw" else "物体朝向固定 0°"
    fig.text(.071, .875, f"{stage}  ·  世界 XY  ·  {ROLE_CN[role]}标称 ({x:g}, {y:g}) cm  ·  {setting}",
             fontsize=12, color="#575045")
    handles = [Patch(facecolor=GREY, edgecolor=GREY, alpha=.45, label="旧范围"),
               Patch(facecolor="#79b8e5", edgecolor=BLUE, label="新范围"),
               Line2D([], [], color=RED, marker="o", ls="", label="标称 N"),
               Line2D([], [], color=INK, marker="o", markerfacecolor="white", ls="", label="样点")]
    if mode == "xy" and np.any(np.abs(np.asarray(XY_OFFSETS_M[role]).mean(axis=1)) > .000001):
        handles.append(Line2D([], [], color=BLUE, marker="x", ls="", label="新域中心"))
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(.965, .959), ncols=len(handles), frameon=False, fontsize=9)
    first, rest = tight_caption(role, mode, runtime["tasks"])
    fig.lines.append(Line2D([.071, .958], [.142, .142], color="#b6aa95", transform=fig.transFigure, lw=1.))
    fig.text(.071, .098, first, fontsize=10, color=INK)
    fig.text(.071, .062, rest, fontsize=10, color=INK)
    target_file = target / (filename + ".png")
    fig.savefig(target_file, dpi=155, facecolor=fig.get_facecolor())
    plt.close(fig)


def run(runtime_path, target, supplement_path=None):
    geometry = check_plot_geometry()
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    if runtime["status"] != "passed":
        raise ValueError("plots require a completed and passing initial-state batch")
    if supplement_path is not None:
        supplement = json.loads(supplement_path.read_text(encoding="utf-8"))
        if supplement["status"] != "passed" or supplement["scope"] != "asymmetric_xy_midpoints":
            raise ValueError("the supplement must be an accepted asymmetric midpoint batch")
        for kind, task in supplement["tasks"].items():
            runtime["tasks"][kind]["points"].extend(task["points"])
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    sans = next((name for name in ("Microsoft YaHei", "Noto Sans CJK SC", "SimHei") if name in fonts), None)
    if sans is None:
        raise RuntimeError("install a CJK font (Microsoft YaHei or Noto Sans CJK SC) before plotting")
    plt.rcParams.update({"font.family": sans, "axes.unicode_minus": False})
    target.mkdir(parents=True, exist_ok=True)
    (target / "PLOT_GEOMETRY.json").write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
    for figure in FIGURES:
        plot_one(target, figure, geometry, runtime)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--supplement", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.runtime, args.output, args.supplement)
