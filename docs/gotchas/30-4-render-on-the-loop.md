# 30-4 · the first say of a line froze the body's loop for a second

**Symptom.** In review round 1, the first `who dis?!` from a fresh checkout stalled DogSession's event loop for 1.12 s. The render took 1073-1383 ms. That loop also sends the drive's 10 Hz Move, the StopMove 0.6 s after a key is released, the follower's ticks and every sport-state callback. A watch-triggered ask during a walk, or while someone held a drive button, would have frozen the body's control for about a second. The RED test measured 1.01 s with a render that sleeps 1 s.

**Root cause.** `ensure()` in `wtdd/dog/audio.py` is a coroutine. It called `render(text, wav)` directly, and render runs `/usr/bin/say` and then ffmpeg with `subprocess.run`. A blocking call inside a coroutine holds the whole loop. `session.say` runs that coroutine on the one loop the body shares with everything else (`self.run(self.with_body(go))`). The later plays do not render, so only the first say of each line stalled.

**Fix (verbatim).** In `ensure()`:

```python
        if not wav.exists():   # off the loop: the render takes about a second and the loop carries the drive's StopMove
            await asyncio.to_thread(render, text, wav)
```

`render` is still looked up at call time, so `mock.patch.object(audio, "render", ...)` in the tests still holds.

**Verify.** Run `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_audio.NeverBlocks.test_a_first_say_never_stalls_the_body_loop -v`. A ticker task on the same loop sleeps 0.02 s at a time during a first say whose render sleeps 1 s, and its worst gap must stay under 0.3 s. The test failed at 1.01 s before the fix and passes after it.
