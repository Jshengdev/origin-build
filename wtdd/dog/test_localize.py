"""Tests for wtdd/dog/localize.py: scan-to-map re-correction on the synthetic world of wtdd/dog/fixtures
(make_voxel_frames.py is the map, make_drift_frames.py the windows with planted odometry drift; nothing here has seen
the real dog). Run:

    python -m unittest wtdd.dog.test_localize

RED until localize.py exists. Every expectation is computed from the fixtures' declared world and drifts (plain sets and
the planted numbers), never from the matcher's own output; the drifted frames reach the session through the driver's own
decoder and Body._on_lidar, the path a live frame takes.

The contract under test (all in the odometry frame, metres and radians; a correction is a rigid 2D transform
(tx, ty, theta): p' = R(theta) p + t):
  IDENTITY, compose(a, b), apply_points(c, xy), apply_pose(c, x, y, yaw)
                            the transform algebra: compose applies a then b; apply_pose rotates the position and adds
                            theta to the yaw
  delta_about(pivot, dx, dy, dtheta)
                            the transform that turns by dtheta about `pivot` (the dog) and then moves by (dx, dy): what
                            one window's correction is
  match(grid, xy, pivot, search_m=, search_deg=, step_deg=, threshold=)
                            correlative scan matching, numpy only: every (dx, dy, dtheta) on the cell lattice within
                            +-search_m / +-search_deg (step_deg) is scored as the fraction of the window's cells that
                            land on a grid cell seen >= threshold times; returns {dx, dy, dtheta, score, score0 (the
                            fraction at zero offset), n (cells scored), candidates, ms}; ties go to the smallest offset,
                            so a wall along x never moves the pose along x; fewer than MIN_CELLS cells is a ValueError
  over_cap(m, cap_m=, cap_deg=)   None when the offset is plausible, else a string naming the cap it exceeds; the cap is
                            inside the search window (CAP_M < SEARCH_M, CAP_DEG < SEARCH_DEG) so it can fire
  DogSession._on_frame      every window: the band's cells through the correction held -> match against the grid ->
                            applied (a pose.corrected row ok, the correction composed, the window drawn into the grid
                            through it) | rejected past the cap (a pose.corrected row ok=False naming the cap, nothing
                            drawn, the correction kept) | unmatched below MIN_SCORE (no row, a WARN line, drawn through
                            the correction held: the map grows into new rooms); counts in lidar()["localize"]
  pose.corrected row        {tool: "pose.corrected", agent: "dog", args: {dx, dy, dtheta, score, shift_id, windows,
                            applied, rejected, unmatched, skipped, largest_m, ...}, state_before/after: {corr, ...}, ok,
                            response_or_error, latency_ms}; cached False, source live
  S7 (Johnny 2026-09-27)    "one message every 30 seconds or new update": applied windows wait in one summary row,
                            written at most once per SUMMARY_S (30 s) since the last pose.corrected row; a new update (an
                            applied nudge over one grid cell, any rejection) is its own row at once, the summary before
                            it first; every row counts every window since the last row (windows, and by verdict); a
                            grid clear or a stream stop writes the pending summary. The receipts panel (ui/index.html)
                            keeps pose.corrected out of its 25 rows and shows the newest one as one line.
  DogSession.map_pose       the believed pose is the odometry pose through the correction, then nav.to_map
  DogSession.calibrate      the drag still works and still logs: it ties the corrected pose to the dragged point (the
                            dot lands exactly there), keeps the correction (the grid stays consistent with it), and its
                            dog.calibrate row carries the correction in force under args.corr
  DogSession.grid_clear     a power cycle: the correction resets with the grid
"""
from __future__ import annotations
import asyncio
import io
import math
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import numpy as np

from . import lidar, localize, nav, occupancy
from .fixtures import make_drift_frames as dfx
from .fixtures import make_voxel_frames as fx

CAL = {"odom": [0.0, 0.0, 0.0], "map": [449.0, 491.0], "heading": 1.5708}   # nav.calibration shape: at map (449, 491) facing down the page
TOL_M = 1.5 * fx.RES          # a recovered offset may be off by a cell and a half (the lattice, plus a snapped rotation)
TOL_RAD = math.radians(1.0)   # and by one yaw step


