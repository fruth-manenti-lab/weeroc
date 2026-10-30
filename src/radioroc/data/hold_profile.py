"""Smooth profile through a hold scan's per-point means, and its maximum."""

from __future__ import annotations

import numpy as np

MIN_POINTS = 5
MAX_DEGREE = 6


def fit_hold_profile(xs, means, stdevs=None, *, samples=400):
    """Fit a polynomial through the mean-vs-hold points and locate its maximum.

    Returns ``{"x": [...], "y": [...], "x_peak": float, "y_peak": float}`` over
    the scanned range, or ``None`` with fewer than ``MIN_POINTS`` distinct points.
    Points are weighted by 1/stdev when every stdev is positive. The polynomial
    is a smooth empirical profile, not a physical pulse-shape model, so the
    peak is only meaningful inside the scanned range (which is all it reports).
    """

    x = np.asarray(xs, dtype=float)
    y = np.asarray(means, dtype=float)
    if len(np.unique(x)) < MIN_POINTS or len(x) != len(y):
        return None
    weights = None
    if stdevs is not None:
        s = np.asarray(stdevs, dtype=float)
        if len(s) == len(x) and np.all(s > 0):
            weights = 1.0 / s
    degree = min(MAX_DEGREE, len(np.unique(x)) - 1)
    centre, half = x.mean(), max((x.max() - x.min()) / 2, 1e-12)
    try:
        coeffs = np.polynomial.polynomial.polyfit((x - centre) / half, y, degree, w=weights)
    except (np.linalg.LinAlgError, ValueError):
        return None
    grid = np.linspace(x.min(), x.max(), samples)
    fitted = np.polynomial.polynomial.polyval((grid - centre) / half, coeffs)
    peak = int(np.argmax(fitted))
    return {"x": grid.tolist(), "y": fitted.tolist(),
            "x_peak": float(grid[peak]), "y_peak": float(fitted[peak])}
