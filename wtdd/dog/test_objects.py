"""Tests for wtdd/dog/objects.py: detector boxes placed on the map at the nearest LiDAR blob along their bearing,
an object store with a drafted line and a thumbnail per object, decay to stale, and the replay PNG. Everything runs
on the synthetic fixtures under wtdd/dog/fixtures/ (voxel_frames.npz for the grid, frame.jpg + watch-frame.json for
the detector, objects.json for the page); nothing here has seen the real dog, a detector or a model. Run:

    python -m unittest wtdd.dog.test_objects

RED until objects.py exists. Expectations are computed from the fixtures' declared world (make_voxel_frames.py's
WALL_A at x = 2.0 m, its BLOB at (0.0, -1.0) seen once; make_objects_fixture.py's two boxes at a stated pose and
field of view), never from the module's own output; map pixels go through occupancy.to_map_px, which 01 proved
pixel-for-pixel against nav.to_map.

The contract under test (wtdd/dog/objects.py):
  bearing(xyxy, frame_w, fov_deg)      radians, right of the optical axis positive, pinhole: atan((u/W - 1/2) * 2 tan(fov/2))
                                       for the box centre u; fov outside (0, 180) is a ValueError
  nearest_blob(grid, xy_m, angle_rad, threshold=occupancy.THRESHOLD, max_range_m=MAX_RANGE_M)
                                       the first grid cell seen >= threshold times along the ray from xy_m (odometry
                                       metres) at angle_rad (odometry yaw convention: counter-clockwise positive), as
                                       {xy (the cell's lattice point, metres), dist_m, count}; None when the ray meets
                                       nothing within max_range_m. The right of the camera is a NEGATIVE odometry angle.
  thumb(file, xyxy, width=THUMB_PX)    the box cropped from the frame as "data:image/jpeg;base64,...", at most width px wide
  Store(append=ledger.append, draft=draft_live, decide=None, stale_windows=STALE_WINDOWS)
    .observe(frame, pose, grid, cal, fov_deg, threshold=occupancy.THRESHOLD) -> {new, seen, stale, unplaced: [ids]}
                                       one detector window (a watch.json dict: boxes [{name, conf, xyxy}], file, t);
                                       pose {position: [x, y], yaw} in odometry or None; an object is matched by label
                                       and a pin within MATCH_PX, else it is new with the next id "o<n>"; a box with no
                                       pose, no grid, or no blob along its bearing is stored unplaced (pos_px None, why)
    .draft() -> id | None              drafts the one-line message for the oldest object without one (at most one per
                                       call: the cadence is the caller's); draft(obj) returns {message, cached, source, model}
    .to_list() -> [objects]            every object with exactly the keys KEYS
    .state() -> {n, objects, windows, why?}   why whenever n is 0
  KEYS                                 id, label, p, label_source, message, message_source, thumb, box, bearing_deg,
                                       hit_m, dist_m, pos_px, why, first_seen, last_seen, windows_unseen, stale
  rows                                 tool "object.seen", agent "objects", app "map", args {id, label, p, pos_px, event,
                                       shift_id} with event in new | drafted | stale | seen_again; state_after is the object
                                       without its thumb; a message drafted by the stub sets cached=True, source="stub"
  draft_stub(obj)                      # DEMO_CACHE: the label, p, distance and bearing as one line tagged "[stub: no model]"
  DogSession.objects_state()           the GET /dog/objects body {n, objects, windows, fov_deg, source, why?} without a dog
  WATCH                                the detector's file the session reads (<repo>/watch.json, what wtdd/watch.py writes)
  python -m wtdd.dog.objects --replay <npz> --watch <watch json> --pose x,y,yaw --fov DEG --png <out> [--threshold N]
                                       the grid from the frames, the boxes placed from the pose, the occupancy PNG with
                                       one PIN_PX square in PIN_RGB per placed object; exit 2 (WARN) when none is placed
  GET /dog/objects with WTDD_OBJECTS=<file>   # DEMO_CACHE: serves that file's objects (the page's dry check) and names it in source
"""
from __future__ import annotations
import base64
import io
import contextlib
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from ..config import ROOT
from . import lidar, occupancy
from .fixtures import make_objects_fixture as ofx
from .fixtures import make_voxel_frames as fx

