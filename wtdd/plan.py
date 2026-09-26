"""A route between two points on the floor plan: A* (python-pathfinding, pure Python) on a grid built from the map's
room polygons, walkable where a cell centre is inside any room, shrunk by the dog's half-width. Returns the corners of
the grid path in map pixels, ready to be the map's `path`. Limit, stated: ui/house.svg draws rooms as rectangles with
no walls or doors between them, so a planned route can cross a shared wall; the demo's route is recorded by driving
(wtdd/dog/session.py record), and this planner is for point-to-point routes inside a room or across drawn doorways.

  python -m wtdd plan_path from=448,455 to=436,586           the waypoints, nothing written
  python -m wtdd plan_path from=448,455 to=436,586 save=true  also written as the map's path (stops cleared)
"""
from __future__ import annotations
import json
import math
from typing import Any

from .config import ROOT
from .field import MAP, inside
from .ledger import log, step

CELL = 10            # px per grid cell, about 9 cm
HALF_WIDTH = 4       # cells the walkable area shrinks by (the dog is about 0.35 m wide)
W, H = 1060, 1540    # the map's viewBox


def grid(rooms: list[dict[str, Any]]):
    """0 = blocked, 1 = walkable: inside any room, then eroded by HALF_WIDTH cells."""
    cols, rows = W // CELL, H // CELL
    free = [[1 if any(inside((c * CELL + CELL / 2, r * CELL + CELL / 2), R["poly"]) for R in rooms) else 0 for c in range(cols)] for r in range(rows)]
    walk = [[1 if all(0 <= r + dr < rows and 0 <= c + dc < cols and free[r + dr][c + dc] for dr in range(-HALF_WIDTH, HALF_WIDTH + 1) for dc in range(-HALF_WIDTH, HALF_WIDTH + 1)) else 0 for c in range(cols)] for r in range(rows)]
    return walk


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


def plan(a, b) -> dict[str, Any]:
    from pathfinding.core.diagonal_movement import DiagonalMovement
    from pathfinding.core.grid import Grid
    from pathfinding.finder.a_star import AStarFinder
    m = json.loads(MAP.read_text())
    with step("plan", "plan.route", "map", {"from": list(a), "to": list(b), "cell_px": CELL}) as r:
        g = Grid(matrix=grid(m["rooms"]))
        start, end = g.node(int(a[0]) // CELL, int(a[1]) // CELL), g.node(int(b[0]) // CELL, int(b[1]) // CELL)
        if not start.walkable or not end.walkable:
            raise ValueError(f"{'start' if not start.walkable else 'end'} is not on walkable floor (inside a room, {HALF_WIDTH * CELL} px from its edge)")
        path, runs = AStarFinder(diagonal_movement=DiagonalMovement.only_when_no_obstacle).find_path(start, end, g)
        if not path:
            raise ValueError(f"no route from {list(a)} to {list(b)} on the drawn rooms ({runs} nodes searched)")
        pts = corners([(n.x * CELL + CELL / 2, n.y * CELL + CELL / 2) for n in path])
        length = sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))
        out = {"path": pts, "cells": len(path), "searched": runs, "length_px": round(length), "length_m": round(length / 108.5, 2)}
        r["state_after"] = {k: v for k, v in out.items() if k != "path"} | {"waypoints": len(pts)}
    log("plan", "route planned", waypoints=len(pts), cells=len(path), searched=runs, length_m=out["length_m"])
    return out
