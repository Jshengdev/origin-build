"""No-go zones (goals/roadmap.md 04): a zone drawn on the map with `nogo: true` blocks the planner, and a taught route
that touches one is refused by the walk and by the follower before anything moves, with one `route.refused` ledger row
sourced to the map. Run: python -m unittest wtdd.test_nogo -v

Fixture: wtdd/fixtures/map_nogo.json (built by wtdd/fixtures/make_map_nogo.py): the shipped rooms, one no-go zone
nogo-1 (x 450..510, y 1040..1250, across the living room) and a taught route straight through it. This module points
WTDD_MAP at a scratch COPY of that fixture and WTDD_LEDGER at a scratch file BEFORE importing the package (the pattern of
wtdd/chat/test_chat.py), so no test touches ui/map.json, the real ledger, a light or the dog. The follower test builds a
DogSession with no calibration and no dog: the refusal must come before the session even tries to connect.
What is NOT here: the remote's shading and its draw-no-go mode are a browser check at GREEN (the PR body), and the
lighting zones a/b/c on the shipped map must stay meaningless to the planner (test_lighting_zones_are_not_nogo).

The row contract (NIGHT-1 contracts, section E): tool "route.refused", app "map", ok false, source "map" (top level
AND args.source, so a fixture built from the roadmap's names finds it either way), args {zone, waypoint: [x, y], index,
source, shift_id}; agent is the caller ("field" for the walk, "dog" for the follower). A waypoint is a map point: the
path point inside the zone, or, when the route crosses the zone between two points, the first sampled point inside it
(index = that segment's first path index)."""
from __future__ import annotations
import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-nogo-test-"))
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "map_nogo.json"
TMP_MAP = _TMP / "map.json"
shutil.copy(FIXTURE, TMP_MAP)
os.environ["WTDD_MAP"] = str(TMP_MAP)                      # the map every module reads (wtdd/field.py MAP), like WTDD_LEDGER
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")

from wtdd import field, ledger, plan  # noqa: E402
from wtdd.field import inside  # noqa: E402

ZONE = next(z for z in json.loads(FIXTURE.read_text())["zones"] if z.get("nogo"))
POLY = ZONE["poly"]
PATH_THROUGH = [[300, 1100], [480, 1100], [650, 1100]]              # point 2 is inside the zone
PATH_ACROSS = [[300, 1100], [430, 1100], [540, 1100], [650, 1100]]  # no point inside; the 430->540 segment crosses it
CLEAR_PX = (plan.HALF_WIDTH - 1) * plan.CELL   # the dog is HALF_WIDTH cells wide: its body, not just the route's line, stays out (same erosion the rooms get)


def _samples(pts, step=1.0):
    """Every point along the polyline at `step` px (both ends included): a route is its segments, not its corners."""
    for a, b in zip(pts, pts[1:]):
        n = max(1, math.ceil(math.dist(a, b) / step))
        for k in range(n + 1):
            yield (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)


def _dist_to_poly(p, poly) -> float:
    """Distance from p to the polygon's outline (0 when on it; the tests reject inside separately)."""
    best = math.inf
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.dist(p, (ax + t * dx, ay + t * dy)))
    return best


def _set_path(pts) -> None:
    m = json.loads(TMP_MAP.read_text())
    m["path"], m["stops"], m["actions"] = pts, [], {}
    TMP_MAP.write_text(json.dumps(m) + "\n")


