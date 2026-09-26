"""Plan a route between two points on the floor plan with A* over the drawn rooms (wtdd/plan.py, python-pathfinding)
and, with save=true, make it the map's path (stops cleared) for the dog to follow. The drawing has no walls or doors
between rooms yet, so a planned route can cross a shared wall; the demo uses the recorded route. Returns the waypoints."""
ARGS = {"from": {"type": "string", "default": None, "doc": "x,y in map pixels (default: where the dog thinks it is)"},
        "to": {"type": "string", "default": "436,586", "doc": "x,y in map pixels"},
        "save": {"type": "boolean", "default": False, "doc": "true = write the planned route as the map's path"}}


def run(**kw):
    import json
    from ..field import MAP
    from ..plan import plan
    src, dst, save = kw.get("from"), kw["to"], kw.get("save", False)
    if src is None:
        import requests
        d = requests.get("http://127.0.0.1:7788/dog/state", timeout=5).json()
        if not d.get("map"):
            raise ValueError("no from= and the dog has no map position; give from=x,y")
        a = d["map"]["p"]
    else:
        a = [float(v) for v in str(src).split(",")]
    b = [float(v) for v in str(dst).split(",")]
    out = plan(a, b)
    if save:
        m = json.loads(MAP.read_text())
        MAP.with_name("map.prev.json").write_text(json.dumps(m, indent=2) + "\n")
        m["path"], m["stops"], m["actions"] = out["path"], [], {}
        MAP.write_text(json.dumps(m, indent=2) + "\n")
        out["saved"] = True
    return out
