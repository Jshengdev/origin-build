# 04-1 · the remote goes blank, and cannot save, in dry mode

## Symptom
In a worktree (no .env, no lights), the remote draws for about a second and then the page is blank. Once that is
guarded, clicking "save" or "▶ walk the path" throws `ReferenceError: roomOf is not defined` in the console and no
POST /map is ever sent, so a zone drawn on the map can never be saved.

## Root cause
1. `POST /tools/lights_status` fails without HUE_APP_KEY (fail loud, on purpose), and the page stores `{error}` as
   `status`. `const palette = status ? [...status.hue.filter(` then calls `.filter` on `undefined`, React unmounts the
   whole app. The State panel (`${status && html`...`) does the same with `status.hue` and `status.strip`.
2. `withRooms` (the step `saveMap` and `play` both take before POST /map) calls `roomOf`, which no line of
   ui/index.html defines.

## Fix (verbatim, the bytes of the night-1 contracts section F, Patches 1, 1b and 2)
- ui/index.html: `const palette = status ? [...status.hue.filter(` became
  `const palette = Array.isArray(status?.hue) ? [...status.hue.filter(`
- ui/index.html: `${status && html`<div class="panel"><h2>State · read back</h2>` became
  `${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>`
- ui/index.html, after the `const inside = ...` line:
  `const roomOf = (p, rooms) => ((rooms || []).find(r => inside(p, r.poly)) || {}).name || null;   // the room a map point sits in, for the page's save; field.py recomputes it anyway`

## Verify
```
cp wtdd/fixtures/map_nogo.json /tmp/night1/04/map.json
WTDD_MAP=/tmp/night1/04/map.json .venv/bin/python -m wtdd.api 7804 &
playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7804/ /tmp/remote.png
```
The screenshot shows the map, not a blank page. Clicking "save" sends POST /map (200 `{"ok": true, ...}`) and the
console has no `pageerror`.
