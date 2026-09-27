"""Tests for wtdd/dog/scout_zones.py (roadmap item 19): the scout proposes red zones from its own cells; a person makes
them rules. Every LiDAR blob the detector boxes and Jev labels a hazard becomes a PROPOSED zone made of its own counted
cells, with the photo, the label and p; one named tap confirms it into 04's `nogo: true` schema or dismisses it;
nothing is refused on a proposal alone, and every model call is its own row. Run:

    python -m unittest wtdd.dog.test_scout_zones
    python -m wtdd.evals --scenario scout          (the eval half; its graders are tested in class Eval below)

RED until scout_zones.py exists (and wtdd/nogo.py, 04's file vendored byte for byte as 06 did, until 04 merges).
Everything runs on the synthetic fixtures (make_voxel_frames' world, make_objects_fixture's two boxes at POSE with
FOV_DEG 90, make_scout_fixture's page bodies, wtdd/fixtures/evals/make_scout.py's ledgers); nothing here has seen the
real dog, a detector or a model. Expected cells are computed from the fixtures' declared world with the bound stated
below, never from the module's own output; map pixels go through occupancy.to_map_px (01's proof against nav.to_map).

The bound (the head's, roadmap 19 "Routing"): a blob is the 8-connected cells seen threshold+ times, flood-filled from
07's hit cell, keeping a cell only when (1) its bearing from the dog lies inside the box's angular extent, the two edge
bearings objects.bearing gives for the box's left and right columns, each widened by the half-cell angle
atan(RES / 2 / d) at the cell's distance d (a cell is in when part of it can be; the lattice point alone would drop the
edge cells on floating-point noise), and (2) its distance d from the dog is in [hit.dist_m - RES, hit.dist_m + DEPTH_M].
Unbounded, the fill takes the whole connected wall (WALL_A: 108 cells). The polygon is the monotone-chain hull of the
cells' corners (+-RES/2) in map px, padded PAD_PX on every side (the corners' hull grown by a PAD_PX square), so every
cell centre sits at least PAD_PX inside it and 04's hit() (samples every STEP_PX = 10 px) cannot step over a
one-cell-thin zone. The pad is a stated rule on points, drawn dashed; it is not geometry a model drew.

The contract under test (wtdd/dog/scout_zones.py):
  DEPTH_M = 1.0 · PAD_PX = 15 · SCOUT_LABELS = ["table", "sharp_object", "blocked_way", "not_a_hazard"] (no "opening":
  a hole has no COCO class and the grid's band has no floor) · JEV_URL · CELL_RGB (the replay PNG's cell colour)
  PROPOSAL_KEYS = id, object_id, kind, label, p, app, cells, cells_px, poly, thumb, photo, dist_m, area_m2, ts
  blob(grid, pose, box, hit, frame_w, fov_deg, threshold=occupancy.THRESHOLD) -> [[x_m, y_m], ...] lattice points
  polygon(cells, cal, resolution) -> [[px, py], ...] ints, >= 3 points; no cells is a ValueError
  decide_stub(q) / decide_live(q) -> {label, p, probabilities, model, raw, app, cached}; q = {kind, conf, state, labels}
      stub (# DEMO_CACHE): dining table, bench, chair -> table; knife, scissors -> sharp_object; anything else ->
      not_a_hazard; p = the detector's conf; probabilities {label: p}; model None; app "stub"; cached True
      live: one requests.post to JEV_URL, a System One Choice over q["labels"] with criteria, Bearer JEV_API_KEY;
      p = probabilities[choice] (never `confidence`); non-200, or a choice outside the labels, raises
  decider() -> decide_live when JEV_API_KEY is set, else decide_stub (read at the point of use)
  Refused(Exception) with .code 400 | 404 | 409
  Proposals(append=ledger.append, decide=None (= decider()), photo_dir=None (= ~/Pictures/wtdd), map_path=None (= field.MAP))
    .feed(objs, frame, pose, grid, cal, fov_deg, threshold=occupancy.THRESHOLD, grid_lock=None)
        objs = 07's Store.to_list(); every placed object (pos_px set) not handled before is handled once: its blob and
        polygon under grid_lock, then (outside every lock) one zone.decided row from decide() with the words-only
        state; when the label is not not_a_hazard and p >= WTDD_DECIDE_THRESHOLD (default 0.7), one zone.proposed row
        and an open proposal "z<n>" whose photo is the detector frame copied once into photo_dir with its sha256. A
        thing whose cells overlap an open, a dismissed or a scout zone on the map is the same thing: logged, no row, no
        model call. A failed call: zone.decided ok false, no proposal, listed in state()["failed"], never retried. An
        unreadable frame: zone.proposed ok false naming the file, no call, never retried. One stderr line per call;
        a WARN when placed objects were handled and nothing was proposed.
    .confirm(id, by, version=None) -> {ok, zone, _version}: blank by -> Refused 400, no open id -> 404, a version not
        the map file's int(mtime) -> 409, each with a zone.confirmed row ok false and the map untouched; else the entry
        {name: next free nogo-<n>, label: "<label> · <p:.2f> · scout", poly, nogo: true, source: "scout", cells,
        proposal: id, by} is checked by nogo.zones(), appended to the map's zones, the previous map kept as
        map.prev.json, one zone.confirmed row {id, zone, by}, and the proposal closed
    .dismiss(id, by) -> one zone.dismissed row {id, by}; blank by 400, no open id 404 (a failed row each)
    .state() -> {n, proposals: [PROPOSAL_KEYS...], failed: [{object_id, kind, error, ts}], why?}  why whenever n is 0
  rows: agent "scout"; tools zone.decided (never "decided": 11's grade_decide owns that name), zone.proposed,
        zone.confirmed, zone.dismissed; every args has shift_id; the stub's rows say cached true, source "stub"; no row
        carries a base64 thumbnail
        zone.decided args {object_id, kind, labels, label, p, model, probabilities, threshold, shift_id},
        state_before {state, labels}, response_or_error = the raw reply or the error, latency_ms = the call's round trip
        zone.proposed args {id, object_id, kind, label, p, cells, cells_n, poly, photo {path, sha256, bytes}, dist_m,
        area_m2, shift_id}
  DogSession.scout (one Proposals) and DogSession.scout_state() -> the GET /dog/scout body with source "session"; the
        objects thread runs 07's tick, then scout_feed(), then 07's draft_due (a model call), the draft even when the feed raises
  GET /dog/scout (WTDD_SCOUT=<file>: # DEMO_CACHE, serves that file, source names it) · POST /dog/scout {id, action,
        by, _version} -> 200 | 400 | 404 | 409, the refusals before anything is written
  python -m wtdd.dog.scout_zones --replay <npz> --watch <watch json> --pose x,y,yaw --fov DEG --png <out> [--threshold N]
        the stub only, no ledger row; the occupancy PNG with every proposed cell a PNG_SCALE square in CELL_RGB; exit 2
        (WARN) when nothing is proposed
  wtdd.evals: grade_scout(rows, m) -> (ok, why, detail), unsafe_scout(rows, m) -> [why], run_scout(fixture=None) ->
        [one dry trial]; `--scenario scout` grades wtdd/fixtures/evals/scout.jsonl against scout-map.json; --write
        refuses a dry trial and leaves README.md alone
"""
from __future__ import annotations
import base64
import contextlib
import hashlib
import io
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from ..config import ROOT
from .. import config, evals, field, ledger
from . import lidar, objects, occupancy
from .fixtures import make_objects_fixture as ofx
from .fixtures import make_scout_fixture as sfx
from .fixtures import make_voxel_frames as fx

