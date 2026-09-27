"""Builds the dry ledgers behind `python -m wtdd.evals --scenario decide | escalate | refuse | correct` (item 11):
one JSONL file per scenario, the rows exactly as the parent branches write them, so the graders are exercised on the
real shapes without a dog, a person or a model. Re-run after a parent changes a row: python wtdd/fixtures/evals/make.py
(stdlib only; rewrites the files next to this script).

  decide.jsonl        one round, three stops: at each, dog.look -> watch.boxes (the local stop) -> llm.generate ->
                      vision.check -> decided (02) -> the say post; stop 22 decides at p 0.55 < 0.7 so it asks
                      ("not sure: ...", 02's ask_line) and a housemate answers (intruder.verdict, 03's acked_ms)
  escalate.jsonl      the detector sees a person: watch.detect -> the look and its boxes -> "who dis?!" to the on-call
                      person's 1:1 (kind escalate, 03) -> their reply (intruder.verdict, acked_ms) -> "ok, standing
                      down" -> record.signed closes the shift -> a second signature refused (ok false)
  refuse.jsonl        a taught route through a drawn no-go zone: route.refused (04: source "map" at the top level and in
                      args, ok false, the waypoint inside the zone) and nothing after it but the "dog done" post
  refuse-map.json     the map that refusal is sourced to: the one zone (04's nogo-1) and the path through it
  correct.jsonl       the failure shot: at stop 10 the agent labels "person" at p 0.9 (no ask), a housemate corrects it
                      ("thats a tarp ...", chat.correction joined to the post, acked_ms), and the next round's look at
                      stop 10 decides "clear": the corrected label re-pins

Every row says cached: true (never a live receipt); source is "stub", or "map" on the route.refused row because that is
04's own contract for it. Shapes copied from: wtdd/decide.py (02), wtdd/chat/oncall.py + listen.py + tools/record_sign.py
(03), wtdd/nogo.py (04), wtdd/tools/dog_say.py, wtdd/watch.py and docs/evidence/ledger-sample-2026-09-13.jsonl (main).
Stub rules honoured: the decided label and p follow 02's DEMO_CACHE stub (person -> 0.9, out of place -> 0.85, clear ->
0.8, minus 0.3 when the eyes disagree), so no row claims a decision the stub would not make.
The people are stand-ins (03's test names): the group is the test guid, the on-call person is +15550002222.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIFT = "2026-09-27"
RUN = "fixture-11"
GROUP = "any;+;00000000000000000000000000000000"   # the housemates' group (wtdd/chat/test_chat.py's fake guid)
NAME, HANDLE = "Sam Stand-in", "+15550002222"      # the on-call person (wtdd/chat/test_oncall.py)
ONCALL = f"any;-;{HANDLE}"                          # their 1:1 chat (wtdd/chat/oncall.py guid())
HOUSEMATE = "+15550003333"
THRESHOLD = 0.7
LABELS = ["clear", "out_of_place", "hazard", "person"]   # wtdd/decide.py DEFAULT_LABELS
MODEL = "x-ai/grok-4.20"
NOGO = {"name": "nogo-1", "label": "no-go 1", "poly": [[450, 1040], [510, 1040], [510, 1250], [450, 1250]], "nogo": True}
PATH_THROUGH = [[300, 1100], [480, 1100], [650, 1100]]   # point 2 is inside nogo-1 (04's fixture route)
UTC_OFFSET_H = 7                                          # PT in September: the ledger's ts is local, chat.db's is UTC


class Clock:
    """Local ledger time and chat.db's UTC time, ticking forward so acked_ms can be computed, never typed."""

    def __init__(self, local: str):
        self.t = dt.datetime.strptime(local, "%Y-%m-%dT%H:%M:%S")

    def tick(self, s: int) -> None:
        self.t += dt.timedelta(seconds=s)

    def local(self) -> str:
        return self.t.strftime("%Y-%m-%dT%H:%M:%S")

    def utc(self) -> str:
        return (self.t + dt.timedelta(hours=UTC_OFFSET_H)).strftime("%Y-%m-%d %H:%M:%S")


