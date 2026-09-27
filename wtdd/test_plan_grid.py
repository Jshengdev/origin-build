"""The planner over the occupancy grid (goals/roadmap.md 06): A* over the grid 01 accumulates from the dog's LiDAR
(wtdd/dog/occupancy.py), obstacles inflated by the dog's half-width, no-go zones (04's schema: {name, label, poly,
nogo: true} in the map's zones[]) as hard blocks, the drawn rooms as the fallback when there is no grid or no
calibration, and a replan when the next waypoint of a route is now occupied. Run:

    python -m unittest wtdd.test_plan_grid -v

RED until wtdd/plan.py grows the grid cost map, occupied() and replan(), and the follower calls them.

Fixtures. wtdd/fixtures/make_grid_wall.py builds the grid in memory: one 1.5 m wall across the top of the living room
(map x ≈ 474, y 829..992), a 0.3 m blob wherever a test plants one, both seen THRESHOLD times, tied to the map by CAL.
wtdd/fixtures/map_nogo.json is 04's zone fixture (the shipped rooms plus the no-go zone nogo-1, x 450..510, y
1040..1250), copied byte for byte so this branch and 04 merge as one. This module points plan.MAP at a scratch COPY of
that map and WTDD_LEDGER at a scratch file BEFORE importing the package (the pattern of wtdd/chat/test_chat.py), so no
test touches ui/map.json, the real ledger, a light or the dog. The follower tests run DogSession.follow with a
teleporting body: nav.steer is replaced by a step that puts the believed pose on the target and reports it reached, so
the follower's own loop (waypoints, stops, the occupied check, the replan) runs unchanged with no dog and no clock.

The contract under test (wtdd/plan.py; the rows in the ledger; NIGHT-1 contracts section E):
  plan(a, b, grid=None, cal=None, threshold=THRESHOLD)
        grid and cal given: the cost map is the grid's walls (cells seen >= threshold times, occupancy.walls) projected
        into map pixels through cal (occupancy.to_map_px), each landing cell blocked and inflated by HALF_WIDTH cells;
        no-go zones blocked before the same erosion (04's rule, so the body and not only the line stays out); the drawn
        rooms are NOT consulted. Returns {path, cells, searched, length_px, length_m, cost_map: "grid"}.
        No grid, or no cal: the rooms fallback (today's planner, zones blocked), returns cost_map "rooms" and why
        ("no grid" | "not calibrated"), and prints one WARN line to stderr.
        One plan.route row (agent plan, app map): args {from, to, cell_px, cost_map, why?, threshold, walls (blocked wall
        cells in the planner's lattice before inflation, 0 on rooms), nogo: [zone names]}; state_after {cells, searched,
        length_px, length_m, waypoints}.
  occupied(p, grid, cal, threshold=THRESHOLD) -> bool
        True when map point p sits in a wall cell or within HALF_WIDTH cells of one, on the SAME lattice the cost map
        uses, so a detour the planner returns is never "occupied" to the follower; False with no grid or no cal.
  replan(p, path, i, grid, cal, threshold=THRESHOLD)
        the dog at map point p was about to drive to path[i], which is now occupied: a detour from p to path[j], the
        first later waypoint that is not occupied, over the grid cost map (zones blocked). Returns {path (planned
        waypoints from p to path[j]), blocked: {index: i, waypoint}, rejoin: {index: j, waypoint}, skipped: [i..j-1],
        cells, searched, length_px, length_m, cost_map: "grid"}. Every waypoint from i to the end occupied (the goal is
        blocked), or no detour: ValueError, the row ok false, the error naming what is occupied.
        One plan.replanned row (agent plan, app map), never a plan.route row: args {from, blocked, rejoin, skipped,
        cost_map, threshold, walls, nogo, cell_px, shift_id}; state_after {cells, searched, length_px, length_m,
        waypoints}.
  DogSession._follow (wtdd/dog/session.py)
        before driving to waypoint i it asks occupied(path[i], session.grid, session.cal); when so it calls replan(),
        drives the detour's waypoints (no stop on a detour), then continues at the rejoin index; a stop whose waypoint
        was skipped is never waited on and is reported. follow_state (GET /dog/state .follow) gains replans: [{at,
        rejoin, waypoints, skipped_stops}] (an empty list when nothing was replanned); the dog.follow row's state_after
        gains replans (a count) and skipped_stops. reached stays the taught indices reached, in order. With no blob
        nothing changes: every waypoint in order, every stop honoured, no plan.replanned row.
  wtdd/tools/plan_path.py run(from, to, save, grid=True)
        grid=True (the default) plans over the grid when one exists and is tied to the map: the session's grid and
        calibration in the API process, else ui/grid.json with the calibration saved in it (the DEMO_CACHE fallback 01
        draws from); grid=False, or no grid, is the rooms fallback. The result carries cost_map.
"""
from __future__ import annotations
import asyncio
import io
import json
import math
import os
import shutil
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import numpy as np

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-plan-grid-test-"))
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "map_nogo.json"
TMP_MAP = _TMP / "map.json"
shutil.copy(FIXTURE, TMP_MAP)
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")

from wtdd import ledger, plan  # noqa: E402
from wtdd.dog import occupancy  # noqa: E402
from wtdd.field import inside, room_of  # noqa: E402
from wtdd.fixtures import make_grid_wall as fx  # noqa: E402

CAL = fx.CAL
MAP_DICT = json.loads(FIXTURE.read_text())
ZONE = next(z for z in MAP_DICT["zones"] if z.get("nogo"))
POLY = ZONE["poly"]
CLEAR_PX = (plan.half_width() - 1) * plan.CELL   # the dog is HALF_WIDTH cells wide: its body, not just the route's line, stays out
ROUTE = [[300 + 50 * k, 1400] for k in range(8)]   # a taught route along the living room's bottom, x 300..650 at y 1400
BLOB_AT = (500, 1400)                              # a blob on waypoint 4; its inflation covers waypoints 3..5 (measured in Replan)
LINE = [[300, 1400], [650, 1400]]                  # S6b: two dots, the straight line Johnny draws through an obstacle


def setUpModule():
    global _map_patch
    _map_patch = mock.patch.object(plan, "MAP", TMP_MAP)   # every read of the map by the planner (and by replan from the follower)
    _map_patch.start()


def tearDownModule():
    _map_patch.stop()


def samples(pts, step=1.0):
    """Every point along the polyline at `step` px (both ends included): a route is its segments, not its corners."""
    for a, b in zip(pts, pts[1:]):
        n = max(1, math.ceil(math.dist(a, b) / step))
        for k in range(n + 1):
            yield (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)


def dist_to_poly(p, poly) -> float:
    """Distance from p to the polygon's outline (0 when on it; the tests reject inside separately)."""
    best = math.inf
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.dist(p, (ax + t * dx, ay + t * dy)))
    return best


def nearest(pts, obstacles_px) -> tuple[float, tuple[int, int] | None]:
    """The closest any of pts comes to any obstacle pixel: (distance, that point)."""
    ob = np.asarray(obstacles_px, dtype=float).reshape(-1, 2)
    best: tuple[float, tuple[int, int] | None] = (math.inf, None)
    for p in pts:
        d = float(np.min(np.hypot(ob[:, 0] - p[0], ob[:, 1] - p[1])))
        if d < best[0]:
            best = (d, (round(p[0]), round(p[1])))
    return best


def rows_since(n0: int, tool: str) -> list[dict]:
    return [r for r in ledger.rows()[n0:] if r["tool"] == tool]


def stop(s) -> None:
    """A DogSession runs its own event loop thread; a test stops and closes it (wtdd/dog/test_occupancy.py)."""
    s.loop.call_soon_threadsafe(s.loop.stop)
    while s.loop.is_running():
        time.sleep(0.01)
    s.loop.close()