from . import objects   # RED until it exists: ModuleNotFoundError, the whole module errors

CAL = ofx.CAL
FOV = ofx.FOV_DEG
POSE = ofx.POSE
PY = sys.executable


def accumulated() -> occupancy.Grid:
    fr = [lidar.decode(fx.decode_wire(b)) for b in fx.blobs()]
    g = occupancy.Grid.from_frame(fr[0])
    for d in fr:
        g.update_frame(d)
    return g


def frame() -> dict:
    """watch-frame.json with `file` made absolute, the shape wtdd/watch.py writes to watch.json."""
    d = json.loads(ofx.WATCH_JSON.read_text())
    d["file"] = str(ofx.FRAME)
    return d


def empty_frame(t: float) -> dict:
    return {**frame(), "t": t, "n": 0, "classes": {}, "boxes": []}


def px_of(xy_m) -> list[int]:
    return occupancy.to_map_px([list(xy_m)], CAL)[0].tolist()


def decode_thumb(data_url: str) -> Image.Image:
    head, b64 = data_url.split(",", 1)
    assert head == "data:image/jpeg;base64", head
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def stop(s) -> None:
    s.loop.call_soon_threadsafe(s.loop.stop)
    while s.loop.is_running():
        time.sleep(0.01)
    s.loop.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Bearing(unittest.TestCase):
    def test_a_centred_box_looks_straight_ahead(self):
        self.assertAlmostEqual(objects.bearing([280, 200, 360, 330], 640, FOV), 0.0, places=9)

    def test_a_box_right_of_centre_is_a_positive_pinhole_angle(self):
        b = objects.bearing([536, 260, 616, 350], 640, FOV)   # centre at 0.9 W
        self.assertAlmostEqual(b, math.atan(0.8), places=9)
        self.assertAlmostEqual(math.degrees(b), 38.66, places=1)

    def test_left_is_negative_and_symmetric(self):
        r = objects.bearing([576, 0, 640, 10], 640, FOV)
        l = objects.bearing([0, 0, 64, 10], 640, FOV)
        self.assertGreater(r, 0)
        self.assertAlmostEqual(l, -r, places=9)

    def test_the_frame_edge_is_half_the_field_of_view(self):
        self.assertAlmostEqual(objects.bearing([640, 0, 640, 10], 640, 120.0), math.radians(60), places=9)

    def test_a_field_of_view_outside_0_180_is_refused(self):
        for fov in (0, -10, 180, 200):
            with self.assertRaises(ValueError, msg=f"fov {fov}"):
                objects.bearing([0, 0, 10, 10], 640, fov)


