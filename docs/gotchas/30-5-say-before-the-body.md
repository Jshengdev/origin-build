# 30-5 · a hooked say that could not reach the dog left no row and no red badge

**Symptom.** In review round 4, a probe called `audio.after("ok, standing down")` twice with no dog reachable. Both calls printed `WARN say FAILED after the post (the ask landed)` to stderr. The ledger had no `dog.say` row, only one `dog.probe` row. `GET /dog/state .say` stayed `None`, so the page said "nothing said yet". After an earlier good play it would have stayed on the grey "said · N s ago". The stand-down went into the chat, the dog said nothing, and the speaker tile did not turn red.

**Root cause.** `audio.say` opens the `dog.say` step, but only once it has a Body. `DogSession.say` got the Body through `self.with_body(go)`, and `_ensure` raises before `go` runs in three cases: the probe is refused, the call falls inside `PROBE_BACKOFF_S` after a failed connect, or the API restarted while the dog was down. The hook is fire-and-forget on its own thread, so no caller ever sees the exception. `.say` was also read only from `self.body.say_state`, and a reconnect swaps in a fresh Body whose `say_state` is `None`.

**Fix (verbatim).** In `wtdd/dog/session.py`:

```python
        async def go() -> dict[str, Any]:
            try:
                b = await self._ensure()
            except Exception as e:
                self.say_state = {"text": text, "code": None, "at": time.time(), "error": f"{type(e).__name__}: {e}"}
                with step("dog", "dog.say", "unitree", {"text": text, "via": "audiohub"}, None):
                    raise
            try:
                if volume is not None:
                    await audio.volume(b, volume)
                return await b.say(text)
            finally:
                self.say_state = b.say_state or self.say_state
        return self.run(go())
```

and in `state()`:

```python
                "say": audio.served(self.body.say_state if self.body and self.body.say_state else self.say_state),
```

The general rule for the other fire-and-forget hooks (25's LED shares the hook line): open the row before you acquire the body, or record the acquisition failure as that row. A row opened inside `with_body` never sees `_ensure` fail.

**Verify.** Run `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_audio.Served.test_a_say_that_cannot_reach_the_body_is_a_failed_row_and_a_red_say -v`. `_ensure` is patched to raise. The test expects `session.say(ASK)` to raise, exactly one `dog.say` row with `ok=False` and the reason, `state()['say']['error']` set, and the error still there after a fresh stub Body is swapped in. Before the fix it failed with `0 != 1 : []` (no `dog.say` row); after the fix it passes.
