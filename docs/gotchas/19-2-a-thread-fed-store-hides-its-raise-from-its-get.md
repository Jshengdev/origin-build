# 19-2 · a store fed by a thread hides that thread's raise from its own GET

**Symptom.** With `WTDD_DECIDE_THRESHOLD=abc` in .env (or ui/map.json unreadable), the scout proposed nothing, ever,
while 07 had the chair pinned. The page said the wrong thing:

```
AssertionError: 'WTDD_DECIDE_THRESHOLD' not found in '' : {'n': 0, 'proposals': [], 'failed': [], 'why': 'no placed object yet: the scout asks once about each thing 07 pins on the grid'}
AssertionError: 'no pose' not found in 'no placed object yet: the scout asks once about each thing 07 pins on the grid' : not 'no placed object yet': 07 placed two
```

The only trace was one stderr line from the objects thread, `[wtdd:objects] WARN tick FAILED err=...`. Objects waiting
for a pose read the same "no placed object yet".

**Root cause.** 07's GET /dog/objects re-runs objects_state(), so a raise there reaches the page as a 500. GET /dog/scout
only reads Proposals.state(), and the feed runs on the objects thread, which logs the raise and tries again next tick.
The raise happened before any object was marked handled, so state() had nothing to say but its empty-store why.

**Fix (verbatim, wtdd/dog/scout_zones.py).**

```python
        try:
            return self._feed(objs, frame, pose, grid, cal, fov_deg, threshold, grid_lock)
        except Exception as e:
            with self._lock:
                self.error = f"feed: {type(e).__name__}: {e}"
            raise
```

plus `self.error = None` once a feed gets past the threshold and the map read, `"error": error` in state() whenever it
is set, and `why = warned or ("no object taken: the last feed FAILED (error)" if error else ...)`. The page already drew
`s.error` red on the layer line and the panel.

**Verify.**

```
.venv/bin/python -m unittest wtdd.dog.test_scout_zones.Feed.test_a_feed_that_raises_is_named_on_the_get_not_an_absence \
    wtdd.dog.test_scout_zones.Feed.test_placed_objects_waiting_for_a_pose_say_so
```

Both fail on 9491174 (`'WTDD_DECIDE_THRESHOLD' not found in ''`, `'no pose' not found in 'no placed object yet ...'`)
and pass on 5d8656f.
