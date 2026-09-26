"""What a chat command actually does. HANDLERS maps each fixed phrase (the WTDD_COMMANDS list in .env, minus "stop",
which wtdd/chat/listen.py handles itself) to exactly one registry tool call, so a text, the remote's button, the CLI and
the MCP run the same code. run(name) wraps the call in one command.<name> ledger row and raises on any failure; the
listener posts the truth either way (the result, or the error class and message). Nothing here fakes a success.
Also hosts the primitives the tools wrap: lights() (living room, both protocols), dog_cmd(), look(), do_round().

  python -m wtdd lights_dim percent=20         the same call as the chat command "dim"
Facts: the living room is the four Hue lights of zone "living room" in wtdd/hue/zones.json (cloud CLIP v2, about 0.8 s
per light incl. read-back) plus the Tuya strip (local protocol 3.5, about 0.4 s); a whole-room change reads back in
about 2.7 s. Never any other light (SCOPE-LOCK: never a device that was not asked for). A dog command opens one WebRTC
connection, runs, and closes it; the connect preflight refuses when the dog is unreachable.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable

from .ledger import step

LOOK = Path("~/Pictures/wtdd/look.jpg").expanduser()
ZONE = "living room"


def lights(on: bool, bri: float | None = None) -> str:
    """The living room, both protocols, each device read back; a failure on either is raised, not hidden."""
    from .hue.api import HueBridge
    from .hue.__main__ import set_zone
    from .tuya.__main__ import strip
    b = HueBridge.from_env()
    names = {l["id"]: l["metadata"]["name"] for l in b.lights()}
    done = [names.get(i, i[:8]) for i in set_zone(b, ZONE, on, bri)]
    st = strip(on=on, bri=bri if on else None)
    done.append(f"strip {'on' if st.get('on') else 'off'}" + (f" {st.get('brightness_pct')}%" if st.get("on") else ""))
    verb = "off" if not on else "on" + (f" at {int(bri)}%" if bri is not None else "")
    return f"{ZONE} lights {verb}: {', '.join(done)} (read back)"


def _via_api(tool: str, **args: Any) -> Any | None:
    """While the API process runs it owns the dog's single WebRTC slot, so any other process sends dog tools to it (and
    walk_path, so the remote's map can follow the walk). Returns None when no API is up (then this process does the work
    itself). The API process itself never recurses."""
    import os
    if os.environ.get("WTDD_API_PROCESS"):
        return None
    import requests
    port = os.environ.get("WTDD_API_PORT", "7788")
    try:
        r = requests.post(f"http://127.0.0.1:{port}/tools/{tool}", json=args, timeout=600)
    except requests.exceptions.ConnectionError:
        return None
    out = r.json()
    if not out.get("ok"):
        err = out.get("error") or f"{tool} failed via the API"
        raise RuntimeError(err.split(": ", 1)[1] if err.split(": ", 1)[0].endswith("Error") else err)   # the API already names the class once
    return out["result"]


def dog_cmd(name: str) -> str:
    via = _via_api("dog_cmd", name=name)
    if via is not None:
        return via["result"]
    from .dog.session import DogSession
    s = DogSession.get()
    code = s.cmd(name)
    st = (s.state().get("state") or {})
    return f"{name.lower()} done (status {code}, mode {st.get('mode')})"


def look(kind: str = "tilt") -> dict[str, Any]:
    via = _via_api("dog_look", look=kind)
    if via is not None:
        return via
    from .dog.session import DogSession
    return DogSession.get().look(kind)


def do_round() -> str:
    via = _via_api("dog_round")
    if via is not None:
        return via["result"]
    from .dog.body import ROUTES, validate_route
    from .dog.session import DogSession
    steps = json.loads((ROUTES / "corridor.json").read_text())
    validate_route(steps)   # raises ValueError on a bad route, before any connection; returns the plan otherwise
    done = DogSession.get().run(DogSession.get().with_body(lambda b: b.route(steps, "corridor")), timeout=600)
    return f"round done: {len(done)} steps"


def _t(tool: str, **args: Any) -> Callable[[], Any]:
    from . import tools
    return lambda: tools.call(tool, **args)


def _status() -> str:
    from . import tools
    st = tools.call("lights_status")
    hue = ", ".join(f"{l['name']} {'on' if l['on'] else 'off'}" for l in st["hue"] if l.get("room") == "Living room")
    s = st["strip"]
    return f"{hue}; strip {'on' if s.get('on') else 'off'} {s.get('brightness_pct', '?')}%" if "error" not in s else f"{hue}; strip: {s['error']}"


HANDLERS: dict[str, Callable[[], Any]] = {
    "lights on": _t("lights_on"),
    "lights off": _t("lights_off"),
    "dim": _t("lights_dim", percent=20),
    "bright": _t("lights_dim", percent=100),
    "show": _t("light_show"),
    "sit": _t("dog_cmd", name="Sit"),
    "stand": _t("dog_cmd", name="RiseSit"),
    "hello": _t("dog_cmd", name="Hello"),
    "look": _t("dog_look"),
    "do a round": _t("dog_round"),
    "status": _status,
}


def run(name: str) -> Any:
    """Returns a str, or {"text", "file"} for a photo reply. Raises on any failure; one ledger row either way."""
    if name not in HANDLERS:
        raise KeyError(f"no handler for command {name!r}; handlers: {', '.join(HANDLERS)}")
    with step("central", "command." + name.replace(" ", "_"), "wtdd", {"command": name}) as r:
        out = HANDLERS[name]()
        r["state_after"] = out if isinstance(out, dict) else {"text": str(out)}
        return out
