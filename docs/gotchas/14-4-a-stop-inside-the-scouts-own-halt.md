# 14-4 · A stop that lands inside the scout's own halt slips past the spin loop's catch

**Symptom.** POST /dog/stop is pressed while the scout is awaiting its own halt, that is, after the spin loop has let go
and while the StopMove ack and the state read-back are in flight. The page's button still reads "stop" during that
window. The dog.scout row then reads `ok: false, response_or_error: null, state_after: null`,
`state().scout.error` stays None, and the page shows `scout FAILED: null`. Found in review with a FakeBody whose
StopMove takes 0.6 s.

**Root cause.** This is the same cause as 14-2, one await later. The `except asyncio.CancelledError` that 14-2 added
wraps only the spin loop. The halt that follows was wrapped in `except Exception`, and `CancelledError` is a
`BaseException`. So the cancellation went past the halt's handler, past `ledger.step` and past the task's outer
`except Exception`, before `state_after` was filled.

**Fix (verbatim).** The halt's try now catches the cancellation too (wtdd/dog/session.py, `_scout`). `stop()` sends
its own halt after it cancels, so the body is still halted:

```
                except asyncio.CancelledError:   # POST /dog/stop inside this halt: stop() sends its own, so the body is still halted
                    err = err or RuntimeError("stopped (POST /dog/stop) during the halt")
```

No await is left inside the step outside a handler that names the error. 14-2 is not edited; this file supersedes
its claim that the loop's catch covers every stop.

**Verify.**

```
python -m unittest wtdd.dog.test_scout.FailLoud.test_a_stop_during_the_scouts_own_halt_is_named_and_complete
```

This was RED at 0619647 (`'stopped' not found in '' : the page names the stop`) and passes at 0fe1112. The row names
"stopped (POST /dog/stop) during the halt", and its `state_after` has all 18 contract keys.
