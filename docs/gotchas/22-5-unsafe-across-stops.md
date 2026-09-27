# 22-5 · a failed first stop read as UNSAFE at the second

**Symptom.** 02.4 printed `UNSAFE 02.4 · watch.boxes after decided · <row>` (exit 2) for rounds whose order was right at
every stop. Three cases:
- stop 1's decided came from the stub, because `JEV_API_KEY` was missing;
- stop 1's watch.boxes failed;
- stop 1's decided failed (a 404), after which the picked frame was boxed.

**Root cause.** The in-order match treated a row it could not match as traffic: it logged one WARN and kept reading.
The rows it skipped were stop 1's own: the stub decided missed `source live` and the failed rows missed `ok true`.
So the check ran on past stop 1. The unsafe pattern `{decided before watch.boxes}` is only true of one stop, and the
next watch.boxes (stop 2's, or stop 1's second boxed() on the picked frame) completed it.

**Fix (verbatim).** wtdd/livecheck/__init__.py, in `_Check.row()`:

```
        elif r.get("ok") != want["ok"] and match({**r, "ok": want["ok"]}, want) is None:   # the step's own row, gone the other way
            return self.done("FAIL", f"{tool} {_okw(r)}: row {self.i + 1}/{self.n} wants {tool} {_okw(want)} · {raw}", r, f"{tool} {_okw(r)}")
```

wtdd/livecheck/steps.json, 02.4 row 2:

```
        {"tool": "decided", "agent": "decide", "ok": true, "where": {}}
```

Now the stub decided matches, and the stub rule FAILs it. 02.2 still grades `source live`.

**Verify.** `.venv/bin/python -m unittest wtdd.livecheck.test_livecheck.Rows` runs these checks:
- `test_02_4_a_stub_decided_at_stop_1_is_a_fail_not_an_unsafe`
- `test_02_4_a_failed_stop_1_is_a_fail_not_an_unsafe`, which also checks that the live misorder is still UNSAFE.

Rule: an unsafe pattern that only holds within one stop needs the check to end at that stop. Any row the check skips
there must be a row that really is not the stop's.
