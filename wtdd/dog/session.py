"""One WebRTC session to the dog per process, shared by every tool, the API and the remote.

The dog accepts one peer at a time and keeps the slot for about ten seconds after a close, so connecting per command is
slow and collides. This module holds a single Body on a background asyncio loop; synchronous callers (tools, HTTP
handlers) submit coroutines with run(). The API process owns the dog while it runs (WTDD_API_PROCESS=1); other
processes reach the dog through the API (wtdd/commands.py) so two peers never fight for the slot. If the 20 Hz state
stream goes quiet for STALE_MS (the dog was power-cycled or left its hotspot) the next call closes the dead peer and
connects once more, logged; there is no reconnect loop.

drive() is hold-to-move: the remote refreshes a velocity every 200 ms while a key is down; the loop republishes it at
MOVE_HZ and sends StopMove 0.6 s after the last refresh or on stop(). Speeds are capped at DRIVE_MAX.

Where it thinks it is: calibrate(p, heading) ties the odometry pose now to a map point (wtdd/dog/nav.py); state() then
carries "map": {p, heading_deg}. follow(path, stops) switches the dog's obstacle avoidance on (read back, refused
otherwise) and is a task that feeds nav.steer velocities into the same drive loop, waypoint by waypoint, pausing at the
map's stops until resume(); stop() cancels it. With avoidance on, the drive loop sends velocities through the
OBSTACLES_AVOID service (MOVE 1003, no ack) instead of SPORT Move; the state read-back is the receipt. record(True)
records the believed pose while Johnny drives, mark(look, say) adds a stop at the current spot with the action to
replay there, record(False) returns the thinned trace as {path, stops, actions} and the API writes it into
ui/map.json: the route the dog drove, and what it did along it, is what it replays. One dog.calibrate and one dog.follow
row; a failed or cancelled follow says so in state().follow.error.

The looks, measured on this dog (firmware < 1.1.15, motion mode mcf) on 2026-09-13:
  level: BalanceStand, frame.
  tilt:  BalanceStand, Pose on, Euler y=+0.3 (nose down, +15 deg at 0.7 s): frame look-down.jpg (the floor) at 0.7 s,
         1.6 s total, Euler y=-0.3 (nose up, -15 deg from 0.36 s to 0.79 s): frame look-tilt.jpg (the room) at 0.6 s,
         Euler 0, Pose off. Two frames per nod, both with the IMU pitch; the vision model picks the one to send. The
         pose is a nod, not a hold, and only fires as this down-then-up pair: a single cold Euler does nothing and
         re-sending it every 2 s does nothing.
  sit:   Sit, 1.8 s, frame at 48 deg up, RiseSit.
Frames land in ~/Pictures/wtdd/look-<kind>.jpg (the API serves them at /pictures/<name>). snapshot() is the
un-receipted newest frame behind GET /dog/frame.jpg, the remote's live view at a few frames per second. lidar(on) is
the dog's own LiDAR band on the map behind GET/POST /dog/lidar (wtdd/dog/lidar.py), also un-receipted; every decoded
frame also lands in the session's occupancy grid (wtdd/dog/occupancy.py) behind GET/POST /dog/grid; save and clear
are rows, reads are not. The floor plan (wtdd/dog/floorplan.py) runs on a copy of that grid on its own thread, started
by lidar(on=True), at most once per FLOORPLAN_S and only when the grid advanced, and on POST /dog/floorplan; each run
is one dog.floorplan row, and GET /dog/floorplan is a read. Objects: every detector window (<repo>/watch.json) is
placed on that grid behind GET /dog/objects by wtdd/dog/objects.py, on an 'objects' thread the first GET starts; its
rows are object.seen. Blob labels: POST /dog/blobs at a stop names what the floor plan drew from a photo of it
(wtdd/dog/blobs.py, one blob.labelled row per label); GET /dog/blobs pins the newest labels and GET /dog/floorplan
greys the runs a furniture label moved.
"""
from __future__ import annotations
import asyncio
import copy
import io
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from .. import config, decide
from ..ledger import log, step
from . import blobs, floorplan, lidar, nav, objects, occupancy
from .body import MOVE_HZ, Body

PICTURES = Path("~/Pictures/wtdd").expanduser()
CAL_FILE = Path(__file__).resolve().parents[2] / "dog_cal.json"   # the last human calibration, so an API restart keeps it (runtime file)
GRID_FILE = Path(__file__).resolve().parents[2] / "ui" / "grid.json"   # the last saved occupancy grid, POST /dog/grid {save} (runtime file, gitignored)
DRIVE_MAX = {"x": 0.4, "y": 0.4, "z": 0.6}   # m/s, m/s, rad/s for the hand-driven remote
DRIVE_HOLD_S = 0.6                            # a velocity older than this is a released key
LOOKS = ("level", "tilt", "sit")
TILT_MIN_DEG = 8.0                            # a tilt frame counts only if the IMU shows at least this much nose-up
STALE_MS = 5000                               # state stream (20 Hz) older than this: the peer is dead, reconnect once
PROBE_BACKOFF_S = 15.0                        # after a failed connect, callers get the same error without a new probe row for this long
WP_TIMEOUT_S = 30.0                           # a waypoint not reached in this long fails the follow (no retry)
REC_HZ, REC_MIN_PX, REC_STEP_PX = 5.0, 10, 45   # route recording: sample rate, min move per sample, waypoint spacing (about 0.4 m)
START_PX = 90                                 # a dog this close to the path's first point replays from the start (a loop's end is also its start)
STOP_TIMEOUT_S = 180.0                        # a stop without resume for this long fails the follow


