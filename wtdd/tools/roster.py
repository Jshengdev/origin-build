"""The night's roster from ui/map.json: every stop to the body once, each fixed camera to its zone, the on-call person.
wtdd/schedule.py roster(): one schedule.shift row; the on-call name is WTDD_ON_CALL_NAME (absent = RuntimeError)."""
ARGS = {}


def run():
    import json
    from ..field import MAP
    from ..schedule import roster
    return roster(json.loads(MAP.read_text()))
