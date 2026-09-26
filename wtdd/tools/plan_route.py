"""Plan one route through the stops a person taps (wtdd/plan.py route(): A* per leg over the dog's occupancy grid, no-go
zones blocked) and, with save=true, make it the map's path with those stops and the default action at each.
The start: from= when given; else, inside the API process, the dog's believed pose when it is calibrated (read from the
session, never over HTTP); else the first tap. The cost map: the API's session grid and calibration, else ui/grid.json
through the calibration saved in it, else the drawn rooms (06's WARN). A leg with no route fails the whole route
("leg k of n", one plan.multistop row ok false) and nothing is written. save=true writes path, stops and actions through
POST /map's own rules (check_path refuses with the points named; the previous map is kept as ui/map.prev.json), one
plan.saved row, ok false with check_path's lines when refused. Returns path, stops, actions, legs, length_m, cost_map,
grid_source, start ("from" | "pose" | "first tap").
  cp wtdd/fixtures/grid_wall.json ui/grid.json && python -m wtdd plan_route "stops=448,455;436,586;520,600"; rm ui/grid.json
Quote the stops in a shell: ';' ends a command (docs/gotchas/21-1-stops-arg-needs-quotes.md). UNVERIFIED on the dog:
planned on synthetic grids only; the pose start has never run with a real calibration."""
ARGS = {"stops": {"type": "string", "default": None, "doc": "x1,y1;x2,y2;… map pixels, in order; quote it in a shell"},
        "from": {"type": "string", "default": None, "doc": "x,y start; default: the dog's believed pose in the API process, else the first tap"},
        "save": {"type": "boolean", "default": False, "doc": "true = write path, stops and actions into the map through POST /map's rules (check_path; previous kept as map.prev.json)"}}


def _xy(s: str, what: str) -> list[float]:
    try:
        x, y = (float(v) for v in s.split(","))
    except ValueError:
        raise ValueError(f"{what} {s!r} is not x,y in map pixels") from None
    return [x, y]


def run(**kw):
    import json
    import os
    import time
    from .. import config
    from ..dog import occupancy, session   # here: session imports the WebRTC driver, and `python -m wtdd list` must stay cheap
    from ..field import MAP, check_path
    from ..ledger import log, step
    from ..plan import route
    taps = [_xy(s.strip(), f"stop {i + 1}") for i, s in enumerate(str(kw.get("stops") or "").split(";")) if s.strip()]
    if not taps:
        raise ValueError(f"no stops: give stops=x1,y1;x2,y2 in map pixels (got {kw.get('stops')!r})")
    start, how = (_xy(str(kw["from"]), "from"), "from") if kw.get("from") else (None, "first tap")
    g = cal = lock = None
    source = "session"
    if os.environ.get("WTDD_API_PROCESS"):
        s = session.DogSession.get()
        with s._grid_lock:
            g, cal = s.grid, s.cal
        lock = s._grid_lock   # frames land on the driver's thread; the planner reads the walls under this lock
        if start is None and (mp := s.map_pose()):   # the body's last state through the calibration; no connect, no HTTP
            start, how = mp["p"], "pose"
    if g is None and session.GRID_FILE.exists():
        # DEMO_CACHE: ui/grid.json, the last grid POST /dog/grid {save: true} wrote (or a fixture planted with
        # `cp wtdd/fixtures/grid_wall.json ui/grid.json`), read through the calibration saved in it (a file saved
        # without one takes the session's, as GET /dog/grid draws it) so the route is planned with no dog; the
        # plan.route and plan.multistop rows are marked cached, source ui/grid.json. Live path: python -m wtdd.api,
        # POST /dog/lidar {on: true}, drag the dog to calibrate, POST /tools/plan_route in that process: the session
        # grid and its calibration are used, the start is the dog's believed pose, and the rows say grid_source
        # session, source live.
        g = occupancy.Grid.load(session.GRID_FILE)
        cal, source, lock = g.cal or cal, "ui/grid.json", None
    pts = ([start] if start is not None else []) + taps
    log("plan", "route start", start=how, at=[round(v) for v in pts[0]], taps=len(taps), grid=source if g is not None else "none")
    out = route(pts, grid=g, cal=cal, lock=lock, grid_source=source)
    out["start"] = how
    if kw.get("save"):
        m = json.loads(MAP.read_text())
        before = {"path_pts": len(m.get("path", [])), "stops": m.get("stops", [])}
        args = {"path_pts": len(out["path"]), "stops": out["stops"], "shift_id": config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")}
        with step("plan", "plan.saved", "map", args, before) as r:
            problems = check_path(out["path"], m.get("rooms", []))   # POST /map's rule, the same words the page shows
            if problems:
                raise ValueError("not saved: " + "; ".join(problems))
            prev = MAP.with_name("map.prev.json")
            prev.write_text(MAP.read_text())   # the previous route survives one overwrite (POST /map's byte copy)
            m["path"], m["stops"], m["actions"] = out["path"], out["stops"], out["actions"]
            MAP.write_text(json.dumps(m, indent=2) + "\n")
            r["state_after"] = {"path_pts": len(m["path"]), "stops": m["stops"], "prev": f"{MAP.parent.name}/{prev.name}"}
        out["saved"] = True
    return out
