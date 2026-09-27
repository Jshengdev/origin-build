"""The head light follows the agent: the dog's own VUI light shows the state in the room where the person stands.

  state      colour   held (HOLD_S)   hooked from (one line each)
  scanning   cyan     120 s           session.lidar(True), session.follow() start
  asking     red      120 s           intruder_alarm right after "who dis?!" (= its PENDING_WINDOW_S: red while the question is open)
  halted     red      30 s            session.stop(), after the halt
  clear      green    5 s             the listener's "ok, standing down", the follow reaching its end

hook(state) is the one line at a call site. It never raises and never blocks the ask, the halt or the follow: in the
process that holds the dog it schedules hold() on the session loop and returns; in the API process without a dog it is
one WARN and no row (a light never triggers a connect); in any other process (the listener) it posts the dog_led tool to
the API on a daemon thread (_post_api). hold() sends one request of time_s() seconds (Body.led: one dog.led row each)
and a keeper task resends it every time_s() until the state's HOLD_S is covered, the k-th at first send + k*time_s()
(a request that waits on a slow 1006 read-back never stretches the period); a newer state cancels the keeper, and a
refused request is never resent. Imports stdlib, config and the ledger only: the listener imports this module, and it
must not load the driver.

UNVERIFIED on the dog (Needs the dog 25.1-25.5): the request shape, the `time` ceiling (WTDD_LED_TIME_S, 5 s as in the
upstream example, so a held state is resent every 5 s), whether the light flickers between resends, the flash_cycle
bounds, whether 1006 answers.
"""
from __future__ import annotations
import asyncio
import math
import os
import sys
import threading
from typing import Any

from .. import config
from ..ledger import log

COLOURS = {"scanning": "cyan", "asking": "red", "halted": "red", "clear": "green"}   # the head's table
HOLD_S = {"scanning": 120.0, "asking": 120.0, "halted": 30.0, "clear": 5.0}         # asking = intruder_alarm.PENDING_WINDOW_S; clear is one request


def time_s() -> float:
    """The `time` of one VUI 1007 request, read at the point of use; a held state is resent this often."""
    return float(config.maybe("WTDD_LED_TIME_S") or 5)


async def hold(b: Any, color: str, seconds: float, flash_ms: float | None = None, **row: Any) -> dict:
    """Shows `color` for `seconds`: one request now (returns its led_state, or raises on a refusal), then a keeper task
    resends it every time_s() until `seconds` is covered or a newer hold supersedes it."""
    gen = b._led_gen = b._led_gen + 1
    if b._led_keeper and not b._led_keeper.done():
        b._led_keeper.cancel()
    t = min(float(seconds), time_s())
    t0 = asyncio.get_running_loop().time()   # the resends keep this clock: the k-th starts at t0 + k*t, whatever 1006 took
    st = await b.led(color, t, flash_ms, **row)
    n = math.ceil(float(seconds) / t - 1e-9) if t > 0 else 1   # requests to cover `seconds`; a time <= 0 is sent once, the dog's to refuse
    if n > 1 and b._led_gen == gen:   # a newer hold that began while this request was in flight wins
        b._led_keeper = asyncio.get_running_loop().create_task(_resend(b, gen, color, t, flash_ms, n, row, t0))
    return st


async def _resend(b: Any, gen: int, color: str, t: float, flash_ms: float | None, n: int, row: dict, t0: float) -> None:
    loop = asyncio.get_running_loop()
    try:
        for k in range(1, n):
            await asyncio.sleep(max(0.0, t0 + k * t - loop.time()))
            if b._led_gen != gen:
                return
            await b.led(color, t, flash_ms, resend=k, **row)
    except asyncio.CancelledError:
        return
    except Exception as e:  # noqa: BLE001  (its FAILED dog.led row is written; the hold stops, never retried)
        log("dog", f"WARN led {color} hold stopped", err=f"{type(e).__name__}: {str(e)[:100]}")


def hook(state: str) -> None:
    """The one line at each call site: the head light shows `state`. Never raises, never blocks, never waits."""
    try:
        color, seconds = COLOURS[state], HOLD_S[state]
        sess = sys.modules.get(f"{__package__}.session")   # never imported here: the listener must stay light
        s = sess.DogSession._inst if sess else None
        if s is not None and s.body is not None:
            fut = asyncio.run_coroutine_threadsafe(hold(s.body, color, seconds), s.loop)
            fut.add_done_callback(lambda f: _done(f, state, color))
        elif os.environ.get("WTDD_API_PROCESS"):
            log("dog", f"WARN led {state} ({color}) skipped: the dog is not connected")
        else:
            threading.Thread(target=_via, args=(state, color, seconds), daemon=True).start()
    except Exception as e:  # noqa: BLE001  (a light never raises into the ask, the halt or the follow)
        log("dog", f"WARN led hook {state!r} failed", err=f"{type(e).__name__}: {str(e)[:100]}")


def _done(fut: Any, state: str, color: str) -> None:
    if not fut.cancelled() and fut.exception() is not None:
        e = fut.exception()
        log("dog", f"WARN led {state} ({color}) not shown (its dog.led row says why)", err=f"{type(e).__name__}: {str(e)[:100]}")


def _via(state: str, color: str, seconds: float) -> None:
    try:
        if _post_api(color, seconds) is None:
            log("dog", f"WARN led {state} ({color}) skipped: no API process holds the dog")
    except Exception as e:  # noqa: BLE001  (the API's own dog.led row has the refusal)
        log("dog", f"WARN led {state} ({color}) via the API failed", err=f"{type(e).__name__}: {str(e)[:100]}")


def _post_api(color: str, seconds: float) -> Any:
    """The hook's cross-process transport: the dog_led tool through the API that holds the dog (None when no API is up).
    Replaced by a recorder in the tests."""
    from ..commands import _via_api
    return _via_api("dog_led", color=color, seconds=seconds)
