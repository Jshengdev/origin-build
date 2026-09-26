"""RED for item 26 (timeline-marks): wtdd/marks.py places a ledger row on the map, GET /marks serves every row as a
tick with its place and its age, computed server-side so the page subtracts nothing.

  python -m unittest wtdd.test_marks

Fixture rows are the dog's own, docs/evidence/ledger-sample-2026-09-13.jsonl (40 rows, 2026-09-13): ten dog.calibrate
with state_before.p (the believed pose, session.map_pose() flat) and args.p (where Johnny dragged it), dog.follow once
FAILED (row 11) and once ok, three FAILED dog.look, four dog.record (counts only: path_pts, length_px), four
lights.signal naming Hue lamps. The pose.corrected rows are synthetic, in the shape of feat/05b-localize's
localize.row() (args dx, dy in odometry metres; state_before {corr, map: {p, heading_deg} | None, grid_frames}), labelled
cached/stub, and written only to a temp file. The lamp points in MAP are copied from ui/map.json on main.
Nothing here reads or writes ledger.jsonl: GET /marks is served from a fixture through ledger.LEDGER patched per test.
UNVERIFIED on the dog: nothing here; the calibrate vector's metres against a tape on the first live calibrate.
"""
from __future__ import annotations
import copy
import json
import math
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from wtdd import api, ledger
from wtdd.config import ROOT
from wtdd.dog.nav import PX_PER_M, to_map

SAMPLE = ROOT / "docs" / "evidence" / "ledger-sample-2026-09-13.jsonl"
ROWS = [json.loads(l) for l in SAMPLE.read_text().splitlines() if l.strip()]
MARK_KEYS = {"kind", "px", "px2", "m", "pts", "why"}
ROW_KEYS = {"i", "ts", "tool", "agent", "ok", "latency_ms", "age_s", "t_s", "mark"}   # nothing the page must subtract
TOP_KEYS = {"rows", "n", "total", "span_s", "lanes"}
NO_PLACE = {"dog.look", "watch.boxes", "vision.check", "chat.correction", "intruder.verdict"}
MAP = {"path": [[449, 491], [465, 535], [483, 596]], "stops": [],
       "lights": [{"id": "1e53ff31-2dcc-496a-ad93-3cc25eb50bad", "kind": "dot", "pts": [[322, 991]]},
                  {"id": "56ecb61c-00c8-46ac-8dca-abe789ba27c3", "kind": "dot", "pts": [[596, 780]]},
                  {"id": "6c2556e3-bf37-4efd-9a04-b60ebd1b3452", "kind": "dot", "pts": [[304, 336]]}]}   # d7b0ae35 left off on purpose
CAL = {"odom": [1.0, 2.0, 0.0], "map": [400.0, 500.0], "heading": 0.0, "at": "2026-09-13T14:00:00"}


def mark(row, m=MAP, cal=None):
    from wtdd import marks   # imported per call: RED names the missing module on every placing test
    return marks.mark(row, m, cal)


def corrected(dx, dy, p=(500, 600), ts="2026-09-13T14:20:00", ok=True):
    """A pose.corrected row in 05b's localize.row() shape (synthetic, labelled stub)."""
    return {"ts": ts, "run_id": "fixture-26", "step": "pose.corrected", "agent": "dog", "tool": "pose.corrected", "app": "map",
            "args": {"dx": dx, "dy": dy, "dtheta": 0.0, "dtheta_deg": 0.0, "score": 0.82, "score0": 0.41, "n": 212,
                     "candidates": 4913, "pivot": "odom", "cap_m": 0.25, "cap_deg": 5.0, "shift_id": "2026-09-13"},
            "state_before": {"corr": {"tx": 0.0, "ty": 0.0, "theta": 0.0, "theta_deg": 0.0},
                             "map": {"p": list(p), "heading_deg": 0.0} if p else None, "grid_frames": 12},
            "state_after": None, "ok": ok, "response_or_error": None if ok else "rejected: over cap 0.25 m",
            "latency_ms": 18, "cached": True, "source": "stub"}


def near(tc, got, want, delta=0.06):
    tc.assertEqual(len(got), 2, got)
    tc.assertAlmostEqual(got[0], want[0], delta=delta, msg=f"{got} vs {want}")
    tc.assertAlmostEqual(got[1], want[1], delta=delta, msg=f"{got} vs {want}")


