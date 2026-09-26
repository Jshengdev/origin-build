"""Read every light back: the Hue lights (id, name, room, on, brightness, xy, signal) and the Tuya strip (on, mode,
brightness_pct, temp_pct), or {"error": ...} for the strip when it does not answer. Those keys are read by
ui/index.html and by light_show's restore, so they are a contract."""
ARGS = {}


def run():
    from ..hue.api import HueBridge, summary
    from ..tuya.__main__ import device, read
    b = HueBridge.from_env()
    rooms = {ch["rid"]: room["metadata"]["name"] for room in b.rooms() for ch in room.get("children", [])}
    hue = [{"id": l["id"], "name": l["metadata"]["name"], "room": rooms.get(l.get("owner", {}).get("rid")), **summary(l)} for l in b.lights()]
    try:
        strip = read(device())
    except Exception as e:  # noqa: BLE001  (reported as an error field, never as fake state)
        strip = {"error": f"{type(e).__name__}: {e}"}
    strip.pop("raw", None)
    return {"hue": hue, "strip": strip}
