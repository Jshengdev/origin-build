# 18-2 · the camera client reads the hook's old answer and dies on the first armed sighting

**Symptom.** With the intruder watch armed, `python -m wtdd.cam --cam lap1` dies on the first frame with a person:
`KeyError: 'asked'`. With `--once` it crashes before it prints. The server has already started the dispatch, but no
more frames are posted, the Cams panel goes stale, and the next sighting is never seen. `wtdd.cam.test_cam` stayed
green, because its Client test runs disarmed only.

**Root cause.** Item 18 changed what `person_seen()` returns (wtdd/cam/__init__.py) for an armed person, from 09's
`{asked, why}` to `{dispatched: True, trigger}`. The laptop client (wtdd/cam/__main__.py) builds its one stderr line
per frame from `person['asked']`, and that line sits outside the loop's try. A hook's return shape is also read over
HTTP by a process the hook's own tests never run.

**Fix (verbatim, `wtdd/cam/__main__.py`).**
```python
            asked = "none" if person is None else f"dispatched {person['trigger']}" if person.get("dispatched") else f"asked=False ({person['why']})"
```

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.cam.test_cam_client -v` passes. It
posts the fixture frame once while armed, through the real API handler, and checks for exit 0 and a stderr line
`person dispatched cam:lap1:<epoch>`. When you change a hook's answer, grep for every reader of its keys
(`grep -rn "person\[" wtdd/cam`), the client on the other machine included.
