"""Plot each workspace freedom separately in world centimetres."""

import argparse
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Circle, Polygon, Rectangle
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plot_nut_bolt_positions import draw_bolt, draw_nut

BLUE = "#287ba8"
NAVY = "#21475c"
GREY = "#6d7071"
DIR = ROOT / "docs/variation/evidence/nut_bolt_workspace"


def cells_for(task, spec, field):
    yaw, *p = spec["presets"]["near"]
    size = np.array(spec["cell_size_mm"])
    cells = np.array(spec["cells"][str(yaw)])[:, :-1]
    p = np.asarray(p)
    if field == "free":
        cells = cells[np.all((cells[:, :2] <= p[:2]) & (p[:2] < cells[:, :2] + size[:2]), axis=1)]
        return p[:2] / 10 + cells[:, 2:] / 10, size[2:] / 10
    if task == "SeatNut":
        cells = cells[np.all((cells[:, 2:] <= p[2:]) & (p[2:] < cells[:, 2:] + size[2:]), axis=1)]
    return cells[:, :2] / 10, size[:2] / 10


def point(task, field, spec, name):
    yaw, *pos = spec["presets"][name]
    p = np.asarray(pos) / 10
    return p[:2] + p[2:] if field == "free" else p[:2]


def plot(task, field, name, models, specs, records):
    model = models[task]
    g = model["geometry"]
    spec = specs[task]
    yaw = spec["presets"]["near"][0]
    table_lo = np.array(g["table_lo"][:2]) * 100
    table_hi = np.array(g["table_hi"][:2]) * 100
    near = point(task, field, spec, "near")
    far = point(task, field, spec, "far")
    yaw_plot = field == "yaw"
    edges, size = cells_for(task, spec, "xy" if yaw_plot else field)
    if yaw_plot:
        common = set.intersection(
            *[set(tuple(c[:-1]) for c in bucket) for bucket in spec["cells"].values()]
        )
        lo = min(
            common, key=lambda c: np.linalg.norm(np.asarray(c) + size * 5 - np.mean(edges, axis=0) * 10)
        )
        anchor = (np.array(lo) + size * 5) / 10
    else:
        anchor = near
    native_xy = (
        np.array(
            g["bolt_spawn_xy_m"]
            if task == "PickBolt"
            else g["table_nut_xy_m"] if field == "free" else g["handoff_xy_m"]
        )
        * 100
    )
    extent = (
        min(edges[:, 0].min(), native_xy[0]) - 6,
        max((edges + size)[:, 0].max(), native_xy[0]) + 6,
        min(edges[:, 1].min(), native_xy[1]) - 6,
        max((edges + size)[:, 1].max(), native_xy[1]) + 6,
    )
    fig, axs = plt.subplots(1, 2, figsize=(11, 5), gridspec_kw={"width_ratios": [0.85, 1.15]})
    for i, ax in enumerate(axs):
        ax.set_aspect("equal")
        ax.add_patch(Rectangle(table_lo, *(table_hi - table_lo), facecolor="#f6f0df", edgecolor="#514d44"))
        for vertices in g["base_parts_xy_m"]:
            ax.add_patch(Polygon(np.asarray(vertices) * 100, fc="#bbb6b0", ec=GREY, lw=0.45))
        if i == 0:
            ax.set_xlim(-126, 85)
            ax.set_ylim(-125, 125)
            ax.set_title("Physical table and robot")
        else:
            ax.set_xlim(*(anchor[0] + np.array([-6, 6]) if yaw_plot else extent[:2]))
            ax.set_ylim(*(anchor[1] + np.array([-6, 6]) if yaw_plot else extent[2:]))
            ax.set_title("Fixed centre, supported yaws" if yaw_plot else "Conditional position domain")
        if yaw_plot:
            for angle in sorted(map(int, spec["cells"])):
                if task == "PickBolt":
                    draw_bolt(ax, g, anchor, yaw=angle, fallen=True, outline=BLUE, fill=False)
                    tracked = anchor + 5.5 * np.array(
                        [np.cos(np.deg2rad(angle)), np.sin(np.deg2rad(angle))]
                    )
                else:
                    draw_nut(ax, g, anchor, yaw=angle, threaded=True, outline=BLUE, fill=False)
                    tracked = anchor + 2.2 * np.array(
                        [np.cos(np.deg2rad(angle)), np.sin(np.deg2rad(angle))]
                    )
                ax.scatter(*tracked, s=12, c=BLUE, zorder=7)
                if i:
                    direction = (tracked - anchor) / np.linalg.norm(tracked - anchor)
                    at = anchor + direction * (4.2 if task == "TurnNut" else 5.85)
                    ax.annotate(
                        f"{angle}°",
                        tracked,
                        xytext=at,
                        ha="center",
                        va="center",
                        arrowprops={"arrowstyle": "-", "lw": 0.6, "color": GREY},
                        fontsize=8,
                    )
            for old in g["candidate"][
                "bolt_spawn_yaw_deg" if task == "PickBolt" else "threaded_nut_relative_yaw_deg"
            ]:
                draw = draw_bolt if task == "PickBolt" else draw_nut
                draw(
                    ax,
                    g,
                    anchor,
                    yaw=old,
                    outline=GREY,
                    style=":",
                    fill=False,
                    **({"fallen": True} if task == "PickBolt" else {"threaded": True}),
                )
        else:
            patches = [Rectangle(lo, *size) for lo in np.unique(edges, axis=0)]
            ax.add_collection(PatchCollection(patches, fc=BLUE, ec="none", alpha=0.36))
            if field == "free":
                half = np.array(g["candidate"]["table_nut_half_range_m"]) * 100
                ax.add_patch(Rectangle(native_xy - half, *(2 * half), fill=False, ec=GREY, lw=1.7))
                native_half = 100 * g["table_nut_native_half_range_m"]
                ax.add_patch(
                    Rectangle(
                        native_xy - native_half,
                        2 * native_half,
                        2 * native_half,
                        fill=False,
                        ec=GREY,
                        ls=":",
                    )
                )
                draw_nut(ax, g, near)
            else:
                rad = (
                    g["candidate"]["bolt_spawn_radius_m" if task == "PickBolt" else "upright_bolt_radius_m"]
                    * 100
                )
                ax.add_patch(Circle(native_xy, rad, fill=False, ec=GREY, lw=1.7))
                if task == "PickBolt":
                    ax.add_patch(
                        Circle(native_xy, 100 * g["bolt_spawn_radius_m"], fill=False, ec=GREY, ls=":")
                    )
                    draw_bolt(ax, g, near, yaw=yaw, fallen=True)
                else:
                    ax.add_patch(
                        Circle(native_xy, g["handoff_radius_m"] * 100, fill=False, ec="#a47751", ls=":")
                    )
                    draw_bolt(ax, g, near)
            ax.scatter(*native_xy, c="#b93433", s=18, zorder=8)
            for text, k in (("near", near), ("far", far)):
                ax.scatter(*k, s=20, fc="white", ec=NAVY, zorder=9)
                if i and (text == "near" or np.linalg.norm(near - far) > 0.01):
                    ax.annotate(text, k, xytext=(5, 4), textcoords="offset points", fontsize=9)
        ax.set_xlabel("world X (cm)")
        ax.set_ylabel("world Y (cm)")
        ax.grid(alpha=0.14)
    minrow = min(records[task]["rows"], key=lambda r: r["table_margin_m"])
    fixed = (
        f"root XY {np.round(anchor,2).tolist()} cm"
        if yaw_plot
        else (
            f"bolt fixed at {point(task,'xy',spec,'near').tolist()} cm"
            if field == "free"
            else (
                f"relative nut offset {(np.array(spec['presets']['near'][3:])/10).tolist()} cm"
                if task == "SeatNut"
                else f"yaw {yaw}°"
            )
        )
    )
    fig.suptitle(f"{task}  ·  {name}", fontsize=16, weight="bold")
    legend = (
        "blue: screened   grey dotted: old yaws   native: full turn"
        if yaw_plot
        else "blue: screened   grey: old explicit   dotted: native / handoff"
    )
    fig.text(
        0.5,
        0.075,
        f"{fixed}   |   {legend}",
        ha="center",
    )
    fig.text(
        0.5,
        0.03,
        f"Smallest measured target-to-table edge in this task: {1000*minrow['table_margin_m']:.2f} mm"
        f" ({minrow['id']}, CPU).",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.12, 1, 0.94))
    fig.savefig(DIR / f"{task}_{field}.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cpu", type=Path)
    args = ap.parse_args()
    models = json.loads((DIR / "model.json").read_text())
    specs = json.loads((ROOT / "tasks/nut_bolt/workspace_cells.json").read_text())["tasks"]
    records = {t: json.loads((args.cpu / f"{t}.json").read_text()) for t in specs}
    for task, field, label in (
        ("PickBolt", "xy", "fallen bolt position"),
        ("PickBolt", "yaw", "fallen bolt heading"),
        ("SeatNut", "xy", "upright bolt axis"),
        ("SeatNut", "free", "free nut position"),
        ("TurnNut", "xy", "engaged bolt axis"),
        ("TurnNut", "yaw", "nut joint start angle"),
    ):
        plot(task, field, label, models, specs, records)
