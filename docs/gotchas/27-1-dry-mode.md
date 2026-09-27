# 27-1 · the remote goes blank in dry mode, and /dog/state raises before any calibration

## Symptom
In a worktree (no .env, no lights, no dog_cal.json), the remote draws for about a second and then the page goes blank,
so a screenshot of the legend and the gauges shows nothing. With the page guarded, every GET /dog/state still answers
500 `AttributeError: 'DogSession' object has no attribute 'recheck'`, so the dog card and the dog tiles never get a
state to draw. "save" and "▶ walk the path" also throw `ReferenceError: roomOf is not defined`.

## Root cause
1. `POST /tools/lights_status` fails without the Hue and Tuya keys (fail loud, on purpose), and the page stores
   `{error}` as `status`. `const palette = status ? [...status.hue.filter(` then calls `.filter` on `undefined`, and
   React unmounts the whole app. The read-back panel (`${status && html`...`) does the same with `status.hue` and
   `status.strip`.
2. `withRooms` calls `roomOf`, which no line of ui/index.html defines.
3. `DogSession.__init__` sets `self.recheck` only inside `if CAL_FILE.exists():`, and `state()` reads it on every
   call, so a fresh API with no dog_cal.json raises on every GET /dog/state.

## Fix (verbatim, the bytes of the night-1 contracts section F, Patches 1, 1b, 2 and 3)
- ui/index.html: `const palette = status ? [...status.hue.filter(` became
  `const palette = Array.isArray(status?.hue) ? [...status.hue.filter(`
- ui/index.html: `${status && html`<div class="panel"><h2>State · read back</h2>` became
  `${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>`
- ui/index.html, right after the `const inside = ...` line:
  `const roomOf = (p, rooms) => ((rooms || []).find(r => inside(p, r.poly)) || {}).name || null;   // the room a map point sits in, for the page's save; field.py recomputes it anyway`
- wtdd/dog/session.py, immediately before `        if CAL_FILE.exists():   # a calibration survives an API restart`:
  `        self.recheck = False   # no calibration loaded; state() reads this before any connect`

## Verify
```
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_page_layers.Patches wtdd.test_page_layers.StateFixture.test_unset_is_a_disconnected_dog_not_an_error
WTDD_LEDGER=/tmp/night2/27/ledger.jsonl /Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.api 7934 &
curl -s http://127.0.0.1:7934/dog/state        # {"connected": false, ..., "recheck": false, ...}, not a 500
playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7934/ /tmp/night2/27/remote.png
```
The tests pass, /dog/state answers `connected: false`, and the screenshot shows the map, the legend and the gauges
rather than a blank page (docs/evidence/night-2/27-failed.png is this run).
