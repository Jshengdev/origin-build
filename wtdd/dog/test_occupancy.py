"""Tests for wtdd/dog/occupancy.py on the synthetic frames in wtdd/dog/fixtures/voxel_frames.npz (made by
fixtures/make_voxel_frames.py; nothing here has seen the real dog). Run:

    python -m unittest wtdd.dog.test_occupancy

RED until occupancy.py exists. Every expectation is computed from the fixture's declared world with plain sets
(make_voxel_frames.frame_cells / world_cells), never from the accumulator's own output; the frames reach the grid
through the driver's own decoder (fixtures.decode_wire), the path a live frame takes.

The contract under test (the grid, in the odometry frame, metres):
  Grid.from_frame(d)        resolution and origin from the decoded frame's own `resolution` and `origin` (x, y)
  grid.update(points)       (N, 3) absolute metres: keeps lidar.Z_MIN..Z_MAX, +1 per distinct cell per call; grows
                            past the first window when a point falls outside; returns cells touched; 0 is a WARN
  grid.update_frame(d)      update() from a decoded frame; refuses a frame at another resolution (ValueError)
  grid.walls(threshold)     (M, 2) float64 metres of the cells seen >= threshold times, at cell corners
                            (index * resolution + origin, the driver's own convention for the dots)
  grid.cell(x, y)           the count at a point (0 outside the extent)
  grid.save / Grid.load     ui/grid.json: {resolution, origin, width, frames, frame_id, cells, saved_at}
  to_map_px(xy, cal)        vectorised nav.to_map: map pixels through the same calibration as the dots
  response(grid, cal, threshold, source)   the GET /dog/grid JSON: {n, cells_px, cell_px, threshold, resolution,
                            frames, extent_m, source, why?}; zero cells always says why
  python -m wtdd.dog.occupancy --replay <npz> --png <out> [--threshold N] [--save <json>]
                            the driver decoder on each stored blob -> grid -> a PNG (PNG_SCALE px per cell: white
                            background, grey below threshold, black walls) and one stderr line per frame
"""
from __future__ import annotations
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import numpy as np

from ..config import ROOT
from . import lidar, nav, occupancy
from .fixtures import make_voxel_frames as fx

CAL = {"odom": [0.0, 0.0, 0.0], "map": [449.0, 491.0], "heading": 1.5708}   # nav.calibration shape: at map (449, 491) facing down the page
PY = sys.executable


def frames() -> list[dict]:
    return [lidar.decode(fx.decode_wire(b)) for b in fx.blobs()]


def idx(xy: np.ndarray) -> set[tuple[int, int]]:
    """Cell corners in metres -> absolute lattice indices (the fixture's own coordinates)."""
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    return {(int(round(x / fx.RES)), int(round(y / fx.RES))) for x, y in xy}


def accumulated() -> occupancy.Grid:
    fr = frames()
    g = occupancy.Grid.from_frame(fr[0])
    for d in fr:
        g.update_frame(d)
    return g


class Fixture(unittest.TestCase):
    def test_npz_decodes_through_the_driver_to_the_declared_world(self):
        fr = frames()
        self.assertEqual(len(fr), len(fx.ORIGINS))
        for k, d in enumerate(fr):
            self.assertEqual(d["width"], [fx.W, fx.H, fx.D])
            self.assertEqual(d["resolution"], fx.RES)
            self.assertEqual(d["frame"], fx.FRAME_ID)
            np.testing.assert_allclose(d["origin"][:2], fx.ORIGINS[k])
            p = d["points"]
            self.assertGreater(len(p), 0)
            band = p[(p[:, 2] >= lidar.Z_MIN) & (p[:, 2] <= lidar.Z_MAX)]
            self.assertEqual(idx(band[:, :2]), fx.frame_cells(k), f"frame {k}: the decoded band is not the declared window")
            self.assertGreater(int((p[:, 2] < lidar.Z_MIN).sum()), 0, "the floor patch below the band must be in the raw frame")

    def test_the_world_moves_past_the_first_window(self):
        w = fx.world_cells()
        self.assertEqual({1, 2, 3}, set(w.values()))
        self.assertTrue(any(gx >= fx.window_offset(fx.ORIGINS[0])[0] + fx.W for gx, _ in w), "no cell beyond the first window")


