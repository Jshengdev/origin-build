# 00-1 · GET /dog/state raises on a fresh API, and the remote goes blank without .env

**Symptom.** Two dry-mode failures on main, both hit by goal 00's gates. (1) In a checkout with no `dog_cal.json`,
every `DogSession().state()` raises `AttributeError: 'DogSession' object has no attribute 'recheck'`: `GET /dog/state`
drops the connection, and every test that reads `state()["halted"]` or `state()["person_watch"]` errors before it
checks anything. (2) `python -m wtdd.api 7920` from a checkout with no `.env` draws the page for about a second, then
it goes blank (an empty cream page), so the headless screenshot of the STOPPED line and the stale chip is one flat
colour. The API log shows `lights_status FAILED err=RuntimeError: [wtdd:config] HUE_APP_KEY is required`.

**Root cause.** (1) wtdd/dog/session.py sets `self.recheck` only inside `if CAL_FILE.exists():`, and `state()` reads
it unconditionally. (2) ui/index.html stores a failed `lights_status` as `{ error }` in `status`, and two render lines
treat any truthy `status` as a read: `status.hue.filter(...)` throws a TypeError and React unmounts the tree. This is
contracts F bugs 3 and 1; 01 met (2) first (docs/gotchas/01-1-dry-mode.md on its branch). The bytes below are the
contracts' exact patches, so identical hunks on sibling branches merge clean.

**Fix (verbatim).** wtdd/dog/session.py, one line inserted immediately before
`        if CAL_FILE.exists():   # a calibration survives an API restart, not a dog power cycle (the odometry frame resets then)`:

```
+        self.recheck = False   # no calibration loaded; state() reads this before any connect
```

ui/index.html, two replaced texts:

```
-  const palette = status ? [...status.hue.filter(
+  const palette = Array.isArray(status?.hue) ? [...status.hue.filter(
```

```
-        ${status && html`<div class="panel"><h2>State · read back</h2>
+        ${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>
```

**Verify.** `python -m unittest wtdd.dog.test_halt.NoDog` passes (a fresh session with no calibration serves
`state()` with `connected: false`, `halted` and `person_watch`). Start `python -m wtdd.api 7920` from a worktree with no
`.env` and take `playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600
http://127.0.0.1:7920/ out.png`: before the fix it is blank; after it the map, the panels and the status row
("lights · offline") are drawn.