from . import scout_zones   # RED until it exists: ModuleNotFoundError, the whole module errors
from .. import nogo         # 04's wtdd/nogo.py, vendored byte for byte until 04 merges (absent on 07's base)

RES = fx.RES
CAL, FOV, POSE, W = ofx.CAL, ofx.FOV_DEG, ofx.POSE, ofx.W
CHAIR, BACKPACK = ofx.BOXES
THR = 3
PY = sys.executable
LABELS = ["table", "sharp_object", "blocked_way", "not_a_hazard"]
EVALS = ROOT / "wtdd" / "fixtures" / "evals"
WALL_A_CELLS = (fx.WALL_A["y"][1] - fx.WALL_A["y"][0]) * (fx.WALL_A["x"][1] - fx.WALL_A["x"][0])   # 108: the whole wall
NAME = "Sam Stand-in"
_SCRATCH = Path(tempfile.mkdtemp(prefix="wtdd-scout-test-"))
_patches: list = []


def setUpModule():   # no test writes the real ledger (nogo.refuse and the default append both go through ledger.LEDGER)
    p = mock.patch.object(ledger, "LEDGER", _SCRATCH / "ledger.jsonl")
    p.start()
    _patches.append(p)


def tearDownModule():
    for p in _patches:
        p.stop()
    shutil.rmtree(_SCRATCH, ignore_errors=True)


def accumulated() -> occupancy.Grid:
    fr = [lidar.decode(fx.decode_wire(b)) for b in fx.blobs()]
    g = occupancy.Grid.from_frame(fr[0])
    for d in fr:
        g.update_frame(d)
    return g


def hand_grid(*point_sets: list, times: int = THR) -> occupancy.Grid:
    """A grid from (N, 2) metre points, each set counted `times` frames (Grid.update skips the z band for 2-column points)."""
    g = occupancy.Grid(RES, (-3.2, -3.2), "odom")
    for pts in point_sets:
        for _ in range(times):
            g.update(np.array(pts, dtype=np.float64))
    return g


def frame() -> dict:
    d = json.loads(ofx.WATCH_JSON.read_text())
    d["file"] = str(ofx.FRAME)
    return d


def edge(u: float) -> float:
    return objects.bearing([u, 0, u, 0], W, FOV)


def in_bound(cell, xyxy, hit, pose=POSE, tol: float = 0.0) -> bool:
    """The stated bound, computed here from the pose and the box, independent of the module."""
    x, y = cell
    px, py = pose["position"]
    d = math.hypot(x - px, y - py)
    a = -((math.atan2(y - py, x - px) - pose["yaw"] + math.pi) % (2 * math.pi) - math.pi)   # camera-right positive
    eps = math.atan(RES / 2 / d)
    return (edge(xyxy[0]) - eps - tol <= a <= edge(xyxy[2]) + eps + tol
            and hit["dist_m"] - RES - tol <= d <= hit["dist_m"] + scout_zones.DEPTH_M + tol)


def wall_a_expected(xyxy, hit) -> set:
    x = fx.WALL_A["x"][0] * RES
    return {(round(x, 3), round(k * RES, 3)) for k in range(*fx.WALL_A["y"]) if in_bound((x, k * RES), xyxy, hit)}


def as_set(cells) -> set:
    return {(round(c[0], 3), round(c[1], 3)) for c in cells}


def px_of(cells) -> list:
    return occupancy.to_map_px([list(c) for c in cells], CAL).tolist()


def dist_to_outline(p, poly) -> float:
    best = math.inf
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.dist(p, (ax + t * dx, ay + t * dy)))
    return best


def chair_hit(g) -> dict:
    return objects.nearest_blob(g, POSE["position"], POSE["yaw"] - objects.bearing(CHAIR["xyxy"], W, FOV), THR)


def load(path) -> list:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stop(s) -> None:
    s.loop.call_soon_threadsafe(s.loop.stop)
    while s.loop.is_running():
        time.sleep(0.01)
    s.loop.close()


class Fake:
    """A requests.Response stand-in for the vendored Jev call."""

    def __init__(self, status: int, body):
        self.status_code = status
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return json.loads(self.text)


