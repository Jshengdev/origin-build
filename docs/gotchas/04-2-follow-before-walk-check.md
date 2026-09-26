# 04-2 · a route check in field.walk alone never stops the real dog

## Symptom
A refusal placed only in `field.walk` (next to `check_path`) looks complete on the simulated walk, but with
`walk_path source=dog` (the chat round with WTDD_ROUND=dog, and the remote's walk button once the dog is calibrated)
the dog is already driving the route when the walk refuses it.

## Root cause
wtdd/tools/walk_path.py starts the follower first and only then runs the walk:
`DogSession.get().follow(m["path"], [int(i) for i in m.get("stops", [])], avoid=avoid)` comes before
`out = walk(dry=dry, source="dog", on_stop=on_stop)`. Only the API's POST /dog/follow validates the path before
calling `follow()`. So the only place every caller of the follower passes through is `DogSession.follow` itself.

## Fix (verbatim)
The first two statements of `DogSession.follow` in wtdd/dog/session.py, before the calibration check, any connect and
the avoidance switch:
```python
        from ..nogo import refuse                  # 04: a route through a drawn no-go zone is refused before anything else is looked at
        refuse(path, "dog")                        # reads the map's zones; one route.refused row, then ValueError; no probe, no connect, no dog.follow row
```
`field.walk` keeps its own `refuse(pts, "field", m)` right after `check_path` for the simulated walk and the chat round.

## Verify
```
.venv/bin/python -m unittest wtdd.test_nogo.Refusal.test_follow_refuses_before_connecting
```
OK: the session is built with no dog and no calibration, `follow()` raises ValueError naming nogo-1, the ledger gets
exactly one `route.refused` row with agent `dog` and no `dog.*` row, `s.body` stays None and `s.follow_state` stays `{}`.
