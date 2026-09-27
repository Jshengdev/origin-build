"""Tests for wtdd/dog/scout.py and DogSession.scout (wtdd/dog/session.py) on the synthetic spin frames in
wtdd/dog/fixtures/spin_frames.npz (made by fixtures/make_spin_frames.py; nothing here has seen the real dog). Run:

    python -m unittest wtdd.dog.test_scout

RED until scout.py exists and the session has scout(). No dog: a FakeBody stands in for wtdd/dog/body.py's Body with
an IMU yaw that turns at a chosen rate, velocity ticks and StopMove recorded, and a LiDAR stream that feeds the fixture
frames to the callback the way Body._on_lidar does. The drive loop that publishes the held velocity is main's
(_drive_loop, proven by the remote's Q/E keys); these tests read the held velocity (session.vel) instead of running it,
so every halt counted here is the scout's own, with the drive loop not running. On the dog the drive loop also sends
its release halt when the held velocity drops (measured dry with it running and a 150 ms StopMove: two StopMoves per
press, the second a harmless retry). Every count is computed from the fixture's declared world with plain sets
(make_spin_frames.frame_cells / wall_cells / world_cells), never from the accumulator.

The contract under test:
  scout.integrate_yaw(prev, now, acc) -> acc + wrap(now - prev), radians: a turn integrated across the +-pi wrap, either sign
  scout.closed(turned_deg, target_deg=360, tol_deg=CLOSE_TOL_DEG) -> | |turned| - target | <= tol
  scout.row(args, before, after) -> {"args", "state_before", "state_after"}; ValueError naming any contract key that is
                            missing (absence of 05b or 05a is the string "absent", never an omitted key)
  scout.TICK_S 0.1, NO_TURN_S 3.0, NO_TURN_DEG 10.0, CLOSE_TOL_DEG 10.0, CANVAS_CENTRE (530, 770), DROPOFF_HEADING_DEG -90:
                            module constants read at call time (patched here to keep the suite fast)
  DogSession.scout(z=0.5, target_deg=360, timeout_s=30)   refuses while following or recording (RuntimeError) and a |z|
                            over session.DRIVE_MAX["z"] (ValueError, never a silent clamp), and a z, target_deg or
                            timeout_s that is not finite (or a target or timeout not over 0: the timeout is the
                            spin's one end guard, and inf never passes it), each one FAILED dog.scout row with nothing
                            moved, its args strict JSON (a bare Infinity/NaN in the ledger breaks the page's
                            JSON.parse of GET /ledger); else a task: connect, calibrate as "dropoff" when not
                            calibrated (canvas centre facing up, one dog.calibrate row with args.source), LiDAR on,
                            snapshot, hold (0, 0, z) refreshed every TICK_S until the integrated IMU yaw passes
                            target_deg (on its magnitude: a negative z turns clockwise and closes too), then one _halt;
                            the yaw read back after the halt is integrated too, so turned_deg and heading_end_deg are
                            where the body stopped, not where the loop let go; one dog.scout row through ledger.step;
                            returns the live state
  z == 0                    the standing control (Needs the dog 14.4: cells added standing still vs spinning): no velocity
                            is held, the no-turn check does not apply, it stands until timeout_s and ends ok with
                            closed false and a `why` naming the control; the frames/cells/cb_errors checks still apply
  POST /dog/scout {z?, target_deg?, timeout_s?}   {ok, scout: the live state}; a refusal is a 500 with the error;
                            POST /dog/stop cancels it
  DogSession.scout_state / state()["scout"]   {active, turned_deg, frames, cells_added, seconds, ranges, error}; present
                            (active false) before any scout, so the page can always read it, on a fresh session with
                            no dog_cal.json too (GET /dog/state 200: night-1 contracts F patch 3, nothing preset here)
  stderr                    one `[wtdd:dog] scout <turned> of <target> ...` line per second of spin, with frames and cells
  DogSession.calibrate(p, heading, source="tap")   the page's tie carries args.source "tap"; the scout's "dropoff"
  DogSession.stop()         cancels a running scout like the follower; its row says stopped, with state_after
                            complete, when the stop lands inside the scout's own halt too; a stop while the press is
                            still connecting or tying the pose (no task yet, the page's button already reads "stop") is
                            read by the press itself, and by its task before the LiDAR switch: one FAILED row naming
                            it, nothing moved
  dog.scout row            args {z_rad_s, target_deg, timeout_s, shift_id, source}
                            state_before {map, heading0_deg, grid_frames, cells, lidar_n, range_obstacle, localize, utlidar}
                            state_after {seconds, frames, cells_added, cells_total, turned_deg, heading_end_deg, closed,
                            avoid, cb_errors_during, range_obstacle, velocity, yaw_speed, localize, utlidar_turned_deg}
                            plus NIGHT-2 contract D's names for 10/11/22's fixtures: {heading0, closed_deg, velocity_path, why}
                            (why: None on a clean close, the WARN on a turn that did not close, the error on a FAILED row);
                            args.source is "dropoff" when the scout tied the pose itself, else the tie's own source ("tap")
                            state_after is complete on a FAILED row too (the finding is the numbers it reached)
  FAILED (ok false, the error named, the scout's own one halt): LiDAR switch refused; no turn after NO_TURN_S (names "avoid on" or
                            "avoid off"); timeout (turned_deg on the row); 0 frames; 0 band cells (names
                            lidar.Z_MIN/Z_MAX); cb_errors rising. Not closed is ok true, closed false, a stderr WARN
                            and `why` both saying "not closed".
  ui/index.html             one component between `// 14 · scout-spin · start` and `// 14 · scout-spin · end`: the
                            'scout: spin and draw' button (POST /dog/scout) with the honest title ("the LiDAR sees 360
                            already ..."), the `scout · ...` / `scouted · ...` / `scout FAILED: ...` status fragment;
                            the button does not wait for dog.connected (the press connects, like the drive keys)
  python -m wtdd.dog.scout --replay <npz> --png <out> [--threshold N] [--save <json>] [--frames N]
                            the driver decoder on each stored blob -> one grid from ONE origin -> a PNG; one
                            `[wtdd:scout] frame <k> ... cells=+<added>` stderr line per frame; a summary naming every
                            wall of the fixture's declared world (make_spin_frames.wall_cells) with its cells found;
                            exit 2 with one `WARN <wall> missing (<found> of <n> cells)` per wall not wholly in the grid
                            at the threshold (default 1: each wall cell is shown by exactly one wedge); --frames N
                            replays only the first N; --save writes the grid json (ui/grid.json for the page's fixture)
"""
from __future__ import annotations
import asyncio
import concurrent.futures
import http.client
import inspect
import io
import json
import math
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from contextlib import ExitStack, redirect_stderr
from pathlib import Path
from unittest import mock

