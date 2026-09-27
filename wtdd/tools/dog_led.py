"""Set the dog's head light (VUI 1007) to a colour for N seconds, acked; brightness read back (1006) or 'no read-back'.
Held longer than one request by a resend every WTDD_LED_TIME_S (wtdd/dog/led.py hold); a colour outside VUI_COLOR is
refused before any send, a non-zero code raises; each request is one dog.led row. Request shape UNVERIFIED on this dog."""
ARGS = {"color": {"type": "string", "default": "cyan", "doc": "white | red | yellow | blue | green | cyan | purple"},
        "seconds": {"type": "number", "default": 5, "doc": "held this long; resent every WTDD_LED_TIME_S (5)"},
        "flash_ms": {"type": "number", "default": None, "doc": "blink period ms (upstream: 499..seconds*1000); none = steady"}}


def run(color="cyan", seconds=5, flash_ms=None):
    from ..commands import _via_api
    via = _via_api("dog_led", color=color, seconds=seconds, flash_ms=flash_ms)
    if via is not None:
        return via
    from ..dog import led
    from ..dog.session import DogSession
    s = DogSession.get()   # an explicit call may connect; a hook never does
    return s.run(s.with_body(lambda b: led.hold(b, color, seconds, flash_ms)))
