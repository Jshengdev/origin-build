"""Builds the dry ledger behind wtdd/dispatch.py's grade() (item 18, dispatch): dispatch.jsonl, one good run of the
filmed ask-first path, the rows exactly as the parents write them, so the grader is exercised on the real shapes
without a dog, a person, a camera or a model. Committed BEFORE the grader exists (CLAUDE.md: evals, RED first); re-run
after a parent changes a row: python wtdd/fixtures/evals/make_dispatch.py (stdlib only; rewrites the file next to this
script). wtdd/test_dispatch.py mutates copies of these rows in memory for the fail and unsafe cases; nothing else is
written here.

  dispatch.jsonl   cam.frame -> cam.detect (09: the local detector, a person box) -> plan.route (06: over the grid,
                   from the dog's believed pose to the camera's arrival point) -> dispatch.decided (18, app stub: the
                   DEMO_CACHE stub says ask, never dispatch) -> the ask with the boxed frame ("person at camera ... send
                   the dog? yes / no", kind dispatch) -> the on-call reply (intruder.verdict, verdict approved, asked =
                   the trigger) -> "on it" -> dispatch.decided (app imessage, args.by, choice dispatch, no p: the person
                   decided) -> plan.route again from the current pose -> dog.follow (reached == of, the end pose within
                   reach_px of the arrival) -> dog.look level -> watch.boxes -> llm.generate -> vision.check -> decided
                   (02's, from look_and_see) -> the arrival post with the photo, read back.

Every row says cached: true, source: "stub" (never a live receipt). The decision's numbers are the stub's own rule
(armed and a route exists -> ask 0.6, probabilities dispatch 0.3 / ask 0.6 / ignore 0.1; the stub NEVER returns
dispatch: a canned number never moves the body), so no row claims a decision the stub would not make; the body moves
only because a person said yes. Shapes copied from: wtdd/cam/__init__.py (09), wtdd/plan.py (06), wtdd/decide.py (02),
wtdd/chat/listen.py verdict(), wtdd/dog/session.py _follow, wtdd/tools/dog_say.py and wtdd/watch.py (main), and the
Ledger helper of 11's wtdd/fixtures/evals/make.py (origin/feat/11-evals; not on this base), copied. The people are
stand-ins (11's test names): the group is the test guid, the person on call answers from it (03's 1:1 is not on this
base, said in the PR). The map points are the fixture's: the dog at (300, 1100) (make_grid_wall.py's CAL), the camera
lap1 at (322, 1284) (09's ui/map.json), a route of three waypoints and 1.74 m clear of the fixture wall and of nogo-1;
the plan.route numbers are what wtdd/plan.py writes for that pair on make_grid_wall.grid() over
wtdd/fixtures/map_nogo.json (walls 18 on the lattice, 58 nodes searched, 188 px). Timestamps are UTC (time.gmtime) so
a re-run writes the same bytes on any machine."""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIFT = "2026-09-27"
RUN = "fixture-18"
GROUP = "any;+;00000000000000000000000000000000"   # the housemates' group (wtdd/chat/test_chat.py's fake guid)
HOUSEMATE = "+15550002222"                          # the person on call (11's stand-in), answering from the group tonight
THRESHOLD = 0.7
AUTO = 0
CHOICES = ["dispatch", "ask", "ignore"]
CAM = {"id": "lap1", "label": "laptop at the gate", "pt": [322, 1284], "zone": "a"}
TRIGGER = "cam:lap1:1790000000"
DOG0 = {"p": [300, 1100], "heading_deg": 0.0}
ARRIVAL = [322, 1284]
END = {"p": [318, 1280], "heading_deg": 96.0}       # within reach_px (30) of the arrival, by the dog's own belief
ROUTE = {"exists": True, "length_m": 1.74, "nogo": ["nogo-1"], "waypoints": 3}
BOXES = [{"name": "person", "conf": 0.87, "xyxy": [108, 34, 212, 236]}]   # wtdd/cam/fixtures/detect.json
STATE = ("a person is in view at camera lap one, the laptop at the gate, in zone a.\nthe intruder watch is armed.\n"
         "the dog is idle at stop one, in the living room, calibrated, avoidance on.\n"
         "a route to the camera exists, about two metres, around one no-go zone.\nno question is open in the thread.")
