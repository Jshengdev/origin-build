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
the dog's own LiDAR band on the map behind GET/POST /dog/lidar (wtdd/dog/lidar.py), also un-receipted.
"""
from __future__ import annotations
import asyncio
import json
import math
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..ledger import log, step
from . import lidar, nav
from .body import MOVE_HZ, Body

PICTURES = Path("~/Pictures/wtdd").expanduser()
CAL_FILE = Path(__file__).resolve().parents[2] / "dog_cal.json"   # the last human calibration, so an API restart keeps it (runtime file)
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
        reads. Returns {on, n (frames), errors, age_ms, frame, points_px, why?}: points_px is the newest frame's
        floor-to-head band in map pixels through the calibration (wtdd/dog/lidar.py), [] with `why` when there is no
        frame yet, the stream is off, or the dog is not calibrated. No ledger row: a read, like /dog/state."""
        if on is True or (on is False and self.body is not None):
            self.run(self.with_body(lambda b: b.lidar_on() if on else b.lidar_off()))
        if self.body is None:
            return {"on": False, "n": 0, "errors": 0, "age_ms": None, "frame": None, "points_px": [], "why": "not connected"}
        lp = self.body.lidar_points()
        out = {k: lp[k] for k in ("on", "n", "errors", "age_ms", "frame", "utlidar_pose")}
        st = self.body.state()
        if lp["points"] is None:
            return {**out, "points_px": [], "why": "no frame yet" if lp["on"] else "lidar off"}
        if not self.cal or not st or not st.get("position") or not st.get("rpy"):
            return {**out, "points_px": [], "why": "not calibrated"}
        xy = lidar.top_down(lp["points"])
        return {**out, "n_xy": len(xy), "points_px": lidar.to_map_points(xy, self.cal, st["position"], st["rpy"][2])}

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
