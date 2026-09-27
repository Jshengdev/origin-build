# 00-2 · cancelling the follower returns before its dog.follow row exists

**Symptom.** A halt that cancels the follower the way stop() does (`self._follower.cancel()`) and then writes its own
row gets the ledger order wrong: stop.person lands first and the cancelled follower's dog.follow row (and its own
StopMove) lands after it. `wtdd.dog.halt.grade` then reads a dog.follow row between stop.person and stop.resumed and
calls the run unsafe ("moved while halted: dog.follow"), although nothing moved. Meanwhile a follower tick that was
already past its last check can still call `_set_vel` and re-arm the drive loop for up to DRIVE_HOLD_S.

**Root cause.** `self._follower` is the concurrent future from `asyncio.run_coroutine_threadsafe`. Its `cancel()`
returns at once and `done()` is True at once, but the task on the session loop only receives CancelledError at its
next await; its `finally` then zeroes the velocity, awaits `_halt()` (a StopMove row) and the `ledger.step` block
appends dog.follow with ok false. `follow_state["error"] = "stopped"` is set only after that row is written. So
"cancelled" on the caller's thread is not "its receipt is in the ledger".

**Fix (verbatim, wtdd/dog/session.py person_tick).** Set the halt before the cancel (it gates `_set_vel` and the drive
loop), then wait for the follower's own end before the halt's row:

```
            self.halted = {"was": was, "pending": True}   # first: from here no tick re-arms the drive loop
            ...
            if self._follower and not self._follower.done():   # exactly as stop() cancels it
                self._follower.cancel()
            self.vel, self.vel_t = (0.0, 0.0, 0.0), 0.0
            if was == "follow":   # its own finally halts and writes its dog.follow row; that row lands before stop.person
                t0 = time.monotonic()
                while not (fs.get("error") or fs.get("done")) and time.monotonic() - t0 < 3.0:
                    time.sleep(0.01)
                if not (fs.get("error") or fs.get("done")):
                    log("halt", "WARN the follower did not end in 3 s; halting anyway")
```

and in `_set_vel`: `if self.halted: return`; in `_drive_loop`: `... and not self.halted` on `fresh`. 14 (scout) and
18a (dispatch) cancel their own tasks through the same path and must wait for their own rows the same way.

**Verify.** `python -m unittest wtdd.dog.test_halt.Watch.test_the_follower_is_cancelled_first_and_never_re_armed`:
dog.follow's index is below stop.person's, and a `_set_vel(0.3, 0, 0.2)` after the halt produces no non-zero tick in
0.6 s. `python -m wtdd.fixtures.evals.make_halt` writes watch.detect, dog.cmd, dog.follow, dog.cmd, stop.person,
stop.resumed in that order and `python -m wtdd.dog.halt --grade wtdd/fixtures/evals/halt.jsonl` prints pass.
