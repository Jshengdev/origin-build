"""Named routines: each demo route (kitchen → bedroom 2, bedroom 2 → living room) saved under a name and put back on the
map with one tap. A routine is ui/map.json's path, stops and actions; nothing else in the map belongs to one.

  listing(mp)       GET /routines: {routines: [{name, dots, stops, saved_at}], loaded}. dots is the path's point count,
                    stops the stop indices, saved_at local time with no zone; loaded is the first routine whose path, stops
                    and actions are the map's now, or null (a page save that changes the route un-loads it). A read, no row.
  act(mp, body)     POST /routines {action: save | load | delete, name}: one routine.saved / routine.loaded /
                    routine.deleted row, ok or not, state_before and state_after {names, loaded, _version}, read back
                    before the row says ok. Answers {ok, routines, loaded, _version}: the new list and the map's version.
    save            the map's route under the name, a name already saved replaced in place (the map is not written).
    load            the routine's route written into the map by field.write_map, POST /map's own write: every other key
                    (rooms, lights, zones, labels, policy) kept, the map it replaces kept as map.prev.json, _version the
                    file's new int(mtime), so an open page's stale POST /map is a 409.
    delete          the name gone from the file; the map keeps its route.
  Refused(code)     a name that is not 1 to 40 characters once trimmed, or an empty path, is 400; a name not saved is 404
                    naming the routines that exist; each on its failed row. An unknown action is 400 with no row (it
                    names no step).
The file is routines.json beside the map (ui/routines.json; a WTDD_MAP scratch copy keeps its own), created by the first
save and gitignored like ledger.jsonl: it is live data. One that does not parse is a ValueError naming it, never [].
No follow code: POST /dog/follow and the chat round read ui/map.json at use, so they walk the route that was loaded.
_version is int(mtime), as POST /map's, moved strictly up by field.write_map: a load in the second of the page's last read
still makes that page's save a 409. UNVERIFIED on the dog: a routine is map pixels, so it is walked
under the calibration tie and scale in force at the walk, not the ones it was drawn or recorded under; the first live
load then POST /dog/follow must show dog.follow's planned points equal to the routine's dots, from the same drop-off.
Offline: python -m unittest wtdd.test_routines
"""
from __future__ import annotations
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .field import write_map
from .ledger import log, step

TOOLS = {"save": "routine.saved", "load": "routine.loaded", "delete": "routine.deleted"}
MAX_NAME = 40
ROUTE = ("path", "stops", "actions")
_LOCK = threading.Lock()   # the API is threaded: one read-modify-write of routines.json and the map at a time


class Refused(Exception):
    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code


def _read(mp: Path) -> list[dict[str, Any]]:
    f = mp.with_name("routines.json")
    if not f.exists():
        return []   # nothing saved yet: the first save creates it
    try:
        rs = json.loads(f.read_text())["routines"]
        [(r["name"] + "", len(r["path"]), r["stops"], r["actions"], r["saved_at"]) for r in rs]   # every routine has its keys
        return rs
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{f} is malformed ({type(e).__name__}: {e}); fix or delete it") from None


def _route(m: dict[str, Any]) -> tuple:
    return m.get("path") or [], m.get("stops") or [], m.get("actions") or {}


def _state(mp: Path, rs: list[dict[str, Any]]) -> dict[str, Any]:
    now = _route(json.loads(mp.read_text()))
    return {"names": [r["name"] for r in rs], "loaded": next((r["name"] for r in rs if _route(r) == now), None),
            "_version": int(mp.stat().st_mtime)}


def listing(mp: Path) -> dict[str, Any]:
    rs = _read(mp)
    return {"routines": [{"name": r["name"], "dots": len(r["path"]), "stops": r["stops"], "saved_at": r["saved_at"]} for r in rs],
            "loaded": _state(mp, rs)["loaded"]}


def act(mp: Path, body: dict[str, Any]) -> dict[str, Any]:
    action, name = body.get("action"), body.get("name")
    if action not in TOOLS:
        log("routines", "refused: unknown action", action=action)
        raise Refused(400, f"action must be save, load or delete, got {action!r}")
    name = name.strip() if isinstance(name, str) else name
    with _LOCK, step("routines", TOOLS[action], "map", {"name": name}) as r:
        rs = _read(mp)
        r["state_before"] = _state(mp, rs)
        if not isinstance(name, str) or not 0 < len(name) <= MAX_NAME:
            raise Refused(400, f"not {TOOLS[action].split('.')[1]}: a routine's name is 1 to {MAX_NAME} characters, got {body.get('name')!r}")
        names = r["state_before"]["names"]
        if action != "save" and name not in names:
            raise Refused(404, f"no routine named {name!r}; routines: {', '.join(names) or 'none saved yet'}")
        if action == "load":
            m = json.loads(mp.read_text())
            want = dict(zip(ROUTE, _route(rs[names.index(name)])))
            write_map(mp, {**m, **want})
            if _route(json.loads(mp.read_text())) != tuple(want.values()):   # loaded when the map says so
                raise RuntimeError(f"{mp} read back another route than {name!r}")
        else:
            if action == "save":
                path, stops, actions = _route(json.loads(mp.read_text()))
                if not path:
                    raise Refused(400, f"not saved: the map has no path to save as {name!r}; draw or record the route first")
                new = {"name": name, "path": path, "stops": stops, "actions": actions, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                rs = [new if x["name"] == name else x for x in rs] if name in names else rs + [new]
            else:
                rs = [x for x in rs if x["name"] != name]
            f = mp.with_name("routines.json")
            f.with_suffix(".tmp").write_text(json.dumps({"routines": rs}, indent=2) + "\n")
            os.replace(f.with_suffix(".tmp"), f)   # a crash mid-write never leaves half a file
        after = r["state_after"] = _state(mp, _read(mp))
        if (name in after["names"]) != (action != "delete"):
            raise RuntimeError(f"{mp.with_name('routines.json')} read back {after['names']} after the {action} of {name!r}")
    return {"ok": True, **listing(mp), "_version": after["_version"]}