class Mark(unittest.TestCase):
    def test_calibrate_is_the_vector_from_belief_to_placement(self):
        for i, px, px2, m in ((7, [417, 462], [438, 515], 0.53), (0, [442, 498], [-17, 554], 4.26), (10, [412, 460], [414, 449], 0.10), (1, [442, 498], [442, 498], 0.0)):
            r = ROWS[i]
            self.assertEqual(r["tool"], "dog.calibrate")
            mk = mark(r)
            self.assertEqual((mk["kind"], mk["px"], mk["px2"]), ("vector", px, px2), i)   # ring at the placed point, arrow from the belief
            self.assertAlmostEqual(mk["m"], m, places=2, msg=i)
            self.assertLessEqual(set(mk), MARK_KEYS)

    def test_calibrate_without_a_belief_is_a_point_that_says_why(self):
        r = copy.deepcopy(ROWS[0]); r["state_before"] = None
        mk = mark(r)
        self.assertEqual((mk["kind"], mk["px"]), ("point", [442, 498]))
        self.assertNotIn("px2", mk); self.assertTrue(mk.get("why"))

    def test_follow_rings_where_it_ended_failed_or_not(self):
        for i, ok, px, px2 in ((11, False, [448, 647], [412, 460]), (30, True, [500, 563], [495, 536])):
            r = ROWS[i]
            self.assertEqual((r["tool"], r["ok"]), ("dog.follow", ok))
            mk = mark(r)
            self.assertEqual((mk["kind"], mk["px"], mk["px2"]), ("vector", px, px2), i)
            self.assertNotIn("m", mk)   # start-to-end metres would read as the distance walked: not served

    def test_lights_row_is_the_lamp_on_the_map_or_says_it_is_not_there(self):
        self.assertEqual(ROWS[32]["args"]["id"][:8], "1e53ff31")
        mk = mark(ROWS[32])
        self.assertEqual((mk["kind"], mk["px"]), ("point", [322, 991]))
        self.assertEqual(ROWS[33]["args"]["id"][:8], "d7b0ae35")
        mk = mark(ROWS[33])
        self.assertIsNone(mk["px"]); self.assertTrue(mk["why"])
        self.assertIsNone(mark({"tool": "lights.tuya_set", "agent": "lights", "args": {"on": True}, "ok": True}))   # names no light

    def test_record_is_the_saved_path_only_while_the_map_still_holds_it(self):
        r = ROWS[29]
        self.assertEqual((r["tool"], r["state_after"]["path_pts"], r["state_after"]["length_px"]), ("dog.record", 23, 1190))
        path = [[400 + 54 * k, 500] for k in range(22)] + [[400 + 54 * 21 + 56, 500]]   # 23 points, 1190 px: the row's own receipts
        mk = mark(r, {**MAP, "path": path})
        self.assertEqual((mk["kind"], mk["px"], mk["pts"]), ("path", path[0], path))
        mk = mark(r)   # the map's path is 3 points now: redrawn since, not the recorded one
        self.assertIsNone(mk["px"]); self.assertNotIn("pts", mk); self.assertTrue(mk["why"])

    def test_pose_corrected_tip_goes_through_to_map(self):
        near(self, mark(corrected(1.0, 0.0), cal=CAL)["px"], [500 + PX_PER_M, 600])   # +1 m forward along heading 0: PX_PER_M px right
        near(self, mark(corrected(0.0, 1.0), cal=CAL)["px"], [500, 600 - PX_PER_M])   # +1 m left: up on screen (y down)
        near(self, mark(corrected(1.0, 0.0), cal={**CAL, "heading": math.pi / 2})["px"], [500, 600 + PX_PER_M])
        near(self, mark(corrected(1.0, 0.0), cal={**CAL, "odom": [1.0, 2.0, math.pi / 2]})["px"], [500, 600 + PX_PER_M])   # odometry-frame delta: nav.py:38-39 too
        mk = mark(corrected(0.3, -0.4), cal=CAL)
        self.assertEqual((mk["kind"], mk["px2"]), ("vector", [500, 600]))
        self.assertAlmostEqual(mk["m"], 0.5, places=2)

    def test_pose_corrected_unplaceable_says_why(self):
        mk = mark(corrected(1.0, 0.0, p=None), cal=CAL)
        self.assertIsNone(mk["px"]); self.assertEqual(mk["why"], "no map pose on the row")
        mk = mark(corrected(1.0, 0.0), cal=None)
        self.assertIsNone(mk["px"]); self.assertTrue(mk["why"])

    def test_no_place_is_none_and_mark_is_pure(self):
        for r in ROWS:
            before = copy.deepcopy(r)
            mk = mark(r)
            self.assertEqual(r, before, f"mark() changed row {r['tool']}")
            if r["tool"] in NO_PLACE:
                self.assertIsNone(mk, r["tool"])
            else:
                self.assertIsNotNone(mk, r["tool"])


