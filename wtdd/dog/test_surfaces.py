"""Tests for the surface filter (wtdd/dog/lidar.py surfaces/keep, wired in Body._on_lidar): the Go2's own voxel map
fills space it cannot see (behind walls) as solid columns, and wtdd drew them as walls. Live, 2026-09-27 19:10, the
first frame after a restart: a flat ~2,400 voxels per layer from 0.12 to 0.73 m (solid columns over large areas, a
wall line would be 100-300), and after POST /dog/grid {clear} 5,900 of ~6,000 cells were hit in 50+ of 550 frames.
Run:

    python -m unittest wtdd.dog.test_surfaces

RED on main: the block behind the room's east wall is drawn. Every scene goes through the driver's own decoder
(fixtures.make_voxel_frames.wire + decode_wire) and Body._on_lidar -> the session's _on_frame -> its grid, the path a
live window takes; expectations are the scene's declared cells, never the filter's own output.

The scene (window corner (-3.2, -3.2) m, z index k above Z0 = -0.3 m, so the floor layer k = 6 is z = 0.0 m):
  ROOM   free floor x, y in -2.0..2.0 m (cells 24..104), the dog at its middle
  WALLS  one cell thick on the room's four sides, floor to 1.2 m, a doorway in the north wall (x -0.5..0.5 m) onto
         a corridor of free floor
  BLOCK  beyond the east wall: SOLID from the floor to 0.75 m in every layer (x 2.05 m to the window's edge, every y),
         what the dog's map fills and never saw; cut by the window on three sides
  TABLE  a top at 0.75 m over the room's floor with four legs: the floor is seen under it
"""
from __future__ import annotations
import asyncio
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import numpy as np

from . import lidar, occupancy
from .fixtures import make_voxel_frames as fx

ORIGIN = (-3.2, -3.2)
FLOOR_K = 6                        # z = 0.0 m
R0, R1 = 24, 104                   # the room's wall lines (cells), x and y -2.0..2.0 m
DOOR = range(54, 75)               # the north wall's doorway, x -0.5..0.5 m
BLOCK_X = range(105, fx.W)         # the fill: x 2.05 m to the window's edge, every y
TABLE_X, TABLE_Y, TOP_K = range(44, 57), range(76, 85), 21   # x -1.0..-0.4, y 0.6..1.0, top at 0.75 m
N = 4


def scene(floor: bool = True, block: bool = True) -> np.ndarray:
    v = np.zeros((fx.D, fx.H, fx.W), dtype=bool)   # [z, y, x]
    if floor:
        v[FLOOR_K, R0:R1 + 1, R0:R1 + 1] = True
        v[FLOOR_K, R1 + 1:R1 + 13, DOOR.start:DOOR.stop] = True   # the corridor through the doorway
    for sl in ((slice(R0, R1 + 1), R0), (slice(R0, R1 + 1), R1)):   # west and east walls
        v[FLOOR_K:31, sl[0], sl[1]] = True
    v[FLOOR_K:31, R0, R0:R1 + 1] = True                            # south wall
    v[FLOOR_K:31, R1, R0:R1 + 1] = True                            # north wall ...
    v[FLOOR_K:31, R1, DOOR.start:DOOR.stop] = False                # ... with its doorway
    if block:
        v[FLOOR_K:22, :, BLOCK_X.start:] = True
    v[TOP_K, TABLE_Y.start:TABLE_Y.stop, TABLE_X.start:TABLE_X.stop] = True
    for x in (TABLE_X.start, TABLE_X.stop - 1):
        for y in (TABLE_Y.start, TABLE_Y.stop - 1):
            v[9:TOP_K + 1, y, x] = True
    return v


def xy(ix: int, iy: int) -> tuple[float, float]:
    return ORIGIN[0] + ix * fx.RES, ORIGIN[1] + iy * fx.RES


