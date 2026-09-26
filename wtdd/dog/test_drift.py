"""The verifying command of roadmap item 05a: python -m unittest wtdd.dog.test_drift. No dog, no ledger writes.

Checks wtdd/dog/drift.py on fixtures/pose_rows.jsonl (planted drift, made by fixtures/make_pose_rows.py): the pose
source the follower uses is chosen by env WTDD_POSE_SOURCE (default sport, anything else refused); a rt/utlidar/
robot_pose message parses to x, y, yaw or is refused loud; a pose.sample row has the contract's fields
{source, x, y, yaw} in args (plus shift_id) and its map projection in state_after; the report measures each source's
end error per walk from where the dog actually stood (the drag after the walk) or, without one, from the taught route
end, says which, names who drove, and names the lower-drift source; a ledger without pose.sample rows fails loud.
WTDD_LEDGER is pointed at a scratch file before anything is imported, so the real ledger is never touched."""
from __future__ import annotations
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="wtdd-drift-test-")
os.environ["WTDD_LEDGER"] = str(Path(_TMP) / "ledger.jsonl")

from wtdd.dog import drift, nav  # noqa: E402
from wtdd.dog.fixtures import make_pose_rows as gen  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "pose_rows.jsonl"
ROUTE = Path(__file__).resolve().parents[2] / "ui" / "route-saved.json"
ROUTE_END = json.loads(ROUTE.read_text())["path"][-1]   # [436, 586], the taught route's end
REACH_M = 30.0 / nav.PX_PER_M                            # the follower's reach_px in metres: the driver's own end error is under this


def _rows() -> list[dict]:
    return drift.load(FIX)


class Fixture(unittest.TestCase):
    def test_matches_its_generator(self):
        self.assertEqual(FIX.read_text(), gen.text(), "pose_rows.jsonl is stale: python -m wtdd.dog.fixtures.make_pose_rows")

    def test_rows_are_labeled_fixture_and_samples_carry_the_contract_fields(self):
        rows = _rows()
        self.assertTrue(rows)
        for r in rows:
            self.assertIs(r["cached"], True)
            self.assertEqual(r["source"], "fixture")   # the ledger's live/stub label, never "live"
        samples = [r for r in rows if r["tool"] == "pose.sample"]
        self.assertGreater(len(samples), 0)
        for r in samples:
            self.assertEqual(r["step"], "pose.sample")
            self.assertIn(r["args"]["source"], drift.SOURCES)
            for k in ("x", "y", "yaw"):
                self.assertIsInstance(r["args"][k], float)
            self.assertEqual(r["args"]["shift_id"], gen.SHIFT_ID)
        self.assertEqual({r["args"]["source"] for r in samples}, set(drift.SOURCES))


class Select(unittest.TestCase):
    def setUp(self):
        self._had = os.environ.pop("WTDD_POSE_SOURCE", None)

    def tearDown(self):
        os.environ.pop("WTDD_POSE_SOURCE", None)
        if self._had is not None:
            os.environ["WTDD_POSE_SOURCE"] = self._had

    def test_default_is_the_shipped_sport_odometry(self):
        self.assertEqual(drift.selected_source(), "sport")

    def test_env_switches_the_follower_to_utlidar(self):
        os.environ["WTDD_POSE_SOURCE"] = "utlidar"
        self.assertEqual(drift.selected_source(), "utlidar")

    def test_unknown_source_is_refused(self):
        os.environ["WTDD_POSE_SOURCE"] = "gps"
        with self.assertRaises(RuntimeError) as cm:
            drift.selected_source()
        self.assertIn("gps", str(cm.exception))
        self.assertIn("WTDD_POSE_SOURCE", str(cm.exception))


class Parse(unittest.TestCase):
    def test_pose_stamped_shape_gives_x_y_yaw(self):
        import math
        th = 0.8
        msg = {"header": {"stamp": {"sec": 1, "nanosec": 0}, "frame_id": "odom"},
               "pose": {"position": {"x": 1.5, "y": -2.0, "z": 0.3},
                        "orientation": {"x": 0.0, "y": 0.0, "z": math.sin(th / 2), "w": math.cos(th / 2)}}}
        x, y, yaw = drift.utpose_xyyaw(msg)
        self.assertAlmostEqual(x, 1.5)
        self.assertAlmostEqual(y, -2.0)
        self.assertAlmostEqual(yaw, th, places=9)

    def test_unknown_shape_is_refused_naming_its_keys(self):
        with self.assertRaises(ValueError) as cm:
            drift.utpose_xyyaw({"foo": 1, "bar": 2})
        self.assertIn("foo", str(cm.exception))
        with self.assertRaises(ValueError):
            drift.utpose_xyyaw(None)


