# 05b-2 · The correction moved for a window the grid refused, with no row

**Symptom.** Review round 1 (probe B on 59ee282): a drifted window that matched and was inside the cap, fed while
the grid refused to take it (01's MAX_SIDE `ValueError` from `Grid.update`), left the session with

```
corr 0.10 -> 0.15, pose.corrected rows written 0, cb_errors 1
```

The believed pose (and the dot on the remote) moved by a correction that has no receipt, and GET /dog/lidar counted
the window as `applied`.

**Root cause.** `DogSession._relocalize`'s applied branch composed the delta into `self.corr` (and bumped the
`applied` counter) before it drew the window, and wrote the `pose.corrected` row after the draw. `Grid.update` is the
one call in the branch that can raise; when it did, the state change before it stayed and the row after it never
came. Body's callback guard counts the raise, so the stream went on with a belief nobody logged.

**Fix (verbatim, the applied branch of `_relocalize` in wtdd/dog/session.py).**

```
        delta = localize.delta_about(pivot, m["dx"], m["dy"], m["dtheta"])
        touched = self.grid.update(localize.apply_points(delta, xy))   # first: a grid that refuses the window (01's MAX_SIDE) raises here and nothing moves
        self.corr = localize.compose(self.corr, delta)
        loc["applied"] += 1
        loc["rejected_streak"], loc["last"] = 0, last
        append(localize.row(m, kind, before, snap()))
```

with the `unmatched` and `rejected` counters and `loc["last"]` set in their own branches (`if verdict != "applied":`)
instead of before the branch. The rule: in a callback, the call that can raise goes first, then the state change, then
the receipt.

**Verify.** `python -m unittest wtdd.dog.test_localize.Session.test_a_window_the_grid_refuses_moves_nothing`: with
`self.s.grid.update` patched to raise on the second drifted window, `self.s.corr` stays at the first window's
correction, no row is appended, `grid.frames` and `localize.applied` are unchanged, and `cb_errors` is 1.
