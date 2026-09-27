# 10-1 · a night that crosses midnight is two shifts unless WTDD_SHIFT is set

**Symptom.** Replaying fixture shift 2026-09-25 with midnight falling between stop 10 and stop 22 (every stamped row
from then on carrying the next date), `record.build` gives two partial pages and splits one stop across them:
```
2026-09-25 rows 17 stops [10, None] flags 0 closed_by shift 2026-09-26 signed None
2026-09-26 rows 18 stops [23] flags 1 closed_by open signed None
```
Stop 22's look, detector boxes and model call are on the 09-25 page with no post (index None); its say post and its
"who dis?!" flag are on the 09-26 page, which has no look for them. The same night with one id is `stops [10, 22, 23]`.

**Root cause.** `oncall.shift_id()` (item 03) is `config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")`, read at
every post and every reply, not once per round. With WTDD_SHIFT unset, a night shift (22:00 to 06:00) stamps its
evening rows with one date and its after-midnight rows with the next. `python -m wtdd record_sign` in the morning
defaults to the morning's date, so it signs the second half and the first half stays "unsigned". The record binds
unstamped rows (looks, boxes, model calls) by window, so the look lands in whichever window was open when it ran.

**Fix (verbatim, an operating step, no code).** Before starting the listener for a night, in
/Users/johnnysheng/code/origin-build/.env:
```
WTDD_SHIFT=2026-09-27
```
Every process that reads config (the listener's posts and replies, `record_sign`, `python -m wtdd.record`'s default)
then stamps, signs and renders the same id. Change it before the next night: a value left in .env makes the next
night the same shift, and its signature is refused as "already signed".

**Verify.** With the id fixed the fixture's round is one shift: `/Users/johnnysheng/code/origin-build/.venv/bin/python
-m unittest wtdd.test_record.Unsigned.test_stops_are_the_looks_with_what_followed_each` (stops [10, 22, 23]). The
split, from the worktree root:
```
PYTHONPATH=. WTDD_LEDGER=wtdd/fixtures/ledger_shift.jsonl /Users/johnnysheng/code/origin-build/.venv/bin/python - <<'PY'
import copy
from wtdd import ledger, record
rows = [r for r in copy.deepcopy(ledger.rows()) if r["ts"] < "2026-09-26T12:00:00"]   # shift A's night only
for r in rows:
    a = r.get("args") or {}
    if a.get("shift_id") and r["ts"] >= "2026-09-25T22:01:00":   # midnight, moved to 22:01:00
        a["shift_id"] = "2026-09-26"
for sid in ("2026-09-25", "2026-09-26"):
    rec = record.build(sid, rows)
    print(sid, "rows", rec["rows"], "stops", [s["index"] for s in rec["stops"]], "flags", len(rec["flags"]),
          "closed_by", rec["window"]["closed_by"], "signed", rec["signed"])
PY
```
prints the two lines under Symptom. It reads the fixture and appends nothing.