class Fixture(unittest.TestCase):
    def test_the_saved_grid_is_the_recipe_and_lands_where_the_arithmetic_says(self):
        """grid_wall.json (the CLI pair's ui/grid.json) is grid() saved; its walls through 01's projection are the pixels
        cells_px() computes by hand, so a clearance measured against wall_px() is a clearance from what the planner sees."""
        saved = occupancy.Grid.load(fx.OUT)
        g = fx.grid()
        np.testing.assert_array_equal(saved.counts, g.counts)
        self.assertEqual((saved.frames, saved.cal), (occupancy.THRESHOLD, CAL))
        seen = sorted(map(tuple, occupancy.to_map_px(g.walls(), CAL).tolist()))
        self.assertEqual(seen, fx.wall_px())
        self.assertEqual(len(seen), 31, "1.5 m of wall at 0.05 m is 31 cells")
        self.assertTrue(any(abs(y - 900) <= plan.CELL and 300 < x < 650 for x, y in seen), "the wall crosses the line y = 900, x 300..650")
        blob = fx.blob_px(BLOB_AT)
        self.assertEqual(len(blob), 49, "a 0.3 m blob at 0.05 m is 7 x 7 cells")
        self.assertLessEqual(nearest([BLOB_AT], blob)[0], 2 * plan.CELL)


class CostMap(unittest.TestCase):
    """A route over the grid keeps the dog's half-width from every wall cell and from every no-go zone; without a grid
    or a calibration the drawn rooms are the cost map and the row says so."""

    def setUp(self):
        self.n0 = len(ledger.rows())

    def test_a_route_avoids_the_inflated_wall(self):
        g, a, b = fx.grid(), (300, 900), (650, 900)
        wall = fx.wall_px()
        out = plan.plan(a, b, grid=g, cal=CAL)
        pts = out["path"]
        self.assertEqual(out["cost_map"], "grid")
        self.assertGreaterEqual(len(pts), 3, f"a straight line crosses the wall; the route must bend: {pts}")
        self.assertLessEqual(math.dist(pts[0], a), plan.CELL)
        self.assertLessEqual(math.dist(pts[-1], b), plan.CELL)
        d, at = nearest(samples(pts), wall)
        self.assertGreaterEqual(d, CLEAR_PX, f"route passes {at} within {d:.0f} px of the wall: {pts}")
        rows = rows_since(self.n0, "plan.route")
        self.assertEqual(len(rows), 1, "one plan.route row")
        r = rows[0]
        self.assertTrue(r["ok"])
        self.assertEqual((r["agent"], r["app"]), ("plan", "map"))
        self.assertEqual(r["args"]["cost_map"], "grid")
        self.assertEqual(r["args"]["threshold"], occupancy.THRESHOLD)
        self.assertGreater(r["args"]["walls"], 0, "the receipt counts the wall cells the planner blocked")
        self.assertEqual(r["args"]["nogo"], [ZONE["name"]], "the receipt names the zones the planner blocked")
        self.assertEqual(r["state_after"]["waypoints"], len(pts))
        self.assertEqual(r["state_after"]["length_px"], out["length_px"])

    def test_a_route_avoids_a_no_go_zone_on_the_grid(self):
        """from=300,1100 to=650,1100 runs straight through nogo-1: on the grid cost map the zone is a hard block too."""
        out = plan.plan((300, 1100), (650, 1100), grid=fx.grid(), cal=CAL)
        pts = out["path"]
        self.assertEqual(out["cost_map"], "grid")
        hits = [p for p in samples(pts) if inside(p, POLY)]
        self.assertEqual(hits, [], f"planned route enters {ZONE['name']} at {hits[:1]} ({len(hits)} px of it): {pts}")
        for p in samples(pts):
            self.assertGreaterEqual(dist_to_poly(p, POLY), CLEAR_PX, f"route passes {p} within {CLEAR_PX} px of {ZONE['name']}: {pts}")
        r = rows_since(self.n0, "plan.route")[0]
        self.assertEqual((r["args"]["cost_map"], r["args"]["nogo"]), ("grid", [ZONE["name"]]))

    def test_the_rooms_fallback_blocks_the_zone_too(self):
        """No grid: today's planner over the drawn rooms, with 04's zone block; the row says which cost map and why."""
        out = plan.plan((300, 1100), (650, 1100))
        pts = out["path"]
        self.assertEqual(out["cost_map"], "rooms")
        self.assertEqual([p for p in samples(pts) if inside(p, POLY)], [], f"the fallback plans through {ZONE['name']}: {pts}")
        for p in samples(pts):
            self.assertGreaterEqual(dist_to_poly(p, POLY), CLEAR_PX, f"route passes {p} within {CLEAR_PX} px of {ZONE['name']}: {pts}")
            self.assertIsNotNone(room_of(p, MAP_DICT["rooms"]), f"the fallback keeps the route inside the drawn rooms: {p}")
        r = rows_since(self.n0, "plan.route")[0]
        self.assertEqual((r["args"]["cost_map"], r["args"]["nogo"], r["args"]["walls"]), ("rooms", [ZONE["name"]], 0))
        self.assertIn("no grid", r["args"]["why"])

    def test_uncalibrated_falls_back_to_rooms_and_says_so(self):
        """A grid in odometry metres with no tie to the map cannot be a cost map: the rooms, logged as such, never a
        grid drawn at a guessed place."""
        err = io.StringIO()
        with redirect_stderr(err):
            out = plan.plan((300, 1100), (650, 1100), grid=fx.grid(), cal=None)
        self.assertEqual(out["cost_map"], "rooms")
        self.assertIn("calibrat", out["why"])
        r = rows_since(self.n0, "plan.route")[0]
        self.assertEqual(r["args"]["cost_map"], "rooms")
        self.assertIn("calibrat", r["args"]["why"])
        warn = [ln for ln in err.getvalue().splitlines() if "WARN" in ln and "rooms" in ln]
        self.assertEqual(len(warn), 1, f"one WARN line naming the fallback, got: {err.getvalue()!r}")


class Occupied(unittest.TestCase):
    def test_a_point_on_or_beside_the_wall_is_occupied(self):
        g = fx.grid()
        wx = round(fx.px(fx.WALL["x"], 0)[0])   # the wall's map x, about 474
        self.assertTrue(plan.occupied((wx, 900), g, CAL), "on the wall")
        self.assertTrue(plan.occupied((wx + (plan.half_width() - 1) * plan.CELL, 900), g, CAL), "within the dog's half-width of the wall")
        self.assertFalse(plan.occupied((wx + (plan.half_width() + 2) * plan.CELL, 900), g, CAL), "beyond the inflation")
        self.assertFalse(plan.occupied((300, 900), g, CAL), "open floor")
        self.assertFalse(plan.occupied((wx, 700), g, CAL), "past the wall's end")

    def test_no_grid_or_no_calibration_is_never_occupied(self):
        wx = round(fx.px(fx.WALL["x"], 0)[0])
        self.assertFalse(plan.occupied((wx, 900), fx.grid(), None), "no calibration: nothing is known to be in the way")
        self.assertFalse(plan.occupied((wx, 900), None, CAL), "no grid")

    def test_a_blob_seen_once_is_not_an_obstacle(self):
        """Something that passed through one frame is not a wall at THRESHOLD (01's rule): no replan for it."""
        self.assertFalse(plan.occupied(BLOB_AT, fx.grid(blob_px=BLOB_AT, blob_frames=1), CAL))
        self.assertTrue(plan.occupied(BLOB_AT, fx.grid(blob_px=BLOB_AT), CAL))

    def test_the_planner_and_occupied_agree(self):
        """Every waypoint of a route planned over the grid is free by occupied(): the follower can never bounce between
        a planner that says walkable and a check that says occupied."""
        g = fx.grid(blob_px=BLOB_AT)
        pts = plan.plan((300, 1400), (650, 1400), grid=g, cal=CAL)["path"]
        self.assertEqual([p for p in pts if plan.occupied(p, g, CAL)], [])


