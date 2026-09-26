"""Tuya strip colour temperature percent: 0 warm to 100 cool, read back."""
ARGS = {"percent": {"type": "number", "default": 50, "doc": "0 warm .. 100 cool"}}


def run(percent=50):
    from ..tuya.__main__ import strip
    return strip(temp=float(percent))