def room_faces() -> list[tuple[int, int]]:
    """The wall cells facing the room (the doorway is not wall)."""
    cells = {(x, y) for y in range(R0, R1 + 1) for x in (R0, R1)} | {(x, y) for x in range(R0, R1 + 1) for y in (R0, R1)}
    return sorted(c for c in cells if not (c[1] == R1 and c[0] in DOOR))


class Surfaces(unittest.TestCase):
    def setUp(self):
        from .body import Body
        from .. import ledger
        self.err = io.StringIO()
        self.enterContext(redirect_stderr(self.err))
        self.enterContext(mock.patch.object(lidar, "subscribe", mock.AsyncMock()))
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(ledger, "LEDGER", Path(tmp) / "ledger.jsonl"))
        self.body = Body()

    def run_scene(self, vox: np.ndarray, n: int = N):
        from . import session
        from .test_occupancy import stop
        s = session.DogSession()
        try:
            asyncio.run(self.body.lidar_on(s._on_frame))
            for k in range(n):
                self.body._on_lidar(fx.decode_wire(fx.wire(vox, ORIGIN, 1000.0 + k)))
            s.body = self.body
            served = (s.grid_px(), s.lidar())
        finally:
            stop(s)
        return s.grid, served

    def test_the_rooms_walls_are_drawn_and_the_filled_block_behind_them_is_not(self):
        g, _ = self.run_scene(scene())
        faces = room_faces()
        drawn = [c for c in faces if g.cell(*xy(*c)) >= occupancy.THRESHOLD]
        self.assertGreaterEqual(len(drawn), 0.95 * len(faces), f"{len(drawn)} of {len(faces)} wall cells facing the room drawn")
        block = [(x, y) for x in BLOCK_X for y in range(fx.H) if g.cell(*xy(x, y)) > 0]
        self.assertEqual(len(block), 0, f"{len(block)} of {len(BLOCK_X) * fx.H} cells of the filled block (its interior and its "
                                        f"window-cut edges) drawn, e.g. {block[:3]}")

    def test_a_table_over_free_floor_is_kept_top_and_legs(self):
        g, _ = self.run_scene(scene())
        table = [(x, y) for x in TABLE_X for y in TABLE_Y]
        missing = [c for c in table if g.cell(*xy(*c)) < occupancy.THRESHOLD]
        self.assertEqual(missing, [], "the floor is seen under the table: its top and legs are surfaces")

    def test_a_frame_with_no_floor_is_a_warn_and_draws_nothing(self):
        g, (grid, lid) = self.run_scene(scene(floor=False), n=2)
        self.assertEqual(int((g.counts > 0).sum()), 0, "a window with no floor cannot say what is a surface: not drawn")
        self.assertRegex(self.err.getvalue(), r"WARN [^\n]*no floor")
        self.assertEqual(lid["fill"]["free"], 0)
        self.assertEqual(grid["fill"]["no_floor"], 2)

    def test_served_counts_say_what_was_filled_and_not_drawn(self):
        _, (grid, lid) = self.run_scene(scene())
        self.assertEqual((grid["surfaces"], lid["surfaces"]), ("on", "on"))
        self.assertGreater(lid["fill"]["dropped"], len(BLOCK_X) * fx.H - 10, "the newest window's dropped cells: the block")
        self.assertEqual(grid["fill"]["frames"], N)
        self.assertEqual(grid["fill"]["dropped"], N * lid["fill"]["dropped"], "the grid's are the sum over its frames")

    def test_WTDD_SURFACES_0_restores_the_old_counts_exactly(self):
        vox = scene()
        with mock.patch.dict(os.environ, {"WTDD_SURFACES": "0"}):
            g, (grid, lid) = self.run_scene(vox)
        raw = [lidar.decode(fx.decode_wire(fx.wire(vox, ORIGIN, 1000.0 + k))) for k in range(N)]
        want = occupancy.Grid.from_frame(raw[0])
        for d in raw:
            want.update_frame(d)
        np.testing.assert_array_equal(g.counts, want.counts)
        self.assertEqual((grid["surfaces"], lid["surfaces"]), ("off", "off"))


if __name__ == "__main__":
    unittest.main()
