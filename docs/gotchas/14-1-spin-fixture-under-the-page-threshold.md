# 14-1 · The spin fixture's grid draws nothing on the remote

**Symptom.** A `ui/grid.json` planted from the spin replay, as in
`python -m wtdd.dog.scout --replay wtdd/dog/fixtures/spin_frames.npz --png /tmp/s.png --save ui/grid.json`, draws no
cells on the remote. The grid label reads `grid · 0 cells seen 3+ times · 8 frames · ui/grid.json · 0 cells seen 3+
times in 8 frames`, although the replay itself exits 0 and reports all four walls found (`front=102/102 ...`).

**Root cause.** The spin fixture places each wall cell in exactly one 45-degree wedge. That is how it makes "the walls
fill in as the nose comes round" checkable, so every cell ends with count 1, and the replay checks walls at its
own `--threshold` default of 1. The remote's GridLayer polls `GET /dog/grid` with no threshold, which is 01's
`occupancy.THRESHOLD = 3`. The real L1 sees 360 degrees in every frame, so on the dog each cell is counted many times
over a 12 s turn. Only the fixture sits under the page's threshold.

**Fix (verbatim).** Neither threshold changes. The screenshot's grid is planted from a `DogSession.scout` run on the
test's FakeBody with the eight wedges fed three times, and the planted `ui/grid.json` is that run's own session grid.
The planted row and the drawn grid then describe the same 24 frames (scratch script, not committed:
`/tmp/night1/14/plant.py`):

```
ok, s_ok = run(FakeBody(yaw_rate=0.5, frames=frames() * 3), z=0.5, target_deg=360, timeout_s=30)
s_ok.grid.save(Path(os.getcwd()) / "ui" / "grid.json")   # the planted ui/grid.json IS the grid the planted row describes
```

Every row that run wrote is relabelled `cached: true, source: "stub"` before it is used as the fixture ledger, so no
fixture row claims to be live.

**Verify.**

```
python -m wtdd.dog.scout --replay wtdd/dog/fixtures/spin_frames.npz --png /tmp/g1.png --save /tmp/g1.json
python -c "import math; from wtdd.dog import nav, occupancy as o; g = o.Grid.load('/tmp/g1.json'); c = nav.calibration((0,0,0), 0, (530,770), -math.pi/2); print([o.response(g, c, t, 'f')['n'] for t in (o.THRESHOLD, 1)])"
```

prints `[0, 404]`: nothing at the page's threshold, and the four walls at the replay's. The planted three-pass grid
gives `n 404` at threshold 3 (docs/evidence/night-2/14-remote.png).
