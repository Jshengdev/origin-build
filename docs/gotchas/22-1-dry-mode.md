# 22-1 · the remote goes blank in a worktree, so the livecheck line can never be seen there

**Symptom.** `WTDD_LEDGER=wtdd/livecheck/fixtures/ledger-01-3.jsonl .venv/bin/python -m wtdd.api 7929` from a worktree
(no `.env`) serves `GET /` 200 and `GET /livecheck` 200, but a headless screenshot after 3 s
(`playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7929/ out.png`)
of main's `ui/index.html` is one flat cream colour: no map, no receipts, no livecheck line. The API's stderr shows
`[wtdd:api] lights_status FAILED err=RuntimeError: [wtdd:config] HUE_APP_KEY is required. ...` and
`"POST /tools/lights_status HTTP/1.1" 500`.

**Root cause.** The page stores the failed `lights_status` call as `status = { error }`, then two render lines read
`status.hue.filter(...)` (the palette, and the "State · read back" panel with `status.strip.error`) on any truthy
`status`. `status.hue` is undefined on the error object, the render throws a TypeError and React unmounts the whole
tree, the LiveCheck line with it. NIGHT-1 contracts F bug 1; not caused by this item, met by its screenshot gate.

**Fix (verbatim, contracts F patches 1 and 1b in ui/index.html, the same bytes as the sibling branches).**

```
-  const palette = status ? [...status.hue.filter(
+  const palette = Array.isArray(status?.hue) ? [...status.hue.filter(
```

```
-        ${status && html`<div class="panel"><h2>State · read back</h2>
+        ${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>
```

The lights card still says `lights · offline`, so the failure stays visible; only the crash is gone.

**Verify.** The same API and screenshot with the patched page draw the map, the receipts panel with the fixture's three
rows and, under it, `Live check · livecheck.json` with `PASS · 01.3 · dog.grid_save ok · replay` in green
(docs/evidence/night-2/22-remote.png); main's page on the same API is blank.
