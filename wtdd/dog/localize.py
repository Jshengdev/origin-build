"""Scan-to-map re-correction: every LiDAR window the dog streams is aligned to the occupancy grid it has drawn so far
(wtdd/dog/occupancy.py), and the small offset that aligns it corrects where the dog believes it is.

Run. DogSession._on_frame (wtdd/dog/session.py) calls match() on every window after the first, before the window is
drawn: the window's band cells, moved through the correction the session holds, against the grid. A match at or above
MIN_SCORE inside the cap is applied (one `pose.corrected` row, the correction composed, the window drawn through it);
past the cap it is rejected (a `pose.corrected` row with ok false naming the cap; the window is not drawn and the
correction is kept); below MIN_SCORE the window is unmatched (no row: a WARN line and a counter on GET /dog/lidar; the
window is drawn through the correction held, so the map grows into rooms it has not seen). Nothing is written to the
ledger here: row() builds the row, the session appends it. Offline: `python -m unittest wtdd.dog.test_localize`.

How. Correlative scan matching on the grid's own lattice, numpy only. The window's cells are turned by each dtheta in
0, +STEP_DEG, -STEP_DEG, ... up to +-SEARCH_DEG about the pivot (the dog's corrected position, or the window's centre
without a state stream), snapped to the grid's cells (occupancy.Grid._index's rint), and every whole-cell shift within
+-SEARCH_M is scored at once by one gather: the fraction of the window's cells that land on a grid cell seen at least
MATCH_THRESHOLD times. The best score wins with a strict comparison, visited zero first and outward (angles, then shifts
by |sx| + |sy|), so a tie goes to the smallest offset: a window that fits as well where it is stays put, and a wall
along x never moves the pose along x. The winning (dx, dy, dtheta) is that window's delta: turn by dtheta about the
pivot, then move by (dx, dy) (delta_about). The score is an overlap fraction used as a gate, not a map accuracy.

A correction is a rigid 2D transform (tx, ty, theta) in the odometry frame, p' = R(theta) p + t. The session holds the
composition of every applied delta (compose) and applies it to the odometry pose before nav.to_map (apply_pose) and to
each new window before it is matched and drawn (apply_points). The grid is therefore drawn in the corrected frame; the
drag (session.calibrate) ties that corrected pose to the map and keeps the correction; clearing the grid resets it.

UNVERIFIED on the real dog (the first live run tunes them from the score, score0 and latency_ms columns of the
pose.corrected rows): every constant below; the frame convention inherited from lidar.py and occupancy.py (windows
absolute in the odometry frame of LF_SPORT_MOD_STATE, so the correction applies to that pose; if the windows turn out
to be in the utlidar frame the correction belongs to that pose source instead); the per-window cost on the driver's
dispatcher (measured on every row; BUDGET_MS warns)."""
from __future__ import annotations
import math
import time
from typing import Any

import numpy as np

from .. import config
from . import lidar

SEARCH_M = 0.40          # +- metres searched in x and y, in whole grid cells (UNVERIFIED: tune on the dog)
SEARCH_DEG = 8.0         # +- degrees searched (UNVERIFIED)
STEP_DEG = 1.0           # the angle step (UNVERIFIED)
CAP_M = 0.25             # a window's correction longer than this is rejected, not applied (UNVERIFIED; inside SEARCH_M so it can fire)
CAP_DEG = 5.0            # likewise for the turn (UNVERIFIED; inside SEARCH_DEG)
MIN_SCORE = 0.5          # below this fraction of the window's cells on occupied grid cells the window is unmatched (UNVERIFIED)
MIN_CELLS = 30           # fewer band cells than this are not matched (UNVERIFIED)
MAX_MATCH_POINTS = 800   # the window's cells are thinned to an even-stride subset of at most this many, bounding the cost
MATCH_THRESHOLD = 2      # a grid cell counts as occupied for matching when seen in at least this many frames (UNVERIFIED)
BUDGET_MS = 40           # a match slower than this is a WARN: it runs inline on the driver's dispatcher (UNVERIFIED)
IDENTITY = (0.0, 0.0, 0.0)


# ---- the transform algebra: a correction (tx, ty, theta) maps p to R(theta) p + t
def apply_points(c, xy) -> np.ndarray:
    p = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    co, si = math.cos(c[2]), math.sin(c[2])
    return np.column_stack([co * p[:, 0] - si * p[:, 1] + c[0], si * p[:, 0] + co * p[:, 1] + c[1]])


def apply_pose(c, x: float, y: float, yaw: float) -> tuple[float, float, float]:
    (px, py), = apply_points(c, [[float(x), float(y)]])
    return float(px), float(py), float(yaw) + c[2]


def compose(a, b) -> tuple[float, float, float]:
    """a, then b."""
    (tx, ty), = apply_points((0.0, 0.0, b[2]), [a[:2]])
    return float(tx + b[0]), float(ty + b[1]), a[2] + b[2]


def delta_about(pivot, dx: float, dy: float, dtheta: float) -> tuple[float, float, float]:
    """Turn by dtheta about pivot, then move by (dx, dy): one window's correction."""
    (rx, ry), = apply_points((0.0, 0.0, dtheta), [pivot[:2]])
    return float(pivot[0] - rx + dx), float(pivot[1] - ry + dy), float(dtheta)


def describe(c) -> dict[str, float]:
    return {"tx": round(c[0], 4), "ty": round(c[1], 4), "theta": round(c[2], 5), "theta_deg": round(math.degrees(c[2]), 2)}


