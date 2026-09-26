"""The verifying command of roadmap item 05a: python -m unittest wtdd.dog.test_drift. No dog; the real ledger is untouched.

Checks wtdd/dog/drift.py on fixtures/pose_rows.jsonl (planted drift, made by fixtures/make_pose_rows.py): the pose
source the follower uses is chosen by env WTDD_POSE_SOURCE (default sport, anything else refused); a rt/utlidar/
robot_pose message parses to x, y, yaw or is refused loud; a pose.sample row has the contract's fields
{source, x, y, yaw} in args (plus shift_id) and its map projection in state_after; the report measures each source's
end error per walk from where the dog actually stood (the drag after the walk, refused loud when the dog moved before it
or when it came past DRAG_WINDOW_S) or, without one, from the taught route end, says which, names who drove, and names
the lower-drift source from the drag-referenced walks only (none when there is none); a ledger without pose.sample rows
fails loud. Session drives the real wtdd/dog/session.py (calibrate, follow, _follow, _sample_poses,
state) with FakeBody in place of the dog on a three-waypoint route: both ties on the drag row, both poses on every
follow, the driver and the counts on the follow row, a silent utlidar as a zero and a WARN, a refused drag as a row.
WTDD_LEDGER and session.CAL_FILE are pointed at a scratch dir before anything runs, so nothing real is written."""
from __future__ import annotations
import contextlib
import io
import json
import math
import os
import tempfile
import time
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="wtdd-drift-test-")
os.environ["WTDD_LEDGER"] = str(Path(_TMP) / "ledger.jsonl")

from wtdd import ledger  # noqa: E402
from wtdd.dog import drift, nav, session  # noqa: E402
from wtdd.dog.fixtures import make_pose_rows as gen  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "pose_rows.jsonl"
ROUTE = Path(__file__).resolve().parents[2] / "ui" / "route-saved.json"
ROUTE_END = json.loads(ROUTE.read_text())["path"][-1]   # [436, 586], the taught route's end
ROUTE_START = json.loads(ROUTE.read_text())["path"][0]  # [448, 455]
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

    def test_each_follow_rows_sample_count_matches_its_rows(self):
        # state_after.samples is a receipt: the pose.sample rows of each source since the previous dog.follow row
        seen, walks = {s: 0 for s in drift.SOURCES}, 0
        for r in _rows():
            if r["tool"] == "pose.sample":
                seen[r["args"]["source"]] += 1
            elif r["tool"] == "dog.follow":
                walks += 1
                self.assertEqual(r["state_after"]["samples"], seen, f"walk {walks}")
                seen = {s: 0 for s in drift.SOURCES}
        self.assertEqual(walks, len(gen.DROVE))


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
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rep = drift.report(rows, ROUTE_END)
        self.assertEqual({w["truth"] for w in rep["walks"]}, {"route end"})
        for w in rep["walks"]:
            self.assertLessEqual(w["end"][w["drove"]]["err_m"], REACH_M + 0.01)   # the driver stopped where it believed the end was
        self.assertEqual(rep["route_end"], ROUTE_END)
        # a route-end number is a belief, not a drift: printed per walk, never summarized, and no source is named
        self.assertIsNone(rep["lower"])
        self.assertEqual(rep["sources"]["sport"]["n"], 0)
        self.assertEqual(rep["sources"]["utlidar"]["n"], 0)
        self.assertEqual(rep["n_drag"], 0)
        self.assertIn("WARN no lower-drift source: no walk has a drag after it", err.getvalue())
        self.assertIn("lower-drift source: none", drift.format(rep))

    def test_a_late_drag_is_not_the_walks_reference_and_says_so(self):
        # Every truth drag made 200 s after its walk (past DRAG_WINDOW_S), the dog not moved in between: the drag is refused
        # as a reference, and it says so, so "you dragged too late" is not silent like "you never dragged".
        rows, follow_t = [], None
        for r in _rows():
            if r["tool"] == "dog.calibrate" and r["state_before"] is not None:
                r = {**r, "ts": time.strftime(drift.TS, time.localtime(follow_t + 200))}
            if r["tool"] == "dog.follow":
                follow_t = drift._t(r)
            rows.append(r)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rep = drift.report(rows, ROUTE_END)
        self.assertEqual([w["truth"] for w in rep["walks"]], ["route end"] * len(gen.DROVE))
        self.assertEqual(err.getvalue().count("past DRAG_WINDOW_S"), len(gen.DROVE), err.getvalue())
        self.assertIn("WARN walk 1: the first drag came 200 s after the walk", err.getvalue())
        self.assertIsNone(rep["lower"])

    def test_a_drag_after_the_dog_moved_is_not_the_walks_reference(self):
        # The truth drag skipped; the dog hand-driven back to the start and dragged there 30 s after the walk (inside
        # DRAG_WINDOW_S) for the next replay. That drag is the next walk's start, not this walk's end: read as the end it
        # would report the start-to-end distance as drift. It is refused, loud, and the walk falls back to the route end.
        rows, follow_t = [], None
        for r in _rows():
            if r["tool"] == "dog.calibrate" and r["state_before"] is not None:
                continue
            if r["tool"] == "dog.calibrate" and follow_t is not None:
                r = {**r, "ts": time.strftime(drift.TS, time.localtime(follow_t + 30)),
                     "state_before": {"p": list(ROUTE_START), "heading_deg": r["args"]["heading_deg"]}}
                follow_t = None
            if r["tool"] == "dog.follow":
                follow_t = drift._t(r)
            rows.append(r)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rep = drift.report(rows, ROUTE_END)
        self.assertEqual([w["truth"] for w in rep["walks"]], ["route end"] * len(gen.DROVE))
        self.assertEqual(err.getvalue().count("not this walk's reference"), len(gen.DROVE) - 1, err.getvalue())   # walk 6 has no drag after it
        self.assertIn("WARN walk 1", err.getvalue())

    def test_a_drag_without_the_belief_at_the_drag_is_not_trusted(self):
        rows = [{**r, "state_before": None} if r["tool"] == "dog.calibrate" else r for r in _rows()]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rep = drift.report(rows, ROUTE_END)
        self.assertEqual({w["truth"] for w in rep["walks"]}, {"route end"})
        self.assertIn("WARN walk 1", err.getvalue())

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