SENTENCE = "a laptop on a table by the door. nothing on the floor."
PROBS = {"dispatch": 0.3, "ask": 0.6, "ignore": 0.1}


class Ledger:
    def __init__(self, t0: int):
        self.t = t0            # epoch seconds, ticked forward
        self.rows: list[dict] = []
        self.n = 0             # posts so far (fake read-back guids)
        self.rowid = 70000     # chat.db rowids

    def ts(self) -> str:
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.t))

    def row(self, tool, agent, app, args, after=None, before=None, ok=True, err=None, ms=0, secs=1) -> dict:
        self.t += secs
        r = {"ts": self.ts(), "run_id": RUN, "cached": True, "source": "stub", "step": tool, "agent": agent, "tool": tool,
             "app": app, "args": args, "state_before": before, "state_after": after, "ok": ok, "response_or_error": err,
             "latency_ms": ms}
        self.rows.append(r)
        return r

    def post(self, trigger: str, kind: str, text: str | None, file: str | None = None) -> dict:
        """gate -> claim -> post, as wtdd/chat/__main__.post writes them; the post's state_after is the read-back."""
        self.row("chat.gate", "central", "imessage", {"guid": GROUP}, after={"guid": GROUP, "name": "wtdd test"}, ms=3)
        self.row("chat.claim", "central", "memory", {"trigger": trigger}, after={"trigger": trigger, "claimed": True}, ms=1)
        self.n += 1
        self.rowid += 1
        after = {"guid": f"FIX-POST-{self.n}", "rowid": self.rowid, "ts": self.ts()}
        return self.row("chat.post", "central", "imessage",
                        {"guid": GROUP, "kind": kind, "trigger": trigger, "text": text, "file": file, "shift_id": SHIFT},
                        before={"max_rowid": self.rowid - 1}, after=after, ms=3400, secs=3)

    def decided_args(self, **extra) -> dict:
        return {"cam": CAM["id"], "trigger": TRIGGER, "shift_id": SHIFT, "threshold": THRESHOLD, "auto": AUTO, "choices": CHOICES,
                "pt": CAM["pt"], "arrival": ARRIVAL, "route": ROUTE, "state_chars": len(STATE), **extra}

    def route(self, frm: list) -> None:
        self.row("plan.route", "plan", "map", {"from": frm, "to": ARRIVAL, "cell_px": 10, "cost_map": "grid", "threshold": 3, "walls": 18,
                                                "nogo": ["nogo-1"], "grid_source": "session"},
                 after={"cells": 19, "searched": 58, "length_px": 188, "length_m": 1.74, "waypoints": 3}, ms=12)