class Association(unittest.TestCase):
    def setUp(self):
        self.g = accumulated()

    def test_the_ray_ahead_meets_wall_a(self):
        h = objects.nearest_blob(self.g, (0.0, 0.0), 0.0, threshold=3)
        self.assertIsNotNone(h, "WALL_A at x = 2.0 m is straight ahead of the origin")
        np.testing.assert_allclose(h["xy"], [2.0, 0.0], atol=1e-9, err_msg="the pin is the cell's lattice point (the dots' convention)")
        self.assertAlmostEqual(h["dist_m"], 2.0, delta=fx.RES)
        self.assertEqual(h["count"], 3)

    def test_the_ray_to_the_right_meets_wall_a_further_along(self):
        h = objects.nearest_blob(self.g, (0.0, 0.0), -math.atan(0.8), threshold=3)   # the camera's right is a negative odometry angle
        self.assertIsNotNone(h)
        self.assertAlmostEqual(h["xy"][0], 2.0, places=9)
        self.assertAlmostEqual(h["xy"][1], -1.6, delta=fx.RES + 1e-9, msg="within one cell of the analytic hit")
        self.assertAlmostEqual(h["dist_m"], math.hypot(2.0, 1.6), delta=2 * fx.RES)

    def test_a_blob_seen_once_is_found_at_threshold_1_and_not_at_2(self):
        h = objects.nearest_blob(self.g, (0.0, 0.0), -math.pi / 2, threshold=1)
        self.assertIsNotNone(h, "the BLOB at (0.0, -1.0) lies straight below the origin (odometry -y)")
        # BLOB's y is the half-open index range (-20, -16): lattice points -1.0 .. -0.85 m; -0.8 m (index -16) is outside it
        np.testing.assert_allclose(h["xy"], [0.0, (fx.BLOB["y"][1] - 1) * fx.RES], atol=1e-9)
        self.assertEqual(h["count"], 1)
        self.assertIsNone(objects.nearest_blob(self.g, (0.0, 0.0), -math.pi / 2, threshold=2), "seen once: not a blob at threshold 2")

    def test_nothing_behind_is_none(self):
        self.assertIsNone(objects.nearest_blob(self.g, (0.0, 0.0), math.pi, threshold=1))

    def test_the_range_limit_holds(self):
        self.assertIsNone(objects.nearest_blob(self.g, (0.0, 0.0), 0.0, threshold=3, max_range_m=1.0))
        self.assertIsNotNone(objects.nearest_blob(self.g, (0.0, 0.0), 0.0, threshold=3, max_range_m=2.5))


