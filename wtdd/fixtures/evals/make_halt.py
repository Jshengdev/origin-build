"""Builds wtdd/fixtures/evals/halt.jsonl, the dry ledger behind `python -m wtdd.dog.halt --grade
wtdd/fixtures/evals/halt.jsonl` (goal 00, the body halting on a person; 11 registers the scenario as `halt` in
evals.py's ORDER at its rebase).

  python -m wtdd.fixtures.evals.make_halt                  rewrites halt.jsonl next to this file
  python -m wtdd.fixtures.evals.make_halt --out <file>     writes it elsewhere (wtdd/dog/test_halt.py compares the two)

This version drives the real code (RED declared the rows by hand, in the shape of a halt that never cancelled the
follower, and graded unsafe). In a scratch ledger, watch.json and pictures dir: the detector's watch.detect row with a
far person is appended; a DogSession on wtdd/dog/test_halt.py's FakeBody, calibrated on the first point of the map's
drawn path, follows three points of it; a near person is planted (a synthetic frame and watch.json in watch.py's
shape) and person_tick() halts it (the follower cancelled, its own StopMove and dog.follow row first, then _halt()'s
StopMove and stop.person); then Sam Stand-in (03's test name) resumes it from the page through resume_halt. The drive
loop is not started, so the rows come out in the same order every run: watch.detect, dog.cmd StopMove, dog.follow
(ok false), dog.cmd StopMove, stop.person, stop.resumed.

Every row is stamped cached: true, source: "stub", run_id "fixture-00", and the frame copy's path (stop.person
args.file, stop.resumed state_before.file) is reduced to its basename, the thumbnail's name under /pictures/: nothing
here is a live receipt, and no scratch path is committed.
"""
from __future__ import annotations
import argparse
import io
import json
import os
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "halt.jsonl"
SHIFT = "2026-09-27"
RUN = "fixture-00"
W, H = 640, 360
FAR = {"name": "person", "conf": 0.81, "xyxy": [402, 210, 440, 300]}     # 0.25 of the frame's height: outside the band
NEAR = {"name": "person", "conf": 0.88, "xyxy": [260, 120, 380, 358]}    # 0.66: inside it
PATH = [[449, 491], [465, 535], [483, 596]]                               # the first three points of ui/map.json's path


def frame_jpeg() -> bytes:
    """The synthetic frame the halt is decided on: the near box drawn the way watch.py's plot draws it, and a line that
    says what it is. No camera, no detector."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (40, 44, 52))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = NEAR["xyxy"]
    d.rectangle([x0, y0, x1, y1], outline=(255, 56, 56), width=4)
    d.rectangle([x0, y0 - 14, x0 + 92, y0], fill=(255, 56, 56))
    d.text((x0 + 4, y0 - 13), f"person {NEAR['conf']}", fill=(255, 255, 255))
    d.text((10, H - 18), "synthetic frame · fixture-00 · no camera, no detector", fill=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m wtdd.fixtures.evals.make_halt")
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="wtdd-make-halt-"))
    os.environ["WTDD_SHIFT"] = SHIFT
    from ... import ledger
    from ...dog import halt, nav, session
    from ...dog.test_halt import FakeBody
    # DEMO_CACHE: the body is FakeBody, the detector's row is declared and the near person is a planted watch.json and a
    # synthetic frame, because an agent has no dog, camera or person. Live: on the dog, run the API and
    # `python -m wtdd.watch`, follow the path, step into the frame, resume from the page with a name, then
    # `python -m wtdd.dog.halt --grade ledger.jsonl`.
    ledger.LEDGER, halt.WATCH, halt.PICTURES = tmp / "ledger.jsonl", tmp / "watch.json", tmp / "pictures"
    ledger.append({"step": "watch.detect", "agent": "watch", "tool": "watch.detect", "app": "yolo", "ok": True,
                   "args": {"source": "fixture", "model": "yolo11n.pt", "conf": 0.35}, "state_before": [],
                   "state_after": {"classes": {"person": 1}, "n": 1}, "response_or_error": [FAR], "latency_ms": 31})
    s = session.DogSession()
    try:
        s.body = FakeBody()
        s.cal = nav.calibration([0.0, 0.0], 0.0, PATH[0], nav.heading_of(PATH[0], PATH[1]))
        s.follow([list(q) for q in PATH], [])
        t0 = time.monotonic()
        while s.vel[0] <= 0 and time.monotonic() - t0 < 5:
            time.sleep(0.02)
        if s.vel[0] <= 0:
            raise RuntimeError("the follower never set a velocity toward waypoint 1")
        img = tmp / "watch.jpg"
        img.write_bytes(frame_jpeg())
        halt.WATCH.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "ms": 31, "n": 1,
                                          "classes": {"person": 1}, "boxes": [NEAR], "source": "fixture",
                                          "model": "yolo11n.pt", "file": str(img)}))
        s.person_tick()   # the person-watch thread may have halted first; either way exactly one stop.person
        if not (s.halted and s.halted.get("ok")):
            raise RuntimeError(f"the dry halt did not land: {s.halted}")
        s.resume_halt("Sam Stand-in", "page")
    finally:
        s.loop.call_soon_threadsafe(s.loop.stop)
        while s.loop.is_running():
            time.sleep(0.01)
        s.loop.close()
    rows = ledger.rows()
    for r in rows:
        r.update(cached=True, source="stub", run_id=RUN)
        if r["tool"] == "stop.person":
            r["args"]["file"] = Path(r["args"]["file"]).name
        if r["tool"] == "stop.resumed" and (r.get("state_before") or {}).get("file"):   # the halted summary it resumed
            r["state_before"]["file"] = Path(r["state_before"]["file"]).name
    out = Path(a.out)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"[wtdd:fixtures] wrote {len(rows)} rows to {out}: {' '.join(r['tool'] for r in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
