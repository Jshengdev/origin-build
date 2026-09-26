# 05a-2 · the summary named a lower-drift source from route-end walks, and a late drag was dropped silently

**Symptom.** Found in review, reproduced on the fixture: every truth drag moved to 200 s after its walk (past
`DRAG_WINDOW_S` = 120 s, the dog not moved in between). `python -m wtdd.dog.drift` printed `vs route end [436, 586]`
on all six walks, correctly, but its last line still read
`lower-drift source: utlidar (0.322 m vs 0.329 m over 6 walks)`, and stderr carried only the report line: no WARN.
The same with the truth drags dropped entirely. Those two means are each driver's own belief (0.000 m on every walk it
drove) averaged with the other source's disagreement (0.60-0.69 m): not drift.

**Root cause.** report() built `sources` and `lower` from every walk that had a number, whatever its reference. Measured
from the route end, the driving source's error is under reach_px by construction (the follower stops where its own
source believes the end is), so the comparison is degenerate and says nothing about which source drifts. Separately, the
drag lookup was `drag = q if _t(q) - _t(r) <= DRAG_WINDOW_S else None; break`: a first drag past the window was dropped
without a word, so on the dog "you dragged too late" read the same as "you never dragged".

**Fix (verbatim, wtdd/dog/drift.py report()).**
```python
            if q.get("tool") == "dog.calibrate" and q.get("ok"):
                drag, dt = q, _t(q) - _t(r)
                if dt > DRAG_WINDOW_S:
                    log("drift", f"WARN walk {len(walks) + 1}: the first drag came {dt:.0f} s after the walk, past "
                        f"DRAG_WINDOW_S={DRAG_WINDOW_S}: not this walk's reference")
                    drag = None
                break
```
```python
    sources, dragged = {}, [w for w in walks if w["truth"] == "drag"]   # a route-end number is a belief, not a drift
    for s in SOURCES:
        errs = [w["end"][s]["err_m"] for w in dragged if w["end"][s]]
```
```python
    elif not dragged:
        rep["why"] = ("no walk has a drag after it: the route-end numbers only say where each source believed the end was "
                      "(the driver's is under reach_px by construction)")
```
plus `n_drag` in the report, `drag_walks=` on the stderr line, and format()'s last line
`over <n_drag> drag-referenced walks`. The route-end numbers stay on each walk's line.

**Verify.**
```
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_drift
```
`Report.test_without_a_drag_the_reference_is_the_route_end_and_the_driver_only_reports_its_own_belief` and
`Report.test_a_late_drag_is_not_the_walks_reference_and_says_so` (RED in 00e5dc7). On the reproduction the CLI now logs
`WARN walk 1: the first drag came 200 s after the walk, past DRAG_WINDOW_S=120: not this walk's reference` for all six
walks and ends `lower-drift source: none (no walk has a drag after it: ...)`. On the dog: drag the dot where the dog
stands within two minutes of each walk ending, before anything moves it.