def jev_reply(body: dict, choice: str, probabilities: dict, confidence: float = 0.75) -> dict:
    q = next(iter(body["questions"]))
    return {"id": "sys1-test", "model": "typesafe/jev-1.13", "provider": "typesafe",
            "answers": {q: {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": probabilities}}}


class Constants(unittest.TestCase):
    def test_the_heads_bound_pad_and_labels(self):
        self.assertEqual(scout_zones.DEPTH_M, 1.0)
        self.assertEqual(scout_zones.PAD_PX, 15)
        self.assertEqual(list(scout_zones.SCOUT_LABELS), LABELS)
        self.assertNotIn("opening", scout_zones.SCOUT_LABELS, "a hole is never proposed from a photo")

    def test_the_pad_beats_04s_step(self):
        self.assertGreater(scout_zones.PAD_PX, nogo.STEP_PX)


class Blob(unittest.TestCase):
    def test_the_chair_blob_is_its_cone_on_the_wall_not_the_whole_wall(self):
        g = accumulated()
        hit = chair_hit(g)
        self.assertEqual(hit["xy"], [2.0, 0.0])
        cells = scout_zones.blob(g, POSE, CHAIR["xyxy"], hit, W, FOV, threshold=THR)
        self.assertEqual(as_set(cells), wall_a_expected(CHAIR["xyxy"], hit))
        self.assertEqual(len(cells), 11, "y -0.25..0.25 m: the chair's cone on WALL_A")
        self.assertLess(len(cells), WALL_A_CELLS, "unbounded, the fill takes all 108 cells of the wall")

    def test_the_backpack_blob_on_an_oblique_bearing(self):
        g = accumulated()
        hit = objects.nearest_blob(g, POSE["position"], POSE["yaw"] - objects.bearing(BACKPACK["xyxy"], W, FOV), THR)
        self.assertEqual(hit["xy"], [2.0, -1.6])
        cells = scout_zones.blob(g, POSE, BACKPACK["xyxy"], hit, W, FOV, threshold=THR)
        self.assertEqual(as_set(cells), wall_a_expected(BACKPACK["xyxy"], hit))
        self.assertEqual(len(cells), 7, "y -1.55..-1.85 m: nearer cells in the cone are before hit - RES")

    def test_no_cell_is_outside_the_bound_or_below_the_threshold(self):
        g = accumulated()
        for box in (CHAIR, BACKPACK):
            hit = objects.nearest_blob(g, POSE["position"], POSE["yaw"] - objects.bearing(box["xyxy"], W, FOV), THR)
            for c in scout_zones.blob(g, POSE, box["xyxy"], hit, W, FOV, threshold=THR):
                self.assertTrue(in_bound(c, box["xyxy"], hit, tol=1e-6), f"{box['name']}: {c} is outside the cone or depth")
                self.assertGreaterEqual(g.cell(*c), THR, f"{c} was not seen {THR}+ times")

    def test_depth_stops_the_fill_one_metre_behind_the_hit(self):
        run = [[round(2.0 + i * RES, 6), 0.0] for i in range(41)]   # a line running away from the dog, 2.0..4.0 m
        g = hand_grid(run)
        hit = chair_hit(g)
        self.assertEqual(hit["xy"], [2.0, 0.0])
        cells = as_set(scout_zones.blob(g, POSE, CHAIR["xyxy"], hit, W, FOV, threshold=THR))
        self.assertIn((2.0, 0.0), cells)
        self.assertIn((2.95, 0.0), cells)
        self.assertFalse({c for c in cells if c[0] >= 3.05}, "past hit + DEPTH_M the fill stops")
        self.assertLessEqual(max(math.hypot(*c) for c in cells), 3.0 + 1e-6)

    def test_the_fill_is_8_connected_from_the_hit_and_counts_only_walls(self):
        line = [[2.0, round(k * RES, 6)] for k in range(-2, 3)]   # y -0.10..0.10 at x 2.0
        corner = [[2.05, 0.15]]                                   # touches (2.0, 0.10) by a corner only
        apart = [[2.5, round(k * RES, 6)] for k in range(-2, 3)]  # inside the cone and the depth, but not connected
        g = hand_grid(line, corner, apart)
        g.update(np.array([[2.0, -0.15]]))                        # adjacent to the line, seen once: not a wall
        cells = as_set(scout_zones.blob(g, POSE, CHAIR["xyxy"], chair_hit(g), W, FOV, threshold=THR))
        self.assertEqual(cells, as_set(line) | {(2.05, 0.15)})


class Polygon(unittest.TestCase):
    def blobs(self):
        g = accumulated()
        for box in (CHAIR, BACKPACK):
            hit = objects.nearest_blob(g, POSE["position"], POSE["yaw"] - objects.bearing(box["xyxy"], W, FOV), THR)
            yield box["name"], scout_zones.blob(g, POSE, box["xyxy"], hit, W, FOV, threshold=THR)

    def test_the_hull_contains_every_cell_centre_under_field_inside(self):
        for name, cells in self.blobs():
            poly = scout_zones.polygon(cells, CAL, RES)
            self.assertGreaterEqual(len(poly), 3)
            for c in px_of(cells):
                self.assertTrue(field.inside(tuple(c), poly), f"{name}: cell centre {c} outside {poly}")

    def test_every_cell_centre_is_at_least_pad_px_inside(self):
        for name, cells in self.blobs():
            poly = scout_zones.polygon(cells, CAL, RES)
            for c in px_of(cells):
                self.assertGreaterEqual(dist_to_outline(c, poly), scout_zones.PAD_PX - 1, f"{name}: {c} is too near the edge")

    def test_the_pad_is_a_bound_on_the_points_not_a_shape(self):
        cell_px = RES * 108.5
        for name, cells in self.blobs():
            poly = scout_zones.polygon(cells, CAL, RES)
            centres = px_of(cells)
            json.dumps(poly)
            for v in poly:
                self.assertTrue(all(isinstance(x, int) for x in v), f"{name}: vertex {v} is not plain ints")
                near = min(math.dist(v, c) for c in centres)
                self.assertLessEqual(near, scout_zones.PAD_PX * math.sqrt(2) + cell_px + 2, f"{name}: vertex {v} reaches past the pad")

    def test_04s_hit_cannot_step_over_a_one_cell_thin_zone(self):
        g = accumulated()
        cells = scout_zones.blob(g, POSE, CHAIR["xyxy"], chair_hit(g), W, FOV, threshold=THR)   # one row: one cell thin
        zone = {"name": "nogo-1", "poly": scout_zones.polygon(cells, CAL, RES), "nogo": True}
        corners = occupancy.to_map_px([[x + sx * RES / 2, y + sy * RES / 2] for x, y in cells for sx in (-1, 1) for sy in (-1, 1)], CAL)
        (x0, y0), (x1, y1) = corners.min(0).tolist(), corners.max(0).tolist()
        bare = {"name": "bare", "poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "nogo": True}
        paths = [[[x, y], [x + s, y + 230]] for x in (440, 449, 458) for y in range(590, 601) for s in (-40, 0, 40)]
        self.assertTrue(any(nogo.hit(p, [bare]) is None for p in paths), "the check has teeth: some routes step over the bare hull")
        for p in paths:
            self.assertIsNotNone(nogo.hit(p, [zone]), f"route {p} stepped over the padded zone")

    def test_one_cell_is_still_a_padded_zone(self):
        poly = scout_zones.polygon([[2.0, 0.0]], CAL, RES)
        c = px_of([[2.0, 0.0]])[0]
        self.assertTrue(field.inside(tuple(c), poly))
        self.assertGreaterEqual(dist_to_outline(c, poly), scout_zones.PAD_PX - 1)

    def test_no_cells_is_an_error_not_an_empty_zone(self):
        with self.assertRaises(ValueError):
            scout_zones.polygon([], CAL, RES)


class Decide(unittest.TestCase):
    def q(self, kind="chair", conf=0.66):
        return {"kind": kind, "conf": conf, "state": "the detector boxed a chair with probability high", "labels": LABELS}

    def test_the_stub_maps_coco_names_and_keeps_the_detectors_conf(self):
        want = {"dining table": "table", "bench": "table", "chair": "table", "knife": "sharp_object", "scissors": "sharp_object",
                "backpack": "not_a_hazard", "person": "not_a_hazard", "cup": "not_a_hazard"}
        for kind, label in want.items():
            d = scout_zones.decide_stub(self.q(kind, 0.66))
            self.assertEqual((d["label"], d["p"], d["app"], d["cached"], d["model"]), (label, 0.66, "stub", True, None), kind)
            self.assertEqual(d["probabilities"], {label: 0.66})
            self.assertIn("stub", str(d["raw"]))

    def test_the_live_call_is_one_system_one_choice_over_the_scout_labels(self):
        sent = []
        probs = {"table": 0.84, "sharp_object": 0.06, "blocked_way": 0.05, "not_a_hazard": 0.05}

        def post(url, headers=None, json=None, timeout=None):   # noqa: A002  (requests' own keyword)
            sent.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return Fake(200, jev_reply(json, "table", probs, confidence=0.75))
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "test-key"}), mock.patch("requests.post", post):
            d = scout_zones.decide_live(self.q())
        self.assertEqual(len(sent), 1, "one request, no retry")
        s = sent[0]
        self.assertEqual(s["url"], scout_zones.JEV_URL)
        self.assertEqual(s["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(s["json"]["state"], self.q()["state"])
        self.assertTrue(s["json"]["model"])
        (qname, question), = s["json"]["questions"].items()
        self.assertEqual(question["type"], "choice")
        self.assertEqual(set(question["criteria"]), set(LABELS))
        self.assertTrue(s["timeout"])
        self.assertEqual((d["label"], d["p"], d["app"]), ("table", 0.84, "openrouter"), "p is the chosen label's probability, not confidence")
        self.assertEqual(d["probabilities"], probs)
        self.assertEqual(d["model"], "typesafe/jev-1.13")
        self.assertFalse(d["cached"])
        self.assertIn('"choice": "table"', d["raw"])

    def test_a_non_200_is_raised_with_its_status(self):
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "test-key"}), mock.patch("requests.post", lambda *a, **k: Fake(500, "upstream down")):
            with self.assertRaises(RuntimeError) as cm:
                scout_zones.decide_live(self.q())
        self.assertIn("500", str(cm.exception))

    def test_a_choice_outside_the_labels_is_raised(self):
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "test-key"}), \
                mock.patch("requests.post", lambda url, json=None, **k: Fake(200, jev_reply(json, "opening", {"opening": 0.9}))):
            with self.assertRaises((RuntimeError, ValueError)):
                scout_zones.decide_live(self.q())

    def test_the_key_picks_the_path(self):
        with mock.patch.object(config, "maybe", lambda k: None):
            self.assertIs(scout_zones.decider(), scout_zones.decide_stub)
        with mock.patch.object(config, "maybe", lambda k: "test-key" if k == "JEV_API_KEY" else None):
            self.assertIs(scout_zones.decider(), scout_zones.decide_live)


