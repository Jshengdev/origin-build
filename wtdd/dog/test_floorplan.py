"""Tests for the floor plan (wtdd/dog/floorplan.py) and the height profile it reads (Grid.zmask, wtdd/dog/occupancy.py),
on the synthetic furnished room in wtdd/dog/fixtures/voxel_furniture.npz (made by fixtures/make_furniture_frames.py;
nothing here has seen the real dog). Run:

    python -m unittest wtdd.dog.test_floorplan wtdd.dog.test_occupancy

RED until floorplan.py exists. Every expectation comes from the fixture's analytic truth (truth_cells, truth_zmask,
wall_lines: plain sets over the declared boxes), never from the code's own output; the frames reach the grid through
the driver's own decoder (decode_wire), the path a live frame takes. No model is called anywhere: shapes from points.

The contract under test (odometry metres; a cell's position is its corner, index * resolution + origin, like walls()):
  Grid.zmask                np.uint64 [iy, ix], same shape as counts, grown with it: bit k = absolute layer k seen
                            (z = z_ref + k * resolution), z_ref = the first frame's origin[2]; a later frame's origin[2]
                            lands on the same lattice; a layer outside 0..63 is a WARN and dropped, never wrapped
  Grid.z_ref                the first frame's origin[2], saved and loaded with the grid
  counts / walls(threshold) exactly what they were before the mask (01's band, +1 per cell per frame)
  to_dict / from_dict       every cell row is [ix, iy, count, zmask]; a 01-era file of [ix, iy, count] still loads
  floorplan.FLOOR GROUND TALL RUN GAP FLOORPLAN_S   0.10 0.30 1.10 m, 1.0 0.2 m, 2.0 s, each line marked UNVERIFIED
  floorplan.classes(grid, threshold=3, tall=TALL)   uint8 [iy, ix]: 0 empty, 1 wall, 2 tall blob, 3 floating slab,
                            5 low blob; wall = grounded and on a straight run >= RUN at any height
  floorplan.segments(grid, threshold=3)             [(x0, y0, x1, y1, cells)] metres, numpy only
  floorplan.run(grid, threshold, tall=TALL, grid_source="session")   one `dog.floorplan` row {args: threshold,
                            constants, grid_source; state_before: cells, frames; state_after: classes {wall, tall, slab,
                            low: count}, segments, ms}; ok=false (and `why`) when no wall; returns {ok, why?, classes,
                            segments, ms, ...}; one `[wtdd:floorplan]` stderr line (a zero class is a WARN)
  DogSession.floorplan_tick(now)   the cadence: a run only when grid.frames advanced since the last run and at least
                            FLOORPLAN_S after it; never from _on_frame (the driver's dispatcher), never from a GET
  DogSession.floorplan(threshold)  POST /dog/floorplan, the button: always one run and one row; with no session grid
                            it runs on ui/grid.json (DEMO_CACHE: the row says cached=True, source="stub", also when the
                            file is unreadable and the row fails); with no grid at all it writes a failed row and raises;
                            a posted threshold of 0 reaches run() and fails loud, never silently runs at 3
  DogSession.grid_clear(why)       the floor plan goes with its grid: GET serves nothing and says why
  DogSession.floorplan_px(threshold)  GET /dog/floorplan: the newest result {segments_px, classes, class_px, ms, ts,
                            threshold, source, why?} through occupancy.to_map_px; a read, no row
  python -m wtdd.dog.floorplan --replay <npz> --png <out> [--tall M] [--save <json>]   exit 0 with segments=N on stderr,
                            exit 2 with a WARN when no wall; a replay of a fixture never writes a row that says live
"""
from __future__ import annotations
import io
import json
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

from .. import ledger
from ..config import ROOT
from . import floorplan, lidar, nav, occupancy
from .fixtures import make_furniture_frames as ff