PATH = [[448, 455], [448, 500], [448, 545]]   # three waypoints straight down the map, 45 px apart: a walk under a second
H0 = nav.heading_of(PATH[0], PATH[1])


class FakeBody:
    """The part of wtdd/dog/body.Body that DogSession's calibrate, follow, _follow and _halt call, without a dog. A true
    pose integrated from the session's velocity (FAST x real time); the sport odometry is that pose from power-on, the
    utlidar pose is the same motion in a rotated, offset frame (its own tie absorbs that), or silent (ut=False)."""
    FAST = 5.0

    def __init__(self, sess, ut: bool = True):
        self.sess, self.ut, self._avoid = sess, ut, True
        self.x = self.y = self.th = 0.0
        self.t = time.monotonic()

    def state(self) -> dict:
        now = time.monotonic()
        dt, self.t = (now - self.t) * self.FAST, now
        vx, _, wz = self.sess.vel
        self.th += wz * dt
        self.x, self.y = self.x + vx * dt * math.cos(self.th), self.y + vx * dt * math.sin(self.th)
        a = 0.7
        ut = {"x": 1.3 + self.x * math.cos(a) - self.y * math.sin(a), "y": -0.4 + self.x * math.sin(a) + self.y * math.cos(a),
              "yaw": nav.wrap(self.th + a), "n": 1, "age_ms": 20} if self.ut else None
        return {"position": [self.x, self.y, 0.3], "rpy": [0.0, 0.0, self.th], "velocity": [0.0, 0.0, 0.0], "n": 1, "age_ms": 10,
                "utpose": ut, "utpose_errors": 0}

    async def fresh_state(self, required: bool = False) -> dict:
        return self.state()

    async def cmd(self, name: str, parameter=None) -> int:
        return 0

    async def _tick(self, kind: str, x: float, y: float, z: float) -> None:
        return None


