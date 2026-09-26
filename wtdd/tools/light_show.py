"""The show: living room on, dim, bright, the corridor sweep a to c, a strip fade, red/blue on one lamp, then back to
how it was. About 25 seconds. Every step is its own receipt; returns the step count and the first failure if any."""
ARGS = {"signal_seconds": {"type": "number", "default": 4}}


def run(signal_seconds=4):
    import time
    from . import call
    steps = [
        ("lights_status", {}), ("lights_on", {"percent": 100}), ("lights_dim", {"percent": 15}), ("lights_dim", {"percent": 100}),
        ("zone_set", {"zone": "a", "on": True}), ("zone_set", {"zone": "b", "on": True}), ("zone_set", {"zone": "a", "on": False}),
        ("zone_set", {"zone": "c", "on": True}), ("strip_set", {"on": True, "percent": 100}), ("zone_set", {"zone": "b", "on": False}),
        ("strip_fade", {"start": 100, "end": 5, "seconds": 3, "steps": 6}), ("strip_fade", {"start": 5, "end": 100, "seconds": 3, "steps": 6}),
        ("hue_signal", {"light": "special", "seconds": float(signal_seconds)}),
    ]
    before = None
    done, failed = 0, None
    for name, args in steps:
        try:
            out = call(name, **args)
            if name == "lights_status":
                before = out
            done += 1
        except Exception as e:  # noqa: BLE001  (the tool's ledger row has it; the show reports the first failure and keeps going)
            failed = failed or f"{name}: {type(e).__name__}: {str(e)[:80]}"
    if before:  # restore: the living room and the strip to their state before the show
        time.sleep(float(signal_seconds))
        try:
            any_on = any(l["on"] for l in before["hue"] if l.get("room") == "Living room")
            call("lights_on" if any_on else "lights_off")
            s = before.get("strip", {})
            if "on" in s:
                call("strip_set", on=bool(s["on"]), percent=s.get("brightness_pct"))
        except Exception as e:  # noqa: BLE001  (reported in the result, not hidden)
            failed = failed or f"restore: {type(e).__name__}: {str(e)[:80]}"
    return {"steps": len(steps), "done": done, "failed": failed}
