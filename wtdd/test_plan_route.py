"""Tests for goal 21, route the map (night-2 roadmap): the stops a person taps become one route planned leg by leg over
the dog's own occupancy grid (06's planner, wtdd/plan.py), the leg ends become the map's stops with the default action,
and the planned route becomes the map's path through the same rules as the page's save. Run:

    python -m unittest wtdd.test_plan_route
    cp wtdd/fixtures/grid_wall.json ui/grid.json && python -m wtdd plan_route "stops=448,455;436,586;520,600"; rm ui/grid.json

RED until wtdd/plan.py grows route() and wtdd/tools/plan_route.py exists.

Fixtures (06's; nothing new): wtdd/fixtures/make_grid_wall.py builds the grid in memory (one 1.5 m wall at map x ≈ 474,
y 829..992, tied to the map by CAL) and grid_wall.json is that grid saved, the file the CLI pair plants as ui/grid.json;
wtdd/fixtures/map_nogo.json is the shipped rooms plus the no-go zone nogo-1 (x 450..510, y 1040..1250). This module
points plan.MAP, field.MAP and nogo.MAP at a scratch COPY of that map and WTDD_LEDGER at a scratch file BEFORE importing
the package (wtdd/test_plan_grid.py's pattern, whose clearance helpers it reuses), so no test touches ui/map.json, the
real ledger, a light or the dog. Every clearance is measured against make_grid_wall.wall_px() and the zone's polygon,
never against the planner's own output. WTDD_NO_PLAN is unset here on purpose: main's room rule decides the save (14's
flag lifts it when 14 is beneath; these tests hold either way).

The contract under test:
  plan.route(points, grid=None, cal=None, zones=None, threshold=None, lock=None, grid_source="session")
        points[0] is the start (the caller's believed pose, or the first tap), points[1:] are the stops. One plan() per
        leg in order (06's plan.route row per leg, with args.leg = k and args.legs = n), the legs' waypoints concatenated
        (a leg's first point is the previous leg's last, kept once), every consecutive gap at most field.MAX_STEP_PX (a
        straight leg longer than a jump is subdivided so the saved path passes check_path's jump rule), stops = the
        index of each leg's end in that path (never 0), actions = {str(index): {look: tilt, say: true, ask: false}}
        (the default the remote's "mark stop here" writes), length_m = the legs' sum. zones None = the map's confirmed
        no-go zones (nogo.zones: nogo: true); a list given is the confirmed set instead and is validated the same way
        (a malformed zone fails the row, 04's rule). Returns {path, stops, actions, legs: [{leg, from, to, waypoints,
        length_m}], length_m, cost_map, why?, grid_source}. Nothing here writes the map.
        One plan.multistop row (agent plan, app map): args {points, legs, cell_px, cost_map, why?, grid_source (on the
        grid), shift_id, failed_leg? {leg, of, from, to, error}}; state_after {legs, stops, length_m, waypoints};
        cached/source follow 06's grid_source rule (a planted ui/grid.json is cached, source ui/grid.json). A leg with
        no route: ValueError naming the leg ("leg k of n"), carrying .failed_leg for the page's red dashed line, the row
        ok false with args.failed_leg, and NO partial route returned.
  wtdd/tools/plan_route.py run(stops="x1,y1;x2,y2;…", from=None, save=False)
        from given: the start; else in the API process the session's believed pose when calibrated; else the first
        stop is the start (never an HTTP call to another API). The grid: the session's in the API process, else
        ui/grid.json through its saved calibration (06's DEMO_CACHE), else the rooms fallback with 06's WARN. save=true
        writes path, stops and actions into the map through POST /map's rules: check_path(path, rooms) refuses with the
        points named, the previous map is kept as map.prev.json, and nothing is written on a refusal or a failed leg.
"""
from __future__ import annotations
import io
import json
import math
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-plan-route-test-"))
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "map_nogo.json"
TMP_MAP = _TMP / "map.json"
PREV = _TMP / "map.prev.json"
shutil.copy(FIXTURE, TMP_MAP)
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ.pop("WTDD_NO_PLAN", None)   # main's room rule decides the save here; 14's flag is a different branch's take

from wtdd import field, ledger, nogo, plan, tools  # noqa: E402
from wtdd.field import inside, room_of  # noqa: E402
from wtdd.fixtures import make_grid_wall as fx  # noqa: E402
from wtdd.test_plan_grid import CLEAR_PX, dist_to_poly, nearest, rows_since, samples  # noqa: E402

