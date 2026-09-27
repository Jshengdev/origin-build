# 25-4 · a resend superseded during its read-back was written FAILED and lost the dog's ack

## Symptom
A newer state can arrive while a held colour's resend is waiting on its 1006 read-back, after the 1007 was already acked. That resend's dog.led row was written `ok=false` with the string `CancelledError: superseded by a newer state`, and the raw 1007 ack was gone. In the stub reproduction (`WTDD_LED_TIME_S=0.5`, a 1006 that takes 0.3 s, `hold(cyan, 5)` then `hold(green, 0.5)`), stderr showed `api_id=1007 code=0` for resend 1, but its row was FAILED.

On the dog, a 1006 that never answers spends `REQ_TIMEOUT_S` (3 s) of every 5 s request in that window. Most state changes during a hold would then put a false `dog.led FAILED` in the receipts.

## Root cause
`asyncio.CancelledError` is a `BaseException`, so `ledger.step()` records it as ok=false with no reason. `Body.led` had one handler for it around the whole request. That handler overwrote `response_or_error` (which held `{"led": <ack>}`) and re-raised inside the `with step(...)` block, whether or not the dog had already acked.

## Fix (verbatim)
wtdd/dog/body.py, `Body.led`: the read-back's handler also takes the cancel, and the cancel is re-raised after the row is written:
```
        gone, superseded = "CancelledError: superseded by a newer state", None
```
```
                except (Exception, asyncio.CancelledError) as e:  # noqa: BLE001  (the colour was acked: the row stays ok and says why there is no read-back, never a default; a cancel here is re-raised after the row)
                    superseded = e if isinstance(e, asyncio.CancelledError) else None
                    r["state_after"] = "no read-back"
                    r["response_or_error"]["readback"] = gone if superseded else f"{type(e).__name__}: {e}"
```
```
        if superseded is not None:
            raise superseded
        return dict(st)
```
A cancel that lands before the ack keeps its FAILED row and `.led.error`, as before.

## Verify
```
python -m unittest wtdd.dog.test_led.Receipt.test_a_cancel_after_the_ack_is_an_ok_row_and_still_cancels wtdd.dog.test_led.Hold.test_a_resend_superseded_during_its_read_back_keeps_its_ack
```
Both tests fail before the fix: the row is `ok=false` with only the string. After the fix, the row is ok, `response_or_error.led.header.status.code == 0`, `readback` is the superseded string and `state_after` is `"no read-back"`. The cancel still propagates (`CancelledError` is raised to the awaiter). On the dog, Needs the dog 25.3 (does 1006 answer?) decides how often this path is taken.