CAL = {"odom": [0.0, 0.0, 0.0], "map": [449.0, 491.0], "heading": 1.5708}   # nav.calibration shape, as in test_occupancy
PY = sys.executable
RES = ff.RES
NAMES = {1: "wall", 2: "tall", 3: "slab", 5: "low"}    # the class names on the row and the page (0 is empty, never counted)
BOX_ONLY = {"box": ff.WORLD["box"]}                    # a room with furniture and no wall: the floor plan must say so


def frames(path=ff.NPZ) -> list[dict]:
    return [lidar.decode(ff.decode_wire(b)) for b in ff.blobs(path)]


def accumulated(path=ff.NPZ) -> occupancy.Grid:
    fr = frames(path)
    g = occupancy.Grid.from_frame(fr[0])
    for d in fr:
        g.update_frame(d)
    return g


def truth():
    """The npz's analytic truth: {(gx, gy): class}, {(gx, gy): zmask}, {(gx, gy): owner}, {wall: (x0, y0, x1, y1)}."""
    z = np.load(ff.NPZ)
    keys = [(int(gx), int(gy)) for gx, gy, _ in z["truth_cells"]]
    return ({k: int(c) for k, (_, _, c) in zip(keys, z["truth_cells"])},
            {k: int(m) for k, m in zip(keys, z["truth_zmask"])},
            {k: str(n) for k, n in zip(keys, z["truth_names"])},
            {str(n): tuple(float(v) for v in line) for n, line in zip(z["wall_names"], z["wall_lines"])})


def at(g: occupancy.Grid, arr: np.ndarray, cell) -> int:
    """arr[iy, ix] at an absolute lattice cell (gx, gy) (the fixture's coordinates)."""
    ox, oy = round(g.origin[0] / g.resolution), round(g.origin[1] / g.resolution)
    return int(arr[cell[1] - oy, cell[0] - ox])


def where(g: occupancy.Grid, arr: np.ndarray, value) -> set[tuple[int, int]]:
    ox, oy = round(g.origin[0] / g.resolution), round(g.origin[1] / g.resolution)
    iy, ix = np.nonzero(arr == value)
    return {(int(x) + ox, int(y) + oy) for x, y in zip(ix, iy)}


def near(p, q, tol=RES + 1e-6) -> bool:
    """Within one cell per axis."""
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def on_line(seg, line) -> bool:
    a, b, p, q = seg[0:2], seg[2:4], line[0:2], line[2:4]
    return (near(a, p) and near(b, q)) or (near(a, q) and near(b, p))


def fp_rows(path: Path | None = None) -> list[dict]:
    if path is not None:
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
    return [r for r in ledger.rows() if r.get("tool") == "dog.floorplan"]


def fp_lines(err: str) -> list[str]:
    return [l for l in err.splitlines() if l.startswith("[wtdd:floorplan]")]


def stop(s) -> None:
    """A DogSession runs its own event loop thread; a test stops and closes it."""
    s.loop.call_soon_threadsafe(s.loop.stop)
    while s.loop.is_running():
        time.sleep(0.01)
    s.loop.close()


