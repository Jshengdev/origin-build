# 14-3 · At drop-off the page cannot see the dog, and its save never leaves the page

**Symptom.** Start the API from a checkout with no `dog_cal.json` (the drop-off case: nothing tied yet). `GET
/dog/state` gets no answer: the connection closes without a response, and the API prints an `AttributeError:
'DogSession' object has no attribute 'recheck'` traceback. The page's poll swallows it (`.catch(() => {})`), so `dog`
stays null: the body panel reads "…" and the scout button stays disabled. The scout's own tests missed this because
their harness set `s.recheck = False` on every session. Separately, clicking the page's "save" logs `ReferenceError:
roomOf is not defined` in the browser console, and the API log shows no `POST /map`. A route or zone drawn on the
no-plan site therefore cannot be saved from the page.

**Root cause.** Three causes:
- `DogSession.__init__` set `self.recheck` only inside `if CAL_FILE.exists():`, but `state()` always reads it (night-1
  contracts F, bug 3).
- The page's `withRooms` calls `roomOf`, and nothing defines it (bug 2).
- The scout button also required `dog.connected`. At drop-off nothing has connected yet, so even with the state
  answering, the one press needed some other command first. `POST /dog/scout` connects on its own
  (`self.run(self._ensure())`), and a failed connect becomes its FAILED row.

**Fix (verbatim).** Patch 3 goes into wtdd/dog/session.py, inserted immediately before `        if CAL_FILE.exists():   # a
calibration survives an API restart`:

```
        self.recheck = False   # no calibration loaded; state() reads this before any connect
```

Patch 2 goes into ui/index.html, inserted after the `const inside = ...` line:

```
const roomOf = (p, rooms) => ((rooms || []).find(r => inside(p, r.poly)) || {}).name || null;   // the room a map point sits in, for the page's save; field.py recomputes it anyway
```

The scout button's gate lives in ui/index.html, inside the `// 14 · scout-spin` block:

```
-    <button ... disabled=${!s?.active && (!dog?.connected || !!dog?.follow?.active || !!dog?.rec)} ...
+    <button ... disabled=${!s?.active && (!dog || !!dog?.follow?.active || !!dog?.rec)} ...
```

Also, `Harness.session()` in wtdd/dog/test_scout.py no longer presets `recheck`.

**Verify.** Run this from a checkout with no `dog_cal.json`:

```
WTDD_NO_PLAN=1 python -m wtdd.api 7921 &
curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:7921/dog/state
```

Before the fix there is no response. After it, the request returns `HTTP 200` with `"calibrated": false, "recheck":
false` and `"scout": {"active": false, ...}` (measured 2026-09-26). A headless page shows "not connected · the first
command connects", with "scout: spin and draw" enabled (docs/evidence/night-2/14-remote.png).

For the save, open `http://127.0.0.1:7921/#admin` headless and click "save":
- Before the fix, the console shows `ReferenceError: roomOf is not defined` and the API log has no `POST /map`.
- After it, the API log shows `[wtdd:field] WARN rooms off under WTDD_NO_PLAN outside=0` and `"POST /map HTTP/1.1"
  400`. The page names the refusal: main's 526 px jump between path points 11 and 12 (contracts F bug 4, never
  patched here).

`python -m unittest wtdd.dog.test_scout.Fresh wtdd.dog.test_scout.Page wtdd.test_noplan.Page` fails 3 tests before the
fix and passes after it.
