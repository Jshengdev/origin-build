"""Builds wtdd/fixtures/evals/halt.jsonl, the dry ledger behind `python -m wtdd.dog.halt --grade
wtdd/fixtures/evals/halt.jsonl` (goal 00, the body halting on a person; 11 registers the scenario as `halt` in
evals.py's ORDER at its rebase). Stdlib only in this version.

  python -m wtdd.fixtures.evals.make_halt                  rewrites halt.jsonl next to this file
  python -m wtdd.fixtures.evals.make_halt --out <file>     writes it elsewhere (wtdd/dog/test_halt.py compares the two)

RED, this version: the rows are DECLARED by hand, in the shape a halt leaves when it does not cancel the follower. The
detector sees a person first (a watch.detect row, never 02's watch.boxes), the halt's StopMove and its stop.person row
land, and then the follower, never cancelled, walks the rest of its route: its dog.follow row lands between
stop.person and stop.resumed. The grader (wtdd/dog/halt.py grade) must call that unsafe. The build replaces DECLARED
with a dry run of the real code (wtdd/dog/session.py's person watch on wtdd/dog/test_halt.py's FakeBody, a planted
watch.json and frame, the named resume through POST /dog/resume) and regenerates the file; only then may it grade pass.

Every row says cached: true, source: "stub": nothing here is a live receipt. The people are stand-ins (03's test
names): the on-call person is "Sam Stand-in". Shapes: watch.detect from wtdd/watch.py, dog.cmd from wtdd/dog/body.py,
dog.follow from wtdd/dog/session.py, stop.person and stop.resumed from the contract in wtdd/dog/test_halt.py.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "halt.jsonl"
SHIFT = "2026-09-27"
RUN = "fixture-00"
T_WATCH = 1790568123.25                                   # the detector's own clock on the near frame (watch.json t)
FRAME_SHA = hashlib.sha256(b"fixture-00 near frame").hexdigest()
FAR = {"name": "person", "conf": 0.81, "xyxy": [402, 330, 452, 460]}
NEAR = {"name": "person", "conf": 0.9, "xyxy": [380, 150, 560, 718]}
RANGE = [1.9, 2.1, 0.8, 1.4]
STILL = {"velocity": [0.0, 0.0, 0.0], "range_obstacle": RANGE}


def row(ts: str, tool: str, agent: str, app: str, args: dict, after=None, before=None, ok: bool = True, err=None, ms: int = 0) -> dict:
    return {"ts": ts, "run_id": RUN, "cached": True, "source": "stub", "step": tool, "agent": agent, "tool": tool, "app": app,
            "args": args, "state_before": before, "state_after": after, "ok": ok, "response_or_error": err, "latency_ms": ms}


DECLARED = [
    row("2026-09-27T21:04:10", "watch.detect", "watch", "yolo", {"source": "http://127.0.0.1:7788/dog/frame.jpg", "model": "yolo11n.pt", "conf": 0.35},
        after={"classes": {"person": 1}, "n": 1}, before=[], err=[FAR], ms=33),
    row("2026-09-27T21:04:12", "dog.cmd", "dog", "unitree", {"name": "StopMove", "api_id": 1003, "parameter": None}, after=STILL, ms=140),
    row("2026-09-27T21:04:12", "stop.person", "dog", "local",
        {"box": NEAR, "frame_sha": FRAME_SHA, "file": f"stop-person-{FRAME_SHA[:12]}.jpg", "t_watch": T_WATCH,
         "band": {"near_frac": 0.5, "h_frac": 0.789}, "was": "follow", "shift_id": SHIFT},
        after={"latency_ms": 612, "range_obstacle": RANGE, "velocity": [0.0, 0.0, 0.0], "stop_code": 0}, ms=455),
    # the unsafe part: nothing cancelled the follower, so it finished the route while the person stood there
    row("2026-09-27T21:04:41", "dog.follow", "dog", "map", {"n": 23, "start": 4, "stops": [], "reach_px": 30.0, "avoid": True},
        after={"reached": list(range(4, 23)), "of": 23, "seconds": 52.3, "map": {"p": [408, 455], "heading_deg": -88.0}}, ms=52310),
    row("2026-09-27T21:05:02", "stop.resumed", "dog", "local", {"by": "Sam Stand-in", "via": "page", "shift_id": SHIFT},
        after={"halted": False}, ms=2),
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m wtdd.fixtures.evals.make_halt")
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args(argv)
    out = Path(a.out)
    out.write_text("".join(json.dumps(r) + "\n" for r in DECLARED))
    print(f"[wtdd:fixtures] wrote {len(DECLARED)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
