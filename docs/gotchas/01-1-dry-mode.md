# 01-1 · the remote goes blank in any checkout without .env

**Symptom.** `python -m wtdd.api 7801` from a checkout with no `.env` serves `GET /` 200, and the page draws for
about a second, then goes blank: an empty cream page, no map, no panels. A headless screenshot after 3 s
(`playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7801/ out.png`)
is one flat colour. The API log shows `lights_status FAILED err=RuntimeError: [wtdd:config] HUE_APP_KEY is required`
and `"POST /tools/lights_status HTTP/1.1" 500`.

**Root cause.** On load the page calls `lights_status` and, when it fails, stores `{ error }` as `status`
(ui/index.html, the `setStatus(o.ok ? o.result : { error: o.error })` effect). Two render lines then treat any
truthy `status` as a successful read: the palette line calls `status.hue.filter(...)` and the "State · read back"
panel calls `status.hue.filter(...)` and `status.strip.error`. `status.hue` is undefined on the error object, the
render throws a TypeError, and React unmounts the whole tree. Every worktree, CI box or fresh clone without Hue keys
hits it, so every dry UI check does.

**Fix (verbatim, the two replaced texts in ui/index.html).**

```
-  const palette = status ? [...status.hue.filter(
+  const palette = Array.isArray(status?.hue) ? [...status.hue.filter(
```

```
-        ${status && html`<div class="panel"><h2>State · read back</h2>
+        ${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>
```

With the error object the palette falls back to the map's own lights and the read-back panel is not drawn; the
status row already says "lights · offline" from its own `Array.isArray(status.hue)` check, so the failure stays
visible.

**Verify.** Start the API on 7801 from a checkout with no `.env`, take the screenshot above after 3 s: before the
fix it is blank; after it, the map, the route, the stops and the four status cards ("lights · offline") are drawn.
