"""Walk the route and drive the real lights by the field (closer = brighter, the strip scored along its length, other
rooms dimmed), pausing at the map's stops. source=entity: a simulated entity walks the drawn path in real time (the dog
is hand-driven). source=dog: the API's follower drives the real dog along the same path (calibrated, avoidance on), the
lights follow where it believes it is, and at every stop the dog performs the action recorded there (map.json
`actions`: the look kind and whether to post; default a tilt look posted to the castle), keyed round:<epoch>:<stop> so a
replay never posts twice for one stop. The chat's wake sequence calls wtdd.field.walk itself to key the posts on the
wake message. Returns seconds, writes, rooms, stops, and the actions done."""
ARGS = {"dry": {"type": "boolean", "default": False, "doc": "true = compute and log levels, write nothing"},
        "source": {"type": "string", "default": "entity", "doc": "entity | dog"},
        "act": {"type": "boolean", "default": True, "doc": "source=dog: perform the recorded action at each stop (look, and post when recorded so)"},
        "avoid": {"type": "boolean", "default": True, "doc": "source=dog: require the dog's obstacle avoidance (false = follow without it, by explicit choice, logged)"},
        "follower": {"type": "boolean", "default": True, "doc": "source=dog: false = no route, the lights just follow the dog wherever it is driven, until POST /field/stop"}}


def run(dry=False, source="entity", act=True, avoid=True, follower=True):
    import json
    import time
    from ..field import MAP, walk
    if source != "dog":
        return walk(dry=dry, source=source)
    from ..commands import _via_api
    via = _via_api("walk_path", dry=dry, source=source, act=act, avoid=avoid, follower=follower)   # the API process owns the dog: it runs the whole round
    if via is not None:
        return via
    from ..dog.session import DogSession
    from ..ledger import log
    m = json.loads(MAP.read_text())
    actions = m.get("actions") or {}
    run_id = int(time.time())
    done = []

    def on_stop(i, p, here):
        if not act:
            return
        a = actions.get(str(i)) or {"look": "tilt", "say": True}
        from . import dog_look, dog_say
        try:
            out = dog_say.run(look=a.get("look", "tilt"), trigger=f"round:{run_id}:{i}", stop=i) if a.get("say", True) else dog_look.run(look=a.get("look", "tilt"))
            done.append({"stop": i, "look": a.get("look", "tilt"), "say": bool(a.get("say", True)), "ok": True, "text": out.get("text")})
        except Exception as e:  # noqa: BLE001  (recorded on the action's own rows; the walk goes on and the result names it)
            done.append({"stop": i, "look": a.get("look", "tilt"), "say": bool(a.get("say", True)), "ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"})
            log("field", f"action at stop {i} FAILED", err=str(e)[:120])

    if not follower:   # the lights follow the dog wherever it is driven; no route, no stops, until POST /field/stop
        return walk(dry=dry, source="dog", follower=False)
    DogSession.get().follow(m["path"], [int(i) for i in m.get("stops", [])], avoid=avoid)
    out = walk(dry=dry, source="dog", on_stop=on_stop)
    return {**out, "actions": done}
