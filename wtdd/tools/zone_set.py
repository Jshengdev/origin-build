"""Set one Hue zone from wtdd/hue/zones.json (a, b, c, living room) on or off with optional brightness, read back per light.
This is the primitive the light show's corridor sweep and the map page use."""
ARGS = {"zone": {"type": "string", "default": "a"}, "on": {"type": "boolean", "default": True},
        "percent": {"type": "number", "default": None}}


def run(zone="a", on=True, percent=None):
    from ..hue.api import HueBridge
    from ..hue.__main__ import set_zone
    return set_zone(HueBridge.from_env(), zone, on, float(percent) if percent is not None else None)
