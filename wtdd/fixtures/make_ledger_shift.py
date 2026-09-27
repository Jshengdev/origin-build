"""The recipe for wtdd/fixtures/ledger_shift.jsonl: two shifts as the ledger holds them after item 03, every row
labeled cached=true source="stub" (no fixture row claims to be live). Regenerate with
    python -m wtdd.fixtures.make_ledger_shift
(writes the file next to this script; wtdd.test_record checks the committed file matches rows()).

Shift 2026-09-25, unsigned: a wake, the picture and "dog doin", the map's three stops [10, 22, 23] as they ran
(10: a nod, a cup and a tarp, no person; 22: a sit, a person, flagged "who dis?!" with the photo to the on-call 1:1,
answered "thats my friend" 14 s later on chat.db's clock; 23: the nod refused by the dog, code 401001, posted as its
error), the follow and the walk rows, "dog done", a housemate's correction nine minutes later ("thats a tarp not a
cup", acked 556 s after the post it corrects), and one refused claim (never twice). Shift 2026-09-26, signed: the
same round with the flag at stop 22 unanswered (the round held, then moved on: no verdict row), signed by the on-call
stand-in the next morning, then a second signature refused with its own ok=false row. Between them, a light write at
noon, unstamped, falls into the unsigned shift's open window (its window runs to the next shift's opener: the reason
an unsigned shift must be signed). Only the two calibrations are in no shift: one hours before the first wake, one
after the signature. Row shapes are the take's (docs/evidence/ledger-take-2026-09-13.jsonl) plus 03's fields
(shift_id on every post, reply and signature; acked_ms; kind "escalate"); handles are E.164-shaped stand-ins, never
real ones."""
from __future__ import annotations
import json
from pathlib import Path

OUT = Path(__file__).with_name("ledger_shift.jsonl")
GROUP = "any;+;00000000000000000000000000000000"   # the housemates' group (fake guid, as the chat tests use)
ONCALL = "any;-;+15550002222"                         # the on-call person's 1:1 (item 03), a stand-in handle
HOUSEMATE, PERSON, NAME = "+15550001111", "+15550002222", "Sam Stand-in"
MODEL = "x-ai/grok-4.20"


def row(ts, run, agent, tool, app, args, after=None, before=None, ok=True, err=None, ms=0):
    return {"ts": ts, "run_id": run, "cached": True, "source": "stub", "step": tool, "agent": agent, "tool": tool, "app": app,
            "args": args, "state_before": before, "state_after": after, "ok": ok, "response_or_error": err, "latency_ms": ms}


def dog_state(n, pos):   # the shape of a Go2 state sample as dog.* rows carry it (values are stand-ins)
    return {"mode": 0, "gait_type": 0, "progress": 0, "position": pos, "velocity": [0.0, 0.0, 0.0], "yaw_speed": 0.0,
            "body_height": 0.31, "range_obstacle": [0, 0, 0, 0], "rpy": [0.0, -0.07, 1.51], "n": n, "hz": 20.0, "age_ms": 12}


def post(ts, run, guid, kind, trigger, text, file, shift, rowid, ts_utc, caption=False):
    after = {"guid": f"POST-{rowid}", "rowid": rowid, "ts": ts_utc}
    if caption:
        after["caption"] = {"guid": f"POST-{rowid}c", "rowid": rowid + 1, "ts": ts_utc}
    return row(ts, run, "central", "chat.post", "imessage",
               {"guid": guid, "kind": kind, "trigger": trigger, "text": text, "file": file, "shift_id": shift},
               after, {"max_rowid": rowid - 1}, ms=3400)


def claim(ts, run, trigger, ok=True):
    return row(ts, run, "central", "chat.claim", "memory", {"trigger": trigger},
               {"trigger": trigger, "claimed": True} if ok else None, ok=ok,
               err=None if ok else f"PermissionError: gate refused: trigger {trigger} already claimed", ms=1)


def gate(ts, run, guid, name):
    return row(ts, run, "central", "chat.gate", "imessage", {"guid": guid}, {"guid": guid, "name": name}, ms=4)


