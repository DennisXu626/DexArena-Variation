"""Audit independent replay, yaw frequencies and held-out paths; draw each Office degree of freedom."""

from collections import Counter
import importlib.util
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon
import numpy as np

from build import EVIDENCE, FRAMES, MAPS, ROUTES, OfficeScreen, zrot


# Offline checks run without loading Gym or the simulator; exercise the shipped sampler verbatim.
def read_module(name):
    source = MAPS.parent / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = read_module("position_workspace")
legacy = read_module("position_layout")


def plot(data, table):
    origin = np.asarray(data["origin"])[:2]
    task = {"laptop": "OpenLaptop", "keyboard": "TypeKeys", "mouse": "ClickMouse"}[data["device"]]
    observation_path = EVIDENCE / "cpu" / task / "report.json"
    observed = (
        json.loads(observation_path.read_text(encoding="utf-8"))["points"]
        if observation_path.exists()
        else []
    )
    yaw_list = table["yaw_deg"]
    target = np.asarray(next(iter(data["controls"]["targets_xyz_m"].values())))[:2]
    fig, axes = plt.subplots(
        1, 4, figsize=(14, 5), layout="constrained", gridspec_kw={"width_ratios": [1.25, 1, 1, 1]}
    )
    for i, ax in enumerate(axes):
        low, high = np.asarray(data["table"])[:, :2] * 100
        ax.add_patch(Rectangle(low, *(high - low), facecolor="#f5e9cd", edgecolor="#24201b"))
        angles = yaw_list if i == 0 else [yaw_list[i - 1]]
        for yaw in angles:
            for x, y, step, _ in table["cells"][str(yaw)]:
                ax.add_patch(
                    Rectangle(
                        (x * 100, y * 100),
                        step * 100,
                        step * 100,
                        facecolor="#488ab4",
                        edgecolor="none",
                        alpha=0.22 if i == 0 else 0.7,
                    )
                )
        lower, upper = np.asarray(legacy.XY_BOUNDS_M[data["device"]]) * 100
        ax.add_patch(
            Rectangle(
                origin * 100 + lower,
                *(upper - lower),
                facecolor="none",
                edgecolor="#51525b",
                lw=1.3,
                ls="--",
            )
        )
        ax.add_patch(
            Rectangle(origin * 100 - 2, 4, 4, facecolor="none", edgecolor="#7d705c", ls=":", lw=1)
        )
        yaw = 0 if i == 0 else angles[0]
        points = (np.asarray(data["footprint"]) - origin) @ zrot(yaw)[:2, :2].T + origin
        ax.add_patch(Polygon(points * 100, closed=True, fill=False, ec="#334344"))
        if i == 0:
            ax.set_xlim(low[0] - 3, high[0] + 3)
            ax.set_ylim(low[1] - 3, high[1] + 3)
        else:
            xy = np.array([cell[:2] for cell in table["cells"][str(yaw)]])
            ax.set_xlim(
                min(xy[:, 0].min() - 0.02, points[:, 0].min() - 0.01) * 100,
                max(xy[:, 0].max() + 0.06, points[:, 0].max() + 0.01) * 100,
            )
            ax.set_ylim(
                min(xy[:, 1].min() - 0.02, points[:, 1].min() - 0.01) * 100,
                max(xy[:, 1].max() + 0.06, points[:, 1].max() + 0.01) * 100,
            )
        ax.scatter(*(origin * 100), color="#bc4026", s=20, zorder=5)
        if i == 0 or yaw == 0:
            for name, (x, y, _) in table["presets"].items():
                ax.plot(x * 100, y * 100, "o", mec="#21262a", mfc="white", ms=3)
                if i > 0 and yaw == 0:
                    ax.annotate(
                        name, (100 * x, 100 * y), xytext=(3, 3), textcoords="offset points", size=7
                    )
        ax.set_aspect("equal")
        ax.set_xlabel("world X (cm)")
        ax.set_ylabel("world Y (cm)")
        title = "Table overview" if i == 0 else f"Root XY at {yaw:+}°"
        eligible = [row for row in observed if row.get("yaw_offset_deg") == yaw]
        if i and eligible:
            limiting = min(eligible, key=lambda row: row["footprint_margin_m"])
            ax.plot(*np.array(limiting["pose"][:2]) * 100, marker="x", color="#64233e", ms=6)
            title += f'\n{limiting["id"]}: {1000 * limiting["footprint_margin_m"]:.1f} mm to table edge'
        ax.set_title(title, fontsize=10)
    fig.suptitle(
        data["device"]
        + " • root XY   |   blue: screened   dashed: old explicit   dotted: native   red: nominal"
    )
    fig.savefig(EVIDENCE / (data["device"] + "_xy.png"), dpi=155)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9, 5), layout="constrained")
    for i, ax in enumerate(axes):
        ax.add_patch(Rectangle(low, *(high - low), facecolor="#f5e9cd", edgecolor="#24201b"))
        points_all = []
        for yaw, color in zip(yaw_list, ("#336897", "#8c5737", "#507849")):
            rot = zrot(yaw)[:2, :2]
            points = (np.asarray(data["footprint"]) - origin) @ rot.T + origin
            target_xy = (target - origin) @ rot.T + origin
            ax.add_patch(Polygon(points * 100, closed=True, fill=False, ec=color, lw=1))
            ax.plot(*target_xy * 100, "o", color=color, label=f"{yaw:+}°", ms=5)
            ax.plot(*np.vstack([origin, target_xy]).T * 100, color=color, lw=0.8)
            points_all.extend(points)
        ax.plot(*origin * 100, "o", color="#bc4026", ms=4)
        if i == 0:
            ax.set_xlim(low[0] - 3, high[0] + 3)
            ax.set_ylim(low[1] - 3, high[1] + 3)
        else:
            p = np.array(points_all) * 100
            ax.set_xlim(p[:, 0].min() - 3, p[:, 0].max() + 3)
            ax.set_ylim(p[:, 1].min() - 3, p[:, 1].max() + 3)
        ax.set_aspect("equal")
        ax.set_xlabel("world X (cm)")
        ax.set_ylabel("world Y (cm)")
        ax.set_title(("Table overview", "Device footprint and tracked contact")[i])
    axes[1].legend()
    fig.suptitle(data["device"] + " • root yaw at nominal XY")
    fig.savefig(EVIDENCE / (data["device"] + "_yaw.png"), dpi=155)
    plt.close(fig)


