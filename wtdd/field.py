"""The proximity field: an entity with a radius walks the path drawn on ui/map.json and every light's brightness is how
much of it sits inside that radius, weighted toward the centre. One implementation, used by the chat's wake demo
(tools.call("walk_path")) and by the remote's walk button (POST /tools/walk_path); the page only animates the dot.

  python -m wtdd walk_path dry=true        compute and log every level, write nothing (writes = 0 in the row)
  python -m wtdd walk_path                 drive the real lights
  lamp:   score = (1 - d/R) ** falloff at the lamp's point
  strip:  the mean of that over `samples` points along its line (a graze at the edge is dim, a pass over the middle bright)
  rooms:  score *= other_room_factor when the light's room (the polygon its point sits in) is not the entity's room
Map keys read: path (at least 2 points), stops [path indices], entity {radius_px 220, speed_px_s 60, falloff 1.6,
other_room_factor 0.3, gain 1.0 (the near light's brightness multiplier, clipped at 100), samples 12, min_step 4, floor 6}, lights [{id, label, kind dot|line, pts, device hue|strip}],
rooms [{name, poly}].
lights[].room is recomputed here from the polygons, whatever the file says.
Writes go through the registry (hue_light_set per lamp, strip_set for the strip): one thread per light and at most one
write in flight per light, so each light steps exactly as fast as its own measured latency allows (the strip about 0.4 s
on the LAN, a Hue lamp through the cloud about 0.8 s), only when the level moved by at least `min_step` points or
crossed zero, and is simply off below `floor`. The loop polls at HZ. Order: every light to 0 and wait for all of it (the
room starts dark and the first latency of each light is measured), the walk in real time at speed_px_s, then every
light to 0 again and wait. One field.walk ledger row with seconds, writes, errors, rooms crossed and the mean latency per
light; every write is its own row, a failed write is counted and logged, never retried. The end dark runs in a finally:
a walk that raises (a failed /dog/state read, an on_stop that raises) or is interrupted (Ctrl-C) still drains its in-flight
writes, puts every light to 0 and shuts its pool down before the error goes on. With the follower (source="dog") it
first halts the dog, before the dark: halt(), POST /dog/stop, one dog.stop row (the remote's walk button and the chat
alike; the error carries dog_halted so the chat does not halt twice). While it runs, <repo>/field.json
holds the entity's position, room, levels and current stop (atomic writes at HZ, removed at the end); the API serves it
at GET /field and the remote draws the dot from it, whichever process runs the walk; a field.json younger than BUSY_S
means a walk is live and a second walk (the button during a chat round, or the reverse) is refused, never interleaved. Stops: map.json `stops` is a list
of path point indices (double-click a path point on the remote); at each one the walk pauses and calls on_stop(index,
point, room), the lights hold, then it resumes. The chat's wake sequence passes its look-and-say as on_stop; with no
stops on the map it looks once at the end of the path. source="dog" (WTDD_ROUND=dog in the chat): the entity is the
real dog's calibrated odometry pose from the API, the follower (POST /dog/follow) drives it and pauses at the stops,
and the walk ends when the follower ends; a failed follow raises with the lights' numbers in the message. Measured on the live wake demo
(2026-09-13): dark start 1.46 s, walk 63.6 s across four rooms (seven crossings, five lights), 67 writes, 0 errors.
No-go zones (map zones with nogo: true, wtdd/nogo.py): a route that touches one is refused right after the path check,
before the busy check and the dark start: one route.refused row, no field.walk row, nothing published, no light written.
WTDD_MAP (plain process env, read once at import like WTDD_LEDGER; .env is not consulted) points every reader of the
map (MAP, imported by name by plan, nogo, api, tools and the chat) at another file: the tests' scratch copy and the dry
remote; unset = ui/map.json.
"""
from __future__ import annotations
import json
import math
import time
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from . import tools
from .config import API, ROOT
from .ledger import log, step

