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
Two more scenes pin what the filter keeps and should not (lidar.py Surfaces, UNVERIFIED), so the limit is tested, not
hidden: fill beyond a doorway cut by the floor the dog sees through it (the cone's sides are kept as lines), and live
19:13's geometry, a block ending short of the window's edge with floor seen beyond it (its edge there is kept).
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


def cone(x: int, y: int, axis_y: bool = True) -> bool:
    """Seen from the dog at cell (64, 64) through a 21-cell doorway 40 cells away (the north one at y 104, or the east
    one at x 104 with axis_y False): the floor beyond it the LiDAR sees."""
    along, across = (y - 64, x - 64) if axis_y else (x - 64, y - 64)
    return along > 40 and abs(across) <= along / 4


def beyond_the_door(axis_y: bool = True, north_gap: bool = False) -> np.ndarray:
    """The two limits the filter keeps (lidar.py Surfaces, UNVERIFIED), in one window: fill beyond a doorway (the north
    one, or one cut in the east wall with axis_y False) except the view cone the dog sees through it, where the floor is
    seen; north_gap: the east fill ends at y 121 and floor is seen from there to the window's edge."""
    v = scene(block=False)
    v[FLOOR_K, R1 + 1:, :] = False                                     # no corridor: only the cone is seen
    if not axis_y:
        v[FLOOR_K + 1:31, DOOR.start:DOOR.stop, R1] = False            # a doorway in the east wall too
    for y in range(fx.H):
        for x in range(fx.W):
            beyond = y > R1 if axis_y else x > R1
            if not beyond:
                continue
            if cone(x, y, axis_y) or (north_gap and y > 121):
                v[FLOOR_K, y, x] = True
            else:
                v[FLOOR_K:22, y, x] = True
    return v


def floor_border(v: np.ndarray) -> set[tuple[int, int]]:
    """The scene's cells with a floor-only column among their 8 neighbours (what the scene declares, not the filter)."""
    fl = v[FLOOR_K] & ~v[FLOOR_K + 1:].any(axis=0)
    return {(x + dx, y + dy) for y, x in zip(*np.nonzero(fl)) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}


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
        from .test_occupancy import CAL, stop
        s = session.DogSession()
        try:
            asyncio.run(self.body.lidar_on(s._on_frame))
            for k in range(n):
                self.body._on_lidar(fx.decode_wire(fx.wire(vox, ORIGIN, 1000.0 + k)))
            s.body = self.body
            served = (s.grid_px(), s.lidar())
            s.cal = dict(CAL)   # calibrated and standing at the window's middle: the follower's live view (_live_px)
            with mock.patch.object(self.body, "state", lambda: {"position": [0.0, 0.0, 0.0], "rpy": [0.0, 0.0, 0.0]}):
                self.live = s._live_px()
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
        self.assertIsNone(self.live, "no floor seen is no live view (the follower goes unchecked), never an empty "
                                     f"one it reads as clear: got {type(self.live).__name__} of {len(self.live or [])} points")

    def test_a_window_with_floor_is_a_live_view(self):
        self.run_scene(scene())
        self.assertGreater(len(self.live or []), 0, "the kept walls are the follower's live view")

    def test_served_counts_say_what_was_filled_and_not_drawn(self):
        _, (grid, lid) = self.run_scene(scene())
        self.assertEqual((grid["surfaces"], lid["surfaces"]), ("on", "on"))
        self.assertGreater(lid["fill"]["dropped"], len(BLOCK_X) * fx.H - 10, "the newest window's dropped cells: the block")
        self.assertEqual(grid["fill"]["frames"], N)
        self.assertEqual(grid["fill"]["dropped"], N * lid["fill"]["dropped"], "the grid's are the sum over its frames")

    def test_the_sides_of_a_doorways_view_cone_through_fill_are_kept_as_lines(self):
        """A known limit (lidar.py Surfaces, UNVERIFIED): the fill's shadow edges border the floor seen through a doorway,
        so they are kept and drawn as lines from each door jamb away from the dog to the window's edge."""
        v = beyond_the_door()
        g, _ = self.run_scene(v)
        faces = room_faces()
        self.assertGreaterEqual(sum(g.cell(*xy(*c)) >= occupancy.THRESHOLD for c in faces), 0.95 * len(faces))
        beyond = [(x, y) for x in range(fx.W) for y in range(R1 + 1, fx.H) if g.cell(*xy(x, y)) >= occupancy.THRESHOLD]
        edge = floor_border(v)
        self.assertEqual([c for c in beyond if c not in edge], [], "only the cone's sides are drawn beyond the north wall")
        far = [(x, y) for x, y in beyond if abs(x - 64) > 20]
        self.assertEqual(far, [], "the fill away from the cone is dropped")
        self.assertGreater(len(beyond), 40, f"the cone's two sides are drawn as lines ({len(beyond)} cells): the limit")

    def test_a_filled_blocks_edge_along_seen_floor_is_kept_and_its_inside_is_not(self):
        """A known limit (lidar.py Surfaces, UNVERIFIED), live 19:13's geometry: the east block ends 6 cells short of the
        window's edge with floor seen beyond it, and a doorway in the east wall cuts a seen wedge into it. Its straight
        edge along that floor and the wedge's sides are kept (drawn as wall lines); its inside and its window-cut edge are not."""
        v = beyond_the_door(axis_y=False, north_gap=True)
        g, _ = self.run_scene(v)
        drawn = lambda x, y: g.cell(*xy(x, y)) >= occupancy.THRESHOLD
        north_edge = [x for x in range(R1 + 2, fx.W) if drawn(x, 121)]
        self.assertGreaterEqual(len(north_edge), 0.9 * (fx.W - R1 - 2), "the block's edge along the seen floor at y 122..127")
        wedge = [(x, y) for x in range(R1 + 1, fx.W) for y in range(fx.H) if drawn(x, y) and (x, y) in floor_border(v)
                 and 40 < y < 90]
        self.assertGreater(len(wedge), 20, "the wedge's sides")
        inside = [(x, y) for x in range(110, 126) for y in (*range(5, 41), *range(90, 119)) if drawn(x, y)]
        self.assertEqual(inside, [], "the block's inside is dropped")
        self.assertEqual([x for x in range(R1 + 1, fx.W) if drawn(x, 0)], [], "its window-cut edge is dropped")

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
