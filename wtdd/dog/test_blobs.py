"""Tests for the blob labels (wtdd/dog/blobs.py): at a stop, every non-wall blob and every low wall run in the camera's
view gets one typed label with a probability from a photo of it; a furniture label moves the run off the wall layer; no
label ever adds a cell, a line, or opens a gap. On goal 15's furnished room (wtdd/dog/fixtures/voxel_furniture.npz,
replayed through the driver's own decoder) and a doorway world written the same way (make_furniture_frames.write);
nothing here has seen the real dog and no test calls a model: every model is a stub the test hands in, or llm.generate
and decide._jev patched. Run:

    python -m unittest wtdd.dog.test_blobs

RED until blobs.py exists. The geometry is graded from the fixture's analytic truth (make_furniture_frames' declared
boxes) and from 15's own classes() and segments(), never from blobs.py's output; the words from what the stub said.

The contract under test (odometry metres; a cell is its corner, index * resolution + origin, the walls() convention;
the fixture's lattice cell (gx, gy) is metres / resolution):
  LABELS     {wall, shelf, table, stack, hazard, person, unknown}: the closed list; `opening` is not on it (a gap in a
             wall run is geometry, and `opening` is goal 17's escalate label). FURNITURE {shelf, table, stack}: the
             labels that move a run off the wall layer at p >= WTDD_DECIDE_THRESHOLD.
  find(grid, threshold=3, tall=floorplan.TALL) -> plan {cls, segments, blobs, origin, resolution, ...}: cls and
             segments are exactly floorplan.classes() and floorplan.segments() of that grid (the geometry is 15's, all of
             it); blobs: one per wall run whose top is below `tall` (kind "run": the shelf, the far wall seen to 0.9 m;
             never the full-height wall) and one per connected group of non-wall cells, classes 2, 3 and 5 (kind
             "blob"). A blob is {id (str, unique), kind, cells [[x, y] metres], xy [x, y] its centre, top_m, length_m,
             grounded (bool), geometry_verdict (e.g. "wall (grounded, straight 2.0 m)")}, JSON as it stands. A read:
             no row.
  bearing_to(xy, pose) -> radians from the optical axis, right positive: 07's bearing() reversed. pose is 07's
             {position: [x, y], yaw}; the ray at yaw - bearing from the position passes through xy.
  crop_box(bearing, (w, h), fov_deg) -> (x0, y0, x1, y1) ints: a full-height strip centred on the column 07's
             bearing() maps back to that bearing, between 32 px and half the frame wide; ValueError when the bearing
             is outside the field of view.
  crop(img, box) -> (data_url, sha): the strip in 07's thumb() shape (data:image/jpeg;base64,...); sha is the sha256
             hex of its JPEG bytes (crop_sha on the row).
  line(blob, dist_m) -> the one text line the models get, in words: height, length, grounded or floating, distance;
             no digit (02's rule), no newline.
  label(blob, img, pose, fov_deg, *, vision=None, choose=None) -> record {blob_id, kind, cells, xy, geometry_verdict,
             label, p, model, erase, source, error?} and one blob.labelled row, ok or FAILED; never raises for a model's
             failure (a FAILED label is label None, p None, error). vision(data_url, line) -> {text, model}: the photo
             and the line to the vision model (live: llm.generate, agent "blobs", one image part, every word of LABELS
             in the ask). choose(text, labels) -> (label, p, model, raw): that reply typed by 02's Jev Choice (live:
             decide._jev over LABELS; never decide.decide, so no `decided` row and nothing for 17's policy). A label off
             the list (opening) or a p outside [0, 1] is FAILED. Both live functions are looked up at call time (07's
             draft_live imports llm inside the function), so a patch of wtdd.llm.generate or wtdd.decide._jev reaches
             them. WTDD_BLOBS_LABEL=stub is the DEMO_CACHE: unknown, p 0, no model call, the row app "stub",
             cached=True, source="stub".
  label_stop(grid, img, pose, fov_deg, threshold=3, *, vision=None, choose=None) -> {plan, labels, skipped}: label()
             for every blob whose centre is inside the field of view, the rest skipped with no row; one
             `[wtdd:blobs]` line with labelled=N; none in view is a WARN.
  erase(plan, labels, threshold=None) -> a new plan: a run that a FURNITURE label with p >= threshold (default
             WTDD_DECIDE_THRESHOLD) was given for moves from class 1 to class 3, its segment is dropped, `moved` lists
             its id. Nothing else ever changes: no cell is added or removed, a wall label moves nothing, a label on a
             non-wall blob moves nothing, a FAILED label moves nothing, a label off the list is a ValueError. The input
             plan is untouched. Deleting every model call (no labels, or the stub's) moves nothing on the map. A run
             whose top reaches TALL in the plan given (a full-height wall: never offered) never moves, whatever a label
             kept from an earlier plan says of it: its id is in `refused`, and a WARN says so.
  blob.labelled row: agent "blobs", app openrouter | stub, args {blob_id, kind, cells (count), geometry_verdict,
             crop_sha, line, shift_id}, state_after {label, p, model, erase}, response_or_error the raw replies of both
             models (or the error), latency_ms.
  DogSession.blobs_label(threshold)   POST /dog/blobs, the press at a stop: the live frame (snapshot()), the dog's pose
             (body.state(), as 07's objects_state reads it), WTDD_CAM_FOV_DEG, a copy of the session grid -> label_stop;
             its rows are the blob.labelled rows and nothing else; no dog or no field of view is one failed row and a
             RuntimeError or ValueError, and never a connect.
  DogSession.blobs_px()   GET /dog/blobs {labels: [record + pos_px], source, moved, why?}: the newest labels, pinned
             through the calibration; a read, no row; WTDD_BLOBS=<file> ({labels: [records]}) serves that file instead
             (DEMO_CACHE, source "fixture: <file>"). Each label's erase and the list moved are GET /dog/floorplan's own
             (the newest plan, the threshold at the read), never the verdict stamped when the label was made, so the
             page's "greyed" is what the map greyed.
  DogSession.floorplan_px(t)   15's read with the newest labels erased into it: a greyed run is a slab, not a wall line.
  wtdd/dog/fixtures/blobs.json   the planted labels for the page's dry check: a shelf over the threshold, one FAILED
             label, every cell one the LiDAR saw.
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from .. import config, decide, ledger
from ..config import ROOT
from . import blobs, floorplan, lidar, objects, occupancy
from .fixtures import make_furniture_frames as ff

config.maybe("WTDD_SHIFT")   # load .env once, now, so a later mock.patch.dict never hides or refills its keys mid-test
CAL = {"odom": [0.0, 0.0, 0.0], "map": [449.0, 491.0], "heading": 1.5708}   # nav.calibration shape, as in 01/15's tests
PY = sys.executable
RES = ff.RES
W, H = 640, 480
FOV = 60.0
CLOSED = {"wall", "shelf", "table", "stack", "hazard", "person", "unknown"}
GROUPS = {"table": ("table_top", "table_legs"), "chair": ("chair_seat", "chair_back", "chair_legs"), "box": ("box",), "person": ("person",)}
ENV = {"WTDD_DECIDE_THRESHOLD": "0.7", "WTDD_BLOBS_LABEL": "live", "WTDD_BLOBS": "", "WTDD_CAM_FOV_DEG": str(FOV), "JEV_API_KEY": ""}
AT_SHELF = {"position": [0.8, 0.0], "yaw": 0.0}                    # facing +x: the shelf run dead ahead, nothing else in 60 degrees
AT_TABLE = {"position": [0.0, -0.5], "yaw": -math.pi / 2}          # facing -y: the table ahead, the chair 36 degrees right (out)
AT_NOTHING = {"position": [0.0, 0.0], "yaw": math.radians(39)}     # between the shelf (0 deg) and the person (79 deg): nothing
DOORWAY = {   # two low wall runs on one line, 1.6 m each, a 0.8 m doorway between them (cells gx -8..7 on gy 40)
    "wall_l": {"x": (-40, -8), "y": (40, 41), "z": (6, 25), "frames": ff.ALL, "cls": 1, "line": True},
    "wall_r": {"x": (8, 40), "y": (40, 41), "z": (6, 25), "frames": ff.ALL, "cls": 1, "line": True},
}
DOOR_CELLS = {(gx, 40) for gx in range(-8, 8)}
AT_DOORWAY = {"position": [0.0, 0.0], "yaw": math.pi / 2}          # facing +y: both runs in a 90 degree view, 31 degrees each side


def accumulated(path=ff.NPZ) -> occupancy.Grid:
    fr = [lidar.decode(ff.decode_wire(b)) for b in ff.blobs(path)]
    g = occupancy.Grid.from_frame(fr[0])
    for d in fr:
        g.update_frame(d)
    return g


def cells_of(*names: str, world: dict = ff.WORLD) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for n in names:
        out |= ff.object_cells(n, world)
    return out


def lattice(cells) -> set[tuple[int, int]]:
    """[[x, y] metres, cell corners] -> {(gx, gy)} (the fixture's absolute lattice)."""
    return {(round(x / RES), round(y / RES)) for x, y in cells}


def at(plan: dict, arr: np.ndarray, cell) -> int:
    ox, oy = round(plan["origin"][0] / RES), round(plan["origin"][1] / RES)
    return int(arr[cell[1] - oy, cell[0] - ox])


def one(bs: list[dict], kind: str, truth: set) -> dict:
    """The one blob of that kind whose cells all belong to truth (an object's declared cells)."""
    got = [b for b in bs if b["kind"] == kind and b["cells"] and lattice(b["cells"]) <= truth]
    assert len(got) == 1, f"{len(got)} {kind} blobs inside that object: {[b['id'] for b in got]}"
    return got[0]


def rec(b: dict, label, p, model="stub", error=None) -> dict:
    """A label record in label()'s shape, for erase()."""
    r = {"blob_id": b["id"], "kind": b["kind"], "cells": b["cells"], "xy": b["xy"], "geometry_verdict": b["geometry_verdict"],
         "label": label, "p": p, "model": model}
    return {**r, "error": error} if error else r


def frame(bars=((20.0, (200, 30, 30)), (-30.0, (30, 30, 200))), fov=90.0) -> Image.Image:
    """A synthetic W x H camera frame: a light background and one 24 px vertical bar per (bearing deg, colour), each
    centred on the column a pinhole of horizontal field of view `fov` puts that bearing on (07's bearing() inverted)."""
    img = Image.new("RGB", (W, H), (235, 235, 230))
    px = img.load()
    for deg, rgb in bars:
        u = W * (0.5 + math.tan(math.radians(deg)) / (2 * math.tan(math.radians(fov) / 2)))
        for x in range(max(int(u) - 12, 0), min(int(u) + 12, W)):
            for y in range(H):
                px[x, y] = rgb
    return img


def jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def sha_of(data_url: str) -> str:
    return hashlib.sha256(base64.b64decode(data_url.split(",", 1)[1])).hexdigest()


def segs(s) -> list[tuple]:
    """Segments as tuples, whatever sequence type carried them."""
    return [tuple(x) for x in s]


def rows(tool: str | None = "blob.labelled") -> list[dict]:
    return [r for r in ledger.rows() if tool is None or r.get("tool") == tool]


def stop(s) -> None:
    s.loop.call_soon_threadsafe(s.loop.stop)
    while s.loop.is_running():
        time.sleep(0.01)
    s.loop.close()


class FakeBody:
    """A connected dog standing at AT_SHELF, as body.state() reports it (position x, y, z; rpy roll, pitch, yaw)."""
    _avoid = False

    def state(self):
        return {"position": [AT_SHELF["position"][0], AT_SHELF["position"][1], 0.3], "rpy": [0.0, 0.0, AT_SHELF["yaw"]]}


class Base(unittest.TestCase):
    """Every test writes its rows to a temp ledger, pins the env it reads, captures stderr, and never calls a model:
    llm.generate, decide._jev and decide.decide raise unless a test patches them itself."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.object(ledger, "LEDGER", self.tmp / "ledger.jsonl"))
        self.enterContext(mock.patch.dict(os.environ, ENV))
        self.err = io.StringIO()
        self.enterContext(redirect_stderr(self.err))
        self.no_model = {n: self.enterContext(mock.patch(n, side_effect=AssertionError(f"{n} called in a test that hands in its own stub")))
                         for n in ("wtdd.llm.generate", "wtdd.decide._jev", "wtdd.decide.decide")}

    _plan = None

    @classmethod
    def plan(cls) -> dict:
        if Base._plan is None:
            Base._plan = blobs.find(accumulated(), 3)
        return Base._plan

    def shelf(self) -> dict:
        return one(self.plan()["blobs"], "run", cells_of("shelf"))

    def table(self) -> dict:
        return one(self.plan()["blobs"], "blob", cells_of(*GROUPS["table"]))

    def assert_nothing_moved(self, plan: dict, out: dict, msg: str) -> None:
        np.testing.assert_array_equal(out["cls"], plan["cls"], err_msg=msg)
        self.assertEqual(segs(out["segments"]), segs(plan["segments"]), msg)
        self.assertEqual(out["moved"], [], msg)

    def assert_only_1_to_3(self, plan: dict, out: dict) -> None:
        a, b = plan["cls"], out["cls"]
        np.testing.assert_array_equal(a != 0, b != 0, err_msg="a label added or removed a cell")
        changed = a != b
        self.assertTrue(np.all(a[changed] == 1) and np.all(b[changed] == 3), "a label changed a cell other than wall -> slab")


class ClosedList(Base):
    def test_the_list_is_closed_and_has_no_opening(self):
        self.assertEqual(set(blobs.LABELS), CLOSED)
        self.assertEqual(len(blobs.LABELS), len(CLOSED), "a label listed twice")
        self.assertNotIn("opening", blobs.LABELS, "an opening is geometry, and 17's escalate label")
        self.assertEqual(set(blobs.FURNITURE), {"shelf", "table", "stack"})

    def test_no_cv2_and_no_chat_in_the_api_process(self):
        r = subprocess.run([PY, "-c", "import sys, wtdd.dog.blobs; print('cv2' in sys.modules, any(m.startswith('wtdd.chat') for m in sys.modules))"],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertEqual(r.stdout.split(), ["False", "False"], "blobs.py may not load cv2 (the API) nor the chat (a label never escalates)")


class Find(Base):
    def test_the_geometry_is_15s_all_of_it(self):
        g = accumulated()
        plan = blobs.find(g, 3)
        np.testing.assert_array_equal(plan["cls"], floorplan.classes(g, 3))
        self.assertEqual(segs(plan["segments"]), segs(floorplan.segments(g, 3)))
        json.dumps(plan["blobs"])
        self.assertEqual(rows(None), [], "find is a read: no row")

    def test_the_shelf_and_the_far_wall_are_low_runs_and_the_full_height_wall_is_not_a_blob(self):
        bs = self.plan()["blobs"]
        shelf, far = self.shelf(), one(bs, "run", cells_of("wall_b"))
        self.assertGreaterEqual(len(shelf["cells"]), len(cells_of("shelf")) // 2, "the shelf's own run, beyond the wall's thickness")
        self.assertEqual(lattice(far["cells"]), cells_of("wall_b"))
        for b in (shelf, far):
            self.assertLessEqual(abs(b["top_m"] - 0.9), RES + 1e-6, b["geometry_verdict"])
            self.assertTrue(b["grounded"])
            self.assertTrue(b["geometry_verdict"].startswith("wall"), b["geometry_verdict"])
            self.assertIn("grounded", b["geometry_verdict"])
            self.assertIn("straight", b["geometry_verdict"])
        self.assertTrue(1.9 <= shelf["length_m"] <= 2.1, shelf["length_m"])
        wall_a = cells_of("wall_a")
        self.assertFalse([b["id"] for b in bs if lattice(b["cells"]) & wall_a], "a full-height wall is never offered to a model")

    def test_every_non_wall_cell_is_in_exactly_one_blob_one_per_object(self):
        plan = self.plan()
        bs = [b for b in plan["blobs"] if b["kind"] == "blob"]
        for group, names in GROUPS.items():
            self.assertEqual(lattice(one(bs, "blob", cells_of(*names))["cells"]), cells_of(*names), group)
        seen: set = set()
        for b in bs:
            c = lattice(b["cells"])
            self.assertFalse(seen & c, f"{b['id']} shares cells with another blob")
            seen |= c
        oy, ox = round(plan["origin"][1] / RES), round(plan["origin"][0] / RES)
        iy, ix = np.nonzero(np.isin(plan["cls"], (2, 3, 5)))
        self.assertEqual(seen, {(int(x) + ox, int(y) + oy) for x, y in zip(ix, iy)})
        self.assertEqual(len(bs), len(GROUPS))

    def test_ids_are_unique_and_every_cell_is_one_the_lidar_saw(self):
        plan = self.plan()
        ids = [b["id"] for b in plan["blobs"]]
        self.assertEqual(len(ids), len(set(ids)))
        for b in plan["blobs"]:
            self.assertTrue(all(at(plan, plan["cls"], c) != 0 for c in lattice(b["cells"])), b["id"])

    def test_the_verdict_says_grounded_or_floating(self):
        bs = self.plan()["blobs"]
        self.assertIn("floating", self.table()["geometry_verdict"])
        self.assertFalse(self.table()["grounded"])
        box = one(bs, "blob", cells_of("box"))
        self.assertIn("grounded", box["geometry_verdict"])
        self.assertTrue(box["grounded"])


class Bearing(Base):
    def test_right_of_the_camera_is_positive(self):
        t = math.tan(math.radians(20))
        pose = {"position": [0.0, 0.0], "yaw": 0.0}
        self.assertAlmostEqual(blobs.bearing_to([2.0, -2 * t], pose), math.radians(20), places=6)
        self.assertAlmostEqual(blobs.bearing_to([2.0, 2 * t], pose), -math.radians(20), places=6)
        up = {"position": [0.0, 0.0], "yaw": math.pi / 2}
        self.assertAlmostEqual(blobs.bearing_to([0.0, 3.0], up), 0.0, places=6)
        self.assertAlmostEqual(blobs.bearing_to([-1.0, 3.0], up), math.pi / 2 - math.atan2(3.0, -1.0), places=6)
        self.assertAlmostEqual(blobs.bearing_to([math.cos(math.radians(-170)), math.sin(math.radians(-170))],
                                                {"position": [0.0, 0.0], "yaw": math.radians(170)}), -math.radians(20), places=6)

    def test_07s_ray_at_yaw_minus_bearing_passes_through_the_blob(self):
        for pose, xy in ((AT_SHELF, [1.75, -0.3]), (AT_TABLE, [0.4, -2.2]), ({"position": [1.0, 2.0], "yaw": 2.5}, [-1.0, 3.5])):
            b = blobs.bearing_to(xy, pose)
            a, d = pose["yaw"] - b, math.dist(pose["position"], xy)
            got = (pose["position"][0] + d * math.cos(a), pose["position"][1] + d * math.sin(a))
            self.assertAlmostEqual(got[0], xy[0], places=6)
            self.assertAlmostEqual(got[1], xy[1], places=6)

    def test_the_crop_is_a_full_height_strip_07s_bearing_maps_back(self):
        for deg in (-20.0, -10.0, 0.0, 10.0, 20.0):
            box = blobs.crop_box(math.radians(deg), (W, H), 90.0)
            x0, y0, x1, y1 = box
            u = W * (0.5 + math.tan(math.radians(deg)) / 2)
            self.assertEqual((y0, y1), (0, H), "a horizontal crop keeps the frame's full height")
            self.assertTrue(0 <= x0 < u < x1 <= W, (deg, box, u))
            self.assertTrue(32 <= x1 - x0 <= W // 2, (deg, box))
            self.assertLess(abs(objects.bearing(box, W, 90.0) - math.radians(deg)), math.radians(0.5), (deg, box))

    def test_outside_the_field_of_view_is_a_value_error(self):
        for deg in (50.0, -50.0, 120.0):
            with self.assertRaises(ValueError, msg=deg):
                blobs.crop_box(math.radians(deg), (W, H), 90.0)

    def test_the_crop_of_a_synthetic_frame_shows_what_sits_at_that_bearing(self):
        img = frame()
        for deg, want in ((20.0, "red"), (-30.0, "blue")):
            url, sha = blobs.crop(img, blobs.crop_box(math.radians(deg), (W, H), 90.0))
            self.assertTrue(url.startswith("data:image/jpeg;base64,"), url[:40])
            self.assertEqual(sha, sha_of(url))
            self.assertRegex(sha, r"^[0-9a-f]{64}$")
            c = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
            r, g, b = c.getpixel((c.width // 2, c.height // 2))
            self.assertTrue((r > 150 > g and b < 100) if want == "red" else (b > 150 > r and g < 100), (deg, (r, g, b)))


class Line(Base):
    def test_words_only_one_line_grounded_or_floating(self):
        for b in self.plan()["blobs"]:
            s = blobs.line(b, 2.3)
            self.assertFalse(re.search(r"\d", s), f"a digit in the line to the models: {s!r}")
            self.assertNotIn("\n", s)
            self.assertIn("grounded" if b["grounded"] else "floating", s, s)


class Erase(Base):
    def test_a_shelf_label_moves_the_shelf_off_the_wall_layer_and_both_walls_stay(self):
        plan, shelf = self.plan(), self.shelf()
        before = plan["cls"].copy()
        out = blobs.erase(plan, [rec(shelf, "shelf", 0.91)])
        np.testing.assert_array_equal(plan["cls"], before, err_msg="erase touched the plan it was given")
        self.assertEqual(out["moved"], [shelf["id"]])
        grey = {c for c in cells_of("shelf") if at(out, out["cls"], c) == 3}
        self.assertGreaterEqual(len(grey), len(cells_of("shelf")) // 2, "the shelf's run is still a wall")
        for wall in ("wall_a", "wall_b"):
            self.assertTrue(all(at(out, out["cls"], c) == 1 for c in cells_of(wall)), f"{wall} left the wall layer")
        self.assert_only_1_to_3(plan, out)
        oy, ox = round(plan["origin"][1] / RES), round(plan["origin"][0] / RES)
        iy, ix = np.nonzero(plan["cls"] != out["cls"])
        self.assertLessEqual({(int(x) + ox, int(y) + oy) for x, y in zip(ix, iy)}, cells_of("shelf"), "a shelf label moved a cell that is not the shelf")
        self.assertEqual(len(out["segments"]), len(plan["segments"]) - 1)
        self.assertLessEqual(set(segs(out["segments"])), set(segs(plan["segments"])), "a segment moved or appeared")
        (gone,) = set(segs(plan["segments"])) - set(segs(out["segments"]))
        for x, y in (gone[:2], gone[2:4]):
            self.assertTrue(1.7 - RES <= x <= 2.0 + RES and -1.0 - RES <= y <= 1.0 + RES, f"the dropped segment {gone} is not the shelf's")

    def test_a_furniture_word_never_greys_the_full_height_wall(self):
        """A label kept from an earlier plan, where this run was low and offered (the far wall seen only to 0.9 m at the
        first stop), named shelf at p 0.95 and covering every cell of the run that is full height in this plan (the dog
        walked closer and the wall filled in): the run stays a wall, its line stays drawn, and the refusal is a WARN."""
        plan = self.plan()
        ox, oy = plan["origin"]
        metres = [[[ox + a * RES, oy + b * RES] for a, b in run] for run in plan["runs"]]
        k = max(range(len(metres)), key=lambda k: len(lattice(metres[k]) & cells_of("wall_a")))
        self.assertLessEqual(cells_of("wall_a"), lattice(metres[k]), "the run picked is not wall_a's")
        self.assertNotIn(f"r{k}", [b["id"] for b in plan["blobs"]], "the full-height wall was offered to a model")
        stale = {"blob_id": "r9", "kind": "run", "cells": metres[k], "xy": np.mean(metres[k], axis=0).tolist(),
                 "geometry_verdict": "wall (grounded, straight 5.3 m, 0.9 m high)", "label": "shelf", "p": 0.95, "model": "jev"}
        out = blobs.erase(plan, [stale])
        self.assert_nothing_moved(plan, out, "a furniture word greyed the full-height wall")
        self.assertTrue(all(at(out, out["cls"], c) == 1 for c in cells_of("wall_a")), "wall_a left the wall layer")
        self.assertEqual(out["refused"], [f"r{k}"])
        self.assertTrue([l for l in self.err.getvalue().splitlines() if l.startswith("[wtdd:blobs] WARN") and "refused" in l],
                        self.err.getvalue()[-600:])

    def test_below_the_threshold_nothing_moves(self):
        plan = self.plan()
        self.assert_nothing_moved(plan, blobs.erase(plan, [rec(self.shelf(), "shelf", 0.69)]), "p 0.69 < 0.7 moved the shelf")
        self.assert_nothing_moved(plan, blobs.erase(plan, [rec(self.shelf(), "shelf", 0.69)], threshold=0.7), "p 0.69 < 0.7")

    def test_a_wall_answer_for_the_table_never_makes_it_a_wall(self):
        plan = self.plan()
        out = blobs.erase(plan, [rec(self.table(), "wall", 0.99)])
        self.assert_nothing_moved(plan, out, "a wall label on the table changed the map")
        self.assertFalse([c for c in cells_of(*GROUPS["table"]) if at(out, out["cls"], c) == 1], "a model made the table a wall")

    def test_a_label_names_a_non_wall_blob_and_moves_nothing(self):
        plan = self.plan()
        self.assert_nothing_moved(plan, blobs.erase(plan, [rec(self.table(), "table", 0.99)]), "a table label reclassified cells")

    def test_every_blob_called_wall_moves_nothing(self):
        plan = self.plan()
        self.assert_nothing_moved(plan, blobs.erase(plan, [rec(b, "wall", 0.99) for b in plan["blobs"]]), "a wall label moved something")

    def test_delete_every_model_call_and_nothing_on_the_map_moves(self):
        plan = self.plan()
        self.assert_nothing_moved(plan, blobs.erase(plan, []), "no labels at all")
        self.assert_nothing_moved(plan, blobs.erase(plan, [rec(b, "unknown", 0.0, model="stub") for b in plan["blobs"]]), "the stub's labels")

    def test_a_failed_label_moves_nothing(self):
        plan = self.plan()
        failed = rec(self.shelf(), None, None, error="RuntimeError: openrouter 502: bad gateway")
        self.assert_nothing_moved(plan, blobs.erase(plan, [failed]), "a FAILED label moved the shelf")

    def test_opening_and_any_word_off_the_list_are_refused(self):
        plan = self.plan()
        for word in ("opening", "door", "Shelf"):
            with self.assertRaises(ValueError, msg=word):
                blobs.erase(plan, [rec(self.shelf(), word, 0.99)])

    def test_a_label_never_adds_a_cell_even_when_it_names_empty_ones(self):
        plan, shelf = self.plan(), self.shelf()
        empty = [[gx * RES, gy * RES] for gx in range(20, 30) for gy in range(-20, 20)]   # open floor in front of the shelf
        self.assertTrue(all(at(plan, plan["cls"], c) == 0 for c in lattice(empty)))
        out = blobs.erase(plan, [{**rec(shelf, "shelf", 0.99), "cells": shelf["cells"] + empty}])
        self.assert_only_1_to_3(plan, out)
        self.assertTrue(all(at(out, out["cls"], c) == 0 for c in lattice(empty)), "a label filled open floor")


class Doorway(Base):
    """A wall with a doorway in it: two low runs on one line, a 0.8 m gap between them. A model answering wall for the
    runs either side must not close the gap, and erasing them must not open anything either."""

    def setUp(self):
        super().setUp()
        self.grid = accumulated(ff.write(self.tmp / "doorway.npz", DOORWAY, ff.ORIGINS))
        self.dplan = blobs.find(self.grid, 3)
        self.runs = [b for b in self.dplan["blobs"] if b["kind"] == "run"]

    def gap_m(self, segs) -> float:
        xs = sorted(v for s in segs for v in (s[0], s[2]))
        return xs[2] - xs[1]

    def test_the_doorway_is_two_runs_and_a_gap_of_empty_cells(self):
        self.assertEqual(len(self.runs), 2)
        self.assertEqual({frozenset(lattice(b["cells"])) for b in self.runs},
                         {frozenset(cells_of("wall_l", world=DOORWAY)), frozenset(cells_of("wall_r", world=DOORWAY))})
        self.assertEqual(len(self.dplan["segments"]), 2)
        self.assertGreaterEqual(self.gap_m(self.dplan["segments"]), 0.75)

    def test_a_stub_that_answers_wall_either_side_leaves_the_gap_a_gap(self):
        said = []

        def vision(url, line):
            said.append(line)
            return {"text": "a plain wall", "model": "vision-stub"}
        out = blobs.label_stop(self.grid, frame(()), AT_DOORWAY, 90.0, 3, vision=vision, choose=lambda text, labels: ("wall", 0.99, "jev-stub", "{}"))
        self.assertEqual(len(out["labels"]), 2, "both runs are in a 90 degree view")
        self.assertEqual({r["label"] for r in out["labels"]}, {"wall"})
        after = blobs.erase(out["plan"], out["labels"])
        self.assert_nothing_moved(out["plan"], after, "a wall answer moved something")
        self.assertTrue(all(at(after, after["cls"], c) == 0 for c in DOOR_CELLS), "the doorway was closed")
        self.assertEqual(len(after["segments"]), 2, "the two runs became one line")
        self.assertGreaterEqual(self.gap_m(after["segments"]), 0.75)

    def test_erasing_both_runs_never_fills_the_doorway(self):
        after = blobs.erase(self.dplan, [rec(b, "shelf", 0.99) for b in self.runs])
        self.assertEqual(sorted(after["moved"]), sorted(b["id"] for b in self.runs))
        self.assert_only_1_to_3(self.dplan, after)
        self.assertEqual(segs(after["segments"]), [])
        self.assertTrue(all(at(after, after["cls"], c) == 0 for c in DOOR_CELLS))


class Label(Base):
    def setUp(self):
        super().setUp()
        self.seen: dict = {}

    def vision(self, text="a wooden shelf with boxes on it"):
        def f(url, line):
            self.seen.update(url=url, line=line, calls=self.seen.get("calls", 0) + 1)
            return {"text": text, "model": "vision-stub"}
        return f

    def choose(self, answer=("shelf", 0.91, "jev-stub", '{"answers": {"stop": {"choice": "shelf"}}}')):
        def f(text, labels):
            self.seen.update(text=text, labels=list(labels))
            return answer
        return f

    def test_one_row_with_both_raw_replies_the_crop_sha_and_the_latency(self):
        shelf = self.shelf()
        r = blobs.label(shelf, frame(), AT_SHELF, FOV, vision=self.vision(), choose=self.choose())
        self.assertEqual((r["blob_id"], r["label"], r["p"], r["erase"]), (shelf["id"], "shelf", 0.91, True))
        self.assertEqual(r["cells"], shelf["cells"])
        self.assertIn("a wooden shelf with boxes on it", self.seen["text"], "the vision reply goes through the chooser")
        self.assertEqual(self.seen["labels"], list(blobs.LABELS))
        (row,) = rows()
        self.assertEqual(rows(None), [row], "one row per blob, nothing else")
        self.assertEqual((row["ok"], row["agent"]), (True, "blobs"))
        a = row["args"]
        self.assertEqual((a["blob_id"], a["kind"], a["cells"], a["geometry_verdict"]), (shelf["id"], "run", len(shelf["cells"]), shelf["geometry_verdict"]))
        self.assertEqual(a["crop_sha"], sha_of(self.seen["url"]), "the row names the photo the model saw")
        self.assertEqual(a["line"], self.seen["line"])
        self.assertFalse(re.search(r"\d", a["line"]), a["line"])
        self.assertIn("shift_id", a)
        for k, v in {"label": "shelf", "p": 0.91, "model": "jev-stub", "erase": True}.items():
            self.assertEqual(row["state_after"][k], v, k)
        self.assertIn("a wooden shelf with boxes on it", row["response_or_error"])
        self.assertIn('"choice": "shelf"', row["response_or_error"])
        self.assertIsInstance(row["latency_ms"], int)
        self.assertGreaterEqual(row["latency_ms"], 0)

    def test_below_the_threshold_the_row_says_it_stays_a_wall(self):
        r = blobs.label(self.shelf(), frame(), AT_SHELF, FOV, vision=self.vision(), choose=self.choose(("shelf", 0.6, "jev-stub", "{}")))
        self.assertEqual((r["label"], r["p"], r["erase"]), ("shelf", 0.6, False))
        self.assertFalse(rows()[0]["state_after"]["erase"])

    def test_a_failed_call_is_a_failed_row_and_no_label(self):
        def boom(url, line):
            raise RuntimeError("openrouter 502: bad gateway")
        r = blobs.label(self.shelf(), frame(), AT_SHELF, FOV, vision=boom, choose=self.choose())
        self.assertEqual((r["label"], r["p"]), (None, None))
        self.assertIn("openrouter 502", r["error"])
        self.assertNotIn("text", self.seen, "the chooser ran on a failed photo")
        (row,) = rows()
        self.assertFalse(row["ok"])
        self.assertIn("openrouter 502", row["response_or_error"])
        self.assert_nothing_moved(self.plan(), blobs.erase(self.plan(), [r]), "a FAILED label moved the shelf")

    def test_opening_or_a_p_out_of_range_from_the_chooser_is_failed(self):
        for answer in (("opening", 0.95, "jev-stub", "{}"), ("shelf", 1.4, "jev-stub", "{}"), ("door", 0.9, "jev-stub", "{}")):
            r = blobs.label(self.shelf(), frame(), AT_SHELF, FOV, vision=self.vision(), choose=self.choose(answer))
            self.assertEqual((r["label"], r["p"]), (None, None), answer)
            self.assertIn(str(answer[0]) if answer[0] != "shelf" else "1.4", r["error"], answer)
        self.assertEqual([x["ok"] for x in rows()], [False, False, False])

    def test_nothing_escalates_no_decided_row_no_chat(self):
        for word in ("hazard", "person"):
            blobs.label(self.shelf(), frame(), AT_SHELF, FOV, vision=self.vision(), choose=self.choose((word, 0.97, "jev-stub", "{}")))
        self.assertEqual([r["tool"] for r in rows(None)], ["blob.labelled", "blob.labelled"])
        self.no_model["wtdd.decide.decide"].assert_not_called()

    def test_the_stub_is_unknown_p_0_no_model_call_and_says_stub(self):
        with mock.patch.dict(os.environ, {"WTDD_BLOBS_LABEL": "stub"}):
            r = blobs.label(self.shelf(), frame(), AT_SHELF, FOV)
        self.assertEqual((r["label"], r["p"], r["erase"], r["source"]), ("unknown", 0.0, False, "stub"))
        for n, m in self.no_model.items():
            m.assert_not_called()
        (row,) = rows()
        self.assertEqual((row["ok"], row["app"], row["cached"], row["source"]), (True, "stub", True, "stub"))
        self.assertEqual((row["state_after"]["label"], row["state_after"]["p"]), ("unknown", 0.0))
        self.assertIn("stub", row["response_or_error"].lower())
        self.assert_nothing_moved(self.plan(), blobs.erase(self.plan(), [r]), "the stub's label moved something")
        self.assertIn("DEMO_CACHE", Path(blobs.__file__).read_text())

    def test_the_live_pair_is_llm_generate_with_the_photo_then_decides_jev_choice(self):
        gen = mock.MagicMock(return_value={"text": "a shelf", "model": "x-ai/grok-4.20", "usage": {}, "finish_reason": "stop", "raw": {}})
        jev = mock.MagicMock(return_value=("shelf", 0.91, "typesafe/jev-1.13", '{"id": "sys1-test"}'))
        with mock.patch("wtdd.llm.generate", gen), mock.patch("wtdd.decide._jev", jev):
            r = blobs.label(self.shelf(), frame(), AT_SHELF, FOV)
        self.assertEqual((r["label"], r["p"], r["source"]), ("shelf", 0.91, "live"))
        gen.assert_called_once()
        self.assertEqual(gen.call_args.args[0], "blobs")
        msgs = gen.call_args.args[1]
        parts = [p for m in msgs if isinstance(m.get("content"), list) for p in m["content"]]
        images = [p["image_url"]["url"] for p in parts if p.get("type") == "image_url"]
        self.assertEqual(len(images), 1, "one photo per blob")
        words = " ".join([m["content"] for m in msgs if isinstance(m.get("content"), str)] + [p.get("text", "") for p in parts])
        for w in blobs.LABELS:
            self.assertIn(w, words, f"the ask does not offer {w}")
        jev.assert_called_once()
        self.assertIn("a shelf", jev.call_args.args[0])
        self.assertEqual(list(jev.call_args.args[1]), list(blobs.LABELS))
        (row,) = rows()
        self.assertEqual((row["app"], row["source"], row["cached"]), ("openrouter", "live", False))
        self.assertEqual(row["args"]["crop_sha"], sha_of(images[0]))
        self.assertEqual(row["state_after"]["model"], "typesafe/jev-1.13")
        self.no_model["wtdd.decide.decide"].assert_not_called()


class Stop(Base):
    def choose(self, word):
        return lambda text, labels: (word, 0.91, "jev-stub", "{}")

    def vision(self, url, line):
        return {"text": "something", "model": "vision-stub"}

    def test_only_what_is_in_the_cameras_view_is_labelled(self):
        out = blobs.label_stop(accumulated(), frame(()), AT_SHELF, FOV, 3, vision=self.vision, choose=self.choose("shelf"))
        (r,) = out["labels"]
        self.assertEqual(lattice(r["cells"]), lattice(one(out["plan"]["blobs"], "run", cells_of("shelf"))["cells"]))
        self.assertEqual(len(out["skipped"]), len(out["plan"]["blobs"]) - 1)
        self.assertEqual(len(rows()), 1, "a blob out of view has no row")
        self.assertTrue([l for l in self.err.getvalue().splitlines() if l.startswith("[wtdd:blobs]") and "labelled=1" in l], self.err.getvalue()[-600:])

    def test_a_wall_answer_at_the_table_leaves_the_table_grey(self):
        out = blobs.label_stop(accumulated(), frame(()), AT_TABLE, FOV, 3, vision=self.vision, choose=self.choose("wall"))
        (r,) = out["labels"]
        self.assertEqual(lattice(r["cells"]), cells_of(*GROUPS["table"]))
        after = blobs.erase(out["plan"], out["labels"])
        self.assert_nothing_moved(out["plan"], after, "a wall answer at the table changed the map")

    def test_nothing_in_view_is_a_warn_and_no_row(self):
        out = blobs.label_stop(accumulated(), frame(()), AT_NOTHING, FOV, 3, vision=self.vision, choose=self.choose("shelf"))
        self.assertEqual(out["labels"], [])
        self.assertEqual(rows(), [])
        self.assertTrue([l for l in self.err.getvalue().splitlines() if l.startswith("[wtdd:blobs] WARN")], self.err.getvalue()[-600:])


class Serve(Base):
    def session(self, grid=None, body=None):
        from . import session as sm
        self.enterContext(mock.patch.object(sm, "GRID_FILE", self.tmp / "grid.json"))
        s = sm.DogSession()
        self.addCleanup(stop, s)
        s.grid, s.cal, s.body = grid if grid is not None else accumulated(), dict(CAL), body
        self.enterContext(mock.patch.object(s, "snapshot", return_value=jpeg(frame(()))) if body else
                          mock.patch.object(s, "snapshot", side_effect=AssertionError("a press never connects to the dog")))
        return s

    def live(self, word="shelf", p=0.91):
        gen = mock.MagicMock(return_value={"text": f"a {word}", "model": "x-ai/grok-4.20", "usage": {}, "finish_reason": "stop", "raw": {}})
        self.enterContext(mock.patch("wtdd.llm.generate", gen))
        self.enterContext(mock.patch("wtdd.decide._jev", mock.MagicMock(return_value=(word, p, "typesafe/jev-1.13", "{}"))))

    def test_the_press_labels_what_is_in_view_and_the_floor_plan_greys_the_shelf(self):
        s = self.session(body=FakeBody())
        self.live()
        empty = s.blobs_px()
        self.assertEqual(empty["labels"], [])
        self.assertTrue(empty["why"].startswith("no labels"), empty["why"])
        s.floorplan(3)
        before = s.floorplan_px(3)
        s.blobs_label(3)
        (row,) = rows()
        self.assertEqual((row["ok"], row["state_after"]["label"]), (True, "shelf"))
        after = s.floorplan_px(3)
        n = before["classes"]["wall"] - after["classes"]["wall"]
        self.assertEqual(len(after["segments_px"]), len(before["segments_px"]) - 1, "the shelf's line is still drawn")
        self.assertGreaterEqual(n, len(cells_of("shelf")) // 2, "the shelf's run did not leave the wall layer")
        self.assertEqual(after["classes"]["slab"], before["classes"]["slab"] + n, "a greyed run's cells are slab, none lost, none added")
        self.assertEqual((after["classes"]["tall"], after["classes"]["low"]), (before["classes"]["tall"], before["classes"]["low"]))
        got = s.blobs_px()
        self.assertEqual(got["source"], "session")
        (lab,) = got["labels"]
        self.assertEqual((lab["label"], lab["p"], lab["blob_id"]), ("shelf", 0.91, self.shelf()["id"]))
        self.assertTrue(lab["geometry_verdict"].startswith("wall"))
        want = occupancy.to_map_px([lab["xy"]], CAL)[0].tolist()
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(lab["pos_px"], want)), (lab["pos_px"], want))
        self.assertEqual(len(rows(None)), 2, "reads write no row: the floor plan press and the one label")
        json.dumps(got)

    def test_greyed_is_what_the_floor_plan_moved_at_the_threshold_of_the_read(self):
        """The planted file says erase true for the shelf (stamped at 0.7). Read at 0.95, the floor plan moves nothing, so
        GET /dog/blobs may not say a run was greyed; read at 0.7, both say the shelf's run."""
        s = self.session(body=None)
        s.floorplan(3)
        f = str(Path(blobs.__file__).parent / "fixtures" / "blobs.json")
        for thr, moved in (("0.95", []), ("0.7", [self.shelf()["id"]])):
            with mock.patch.dict(os.environ, {"WTDD_BLOBS": f, "WTDD_DECIDE_THRESHOLD": thr}):
                b, fp = s.blobs_px(), s.floorplan_px(3)
            self.assertEqual(sum(1 for x in b["labels"] if x["erase"]), len(moved), f"threshold {thr}: a label says greyed, the map did not")
            self.assertEqual((b["moved"], fp["moved"]), (moved, moved), f"threshold {thr}")
        self.assertEqual(rows(None), [r for r in rows(None) if r["tool"] == "dog.floorplan"], "reads write no row")

    def test_a_press_with_no_dog_is_one_failed_row_and_the_page_says_failed(self):
        s = self.session(body=None)
        with self.assertRaises(RuntimeError):
            s.blobs_label(3)
        (row,) = rows()
        self.assertFalse(row["ok"])
        # args.threshold on every blob.labelled row is WTDD_DECIDE_THRESHOLD (a p), never the LiDAR count the press was at
        self.assertEqual(row["args"]["lidar_threshold"], 3)
        self.assertIsNone(row["args"]["threshold"])
        got = s.blobs_px()
        self.assertEqual(got["labels"], [])
        self.assertIn("FAILED", got["why"])

    def test_a_press_with_no_field_of_view_fails_loud_naming_the_key(self):
        s = self.session(body=FakeBody())
        with mock.patch.dict(os.environ, {"WTDD_CAM_FOV_DEG": ""}), self.assertRaises((RuntimeError, ValueError)):
            s.blobs_label(3)
        (row,) = rows()
        self.assertFalse(row["ok"])
        self.assertIn("WTDD_CAM_FOV_DEG", row["response_or_error"])

    def test_the_api_serves_the_planted_labels_under_WTDD_BLOBS_and_the_press(self):
        from http.server import ThreadingHTTPServer
        from .. import api
        from . import session as sm
        s = self.session(body=None)
        self.enterContext(mock.patch.object(sm.DogSession, "_inst", s))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        get = lambda path: json.loads(urllib.request.urlopen(base + path, timeout=30).read())   # noqa: E731
        s.floorplan(3)
        n0 = len(get("/dog/floorplan?threshold=3")["segments_px"])
        planted = self.tmp / "blobs.json"
        planted.write_text(json.dumps({"labels": [rec(self.shelf(), "shelf", 0.91, model="fixture"),
                                                  rec(self.table(), None, None, model="fixture", error="RuntimeError: openrouter 502: bad gateway")]}))
        with mock.patch.dict(os.environ, {"WTDD_BLOBS": str(planted)}):
            b = get("/dog/blobs")
            fp = get("/dog/floorplan?threshold=3")
        self.assertTrue(b["source"].startswith("fixture"), b["source"])
        self.assertIn("blobs.json", b["source"])
        byid = {x["blob_id"]: x for x in b["labels"]}
        self.assertEqual((byid[self.shelf()["id"]]["label"], byid[self.shelf()["id"]]["p"]), ("shelf", 0.91))
        self.assertEqual(len(byid[self.shelf()["id"]]["pos_px"]), 2)
        failed = byid[self.table()["id"]]
        self.assertEqual((failed["label"], failed["p"]), (None, None))
        self.assertIn("openrouter 502", failed["error"])
        self.assertEqual(len(fp["segments_px"]), n0 - 1, "the planted shelf label did not grey the shelf's run")
        req = urllib.request.Request(base + "/dog/blobs", data=b'{"threshold": 3}', headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=60)
        self.assertEqual(e.exception.code, 500)
        self.assertEqual([r["ok"] for r in rows()], [False])
        self.assertIn("FAILED", get("/dog/blobs")["why"])


class Planted(Base):
    def test_the_planted_fixture_names_only_cells_the_lidar_saw(self):
        f = Path(blobs.__file__).parent / "fixtures" / "blobs.json"
        labs = json.loads(f.read_text())["labels"]
        plan = self.plan()
        thr = float(ENV["WTDD_DECIDE_THRESHOLD"])
        for r in labs:
            self.assertIn(r["label"], CLOSED | {None}, r)
            self.assertTrue(all(at(plan, plan["cls"], c) != 0 for c in lattice(r["cells"])), f"{r['blob_id']} names a cell the LiDAR never saw")
        shelf = lattice(self.shelf()["cells"])
        self.assertTrue([r for r in labs if r["label"] in blobs.FURNITURE and r["p"] >= thr and len(lattice(r["cells"]) & shelf) * 2 > len(shelf)],
                        "no planted furniture label over the threshold on the shelf's run")
        self.assertTrue([r for r in labs if r["label"] is None and r.get("error")], "no planted FAILED label")
        self.assertEqual(blobs.erase(plan, labs)["moved"], [self.shelf()["id"]])


if __name__ == "__main__":
    unittest.main()
