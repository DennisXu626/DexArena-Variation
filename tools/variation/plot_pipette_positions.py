"""Generate one Pipette boundary PNG per variable from native runtime records."""

import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
from matplotlib import font_manager, pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Patch, Polygon, Rectangle
import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation


BG, TABLE, EDGE = '#f3f0e7', '#e4dcc8', '#555247'
BLUE, OLD, RED, INK = '#176ba5', '#808891', '#b83233', '#242a29'
OBJECT_COLORS = {'stand': '#81a0ad', 'cup': '#91b3a7', 'rack': '#8da7ba', 'tube': '#538779'}
NAMES = {'stand': '移液器支架', 'cup': '样品皿', 'rack': '试管架', 'tube': '试管'}
FIGURES = (
    ('AspirateLiquid', 'stand-xy', '01_stand_xy.png', '移液器支架 / XY 平移'),
    ('AspirateLiquid', 'stand-yaw', '02_stand_yaw.png', '移液器支架 / 朝向'),
    ('AspirateLiquid', 'cup-xy', '03_sample_dish_xy.png', '样品皿 / XY 平移'),
    ('DispenseLiquid', 'rack-xy', '04_tube_rack_xy.png', '试管架 / XY 平移'),
)


def cm(x):
    return np.asarray(x) * 100


def rotate(points, yaw):
    return Rotation.from_euler('z', yaw, degrees=True).apply(np.c_[points, np.zeros(len(points))])[:, :2]


def outline(hulls, name, xy, yaw=0):
    return cm(rotate(hulls[name], yaw) + np.asarray(xy))


def label(ax, txt, xy, to=None):
    if to is None:
        ax.text(*xy, txt, ha='center', va='center', color=INK, fontsize=9)
    else:
        ax.annotate(txt, xy, xytext=to, fontsize=9, color=INK,
                    arrowprops={'arrowstyle': '->', 'color': INK, 'lw': .85},
                    bbox={'fc': BG, 'ec': 'none', 'pad': 1.5}, ha='center')


def poly(ax, points, face, edge, **kwargs):
    ax.add_patch(Polygon(points, closed=True, facecolor=face, edgecolor=edge, **kwargs))


def box(ax, lo, hi, face, edge, **kwargs):
    ax.add_patch(Rectangle(lo, *(hi - lo), facecolor=face, edgecolor=edge, **kwargs))


def scene(ax, geometry, poses, bounds, focus=None):
    box(ax, *bounds, TABLE, EDGE, linewidth=1.5, zorder=0)
    poly(ax, cm(geometry['robot_base_world_hull_xy']), '#a9a38f', EDGE, alpha=.9, zorder=1)
    hulls = geometry['local_hulls_xy']
    for name, color in OBJECT_COLORS.items():
        if name in poses and name != focus:
            yaw = geometry['stand_nominal_yaw_deg'] if name == 'stand' else 0
            poly(ax, outline(hulls, name, poses[name][:2], yaw), color, EDGE, lw=1, alpha=.8, zorder=2)
    ax.set_aspect('equal')
    ax.grid(color='#a99f8e', alpha=.27, lw=.6)
    ax.set_facecolor('#f6f3eb')
    ax.set_xlabel('场景 X (cm)')
    ax.set_ylabel('场景 Y (cm)')
    ax.tick_params(labelsize=9)
    for spine in ax.spines.values():
        spine.set_color('#a59b86')


def full_table(ax, geometry, poses, bounds):
    scene(ax, geometry, poses, bounds)
    near = bounds[0, 0]
    ax.set_xlim(-140, 86)
    ax.set_ylim(-128, 128)
    ax.set_title('整桌与操作侧', loc='left', fontweight='bold')
    label(ax, '机器人底座', (-88, 0))
    label(ax, '桌面', (25, 95))
    label(ax, NAMES['stand'], cm(poses['stand'][:2]), (28, -35))
    target = 'cup' if 'cup' in poses else 'rack'
    label(ax, NAMES[target], cm(poses[target][:2]), (28, 39))
    label(ax, f'物理桌边  X = {near:.2f}', (near, -77), (-87, -93))