def look(ts, run, kind, n, ok=True):
    before = dog_state(n, [-0.86, 4.12, 0.29])
    if not ok:
        return row(ts, run, "dog", "dog.look", "unitree", {"kind": kind}, None, before, ok=False,
                   err="RuntimeError: Pose refused by the dog: code=401001", ms=2100)
    tilt = kind == "tilt"
    return row(ts, run, "dog", "dog.look", "unitree", {"kind": kind},
               {"text": "here's what i see", "file": f"look-{kind}.jpg", "kind": kind, "pitch_deg": -15.1 if tilt else 12.3,
                "fired": True, "attempts": 1, "file_down": "look-down.jpg" if tilt else None, "pitch_down_deg": -14.8 if tilt else None},
               before, ms=4200)


def report(ts, run, wake, stop, shift, kind, classes, sentence, person, out_of_place, check, agree, rowid, ts_utc):
    """What the chat process writes after a stop's look: the detector, the model, the check, the claim, the post."""
    src = "look-down.jpg" if kind == "tilt" else f"look-{kind}.jpg"
    boxed = src.replace(".jpg", "-boxed.jpg")
    return [
        row(ts[0], run, "watch", "watch.boxes", "yolo", {"file": src}, {"file": boxed, "classes": classes, "n": sum(classes.values()), "ms": 3100}, ms=3100),
        row(ts[1], run, "watch", "llm.generate", "openrouter", {"model": MODEL, "n_messages": 2, "n_images": 2 if kind == "tilt" else 1, "max_tokens": 160},
            {"model": MODEL, "usage": {"prompt_tokens": 1006, "completion_tokens": 80, "total_tokens": 1086}, "finish": "stop", "chars": 210, "tool_calls": []},
            err=json.dumps({"sentence": sentence, "person": person, "out_of_place": out_of_place, "send": "down" if kind == "tilt" else "level", "detector_check": check}), ms=1900),
        row(ts[1], run, "watch", "vision.check", "openrouter", {"detector": classes, "file": f"look-{kind}.jpg"},
            {"out_of_place": out_of_place, "person": person, "detector_check": check, "agree": agree}, err=sentence, ms=1900),
        claim(ts[1], run, f"say:{wake}:{stop}"),
        post(ts[2], run, GROUP, "listen", f"say:{wake}:{stop}", sentence, boxed, shift, rowid, ts_utc, caption=True),
    ]


def flag(ts, run, wake, stop, shift, file, rowid, ts_utc):
    """The flag to the on-call person: the gate names them, the claim, the escalate post with the photo."""
    return [gate(ts[0], run, ONCALL, NAME), claim(ts[0], run, f"alarm:{wake}:{stop}"),
            post(ts[1], run, ONCALL, "escalate", f"alarm:{wake}:{stop}", "who dis?!", file, shift, rowid, ts_utc, caption=True)]


def walk(ts, chat, dog, stops, done, seconds):
    return [
        row(ts[0], dog, "dog", "dog.follow", "map", {"n": 48, "start": 0, "stops": stops, "reach_px": 30.0, "avoid": True},
            {"reached": list(range(48)), "of": 48, "seconds": seconds, "map": {"p": [566, 1132], "heading_deg": -92.0}},
            {"p": [449, 491], "heading_deg": 88.5}, ms=int(seconds * 1000)),
        row(ts[1], chat, "field", "field.walk", "map",
            {"path_pts": 48, "lights": 5, "radius": 350, "falloff": 1.6, "speed": 60.0, "seconds": 20.0, "stops": stops, "dry": False, "source": "dog", "follower": True},
            {"seconds": seconds + 0.6, "dark_ms": 1400, "writes": 70, "errors": 0, "rooms": ["living room", "dining room", "kitchen"], "stops": done,
             "latency_ms": {"Hue Iris 2": 845, "Go table lamp 1": 822, "special": 892, "sticky canbo": 937, "LED strip": 650},
             "lights": ["Hue Iris 2", "Go table lamp 1", "special", "sticky canbo", "LED strip"], "source": "dog", "follower": True}, ms=int(seconds * 1000 + 600)),
    ]


def wake(ts, run, guid_msg, sender):
    return [row(ts, run, "central", "chat.wake", "imessage", {"from": sender, "text": "what the dog doin", "guid": guid_msg, "phrase": "what the dog doin", "score": 1.0},
                {"armed": True, "armed_by": sender}),
            gate(ts, run, GROUP, "wtdd test"), claim(ts, run, f"fire:{guid_msg}")]


