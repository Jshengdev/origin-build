# 05a-3 · a source silent at a drag kept its old tie, and a power cycle made that tie a dead frame

**Symptom.** Found in review. Drag the dot with both poses live, power-cycle the dog (both odometry frames reset), drag
again while rt/utlidar/robot_pose is still silent. The drag row logged `WARN no utlidar pose at this drag: utlidar keeps
its old tie`, and its `state_after.cals` and dog_cal.json still carried the pre-cycle utlidar tie beside the fresh sport
one, indistinguishable from it. When utlidar came back, every pose.sample it wrote was projected through the dead frame
and `python -m wtdd.dog.drift` printed that as a valid-looking utlidar end error.

**Root cause.** calibrate() updated `self.cals` with the sources that had a pose (`self.cals.update(ties)`) and only
logged the ones that did not, so a missing source's previous tie survived the drag. A tie is only good in the odometry
frame it was taken in, and nothing on the row says whether that frame still exists.

**Fix (verbatim, wtdd/dog/session.py calibrate()).**
```python
            for s in drift.SOURCES:
                if raws[s] is None:   # a kept tie may be in a frame a power cycle reset: untied, its samples say so
                    had = self.cals.pop(s, None) is not None
                    log("dog", f"WARN no {s} pose at this drag: {s} is untied until a drag sees it", had_tie=had)
```
The selected source's RuntimeError before it is unchanged. The untied source's samples land as
`{"map": null, "why": "no calibration for utlidar"}` (drift.sample), which drift.py counts as uncalibrated and WARNs.

**Verify.**
```
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_drift
```
`Session.test_a_source_silent_at_a_drag_loses_its_old_tie` (RED in 84f6e6e): the second drag's `state_after.cals` and
dog_cal.json hold sport only, and the utlidar samples of the next walk carry map null with the why. The same sequence
on FakeBody into a scratch ledger, then `python -m wtdd.dog.drift --ledger <it>`, logs
`WARN 2 pose.sample rows without a map projection (their source was not calibrated)`, prints the walk as
`sport 0.221 m  utlidar -` and ends `lower-drift source: none (no drag-referenced walk measured utlidar)`. On the dog:
after a power cycle, drag once more when `GET /dog/state` shows `state.utpose` again, or its walks are not measured.