def add_workpoint(ax, obj, poses, geometry):
    xy = cm(poses[obj][:2])
    if obj == 'cup':
        radius = geometry['dish_target_radius_m'] * 100
        ax.add_patch(Circle(xy, radius, fc='none', ec='#3f6f62', ls='--', lw=1.25, zorder=4))
        label(ax, '判定用皿内区', xy + [0, radius], xy + [14, 7])
    if obj == 'rack':
        label(ax, '试管与中央槽同移', cm(poses['tube'][:2]), xy + [4, 11])
    if obj == 'stand':
        radius = 100 * geometry['stand_return_radius_m']
        ax.add_patch(Circle(xy, radius, fc='none', ec='#3f6f62', ls='--', lw=1.15, zorder=3))
        label(ax, '停放判定 XY 区', xy + [radius, 0], xy + [21, -2])
        ax.annotate('手指接近', xy=xy + [-4, -1], xytext=xy + [-17, -1],
                    color=INK, fontsize=9, arrowprops={'arrowstyle': '->', 'color': INK})


def translation(ax, geometry, poses, bounds, samples, obj):
    scene(ax, geometry, poses, bounds, focus=obj)
    hulls = geometry['local_hulls_xy']
    xy0 = np.asarray(poses[obj][:2])
    values = np.asarray([cm(json.loads(row['pose_wxyz'])[obj][:2]) for row in samples])
    yaw = geometry['stand_nominal_yaw_deg'] if obj == 'stand' else 0
    hull = outline(hulls, obj, xy0, yaw)
    envelope = np.vstack([outline(hulls, obj, xy/100, yaw) for xy in values])
    poly(ax, envelope[ConvexHull(envelope).vertices], 'none', EDGE, ls='--', lw=1.1, zorder=2)
    poly(ax, hull, OBJECT_COLORS[obj], EDGE, alpha=.68, lw=1.3, zorder=2)
    old_half = cm(geometry['native_xy_half_ranges_m'][obj])
    box(ax, cm(xy0) - old_half, cm(xy0) + old_half, OLD, '#656f76', alpha=.58, zorder=3)
    new_lo, new_hi = values.min(axis=0), values.max(axis=0)
    box(ax, new_lo, new_hi, '#98c9e5', BLUE, linewidth=1.3, alpha=.69, zorder=4)
    for row, pt in zip(samples, values):
        if row['id'] == 'N0':
            continue
        if row['id'] == 'M':
            ax.scatter(*pt, s=35, marker='x', color=BLUE, zorder=7)
        else:
            ax.scatter(*pt, s=30, color='white', edgecolor=INK, zorder=6)
        ax.annotate(row['id'], pt, xytext=(5, 4), textcoords='offset points', fontsize=7.8, zorder=7)
    ax.scatter(*cm(xy0), s=42, color=RED, edgecolor='white', zorder=8)
    ax.annotate('N0', cm(xy0), xytext=(4, 5), textcoords='offset points', fontsize=7.8, zorder=9)
    add_workpoint(ax, obj, poses, geometry)
    y = xy0[1] * 100
    refs = ('cup',) if obj == 'stand' else ('stand',) if obj == 'cup' else ()
    for name in refs:
        px, py = cm(poses[name][:2])
        label(ax, NAMES[name], (px, py), (px + 14, py + 3))
    if obj != 'rack':
        ylo, yhi = min(y - 14, -29), max(y + 14, 10)
    else:
        ylo, yhi = y - 18, y + 18
    ax.set(xlim=(-44, 13), ylim=(ylo, yhi))
    ax.set_title('中心域与完整碰撞外廓', loc='left', fontweight='bold')


def heading(ax, geometry, poses, bounds, samples):
    scene(ax, geometry, poses, bounds, focus='stand')
    center = np.asarray(poses['stand'][:2])
    hulls = geometry['local_hulls_xy']
    mid = geometry['stand_nominal_yaw_deg']
    half = geometry['native_yaw_half_range_deg']
    old = np.vstack([outline(hulls, 'stand', center, yaw) for yaw in np.linspace(mid - half, mid + half, 13)])
    poly(ax, old[ConvexHull(old).vertices], OLD, OLD, alpha=.38, zorder=2)
    stand = outline(hulls, 'stand', center, mid)
    poly(ax, stand, OBJECT_COLORS['stand'], EDGE, alpha=.69, zorder=3)
    tracked = np.asarray(geometry['dimensions']['stand']['shapes'][1]['pose'][:2])
    dashes = ('-', '--', ':')
    for k, (row, style) in enumerate(zip(samples, dashes)):
        yaw = round(json.loads(row['measurements'])['stand_yaw_deg'])
        poly(ax, outline(hulls, 'stand', center, yaw), 'none', BLUE, ls=style, lw=1.35, zorder=4)
        pt = cm(rotate([tracked], yaw)[0] + center)
        ax.scatter(*pt, s=25, color='white', edgecolor=INK, zorder=5)
        label(ax, f'{row["id"]}  {yaw}°', pt, (-4, -23 + 3.2*k))
    ax.scatter(*cm(center), color=RED, s=42, edgecolor='white', zorder=6)
    label(ax, '固定转心', cm(center), (-3, -12))
    label(ax, '同一根后立柱中心', (-11, -21), (0, -30))
    label(ax, '样品皿', cm(poses['cup'][:2]), (-2, 1))
    ax.set(xlim=(-39, 12), ylim=(-36, 10))
    ax.set_title('支架轮廓与同一后立柱', loc='left', fontweight='bold')


