# 14-6 · A stop that lands before the scout has a task is lost, and cancelling a task not yet started runs nothing

**Symptom.** At drop-off the scout press is the first command, so it is the press that connects (about a second over
WebRTC). The press claims `scout_state` before it connects, so the page's button reads "stop" from the first moment.
If POST /dog/stop lands during the connect or the drop-off tie, nothing is cancelled and nothing is halted, because
the body is still None. The task then starts and the dog turns a full 360. In the reviewer's probe the stop landed
0.5 s into a 1.5 s connect, and the row read `ok: true, turned_deg: 368.3` with no error. Found in review.

A second case turned up while fixing the first. Suppose the press has already handed the spin over but the loop is busy
and has not started the task yet. A stop then cancels the future, and the coroutine never runs a line. No dog.scout row
is written, `scout_state.active` stays true for good, the page reads "stop" forever, and every later press is refused
as "already scouting".

**Root cause.** `stop()` only knew how to cancel `_scouter`, the future of a task that was already running. Before
that task exists there is nothing to cancel. The second case comes from `run_coroutine_threadsafe` on Python 3.13: if
the concurrent future is cancelled before the loop creates the task, the chain cancels the new task on the loop
thread before its first step, so the coroutine body, its `try`, `ledger.step` and its `finally` never run. Measured
with a scratch probe: `cancel before the loop takes it -> []`, `cancel after it exists -> ['first line', 'cancelled
at the first await']`. The closing sentence of commit 7f54e51 claims the opposite. That claim is wrong, and 22298dc
corrects it.

**Fix (verbatim).** The fix is in wtdd/dog/session.py. `stop()` now flags any active press before it cancels, and it
cancels only a task that has already run its first line:

```
        if self.scout_state["active"]:   # 14: set before the cancel below; a press with no task yet reads it and ends stopped
            self._scout_stop = True
        if self._scouter and not self._scouter.done() and self._scout_running:   # 14: the scout halts itself and its row says stopped
            self._scouter.cancel()
```

The press reads the flag after the connect and after the tie. A stopped press ties nothing:

```
            if self.cal is None and not self._scout_stop:   # nose at drop-off is up: a stated convention, not a measurement (no map to orient against yet)
                self.calibrate(scout.CANVAS_CENTRE, math.radians(scout.DROPOFF_HEADING_DEG), source="dropoff")
            if self._scout_stop:   # the page reads "stop" from the claim on; there was no task to cancel, so the press reads it
                raise RuntimeError("stopped (POST /dog/stop) before the spin started")
```

The task marks itself running as its first statement, and it reads the flag once more before the LiDAR switch:

```
        self._scout_running = True   # first line, before any await: a stop before this only flags (a cancel now would run nothing, no row)
...
                    if self._scout_stop:   # a stop after the press's last look and before this task could be cancelled
                        raise RuntimeError("stopped (POST /dog/stop) before the spin started")
```

`stop()` writes the flag and then reads the mark, and the task writes the mark and then reads the flag, so one of the
two always sees the stop. The press clears both at its claim.

**Verify.**

```
python -m unittest wtdd.dog.test_scout.FailLoud.test_a_stop_while_the_press_connects_ends_it_before_anything_moves \
  wtdd.dog.test_scout.FailLoud.test_a_stop_during_the_dropoff_tie_ends_the_press \
  wtdd.dog.test_scout.FailLoud.test_a_stop_between_the_press_and_its_task_is_read_by_the_task \
  wtdd.dog.test_scout.FailLoud.test_a_stop_before_the_loop_starts_the_task_still_ends_it_with_its_row
```

The first three were RED at e31eee9 with, in order, `the press started a spin after the stop`, `RuntimeError not
raised`, and `did not turn` (from a spin that ran anyway). The fourth was RED at 8874a59 with `the scout never ended`.

The first two pass at 7f54e51 and the fourth at 22298dc. The third passes at 02f2af1: until then its check that
`state_after` has every contract key was waiting on band_hits (14-7). Each ends as one FAILED dog.scout row naming
"stopped", with no velocity held and nothing commanded by the press.

On the dog this is Needs-the-dog 14.7: press stop while the page still shows "connecting", and the dog must not turn.