def calibrate(ts, run):
    return row(ts, run, "dog", "dog.calibrate", "map", {"p": [442, 498], "heading_deg": -126.6}, {"cal": {"odom": [-0.25, 2.52, 0.01], "map": [442.0, 498.0], "heading": -2.21, "at": ts},
                                                                                                 "map": {"p": [442, 498], "heading_deg": -126.6}}, {"p": [-17, 554], "heading_deg": -126.6})


SAID_10 = "a cup on the floor by the chairs & a tarp over the pallet. [detector: chair x2, cup]"
SAID_22 = "someone standing by the scaffold, hard hat on. [detector: person]"
SAID_23 = "a coil of cable across the walkway. [detector: chair]"


def rows() -> list[dict]:
    A, B = "2026-09-25", "2026-09-26"
    d = "2026-09-25T"
    out = [calibrate(d + "18:00:00", "fixA-dog")]                                                  # no shift: hours before the wake
    out += wake(d + "22:00:00", "fixA-chat", "WAKE-A", HOUSEMATE)
    out += [post(d + "22:00:04", "fixA-chat", GROUP, "listen", "fire:WAKE-A", None, "this-is-fine.jpg", A, 70001, "2026-09-26 05:00:03"),
            claim(d + "22:00:05", "fixA-chat", "doin:WAKE-A"),
            post(d + "22:00:06", "fixA-chat", GROUP, "listen", "doin:WAKE-A", "dog doin", None, A, 70002, "2026-09-26 05:00:06"),
            look(d + "22:00:40", "fixA-dog", "tilt", 2718)]
    out += report((d + "22:00:44", d + "22:00:46", d + "22:00:50"), "fixA-chat", "WAKE-A", 10, A, "tilt", {"chair": 2, "cup": 1}, SAID_10, False,
                  ["cup", "tarp"], "it says chair x2 and cup and that is right", True, 70003, "2026-09-26 05:00:49")
    out += [look(d + "22:01:20", "fixA-dog", "sit", 3410)]
    out += report((d + "22:01:24", d + "22:01:26", d + "22:01:30"), "fixA-chat", "WAKE-A", 22, A, "sit", {"person": 1}, SAID_22, True,
                  [], "it says person and that is right", True, 70005, "2026-09-26 05:01:29")
    out += flag((d + "22:01:30", d + "22:01:34"), "fixA-chat", "WAKE-A", 22, A, "look-sit-boxed.jpg", 70007, "2026-09-26 05:01:33")
    out += [row(d + "22:01:47", "fixA-chat", "central", "intruder.verdict", "imessage",
                {"from": PERSON, "text": "thats my friend, standing down", "guid": "REPLY-A1", "asked": "alarm:WAKE-A:22", "acked_ms": 14000, "shift_id": A, "chat": ONCALL},
                {"verdict": "known"}),
            claim(d + "22:01:47", "fixA-chat", "ok:REPLY-A1"),
            post(d + "22:01:50", "fixA-chat", ONCALL, "listen", "ok:REPLY-A1", "ok, standing down", None, A, 70009, "2026-09-26 05:01:49"),
            look(d + "22:02:10", "fixA-dog", "tilt", 4102, ok=False),
            claim(d + "22:02:10", "fixA-chat", "say:WAKE-A:23"),
            post(d + "22:02:13", "fixA-chat", GROUP, "listen", "say:WAKE-A:23", "couldn't look: RuntimeError: Pose refused by the dog: code=401001", None, A, 70010, "2026-09-26 05:02:12")]
    out += walk((d + "22:02:20", d + "22:02:21"), "fixA-chat", "fixA-dog", [10, 22, 23], [10, 22, 23], 130.4)
    out += [claim(d + "22:02:21", "fixA-chat", "done:WAKE-A"),
            post(d + "22:02:24", "fixA-chat", GROUP, "listen", "done:WAKE-A", "dog done (1 look failed: stop 23: Pose refused by the dog: code=401001)", None, A, 70011, "2026-09-26 05:02:23"),
            row(d + "22:10:05", "fixA-chat", "central", "chat.correction", "imessage",
                {"from": HOUSEMATE, "text": "thats a tarp not a cup", "guid": "REPLY-A2", "corrects": {"said": SAID_10, "file": "look-down-boxed.jpg", "at": d + "22:00:50"},
                 "acked_ms": 556000, "shift_id": A, "chat": GROUP}, {"corrections": 1}),
            claim(d + "22:10:05", "fixA-chat", "fix:REPLY-A2"),
            post(d + "22:10:08", "fixA-chat", GROUP, "listen", "fix:REPLY-A2", "noted: thats a tarp not a cup", None, A, 70012, "2026-09-26 05:10:07"),
            claim(d + "22:10:30", "fixA-chat", "fix:REPLY-A2", ok=False),                          # the same message read again: refused, never twice
            row("2026-09-26T12:00:00", "fixX", "lights", "lights.set", "hue", {"id": "1e53ff31-2dcc-496a-ad93-3cc25eb50bad", "on": {"on": True}},
                {"on": True, "brightness": 100, "xy": [0.4832, 0.4231], "signal": None}, {"on": False, "brightness": 100, "xy": [0.4832, 0.4231], "signal": None},
                err='{"data":[{"rid":"1e53ff31-2dcc-496a-ad93-3cc25eb50bad","rtype":"light"}],"errors":[]}', ms=817)]   # noon, no shift of its own
    d = "2026-09-26T"
    out += wake(d + "22:00:00", "fixB-chat", "WAKE-B", HOUSEMATE)
    out += [post(d + "22:00:04", "fixB-chat", GROUP, "listen", "fire:WAKE-B", None, "this-is-fine.jpg", B, 80001, "2026-09-27 05:00:03"),
            claim(d + "22:00:05", "fixB-chat", "doin:WAKE-B"),
            post(d + "22:00:06", "fixB-chat", GROUP, "listen", "doin:WAKE-B", "dog doin", None, B, 80002, "2026-09-27 05:00:06"),
            look(d + "22:00:40", "fixB-dog", "tilt", 5001)]
    out += report((d + "22:00:44", d + "22:00:46", d + "22:00:50"), "fixB-chat", "WAKE-B", 10, B, "tilt", {"chair": 2}, "two chairs by the wall, nothing on the floor. [detector: chair x2]", False,
                  [], "it says chair x2 and that is right", True, 80003, "2026-09-27 05:00:49")
    out += [look(d + "22:01:20", "fixB-dog", "sit", 5610)]
    out += report((d + "22:01:24", d + "22:01:26", d + "22:01:30"), "fixB-chat", "WAKE-B", 22, B, "sit", {"person": 1}, SAID_22, True,
                  [], "it says person and that is right", True, 80005, "2026-09-27 05:01:29")
    out += flag((d + "22:01:30", d + "22:01:34"), "fixB-chat", "WAKE-B", 22, B, "look-sit-boxed.jpg", 80007, "2026-09-27 05:01:33")
    out += [look(d + "22:02:30", "fixB-dog", "tilt", 6220)]                                        # no verdict came in the hold: the round moved on
    out += report((d + "22:02:34", d + "22:02:36", d + "22:02:40"), "fixB-chat", "WAKE-B", 23, B, "tilt", {"chair": 1}, SAID_23, False,
                  ["cable"], "it says chair but that is really a coil of cable", False, 80009, "2026-09-27 05:02:39")
    out += walk((d + "22:02:50", d + "22:02:51"), "fixB-chat", "fixB-dog", [10, 22, 23], [10, 22, 23], 160.8)
    out += [claim(d + "22:02:51", "fixB-chat", "done:WAKE-B"),
            post(d + "22:02:54", "fixB-chat", GROUP, "listen", "done:WAKE-B", "dog done", None, B, 80011, "2026-09-27 05:02:53"),
            row("2026-09-27T06:05:00", "fixB-sign", "central", "record.signed", "wtdd", {"by": NAME, "at": "2026-09-27T06:05:00", "shift_id": B},
                {"signed": True, "at": "2026-09-27T06:05:00", "shift_id": B}, {"signed": False, "flags": 1}, ms=2),
            row("2026-09-27T06:06:00", "fixB-sign2", "central", "record.signed", "wtdd", {"by": NAME, "at": "2026-09-27T06:06:00", "shift_id": B},
                None, {"signed": True, "flags": 1}, ok=False, err=f"PermissionError: refused: shift {B} already signed by {NAME} at 2026-09-27T06:05:00", ms=1),
            calibrate("2026-09-27T09:00:00", "fixC-dog")]                                           # after the signature: no shift
    return out


def main() -> int:
    OUT.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows()))
    print(f"{OUT}: {len(rows())} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