def audit(kind):
    frame = json.loads((FRAMES / (kind + ".json")).read_text(encoding="utf-8"))
    workspace = runtime.OfficeWorkspace(frame["device"], 2)
    model = OfficeScreen(frame)
    table = workspace.table
    counts = Counter()
    sampled = []
    for n in range(8192):
        xy, yaw = workspace.draw(43, 1, n)
        assert (xy, yaw) == workspace.draw(43, 1, n)
        cell = runtime.cell_at(table, xy, yaw)
        assert cell is not None
        counts[(yaw, cell[0], cell[1], cell[2])] += 1
        sampled.append((yaw, xy))
    distribution = {}
    holdout = []
    neighbours = []
    rng = np.random.default_rng(434343)
    for yaw in table["yaw_deg"]:
        cells = table["cells"][str(yaw)]
        area = sum(c[2] ** 2 for c in cells)
        yy = sum(c for (a, *_), c in counts.items() if a == yaw)
        residuals = []
        for x, y, step, routes in cells:
            weighted = step**2 / area
            obs = counts[yaw, x, y, step]
            residuals.append((obs - yy * weighted) / np.sqrt(yy * weighted * (1 - weighted)))
        distribution[yaw] = dict(
            draws=yy,
            cells=len(cells),
            area_cm2=round(area * 1e4, 2),
            worst_cell_standardized_residual=float(np.max(np.abs(residuals))),
        )
        assert abs(yy - 8192 / len(table["yaw_deg"])) < 6 * np.sqrt(8192 * (1 / 3) * (2 / 3))
        for axis, side in ((0, -1), (0, 1), (1, -1), (1, 1)):
            cell = max(cells, key=lambda c: side * (c[axis] + (c[2] if side > 0 else 0.0)))
            edge = np.asarray(cell[:2]) + cell[2] / 2
            edge[axis] = cell[axis] + (cell[2] if side > 0 else 0.0)
            outside = edge.copy()
            outside[axis] += side * 0.02
            assert runtime.cell_at(table, outside, yaw) is None
            tested = {
                route: list(model.evaluate(outside, yaw, route, 45.0)[:5]) for route in ROUTES[kind]
            }
            neighbours.append(
                dict(
                    axis=axis,
                    side=side,
                    yaw_deg=yaw,
                    edge=edge.tolist(),
                    outside=outside.tolist(),
                    results=tested,
                )
            )
        for trial in range(24):
            x, y, step, routes = cells[rng.integers(len(cells))]
            xy = np.array([x, y]) + step * rng.random(2)
            angle = rng.uniform(40.0, 50.0) if kind == "OpenLaptop" else 0.0
            codes = [model.evaluate(xy, yaw, r, angle)[:5] for r in routes]
            holdout.append(
                dict(
                    xy=xy.tolist(),
                    yaw=yaw,
                    angle=angle,
                    results={r: list(v) for r, v in zip(routes, codes)},
                )
            )
    passed = sum(any(v[0] == 0 for v in p["results"].values()) for p in holdout)
    report = dict(
        replayed=len(sampled),
        distribution=distribution,
        independent_paths=len(holdout),
        passed=passed,
        holdout=holdout,
        neighbouring_paths=neighbours,
    )
    (EVIDENCE / (kind + "_audit.json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    plot(frame, table)
    print(kind, "independent", passed, "/", len(holdout), flush=True)


if __name__ == "__main__":
    for task in ROUTES:
        audit(task)
