"""Tests for the no-plan rule of item 14 (the scout): with WTDD_NO_PLAN=1 the house's drawn rooms are off (never
hidden), so a route recorded, drawn or planned on the dog's own map is accepted on its own terms. Run:

    python -m unittest wtdd.test_noplan

RED until wtdd/field.py, wtdd/plan.py and wtdd/api.py read the flag. No dog, no lights: a temp ui/map.json with one
drawn room, a temp ledger, and wtdd.api's handler on an ephemeral port in this process (never 7788).

The contract under test:
  WTDD_NO_PLAN      an env key read at the point of use through config.maybe() (night-1 contracts D: no new constant in
                    config.py); "1" turns the room rule off; unset or "0" changes nothing
  field.check_path(path, rooms)   under the flag: no "outside every room" line, and exactly one stderr line
                    `[wtdd:field] WARN rooms off under WTDD_NO_PLAN` per call; the other two rules stay (at least 2
                    points; no jump over MAX_STEP_PX)
  field.walk        the field.walk row of a walk the room rule would have refused carries args.why
                    "rooms off: WTDD_NO_PLAN" (no why when every point is in a room); without the flag the same walk is
                    refused as today (ValueError, no row)
  plan.plan(a, b)   under the flag: one plan.route row ok=false naming "no session grid under WTDD_NO_PLAN", and it
                    raises (the rooms path only; 06's grid path is not on this branch); without the flag it plans over
                    the drawn rooms as today
  GET /map          no_plan: true under the flag; no no_plan (or false) without it
  POST /map         under the flag a path outside every room is saved (200, why "rooms off: WTDD_NO_PLAN") and the
                    no_plan that GET added is never written into ui/map.json; without the flag it is refused (400)
  POST /dog/follow  under the flag the room rule does not refuse (the next refusal is the session's "not calibrated");
                    without the flag it is refused naming the room
  ui/index.html     the house.svg layer is conditioned on no_plan, and the `no plan · site` chip is on the page
"""
from __future__ import annotations
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import ExitStack, redirect_stderr
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from . import api, config, field, ledger, plan
from .dog import session

WHY = "rooms off: WTDD_NO_PLAN"
WARN = "rooms off under WTDD_NO_PLAN"
ROOMS = [{"name": "hall", "poly": [[100, 100], [500, 100], [500, 500], [100, 500]]}]
INSIDE = [[200, 200], [300, 300]]
OUTSIDE = [[700, 700], [780, 760], [860, 820]]   # every point outside the one room, 100 px apart (under MAX_STEP_PX)


def setUpModule():
    config.maybe("WTDD_NO_PLAN")   # a .env, if any, is read now, once; each test's flag() below is then the only setting