def frames(module) -> list[dict]:
    return [lidar.decode(fx.decode_wire(b)) for b in module.blobs()]


def idx(xy) -> set[tuple[int, int]]:
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    return {(int(round(x / fx.RES)), int(round(y / fx.RES))) for x, y in xy}


def band_xy(d: dict) -> np.ndarray:
    """The window's unique (x, y) in the band, sorted: what the session hands the matcher."""
    p = d["points"]
    keep = p[(p[:, 2] >= lidar.Z_MIN) & (p[:, 2] <= lidar.Z_MAX)][:, :2]
    return np.unique(keep, axis=0)


def accumulated() -> occupancy.Grid:
    fr = frames(fx)
    g = occupancy.Grid.from_frame(fr[0])
    for d in fr:
        g.update_frame(d)
    return g


def stop(s) -> None:
    s.loop.call_soon_threadsafe(s.loop.stop)
    while s.loop.is_running():
        time.sleep(0.01)
    s.loop.close()


class Fixture(unittest.TestCase):
    def test_drift_npz_decodes_through_the_driver_to_the_declared_drifted_world(self):
        fr = frames(dfx)
        self.assertEqual(len(fr), len(dfx.ORIGINS))
        for k, d in enumerate(fr):
            self.assertEqual((d["width"], d["resolution"], d["frame"]), ([fx.W, fx.H, fx.D], fx.RES, fx.FRAME_ID))
            np.testing.assert_allclose(d["origin"][:2], dfx.ORIGINS[k])
            self.assertEqual(idx(band_xy(d)), dfx.frame_cells(k), f"frame {k}: the decoded band is not the declared drifted window")
            self.assertGreaterEqual(len(dfx.frame_cells(k)), 100, f"frame {k}: too thin a window to match")

    def test_drifts_are_whole_cells_and_the_true_cells_are_the_map(self):
        world = fx.world_cells()
        for k in range(3):   # the walk's windows: their true cells are cells of the map fixture
            cx, cy = dfx.drift_cells(k)
            np.testing.assert_allclose((cx * fx.RES, cy * fx.RES), dfx.DRIFTS[k])
            wall = {c for c in dfx.true_cells(k) if c[0] == 40}   # WALL_A at x = 2.0 m
            self.assertTrue(wall and wall <= set(world), f"frame {k}: WALL_A moved back by the drift is not on the map")
        self.assertTrue(dfx.true_cells(3).isdisjoint(world), "frame 3 is a room the map has never seen")


class Transform(unittest.TestCase):
    def test_identity_and_compose(self):
        xy = np.array([[1.0, 2.0], [-0.5, 0.25]])
        np.testing.assert_allclose(localize.apply_points(localize.IDENTITY, xy), xy)
        a = localize.delta_about((0.0, 0.0), 0.1, -0.2, 0.05)
        b = localize.delta_about((1.0, 1.0), -0.3, 0.1, -0.02)
        np.testing.assert_allclose(localize.apply_points(localize.compose(a, b), xy),
                                   localize.apply_points(b, localize.apply_points(a, xy)), atol=1e-12)
        self.assertAlmostEqual(localize.compose(a, b)[2], 0.05 - 0.02)

    def test_delta_about_turns_around_the_pivot(self):
        c = (2.0, -1.0)
        t = localize.delta_about(c, 0.0, 0.0, math.radians(30))
        np.testing.assert_allclose(localize.apply_points(t, np.array([c])), [c], atol=1e-12, err_msg="the pivot stays put")
        t2 = localize.delta_about(c, 0.3, -0.1, math.radians(30))
        np.testing.assert_allclose(localize.apply_points(t2, np.array([c])), [[2.3, -1.1]], atol=1e-12)

    def test_apply_pose_moves_the_position_and_adds_theta_to_the_yaw(self):
        t = localize.delta_about((0.0, 0.0), 0.15, -0.05, 0.1)
        x, y, yaw = localize.apply_pose(t, 1.0, 0.0, 0.5)
        np.testing.assert_allclose([x, y], localize.apply_points(t, np.array([[1.0, 0.0]]))[0])
        self.assertAlmostEqual(yaw, 0.6)