class Base(unittest.TestCase):
    """Every test writes its rows to a temp ledger and its grid file to a temp dir; stderr is captured."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.object(ledger, "LEDGER", self.tmp / "ledger.jsonl"))
        self.err = io.StringIO()
        self.enterContext(redirect_stderr(self.err))

    def session(self, grid, cal=CAL):
        from . import session as sm
        self.enterContext(mock.patch.object(sm, "GRID_FILE", self.tmp / "grid.json"))
        s = sm.DogSession()
        self.addCleanup(stop, s)
        s.grid, s.cal = grid, (dict(cal) if cal else None)
        return s


class Fixture(Base):
    def test_the_committed_npz_is_what_the_generator_writes(self):
        fresh, kept = np.load(ff.write(self.tmp / "fresh.npz")), np.load(ff.NPZ)
        self.assertEqual(sorted(fresh.files), sorted(kept.files))
        for k in kept.files:
            np.testing.assert_array_equal(fresh[k], kept[k], err_msg=f"{k}: rerun python -m wtdd.dog.fixtures.make_furniture_frames")

    def test_every_frame_decodes_through_the_driver_to_the_declared_voxels(self):
        z0 = ff.ORIGINS[0][2]
        for k, d in enumerate(frames()):
            self.assertEqual((d["frame"], d["resolution"], d["width"]), (ff.FRAME_ID, RES, [ff.W, ff.H, ff.D]))
            np.testing.assert_allclose(d["origin"], ff.ORIGINS[k])
            got = {(int(round(x / RES)), int(round(y / RES)), int(round((z - z0) / RES))) for x, y, z in d["points"]}
            self.assertEqual(got, ff.frame_voxels(k), f"frame {k}: the decoded voxels are not the declared world")
        self.assertNotEqual(ff.ORIGINS[2][2], z0, "the third window must sit one layer higher (the re-base case)")


class Mask(Base):
    def test_zmask_is_the_truth_in_every_cell_including_the_rebased_frame(self):
        g, (cls, zmask, _, _) = accumulated(), truth()
        self.assertEqual(g.zmask.dtype, np.uint64)
        self.assertEqual(g.shape, (ff.H, ff.W), "fixture: every object sits inside the first window (check()), so the grid has not grown yet")
        far = (round(g.origin[0] / RES) - 20, 0)   # a cell 1 m past the first window's low-x edge
        g.update(np.array([[far[0] * RES, far[1] * RES, 0.5]]))   # one voxel in the band there: the grid grows on that side
        self.assertGreater(g.shape[1], ff.W, "one band voxel past the window: the grid grew")
        self.assertEqual(g.zmask.shape, g.counts.shape, "the mask grows with the counts")
        self.assertAlmostEqual(g.z_ref, ff.ORIGINS[0][2], msg="z_ref is the first frame's origin[2]")
        for c, m in zmask.items():
            self.assertEqual(at(g, g.zmask, c), m, f"cell {c}: bit k must be absolute layer k (frame 2 sits one layer up), moved with the grow")
        self.assertEqual(at(g, g.zmask, far), 1 << round((0.5 - g.z_ref) / RES), "the new cell carries its own layer")
        self.assertEqual(int(np.count_nonzero(g.zmask)), len(zmask) + 1, "no bits outside the declared world and the one voxel")

    def test_counts_and_walls_are_what_they_were_before_the_mask(self):
        g, world = accumulated(), ff.world_cells()
        self.assertEqual(where(g, g.counts, 3) | where(g, g.counts, 2) | where(g, g.counts, 1), set(world))
        for c, n in world.items():
            self.assertEqual(at(g, g.counts, c), n, f"cell {c}: counts are 01's band count, unchanged")
        for t in (1, 2, 3):
            got = {(int(round(x / RES)), int(round(y / RES))) for x, y in g.walls(t)}
            self.assertEqual(got, {c for c, n in world.items() if n >= t}, f"walls({t}) moved")

    def test_a_layer_outside_0_63_is_a_warn_and_dropped_never_wrapped(self):
        g = accumulated()
        before = g.zmask.copy()
        for k in (64, 65, -1):   # 64 would wrap to bit 0, -1 to bit 63
            buf = io.StringIO()   # this update's stderr only: the fixture's re-based frame may WARN too
            with redirect_stderr(buf):
                g.update(np.array([[0.0, 0.0, g.z_ref + k * RES]]))
            self.assertTrue(any("WARN" in l and "layer" in l for l in buf.getvalue().splitlines()), f"layer {k}: no WARN line")
        np.testing.assert_array_equal(g.zmask, before, "an out-of-lattice layer changed the mask")

    def test_the_mask_round_trips_through_save_and_load_bit_63_too(self):
        g, (_, zmask, _, lines) = accumulated(), truth()
        g.update(np.array([[2.0, 0.0, g.z_ref + 63 * RES]]))   # on wall A; out of the band, so counts do not move
        self.assertEqual(at(g, g.zmask, (40, 0)), zmask[(40, 0)] | (1 << 63))
        p = g.save(self.tmp / "grid.json")
        rows = json.loads(Path(p).read_text())["cells"]
        self.assertTrue(rows and all(len(r) == 4 for r in rows), "each cell is [ix, iy, count, zmask]")
        g2 = occupancy.Grid.load(p)
        self.assertEqual(g2.zmask.dtype, np.uint64)
        np.testing.assert_array_equal(g2.zmask, g.zmask)
        np.testing.assert_array_equal(g2.counts, g.counts)
        self.assertEqual(g2.z_ref, g.z_ref)

    def test_a_01_era_grid_json_without_masks_still_loads(self):
        d = accumulated().to_dict()
        d["cells"] = [r[:3] for r in d["cells"]]
        d.pop("z_ref", None)
        g = occupancy.Grid.from_dict(d)
        np.testing.assert_array_equal(g.counts, accumulated().counts)
        self.assertEqual(int(np.count_nonzero(g.zmask)), 0)


class Classes(Base):
    def test_the_constants_are_the_goals_each_marked_unverified(self):
        self.assertEqual((floorplan.FLOOR, floorplan.GROUND, floorplan.TALL, floorplan.RUN, floorplan.GAP, floorplan.FLOORPLAN_S),
                         (0.10, 0.30, 1.10, 1.0, 0.2, 2.0))
        src = Path(floorplan.__file__).read_text().splitlines()
        for name in ("FLOOR", "GROUND", "TALL", "RUN", "GAP"):
            line = next((l for l in src if re.match(rf"{name}\s*=", l)), None)
            self.assertIsNotNone(line, f"{name} is not on its own line in the constants block")
            self.assertIn("UNVERIFIED", line, f"{name}: every constant is UNVERIFIED until the first live frame")

    def test_every_cell_gets_its_declared_class_and_every_other_cell_is_empty(self):
        g, (cls, _, names, _) = accumulated(), truth()
        c = floorplan.classes(g)
        self.assertEqual((c.dtype, c.shape), (np.dtype(np.uint8), g.counts.shape))
        wrong = {cell: (names[cell], want, at(g, c, cell)) for cell, want in cls.items() if at(g, c, cell) != want}
        self.assertEqual(wrong, {}, "cell: (owner, declared, got); the floor clutter under the table must not ground its top")
        self.assertEqual(int(np.count_nonzero(c)), len(cls), "a class on a cell the world does not have")

    def test_no_table_chair_box_or_person_cell_is_a_wall(self):
        g, (_, _, names, _) = accumulated(), truth()
        walls = where(g, floorplan.classes(g), 1)
        furniture = {cell for cell, n in names.items() if n in ff.FURNITURE + ("person",)}
        self.assertTrue(furniture)
        self.assertEqual(walls & furniture, set())

    def test_the_shelf_is_a_wall_the_documented_limit_for_goal_16(self):
        """A 2 m long, 0.9 m high shelf against the wall is grounded and straight: the geometry calls it a wall, by
        design. Only goal 16's label may move it to grey; no rule here may be tuned to hide it."""
        g, (_, _, names, _) = accumulated(), truth()
        shelf = {cell for cell, n in names.items() if n == "shelf"}
        self.assertEqual(len(shelf), 240)
        self.assertLessEqual(shelf, where(g, floorplan.classes(g), 1))

    def test_walls_by_straightness_not_height_tall_9_9(self):
        g, (cls, _, names, _) = accumulated(), truth()
        c = floorplan.classes(g, tall=9.9)
        self.assertLessEqual({cell for cell, k in cls.items() if k == 1}, where(g, c, 1), "a wall left the wall class when nothing is tall")
        self.assertEqual(where(g, c, 2), set(), "nothing is tall at 9.9 m")
        self.assertLessEqual({cell for cell, n in names.items() if n == "person"}, where(g, c, 5))


