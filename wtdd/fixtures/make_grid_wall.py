"""Synthetic occupancy grid for wtdd/test_plan_grid.py (item 06, the planner over the grid): one wall and, when a test
asks for one, one blob, planted as points in odometry metres into wtdd/dog/occupancy.py's Grid the way a LiDAR frame
lands there (Grid.update, one call per frame, THRESHOLD frames), tied to the shipped floor plan by CAL. Nothing here has
seen the real dog: the wall is a list of points typed below, no frame, no model.

    python -m wtdd.fixtures.make_grid_wall      writes grid_wall.json next to this file (Grid.save with `cal`, the shape
                                                 POST /dog/grid {save} writes) and prints the wall's map-pixel extent

The tie (CAL, nav.calibration's shape): odometry (0, 0) at yaw 0 is map point (300, 1100) facing heading 0 (+x on
screen), so odometry x runs right along the page and odometry y (the dog's left) runs UP the page (y is down on screen):
  px(x, y) = (300 + PX_PER_M * x, 1100 - PX_PER_M * y),   PX_PER_M = 108.5 (wtdd/dog/nav.py)
The world, in that odometry frame (lattice RES = 0.05 m, the driver's; ORIGIN is the grid's first corner):
  WALL   x = 1.6 m, y 1.0..2.5 m, at z 0.5 (inside lidar.Z_MIN..Z_MAX): a 1.5 m wall at map x ≈ 474, y 829..992, across
         the top of the living room. A route along y = 900 from x 300 to 650 runs straight through it.
  BLOB   a BLOB_M square centred on a map point a test chooses (grid(blob_px=...)), the "new blob" that lands on a route
         after it was planned; blob_frames=1 makes one seen once, which is not a wall at THRESHOLD.
cells_px() is the independent answer for a test's clearance checks: each point snapped to its lattice cell the way
Grid._index snaps (round to the nearest cell), then the cell corner through px(), plain arithmetic, no grid.
The CLI pair, once the planner reads the grid (ui/grid.json is the saved-grid fallback the tool reads with no dog):
  cp wtdd/fixtures/grid_wall.json ui/grid.json && python -m wtdd plan_path from=300,900 to=650,900
(today's straight line crosses the wall; a planner that reads the grid prints a detour, cost_map "grid")."""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

from ..dog import nav, occupancy

HERE = Path(__file__).resolve().parent
OUT = HERE / "grid_wall.json"
RES = 0.05
ORIGIN = (-3.2, -3.2)                                                   # one 128-voxel window's corner, like the fixture frames
CAL = {"odom": [0.0, 0.0, 0.0], "map": [300.0, 1100.0], "heading": 0.0, "at": "fixture: make_grid_wall.py"}
Z = 0.5                                                                  # inside the band; z never matters after that
WALL = {"x": 1.6, "y": (1.0, 2.5)}
BLOB_M = 0.3


def px(x_m: float, y_m: float) -> tuple[float, float]:
    """Odometry metres -> map pixels through CAL, written out (heading 0: forward is +x, left is up the page)."""
    return CAL["map"][0] + nav.PX_PER_M * x_m, CAL["map"][1] - nav.PX_PER_M * y_m


def metres(px_x: float, px_y: float) -> tuple[float, float]:
    """The inverse of px()."""
    return (px_x - CAL["map"][0]) / nav.PX_PER_M, (CAL["map"][1] - px_y) / nav.PX_PER_M


def wall_points() -> np.ndarray:
    ys = np.arange(WALL["y"][0], WALL["y"][1] + RES / 2, RES)
    return np.column_stack([np.full_like(ys, WALL["x"]), ys, np.full_like(ys, Z)])


def blob_points(at_px) -> np.ndarray:
    cx, cy = metres(*at_px)
    h = BLOB_M / 2
    X, Y = np.meshgrid(np.arange(cx - h, cx + h + RES / 2, RES), np.arange(cy - h, cy + h + RES / 2, RES))
    return np.column_stack([X.ravel(), Y.ravel(), np.full(X.size, Z)])


def cells_px(points) -> list[tuple[int, int]]:
    """The map pixel of each point's lattice cell corner: the obstacle pixels a test measures clearance from."""
    out = set()
    for x, y, *_ in np.asarray(points, dtype=float):
        cx = ORIGIN[0] + round((x - ORIGIN[0]) / RES) * RES
        cy = ORIGIN[1] + round((y - ORIGIN[1]) / RES) * RES
        out.add(tuple(int(round(v)) for v in px(cx, cy)))
    return sorted(out)


def wall_px() -> list[tuple[int, int]]:
    return cells_px(wall_points())


def blob_px(at_px) -> list[tuple[int, int]]:
    return cells_px(blob_points(at_px))


def grid(blob_px=None, blob_frames: int = occupancy.THRESHOLD) -> occupancy.Grid:
    """The wall seen THRESHOLD times; with blob_px, the blob in the last blob_frames of those frames."""
    g = occupancy.Grid(RES, ORIGIN, "odom")
    for k in range(occupancy.THRESHOLD):
        pts = wall_points()
        if blob_px is not None and k >= occupancy.THRESHOLD - blob_frames:
            pts = np.vstack([pts, blob_points(blob_px)])
        g.update(pts)
    g.cal = dict(CAL)
    return g


def main() -> int:
    g = grid()
    g.save(OUT)
    back = occupancy.Grid.load(OUT)
    w = wall_px()
    print(f"wrote {OUT.relative_to(HERE.parents[1])}: {back.frames} frames, {len(back.walls())} wall cells at threshold "
          f"{occupancy.THRESHOLD}, cal at map {CAL['map']}; the wall on the map: x {min(x for x, _ in w)}..{max(x for x, _ in w)}, "
          f"y {min(y for _, y in w)}..{max(y for _, y in w)} px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
