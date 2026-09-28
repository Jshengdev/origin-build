# round-2 · a round that raised left the chat armed with no round_end: the next wake only re-armed

**Symptom.** Found building fix/listener-survives on 2026-09-27. With run() catching the failed poll, the listener survived a failed "dog done", but the next "what the dog doin" (typed after it) started no round: `wtdd.chat.test_round.Survives` posted nothing for S3.

**Root cause.** `handle()` stamped `self.round_end = db.max_rowid()` on the line after `self.wake_show(m)`, so a round that raised never stamped it. A round shorter than `WTDD_LISTEN_S` leaves the chat armed, and an armed wake is judged by its ROWID only when `round_end > 0`; with it still 0 the wake fell through to the silent re-arm.

**Fix (verbatim).** In `wtdd/chat/listen.py`, `handle()`:
```
            if _flag("WTDD_WAKE_SHOW"):
                try:
                    self.wake_show(m)
                finally:   # a round that raised (a failed "dog done") has ended too: a wake typed during it starts nothing
                    self.round_end = db.max_rowid()
```

**Verify.** `python -m unittest wtdd.chat.test_round.Survives`: S1's "dog done" fails, S2 (typed during it) starts nothing, S3 starts the next round and its "dog done" posts.