class Segments(Base):
    def test_each_wall_is_one_segment_within_one_cell_of_its_true_line(self):
        g, (_, _, _, lines) = accumulated(), truth()
        segs = floorplan.segments(g)
        self.assertTrue(all(len(s) == 5 for s in segs), segs)
        self.assertEqual(set(lines), {"wall_a", "wall_b"})
        for name, line in lines.items():
            hits = [s for s in segs if on_line(s, line)]
            self.assertEqual(len(hits), 1, f"{name} {line}: {len(hits)} segments within one cell of it, want 1; all: {segs}")

    def test_the_far_wall_seen_only_to_0_9_m_is_still_a_segment(self):
        g, (_, zmask, names, lines) = accumulated(), truth()
        top = max(max(i for i in range(64) if m >> i & 1) for cell, m in zmask.items() if names[cell] == "wall_b")
        self.assertLess(ff.ORIGINS[0][2] + top * RES, floorplan.TALL, "fixture: the far wall must stay under TALL")
        self.assertTrue(any(on_line(s, lines["wall_b"]) for s in floorplan.segments(g)))

    def test_no_segment_runs_through_anything_but_wall_cells(self):
        """Lines come only from grounded straight cells: every point along every segment is within one cell of a
        declared class-1 cell (the walls and the shelf), never over the table, the chair, the box or the person."""
        g, (cls, _, _, _) = accumulated(), truth()
        wall = {cell for cell, k in cls.items() if k == 1}
        for x0, y0, x1, y1, _n in floorplan.segments(g):
            n = int(np.ceil(max(abs(x1 - x0), abs(y1 - y0)) / (RES / 2))) + 1
            for t in np.linspace(0.0, 1.0, n):
                x, y = (x0 + t * (x1 - x0)) / RES, (y0 + t * (y1 - y0)) / RES
                ok = any((gx, gy) in wall for gx in range(int(np.floor(x)) - 1, int(np.ceil(x)) + 2)
                         for gy in range(int(np.floor(y)) - 1, int(np.ceil(y)) + 2) if abs(gx - x) <= 1 + 1e-6 and abs(gy - y) <= 1 + 1e-6)
                self.assertTrue(ok, f"segment {(x0, y0, x1, y1)} passes ({x * RES:.2f}, {y * RES:.2f}), not on a wall cell")

    def test_numpy_only_no_cv2_in_the_api_process(self):
        code = ("import sys, wtdd.dog.floorplan, wtdd.api; "
                "print(sorted({m.split('.')[0] for m in sys.modules} & {'cv2', 'scipy', 'skimage', 'shapely', 'sklearn'}))")
        r = subprocess.run([PY, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "[]"), r.stderr[-400:])