class Replan(unittest.TestCase):
    def test_a_blob_on_the_route_makes_a_detour_that_rejoins(self):
        g, blob = fx.grid(blob_px=BLOB_AT), fx.blob_px(BLOB_AT)
        cov = [i for i, p in enumerate(ROUTE) if plan.occupied(p, g, CAL)]   # S8: the padding is metres, so which waypoints it covers follows the scale
        self.assertIn(4, cov, "the blob sits on waypoint 4")
        self.assertEqual(cov, list(range(cov[0], cov[-1] + 1)), "one run of covered waypoints")
        b, j = cov[0], cov[-1] + 1
        n0 = len(ledger.rows())
        p = ROUTE[b - 1]   # the dog has reached the waypoint before the blob and is about to drive to the first covered one
        det = plan.replan(p, ROUTE, b, g, CAL)
        self.assertEqual(det["blocked"], {"index": b, "waypoint": ROUTE[b]})
        self.assertEqual(det["rejoin"], {"index": j, "waypoint": ROUTE[j]})
        self.assertEqual(det["skipped"], cov)
        self.assertEqual(det["cost_map"], "grid")
        pts = det["path"]
        self.assertGreaterEqual(len(pts), 3, f"a straight line to the rejoin crosses the blob; the detour must bend: {pts}")
        self.assertLessEqual(math.dist(pts[0], p), plan.CELL, "the detour starts where the dog is")
        self.assertLessEqual(math.dist(pts[-1], ROUTE[j]), plan.CELL, "the detour ends on the rejoin waypoint")
        d, at = nearest(samples(pts), blob)
        self.assertGreaterEqual(d, CLEAR_PX, f"detour passes {at} within {d:.0f} px of the blob: {pts}")
        self.assertEqual([q for q in pts if plan.occupied(q, g, CAL)], [], "no detour waypoint is occupied")
        rows = rows_since(n0, "plan.replanned")
        self.assertEqual(len(rows), 1, "one plan.replanned row")
        r = rows[0]
        self.assertTrue(r["ok"])
        self.assertEqual((r["agent"], r["app"]), ("plan", "map"))
        a = r["args"]
        self.assertEqual(a["from"], [int(v) for v in ROUTE[b - 1]])
        self.assertEqual((a["blocked"], a["rejoin"], a["skipped"]), (det["blocked"], det["rejoin"], cov))
        self.assertEqual((a["cost_map"], a["threshold"], a["nogo"], a["cell_px"]), ("grid", occupancy.THRESHOLD, [ZONE["name"]], plan.CELL))
        self.assertGreater(a["walls"], int(plan._cells(plan.walls_px(fx.grid(), CAL)).sum()), "the wall's cells and the blob's")
        self.assertTrue(isinstance(a.get("shift_id"), str) and a["shift_id"], "every shift row carries args.shift_id")
        self.assertEqual(r["state_after"]["waypoints"], len(pts))
        self.assertEqual(rows_since(n0, "plan.route"), [], "a replan is its own row, not a plan.route")

    def test_a_blob_on_the_end_of_the_route_fails_loud(self):
        """The goal itself is occupied: no rejoin exists, ValueError, the row ok false naming it; never a route to
        somewhere else."""
        g = fx.grid(blob_px=tuple(ROUTE[-1]))
        i = next(k for k, p in enumerate(ROUTE) if plan.occupied(p, g, CAL))
        self.assertIn(i, (6, 7), "the blob on the end and its padding cover the last waypoint or the last two (S8: the padding follows the scale)")
        n0 = len(ledger.rows())
        with self.assertRaises(ValueError) as cm:
            plan.replan(ROUTE[i - 1], ROUTE, i, g, CAL)
        self.assertIn("occupied", str(cm.exception).lower())
        rows = rows_since(n0, "plan.replanned")
        self.assertEqual(len(rows), 1, "one plan.replanned row, failed")
        self.assertIs(rows[0]["ok"], False)
        self.assertIn("occupied", rows[0]["response_or_error"].lower())
        self.assertEqual(rows[0]["args"]["blocked"], {"index": i, "waypoint": ROUTE[i]})


class _Harness(unittest.TestCase):
    """DogSession.follow with a teleporting body (module doc): the follower's own loop, no dog, no clock. No live view
    unless a test sets one (S6): self.live(points) is the newest LiDAR window's band in map pixels."""

    def setUp(self):
        from wtdd.dog import session
        self.believed = list(ROUTE[0])
        self.targets: list[tuple[int, int]] = []
        self.blocked, self.free_after, self.free_ticks, self.aims = None, math.inf, math.inf, []   # S6b: a point the dog cannot get closer to (Stuck)

        def steer(px, py, heading, target, reach_px):
            if math.dist((px, py), target) > 500:   # S6b: the stuck sweep holding a heading (its aim point is 1000 px out)
                a = round(math.degrees(math.atan2(target[1] - py, target[0] - px)))
                self.aims += [] if self.aims and self.aims[-1] == a else [a]
                if self.blocked and len(self.aims) >= self.free_after:   # this heading gets it past: 10 px closer, and free
                    (bx, by), self.blocked = self.blocked, None
                    k = 10 / math.dist((px, py), (bx, by))
                    self.believed[:] = [px + (bx - px) * k, py + (by - py) * k]
                return {"x": 0.3, "z": 0.0, "dist_px": 999, "err_deg": 0.0, "reached": False}
            if self.blocked == (int(target[0]), int(target[1])):   # held still: no progress toward it, for free_ticks drive ticks
                self.free_ticks -= 1
                if self.free_ticks >= 0:
                    return {"x": 0.3, "z": 0.0, "dist_px": round(math.dist((px, py), target)), "err_deg": 0.0, "reached": False}
            self.targets.append((int(target[0]), int(target[1])))
            self.believed[:] = [target[0], target[1]]
            return {"x": 0.0, "z": 0.0, "dist_px": 0, "err_deg": 0.0, "reached": True}

        self.enterContext(mock.patch.object(session.nav, "steer", steer))
        self.enterContext(mock.patch.object(session, "CAL_FILE", _TMP / "dog_cal.json"))   # never the checkout's calibration
        self.grid_file = Path(self.enterContext(tempfile.TemporaryDirectory())) / "grid.json"
        self.enterContext(mock.patch.object(session, "GRID_FILE", self.grid_file))   # S13: memory, the saved map; none unless a test saves one
        s = self.s = session.DogSession()
        s.cal = dict(CAL)
        off = {"on": False, "n": 0, "errors": 0, "cb_errors": 0, "age_ms": None, "frame": None, "points": None, "utlidar_pose": None}
        s.body = types.SimpleNamespace(_avoid=True, lidar_points=lambda: off, state=lambda: None)   # Body's answers with the LiDAR off, before any state
        s._ensure = mock.AsyncMock(return_value=s.body)
        s._halt = mock.AsyncMock(return_value={})
        s.map_pose = lambda st=None: {"p": [round(self.believed[0]), round(self.believed[1])], "heading_deg": 0.0}
        self.enterContext(mock.patch.dict(os.environ, {"JEV_API_KEY": ""}))   # S6b: decide._stub names things unless a test sets a key
        s._look_at = mock.AsyncMock(return_value={"text": "a cardboard box on the floor", "person": False})   # S6b: face, look, sentence
        self.n0 = len(ledger.rows())

    def tearDown(self):
        stop(self.s)

    def live(self, pts) -> None:
        """S6: the follower sees this band as the newest LiDAR window (map pixels); [] is a clear view."""
        band = [[int(p[0]), int(p[1])] for p in pts]
        self.s._live_px = lambda: band

    def save(self, grid) -> None:
        """S13: a scan saved as memory, the way POST /dog/grid {save: true} does it (the session's grid_save, one row)."""
        self.s.grid = grid
        self.s.grid_save()

    def decided(self) -> list[dict]:
        return rows_since(self.n0, "route.decided")

    def assertSays(self, row: dict) -> None:
        """Johnny, 03:15: "add the decision log to the receipts … as if im talking to the agent". Every decision row
        carries one first-person sentence, dots numbered as the page draws them (index + 1)."""
        say = row["args"].get("say") or ""
        self.assertRegex(say, r"\bI\b|I'm", row["args"])
        if row["args"].get("at") is not None:
            self.assertIn(f"dot {row['args']['at'] + 1}", say.lower(), row["args"])

    def run_follow(self, stops: list[int], grid, path=ROUTE) -> tuple[dict, list[int]]:
        s = self.s
        s.grid = grid
        resumed: list[int] = []
        s.follow(path, stops, reach_px=30.0)

        def auto_resume():   # a housemate pressing resume at every stop the follower pauses at
            while not s._follower.done():
                at = s.follow_state.get("stopped_at")
                if at is not None and at not in resumed:
                    resumed.append(at)
                    s.resume()
                time.sleep(0.02)

        threading.Thread(target=auto_resume, daemon=True).start()
        s._follower.result(timeout=30)
        return dict(s.follow_state), resumed