class DogSession:
    _inst: "DogSession | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "DogSession":
        with cls._lock:
            if cls._inst is None:
                cls._inst = cls()
            return cls._inst

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="dog-session", daemon=True).start()
        self.body: Body | None = None
        self._connecting = asyncio.Lock()   # one connect at a time: the dog takes one peer (a frame pull and a look can race)
        self._unreachable: tuple[float, str] | None = None   # (when, why) of the last failed connect: not re-probed for PROBE_BACKOFF_S
        self.vel = (0.0, 0.0, 0.0)
        self.vel_t = 0.0
        self.moving = False
        self._driver: asyncio.Task | None = None
        self.cal: dict[str, Any] | None = None       # odometry <-> map tie (nav.calibration); None until "the dog is here"
        if CAL_FILE.exists():   # a calibration survives an API restart, not a dog power cycle (the odometry frame resets then)
            self.cal = json.loads(CAL_FILE.read_text())
            self.recheck = True   # loaded, not confirmed: the remote asks for the dog's position until someone drags it
            log("dog", "calibration loaded, to be confirmed", file=CAL_FILE.name, map=self.cal.get("map"), at=self.cal.get("at"))
        self.follow_state: dict[str, Any] = {}       # the follower's live status (GET /dog/state .follow)
        self._follower: asyncio.Task | None = None
        self.rec: dict[str, Any] | None = None       # a route being recorded by driving: {points, marks, started}
        self._recorder: asyncio.Task | None = None
        self.grid: occupancy.Grid | None = None      # every LiDAR window this session, accumulated (odometry metres); None until the first frame
        self._grid_lock = threading.Lock()           # frames arrive on the driver's dispatcher, reads on HTTP threads
        self._grid_file: tuple[float, occupancy.Grid] | None = None   # (mtime, grid) of ui/grid.json as last loaded
        self._fp: tuple[dict, str, dict | None] | None = None   # the newest floor plan: (floorplan.run's result, its grid source, a file grid's saved cal)
        self._fp_t: float | None = None       # monotonic time of the last floor plan on the session grid
        self._fp_frames: int | None = None    # grid.frames it ran on
        self._fp_lock = threading.Lock()      # one floor plan at a time: the ticker and the button
        self._fp_thread: threading.Thread | None = None   # the ticker, started once by lidar(on=True), never by _on_frame
        self.fp_errors = 0                    # ticks that raised (each already a failed row)
        self.objects = objects.Store(draft=objects.drafter())   # what the detector boxed, placed on the grid (GET /dog/objects)
        self._objects_lock = threading.Lock()        # one detector window at a time: the objects thread and GET /dog/objects both tick
        self._objects_ticker: threading.Thread | None = None   # started by the first objects_state()
        self._labels: dict[str, Any] | None = None   # the newest blob press: {labels, source, ts, why?}; a FAILED press is labels [] and why

    # ---- plumbing
    def run(self, coro: Awaitable[Any], timeout: float = 120.0) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _ensure(self) -> Body:
      async with self._connecting:
        if self.body is not None:
            st = self.body.state()
            if st and st["age_ms"] > STALE_MS:   # the peer is gone (power cycle, hotspot drop): one logged reconnect, no loop
                log("dog", "WARN session stale, reconnecting once", age_ms=st["age_ms"], state_n=st["n"])
                self.recheck = True   # the page asks for the dog's position to be confirmed (a power cycle resets the odometry frame)
                if (g := self.grid) is not None:   # not cleared here: the code cannot tell a hotspot drop (odometry kept) from a power cycle (reset)
                    log("dog", "WARN grid kept across the reconnect: if the dog was power-cycled its odometry frame reset; clear it (POST /dog/grid {clear: true})", grid_frames=g.frames)
                if self._driver:
                    self._driver.cancel()
                try:
                    await asyncio.wait_for(self.body.close(), 5)
                except Exception as e:  # noqa: BLE001  (the old peer is already dead; a failed close is logged, then replaced)
                    log("dog", "old session close failed", err=f"{type(e).__name__}: {str(e)[:80]}")
                self.body = None
        if self.body is None:
            if self._unreachable and time.monotonic() - self._unreachable[0] < PROBE_BACKOFF_S:
                raise RuntimeError(f"dog unreachable {round(time.monotonic() - self._unreachable[0])} s ago, not probing again yet: {self._unreachable[1]}")
            b = Body()
            try:
                await b.connect()
            except Exception as e:
                self._unreachable = (time.monotonic(), f"{type(e).__name__}: {str(e)[:120]}")
                raise
            self._unreachable = None
            self.body = b
            self._driver = self.loop.create_task(self._drive_loop())
        return self.body

    async def with_body(self, fn: Callable[[Body], Awaitable[Any]]) -> Any:
        return await fn(await self._ensure())

    def connected(self) -> bool:
        return self.body is not None

    def state(self) -> dict[str, Any]:
        st = self.body.state() if self.body else None
        return {"connected": self.body is not None, "moving": self.moving, "vel": list(self.vel), "state": st,
                "map": self.map_pose(st), "calibrated": self.cal is not None, "follow": self.follow_state,
                "avoid": self.body._avoid if self.body else None, "recheck": self.recheck,
                "rec": {"active": True, "n": len(self.rec["points"]), "points": self.rec["points"], "marks": [m["p"] for m in self.rec["marks"]],
                        "actions": [m["action"] for m in self.rec["marks"]]} if self.rec else None}

    # ---- recording a route by driving (the trace of where it thinks it is becomes the map's path)
    def record(self, on: bool) -> dict[str, Any]:
        """on: start sampling map_pose() at REC_HZ (a point every REC_MIN_PX). off: stop and return {path, stops}: the
        trace thinned to REC_STEP_PX between waypoints, marks mapped to their nearest waypoint. One dog.record row."""
        if on:
            if self.cal is None:
                raise RuntimeError("not calibrated: drag the dog to where it is first")
            if self.rec:
                raise RuntimeError("already recording")
            self.run(self._ensure())
            pose = self.map_pose()
            if pose is None:
                raise RuntimeError("no pose yet")
            self.rec = {"points": [pose["p"]], "marks": [], "started": time.time()}
            self._recorder = asyncio.run_coroutine_threadsafe(self._record(), self.loop)
            log("dog", "recording route", start=pose["p"])
            return {"active": True, "n": 1}
        if not self.rec:
            raise RuntimeError("not recording")
        if self._recorder:
            self._recorder.cancel()
        rec, self.rec = self.rec, None
        pts = rec["points"]
        path: list = [pts[0]]
        for q in pts[1:]:
            if math.dist(q, path[-1]) >= REC_STEP_PX:
                path.append(q)
        if math.dist(pts[-1], path[-1]) > 1:
            path.append(pts[-1])
        actions: dict[str, dict] = {}
        for m in rec["marks"]:   # each mark becomes the nearest waypoint, carrying the action recorded there
            i = min(range(len(path)), key=lambda i: math.dist(path[i], m["p"]))
            actions[str(i)] = m["action"]
        stops = sorted(int(k) for k in actions)
        length = round(sum(math.dist(path[i - 1], path[i]) for i in range(1, len(path))))
        with step("dog", "dog.record", "map", {"samples": len(pts), "marks": rec["marks"]}) as r:
            r["state_after"] = {"path_pts": len(path), "stops": stops, "actions": actions, "length_px": length, "seconds": round(time.time() - rec["started"], 1)}
        log("dog", "route recorded", samples=len(pts), waypoints=len(path), stops=stops, length_px=length)
        return {"active": False, "path": path, "stops": stops, "actions": actions, "length_px": length, "samples": len(pts)}

    def mark(self, look: str = "tilt", say: bool = True, ask: bool = False) -> dict[str, Any]:
        """A stop at the dog's current believed position (while recording), with the action to replay there: the look
        kind (tilt | level | sit), whether to post the sentence, and ask = the intruder check (if someone is in frame
        the round asks the group "who dis?!" and holds for the verdict; only stops marked ask do). The remote marks one
        whenever a look button is pressed during a recording, so the recording holds what the dog did, not only where."""
        if not self.rec:
            raise RuntimeError("not recording")
        pose = self.map_pose()
        if pose is None:
            raise RuntimeError("no pose: the dog is not connected or not calibrated")
        if look not in LOOKS:
            raise ValueError(f"look must be one of {LOOKS}, got {look!r}")
        self.rec["marks"].append({"p": pose["p"], "action": {"look": look, "say": bool(say), "ask": bool(ask)}})
        log("dog", "stop marked", p=pose["p"], look=look, say=say, ask=ask, n=len(self.rec["marks"]))
        return {"marks": self.rec["marks"]}

    async def _record(self) -> None:
        try:
            while self.rec:
                pose = self.map_pose()
                if pose and math.dist(pose["p"], self.rec["points"][-1]) >= REC_MIN_PX:
                    self.rec["points"].append(pose["p"])
                await asyncio.sleep(1 / REC_HZ)
        except asyncio.CancelledError:
            return

    def avoid(self, on: bool) -> bool:
        """The dog's own obstacle avoidance, with read-back (wtdd/dog/body.py avoid). While it is on, every velocity this
        session sends (hold-to-drive and the follower) goes through the avoidance service instead of the sport service."""
        return self.run(self.with_body(lambda b: b.avoid(on)))

    def lidar(self, on: bool | None = None) -> dict[str, Any]:
        """GET/POST /dog/lidar. on=True switches the dog's LiDAR voxel stream on (connecting first), on=False off, None
        reads. Returns {on, n (frames), errors, cb_errors (frames the grid failed to take), grid_frames, age_ms, frame,
        points_px, why?}; switching on hands every frame to the session grid (_on_frame). points_px is the newest frame's
        floor-to-head band in map pixels through the calibration (wtdd/dog/lidar.py), [] with `why` when there is no
        frame yet, the stream is off, or the dog is not calibrated. No ledger row: a read, like /dog/state."""
        if on is True or (on is False and self.body is not None):
            self.run(self.with_body(lambda b: b.lidar_on(self._on_frame) if on else b.lidar_off()))
        if on is True and self._fp_thread is None:   # the floor plan's own thread, off the driver's dispatcher
            self._fp_thread = threading.Thread(target=self._fp_loop, name="floorplan", daemon=True)
            self._fp_thread.start()
        if self.body is None:
            return {"on": False, "n": 0, "errors": 0, "cb_errors": 0, "grid_frames": g.frames if (g := self.grid) is not None else 0,
                    "age_ms": None, "frame": None, "points_px": [], "why": "not connected"}
        lp = self.body.lidar_points()
        out = {k: lp[k] for k in ("on", "n", "errors", "cb_errors", "age_ms", "frame", "utlidar_pose")}
        out["grid_frames"] = g.frames if (g := self.grid) is not None else 0
        st = self.body.state()
        if lp["points"] is None:
            return {**out, "points_px": [], "why": "no frame yet" if lp["on"] else "lidar off"}
        if not self.cal or not st or not st.get("position") or not st.get("rpy"):
            return {**out, "points_px": [], "why": "not calibrated"}
        xy = lidar.top_down(lp["points"])
        return {**out, "n_xy": len(xy), "points_px": lidar.to_map_points(xy, self.cal, st["position"], st["rpy"][2])}

    # ---- the occupancy grid (wtdd/dog/occupancy.py): every LiDAR window this session, accumulated in odometry metres
    def _on_frame(self, d: dict) -> None:
        """Body._on_lidar hands every decoded frame here, on the driver's dispatcher: one count per cell per frame. A raise
        is counted by Body (cb_errors, on GET /dog/lidar and /dog/grid) and logged there; it never stops the stream."""
        with self._grid_lock:
            if self.grid is None:
                self.grid = occupancy.Grid.from_frame(d)
                log("dog", "grid started", frame_id=d["frame"], resolution=d["resolution"], origin=[round(v, 2) for v in d["origin"][:2]])
            t0 = time.perf_counter()
            touched = self.grid.update_frame(d)
            if self.grid.frames % 100 == 0:
                log("dog", "grid", frames=self.grid.frames, cells=int((self.grid.counts > 0).sum()), shape=self.grid.shape,
                    touched=touched, ms=round((time.perf_counter() - t0) * 1000, 1), z_rebased=self.grid.z_rebased, z_dropped=self.grid.z_dropped)

    def grid_px(self, threshold: int = occupancy.THRESHOLD) -> dict[str, Any]:
        """GET /dog/grid: the cells seen threshold+ times in map pixels through the calibration (occupancy.response),
        `source` naming the grid drawn, plus cb_errors while a dog is connected. No ledger row: a read, like /dog/state."""
        errs = {"cb_errors": self.body.lidar_points()["cb_errors"]} if self.body else {}
        with self._grid_lock:
            if self.grid is not None:
                return {**occupancy.response(self.grid, self.cal, threshold, "session"), **errs}
            # DEMO_CACHE: ui/grid.json, the last grid saved by POST /dog/grid {save: true} (or a fixture planted with
            # `python -m wtdd.dog.occupancy --replay wtdd/dog/fixtures/voxel_frames.npz --png /tmp/g.png --save ui/grid.json`),
            # drawn while this session has taken no LiDAR frame so the page shows the site with no dog present, through the
            # calibration saved with it (its cells are in the odometry frame of the power-on that made them; a planted
            # fixture has none and takes the session's). Live path: POST /dog/lidar {on: true}; the first frame starts the
            # session grid and `source` flips to "session".
            if GRID_FILE.exists():
                mt = GRID_FILE.stat().st_mtime
                if self._grid_file is None or self._grid_file[0] != mt:
                    g = occupancy.Grid.load(GRID_FILE)
                    self._grid_file = (mt, g)
                    log("dog", "grid loaded from file", file="ui/grid.json", frames=g.frames, cells=int((g.counts > 0).sum()), frame_id=g.frame_id,
                        cal_at=g.cal.get("at") if g.cal else "none saved: drawn through the session's calibration")
                fg = self._grid_file[1]
                return {**occupancy.response(fg, fg.cal or self.cal, threshold, "ui/grid.json"), **errs}
        return {**occupancy.response(None, self.cal, threshold, None), **errs}

    def grid_save(self) -> dict[str, Any]:
        """POST /dog/grid {save: true}: the session grid to ui/grid.json, with the calibration it is drawn through (so a
        power cycle and a new tie do not move the saved site). One dog.grid_save row; with no session grid the row fails
        (RuntimeError) and no file is written, never an empty one."""
        with self._grid_lock:
            g = self.grid
            args = {"file": "ui/grid.json", "frames": g.frames if g else 0, "frame_id": g.frame_id if g else None,
                    "resolution": g.resolution if g else None, "cal_at": self.cal.get("at") if self.cal else None}
            with step("dog", "dog.grid_save", "map", args, {"file_bytes": GRID_FILE.stat().st_size if GRID_FILE.exists() else None}) as r:
                if g is None:
                    raise RuntimeError("no grid this session: switch the LiDAR on and walk first (POST /dog/lidar {on: true})")
                g.cal = dict(self.cal) if self.cal else None
                if g.cal is None:
                    log("dog", "WARN grid saved without a calibration: it will be drawn through whatever calibration exists when it is read",
                        frames=g.frames)
                p = g.save(GRID_FILE)
                self._grid_file = None   # the next fallback re-reads the file, whatever the mtime resolution
                r["state_after"] = {"file": "ui/grid.json", "bytes": p.stat().st_size, "cells": int((g.counts > 0).sum()),
                                    "frames": g.frames, "extent_m": g.extent_m()}
        return r["state_after"]

    def grid_clear(self, why: str) -> dict[str, Any]:
        """POST /dog/grid {clear: true, why}: drops the session grid (after a power cycle the odometry frame reset, so the
        old counts belong to another frame). One dog.grid_clear row, also with no grid. ui/grid.json is left as it is.
        The floor plan goes with its grid: its walls belong to the same old frame."""
        with self._grid_lock:
            g = self.grid
            before = {"frames_before": g.frames if g else 0, "cells_before": int((g.counts > 0).sum()) if g else 0}
            with step("dog", "dog.grid_clear", "map", {"why": why, **before}) as r:
                self.grid = None
                r["state_after"] = {"cleared": True}
        with self._fp_lock:   # after a run in flight on the old grid has landed, so its result is dropped too
            self._fp = self._fp_t = self._fp_frames = None
        self._labels = None   # the labels named that grid's runs
        return {"cleared": True, "frames_before": before["frames_before"]}

    # ---- the floor plan (wtdd/dog/floorplan.py): walls and furniture from the grid's height profile, off the dispatcher
    def floorplan_tick(self, now: float | None = None) -> dict[str, Any] | None:
        """One floorplan.run on a copy of the session grid when grid.frames advanced since the last run and at least
        FLOORPLAN_S after it, else None. Called by the ticker (_fp_loop), never by _on_frame or a GET."""
        now = time.monotonic() if now is None else now
        with self._grid_lock:   # copied under the dispatcher's lock, classified outside it
            g = self.grid
            if g is None or g.frames == self._fp_frames or (self._fp_t is not None and now - self._fp_t < floorplan.FLOORPLAN_S):
                return None
            snap, self._fp_t, self._fp_frames = copy.deepcopy(g), now, g.frames
        return self._fp_run(snap, occupancy.THRESHOLD, "session", None)

    def _fp_run(self, g: occupancy.Grid, threshold: int, source: str, cal: dict | None) -> dict[str, Any]:
        with self._fp_lock:
            res = floorplan.run(g, threshold, grid_source=source)
            self._fp = (res, source, cal)
        return res

    def _fp_loop(self) -> None:
        """The ticker thread: floorplan_tick every FLOORPLAN_S / 4. A raise (its failed row already written by step) is
        counted, logged and becomes the newest result, so the page shows FAILED in red; the loop goes on."""
        while True:
            time.sleep(floorplan.FLOORPLAN_S / 4)
            try:
                self.floorplan_tick()
            except Exception as e:  # noqa: BLE001  (counted, logged, served as a FAILED floor plan; never hidden)
                self.fp_errors += 1
                err = f"{type(e).__name__}: {str(e)[:120]}"
                log("floorplan", "WARN tick FAILED", err=err, errors=self.fp_errors)
                self._fp = ({"ok": False, "why": f"FAILED floor plan tick ({self.fp_errors} so far): {err}", "threshold": occupancy.THRESHOLD,
                             "frames": self._fp_frames, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, "session", None)

    def floorplan(self, threshold: int = occupancy.THRESHOLD) -> dict[str, Any]:
        """POST /dog/floorplan, the button: always one run and one dog.floorplan row, on a copy of the session grid,
        else on ui/grid.json; with no grid at all (or an unreadable file) one failed row and a RuntimeError. Any raise
        also becomes the newest result, as a FAILED tick does, so every later GET keeps it red with its reason until the
        next run (the 500 alone lasts one 2 s poll). Returns the run's JSON summary {ok, why?, threshold, frames, cells,
        classes, segments, ms, ts, grid_source}."""
        with self._grid_lock:
            g = copy.deepcopy(self.grid) if self.grid is not None else None
            if g is not None:
                self._fp_t, self._fp_frames = time.monotonic(), g.frames
        source = "session" if g is not None else "ui/grid.json" if GRID_FILE.exists() else None
        try:
            if g is None:
                # DEMO_CACHE: ui/grid.json, the last saved grid (or a fixture planted with `python -m wtdd.dog.floorplan
                # --replay wtdd/dog/fixtures/voxel_furniture.npz --png /tmp/fp.png --save ui/grid.json`), classified when
                # this session has taken no LiDAR frame, so the page shows a floor plan with no dog; its row says
                # cached=True, source="stub", and it is drawn through the calibration saved with it. Live path: POST
                # /dog/lidar {on: true}; the ticker then runs on the session grid and `source` flips to "session".
                why = None
                try:
                    g = occupancy.Grid.load(GRID_FILE) if source else None
                except Exception as e:  # noqa: BLE001  (an unreadable file is the failed row below, never skipped)
                    why = f"ui/grid.json unreadable: {type(e).__name__}: {e}"
                if g is None:
                    with step("dog", "dog.floorplan", "map", {"threshold": threshold, "grid_source": source}, {"cells": 0, "frames": 0}) as r:
                        if why:   # the DEMO_CACHE file's own failure is a stub row too; no grid at all stays live
                            r["cached"], r["source"] = True, "stub"
                        raise RuntimeError(why or "no grid: no LiDAR frames this session and no ui/grid.json")
            res = self._fp_run(g, threshold, source, g.cal if source == "ui/grid.json" else None)
        except Exception as e:  # noqa: BLE001  (its failed row is written; kept as the newest result, then re-raised for the 500)
            with self._fp_lock:
                self._fp = ({"ok": False, "why": f"FAILED floor plan press: {type(e).__name__}: {str(e)[:120]}", "threshold": threshold,
                             "frames": g.frames if g is not None else 0, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, source, None)
            raise
        return {k: v for k, v in res.items() if k not in ("cls", "runs", "origin", "resolution")}

    def floorplan_px(self, threshold: int = occupancy.THRESHOLD) -> dict[str, Any]:
        """GET /dog/floorplan: the newest floor plan in map pixels (floorplan.to_px) through a file grid's saved
        calibration, else the session's: {ok, threshold, frames, ms, ts, source, cell_px, classes, segments_px,
        class_px, why?}. A read: it never runs one and writes no row; nothing yet, not calibrated, no wall, a FAILED
        tick and a result at another threshold each say why."""
        empty = {"segments_px": [], "classes": {}, "class_px": {}}
        if self._fp is None:
            return {**empty, "source": None, "why": "no floor plan yet: switch the LiDAR on and walk, or press floor plan (POST /dog/floorplan)"}
        res, source, fcal = self._fp
        base = {"ok": res["ok"], "threshold": res["threshold"], "frames": res["frames"], "ms": res.get("ms"), "ts": res["ts"], "source": source}
        if "cls" not in res:   # the ticker's last attempt raised
            return {**empty, **base, "why": res["why"]}
        if (cal := fcal or self.cal) is None:
            return {**empty, **base, "why": "not calibrated: drag the dog to where it is (POST /dog/calibrate)"}
        if (lab := self._labels_now()) and lab["labels"]:   # 16: a furniture label greys its run; the geometry stays 15's
            e = blobs.erase(res, lab["labels"])
            res = {**res, "cls": e["cls"], "segments": e["segments"], "classes": floorplan._counts(e["cls"]), "moved": e["moved"]}
        out = {**base, "classes": res["classes"], **floorplan.to_px(res, cal), "moved": res.get("moved", [])}
        whys = ([res["why"]] if not res["ok"] else []) + \
            ([f"the newest floor plan is at threshold {res['threshold']}, not {threshold}: press floor plan"] if threshold != res["threshold"] else [])
        return {**out, "why": " · ".join(whys)} if whys else out

    # ---- blob labels (wtdd/dog/blobs.py): a word and a p for what the floor plan drew, from a photo of it
    def blobs_label(self, threshold: int = occupancy.THRESHOLD) -> dict[str, Any]:
        """POST /dog/blobs, the press at a stop: the live frame, the dog's pose (as objects_state reads it),
        WTDD_CAM_FOV_DEG and a copy of the session grid -> blobs.label_stop; its rows are the blob.labelled rows. No dog, no
        pose, no grid or no field of view is one failed blob.labelled row (app unitree), never a connect, and a raise; a
        failed press becomes the newest labels, so GET /dog/blobs keeps it red. Returns {labelled, skipped, failed, labels}."""
        fov = config.maybe("WTDD_CAM_FOV_DEG")
        st = self.body.state() if self.body else None
        pose = {"position": list(st["position"][:2]), "yaw": st["rpy"][2]} if st and st.get("position") and st.get("rpy") else None
        why = ("no dog: connect it first (any dog command), then press at a stop" if self.body is None else
               "no pose: the dog's state has no position or yaw yet" if pose is None else
               "no grid: switch the LiDAR on and walk first (POST /dog/lidar {on: true})" if self.grid is None else
               objects.FOV_WHY if not fov else None)
        try:
            if why:
                raise RuntimeError(why)
            from PIL import Image
            img = Image.open(io.BytesIO(self.snapshot())).convert("RGB")
            with self._grid_lock:
                g = copy.deepcopy(self.grid)
            out = blobs.label_stop(g, img, pose, float(fov), threshold)
        except Exception as e:  # noqa: BLE001  (a press that failed before any blob: one failed row, kept red on the page, raised for the 500)
            self._labels = {"labels": [], "source": "session", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "why": f"FAILED name blobs press: {type(e).__name__}: {str(e)[:160]}"}
            before = {"connected": self.body is not None, "pose": pose, "fov_deg": fov, "grid_frames": self.grid.frames if self.grid else 0}
            with step("blobs", "blob.labelled", "unitree", {"blob_id": None, "threshold": threshold, "shift_id": decide.shift_id()}, before):
                raise
        self._labels = {"labels": out["labels"], "source": "session", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        return {"labelled": len(out["labels"]), "skipped": out["skipped"], "failed": sum(1 for x in out["labels"] if x.get("error")),
                "labels": [{k: v for k, v in x.items() if k != "cells"} for x in out["labels"]]}

    def _labels_now(self) -> dict[str, Any] | None:
        """The labels in force: a planted file under WTDD_BLOBS, else the newest press's, else None."""
        f = config.maybe("WTDD_BLOBS")
        if f:
            # DEMO_CACHE: WTDD_BLOBS=<file> serves that file's {labels: [records]} (wtdd/dog/fixtures/blobs.json: the
            # shelf's run named shelf at p 0.91, the far wall named wall, the table's label FAILED; every cell one the
            # fixture's LiDAR saw) instead of the session's, for the page's dry check with no dog and no key; GET
            # /dog/floorplan greys what it names, as it would a press's. Live: unset it and press name blobs at a stop.
            path = Path(f) if Path(f).is_absolute() else config.ROOT / f
            return {"labels": json.loads(path.read_text())["labels"], "source": f"fixture: {f}"}
        return self._labels

    def blobs_px(self) -> dict[str, Any]:
        """GET /dog/blobs: the labels in force, each pinned at its centre through the floor plan's saved calibration, else
        the session's: {labels: [record without cells + pos_px], source, ts?, why?}. A read: no row, no model."""
        lab = self._labels_now()
        if lab is None:
            return {"labels": [], "source": None, "why": "no labels yet: press name blobs at a stop (POST /dog/blobs)"}
        cal = (self._fp[2] if self._fp else None) or self.cal
        out = {**lab, "labels": [{**{k: v for k, v in x.items() if k != "cells"},
                                  "pos_px": occupancy.to_map_px([x["xy"]], cal)[0].tolist() if cal else None} for x in lab["labels"]]}
        if cal is None:
            out["why"] = " · ".join(filter(None, [lab.get("why"), "not calibrated: drag the dog to where it is (POST /dog/calibrate)"]))
        return out

    # ---- the object layer (wtdd/dog/objects.py): detector boxes placed on the grid along their bearing
    def objects_state(self, draft: bool = False) -> dict[str, Any]:
        """GET /dog/objects: takes the detector's newest window from watch.json if it is new, places its boxes on the
        session grid from the dog's odometry pose, and returns {n, objects, windows, fov_deg, source, why?}. The first
        call starts the 'objects' thread, which does the same every objects.TICK_S with draft=True: the one-line drafts
        (a model call) run there, outside every lock, never on the session loop and never inside a GET. WTDD_CAM_FOV_DEG
        is read here, at the point of use. No ledger row for the read; the store's events are object.seen rows."""
        fov = config.maybe("WTDD_CAM_FOV_DEG")
        fov_deg = float(fov) if fov else None
        st = self.body.state() if self.body else None
        pose = {"position": list(st["position"][:2]), "yaw": st["rpy"][2]} if st and st.get("position") and st.get("rpy") else None
        with self._objects_lock:
            why = objects.tick(self.objects, objects.WATCH, pose, self.grid, self.cal, fov_deg, self._grid_lock)
            body = {**self.objects.state(), "fov_deg": fov_deg, "source": "session"}
            if self._objects_ticker is None:
                self._objects_ticker = threading.Thread(target=self._objects_loop, name="objects", daemon=True)
                self._objects_ticker.start()
        if why:
            body["why"] = why
        if draft:
            objects.draft_due(self.objects)
        return body

    def _objects_loop(self) -> None:
        """The 'objects' thread: windows are taken and objects decay and get drafted while the page is closed. Ends when
        the session loop is closed (a test's teardown); a raise is logged each time it changes, never silent, never fatal
        (GET /dog/objects answers the same raise as a 500)."""
        last = None
        while True:
            time.sleep(objects.TICK_S)
            if self.loop.is_closed():
                return
            try:
                self.objects_state(draft=True)
                last = None
            except Exception as e:  # noqa: BLE001  (logged; the next tick tries again, the GET shows it)
                err = f"{type(e).__name__}: {e}"
                if err != last:
                    log("objects", "WARN tick FAILED", err=err[:160])
                last = err

    # ---- where it thinks it is (wtdd/dog/nav.py)
    def map_pose(self, st: dict[str, Any] | None = None) -> dict[str, Any] | None:
        st = st if st is not None else (self.body.state() if self.body else None)
        if not self.cal or not st or not st.get("position") or not st.get("rpy"):
            return None
        px, py, h = nav.to_map(self.cal, st["position"], st["rpy"][2])
        return {"p": [round(px), round(py)], "heading_deg": round(math.degrees(h), 1)}

    def calibrate(self, p, heading: float) -> dict[str, Any]:
        """Ties the odometry pose right now to map point p facing `heading` (radians). One dog.calibrate row."""
        st = self.run(self.with_body(lambda b: b.fresh_state(required=True)))
        with step("dog", "dog.calibrate", "map", {"p": list(p), "heading_deg": round(math.degrees(heading), 1)}, self.map_pose(st)) as r:
            self.cal = {**nav.calibration(st["position"], st["rpy"][2], p, heading), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self.recheck = False
            CAL_FILE.write_text(json.dumps(self.cal))
            r["state_after"] = {"cal": self.cal, "map": self.map_pose(st)}
        log("dog", "calibrated", p=list(p), heading_deg=round(math.degrees(heading), 1))
        return self.map_pose(st)

    # ---- following the drawn path
    def follow(self, path: list, stops: list[int], reach_px: float = 30.0, from_nearest: bool = True, avoid: bool = True) -> dict[str, Any]:
        if self.cal is None:
            raise RuntimeError("not calibrated: tell the dog where it is first (POST /dog/calibrate)")
        if self._follower and not self._follower.done():
            raise RuntimeError("already following; POST /dog/stop first")
        if len(path) < 2:
            raise ValueError("the map path has fewer than 2 points")
        self.run(self._ensure())
        if avoid and not self.body._avoid:   # never follow blind by default: avoidance on and read back first, or the follow is refused
            self.avoid(True)
        elif not avoid:                      # a person's explicit choice (the service is down): loud, and on the row
            log("dog", "WARN following WITHOUT obstacle avoidance, by explicit request")
        pose = self.map_pose()
        near_start = math.dist(path[0], pose["p"]) <= START_PX
        start = 0 if (near_start or not from_nearest) else nav.nearest_index(path, pose["p"])   # at the start of a loop: replay it, not the end
        log("dog", "follow from waypoint", start=start, n=len(path), near_start=near_start, dist_to_start_px=round(math.dist(path[0], pose["p"])))
        self.follow_state = {"active": True, "i": start, "n": len(path), "stops": stops, "stopped_at": None, "resume": False,
                             "reached": [], "started": time.time(), "error": None, "avoid": bool(self.body._avoid)}
        self._follower = asyncio.run_coroutine_threadsafe(self._follow(path, stops, reach_px, start), self.loop)
        return dict(self.follow_state)

    def resume(self) -> dict[str, Any]:
        self.follow_state["resume"] = True
        return dict(self.follow_state)

    def _set_vel(self, x: float, y: float, z: float) -> None:
        self.vel, self.vel_t = (x, y, z), time.monotonic()   # the drive loop publishes it and stops 0.6 s after the last refresh

    async def _follow(self, path: list, stops: list[int], reach_px: float, start: int) -> None:
        """Waypoint by waypoint from `start`: nav.steer at 10 Hz feeding the drive loop; pauses at stops until resume().
        One dog.follow row at the end with the waypoints reached and the error, if any. Never retries a waypoint."""
        fs = self.follow_state
        args = {"n": len(path), "start": start, "stops": stops, "reach_px": reach_px, "avoid": bool(self.body._avoid)}
        try:
            with step("dog", "dog.follow", "map", args, self.map_pose()) as r:
                try:
                    for i in range(start, len(path)):
                        fs["i"] = i
                        t_wp = time.monotonic()
                        while True:
                            pose = self.map_pose()
                            if pose is None:
                                raise RuntimeError("no pose (state stream stopped)")
                            ctl = nav.steer(pose["p"][0], pose["p"][1], math.radians(pose["heading_deg"]), path[i], reach_px)
                            fs.update({"dist_px": ctl["dist_px"], "err_deg": ctl["err_deg"], "p": pose["p"], "heading_deg": pose["heading_deg"]})
                            if ctl["reached"]:
                                break
                            if time.monotonic() - t_wp > WP_TIMEOUT_S:
                                raise TimeoutError(f"waypoint {i} not reached in {WP_TIMEOUT_S}s (dist {ctl['dist_px']} px, err {ctl['err_deg']} deg)")
                            self._set_vel(ctl["x"], 0.0, ctl["z"])
                            await asyncio.sleep(0.1)
                        fs["reached"].append(i)
                        log("dog", f"waypoint {i}/{len(path) - 1} reached", p=pose["p"])
                        if i in stops:
                            self.vel, self.vel_t = (0.0, 0.0, 0.0), 0.0
                            fs["stopped_at"], fs["resume"] = i, False
                            log("dog", f"stop at waypoint {i}: waiting for resume")
                            t_stop = time.monotonic()
                            while not fs["resume"]:
                                if time.monotonic() - t_stop > STOP_TIMEOUT_S:
                                    raise TimeoutError(f"stopped at {i} for {STOP_TIMEOUT_S}s without resume")
                                await asyncio.sleep(0.2)
                            fs["stopped_at"] = None
                    fs["done"] = True
                finally:
                    self.vel, self.vel_t = (0.0, 0.0, 0.0), 0.0
                    await self._halt()
                    fs["active"] = False
                    r["state_after"] = {"reached": list(fs["reached"]), "of": len(path), "seconds": round(time.time() - fs["started"], 1), "map": self.map_pose()}
        except asyncio.CancelledError:
            fs["error"] = "stopped"
            log("dog", "follow cancelled (stop)")
        except Exception as e:  # noqa: BLE001  (the row above has it; the state carries it for the page)
            fs["error"] = f"{type(e).__name__}: {e}"
            log("dog", "follow FAILED", err=fs["error"][:120])

    def close(self) -> None:
        if self.body is not None:
            self.run(self.body.close())
            self.body = None

    # ---- commands
    def cmd(self, name: str, parameter: Any = None) -> int:
        return self.run(self.with_body(lambda b: b.cmd(name, parameter)))

    def snapshot(self) -> bytes:
        """The newest camera frame as JPEG, no ledger row (the remote's live view)."""
        return self.run(self.with_body(lambda b: b.jpeg()))[0]

    # ---- hold-to-move
    def drive(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> dict[str, Any]:
        clamp = lambda v, k: max(-DRIVE_MAX[k], min(DRIVE_MAX[k], float(v)))  # noqa: E731
        self.vel = (clamp(x, "x"), clamp(y, "y"), clamp(z, "z"))
        self.vel_t = time.monotonic()
        if self.body is None:
            self.run(self._ensure())
        return {"vel": list(self.vel), "hold_s": DRIVE_HOLD_S}

    def stop(self) -> dict[str, Any]:
        """Cancels the follower, zeroes the held velocity, and halts the body now: a zero through the avoidance service
        when it is on (it keeps the last velocity until told zero; measured 2026-09-13, the dog kept walking after
        StopMove alone), then StopMove, then the state read back."""
        if self._follower and not self._follower.done():
            self._follower.cancel()
        self.vel, self.vel_t = (0.0, 0.0, 0.0), 0.0
        out: dict[str, Any] = {"vel": [0.0, 0.0, 0.0]}
        if self.body is not None:
            out["halt"] = self.run(self._halt(), timeout=10)
        return out

    async def _halt(self) -> dict[str, Any]:
        """The stop that works with avoidance on: zero velocity to the avoidance service, StopMove, state read back."""
        b = self.body
        if b._avoid:
            await b._tick("avoid", 0.0, 0.0, 0.0)
        code = await b.cmd("StopMove")
        self.moving = False
        st = await b.fresh_state(required=True)
        v = st.get("velocity") or [0, 0, 0]
        log("dog", "halt", stop_code=code, avoid=bool(b._avoid), velocity=[round(x, 2) for x in v])
        return {"stop_code": code, "velocity": v}

    async def _drive_loop(self) -> None:
        while True:
            try:
                fresh = time.monotonic() - self.vel_t < DRIVE_HOLD_S and any(abs(v) > 0 for v in self.vel)
                if fresh:
                    await self.body._tick("avoid" if self.body._avoid else "sport", *self.vel)
                    self.moving = True
                    await asyncio.sleep(1 / MOVE_HZ)
                else:
                    if self.moving:
                        await self._halt()   # zero through the avoidance service first when it is on, then StopMove
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                return
            except Exception as e:  # noqa: BLE001  (logged and the loop keeps serving; the tick's own row has it)
                log("dog", "drive tick failed", err=f"{type(e).__name__}: {str(e)[:100]}")
                await asyncio.sleep(0.5)

    # ---- the looks
    def look(self, kind: str = "tilt") -> dict[str, Any]:
        if kind not in LOOKS:
            raise ValueError(f"look must be one of {LOOKS}, got {kind!r}")
        return self.run(self.with_body(lambda b: self._look(b, kind)))

    async def _look(self, b: Body, kind: str) -> dict[str, Any]:
        """The looks. The tilt nod is verified by the IMU at capture: below TILT_MIN_DEG it did not fire (this dog
        sometimes ignores the pair after a long idle), so the routine settles the controller (StopMove, BalanceStand)
        and on a miss warms it with StandUp and tries once more. Pose refused with code 401001 (after the physical
        controller drove it, or after being carried; StandUp and BalanceStand do not clear it) is cured by Sit then
        RiseSit, once. The returned pitch_deg is what the IMU measured; a miss is reported as fired=False, never hidden."""
        out = PICTURES / f"look-{kind}.jpg"
        out_down = PICTURES / "look-down.jpg"
        with step("dog", "dog.look", "unitree", {"kind": kind}, b.state()) as r:
            attempts, pitch, pitch_down = 0, 0.0, None
            if kind == "level":
                await b.cmd("BalanceStand"); await asyncio.sleep(0.8)
                pitch = self._pitch(b); await b.frame(out); attempts = 1
            elif kind == "sit":
                await b.cmd("Sit"); await asyncio.sleep(1.8)
                pitch = self._pitch(b); await b.frame(out); attempts = 1
                await b.cmd("RiseSit"); await asyncio.sleep(2.0)
            else:
                for attempts in (1, 2):
                    if attempts == 2:
                        log("dog", "tilt did not fire, warming with StandUp and retrying once")
                        await b.cmd("StandUp"); await asyncio.sleep(2.0)
                    await b.cmd("StopMove"); await asyncio.sleep(0.3)
                    await b.cmd("BalanceStand"); await asyncio.sleep(1.0)
                    try:
                        await b.cmd("Pose", {"flag": True})
                    except RuntimeError as e:   # 401001 after the controller drove it or it was carried: a sit and rise unlocks the pose (measured 2026-09-13 14:2x)
                        if "401001" not in str(e) or attempts == 2:
                            raise
                        log("dog", "pose refused (401001): sitting and rising to unlock it, then retrying once")
                        await b.cmd("Sit"); await asyncio.sleep(1.8)
                        await b.cmd("RiseSit"); await asyncio.sleep(2.0)
                        await b.cmd("BalanceStand"); await asyncio.sleep(1.0)
                        await b.cmd("Pose", {"flag": True})
                    await asyncio.sleep(0.5)
                    await b.cmd("Euler", {"x": 0.0, "y": 0.3, "z": 0.0}); await asyncio.sleep(0.7)    # nod down: the floor at the +15 deg peak
                    pitch_down = self._pitch(b)
                    await b.frame(out_down)
                    await asyncio.sleep(0.9)
                    await b.cmd("Euler", {"x": 0.0, "y": -0.3, "z": 0.0}); await asyncio.sleep(0.6)   # nod up, plateau: the room
                    pitch = self._pitch(b)
                    await b.frame(out)
                    await b.cmd("Euler", {"x": 0.0, "y": 0.0, "z": 0.0}); await asyncio.sleep(0.8)
                    await b.cmd("Pose", {"flag": False}); await asyncio.sleep(0.3)
                    if pitch <= -TILT_MIN_DEG:
                        break
            fired = kind != "tilt" or pitch <= -TILT_MIN_DEG
            res = {"text": "here's what i see", "file": str(out), "kind": kind, "pitch_deg": pitch, "fired": fired, "attempts": attempts,
                   "file_down": str(out_down) if pitch_down is not None else None, "pitch_down_deg": pitch_down}
            r["state_after"] = res
            log("dog", f"look {kind}", pitch=pitch, fired=fired, attempts=attempts)
            return res

    @staticmethod
    def _pitch(b: Body) -> float:
        raw = b.raw() or {}
        rpy = (raw.get("imu_state") or {}).get("rpy") or [0, 0, 0]
        return round(math.degrees(rpy[1]), 1)
