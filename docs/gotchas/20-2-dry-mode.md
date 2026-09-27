# 20-2 · in dry mode the remote goes blank and GET /dog/state never answers

**Symptom.** A dry API from a worktree (no `.env`, no Hue key, no `dog_cal.json`), `WTDD_MODE=site python -m wtdd.api 7927`,
on the tree just before this fix:
- `curl http://127.0.0.1:7927/dog/state` got no response (curl's `%{http_code}` = `000`). The API's stderr read
  `AttributeError: 'DogSession' object has no attribute 'recheck'`. The item's mode chip reads `mode` off that response,
  so it had nothing to show.
- `playwright screenshot --wait-for-timeout 3000 ... http://127.0.0.1:7927/` was an empty page (background only).

**Root cause.**
- `DogSession.__init__` set `self.recheck` only inside `if CAL_FILE.exists():`. `state()` reads it on every call, so
  GET /dog/state raised on every fresh API until a calibration existed. This is night-1 bug F3.
- When `lights_status` fails without a key, the page stores `{ error }` as `status`. Two render expressions test
  `status` for truthiness and then read `status.hue.filter(...)`. `{ error }` is truthy and has no `hue`, so React
  unmounts the whole tree. These are night-1 bugs F1 and F1b.

**Fix (verbatim, NIGHT-1-CONTRACTS section F patches 3, 1 and 1b: the same bytes as every sibling branch).**
In `wtdd/dog/session.py`, immediately before the line `        if CAL_FILE.exists():   # a calibration survives an API restart`,
insert exactly:
```
        self.recheck = False   # no calibration loaded; state() reads this before any connect
```
In `ui/index.html`, replace `const palette = status ? [...status.hue.filter(` with
`const palette = Array.isArray(status?.hue) ? [...status.hue.filter(`, and replace
``${status && html`<div class="panel"><h2>State · read back</h2>`` with
``${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>``.
The lights card already reports the failure ("offline"). These lines only stop two panels from reading a list that is
not there.

**Verify.**
```
WTDD_MODE=site WTDD_LEDGER=/tmp/night1/20/ledger.jsonl /Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.api 7927
curl -s http://127.0.0.1:7927/dog/state        # 200: connected false, recheck false, mode site, vocab [14 words], vocab_error null
playwright screenshot --browser chromium --wait-for-timeout 3000 --viewport-size 1200,1600 http://127.0.0.1:7927/ out.png
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_vocab.Api
```
The page draws (the map, the status cards reading `lights offline`, the `mode · site` chip) and
`test_state_carries_mode_and_map_carries_vocab` passes.