class Ledger:
    def __init__(self, start: str):
        self.c = Clock(start)
        self.rows: list[dict] = []
        self.n = 0          # posts so far (fake read-back guids)
        self.rowid = 60000  # chat.db rowids

    def row(self, tool, agent, app, args, after=None, before=None, ok=True, err=None, ms=0, secs=1, **extra) -> dict:
        self.c.tick(secs)
        r = {"ts": self.c.local(), "run_id": RUN, "cached": True, "source": "stub", "step": tool, "agent": agent, "tool": tool,
             "app": app, "args": args, "state_before": before, "state_after": after, "ok": ok, "response_or_error": err,
             "latency_ms": ms, **extra}
        self.rows.append(r)
        return r

    def post(self, to: str, trigger: str, kind: str, text: str | None, file: str | None = None) -> dict:
        """gate -> claim -> post, as wtdd/chat/__main__.post writes them; the post's state_after is the read-back."""
        name = NAME if to == ONCALL else "wtdd test"
        self.row("chat.gate", "central", "imessage", {"guid": to}, after={"guid": to, "name": name}, ms=3)
        self.row("chat.claim", "central", "memory", {"trigger": trigger}, after={"trigger": trigger, "claimed": True}, ms=1)
        self.n += 1
        self.rowid += 1
        after = {"guid": f"FIX-POST-{self.n}", "rowid": self.rowid, "ts": self.c.utc()}
        if file and text:   # a photo with a caption lands as two from-me rows (03: the caption is its own read-back)
            self.rowid += 1
            after["caption"] = {"guid": f"FIX-POST-{self.n}c", "rowid": self.rowid, "ts": self.c.utc()}
        return self.row("chat.post", "central", "imessage",
                        {"guid": to, "kind": kind, "trigger": trigger, "text": text, "file": file, "shift_id": SHIFT},
                        before={"max_rowid": self.rowid - (2 if file and text else 1)}, after=after, ms=3400, secs=3)

    def acked(self, post: dict, secs: int) -> int:
        """The reply lands `secs` after the post's confirmed from-me row: acked_ms on chat.db's clock (whole seconds)."""
        posted = dt.datetime.strptime(post["state_after"]["ts"], "%Y-%m-%d %H:%M:%S")
        self.c.t = posted - dt.timedelta(hours=UTC_OFFSET_H) + dt.timedelta(seconds=secs)
        return secs * 1000

    def wake(self, guid: str) -> None:
        self.row("chat.wake", "central", "imessage", {"text": "what the dog doin", "phrase": "what the dog doin", "score": 1.0},
                 after={"armed": True, "armed_by": HOUSEMATE})
        self.post(GROUP, f"fire:{guid}", "listen", None, "this-is-fine.jpg")

    def look(self, kind: str, classes: dict) -> None:
        """The stop's own receipts before any model: the nod and the detector's boxes (the local person-in-frame stop)."""
        self.row("dog.look", "dog", "unitree", {"kind": kind},
                 before={"mode": 0, "position": [-1.42, 2.77, 0.31], "rpy": [-0.04, 0.04, -0.63], "age_ms": 5},
                 after={"text": "here's what i see", "file": f"look-{kind}.jpg", "kind": kind, "pitch_deg": -13.8 if kind == "tilt" else -0.4,
                        "fired": True, "attempts": 1}, ms=2400, secs=2)
        self.row("watch.boxes", "watch", "yolo", {"file": "look-down.jpg" if kind == "tilt" else f"look-{kind}.jpg"},
                 after={"file": "look-down-boxed.jpg" if kind == "tilt" else f"look-{kind}-boxed.jpg", "classes": classes,
                        "n": sum(classes.values()), "ms": 900}, ms=900)

    def stop(self, wake: str, k: int, classes: dict, sentence: str, person: bool, label: str, p: float,
             out_of_place: list[str] = (), check: str = "agree", reply: str | None = None) -> None:
        """One stop of the round with a decision (02 ordering: boxes, then the model, then decided, then the post)."""
        self.look("tilt", classes)
        self.row("llm.generate", "watch", "openrouter", {"model": MODEL, "n_messages": 2, "n_images": 2, "max_tokens": 160},
                 after={"model": MODEL, "usage": {"prompt_tokens": 1006, "completion_tokens": 91, "total_tokens": 1097}, "finish_reason": "stop"}, ms=1500, secs=2)
        self.row("vision.check", "watch", "openrouter", {"detector": classes, "file": "look-tilt.jpg"},
                 after={"out_of_place": list(out_of_place), "person": person, "detector_check": check, "agree": check == "agree"},
                 err=sentence, ms=1500)
        self.row("decided", "decide", "stub", {"stop": k, "shift_id": SHIFT, "state_chars": 180 + 7 * k, "threshold": THRESHOLD},
                 before={"labels": LABELS}, after={"label": label, "p": p, "needs_person": p < THRESHOLD, "model": "stub"},
                 err=f"stub: {label}; eyes {'agree' if check == 'agree' else 'disagree'}", ms=1)
        suffix = " [detector: " + ", ".join(f"{c} x{n}" if n > 1 else c for c, n in classes.items()) + "]" if classes else ""
        self.post(GROUP, f"say:{wake}:{k}", "listen", sentence + suffix, "look-down-boxed.jpg")
        if p < THRESHOLD:   # 02: the "not sure" question with the photo, then the chat's answer through the verdict path
            ask = self.post(GROUP, f"decide:{wake}:{k}", "listen", f"not sure: {label.replace('_', ' ')} at {int(round(p * 100))} percent. what is it?", "look-down-boxed.jpg")
            self.n += 1
            self.row("intruder.verdict", "central", "imessage",
                     {"from": HOUSEMATE, "text": reply, "guid": f"FIX-REPLY-{self.n}", "asked": f"decide:{wake}:{k}",
                      "acked_ms": self.acked(ask, 15), "shift_id": SHIFT, "chat": GROUP}, after={"verdict": "known"})
            self.post(GROUP, f"ok:FIX-REPLY-{self.n}", "listen", "ok, standing down")

    def write(self, name: str) -> Path:
        out = HERE / f"{name}.jsonl"
        out.write_text("".join(json.dumps(r) + "\n" for r in self.rows))
        print(f"{out.relative_to(HERE.parents[2])}: {len(self.rows)} rows")
        return out


