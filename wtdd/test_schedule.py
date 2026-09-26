"""Item 08, the roster and the quote, offline. Run: python -m unittest wtdd.test_schedule -v
Pins wtdd/schedule.py to its goal (goals/roadmap.md, 08). roster(map): every stop of the map exactly once, each to the
body; every fixed camera to its zone (its own `zone` when it says one, else the zone polygon its `pt` sits in, never a
`nogo` zone, never invented); the on-call name from config, refused loudly without one; one `schedule.shift` row.
quote(map, price_per_stop_night): stops x nights x price, the guard-shift figure and its citation from config (a number
Johnny enters), a quote for nothing refused; one `quote.night` row. Both rows carry the shift id in args and the result
in state_after; a refusal leaves a FAILED row. The two tools (roster, quote) sit in the registry so the CLI and the
API get them for free; the page reads both rows by their tool names from the ledger it already polls.
Nothing here touches a device: the map is a dict, the ledger a temp file, config is patched env. The page is checked by
string only; its drawing is proven by the headless screenshot in the PR (docs/evidence/night-1/08-remote.png).
"""
from __future__ import annotations
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from wtdd import config, ledger, schedule, tools

ENV = {"WTDD_ON_CALL_NAME": "Teri Test",                       # 03 defines the key; 08 reads it
       "WTDD_GUARD_SHIFT_USD": "240",                           # test fixture: not a wage, not a source
       "WTDD_GUARD_SHIFT_CITE": "test fixture, not a source",
       "WTDD_PRICE_PER_STOP_NIGHT": "10",
       "WTDD_SHIFT": "2026-09-27-test"}
SHIPPED = json.loads((config.ROOT / "ui" / "map.json").read_text())   # the shipped map; its cameras key is 09's to add


def _map(**over):
    """A five-point path with three stops, two drawn zones and one no-go zone, two cameras: one says its zone, one is
    placed by its point (inside b). cam-gate's point also sits in b, so an explicit zone is seen to win."""
    m = {"path": [[0, 0], [10, 0], [20, 0], [30, 0], [40, 0]], "stops": [1, 3, 4],
         "zones": [{"name": "a", "label": "zone a", "poly": [[0, 0], [100, 0], [100, 100], [0, 100]]},
                   {"name": "b", "label": "zone b", "poly": [[100, 0], [200, 0], [200, 100], [100, 100]]},
                   {"name": "nogo-1", "label": "no-go 1", "nogo": True, "poly": [[300, 0], [400, 0], [400, 100], [300, 100]]}],
         "cameras": [{"id": "cam-gate", "label": "gate", "pt": [150, 50], "zone": "a"},
                     {"id": "cam-yard", "label": "yard", "pt": [150, 50]}]}
    return {**m, **over}


class Base(unittest.TestCase):
    def setUp(self):
        config.maybe("WTDD_SHIFT")                                  # load <repo>/.env first (if any), so the patch below wins over it
        self._env = mock.patch.dict(os.environ, ENV)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.led = Path(tempfile.mkdtemp(prefix="wtdd-schedule-test-")) / "ledger.jsonl"
        p = mock.patch.object(ledger, "LEDGER", self.led)
        p.start()
        self.addCleanup(p.stop)

    def without(self, *keys):
        """A context in which these env keys are absent (config.get must raise)."""
        ctx = mock.patch.dict(os.environ)
        ctx.start()
        for k in keys:
            os.environ.pop(k, None)
        return ctx


class Roster(Base):
    def test_every_stop_once_to_the_body(self):
        r = schedule.roster(_map())
        self.assertEqual([s["i"] for s in r["stops"]], [1, 3, 4])           # every stop, map order, exactly once
        self.assertEqual({s["who"] for s in r["stops"]}, {"body"})
        self.assertEqual(sorted(r), ["cameras", "on_call", "shift_id", "stops"])

    def test_duplicate_stop_refused(self):
        with self.assertRaises(ValueError) as e:
            schedule.roster(_map(stops=[1, 1, 3]))
        self.assertIn("1", str(e.exception))

    def test_stop_off_the_path_refused(self):
        with self.assertRaises(ValueError) as e:
            schedule.roster(_map(stops=[1, 9]))
        self.assertIn("9", str(e.exception))

    def test_no_stops_is_an_empty_roster(self):
        self.assertEqual(schedule.roster(_map(stops=[]))["stops"], [])       # honest empty list (a WARN on stderr), not a raise

    def test_cameras_to_zones(self):
        r = schedule.roster(_map())
        self.assertEqual(r["cameras"], [{"id": "cam-gate", "zone": "a"}, {"id": "cam-yard", "zone": "b"}])

    def test_camera_in_no_zone_refused(self):
        for pt in ([999, 999], [350, 50]):                                   # outside everything; inside only the no-go zone
            with self.assertRaises(ValueError) as e:
                schedule.roster(_map(cameras=[{"id": "cam-lost", "pt": pt}]))
            self.assertIn("cam-lost", str(e.exception))

    def test_camera_naming_unknown_or_nogo_zone_refused(self):
        for zone in ("z", "nogo-1"):
            with self.assertRaises(ValueError) as e:
                schedule.roster(_map(cameras=[{"id": "cam-x", "pt": [50, 50], "zone": zone}]))
            self.assertIn("cam-x", str(e.exception))

    def test_no_cameras_key_is_no_cameras(self):
        m = {k: v for k, v in SHIPPED.items() if k != "cameras"}             # 09 owns the key: its absence is tested on a copy,
        self.assertEqual(schedule.roster(m)["cameras"], [])                  # never pinned on the shipped file; none invented
        self.assertEqual([s["i"] for s in schedule.roster(SHIPPED)["stops"]], SHIPPED["stops"])

    def test_on_call_from_config_and_loud_without(self):
        self.assertEqual(schedule.roster(_map())["on_call"], "Teri Test")
        ctx = self.without("WTDD_ON_CALL_NAME")
        try:
            with self.assertRaises(RuntimeError) as e:
                schedule.roster(_map())
            self.assertIn("WTDD_ON_CALL_NAME", str(e.exception))
        finally:
            ctx.stop()

    def test_shift_id_from_env_or_today(self):
        self.assertEqual(schedule.roster(_map())["shift_id"], "2026-09-27-test")
        ctx = self.without("WTDD_SHIFT")
        try:
            self.assertEqual(schedule.roster(_map())["shift_id"], time.strftime("%Y-%m-%d"))
        finally:
            ctx.stop()

    def test_row(self):
        r = schedule.roster(_map())
        row = ledger.rows(1)[0]
        self.assertEqual((row["tool"], row["agent"], row["ok"]), ("schedule.shift", "schedule", True))
        self.assertEqual(row["args"]["shift_id"], "2026-09-27-test")
        self.assertEqual(row["state_after"], r)
        self.assertEqual((row["cached"], row["source"]), (False, "live"))      # computed from the map, nothing stubbed
        self.assertIsInstance(row["latency_ms"], int)

    def test_refusal_leaves_a_failed_row(self):
        with self.assertRaises(ValueError):
            schedule.roster(_map(stops=[1, 1]))
        row = ledger.rows(1)[0]
        self.assertEqual((row["tool"], row["ok"]), ("schedule.shift", False))
        self.assertIn("ValueError", row["response_or_error"])


