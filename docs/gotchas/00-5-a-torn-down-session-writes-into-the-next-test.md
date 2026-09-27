# 00-5 · a torn-down session's person-watch thread writes its row into the next test's ledger

**Symptom.** `python -m unittest wtdd.dog.test_halt` failed in 1 of the 7 runs seen (the other 6 passed), on
`Resume.test_the_real_rows_of_a_halt_and_a_named_resume_grade_pass`. The graded rows held a second stop.person (was
drive, ok false, `ms=10010 err=TimeoutError`) that the test never caused. stderr showed
`RuntimeWarning: coroutine 'DogSession._halt' was never awaited`. Every other run passed.

**Root cause.** Each test makes its own DogSession, and the first drive or follow starts a 'person-watch' daemon
thread. tearDown stops and closes that session's loop, and the thread exits only on its next `loop.is_closed()` check.
One test ended with `drive()` and a near person still planted. Its thread began a halt at the moment tearDown stopped
the loop, so `self.run(self._halt(), timeout=10)` waited the full 10 s on a loop that would never run it. By then
another test had patched the module-global `ledger.LEDGER` (and `halt.WATCH`), and `ledger.step` wrote the late row
into that test's ledger. Production never stops the session loop; only the test harness did.

**Fix (verbatim, wtdd/dog/test_halt.py Dry.tearDown).**

```
    def tearDown(self):
        with self.s._person_lock:   # an in-flight tick ends on a running loop, and no later tick halts on a stopped one
            self.s.halted = self.s.halted or {"was": "torn down"}
        stop_loop(self.s)
```

**Verify.** Run `python -m unittest wtdd.dog.test_halt` repeatedly. No `ms=100xx err=TimeoutError` line appears, and
no stop.person shows up that the test did not cause. The one failure seen before the fix is in
/tmp/night1/00/fix1/baseline.txt (scratch, not committed).