class Follower(_Harness):
    """S6 (Johnny, 2026-09-27): "take the grey as guidance but fully rely on the blue". What blocks a waypoint is the
    newest LiDAR window, padded by HALF_WIDTH; the accumulated grid is memory only. A blob only in memory never blocks:
    before S6 it made the follower skip waypoints 3 to 5, which is what Johnny saw live as "not following the path"."""

    def test_a_blob_only_in_memory_never_blocks_the_drawn_path(self):
        fs, resumed = self.run_follow([4], fx.grid(blob_px=BLOB_AT))   # no live view in this test
        self.assertIsNone(fs.get("error"), fs)
        self.assertTrue(fs.get("done"), fs)
        self.assertEqual(self.targets, [tuple(p) for p in ROUTE], "every drawn waypoint, in order, nothing else")
        self.assertEqual(resumed, [4], "the stop on the remembered blob is honoured")
        self.assertEqual(fs["reached"], list(range(len(ROUTE))))
        self.assertEqual(rows_since(self.n0, "plan.replanned"), [])
        d = self.decided()
        self.assertEqual([r["args"]["action"] for r in d], ["unchecked"], "one receipt: no live view, the path is followed as drawn")
        self.assertIn("no live view", d[0]["args"]["reason"])
        self.assertSays(d[0])

    def test_without_a_blob_the_follower_is_unchanged(self):
        self.live([])
        fs, resumed = self.run_follow([2], fx.grid())
        self.assertIsNone(fs.get("error"), fs)
        self.assertTrue(fs.get("done"), fs)
        self.assertEqual(self.targets, [tuple(p) for p in ROUTE], "every waypoint, in order, nothing else")
        self.assertEqual(resumed, [2], "the stop is honoured")
        self.assertEqual(fs["reached"], list(range(len(ROUTE))))
        self.assertEqual(fs["replans"], [])
        self.assertEqual(rows_since(self.n0, "plan.replanned"), [])
        self.assertEqual(self.decided(), [], "nothing was decided, so nothing is written")
        f = rows_since(self.n0, "dog.follow")
        self.assertEqual(len(f), 1)
        self.assertTrue(f[0]["ok"], f[0])
        self.assertEqual((f[0]["state_after"]["replans"], f[0]["state_after"]["skipped_stops"]), (0, []))


class FollowerLive(_Harness):
    """S6: the live view decides, memory labels, the drawn path is followed in order from point 1, and every decision is
    one route.decided row with its reason: snapped (within 0.5 m), refused (S6b: no route to the dot; S6's detour to the
    next free waypoint is gone, a dot with no free floor is looked at and passed, class OnBlue). Nothing is skipped
    silently."""

    def test_memory_grey_with_a_clear_live_view_is_driven_in_order(self):
        self.live([])                                            # the blob is remembered but gone from the live view
        fs, resumed = self.run_follow([4], fx.grid(blob_px=BLOB_AT))
        self.assertIsNone(fs.get("error"), fs)
        self.assertEqual(self.targets, [tuple(p) for p in ROUTE])
        self.assertEqual(resumed, [4])
        self.assertEqual(self.decided(), [])
        self.assertEqual(rows_since(self.n0, "plan.replanned"), [])

    def test_a_new_obstacle_beside_a_waypoint_is_snapped_around_and_named(self):
        blob = fx.blob_px((500, 1435))                          # 35 px below waypoint 4: its padding covers 3, 4 and 5
        self.live(blob)
        fs, resumed = self.run_follow([4], fx.grid())            # memory does not have it
        self.assertIsNone(fs.get("error"), fs)
        self.assertTrue(fs.get("done"), fs)
        snaps = [r for r in self.decided() if r["args"]["action"] == "snapped"]
        cov = [k for k, q in enumerate(ROUTE) if plan.blocker(q, blob) is not None]   # S8: the padding follows the scale
        self.assertIn(4, cov)
        self.assertEqual([r["args"]["at"] for r in snaps], cov, "each covered waypoint, in order")
        for r in snaps:
            a = r["args"]
            self.assertEqual(a["blocker"]["kind"], "new obstacle", a)
            self.assertEqual(a["blocker"]["in_memory"], 0, a)
            self.assertGreater(a["blocker"]["cells"], 0, a)
            self.assertLessEqual(a["m"], 0.5, a)
            self.assertIn("new obstacle", a["reason"])
            self.assertSays(r)
        self.assertEqual(fs["reached"], list(range(len(ROUTE))), "every waypoint reached, three of them at their snapped spot")
        self.assertEqual(resumed, [4], "the stop is honoured at its snapped spot")
        d, at = nearest(self.targets, blob)
        self.assertGreaterEqual(d, CLEAR_PX, f"the follower drove to {at}, {d:.0f} px from the obstacle: {self.targets}")

    def test_the_same_blocker_already_in_memory_is_named_permanent(self):
        """S13: memory is the map saved after a scan (what was there before this walk), not the live session grid: the
        blob was in the saved scan, and the live grid this walk has not taken it yet."""
        self.save(fx.grid(blob_px=(500, 1435)))
        self.live(fx.blob_px((500, 1435)))
        self.run_follow([], fx.grid())
        snaps = [r for r in self.decided() if r["args"]["action"] == "snapped"]
        self.assertTrue(snaps, self.decided())
        for r in snaps:
            self.assertEqual(r["args"]["blocker"]["kind"], "permanent", r["args"])
            self.assertGreater(r["args"]["blocker"]["in_memory"], 0, r["args"])
            self.assertIn("permanent", r["args"]["reason"])

    def test_a_box_set_down_after_the_save_is_a_new_obstacle_after_10_live_frames(self):
        """S13, Johnny: "if it was there before maybe its permanent but if it wasnt maybe its classified as an obstacle".
        The live session grid takes a box in a few frames (5 to 10 a second); memory is the scan saved before it."""
        self.save(fx.grid())
        live = fx.grid(blob_px=(500, 1435))
        for _ in range(10 - occupancy.THRESHOLD):
            live.update(fx.blob_points((500, 1435)))
        self.assertGreaterEqual(live.cell(*fx.metres(500, 1435)), 10, "the live grid has taken the box: 10 frames")
        self.live(fx.blob_px((500, 1435)))
        self.run_follow([], live)
        snaps = [r for r in self.decided() if r["args"]["action"] == "snapped"]
        self.assertTrue(snaps, self.decided())
        for r in snaps:
            self.assertEqual((r["args"]["blocker"]["kind"], r["args"]["blocker"]["in_memory"]), ("new obstacle", 0), r["args"])
            self.assertIn("new obstacle", r["args"]["reason"])

    def test_no_saved_map_is_a_new_obstacle_and_the_reason_says_so(self):
        self.live(fx.blob_px((500, 1435)))
        self.run_follow([], fx.grid(blob_px=(500, 1435)))   # the live grid has it; no map was ever saved
        snaps = [r for r in self.decided() if r["args"]["action"] == "snapped"]
        self.assertTrue(snaps, self.decided())
        for r in snaps:
            self.assertEqual((r["args"]["blocker"]["kind"], r["args"]["blocker"]["in_memory"]), ("new obstacle", 0), r["args"])
            self.assertIn("memory: no saved map", r["args"]["reason"])

    def test_a_dot_walled_in_by_the_live_view_is_refused_loud(self):
        """S6b: the dot itself is free but the live view rings it: no leg reaches it, the follow is refused (a FAILED row
        with the reason and its sentence) and the dot is never driven to."""
        ring = [(650 + 70 * math.cos(math.radians(a)), 1400 + 70 * math.sin(math.radians(a))) for a in range(0, 360, 3)]
        self.live(ring)
        self.assertIsNone(plan.blocker(LINE[-1], ring), "the ring leaves the dot itself free")
        fs, _ = self.run_follow([], fx.grid(), path=LINE)
        self.assertIn("refused", (fs.get("error") or ""), fs)
        ref = [r for r in self.decided() if r["args"]["action"] == "refused"]
        self.assertEqual(len(ref), 1, self.decided())
        self.assertIs(ref[0]["ok"], False)
        self.assertEqual(ref[0]["args"]["at"], 1)
        self.assertIn("no route", ref[0]["args"]["reason"])
        self.assertSays(ref[0])
        self.assertNotIn(tuple(LINE[-1]), self.targets, "never driven into the ring")

    def test_a_drawn_path_starts_at_point_one(self):
        self.believed[:] = list(ROUTE[5])                        # the dog stands on waypoint 5
        self.live([])
        fs, _ = self.run_follow([], fx.grid())
        self.assertEqual(self.targets[0], tuple(ROUTE[0]), "point 1 first, not the nearest point")
        self.assertEqual(fs["reached"], list(range(len(ROUTE))))


