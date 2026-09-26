"""Set one Hue light by name or id (on/off, brightness percent), read back. The proximity field uses this per lamp."""
ARGS = {"light": {"type": "string", "default": "special"}, "on": {"type": "boolean", "default": True},
        "percent": {"type": "number", "default": None}}


def run(light="special", on=True, percent=None):
    from ..hue.api import HueBridge
    from ..hue.__main__ import resolve
    b = HueBridge.from_env()
    rid = light if len(light) == 36 and light.count("-") == 4 else resolve(b.lights(), light)["id"]   # a uuid needs no lookup
    return b.set(rid, on=on, bri=float(percent) if (percent is not None and on) else None)
