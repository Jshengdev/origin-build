# 25-2 · a held colour went dark for the read-back's latency every period, and a CLI's hold died at exit

## Symptom
- A held state was resent every `time` + latency(1007) + latency(1006), not every `time`. With the stub (t = 0.05 s, a 1006 that takes 0.03 s) the 1007 sends were 0.083 s apart. On the dog, a 1006 that never answers waits `REQ_TIMEOUT_S` (3 s), so a 5 s colour would be resent about every 8 s: dark about 3 s in every 8, and the 120 s red of an open question would run to about 190 s.
- `python -m wtdd dog_led color=red seconds=30` with no API up lit one 5 s request, printed ok and exited 0. The other five requests were never sent and had no rows.

## Root cause
- `led._resend` slept `t` after each `Body.led` returned, and `Body.led` returns only after the 1006 read-back.
- `led.hold` returns after the first request and leaves the resends to a task on `DogSession`'s loop, which runs on a daemon thread. A CLI process exits right after `run()` returns, and the daemon thread and its task die with it. The API process lives on, so there the hold works.

## Fix (verbatim)
wtdd/dog/led.py, in `hold()` before the first request, and in `_resend()`:
```
    t0 = asyncio.get_running_loop().time()   # the resends keep this clock: the k-th starts at t0 + k*t, whatever 1006 took
```
```
            await asyncio.sleep(max(0.0, t0 + k * t - loop.time()))
```
(was `await asyncio.sleep(t)`; `t0` is passed to `_resend`, which reads `loop = asyncio.get_running_loop()`)

wtdd/tools/dog_led.py, `run()` after the hold, and a helper:
```
    if not os.environ.get("WTDD_API_PROCESS"):   # a CLI: the resend rows land before it exits
        s.run(_held(s.body), timeout=float(seconds) + 30)
```
```
async def _held(b):
    import asyncio
    if b._led_keeper is not None:
        await asyncio.wait([b._led_keeper])
```

## Verify
```
python -m unittest wtdd.dog.test_led.Hold.test_the_resend_period_is_time_not_time_plus_the_read_back
python -m unittest wtdd.dog.test_led.Tool.test_the_cli_waits_out_the_hold_and_the_api_process_does_not
```
Both fail before the fix (gaps 0.083 s; 1 row instead of 4 when the CLI's `run()` returns) and pass after. On the dog: Needs the dog 25.2 counts the rows and their timestamps.
