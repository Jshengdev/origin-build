"""The local HTTP API over the tool registry, plus the static remote (ui/). Stdlib only, bound to 127.0.0.1.

  python -m wtdd.api              serves http://127.0.0.1:7788/   (python -m wtdd.api 8000 for another port)
  GET  /                          ui/index.html (the remote and the map page); any other path is a file under ui/
                                  (house.svg; tokens.css is a symlink into ../../taste-library and is followed)
  GET  /tools                     [{name, doc, args}] for every tool
  POST /tools/<name>  {args}      {ok, tool, args, result}, or 500 {ok: false, tool, args, error}
  GET  /ledger?n=25               the last n ledger rows (the page polls this every 2 s)
  GET  /field                     the running walk's position, room, levels and stop from <repo>/field.json, {} when idle (polled at 10 Hz)
  GET  /chat                      the listener's heartbeat (<repo>/listen.json, written every poll): alive, armed, the gated group's name
  GET  /evals                     <repo>/evals.json, every scenario's newest trials (python -m wtdd.evals --write)
  GET  /watch                     <repo>/watch.json, the detector's newest counts and boxes plus age_ms and the intruder flag
  POST /intruder {on}             arm/disarm the intruder watch (<repo>/intruder.on; python -m wtdd.watch sounds intruder_alarm)
  GET  /shift                     the run in force {shift_id, source: file | WTDD_SHIFT | date} (a read, no row; wtdd/shift.py)
  POST /shift {name}              start a "morning" or "night" run: <repo>/shift.json, one shift.started row; any other name is a 400
  GET  /record?shift=<id>         item 10's record of one shift, exactly the JSON `python -m wtdd.record --shift <id>` prints (default: the run in
                                  force, shift.current()); an unknown shift is a 404 naming the shifts that exist, never an empty record (a read, no row)
  GET  /record/shifts             {shifts: [every shift id stamped on a row, newest first], current: shift.current()} (a read, no row)
  POST /map/restore               ui/route-saved.json's path and stops back into the map (GET /route-saved.json serves it: the guide while drawing)
  POST /field/stop                end the running walk (any source) at its next tick
  GET  /dog/state                 the shared dog session's state (+ map pose, follow status); POST /dog/drive {x,y,z}, /dog/stop
  POST /dog/calibrate {p, heading_deg | toward}   the dog is at map point p now, facing heading_deg (or facing point `toward`)
  POST /dog/follow {reach_px?}    follow ui/map.json's path from the nearest waypoint, pausing at its stops; /dog/resume continues
  POST /dog/avoid {on}            the dog's obstacle avoidance on/off with read-back (the follower turns it on itself)
  POST /dog/record {on}           on: record the believed pose while driving; off: the trace becomes ui/map.json's path + stops
  POST /dog/mark {look?, say?, ask?}   a stop with its action (the look kind, post or not, ask = the intruder check) at the current believed position, while recording
  GET  /dog/lidar                 the dog's LiDAR band in map pixels {on, n, age_ms, frame, points_px, known?, why?} (polled every 500 ms while
                                  connected); known [bool per points_px entry]: its cell already a wall in the session grid at THRESHOLD, absent
                                  with a why when there is no grid; POST /dog/lidar {on} switches the voxel stream on/off (wtdd/dog/lidar.py)
  GET  /dog/frame.jpg             the newest camera frame (no ledger row; the page's live view), 503 without a dog
  GET  /dog/scale                 the map scale in force {px_per_m, source: default | WTDD_PX_PER_M | dog_cal.json | page} (a read, no row)
  POST /dog/scale {px_per_m}      the page's slider: one dog.scale row, saved in dog_cal.json beside the tie; a bad value is a 400 naming it
  GET  /map                       ui/map.json
  POST /map  {path, lights, ...}  rewrites ui/map.json (the page saves the drawn path, lights and rooms here before every walk);
                                  the previous file is kept as ui/map.prev.json (same for a recorded route)
  GET  /dog/grid?threshold=N      the accumulated LiDAR occupancy grid in map pixels {n, cells_px, hits, cell_px, threshold, frames, source: session | ui/grid.json | null, why?} (polled every 2 s, with or without a dog);
                                  hits [int per cells_px entry]: the frames that cell was seen in, the count the threshold is applied to; absent with no grid
  POST /dog/grid {save: true} | {clear: true, why?}   save the session grid to ui/grid.json (one dog.grid_save row) or drop it after a power cycle (one dog.grid_clear row);
                                  a saved grid carries the calibration it was tied to and GET draws it through that, not the current one
  GET  /dog/objects               the live object layer {n, objects: [{id, label, p, message, thumb, pos_px, stale, ...}], windows, fov_deg, source, why?} (polled every 2 s, with or without a dog); WTDD_OBJECTS=<file> serves a fixture instead (DEMO_CACHE)
  GET  /dog/floorplan?threshold=N the newest floor plan in map pixels {ok, segments_px, classes, class_px, cell_px, ms, ts, source, why?} (a read, no row; polled every 2 s);
                                  segments_top_m [m per segments_px entry] and class_top_m {name: [m per class_px cell]}, measured tops rounded to 0.05, absent from a grid with no height profile
  POST /dog/floorplan {threshold?}   run the floor plan now (one dog.floorplan row): {ok, why?, classes, segments, ms, frames, grid_source}; 500 with no grid at all
Every tool call is already its own ledger row; the API adds one stderr log line per request and nothing else.
CORS headers (and OPTIONS) are sent so the page also works when opened from another origin; today it is same-origin.
The ui/index.html buttons are these tools: lights_status, identify, walk_path, lights_on, lights_off, lights_dim,
strip_temp, strip_fade, strip_set, light_show, hue_signal, dog_on_fire, dog_look, dog_say, dog_cmd, chat_post.
"""
from __future__ import annotations
import json
import mimetypes
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, shift, tools
from .config import ROOT
from .field import FIELD, MAP, STOP, check_path
from pathlib import Path

