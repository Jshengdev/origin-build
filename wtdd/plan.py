"""A route between two points on the floor plan: A* (python-pathfinding, pure Python) on a lattice of CELL px over the
map's viewBox. Returns the corners of the lattice path in map pixels, ready to be the map's `path`.

The cost map (cost_map()), one of two, named on the plan.route row as args.cost_map:
  grid   the occupancy grid the dog's LiDAR accumulates (wtdd/dog/occupancy.py, odometry metres), when there is one AND
         a calibration ties it to the map: its walls (cells seen >= threshold frames) projected into map pixels through
         that calibration (occupancy.to_map_px), each landing lattice cell blocked; the drawn rooms are not consulted.
  rooms  the fallback when there is no grid or no calibration: walkable where a cell centre is inside any room (limit,
         stated: ui/house.svg draws rooms as rectangles with no walls or doors between them, so a route can cross a
         shared wall). One WARN line says which and why; the row carries args.why.
On both, no-go zones (map zones with nogo: true, wtdd/nogo.py, 04's schema; nogo.py is 04's file byte for byte until
04 merges) are blocked before the same HALF_WIDTH inflation, so the dog's body and not only the route's line stays
out, and args.nogo names them; a malformed zone fails the row instead of being planned through. Every blocked cell
(wall or zone) grows by HALF_WIDTH cells, the square the rooms' erosion already used.

replan(p, path, i, grid, cal): the dog at p was about to drive to path[i], which occupied() now says sits in an
inflated wall (a blob the LiDAR saw after the route was taught): a detour from p to the first later waypoint that is
not occupied, on the grid cost map, one plan.replanned row (never a plan.route row). The follower
(wtdd/dog/session.py _follow) calls it per waypoint. occupied() and the cost map share one lattice and one inflation,
so a waypoint the planner returns is never occupied to the follower. The route's end occupied fails loud (ValueError,
the row ok false): the planner never picks another goal.

    python -m wtdd plan_path from=448,455 to=436,586           the waypoints, nothing written
    python -m wtdd plan_path from=448,455 to=436,586 save=true  also written as the map's path (stops cleared)
    cp wtdd/fixtures/grid_wall.json ui/grid.json && python -m wtdd plan_path from=300,900 to=650,900
                                                                 a detour around the fixture's wall, cost_map grid
                                                                 (the saved-grid DEMO_CACHE, row cached; rm ui/grid.json after)
The zone fixture (wtdd/fixtures/map_nogo.json) is exercised by wtdd/test_plan_grid.py through plan.MAP patched in the
test; this branch has no WTDD_MAP (04's) to point the CLI at it.

Measured on the fixtures (this Mac, 2026-09-26, median of 10): cost_map() on the grid 0.8 ms, on the rooms 85 ms;
occupied() 0.2 ms; plan() around the wall on the grid 12 ms end to end, row included (on the rooms 99 ms); replan()
around a blob 11 ms. The follower runs both on the session's loop between two waypoints.

Limits, stated: unknown floor (never seen by the LiDAR) is walkable on the grid, which knows only occupied cells; the
lattice is CELL px (about 9 cm), so a wall thinner than a cell blocks the whole cell; wall cells off the viewBox are
dropped (WARN); field.check_path's "outside every room" rule is untouched, so a grid-planned route saved as the map's
path with a point outside the drawn rooms is still refused at POST /map, POST /dog/follow and field.walk (loud, named);
the follower's own detour never passes through check_path. UNVERIFIED on the dog: the grid cost map and replan() have
run on synthetic grids only (wtdd/fixtures/make_grid_wall.py).
"""
from __future__ import annotations
import contextlib
import json
import math
import time
from typing import Any

import numpy as np

from . import config
from . import nogo
from .config import ROOT
from .field import MAP, inside
from .ledger import log, step

CELL = 10            # px per grid cell, about 9 cm
HALF_WIDTH = 4       # cells the walkable area shrinks by (the dog is about 0.35 m wide)
W, H = 1060, 1540    # the map's viewBox


