# 22-3 · a fixture shaped by guesswork hid a step that could never pass on the dog

**Symptom.** The goal's own verifying command, `python -m wtdd.livecheck --step 01.3 --ledger
wtdd/livecheck/fixtures/ledger-01-3.jsonl --log wtdd/livecheck/fixtures/api-01-3.log --replay`, printed `PASS 01.3`.
On rows shaped like feat/01-occupancy's, the same step printed
`WARN ... state_after.extent_m gte 3: saw {"x": [-3.2, 6.4], "y": [-3.2, 3.2]}`, then
`FAIL 01.3 · timeout after 180 s: missing dog.grid_save where ... state_after.extent_m gte 3`. The fatal-WARN fixture
also carried `frame_id map is not odom`, a message feat/01 never prints.

**Root cause.** fixtures/make.py wrote `extent_m` as a number (5.6, 8.9) and invented the refusal text, while its
docstring said it followed feat/01's rows. On feat/01, `session.grid_save` writes `extent_m = Grid.extent_m()`, which is
`{"x": [x0, x1], "y": [y0, y1]}` (occupancy.py). `_holds("gte", ...)` on a dict is False. The refusal is
occupancy.update_frame's `frame_id 'map' is not the grid's 'odom': another frame, refused`. The same session showed a
second false belief from the invented text: feat/01 refuses only a frame_id that changes, so a frame that is
consistently not odom never prints the callback WARN.

**Fix (verbatim, wtdd/livecheck/fixtures/make.py, then `python wtdd/livecheck/fixtures/make.py`).**

```
"extent_m": {"x": [-3.2, 3.2], "y": [-3.2, 3.2]}}     # SAVE_0
"extent_m": {"x": [-3.2, 6.4], "y": [-3.2, 3.2]}}     # SAVE_1
GRID_STARTED = "[wtdd:dog] grid started frame_id=odom resolution=0.05 origin=[-3.2, -3.2]\n"
LOG_WARN = LOG_OK.replace(GRID_STARTED, GRID_STARTED + "[wtdd:dog] WARN lidar frame callback failed err=ValueError: frame_id 'map' is not "
                          "the grid's 'odom': another frame, refused errors=1\n")
```

In steps.json, 01.3 drops `state_after.extent_m` from `where` (a person reads the growth on GET /dog/grid). 01.1 and
01.3 gain the fatal regex `first lidar frame frame_id=(?!odom\b)`, and 01.1 gains a `dog.grid_save` row with
`args.frame_id` `odom`. Rule: copy a fixture's row and log shapes from the branch that writes them
(`git show origin/feat/<nn>-*:<file>`), never from a note.

**Verify.** `python -m unittest wtdd.livecheck.test_livecheck` runs 25 tests OK. `Replay.test_fixture_pass_names_its_row`
passes on the dict-shaped rows. `Rows.test_01_1_grades_the_frame_id_from_the_device` shows `first lidar frame frame_id=map`
failing 01.1, and a LiDAR never switched on timing out on `dog.grid_save`.