import numpy as np

from .. import ledger
from ..config import ROOT
from . import lidar, nav, occupancy, scout, session
from .fixtures import make_spin_frames as fx
from .fixtures.make_voxel_frames import blobs, decode_wire

PY = sys.executable
RANGES = [1.9, 0.8, 1.2, 2.4]
ARGS = {"z_rad_s", "target_deg", "timeout_s", "shift_id", "source"}
BEFORE = {"map", "heading0_deg", "grid_frames", "cells", "lidar_n", "range_obstacle", "localize", "utlidar"}
AFTER = {"seconds", "frames", "cells_added", "cells_total", "turned_deg", "heading_end_deg", "closed", "avoid",
         "cb_errors_during", "range_obstacle", "velocity", "yaw_speed", "localize", "utlidar_turned_deg",
         "heading0", "closed_deg", "velocity_path", "why"}
PAGE = {"active", "turned_deg", "frames", "cells_added", "seconds", "ranges", "error"}


def frames() -> list[dict]:
    return [lidar.decode(decode_wire(b)) for b in blobs(fx.NPZ)]


def idx(xy: np.ndarray) -> set[tuple[int, int]]:
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    return {(int(round(x / fx.RES)), int(round(y / fx.RES))) for x, y in xy}


class FakeBody:
    """Enough of Body for DogSession.scout offline: a state whose IMU yaw turns at yaw_rate rad/s from construction
    until the first StopMove (then it holds, as a halted body does, coast_deg further on: a body that slides past the
    halt), ticks and commands recorded, lidar_on feeding `frames` to the callback 50 ms apart on the session loop (a raise
    counted as cb_errors, like Body._on_lidar), or refusing like a refused disable_traffic_saving."""

    def __init__(self, yaw_rate: float = 6.0, frames: list[dict] | None = None, avoid: bool = False, lidar_refused: bool = False,
                 coast_deg: float = 0.0):
        self.t0, self.yaw_rate, self.frames = time.monotonic(), yaw_rate, list(frames or [])
        self._avoid, self.lidar_refused, self.coast = avoid, lidar_refused, math.radians(coast_deg)
        self.ticks: list[tuple] = []
        self.cmds: list[str] = []
        self._lidar_on, self._lidar_cb, self._lidar, self._lidar_n, self._lidar_cb_err = False, None, None, 0, 0
        self._utpose, self._feeder, self.halted_at = None, None, None

    def _yaw(self) -> float:
        return nav.wrap(self.yaw_rate * ((self.halted_at or time.monotonic()) - self.t0) + (self.coast if self.halted_at else 0.0))

    def state(self) -> dict:
        return {"mode": 1, "gait_type": 0, "progress": 0, "position": [0.0, 0.0, 0.0], "velocity": [0.0, 0.0, 0.0],
                "yaw_speed": self.yaw_rate, "body_height": 0.3, "range_obstacle": list(RANGES), "rpy": [0.0, 0.0, self._yaw()],
                "n": 1, "hz": 20.0, "age_ms": 10}

    async def fresh_state(self, required: bool = False) -> dict:
        await asyncio.sleep(0.01)
        return self.state()

    async def _tick(self, via: str, x: float, y: float, z: float):
        self.ticks.append((via, x, y, z))
        return None if via == "avoid" else 0

    async def cmd(self, name: str, parameter=None) -> int:
        self.cmds.append(name)
        if name == "StopMove" and self.halted_at is None:
            self.halted_at = time.monotonic()
        return 0

    async def lidar_on(self, on_frame=None) -> None:
        if self.lidar_refused:
            raise RuntimeError("disable_traffic_saving refused by the dog (execution not ok): LiDAR stream not switched on")
        self._lidar_cb = on_frame
        if not self._lidar_on:
            self._lidar_on = True
            self._feeder = asyncio.get_running_loop().create_task(self._feed())

    async def _feed(self) -> None:
        for d in self.frames:
            await asyncio.sleep(0.05)
            self._lidar, self._lidar_n = d, self._lidar_n + 1
            if self._lidar_cb:
                try:
                    self._lidar_cb(d)
                except Exception:  # noqa: BLE001  (what Body._on_lidar does: counted, never raised into the driver)
                    self._lidar_cb_err += 1

    async def lidar_off(self) -> None:
        self._lidar_on = False

    def lidar_points(self) -> dict:
        d = self._lidar
        return {"on": self._lidar_on, "n": self._lidar_n, "errors": 0, "cb_errors": self._lidar_cb_err,
                "age_ms": 0 if d else None, "points": d["points"] if d else None, "utlidar_pose": self._utpose,
                "frame": {"id": d["frame"], "stamp": d["stamp"], "origin": d["origin"], "resolution": d["resolution"],
                          "width": d["width"], "center": d["center"], "voxels": d["n"]} if d else None}

    async def close(self) -> None:
        return None