MAP = Path(os.environ.get("WTDD_MAP", ROOT / "ui" / "map.json"))
HZ = 10.0
FIELD = ROOT / "field.json"   # the running walk: p, here, levels, s, total, stop; written at HZ, removed at the end (GET /field)
STOP = ROOT / "field.stop"    # POST /field/stop touches it: the running walk ends at its next tick (lights off, row written)
BUSY_S = 2.0                  # a field.json younger than this means a walk is live somewhere (the remote or the chat): refuse a second
YIELD = ROOT / "field.yield"  # a round's walk touches it: a running lights-only walk (follower=False) ends at its next tick, lit
YIELD_S = 5.0                 # how long that round waits for the lights walk's field.json to go before it is refused as busy


def inside(p, poly) -> bool:
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def room_of(p, rooms) -> str | None:
    return next((r["name"] for r in rooms if inside(p, r["poly"])), None)


MAX_STEP_PX = 300   # about 2.8 m: consecutive path points further apart are a jump (a stray click, or the trace hopping at a correction)


def check_path(path, rooms) -> list[str]:
    """Why a path cannot be run, one line per problem, [] when it can: fewer than 2 points, a point outside every room,
    two consecutive points further apart than MAX_STEP_PX. Points are numbered from 1 as on the remote."""
    bad: list[str] = []
    if len(path) < 2:
        bad.append(f"only {len(path)} path point(s); draw at least 2")
    for i, q in enumerate(path):
        if room_of(q, rooms) is None:
            bad.append(f"point {i + 1} at {int(q[0])},{int(q[1])} is outside every room")
    for i in range(1, len(path)):
        d = math.dist(path[i - 1], path[i])
        if d > MAX_STEP_PX:
            bad.append(f"points {i} and {i + 1} are {int(d)} px apart (over {MAX_STEP_PX}): a jump, delete the stray one")
    return bad


def write_map(mp: Path, m: dict[str, Any]) -> int:
    """mp rewritten with m, the file it replaces kept as map.prev.json (the previous route survives one overwrite); returns
    the new _version, int(mtime), which a page sends back so a stale save is a 409. POST /map's write and a routine's load.
    The version only goes up: a write in the second of the last one sets the mtime to the last version + 1, so a page that
    read in that second is stale and its poll sees the change (a burst of writes can run the mtime a few seconds ahead)."""
    old = -1
    if mp.exists():
        old = int(mp.stat().st_mtime)
        mp.with_name("map.prev.json").write_text(mp.read_text())
    mp.write_text(json.dumps(m, indent=2) + "\n")
    v = max(int(mp.stat().st_mtime), old + 1)
    os.utime(mp, (v, v))
    return v


def score(light: dict[str, Any], p, ent: dict[str, Any], here: str | None) -> float:
    R, k = float(ent.get("radius_px", 220)), float(ent.get("falloff", 1.6))
    w = lambda q: max(0.0, 1 - math.dist(p, q) / R) ** k  # noqa: E731
    if light["kind"] == "line":
        n = int(ent.get("samples", 12))
        (ax, ay), (bx, by) = light["pts"]
        s = sum(w((ax + (bx - ax) * i / n, ay + (by - ay) * i / n)) for i in range(n + 1)) / (n + 1)
    else:
        s = w(light["pts"][0])
    if here and light["room"] and light["room"] != here:
        s *= float(ent.get("other_room_factor", 0.3))
    return min(1.0, s * float(ent.get("gain", 1.0)))   # gain: how bright the near light gets (2 = twice, clipped at 100%)


def _label(light: dict[str, Any]) -> str:
    return light.get("label", light["id"])


def _write(light: dict[str, Any], level: int) -> float:
    """One real write through the registry; returns its latency in seconds."""
    t0 = time.monotonic()
    if light["device"] == "strip":
        tools.call("strip_set", on=level > 0, percent=max(level, 1))
    else:
        tools.call("hue_light_set", light=light["id"], on=level > 0, percent=max(level, 1))
    return time.monotonic() - t0