class Planner(unittest.TestCase):
    def test_planned_path_keeps_out_of_the_zone(self):
        """from=300,1100 to=650,1100: the straight line runs through nogo-1, so the planner must detour, and no point of
        the route (sampled every px, not only the corners) is inside the zone or closer than the dog's half-width."""
        n0 = len(ledger.rows())
        out = plan.plan((300, 1100), (650, 1100))
        pts = out["path"]
        self.assertGreaterEqual(len(pts), 2, out)
        hits = [p for p in _samples(pts) if inside(p, POLY)]
        self.assertEqual(hits, [], f"planned route enters {ZONE['name']} at {hits[:1]} ({len(hits)} px of it): {pts}")
        for p in _samples(pts):
            self.assertGreaterEqual(_dist_to_poly(p, POLY), CLEAR_PX, f"route passes {p} within {CLEAR_PX} px of {ZONE['name']}: {pts}")
        rows = [r for r in ledger.rows()[n0:] if r["tool"] == "plan.route"]
        self.assertEqual(len(rows), 1, "one plan.route row")
        self.assertEqual(rows[0]["args"].get("nogo"), [ZONE["name"]], "the receipt names the zones the planner blocked")

    def test_lighting_zones_are_not_nogo(self):
        """zones a/b/c on the shipped map carry no nogo flag: they are the light show's zones, never a block."""
        from wtdd import nogo
        shipped = json.loads((Path(__file__).resolve().parents[1] / "ui" / "map.json").read_text())
        self.assertEqual(nogo.zones(shipped), [])
        self.assertEqual([z["name"] for z in nogo.zones(json.loads(FIXTURE.read_text()))], [ZONE["name"]])


class Refusal(unittest.TestCase):
    def setUp(self):
        self.n0 = len(ledger.rows())
        field.FIELD.unlink(missing_ok=True)

    def new_rows(self):
        return ledger.rows()[self.n0:]

    def assert_refused_row(self, row, agent, index):
        self.assertEqual(row["tool"], "route.refused")
        self.assertEqual(row["agent"], agent)
        self.assertEqual(row["app"], "map")
        self.assertIs(row["ok"], False)
        self.assertEqual(row["source"], "map", "the refusal is sourced to the map, not a model and not 'live'")
        a = row["args"]
        self.assertEqual(a["zone"], ZONE["name"])
        self.assertEqual(a["source"], "map")
        self.assertEqual(a["index"], index)
        self.assertTrue(inside(a["waypoint"], POLY), f"the refused waypoint {a['waypoint']} must be inside the zone")
        self.assertTrue(isinstance(a.get("shift_id"), str) and a["shift_id"], "every shift row carries args.shift_id")

    def test_walk_refuses_a_waypoint_inside_the_zone(self):
        _set_path(PATH_THROUGH)
        with self.assertRaises(ValueError) as cm:
            field.walk(dry=True)
        self.assertIn(ZONE["name"], str(cm.exception))
        rows = self.new_rows()
        refused = [r for r in rows if r["tool"] == "route.refused"]
        self.assertEqual(len(refused), 1, f"exactly one route.refused row, got {[r['tool'] for r in rows]}")
        self.assert_refused_row(refused[0], "field", 1)
        self.assertEqual(refused[0]["args"]["waypoint"], [480, 1100])
        self.assertEqual([r["tool"] for r in rows if r["tool"] == "field.walk"], [], "refused before the walk began: no field.walk row")
        self.assertFalse(field.FIELD.exists(), "nothing was published to the remote")

    def test_walk_refuses_a_segment_crossing_the_zone(self):
        _set_path(PATH_ACROSS)
        with self.assertRaises(ValueError) as cm:
            field.walk(dry=True)
        self.assertIn(ZONE["name"], str(cm.exception))
        refused = [r for r in self.new_rows() if r["tool"] == "route.refused"]
        self.assertEqual(len(refused), 1)
        self.assert_refused_row(refused[0], "field", 1)   # the segment 430->540 starts at path index 1

    def test_follow_refuses_before_connecting(self):
        """dog.follow with a route through the zone: refused first, before calibration is checked, before any probe or
        connect, with the row; the session stays untouched (no body, no follow state, no dog.* row)."""
        from wtdd.dog.session import DogSession
        _set_path(PATH_THROUGH)
        s = DogSession()
        with self.assertRaises(ValueError) as cm:
            s.follow(PATH_THROUGH, [])
        self.assertIn(ZONE["name"], str(cm.exception))
        rows = self.new_rows()
        refused = [r for r in rows if r["tool"] == "route.refused"]
        self.assertEqual(len(refused), 1, f"exactly one route.refused row, got {[r['tool'] for r in rows]}")
        self.assert_refused_row(refused[0], "dog", 1)
        self.assertEqual([r["tool"] for r in rows if r["tool"].startswith("dog.")], [], "no probe, no connect, no dog.follow row")
        self.assertIsNone(s.body)
        self.assertEqual(s.follow_state, {})


if __name__ == "__main__":
    unittest.main()