class NoPlan(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.map = self.tmp / "map.json"
        self.write_map(OUTSIDE)
        for mod in (field, plan, api):   # each module bound ui/map.json at import
            self.stack.enter_context(mock.patch.object(mod, "MAP", self.map))
        self.stack.enter_context(mock.patch.object(field, "FIELD", self.tmp / "field.json"))
        self.stack.enter_context(mock.patch.object(field, "STOP", self.tmp / "field.stop"))
        self.stack.enter_context(mock.patch.object(ledger, "LEDGER", self.tmp / "ledger.jsonl"))
        self.stack.enter_context(mock.patch.dict(os.environ))
        self.err = self.stack.enter_context(redirect_stderr(io.StringIO()))

    @staticmethod
    def flag(value: str | None) -> None:
        if value is None:
            os.environ.pop("WTDD_NO_PLAN", None)
        else:
            os.environ["WTDD_NO_PLAN"] = value

    def write_map(self, path: list) -> None:
        self.map.write_text(json.dumps({"path": path, "stops": [], "rooms": ROOMS, "lights": [],
                                        "entity": {"speed_px_s": 5000}}))

    def warns(self) -> list[str]:
        return [l for l in self.err.getvalue().splitlines() if WARN in l]

    def rows(self, tool: str) -> list[dict]:
        return [r for r in ledger.rows() if r.get("tool") == tool]

    def serve(self) -> str:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    @staticmethod
    def call(base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(base + path, method="GET" if body is None else "POST",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


class CheckPath(NoPlan):
    def test_the_room_rule_refuses_without_the_flag(self):
        for v in (None, "0"):
            self.flag(v)
            bad = field.check_path(OUTSIDE, ROOMS)
            self.assertEqual(sum("outside every room" in b for b in bad), 3, (v, bad))
        self.assertEqual(self.warns(), [], "with the flag unset or 0 nothing changes")

    def test_under_the_flag_a_path_anywhere_passes_with_one_warn(self):
        self.flag("1")
        self.assertEqual(field.check_path(OUTSIDE, ROOMS), [])
        w = self.warns()
        self.assertEqual(len(w), 1, w)
        self.assertTrue(w[0].startswith("[wtdd:field]") and "WARN" in w[0], w[0])

    def test_under_the_flag_the_other_two_rules_stay(self):
        self.flag("1")
        one = field.check_path([[700, 700]], ROOMS)
        self.assertTrue(any("only 1 path point" in b for b in one), one)
        jump = field.check_path([[700, 700], [700 + field.MAX_STEP_PX + 50, 700]], ROOMS)
        self.assertTrue(any("px apart" in b for b in jump), jump)
        self.assertFalse(any("outside every room" in b for b in one + jump))


class Walk(NoPlan):
    def test_a_walk_the_rooms_would_refuse_runs_with_why_on_its_row(self):
        self.flag("1")
        out = field.walk(dry=True)
        self.assertEqual(out["writes"], 0)
        r = self.rows("field.walk")
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["ok"], r[0]["response_or_error"])
        self.assertEqual(r[0]["args"].get("why"), WHY)

    def test_why_is_only_on_a_call_that_would_have_refused(self):
        self.flag("1")
        self.write_map(INSIDE)
        field.walk(dry=True)
        self.assertIsNone(self.rows("field.walk")[0]["args"].get("why"))

    def test_without_the_flag_the_walk_is_refused_as_today(self):
        self.flag(None)
        with self.assertRaises(ValueError) as cm:
            field.walk(dry=True)
        self.assertIn("outside every room", str(cm.exception))
        self.assertEqual(self.rows("field.walk"), [])


class Plan(NoPlan):
    def test_under_the_flag_the_rooms_planner_refuses_with_a_row(self):
        self.flag("1")
        with self.assertRaises(Exception) as cm:
            plan.plan([200, 200], [400, 400])
        self.assertIn("no session grid under WTDD_NO_PLAN", str(cm.exception))
        r = self.rows("plan.route")
        self.assertEqual(len(r), 1, "the refusal is a row, not a silence")
        self.assertFalse(r[0]["ok"])
        self.assertIn("no session grid under WTDD_NO_PLAN", str(r[0]["response_or_error"]))

    def test_without_the_flag_it_plans_over_the_drawn_rooms_as_today(self):
        self.flag(None)
        out = plan.plan([200, 200], [400, 400])
        self.assertGreaterEqual(len(out["path"]), 2)
        self.assertTrue(self.rows("plan.route")[0]["ok"])


class Api(NoPlan):
    def test_get_map_says_no_plan_under_the_flag_only(self):
        base = self.serve()
        self.flag("1")
        code, d = self.call(base, "/map")
        self.assertEqual(code, 200, d)
        self.assertIs(d.get("no_plan"), True)
        self.flag(None)
        code, d = self.call(base, "/map")
        self.assertFalse(d.get("no_plan"), "with the flag unset nothing changes")

    def test_post_map_saves_a_path_anywhere_under_the_flag_and_refuses_it_without(self):
        self.write_map(INSIDE)
        base = self.serve()
        body = {"path": OUTSIDE, "stops": [], "rooms": ROOMS, "lights": [], "no_plan": True}   # the page sends back what GET gave
        self.flag(None)
        code, o = self.call(base, "/map", body)
        self.assertEqual(code, 400, o)
        self.assertIn("outside every room", o["error"])
        self.assertEqual(json.loads(self.map.read_text())["path"], INSIDE, "refused: the file is unchanged")
        self.flag("1")
        code, o = self.call(base, "/map", body)
        self.assertEqual(code, 200, o)
        self.assertEqual(o.get("why"), WHY)
        saved = json.loads(self.map.read_text())
        self.assertEqual(saved["path"], OUTSIDE)
        self.assertNotIn("no_plan", saved, "no_plan is the API's view, never written into the map file")

    def test_post_dog_follow_is_not_refused_on_rooms_under_the_flag(self):
        self.stack.enter_context(mock.patch.object(session, "CAL_FILE", self.tmp / "dog_cal.json"))   # absent: not calibrated, nothing connects
        self.stack.enter_context(mock.patch.object(session.DogSession, "_inst", None))
        base = self.serve()
        self.flag(None)
        code, o = self.call(base, "/dog/follow", {})
        self.assertEqual(code, 500, o)
        self.assertIn("outside every room", o["error"])
        self.flag("1")
        code, o = self.call(base, "/dog/follow", {})
        inst = session.DogSession._inst
        if inst is not None:
            inst.loop.call_soon_threadsafe(inst.loop.stop)
        self.assertEqual(code, 500, o)
        self.assertNotIn("outside every room", o["error"])
        self.assertIn("not calibrated", o["error"], "the room rule is off at this caller; the session's own refusal is next")


class Page(unittest.TestCase):
    def test_the_plan_layer_follows_no_plan_and_the_chip_is_there(self):
        html = (config.ROOT / "ui" / "index.html").read_text()
        self.assertTrue("no plan · site" in html, "the no plan · site chip is on the page")
        img = [l for l in html.splitlines() if 'href="house.svg"' in l]
        self.assertEqual(len(img), 1, img)
        self.assertIn("no_plan", img[0], "house.svg is drawn only when GET /map carries no no_plan")


if __name__ == "__main__":
    unittest.main()