class Legs(_Harness):
    """S6b, Johnny 2026-09-27: "draw a line straight through the obstacle and just have it pathfind around it and show its
    actual route compared to the planned one". Every leg, the dog's pose to the next dot, is planned over the live view
    (padded) and the no-go zones; memory never bends it; the dog's own body in the band is dropped; a leg the newest view
    blocks mid-way is re-planned from where the dog stands. follow_state carries the planned legs and the actual trace."""

    def own_legs(self, at, r_m=0.2) -> list:
        """The dog's own legs in its band: a ring of points r_m around map point `at`."""
        from wtdd.dog import nav
        r = r_m * nav.PX_PER_M
        return [(at[0] + r * math.cos(math.radians(a)), at[1] + r * math.sin(math.radians(a))) for a in range(0, 360, 20)]

    def test_a_straight_line_through_a_live_blob_is_planned_around_it_to_the_next_dot(self):
        blob = fx.blob_px((475, 1400))                          # on the drawn line, halfway between the two dots
        self.live(blob + self.own_legs(LINE[0]))
        self.assertIsNotNone(plan.blocker(LINE[0], self.own_legs(LINE[0])), "without the drop, its own legs would cover dot 1")
        fs, _ = self.run_follow([], fx.grid(), path=LINE)
        self.assertIsNone(fs.get("error"), fs)
        self.assertTrue(fs.get("done"), fs)
        self.assertEqual(fs["reached"], [0, 1])
        self.assertEqual(self.targets[-1], tuple(LINE[-1]), "the next dot is reached, exactly")
        self.assertGreaterEqual(len(self.targets), 4, f"the leg bends around the blob: {self.targets}")
        d, at = nearest(samples([LINE[0]] + self.targets), blob)
        self.assertGreaterEqual(d, CLEAR_PX, f"the dog drove past {at}, {d:.0f} px from the blob: {self.targets}")
        self.assertEqual(self.decided(), [], "the dog's own legs in the band never cover dot 1, and nothing else was decided")
        legs = rows_since(self.n0, "plan.route")
        self.assertEqual(len(legs), 2, "one plan.route row per leg")
        a = legs[-1]["args"]
        self.assertTrue(a.get("live"), a)
        self.assertEqual(a.get("dots"), [1, 2], "the leg's dot numbers, as the page draws them")
        self.assertEqual(a.get("cost_map"), "live", a)
        self.assertRegex(a.get("say") or "", r"\bI\b|I'm", a)
        self.assertIn("dot 2", (a.get("say") or "").lower(), a)

    def test_memory_walls_alone_do_not_bend_a_leg(self):
        self.live([])
        fs, _ = self.run_follow([], fx.grid(blob_px=(475, 1400)), path=LINE)   # the blob is grey only
        self.assertIsNone(fs.get("error"), fs)
        self.assertEqual(self.targets, [tuple(p) for p in LINE], "straight to the dot: memory only labels")
        legs = rows_since(self.n0, "plan.route")
        self.assertEqual(len(legs), 2)
        self.assertEqual([(r["args"].get("cost_map"), r["args"].get("walls"), r["args"].get("memory")) for r in legs],
                         [("live", 0, "labels only")] * 2, "the row says memory was not read")

    def test_a_leg_blocked_mid_way_is_replanned_from_where_the_dog_stands(self):
        blob, later = fx.blob_px((475, 1400)), []

        def view():   # a second blob appears 60 px ahead of the dog once it has stepped off the line to pass the first
            if not later and abs(self.believed[1] - 1400) > 20:
                later.extend(fx.blob_px((self.believed[0] + 60, self.believed[1])))
            return [[int(p[0]), int(p[1])] for p in blob + later]

        self.s._live_px = view
        fs, _ = self.run_follow([], fx.grid(), path=LINE)
        self.assertIsNone(fs.get("error"), fs)
        self.assertTrue(later, "the dog stepped off the line and the second blob appeared")
        rp = rows_since(self.n0, "plan.replanned")
        self.assertEqual(len(rp), 1, "one re-plan")
        a = rp[0]["args"]
        self.assertTrue(rp[0]["ok"], rp[0])
        self.assertTrue(a.get("live"), a)
        self.assertIn(tuple(a["from"]), self.targets, "re-planned from a point the dog had driven to")
        self.assertGreater(abs(a["from"][1] - 1400), 20, "where it stood when the blob appeared, off the line")
        self.assertRegex(a.get("say") or "", r"\bI\b|I'm", a)
        self.assertIn("dot 2", (a.get("say") or "").lower(), a)
        after = self.targets[self.targets.index(tuple(a["from"])):]
        d, at = nearest(samples(after), later + blob)
        self.assertGreaterEqual(d, CLEAR_PX, f"after the re-plan the dog drove past {at}, {d:.0f} px from a blob: {after}")
        self.assertEqual(self.targets[-1], tuple(LINE[-1]))
        self.assertEqual(len(fs["replans"]), 1, fs["replans"])

    def test_the_state_carries_the_planned_legs_and_the_actual_trace(self):
        self.live(fx.blob_px((475, 1400)))
        fs, _ = self.run_follow([], fx.grid(), path=LINE)
        self.s.body.state = lambda: None
        served = json.loads(json.dumps(self.s.state()))["follow"]   # what GET /dog/state serves the page
        self.assertEqual(len(served["planned"]), 2, "one polyline per leg")
        leg = served["planned"][-1]
        self.assertEqual((leg[0], leg[-1]), (LINE[0], LINE[-1]), "a leg starts where the dog stands and ends on its dot")
        self.assertGreaterEqual(len(leg), 3, f"bent around the blob: {leg}")
        tr = served["trace"]
        self.assertEqual(tr[0], LINE[0], "the actual route starts where the dog stood")
        self.assertEqual(tr[-1], LINE[-1], "and ends at the last dot")
        self.assertTrue(all(math.dist(p, q) >= 10 for p, q in zip(tr, tr[1:])), f"a point every 10 px moved: {tr}")
        self.assertTrue({tuple(p) for p in tr} <= {tuple(LINE[0])} | set(self.targets), "only where the dog believed it was")


