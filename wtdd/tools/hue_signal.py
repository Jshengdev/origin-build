"""Alternate one Hue colour light between red and blue for N seconds (the alert), read back."""
ARGS = {"light": {"type": "string", "default": "special", "doc": "Hue light name or id"},
        "seconds": {"type": "number", "default": 5}}


def run(light="special", seconds=5):
    from ..hue.api import HueBridge
    from ..hue.__main__ import resolve
    b = HueBridge.from_env()
    return b.signal(resolve(b.lights(), light)["id"], float(seconds))
