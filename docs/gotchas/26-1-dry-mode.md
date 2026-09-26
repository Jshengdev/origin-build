# 26-1 · the remote goes blank in dry mode, so the timeline cannot be tapped headless

**Symptom.** Served from a worktree (no `.env`, so no Hue key) with the sample ledger, the remote draws for about a
second and then the page is empty: no map, no receipts, no timeline to tap. Headless check on this branch's
`ui/index.html` with the two guards below reverted (route-intercepted in the browser, the file on disk untouched), dry
API on port 7933:
`patches reverted: root children after 4 s: 0; page errors: ["TypeError: Cannot read properties of undefined (reading 'filter')"]`.
The API log at the same time: `[wtdd:api] lights_status FAILED err=RuntimeError: [wtdd:config] HUE_APP_KEY is required.`

**Root cause.** At load the page calls `lights_status`; without a key the tool fails loud (500) and the page stores
`{ error }` as `status`. Two render expressions test only `status` for truthiness and then read `status.hue.filter(...)`
(the palette, and the "State · read back" panel). `{ error }` is truthy and has no `hue`, so the render throws and
React unmounts the whole tree, the Timeline and the MarksLayer with it.

**Fix (verbatim, NIGHT-1-CONTRACTS section F patches 1 and 1b; the same bytes as on the sibling branches).**
In `ui/index.html`, replace `const palette = status ? [...status.hue.filter(` with
`const palette = Array.isArray(status?.hue) ? [...status.hue.filter(`, and replace
``${status && html`<div class="panel"><h2>State · read back</h2>`` with
``${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>``.
The lights card already reports the failure ("offline"); these lines only stop two panels from reading a list that is
not there.

**Verify.** From the worktree, `WTDD_LEDGER=docs/evidence/ledger-sample-2026-09-13.jsonl python -m wtdd.api 7933`, then
a headless Chromium at 1200x1600 on `http://127.0.0.1:7933/`: the page stays drawn (status cards read `lights offline`),
40 ticks are on the timeline, a pointerdown on tick 7 pins the calibrate ring, and a `pageerror` listener records no
errors (docs/evidence/night-2/26-remote.png).
