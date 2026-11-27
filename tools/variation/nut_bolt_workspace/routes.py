"""Task-space paths common to the offline screen and real short-action probe."""

import numpy as np


def route(task, params, yaw, angle, model):
    geometry = model["geometry"]
    primary = np.asarray(params[:2], float) / 1000
    span = np.diff(model["chain"][-1], axis=0)[0]
    width = np.linalg.norm(span) / 2
    bolt_h = model["bolt_height"]
    axis = np.array([np.cos(np.deg2rad(yaw)), np.sin(np.deg2rad(yaw)), 0.0])
    if task == "PickBolt":
        hand_axis = np.array([-axis[1], axis[0], 0.0])
        grip = (
            np.r_[primary, geometry["bolt_head_circumradius_m"] * np.cos(np.pi / 6) + 0.001] + 0.01 * axis
        )
        goal = np.r_[geometry["handoff_xy_m"], bolt_h / 2 + 0.01]
        obstacle = np.zeros(4)
    else:
        hand_axis = np.array([np.cos(angle), np.sin(angle), 0.0])
        if task == "SeatNut":
            grip = np.r_[primary + np.array(params[2:]) / 1000, geometry["nut_half_height_m"] + 0.001]
            goal = np.r_[primary, geometry["platform_support_height_m"] + geometry["nut_half_height_m"]]
        else:
            grip = np.r_[primary, geometry["platform_support_height_m"] + geometry["nut_half_height_m"]]
        obstacle = np.r_[primary, bolt_h + model["tip_height"], geometry["platform_radius_m"]]
    if np.dot(span, hand_axis) < 0:
        hand_axis = -hand_axis
    if task == "PickBolt":
        approach_side = np.array([np.cos(angle), np.sin(angle), 0.0])
    else:
        approach_side = np.array([-hand_axis[1], hand_axis[0], 0.0])
    # Open-hand tip centres straddle the grasp zone. Actual closing, load and
    # possible slips are measured separately by the native action probe.
    grip[2] += 0.012
    points = [(grip + 0.055 * np.array([0, 0, 1]) + 0.025 * approach_side, hand_axis), (grip, hand_axis)]
    if task == "TurnNut":
        # Each 60 degree stroke leaves a symmetry-equivalent face. Release,
        # lift and return the open hand before the next stroke.
        for stroke in range(3):
            for deg in (15, 30, 45, 60):
                a = np.deg2rad(deg)
                end = np.array(
                    [
                        hand_axis[0] * np.cos(a) - hand_axis[1] * np.sin(a),
                        hand_axis[0] * np.sin(a) + hand_axis[1] * np.cos(a),
                        0.0,
                    ]
                )
                points.append((grip, end))
            if stroke < 2:
                points.extend(
                    [(grip + [0, 0, 0.055], end), (grip + [0, 0, 0.055], hand_axis), (grip, hand_axis)]
                )
    else:
        high = max(0.145, grip[2] + 0.07)
        lift = np.r_[grip[:2], high]
        above = np.r_[goal[:2], high]
        points.append((lift, hand_axis))
        for fraction in (1 / 3, 2 / 3, 1.0):
            points.append((lift + fraction * (above - lift), hand_axis))
        points.extend([(goal + [0, 0, 0.012], hand_axis), (above, hand_axis)])
    goals = np.array([p + np.stack((-axis, axis)) * width for p, axis in points])
    shaft = np.empty((0, 3))
    if task == "PickBolt":
        shaft = np.array(
            [
                np.cos(a) * axis + np.array([0, 0, np.sin(a)])
                for a in np.deg2rad([0, 0, 0, 30, 60, 90, 90, 90])
            ]
        )
    return goals, shaft, obstacle
