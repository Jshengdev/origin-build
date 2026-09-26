"""Fade the Tuya strip brightness from start to end over seconds (real-time steps), read back at the end."""
ARGS = {"start": {"type": "number", "default": 5}, "end": {"type": "number", "default": 100},
        "seconds": {"type": "number", "default": 4}, "steps": {"type": "number", "default": 8}}


def run(start=5, end=100, seconds=4, steps=8):
    import argparse
    from ..ledger import rows
    from ..tuya.__main__ import cmd_fade
    cmd_fade(argparse.Namespace(start=float(start), end=float(end), seconds=float(seconds), steps=int(steps)))
    return {"result": rows(1)[0]["state_after"]}   # cmd_fade prints; its lights.tuya_fade row holds the read-back