class Harness(unittest.TestCase):
    """A DogSession on a temp ledger, temp dog_cal.json and temp ui/grid.json, with a FakeBody in place of the dog."""

    def setUp(self):
        self.stack = ExitStack()
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(mock.patch.object(ledger, "LEDGER", self.tmp / "ledger.jsonl"))
        self.stack.enter_context(mock.patch.object(session, "CAL_FILE", self.tmp / "dog_cal.json"))
        self.stack.enter_context(mock.patch.object(session, "GRID_FILE", self.tmp / "grid.json"))
        self.stack.enter_context(mock.patch.object(scout, "TICK_S", 0.02))
        self.err = self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.frames = frames()
        self.s: session.DogSession | None = None

    def tearDown(self):
        if self.s is not None:
            self.s.loop.call_soon_threadsafe(self.s.loop.stop)
            while self.s.loop.is_running():
                time.sleep(0.01)
            self.s.loop.close()
        self.stack.close()

    def session(self, body: FakeBody) -> session.DogSession:
        s = session.DogSession()
        s.body = body
        self.s = s
        return s

    def wait(self, s: session.DogSession, timeout: float = 15.0) -> dict:
        t0 = time.monotonic()
        while s.state()["scout"]["active"]:
            self.assertLess(time.monotonic() - t0, timeout, "the scout never ended")
            time.sleep(0.02)
        return s.state()["scout"]

    def rows(self, tool: str) -> list[dict]:
        return [r for r in ledger.rows() if r.get("tool") == tool]

    def serve(self) -> str:
        """wtdd.api's handler on an ephemeral port in this process (never 7788), shut down after the test."""
        from .. import api
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    @staticmethod
    def post(base: str, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


class Integrator(unittest.TestCase):
    def test_integrates_a_full_turn_across_the_wrap(self):
        acc, prev = 0.0, 0.0
        for k in range(1, 40):
            now = nav.wrap(k * 0.35)   # 20 deg steps; the IMU yaw wraps at +-pi three times in 40 steps
            acc = scout.integrate_yaw(prev, now, acc)
            prev = now
        self.assertAlmostEqual(acc, 39 * 0.35, places=9, msg="a wrap must not cost a 2 pi jump")

    def test_integrates_a_negative_turn(self):
        acc, prev = 0.0, 0.0
        for k in range(1, 40):
            now = nav.wrap(-k * 0.35)
            acc = scout.integrate_yaw(prev, now, acc)
            prev = now
        self.assertAlmostEqual(acc, -39 * 0.35, places=9)

    def test_one_step_across_pi(self):
        self.assertAlmostEqual(scout.integrate_yaw(3.0, -3.0, 1.0), 1.0 + (2 * math.pi - 6.0), places=9)
        self.assertAlmostEqual(scout.integrate_yaw(-3.0, 3.0, -1.0), -1.0 - (2 * math.pi - 6.0), places=9)

    def test_closes_at_360_either_way(self):
        acc, prev, steps = 0.0, 0.0, 0
        while abs(math.degrees(acc)) < 360:
            steps += 1
            now = nav.wrap(steps * 0.35)
            acc = scout.integrate_yaw(prev, now, acc)
            prev = now
        self.assertEqual(steps, 18)   # ceil(2 pi / 0.35)
        self.assertTrue(scout.closed(math.degrees(acc), 360, 25), math.degrees(acc))
        self.assertTrue(scout.closed(358, 360, 10))
        self.assertTrue(scout.closed(-355, 360, 10), "a clockwise turn (negative z) closes on its magnitude")
        self.assertFalse(scout.closed(340, 360, 10))
        self.assertFalse(scout.closed(371, 360, 10))
        self.assertEqual(scout.CLOSE_TOL_DEG, 10.0)


class Row(unittest.TestCase):
    def complete(self) -> tuple[dict, dict, dict]:
        args = {"z_rad_s": 0.5, "target_deg": 360, "timeout_s": 30, "shift_id": "2026-09-27", "source": "dropoff"}
        before = {"map": {"p": [530, 770], "heading_deg": -90.0}, "heading0_deg": 12.3, "grid_frames": 0, "cells": 0, "lidar_n": 0,
                  "range_obstacle": RANGES, "localize": "absent", "utlidar": "absent"}
        after = {"seconds": 12.8, "frames": 96, "cells_added": 1203, "cells_total": 1203, "turned_deg": 358.2, "heading_end_deg": 10.5,
                 "closed": True, "avoid": False, "cb_errors_during": 0, "range_obstacle": RANGES, "velocity": [0, 0, 0], "yaw_speed": 0.0,
                 "localize": "absent", "utlidar_turned_deg": "absent", "heading0": 12.3, "closed_deg": 358.2, "velocity_path": "sport", "why": None}
        return args, before, after

    def test_the_row_shape_is_the_contract(self):
        args, before, after = self.complete()
        r = scout.row(args, before, after)
        self.assertEqual(set(r), {"args", "state_before", "state_after"})
        self.assertTrue(ARGS <= set(r["args"]))
        self.assertTrue(BEFORE <= set(r["state_before"]))
        self.assertTrue(AFTER <= set(r["state_after"]))
        json.dumps(r)

    def test_the_defaults_and_constants_are_the_goal(self):
        sig = inspect.signature(session.DogSession.scout)
        self.assertEqual({k: sig.parameters[k].default for k in ("z", "target_deg", "timeout_s")},
                         {"z": 0.5, "target_deg": 360, "timeout_s": 30})
        self.assertEqual((scout.TICK_S, scout.NO_TURN_S, scout.NO_TURN_DEG, scout.CLOSE_TOL_DEG), (0.1, 3.0, 10.0, 10.0))
        self.assertEqual((tuple(scout.CANVAS_CENTRE), scout.DROPOFF_HEADING_DEG), ((530, 770), -90))

    def test_a_missing_key_is_named_never_omitted(self):
        args, before, after = self.complete()
        del before["localize"]
        with self.assertRaises(ValueError) as cm:
            scout.row(args, before, after)
        self.assertIn("localize", str(cm.exception))
        args, before, after = self.complete()
        del after["utlidar_turned_deg"]
        with self.assertRaises(ValueError) as cm:
            scout.row(args, before, after)
        self.assertIn("utlidar_turned_deg", str(cm.exception))


class Spin(Harness):
    def test_the_spin_turns_fills_the_grid_and_writes_one_row(self):
        body = FakeBody(yaw_rate=3.0, frames=self.frames)   # 2.1 s per turn: at least two once-a-second lines
        s = self.session(body)
        page0 = s.state()["scout"]
        self.assertTrue(PAGE <= set(page0), f"state().scout is there before any scout: {sorted(page0)}")
        self.assertFalse(page0["active"])
        live = s.scout(z=0.5, target_deg=360, timeout_s=10)
        self.assertTrue(live["active"])
        seen_vel = False
        t0 = time.monotonic()
        while s.state()["scout"]["active"] and time.monotonic() - t0 < 15:
            if tuple(s.state()["vel"]) == (0.0, 0.0, 0.5) and time.monotonic() - s.vel_t < session.DRIVE_HOLD_S:
                seen_vel = True   # the held velocity the drive loop publishes (0, 0, z), refreshed within DRIVE_HOLD_S
            time.sleep(0.01)
        st = self.wait(s)
        self.assertTrue(seen_vel, "the scout never held (0, 0, z) for the drive loop")
        self.assertIsNone(st["error"], st)
        self.assertEqual(tuple(s.vel), (0.0, 0.0, 0.0), "the held velocity is zero after the spin")
        self.assertEqual(body.cmds.count("StopMove"), 1, body.cmds)
        cal = self.rows("dog.calibrate")
        self.assertEqual(len(cal), 1, "not calibrated: one dropoff tie before the spin")
        self.assertEqual(cal[0]["args"]["source"], "dropoff")
        self.assertEqual(cal[0]["args"]["p"], [530, 770], "the canvas centre (ui/house.svg viewBox 1060x1540)")
        self.assertEqual(cal[0]["args"]["heading_deg"], -90.0, "nose at drop-off is up: map heading -90")
        rows = self.rows("dog.scout")
        self.assertEqual(len(rows), 1, "exactly one dog.scout row per press")
        r = rows[0]
        self.assertTrue(r["ok"], r["response_or_error"])
        self.assertEqual((r["agent"], r["app"]), ("dog", "map"))
        self.assertTrue(ARGS <= set(r["args"]), sorted(r["args"]))
        self.assertTrue(BEFORE <= set(r["state_before"]), sorted(r["state_before"]))
        self.assertTrue(AFTER <= set(r["state_after"]), sorted(r["state_after"]))
        a, b, c = r["args"], r["state_before"], r["state_after"]
        self.assertEqual((a["z_rad_s"], a["target_deg"], a["timeout_s"], a["source"]), (0.5, 360, 10, "dropoff"))
        self.assertTrue(isinstance(a["shift_id"], str) and a["shift_id"])
        self.assertEqual((b["grid_frames"], b["cells"], b["lidar_n"]), (0, 0, 0))
        self.assertEqual(b["range_obstacle"], RANGES)
        self.assertEqual((b["localize"], b["utlidar"]), ("absent", "absent"), "05b and 05a are absent on 01: named, never omitted")
        self.assertEqual(b["map"]["p"], [530, 770])
        self.assertEqual(c["frames"], len(self.frames))
        self.assertEqual(c["cells_added"], len(fx.world_cells()), "every wall cell the eight wedges showed")
        self.assertEqual(c["cells_total"], len(fx.world_cells()))
        self.assertGreaterEqual(c["turned_deg"], 360)
        self.assertTrue(c["closed"], c["turned_deg"])
        self.assertLess(abs(math.degrees(nav.wrap(math.radians(c["heading_end_deg"] - c["heading0"])))), 15,
                        "a full turn ends near the heading it began at (compared across the wrap)")
        self.assertEqual(c["closed_deg"], c["turned_deg"])
        self.assertEqual((c["avoid"], c["velocity_path"]), (False, "sport"))
        self.assertEqual(c["cb_errors_during"], 0)
        self.assertEqual(c["range_obstacle"], RANGES)
        self.assertEqual(c["velocity"], [0.0, 0.0, 0.0])
        self.assertEqual((c["localize"], c["utlidar_turned_deg"]), ("absent", "absent"))
        self.assertEqual(c["heading0"], b["heading0_deg"])
        self.assertIsNone(c["why"])
        self.assertGreater(c["seconds"], 0)
        self.assertEqual(s.grid.frames, len(self.frames))
        self.assertEqual(idx(s.grid.walls(1)), set(fx.world_cells()), "the session grid holds the four walls around one centre")
        self.assertEqual(s.grid.shape, (fx.H, fx.W), "one origin: the grid never grew during a pure turn")
        self.assertRegex(self.err.getvalue(), r"\[wtdd:dog\] scout .*of 360", "one stderr line per second of spin")
        page = s.state()["scout"]
        self.assertTrue(PAGE <= set(page), sorted(page))
        self.assertEqual((page["active"], page["frames"], page["cells_added"], page["ranges"]), (False, len(self.frames), len(fx.world_cells()), RANGES))

    def test_a_tap_before_the_spin_is_the_tie(self):
        body = FakeBody(yaw_rate=6.0, frames=self.frames)
        s = self.session(body)
        s.calibrate([300, 900], 0.0)
        s.scout(z=0.5, target_deg=360, timeout_s=10)
        st = self.wait(s)
        self.assertIsNone(st["error"], st)
        cal = self.rows("dog.calibrate")
        self.assertEqual(len(cal), 1, "already calibrated: the scout writes no second tie")
        self.assertEqual(cal[0]["args"]["source"], "tap", "the page's dog is here... / drag is the tap")
        self.assertEqual(cal[0]["args"]["p"], [300, 900])
        r = self.rows("dog.scout")[0]
        self.assertEqual(r["args"]["source"], "tap")
        self.assertEqual(r["state_before"]["map"]["p"], [300, 900])

    def test_refused_while_following_or_recording_nothing_moves(self):
        body = FakeBody(yaw_rate=6.0, frames=self.frames)
        s = self.session(body)
        s._follower = concurrent.futures.Future()   # a follow in flight (session.follow's handle), not done
        with self.assertRaises(RuntimeError) as cm:
            s.scout()
        self.assertIn("following", str(cm.exception))
        s._follower = None
        s.rec = {"points": [[1, 1]], "marks": [], "started": time.time()}
        with self.assertRaises(RuntimeError) as cm:
            s.scout()
        self.assertIn("recording", str(cm.exception))
        s.rec = None
        with self.assertRaises(ValueError) as cm:
            s.scout(z=session.DRIVE_MAX["z"] + 0.4)
        self.assertIn(str(session.DRIVE_MAX["z"]), str(cm.exception), "an over-cap z is refused naming the cap, never clamped")
        self.assertEqual((body.ticks, body.cmds), ([], []), "refused before anything moves: no tick, no halt")
        rows = self.rows("dog.scout")
        self.assertEqual(len(rows), 3, "a refusal is a FAILED row too")
        self.assertTrue(all(not r["ok"] for r in rows))
        self.assertEqual(self.rows("dog.calibrate"), [])
        self.assertFalse(s.state()["scout"]["active"])

    def test_a_z_target_or_timeout_that_is_not_finite_is_refused(self):
        """json.loads takes Infinity and NaN, float() takes "inf": a target or timeout of inf would never end the spin
        (the timeout is its one end guard), a nan z holds nothing and reads as "did not turn". Each is refused by name
        before anything moves, one FAILED row per press whose args stay strict JSON for the page."""
        body = FakeBody(yaw_rate=6.0, frames=self.frames)
        s = self.session(body)
        bad = [("target_deg", math.inf), ("target_deg", math.nan), ("target_deg", 0.0), ("target_deg", -360.0),
               ("timeout_s", math.inf), ("timeout_s", math.nan), ("timeout_s", 0.0), ("timeout_s", -1.0), ("z", math.nan)]
        for k, v in bad:
            with self.subTest(k=k, v=v):
                with self.assertRaises(ValueError) as cm:
                    s.scout(**{k: v})
                self.assertIn(f"{v:g}", str(cm.exception), "the refusal names the value")
                self.assertFalse(s.state()["scout"]["active"])
        self.assertEqual((body.ticks, body.cmds), ([], []), "refused before anything moves: no tick, no halt")
        rows = self.rows("dog.scout")
        self.assertEqual(len(rows), len(bad), "a refusal is a FAILED row too, one per press")
        self.assertTrue(all(not r["ok"] for r in rows))
        for r in rows:
            json.dumps(r, allow_nan=False)   # raises on a bare inf/nan: GET /ledger must stay parseable by the page
        self.assertEqual(self.rows("dog.calibrate"), [])

    def test_a_clockwise_spin_closes_on_its_magnitude(self):
        body = FakeBody(yaw_rate=-3.0, frames=self.frames)   # the main spin's rate: loop jitter stays inside the 10 deg tolerance
        s = self.session(body)
        s.scout(z=-0.5, target_deg=360, timeout_s=10)
        st = self.wait(s)
        self.assertIsNone(st["error"], st)
        r = self.rows("dog.scout")[0]
        self.assertTrue(r["ok"], r["response_or_error"])
        self.assertEqual(r["args"]["z_rad_s"], -0.5)
        c = r["state_after"]
        self.assertLessEqual(c["turned_deg"], -360, "negative z turns clockwise: the integrated yaw is negative")
        self.assertGreater(c["turned_deg"], -370)
        self.assertTrue(c["closed"])
        self.assertEqual(body.cmds.count("StopMove"), 1, body.cmds)

    def test_a_turn_that_does_not_close_is_ok_with_closed_false_and_a_warn(self):
        body = FakeBody(yaw_rate=6.0, frames=self.frames, coast_deg=40.0)   # the body slides 40 deg past the halt
        s = self.session(body)
        s.scout(z=0.5, target_deg=360, timeout_s=10)
        st = self.wait(s)
        self.assertIsNone(st["error"], "not closed is a finding, not a failure")
        r = self.rows("dog.scout")[0]
        self.assertTrue(r["ok"], r["response_or_error"])
        c = r["state_after"]
        self.assertGreater(c["turned_deg"], 390, "the yaw read back after the halt is integrated: where the body stopped")
        self.assertFalse(c["closed"])
        self.assertEqual(c["closed_deg"], c["turned_deg"])
        self.assertIn("not closed", str(c["why"]))
        end_vs_start = math.degrees(nav.wrap(math.radians(c["heading_end_deg"] - c["heading0"])))
        self.assertLess(abs(end_vs_start - (c["turned_deg"] - 360)), 5, "heading_end_deg agrees with turned_deg")
        self.assertTrue(any("WARN" in l and "not closed" in l for l in self.err.getvalue().splitlines()),
                        "one stderr WARN names it:\n" + self.err.getvalue()[-800:])
        self.assertEqual(body.cmds.count("StopMove"), 1, body.cmds)

    def test_z_zero_is_the_standing_control(self):
        body = FakeBody(yaw_rate=0.0, frames=self.frames)
        s = self.session(body)
        with mock.patch.object(scout, "NO_TURN_S", 0.2):   # the no-turn check must not fire on a press that asked for no turn
            s.scout(z=0.0, target_deg=360, timeout_s=1.0)
            st = self.wait(s)
        self.assertIsNone(st["error"], st)
        r = self.rows("dog.scout")[0]
        self.assertTrue(r["ok"], r["response_or_error"])
        c = r["state_after"]
        self.assertIn("control", str(c["why"]))
        self.assertFalse(c["closed"])
        self.assertLess(abs(c["turned_deg"]), 1)
        self.assertEqual((c["frames"], c["cells_added"]), (len(self.frames), len(fx.world_cells())),
                         "the control's cells are the number the spin is compared against")
        self.assertGreaterEqual(c["seconds"], 1.0)
        self.assertEqual(body.ticks, [], "no velocity was sent to a body told to stand")
        self.assertNotIn("did not turn", self.err.getvalue())
        self.assertEqual(body.cmds.count("StopMove"), 1, body.cmds)


class FailLoud(Harness):
    def failed(self, s: session.DogSession, body: FakeBody) -> tuple[dict, dict]:
        st = self.wait(s)
        rows = self.rows("dog.scout")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])
        self.assertIsNotNone(st["error"])
        self.assertIn(st["error"].split(":")[0][:20], str(rows[0]["response_or_error"]), "the page's error is the row's")
        self.assertEqual(body.cmds.count("StopMove"), 1, f"one halt: {body.cmds}")
        self.assertEqual(tuple(s.vel), (0.0, 0.0, 0.0))
        return st, rows[0]

    def test_a_body_that_does_not_turn_is_failed_and_halted_once(self):
        body = FakeBody(yaw_rate=0.0, frames=self.frames)
        s = self.session(body)
        with mock.patch.object(scout, "NO_TURN_S", 0.3):
            s.scout(z=0.5, target_deg=360, timeout_s=10)
            st, r = self.failed(s, body)
        self.assertIn("did not turn", st["error"])
        self.assertIn("avoid off", st["error"], "names which velocity path was tried")
        self.assertEqual(r["state_after"]["velocity_path"], "sport")

    def test_did_not_turn_with_avoidance_on_names_that_path(self):
        body = FakeBody(yaw_rate=0.0, frames=self.frames, avoid=True)
        s = self.session(body)
        with mock.patch.object(scout, "NO_TURN_S", 0.3):
            s.scout(z=0.5, target_deg=360, timeout_s=10)
            st, r = self.failed(s, body)
        self.assertIn("did not turn", st["error"])
        self.assertIn("avoid on", st["error"], "the avoidance MOVE has never carried a yaw on this dog: the row must say it was tried")
        self.assertEqual((r["state_after"]["velocity_path"], r["state_after"]["avoid"]), ("avoid", True))
        self.assertIn(("avoid", 0.0, 0.0, 0.0), body.ticks, "the halt zeroes the avoidance service first (session._halt)")

    def test_a_timeout_carries_the_degrees_it_managed(self):
        body = FakeBody(yaw_rate=1.0, frames=self.frames)   # 6.3 s per turn; the scout gets 0.5 s
        s = self.session(body)
        s.scout(z=0.5, target_deg=360, timeout_s=0.5)
        st, r = self.failed(s, body)
        self.assertIn("timeout", st["error"].lower())
        self.assertTrue(10 < r["state_after"]["turned_deg"] < 90, r["state_after"]["turned_deg"])
        self.assertFalse(r["state_after"]["closed"])

    def test_zero_frames_is_failed_by_name(self):
        body = FakeBody(yaw_rate=6.0, frames=[])
        s = self.session(body)
        s.scout(z=0.5, target_deg=360, timeout_s=10)
        st, r = self.failed(s, body)
        self.assertIn("0 frames", st["error"])
        self.assertEqual(r["state_after"]["frames"], 0)

    def test_zero_band_cells_names_the_band(self):
        d = dict(self.frames[0])
        p = d["points"]
        d["points"] = np.column_stack([p[:, :2], np.full(len(p), fx.Z0)])   # every voxel on the floor, below lidar.Z_MIN
        body = FakeBody(yaw_rate=6.0, frames=[d, d, d])
        s = self.session(body)
        s.scout(z=0.5, target_deg=360, timeout_s=10)
        st, r = self.failed(s, body)
        self.assertIn("Z_MIN", st["error"])
        self.assertIn(str(lidar.Z_MIN), st["error"])
        self.assertEqual((r["state_after"]["frames"], r["state_after"]["cells_added"]), (3, 0))

    def test_cb_errors_rising_is_failed_with_the_count(self):
        other = dict(self.frames[1])
        other["frame"] = "map"   # another frame_id is another world: the grid refuses it, Body counts a cb_error
        body = FakeBody(yaw_rate=6.0, frames=[self.frames[0], other, self.frames[2]])
        s = self.session(body)
        s.scout(z=0.5, target_deg=360, timeout_s=10)
        st, r = self.failed(s, body)
        self.assertIn("cb_errors", st["error"])
        self.assertEqual(r["state_after"]["cb_errors_during"], 1)

    def test_a_refused_lidar_switch_is_failed(self):
        body = FakeBody(yaw_rate=6.0, frames=self.frames, lidar_refused=True)
        s = self.session(body)
        s.scout(z=0.5, target_deg=360, timeout_s=10)
        st, r = self.failed(s, body)
        self.assertIn("disable_traffic_saving", st["error"])
        self.assertEqual(body.ticks, [], "nothing was commanded after the refusal")

    def test_stop_cancels_the_scout(self):
        body = FakeBody(yaw_rate=0.5, frames=self.frames)   # 12.6 s per turn
        s = self.session(body)
        s.scout(z=0.5, target_deg=360, timeout_s=30)
        time.sleep(0.3)
        s.stop()
        st = self.wait(s)
        self.assertIn("stopped", st["error"])
        self.assertGreaterEqual(body.cmds.count("StopMove"), 1)
        self.assertEqual(tuple(s.vel), (0.0, 0.0, 0.0))
        r = self.rows("dog.scout")[0]
        self.assertFalse(r["ok"])
        self.assertIn("stopped", str(r["response_or_error"]))

    def test_a_stop_during_the_scouts_own_halt_is_named_and_complete(self):
        """POST /dog/stop lands while the scout awaits its own StopMove (the page's button still reads "stop" then).
        CancelledError is not an Exception: caught only around the spin, it went past the halt's except and ledger.step,
        leaving a row with no error and no state_after, and the page saying "scout FAILED: null"."""
        class SlowStop(FakeBody):   # a StopMove ack that takes 0.4 s
            stopping = False

            async def cmd(self, name, parameter=None):
                if name == "StopMove":
                    self.stopping = True
                    await asyncio.sleep(0.4)
                return await super().cmd(name, parameter)

        body = SlowStop(yaw_rate=6.0, frames=self.frames)   # closes in about 1 s, then halts
        s = self.session(body)
        s.scout(z=0.5, target_deg=360, timeout_s=10)
        t0 = time.monotonic()
        while not body.stopping:
            self.assertLess(time.monotonic() - t0, 10, "the scout never reached its halt")
            time.sleep(0.005)
        time.sleep(0.1)   # inside the scout's own _halt now
        s.stop()          # cancels the task, then sends its own halt: the body is still halted
        st = self.wait(s)
        self.assertIn("stopped", st["error"] or "", "the page names the stop")
        rows = self.rows("dog.scout")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertFalse(r["ok"])
        self.assertIn("stopped", str(r["response_or_error"]))
        self.assertEqual(set(r["state_after"] or {}), AFTER, "state_after is complete on this FAILED row too")
        self.assertIn("stopped", r["state_after"]["why"])
        self.assertGreaterEqual(body.cmds.count("StopMove"), 1)
        self.assertEqual(tuple(s.vel), (0.0, 0.0, 0.0))

    def test_a_stop_while_the_press_connects_ends_it_before_anything_moves(self):
        """At drop-off the press is the first command, so it is the one that connects (about a second over WebRTC). The
        press is claimed first (the page's button reads "stop" from then), so POST /dog/stop can land while there is no
        task to cancel and no body to halt: the press must read that stop itself. One FAILED row naming it, no tie,
        no velocity held, nothing commanded."""
        body = FakeBody(yaw_rate=3.0, frames=self.frames)
        s = session.DogSession()   # no body: this press connects
        self.s = s

        async def connect() -> FakeBody:
            await asyncio.sleep(1.0)
            s.body = body
            return body

        s._ensure, vels, out = connect, [], {}
        s._set_vel = lambda x, y, z: vels.append((x, y, z))

        def press() -> None:
            try:
                out["ok"] = s.scout(z=0.5, target_deg=360, timeout_s=10)
            except Exception as e:  # noqa: BLE001  (the refusal is what this test reads)
                out["err"] = e

        t = threading.Thread(target=press)
        t.start()
        time.sleep(0.3)
        self.assertTrue(s.state()["scout"]["active"], "claimed while it connects: the page's button reads stop")
        s.stop()
        t.join(10)
        st = self.wait(s)
        self.assertIn("err", out, f"the press started a spin after the stop: {out}")
        self.assertIn("stopped", str(out["err"]))
        self.assertIn("stopped", st["error"] or "", "the page names the stop")
        self.assertEqual(vels, [], "no velocity was held after the stop")
        self.assertEqual((body.ticks, body.cmds), ([], []), "nothing was commanded")
        rows = self.rows("dog.scout")
        self.assertEqual(len(rows), 1, rows)
        self.assertFalse(rows[0]["ok"])
        self.assertIn("stopped", str(rows[0]["response_or_error"]))
        self.assertEqual(self.rows("dog.calibrate"), [], "stopped before the drop-off tie: nothing tied")

    def test_a_stop_during_the_dropoff_tie_ends_the_press(self):
        body = FakeBody(yaw_rate=3.0, frames=self.frames)
        s = self.session(body)
        tie, vels = s.calibrate, []
        s._set_vel = lambda x, y, z: vels.append((x, y, z))

        def calibrate(*a, **k):   # POST /dog/stop lands while the drop-off tie is written
            out = tie(*a, **k)
            s.stop()
            return out

        s.calibrate = calibrate
        with self.assertRaises(RuntimeError) as cm:
            s.scout(z=0.5, target_deg=360, timeout_s=10)
        self.assertIn("stopped", str(cm.exception))
        self.assertEqual(vels, [])
        self.assertEqual(body.cmds, ["StopMove"], "stop()'s own halt only: the press commanded nothing")
        self.assertEqual(len(self.rows("dog.calibrate")), 1, "the tie was written before the stop landed")
        r = self.rows("dog.scout")
        self.assertEqual((len(r), r[0]["ok"]), (1, False))
        self.assertIn("stopped", str(r[0]["response_or_error"]))
        self.assertFalse(s.state()["scout"]["active"])

    def test_a_stop_between_the_press_and_its_task_is_read_by_the_task(self):
        """The last gap: the press has passed its own checks and hands the spin to the loop; a stop now finds no running
        task to cancel. The task reads it before the LiDAR switch and the first velocity."""
        body = FakeBody(yaw_rate=3.0, frames=self.frames)
        s = self.session(body)
        vels, real = [], asyncio.run_coroutine_threadsafe
        s._set_vel = lambda x, y, z: vels.append((x, y, z))

        def late(coro, loop):
            if getattr(coro, "__name__", "") == "_scout":
                s.stop()
            return real(coro, loop)

        with mock.patch.object(session.asyncio, "run_coroutine_threadsafe", late):
            s.scout(z=0.5, target_deg=360, timeout_s=10)
        st = self.wait(s)
        self.assertIn("stopped", st["error"] or "")
        self.assertEqual(vels, [], "no velocity was held after the stop")
        self.assertFalse(body._lidar_on, "stopped before the LiDAR switch")
        r = self.rows("dog.scout")
        self.assertEqual((len(r), r[0]["ok"]), (1, False))
        self.assertIn("stopped", str(r[0]["response_or_error"]))
        self.assertEqual(set(r[0]["state_after"] or {}), AFTER, "state_after is complete on this FAILED row too")