class Thumb(unittest.TestCase):
    def test_the_thumb_is_the_box_cropped_from_the_frame(self):
        for b in ofx.BOXES:
            t = decode_thumb(objects.thumb(str(ofx.FRAME), b["xyxy"]))
            self.assertLessEqual(t.width, objects.THUMB_PX)
            mean = np.asarray(t, dtype=np.float64).reshape(-1, 3).mean(axis=0)
            np.testing.assert_allclose(mean, b["rgb"], atol=12, err_msg=f"{b['name']}: the thumb is not the {b['rgb']} rectangle")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.g = accumulated()
        self.rows: list[dict] = []
        self.drafts: list[dict] = []

    def draft(self, obj: dict) -> dict:
        self.drafts.append(obj)
        return {"message": f"line for {obj['label']}", "cached": False, "source": "live", "model": "test"}

    def store(self, **kw) -> "objects.Store":
        return objects.Store(append=self.rows.append, draft=self.draft, **kw)

    def observe(self, s, fr=None, pose=POSE, grid="default", **kw):
        return s.observe(fr or frame(), pose, self.g if grid == "default" else grid, CAL, FOV, **kw)

    def test_new_objects_are_placed_at_the_blob_along_their_bearing(self):
        s = self.store()
        r = self.observe(s, threshold=3)
        self.assertEqual(r["new"], ["o1", "o2"])
        self.assertEqual((r["stale"], r["unplaced"]), ([], []))
        objs = {o["id"]: o for o in s.to_list()}
        a, b = objs["o1"], objs["o2"]
        self.assertEqual((a["label"], a["p"], a["label_source"]), ("chair", 0.71, "detector"))
        self.assertEqual((b["label"], b["p"], b["label_source"]), ("backpack", 0.55, "detector"))
        self.assertEqual(a["hit_m"], [2.0, 0.0])
        self.assertEqual(a["pos_px"], px_of([2.0, 0.0]), "the pin is WALL_A's cell through the calibration, like the dots")
        self.assertEqual(b["hit_m"][0], 2.0)
        self.assertAlmostEqual(b["hit_m"][1], -1.6, delta=fx.RES + 1e-9)
        self.assertEqual(b["pos_px"], px_of(b["hit_m"]))
        self.assertAlmostEqual(a["bearing_deg"], 0.0, places=6)
        self.assertAlmostEqual(b["bearing_deg"], 38.66, places=1)
        self.assertAlmostEqual(a["dist_m"], 2.0, delta=fx.RES)
        for o in (a, b):
            self.assertEqual(set(o), set(objects.KEYS), "every object carries exactly KEYS")
            self.assertIsNone(o["message"])
            self.assertFalse(o["stale"])
            self.assertEqual(o["windows_unseen"], 0)
            self.assertIsNone(o["why"])
            self.assertEqual(o["first_seen"], o["last_seen"])
            t = decode_thumb(o["thumb"])
            self.assertLessEqual(t.width, objects.THUMB_PX)
        np.testing.assert_allclose(np.asarray(decode_thumb(a["thumb"]), dtype=np.float64).reshape(-1, 3).mean(axis=0), ofx.BOXES[0]["rgb"], atol=12)

    def test_one_row_per_new_object_with_the_contract_fields(self):
        s = self.store()
        self.observe(s, threshold=3)
        self.assertEqual(len(self.rows), 2)
        for row, want in zip(self.rows, ("o1", "o2")):
            self.assertEqual((row["tool"], row["agent"], row["app"], row["ok"]), ("object.seen", "objects", "map", True))
            self.assertEqual(row["args"]["id"], want)
            self.assertEqual(row["args"]["event"], "new")
            self.assertTrue({"id", "label", "p", "pos_px", "event", "shift_id"} <= set(row["args"]), sorted(row["args"]))
            self.assertEqual(row["args"]["label"], row["state_after"]["label"])
            self.assertEqual(row["args"]["pos_px"], row["state_after"]["pos_px"])
            self.assertNotIn("thumb", row["state_after"], "a 1 KB thumbnail per row would bloat the ledger; the object carries it")
            self.assertIsInstance(row["latency_ms"], int)
            json.dumps(row)

    def test_the_same_frame_again_is_neither_new_nor_a_row(self):
        s = self.store()
        self.observe(s, threshold=3)
        n = len(self.rows)
        r = self.observe(s, {**frame(), "t": frame()["t"] + 0.25}, threshold=3)
        self.assertEqual((r["new"], sorted(r["seen"])), ([], ["o1", "o2"]))
        self.assertEqual(len(self.rows), n, "an unchanged object is not a new row")
        self.assertEqual([o["id"] for o in s.to_list()], ["o1", "o2"])
        self.assertEqual(s.state()["windows"], 2)

    def test_a_message_is_drafted_once_per_new_object(self):
        s = self.store()
        self.observe(s, threshold=3)
        self.assertEqual(s.draft(), "o1")
        self.assertEqual(s.draft(), "o2")
        self.assertIsNone(s.draft(), "nothing left to draft")
        self.assertIsNone(s.draft())
        self.assertEqual([d["id"] for d in self.drafts], ["o1", "o2"], "exactly one draft per new object")
        objs = {o["id"]: o for o in s.to_list()}
        self.assertEqual(objs["o1"]["message"], "line for chair")
        self.assertEqual(objs["o1"]["message_source"], "live")
        drafted = [r for r in self.rows if r["args"]["event"] == "drafted"]
        self.assertEqual([r["args"]["id"] for r in drafted], ["o1", "o2"])
        self.assertEqual(drafted[0]["response_or_error"], "line for chair")
        self.observe(s, {**frame(), "t": frame()["t"] + 0.25}, threshold=3)
        self.assertIsNone(s.draft(), "seen again is not new: no second draft")
        self.assertEqual(len(self.drafts), 2)

    def test_a_failed_draft_is_a_failed_row_not_a_canned_line(self):
        def boom(obj):
            raise RuntimeError("no model tonight")
        s = objects.Store(append=self.rows.append, draft=boom)
        self.observe(s, threshold=3)
        with self.assertRaises(RuntimeError):
            s.draft()
        bad = [r for r in self.rows if r["args"]["event"] == "drafted"]
        self.assertEqual(len(bad), 1)
        self.assertFalse(bad[0]["ok"])
        self.assertIn("no model tonight", bad[0]["response_or_error"])
        self.assertIsNone({o["id"]: o for o in s.to_list()}["o1"]["message"], "no sentence stands in for the failed one")

    def test_stub_drafts_are_labeled_stub_on_the_ledger_and_in_the_text(self):
        from .. import ledger
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ledger, "LEDGER", Path(tmp) / "ledger.jsonl"):
            s = objects.Store(draft=objects.draft_stub)   # the default append is ledger.append
            self.observe(s, threshold=3)
            s.draft()
            got = ledger.rows()
        new, drafted = got[0], got[-1]
        self.assertEqual((new["args"]["event"], new["cached"], new["source"]), ("new", False, "live"))
        self.assertEqual((drafted["args"]["event"], drafted["cached"], drafted["source"]), ("drafted", True, "stub"))
        msg = {o["id"]: o for o in s.to_list()}["o1"]["message"]
        self.assertIn("[stub", msg)
        self.assertIn("chair", msg)
        self.assertIn("0.71", msg)
        self.assertEqual({o["id"]: o for o in s.to_list()}["o1"]["message_source"], "stub")

    def test_objects_decay_to_stale_after_n_windows_unseen_and_come_back(self):
        s = self.store(stale_windows=3)
        t0 = frame()["t"]
        self.observe(s, threshold=3)
        for k in range(1, 3):
            r = self.observe(s, empty_frame(t0 + k), threshold=3)
            self.assertEqual(r["stale"], [], f"window {k}: not yet")
        r = self.observe(s, empty_frame(t0 + 3), threshold=3)
        self.assertEqual(sorted(r["stale"]), ["o1", "o2"])
        objs = {o["id"]: o for o in s.to_list()}
        self.assertTrue(all(o["stale"] for o in objs.values()))
        self.assertEqual(objs["o1"]["windows_unseen"], 3)
        self.assertEqual(objs["o1"]["first_seen"], objs["o1"]["last_seen"], "last_seen is the last window that saw it")
        stale_rows = [r for r in self.rows if r["args"]["event"] == "stale"]
        self.assertEqual(sorted(r["args"]["id"] for r in stale_rows), ["o1", "o2"])
        n = len(self.rows)
        self.observe(s, empty_frame(t0 + 4), threshold=3)
        self.assertEqual(len(self.rows), n, "stale once is one row, not one per window")
        r = self.observe(s, {**frame(), "t": t0 + 5}, threshold=3)
        self.assertEqual((r["new"], sorted(r["seen"])), ([], ["o1", "o2"]), "the same things at the same pins are the same objects")
        objs = {o["id"]: o for o in s.to_list()}
        self.assertFalse(objs["o1"]["stale"])
        self.assertEqual(objs["o1"]["windows_unseen"], 0)
        self.assertEqual(sorted(r["args"]["id"] for r in self.rows if r["args"]["event"] == "seen_again"), ["o1", "o2"])

    def test_a_box_with_no_pose_is_stored_unplaced_and_says_why(self):
        s = self.store()
        r = self.observe(s, pose=None, threshold=3)
        self.assertEqual(sorted(r["unplaced"]), ["o1", "o2"])
        for o in s.to_list():
            self.assertIsNone(o["pos_px"])
            self.assertIsNone(o["hit_m"])
            self.assertIn("pose", o["why"])
            self.assertIsNotNone(o["thumb"], "the thumbnail does not need a pose")
        self.assertEqual(len(self.rows), 2, "unplaced is still seen: a row each, pos_px null")
        self.assertIsNone(self.rows[0]["args"]["pos_px"])

    def test_a_box_with_no_grid_or_no_blob_says_why(self):
        s = self.store()
        r = self.observe(s, grid=None, threshold=3)
        self.assertEqual(sorted(r["unplaced"]), ["o1", "o2"])
        self.assertIn("grid", s.to_list()[0]["why"])
        s2 = self.store()
        r = self.observe(s2, pose={"position": [0.0, 0.0], "yaw": math.pi}, threshold=3)   # facing -x: nothing there
        self.assertEqual(sorted(r["unplaced"]), ["o1", "o2"])
        self.assertIn("blob", s2.to_list()[0]["why"])

    def test_a_window_that_cannot_place_a_known_object_does_not_spawn_a_second_one(self):
        s = self.store()
        self.observe(s, threshold=3)
        r = self.observe(s, {**frame(), "t": frame()["t"] + 1}, pose=None, threshold=3)
        self.assertEqual((r["new"], sorted(r["seen"])), ([], ["o1", "o2"]))
        objs = {o["id"]: o for o in s.to_list()}
        self.assertEqual(objs["o1"]["pos_px"], px_of([2.0, 0.0]), "the last pin stays until a window places it again")
        self.assertIn("pose", objs["o1"]["why"])
        self.assertEqual([r["args"]["event"] for r in self.rows], ["new", "new"])

    def test_a_known_unplaced_object_takes_its_first_pin_instead_of_a_second_one(self):
        s = self.store()
        self.observe(s, pose=None, threshold=3)   # boxed before the dog's pose (or the calibration) is there
        r = self.observe(s, {**frame(), "t": frame()["t"] + 1}, threshold=3)
        self.assertEqual((r["new"], sorted(r["seen"]), r["unplaced"]), ([], ["o1", "o2"], []))
        objs = {o["id"]: o for o in s.to_list()}
        self.assertEqual(objs["o1"]["pos_px"], px_of([2.0, 0.0]))
        self.assertIsNone(objs["o1"]["why"])
        self.assertEqual([r["args"]["event"] for r in self.rows], ["new", "new"])

    def test_an_unplaced_box_does_not_revive_a_stale_pin(self):
        s = self.store(stale_windows=1)
        t0 = frame()["t"]
        self.observe(s, threshold=3)
        self.observe(s, empty_frame(t0 + 1), threshold=3)   # o1, o2 stale: the continuity is gone
        r = self.observe(s, {**frame(), "t": t0 + 2}, pose=None, threshold=3)
        self.assertEqual(r["new"], ["o3", "o4"], "a pin is a claim: only a placement near it brings a stale object back")
        self.assertTrue({o["id"]: o for o in s.to_list()}["o1"]["stale"])
        self.assertNotIn("seen_again", [r["args"]["event"] for r in self.rows])

    def test_an_unknown_draft_mode_fails_every_draft_loud_not_live(self):
        with mock.patch.dict(os.environ, {"WTDD_OBJECTS_DRAFT": "stubb"}):
            d = objects.drafter()
        self.assertIsNot(d, objects.draft_live, "a mistyped mode must not quietly call the model")
        s = objects.Store(append=self.rows.append, draft=d)
        self.observe(s, threshold=3)
        with self.assertRaises(ValueError):
            s.draft()
        bad = [r for r in self.rows if r["args"]["event"] == "drafted"]
        self.assertEqual((len(bad), bad[0]["ok"]), (1, False))
        self.assertIn("WTDD_OBJECTS_DRAFT", bad[0]["response_or_error"])
        self.assertIn("FAILED", {o["id"]: o for o in s.to_list()}["o1"]["message_source"])

    def test_an_old_detector_frame_is_logged_once_not_every_second(self):
        s = self.store()
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(err):
            w = Path(tmp) / "watch.json"
            w.write_text(json.dumps(frame()))
            whys = []
            for age in (10, 11, 12):
                os.utime(w, (time.time() - age,) * 2)
                whys.append(objects.tick(s, w, POSE, self.g, CAL, FOV))
        self.assertIn("10 s old", whys[0], "the body keeps the age")
        self.assertIn("12 s old", whys[2])
        self.assertEqual(err.getvalue().count("detector frame"), 1, err.getvalue())

    def test_a_decide_hook_sets_label_and_p(self):
        calls = []

        def decide(box, fr):
            calls.append(box["name"])
            return {"label": "material stack", "p": 0.82}
        s = objects.Store(append=self.rows.append, draft=self.draft, decide=decide)
        self.observe(s, threshold=3)
        self.assertEqual(calls, ["chair", "backpack"])
        o = s.to_list()[0]
        self.assertEqual((o["label"], o["p"], o["label_source"]), ("material stack", 0.82, "decide"))
        self.assertEqual(self.rows[0]["args"]["label"], "material stack")

    def test_state_with_nothing_seen_says_why(self):
        s = self.store()
        st = s.state()
        self.assertEqual((st["n"], st["objects"], st["windows"]), (0, [], 0))
        self.assertTrue(st.get("why"), "zero objects always says why")
        self.observe(s, empty_frame(1.0), threshold=3)
        st = s.state()
        self.assertEqual((st["n"], st["windows"]), (0, 1))
        self.assertTrue(st.get("why"))


