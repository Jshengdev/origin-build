# 28-1 · the admin page goes blank in any checkout without .env, so the Streams table cannot be screenshotted

**Symptom.** Run `WTDD_LEDGER=/tmp/night1/28/ok.jsonl python -m wtdd.api 7935` from a worktree (no `.env`) and open
`http://127.0.0.1:7935/#admin`. The page draws for about a second, then goes blank, so the Streams panel is never seen.
The API log shows `lights_status FAILED err=RuntimeError: [wtdd:config] HUE_APP_KEY is required` and
`"POST /tools/lights_status HTTP/1.1" 500`.

**Root cause.** This is night-1 contracts F bug 1, still on main. When `lights_status` fails, the page stores `{ error }` as
`status`, and then two render lines treat any truthy `status` as a successful read: the palette line calls
`status.hue.filter(...)` and the "State · read back" panel calls `status.hue.filter(...)` and `status.strip.error`. On
the error object `status.hue` is undefined, so the render throws a TypeError and React unmounts the whole tree.

**Fix (verbatim, patches 1 and 1b of the night-1 contracts, the same bytes as on the 01, 04, 07, 08 and 09 branches).**

```
-  const palette = status ? [...status.hue.filter(
+  const palette = Array.isArray(status?.hue) ? [...status.hue.filter(
```

```
-        ${status && html`<div class="panel"><h2>State · read back</h2>
+        ${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>
```

Patch 3 (session.py `self.recheck`) was not applied. `GET /dog/state` still raises `AttributeError: 'DogSession' object
has no attribute 'recheck'` in the API log on every poll (contracts F bug 3), but the page's `/dog/state` poll catches
it and the dog chip truthfully reads "dog · off". No stub Body is attached, and GET /dog/streams never reads `recheck`.

**Verify.** Plant the rows with `python -m wtdd.dog.test_sniff --rows /tmp/night1/28/ok.jsonl`, start the API on 7935 with
`WTDD_LEDGER` pointing at that file, then run
`playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 'http://127.0.0.1:7935/#admin' out.png`.
Before the fix the screenshot is one flat colour. After it, the map, the four status cards ("lights · offline"), the
receipts and the Streams table are all drawn (docs/evidence/night-2/28-remote.png).
