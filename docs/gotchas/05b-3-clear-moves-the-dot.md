# 05b-3 · Clearing the grid under a correction moved the dot and the remote still read "located"

**Symptom.** Review round 1 (probe D on 59ee282): drag the dog to map (300, 900) while the correction is
(0.15, -0.05), then POST /dog/grid {clear: true} without a power cycle (a bad grid cleared from the page, or the
"windows past the cap in a row" WARN followed on a dog that was not power-cycled). The dot jumps to (286, 890) and
GET /dog/state still says `recheck: false`, so the remote's status reads "located" and nothing asks for a drag. The
`dog.grid_clear` row names `corr_before`, so the amount is receipted, but the belief afterwards is wrong by it.

**Root cause.** The dot is `nav.to_map(cal, apply_pose(corr, odometry))`. `calibrate()` ties the corrected pose and
keeps the correction (05b's design: the grid is drawn through it); `grid_clear()` resets `corr` to identity with the
grid it was measured against, but leaves `cal` as it was. With a calibration in force, dropping a non-identity
correction therefore moves the dot by exactly that correction, and nothing flagged it.

**Fix (verbatim, inside the `dog.grid_clear` step in wtdd/dog/session.py, before the grid and the correction are
dropped).**

```
                if self.cal is not None and tuple(self.corr) != localize.IDENTITY:   # the dot is drawn through it: dropping it moves the dot
                    self.recheck = True
                    log("dog", "WARN grid cleared under a correction: the dot moved by it, drag the dog to where it is", corr=before["corr_before"])
```

and `r["state_after"] = {"cleared": True, "corr_reset": True, "recheck": self.recheck}`. ui/index.html already renders
`recheck` as "confirm its location (drag it)"; the next drag sets it back to false. The narrower choice was kept on
purpose: re-expressing `cal` in the raw frame (so the dot does not move) is more algebra in a shared file, and a clear
usually follows a power cycle, after which the tie is stale anyway. Without a calibration nothing is set: the page
says "not calibrated", not "reconnected".

**Verify.** `python -m unittest wtdd.dog.test_localize.Session.test_a_clear_under_a_correction_asks_for_the_drag_again`:
drag, feed the drifted windows, clear; `state()["recheck"]` is true and the `dog.grid_clear` row's
`state_after.recheck` is true.