class Session(unittest.TestCase):
    def test_objects_state_without_a_detector_frame_says_why(self):
        from .. import ledger
        from . import session
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(objects, "WATCH", Path(tmp) / "watch.json"), \
                mock.patch.object(ledger, "LEDGER", Path(tmp) / "ledger.jsonl"), mock.patch.dict(os.environ, {"WTDD_CAM_FOV_DEG": str(FOV)}):
            s = session.DogSession()
            try:
                d = s.objects_state()
            finally:
                stop(s)
        self.assertEqual((d["n"], d["objects"], d["windows"]), (0, [], 0))
        self.assertEqual(d["source"], "session")
        self.assertEqual(d["fov_deg"], FOV)
        self.assertIn("watch.json", d["why"])
        json.dumps(d)

    def test_objects_state_without_a_field_of_view_is_loud_not_silent(self):
        from .. import ledger
        from . import session
        env = {k: v for k, v in os.environ.items() if k != "WTDD_CAM_FOV_DEG"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(objects, "WATCH", Path(tmp) / "watch.json"), \
                mock.patch.object(ledger, "LEDGER", Path(tmp) / "ledger.jsonl"), mock.patch.dict(os.environ, env, clear=True):
            (Path(tmp) / "watch.json").write_text(json.dumps(frame()))
            s = session.DogSession()
            try:
                d = s.objects_state()
            finally:
                stop(s)
        self.assertIsNone(d["fov_deg"])
        self.assertIn("WTDD_CAM_FOV_DEG", d["why"])


class Fixture(unittest.TestCase):
    def test_watch_frame_json_is_what_watch_py_writes(self):
        d = json.loads(ofx.WATCH_JSON.read_text())
        self.assertTrue({"ts", "t", "ms", "n", "classes", "boxes", "source", "model", "file"} <= set(d), sorted(d))
        self.assertEqual(d["n"], len(d["boxes"]))
        for b in d["boxes"]:
            self.assertEqual(set(b), {"name", "conf", "xyxy"})
            self.assertEqual(len(b["xyxy"]), 4)
        self.assertEqual(Image.open(ofx.FRAME).size, (ofx.W, ofx.H))

    def test_objects_json_is_the_page_contract(self):
        d = json.loads(ofx.OBJECTS_JSON.read_text())
        self.assertEqual(set(d), {"n", "objects", "windows", "fov_deg", "source", "why"})
        self.assertEqual(d["n"], len(d["objects"]))
        self.assertEqual([o["id"] for o in d["objects"]], ["o1", "o2"])
        self.assertEqual([o["stale"] for o in d["objects"]], [False, True])
        self.assertEqual(d["objects"][0]["pos_px"], px_of([2.0, 0.0]))
        self.assertEqual(d["objects"][1]["pos_px"], px_of([2.0, -1.6]))
        for o in d["objects"]:
            self.assertGreater(decode_thumb(o["thumb"]).width, 0)
            self.assertIn("[stub", o["message"])
            self.assertEqual(o["message_source"], "stub")
            self.assertEqual(o["label_source"], "detector")

    def test_objects_json_has_exactly_the_store_keys(self):
        d = json.loads(ofx.OBJECTS_JSON.read_text())
        for o in d["objects"]:
            self.assertEqual(set(o), set(objects.KEYS), "the fixture and the live store draw the same shape")


class Replay(unittest.TestCase):
    def run_cli(self, *extra, timeout=90):
        return subprocess.run([PY, "-m", "wtdd.dog.objects", *extra], cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "WTDD_LEDGER": str(Path(tempfile.mkdtemp()) / "ledger.jsonl")})

    def test_replay_writes_the_grid_png_with_one_pin_per_placed_object(self):
        g = accumulated()
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "objects.png"
            r = self.run_cli("--replay", str(fx.NPZ), "--watch", str(ofx.WATCH_JSON), "--pose", "0,0,0", "--fov", str(FOV), "--png", str(png), "--threshold", "3")
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertGreaterEqual(r.stderr.count("[wtdd:objects]"), len(ofx.BOXES) + 1, "one stderr line per object plus a summary")
            self.assertIn("placed=2", r.stderr)
            im = np.asarray(Image.open(png).convert("RGB"))
        self.assertEqual(im.shape[:2], (g.shape[0] * occupancy.PNG_SCALE, g.shape[1] * occupancy.PNG_SCALE), "the occupancy PNG, pins on top")
        pin = int(np.all(im == np.array(objects.PIN_RGB, dtype=np.uint8), axis=2).sum())
        self.assertEqual(pin, len(ofx.BOXES) * objects.PIN_PX ** 2, "two pins, PIN_PX square each, not overlapping")
        self.assertGreater(int(np.all(im == 0, axis=2).sum()), 0, "the walls are still drawn under the pins")

    def test_replay_with_nothing_placed_warns_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "objects.png"
            r = self.run_cli("--replay", str(fx.NPZ), "--watch", str(ofx.WATCH_JSON), "--pose", "0,0,3.14159", "--fov", str(FOV), "--png", str(png))
            self.assertEqual(r.returncode, 2, r.stderr[-800:])
            self.assertIn("WARN", r.stderr)
            self.assertIn("placed=0", r.stderr)
            self.assertTrue(png.is_file(), "the PNG is still written: the grid with no pin is what happened")

    def test_replay_fails_loud_on_a_missing_watch_json(self):
        r = self.run_cli("--replay", str(fx.NPZ), "--watch", "/nonexistent/watch.json", "--pose", "0,0,0", "--fov", str(FOV), "--png", "/tmp/never-objects.png")
        self.assertEqual(r.returncode, 1)
        self.assertIn("/nonexistent/watch.json", r.stderr)

    def test_replay_writes_no_ledger_row(self):
        led = Path(tempfile.mkdtemp()) / "ledger.jsonl"
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([PY, "-m", "wtdd.dog.objects", "--replay", str(fx.NPZ), "--watch", str(ofx.WATCH_JSON), "--pose", "0,0,0", "--fov", str(FOV), "--png", str(Path(tmp) / "o.png")],
                               cwd=ROOT, capture_output=True, text=True, timeout=90, env={**os.environ, "WTDD_LEDGER": str(led)})
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertFalse(led.exists(), "a replay of a fixture is not a step")


class Api(unittest.TestCase):
    def test_get_dog_objects_serves_the_fixture_when_told_to(self):
        """# DEMO_CACHE path under test: WTDD_OBJECTS=<file> makes GET /dog/objects serve that file for the page's dry check."""
        port = free_port()
        led = Path(tempfile.mkdtemp()) / "ledger.jsonl"
        p = subprocess.Popen([PY, "-m", "wtdd.api", str(port)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                             env={**os.environ, "WTDD_LEDGER": str(led), "WTDD_OBJECTS": str(ofx.OBJECTS_JSON)})
        try:
            body = None
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/dog/objects", timeout=2) as r:
                        body = json.loads(r.read())
                    break
                except (urllib.error.URLError, ConnectionError, OSError):
                    time.sleep(0.1)
        finally:
            p.kill()
            p.wait()
        self.assertIsNotNone(body, "the API never answered GET /dog/objects")
        want = json.loads(ofx.OBJECTS_JSON.read_text())
        self.assertEqual(body["objects"], want["objects"])
        self.assertEqual(body["n"], 2)
        self.assertIn("objects.json", body["source"], "the body names the fixture it came from, never 'session'")


if __name__ == "__main__":
    unittest.main()