class Session(unittest.TestCase):
    def setUp(self):
        self._had = os.environ.pop("WTDD_POSE_SOURCE", None)
        self._cal_file = session.CAL_FILE
        session.CAL_FILE = Path(_TMP) / "dog_cal.json"
        session.CAL_FILE.unlink(missing_ok=True)

    def tearDown(self):
        session.CAL_FILE = self._cal_file
        os.environ.pop("WTDD_POSE_SOURCE", None)
        if self._had is not None:
            os.environ["WTDD_POSE_SOURCE"] = self._had

    def _session(self, source: str, ut: bool = True) -> "session.DogSession":
        os.environ["WTDD_POSE_SOURCE"] = source
        session.CAL_FILE.unlink(missing_ok=True)   # each session starts untied
        s = session.DogSession()
        s.body = FakeBody(s, ut)
        self.addCleanup(s.loop.call_soon_threadsafe, s.loop.stop)
        return s

    def _walk(self, s) -> list[dict]:
        n0 = len(ledger.rows())
        s.follow(PATH, [], reach_px=30.0)
        s._follower.result(10)
        return ledger.rows()[n0:]

    def test_the_drag_ties_both_sources_and_puts_both_on_its_row(self):
        s = self._session("sport")
        n0 = len(ledger.rows())
        s.calibrate(PATH[0], H0)
        row = [r for r in ledger.rows()[n0:] if r["tool"] == "dog.calibrate"][-1]
        self.assertIs(row["ok"], True)
        self.assertEqual(sorted(row["state_after"]["cals"]), sorted(drift.SOURCES))
        self.assertEqual(row["state_after"]["cal"]["odom"], row["state_after"]["cals"]["sport"]["odom"])   # cal keeps the sport tie
        self.assertEqual(sorted(json.loads(session.CAL_FILE.read_text())["cals"]), sorted(drift.SOURCES))
        st = s.state()
        self.assertEqual((st["pose_source"], st["calibrated"]), ("sport", True))
        for src in drift.SOURCES:
            self.assertEqual(st["poses"][src]["p"], PATH[0], src)

    def test_a_follow_on_either_source_records_both_poses_and_names_its_driver(self):
        for src in drift.SOURCES:
            with self.subTest(source=src):
                s = self._session(src)
                s.calibrate(PATH[0], H0)
                rows = self._walk(s)
                fol = [r for r in rows if r["tool"] == "dog.follow"]
                self.assertEqual(len(fol), 1)
                fol = fol[0]
                self.assertIs(fol["ok"], True, fol["response_or_error"])
                self.assertEqual(fol["args"]["pose_source"], src)
                self.assertEqual(fol["state_after"]["reached"], [0, 1, 2])
                samples = [r for r in rows if r["tool"] == "pose.sample"]
                counts = {x: sum(r["args"]["source"] == x for r in samples) for x in drift.SOURCES}
                self.assertEqual(fol["state_after"]["samples"], counts)
                for r in samples:
                    self.assertEqual(sorted(r["args"]), ["shift_id", "source", "x", "y", "yaw"])
                    self.assertIsNotNone(r["state_after"]["map"], r)
                ends = {r["args"]["source"]: r["state_after"]["map"]["p"] for r in rows[rows.index(fol) - 2:rows.index(fol)]}
                self.assertEqual(sorted(ends), sorted(drift.SOURCES))   # the last sample of each source lands right before the follow row
                self.assertLessEqual(math.dist(ends[src], PATH[-1]), 30.0)   # the driver stopped inside reach of the end
                self.assertLessEqual(math.dist(ends["sport"], ends["utlidar"]), 2.0)   # no drift in FakeBody: each tie projects the same spot

    def test_a_silent_utlidar_is_a_zero_on_the_follow_row_and_a_warn(self):
        s = self._session("sport", ut=False)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            s.calibrate(PATH[0], H0)
            rows = self._walk(s)
        self.assertIn("WARN no utlidar pose at this drag", err.getvalue())
        fol = [r for r in rows if r["tool"] == "dog.follow"][0]
        self.assertIs(fol["ok"], True, fol["response_or_error"])
        self.assertEqual(fol["state_after"]["samples"]["utlidar"], 0)
        self.assertGreater(fol["state_after"]["samples"]["sport"], 0)
        self.assertIn("WARN 0 utlidar pose samples on this walk", err.getvalue())
        self.assertFalse([r for r in rows if r["tool"] == "pose.sample" and r["args"]["source"] == "utlidar"])

    def test_utlidar_selected_without_a_utlidar_pose_is_a_failed_drag_row_and_no_follow(self):
        s = self._session("utlidar", ut=False)
        n0 = len(ledger.rows())
        with self.assertRaises(RuntimeError):
            s.calibrate(PATH[0], H0)
        row = [r for r in ledger.rows()[n0:] if r["tool"] == "dog.calibrate"][-1]
        self.assertIs(row["ok"], False)
        self.assertIn("no utlidar pose", row["response_or_error"])
        with self.assertRaises(RuntimeError) as cm:
            s.follow(PATH, [], reach_px=30.0)
        self.assertIn("not calibrated for utlidar", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
