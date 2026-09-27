"""Plan a route between two points on the floor plan with A* (wtdd/plan.py, python-pathfinding) and, with save=true,
make it the map's path (stops cleared) for the dog to follow. With grid=true (the default) the cost map is the dog's
occupancy grid when one exists and is tied to the map: the API's session grid and calibration, else ui/grid.json
through the calibration saved in it; otherwise, and with grid=false, the drawn rooms, which have no walls or doors
between them yet, so a route over them can cross a shared wall (the demo uses the recorded route). Zones drawn on the
map with nogo: true are blocked on both. Returns the waypoints and cost_map ("grid" | "rooms", with why).
  cp wtdd/fixtures/grid_wall.json ui/grid.json && python -m wtdd plan_path from=300,900 to=650,900   around the fixture's wall"""
ARGS = {"from": {"type": "string", "default": None, "doc": "x,y in map pixels (default: where the dog thinks it is)"},
        "to": {"type": "string", "default": "436,586", "doc": "x,y in map pixels"},
        "save": {"type": "boolean", "default": False, "doc": "true = write the planned route as the map's path"},
        "grid": {"type": "boolean", "default": True, "doc": "true = the occupancy grid is the cost map when one exists and is tied to the map (the API's session grid, else ui/grid.json with its saved calibration); false = the drawn rooms"}}


def run(**kw):
    import json
    import os
    from ..field import MAP
    from ..plan import plan
    src, dst, save = kw.get("from"), kw["to"], kw.get("save", False)
    if src is None:
        import requests
        from ..config import API
        d = requests.get(f"{API}/dog/state", timeout=5).json()
        if not d.get("map"):
            raise ValueError("no from= and the dog has no map position; give from=x,y")
        a = d["map"]["p"]
    else:
        a = [float(v) for v in str(src).split(",")]
    b = [float(v) for v in str(dst).split(",")]
    g = cal = None
    source = "session"
    if kw.get("grid", True):
        from ..dog import occupancy, session   # here: session imports the WebRTC driver
        if os.environ.get("WTDD_API_PROCESS"):
            s = session.DogSession.get()
            with s._grid_lock:
                g, cal = s.grid, s.cal
        if g is None and session.GRID_FILE.exists():
            # DEMO_CACHE: ui/grid.json, the last grid POST /dog/grid {save: true} wrote (or a fixture planted with
            # `cp wtdd/fixtures/grid_wall.json ui/grid.json`), read through the calibration saved in it (a file saved
            # without one takes the session's, as GET /dog/grid draws it) so the planner runs with no dog; the plan.route
            # row is marked cached, source ui/grid.json. Live path: python -m wtdd.api, POST /dog/lidar {on: true}, drag
            # the dog to calibrate, POST /tools/plan_path in that process: the session grid and its calibration are
            # used and the row says grid_source session, source live.
            g = occupancy.Grid.load(session.GRID_FILE)
            cal, source = g.cal or cal, "ui/grid.json"
    out = plan(a, b, grid=g, cal=cal, grid_source=source)
    if save:
        m = json.loads(MAP.read_text())
        MAP.with_name("map.prev.json").write_text(json.dumps(m, indent=2) + "\n")
        m["path"], m["stops"], m["actions"] = out["path"], [], {}
        MAP.write_text(json.dumps(m, indent=2) + "\n")
        out["saved"] = True
    return out
