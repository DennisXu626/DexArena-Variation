"""Explicit short-task reset coordinates, in metres and degrees."""
import numpy as np


def requested_layout(options, env_idx, task):
    if "position_layout" not in options:
        return None
    rows = []
    for index in env_idx.tolist():
        request = options["position_layout"][str(index)]
        if task == "PourBeads":
            xy = np.asarray(request["bowl_xy_m"], dtype=float)
            if (set(request) != {"bowl_xy_m"} or xy.shape != (2,)
                    or not np.isfinite(xy).all() or np.linalg.norm(xy - [-.20, -.50]) > .0300000001):
                raise ValueError(f"Invalid bowl position for environment {index}")
            rows.append(xy)
            continue
        allowed = {"cabinet_xy_m", "yaw_deg"}
        if task == "PickBottle":
            allowed.add("shelf_xy_m")
        xy = np.asarray(request.get("cabinet_xy_m", [.14, .12]), dtype=float)
        yaw = float(request.get("yaw_deg", 15))
        if (set(request) - allowed or xy.shape != (2,) or not np.isfinite(xy).all()
                or np.any(np.abs(xy - [.14, .12]) > .0500000001) or yaw not in (10, 15, 20)):
            raise ValueError(f"Invalid cabinet pose for environment {index}")
        shelf = np.asarray(request.get("shelf_xy_m", [-.21, -.005]), dtype=float)
        if (shelf.shape != (2,) or not np.isfinite(shelf).all()
                or not (-.2204 <= shelf[0] <= -.18 and -.035 <= shelf[1] <= .025)):
            raise ValueError(f"Shelf position outside approved bounds for environment {index}: {shelf}")
        rows.append([*xy, yaw, *shelf])
    return np.asarray(rows, dtype=np.float32)
