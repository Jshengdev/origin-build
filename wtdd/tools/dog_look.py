"""Nod and shoot: the dog takes a picture with one of three looks and returns the file. tilt (default) = the
down-then-up nod, frame at 15 degrees up; level = standing, straight ahead; sit = 48 degrees up. Measured recipes and
timings live in wtdd/dog/session.py. Returns text, file, kind, pitch_deg."""
ARGS = {"look": {"type": "string", "default": "tilt", "doc": "tilt | level | sit"}}


def run(look="tilt"):
    from ..commands import look as _look
    return _look(look)