class OnBlue(_Harness):
    """S6b, Johnny 2026-09-27: "attempt to reach each dot unless its impossible because the dot sits on a blue lidar scan
    and in that moment it does the jev classification and moves on and continues to the next dot". An obstacle about
    0.55 m square on dot 5 (index 4) leaves no free floor within 0.5 m (S6's snap fails): the dog faces the dot, looks,
    Jev names what is there from a closed list (decide._jev, never decide.decide: no `decided` row), one route.decided row
    "classified", the dot is passed and the follow moves on. A person pauses it until resume(); a failed look is a
    FAILED row and it moves on."""
    JEV = ("chair", 0.84, "typesafe/jev-test", '{"answers": {"stop": {"type": "choice", "choice": "chair"}}}')

    def follow_blob(self, stops=()) -> tuple[dict, list[int]]:
        self.blob = [q for dx in (-25, 25) for dy in (-25, 25) for q in fx.blob_px((BLOB_AT[0] + dx, BLOB_AT[1] + dy))]
        self.assertIsNotNone(plan.blocker(ROUTE[4], self.blob))
        self.assertIsNone(plan.snap(ROUTE[4], self.blob), "no free floor within 0.5 m of dot 5")
        self.live(self.blob)
        return self.run_follow(list(stops), fx.grid())

    def classified(self) -> list[dict]:
        return [r for r in self.decided() if r["args"]["action"] == "classified"]

    def assertMovedOn(self, fs) -> None:
        self.assertIsNone(fs.get("error"), fs)
        self.assertTrue(fs.get("done"), fs)
        self.assertEqual(fs["reached"], [0, 1, 2, 3, 5, 6, 7], "every dot but the one on blue, in order")
        self.assertEqual(fs["passed"], [4], "the dot on blue is named as passed, never silently dropped")
        self.assertEqual(self.targets[-1], tuple(ROUTE[-1]))
        d, at = nearest(self.targets, self.blob)
        self.assertGreaterEqual(d, CLEAR_PX, f"the follower drove to {at}, {d:.0f} px from the obstacle: {self.targets}")

    def test_a_dot_on_live_blue_is_looked_at_named_once_and_passed(self):
        from wtdd import decide
        from wtdd.dog import session
        self.s._look_at = mock.AsyncMock(return_value={"text": "a black office chair in the way", "person": False})
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "test-key"}), mock.patch.object(decide, "_jev", return_value=self.JEV) as jev:
            fs, resumed = self.follow_blob(stops=[4])
        self.assertMovedOn(fs)
        self.assertEqual(resumed, [], "the stop on the obstacle is passed, never waited on")
        self.assertEqual(fs["skipped_stops"], [4])
        self.s._look_at.assert_awaited_once_with(ROUTE[4])
        jev.assert_called_once()
        state, choices = jev.call_args[0]
        self.assertEqual(choices, session.OBSTACLES, "one label from the closed list")
        self.assertIn("office chair", state, "Jev reads the sentence the look gave")
        c = self.classified()
        self.assertEqual(len(c), 1, self.decided())
        a = c[0]["args"]
        self.assertTrue(c[0]["ok"], c[0])
        self.assertEqual((a["at"], a["label"], a["p"], a["passed"]), (4, "chair", 0.84, [4]))
        self.assertIn("office chair", a["scene"])
        self.assertEqual(a["say"], "Dot 5 is on a chair (0.84), a new obstacle. I'm moving on to dot 6.")
        self.assertFalse(c[0]["cached"], c[0])
        self.assertEqual(rows_since(self.n0, "decided"), [], "decide.decide is not called: no `decided` row, no escalation")

    def test_with_no_jev_key_the_stub_names_it_and_the_row_says_so(self):
        self.s._look_at = mock.AsyncMock(return_value={"text": "a black office chair in the way", "person": False})
        fs, _ = self.follow_blob()
        self.assertMovedOn(fs)
        c = self.classified()
        self.assertEqual(len(c), 1, self.decided())
        self.assertEqual(c[0]["args"]["label"], "chair", c[0])
        self.assertEqual((c[0]["cached"], c[0]["source"], c[0]["args"]["model"]), (True, "stub", "stub"))

    def test_a_person_on_a_dot_pauses_the_follow_until_resume(self):
        from wtdd import decide
        self.s._look_at = mock.AsyncMock(return_value={"text": "someone standing right there", "person": True})
        person = ("person", 0.93, "typesafe/jev-test", '{"answers": {"stop": {"choice": "person"}}}')
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "test-key"}), mock.patch.object(decide, "_jev", return_value=person):
            fs, resumed = self.follow_blob()
        self.assertEqual(resumed, [4], "paused at that spot like a stop, until resume")
        self.assertMovedOn(fs)
        c = self.classified()
        self.assertEqual(len(c), 1, self.decided())
        self.assertEqual(c[0]["args"]["label"], "person")
        self.assertEqual(c[0]["args"]["say"], "There's a person on dot 5. I'm waiting here until you press resume.")

    def test_a_failed_look_is_a_failed_row_and_the_follow_moves_on(self):
        self.s._look_at = mock.AsyncMock(side_effect=RuntimeError("no camera frame in 5 s"))
        fs, _ = self.follow_blob()
        self.assertMovedOn(fs)
        c = self.classified()
        self.assertEqual(len(c), 1, self.decided())
        self.assertIs(c[0]["ok"], False)
        self.assertIn("no camera frame", c[0]["response_or_error"])
        self.assertSays(c[0])
        self.assertIn("moving on to dot 6", c[0]["args"]["say"])


class NoViewZones(_Harness):
    """B11 (the head's probe on main): LiDAR off, a two-dot line across a no-go zone gave route.decided "unchecked", then
    dog.follow ok, straight through the zone. S12 let follow() refuse only a dot inside a zone and left a crossing line to
    S6b's legs, which only run with a live view; with none, _as_drawn drove the line as drawn. Without a live view the dog
    still keeps out of every zone: the line is planned around them, or refused naming the zone."""

    def test_with_no_live_view_a_line_across_a_zone_is_driven_around_it(self):
        line = [[400, 1150], [560, 1150]]   # either side of nogo-1 (x 450..510, y 1040..1250), the line straight through it
        self.believed[:] = line[0]
        fs, _ = self.run_follow([], fx.grid(), path=line)   # no self.live(): the LiDAR is off
        self.assertIsNone(fs.get("error"), fs)
        self.assertEqual(fs["reached"], [0, 1], fs)
        self.assertEqual(self.targets[-1], tuple(line[1]), "it still gets to dot 2")
        through = [q for q in samples([line[0], *self.targets]) if inside(q, POLY)]
        self.assertEqual(through[:3], [], f"the dog drove through {ZONE['name']}: {self.targets}")
        route = rows_since(self.n0, "plan.route")
        self.assertEqual(len(route), 1, "one leg planned around the zone")
        self.assertIn(ZONE["name"], route[0]["args"]["nogo"])
        self.assertSays(route[0])

    def test_with_no_live_view_no_way_around_a_zone_is_refused_by_name(self):
        line = [[400, 1150], [515, 1150]]   # dot 2 sits beside nogo-1, inside its padding: no floor the body fits on there
        self.believed[:] = line[0]
        fs, _ = self.run_follow([], fx.grid(), path=line)
        self.assertIn("refused", fs.get("error") or "", fs)
        self.assertIn(ZONE["name"], fs.get("error") or "", fs)
        self.assertEqual(self.targets, [tuple(line[0])], "nothing driven toward the zone")
        ref = [r for r in self.decided() if r["args"]["action"] == "refused"]
        self.assertEqual(len(ref), 1, self.decided())
        self.assertIs(ref[0]["ok"], False)
        self.assertIn(ZONE["name"], ref[0]["args"]["reason"])
        self.assertSays(ref[0])