CAL = fx.CAL
MAP_DICT = json.loads(FIXTURE.read_text())
ROOMS = MAP_DICT["rooms"]
ZONE = next(z for z in MAP_DICT["zones"] if z.get("nogo"))
POLY = ZONE["poly"]
DEFAULT_ACTION = {"look": "tilt", "say": True, "ask": False}   # what the remote's "mark stop here" records (POST /dog/mark)
THROUGH_WALL = [(300, 900), (650, 900), (300, 1100)]           # leg 1 crosses the fixture wall; leg 2 passes its end
THROUGH_ZONE = [(300, 1100), (650, 1100)]                     # 06's pair: the straight line runs through nogo-1
AROUND_ZONE = [(300, 1100), (650, 1100), (650, 1300)]         # the same, then south: every point in the living room, saveable
ON_WALL = (474, 900)                                          # the wall's own map x (make_grid_wall: 300 + 108.5 * 1.6)
OUTSIDE = (150, 1300)                                         # outside every drawn room; open floor to the grid


def setUpModule():
    global _patches
    _patches = [mock.patch.object(mod, "MAP", TMP_MAP) for mod in (plan, field, nogo)]   # the planner, the tool's save, the zone check
    for p in _patches:
        p.start()


def tearDownModule():
    for p in _patches:
        p.stop()


def gaps(pts) -> list[float]:
    return [math.dist(a, b) for a, b in zip(pts, pts[1:])]


def near(p, q, tol=plan.CELL) -> bool:
    return math.dist(p, q) <= tol


def clear_of_wall_and_zone(tc: unittest.TestCase, pts, wall) -> None:
    """wall None: the rooms fallback, whose cost map has no LiDAR wall on it; only the zone is checked there."""
    if wall is not None:
        d, at = nearest(samples(pts), wall)
        tc.assertGreaterEqual(d, CLEAR_PX, f"route passes {at} within {d:.0f} px of the wall: {pts}")
    hits = [p for p in samples(pts) if inside(p, POLY)]
    tc.assertEqual(hits, [], f"route enters {ZONE['name']} at {hits[:1]} ({len(hits)} px of it): {pts}")
    for p in samples(pts):
        tc.assertGreaterEqual(dist_to_poly(p, POLY), CLEAR_PX, f"route passes {p} within {CLEAR_PX} px of {ZONE['name']}: {pts}")


class Fresh(unittest.TestCase):
    """Every test starts from the fixture map with no previous file, so 'nothing written' is measurable."""

    def setUp(self):
        shutil.copy(FIXTURE, TMP_MAP)
        PREV.unlink(missing_ok=True)
        self.before = TMP_MAP.read_text()
        self.n0 = len(ledger.rows())
        self.g = fx.grid()
        self.wall = fx.wall_px()

    def assert_nothing_written(self):
        self.assertEqual(TMP_MAP.read_text(), self.before, "the map must not change")
        self.assertFalse(PREV.exists(), "no previous file is written when nothing is saved")