class Route(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def get(self, path, ledger_file=SAMPLE):
        with mock.patch.object(ledger, "LEDGER", Path(ledger_file)):
            try:
                with urllib.request.urlopen(self.base + path, timeout=10) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read() or b"{}")

    def test_serves_every_row_with_its_age_and_nothing_to_subtract(self):
        t0 = time.time()
        code, d = self.get("/marks?n=2000")
        self.assertEqual(code, 200, d)
        self.assertEqual(set(d), TOP_KEYS)
        self.assertEqual((d["n"], d["total"], [r["i"] for r in d["rows"]]), (40, 40, list(range(40))))
        self.assertEqual(d["lanes"], list(dict.fromkeys(r["agent"] for r in ROWS)))
        self.assertEqual((d["rows"][0]["t_s"], d["rows"][-1]["t_s"], d["span_s"]), (0, 1814, 1814))   # 13:43:51 → 14:14:05
        for s, r in zip(d["rows"], ROWS):
            self.assertEqual(set(s), ROW_KEYS)
            self.assertEqual((s["ts"], s["tool"], s["agent"], s["ok"], s["latency_ms"]), (r["ts"], r["tool"], r["agent"], r["ok"], r["latency_ms"]))
            age = t0 - time.mktime(time.strptime(r["ts"], "%Y-%m-%dT%H:%M:%S"))
            self.assertAlmostEqual(s["age_s"], age, delta=3)
            self.assertTrue(s["mark"] is None or set(s["mark"]) <= MARK_KEYS, s["mark"])

    def test_failed_rows_carry_ok_false_and_their_place(self):
        code, d = self.get("/marks")   # n defaults to 2000
        self.assertEqual(code, 200, d)
        failed = [s for s in d["rows"] if s["ok"] is False]
        self.assertEqual(sorted(s["tool"] for s in failed), ["dog.follow", "dog.look", "dog.look", "dog.look"])
        follow = next(s for s in failed if s["tool"] == "dog.follow")
        self.assertEqual((follow["i"], follow["mark"]["px"], follow["mark"]["px2"]), (11, [448, 647], [412, 460]))
        cal7 = d["rows"][7]["mark"]
        self.assertEqual((cal7["kind"], cal7["px"], cal7["px2"], round(cal7["m"], 2)), ("vector", [417, 462], [438, 515], 0.53))

    def test_window_keeps_ledger_indices_and_parses_once(self):
        with mock.patch.object(api, "rows", wraps=api.rows) as spy:
            code, d = self.get("/marks?n=5")
        self.assertEqual(code, 200, d)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual((d["n"], d["total"], [s["i"] for s in d["rows"]]), (5, 40, [35, 36, 37, 38, 39]))
        self.assertEqual((d["rows"][0]["t_s"], d["span_s"]), (0, 371))   # 14:07:54 → 14:14:05

    def test_pose_corrected_is_drawn_through_the_calibration_in_force(self):
        calib = ROWS[0]   # dog.calibrate 13:43:51, state_after.cal is the tie in force after it
        rows = [corrected(0.10, -0.05, p=(442, 498), ts="2026-09-13T13:43:00"), calib,
                corrected(0.10, -0.05, p=(442, 498), ts="2026-09-13T13:44:00"),
                corrected(0.35, 0.0, p=(442, 498), ts="2026-09-13T13:44:05", ok=False)]
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "ledger.jsonl"
            f.write_text("".join(json.dumps(r) + "\n" for r in rows))
            code, d = self.get("/marks", f)
        self.assertEqual(code, 200, d)
        before, _, after, rejected = (s["mark"] for s in d["rows"])
        self.assertIsNone(before["px"]); self.assertTrue(before["why"])   # no calibration before it in the ledger
        cal = calib["state_after"]["cal"]
        ox, oy, oyaw = cal["odom"]
        tx, ty, _ = to_map(cal, (ox + 0.10, oy - 0.05), oyaw)
        near(self, after["px"], [442 + tx - cal["map"][0], 498 + ty - cal["map"][1]])
        self.assertEqual(after["px2"], [442, 498]); self.assertAlmostEqual(after["m"], 0.11, places=2)
        self.assertIs(d["rows"][3]["ok"], False); self.assertIsNotNone(rejected["px"])   # a rejected correction is a red mark, still placed


if __name__ == "__main__":
    unittest.main()