def decide() -> None:
    l = Ledger("2026-09-27T01:10:00")
    l.wake("FIX-WAKE-1")
    l.stop("FIX-WAKE-1", 10, {"chair": 2}, "a chair pulled out from the table. nothing on the floor.", False, "clear", 0.8)
    l.stop("FIX-WAKE-1", 22, {"bottle": 1}, "a cup on the floor by the door.", False, "out_of_place", 0.55, ["cup"],
           check="it says bottle but that is a cup", reply="its teris cup, leave it")
    l.stop("FIX-WAKE-1", 31, {}, "the hallway is clear.", False, "clear", 0.8)
    l.post(GROUP, "done:FIX-WAKE-1", "listen", "dog done")
    l.write("decide")


def escalate() -> None:
    l = Ledger("2026-09-27T02:40:00")
    l.row("watch.detect", "watch", "yolo", {"source": "http://127.0.0.1:7788/dog/frame.jpg", "model": "yolo11n.pt", "conf": 0.35},
          before=[], after={"classes": {"person": 1}, "n": 1}, err=[{"name": "person", "conf": 0.81, "xyxy": [612, 140, 790, 520]}], ms=21)
    l.look("level", {"person": 1})
    flag = l.post(ONCALL, "alarm:FIX-2", "escalate", "who dis?!", "look-level-boxed.jpg")
    l.row("intruder.alarm", "central", "wtdd", {"look": "level", "seconds": 5, "ask": True},
          after={"file": "look-level-boxed.jpg", "pitch_deg": -0.4, "posted": flag["state_after"]["rowid"], "asked": True, "classes": {"person": 1}}, ms=6900)
    l.n += 1
    l.row("intruder.verdict", "central", "imessage",
          {"from": HANDLE, "text": "thats the night electrician, standing down", "guid": f"FIX-REPLY-{l.n}", "asked": "alarm:FIX-2",
           "acked_ms": l.acked(flag, 12), "shift_id": SHIFT, "chat": ONCALL}, after={"verdict": "known"})
    l.post(ONCALL, f"ok:FIX-REPLY-{l.n}", "listen", "ok, standing down")
    l.c.tick(3600)
    at = l.c.local()
    l.row("record.signed", "central", "wtdd", {"by": NAME, "at": at, "shift_id": SHIFT}, before={"signed": False, "flags": 1},
          after={"signed": True, "at": at, "shift_id": SHIFT}, ms=2, secs=0)
    l.c.tick(40)
    l.row("record.signed", "central", "wtdd", {"by": NAME, "at": l.c.local(), "shift_id": SHIFT}, before={"signed": True, "flags": 1},
          ok=False, err=f"PermissionError: refused: shift {SHIFT} already signed by {NAME} at {at}", ms=1, secs=0)
    l.write("escalate")


