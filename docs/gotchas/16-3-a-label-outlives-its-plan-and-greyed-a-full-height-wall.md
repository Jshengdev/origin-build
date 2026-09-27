# 16-3 · a label outlives the plan it was made on, and it greyed a wall the newest plan sees at full height

**Symptom.** A shelf label at p 0.95 whose cells are wall_a's run (full height, never offered to a model) made
`blobs.erase` move that run: `moved ['r0']`, 0 of wall_a's 108 cells still class 1, and 3 segments became 2. On the
remote, the full-height wall lost its line and turned grey. Found by review (probe_tall.py in the review scratch).

**Root cause.** find() offers only runs whose top is below TALL, but erase() matched a label to the plan it was
given by cell overlap alone and never asked how high that run is now. Labels live longer than plans: the session keeps
a press's labels until the next press or grid_clear, GET /dog/floorplan re-erases them into the newest plan on every
2 s read, and WTDD_BLOBS can plant any cells. The pack's own case: a far wall is seen only to 0.9 m at the first stop,
it is offered and named shelf at 0.8, then the dog walks closer, the wall fills in to full height, and it stayed grey
with no line.

**Fix (verbatim).** wtdd/dog/floorplan.py `_plan` says, per run, whether it reaches TALL (carried by run(), dropped
from the JSON like runs):

```
    out["full"] = [bool(tallc[grounded][t].any()) for t in takes]
```

wtdd/dog/blobs.py find() skips a run by that one flag, and erase() never moves it:

```
    gone = sorted({k for c in covers for k in c if not plan["full"][k]})
    refused = sorted({k for c in covers for k in c if plan["full"][k]})
```

A refusal is listed in `refused` and WARNed once per label and run (`[wtdd:blobs] WARN erase refused: ...`), not on
every read. No constant changed.

**Verify.** `python -m unittest wtdd.dog.test_blobs`: Erase.test_a_furniture_word_never_greys_the_full_height_wall
(committed RED at 0b847db with 188 cells moved from 1 to 3, GREEN at a7982ff). The review's probe now prints `moved: []
| wall_a cells still class 1: 108 of 108 | segments 3 -> 3`.
