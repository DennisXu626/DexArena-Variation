"""Bounded, warm-started arm IK and conservative collision checks for Office maps."""

import numpy as np

try:
    from numba import njit
except ImportError:

    def njit(func):
        return func


@njit
def transforms(q, home, origins, axes):
    rotations = np.empty((8, 3, 3))
    shifts = np.zeros((8, 3))
    rotations[0] = np.eye(3)
    jac_axes = np.empty((7, 3))
    pivots = np.empty((7, 3))
    for j in range(7):
        axis = axes[j]
        x, y, z = axis
        skew = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
        delta = q[j] - home[j]
        turn = np.eye(3) + np.sin(delta) * skew + (1.0 - np.cos(delta)) * (skew @ skew)
        jac_axes[j] = rotations[j] @ axis
        pivots[j] = rotations[j] @ origins[j] + shifts[j]
        rotations[j + 1] = rotations[j] @ turn
        shifts[j + 1] = pivots[j] - rotations[j + 1] @ origins[j]
    return rotations, shifts, jac_axes, pivots


@njit
def solve(previous, home, origins, axes, limits, tip, palm, goal, offset, tolerance):
    q = previous.copy()
    weight = 0.65
    # The secondary palm target selects an approach orientation while the fingertip
    # remains free to rotate about the palm-to-pad line.
    for iteration in range(70):
        rotations, shifts, directions, pivots = transforms(q, home, origins, axes)
        point = rotations[7] @ tip + shifts[7]
        arm = rotations[7] @ (palm - tip)
        error = np.empty(6)
        error[:3] = goal - point
        error[3:] = weight * (offset - arm)
        if np.linalg.norm(error[:3]) < tolerance and np.linalg.norm(error[3:]) < 0.004:
            break
        jac = np.empty((6, 7))
        for j in range(7):
            jac[:3, j] = np.cross(directions[j], point - pivots[j])
            jac[3:, j] = weight * np.cross(directions[j], arm)
        step = jac.T @ np.linalg.solve(jac @ jac.T + 0.00012 * np.eye(6), error)
        factor = max(1.0, np.max(np.abs(step)) / 0.15)
        old = q.copy()
        q = np.minimum(np.maximum(q + step / factor, limits[:, 0] + 0.002), limits[:, 1] - 0.002)
        if np.max(np.abs(q - old)) < 0.00001:
            break
    rotations, shifts, _, _ = transforms(q, home, origins, axes)
    error_m = np.linalg.norm(rotations[7] @ tip + shifts[7] - goal)
    return q, error_m


@njit
def margin(q, home, origins, axes, corners, links, centers, bases, sizes):
    rotations, shifts, _, _ = transforms(q, home, origins, axes)
    clearance = 1.0
    for group in range(len(links)):
        j = links[group]
        vertices = corners[group] @ rotations[j].T + shifts[j]
        for k in range(len(centers)):
            local = (vertices - centers[k]) @ bases[k]
            distance = -100.0
            for axis in range(3):
                low = np.min(local[:, axis])
                high = np.max(local[:, axis])
                distance = max(distance, max(low - sizes[k, axis], -sizes[k, axis] - high))
            clearance = min(clearance, distance)
    return clearance


@njit
def trace(home, origins, axes, limits, tip, palm, corners, links, goals, offsets, centers, bases, sizes):
    q = home.copy()
    solutions = np.empty((len(goals), 7))
    min_clearance, max_error, max_jump = 1.0, 0.0, 0.0
    for i in range(len(goals)):
        new_q, error = solve(q, home, origins, axes, limits, tip, palm, goals[i], offsets[i], 0.0008)
        max_error = max(max_error, error)
        jump = np.max(np.abs(new_q - q))
        max_jump = max(max_jump, jump)
        if error > 0.003:
            return 1, i, max_error, min_clearance, max_jump, solutions
        if jump > 0.70:
            return 2, i, max_error, min_clearance, max_jump, solutions
        # Bound the spacing of collision observations in joint space.
        segments = max(1, int(np.ceil(jump / 0.12)))
        for m in range(1, segments + 1):
            intermediate = q + (new_q - q) * (m / segments)
            c = margin(intermediate, home, origins, axes, corners, links, centers[i], bases[i], sizes[i])
            min_clearance = min(min_clearance, c)
            if c < 0.001:
                return 3, i, max_error, min_clearance, max_jump, solutions
        solutions[i] = new_q
        q = new_q
    return 0, len(goals) - 1, max_error, min_clearance, max_jump, solutions