def refuse() -> None:
    l = Ledger("2026-09-27T03:05:00")
    l.wake("FIX-WAKE-3")
    why = "route refused: point 2 at 480,1100 is inside no-go zone nogo-1 (drawn on the map)"
    l.row("route.refused", "field", "map", {"zone": NOGO["name"], "waypoint": [480, 1100], "index": 1, "source": "map",
                                             "path_pts": len(PATH_THROUGH), "shift_id": SHIFT}, ok=False, err=why, source="map")
    l.post(GROUP, "done:FIX-WAKE-3", "listen", f"dog done (couldn't walk the path: ValueError: {why})")
    l.write("refuse")
    m = {"note": "The map wtdd/fixtures/evals/refuse.jsonl's refusal is sourced to (item 11): 04's fixture zone nogo-1 and the "
                 "taught route through it, in house.svg pixel space (0 0 1060 1540). zones[].nogo: true is a no-go zone; "
                 "lighting zones carry no nogo key. Built by wtdd/fixtures/evals/make.py.",
         "zones": [NOGO], "path": PATH_THROUGH}
    (HERE / "refuse-map.json").write_text(json.dumps(m, indent=1) + "\n")
    print(f"{(HERE / 'refuse-map.json').relative_to(HERE.parents[2])}: 1 zone, {len(PATH_THROUGH)} path points")


def correct() -> None:
    l = Ledger("2026-09-27T01:10:00")
    l.wake("FIX-WAKE-4")
    l.stop("FIX-WAKE-4", 10, {"chair": 2, "person": 1}, "someone standing by the trench cover at the far wall.", True, "person", 0.9)
    said = l.rows[-1]
    l.n += 1
    l.row("chat.correction", "central", "imessage",
          {"from": HOUSEMATE, "text": "thats a tarp over the cover, not a person", "guid": f"FIX-REPLY-{l.n}",
           "corrects": {"said": said["args"]["text"], "file": said["args"]["file"], "at": said["ts"]},
           "acked_ms": l.acked(said, 20), "shift_id": SHIFT, "chat": GROUP}, after={"corrections": 1})
    l.post(GROUP, f"fix:FIX-REPLY-{l.n}", "listen", "noted: thats a tarp over the cover, not a person")
    l.post(GROUP, "done:FIX-WAKE-4", "listen", "dog done")
    l.c.tick(3600)   # the next round: the correction is in the next look's prompt (dog_say.corrections)
    l.wake("FIX-WAKE-5")
    l.stop("FIX-WAKE-5", 10, {"chair": 2}, "a tarp over the trench cover at the far wall. nothing else.", False, "clear", 0.8)
    l.post(GROUP, "done:FIX-WAKE-5", "listen", "dog done")
    l.write("correct")


if __name__ == "__main__":
    decide()
    escalate()
    refuse()
    correct()