def make_figure(directory, outfile, task, category, title, rows):
    geometry = json.loads((directory / f'GEOMETRY-{task}.json').read_text(encoding='utf-8'))
    task_rows = [row for row in rows if row['task'] == f'PipetteTransfer{task}-Sharpa-v1']
    nominal = next(row for row in task_rows if row['category'] == 'stand-xy' and row['id'] == 'N0')
    samples = [row for row in task_rows if row['category'] == category]
    poses, bounds = json.loads(nominal['pose_wxyz']), cm(json.loads(nominal['measurements'])['table_bounds_m'])
    fig, (wide, detail) = plt.subplots(1, 2, figsize=(13.7, 7.2), gridspec_kw={'width_ratios': [1, 1.3]})
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=.09, right=.96, top=.78, bottom=.16, wspace=.23)
    fig.text(.085, .92, title, fontsize=24, fontweight='bold', color=INK)
    scope = 'AspirateLiquid、DispenseLiquid' if category.startswith('stand-') else task
    fig.text(.088, .862, f'{scope}  ·  场景 XY  ·  支架与竖直移液器共用根 XY，吸头朝下', fontsize=10.5, color=EDGE)
    fig.legend(handles=[Patch(facecolor=OLD, edgecolor=EDGE, label='旧域'),
                        Patch(facecolor='#98c9e5', edgecolor=BLUE, label='候选域'),
                        Line2D([], [], marker='o', ls='', mfc=RED, mec='white', label='标称点'),
                        Line2D([], [], marker='o', ls='', mfc='white', mec=INK, label='样点'),
                        Line2D([], [], marker='x', ls='', color=BLUE, label='新域中心')],
               ncol=5, loc='upper right', bbox_to_anchor=(.966, .985), frameon=False, fontsize=9)
    full_table(wide, geometry, poses, bounds)
    if category == 'stand-yaw':
        heading(detail, geometry, poses, bounds, samples)
        note = '桌上其余物体固定标称值。白点跟踪同一根后立柱。支架转动时，竖直移液器保持原生朝向。'
        margin_key, metric_obj, metric_name = 'stand_dish_gap_lower_bound_m', None, '皿与支架投影净距下界'
    else:
        obj = category.split('-')[0]
        translation(detail, geometry, poses, bounds, samples, obj)
        note = '其余位置取标称值，支架固定 90°。虚线是完整足迹的移动包络；红点与蓝叉区分标称点和候选域中心。'
        margin_key, metric_obj, metric_name = 'table_margin_m', obj, '完整足迹到桌边余量'
    pairs = []
    for row in samples:
        margin = json.loads(row['measurements'])[margin_key]
        pairs.append((margin if metric_obj is None else margin[metric_obj], row['id']))
    minimum, sample = min(pairs)
    passes = sum(json.loads(row['ik'])['passed'] for row in samples)
    if category == 'rack-xy':
        slot_margin = json.loads(nominal['measurements'])['tube_slot_margin_m'] * 1000
        note = f'试管在中央槽随架移动；槽壁与管体的投影余量 {slot_margin:.2f} mm。其余位置取标称值。'
    fig.text(.088, .077, note, fontsize=10, color=INK)
    fig.text(.088, .048, f'按实测 reset 位姿和加载碰撞体计算最紧样点 {sample}，{metric_name} {minimum*1000:.2f} mm。'
             f'初态 {len(samples)}/{len(samples)}，指尖 IK {passes}/{len(samples)}。', fontsize=10, color=INK)
    fig.savefig(outfile, dpi=170, facecolor=BG)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('measurements', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--font', type=Path)
    args = parser.parse_args()
    if args.font:
        font_manager.fontManager.addfont(args.font)
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=args.font).get_name()
    plt.rcParams['axes.unicode_minus'] = False
    with (args.measurements / 'POINTS.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    args.output.mkdir(parents=True, exist_ok=True)
    for task, category, name, title in FIGURES:
        make_figure(args.measurements, args.output / name, task, category, title, rows)


if __name__ == '__main__':
    main()