class Api(Harness):
    def test_post_dog_scout_runs_and_post_dog_stop_cancels_it(self):
        body = FakeBody(yaw_rate=0.5, frames=self.frames)   # 12.6 s per turn: still turning when stopped
        s = self.session(body)
        self.stack.enter_context(mock.patch.object(session.DogSession, "_inst", s))
        base = self.serve()
        s.rec = {"points": [[1, 1]], "marks": [], "started": time.time()}
        code, o = self.post(base, "/dog/scout", {})
        self.assertEqual(code, 500, o)
        self.assertFalse(o["ok"])
        self.assertIn("recording", o["error"], "the refusal reaches the page as the error")
        s.rec = None
        code, o = self.post(base, "/dog/scout", {"z": 0.5, "target_deg": 360, "timeout_s": 30})
        self.assertEqual(code, 200, o)
        self.assertTrue(o["ok"])
        self.assertTrue(o["scout"]["active"], o)
        time.sleep(0.3)
        code, o = self.post(base, "/dog/stop", {})
        self.assertEqual(code, 200, o)
        st = self.wait(s)
        self.assertIn("stopped", st["error"])
        rows = self.rows("dog.scout")
        self.assertEqual(len(rows), 2, "the refusal and the stopped spin, one row each")
        self.assertTrue(all(not r["ok"] for r in rows))
        self.assertIn("stopped", str(rows[-1]["response_or_error"]))
        self.assertEqual(tuple(s.vel), (0.0, 0.0, 0.0))