class Match(unittest.TestCase):
    def setUp(self):
        self.grid = accumulated()
        self.win = band_xy(frames(fx)[1])               # the walk's middle window: WALL_A, WALL_B's middle and the blob
        self.pivot = (fx.ORIGINS[1][0] + fx.W * fx.RES / 2, fx.ORIGINS[1][1] + fx.H * fx.RES / 2)   # the window's centre

    def test_constants_leave_the_cap_inside_the_search(self):
        self.assertLess(localize.CAP_M, localize.SEARCH_M, "a cap the search cannot reach never fires")
        self.assertLess(localize.CAP_DEG, localize.SEARCH_DEG)
        self.assertGreater(localize.MIN_SCORE, 0.0)
        self.assertGreaterEqual(localize.MIN_CELLS, 1)

    def test_an_unshifted_window_is_left_alone(self):
        m = localize.match(self.grid, self.win, self.pivot)
        self.assertTrue({"dx", "dy", "dtheta", "score", "score0", "n", "ms"} <= set(m), sorted(m))
        self.assertEqual((m["dx"], m["dy"], m["dtheta"]), (0.0, 0.0, 0.0))
        self.assertGreaterEqual(m["score"], 0.85)
        self.assertEqual(m["score"], m["score0"])
        self.assertEqual(m["n"], len(self.win))
        self.assertLess(m["ms"], 500, "not vectorised: a window must never take a state period")

    def test_a_known_offset_is_recovered_within_tolerance(self):
        for dx, dy, deg in [(0.15, -0.10, 0.0), (0.0, 0.0, 3.0), (-0.20, 0.10, -4.0), (0.10, 0.15, 2.0)]:
            with self.subTest(dx=dx, dy=dy, deg=deg):
                shifted = localize.apply_points(localize.delta_about(self.pivot, dx, dy, math.radians(deg)), self.win)
                m = localize.match(self.grid, shifted, self.pivot)
                back = localize.apply_points(localize.delta_about(self.pivot, m["dx"], m["dy"], m["dtheta"]), shifted)
                self.assertLessEqual(float(np.abs(back - self.win).max()), TOL_M, f"recovered {m}")
                self.assertLessEqual(abs(m["dtheta"] + math.radians(deg)), TOL_RAD + 1e-9, f"recovered {m}")
                self.assertGreaterEqual(m["score"], 0.85, f"recovered {m}")
                self.assertGreaterEqual(m["score"], m["score0"])

    def test_a_wall_along_x_does_not_move_the_pose_along_x(self):
        wall_b = np.array([[gx * fx.RES, 56 * fx.RES] for gx in range(-40, 41)])   # WALL_B's middle, inside the map at every shift
        m = localize.match(self.grid, wall_b, (0.0, 0.0))
        self.assertEqual((m["dx"], m["dy"], m["dtheta"]), (0.0, 0.0, 0.0), f"a tie must go to no correction: {m}")
        self.assertEqual(m["score"], 1.0)

    def test_an_empty_grid_matches_nothing(self):
        g = occupancy.Grid(fx.RES, (-3.2, -3.2), fx.FRAME_ID)
        m = localize.match(g, self.win, self.pivot)
        self.assertEqual((m["dx"], m["dy"], m["dtheta"], m["score"]), (0.0, 0.0, 0.0, 0.0))

    def test_too_few_cells_is_refused_loud(self):
        with self.assertRaises(ValueError) as cm:
            localize.match(self.grid, self.win[:3], self.pivot)
        self.assertIn("MIN_CELLS", str(cm.exception))

    def test_the_cap(self):
        self.assertIsNone(localize.over_cap({"dx": 0.10, "dy": -0.05, "dtheta": math.radians(2)}))
        far = localize.over_cap({"dx": 0.35, "dy": 0.0, "dtheta": 0.0})
        self.assertIsInstance(far, str)
        self.assertIn("cap", far.lower())
        self.assertIsInstance(localize.over_cap({"dx": 0.0, "dy": 0.0, "dtheta": math.radians(localize.CAP_DEG + 1)}), str)
        m = localize.match(self.grid, localize.apply_points(localize.delta_about(self.pivot, -0.35, 0.0, 0.0), self.win), self.pivot)
        self.assertAlmostEqual(m["dx"], 0.35, delta=TOL_M, msg=f"the search must reach the jump so the cap can judge it: {m}")
        self.assertIsNotNone(localize.over_cap(m))


