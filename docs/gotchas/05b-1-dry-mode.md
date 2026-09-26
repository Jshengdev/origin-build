# 05b-1 · GET /dog/state raises until a calibration file exists

**Symptom.** In any checkout without `dog_cal.json` (a worktree, a fresh clone, a test that points `session.CAL_FILE`
at a temp directory), `DogSession().state()` raises before any dog is connected:

```
AttributeError 'DogSession' object has no attribute 'recheck'
```

GET /dog/state answers 500 on every poll of a fresh API, and `test_localize.Session.test_the_believed_pose_is_the_corrected_one`
(which reads `state()["corr"]`) errors instead of checking the corrected pose.

**Root cause.** `DogSession.__init__` set `self.recheck` only inside `if CAL_FILE.exists():` (a loaded calibration
is "to be confirmed"), and `_ensure()` sets it only on a stale reconnect; `state()` reads `self.recheck`
unconditionally. With no saved calibration the attribute never exists. This is known bug 3 of the night-1 preflight,
on main and on feat/01-occupancy alike.

**Fix (verbatim, the line inserted in wtdd/dog/session.py immediately before
`        if CAL_FILE.exists():   # a calibration survives an API restart`).**

```
        self.recheck = False   # no calibration loaded; state() reads this before any connect
```

The same bytes as every sibling branch that needs it, so the identical hunks merge without a conflict.

**Verify.** With `session.CAL_FILE` patched to a path that does not exist, `DogSession().state()` returns a dict with
`recheck: False` instead of raising; `python -m unittest wtdd.dog.test_localize` runs its Session case green.