def grid(rooms: list[dict[str, Any]], zones: list[dict[str, Any]] = ()):
    """0 = blocked: outside every room or inside a no-go zone, then eroded by HALF_WIDTH cells; 1 = walkable."""
    cols, rows = W // CELL, H // CELL
    free = [[1 if any(inside(q, R["poly"]) for R in rooms) and not any(inside(q, Z["poly"]) for Z in zones) else 0
             for c in range(cols) for q in [(c * CELL + CELL / 2, r * CELL + CELL / 2)]] for r in range(rows)]
    walk = [[1 if all(0 <= r + dr < rows and 0 <= c + dc < cols and free[r + dr][c + dc] for dr in range(-HALF_WIDTH, HALF_WIDTH + 1) for dc in range(-HALF_WIDTH, HALF_WIDTH + 1)) else 0 for c in range(cols)] for r in range(rows)]
    return walk


def walls_px(g, cal: dict, threshold: int | None = None, lock=None) -> np.ndarray:
    """(M, 2) int map pixels: the grid's wall cells (occupancy.walls, cell corners in odometry metres) through cal.
    `lock` (the session's _grid_lock) is held only around the read, never across an await."""
    from .dog import occupancy   # here, not at the top: occupancy imports lidar, which imports the WebRTC driver
    with lock if lock is not None else contextlib.nullcontext():
        w = g.walls(occupancy.THRESHOLD if threshold is None else threshold)
    return occupancy.to_map_px(w, cal)


