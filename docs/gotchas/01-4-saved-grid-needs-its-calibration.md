# 01-4 · A saved grid is only placed right through the calibration it was saved under

**Symptom.** After POST /dog/grid {save: true}, a battery swap, POST /dog/grid {clear: true} and a new "dog is here"
drag, the remote draws ui/grid.json offset and rotated from where the site was, labelled only `ui/grid.json`, with no
`why` and no row. It stays wrong until the LiDAR is switched on again, and for good in the no-dog story. In the
test replaying that sequence, the first wall cell came back at map pixel `[334, 1028]` where it had been saved at
`[156, 708]`.

**Root cause.** ui/grid.json stores cells in odometry metres, and odometry restarts at zero on every power-on. The
file fallback in `DogSession.grid_px` projected it through `self.cal`, the calibration as it is NOW, which after a
power cycle ties a different odometry frame to the map. Nothing in the file recorded which tie its metres belonged
to, so nothing could tell a well-placed file grid from a misplaced one.

**Fix (verbatim).** The grid carries the tie it was saved under, and the file is drawn through it:

```
# wtdd/dog/occupancy.py, Grid.__init__ / to_dict / from_dict
        self.cal: dict | None = None   # the odometry <-> map tie it was saved under (session.cal); None for a replayed fixture
                "frame_id": self.frame_id, "z_band": list(self.z_band), "cal": self.cal,
        g.frames, g.z_band, g.cal = int(d["frames"]), tuple(d["z_band"]), d.get("cal")

# wtdd/dog/session.py, grid_save (inside the dog.grid_save step) and the grid_px file fallback
                g.cal = dict(self.cal) if self.cal else None
                fg = self._grid_file[1]
                return {**occupancy.response(fg, fg.cal or self.cal, threshold, "ui/grid.json"), **errs}
```

The live session grid is still drawn through `self.cal` (the current tie of the current odometry frame; its drift
smear is 05b's). A planted fixture has no `cal` and keeps the session's. Anything else that persists odometry-frame
geometry across an API restart (05b's corrections, 06's cost map) needs the same: save the tie with the metres.

**Verify.** `python -m unittest wtdd.dog.test_occupancy`:
`Persistence.test_a_saved_grid_is_drawn_through_the_calibration_it_was_saved_under` saves a grid under one
calibration on a DogSession (scratch GRID_FILE and ledger), clears it, sets a different calibration, and asserts the
file grid comes back on the same pixels with `source` `ui/grid.json` and `cal` in the file. It failed before the fix
(`[334, 1028] != [156, 708]`) and passes after.