def dispatch() -> Path:
    l = Ledger(1790000000)
    dog = {**DOG0, "calibrated": True, "following": False, "recording": False, "pending": False}
    # the camera's own receipts, before any model: the frame lands, the local detector boxes it (09)
    l.row("cam.frame", "cam", "camera", {"cam": CAM["id"], "shift_id": SHIFT, "bytes": 3668}, after={"file": "cams/lap1.jpg"}, ms=2)
    l.row("cam.detect", "cam", "yolo", {"cam": CAM["id"], "shift_id": SHIFT, "model": "yolo11n.pt", "classes": {"person": 1}, "boxes": BOXES},
          before=None, after={"classes": {"person": 1}, "n": 1, "file": "lap1-boxed.jpg"}, ms=1400, secs=2)
    # plan FIRST, over the grid, from where the dog believes it is to the camera's arrival point (06)
    l.route(DOG0["p"])
    # the typed decision on words (18): the stub says ask; the page draws the route and the numbers before anything moves
    l.row("dispatch.decided", "dispatch", "stub", l.decided_args(), before={"dog": dog},
          after={"choice": "ask", "p": 0.6, "probabilities": PROBS, "demoted": None, "model": "stub"},
          err="stub: armed and a route to the camera exists -> ask 0.6 (the stub never dispatches)", ms=1)
    # the ask to the person on call, with the boxed frame; the reply through listen.verdict (kind dispatch)
    l.post(TRIGGER, "dispatch", f"person at camera {CAM['id']} ({CAM['label']}). send the dog? yes / no", "cams/lap1-boxed.jpg")   # dispatch.ask_line
    l.t += 12
    l.rowid += 1
    l.row("intruder.verdict", "central", "imessage",
          {"from": HOUSEMATE, "text": "yes", "guid": "FIX-REPLY-1", "asked": TRIGGER, "shift_id": SHIFT},
          after={"verdict": "approved"}, secs=0)
    l.post("dispatch-go:FIX-REPLY-1", "listen", f"on it: sending the dog to camera {CAM['id']}")
    # the approved run: the person decided (app imessage, args.by, no p), re-planned from the current pose, then the walk
    l.row("dispatch.decided", "dispatch", "imessage", l.decided_args(by=HOUSEMATE, approved=True), before={"dog": dog},
          after={"choice": "dispatch", "p": None, "probabilities": None, "demoted": None, "model": None},
          err="approved by the person on call", ms=1)
    l.route(DOG0["p"])
    l.row("dog.follow", "dog", "map", {"n": 3, "start": 0, "stops": [], "reach_px": 30.0, "avoid": True}, before=DOG0,
          after={"reached": [0, 1, 2], "of": 3, "seconds": 20.3, "map": END, "replans": 0, "skipped_stops": []}, ms=20300, secs=21)
    # on arrival: a level look, the detector's boxes (the local stop), the sentence, 02's decision, one post with the photo
    l.row("dog.look", "dog", "unitree", {"kind": "level"}, before={"mode": 0, "position": [0.2, -1.7, 0.31], "rpy": [-0.04, 0.04, 1.68], "age_ms": 5},
          after={"text": "here's what i see", "file": "look-level.jpg", "kind": "level", "pitch_deg": -0.4, "fired": True, "attempts": 1}, ms=1500, secs=2)
    l.row("watch.boxes", "watch", "yolo", {"file": "look-level.jpg"}, after={"file": "look-level-boxed.jpg", "classes": {"laptop": 1}, "n": 1, "ms": 900}, ms=900)
    l.row("llm.generate", "watch", "openrouter", {"model": "x-ai/grok-4.20", "n_messages": 2, "n_images": 1, "max_tokens": 160},
          after={"model": "x-ai/grok-4.20", "usage": {"prompt_tokens": 800, "completion_tokens": 60, "total_tokens": 860}, "finish_reason": "stop"}, ms=1200, secs=2)
    l.row("vision.check", "watch", "openrouter", {"detector": {"laptop": 1}, "file": "look-level.jpg"},
          after={"out_of_place": [], "person": False, "detector_check": "agree", "agree": True}, err=SENTENCE, ms=1200)
    l.row("decided", "decide", "stub", {"stop": None, "shift_id": SHIFT, "state_chars": 150, "threshold": THRESHOLD},
          before={"labels": ["clear", "out_of_place", "hazard", "person"]},
          after={"label": "clear", "p": 0.8, "needs_person": False, "model": "stub"}, err="stub: clear; eyes agree", ms=1)
    l.post(f"{TRIGGER}:done", "dispatch", f"here's what i see at camera {CAM['id']} ({CAM['label']}): {SENTENCE} [detector: laptop]",
           "look-level-boxed.jpg")
    out = HERE / "dispatch.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in l.rows))
    print(f"{out.relative_to(HERE.parents[2])}: {len(l.rows)} rows, every one cached (stub)")
    return out


if __name__ == "__main__":
    dispatch()
