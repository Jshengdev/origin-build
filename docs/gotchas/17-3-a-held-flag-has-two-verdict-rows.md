# 17-3 · a held flag has two verdict rows, and every reader counts every acked_ms

**Symptom.** On 3f6ef48 (item 17's build, before its review fixes), the README's numbers read the committed remote
fixture, one flag answered "on it" and then "handled, cover is back on", as two replies:
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_reply
FAIL: test_numbers_counts_one_acked_ms_for_the_one_flag (wtdd.chat.test_reply.Fixture.test_numbers_counts_one_acked_ms_for_the_one_flag)
AssertionError: Lists differ: [('2026-09-27', 1, [12000, 95000])] != [('2026-09-27', 1, [12000])]
```
The block would print `12000, 95000 (n=2, median 53500)` for one flag. After a re-ask the single verdict row's acked_ms
ran to the answer of the re-ask (50000 in the check), not to the first reply (12000).

**Root cause.** Item 03 wrote one intruder.verdict row per flag, so its readers count acked_ms per row:
`numbers.shifts()` appends `a["acked_ms"]` for every ok intruder.verdict / chat.correction row, and
origin/feat/10-morning-page's `record.py` does the same for `acked` and `acked_median_ms`. Item 17's verdict() holds
an acknowledged flag open for "handled" and writes a second verdict row when it closes, and each row carried
`oncall.reply_fields(...)`, so each carried an acked_ms. The re-ask writes no row, so the final row measured the
second reply.

**Fix (verbatim).** In wtdd/chat/listen.py `verdict()`, one acked_ms per flag. The close after a hold renames the
fields, and a re-ask keeps the first reply's:
```
        now = oncall.reply_fields(oncall.post_for(pend.get("trigger"), ledger_rows()), m.get("ts_utc"))
        # one acked_ms per flag (numbers.py and 10's record count every one): after a hold, the hold's row has it and this
        # reply's time from the flag is closed_ms; after a re-ask, the first reply's time stands (the person answered then)
        acked = {k.replace("acked_", "closed_"): v for k, v in now.items()} if pend.get("acknowledged") else (pend.get("acked") or now)
```
and the re-ask writes `{**pend, "reasked": True, "question": REASK, "acked": acked}`. The fixture is regenerated
through `python -m wtdd.fixtures.make_ledger_17`, so its close row has `closed_ms: 95000` and no acked_ms. 10's
record.py still resolves a flag from the first verdict row matching its trigger, so a held-then-handled flag shows as
"acknowledged" there. That is 10's reader, not changed here.

**Verify.**
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide wtdd.chat.test_reply
Ran 87 tests
OK
```
