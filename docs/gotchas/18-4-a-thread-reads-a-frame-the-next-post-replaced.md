# 18-4 · a thread reads the camera's frame after the next POST has replaced it

**Symptom.** In a test that posts a second frame 0.3 s after an armed sighting, the file handed to dispatch holds the
second frame, not the one the detector boxed a person in. On the night that would mean the ask "person at camera lap1
(laptop at the gate). send the dog? yes / no" could carry a later photo, maybe with nobody in it. Before the fix it
was also the raw frame, not the boxed one 09 posted.

**Root cause.** Item 18 moved the ask off the camera's POST onto a thread, so the POST returns at once. `person_seen()`
handed the thread `cams/<id>.jpg`. But `ingest()` replaces that file, and `cams/<id>-boxed.jpg`, with `os.replace` on
every posted frame. The laptop client posts again 0-1 s later (`sleep(max(0, 1/hz - elapsed))` after a 1-2 s
detector). The thread reads the file only after planning, a Jev call and two chat gates. While the ask ran inside the
POST in 09, the client's next frame waited, so there was no race. Handing a thread a path that the next request
rewrites turns a per-camera file into a race.

**Fix (verbatim, `wtdd/cam/__init__.py`).** `ingest()` passes the detector's boxed file, and `person_seen()` copies it
under the trigger's epoch before the thread starts:
```python
        person = person_seen(cam_id, path, d["boxes"], boxed=Path(d["file"]))
```
```python
    if boxed is not None:   # ids have no ".", so the copy never collides with another camera's files (a missing boxed file raises)
        frame = cams() / f"{cam_id}.{int(now)}.boxed.jpg"
        shutil.copyfile(boxed, frame)
```
dispatch's `_ask()` posts only the file handed in. It never falls back to `cams/<id>-boxed.jpg` on disk; with no file it
posts text only and logs a WARN.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.cam.test_cam -v`, run alone. It
includes `Person.test_the_ask_carries_the_sightings_own_bytes_whatever_the_next_frame_is`: the shared
`lap1-boxed.jpg` is the later frame, and the handed-in file still holds `b"boxed:" + FRAME`. When you move work
onto a thread, list every path it reads and ask whether the next request rewrites it.