def _publish(d: dict[str, Any] | None) -> None:
    """The live position for the remote (GET /field): atomic file write, or removal when the walk is over."""
    if d is None:
        FIELD.unlink(missing_ok=True)
        return
    tmp = FIELD.with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    os.replace(tmp, FIELD)


def _dog() -> dict[str, Any]:
    """The dog's believed map pose and follow status from the API (source="dog")."""
    import requests
    d = requests.get(f"{API}/dog/state", timeout=3).json()
    if not d.get("map"):
        raise RuntimeError("the dog has no map pose (not calibrated, or no state)")
    return d


def _live() -> dict[str, Any] | None:
    """The running walk's field.json plus its age, None when no walk is live (no file, or one older than BUSY_S)."""
    try:
        age = time.time() - FIELD.stat().st_mtime
        return {**json.loads(FIELD.read_text()), "age": age} if age < BUSY_S else None
    except FileNotFoundError:   # no walk, or it ended between the two reads
        return None


def halt(why: str, agent: str = "field") -> None:
    """POST /dog/stop when a dog walk is gone (it raised, or never began): the API cancels the follower and halts the
    dog, walking or held at a stop. One dog.stop row; a stop that fails is that row FAILED and a WARN, never raised."""
    import requests
    try:
        with step(agent, "dog.stop", "unitree", {"why": why[:160]}) as r:
            r["state_after"] = requests.post(f"{API}/dog/stop", json={}, timeout=15).json()   # the API's halt waits up to 10 s
            if not r["state_after"].get("ok"):
                raise RuntimeError(r["state_after"].get("error") or "the API refused the stop")
    except Exception as e:  # noqa: BLE001  (the dog.stop row has it)
        log(agent, "WARN the follower could NOT be stopped after the failed walk", err=f"{type(e).__name__}: {str(e)[:100]}")


