# 17-2 · the remote goes blank in dry mode, and the Rules panel with it

**Symptom.** Served from this worktree (no `.env`, so no Hue key), the remote draws and then the whole page is empty,
the Rules panel and the stop pins included, so 17's screenshots show nothing. Headless check (playwright, chromium,
1200x1600, 4 s) on the dry API on port 7924, with this branch's page and the two guards below reverted in a scratch
copy served in its place:
```
{"rootChildren":0,"errors":["TypeError: Cannot read properties of undefined (reading 'filter')"]}
NO RULES PANEL
```
With the guards (the committed page):
```
{"rootChildren":1,"errors":[]}
Rules · what a stop does
opening · hazard · person → the person on call, any p
below 0.7 → ask
else continue
table from map · replies read at 0.8
```

**Root cause.** NIGHT-1-CONTRACTS section F bug 1, still on this base (02 + 03 merged; neither applied it). At load the
page calls `lights_status`; without a key the tool fails loud and the page stores `{ error }` as `status`. Two render
expressions test only `status` for truthiness and then read `status.hue.filter(...)` (the palette, and the "State · read
back" panel). `{ error }` is truthy and has no `hue`, so the render throws and React unmounts the whole tree.

**Fix (verbatim, contract F patches 1 and 1b; the same bytes as on 01, 04, 07, 08, 09).** In `ui/index.html`, replace
`const palette = status ? [...status.hue.filter(` with
`const palette = Array.isArray(status?.hue) ? [...status.hue.filter(`, and replace
``${status && html`<div class="panel"><h2>State · read back</h2>`` with
``${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>``.
The lights card already reports the failure ("offline"); these lines only stop two panels from reading a list that is
not there.

**Verify.** From the worktree, `WTDD_LEDGER=<scratch> /Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.api 7924`,
then `/opt/homebrew/bin/playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600
--full-page http://127.0.0.1:7924/ out.png`: the page is drawn (map, status cards reading `lights offline`, the Rules
panel), and a headless `pageerror` listener records no errors.