# ---- the match
def band(points) -> np.ndarray:
    """(N, 3) voxels -> the unique (x, y) inside lidar.Z_MIN..Z_MAX (the band the grid keeps). No log line: per window."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return np.unique(p[(p[:, 2] >= lidar.Z_MIN) & (p[:, 2] <= lidar.Z_MAX)][:, :2], axis=0)


def same_lattice(grid, d: dict) -> None:
    """occupancy.Grid.update_frame's two refusals, run before a window is matched: another resolution or another
    frame_id is another lattice or another world."""
    if float(d["resolution"]) != grid.resolution:
        raise ValueError(f"frame resolution {d['resolution']} m is not the grid's {grid.resolution} m: refused")
    if grid.frame_id is not None and d["frame"] != grid.frame_id:
        raise ValueError(f"frame_id {d['frame']!r} is not the grid's {grid.frame_id!r}: another frame, refused")


def match(grid, xy, pivot, *, search_m: float = SEARCH_M, search_deg: float = SEARCH_DEG, step_deg: float = STEP_DEG,
          threshold: int = MATCH_THRESHOLD) -> dict[str, Any]:
    """The best (dx, dy, dtheta) aligning the window's cells xy (N, 2 odometry metres) to the grid's occupied cells (see
    the module docstring). Returns {dx, dy (m), dtheta (rad), dtheta_deg, score, score0 (at zero offset), n (cells
    scored), candidates, ms}. Fewer than MIN_CELLS cells: ValueError."""
    t0 = time.perf_counter()
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    if len(xy) < MIN_CELLS:
        raise ValueError(f"window has {len(xy)} cells, fewer than MIN_CELLS={MIN_CELLS}: not matched")
    if len(xy) > MAX_MATCH_POINTS:
        xy = xy[::-(-len(xy) // MAX_MATCH_POINTS)]
    n, res = len(xy), grid.resolution
    s = int(round(search_m / res))
    h, w = grid.counts.shape
    occ = np.zeros((h + 4 * s, w + 4 * s), dtype=bool)   # padded by 2s: a shifted index never leaves the array, never wraps
    occ[2 * s:2 * s + h, 2 * s:2 * s + w] = grid.counts >= threshold
    r = np.arange(-s, s + 1)
    sx, sy = (a.ravel() for a in np.meshgrid(r, r))
    order = np.argsort(np.abs(sx) + np.abs(sy), kind="stable")   # zero first: ties go to the smallest shift
    sx, sy = sx[order], sy[order]
    k = int(round(search_deg / step_deg))
    angles = [0.0] + [sign * i * step_deg for i in range(1, k + 1) for sign in (1, -1)]
    best, hits0 = (-1, 0.0, 0, 0), 0
    for deg in angles:
        p = apply_points(delta_about(pivot, 0.0, 0.0, math.radians(deg)), xy) if deg else xy
        ix = np.rint((p[:, 0] - grid.origin[0]) / res).astype(np.int64) + 2 * s
        iy = np.rint((p[:, 1] - grid.origin[1]) / res).astype(np.int64) + 2 * s
        ok = (ix >= s) & (ix < w + 3 * s) & (iy >= s) & (iy < h + 3 * s)   # the rest cannot reach the grid at any shift: 0
        hits = occ[iy[ok][None, :] + sy[:, None], ix[ok][None, :] + sx[:, None]].sum(axis=1)
        if deg == 0.0:
            hits0 = int(hits[0])
        i = int(np.argmax(hits))   # the first maximum: the smallest shift
        if hits[i] > best[0]:
            best = (int(hits[i]), deg, int(sx[i]), int(sy[i]))
    hits, deg, bx, by = best
    return {"dx": bx * res, "dy": by * res, "dtheta": math.radians(deg), "dtheta_deg": deg, "score": hits / n,
            "score0": hits0 / n, "n": n, "candidates": len(angles) * len(sx), "ms": round((time.perf_counter() - t0) * 1000, 1)}


def over_cap(m: dict, cap_m: float = CAP_M, cap_deg: float = CAP_DEG) -> str | None:
    """None when the offset is plausible for one window, else why not."""
    d, deg = math.hypot(m["dx"], m["dy"]), abs(math.degrees(m["dtheta"]))
    if d > cap_m + 1e-9:
        return f"over the cap: |dx, dy| {d:.2f} m > CAP_M {cap_m} m"
    if deg > cap_deg + 1e-9:
        return f"over the cap: |dtheta| {deg:.1f} deg > CAP_DEG {cap_deg} deg"
    return None


def shift_id() -> str:
    return config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")


def row(m: dict, pivot: str, before: dict, after: dict, why: str | None = None) -> dict[str, Any]:
    """The pose.corrected row for ledger.append: ok when applied, ok false with the cap named when rejected;
    before/after are {corr, map, grid_frames}; latency_ms is the match's own time."""
    return {"step": "pose.corrected", "agent": "dog", "tool": "pose.corrected", "app": "map",
            "args": {"dx": round(m["dx"], 4), "dy": round(m["dy"], 4), "dtheta": round(m["dtheta"], 5), "dtheta_deg": m["dtheta_deg"],
                     "score": round(m["score"], 3), "score0": round(m["score0"], 3), "n": m["n"], "candidates": m["candidates"],
                     "pivot": pivot, "cap_m": CAP_M, "cap_deg": CAP_DEG, "shift_id": shift_id()},
            "state_before": before, "state_after": after, "ok": why is None, "response_or_error": why, "latency_ms": round(m["ms"])}
