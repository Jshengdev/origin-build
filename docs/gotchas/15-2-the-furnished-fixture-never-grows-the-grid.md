# 15-2 · the furnished fixture never grows the grid, so a test that expects growth from it can never pass

**Symptom.** With the mask built and every other floor plan test green, one assertion in the RED commit failed for
any implementation:
`AssertionError: 128 not greater than 128 : the fixture walks past the first window: the grid grew`
(`wtdd.dog.test_floorplan.Mask.test_zmask_is_the_truth_in_every_cell_including_the_rebased_frame`).

**Root cause.** The line was carried over from 01's test_occupancy, whose world (voxel_frames.npz) has cells past
x = 3.2 m. The furnished world is built the other way on purpose: `make_furniture_frames.check()` asserts that every
object sits inside every one of the three windows, so all of it lies inside the first 128 x 128 window. 01's grid
grows only when a point in the Z band falls outside it (`Grid.update` calls `_grow` with the band cells' extent), and
the windows' empty space carries no points. The dog "walks past the first window", the grid does not.

**Fix (verbatim).** The test now plants one band voxel 1 m past the first window and checks what the old line was
after (the mask grows with the counts and keeps every bit through the origin shift), in wtdd/dog/test_floorplan.py:

```
        self.assertEqual(g.shape, (ff.H, ff.W), "fixture: every object sits inside the first window (check()), so the grid has not grown yet")
        far = (round(g.origin[0] / RES) - 20, 0)   # a cell 1 m past the first window's low-x edge
        g.update(np.array([[far[0] * RES, far[1] * RES, 0.5]]))   # one voxel in the band there: the grid grows on that side
        self.assertGreater(g.shape[1], ff.W, "one band voxel past the window: the grid grew")
        self.assertEqual(g.zmask.shape, g.counts.shape, "the mask grows with the counts")
```

plus `at(g, g.zmask, far) == 1 << round((0.5 - g.z_ref) / RES)` and `count_nonzero(g.zmask) == len(zmask) + 1`.

**Verify.** `python -m unittest wtdd.dog.test_floorplan.Mask` passes, and the same test fails
(`failures=1`) against a `_grow` monkeypatched to pad the counts and keep the old mask: the new lines check something
the old one could not reach.