class Session(unittest.TestCase):
    """The live path, offline: the driver's own messages -> Body._on_lidar -> DogSession._on_frame -> match -> the
    correction, the rows, the grid. The map fixture's three windows build the grid; the drift fixture's four follow."""

    def setUp(self):
        from .. import ledger
        from . import session
        from .body import Body
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(ledger, "LEDGER", Path(self.tmp) / "ledger.jsonl"))
        self.enterContext(mock.patch.object(session, "CAL_FILE", Path(self.tmp) / "dog_cal.json"))
        self.enterContext(mock.patch.object(session, "GRID_FILE", Path(self.tmp) / "grid.json"))
        self.enterContext(mock.patch.object(lidar, "subscribe", mock.AsyncMock()))
        self.err = self.enterContext(redirect_stderr(io.StringIO()))
        # both fixtures' worlds have walls and no floor: the surface filter (lidar.keep, test_surfaces) would keep
        # nothing; these tests are about the re-correction, so the windows pass as they came (the old behaviour)
        self.enterContext(mock.patch.dict("os.environ", {"WTDD_SURFACES": "0"}))
        self.ledger, self.body, self.s = ledger, Body(), session.DogSession()
        self.addCleanup(stop, self.s)
        self.s.body = self.body
        asyncio.run(self.body.lidar_on(self.s._on_frame))
        for b in fx.blobs():
            self.body._on_lidar(fx.decode_wire(b))
        self.n0 = len(self.ledger.rows())
        self.loc0 = dict(self.s.lidar()["localize"])

    def feed_drift(self) -> list[dict]:
        for b in dfx.blobs():
            self.body._on_lidar(fx.decode_wire(b))
        return [r for r in self.ledger.rows()[self.n0:] if r["tool"] == "pose.corrected"]

    def test_every_window_is_matched_and_the_rows_say_what_happened(self):
        rows = self.feed_drift()
        self.assertEqual([r["ok"] for r in rows], [True, True, False], [r.get("response_or_error") for r in rows])
        for r in rows:
            self.assertEqual((r["agent"], r["cached"], r["source"]), ("dog", False, "live"))
            self.assertTrue({"dx", "dy", "dtheta", "score", "shift_id"} <= set(r["args"]), sorted(r["args"]))
            self.assertIn("corr", r["state_before"])
            self.assertIn("corr", r["state_after"])
            self.assertIsInstance(r["latency_ms"], int)
        self.assertAlmostEqual(rows[0]["args"]["dx"], 0.10, delta=TOL_M)
        self.assertAlmostEqual(rows[0]["args"]["dy"], -0.05, delta=TOL_M)
        self.assertAlmostEqual(rows[0]["args"]["dtheta"], 0.0, delta=TOL_RAD)
        self.assertGreaterEqual(rows[0]["args"]["score"], 0.85)
        self.assertAlmostEqual(rows[1]["args"]["dx"], 0.05, delta=TOL_M, msg="the second window corrects the change since the first")
        self.assertAlmostEqual(rows[1]["args"]["dy"], 0.0, delta=TOL_M)
        self.assertAlmostEqual(rows[2]["args"]["dx"], 0.35, delta=TOL_M)
        self.assertIn("cap", rows[2]["response_or_error"].lower())
        loc = self.s.lidar()["localize"]
        self.assertEqual({k: loc[k] - self.loc0[k] for k in ("applied", "rejected", "unmatched")}, {"applied": 2, "rejected": 1, "unmatched": 1})
        self.assertIn("WARN", self.err.getvalue())
        self.assertEqual(self.body.lidar_points()["cb_errors"], 0, "a rejected or unmatched window is a verdict, not a callback failure")

    def test_the_correction_accumulates_and_the_grid_stays_unsmeared(self):
        self.feed_drift()
        x, y, th = localize.apply_pose(self.s.corr, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(x, 0.15, delta=TOL_M)
        self.assertAlmostEqual(y, -0.05, delta=TOL_M)
        self.assertAlmostEqual(th, 0.0, delta=TOL_RAD)
        g = self.s.grid
        self.assertEqual(g.frames, 3 + 2 + 1, "applied and unmatched windows are drawn, the rejected one is not")
        self.assertEqual(g.cell(2.0, 0.0), 5, "WALL_A: three map windows plus two corrected ones, all on one cell")
        self.assertEqual((g.cell(1.9, 0.0), g.cell(1.85, 0.0), g.cell(1.5, 0.0)), (0, 0, 0), "no drifted copy of WALL_A")
        self.assertEqual(g.cell(12.0, 13.0), 1, "the new room is drawn where it is, through the correction held")
        self.assertEqual(g.cell(11.85, 13.05), 0)

    def test_the_believed_pose_is_the_corrected_one(self):
        self.feed_drift()
        self.s.cal = dict(CAL)
        st = {"position": [0.4, 0.2, 0.0], "rpy": [0.0, 0.0, 0.3], "age_ms": 0, "n": 1}
        x, y, yaw = localize.apply_pose(self.s.corr, 0.4, 0.2, 0.3)
        want = nav.to_map(CAL, (x, y), yaw)
        raw = nav.to_map(CAL, (0.4, 0.2), 0.3)
        pose = self.s.map_pose(st)
        self.assertEqual(pose["p"], [round(want[0]), round(want[1])])
        self.assertEqual(pose["heading_deg"], round(math.degrees(want[2]), 1))
        self.assertNotEqual(pose["p"], [round(raw[0]), round(raw[1])], "the correction moved the dot")
        self.assertIn("corr", self.s.state())

    def test_the_drag_still_works_and_still_logs(self):
        self.feed_drift()
        corr = tuple(self.s.corr)
        st = {"position": [0.4, 0.2, 0.0], "rpy": [0.0, 0.0, 0.3], "age_ms": 0, "n": 1}
        with mock.patch.object(self.s, "run", return_value=st):
            out = self.s.calibrate((300.0, 900.0), 0.0)
        self.assertEqual(out["p"], [300, 900], "the dot lands where it was dragged, correction and all")
        self.assertEqual(self.s.map_pose(st)["p"], [300, 900])
        self.assertEqual(tuple(self.s.corr), corr, "the drag re-ties the map; the matcher's belief stays")
        row = [r for r in self.ledger.rows() if r["tool"] == "dog.calibrate"][-1]
        self.assertTrue(row["ok"])
        self.assertIn("corr", row["args"], "the drag's row says which correction was in force")
        self.assertEqual(row["state_after"]["map"]["p"], [300, 900])

    def test_a_grid_clear_resets_the_correction(self):
        self.feed_drift()
        self.assertNotEqual(tuple(self.s.corr), localize.IDENTITY)
        self.s.grid_clear("test: power cycle")
        self.assertEqual(tuple(self.s.corr), localize.IDENTITY)
        self.assertIsNone(self.s.grid)

    # ---- review round 1: added after the build, each seen failing on 59ee282 before the fix
    def test_a_window_the_grid_refuses_moves_nothing(self):
        """The window is drawn before the belief moves: a grid that refuses it (01's MAX_SIDE) leaves the correction,
        the counts and the ledger as they were, and Body counts the raise."""
        blobs = dfx.blobs()
        self.body._on_lidar(fx.decode_wire(blobs[0]))
        corr, frames, n = tuple(self.s.corr), self.s.grid.frames, len(self.ledger.rows())
        self.assertNotEqual(corr, localize.IDENTITY, "the first drifted window was applied")
        with mock.patch.object(self.s.grid, "update", side_effect=ValueError("grid would pass MAX_SIDE: refused")):
            self.body._on_lidar(fx.decode_wire(blobs[1]))
        self.assertEqual(tuple(self.s.corr), corr, "the dot does not move for a window the grid did not take")
        self.assertEqual([r["tool"] for r in self.ledger.rows()[n:]], [], "no pose.corrected row for a correction never applied")
        self.assertEqual(self.s.grid.frames, frames)
        self.assertEqual(self.s.lidar()["localize"]["applied"] - self.loc0["applied"], 1, "the refused window is not counted applied")
        self.assertEqual(self.body.lidar_points()["cb_errors"], 1)

    def test_a_clear_under_a_correction_asks_for_the_drag_again(self):
        """The drag tied the corrected pose; clearing the correction moves the dot by it, so the remote asks for the drag
        (recheck) instead of reading 'located'."""
        st = {"position": [0.4, 0.2, 0.0], "rpy": [0.0, 0.0, 0.3], "age_ms": 0, "n": 1}
        with mock.patch.object(self.s, "run", return_value=st):
            self.s.calibrate((300.0, 900.0), 0.0)
        self.feed_drift()
        self.assertFalse(self.s.recheck)
        self.s.grid_clear("test: a bad grid, the dog was not power-cycled")
        self.assertTrue(self.s.state()["recheck"], "the tie was made through a correction that is gone")
        row = [r for r in self.ledger.rows() if r["tool"] == "dog.grid_clear"][-1]
        self.assertTrue(row["ok"])
        self.assertTrue(row["state_after"]["recheck"])

    def test_every_unmatched_window_is_one_line(self):
        """An unmatched window prints one stderr line, as applied and rejected ones do; only its WARN is rate-limited, so
        a new corridor does not go quiet after five windows while the counter climbs."""
        with mock.patch.object(localize, "MIN_SCORE", 1.01):   # nothing clears the gate: every window is unmatched
            self.feed_drift()
            self.feed_drift()
        n = self.s.lidar()["localize"]["unmatched"]
        self.assertGreater(n, 5, "past the WARN's rate limit")
        self.assertEqual(len([ln for ln in self.err.getvalue().splitlines() if "localize unmatched" in ln]), n)

    # ---- S7, Johnny 2026-09-27: "one message every 30 seconds or new update". Live, 05b wrote 2,511 pose.corrected rows
    # in 5 minutes, each applied with zero nudge, and a decision scrolled off the receipts panel's 25 rows in seconds.
    def clock(self) -> list[float]:
        """The session's monotonic clock, set by the test (the rest of `time` passes through); starts now, so setUp's
        row (the session's first correction, written at once) is the last row."""
        from . import session
        now = [time.monotonic()]
        self.enterContext(mock.patch.object(session, "time", mock.Mock(wraps=time, monotonic=lambda: now[0])))
        return now

    def feed(self, now: list[float], t: float, blob: bytes) -> None:
        now[0] = t
        self.body._on_lidar(fx.decode_wire(blob))

    def corrected(self) -> list[dict]:
        return [r for r in self.ledger.rows()[self.n0:] if r["tool"] == "pose.corrected"]

    def test_zero_nudges_at_ten_windows_a_second_for_65_s_are_at_most_3_rows(self):
        now = self.clock()
        t0, blob = now[0], fx.blobs()[1]   # the map's middle window again: applied with zero nudge, as live
        for k in range(650):
            self.feed(now, t0 + k / 10, blob)
        self.enterContext(mock.patch.object(lidar, "unsubscribe", mock.Mock()))
        self.s.lidar(False)   # the stream stops: the pending summary is written, nothing dropped
        rows = self.corrected()
        self.assertEqual(self.s.lidar()["localize"]["applied"] - self.loc0["applied"], 650, "every window applied")
        self.assertLessEqual(len(rows), 3, [r["args"].get("windows") for r in rows][:5])
        self.assertEqual(sum(r["args"]["windows"] for r in rows), 650, "the rows' counts cover every window")
        self.assertEqual(sum(r["args"]["applied"] for r in rows), 650)
        self.assertEqual({r["args"]["largest_m"] for r in rows}, {0.0})
        self.assertTrue(all(r["ok"] for r in rows))

    def test_a_nudge_over_one_cell_is_written_at_once(self):
        now = self.clock()
        t0 = now[0]
        self.feed(now, t0 + 0.1, fx.blobs()[1])    # zero nudge: pending, the last row was setUp's
        self.feed(now, t0 + 0.2, dfx.blobs()[0])   # the drift fixture's jump, 0.10 m and -0.05 m: over one 0.05 m cell
        rows = self.corrected()
        self.assertEqual([(r["args"].get("windows"), r["args"].get("applied")) for r in rows], [(1, 1), (1, 1)],
                         "the pending window as its summary first, then the jump as its own row, inside the same second")
        jump = rows[-1]["args"]
        self.assertAlmostEqual(jump["dx"], 0.10, delta=TOL_M)
        self.assertAlmostEqual(jump["dy"], -0.05, delta=TOL_M)
        self.assertGreater(jump["largest_m"], fx.RES)
        self.assertAlmostEqual(jump["largest_m"], math.hypot(jump["dx"], jump["dy"]), places=3)
        self.assertEqual(rows[0]["args"]["largest_m"], 0.0)

    def test_a_rejection_is_written_at_once(self):
        now = self.clock()
        t0, blobs = now[0], dfx.blobs()
        for k in range(3):   # the jump (its own row), a one-cell step (pending), the 0.35 m jump past the cap
            self.feed(now, t0 + 0.1 * (k + 1), blobs[k])
        rows = self.corrected()
        self.assertEqual([(r["ok"], r["args"].get("windows"), r["args"].get("rejected")) for r in rows],
                         [(True, 1, 0), (True, 1, 0), (False, 1, 1)])
        self.assertIn("cap", rows[-1]["response_or_error"].lower())

    def test_a_clear_writes_the_pending_summary_first(self):
        now = self.clock()
        for k in range(3):
            self.feed(now, now[0] + 0.1, fx.blobs()[1])
        self.s.grid_clear("test: the summary is not lost with the grid")
        got = [(r["tool"], r["args"].get("windows")) for r in self.ledger.rows()[self.n0:]]
        self.assertEqual(got, [("pose.corrected", 3), ("dog.grid_clear", None)])

    def test_a_clear_counts_the_windows_no_pose_corrected_row_will(self):
        """Unmatched windows since the last pose.corrected row have no applied window to ride on and their counters
        reset with the grid: the dog.grid_clear row counts them, so every window is in a row."""
        with mock.patch.object(localize, "MIN_SCORE", 1.01):   # nothing clears the gate: every window is unmatched
            self.assertEqual(self.feed_drift(), [])
        self.s.grid_clear("test: four unmatched windows")
        row = [r for r in self.ledger.rows() if r["tool"] == "dog.grid_clear"][-1]
        self.assertEqual(row["args"].get("windows_since_pose_corrected"),
                         {"windows": 4, "applied": 0, "rejected": 0, "unmatched": 4, "skipped": 0})


class Page(unittest.TestCase):
    """S7: the receipts panel (ui/index.html) shows the 25 newest rows that are not pose.corrected, plus one line for the
    newest pose.corrected row from that row's own windows and largest_m (the page counts nothing). Reads the source, as
    wtdd/test_drive_keys.py does; the headless check is in the PR body."""
    PAGE = (Path(__file__).resolve().parents[2] / "ui" / "index.html").read_text()

    def line(self, needle: str) -> str:
        return next((l for l in self.PAGE.splitlines() if needle in l), "")

    def test_corrections_are_filtered_out_of_the_25(self):
        self.assertIn('.filter(r => r.tool !== "pose.corrected").slice(0, 25)', self.line(".slice(0, 25)"))

    def test_the_newest_correction_is_one_line_from_its_own_fields(self):
        pc = self.line('.find(r => r.tool === "pose.corrected")')
        self.assertIn("[...ledger].reverse()", pc, "the newest, not the oldest")
        self.assertIn("args?.windows", pc)
        self.assertIn("args?.largest_m", pc)


if __name__ == "__main__":
    unittest.main()
