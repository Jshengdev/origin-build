# 07-1 · a fixture box's upper bound is not one of its cells

**Symptom.** With `wtdd/dog/objects.py` in place, `python -m unittest wtdd.dog.test_objects` failed one test,
`Association.test_a_blob_seen_once_is_found_at_threshold_1_and_not_at_2`:

```
Mismatch at index:
 [1]: -0.85 (ACTUAL), -0.8 (DESIRED)
```

The ray from the origin down odometry -y found the BLOB of `make_voxel_frames.py` at y = -0.85 m, and the test
expected -0.8 m.

**Root cause.** `make_voxel_frames.py` declares every world box as a half-open index range `[lo, hi)`. BLOB's y is
`(-20, -16)`: cells -20, -19, -18, -17, lattice points -1.0, -0.95, -0.9, -0.85 m. -0.8 m is index -16, the open
edge, and the grid counts 0 there (probed: `g.cell(0.0, -0.8) == 0`, `g.cell(0.0, -0.85) == 1`). A ray coming down
from y = 0 first lands in the -0.85 m cell (np.rint onto the lattice, Grid.cell's own rule), so no correct
nearest_blob can return -0.8 on this fixture. The expectation had been written from the box's bounds, not from its
last cell.

**Fix (verbatim, wtdd/dog/test_objects.py).**

```
-        np.testing.assert_allclose(h["xy"], [0.0, -0.8], atol=1e-9)
+        # BLOB's y is the half-open index range (-20, -16): lattice points -1.0 .. -0.85 m; -0.8 m (index -16) is outside it
+        np.testing.assert_allclose(h["xy"], [0.0, (fx.BLOB["y"][1] - 1) * fx.RES], atol=1e-9)
```

Any expectation about where a ray first meets a fixture box is the box's last (or first) lattice point, `(hi - 1) *
RES` from above and `lo * RES` from below, never `hi * RES`.

**Verify.** `python -m unittest wtdd.dog.test_objects`: Ran 32 tests, OK. The same test still asserts count 1 at
threshold 1 and None at threshold 2 (the blob is seen in one frame only).