class Stuck(_Harness):
    """S6b, live 03:41 and 03:42: "TimeoutError: waypoint 2 not reached in 30.0s (dist 131 px, err -0.8 deg)", twice: it
    aimed within 1 degree and the Go2's own avoidance held it at the gap. Johnny, 03:48: "if it decided to trust its lidar
    and actually just guide itself and reposition then it might allow it to go through it should test the different
    degrees and angles to guide itself through". Under STUCK_M of progress in STUCK_S (0.2 s here): the clear metres
    left and right in the live band ahead, a sidestep toward the open side, then headings 15, 30, 45 degrees off the
    direct line, the open side first, the first that makes progress kept; one "stuck" row per heading. A failed sweep
    re-plans the leg once; failing again, the dot is given up and passed (the last dot: refused)."""

    def setUp(self):
        super().setUp()
        from wtdd.dog import session
        self.enterContext(mock.patch.object(session, "STUCK_S", 0.2))
        self.enterContext(mock.patch.object(session, "SIDESTEP_S", 0.1))
        self.vels: list[tuple] = []
        set_vel = self.s._set_vel
        self.s._set_vel = lambda x, y, z: (self.vels.append((x, y, z)), set_vel(x, y, z))

    def stuck(self) -> list[dict]:
        return [r for r in self.decided() if r["args"]["action"] == "stuck"]

    def test_the_open_side_is_read_from_the_scan_and_the_first_heading_that_moves_is_kept(self):
        from wtdd.dog import nav
        self.live([(380, y) for y in range(1320, 1341, 4)])   # 80 px ahead, 60..80 px to the dog's left (up the page); the right is open
        self.blocked, self.free_after = tuple(LINE[-1]), 2    # no progress to dot 2 until the second heading tried
        fs, _ = self.run_follow([], fx.grid(), path=LINE)
        self.assertIsNone(fs.get("error"), fs)
        self.assertEqual(fs["reached"], [0, 1])
        self.assertEqual(self.aims, [15, 30], "the open side first, 15 then 30 degrees off the direct line (right is clockwise)")
        st = self.stuck()
        self.assertEqual([(r["args"]["side"], r["args"]["angle"], r["args"]["attempt"]) for r in st], [("right", 15, 1), ("right", 30, 2)],
                         "one row per heading tried; the first that moved is kept, so no 45")
        c = st[0]["args"]["clear_m"]
        self.assertEqual(c["right"], 2.0, "nothing on the right within 2 m")
        self.assertAlmostEqual(c["left"], 60 / nav.PX_PER_M, delta=plan.CELL / nav.PX_PER_M, msg="the wall 60 px to the left")
        for r in st:
            self.assertSays(r)
            self.assertIn("blocked straight ahead", r["args"]["say"])
            self.assertIn(f"{r['args']['angle']}° right, where my scan shows 2.0 m clear", r["args"]["say"])
            self.assertGreater(r["args"]["dist_m"], 0)
        self.assertIn((0.0, -0.15, 0.0), self.vels, "a sidestep toward the open side first (the dog's right is -y)")
        self.assertEqual([r for r in self.decided() if r["args"]["action"] == "gave up"], [])

    def test_a_sweep_that_works_restarts_the_waypoint_clock(self):
        """Head's review: the stuck wait plus a sweep that works can outlast WP_TIMEOUT_S counted from the first
        approach, and the follow then failed on the next tick, just after it got unstuck. A recovery that made progress
        restarts the clock (each needs STUCK_M of real progress, so this cannot loop forever). Here the body moves 20 px
        a tick, the recovery takes 0.6 s and works, and WP_TIMEOUT_S is 0.5 s."""
        from wtdd.dog import session
        s, target = self.s, (self.believed[0] + 60, self.believed[1])
        self.enterContext(mock.patch.object(session, "WP_TIMEOUT_S", 0.5))

        def step(px, py, heading, tgt, reach_px):
            d = math.dist((px, py), tgt)
            if d <= reach_px:
                return {"x": 0.0, "z": 0.0, "dist_px": round(d), "err_deg": 0.0, "reached": True}
            k = min(1.0, 20 / d)
            self.believed[:] = [px + (tgt[0] - px) * k, py + (tgt[1] - py) * k]
            return {"x": 0.3, "z": 0.0, "dist_px": round(d), "err_deg": 0.0, "reached": False}

        self.enterContext(mock.patch.object(session.nav, "steer", step))
        s._view = lambda: ([], None)
        fronts = iter([0.4])
        self.enterContext(mock.patch.object(session.plan, "ahead", lambda *a, **k: next(fronts, None)))

        async def unstick(*a, **k):
            await asyncio.sleep(0.6)
            return True

        s._unstick = unstick
        pose = s.run(s._goto(target, 10.0, {"trace": [], "planned": []}, "the test point"), timeout=10)
        self.assertLessEqual(math.dist(pose["p"], target), 10.0)

    def test_a_failed_sweep_replans_once_then_gives_up_and_moves_on(self):
        self.live([])
        self.blocked = tuple(LINE[-1])                        # dot 2 never gets closer
        fs, _ = self.run_follow([1], fx.grid(), path=LINE + [[650, 1200]])
        self.assertIsNone(fs.get("error"), fs)
        self.assertTrue(fs.get("done"), fs)
        self.assertEqual((fs["reached"], fs["passed"], fs["skipped_stops"]), ([0, 2], [1], [1]), "dot 2 passed and named, dot 3 reached")
        sweep = [("left", 15), ("left", 30), ("left", 45), ("right", 15), ("right", 30), ("right", 45)]
        self.assertEqual([(r["args"]["side"], r["args"]["angle"]) for r in self.stuck()], sweep * 2,
                         "a clear scan ties, left first; the other side from 15; the whole sweep again after the re-plan")
        rp = rows_since(self.n0, "plan.replanned")
        self.assertEqual(len(rp), 1, "one re-plan from where the dog stands")
        self.assertIn("dot 2", rp[0]["args"]["say"].lower())
        g = [r for r in self.decided() if r["args"]["action"] == "gave up"]
        self.assertEqual(len(g), 1, self.decided())
        self.assertIs(g[0]["ok"], False, "a dot not reached is a red row")
        self.assertEqual((g[0]["args"]["at"], g[0]["args"]["passed"]), (1, [1]))
        self.assertSays(g[0])
        self.assertIn("moving on to dot 3", g[0]["args"]["say"])

    def test_an_obstacle_half_a_metre_ahead_is_stuck_at_once_and_swept_toward_the_open_side(self):
        """Live, 2026-09-27: the Go2's avoidance stops its nose about 0.15 m short, 0.50 m ahead of its middle. Something
        that steps into the body's corridor within FRONT_M after the leg was planned is stuck at once, not after STUCK_S."""
        from wtdd.dog import nav, session
        ppm, wall = nav.PX_PER_M, [(380, y) for y in range(1320, 1341, 4)]   # the left narrowed by a wall 60..80 px up the page
        step_in = fx.blob_px((300 + 0.4 * ppm, 1400)) + wall

        def view():   # the blob steps in 0.4 m ahead once the leg to dot 2 is planned
            return step_in if len(rows_since(self.n0, "plan.route")) >= 2 else []

        self.s._live_px = view
        self.blocked, self.free_after = tuple(LINE[-1]), 1
        self.enterContext(mock.patch.object(session, "STUCK_S", 3.0))
        t0 = time.monotonic()
        fs, _ = self.run_follow([], fx.grid(), path=LINE)
        self.assertLess(time.monotonic() - t0, session.STUCK_S, "at once: no STUCK_S wait for no progress")
        self.assertIsNone(fs.get("error"), fs)
        st = self.stuck()
        self.assertEqual([(r["args"]["side"], r["args"]["angle"]) for r in st], [("right", 15)], "toward the open side, and kept")
        self.assertRegex(st[0]["args"]["reason"], r"an obstacle 0\.\d+ m ahead")
        self.assertEqual(set(st[0]["args"]["clear_m"]), {"left", "right"})
        self.assertGreater(st[0]["args"]["clear_m"]["right"], st[0]["args"]["clear_m"]["left"])

    def test_an_obstacle_beside_the_corridor_is_not_stuck(self):
        from wtdd.dog import nav, session
        self.live(fx.blob_px((300 + 0.4 * nav.PX_PER_M, 1400 - 0.55 * nav.PX_PER_M)))   # 0.4 m ahead, 0.55 m to the left
        self.blocked, self.free_ticks = tuple(LINE[-1]), 5                                # five drive ticks before it gets there
        self.enterContext(mock.patch.object(session, "STUCK_S", 3.0))
        fs, _ = self.run_follow([], fx.grid(), path=LINE)
        self.assertIsNone(fs.get("error"), fs)
        self.assertEqual(self.targets, [tuple(p) for p in LINE], "a straight leg, driven")
        self.assertEqual(self.stuck(), [], "beside the corridor is not in the way")

    def test_stuck_on_the_last_dot_is_refused(self):
        self.live([])
        self.blocked = tuple(LINE[-1])
        fs, _ = self.run_follow([], fx.grid(), path=LINE)
        self.assertIn("refused", fs.get("error") or "", fs)
        ref = [r for r in self.decided() if r["args"]["action"] == "refused"]
        self.assertEqual(len(ref), 1, self.decided())
        self.assertEqual(ref[0]["args"]["at"], 1)
        self.assertSays(ref[0])
        self.assertEqual(fs["passed"], [], "refused, not passed")


