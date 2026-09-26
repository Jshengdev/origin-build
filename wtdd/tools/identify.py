"""Make one physical light announce itself so the map marker can be matched to it: a Hue lamp blinks (native on_off
signal) for a few seconds; the strip dips to 5 percent and back. Read back."""
ARGS = {"light": {"type": "string", "default": "special", "doc": "Hue light name/id, or 'strip'"},
        "seconds": {"type": "number", "default": 3}}


def run(light="special", seconds=3):
    if light == "strip":
        from ..tuya.__main__ import device, read, strip
        before = read(device())
        strip(on=True, bri=100)
        strip(bri=5)
        return strip(on=bool(before.get("on")), bri=before.get("brightness_pct") or 30)
    from ..hue.api import HueBridge
    from ..hue.__main__ import resolve
    b = HueBridge.from_env()
    rid = resolve(b.lights(), light)["id"]
    return b._put_light(rid, "lights.identify", {"signaling": {"signal": "on_off", "duration": int(seconds) * 1000}})