class Fresh(Harness):
    """Beat 1.1 as the page meets it: a fresh API at drop-off, no dog_cal.json, nothing preset on the session."""

    def test_a_fresh_session_with_no_tie_answers_get_dog_state(self):
        self.assertFalse(session.CAL_FILE.exists(), "the drop-off case: no tie on disk")
        s = session.DogSession()
        s.body = FakeBody(frames=self.frames)
        self.s = s
        self.stack.enter_context(mock.patch.object(session.DogSession, "_inst", s))
        base = self.serve()
        try:
            with urllib.request.urlopen(base + "/dog/state", timeout=10) as r:
                code, d = r.status, json.loads(r.read())
        except (urllib.error.URLError, ConnectionError, http.client.HTTPException) as e:
            self.fail(f"GET /dog/state gave the page no answer on a fresh API with no tie: {e!r}")
        self.assertEqual(code, 200, d)
        self.assertEqual((d["calibrated"], d["recheck"]), (False, False), "nothing tied, so nothing to re-check")
        self.assertTrue(PAGE <= set(d["scout"]), sorted(d["scout"]))
        self.assertFalse(d["scout"]["active"])
        self.assertFalse(s.state()["scout"]["active"])


class Page(unittest.TestCase):
    def test_the_button_and_its_honest_title_are_on_the_remote(self):
        html = (ROOT / "ui" / "index.html").read_text()
        for needle in ("// 14 · scout-spin · start", "// 14 · scout-spin · end", "scout: spin and draw",
                       "the LiDAR sees 360 already", "/dog/scout", "scouted · ", "scout FAILED"):
            self.assertTrue(needle in html, f"ui/index.html lacks {needle!r}")
        self.assertFalse("maps the room" in html, "never say the spin maps the room")

    def test_the_button_does_not_wait_for_another_command_to_connect(self):
        html = (ROOT / "ui" / "index.html").read_text()
        block = html.split("// 14 · scout-spin · start")[1].split("// 14 · scout-spin · end")[0]
        self.assertFalse("dog?.connected" in block, "POST /dog/scout connects itself (a connect failure is its FAILED row): "
                         "one press at drop-off, not a second command first")