class Route(Fresh):
    def test_three_taps_make_one_route_with_two_stops_clear_of_the_wall_and_the_zone(self):
        out = plan.route(THROUGH_WALL, grid=self.g, cal=CAL)
        pts, stops = out["path"], out["stops"]
        self.assertEqual(out["cost_map"], "grid")
        self.assertTrue(near(pts[0], THROUGH_WALL[0]), f"the route starts at the first tap: {pts[0]}")
        self.assertEqual(len(stops), 2, f"two taps after the start are two stops: {stops}")
        self.assertEqual(stops, sorted(stops))
        self.assertNotIn(0, stops, "the start is not a stop")
        for k, i in enumerate(stops):
            self.assertTrue(near(pts[i], THROUGH_WALL[k + 1]), f"stop {k + 1} sits on tap {k + 1}: path[{i}] = {pts[i]}")
        self.assertEqual(stops[-1], len(pts) - 1, "the last stop is the route's end")
        self.assertEqual(out["actions"], {str(i): DEFAULT_ACTION for i in stops}, "every stop gets the default action, keyed as the map keys them")
        legs = out["legs"]
        self.assertEqual([(l["leg"], l["from"], l["to"]) for l in legs], [(1, [300, 900], [650, 900]), (2, [650, 900], [300, 1100])])
        self.assertGreaterEqual(len(pts), 5, f"a straight line crosses the wall; the legs must bend: {pts}")
        clear_of_wall_and_zone(self, pts, self.wall)
        self.assertLessEqual(max(gaps(pts)), field.MAX_STEP_PX, "no jump: the saved path must pass check_path")
        self.assertAlmostEqual(out["length_m"], sum(l["length_m"] for l in legs), delta=0.05)
        self.assertGreater(out["length_m"], 0)
        self.assert_nothing_written()
        legs_rows = rows_since(self.n0, "plan.route")
        self.assertEqual([(r["ok"], r["args"]["leg"], r["args"]["legs"]) for r in legs_rows], [(True, 1, 2), (True, 2, 2)], "one plan.route row per leg, numbered")
        rows = rows_since(self.n0, "plan.multistop")
        self.assertEqual(len(rows), 1, "one plan.multistop row")
        r = rows[0]
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["agent"], r["app"]), ("plan", "map"))
        a = r["args"]
        self.assertEqual(a["points"], [[300, 900], [650, 900], [300, 1100]])
        self.assertEqual((a["legs"], a["cell_px"], a["cost_map"], a["grid_source"]), (2, plan.CELL, "grid", "session"))
        self.assertTrue(isinstance(a.get("shift_id"), str) and a["shift_id"], "every shift row carries args.shift_id")
        self.assertNotIn("failed_leg", a)
        self.assertEqual((r["state_after"]["stops"], r["state_after"]["waypoints"], r["state_after"]["length_m"]), (stops, len(pts), out["length_m"]))
        self.assertEqual([l["leg"] for l in r["state_after"]["legs"]], [1, 2])
        self.assertEqual((r["cached"], r["source"]), (False, "live"), "an in-memory session grid is the live path")
        all_rows = ledger.rows()[self.n0:]
        self.assertGreater(all_rows.index(r), max(all_rows.index(x) for x in legs_rows), "the legs' receipts land before the route's")

    def test_a_tap_behind_the_zone_detours_around_it(self):
        out = plan.route(THROUGH_ZONE, grid=self.g, cal=CAL)
        pts = out["path"]
        self.assertGreaterEqual(len(pts), 3, f"a straight line runs through {ZONE['name']}; the leg must bend: {pts}")
        clear_of_wall_and_zone(self, pts, self.wall)
        self.assertEqual(out["stops"], [len(pts) - 1])
        self.assertEqual(len(out["legs"]), 1)
        rows = rows_since(self.n0, "plan.multistop")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["ok"])
        self.assertEqual(rows[0]["args"]["legs"], 1)

    def test_zones_given_are_the_confirmed_set_and_a_malformed_one_fails_the_row(self):
        out = plan.route(THROUGH_ZONE, grid=self.g, cal=CAL, zones=[ZONE])
        clear_of_wall_and_zone(self, out["path"], self.wall)
        n1 = len(ledger.rows())
        with self.assertRaises(ValueError) as cm:
            plan.route(THROUGH_ZONE, grid=self.g, cal=CAL, zones=[{"name": "bad", "nogo": "yes", "poly": []}])
        self.assertIn("bad", str(cm.exception))
        rows = rows_since(n1, "plan.multistop")
        self.assertEqual(len(rows), 1, "a malformed zone is a failed row, never an inert zone")
        self.assertIs(rows[0]["ok"], False)
        self.assertIn("bad", rows[0]["response_or_error"])
        self.assert_nothing_written()

    def test_a_tap_inside_a_wall_is_a_failed_leg_and_no_partial_route(self):
        taps = [(300, 900), (650, 900), ON_WALL]
        with self.assertRaises(ValueError) as cm:
            plan.route(taps, grid=self.g, cal=CAL)
        self.assertIn("leg 2 of 2", str(cm.exception), "the error names the leg")
        fl = getattr(cm.exception, "failed_leg", None)
        self.assertIsNotNone(fl, "the exception carries the failed leg for the page's red dashed line")
        self.assertEqual((fl["leg"], fl["of"], fl["from"], fl["to"]), (2, 2, [650, 900], [474, 900]))
        self.assertTrue(fl.get("error"), "and why")
        self.assertEqual([r["ok"] for r in rows_since(self.n0, "plan.route")], [True, False], "leg 1 planned, leg 2 failed, nothing after")
        rows = rows_since(self.n0, "plan.multistop")
        self.assertEqual(len(rows), 1, "one plan.multistop row, failed")
        r = rows[0]
        self.assertIs(r["ok"], False)
        self.assertIn("leg 2 of 2", r["response_or_error"])
        self.assertEqual((r["args"]["failed_leg"]["leg"], r["args"]["failed_leg"]["of"], r["args"]["failed_leg"]["to"]), (2, 2, [474, 900]))
        self.assertEqual(r["args"]["legs"], 2)
        self.assert_nothing_written()

    def test_a_double_tap_is_a_failed_leg_never_a_repeated_stop(self):
        """Two points in one lattice cell (a double tap, or a tap on the dog's own cell) leave that leg nothing to
        route: stops would repeat (or be 0) with fewer actions than stops. It fails the route by the leg instead."""
        for taps, leg in (([(300, 900), (650, 900), (650, 900)], "leg 2 of 2"), ([(300, 900), (302, 901)], "leg 1 of 1")):
            n1 = len(ledger.rows())
            with self.assertRaises(ValueError, msg=f"{taps}: a same-cell leg must fail, not repeat a stop") as cm:
                plan.route(taps, grid=self.g, cal=CAL)
            self.assertIn(leg, str(cm.exception))
            self.assertEqual(cm.exception.failed_leg["to"], list(taps[-1]))
            rows = rows_since(n1, "plan.multistop")
            self.assertEqual([r["ok"] for r in rows], [False], "one plan.multistop row, failed")
            self.assertIn(leg, rows[0]["response_or_error"])
            self.assert_nothing_written()

    def test_no_grid_is_the_rooms_fallback_and_the_row_says_so(self):
        err = io.StringIO()
        with redirect_stderr(err):
            out = plan.route(AROUND_ZONE)
        self.assertEqual(out["cost_map"], "rooms")
        self.assertIn("no grid", out["why"])
        clear_of_wall_and_zone(self, out["path"], None)   # no grid, so no LiDAR wall to clear (06's rooms route passes 3 px from it); the zone is blocked on both
        for p in samples(out["path"]):
            self.assertIsNotNone(room_of(p, ROOMS), f"the fallback keeps the route inside the drawn rooms: {p}")
        r = rows_since(self.n0, "plan.multistop")[0]
        self.assertEqual(r["args"]["cost_map"], "rooms")
        self.assertIn("no grid", r["args"]["why"])
        self.assertNotIn("grid_source", r["args"])
        warn = [ln for ln in err.getvalue().splitlines() if "WARN" in ln and "rooms" in ln]
        self.assertGreaterEqual(len(warn), 1, f"06's WARN names the fallback: {err.getvalue()!r}")


