# 30-3 · the dry page goes blank, and GET /dog/state raises on a fresh API

**Symptom.** Two failures in a worktree (no .env, no dog_cal.json) with `python -m wtdd.api 7937`:
- the remote renders, then goes blank about a second later;
- `GET /dog/state` answers 500, `AttributeError: 'DogSession' object has no attribute 'recheck'`. The same error made `wtdd.dog.test_audio.Served` and `.Fixture` fail in RED.

Either one blocks the speaker badge's screenshot.

**Root cause.**
- `lights_status` fails with no Hue keys, and the page stores `{error}` in `status`. `ui/index.html` then calls `status.hue.filter(...)` for the palette and the "State · read back" panel. The TypeError unmounts React.
- `DogSession.__init__` sets `self.recheck` only when `dog_cal.json` exists, but `state()` reads it every time.

These are night-1 contracts F bugs 1 and 3.

**Fix (verbatim).** The contracts' patches, byte for byte, so identical hunks on sibling branches merge cleanly.

- Patch 1 (ui/index.html):
  `const palette = status ? [...status.hue.filter(` → `const palette = Array.isArray(status?.hue) ? [...status.hue.filter(`
- Patch 1b (ui/index.html):
  `${status && html`<div class="panel"><h2>State · read back</h2>` → `${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>`
- Patch 3 (wtdd/dog/session.py), inserted immediately before `        if CAL_FILE.exists():   # a calibration survives an API restart`:
  `        self.recheck = False   # no calibration loaded; state() reads this before any connect`

Patches 2, 4 and 5 are not applied: this item's gate does not need them.

**Verify.**
- `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_audio.Served wtdd.dog.test_audio.Fixture -v` passes.
- With `WTDD_STATE_FIXTURE=<abs>/wtdd/dog/fixtures/state-say.json python -m wtdd.api 7937`, the headless screenshot `docs/evidence/night-2/30-remote.png` shows the full page with the speaker badge. `30-failed.png` shows the red `say FAILED` state from `state-say-failed.json`.