class Run(Base):
    def test_one_row_per_run_with_the_contract_fields(self):
        g, (cls, _, _, _) = accumulated(), truth()
        res = floorplan.run(g, 3)
        rows = fp_rows()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertTrue(r["ok"], r.get("response_or_error"))
        self.assertEqual(r["args"]["threshold"], 3)
        self.assertLessEqual({"FLOOR", "GROUND", "TALL", "RUN", "GAP"}, set(r["args"]["constants"]))
        self.assertEqual((r["state_before"]["cells"], r["state_before"]["frames"]), (len(cls), 3))
        want = {name: sum(1 for k in cls.values() if k == v) for v, name in NAMES.items()}
        self.assertEqual(r["state_after"]["classes"], want)
        self.assertEqual(len(r["state_after"]["segments"]), len(res["segments"]))
        self.assertGreaterEqual(len(res["segments"]), 2)
        self.assertIsInstance(r["state_after"]["ms"], (int, float))
        self.assertTrue(res["ok"])
        lines = fp_lines(self.err.getvalue())
        self.assertEqual(len(lines), 1, "one stderr line per run")
        self.assertIn("segments=", lines[0])
        self.assertIn("ms=", lines[0])
        self.assertNotIn("WARN", lines[0], "no class is zero in the furnished room")

    def test_a_run_with_no_wall_writes_ok_false(self):
        g = accumulated(ff.write(self.tmp / "box.npz", world=BOX_ONLY))
        res = floorplan.run(g, 3)
        self.assertFalse(res["ok"])
        self.assertIn("no wall", res["why"])
        rows = fp_rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])
        self.assertIn("no wall", rows[0]["response_or_error"])
        self.assertEqual(rows[0]["state_after"]["classes"]["wall"], 0)
        self.assertEqual(rows[0]["state_after"]["classes"]["low"], len(ff.object_cells("box", BOX_ONLY)))
        self.assertIn("WARN", "\n".join(fp_lines(self.err.getvalue())), "a zero class is a WARN")


