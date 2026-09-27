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
map's stops until resume(); stop() cancels it. Every connect (and every reconnect) also switches avoidance on and
reads it back (S3); a refusal is a FAILED dog.avoid row and a WARN, never a failed connect. With avoidance on, the drive loop sends velocities through the
OBSTACLES_AVOID service (MOVE 1003, no ack) instead of SPORT Move; the state read-back is the receipt. record(True)
records the believed pose while Johnny drives, mark(look, say) adds a stop at the current spot with the action to
replay there, record(False) returns the thinned trace as {path, stops, actions} and the API writes it into
ui/map.json: the route the dog drove, and what it did along it, is what it replays. One dog.calibrate and one dog.follow
row; a failed or cancelled follow says so in state().follow.error.
The map scale (S5b): scale(v) is the page's slider (GET/POST /dog/scale), nav.set_scale inside one dog.scale row, saved as
px_per_m beside the tie in dog_cal.json; a new session takes that over WTDD_PX_PER_M (an out-of-range one is a WARN and
ignored) and names the scale's source in one stderr line. Only the process that holds the session sees the saved value.
A path that touches a drawn no-go zone (wtdd/nogo.py) is refused as the first thing follow() does, before the
calibration check, any connect or the avoidance switch: one route.refused row and a ValueError, no dog.follow row.
The follower (S6, S6b; _follow) takes the dots in order from the first. The live LiDAR view decides, without the dog's
own body (points within SELF_M of it); the grid is memory that only labels. Every leg, from where the dog stands to the
next dot, is planned around the live view (plan.leg) and driven point by point; before each point the rest of the leg
is checked against the newest view and re-planned from where the dog stands when it is now blocked (MAX_REPLANS per
leg, then refused). A dot the view covers moves to free floor within plan.LIVE_SNAP_M; with none, the dog faces it,
looks and Jev names what is there from OBSTACLES (_classify), and the dot is passed (a person pauses the follow until
resume()). Every decision is one route.decided row with a first-person sentence. state().follow carries planned (every
leg's polyline) and trace (the believed pose, the actual route), both kept until the next follow. A stop on a passed dot
is reported in skipped_stops, never waited on. UNVERIFIED on the dog: exercised with a teleporting body only
(wtdd/test_plan_grid.py); the turn to face a dot and the look inside a follow have run in no test.

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
are rows, reads are not. Objects: every detector window (<repo>/watch.json) is placed on that grid behind GET
/dog/objects by wtdd/dog/objects.py, on an 'objects' thread the first GET starts; its rows are object.seen.

Re-correction (wtdd/dog/localize.py, 05b). Every window after the first is matched against the grid before it is drawn:
its band cells through the correction held (self.corr, a rigid 2D transform in the odometry frame) against the cells
seen MATCH_THRESHOLD+ times. Applied: one pose.corrected row, the window's delta composed into self.corr, the window
drawn through it. Rejected past the cap: a pose.corrected row with ok false, not drawn, the correction kept (a streak of
them is a WARN: after a power cycle, clear the grid). Unmatched below MIN_SCORE: no row, one line per window (a WARN
the first five times, then every 100th), drawn through the correction held; skipped under MIN_CELLS: the same with the
rate-limited WARN only. Counts and the last verdict are on GET /dog/lidar .localize.
map_pose() is the odometry pose through self.corr, then nav.to_map; calibrate() ties that corrected pose and keeps the
correction (the grid is drawn through it); grid_clear() resets it and, with a calibration, sets recheck (the dot moves
by the dropped correction, so the remote asks for the drag). The match runs inline on the driver's dispatcher, as the
grid's accumulate does, measured on every row (latency_ms, a WARN over BUDGET_MS); if the dog's windows blow the budget
the fallback is a queue and one worker thread (not built: the first live run reads the ms).
"""
from __future__ import annotations
import asyncio
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..ledger import append, log, step
from . import lidar, localize, nav, objects, occupancy
from .. import config, plan
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
MAX_REPLANS = 5                               # S6b: re-plans per leg; past it the follow is refused rather than circling
SELF_M = 0.35                                 # S6b: live points this close to the believed pose are the dog's own body in its band
TRACE_MIN_PX, TRACE_MAX = 10, 2000            # S6b: the actual route (follow.trace): a point every 10 px moved, the last 2000 kept
FACE_DEG, FACE_S = 10.0, 8.0                  # S6b: facing a dot on blue: within this many degrees, or TimeoutError after FACE_S
OBSTACLES = ["person", "chair", "table", "box", "bag", "wall", "door", "other"]   # S6b: what Jev may name on a dot on blue
STUCK_M, STUCK_S = 0.05, 3.0                  # S6b: under STUCK_M closer to the point being driven to in STUCK_S is stuck
FRONT_M, BODY_HALF_M = 0.50, 0.155            # S6b: so is a live point in the body's corridor this close ahead of its middle (the Go2 stops its nose ~0.15 m short)
SIDESTEP_MS, SIDESTEP_S = 0.15, 1.0           # S6b: stuck, it first sidesteps toward the open side at this speed for this long
SWEEP_DEG = (15, 30, 45)                      # S6b: then holds these headings off the direct line, the open side first


class Stuck(RuntimeError):
    """S6b: no heading of the sweep brought the dog closer to the point it was driving to (_unstick)."""
REC_HZ, REC_MIN_PX, REC_STEP_PX = 5.0, 10, 45   # route recording: sample rate, min move per sample, waypoint spacing (about 0.4 m)
LIVE_MAX_AGE_MS = 1000                        # S6: an older LiDAR window is no live view; the follower says so once
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
        self.recheck = False   # no calibration loaded; state() reads this before any connect
        saved = json.loads(CAL_FILE.read_text()) if CAL_FILE.exists() else {}
        if (v := saved.pop("px_per_m", None)) is not None:   # the page's scale, saved beside the tie, wins over WTDD_PX_PER_M
            try:
                nav.set_scale(v, CAL_FILE.name)
            except ValueError as e:
                log("dog", f"WARN saved scale ignored, keeping {nav.SCALE_SOURCE}", file=CAL_FILE.name, err=str(e))
        log("dog", f"scale {nav.PX_PER_M} px/m from {nav.SCALE_SOURCE}")
        if saved:   # a calibration survives an API restart, not a dog power cycle (the odometry frame resets then)
            self.cal = saved
            self.recheck = True   # loaded, not confirmed: the remote asks for the dog's position until someone drags it
            log("dog", "calibration loaded, to be confirmed", file=CAL_FILE.name, map=self.cal.get("map"), at=self.cal.get("at"))
        self.follow_state: dict[str, Any] = {}       # the follower's live status (GET /dog/state .follow)
        self._follower: asyncio.Task | None = None
        self.rec: dict[str, Any] | None = None       # a route being recorded by driving: {points, marks, started}
        self._recorder: asyncio.Task | None = None
        self.grid: occupancy.Grid | None = None      # every LiDAR window this session, accumulated (odometry metres); None until the first frame
        self._grid_lock = threading.Lock()           # frames arrive on the driver's dispatcher, reads on HTTP threads
        self._grid_file: tuple[float, occupancy.Grid] | None = None   # (mtime, grid) of ui/grid.json as last loaded
        self.corr = localize.IDENTITY                # the scan-to-map correction (localize.py), odometry frame; identity until a window is applied
        self.loc: dict[str, Any] = {"applied": 0, "rejected": 0, "unmatched": 0, "skipped": 0, "rejected_streak": 0, "last": None}
        self.objects = objects.Store(draft=objects.drafter())   # what the detector boxed, placed on the grid (GET /dog/objects)
        self._objects_lock = threading.Lock()        # one detector window at a time: the objects thread and GET /dog/objects both tick
        self._objects_ticker: threading.Thread | None = None   # started by the first objects_state()

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
            try:   # S3: the dog's own obstacle avoidance on at every connect, read back (its own dog.avoid row)
                await b.avoid(True)
            except Exception as e:  # noqa: BLE001  (loud, not fatal: the row is FAILED, the chip shows OFF, the dog stays usable)
                log("dog", "WARN avoidance NOT on after connect: hold-to-drive goes through the sport service until it answers",
                    err=f"{type(e).__name__}: {str(e)[:120]}")
        return self.body

    async def with_body(self, fn: Callable[[Body], Awaitable[Any]]) -> Any:
        return await fn(await self._ensure())

    def connected(self) -> bool:
        return self.body is not None

    def state(self) -> dict[str, Any]:
        st = self.body.state() if self.body else None
        return {"connected": self.body is not None, "moving": self.moving, "vel": list(self.vel), "state": st,
                "map": self.map_pose(st), "calibrated": self.cal is not None, "follow": self.follow_state,
                "avoid": self.body._avoid if self.body else None, "recheck": self.recheck, "corr": localize.describe(self.corr),
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
        reads. Returns {on, n (frames), errors, cb_errors (frames the grid failed to take), grid_frames, localize, age_ms,
        frame, points_px, why?}; switching on hands every frame to the session grid (_on_frame). localize is the
        re-correction's {applied, rejected, unmatched, skipped, corr, last}. points_px is the newest frame's floor-to-head
        band in map pixels through the correction and the calibration (wtdd/dog/lidar.py), [] with `why` when there is no
        frame yet, the stream is off, or the dog is not calibrated. No ledger row: a read, like /dog/state."""
        if on is True or (on is False and self.body is not None):
            self.run(self.with_body(lambda b: b.lidar_on(self._on_frame) if on else b.lidar_off()))
        loc = {**{k: self.loc[k] for k in ("applied", "rejected", "unmatched", "skipped", "last")}, "corr": localize.describe(self.corr)}
        if self.body is None:
            return {"on": False, "n": 0, "errors": 0, "cb_errors": 0, "grid_frames": g.frames if (g := self.grid) is not None else 0,
                    "localize": loc, "age_ms": None, "frame": None, "points_px": [], "why": "not connected"}
        lp = self.body.lidar_points()
        out = {k: lp[k] for k in ("on", "n", "errors", "cb_errors", "age_ms", "frame", "utlidar_pose")}
        out["grid_frames"], out["localize"] = g.frames if (g := self.grid) is not None else 0, loc
        st = self.body.state()
        if lp["points"] is None:
            return {**out, "points_px": [], "why": "no frame yet" if lp["on"] else "lidar off"}
        if not self.cal or not st or not st.get("position") or not st.get("rpy"):
            return {**out, "points_px": [], "why": "not calibrated"}
        xy = localize.apply_points(self.corr, lidar.top_down(lp["points"]))
        x, y, yaw = localize.apply_pose(self.corr, st["position"][0], st["position"][1], st["rpy"][2])
        return {**out, "n_xy": len(xy), "points_px": lidar.to_map_points(xy, self.cal, (x, y), yaw)}

    # ---- the occupancy grid (wtdd/dog/occupancy.py): every LiDAR window this session, accumulated in odometry metres
    def _on_frame(self, d: dict) -> None:
        """Body._on_lidar hands every decoded frame here, on the driver's dispatcher: one count per cell per drawn frame,
        every window after the first re-corrected first (_relocalize). A raise is counted by Body (cb_errors, on GET
        /dog/lidar and /dog/grid) and logged there; it never stops the stream."""
        with self._grid_lock:
            t0 = time.perf_counter()
            if self.grid is None:
                self.grid = occupancy.Grid.from_frame(d)
                log("dog", "grid started", frame_id=d["frame"], resolution=d["resolution"], origin=[round(v, 2) for v in d["origin"][:2]])
                self.loc["skipped"] += 1   # nothing to match the first window against
                touched = self.grid.update_frame(d)
            else:
                touched = self._relocalize(d)
            if touched is not None and self.grid.frames % 100 == 0:
                log("dog", "grid", frames=self.grid.frames, cells=int((self.grid.counts > 0).sum()), shape=self.grid.shape,
                    touched=touched, ms=round((time.perf_counter() - t0) * 1000, 1))

    def _relocalize(self, d: dict) -> int | None:
        """One window against the grid (wtdd/dog/localize.py), under _grid_lock: applied, rejected, unmatched or skipped
        (the docstring's Re-correction paragraph). Returns the cells drawn, None for a rejected window (not drawn). An
        applied window is drawn before anything moves: a grid that refuses it raises (Body counts it in cb_errors) and
        leaves the correction, the counts and the ledger as they were."""
        localize.same_lattice(self.grid, d)   # 01's two refusals, before anything is matched or drawn
        xy, loc = localize.apply_points(self.corr, localize.band(d["points"])), self.loc
        if len(xy) < localize.MIN_CELLS:
            loc["skipped"] += 1
            if loc["skipped"] <= 5 or loc["skipped"] % 100 == 0:
                log("dog", "WARN localize skipped: too few band cells to match, drawn through the correction held",
                    n=len(xy), min_cells=localize.MIN_CELLS, skipped=loc["skipped"])
            return self.grid.update(xy)
        st = self.body.state() if self.body else None
        if st and st.get("position"):   # the dog's corrected position; without a state stream, the window's centre
            pivot, kind = localize.apply_pose(self.corr, st["position"][0], st["position"][1], 0.0)[:2], "odom"
        else:
            pivot, kind = (float(d["center"][0]), float(d["center"][1])), "window"
        m = localize.match(self.grid, xy, pivot)
        why = localize.over_cap(m)
        verdict = "unmatched" if m["score"] < localize.MIN_SCORE else "rejected" if why else "applied"
        kv = {"dx": round(m["dx"], 3), "dy": round(m["dy"], 3), "dtheta_deg": m["dtheta_deg"], "score": round(m["score"], 3),
              "score0": round(m["score0"], 3), "n": m["n"], "ms": m["ms"], "pivot": kind}
        last = {"verdict": verdict, **kv, "why": why, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if m["ms"] > localize.BUDGET_MS:
            log("dog", "WARN localize over budget on the driver's dispatcher", ms=m["ms"], budget_ms=localize.BUDGET_MS, n=m["n"])
        if verdict != "applied":   # an applied window is counted below, once the grid has taken it
            loc[verdict] += 1
            loc["last"] = last
        if verdict == "unmatched":
            if loc["unmatched"] <= 5 or loc["unmatched"] % 100 == 0:
                log("dog", "WARN localize unmatched: new territory or a bad grid, drawn through the correction held",
                    unmatched=loc["unmatched"], min_score=localize.MIN_SCORE, **kv)
            else:   # one line per window, as applied and rejected: only the WARN is rate-limited
                log("dog", "localize unmatched", unmatched=loc["unmatched"], **kv)
            return self.grid.update(xy)
        snap = lambda: {"corr": localize.describe(self.corr), "map": self.map_pose(st), "grid_frames": self.grid.frames}  # noqa: E731
        before = snap()
        if verdict == "rejected":
            loc["rejected_streak"] += 1
            append(localize.row(m, kind, before, before, why))
            log("dog", "localize rejected", why=why, streak=loc["rejected_streak"], **kv)
            if loc["rejected_streak"] == 5 or (loc["rejected_streak"] > 5 and loc["rejected_streak"] % 50 == 0):
                log("dog", "WARN windows past the cap in a row: was the dog power-cycled? POST /dog/grid {clear: true}",
                    streak=loc["rejected_streak"])
            return None
        delta = localize.delta_about(pivot, m["dx"], m["dy"], m["dtheta"])
        touched = self.grid.update(localize.apply_points(delta, xy))   # first: a grid that refuses the window (01's MAX_SIDE) raises here and nothing moves
        self.corr = localize.compose(self.corr, delta)
        loc["applied"] += 1
        loc["rejected_streak"], loc["last"] = 0, last
        append(localize.row(m, kind, before, snap()))
        c = localize.describe(self.corr)
        log("dog", "localize applied", corr_tx=c["tx"], corr_ty=c["ty"], corr_deg=c["theta_deg"], **kv)
        return touched

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
        old counts belong to another frame), and the scan-to-map correction with it (it was measured against that grid).
        With a calibration, dropping a correction moves the dot by it, so recheck is set and the remote asks for the
        drag. One dog.grid_clear row, also with no grid. ui/grid.json is left as it is."""
        with self._grid_lock:
            g = self.grid
            before = {"frames_before": g.frames if g else 0, "cells_before": int((g.counts > 0).sum()) if g else 0,
                      "corr_before": localize.describe(self.corr)}
            with step("dog", "dog.grid_clear", "map", {"why": why, **before}) as r:
                if self.cal is not None and tuple(self.corr) != localize.IDENTITY:   # the dot is drawn through it: dropping it moves the dot
                    self.recheck = True
                    log("dog", "WARN grid cleared under a correction: the dot moved by it, drag the dog to where it is", corr=before["corr_before"])
                self.grid = None
                self.corr = localize.IDENTITY
                self.loc.update(applied=0, rejected=0, unmatched=0, skipped=0, rejected_streak=0, last=None)
                r["state_after"] = {"cleared": True, "corr_reset": True, "recheck": self.recheck}
        return {"cleared": True, "frames_before": before["frames_before"]}

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
        x, y, yaw = localize.apply_pose(self.corr, st["position"][0], st["position"][1], st["rpy"][2])   # the believed pose: odometry through the correction
        px, py, h = nav.to_map(self.cal, (x, y), yaw)
        return {"p": [round(px), round(py)], "heading_deg": round(math.degrees(h), 1)}

    def calibrate(self, p, heading: float) -> dict[str, Any]:
        """Ties the corrected odometry pose right now to map point p facing `heading` (radians); the scan-to-map correction
        is kept (the grid is drawn through it) and named on the row. One dog.calibrate row."""
        st = self.run(self.with_body(lambda b: b.fresh_state(required=True)))
        c = self.corr
        x, y, yaw = localize.apply_pose(c, st["position"][0], st["position"][1], st["rpy"][2])
        with step("dog", "dog.calibrate", "map", {"p": list(p), "heading_deg": round(math.degrees(heading), 1), "corr": localize.describe(c)}, self.map_pose(st)) as r:
            self.cal = {**nav.calibration((x, y), yaw, p, heading), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self.recheck = False
            self._save_cal()
            r["state_after"] = {"cal": self.cal, "map": self.map_pose(st)}
        log("dog", "calibrated", p=list(p), heading_deg=round(math.degrees(heading), 1))
        return self.map_pose(st)

    def _save_cal(self) -> None:
        """dog_cal.json: the tie and, once the page has set it, the scale beside it; each write keeps the other."""
        keep = {"px_per_m": nav.PX_PER_M} if nav.SCALE_SOURCE in ("page", CAL_FILE.name) else {}
        CAL_FILE.write_text(json.dumps({**(self.cal or {}), **keep}))

    def scale(self, px_per_m: Any = None) -> dict[str, Any]:
        """GET/POST /dog/scale, the page's slider. None reads {px_per_m, source}, no row. A value goes through
        nav.set_scale inside one dog.scale row (px_per_m before and after) and is saved beside the tie; a value that is
        not a number or outside 20..400 fails the row (ValueError naming it) and changes nothing."""
        now = {"px_per_m": nav.PX_PER_M, "source": nav.SCALE_SOURCE}
        if px_per_m is None:
            return now
        with step("dog", "dog.scale", "map", {"px_per_m": px_per_m, "source": "page"}, now) as r:
            nav.set_scale(px_per_m, "page")
            self._save_cal()
            r["state_after"] = {"px_per_m": nav.PX_PER_M, "source": nav.SCALE_SOURCE, "file": CAL_FILE.name}
        log("dog", "scale set", px_per_m=nav.PX_PER_M, was=now["px_per_m"])
        return r["state_after"]

    # ---- following the drawn path
    def follow(self, path: list, stops: list[int], reach_px: float = 30.0, from_nearest: bool = False, avoid: bool = True) -> dict[str, Any]:
        from ..nogo import refuse                  # 04: a route through a drawn no-go zone is refused before anything else is looked at
        refuse(path, "dog")                        # reads the map's zones; one route.refused row, then ValueError; no probe, no connect, no dog.follow row
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
                             "reached": [], "started": time.time(), "error": None, "avoid": bool(self.body._avoid),
                             "replans": [], "skipped_stops": [], "passed": [], "unchecked": False, "planned": [], "trace": [pose["p"]]}
        self._follower = asyncio.run_coroutine_threadsafe(self._follow(path, stops, reach_px, start), self.loop)
        return dict(self.follow_state)

    def resume(self) -> dict[str, Any]:
        self.follow_state["resume"] = True
        return dict(self.follow_state)

    def _live_px(self) -> list | None:
        """S6: the newest LiDAR window's floor-to-head band in map pixels, every point, through the correction and the
        tie (what the page draws as blue dots); None when there is no live view: no body or stream, a window older than
        LIVE_MAX_AGE_MS, no pose, or not calibrated."""
        b = self.body
        if b is None or not hasattr(b, "lidar_points") or self.cal is None:
            return None
        lp, st = b.lidar_points(), b.state()
        if lp.get("points") is None or lp.get("age_ms") is None or lp["age_ms"] > LIVE_MAX_AGE_MS:
            return None
        if not st or not st.get("position") or not st.get("rpy"):
            return None
        xy = localize.apply_points(self.corr, lidar.top_down(lp["points"]))
        x, y, yaw = localize.apply_pose(self.corr, st["position"][0], st["position"][1], st["rpy"][2])
        return lidar.to_map_points(xy, self.cal, (x, y), yaw, max_points=max(1, len(xy)))

    def _decided(self, i: int | None, action: str, reason: str, say: str, **extra: Any) -> None:
        """S6: one route.decided row per decision the follower makes: the action (unchecked, snapped, refused; S6b's
        classified row is _classify's own; stuck, gave up), the reason, and one first-person sentence (args.say, the
        receipts' main line). A refusal is a FAILED row and raises, so the follow fails loud with it; "gave up" (S6b: a dot
        not reached, passed) is a FAILED row the follow moves on from."""
        args = {"at": i, "action": action, "reason": reason, "say": say, **extra}
        log("dog", f"decided {action}: {say}")
        try:
            with step("dog", "route.decided", "map", args, self.map_pose()) as r:
                if action in ("refused", "gave up"):
                    raise RuntimeError(f"{action}: {reason}")
                r["state_after"] = {"action": action}
        except RuntimeError:
            if action == "refused":
                raise

    def _set_vel(self, x: float, y: float, z: float) -> None:
        self.vel, self.vel_t = (x, y, z), time.monotonic()   # the drive loop publishes it and stops 0.6 s after the last refresh

    async def _goto(self, target, reach_px: float, fs: dict[str, Any], what: str) -> dict[str, Any]:
        """nav.steer at 10 Hz feeding the drive loop until `target` is within reach_px; returns the pose there. Not
        reached in WP_TIMEOUT_S: TimeoutError naming `what`. S6b: stuck (under STUCK_M closer in STUCK_S, or at once a live
        point in the body's corridor within FRONT_M ahead, plan.ahead), _unstick; its sweep moving the dog no closer: Stuck."""
        t_wp = time.monotonic()
        best, t_best = math.inf, t_wp   # the stuck window: the closest so far, and since when
        while True:
            pose = self.map_pose()
            if pose is None:
                raise RuntimeError("no pose (state stream stopped)")
            self._traced(fs, pose["p"])
            ctl = nav.steer(pose["p"][0], pose["p"][1], math.radians(pose["heading_deg"]), target, reach_px)
            fs.update({"dist_px": ctl["dist_px"], "err_deg": ctl["err_deg"], "p": pose["p"], "heading_deg": pose["heading_deg"]})
            if ctl["reached"]:
                return pose
            if time.monotonic() - t_wp > WP_TIMEOUT_S:
                raise TimeoutError(f"{what} not reached in {WP_TIMEOUT_S}s (dist {ctl['dist_px']} px, err {ctl['err_deg']} deg)")
            if ctl["dist_px"] <= best - STUCK_M * nav.PX_PER_M or best == math.inf:
                best, t_best = ctl["dist_px"], time.monotonic()
            live = self._view()[0]
            near = None if live is None else plan.ahead(pose["p"], math.radians(pose["heading_deg"]), live, FRONT_M, BODY_HALF_M)
            if near is not None or time.monotonic() - t_best > STUCK_S:
                why = f"an obstacle {near} m ahead" if near is not None else f"no progress in {STUCK_S} s"
                if not await self._unstick(target, fs, what, why):
                    raise Stuck(f"{why}, and none of {2 * len(SWEEP_DEG)} headings brought me {STUCK_M} m closer")
                best, t_best = math.inf, time.monotonic()
                continue
            self._set_vel(ctl["x"], 0.0, ctl["z"])
            await asyncio.sleep(0.1)

    async def _unstick(self, target, fs: dict[str, Any], what: str, why: str) -> bool:
        """S6b, Johnny 03:48: "trust its lidar and actually just guide itself and reposition ... test the different degrees
        and angles". The clear metres left and right of the dog in the newest live view 1 m ahead (plan.sides; the wider is
        the open side, left on a tie), a sidestep toward it (SIDESTEP_MS for SIDESTEP_S), then headings SWEEP_DEG off the
        direct line to `target`, the open side first and the other from 15, each held up to STUCK_S; the first that brings
        the dog STUCK_M closer is kept and steering to the target resumes. One route.decided "stuck" row per heading. All
        through the same drive loop, so the Go2's avoidance stays on (S3). True when a heading moved it.
        UNVERIFIED on the dog: the sidestep (y velocity) through the avoidance service and the held headings."""
        live, pose = self._view()
        clear = plan.sides(pose["p"], math.radians(pose["heading_deg"]), live) if live is not None else {"left": None, "right": None}
        first = "right" if (clear["right"] or 0) > (clear["left"] or 0) else "left"
        for _ in range(max(1, round(SIDESTEP_S * 10))):   # refreshed every 0.1 s: the drive loop drops a velocity after DRIVE_HOLD_S
            self._set_vel(0.0, SIDESTEP_MS if first == "left" else -SIDESTEP_MS, 0.0)
            await asyncio.sleep(0.1)
        n = 0
        for side in (first, "right" if first == "left" else "left"):
            for deg in SWEEP_DEG:
                n, pose = n + 1, self._view()[1]
                d0 = math.dist(pose["p"], target)
                scan = f"where my scan shows {clear[side]} m clear" if clear[side] is not None else "with no live view to go by"
                self._decided(fs["i"], "stuck", f"{why} on the way to {what}: holding {deg} deg {side} of the direct line",
                              f"I'm blocked straight ahead on the way to dot {fs['i'] + 1}. Trying {deg}° {side}, {scan}.",
                              angle=deg, side=side, clear_m=clear, attempt=n, dist_m=round(d0 / nav.PX_PER_M, 2))
                h = nav.heading_of(pose["p"], target) + math.radians(deg if side == "right" else -deg)   # map heading is clockwise: right is +
                t0 = time.monotonic()
                while time.monotonic() - t0 < STUCK_S:
                    if (pose := self.map_pose()) is None:
                        raise RuntimeError("no pose (state stream stopped)")
                    self._traced(fs, pose["p"])
                    if d0 - math.dist(pose["p"], target) >= STUCK_M * nav.PX_PER_M:
                        log("dog", f"unstuck: {deg} deg {side} moved me closer, back to steering", at=fs["i"], attempt=n)
                        return True
                    aim = (pose["p"][0] + 1000 * math.cos(h), pose["p"][1] + 1000 * math.sin(h))   # a point far down that heading
                    ctl = nav.steer(pose["p"][0], pose["p"][1], math.radians(pose["heading_deg"]), aim, 0.0)
                    self._set_vel(ctl["x"], 0.0, ctl["z"])
                    await asyncio.sleep(0.1)
        return False

    def _gave_up(self, i: int, path: list, stops: list[int], fs: dict[str, Any], why: str) -> bool:
        """S6b: dot i not reached after a sweep, a re-plan and another sweep: one FAILED "gave up" row, the dot passed (a
        stop on it skipped) and False, so the follow moves on. The last dot has no next one: refused, which raises."""
        if i + 1 >= len(path):
            self._decided(i, "refused", f"stuck on the way to the last dot, {i + 1}, after a sweep, a re-plan and another sweep: {why}",
                          f"I can't get to dot {i + 1}, the last one: {why}. I'm stopping here.")
        self._decided(i, "gave up", f"stuck on the way to dot {i + 1} after a sweep, a re-plan and another sweep: {why}",
                      f"I couldn't get to dot {i + 1}: {why}. I'm naming it passed and moving on to dot {i + 2}.", passed=[i])
        fs["passed"].append(i)
        fs["skipped_stops"] += [i] if i in stops else []
        return False

    async def _follow(self, path: list, stops: list[int], reach_px: float, start: int) -> None:
        """Dot by dot from `start`: nav.steer at 10 Hz feeding the drive loop; pauses at stops until resume(). S6: the LIVE
        view decides (the newest LiDAR window's band without the dog's own body, _view) and the grid is memory that only
        labels a blocker permanent or new. S6b: each dot is reached by a planned leg (_leg); a dot on live blue with no free
        floor near it is looked at, named and passed (_classify). No live view: one "unchecked" row and the dots are
        followed as drawn. One dog.follow row at the end with the dots reached and passed, the re-plans, the stops skipped
        and the error, if any. Never retries a dot."""
        fs = self.follow_state
        args = {"n": len(path), "start": start, "stops": stops, "reach_px": reach_px, "avoid": bool(self.body._avoid)}
        try:
            with step("dog", "dog.follow", "map", args, self.map_pose()) as r:
                try:
                    for i in range(start, len(path)):
                        fs["i"] = i
                        live, pose = self._view()
                        if not await (self._as_drawn(i, path, stops, reach_px, fs, pose) if live is None
                                      else self._leg(i, path, stops, reach_px, fs, live, pose)):
                            continue   # passed: looked at and named, or given up; its row says so
                        fs["reached"].append(i)
                        log("dog", f"waypoint {i}/{len(path) - 1} reached", p=fs.get("p"))
                        if i in stops:
                            await self._hold(fs, i, f"stop at waypoint {i}")
                    fs["done"] = True
                finally:
                    self.vel, self.vel_t = (0.0, 0.0, 0.0), 0.0
                    await self._halt()
                    fs["active"] = False
                    if (end := self.map_pose()) is not None:
                        self._traced(fs, end["p"])
                    r["state_after"] = {"reached": list(fs["reached"]), "passed": list(fs["passed"]), "of": len(path),
                                        "seconds": round(time.time() - fs["started"], 1), "map": end, "replans": len(fs["replans"]),
                                        "skipped_stops": list(fs["skipped_stops"])}
        except asyncio.CancelledError:
            fs["error"] = "stopped"
            log("dog", "follow cancelled (stop)")
        except Exception as e:  # noqa: BLE001  (the row above has it; the state carries it for the page)
            fs["error"] = f"{type(e).__name__}: {e}"
            log("dog", "follow FAILED", err=fs["error"][:120])

    def _view(self) -> tuple[list | None, dict]:
        """S6b: (the newest live band without the dog's own body, the believed pose). Points within SELF_M of the pose are
        dropped: the dog's legs land in its own band. (None, pose) with no live view; no pose raises."""
        live, pose = self._live_px(), self.map_pose()
        if pose is None:
            raise RuntimeError("no pose (state stream stopped)")
        if live is None:
            return None, pose
        r = SELF_M * nav.PX_PER_M
        return [q for q in live if math.dist(q, pose["p"]) > r], pose

    @staticmethod
    def _traced(fs: dict[str, Any], p) -> None:
        """S6b: the actual route, follow.trace: the believed pose appended once it moved TRACE_MIN_PX, the last TRACE_MAX kept."""
        t = fs["trace"]
        if not t or math.dist(t[-1], p) >= TRACE_MIN_PX:
            t.append([int(p[0]), int(p[1])])
            del t[:-TRACE_MAX]

    async def _as_drawn(self, i: int, path: list, stops: list[int], reach_px: float, fs: dict[str, Any], pose: dict) -> bool:
        """No live view: dot i straight as drawn, with the dog's own avoidance; S6's "unchecked" row once per follow.
        Stuck (S6b) with no view to re-plan on: given up (_gave_up). True when reached."""
        if not fs["unchecked"]:
            fs["unchecked"] = True
            self._decided(None, "unchecked", "no live view (the LiDAR is off, its newest window is older than "
                          f"{LIVE_MAX_AGE_MS} ms, or the dog is not calibrated): the waypoints are followed as drawn, avoidance on",
                          "I can't see live right now, so I'm following your dots as drawn with my own obstacle avoidance on.")
        fs["planned"].append([pose["p"], [int(path[i][0]), int(path[i][1])]])
        try:
            await self._goto(path[i], reach_px, fs, f"waypoint {i}")
        except Stuck as e:
            return self._gave_up(i, path, stops, fs, f"{e}, and no live view to re-plan on")
        return True

    async def _hold(self, fs: dict[str, Any], i: int, what: str) -> None:
        """Stopped at dot i (zero velocity, follow.stopped_at) until resume(); STOP_TIMEOUT_S without one fails the follow."""
        self.vel, self.vel_t = (0.0, 0.0, 0.0), 0.0
        fs["stopped_at"], fs["resume"] = i, False
        log("dog", f"{what}: waiting for resume")
        t_stop = time.monotonic()
        while not fs["resume"]:
            if time.monotonic() - t_stop > STOP_TIMEOUT_S:
                raise TimeoutError(f"stopped at {i} for {STOP_TIMEOUT_S}s without resume")
            await asyncio.sleep(0.2)
        fs["stopped_at"] = None

    async def _leg(self, i: int, path: list, stops: list[int], reach_px: float, fs: dict[str, Any], live: list, pose: dict) -> bool:
        """S6b: dot i by a planned leg. The dot covered in the live view moves to free floor within plan.LIVE_SNAP_M
        (snapped); with none it is looked at and named instead (_classify) and False is returned. The leg (plan.leg, one
        plan.route row) runs from where the dog stands, around what the view shows; before each point after the first the
        rest of it is checked against the newest view (plan.clear) and, now blocked, the dot is decided again and the leg
        re-planned from where the dog stands (one plan.replanned row with its sentence). Stuck (_goto's sweep failed): one
        re-plan from where it stands, and stuck again, given up (_gave_up). Past MAX_REPLANS re-plans, or no route:
        refused, which raises. True when the dot (or its snapped spot) is reached."""
        say, stuck = None, False
        for n in range(MAX_REPLANS + 1):
            if n:
                live, pose = self._view()
                if live is None:
                    return await self._as_drawn(i, path, stops, reach_px, fs, pose)
            target = path[i]
            if (b := plan.blocker(target, live, self.grid, self.cal, lock=self._grid_lock)) is not None:
                if (sn := plan.snap(target, live)) is None:
                    await self._classify(i, path, stops, b, fs)
                    return False
                (q, m), what = sn, f"{b['kind']}, {b['cells']} cells, {b['in_memory']} in memory"
                seen = (f"something new ({b['cells']} cells, not in my memory: a new obstacle)" if b["kind"] == "new obstacle"
                        else f"something I've seen here before ({b['cells']} cells, {b['in_memory']} in my memory: permanent)")
                self._decided(i, "snapped", f"dot {i + 1} blocked by {what}: moved {m} m to free floor",
                              f"Dot {i + 1} is covered by {seen}. I'm going to the free spot {m} m away and carrying on in order.",
                              blocker=b, m=m, **{"from": [int(target[0]), int(target[1])], "to": q})
                target = q
            try:
                leg = plan.leg(pose["p"], target, live, [fs["reached"][-1] + 1 if fs["reached"] else None, i + 1], say, again=n > 0)
            except ValueError as e:
                self._decided(i, "refused", f"no route to dot {i + 1} in the live view: {e}",
                              f"I can't find a way to dot {i + 1} around what I see ({e}), so I'm stopping here.", to=[int(v) for v in target])
            fs["planned"].append(leg["path"])
            if n:
                fs["replans"].append({"at": i, "from": pose["p"], "waypoints": len(leg["path"]) - 1})
            for k in range(1, len(leg["path"])):
                if k > 1 and (view := self._view())[0] is not None:
                    live, pose = view
                    if not plan.clear([pose["p"], *leg["path"][k:]], live):
                        say = f"The way to dot {i + 1} is blocked now by something I see live. I'm re-planning from where I stand ({n + 1} of {MAX_REPLANS})."
                        break
                try:
                    pose = await self._goto(leg["path"][k], reach_px, fs, f"point {k} of the leg to waypoint {i}")
                except Stuck as e:
                    if stuck:
                        return self._gave_up(i, path, stops, fs, str(e))
                    stuck, say = True, f"I couldn't get past on the way to dot {i + 1} ({e}). I'm re-planning from where I stand."
                    break
            else:
                return True
            log("dog", f"WARN leg re-planned: {say}", at=i, re_plan=n + 1, of=MAX_REPLANS)
        self._decided(i, "refused", f"the way to dot {i + 1} was blocked again after {MAX_REPLANS} re-plans (MAX_REPLANS): not circling",
                      f"The way to dot {i + 1} keeps getting blocked, {MAX_REPLANS} re-plans, so I'm stopping here instead of circling.")

    async def _classify(self, i: int, path: list, stops: list[int], b: dict, fs: dict[str, Any]) -> None:
        """S6b: dot i sits on live blue with no free floor within plan.LIVE_SNAP_M. The dog faces it and looks (_look_at),
        Jev picks one label from OBSTACLES (decide._jev, never decide.decide: no `decided` row, no escalation; with no
        JEV_API_KEY decide._stub, the row cached, source stub). One route.decided row, action classified, with the label,
        p, the scene sentence and a first-person say; the dot is passed (follow.passed, a stop on it skipped). A person
        pauses the follow here like a stop until resume(). A failed look or label is the same row FAILED, and the follow
        still moves on."""
        from .. import decide
        nxt = f"I'm moving on to dot {i + 2}." if i + 1 < len(path) else "It was the last dot, so I'm done."
        kind = "a new obstacle" if b["kind"] == "new obstacle" else "something my memory already had (permanent)"
        args = {"at": i, "action": "classified", "blocker": b, "passed": [i],
                "reason": f"dot {i + 1} on live blue ({b['kind']}, {b['cells']} cells) with no free floor within {plan.LIVE_SNAP_M} m: looked and named"}
        try:
            with step("dog", "route.decided", "map", args, self.map_pose()) as r:
                try:
                    sight = await self._look_at(path[i])
                    state = (f"a robot dog following a drawn route stopped short of a dot its lidar sees covered ({b['kind']}). facing it, "
                             f"its camera sees: {sight['text']}" + (" someone is in view." if sight.get("person") else ""))
                    stub = not config.maybe("JEV_API_KEY")
                    label, p, model, raw = decide._stub(state, OBSTACLES) if stub else await asyncio.to_thread(decide._jev, state, OBSTACLES)
                    if label not in OBSTACLES or not 0.0 <= p <= 1.0:
                        raise ValueError(f"label out of contract: {label!r} (choices {OBSTACLES}), p={p!r}")
                    if stub:
                        r["cached"], r["source"] = True, "stub"
                    name = "something I can't name" if label == "other" else f"a {label}"
                    args |= {"label": label, "p": round(p, 3), "scene": sight["text"], "model": model,
                             "say": f"There's a person on dot {i + 1}. I'm waiting here until you press resume." if label == "person"
                             else f"Dot {i + 1} is on {name} ({p:.2f}), {kind}. {nxt}"}
                    r["state_after"], r["response_or_error"] = {"label": label, "p": round(p, 3), "passed": [i]}, raw[:600]
                except Exception as e:
                    args["say"] = f"I tried to see what's on dot {i + 1}, but {type(e).__name__}: {str(e)[:120]}. I'm naming it passed. {nxt}"
                    raise
        except Exception:  # noqa: BLE001  (the row above is FAILED with the error; S6b: the follow still moves on)
            label = None
        log("dog", f"decided classified{'' if label else ' FAILED'}: {args['say']}")
        fs["passed"].append(i)
        fs["skipped_stops"] += [i] if i in stops else []
        if label == "person":
            await self._hold(fs, i, f"a person on waypoint {i}")

    async def _look_at(self, p) -> dict[str, Any]:
        """S6b: what is on map point p, in words. The dog turns in place to face it (nav.steer's turn, no step forward,
        until within FACE_DEG, else TimeoutError after FACE_S), the level look (_look: one frame, its dog.look row), and
        the vision model's sentence on that frame (dog_say.see: {text, person, ...}, its llm.generate row). Raises on any
        failure. UNVERIFIED on the dog: the tests replace this."""
        from ..tools.dog_say import see
        t0 = time.monotonic()
        while True:
            if (pose := self.map_pose()) is None:
                raise RuntimeError("no pose (state stream stopped)")
            ctl = nav.steer(pose["p"][0], pose["p"][1], math.radians(pose["heading_deg"]), p, 0.0)
            if abs(ctl["err_deg"]) <= FACE_DEG:
                break
            if time.monotonic() - t0 > FACE_S:
                raise TimeoutError(f"not facing {[int(v) for v in p]} in {FACE_S}s (err {ctl['err_deg']} deg)")
            self._set_vel(0.0, 0.0, ctl["z"])
            await asyncio.sleep(0.1)
        self.vel, self.vel_t = (0.0, 0.0, 0.0), 0.0
        shot = await self._look(self.body, "level")
        return await asyncio.to_thread(see, shot["file"])

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