class Base(unittest.TestCase):
    """07's store placing the fixture's two boxes on the fixture grid, a scratch map and picture folder, captured rows."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wtdd-scout-"))
        self.map = self.tmp / "map.json"
        shutil.copy(ROOT / "ui" / "map.json", self.map)
        self.pics = self.tmp / "pictures"
        self.rows: list = []
        self.g = accumulated()
        self.store = objects.Store(append=lambda r: None, draft=objects.draft_stub)
        self.store.observe(frame(), POSE, self.g, CAL, FOV, threshold=THR)
        env = mock.patch.dict(os.environ, {"WTDD_DECIDE_THRESHOLD": "0.7", "WTDD_SHIFT": "2026-09-27"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def props(self, decide=None):
        return scout_zones.Proposals(append=self.rows.append, decide=decide or scout_zones.decide_stub, photo_dir=self.pics, map_path=self.map)

    def feed(self, p, objs=None, fr=None, lock=None):
        return p.feed(self.store.to_list() if objs is None else objs, fr or frame(), POSE, self.g, CAL, FOV, threshold=THR, grid_lock=lock)

    def tool(self, name) -> list:
        return [r for r in self.rows if r["tool"] == name]

    def chair_cells(self) -> set:
        return wall_a_expected(CHAIR["xyxy"], chair_hit(self.g))


class Feed(Base):
    def test_one_zone_decided_per_placed_object_with_latency_and_probabilities(self):
        self.feed(self.props())
        dec = self.tool("zone.decided")
        self.assertEqual(sorted(r["args"]["object_id"] for r in dec), ["o1", "o2"])
        for r in dec:
            self.assertEqual((r["agent"], r["step"], r["app"]), ("scout", "zone.decided", "stub"))
            self.assertTrue({"object_id", "kind", "labels", "label", "p", "model", "probabilities", "threshold", "shift_id"} <= set(r["args"]), r["args"])
            self.assertEqual(r["args"]["labels"], LABELS)
            self.assertEqual(r["args"]["threshold"], 0.7)
            self.assertEqual(r["args"]["shift_id"], "2026-09-27")
            self.assertIsInstance(r["latency_ms"], int)
            self.assertGreaterEqual(r["latency_ms"], 0)
            self.assertIsInstance(r["args"]["probabilities"], dict)
            self.assertTrue(r["ok"])
        self.assertFalse([r for r in self.rows if r["tool"] == "decided"], "11's grade_decide owns every `decided` row")

    def test_the_stubs_p_is_the_detectors_conf(self):
        self.feed(self.props())
        by = {r["args"]["object_id"]: r for r in self.tool("zone.decided")}
        self.assertEqual((by["o1"]["args"]["kind"], by["o1"]["args"]["label"], by["o1"]["args"]["p"]), ("chair", "table", CHAIR["conf"]))
        self.assertEqual((by["o2"]["args"]["kind"], by["o2"]["args"]["label"], by["o2"]["args"]["p"]), ("backpack", "not_a_hazard", BACKPACK["conf"]))
        for r in by.values():
            self.assertEqual((r.get("cached"), r.get("source")), (True, "stub"), "a DEMO_CACHE row never claims to be live")

    def test_a_hazard_at_the_threshold_is_one_proposal_with_its_cells_photo_label_and_p(self):
        p = self.props()
        self.feed(p)
        (r,) = self.tool("zone.proposed")
        a = r["args"]
        self.assertTrue(r["ok"])
        self.assertEqual((r["agent"], a["id"], a["object_id"], a["kind"], a["label"], a["p"]), ("scout", "z1", "o1", "chair", "table", 0.71))
        self.assertEqual(as_set(a["cells"]), self.chair_cells())
        self.assertEqual(a["cells_n"], 11)
        self.assertAlmostEqual(a["area_m2"], round(11 * RES * RES, 4))
        self.assertAlmostEqual(a["dist_m"], 2.0, places=3)
        self.assertEqual(a["poly"], scout_zones.polygon(a["cells"], CAL, RES))
        photo = Path(a["photo"]["path"])
        self.assertTrue(photo.is_file(), "the detector frame is copied once, beside the dog's other pictures")
        self.assertEqual(photo.parent, self.pics)
        self.assertIn("z1", photo.name)
        data = photo.read_bytes()
        self.assertEqual(a["photo"]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(a["photo"]["sha256"], hashlib.sha256(ofx.FRAME.read_bytes()).hexdigest())
        self.assertEqual(a["photo"]["bytes"], len(data))
        self.assertEqual((r.get("cached"), r.get("source")), (True, "stub"))
        self.assertNotIn("base64,", json.dumps(r), "a row never carries the thumbnail")

    def test_not_a_hazard_or_below_the_threshold_is_no_proposal(self):
        self.feed(self.props())
        self.assertEqual([r["args"]["object_id"] for r in self.tool("zone.proposed")], ["o1"], "the backpack is not a hazard")
        self.rows.clear()
        with mock.patch.dict(os.environ, {"WTDD_DECIDE_THRESHOLD": "0.8"}):
            p = self.props()
            self.feed(p)
        self.assertEqual(len(self.tool("zone.decided")), 2, "still asked")
        self.assertFalse(self.tool("zone.proposed"), "0.71 < 0.8: the chair stays a 07 pin")
        self.assertEqual(p.state()["n"], 0)

    def test_one_row_per_thing_never_per_window(self):
        p = self.props()
        self.feed(p)
        n = len(self.rows)
        for t in (2.0, 3.0):
            self.store.observe({**frame(), "t": t}, POSE, self.g, CAL, FOV, threshold=THR)
            self.feed(p)
        self.assertEqual(len(self.rows), n, "the same objects again are no new ask and no new proposal")
        self.assertEqual(p.state()["n"], 1)

    def test_the_same_cells_again_are_the_same_thing(self):
        p = self.props(decide=lambda q: {**scout_zones.decide_stub(q), "label": "table", "p": 0.9, "probabilities": {"table": 0.9}})
        self.feed(p)
        self.assertEqual([r["args"]["id"] for r in self.tool("zone.proposed")], ["z1", "z2"])
        n = len(self.rows)
        respawn = [{**o, "id": o["id"] + "b"} for o in self.store.to_list()]   # 07 re-spawned both things under new ids
        self.feed(p, objs=respawn)
        self.assertEqual(len(self.rows), n, "cells that overlap an open proposal: logged, no call, no row")
        p.dismiss("z2", NAME)
        n = len(self.rows)
        self.feed(p, objs=[{**o, "id": o["id"] + "c"} for o in self.store.to_list()])
        self.assertEqual(len(self.rows), n, "cells that overlap a dismissed proposal: the person already said no")
        p.confirm("z1", NAME, int(self.map.stat().st_mtime))
        self.rows.clear()
        fresh = self.props()                                                    # a new session, the map remembers
        self.feed(fresh)
        self.assertNotIn("o1", [r["args"]["object_id"] for r in self.tool("zone.decided")], "cells inside a scout zone on the map")
        self.assertIn("o2", [r["args"]["object_id"] for r in self.tool("zone.decided")])

    def test_a_failed_model_call_is_its_row_and_no_proposal(self):
        def boom(q):
            raise RuntimeError("jev 500: upstream down")
        p = self.props(decide=boom)
        self.feed(p)
        dec = self.tool("zone.decided")
        self.assertEqual(len(dec), 2)
        for r in dec:
            self.assertFalse(r["ok"])
            self.assertIn("jev 500", r["response_or_error"])
            self.assertIsNone(r["args"]["label"])
        self.assertFalse(self.tool("zone.proposed"), "no canned label, no proposal")
        st = p.state()
        self.assertEqual(st["n"], 0)
        self.assertEqual(sorted(f["object_id"] for f in st["failed"]), ["o1", "o2"])
        self.assertTrue(all("jev 500" in f["error"] for f in st["failed"]))
        self.assertTrue(st["why"])
        n = len(self.rows)
        self.feed(p)
        self.assertEqual(len(self.rows), n, "a failed call is not retried")

    def test_the_live_path_failing_end_to_end(self):
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "test-key"}), mock.patch("requests.post", lambda *a, **k: Fake(401, "no auth")):
            p = scout_zones.Proposals(append=self.rows.append, photo_dir=self.pics, map_path=self.map)   # decide=None: the key picks live
            self.feed(p)
        dec = self.tool("zone.decided")
        self.assertEqual(len(dec), 2)
        for r in dec:
            self.assertEqual((r["app"], r["ok"]), ("openrouter", False))
            self.assertIn("401", r["response_or_error"])
            self.assertIsNot(r.get("cached"), True)
        self.assertFalse(self.tool("zone.proposed"))

    def test_the_model_call_runs_outside_the_grid_lock(self):
        lock, held = threading.Lock(), []

        def d(q):
            held.append(lock.locked())
            return scout_zones.decide_stub(q)
        self.feed(self.props(decide=d), lock=lock)
        self.assertEqual(held, [False, False])

    def test_the_state_sent_is_words_only(self):
        asked = []

        def d(q):
            asked.append(q)
            return scout_zones.decide_stub(q)
        self.feed(self.props(decide=d))
        self.assertEqual(sorted(q["kind"] for q in asked), ["backpack", "chair"])
        for q in asked:
            self.assertEqual(q["labels"], LABELS)
            self.assertIsNone(re.search(r"\d", q["state"]), f"digits in the state: {q['state']!r}")
            self.assertIn(q["kind"], q["state"])
        for r in self.tool("zone.decided"):
            self.assertIsNone(re.search(r"\d", r["state_before"]["state"]))
            self.assertEqual(r["state_before"]["labels"], LABELS)

    def test_an_unreadable_frame_is_a_failed_proposal_row(self):
        p = self.props()
        self.feed(p, fr={**frame(), "file": str(self.tmp / "gone.jpg")})
        self.assertFalse(self.tool("zone.decided"), "no picture, no question")
        pro = self.tool("zone.proposed")
        self.assertEqual(len(pro), 2)
        for r in pro:
            self.assertFalse(r["ok"])
            self.assertIn("gone.jpg", r["response_or_error"])
        self.assertEqual(len(p.state()["failed"]), 2)
        n = len(self.rows)
        self.feed(p)
        self.assertEqual(len(self.rows), n, "not retried")

    def test_state_is_the_get_body(self):
        empty = self.props().state()
        self.assertEqual((empty["n"], empty["proposals"], empty["failed"]), (0, [], []))
        self.assertTrue(empty["why"])
        p = self.props()
        self.feed(p)
        st = p.state()
        json.dumps(st)
        self.assertEqual(st["n"], 1)
        (z,) = st["proposals"]
        self.assertEqual(set(z), set(scout_zones.PROPOSAL_KEYS))
        self.assertEqual((z["id"], z["label"], z["p"], z["app"], z["kind"]), ("z1", "table", 0.71, "stub", "chair"))
        self.assertEqual(z["cells_px"], px_of(z["cells"]))
        self.assertTrue(z["thumb"].startswith("data:image/jpeg;base64,"))

    def test_one_stderr_line_per_call_and_a_warn_when_nothing_is_proposed(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.feed(self.props())
        self.assertIn("[wtdd:scout]", err.getvalue())
        self.assertIn("proposed=1", err.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.feed(self.props(decide=lambda q: {**scout_zones.decide_stub(q), "label": "not_a_hazard", "probabilities": {"not_a_hazard": q["conf"]}}))
        self.assertIn("WARN", err.getvalue())
        self.assertIn("proposed=0", err.getvalue())

    def test_a_feed_that_raises_is_named_on_the_get_not_an_absence(self):
        # fix round 1: a mistyped WTDD_DECIDE_THRESHOLD stopped every proposal while state() said "no placed object yet";
        # the objects thread's stderr line was the only trace. The raise stays on GET /dog/scout until a feed gets through.
        p = self.props()
        with mock.patch.dict(os.environ, {"WTDD_DECIDE_THRESHOLD": "abc"}):
            with self.assertRaises(ValueError):
                self.feed(p)
        st = p.state()
        self.assertIn("WTDD_DECIDE_THRESHOLD", st.get("error") or "", st)
        self.assertFalse(self.rows, "nothing was asked, so no row")
        self.feed(p)
        st = p.state()
        self.assertNotIn("error", st, "a feed past the threshold and the map clears it")
        self.assertEqual(st["n"], 1, "the placed objects were not taken by the failed feed: asked now")

    def test_a_ledger_write_that_raises_mid_feed_leaves_the_untaken_things_for_the_next_feed(self):
        # fix round 3: every candidate went into `handled` before the loop, so a raise on o1's row left o2 handled, never
        # asked, and named nowhere once the error cleared. A thing is taken when the loop reaches it: o1 (its call was
        # made) is not asked again and stays a failed line; o2 is asked by the next feed.
        down = {"on": True}

        def append(r):
            if down["on"] and r["tool"] == "zone.decided":
                raise OSError("disk full (test)")
            self.rows.append(r)
        p = scout_zones.Proposals(append=append, decide=scout_zones.decide_stub, photo_dir=self.pics, map_path=self.map)
        with self.assertRaises(OSError):
            self.feed(p)
        st = p.state()
        self.assertIn("disk full", st.get("error") or "", st)
        down["on"] = False
        self.feed(p)
        self.assertEqual([r["args"]["object_id"] for r in self.tool("zone.decided")], ["o2"],
                         "o2 asked once by the next feed, o1 not asked twice")
        st = p.state()
        self.assertNotIn("error", st)
        self.assertEqual([(f["object_id"], "disk full" in f["error"]) for f in st["failed"]], [("o1", True)],
                         "the thing in flight when the feed raised stays named after the error clears; o2 was never reached")

    def test_placed_objects_waiting_for_a_pose_say_so(self):
        p = self.props()
        p.feed(self.store.to_list(), frame(), None, self.g, CAL, FOV, threshold=THR)
        self.assertIn("no pose", p.state()["why"], "not 'no placed object yet': 07 placed two")

    def test_a_dog_that_moved_since_07_placed_it_waits_and_is_asked_when_07_places_it_again(self):
        # fix round 2: 07 placed both boxes from POSE, the scout is fed 0.1 m further on (the objects thread's draft call or
        # a GET tick in between). The cone from where the dog is now misses 07's old hit: a wait, never a failure, and the
        # thing is asked once 07 places it again from where the dog stands.
        moved = {"position": [0.10, 0.0], "yaw": 0.0}
        with mock.patch.dict(os.environ, {"JEV_API_KEY": ""}):   # decide=None: decider() picks the stub, and says so when called
            p = scout_zones.Proposals(append=self.rows.append, photo_dir=self.pics, map_path=self.map)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                for _ in range(2):   # two 4 Hz ticks before 07's next window
                    p.feed(self.store.to_list(), frame(), moved, self.g, CAL, FOV, threshold=THR)
            self.assertFalse([r for r in self.rows if r["tool"].startswith("zone.")], "a wait writes no row")
            st = p.state()
            self.assertEqual((st["n"], st["failed"]), (0, []), "not a failure: nothing was asked")
            self.assertIn("waiting", st["why"])
            self.assertIn("o1", st["why"], "the why names the waiting object")
            self.assertEqual(err.getvalue().count("[wtdd:scout]"), 1, f"one WARN per change, no summary, no model picked: {err.getvalue()!r}")
            self.assertIn("WARN", err.getvalue())
            self.store.observe({**frame(), "t": 2.0}, moved, self.g, CAL, FOV, threshold=THR)   # 07 places them again from here
            o1 = next(o for o in self.store.to_list() if o["id"] == "o1")
            self.assertAlmostEqual(o1["dist_m"], 1.9, places=3)
            p.feed(self.store.to_list(), frame(), moved, self.g, CAL, FOV, threshold=THR)
        self.assertEqual(sorted(r["args"]["object_id"] for r in self.tool("zone.decided")), ["o1", "o2"])
        (r,) = self.tool("zone.proposed")
        self.assertEqual((r["ok"], r["args"]["id"], r["args"]["object_id"], r["args"]["label"]), (True, "z1", "o1", "table"))
        x = fx.WALL_A["x"][0] * RES
        hit = {"xy": o1["hit_m"], "dist_m": o1["dist_m"]}
        want = {(round(x, 3), round(k * RES, 3)) for k in range(*fx.WALL_A["y"]) if in_bound((x, k * RES), CHAIR["xyxy"], hit, pose=moved)}
        self.assertTrue(want)
        self.assertEqual(as_set(r["args"]["cells"]), want, "the cells the bound gives from where the dog stands, with 07's new hit")
        st = p.state()
        self.assertEqual((st["n"], st["failed"]), (1, []))

    def test_a_waiting_thing_07_no_longer_sees_stops_waiting(self):
        moved = {"position": [0.10, 0.0], "yaw": 0.0}
        p = self.props()
        p.feed(self.store.to_list(), frame(), moved, self.g, CAL, FOV, threshold=THR)
        self.assertIn("waiting", p.state()["why"])
        for t in range(objects.STALE_WINDOWS):   # the detector stops boxing them: 07 marks both stale, their old pins kept
            self.store.observe({**frame(), "boxes": [], "t": 10.0 + t}, moved, self.g, CAL, FOV, threshold=THR)
        self.assertTrue(all(o["stale"] and o["hit_m"] for o in self.store.to_list()))
        p.feed(self.store.to_list(), frame(), moved, self.g, CAL, FOV, threshold=THR)
        self.assertNotIn("waiting", p.state()["why"], "a thing no longer seen does not wait forever")
        self.assertFalse(self.rows)

    def test_a_waiting_thing_that_goes_stale_untaken_is_named_not_dropped_without_a_trace(self):
        # review round 4: the feed after the stale windows cleared the waiting WARN with no line, and state()'s why said
        # "no placed object yet" although 07 placed both. What went stale before the scout took it is one WARN and the why.
        moved = {"position": [0.10, 0.0], "yaw": 0.0}
        p = self.props()
        p.feed(self.store.to_list(), frame(), moved, self.g, CAL, FOV, threshold=THR)
        for t in range(objects.STALE_WINDOWS):
            self.store.observe({**frame(), "boxes": [], "t": 10.0 + t}, moved, self.g, CAL, FOV, threshold=THR)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for _ in range(2):   # two ticks: the change is logged once
                p.feed(self.store.to_list(), frame(), moved, self.g, CAL, FOV, threshold=THR)
        why = p.state()["why"]
        self.assertNotIn("no placed object yet", why, "07 placed two")
        for name in ("o1", "o2", "stale"):
            self.assertIn(name, why, "the why names what went stale un-proposed")
        lines = [ln for ln in err.getvalue().splitlines() if ln.startswith("[wtdd:scout]")]
        self.assertEqual(len(lines), 1, f"one WARN line for the change: {err.getvalue()!r}")
        self.assertTrue(all(s in lines[0] for s in ("WARN", "o1", "o2", "stale")), lines[0])
        self.assertFalse(self.rows, "nothing was asked, so no row")


class Confirm(Base):
    def setUp(self):
        super().setUp()
        self.p = self.props()
        self.feed(self.p)
        self.before = self.map.read_text()
        self.version = int(self.map.stat().st_mtime)
        self.prop = self.p.state()["proposals"][0]
        self.rows.clear()

    def refused(self, code, fn):
        with self.assertRaises(scout_zones.Refused) as cm:
            fn()
        self.assertEqual(cm.exception.code, code)
        self.assertEqual(self.map.read_text(), self.before, "a refused confirm leaves the map alone")
        self.assertFalse(self.map.with_name("map.prev.json").exists())
        return cm.exception

    def test_confirm_writes_04s_schema_and_nogo_zones_accepts_it(self):
        out = self.p.confirm("z1", NAME, self.version)
        m = json.loads(self.map.read_text())
        want = {"name": "nogo-1", "label": "table · 0.71 · scout", "poly": self.prop["poly"], "nogo": True, "source": "scout",
                "cells": self.prop["cells"], "proposal": "z1", "by": NAME,
                "app": "stub"}   # fix round 2: Base decides with the stub; a zone confirmed from it keeps the stub mark on the map
        self.assertEqual(m["zones"][-1], want)
        self.assertEqual(nogo.zones(m), [want])
        old = json.loads(self.before)
        self.assertEqual(m["zones"][:-1], old["zones"], "the lighting zones stay as they were")
        self.assertEqual({k: v for k, v in m.items() if k != "zones"}, {k: v for k, v in old.items() if k != "zones"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["zone"], want)
        self.assertEqual(out["_version"], int(self.map.stat().st_mtime))
        (r,) = self.tool("zone.confirmed")
        self.assertTrue(r["ok"])
        self.assertEqual((r["agent"], r["args"]["id"], r["args"]["zone"], r["args"]["by"]), ("scout", "z1", "nogo-1", NAME))
        self.assertIn("shift_id", r["args"])
        self.assertEqual(self.p.state()["n"], 0, "a confirmed proposal is closed")

    def test_the_previous_map_survives_as_map_prev_json(self):
        self.p.confirm("z1", NAME, self.version)
        self.assertEqual(self.map.with_name("map.prev.json").read_text(), self.before)

    def test_the_next_free_name(self):
        m = json.loads(self.before)
        m["zones"].append({"name": "nogo-1", "label": "no-go 1", "poly": [[450, 1040], [510, 1040], [510, 1250], [450, 1250]], "nogo": True})
        self.map.write_text(json.dumps(m, indent=2) + "\n")
        out = self.p.confirm("z1", NAME, int(self.map.stat().st_mtime))
        self.assertEqual(out["zone"]["name"], "nogo-2")

    def test_a_stale_version_is_refused_409_with_a_failed_row(self):
        self.refused(409, lambda: self.p.confirm("z1", NAME, self.version - 7))
        (r,) = self.tool("zone.confirmed")
        self.assertFalse(r["ok"])
        self.assertTrue(r["response_or_error"])
        self.assertEqual(self.p.state()["n"], 1, "still open")

    def test_an_empty_name_is_refused_400_with_a_failed_row(self):
        for by in ("", "   ", None):
            self.refused(400, lambda by=by: self.p.confirm("z1", by, self.version))
        rows = self.tool("zone.confirmed")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["ok"] is False for r in rows))
        self.assertEqual(self.p.state()["n"], 1)

    def test_an_unknown_or_closed_id_is_404(self):
        self.refused(404, lambda: self.p.confirm("z9", NAME, self.version))
        self.p.confirm("z1", NAME, self.version)
        with self.assertRaises(scout_zones.Refused) as cm:
            self.p.confirm("z1", NAME, int(self.map.stat().st_mtime))
        self.assertEqual(cm.exception.code, 404)
        self.assertEqual([r["ok"] for r in self.tool("zone.confirmed")], [False, True, False])

    def test_a_proposal_never_refuses_and_a_confirmed_one_refuses_with_04s_own_row(self):
        cx = sum(v[0] for v in self.prop["poly"]) // len(self.prop["poly"])
        cy = sum(v[1] for v in self.prop["poly"]) // len(self.prop["poly"])
        path = [[cx, cy - 150], [cx, cy + 150]]
        n = len(ledger.rows())
        nogo.refuse(path, "field", json.loads(self.map.read_text()))   # the proposal is not on the map: nothing to refuse
        self.assertFalse([r for r in ledger.rows()[n:] if r["tool"] == "route.refused"])
        self.p.confirm("z1", NAME, self.version)
        with self.assertRaises(ValueError):
            nogo.refuse(path, "field", json.loads(self.map.read_text()))
        (r,) = [r for r in ledger.rows()[n:] if r["tool"] == "route.refused"]
        self.assertEqual((r["args"]["zone"], r["args"]["source"], r["source"], r["ok"]), ("nogo-1", "map", "map", False))


class Dismiss(Base):
    def test_dismiss_writes_its_row_and_drops_the_proposal(self):
        p = self.props()
        self.feed(p)
        before = self.map.read_text()
        self.rows.clear()
        p.dismiss("z1", NAME)
        (r,) = self.tool("zone.dismissed")
        self.assertTrue(r["ok"])
        self.assertEqual((r["agent"], r["args"]["id"], r["args"]["by"]), ("scout", "z1", NAME))
        self.assertIn("shift_id", r["args"])
        self.assertEqual(p.state()["n"], 0)
        self.assertEqual(self.map.read_text(), before, "a dismiss writes no zone")

    def test_dismiss_needs_a_name_and_an_open_id(self):
        p = self.props()
        self.feed(p)
        self.rows.clear()
        for by, oid, code in (("", "z1", 400), (NAME, "z9", 404)):
            with self.assertRaises(scout_zones.Refused) as cm:
                p.dismiss(oid, by)
            self.assertEqual(cm.exception.code, code)
        self.assertEqual([r["ok"] for r in self.tool("zone.dismissed")], [False, False])
        self.assertEqual(p.state()["n"], 1)


class Session(unittest.TestCase):
    def test_the_session_owns_one_store_and_serves_an_empty_state(self):
        from . import session
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(objects, "WATCH", Path(tmp) / "watch.json"):
            s = session.DogSession()
            try:
                self.assertIsInstance(s.scout, scout_zones.Proposals)
                d = s.scout_state()
            finally:
                stop(s)
        json.dumps(d)
        self.assertEqual((d["n"], d["proposals"], d["failed"], d["source"]), (0, [], [], "session"))
        self.assertTrue(d["why"])

    def test_the_scout_is_fed_right_after_07s_tick_and_before_the_draft_call(self):
        # fix round 3: the hook ran after objects_state(draft=True), whose draft is a model call that can take seconds, so
        # every new thing was first seen by the scout from a pose one model call later (a turn of a few degrees shifts the
        # cone onto the wall beside the thing). The draft now runs after the feed, and still runs when the feed raises.
        from . import session
        calls, closed, err = [], iter([False, True]), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(objects, "WATCH", Path(tmp) / "watch.json"):
            s = session.DogSession()
            try:
                with mock.patch.object(objects, "TICK_S", 0), \
                        mock.patch.object(s, "loop", mock.Mock(is_closed=lambda: next(closed))), \
                        mock.patch.object(s, "objects_state", lambda draft=False: calls.append(("tick", draft))), \
                        mock.patch.object(s, "scout_feed", mock.Mock(side_effect=lambda: (calls.append("feed"), 1 / 0))), \
                        mock.patch.object(objects, "draft_due", lambda store: calls.append("draft")), \
                        contextlib.redirect_stderr(err):
                    s._objects_loop()
            finally:
                stop(s)
        self.assertEqual(calls, [("tick", False), "feed", "draft"], "07's tick, the scout, then 07's draft: a feed that raises skips no draft")
        self.assertIn("WARN tick FAILED", err.getvalue(), "the feed's raise is still the objects thread's line")


class Fixture(unittest.TestCase):
    def test_scout_json_is_the_page_contract(self):
        d = json.loads(sfx.SCOUT_JSON.read_text())
        self.assertEqual(set(d), {"n", "proposals", "failed", "source", "why"})
        self.assertEqual(d["n"], len(d["proposals"]))
        self.assertEqual(d["n"], 1)
        (z,) = d["proposals"]
        self.assertEqual(set(z), set(scout_zones.PROPOSAL_KEYS), "the fixture and the live store draw the same shape")
        self.assertEqual((z["kind"], z["label"], z["p"], z["app"]), ("chair", "table", CHAIR["conf"], "stub"))
        g = accumulated()
        self.assertEqual(as_set(z["cells"]), wall_a_expected(CHAIR["xyxy"], chair_hit(g)))
        self.assertEqual(z["cells_px"], px_of(z["cells"]))
        for c in z["cells_px"]:
            self.assertTrue(field.inside(tuple(c), z["poly"]))
            self.assertGreaterEqual(dist_to_outline(c, z["poly"]), scout_zones.PAD_PX - 1)
        head, b64 = z["thumb"].split(",", 1)
        self.assertEqual(head, "data:image/jpeg;base64")
        self.assertGreater(Image.open(io.BytesIO(base64.b64decode(b64))).width, 0)
        self.assertEqual(z["photo"]["sha256"], hashlib.sha256(ofx.FRAME.read_bytes()).hexdigest())

    def test_scout_failed_json_names_the_failure(self):
        d = json.loads(sfx.SCOUT_FAILED_JSON.read_text())
        self.assertEqual((d["n"], d["proposals"]), (0, []))
        (f,) = d["failed"]
        self.assertEqual(set(f), {"object_id", "kind", "error", "ts"})
        self.assertIn("jev", f["error"])
        self.assertIn("(fixture)", f["error"], "a fixture's error never passes for a reply someone received")
        self.assertTrue(d["why"])


class Replay(unittest.TestCase):
    def run_cli(self, pose, png, led):
        return subprocess.run([PY, "-m", "wtdd.dog.scout_zones", "--replay", str(fx.NPZ), "--watch", str(ofx.WATCH_JSON), "--pose", pose,
                               "--fov", str(FOV), "--png", str(png), "--threshold", str(THR)], cwd=ROOT, capture_output=True, text=True,
                              timeout=90, env={**os.environ, "WTDD_LEDGER": str(led), "WTDD_DECIDE_THRESHOLD": "0.7"})

    def test_replay_draws_the_proposed_cells_and_writes_no_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            png, led = Path(tmp) / "scout.png", Path(tmp) / "ledger.jsonl"
            r = self.run_cli("0,0,0", png, led)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertIn("[wtdd:scout]", r.stderr)
            im = np.asarray(Image.open(png).convert("RGB"))
            self.assertFalse(led.exists(), "a replay of a fixture is not a step")
        n = int(np.all(im == np.array(scout_zones.CELL_RGB, dtype=np.uint8), axis=2).sum())
        self.assertEqual(n, 11 * occupancy.PNG_SCALE ** 2, "the chair's 11 proposed cells, one PNG_SCALE square each")

    def test_replay_with_nothing_proposed_warns_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_cli("0,0,3.14159", Path(tmp) / "scout.png", Path(tmp) / "ledger.jsonl")
        self.assertEqual(r.returncode, 2, r.stderr[-800:])
        self.assertIn("WARN", r.stderr)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.led = Path(tempfile.mkdtemp()) / "ledger.jsonl"
        cls.map_before = (ROOT / "ui" / "map.json").read_bytes()
        cls.proc = subprocess.Popen([PY, "-m", "wtdd.api", str(cls.port)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                    env={**os.environ, "WTDD_LEDGER": str(cls.led), "WTDD_SCOUT": str(sfx.SCOUT_JSON)})

    @classmethod
    def tearDownClass(cls):
        cls.proc.kill()
        cls.proc.wait()

    def call(self, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
        for _ in range(100):
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.1)
        self.fail(f"the API never answered {path}")

    def test_get_dog_scout_serves_the_fixture_when_told_to(self):
        """# DEMO_CACHE path under test: WTDD_SCOUT=<file> makes GET /dog/scout serve that file for the page's dry check."""
        code, body = self.call("/dog/scout")
        self.assertEqual(code, 200)
        want = json.loads(sfx.SCOUT_JSON.read_text())
        self.assertEqual(body["proposals"], want["proposals"])
        self.assertEqual(body["n"], 1)
        self.assertIn("scout.json", body["source"], "the body names the fixture it came from, never 'session'")

    def test_post_dog_scout_without_a_name_is_400_and_a_failed_row(self):
        code, body = self.call("/dog/scout", {"id": "z1", "action": "confirm", "by": "", "_version": 0})
        self.assertEqual(code, 400, body)
        self.assertFalse(body["ok"])
        self.assertTrue(body["error"])
        rows = [r for r in load(self.led) if r["tool"] == "zone.confirmed"] if self.led.exists() else []
        self.assertEqual([r["ok"] for r in rows], [False])
        self.assertEqual((ROOT / "ui" / "map.json").read_bytes(), self.map_before, "nothing written on a refusal")


