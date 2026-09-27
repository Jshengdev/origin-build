# 14-2 · A task cancelled inside ledger.step writes a FAILED row that names no error

**Symptom.** When a task is stopped (POST /dog/stop cancels it) while it is inside `with step(...)`, its ledger row
reads `ok: false, response_or_error: null`. The receipts panel shows the step as FAILED with no reason. Main's
`DogSession._follow` already writes this row on every stop, and a first draft of the scout would have too.

**Root cause.** `ledger.step` records `except Exception`, and `asyncio.CancelledError` is a `BaseException` (Python
3.8+). The cancellation therefore passes through the handler. Only the `finally` runs, and it appends the row with
`ok` still False and `response_or_error` still None.

**Fix (verbatim).** Inside the step, the scout turns the cancellation into a named error, halts once and fills a
complete `state_after`, then raises that error so the step records it (wtdd/dog/session.py, `_scout`):

```
                except asyncio.CancelledError:   # POST /dog/stop; ledger.step records Exception, and CancelledError is not one
                    err = RuntimeError("stopped (POST /dog/stop)")
```

The row then reads `ok: false, response_or_error: "RuntimeError: stopped (POST /dog/stop)"`, and `state().scout.error`
is the same string. `_follow` on main is not changed here (not this item's file to rewrite). Its stopped rows stay
nameless until someone gives them the same four lines.

**Verify.**

```
WTDD_LEDGER=/tmp/probe.jsonl python -c "
import asyncio
from wtdd.ledger import step, rows
async def spin():
    with step('dog', 'probe.cancelled', 'map', {}):
        await asyncio.sleep(10)
async def main():
    t = asyncio.create_task(spin()); await asyncio.sleep(0.05); t.cancel()
    try: await t
    except asyncio.CancelledError: pass
asyncio.run(main()); r = rows()[-1]; print(r['ok'], r['response_or_error'])"
```

prints `False None` (measured 2026-09-26). `python -m unittest wtdd.dog.test_scout.FailLoud.test_stop_cancels_the_scout`
passes, and its row names "stopped".
