# 25-3 · the hook's post to the API died with a short-lived caller: no request, no row, no WARN

## Symptom
A process that holds no dog and exits right after its hook dropped the light without a word. Examples are `python -m wtdd intruder_alarm` by hand (red after "who dis?!") and `python -m wtdd.chat simulate` (green after "ok, standing down"). The reproduction replaced `led._post_api` with a recorder that sleeps 0.5 s and then writes a file. The process printed that `run()` had returned and exited 0. The file was never written, and stderr said nothing about the light.

## Root cause
With no dog in the process and no `WTDD_API_PROCESS`, `led.hook` posts the dog_led tool to the API from `threading.Thread(..., daemon=True)` so that it never blocks the ask. A daemon thread is killed at interpreter exit. The caller returns at once, the CLI exits, and the post dies before it is sent or answered. Gotcha 25-2 fixed the same failure for the dog_led CLI's resends; the hook's post was left open.

A non-daemon thread would not drop the post, but `_via_api` waits up to 600 s for the API, so the exit could hang for ten minutes with nothing said.

## Fix (verbatim)
wtdd/dog/led.py, at module level:
```
POST_WAIT_S = 10.0   # at exit, the hook's posts still out get this long: a connected dog answers 1007 and 1006 within 2 x REQ_TIMEOUT_S (6 s)
_POSTS: dict[threading.Thread, tuple[str, str]] = {}   # the hook's posts in flight: thread -> (state, colour)
```
in `hook()` (was `threading.Thread(target=_via, args=(state, color, seconds), daemon=True).start()`):
```
            th = threading.Thread(target=_via, args=(state, color, seconds), daemon=True)
            _POSTS[th] = (state, color)
            th.start()
```
at the end of `_via()`:
```
    finally:
        _POSTS.pop(threading.current_thread(), None)
```
and the drain:
```
@atexit.register
def _drain() -> None:
    end = time.monotonic() + POST_WAIT_S
    for th, (state, color) in list(_POSTS.items()):
        th.join(max(0.0, end - time.monotonic()))
        if th.is_alive():
            log("dog", f"WARN led {state} ({color}) unconfirmed: this process exited before the API answered", waited_s=POST_WAIT_S)
```
The hook still returns at once. Only the interpreter's exit waits, and for no longer than POST_WAIT_S.

## Verify
```
python -m unittest wtdd.dog.test_led.Hook.test_a_short_lived_callers_post_lands_before_exit_or_says_it_did_not
```
The test runs a subprocess with no dog, no `WTDD_API_PROCESS` and a dead `WTDD_API_PORT`, and with `_post_api` replaced by a recorder. It checks two cases:
- A 0.3 s post must write its file before the exit.
- A 3 s post with `POST_WAIT_S = 0.2` must print `WARN led asking (red) unconfirmed` and exit in under 3 s.

In both cases the hook itself must return in under 0.2 s. Before the fix, the first case fails because the file is never written. On the dog, Needs the dog 25.4 runs `python -m wtdd intruder_alarm` by hand while the API holds the dog, and expects a red dog.led row in the API's ledger.
