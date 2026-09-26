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
CLEAR_PX = (plan.HALF_WIDTH - 1) * plan.CELL   # the dog is HALF_WIDTH cells wide: its body, not just the route's line, stays out
ROUTE = [[300 + 50 * k, 1400] for k in range(8)]   # a taught route along the living room's bottom, x 300..650 at y 1400
BLOB_AT = (500, 1400)                              # a blob on waypoint 4; its inflation covers waypoints 3..5 (measured in Replan)


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
        self.assertTrue(plan.occupied((wx + (plan.HALF_WIDTH - 1) * plan.CELL, 900), g, CAL), "within the dog's half-width of the wall")
        self.assertFalse(plan.occupied((wx + (plan.HALF_WIDTH + 2) * plan.CELL, 900), g, CAL), "beyond the inflation")
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
        self.assertEqual([i for i, p in enumerate(ROUTE) if plan.occupied(p, g, CAL)], [3, 4, 5], "the blob and its inflation cover waypoints 3..5")
        n0 = len(ledger.rows())
        p = ROUTE[2]   # the dog has reached waypoint 2 and is about to drive to 3
        det = plan.replan(p, ROUTE, 3, g, CAL)
        self.assertEqual(det["blocked"], {"index": 3, "waypoint": [450, 1400]})
        self.assertEqual(det["rejoin"], {"index": 6, "waypoint": [600, 1400]})
        self.assertEqual(det["skipped"], [3, 4, 5])
        self.assertEqual(det["cost_map"], "grid")
        pts = det["path"]
        self.assertGreaterEqual(len(pts), 3, f"a straight line to the rejoin crosses the blob; the detour must bend: {pts}")
        self.assertLessEqual(math.dist(pts[0], p), plan.CELL, "the detour starts where the dog is")
        self.assertLessEqual(math.dist(pts[-1], ROUTE[6]), plan.CELL, "the detour ends on the rejoin waypoint")
        d, at = nearest(samples(pts), blob)
        self.assertGreaterEqual(d, CLEAR_PX, f"detour passes {at} within {d:.0f} px of the blob: {pts}")
        self.assertEqual([q for q in pts if plan.occupied(q, g, CAL)], [], "no detour waypoint is occupied")
        rows = rows_since(n0, "plan.replanned")
        self.assertEqual(len(rows), 1, "one plan.replanned row")
        r = rows[0]
        self.assertTrue(r["ok"])
        self.assertEqual((r["agent"], r["app"]), ("plan", "map"))
        a = r["args"]
        self.assertEqual(a["from"], [400, 1400])
        self.assertEqual((a["blocked"], a["rejoin"], a["skipped"]), (det["blocked"], det["rejoin"], [3, 4, 5]))
        self.assertEqual((a["cost_map"], a["threshold"], a["nogo"], a["cell_px"]), ("grid", occupancy.THRESHOLD, [ZONE["name"]], plan.CELL))
        self.assertGreater(a["walls"], 31, "the wall's cells and the blob's")
        self.assertTrue(isinstance(a.get("shift_id"), str) and a["shift_id"], "every shift row carries args.shift_id")
        self.assertEqual(r["state_after"]["waypoints"], len(pts))
        self.assertEqual(rows_since(n0, "plan.route"), [], "a replan is its own row, not a plan.route")

    def test_a_blob_on_the_end_of_the_route_fails_loud(self):
        """The goal itself is occupied: no rejoin exists, ValueError, the row ok false naming it; never a route to
        somewhere else."""
        g = fx.grid(blob_px=tuple(ROUTE[-1]))
        i = next(k for k, p in enumerate(ROUTE) if plan.occupied(p, g, CAL))
        self.assertEqual(i, 6, "the blob on the end and its inflation cover waypoints 6..7")
        n0 = len(ledger.rows())
        with self.assertRaises(ValueError) as cm:
            plan.replan(ROUTE[i - 1], ROUTE, i, g, CAL)
        self.assertIn("occupied", str(cm.exception).lower())
        rows = rows_since(n0, "plan.replanned")
        self.assertEqual(len(rows), 1, "one plan.replanned row, failed")
        self.assertIs(rows[0]["ok"], False)
        self.assertIn("occupied", rows[0]["response_or_error"].lower())
        self.assertEqual(rows[0]["args"]["blocked"], {"index": 6, "waypoint": [600, 1400]})


