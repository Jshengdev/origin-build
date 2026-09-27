# 15-4 · A finer rho histogram picks the lattice's own axes, not the walls

**Symptom.** A closed 4 x 3 m room (`closed_room` in wtdd/dog/test_floorplan.py), walls 1 to 3 cells thick, turned 0 to
89 degrees. With the main direction chosen as the single highest 1-cell bin, a thick or cornered wall ties with a
1-degree tilt: walls came out doubled (7 segments for 4 walls at 2 cells thick, square) and tilted. The first repair,
the sum of squared counts over bins a quarter of a cell wide (`np.rint(rho * 4)`), made it worse: a room turned a few
degrees off the axes or off 45 degrees came back drawn on the lattice's axes or its diagonal, with up to 13 segments
and 152 wall cells dropped into tall blobs (a scratch sweep of 270 turns and thicknesses, THICK 0.15 m: 63 failing,
against 11 with half-cell bins and 7 with the fix below, all 7 at 3 cells thick).

**Root cause.** On the axes (and near 45 degrees) every cell's rho is a whole number (or a multiple of 1/sqrt 2), so
all of a room's cells land on a few fine bins and leave the rest empty. The squared sum rewards that, however far the
room is really turned, and the finer the bins the bigger the reward. With 1-cell bins, a turned wall's staircase
(its cells within half a cell of the true line) is cut in two by a fixed bin edge, and that split can score below a
1-degree tilt.

**Fix (verbatim).** wtdd/dog/floorplan.py `_runs`: a one-cell window, slid along rho in quarter-cell steps, counts
squared and summed. The window is a cell wide, so the lattice earns nothing; the quarter steps mean some window always
holds a whole staircase. Quarter bins by `np.floor`, never `np.rint` (half to even would merge whole offsets):

```
        q = np.floor((x * math.cos(math.radians(a)) + y * math.sin(math.radians(a))) * 4).astype(np.int64)
        cum = np.concatenate([[0], np.cumsum(np.bincount(q - q.min() + 3), dtype=np.int64), np.zeros(3, np.int64)])
        cum[-3:] = cum[-4]   # 3 empty quarter bins at each end: every window that touches a cell is counted
        w = cum[4:] - cum[:-4]
        score.append(int((w * w).sum()))
```

It costs one bincount per angle, like the rule it replaces (66 ms on a 602 x 601 site with 34k occupied cells, as
before).

**Verify.** `python -m unittest wtdd.dog.test_floorplan.ClosedRoom`: every whole degree from 1 to 89, walls 1 and 2
cells thick, is 4 segments with every wall cell a wall. Put back the single highest bin
(`r = np.rint(rho)`; `score.append(int(np.bincount(r - r.min()).max()))`) and 4 cases fail, at 8, 43, 47 and 82
degrees.