class Reconnect(_Harness):
    """B2 (CLEANUP-PLAN): the state stream goes quiet mid-follow (a power cycle, a hotspot drop) and the next call's stale
    reconnect (_ensure) closed the dead peer and cancelled the drive loop but left the follower running: it walked on
    into whatever session came next, and when it ended, _halt read `_avoid` on no body, so the dog.follow row said
    AttributeError instead of why. The follow must end at the reconnect, and its row and follow.error must say so."""

    def test_a_stale_reconnect_stops_the_follow_and_its_row_names_the_reconnect(self):
        from wtdd.dog import session
        s = self.s
        del s._halt                                    # the real halt: it is what read `_avoid` on no body
        s.grid = fx.grid()
        s.follow(ROUTE, [1], reach_px=30.0)

        def until(ok, sec: float) -> bool:
            t = time.monotonic() + sec
            while not ok():
                if time.monotonic() > t:
                    return False
                time.sleep(0.02)
            return True

        self.assertTrue(until(lambda: s.follow_state.get("stopped_at") == 1, 10), s.follow_state)
        s.body.state = lambda: {"age_ms": session.STALE_MS + 1, "n": 42}   # the peer went quiet while held at dot 2
        s.body.close = mock.AsyncMock()
        gone = types.SimpleNamespace(connect=mock.AsyncMock(side_effect=ConnectionError("no answer: the dog left the hotspot")))
        with mock.patch.object(session, "Body", lambda: gone), redirect_stderr(err := io.StringIO()):
            with self.assertRaises(ConnectionError):
                s.run(session.DogSession._ensure(s))   # the real reconnect (the harness mocks _ensure): the dead peer is closed, no new one answers
            ended = until(lambda: s.follow_state.get("error") is not None, 3)   # set after the dog.follow row is written
            if not ended:   # before B2 the follow still waits at its stop on the dead session: resume it to see how it ends
                s.resume()
                s._follower.result(timeout=10)
        fs = dict(s.follow_state)
        f = rows_since(self.n0, "dog.follow")
        self.assertEqual(len(f), 1, f)
        self.assertNotIn("AttributeError", str(f[0]["response_or_error"]), f[0])
        self.assertIn("reconnect", str(f[0]["response_or_error"]), f[0])
        self.assertIs(f[0]["ok"], False)
        self.assertIn("reconnect", fs.get("error") or "", fs)
        self.assertTrue(ended, f"the follow was still running on a dead session after the reconnect: {fs}")
        self.assertTrue(s._follower.done())
        self.assertFalse(fs["active"], fs)
        self.assertEqual(fs["reached"], [0, 1], "no dot after the reconnect")
        self.assertRegex(err.getvalue(), r"WARN [^\n]*follow[^\n]*reconnect", "one WARN line names the follow and the reconnect")


class Padding(unittest.TestCase):
    """S8 (live on main 93605f1, 03:29): the padding was 4 lattice cells of 10 px, so at the measured 87 px/m every side
    grew 0.46 m and any gap under ~0.9 m read as closed; the Go2 is ~0.31 m wide. Johnny, at the gap: "can it seriously not
    go through this gap?" The padding is now HALF_WIDTH_M per side in metres, converted at the scale in force, and a
    detour trusts the live view where it can see (memory counts only beyond LIVE_TRUST_M of the dog)."""

    def at_scale(self, v):
        from wtdd.dog import nav
        return mock.patch.object(nav, "PX_PER_M", v)

    def test_the_padding_is_metres_at_the_scale_in_force(self):
        with self.at_scale(87.0):
            self.assertEqual(plan.half_width(), 2)
        with self.at_scale(108.5):
            self.assertEqual(plan.half_width(), 3)

    def test_a_detour_goes_through_a_seventy_centimetre_gap(self):
        with self.at_scale(87.0):
            gap = 0.7 * 87.0
            live = [[600, y] for y in range(0, plan.H, 4) if abs(y - 1400) > gap / 2]   # a wall across the whole map, one 0.7 m gap
            path = [[500, 1400], [650, 1400], [700, 1400]]
            out = plan.replan((500, 1400), path, 1, fx.grid(), CAL, live_px=live, rejoin=2)   # no way round: only the gap
            cross = [a[1] + (b[1] - a[1]) * (600 - a[0]) / (b[0] - a[0]) for a, b in zip(out["path"], out["path"][1:])
                     if a[0] != b[0] and min(a[0], b[0]) <= 600 <= max(a[0], b[0])]
            self.assertEqual(len(cross), 1, out["path"])
            self.assertLess(abs(cross[0] - 1400), gap / 2, f"it crosses the wall inside the gap: {out['path']}")

    def test_a_detour_ignores_remembered_walls_the_live_view_shows_gone(self):
        with self.at_scale(87.0):
            path = [[500, 1400], [600, 1400], [700, 1400]]
            out = plan.replan((500, 1400), path, 1, fx.grid(blob_px=(600, 1400)), CAL, live_px=[], rejoin=2)
            self.assertLessEqual(out["length_px"], 210, f"a straight run, not a bend around a blob that is gone: {out}")
            self.assertEqual(out.get("cost_map"), "live")


class Receipts(unittest.TestCase):
    """S6, Johnny 03:15: the receipts panel reads like the agent talking. A row's first-person sentence (args.say) is its
    main line, and a red row shows its error (response_or_error), which the panel never showed before S6."""
    PAGE = (Path(__file__).resolve().parent.parent / "ui" / "index.html").read_text()

    def receipt_line(self) -> str:
        return next(l for l in self.PAGE.splitlines() if ".slice(0, 25)" in l)   # S7 filters pose.corrected before the slice

    def test_the_sentence_is_the_main_line(self):
        self.assertIn("r.args?.say", self.receipt_line())

    def test_a_red_row_shows_its_error(self):
        self.assertIn("r.response_or_error", self.receipt_line())


class RouteLines(unittest.TestCase):
    """S6b: the map draws what GET /dog/state serves, the planned legs dashed and the actual route solid, each named in a
    legend, on the one map both the demo view and #admin show, from a follow's start until the next one."""
    PAGE = Receipts.PAGE

    def test_the_map_draws_the_planned_legs_and_the_actual_trace(self):
        self.assertIn("dog?.follow?.planned", self.PAGE)
        self.assertIn("dog?.follow?.trace", self.PAGE)
        self.assertRegex(self.PAGE, r"\.planned \{[^}]*stroke-dasharray", "planned is dashed")
        self.assertRegex(self.PAGE, r"\.actual \{[^}]*stroke:", "actual is a line of its own")
        self.assertNotRegex(self.PAGE, r"\.actual \{[^}]*stroke-dasharray", "actual is solid")
        self.assertIn(">planned</text>", self.PAGE)
        self.assertIn(">actual</text>", self.PAGE)


class Tool(unittest.TestCase):
    def test_plan_path_reads_the_saved_grid_with_no_dog(self):
        """`python -m wtdd plan_path from=300,900 to=650,900` with the fixture as ui/grid.json: the grid, through the
        calibration saved in it, is the cost map (DEMO_CACHE: 01's saved-grid fallback); grid=false is the rooms."""
        from wtdd.dog import session
        from wtdd.tools import plan_path
        with mock.patch.object(session, "GRID_FILE", fx.OUT), mock.patch.dict(os.environ, {"WTDD_API_PROCESS": ""}):
            out = plan_path.run(**{"from": "300,900", "to": "650,900"})
            self.assertEqual(out["cost_map"], "grid")
            d, at = nearest(samples(out["path"]), fx.wall_px())
            self.assertGreaterEqual(d, CLEAR_PX, f"route passes {at} within {d:.0f} px of the wall: {out['path']}")
            # (650, 900) is 30 px from the kitchen's edge: unwalkable on the rooms; the rooms half uses the living-room pair
            self.assertEqual(plan_path.run(**{"from": "300,1100", "to": "650,1100", "grid": False})["cost_map"], "rooms")


if __name__ == "__main__":
    unittest.main()
