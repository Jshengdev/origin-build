"""S5 · the map scale (pixels per metre on house.svg) is a measured setting, WTDD_PX_PER_M, not a hand guess in code.

Before S5, wtdd/dog/nav.py fixed PX_PER_M = 108.5 from "the bottom living room is 445 px wide and 4.1 m", and every
metre-to-pixel conversion (the dog, the grid, the floor plan, routes, pins) went through it. S5 reads the measured
value at import; a missing key keeps 108.5; a value that is not a number, or outside 20..400, stops the import loud.
S5b · Johnny: "rescale the 2d to match the bounds of the 3d with a manually scale feature". The page's slider sets the
scale while the API runs: nav.set_scale (every conversion follows at once), DogSession.scale (one dog.scale row, saved
beside the tie in dog_cal.json), and a fresh session takes the saved value over WTDD_PX_PER_M.
  python -m unittest wtdd.dog.test_scale
"""
import importlib
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from .. import config, ledger
from . import nav, session

TIE = {"odom": [0.1, 0.2, 0.3], "map": [449.0, 491.0], "heading": 1.5708, "at": "2026-09-27T03:00:00"}   # nav.calibration's shape


def reload_with(value):
    env = {k: v for k, v in os.environ.items() if k != "WTDD_PX_PER_M"}
    if value is not None:
        env["WTDD_PX_PER_M"] = value
    with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(config, "_loaded", True):
        return importlib.reload(nav).PX_PER_M


class Scale(unittest.TestCase):
    def tearDown(self):
        reload_with(None)   # leave nav at the default for every other test in the process

    def test_the_default_is_the_old_guess(self):
        self.assertEqual(reload_with(None), 108.5)

    def test_a_measured_scale_is_used(self):
        self.assertEqual(reload_with("103.4"), 103.4)

    def test_every_conversion_follows_it(self):
        reload_with("100")
        cal = nav.calibration([0.0, 0.0, 0.0], 0.0, [500.0, 500.0], 0.0)
        px, py, _ = nav.to_map(cal, [1.0, 0.0, 0.0], 0.0)   # one metre forward, heading 0 = +x on screen
        self.assertAlmostEqual(px - 500.0, 100.0, places=6)

    def test_a_scale_that_is_not_a_number_stops_loud(self):
        with self.assertRaisesRegex(ValueError, "WTDD_PX_PER_M"):
            reload_with("108,5")

    def test_a_scale_outside_twenty_to_four_hundred_stops_loud(self):
        for bad in ("0", "-5", "5000"):
            with self.assertRaisesRegex(ValueError, "WTDD_PX_PER_M", msg=bad):
                reload_with(bad)


class SetScale(unittest.TestCase):
    """nav.set_scale(v, source): 20..400 or a ValueError naming the value; every reader follows at once."""

    def setUp(self):
        self.enterContext(mock.patch.object(nav, "PX_PER_M", nav.PX_PER_M))   # restored after, whatever set_scale did
        self.enterContext(mock.patch.object(nav, "SCALE_SOURCE", "test", create=True))

    def test_to_map_follows_a_set_at_once(self):
        cal = nav.calibration([0.0, 0.0, 0.0], 0.0, [500.0, 500.0], 0.0)
        nav.set_scale(100, "test")
        self.assertAlmostEqual(nav.to_map(cal, [1.0, 0.0, 0.0], 0.0)[0] - 500.0, 100.0, places=6)
        nav.set_scale(150.5, "test")
        self.assertAlmostEqual(nav.to_map(cal, [1.0, 0.0, 0.0], 0.0)[0] - 500.0, 150.5, places=6)
        self.assertEqual((nav.PX_PER_M, nav.SCALE_SOURCE), (150.5, "test"))

    def test_a_set_out_of_range_raises_naming_it_and_leaves_the_scale(self):
        nav.set_scale(100, "before")
        for bad in (19.9, 400.5, "abc", None, float("nan")):
            with self.assertRaisesRegex(ValueError, str(bad), msg=bad):
                nav.set_scale(bad, "page")
            self.assertEqual((nav.PX_PER_M, nav.SCALE_SOURCE), (100.0, "before"), bad)


def stop(s) -> None:
    s.loop.call_soon_threadsafe(s.loop.stop)
    while s.loop.is_running():
        time.sleep(0.01)
    s.loop.close()


