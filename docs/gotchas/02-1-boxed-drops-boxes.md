# 02-1 · dog_say.boxed() threw away the detector's boxes

**Symptom.** A stop's text state could only ever say "footprint: unknown. height: unknown." on the real round: `look_and_see()` had the detector's class counts in hand but no box to measure, although `python -m wtdd.watch --source <file> --once` prints the boxes.

**Root cause.** `wtdd/watch.py` `--once` prints `{ts, ms, n, classes, boxes, file}` (the `boxes` are `[{name, conf, xyxy}]` from `detect()`), and `wtdd/tools/dog_say.py` `boxed()` built its result from `file`, `classes` and `n` only, so every caller downstream of `boxed()` lost the geometry the detector had measured.

**Fix (verbatim, `wtdd/tools/dog_say.py` `boxed()`).**
```python
        r["state_after"] = res
        res = {**res, "boxes": d["boxes"]}   # [{name, conf, xyxy}] for decide's footprint words; the row keeps the counts
```
The `watch.boxes` row keeps its counts-only `state_after` (no bloat); the returned dict carries the boxes. `d["boxes"]` is read strictly: a detector that stops printing boxes fails its own `watch.boxes` row instead of wording every stop "unknown".

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide.State wtdd.test_decide.Ordering` passes (the take's first stop words its largest box as "footprint: large. height: tall."). On the dog: after a round, the stderr line `[wtdd:decide] state ... footprint=<small|medium|large>` at a stop where the detector saw something; `footprint=unknown` there means the boxes were lost again.
