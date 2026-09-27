# 16-5 · a failed press wrote the LiDAR count under the key every label row uses for the p threshold

**Symptom.** Pressing "name blobs" (POST /dog/blobs) with no dog wrote one failed blob.labelled row with
`"args": {"blob_id": null, "threshold": 3, ...}`, and the first 16-failed.png showed `"threshold":3` in the receipts.
Every label row from blobs.label() writes `args.threshold = 0.7`, WTDD_DECIDE_THRESHOLD. A grader or record page that
compares p against args.threshold on blob.labelled rows (livecheck 16.2 does) would read 3 on a failed press, and could
not tell the count from the p. Found by review.

**Root cause.** session.blobs_label takes `threshold`, the LiDAR count threshold of the plan it labels
(occupancy.THRESHOLD = 3, the POST body's `{threshold?}`), and its failure path passed it straight into the row's args
under the name `threshold`. blobs.label names a different number the same way: the p cut above which a furniture word
greys a run. Same key, same row type, two meanings.

**Fix (verbatim).** wtdd/dog/session.py blobs_label, the failed press's row:

```
            # args.threshold is WTDD_DECIDE_THRESHOLD on every blob.labelled row, None here as in label() before it is read
            with step("blobs", "blob.labelled", "unitree", {"blob_id": None, "lidar_threshold": threshold, "threshold": None,
                                                             "shift_id": decide.shift_id()}, before):
```

`threshold` is None rather than a read of WTDD_DECIDE_THRESHOLD because decide.threshold() raises on a malformed value,
and the failure path must never raise a second error over the first.

**Verify.** `python -m unittest wtdd.dog.test_blobs`:
Serve.test_a_press_with_no_dog_is_one_failed_row_and_the_page_says_failed now asserts `args.lidar_threshold == 3` and
`args.threshold is None` (committed RED at 85065da with `KeyError: 'lidar_threshold'`, GREEN at ba8a59d). The retaken
docs/evidence/night-2/16-failed.png shows `"lidar_threshold":3,"threshold":null` in the receipts.