class Fixture(unittest.TestCase):
    def test_eight_wedges_from_one_origin_decode_through_the_driver(self):
        fr = frames()
        self.assertEqual(len(fr), fx.WEDGES)
        seen: dict[tuple[int, int], int] = {}
        for k, d in enumerate(fr):
            self.assertEqual(d["frame"], fx.FRAME_ID)
            self.assertEqual(d["resolution"], fx.RES)
            np.testing.assert_allclose(d["origin"][:2], fx.ORIGIN, err_msg="a pure turn: the window origin never moves")
            p = d["points"]
            band = p[(p[:, 2] >= lidar.Z_MIN) & (p[:, 2] <= lidar.Z_MAX)]
            cells = idx(band[:, :2])
            self.assertEqual(cells, fx.frame_cells(k), f"frame {k}: not the declared wedge")
            self.assertGreater(int((p[:, 2] < lidar.Z_MIN).sum()), 0, "the floor patch below the band is in the raw frame")
            for c in cells:
                seen[c] = seen.get(c, 0) + 1
        walls = fx.wall_cells()
        self.assertEqual(set(walls), {"front", "left", "back", "right"})
        self.assertEqual(set(seen), set().union(*walls.values()), "the union of the wedges is the four walls")
        self.assertEqual(set(seen.values()), {1}, "each wall cell is in exactly one wedge")
        self.assertEqual(seen, fx.world_cells())
        self.assertTrue(all(len(w) > 0 for w in walls.values()))