class Eval(unittest.TestCase):
    def rows_map(self, name="scout.jsonl"):
        return load(EVALS / name), json.loads((EVALS / "scout-map.json").read_text())

    def test_every_fixture_row_is_labelled_cached(self):
        for name in ("scout.jsonl", "scout-unsafe.jsonl"):
            for i, r in enumerate(load(EVALS / name)):
                self.assertIs(r.get("cached"), True, f"{name} row {i} claims to be live")

    def test_the_committed_round_passes(self):
        rows, m = self.rows_map()
        ok, why, detail = evals.grade_scout(rows, m)
        self.assertTrue(ok, why)
        self.assertEqual(evals.unsafe_scout(rows, m), [])
        (t,) = evals.run_scout()
        self.assertEqual((t["scenario"], t["grade"], t["dry"]), ("scout", "pass", True), t)
        self.assertTrue(t["detail"].startswith("dry:"), t["detail"])

    def test_the_unsafe_fixture_is_graded_unsafe(self):
        (t,) = evals.run_scout(EVALS / "scout-unsafe.jsonl")
        self.assertEqual(t["grade"], "unsafe", t)
        self.assertIn("nogo-1", t["why"])
        rows, m = self.rows_map("scout-unsafe.jsonl")
        bad = evals.unsafe_scout(rows, m)
        self.assertEqual(len(bad), 2, bad)

    def test_a_refusal_at_a_proposal_is_unsafe(self):
        rows, m = self.rows_map()
        for r in rows:
            if r["tool"] == "route.refused" and r["args"]["zone"] == "nogo-1":
                r["args"]["zone"] = "z2"
        self.assertTrue(evals.unsafe_scout(rows, m))

    def test_a_refusal_at_a_zone_drawn_by_hand_is_not_this_graders(self):
        rows, m = self.rows_map()
        rows = [r for r in rows if not (r["tool"] == "route.refused" and r["args"]["zone"] == "nogo-1")]
        self.assertEqual(evals.unsafe_scout(rows, m), [], "nogo-2 has no source key: a person drew it (04)")

    def test_a_confirm_with_an_empty_name_is_unsafe(self):
        rows, m = self.rows_map()
        for r in rows:
            if r["tool"] == "zone.confirmed":
                r["args"]["by"] = "  "
        self.assertTrue(evals.unsafe_scout(rows, m))

    def test_a_proposal_with_no_cells_or_no_photo_fails(self):
        for breaks in ({"cells": [], "cells_n": 0}, {"photo": None}, {"photo": {"path": "x.jpg", "sha256": ""}}):
            rows, m = self.rows_map()
            for r in rows:
                if r["tool"] == "zone.proposed" and r["args"]["id"] == "z1":
                    r["args"].update(breaks)
            ok, why, _ = evals.grade_scout(rows, m)
            self.assertFalse(ok, breaks)
            self.assertTrue(why)

    def test_a_proposal_below_its_threshold_or_not_its_decision_fails(self):
        rows, m = self.rows_map()
        for r in rows:
            if r["tool"] in ("zone.decided", "zone.proposed") and (r["args"].get("object_id") == "o1"):
                r["args"]["p"] = 0.5
        self.assertFalse(evals.grade_scout(rows, m)[0], "0.5 < 0.7 must never have been proposed")
        rows, m = self.rows_map()
        for r in rows:
            if r["tool"] == "zone.proposed" and r["args"]["id"] == "z1":
                r["args"]["label"] = "sharp_object"
        self.assertFalse(evals.grade_scout(rows, m)[0], "the proposal's label is not its decision's")

    def test_the_cli_grades_scout_dry(self):
        r = subprocess.run([PY, "-m", "wtdd.evals", "--scenario", "scout"], cwd=ROOT, capture_output=True, text=True, timeout=60,
                           env={**os.environ, "WTDD_LEDGER": str(_SCRATCH / "cli-ledger.jsonl")})
        self.assertEqual(r.returncode, 0, r.stdout[-600:] + r.stderr[-600:])
        self.assertIn("scout", r.stdout)
        self.assertIn("pass", r.stdout)

    def test_write_refuses_a_dry_trial_and_leaves_the_readme_alone(self):
        readme = ROOT / "README.md"
        before = readme.read_bytes()
        try:
            r = subprocess.run([PY, "-m", "wtdd.evals", "--scenario", "scout", "--write"], cwd=ROOT, capture_output=True, text=True, timeout=60,
                               env={**os.environ, "WTDD_LEDGER": str(_SCRATCH / "cli-ledger.jsonl")})
            after = readme.read_bytes()
        finally:
            readme.write_bytes(before)
        self.assertNotEqual(r.returncode, 0, "the README's trials table is device grades only")
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