class Cadence(Base):
    def test_the_session_runs_only_when_the_grid_advanced_and_at_most_every_FLOORPLAN_S(self):
        s, t0, S = self.session(accumulated()), 1000.0, floorplan.FLOORPLAN_S
        self.assertIsNotNone(s.floorplan_tick(now=t0), "frames and no floor plan yet: a run")
        self.assertIsNone(s.floorplan_tick(now=t0 + S / 4), "the grid did not advance: no run")
        s.grid.update_frame(frames()[0])
        self.assertIsNone(s.floorplan_tick(now=t0 + S / 2), "advanced, but inside FLOORPLAN_S of the last run")
        self.assertIsNotNone(s.floorplan_tick(now=t0 + S + 0.01))
        self.assertIsNone(s.floorplan_tick(now=t0 + 10 * S), "no frame since the last run: no run, however long it waits")
        self.assertEqual([r["state_before"]["frames"] for r in fp_rows()], [3, 4])

    def test_no_run_per_window_or_per_poll(self):
        s = self.session(None)
        for d in frames():
            s._on_frame(d)   # the driver's dispatcher: accumulates, never classifies
        for _ in range(3):
            s.floorplan_px(3)   # the page's poll: a read
        self.assertEqual(s.grid.frames, 3)
        self.assertEqual(fp_rows(), [])

    def test_the_button_always_runs(self):
        s = self.session(accumulated())
        s.floorplan(3)
        s.floorplan(3)
        self.assertEqual(len(fp_rows()), 2, "POST /dog/floorplan is one run and one row per press, advanced or not")


class Serve(Base):
    def test_get_serves_the_newest_result_in_map_pixels_and_writes_no_row(self):
        s, (cls, _, _, _) = self.session(accumulated()), truth()
        r0 = s.floorplan_px(3)
        self.assertEqual(r0["segments_px"], [])
        self.assertTrue(r0["why"].startswith("no floor plan"), r0["why"])
        res = s.floorplan(3)
        r = s.floorplan_px(3)
        self.assertEqual(len(fp_rows()), 1, "GET is a read")
        self.assertEqual(r["source"], "session")
        self.assertEqual(len(r["segments_px"]), len(res["segments"]))
        for (x0, y0, x1, y1, _n), px in zip(res["segments"], r["segments_px"]):
            want = [round(v) for v in nav.to_map(CAL, (x0, y0), 0.0)[:2]] + [round(v) for v in nav.to_map(CAL, (x1, y1), 0.0)[:2]]
            self.assertEqual([int(v) for v in px], want, "a segment and the LiDAR dots disagree on the map")
        self.assertEqual(r["classes"], {name: sum(1 for k in cls.values() if k == v) for v, name in NAMES.items()})
        self.assertEqual({n: len(r["class_px"][n]) for n in NAMES.values()}, r["classes"])
        self.assertNotIn("why", r)
        json.dumps(r)
        s.cal = None
        self.assertIn("not calibrated", s.floorplan_px(3)["why"])

    def test_with_no_session_grid_the_button_runs_on_ui_grid_json_labelled_stub(self):
        s = self.session(None)
        accumulated().save(self.tmp / "grid.json")
        s.floorplan(3)
        r = fp_rows()[-1]
        self.assertEqual((r["ok"], r["cached"], r["source"], r["args"]["grid_source"]), (True, True, "stub", "ui/grid.json"))
        out = s.floorplan_px(3)
        self.assertEqual(out["source"], "ui/grid.json")
        self.assertGreaterEqual(len(out["segments_px"]), 2)

    def test_with_no_grid_at_all_the_button_fails_loud_with_a_row(self):
        s = self.session(None)
        with self.assertRaises(RuntimeError):
            s.floorplan(3)
        rows = fp_rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])

    def test_the_api_serves_get_and_post_dog_floorplan(self):
        from http.server import ThreadingHTTPServer
        from .. import api
        from . import session as sm
        s = self.session(accumulated())
        self.enterContext(mock.patch.object(sm.DogSession, "_inst", s))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        base = f"http://127.0.0.1:{srv.server_address[1]}/dog/floorplan"
        get = lambda: json.loads(urllib.request.urlopen(f"{base}?threshold=3", timeout=30).read())   # noqa: E731
        self.assertTrue(get()["why"].startswith("no floor plan"))
        req = urllib.request.Request(base, data=b'{"threshold": 3}', headers={"Content-Type": "application/json"}, method="POST")
        self.assertTrue(json.loads(urllib.request.urlopen(req, timeout=60).read())["ok"])
        self.assertGreaterEqual(len(get()["segments_px"]), 2)
        self.assertEqual(len(fp_rows()), 1)
        bad = urllib.request.Request(base, data=b'{"threshold": 0}', headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError, msg="threshold 0 must fail loud, never run at the default") as e:
            urllib.request.urlopen(bad, timeout=60)
        self.assertEqual(e.exception.code, 500)
        self.assertEqual([(r["ok"], r["args"]["threshold"]) for r in fp_rows()][1:], [(False, 0)])

    def test_clearing_the_grid_drops_its_floor_plan(self):
        s = self.session(accumulated())
        s.floorplan(3)
        s.grid_clear("power cycle: the odometry frame reset")
        r = s.floorplan_px(3)
        self.assertEqual((r["segments_px"], r["class_px"], r["source"]), ([], {}, None), "a cleared grid's walls are still drawn")
        self.assertTrue(r["why"].startswith("no floor plan"), r["why"])

    def test_an_unreadable_ui_grid_json_fails_with_a_row_labelled_stub(self):
        s = self.session(None)
        (self.tmp / "grid.json").write_text("{not json")
        with self.assertRaises(RuntimeError):
            s.floorplan(3)
        r = fp_rows()[-1]
        self.assertEqual((r["ok"], r["cached"], r["source"], r["args"]["grid_source"]), (False, True, "stub", "ui/grid.json"))


