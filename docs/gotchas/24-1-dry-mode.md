# 24-1 · dry mode: GET /dog/state raises without a calibration file, and the page blanks without Hue keys

**Symptom.** Two failures, both before any vitals code runs, both in any checkout without `dog_cal.json` and `.env`
(every worktree):
1. `DogSession().state()` raises `AttributeError: 'DogSession' object has no attribute 'recheck'` (wtdd/dog/session.py,
   the `"recheck": self.recheck` key of `state()`). GET /dog/state answers 500 on every fresh API until someone
   calibrates. In `python -m unittest wtdd.dog.test_vitals` on the RED commit, three Session/Fixture tests error on
   exactly this line before they reach the missing vitals code.
2. `python -m wtdd.api 7931` serves the page, which draws for about a second and then goes blank: `lights_status`
   fails (`HUE_APP_KEY is required`), the page stores `{ error }` as `status`, and two render lines call
   `status.hue.filter(...)` on it. React unmounts the tree, so the Vitals strip can never be screenshotted.

**Root cause.** 1: `self.recheck` is assigned only inside `if CAL_FILE.exists():` in `DogSession.__init__` (and later
in `calibrate()` and the stale reconnect), so with no `dog_cal.json` the attribute never exists. 2: the palette line and
the "State · read back" panel treat any truthy `status` as a successful lights read (the same bug as 01-1-dry-mode.md).

**Fix (verbatim; the night-1 contract patches 3, 1 and 1b, byte for byte, so identical hunks on 05b, 01, 04, 07, 08
and 09 merge clean).**

wtdd/dog/session.py, immediately before `        if CAL_FILE.exists():   # a calibration survives an API restart`:
```
+        self.recheck = False   # no calibration loaded; state() reads this before any connect
```

ui/index.html:
```
-  const palette = status ? [...status.hue.filter(
+  const palette = Array.isArray(status?.hue) ? [...status.hue.filter(
```
```
-        ${status && html`<div class="panel"><h2>State · read back</h2>
+        ${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>
```

A calibration file still sets `recheck = True` on load (the line after), so the live behaviour with a calibration is
unchanged. With the lights failing, the palette falls back to the map's own lights and the read-back panel is not
drawn; the status row still says "lights · offline", so the failure stays visible.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_vitals -v` from a
worktree: the Session and Fixture tests reach their own assertions (no `recheck` AttributeError). Then
`WTDD_STATE_FIXTURE=wtdd/dog/fixtures/state-vitals.json /Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.api 7931`
and `playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7931/ out.png`:
the page is drawn after 3 s, not blank.