class GridTests(unittest.TestCase):
    def setUp(self):
        self.frames = frames()

    def test_grid_takes_resolution_and_origin_from_the_first_frame(self):
        d = self.frames[0]
        g = occupancy.Grid.from_frame(d)
        self.assertEqual(g.resolution, d["resolution"])
        np.testing.assert_allclose(g.origin, d["origin"][:2])
        self.assertEqual(g.frames, 0)
        self.assertEqual(g.frame_id, d["frame"])
        self.assertEqual(g.walls(1).shape, (0, 2))

    def test_update_counts_a_cell_once_per_frame(self):
        d = self.frames[0]
        g = occupancy.Grid.from_frame(d)
        n = g.update(d["points"])
        self.assertEqual(n, len(fx.frame_cells(0)))
        self.assertEqual(g.cell(2.0, 0.0), 1, "wall A stacks 14 z voxels on one cell: one count per frame, not per voxel")
        g.update(d["points"])
        self.assertEqual(g.cell(2.0, 0.0), 2)
        self.assertEqual(g.frames, 2)

    def test_walls_match_the_world_at_every_threshold(self):
        g = accumulated()
        world = fx.world_cells()
        self.assertEqual(g.frames, 3)
        for t in (1, 2, 3):
            want = {c for c, n in world.items() if n >= t}
            self.assertEqual(idx(g.walls(t)), want, f"threshold {t}")
        self.assertEqual(len(g.walls(4)), 0)
        self.assertEqual(g.walls(2).dtype, np.float64)

    def test_grid_grows_past_the_first_window(self):
        g = accumulated()
        self.assertGreater(g.shape[1], fx.W, "the grid stayed one window wide: cells past x = 3.2 m were dropped")
        self.assertIn((79, 56), idx(g.walls(1)), "wall B's far end (x = 3.95 m) is outside the first window and must be kept")
        self.assertGreaterEqual(g.extent_m()["x"][1], 3.95)

    def test_floor_clutter_below_the_band_is_not_counted(self):
        g = accumulated()
        self.assertEqual(g.cell(-0.95, -0.95), 0)

    def test_a_blob_seen_once_is_not_a_wall(self):
        g = accumulated()
        self.assertEqual(g.cell(0.05, -0.95), 1)
        self.assertIn((1, -19), idx(g.walls(1)))
        self.assertNotIn((1, -19), idx(g.walls(2)))

    def test_zero_points_is_a_warn_not_a_crash(self):
        g = accumulated()
        before = g.walls(1)
        buf = io.StringIO()
        with redirect_stderr(buf):
            n = g.update(np.empty((0, 3)))
        self.assertEqual(n, 0)
        self.assertIn("WARN", buf.getvalue())
        np.testing.assert_array_equal(g.walls(1), before)

    def test_a_frame_at_another_resolution_is_refused(self):
        g = occupancy.Grid.from_frame(self.frames[0])
        other = {**self.frames[1], "resolution": 0.1}
        with self.assertRaises(ValueError):
            g.update_frame(other)


