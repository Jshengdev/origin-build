# 05a-1 · a drag after the dog moved was read as the walk's end

**Symptom.** Found in review, reproduced on the fixture: the truth drag after each walk removed and the next walk's
start drag moved to 30 s after the walk. `python -m wtdd.dog.drift` printed
`walk 1 ... vs drag [448, 455]: sport 1.212 m  utlidar 1.286 m` for walks 1-5, still named
`lower-drift source: utlidar`, and logged no WARN. 1.2 m is the distance from the route end back to the route start,
not drift.

**Root cause.** The report took the first ok `dog.calibrate` within `DRAG_WINDOW_S` (120 s) after a `dog.follow` as
where the dog stood at the end of the walk, with nothing checking that the dog was still there. The live procedure
(walk ends, hand-drive back to the start, drag the dot at the start for the next replay) puts the start drag inside that
window whenever the truth drag is skipped or late.

**Fix (verbatim, wtdd/dog/drift.py report()).**
```python
        if drag is not None:   # the walk's end only if the driver's belief at the drag is still where the walk left it
            at, was = (drag.get("state_before") or {}).get("p"), last.get(args.get("pose_source"))
            moved = round(math.dist(at, was)) if at and was else None
            if moved is None or moved > args["reach_px"]:
                log("drift", f"WARN walk {len(walks) + 1}: the drag at {drag['args']['p']} came after the dog moved "
                    f"{'an unknown distance' if moved is None else f'{moved} px'} from where the walk ended: not this walk's reference")
                drag = None
```
`state_before` of every `dog.calibrate` row is the steering source's belief at the drag; the walk's last sample of
`args.pose_source` is where that belief was when the walk ended. More than the walk's own `reach_px` apart, or either
missing, and the drag is not this walk's reference: WARN, and the walk falls back to the route end (or no number).

**Verify.**
```
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_drift
```
`Report.test_a_drag_after_the_dog_moved_is_not_the_walks_reference` and
`Report.test_a_drag_without_the_belief_at_the_drag_is_not_trusted` (RED in 6546f81, GREEN from fb973f9). On the
reproduction the CLI now prints `WARN walk 1: the drag at [448, 455] came after the dog moved 132 px from where the walk
ended: not this walk's reference` for walks 1-5 and every walk reads `vs route end`. On the dog: drag the dot where the
dog stands right after each walk, before anything moves it.