class Follower(unittest.TestCase):
    """DogSession.follow with a teleporting body (module doc): the follower's own loop, no dog, no clock."""

    def setUp(self):
        from wtdd.dog import session
        self.believed = list(ROUTE[0])
        self.targets: list[tuple[int, int]] = []

        def steer(px, py, heading, target, reach_px):
            self.targets.append((int(target[0]), int(target[1])))
            self.believed[:] = [target[0], target[1]]
            return {"x": 0.0, "z": 0.0, "dist_px": 0, "err_deg": 0.0, "reached": True}

        self.enterContext(mock.patch.object(session.nav, "steer", steer))
        self.enterContext(mock.patch.object(session, "CAL_FILE", _TMP / "dog_cal.json"))   # never the checkout's calibration
        s = self.s = session.DogSession()
        s.cal = dict(CAL)
        s.body = types.SimpleNamespace(_avoid=True)
        s._ensure = mock.AsyncMock(return_value=s.body)
        s._halt = mock.AsyncMock(return_value={})
        s.map_pose = lambda st=None: {"p": [round(self.believed[0]), round(self.believed[1])], "heading_deg": 0.0}
        self.n0 = len(ledger.rows())

    def tearDown(self):
        stop(self.s)

    def run_follow(self, stops: list[int], grid) -> tuple[dict, list[int]]:
        s = self.s
        s.grid = grid
        resumed: list[int] = []
        s.follow(ROUTE, stops, reach_px=30.0)

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

    def test_a_blob_on_the_next_waypoint_makes_the_follower_replan_and_reach_the_end(self):
        blob = fx.blob_px(BLOB_AT)
        fs, resumed = self.run_follow([4], fx.grid(blob_px=BLOB_AT))
        self.assertIsNone(fs.get("error"), fs)
        self.assertTrue(fs.get("done"), fs)
        self.assertEqual(self.targets[-1], (650, 1400), "the route's end is reached")
        for k in (3, 4, 5):
            self.assertNotIn(tuple(ROUTE[k]), self.targets, f"waypoint {k} is occupied and is never driven to")
        taught = {tuple(p) for p in ROUTE}
        self.assertEqual([t for t in self.targets if t in taught], [tuple(p) for p in ROUTE[:3] + ROUTE[6:]], "the taught route resumes at the rejoin")
        i400, i600 = self.targets.index((400, 1400)), self.targets.index((600, 1400))
        self.assertGreaterEqual(i600 - i400 - 1, 1, f"the detour has waypoints of its own: {self.targets}")
        d, at = nearest(self.targets, blob)
        self.assertGreaterEqual(d, CLEAR_PX, f"the follower drove to {at}, {d:.0f} px from the blob: {self.targets}")
        self.assertEqual(resumed, [], "stop 4 sits on the blob: skipped, never waited on")
        self.assertEqual(fs["reached"], [0, 1, 2, 6, 7])
        self.assertEqual(len(fs["replans"]), 1, fs)
        rp = fs["replans"][0]
        self.assertEqual((rp["at"], rp["rejoin"], rp["skipped_stops"]), (3, 6, [4]))
        self.assertEqual(rp["waypoints"], i600 - i400 - 1, "the detour's own points, every one driven, the taught rejoin not among them")
        rows = rows_since(self.n0, "plan.replanned")
        self.assertEqual(len(rows), 1, "one plan.replanned row")
        self.assertTrue(rows[0]["ok"])
        self.assertEqual(rows[0]["state_after"]["waypoints"], rp["waypoints"])
        self.assertEqual((rows[0]["args"]["blocked"]["index"], rows[0]["args"]["rejoin"]["index"]), (3, 6))
        f = rows_since(self.n0, "dog.follow")
        self.assertEqual(len(f), 1, "one dog.follow row")
        self.assertTrue(f[0]["ok"], f[0])
        self.assertEqual((f[0]["state_after"]["replans"], f[0]["state_after"]["skipped_stops"]), (1, [4]))
        self.assertEqual(f[0]["state_after"]["reached"], [0, 1, 2, 6, 7])

    def test_without_a_blob_the_follower_is_unchanged(self):
        fs, resumed = self.run_follow([2], fx.grid())
        self.assertIsNone(fs.get("error"), fs)
        self.assertTrue(fs.get("done"), fs)
        self.assertEqual(self.targets, [tuple(p) for p in ROUTE], "every waypoint, in order, nothing else")
        self.assertEqual(resumed, [2], "the stop is honoured")
        self.assertEqual(fs["reached"], list(range(len(ROUTE))))
        self.assertEqual(fs["replans"], [])
        self.assertEqual(rows_since(self.n0, "plan.replanned"), [])
        f = rows_since(self.n0, "dog.follow")
        self.assertEqual(len(f), 1)
        self.assertTrue(f[0]["ok"], f[0])
        self.assertEqual((f[0]["state_after"]["replans"], f[0]["state_after"]["skipped_stops"]), (0, []))


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
