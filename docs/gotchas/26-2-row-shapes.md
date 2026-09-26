# 26-2 · a dog row's pose is flat on state_before, and a record row carries counts, not points

**Symptom.** Reading the place a row names by the goal's wording finds nothing on main's rows. The goal names
`state_before.map.p` for `dog.follow` and "the saved path's points" for `dog.record`. In the sample ledger
(`docs/evidence/ledger-sample-2026-09-13.jsonl`) row 11, a FAILED `dog.follow`, has
`"state_before": {"p": [412, 460], "heading_deg": -94.0}` (no `map` key), and row 29, a `dog.record`, has
`"state_before": null, "state_after": {"path_pts": 23, "stops": [], "length_px": 1190, "seconds": 49.5}` (no points).
Only feat/05b-localize's `pose.corrected` row nests the pose, as `state_before.map.p`.

**Root cause.** `wtdd/dog/session.py` passes `self.map_pose()` as `state_before`, and `map_pose()` returns the flat
`{"p": [px, py], "heading_deg": h}`: `calibrate()` at session.py:240 and `_follow()` at session.py:283. Only the
follow's end pose is nested, as `state_after.map` (session.py:317). `record()` writes the counts, `path_pts` and
`length_px`, into `state_after` (session.py:173-175). The path's points go to `ui/map.json` and are overwritten by the
next recording or the next save.

**Fix (verbatim).** The kind table in `wtdd/marks.py` reads each shape where it is:
`start, end = sb.get("p"), (sa.get("map") or {}).get("p")` for `dog.follow`, where `sb` is `state_before` and `sa` is
`state_after`. For `dog.record` it serves the map's path only while it still matches the row's own receipts:
`if len(path) == sa.get("path_pts") and _len(path) == sa.get("length_px"):`. Otherwise it serves `px: None` and a
`why` naming both.

**Verify.** `python -m unittest wtdd.test_marks`. Row 0 (calibrate) gives the vector `[-17, 554] -> [442, 498]` at
4.26 m. Row 11 (FAILED follow) gives `[412, 460] -> [448, 647]`. Row 29 (record) against today's 48-point map gives
`why: "the row recorded 23 pts / 1190 px; the map's path is 48 pts / 2953 px now"` (served by GET /marks on port 7933).
