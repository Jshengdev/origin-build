"""Living room off: the four Hue lights in the zone and the Tuya strip, each read back."""
ARGS = {}


def run():
    from ..commands import lights
    return {"result": lights(False)}
