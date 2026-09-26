# 10-5 · a post after the signature joins the signed shift, its look does not

**Symptom.** Gotcha 10-1 says to leave `WTDD_SHIFT` set until the next night. After the morning `record_sign`, one
dog_say pressed from the page, then the record re-rendered: at d57fe46 the SIGNED page grows a fourth stop, FAILED,
claiming a row is missing that sits in the ledger nine seconds earlier:
```
rows 34 stops [10, 22, 23, None] window {'from': '2026-09-26T22:00:00', 'to': '2026-09-27T10:00:09', 'closed_by': 'signature'}
stop 4 error: no dog.look row before this post: a cup on the table
```

**Root cause.** Every chat.post is stamped `args.shift_id = oncall.shift_id()` (wtdd/chat/__main__.py:74), which
reads `WTDD_SHIFT`, so dog_say's `say-<epoch>` post is stamped with the signed shift, and a stamped row always joins
its shift. The look, boxes and model call are unstamped and come after the signature, which closed the window, so
they do not join. The stop loop saw a say post with no look before it and opened a FAILED stop, the same path as a
look that never reached the dog. The midnight split of 10-1 hits the same path from the other side (stop 22's look
on the 09-25 page, its post on the 09-26 page), where the old wording "no dog.look row before this post" was false
about the ledger too.

**Fix (verbatim, wtdd/record.py, build()).** The signature is read before the stop loop, and a say post after it is
set aside, never a stop:
```
    sig = oncall.signed(shift_id, members)
    stops: list[dict] = []
    after_sig: list[dict] = []   # say posts stamped with the shift after its signature: never a stop of the signed record
...
        if say and sig and r["ts"] > sig["ts"]:   # dog_say pressed after signing with WTDD_SHIFT still set: its look is outside the window
            after_sig.append({"ts": r["ts"], "trigger": a.get("trigger"), "rowid": after.get("rowid")})
            continue
        if say and (cur is None or cur["posted"] is not None):   # a look that never reached the dog, or one outside the window
            cur = stop(r, error=f"no dog.look row in this shift's window before this post: {a.get('text')}")
```
The page prints one red line under the signature ("1 post stamped after the signature, not on the record: ...") and
the stderr line carries `after_signature=<n>`. The post still counts in `rows` and `posts`, and the window's last ts
is still the last member's (the refused second signature already sits after the signature in the fixture);
`closed_by` names what closed the window for unstamped rows.

**Verify.**
```
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_record.Signed
```
prints `Ran 4 tests` and `OK`. The case above, from the worktree root:
```
PYTHONPATH=. WTDD_LEDGER=wtdd/fixtures/ledger_shift.jsonl /Users/johnnysheng/code/origin-build/.venv/bin/python - <<'PY'
from wtdd import ledger, record
from wtdd.fixtures import make_ledger_shift as m
rows = ledger.rows()
sig = next(i for i, r in enumerate(rows) if r["tool"] == "record.signed" and r["ok"])
late = [m.look("2026-09-27T10:00:00", "late-dog", "tilt", 9001),
        m.claim("2026-09-27T10:00:06", "late-chat", "say-1790500000"),
        m.post("2026-09-27T10:00:09", "late-chat", m.GROUP, "remote", "say-1790500000", "a cup on the table",
               "look-down-boxed.jpg", "2026-09-26", 90001, "2026-09-27 17:00:08")]
rec = record.build("2026-09-26", rows[:sig + 2] + late + rows[sig + 2:])
print("rows", rec["rows"], "stops", [s["index"] for s in rec["stops"]], "window", rec["window"])
print("after_signature", rec["after_signature"], "page says no dog.look row:", "no dog.look row" in record.html(rec))
PY
```
prints
```
rows 34 stops [10, 22, 23] window {'from': '2026-09-26T22:00:00', 'to': '2026-09-27T10:00:09', 'closed_by': 'signature'}
after_signature [{'ts': '2026-09-27T10:00:09', 'trigger': 'say-1790500000', 'rowid': 90001}] page says no dog.look row: False
```
It reads the fixture and appends nothing. Gotcha 10-1's Verify still prints the two lines gotcha 10-3 records.