def _cells(px: np.ndarray) -> np.ndarray:
    """bool [rows, cols]: the lattice cells the map pixels land in; pixels off the viewBox are dropped, counted, WARNed."""
    m = np.zeros((H // CELL, W // CELL), dtype=bool)
    on = (px[:, 0] >= 0) & (px[:, 0] < W) & (px[:, 1] >= 0) & (px[:, 1] < H)
    if (off := int((~on).sum())):
        log("plan", "WARN wall cells off the map, not in the cost map", off=off, of=len(px))
    m[px[on, 1] // CELL, px[on, 0] // CELL] = True
    return m


def _zone_cells(zs: list[dict[str, Any]]) -> np.ndarray:
    """bool [rows, cols]: cells whose centre is inside a no-go zone (grid()'s test, over each zone's bounding box)."""
    m = np.zeros((H // CELL, W // CELL), dtype=bool)
    for z in zs:
        xs, ys = [q[0] for q in z["poly"]], [q[1] for q in z["poly"]]
        for r in range(max(0, int(min(ys)) // CELL), min(H // CELL, int(max(ys)) // CELL + 1)):
            for c in range(max(0, int(min(xs)) // CELL), min(W // CELL, int(max(xs)) // CELL + 1)):
                m[r, c] |= inside((c * CELL + CELL / 2, r * CELL + CELL / 2), z["poly"])
    return m


def _inflate(m: np.ndarray, k: int = HALF_WIDTH) -> np.ndarray:
    """Every True cell grown by k cells in every direction (a (2k+1)^2 square, like grid()'s erosion); cells past the
    lattice's edge are not walls."""
    rows, cols = m.shape
    out = m.copy()
    for dr in range(-k, k + 1):
        for dc in range(-k, k + 1):
            out[max(dr, 0):rows + min(dr, 0), max(dc, 0):cols + min(dc, 0)] |= m[max(-dr, 0):rows + min(-dr, 0), max(-dc, 0):cols + min(-dc, 0)]
    return out


def _at(m, p) -> bool:
    """The lattice cell under map point p (a bool array or a 0/1 matrix); off the viewBox is False."""
    r, c = int(p[1]) // CELL, int(p[0]) // CELL
    return 0 <= r < H // CELL and 0 <= c < W // CELL and bool(m[r][c])


def cost_map(m: dict[str, Any], g=None, cal: dict | None = None, threshold: int | None = None, lock=None):
    """(matrix: 0 blocked / 1 walkable [rows][cols], info for the row, the wall-only inflated mask or None on rooms).
    nogo.zones(m) raises on a malformed zone: the caller's row fails, 04's rule."""
    zs = nogo.zones(m)
    info: dict[str, Any] = {"nogo": [z["name"] for z in zs]}
    if g is None or cal is None:
        why = ("no grid: none given (no LiDAR frame this session and no ui/grid.json, or plan_path grid=false)" if g is None
               else "not calibrated: the grid is in odometry metres with no tie to the map (POST /dog/calibrate)")
        log("plan", f"WARN cost map is the drawn rooms: {why}", nogo=len(zs))
        return grid(m["rooms"], zs), {"cost_map": "rooms", "why": why, "threshold": None, "walls": 0, **info}, None
    if threshold is None:
        from .dog.occupancy import THRESHOLD as threshold   # occupancy is loaded already: `g` is one of its grids
    wall = _cells(walls_px(g, cal, threshold, lock))
    n = int(wall.sum())
    if n == 0:
        log("plan", f"WARN cost map is the grid with 0 wall cells at threshold {threshold} on the map: open floor and the zones only",
            frames=getattr(g, "frames", None))
    blocked = _inflate(wall | _zone_cells(zs))
    return (~blocked).astype(np.uint8).tolist(), {"cost_map": "grid", "threshold": threshold, "walls": n, **info}, _inflate(wall)


def occupied(p, g, cal: dict | None, threshold: int | None = None, lock=None) -> bool:
    """True when map point p sits in a wall cell of the grid or within HALF_WIDTH cells of one, on cost_map()'s lattice
    and inflation (zones are not obstacles here: a route through a zone is 04's refusal, never a replan). False with no
    grid or no calibration (nothing is known to be in the way) and off the map."""
    if g is None or cal is None:
        return False
    return _at(_inflate(_cells(walls_px(g, cal, threshold, lock))), p)


def corners(pts: list[tuple[float, float]]) -> list[list[int]]:
    """Keep the points where the direction changes, plus the ends."""
    if len(pts) < 3:
        return [[int(x), int(y)] for x, y in pts]
    out = [pts[0]]
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
            out.append(b)
    out.append(pts[-1])
    return [[int(x), int(y)] for x, y in out]


def _route(matrix, a, b, info: dict[str, Any]) -> dict[str, Any]:
    """A* from a to b on the matrix: {path (corners), cells, searched, length_px, length_m}; ValueError when either end
    is off the map or blocked, or no route exists, the message naming the cost map."""
    from pathfinding.core.diagonal_movement import DiagonalMovement
    from pathfinding.core.grid import Grid
    from pathfinding.finder.a_star import AStarFinder
    for q, name in ((a, "start"), (b, "end")):
        if not (0 <= q[0] < W and 0 <= q[1] < H):
            raise ValueError(f"{name} {[round(v) for v in q]} is off the map (0..{W} x 0..{H} px)")
    g = Grid(matrix=matrix)
    start, end = g.node(int(a[0]) // CELL, int(a[1]) // CELL), g.node(int(b[0]) // CELL, int(b[1]) // CELL)
    rooms = info["cost_map"] == "rooms"
    if not start.walkable or not end.walkable:
        on = "inside a room, outside every no-go zone" if rooms else "clear of every wall cell the LiDAR saw and every no-go zone"
        raise ValueError(f"{'start' if not start.walkable else 'end'} is not on walkable floor ({on}, {HALF_WIDTH * CELL} px from their edges)")
    path, runs = AStarFinder(diagonal_movement=DiagonalMovement.only_when_no_obstacle).find_path(start, end, g)
    if not path:
        over = "the drawn rooms" if rooms else f"the grid's {info['walls']} wall cells"
        raise ValueError(f"no route from {list(a)} to {list(b)} on {over} around {len(info['nogo'])} no-go zone(s) ({runs} nodes searched)")
    pts = corners([(n.x * CELL + CELL / 2, n.y * CELL + CELL / 2) for n in path])
    length = sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))
    return {"path": pts, "cells": len(path), "searched": runs, "length_px": round(length), "length_m": round(length / 108.5, 2)}


def plan(a, b, grid=None, cal: dict | None = None, threshold: int | None = None, lock=None, grid_source: str = "session") -> dict[str, Any]:
    """One plan.route row. `grid_source` names where the grid came from ("session", or "ui/grid.json" for the saved
    file): anything but the session marks the row cached with that source, so a planted file never claims live."""
    m = json.loads(MAP.read_text())
    with step("plan", "plan.route", "map", {"from": list(a), "to": list(b), "cell_px": CELL}) as r:
        matrix, info, _ = cost_map(m, grid, cal, threshold, lock)   # inside the step: a malformed zone fails this row
        r["args"].update(info)
        if info["cost_map"] == "grid":
            r["args"]["grid_source"] = grid_source
            if grid_source != "session":
                r["cached"], r["source"] = True, grid_source
        out = _route(matrix, a, b, info)
        r["state_after"] = {k: v for k, v in out.items() if k != "path"} | {"waypoints": len(out["path"])}
    out |= {k: info[k] for k in ("cost_map", "why") if k in info}
    log("plan", "route planned", cost_map=info["cost_map"], walls=info["walls"], nogo=len(info["nogo"]), waypoints=len(out["path"]),
        cells=out["cells"], searched=out["searched"], length_m=out["length_m"])
    return out


def replan(p, path: list, i: int, grid, cal: dict | None, threshold: int | None = None, lock=None) -> dict[str, Any]:
    """The dog at map point p, path[i] occupied: a detour to path[j], the first later waypoint not occupied. One
    plan.replanned row. When the dog's own cell is inside the inflation it starts from the nearest walkable cell within
    HALF_WIDTH + 1 cells (args.start_snapped); none, no grid, no calibration, every waypoint i..end occupied, or no
    detour: ValueError, the row ok false."""
    m = json.loads(MAP.read_text())
    args = {"from": [int(p[0]), int(p[1])], "blocked": {"index": i, "waypoint": [int(path[i][0]), int(path[i][1])]}, "cell_px": CELL,
            "shift_id": config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")}
    with step("plan", "plan.replanned", "map", args) as r:
        if grid is None or cal is None:
            raise ValueError(f"replan needs the grid and a calibration ({'no grid' if grid is None else 'not calibrated'})")
        matrix, info, occ = cost_map(m, grid, cal, threshold, lock)
        r["args"].update(info)
        j = next((k for k in range(i + 1, len(path)) if not _at(occ, path[k])), None)
        if j is None:
            raise ValueError(f"waypoints {i}..{len(path) - 1} are all occupied, the route's end {[int(v) for v in path[-1]]} included: nothing to rejoin")
        rejoin, skipped = {"index": j, "waypoint": [int(path[j][0]), int(path[j][1])]}, list(range(i, j))
        r["args"] |= {"rejoin": rejoin, "skipped": skipped}
        start = p
        if 0 <= p[0] < W and 0 <= p[1] < H and not _at(matrix, p):   # the dog stands inside the inflation (beside a wall): leave it by the nearest free cell
            r0, c0, k = int(p[1]) // CELL, int(p[0]) // CELL, HALF_WIDTH + 1
            free = [(math.hypot(dr, dc), (c0 + dc) * CELL + CELL // 2, (r0 + dr) * CELL + CELL // 2)
                    for dr in range(-k, k + 1) for dc in range(-k, k + 1)
                    if 0 <= r0 + dr < H // CELL and 0 <= c0 + dc < W // CELL and matrix[r0 + dr][c0 + dc]]
            if not free:
                raise ValueError(f"the dog at {args['from']} is inside the inflated walls with no free cell within {k * CELL} px: no detour starts here")
            start = list(min(free)[1:])
            r["args"]["start_snapped"] = start
            log("plan", "WARN the dog stands inside the inflation: the detour starts at the nearest free cell", at=args["from"], start=start)
        out = _route(matrix, start, path[j], info)
        r["state_after"] = {k: v for k, v in out.items() if k != "path"} | {"waypoints": len(out["path"])}
    out |= {"blocked": args["blocked"], "rejoin": rejoin, "skipped": skipped, "cost_map": "grid"}
    log("plan", "replanned", at=i, rejoin=j, skipped=skipped, walls=info["walls"], nogo=len(info["nogo"]), waypoints=len(out["path"]),
        length_m=out["length_m"])
    return out