PICTURES = Path("~/Pictures/wtdd").expanduser()
from .ledger import log, rows

UI = ROOT / "ui"


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, "application/json", json.dumps(obj, default=str).encode())

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/tools":
            return self._json(200, tools.describe())
        if u.path == "/map":
            return self._json(200, {**json.loads(MAP.read_text()), "_version": int(MAP.stat().st_mtime)})   # the page sends it back on save
        if u.path == "/ledger":
            return self._json(200, rows(int((parse_qs(u.query).get("n") or ["20"])[0])))
        if u.path == "/field":   # a walk writes it at 10 Hz; older than BUSY_S it is a leftover of a killed process, not a walk
            from .field import BUSY_S
            live = FIELD.exists() and time.time() - FIELD.stat().st_mtime < BUSY_S
            return self._json(200, json.loads(FIELD.read_text()) if live else {})
        if u.path == "/chat":   # the listener's heartbeat (<repo>/listen.json) plus the gated group's name
            f = ROOT / "listen.json"
            d = json.loads(f.read_text()) if f.exists() else {}
            age = round(time.time() - d["t"], 1) if d.get("t") else None
            from .chat.send import TARGET_NAME
            return self._json(200, {"alive": age is not None and age < 10, "age_s": age, "armed": d.get("armed"), "armed_by": d.get("armed_by"),
                                    "pending": d.get("pending"), "group": TARGET_NAME})
        if u.path == "/evals":
            f = ROOT / "evals.json"
            return self._json(200, json.loads(f.read_text()) if f.exists() else {})
        if u.path == "/watch":
            f = ROOT / "watch.json"
            d = json.loads(f.read_text()) if f.exists() else {}
            if f.exists():
                d["age_ms"] = round((time.time() - f.stat().st_mtime) * 1000)
            d["intruder"] = (ROOT / "intruder.on").exists()
            return self._json(200, d)
        if u.path == "/shift":   # the run in force, a read (no row); a malformed shift.json is a 500 naming the file
            try:
                return self._json(200, shift.read())
            except ValueError as e:
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        if u.path in ("/record", "/record/shifts"):   # item 10's record over HTTP, a read (no row); a malformed shift.json, ledger or ui/map.json is a 500 naming it
            from . import record
            try:
                rs = rows()
                if u.path == "/record/shifts":
                    return self._json(200, {"shifts": record.shifts(rs), "current": shift.current()})
                sid = (parse_qs(u.query).get("shift") or [None])[0] or shift.current()   # record.py's default: the run in force
                if sid not in (ids := record.shifts(rs)):   # record.py's rule: no row stamped with it, no shift; never an empty record
                    return self._json(404, {"error": f"no shift {sid}: no row is stamped with it; shifts: {', '.join(ids) or 'none'}"})
                return self._json(200, record.build(sid, rs))   # what python -m wtdd.record --shift <id> prints
            except Exception as e:  # noqa: BLE001  (reported, the page shows it)
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        if u.path == "/dog/state":
            from .dog.session import DogSession
            return self._json(200, DogSession.get().state())
        if u.path == "/dog/lidar":
            from .dog.session import DogSession
            return self._json(200, DogSession.get().lidar())
        if u.path == "/dog/scale":
            from .dog.session import DogSession
            return self._json(200, DogSession.get().scale())
        if u.path == "/dog/frame.jpg":
            from .dog.session import DogSession
            try:
                return self._send(200, "image/jpeg", DogSession.get().snapshot())
            except Exception as e:  # noqa: BLE001  (no dog, or stale video: reported, the page shows nothing)
                return self._json(503, {"error": f"{type(e).__name__}: {e}"})
        # 01 · occupancy
        if u.path == "/dog/grid":   # a read: never connects, no ledger row; `source` says which grid is drawn
            from .dog import occupancy
            from .dog.session import DogSession
            try:
                t = int((parse_qs(u.query).get("threshold") or [occupancy.THRESHOLD])[0])
                return self._json(200, DogSession.get().grid_px(t))
            except Exception as e:  # noqa: BLE001  (a bad threshold or an unreadable ui/grid.json is reported, the page shows it)
                return self._json(500, {"n": 0, "cells_px": [], "error": f"{type(e).__name__}: {e}"})
        # 07 · objects
        if u.path == "/dog/objects":   # a read: never connects, no row of its own; the store's events are object.seen rows
            try:
                fixture = config.maybe("WTDD_OBJECTS")
                if fixture:
                    # DEMO_CACHE: WTDD_OBJECTS=<file> serves that file (wtdd/dog/fixtures/objects.json: two objects pinned on
                    # WALL_A of the synthetic grid, one stale) so the remote's pins can be screenshotted with no dog, no
                    # detector and no key; `source` names the file. Live: unset it; the session store fed by watch.json answers.
                    f = Path(fixture) if Path(fixture).is_absolute() else ROOT / fixture
                    return self._json(200, {**json.loads(f.read_text()), "source": f"fixture: {fixture}"})
                from .dog.session import DogSession
                return self._json(200, DogSession.get().objects_state())
            except Exception as e:  # noqa: BLE001  (a missing fixture, a bad WTDD_CAM_FOV_DEG, an unreadable watch.json: the page shows it)
                return self._json(500, {"n": 0, "objects": [], "error": f"{type(e).__name__}: {e}"})
        # 15 · floorplan
        if u.path == "/dog/floorplan":   # a read: the newest floor plan in map pixels; never runs one, no ledger row
            from .dog import occupancy
            from .dog.session import DogSession
            try:
                t = int((parse_qs(u.query).get("threshold") or [occupancy.THRESHOLD])[0])
                return self._json(200, DogSession.get().floorplan_px(t))
            except Exception as e:  # noqa: BLE001  (a bad threshold is reported, the page shows FAILED)
                return self._json(500, {"segments_px": [], "error": f"{type(e).__name__}: {e}"})
        if u.path.startswith("/pictures/"):
            name = u.path[len("/pictures/"):]
            f = PICTURES / name
            if ".." in name or not f.is_file():
                return self._json(404, {"error": f"no picture {name}"})
            return self._send(200, mimetypes.guess_type(str(f))[0] or "image/jpeg", f.read_bytes())
        rel = "index.html" if u.path in ("", "/") else u.path.lstrip("/")
        f = UI / rel
        if ".." in rel or not f.is_file():
            return self._json(404, {"error": f"no {rel}"})
        self._send(200, mimetypes.guess_type(str(f))[0] or "application/octet-stream", f.read_bytes())

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/field/stop":   # end the running walk at its next tick (lights off, its row written)
            STOP.write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
            log("api", "field stop requested")
            return self._json(200, {"ok": True})
        if u.path == "/map/restore":   # the saved route (ui/route-saved.json) back into the map; the current one goes to map.prev.json
            saved = json.loads((UI / "route-saved.json").read_text())
            m = json.loads(MAP.read_text())
            MAP.with_name("map.prev.json").write_text(json.dumps(m, indent=2) + "\n")
            m["path"], m["stops"] = saved["path"], saved.get("stops", [])
            MAP.write_text(json.dumps(m, indent=2) + "\n")
            log("api", "map restored from route-saved.json", points=len(m["path"]), stops=m["stops"])
            return self._json(200, {"ok": True, "path_pts": len(m["path"]), "stops": m["stops"]})
        if u.path == "/intruder":   # {on}: arm or disarm the intruder watch (python -m wtdd.watch acts on the file)
            on = bool(self._body().get("on", True))
            f = ROOT / "intruder.on"
            if on:
                f.write_text(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
            else:
                f.unlink(missing_ok=True)
            log("api", "intruder watch " + ("armed" if on else "disarmed"))
            return self._json(200, {"ok": True, "intruder": on})
        if u.path == "/shift":   # {name: morning | night}: one shift.started row, ok or not; a bad name is the caller's 400
            try:
                return self._json(200, {"ok": True, **shift.start(self._body().get("name"))})
            except Exception as e:  # noqa: BLE001  (the row has it; a bad name or a malformed shift.json is a 400, anything else ours)
                return self._json(400 if isinstance(e, ValueError) else 500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        if u.path == "/map":
            data = self._body()
            seen = data.pop("_version", None)
            if seen is not None and MAP.exists() and int(MAP.stat().st_mtime) != int(seen):   # a stale page must not overwrite a recording or another tab's save
                log("api", "map NOT saved: stale page", page=seen, file=int(MAP.stat().st_mtime))
                return self._json(409, {"ok": False, "error": "not saved: the map changed on the server since this page loaded (a recording, or another tab). Reload the page, then redo the edit."})
            problems = check_path(data.get("path", []), data.get("rooms", []))
            if problems and data.get("path"):   # an unrunnable path is refused, with the points named; the page keeps the edit
                log("api", "map NOT saved", problems=len(problems))
                return self._json(400, {"ok": False, "error": "not saved: " + "; ".join(problems)})
            if MAP.exists():
                MAP.with_name("map.prev.json").write_text(MAP.read_text())   # the previous route survives one overwrite
            MAP.write_text(json.dumps(data, indent=2) + "\n")
            log("api", "map saved", points=len(data.get("path", [])), stops=len(data.get("stops", [])))
            return self._json(200, {"ok": True, "_version": int(MAP.stat().st_mtime)})
        if u.path in ("/dog/drive", "/dog/stop", "/dog/calibrate", "/dog/follow", "/dog/resume", "/dog/avoid", "/dog/record", "/dog/mark", "/dog/lidar"):
            import math
            from .dog import nav
            from .dog.session import DogSession
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            s = DogSession.get()
            try:
                if u.path == "/dog/stop":
                    out = s.stop()
                elif u.path == "/dog/drive":
                    out = s.drive(body.get("x", 0), body.get("y", 0), body.get("z", 0))
                elif u.path == "/dog/calibrate":      # {p: [px, py], heading_deg} or {p, toward: [px, py]} (face that point)
                    p = body["p"]
                    h = math.radians(body["heading_deg"]) if "heading_deg" in body else nav.heading_of(p, body["toward"])
                    out = {"map": s.calibrate(p, h)}
                elif u.path == "/dog/follow":         # the map's path and stops, from the start (or the nearest waypoint)
                    m = json.loads(MAP.read_text())
                    problems = check_path(m["path"], m.get("rooms", []))
                    if problems:
                        raise ValueError("the path cannot be followed: " + "; ".join(problems))
                    out = {"follow": s.follow(m["path"], [int(i) for i in m.get("stops", [])], float(body.get("reach_px", 30)), avoid=bool(body.get("avoid", True)))}
                elif u.path == "/dog/avoid":          # {on: true|false}: the dog's own obstacle avoidance, read back
                    out = {"avoid": s.avoid(bool(body.get("on", True)))}
                elif u.path == "/dog/mark":           # {look?, say?}: a stop with its action at the current believed position, while recording
                    out = {"rec": s.mark(body.get("look", "tilt"), bool(body.get("say", True)), bool(body.get("ask", False)))}
                elif u.path == "/dog/record":         # {on: true} start; {on: false} stop and write the trace as the map's path + stops
                    rec = s.record(bool(body.get("on", True)))
                    if not rec["active"]:             # written even with problems (the drive is not lost); they are returned and shown
                        m = json.loads(MAP.read_text())
                        MAP.with_name("map.prev.json").write_text(json.dumps(m, indent=2) + "\n")   # the previous route survives one overwrite
                        if len(rec["path"]) < 2:
                            raise ValueError(f"recording too short to be a route ({len(rec['path'])} point); the map was not changed")
                        m["path"], m["stops"], m["actions"] = rec["path"], rec["stops"], rec["actions"]
                        MAP.write_text(json.dumps(m, indent=2) + "\n")
                        rec["problems"] = check_path(rec["path"], m.get("rooms", []))
                        log("api", "map saved from the recorded route", points=len(rec["path"]), stops=rec["stops"], problems=len(rec["problems"]))
                    out = {"rec": rec}
                elif u.path == "/dog/lidar":          # {on: true|false}: the dog's LiDAR voxel stream (GET /dog/lidar reads it)
                    out = {"lidar": s.lidar(bool(body.get("on", True)))}
                else:
                    out = {"follow": s.resume()}
                return self._json(200, {"ok": True, **out})
            except Exception as e:  # noqa: BLE001  (a connect failure or a refused follow is reported, never hidden)
                return self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        # 01 · occupancy
        if u.path == "/dog/grid":   # {save: true} (default) or {clear: true, why?}; each is one ledger row, ok or not
            from .dog.session import DogSession
            body, s = self._body(), DogSession.get()
            try:
                out = s.grid_clear(str(body.get("why") or "cleared from the page")) if body.get("clear") else s.grid_save()
                return self._json(200, {"ok": True, **out})
            except Exception as e:  # noqa: BLE001  (a save with no grid is a visible FAILED and a failed row, never an empty file)
                return self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        if u.path == "/dog/scale":   # {px_per_m}: the page's slider; one dog.scale row, ok or not; no value is a bad value, not a read
            from .dog.session import DogSession
            v = self._body().get("px_per_m")
            try:
                return self._json(200, {"ok": True, **DogSession.get().scale("none sent" if v is None else v)})
            except Exception as e:  # noqa: BLE001  (the row has it; a bad value is the caller's 400, anything else ours)
                return self._json(400 if isinstance(e, ValueError) else 500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        # 15 · floorplan
        if u.path == "/dog/floorplan":   # {threshold?}: the button, always one run and one dog.floorplan row, ok or not
            from .dog import occupancy
            from .dog.session import DogSession
            try:
                t = self._body().get("threshold")   # absent only: a posted 0 reaches run() and fails loud with its row
                out = DogSession.get().floorplan(occupancy.THRESHOLD if t is None else int(t))
                return self._json(200, out)   # ok=false when no wall was found: the row and `why` say so
            except Exception as e:  # noqa: BLE001  (no grid at all is a failed row and a visible FAILED, never an empty plan)
                return self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        if not u.path.startswith("/tools/"):
            return self._json(404, {"error": "not found"})
        name, args = u.path[len("/tools/"):], self._body()
        t0 = time.perf_counter()
        try:
            out = tools.call(name, **args)
            log("api", f"{name} ok", ms=round((time.perf_counter() - t0) * 1000))
            return self._json(200, {"ok": True, "tool": name, "args": args, "result": out})
        except Exception as e:  # noqa: BLE001  (the tool's own ledger row has the failure; the API reports it truthfully)
            log("api", f"{name} FAILED", err=f"{type(e).__name__}: {str(e)[:100]}", ms=round((time.perf_counter() - t0) * 1000))
            return self._json(500, {"ok": False, "tool": name, "args": args, "error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *a):  # one line per request through our logger
        log("api", fmt % a)


def main(argv: list[str] | None = None) -> int:
    import os
    os.environ["WTDD_API_PROCESS"] = "1"   # this process owns the dog session; others reach it over HTTP
    port = int((argv or sys.argv[1:] or ["7788"])[0])
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    log("api", f"serving http://127.0.0.1:{port}/  tools={len(tools.registry())} ui={UI}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