class Tool(Fresh):
    """python -m wtdd plan_route: the saved grid with no dog (06's DEMO_CACHE), the start rule, and the save through
    the map's own rules."""

    def setUp(self):
        super().setUp()
        from wtdd.dog import session
        self.enterContext(mock.patch.object(session, "GRID_FILE", fx.OUT))
        self.enterContext(mock.patch.dict(os.environ, {"WTDD_API_PROCESS": ""}))

    def run_tool(self, **kw):
        from wtdd.tools import plan_route
        return plan_route.run(**kw)

    def test_the_tool_is_listed_with_its_args(self):
        spec = {t["name"]: t["args"] for t in tools.describe()}
        self.assertIn("plan_route", spec)
        self.assertEqual(set(spec["plan_route"]), {"stops", "from", "save"})
        self.assertIs(spec["plan_route"]["save"]["default"], False)

    def test_the_cli_pair_prints_the_legs_and_the_stops_from_the_saved_grid(self):
        """cp wtdd/fixtures/grid_wall.json ui/grid.json && python -m wtdd plan_route "stops=448,455;436,586;520,600"."""
        out = self.run_tool(stops="448,455;436,586;520,600")
        self.assertEqual(len(out["legs"]), 2)
        self.assertEqual(len(out["stops"]), 2)
        self.assertEqual((out["cost_map"], out["grid_source"]), ("grid", "ui/grid.json"))
        self.assertTrue(near(out["path"][0], (448, 455)), "no from= and no dog: the first tap is the start")
        self.assertTrue(near(out["path"][out["stops"][0]], (436, 586)) and near(out["path"][out["stops"][1]], (520, 600)))
        self.assertNotIn("saved", out)
        self.assert_nothing_written()
        r = rows_since(self.n0, "plan.multistop")[0]
        self.assertEqual((r["cached"], r["source"], r["args"]["grid_source"]), (True, "ui/grid.json", "ui/grid.json"), "a planted grid never claims live")

    def test_from_stands_for_the_believed_pose_so_every_tap_is_a_stop(self):
        out = self.run_tool(**{"from": "300,900", "stops": "650,900;300,1100"})
        self.assertTrue(near(out["path"][0], (300, 900)))
        self.assertEqual(len(out["stops"]), 2, "with a start given, every tap is a stop")
        self.assertEqual(out["path"], plan.route(THROUGH_WALL, grid=fx.grid(), cal=CAL)["path"], "the same legs as the first-tap start")

    def test_save_writes_the_route_through_the_maps_rules_and_keeps_the_previous_path(self):
        prev = json.loads(self.before)
        out = self.run_tool(stops="300,1100;650,1100;650,1300", save=True)
        self.assertIs(out.get("saved"), True)
        m = json.loads(TMP_MAP.read_text())
        self.assertEqual((m["path"], m["stops"], m["actions"]), (out["path"], out["stops"], out["actions"]))
        self.assertEqual((m["rooms"], m["zones"], m["lights"], m["entity"]), (prev["rooms"], prev["zones"], prev["lights"], prev["entity"]), "only path, stops and actions change")
        self.assertEqual(field.check_path(m["path"], m["rooms"]), [], "the saved route passes the page's own rules")
        clear_of_wall_and_zone(self, m["path"], self.wall)
        self.assertTrue(PREV.exists(), "the previous map is kept as map.prev.json")
        self.assertEqual(json.loads(PREV.read_text())["path"], prev["path"], "the taught route survives as the fallback")
        rows = rows_since(self.n0, "plan.saved")
        self.assertEqual(len(rows), 1, "one plan.saved row, the save's own receipt")
        r = rows[0]
        self.assertIs(r["ok"], True, r)
        self.assertEqual((r["agent"], r["app"]), ("plan", "map"))
        self.assertEqual((r["args"]["path_pts"], r["args"]["stops"]), (len(out["path"]), out["stops"]))
        self.assertTrue(isinstance(r["args"].get("shift_id"), str) and r["args"]["shift_id"], "every shift row carries args.shift_id")
        self.assertEqual(r["state_before"], {"path_pts": len(prev["path"]), "stops": prev.get("stops", [])}, "the map it replaced")
        self.assertEqual(r["state_after"], {"path_pts": len(m["path"]), "stops": m["stops"], "prev": f"{TMP_MAP.parent.name}/map.prev.json"})

    def test_a_straight_leg_longer_than_a_jump_is_subdivided_so_the_save_is_accepted(self):
        out = self.run_tool(stops="300,1300;650,1300", save=True)   # 350 px straight on the grid: over MAX_STEP_PX as one segment
        self.assertLessEqual(max(gaps(out["path"])), field.MAX_STEP_PX, out["path"])
        self.assertTrue(near(out["path"][out["stops"][0]], (650, 1300)))
        self.assertEqual(field.check_path(json.loads(TMP_MAP.read_text())["path"], ROOMS), [])

    def test_a_route_with_a_point_outside_every_room_is_refused_by_check_path(self):
        """main's rule: the drawn rooms decide the save (field.check_path). 14's WTDD_NO_PLAN=1 lifts it when 14 is
        beneath; unset here (module setup), so this holds on this branch and after that merge."""
        self.assertIsNone(room_of(OUTSIDE, ROOMS))
        with self.assertRaises(ValueError) as cm:
            self.run_tool(stops=f"300,1300;{OUTSIDE[0]},{OUTSIDE[1]}", save=True)
        self.assertIn("outside every room", str(cm.exception))
        self.assert_nothing_written()
        rows = rows_since(self.n0, "plan.multistop")
        self.assertEqual([r["ok"] for r in rows], [True], "the plan itself succeeded on the grid; the refusal is the save's")
        saved = rows_since(self.n0, "plan.saved")
        self.assertEqual([r["ok"] for r in saved], [False], "the refusal is one plan.saved row, failed")
        self.assertIn("outside every room", saved[0]["response_or_error"], "with check_path's words")
        self.assertIsNone(saved[0]["state_after"], "nothing was written")

    def test_a_failed_leg_writes_nothing_even_with_save(self):
        with self.assertRaises(ValueError) as cm:
            self.run_tool(stops=f"300,900;650,900;{ON_WALL[0]},{ON_WALL[1]}", save=True)
        self.assertIn("leg 2 of 2", str(cm.exception))
        self.assert_nothing_written()
        self.assertEqual(rows_since(self.n0, "plan.saved"), [], "no route, so no save was attempted: no plan.saved row")


if __name__ == "__main__":
    unittest.main()
