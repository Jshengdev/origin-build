# 25-5 · a process that held the dog itself exited before the acked colour's row was written, and said nothing

## Symptom
A process that holds the dog itself (not the API) and exits right after a hook sent the head-light request and got it acked, but never wrote its dog.led row, and printed nothing about it. The real case is `python -m wtdd walk_path` with no API up: the follow's end fires `led.hook("clear")`, then the halt, the tool returns and the process exits. The reviewer's probe held a StubConn body in-process, set `WTDD_API_PORT=9`, replaced `_post_api` with a raise, delayed 1006 by 1.0 s and exited 0.3 s after `hook("clear")`. stderr showed `req rt/api/vui/request api_id=1007 code=0`, and the scratch ledger was never created: 0 rows and no WARN. With 1006 answering at once, the row landed.

## Root cause
In the process that holds the dog, `hook()` hands `hold()` to the session loop with `asyncio.run_coroutine_threadsafe` and returns. That loop runs on a daemon thread (`DogSession.__init__`), which dies with the interpreter. Body.led writes the dog.led row only after the 1007 ack and the 1006 read-back (up to REQ_TIMEOUT_S, 3 s). The exit drain from gotcha 25-3 waited only for the cross-process posts in `_POSTS`, so a slow or silent 1006 outlived the process and the ack had no receipt. Gotcha 25-2 closed the same gap for the dog_led CLI, and 25-3 closed it for the post path, but not for this one.

## Fix (verbatim)
wtdd/dog/led.py, at module level:
```
import concurrent.futures as futures
```
```
POST_WAIT_S = 10.0   # at exit, the hook's posts and holds still out get this long: a connected dog answers 1007 and 1006 within 2 x REQ_TIMEOUT_S (6 s)
_POSTS: dict[Any, tuple[str, str]] = {}   # the hook's work in flight: a post's thread, or (outside the API) a hold()'s future -> (state, colour)
```
in `hook()`'s in-process branch:
```
            fut = asyncio.run_coroutine_threadsafe(hold(s.body, color, seconds), s.loop)
            if not os.environ.get("WTDD_API_PROCESS"):   # a CLI holding the dog may exit first; its loop is a daemon thread
                _POSTS[fut] = (state, color)
            fut.add_done_callback(lambda f: _done(f, state, color))
```
first line of `_done()`:
```
    _POSTS.pop(fut, None)
```
and the drain's loop:
```
    end = time.monotonic() + POST_WAIT_S
    for w, (state, color) in list(_POSTS.items()):
        left = max(0.0, end - time.monotonic())
        if isinstance(w, threading.Thread):
            w.join(left)
            if w.is_alive():
                log("dog", f"WARN led {state} ({color}) unconfirmed: this process exited before the API answered", waited_s=POST_WAIT_S)
        elif futures.wait([w], left).not_done:
            log("dog", f"WARN led {state} ({color}) unconfirmed: this process exited before the dog answered, its dog.led row unwritten", waited_s=POST_WAIT_S)
```
The hook still returns at once. Only the exit waits, for the hold's first request (1007, then 1006) and for no longer than POST_WAIT_S. The API process (WTDD_API_PROCESS set) registers nothing and never waits at exit. A long hold's later resends are the keeper's and stop with the process, as before.

## Verify
```
python -m unittest wtdd.dog.test_led.Hook.test_a_short_lived_process_holding_the_dog_writes_its_row_before_exit_or_says_it_did_not
```
The test runs a subprocess with no `WTDD_API_PROCESS`, `WTDD_API_PORT=9` and `_post_api` replaced by a raise. A DogSession holds a StubConn body whose 1006 is delayed, and the process calls `hook("clear")` and exits. It checks two cases:
- A 1.0 s read-back with the default bound must leave one ok green dog.led row, `state_after {brightness: 7}`, in the scratch ledger at exit.
- A 2.5 s read-back with `POST_WAIT_S = 0.2` must show the 1007 ack, leave no row, print `WARN led clear (green) unconfirmed: ... its dog.led row unwritten`, and exit in under 2.5 s after the hook.

In both cases the hook itself must return in under 0.2 s. Before the fix, the first case fails with `0 != 1`: the process exits before the row is written. On the dog (added to Needs the dog 25.4), `python -m wtdd walk_path` from the repo checkout with no API up, run to the path's end, must leave a green dog.led row in the ledger when the process exits, or print this WARN.