def walk(dry: bool = False, on_stop: Callable[[int, tuple[float, float], str | None], Any] | None = None,
         source: str = "entity", follower: bool = True) -> dict[str, Any]:
    """Runs the entity along the map's path in real time and drives the real lights (see the module doc for the order).
    At each of the map's stops (path point indices) the entity pauses, on_stop(index, point, room) runs to completion
    (the chat's look-and-say; the lights hold), then the walk resumes from the same spot. Returns seconds, dark_ms,
    writes, errors, rooms crossed, stops done, latency_ms per light, and the light labels.
    source="dog": the entity IS the dog. Its position is the calibrated odometry pose from GET /dog/state (the API's
    follower must be running: POST /dog/follow first), the stops are where the follower pauses (on_stop runs, then
    POST /dog/resume), and the walk ends when the follower is done or failed (the error is in the row); a walk that
    raises in its loop halts the dog (halt()) before it goes dark.
    source="dog", follower=False: the lights simply follow the dog wherever it is driven (the controller, the keys),
    no route and no stops, until POST /field/stop (or STOP appears); the row says how long and how many writes."""
    if source not in ("entity", "dog"):
        raise ValueError(f"source must be entity or dog, got {source!r}")
    m = json.loads(MAP.read_text())
    pts, ent, lights, rooms = m["path"], m.get("entity", {}), m.get("lights", []), m.get("rooms", [])
    problems = check_path(pts, rooms)
    if problems:
        raise ValueError("the path cannot be run: " + "; ".join(problems))
    from .nogo import refuse                       # lazy: nogo imports this module
    refuse(pts, "field", m, dots_only=True)        # a dot inside a drawn no-go zone (S12: a line crossing one is routed around): one route.refused row, then ValueError; nothing moves, nothing published
    stops = sorted({int(i) for i in m.get("stops", []) if 0 <= int(i) < len(pts)})
    live = _live()
    if live and live.get("follower") is False and source == "dog" and follower and not dry:   # Lights on, a round's walk: it takes over
        YIELD.write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")   # never STOP: the chat's round reads a STOP since its wake as Stop pressed
        t_y = time.monotonic()
        while (live := _live()) and time.monotonic() - t_y < YIELD_S:
            time.sleep(0.05)
        YIELD.unlink(missing_ok=True)
        log("field", "WARN the lights walk did not yield" if live else "the lights walk yielded", waited_s=round(time.monotonic() - t_y, 2))
    if live:   # another process's walk is live: refuse, never interleave
        raise RuntimeError(f"a walk is already running ({FIELD.name} written {round(live['age'], 1)} s ago)")
    STOP.unlink(missing_ok=True)
    YIELD.unlink(missing_ok=True)
    for L in lights:
        (ax, ay), (bx, by) = L["pts"][0], L["pts"][-1]     # a dot's midpoint is the dot itself
        L["room"] = room_of(((ax + bx) / 2, (ay + by) / 2), rooms)
    speed = float(ent.get("speed_px_s", 60))
    min_step = int(ent.get("min_step", 4))
    floor = int(ent.get("floor", 6))
    segs = [(pts[i - 1], pts[i], math.dist(pts[i - 1], pts[i])) for i in range(1, len(pts))]
    total = sum(d for _, _, d in segs)
    cum = [0.0]                                              # distance along the path to each point: when a stop is reached
    for _, _, d in segs:
        cum.append(cum[-1] + d)

    def at(s):
        acc = 0.0
        for a, b, d in segs:
            if s <= acc + d:
                k = (s - acc) / d if d else 0
                return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
            acc += d
        return tuple(pts[-1])

    pool = ThreadPoolExecutor(max_workers=max(1, len(lights)))
    lat: dict[str, list[float]] = {L["id"]: [] for L in lights}
    inflight: dict[str, Any] = {}
    last: dict[str, int] = {L["id"]: 0 for L in lights}
    writes = errors = 0

    def settle(fut, lid):
        nonlocal errors
        try:
            lat[lid].append(fut.result(timeout=30))
        except Exception as e:  # noqa: BLE001  (counted and logged here; the failed write has its own ledger row)
            errors += 1
            log("field", "write failed", light=lid[:8], err=f"{type(e).__name__}: {str(e)[:80]}")

    with step("field", "field.walk", "map", {"path_pts": len(pts), "lights": len(lights), "radius": ent.get("radius_px"),
                                             "falloff": ent.get("falloff"), "speed": speed, "seconds": round(total / speed, 1),
                                             "stops": stops, "dry": dry, "source": source, "follower": follower}) as r:
        t_dark = time.monotonic()
        if not dry:                                      # dark start: everything off, and wait for it
            for lid, fut in {L["id"]: pool.submit(_write, L, 0) for L in lights}.items():
                settle(fut, lid)
            writes += len(lights)
        dark_ms = round((time.monotonic() - t_dark) * 1000)
        log("field", "dark, starting", ms=dark_ms, latency={_label(L)[:12]: round(1000 * lat[L["id"]][-1]) if lat[L["id"]] else None for L in lights})
        t0 = time.monotonic()
        rooms_seen: list[str] = []
        stops_done: list[int] = []
        pending_stops = list(stops)
        follow_error: str | None = None
        yielded = False
        try:
          while True:
            if source == "dog":
                d = _dog()
                p = tuple(d["map"]["p"])
                f = d.get("follow") or {}
                if follower and not f.get("active") and not stops_done and not f.get("done") and not f.get("error"):
                    raise RuntimeError("the dog's follower is not running (POST /dog/follow first)")
                s = cum[min(int(f.get("i", 0)), len(cum) - 1)]
            else:
                s = min(total, (time.monotonic() - t0) * speed)
                p = at(s)
            here = room_of(p, rooms)
            if here and (not rooms_seen or rooms_seen[-1] != here):
                rooms_seen.append(here)
            lv: dict[str, int] = {}
            for L in lights:
                lid = L["id"]
                level = int(round(100 * score(L, p, ent, here)))
                if level < floor:
                    level = 0
                lv[lid] = level
                fut = inflight.get(lid)
                if fut is not None:
                    if not fut.done():
                        continue                       # one write in flight per light: pace = that light's real latency
                    settle(fut, lid)
                    inflight.pop(lid)
                if abs(level - last[lid]) >= min_step or (level == 0) != (last[lid] == 0):
                    last[lid] = level
                    log("field", f"{_label(L)[:18]} -> {level}%", room=here or "-", x=int(p[0]), y=int(p[1]))
                    if not dry:
                        writes += 1
                        inflight[lid] = pool.submit(_write, L, level)
            live = {"p": [round(p[0]), round(p[1])], "here": here, "levels": lv, "s": round(s), "total": round(total), "dry": dry, "stop": None, "source": source, "follower": follower}
            at_stop = (pending_stops and s >= cum[pending_stops[0]]) if source == "entity" else (follower and f.get("stopped_at") is not None and f["stopped_at"] not in stops_done)
            if at_stop:
                i = pending_stops.pop(0) if source == "entity" else int(f["stopped_at"])
                _publish({**live, "stop": i})
                log("field", f"stop {i}: pausing", room=here or "-", x=int(p[0]), y=int(p[1]))
                t_pause = time.monotonic()
                if on_stop is not None:
                    on_stop(i, p, here)
                t0 += time.monotonic() - t_pause                 # resume from the same spot
                stops_done.append(i)
                log("field", f"stop {i}: resuming", paused_s=round(time.monotonic() - t_pause, 1))
                if source == "dog":
                    import requests
                    requests.post(f"{API}/dog/resume", json={}, timeout=3)
            _publish(live)
            if STOP.exists():
                log("field", "stopped by request", after_s=round(time.monotonic() - t0, 1))
                break
            if not follower and YIELD.exists():          # a round's walk is taking over: end now, lit; its dark start is next
                log("field", "yielded to the round", after_s=round(time.monotonic() - t0, 1))
                yielded = True
                break
            if source == "dog" and follower:
                if not f.get("active"):
                    follow_error = f.get("error")
                    break
            elif source == "entity" and s >= total:
                break
            time.sleep(1 / HZ)
        except BaseException as e:                       # the loop is gone: stop the dog first, then go dark
          if source == "dog" and follower:
              halt(f"{type(e).__name__}: {e}")
              e.dog_halted = True                        # the caller (the chat's round) does not halt it again
          raise
        finally:                                         # a failed read or a Ctrl-C too: never leave a light lit
          for lid in list(inflight):                     # drained before field.json goes: a walk taking over never meets a late write
              settle(inflight.pop(lid), lid)
          _publish(None)
          for L in lights:                               # ends dark, and wait for it (yielded: the round's dark start does it)
              if not dry and not yielded:
                  writes += 1
                  inflight[L["id"]] = pool.submit(_write, L, 0)
          for lid, fut in inflight.items():
              settle(fut, lid)
          pool.shutdown(wait=True)
        latency = {_label(L): round(1000 * sum(lat[L["id"]]) / len(lat[L["id"]])) if lat[L["id"]] else None for L in lights}
        out = {"seconds": round(time.monotonic() - t0, 1), "dark_ms": dark_ms, "writes": writes, "errors": errors,
               "rooms": rooms_seen, "stops": stops_done, "latency_ms": latency, "lights": [_label(L) for L in lights],
               "source": source, "follower": follower, "follow_error": follow_error, "yielded": yielded}
        r["state_after"] = out
        if follow_error:
            raise RuntimeError(f"the dog's follow ended with: {follow_error} (lights walked {out['seconds']} s, {writes} writes)")
        return out
