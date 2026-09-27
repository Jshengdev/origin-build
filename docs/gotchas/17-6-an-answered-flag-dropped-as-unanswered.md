# 17-6 · an answered flag dropped as if nobody answered

**Symptom.** On fee4189 (item 17 after its third review), with no JEV_API_KEY, two flags that the on-call person
answered left the ledger as if they had never been answered.

**Case 1, an unanswered re-ask.** The person answers a heads_up with "wait what". The listener reads it as unclear and
re-asks "do you know them? yes or no". No second reply comes within VERDICT_WAIT_S. await_verdict's timeout then
unlinks pending.json and logs "who dis: no answer at the stop, moving on". The flag has a reply.decided row but no
intruder.verdict row, so the first reply's acked_ms is lost and 11's escalate grader reports "no reply to flag ...".
The PENDING_WINDOW_S expiries in verdict() and poll() drop a re-asked question the same way.

**Case 2, a held flag.** The person answers "on it" 12 s after the heads-up, then "handled, cover is back on" 130 s
after it. The hold rewrote pending.json but kept the post's `t`, so both PENDING_WINDOW_S checks drop the flag at
120 s and log "no answer in time". The "handled" is never read: no close row, no "ok, closed". Beat 2.4b only worked
if the cover was fixed within two minutes of the flag.

```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide wtdd.chat.test_reply
FAIL: test_an_unanswered_reask_is_one_unclear_verdict_row (wtdd.chat.test_reply.Verdict...)
AssertionError: 0 != 1 : []
FAIL: test_an_unanswered_reask_past_the_window_is_the_same_row (wtdd.chat.test_reply.Verdict...)
AssertionError: Lists differ: [] != [('unclear', 'stand_down')]
FAIL: test_a_held_flag_outlives_the_question_window_and_handled_closes_it (wtdd.chat.test_reply.Verdict...)
AssertionError: False is not true
FAIL: test_a_held_flag_never_closed_expires_at_the_ack_window_with_its_row (wtdd.chat.test_reply.Verdict...)
AssertionError: False is not true
```

**Root cause.** A pending question had one way out without a reading: unlink and log "no answer". Before 17 that was
true, because a question was either answered, and got its row at once, or it was not answered. Two of 17's states break
that. A re-ask writes no verdict row, on purpose, and waits for the answer to the re-ask. A hold writes its row and
keeps the question open for "handled". Both are answered questions still sitting in pending.json, and both still
expired through the "nobody answered" path. The window also still counted from the post, not from the
acknowledgement.

**Fix (verbatim).** wtdd/chat/listen.py:
```
ACK_WINDOW_S = 1800           # the head's choice for beat 2.4b: a held flag ("on it") stays open this long after the acknowledgement
```
verdict() keeps the reading the question rests on. At the re-ask:
```
            PENDING.write_text(json.dumps({**pend, "reasked": True, "question": REASK, "acked": acked,
                                           "first": {**reply, "meaning": r["meaning"], "p": r["p"], "stub": stub}}))
```
At the hold:
```
            PENDING.write_text(json.dumps({**pend, "acknowledged": True, "held": {**reply, "meaning": r["meaning"], "p": r["p"],
                                           "stub": stub, "shift_id": acked.get("shift_id"), "t": time.time()}}))
```
verdict()'s expiry is `if self._expired(pend): return False`, poll()'s is `if PENDING.exists():
self._expired(json.loads(PENDING.read_text()))`, and await_verdict's timeout is `self._drop(json.loads(PENDING.read_text())
if PENDING.exists() else {}, "who dis: no answer at the stop, moving on", waited_s=...)`. The row writer moved out of
verdict() into `_row()` (same fields). The two new methods, docstrings omitted:
```
    def _expired(self, pend: dict[str, Any]) -> bool:
        held = pend.get("acknowledged")
        since = ((pend.get("held") or {}).get("t") or pend.get("t", 0)) if held else pend.get("t", 0)
        if time.time() - since <= (ACK_WINDOW_S if held else PENDING_WINDOW_S):
            return False
        self._drop(pend, "who dis: no answer in time, standing down")
        return True

    def _drop(self, pend: dict[str, Any], unanswered: str, **kv: Any) -> None:
        PENDING.unlink(missing_ok=True)
        first, held = pend.get("first"), pend.get("held")
        if pend.get("acknowledged"):
            if held:
                self._row(pend, held, {"shift_id": held["shift_id"], "window_s": ACK_WINDOW_S}, held["stub"],
                          "expired", held["meaning"], held["p"], "stand_down")
            log("chat", "WARN a held flag was never closed: standing down", trigger=pend.get("trigger"),
                held_on=(held or {}).get("text", "")[:40], window_s=ACK_WINDOW_S, **kv)
        elif pend.get("reasked") and first:
            self._row(pend, first, pend.get("acked") or {}, first["stub"], "unclear", first["meaning"], first["p"], "stand_down")
            log("chat", "re-ask unanswered: standing down, unclear", trigger=pend.get("trigger"), **kv)
        else:
            log("chat", unanswered, **kv)
```
The expired row carries no acked_ms, because the hold's row already has the flag's one (17-3). A pending held before
this change has no `held` entry: it expires ACK_WINDOW_S from its post, with the WARN and no row, because there is no
recorded reply to put on one.

UNVERIFIED until the first live run: that 1800 s is long enough for a real "handled" on camera.

**Verify.**
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide wtdd.chat.test_reply
Ran 97 tests
OK
```