class Projection(unittest.TestCase):
    def test_cells_px_match_nav_to_map_pixel_for_pixel(self):
        g = accumulated()
        xy = g.walls(2)
        px = occupancy.to_map_px(xy, CAL)
        self.assertEqual(px.shape, (len(xy), 2))
        for i in range(len(xy)):
            want = [round(v) for v in nav.to_map(CAL, xy[i], 0.0)[:2]]
            self.assertEqual([int(px[i][0]), int(px[i][1])], want, f"cell {i}: the grid and the dots disagree")

    def test_response_calibrated(self):
        g = accumulated()
        r = occupancy.response(g, CAL, threshold=2, source="session")
        self.assertEqual(r["n"], len(g.walls(2)))
        self.assertEqual(len(r["cells_px"]), r["n"])
        self.assertTrue(all(len(p) == 2 and all(isinstance(v, int) for v in p) for p in r["cells_px"]))
        self.assertEqual(r["cell_px"], round(fx.RES * nav.PX_PER_M, 1))
        self.assertEqual(r["threshold"], 2)
        self.assertEqual(r["frames"], 3)
        self.assertEqual(r["resolution"], fx.RES)
        self.assertEqual(r["source"], "session")
        self.assertIn("extent_m", r)
        self.assertNotIn("why", r)
        json.dumps(r)   # what the API sends

    def test_response_uncalibrated_says_so(self):
        r = occupancy.response(accumulated(), None, threshold=2, source="session")
        self.assertEqual((r["n"], r["cells_px"]), (0, []))
        self.assertIn("not calibrated", r["why"])

    def test_response_without_a_grid_says_so(self):
        r = occupancy.response(None, CAL, threshold=2, source=None)
        self.assertEqual((r["n"], r["cells_px"], r["source"]), (0, [], None))
        self.assertTrue(r["why"].startswith("no grid"), r["why"])


class Persistence(unittest.TestCase):
    def test_save_load_round_trip(self):
        g = accumulated()
        with tempfile.TemporaryDirectory() as tmp:
            p = g.save(Path(tmp) / "grid.json")
            d = json.loads(Path(p).read_text())
            self.assertTrue({"resolution", "origin", "width", "frames", "frame_id", "cells", "saved_at"} <= set(d), sorted(d))
            self.assertEqual(d["frames"], 3)
            self.assertEqual(len(d["cells"]), len(g.walls(1)))
            g2 = occupancy.Grid.load(p)
        self.assertEqual(g2.resolution, g.resolution)
        np.testing.assert_allclose(g2.origin, g.origin)
        self.assertEqual(g2.frames, g.frames)
        self.assertEqual(g2.frame_id, g.frame_id)
        np.testing.assert_array_equal(g2.counts, g.counts)
        np.testing.assert_array_equal(g2.walls(3), g.walls(3))


class Replay(unittest.TestCase):
    def test_replay_cli_writes_a_png_with_the_walls(self):
        from PIL import Image
        g = accumulated()
        with tempfile.TemporaryDirectory() as tmp:
            png, saved = Path(tmp) / "grid.png", Path(tmp) / "grid.json"
            r = subprocess.run([PY, "-m", "wtdd.dog.occupancy", "--replay", str(fx.NPZ), "--png", str(png), "--threshold", "2", "--save", str(saved)],
                               cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertGreaterEqual(r.stderr.count("[wtdd:occupancy]"), len(fx.ORIGINS) + 1, "one stderr line per frame plus a summary")
            self.assertIn("walls=", r.stderr)
            self.assertTrue(png.is_file())
            im = np.asarray(Image.open(png).convert("RGB"))
            self.assertEqual(im.shape[:2], (g.shape[0] * occupancy.PNG_SCALE, g.shape[1] * occupancy.PNG_SCALE))
            black = int(np.all(im == 0, axis=2).sum())
            self.assertEqual(black, occupancy.PNG_SCALE ** 2 * len(g.walls(2)), "black pixels are exactly the walls at threshold 2")
            self.assertGreater(int(np.all(im == 255, axis=2).sum()), black, "the background is white")
            self.assertEqual(occupancy.Grid.load(saved).frames, 3)

    def test_replay_cli_fails_loud_on_a_missing_npz(self):
        r = subprocess.run([PY, "-m", "wtdd.dog.occupancy", "--replay", "/nonexistent/frames.npz", "--png", "/tmp/never.png"],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("/nonexistent/frames.npz", r.stderr)


if __name__ == "__main__":
    unittest.main()
