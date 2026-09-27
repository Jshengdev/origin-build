# 14-7 · A grid that already holds the room is not a z band that caught nothing

**Symptom.** In the reviewer's probe, a second scout press at the same spot FAILED with `0 cells added in z band
0.1..1.0 m over 8 frames: tune lidar.Z_MIN/Z_MAX`, and so did the z 0 control run after a spin. Needs-the-dog 14.2
("press again") and 14.4 (the control) do exactly that. Both presses had 8 frames, and every frame hit the band. The
row told Johnny to retune a band that works. On one grid, 14.4's spin-versus-control comparison is also meaningless:
whichever press runs second only counts the cells the first one missed. Found in review.

**Root cause.** The FAILED check was `cells() - c0 == 0`, which counts newly occupied cells. A grid that already held
every cell the band hit gives the same 0 as a band that caught nothing. Only the count of band hits tells the two
apart. Grid.update adds one per distinct band cell per frame, so that count is the gain in `counts.sum()` over the spin.

**Fix (verbatim).** In wtdd/dog/session.py (`_scout`), the grid read returns both numbers, and the row carries
`band_hits`:

```
        def cells() -> tuple[int, int]:   # (occupied cells, band hits: the counts' sum, one per band cell per frame)
            with self._grid_lock:
                return (int((g.counts > 0).sum()), int(g.counts.sum())) if (g := self.grid) is not None else (0, 0)
...
                           RuntimeError(f"0 band cells: no voxel of {frames} frames in z band {lidar.Z_MIN}..{lidar.Z_MAX} m: tune lidar.Z_MIN/Z_MAX") if hits == 0 else None)
...
                        ([f"no new cells: the band was hit {hits} times but the grid already held all {total} cells here; POST /dog/grid {{clear: true}} "
                          "to measure afresh"] if hits > 0 and added == 0 else [])   # the band caught the room; nothing here was new to the grid
```

When the band was hit but nothing was new, the press is ok with a WARN, and its why names the full grid and the
clear. That why is joined to "not closed" or to the control's why when those apply. Needs-the-dog 14.4 now clears the
grid (`POST /dog/grid {clear: true, why: "scout control"}`) before each of the two presses it compares.

**Verify.**

```
python -m unittest wtdd.dog.test_scout.Spin.test_a_second_press_and_the_control_on_one_grid_do_not_blame_the_band \
  wtdd.dog.test_scout.FailLoud.test_zero_band_cells_names_the_band
```

Both were RED at 44f3702. The first failed with `second press: RuntimeError: 0 cells added in z band ...`, the second
with `KeyError: 'band_hits'`. Both pass at 02f2af1. On the fixture, the second press and the control each read
frames 8, band_hits 404, cells_added 0, ok true, with one WARN each. Floor-only frames still FAIL with band_hits 0,
naming lidar.Z_MIN/Z_MAX.
