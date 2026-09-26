"""Every ledger row as a tick on the remote's timeline, and the place on the map a row names, computed here so the page
draws and subtracts nothing (GET /marks, wtdd/api.py; the Timeline and MarksLayer in ui/index.html).

  mark(row, map, cal) -> {kind, px, px2?, m?, pts?, why?} | None     pure: reads the row, never writes into it, no I/O
  serve(all_rows, map, n, now) -> {rows, n, total, span_s, lanes}    the last n rows as ticks {i, ts, tool, agent, ok,
                                                                     latency_ms, age_s, t_s, mark}; i is the ledger index

The kind table (px is where the ring goes, the place the row names; px2 is the arrow's tail, the arrow runs px2 -> px):
  dog.calibrate   vector from the believed pose (state_before.p, session.map_pose() flat) to where it was placed (args.p),
                  with m, the metres between them: the realign made visible. No belief before it: a point that says why.
  dog.follow      vector from where it started (state_before.p) to where it ended or gave up (state_after.map.p); no m,
                  because start-to-end metres would read as the distance walked.
  dog.record      the map's path, only while the map still holds the recorded one (its point count and length match the
                  row's own path_pts and length_px); otherwise px None and why. The row carries counts, not points.
  lights.* + id   the lamp's point on ui/map.json (lights[].pts[0]); a lamp not on the map is px None with why.
  pose.corrected  (feat/05b's localize.row shape) origin state_before.map.p, tip origin + nav.to_map of the odometry-frame
                  (dx, dy) through the calibration in force, m = |(dx, dy)|. No map pose, or no calibration: px None, why.
  anything else   None: the row names no place.
The calibration in force for a row is state_after.cal of the last ok dog.calibrate row before it in the whole ledger
(not only the window), so no row is ever drawn through a calibration made after it.
One stderr line per serve: `[wtdd:marks] served rows= total= placed= unplaced= failed= ms=`; WARN on zero rows or a ts
that will not parse (that row's age_s and t_s are null, never guessed).
UNVERIFIED on the dog: nothing in the code; the calibrate vector's metres against a tape on the first live calibrate.
"""
from __future__ import annotations
import math
import time

from .dog.nav import PX_PER_M, to_map
from .ledger import log

TS = "%Y-%m-%dT%H:%M:%S"   # ledger.append's format


def _len(path) -> int:
    return round(sum(math.dist(path[k - 1], path[k]) for k in range(1, len(path))))


def mark(row: dict, map: dict, cal: dict | None) -> dict | None:   # noqa: A002  (the contract's name)
    t, a = row.get("tool") or "", row.get("args") or {}
    sb, sa = row.get("state_before") or {}, row.get("state_after") or {}
    if t == "dog.calibrate":
        if not sb.get("p"):
            return {"kind": "point", "px": list(a["p"]), "why": "no believed pose before this calibration"}
        return {"kind": "vector", "px": list(a["p"]), "px2": list(sb["p"]), "m": round(math.dist(a["p"], sb["p"]) / PX_PER_M, 2)}
    if t == "dog.follow":
        start, end = sb.get("p"), (sa.get("map") or {}).get("p")
        if start and end:
            return {"kind": "vector", "px": list(end), "px2": list(start)}
        if start or end:
            return {"kind": "point", "px": list(start or end)}
        return {"kind": "point", "px": None, "why": "no map pose on the row"}
    if t == "dog.record":
        path = map.get("path") or []
        if len(path) == sa.get("path_pts") and _len(path) == sa.get("length_px"):
            return {"kind": "path", "px": list(path[0]), "pts": [list(p) for p in path]}
        return {"kind": "path", "px": None, "why": f"the row recorded {sa.get('path_pts')} pts / {sa.get('length_px')} px; "
                                                   f"the map's path is {len(path)} pts / {_len(path)} px now"}
    if t.startswith("lights.") and a.get("id"):
        lamp = next((L for L in map.get("lights") or [] if L.get("id") == a["id"]), None)
        if lamp is None:
            return {"kind": "point", "px": None, "why": f"light {a['id'][:8]} is not on the map (ui/map.json lights)"}
        return {"kind": "point", "px": list(lamp["pts"][0])}
    if t == "pose.corrected":
        o = (sb.get("map") or {}).get("p")
        if not o:
            return {"kind": "vector", "px": None, "why": "no map pose on the row"}
        if not cal:
            return {"kind": "vector", "px": None, "why": "no calibration before this row in the ledger"}
        ox, oy, oyaw = cal["odom"]
        x, y, _ = to_map(cal, (ox + a["dx"], oy + a["dy"]), oyaw)   # the delta is odometry-frame metres: the dots' own projection
        return {"kind": "vector", "px": [round(o[0] + x - cal["map"][0], 1), round(o[1] + y - cal["map"][1], 1)], "px2": list(o),
                "m": round(math.hypot(a["dx"], a["dy"]), 2)}
    return None


def serve(all_rows: list[dict], map: dict, n: int, now: float) -> dict:   # noqa: A002
    t0 = time.perf_counter()
    if n < 1:
        raise ValueError(f"n must be at least 1, got {n}")
    base = len(all_rows) - len(all_rows[-n:])
    cal, win, bad = None, [], 0
    for i, r in enumerate(all_rows):
        if i >= base:
            try:
                t = time.mktime(time.strptime(r.get("ts"), TS))
            except (TypeError, ValueError):
                t, bad = None, bad + 1
            win.append((i, r, t, mark(r, map, cal)))
        if r.get("tool") == "dog.calibrate" and r.get("ok"):
            cal = (r.get("state_after") or {}).get("cal")
    first = next((t for _, _, t, _ in win if t is not None), None)
    rows = [{"i": i, "ts": r.get("ts"), "tool": r.get("tool"), "agent": r.get("agent"), "ok": r.get("ok"),
             "latency_ms": r.get("latency_ms"), "age_s": None if t is None else round(now - t),
             "t_s": None if t is None else round(t - first), "mark": mk} for i, r, t, mk in win]
    spans = [s["t_s"] for s in rows if s["t_s"] is not None]
    placed = sum(1 for s in rows if s["mark"] and s["mark"]["px"] is not None)
    unplaced = sum(1 for s in rows if s["mark"] and s["mark"]["px"] is None)
    warn = not rows or bad
    log("marks", ("WARN " if warn else "") + "served", rows=len(rows), total=len(all_rows), placed=placed, unplaced=unplaced,
        failed=sum(1 for s in rows if s["ok"] is False), **({"bad_ts": bad} if bad else {}), ms=round((time.perf_counter() - t0) * 1000))
    return {"rows": rows, "n": len(rows), "total": len(all_rows), "span_s": max(spans) if spans else None,
            "lanes": list(dict.fromkeys(s["agent"] for s in rows))}