class Replay(Base):
    def cli(self, *args, npz=ff.NPZ):
        env = {**os.environ, "WTDD_LEDGER": str(self.tmp / "cli-ledger.jsonl")}
        return subprocess.run([PY, "-m", "wtdd.dog.floorplan", "--replay", str(npz), *args],
                              cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)

    @staticmethod
    def nseg(err: str) -> int:
        m = re.findall(r"segments=(\d+)", err)
        return int(m[-1]) if m else -1

    def test_replay_exits_0_with_2_plus_segments_draws_the_png_and_saves_the_masks(self):
        from PIL import Image
        png, saved = self.tmp / "fp.png", self.tmp / "grid.json"
        r = self.cli("--png", str(png), "--save", str(saved))
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertGreaterEqual(self.nseg(r.stderr), 2, r.stderr[-800:])
        im = np.asarray(Image.open(png).convert("RGB"))
        self.assertGreaterEqual(len(np.unique(im.reshape(-1, 3), axis=0)), 5, "empty, wall, tall, slab and low each drawn")
        np.testing.assert_array_equal(occupancy.Grid.load(saved).zmask, accumulated().zmask)
        self.assertEqual([x for x in fp_rows(self.tmp / "cli-ledger.jsonl") if x.get("source") == "live"], [],
                         "a replay of a fixture never writes a row that says live")

    def test_tall_9_9_still_yields_both_walls(self):
        r = self.cli("--png", str(self.tmp / "fp.png"), "--tall", "9.9")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertGreaterEqual(self.nseg(r.stderr), 2)

    def test_no_wall_exits_2_with_a_warn(self):
        r = self.cli("--png", str(self.tmp / "fp.png"), npz=ff.write(self.tmp / "box.npz", world=BOX_ONLY))
        self.assertEqual(r.returncode, 2, r.stderr[-800:])
        self.assertTrue(any("WARN" in l and "no wall" in l for l in r.stderr.splitlines()), r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
