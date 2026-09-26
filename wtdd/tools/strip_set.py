"""Tuya strip on/off with optional brightness percent, read back (the strip half of a zone)."""
ARGS = {"on": {"type": "boolean", "default": True}, "percent": {"type": "number", "default": None}}


def run(on=True, percent=None):
    from ..tuya.__main__ import strip
    return strip(on=on, bri=float(percent) if (percent is not None and on) else None)