class Replay(unittest.TestCase):
    def run_cli(self, *extra: str, tmp: Path) -> tuple[subprocess.CompletedProcess, Path, Path]:
        png, saved = tmp / "scout.png", tmp / "grid.json"
        r = subprocess.run([PY, "-m", "wtdd.dog.scout", "--replay", str(fx.NPZ), "--png", str(png), "--save", str(saved), *extra],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
        return r, png, saved

    def test_replay_draws_all_four_walls_from_one_origin(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            r, png, saved = self.run_cli(tmp=Path(tmp))
            self.assertEqual(r.returncode, 0, r.stderr[-1200:])
            lines = [l for l in r.stderr.splitlines() if "[wtdd:scout]" in l and "cells=" in l]
            self.assertGreaterEqual(len(lines), fx.WEDGES, "one stderr line per frame with the cells it added:\n" + r.stderr[-1200:])
            for k in range(fx.WEDGES):
                self.assertRegex(r.stderr, rf"frame {k}\b.*cells=\+?{len(fx.frame_cells(k))}\b")
            for name in ("front", "left", "back", "right"):
                self.assertIn(name, r.stderr, "the summary names every wall")
            self.assertNotIn("WARN", r.stderr)
            self.assertTrue(png.is_file())
            g = occupancy.Grid.load(saved)
            self.assertEqual(g.frames, fx.WEDGES)
            self.assertEqual(g.shape, (fx.H, fx.W), "one origin: the grid is one window, it never grew")
            np.testing.assert_allclose(g.origin, fx.ORIGIN)
            self.assertEqual(idx(g.walls(1)), set(fx.world_cells()))
            im = np.asarray(Image.open(png).convert("RGB"))
            self.assertEqual(im.shape[:2], (fx.H * occupancy.PNG_SCALE, fx.W * occupancy.PNG_SCALE))
            self.assertEqual(int(np.all(im == 0, axis=2).sum()), occupancy.PNG_SCALE ** 2 * len(fx.world_cells()), "black pixels are exactly the wall cells")

    def test_replay_warns_and_exits_2_when_a_wall_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, png, saved = self.run_cli("--frames", "4", tmp=Path(tmp))   # wedges 0..3: the right wall (225..315 deg) is never seen
            self.assertEqual(r.returncode, 2, r.stderr[-1200:])
            self.assertIn("WARN", r.stderr)
            self.assertIn("right", r.stderr)
            self.assertNotIn("left missing", r.stderr, "the left wall (45..135 deg) is wholly inside the first four wedges")
            self.assertTrue(png.is_file(), "the PNG is still written: the WARN is the finding")

    def test_replay_fails_loud_on_a_missing_npz(self):
        r = subprocess.run([PY, "-m", "wtdd.dog.scout", "--replay", "/nonexistent/spin.npz", "--png", "/tmp/never.png"],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("/nonexistent/spin.npz", r.stderr)


if __name__ == "__main__":
    unittest.main()
