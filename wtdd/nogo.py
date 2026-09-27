"""No-go zones: a zone a person draws on the map with `nogo: true` (ui/map.json `zones[]`; the lighting zones a, b, c
carry no such flag and mean nothing here). The planner (wtdd/plan.py) blocks a zone's cells like the outside of a room;
the walk (field.walk) and the follower (DogSession.follow) refuse a route that touches one before anything moves. The
refusal is the superintendent's drawing applied, never the dog's judgment and never a probability: one `route.refused`
ledger row sourced to the map, one stderr line, then ValueError. The only place zone semantics live.

  zones(m)                   the map's no-go zones (entries with nogo: true); no nogo key or nogo: false is skipped, and
                             any other nogo value or a poly under 3 points raises: a malformed zone, never a silently inert one
  hit(path, zs)              the first place the route touches a zone, or None: {zone, waypoint: [x, y], index}
  refuse(path, agent, m)     no hit: one stderr line, returns; a hit: the row, the line, then ValueError

The waypoint/index rule: every path POINT is checked first (the first one inside a zone is the waypoint, index = its
path index); only when none is inside are the segments sampled every STEP_PX (interior points only) and the first
sample inside is the waypoint, index = that segment's first path index. The check is on the route's line; the dog's
width is kept out by the planner's HALF_WIDTH erosion, not here. Error sentences number points from 1, as check_path
and the remote do.
UNVERIFIED: nothing here has run on the dog; the follower's refusal was exercised with a session that never connected.
"""
from __future__ import annotations
import json
import math
import time
from typing import Any

from . import config
from .field import MAP, inside
from .ledger import append, log

STEP_PX = 10   # = plan.CELL (plan imports this module, so this module never imports plan)


def zones(m: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for z in m.get("zones", []):
        if "nogo" not in z or z["nogo"] is False:   # a lighting zone (a, b, c), or a zone switched off by hand
            continue
        n = len(z.get("poly") or [])
        if z["nogo"] is not True or n < 3:         # a hand-edited zone the planner and refuse() could not honour: never inert
            log("nogo", "FAILED malformed no-go zone", zone=z.get("name"), nogo=repr(z["nogo"]), poly_pts=n)
            raise ValueError(f"zone {z.get('name')!r}: nogo must be true and poly needs at least 3 points "
                             f"(got nogo={z['nogo']!r}, {n} points); fix it in {MAP}")
        out.append(z)
    return out


def hit(path: list, zs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for i, p in enumerate(path):
        for z in zs:
            if inside(p, z["poly"]):
                return {"zone": z["name"], "waypoint": [int(p[0]), int(p[1])], "index": i, "crosses": False}
    for i in range(1, len(path)):
        (ax, ay), (bx, by) = path[i - 1], path[i]
        n = max(1, math.ceil(math.dist((ax, ay), (bx, by)) / STEP_PX))
        for k in range(1, n):
            q = (round(ax + (bx - ax) * k / n), round(ay + (by - ay) * k / n))
            for z in zs:
                if inside(q, z["poly"]):
                    return {"zone": z["name"], "waypoint": list(q), "index": i - 1, "crosses": True}
    return None


def refuse(path: list, agent: str, m: dict[str, Any] | None = None) -> None:
    m = json.loads(MAP.read_text()) if m is None else m
    zs = zones(m)
    h = hit(path, zs)
    if h is None:
        log("nogo", "route clear" if zs else "WARN no no-go zones on the map: the route is checked against none", zones=len(zs), pts=len(path), by=agent)
        return
    x, y = h["waypoint"]
    n = h["index"] + 1
    why = (f"route refused: the route crosses no-go zone {h['zone']} between points {n} and {n + 1} at {x},{y}" if h["crosses"]
           else f"route refused: point {n} at {x},{y} is inside no-go zone {h['zone']} (drawn on the map)")
    append({"step": "route.refused", "agent": agent, "tool": "route.refused", "app": "map", "source": "map",
            "args": {"zone": h["zone"], "waypoint": h["waypoint"], "index": h["index"], "source": "map", "path_pts": len(path),
                     "shift_id": config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")},
            "state_before": None, "state_after": None, "ok": False, "response_or_error": why, "latency_ms": 0})
    log("nogo", "route REFUSED", zone=h["zone"], waypoint=f"{x},{y}", index=h["index"], by=agent)
    raise ValueError(why)
