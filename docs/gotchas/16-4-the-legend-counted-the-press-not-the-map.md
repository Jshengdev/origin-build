# 16-4 · the blobs legend counted the press's erase flag, not what the floor plan greyed

**Symptom.** With `WTDD_DECIDE_THRESHOLD=0.95` and the planted `WTDD_BLOBS=wtdd/dog/fixtures/blobs.json`, GET
/dog/blobs served 1 label with `erase: true`, which the remote's legend counts as `1 greyed`, while GET /dog/floorplan
had `moved: []` and still drew all 3 segments, the shelf's line included. Found by review (probe_greyed.py in the review scratch).

**Root cause.** Each label record carries `erase`, the verdict at the moment it was made: label() stamps it with the
threshold at the press, and make_blobs_fixture.py writes it at p >= 0.7. GET /dog/blobs served that stamp and the page
counted it. GET /dog/floorplan erases again at every read, at the threshold of that read and on the newest plan. The
two disagree as soon as the threshold changes or a newer plan no longer has a run the label covers. Matching a label's
`blob_id` against `moved` does not fix it: ids are indices into the plan the label was made on.

**Fix (verbatim).** wtdd/dog/session.py blobs_px runs the same erase that floorplan_px draws and serves its result:

```
        e = (blobs.erase(res, lab["labels"]) if cal and res and "cls" in res and lab["labels"] else
             {"moved": [], "erased": [False] * len(lab["labels"])})
```

blobs.erase returns `erased`, one flag per label given (did this label move a run in this plan). The page counts
`moved`:

```
  const all = b?.labels || [], failed = all.filter(x => x.label == null).length, greyed = (b?.moved || []).length;
```

**Verify.** `python -m unittest wtdd.dog.test_blobs`:
Serve.test_greyed_is_what_the_floor_plan_moved_at_the_threshold_of_the_read (committed RED at 2843798 with `1 != 0 :
threshold 0.95: a label says greyed, the map did not`, GREEN at e3a5d92). The review's probe now prints 0 labels with
erase true and `moved = []`.