class Sample(unittest.TestCase):
    CAL = {"odom": [-0.25, 2.52, 0.015], "map": [448.0, 455.0], "heading": 1.6461252176232368}

    def test_row_shape_and_map_projection(self):
        r = drift.sample("utlidar", 1.0, 2.0, 0.5, self.CAL, "2026-09-26")
        self.assertEqual((r["step"], r["tool"], r["agent"], r["app"]), ("pose.sample", "pose.sample", "dog", "map"))
        self.assertEqual(r["args"], {"source": "utlidar", "x": 1.0, "y": 2.0, "yaw": 0.5, "shift_id": "2026-09-26"})
        px, py, h = nav.to_map(self.CAL, (1.0, 2.0), 0.5)
        self.assertEqual(r["state_after"]["map"]["p"], [round(px), round(py)])
        self.assertEqual(r["state_after"]["map"]["heading_deg"], round(__import__("math").degrees(h), 1))
        self.assertIs(r["ok"], True)

    def test_uncalibrated_source_says_so_on_the_row(self):
        r = drift.sample("sport", 1.0, 2.0, 0.5, None, "2026-09-26")
        self.assertIsNone(r["state_after"]["map"])
        self.assertIn("why", r["state_after"])

    def test_unknown_source_is_refused(self):
        with self.assertRaises(ValueError):
            drift.sample("gps", 1.0, 2.0, 0.5, self.CAL, "2026-09-26")


class Report(unittest.TestCase):
    def test_names_the_lower_drift_source(self):
        rep = drift.report(_rows(), ROUTE_END)
        self.assertEqual(rep["lower"], "utlidar")
        self.assertEqual(len(rep["walks"]), len(gen.DROVE))
        self.assertEqual(rep["sources"]["sport"]["n"], len(gen.DROVE))
        self.assertEqual(rep["sources"]["utlidar"]["n"], len(gen.DROVE))
        self.assertLess(rep["sources"]["utlidar"]["mean_m"], rep["sources"]["sport"]["mean_m"])

    def test_end_error_per_source_is_the_planted_drift(self):
        rep = drift.report(_rows(), ROUTE_END)
        for k, w in enumerate(rep["walks"]):
            self.assertAlmostEqual(w["end"]["sport"]["err_m"], gen.SPORT_M[k], delta=0.02, msg=f"walk {k + 1} sport")
            self.assertAlmostEqual(w["end"]["utlidar"]["err_m"], gen.UTLIDAR_M[k], delta=0.02, msg=f"walk {k + 1} utlidar")
        self.assertAlmostEqual(rep["sources"]["sport"]["mean_m"], sum(gen.SPORT_M) / len(gen.SPORT_M), delta=0.02)
        self.assertAlmostEqual(rep["sources"]["utlidar"]["mean_m"], sum(gen.UTLIDAR_M) / len(gen.UTLIDAR_M), delta=0.02)

    def test_each_walk_names_who_drove_and_where_the_truth_came_from(self):
        rep = drift.report(_rows(), ROUTE_END)
        self.assertEqual([w["drove"] for w in rep["walks"]], gen.DROVE)
        self.assertEqual({w["truth"] for w in rep["walks"]}, {"drag"})
        for w in rep["walks"]:
            self.assertEqual(w["reached"], w["of"])

    def test_without_a_drag_the_reference_is_the_route_end_and_the_driver_only_reports_its_own_belief(self):
        rows = [r for r in _rows() if not (r["tool"] == "dog.calibrate" and r["state_before"] is not None)]   # keep the start drags, drop the truth drags
        rep = drift.report(rows, ROUTE_END)
        self.assertEqual({w["truth"] for w in rep["walks"]}, {"route end"})
        for w in rep["walks"]:
            self.assertLessEqual(w["end"][w["drove"]]["err_m"], REACH_M + 0.01)   # the driver stopped where it believed the end was
        self.assertEqual(rep["route_end"], ROUTE_END)

    def test_no_pose_samples_fails_loud(self):
        rows = [r for r in _rows() if r["tool"] != "pose.sample"]
        with self.assertRaises(RuntimeError) as cm:
            drift.report(rows, ROUTE_END)
        self.assertIn("pose.sample", str(cm.exception))


class Cli(unittest.TestCase):
    def test_prints_the_lower_drift_source(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = drift.main(["--ledger", str(FIX), "--route", str(ROUTE)])
        self.assertEqual(rc, 0, err.getvalue())
        text = out.getvalue()
        self.assertIn("lower-drift source: utlidar", text)
        self.assertIn("sport", text)
        self.assertIn("walks=6", err.getvalue())   # the one stderr line with counts

    def test_a_ledger_without_samples_exits_nonzero_with_a_warn(self):
        p = Path(_TMP) / "no-samples.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in _rows() if r["tool"] != "pose.sample"))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = drift.main(["--ledger", str(p), "--route", str(ROUTE)])
        self.assertNotEqual(rc, 0)
        self.assertIn("WARN", err.getvalue())
        self.assertIn("pose.sample", err.getvalue())


if __name__ == "__main__":
    unittest.main()