class Quote(Base):
    def test_arithmetic(self):
        q = schedule.quote(_map(), 12.5, nights=2)
        self.assertEqual((q["stops"], q["nights"], q["price"]), (3, 2, 75.0))
        q1 = schedule.quote(_map(), 19.99)
        self.assertEqual((q1["nights"], q1["price"]), (1, round(3 * 19.99, 2)))
        self.assertEqual(sorted(q1), ["guard_shift_ref", "nights", "price", "shift_id", "stops"])

    def test_guard_shift_ref_from_config_and_loud_without(self):
        q = schedule.quote(_map(), 10)
        self.assertEqual(q["guard_shift_ref"], {"value": 240.0, "cite": "test fixture, not a source"})
        for key in ("WTDD_GUARD_SHIFT_USD", "WTDD_GUARD_SHIFT_CITE"):
            ctx = self.without(key)
            try:
                with self.assertRaises(RuntimeError) as e:
                    schedule.quote(_map(), 10)
                self.assertIn(key, str(e.exception))
            finally:
                ctx.stop()

    def test_refuses_a_quote_for_nothing(self):
        with self.assertRaises(ValueError):
            schedule.quote(_map(stops=[]), 10)                               # no stops: nothing to price
        with self.assertRaises(ValueError):
            schedule.quote(_map(stops=[1, 1]), 10)                           # the same stop rule as the roster
        with self.assertRaises(ValueError):
            schedule.quote(_map(), 0)                                        # a free night is not a quote
        with self.assertRaises(ValueError):
            schedule.quote(_map(), 10, nights=0)

    def test_row(self):
        q = schedule.quote(_map(), 12.5, nights=2)
        row = ledger.rows(1)[0]
        self.assertEqual((row["tool"], row["agent"], row["ok"]), ("quote.night", "schedule", True))
        self.assertEqual(row["args"], {"shift_id": "2026-09-27-test", "price_per_stop_night": 12.5, "nights": 2})
        self.assertEqual(row["state_after"], q)
        self.assertEqual((row["cached"], row["source"]), (False, "live"))


class Tools(Base):
    """The two tools read ui/map.json and config and call the same functions: python -m wtdd roster / quote."""

    def test_registry_has_both(self):
        self.assertLessEqual({"roster", "quote"}, set(tools.registry()))

    def test_roster_tool_reads_the_map(self):
        out = tools.call("roster")
        self.assertEqual([s["i"] for s in out["stops"]], SHIPPED["stops"])
        self.assertEqual(out["on_call"], "Teri Test")
        self.assertEqual(ledger.rows(1)[0]["tool"], "schedule.shift")

    def test_quote_tool_reads_the_price_from_config(self):
        out = tools.call("quote", nights=2)
        self.assertEqual(out["price"], round(len(SHIPPED["stops"]) * 2 * 10.0, 2))
        self.assertEqual(ledger.rows(1)[0]["args"]["price_per_stop_night"], 10.0)
        ctx = self.without("WTDD_PRICE_PER_STOP_NIGHT")
        try:
            with self.assertRaises(RuntimeError) as e:
                tools.call("quote")
            self.assertIn("WTDD_PRICE_PER_STOP_NIGHT", str(e.exception))
        finally:
            ctx.stop()


class Remote(unittest.TestCase):
    """The page shows both rows under where the queue goes: one component reading them by tool name from GET /ledger,
    with a visible fail-loud line when there is none. String check only; the screenshot in the PR proves the drawing."""

    def test_page_reads_both_rows(self):
        page = (config.ROOT / "ui" / "index.html").read_text()
        for needle in ("// 08 · roster-quote · start", "// 08 · roster-quote · end", "schedule.shift", "quote.night",
                       "no roster yet", "no quote yet"):
            self.assertIn(needle, page)


if __name__ == "__main__":
    unittest.main()
