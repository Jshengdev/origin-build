"""Set the dog's head light (VUI 1007) to a colour for N seconds, acked; brightness read back (1006) or 'no read-back'.
Held longer than one request by a resend every WTDD_LED_TIME_S (wtdd/dog/led.py hold); a colour outside VUI_COLOR is
refused before any send, a non-zero code raises; each request is one dog.led row. Request shape UNVERIFIED on this dog.
Through the API the hold is fire-and-forget; from a CLI with no API up, run() waits out the resends, which live on the
session's daemon thread and would die with the process."""
ARGS = {"color": {"type": "string", "default": "cyan", "doc": "white | red | yellow | blue | green | cyan | purple"},
        "seconds": {"type": "number", "default": 5, "doc": "held this long; resent every WTDD_LED_TIME_S (5)"},
        "flash_ms": {"type": "number", "default": None, "doc": "blink period ms (upstream: 499..seconds*1000); none = steady"}}


def run(color="cyan", seconds=5, flash_ms=None):
    import os
    from ..commands import _via_api
    via = _via_api("dog_led", color=color, seconds=seconds, flash_ms=flash_ms)
    if via is not None:
        return via
    from ..dog import led
    from ..dog.session import DogSession
    s = DogSession.get()   # an explicit call may connect; a hook never does
    st = s.run(s.with_body(lambda b: led.hold(b, color, seconds, flash_ms)))
    if not os.environ.get("WTDD_API_PROCESS"):   # a CLI: the resend rows land before it exits
        s.run(_held(s.body), timeout=float(seconds) + 30)
    return st


async def _held(b):
    """Waits for the held colour's resend task (led.hold's keeper), if one was started. asyncio.wait never raises: a
    resend's refusal is its own FAILED row and WARN line, and a newer state cancelling the hold ends the wait."""
    import asyncio
    if b._led_keeper is not None:
        await asyncio.wait([b._led_keeper])