class SessionScale(unittest.TestCase):
    """DogSession.scale: a read is {px_per_m, source} and no row; a set is one dog.scale row and dog_cal.json keeps it
    beside the tie; a fresh session loads it over WTDD_PX_PER_M. The ledger and the calibration file are temp files."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.object(ledger, "LEDGER", self.tmp / "ledger.jsonl"))
        self.cal_file = self.tmp / "dog_cal.json"
        self.enterContext(mock.patch.object(session, "CAL_FILE", self.cal_file))
        self.enterContext(mock.patch.object(session, "GRID_FILE", self.tmp / "grid.json"))
        self.enterContext(mock.patch.object(nav, "PX_PER_M", nav.PX_PER_M))
        self.enterContext(mock.patch.object(nav, "SCALE_SOURCE", getattr(nav, "SCALE_SOURCE", None), create=True))
        self.err = self.enterContext(redirect_stderr(io.StringIO()))

    def fresh(self) -> "session.DogSession":
        s = session.DogSession()
        self.addCleanup(stop, s)
        return s

    def test_a_set_is_one_row_with_before_and_after_and_is_saved_beside_the_tie(self):
        self.cal_file.write_text(json.dumps(TIE))
        s = self.fresh()
        was = nav.PX_PER_M
        self.assertEqual(ledger.rows(), [], "a read is not a step")
        out = s.scale(103.4)
        rows = [r for r in ledger.rows() if r["tool"] == "dog.scale"]
        self.assertEqual(len(rows), 1, ledger.rows())
        r = rows[0]
        self.assertEqual((r["agent"], r["app"], r["ok"]), ("dog", "map", True), r)
        self.assertEqual(r["args"], {"px_per_m": 103.4, "source": "page"})
        self.assertEqual(r["state_before"]["px_per_m"], was)
        self.assertEqual(r["state_after"]["px_per_m"], 103.4)
        self.assertEqual(out["px_per_m"], 103.4)
        self.assertEqual(s.scale(), {"px_per_m": 103.4, "source": "page"})
        self.assertEqual(json.loads(self.cal_file.read_text()), {**TIE, "px_per_m": 103.4}, "the tie is kept, the scale sits beside it")
        self.assertNotIn("px_per_m", s.cal, "the tie in memory stays nav.calibration's shape")
        st = {"position": [0.4, 0.2, 0.0], "rpy": [0.0, 0.0, 0.3], "age_ms": 0, "n": 1}
        with mock.patch.object(s, "run", return_value=st):
            s.calibrate((300.0, 900.0), 0.0)
        self.assertEqual(json.loads(self.cal_file.read_text())["px_per_m"], 103.4, "a new tie keeps the scale set from the page")

    def test_a_bad_set_is_one_failed_row_and_changes_nothing(self):
        self.cal_file.write_text(json.dumps(TIE))
        s = self.fresh()
        was, before = nav.PX_PER_M, self.cal_file.read_text()
        with self.assertRaisesRegex(ValueError, "500"):
            s.scale(500)
        rows = [r for r in ledger.rows() if r["tool"] == "dog.scale"]
        self.assertEqual([r["ok"] for r in rows], [False], ledger.rows())
        self.assertIn("500", rows[0]["response_or_error"])
        self.assertEqual(rows[0]["state_before"]["px_per_m"], was)
        self.assertEqual(nav.PX_PER_M, was)
        self.assertEqual(self.cal_file.read_text(), before, "nothing saved")

    def test_a_fresh_session_takes_the_saved_scale_over_the_env(self):
        reload_with("100")
        self.cal_file.write_text(json.dumps({**TIE, "px_per_m": 103.4}))
        s = self.fresh()
        self.assertEqual(s.scale(), {"px_per_m": 103.4, "source": "dog_cal.json"})
        self.assertIn("scale 103.4 px/m from dog_cal.json", self.err.getvalue())
        self.assertEqual(s.cal, TIE, "the tie loads as before")

    def test_a_saved_scale_out_of_range_is_ignored_loud(self):
        reload_with("100")
        self.cal_file.write_text(json.dumps({**TIE, "px_per_m": 5000}))
        s = self.fresh()
        self.assertEqual(s.scale(), {"px_per_m": 100.0, "source": "WTDD_PX_PER_M"})
        self.assertIn("WARN", self.err.getvalue())
        self.assertIn("5000", self.err.getvalue())
        self.assertEqual(s.cal, TIE)

    def test_a_scale_saved_before_any_tie_loads_without_one(self):
        self.cal_file.write_text(json.dumps({"px_per_m": 120.0}))
        s = self.fresh()
        self.assertEqual(s.scale(), {"px_per_m": 120.0, "source": "dog_cal.json"})
        self.assertIsNone(s.cal, "a file holding only the scale is not a calibration")
        self.assertFalse(s.recheck)


if __name__ == "__main__":
    unittest.main()
