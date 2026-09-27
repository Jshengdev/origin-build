# 25-1 · dry mode: GET /dog/state crashes and the page goes blank before the ring can be drawn

## Symptom
On main, from a worktree (no `.env`, no `dog_cal.json`), the 25 screenshot gate had nothing to draw:
- `WTDD_STATE_FIXTURE=wtdd/dog/fixtures/state-led.json WTDD_LEDGER=/tmp/night1/25/ledger-red.jsonl python -m wtdd.api 7932`, then `curl http://127.0.0.1:7932/dog/state`: empty reply (curl exit 52); the API log says `AttributeError: 'DogSession' object has no attribute 'recheck'` (session.py `state()`).
- With the state served, the page still unmounts about a second after load: `lights_status` fails without Hue keys, App stores `{error}` in `status`, and `status.hue.filter(...)` throws, so React drops the whole tree (ring included).

## Root cause
- `DogSession.__init__` sets `self.recheck` only inside `if CAL_FILE.exists():`; `state()` reads it unconditionally (night-1 contracts F3).
- `ui/index.html` guards the lights palette and the "State · read back" panel with `status ? ...` / `${status && ...}`, which is true for the `{error}` object (F1, F1b).

## Fix (verbatim)
wtdd/dog/session.py, immediately before `        if CAL_FILE.exists():   # a calibration survives an API restart`:
```
        self.recheck = False   # no calibration loaded; state() reads this before any connect
```
ui/index.html, patch 1:
```
const palette = Array.isArray(status?.hue) ? [...status.hue.filter(
```
(was `const palette = status ? [...status.hue.filter(`)

ui/index.html, patch 1b:
```
${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>
```
(was `${status && html`<div class="panel"><h2>State · read back</h2>`)

The same bytes as every sibling that applies F1, F1b, F3, so the hunks merge. F2 (roomOf) is not applied: nothing here saves the map or walks.

## Verify
```
python -m unittest wtdd.dog.test_led     # Served.* (state() with no calibration) and Page.test_the_night_1_dry_mode_patches_1_and_1b
WTDD_STATE_FIXTURE=wtdd/dog/fixtures/state-led.json WTDD_LEDGER=/tmp/night1/25/ledger.jsonl python -m wtdd.api 7932 &
curl -s http://127.0.0.1:7932/dog/state    # 200, .led {color: cyan, code: 0}, source "stub"
playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7932/ docs/evidence/night-2/25-remote.png
```
The page stays mounted after 3 s and the ring is drawn (docs/evidence/night-2/25-remote.png, 25-failed.png). The worktree's `ui/tokens.css` symlink dangles (F5), so these screenshots show the page's fallback palette, not the tokens'.
