"""The recipe for item 17's two fixture ledgers, the rows its screenshots and 11's graders read. Every row is labeled
cached=true source="stub" (no fixture row claims to be live). Regenerate with
    python -m wtdd.fixtures.make_ledger_17
(writes both files next to this script, byte for byte the same on every run: fixed timestamps and ids).

ledger-17-remote.jsonl, one stop of a round, shift 2026-09-27: the dog's look at stop 22 (the map's stop two), the
detector's row with nothing boxed (the local stop, before any model), the vision model's sentence ("a floor cover is off
and the opening below it is dark. no one is around.") and its check, then the decided row, then the look's sentence to
the group and the heads-up with the photo to the on-call 1:1 (kind escalate, under decide:<wake guid>:22), then the
person's two replies read typed: "on it" 12 s later on chat.db's clock (reply.decided acknowledged, then intruder.verdict
acknowledged / hold with acked_ms 12000: the question stays open), and "handled, cover is back on" 95 s after the post
(reply.decided handled, intruder.verdict handled / close with closed_ms 95000 and no acked_ms, since a flag has one,
then "ok, closed" to the 1:1).
ledger-17-failed.jsonl, the same stop to the heads-up, then a live reading that failed: reply.decided ok=false, app
openrouter, a ConnectionError planted for the screenshot (said in its response_or_error), then intruder.verdict unread /
stand_down and "couldn't read the reply: ..." to the 1:1.

The typed fields are not typed here: the state is decide.state_for_stop's, the label and p are decide._stub's (the
DEMO_CACHE rules: "opening" in the sentence -> opening 0.9), the action and rule are decide.policy's over the table on
ui/map.json, the heads-up text is decide.heads_up_line's, each reading is decide._reply_stub's with read_reply's action
rule. Row shapes are the take's (docs/evidence/ledger-take-2026-09-13.jsonl) plus 03's fields (shift_id, acked_ms, kind
escalate) and 17's (action, rule, policy_source, reply.decided, the typed verdict). Handles are E.164-shaped stand-ins,
never real ones. Nothing here ran on the dog, the phone or Jev."""
from __future__ import annotations
import json
from pathlib import Path

from .. import decide

HERE = Path(__file__).parent
GROUP = "any;+;00000000000000000000000000000000"   # the housemates' group (fake guid, as the chat tests use)
HANDLE = "+15550002222"                             # the on-call stand-in (item 03's fixture handle)
ONCALL = f"any;-;{HANDLE}"
SHIFT, RUN, WAKE, STOP = "2026-09-27", "fixture-17", "FIX17-W", 22
KEY = f"{WAKE}:{STOP}"
MODEL = "x-ai/grok-4.20"
SAID = "a floor cover is off and the opening below it is dark. no one is around."
FILE = "look-sit.jpg"   # stop 22's look on ui/map.json is "sit"
PLANTED = "ConnectionError: Max retries exceeded with url: /api/v1/systemone (planted for the screenshot)"   # message under listen's 100-char cut


def row(ts, agent, tool, app, args, after=None, before=None, ok=True, err=None, ms=0):
    return {"ts": f"2026-09-27T{ts}", "run_id": RUN, "cached": True, "source": "stub", "step": tool, "agent": agent, "tool": tool,
            "app": app, "args": args, "state_before": before, "state_after": after, "ok": ok, "response_or_error": err, "latency_ms": ms}


def post(ts, guid, name, kind, trigger, text, file, rowid, utc):
    """chat.gate, chat.claim and the confirmed chat.post (read back: rowid and chat.db's UTC ts), as __main__.post writes them."""
    return [row(ts, "central", "chat.gate", "imessage", {"guid": guid}, {"guid": guid, "name": name}, ms=4),
            row(ts, "central", "chat.claim", "memory", {"trigger": trigger}, {"trigger": trigger, "claimed": True}, ms=1),
            row(ts, "central", "chat.post", "imessage", {"guid": guid, "kind": kind, "trigger": trigger, "text": text, "file": file,
                                                          "shift_id": SHIFT},
                {"guid": f"FIX17-POST-{rowid}", "rowid": rowid, "ts": utc}, {"max_rowid": rowid - 1}, ms=3400)]


def stop() -> tuple[list[dict], str]:
    """The stop up to the heads-up; returns (rows, the heads-up text)."""
    seen = {"text": SAID, "out_of_place": ["cover"], "detector_check": "agree"}
    det = {"classes": {}, "boxes": []}
    state = decide.state_for_stop(decide.stop_name(STOP), seen, det, None)
    labels, (table, source), thr = decide.labels(), decide._table(), decide.threshold()
    label, p, model, raw = decide._stub(state, labels)
    pol = decide.policy(label, p, thr, table)
    d = {"label": label, "p": round(p, 3), "needs_person": round(p, 3) < thr, "model": model, "action": pol["action"]}
    assert (d["action"], source) == ("escalate", "map"), (d, source)   # the fixture is the escalate beat, on the map's table
    heads = decide.heads_up_line(d, STOP)
    said = {"say": SAID, "person": False, "out_of_place": ["cover"], "pick": 2, "why": "", "detector_check": "agree"}
    return [
        row("21:14:00", "dog", "dog.look", "unitree", {"kind": "sit"},
            {"text": "here's what i see", "file": FILE, "kind": "sit", "pitch_deg": 48.0, "fired": True, "attempts": 1,
             "file_down": None, "pitch_down_deg": None}, ms=2410),
        row("21:14:01", "watch", "watch.boxes", "yolo", {"file": FILE}, {"file": "look-sit-boxed.jpg", "classes": {}, "n": 0, "ms": 412}, ms=412),
        row("21:14:03", "watch", "llm.generate", "openrouter", {"model": MODEL, "n_messages": 2, "n_images": 1, "max_tokens": 160},
            {"model": MODEL, "finish": "stop", "chars": len(json.dumps(said)), "tool_calls": []}, err=json.dumps(said), ms=2104),
        row("21:14:03", "watch", "vision.check", "openrouter", {"detector": {}, "file": FILE},
            {"out_of_place": ["cover"], "person": False, "detector_check": "agree", "agree": True}, err=SAID, ms=2104),
        row("21:14:03", "decide", "decided", "stub",
            {"stop": STOP, "shift_id": SHIFT, "state_chars": len(state), "threshold": thr, "rule": pol["rule"], "policy_source": source},
            d, {"labels": labels}, err=raw, ms=1),
        *post("21:14:04", GROUP, "wtdd test", "listen", f"say:{KEY}", SAID, FILE, 61001, "2026-09-28 04:14:07"),
        *post("21:14:08", ONCALL, "", "escalate", f"decide:{KEY}", heads, FILE, 61002, "2026-09-28 04:14:12"),
    ], heads


def reading(ts, heads, text, guid, ok=True):
    """reply.decided as read_reply writes it (the stub's reading, or a planted live failure)."""
    args = {"question": heads, "text": text, "shift_id": SHIFT, "threshold": decide.reply_threshold(), "model": "stub" if ok else None,
            "trigger": f"decide:{KEY}", "chat": ONCALL, "guid": guid, "from": HANDLE}
    before = {"meanings": decide.MEANINGS, "labels": decide.labels() + ["not_said"]}
    if not ok:
        return row(ts, "central", "reply.decided", "openrouter", args, None, before, ok=False, err=PLANTED, ms=1203)
    meaning, p, named, p_named, raw = decide._reply_stub(text)
    action = "reask" if meaning == "unclear" or round(p, 3) < args["threshold"] else decide.ACTION[meaning]
    return row(ts, "central", "reply.decided", "stub", args,
               {"meaning": meaning, "p": round(p, 3), "named": named, "p_named": round(p_named, 3), "action": action}, before, err=raw, ms=2)


def verdict(ts, text, guid, ms, after):
    """intruder.verdict as listen.verdict() writes it: 03's args (ms is {"acked_ms": n}, or {"closed_ms": n} on the close
    after a hold, since a flag has one acked_ms), 17's typed state_after."""
    return row(ts, "central", "intruder.verdict", "imessage",
               {"from": HANDLE, "text": text, "guid": guid, "asked": f"decide:{KEY}", **ms, "shift_id": SHIFT, "chat": ONCALL},
               after)


def remote() -> list[dict]:
    rows, heads = stop()
    on_it, done = reading("21:14:24", heads, "on it", "FIX17-R1"), reading("21:15:47", heads, "handled, cover is back on", "FIX17-R2")
    assert (on_it["state_after"]["action"], done["state_after"]["action"]) == ("hold", "close"), (on_it, done)
    return rows + [
        on_it, verdict("21:14:24", "on it", "FIX17-R1", {"acked_ms": 12000},
                       {"verdict": "acknowledged", "meaning": "acknowledged", "p": on_it["state_after"]["p"], "action": "hold"}),
        done, verdict("21:15:47", "handled, cover is back on", "FIX17-R2", {"closed_ms": 95000},
                      {"verdict": "handled", "meaning": "handled", "p": done["state_after"]["p"], "action": "close"}),
        *post("21:15:48", ONCALL, "", "listen", "ok:FIX17-R2", "ok, closed", None, 61005, "2026-09-28 04:15:51"),
    ]


def failed() -> list[dict]:
    rows, heads = stop()
    return rows + [
        reading("21:14:25", heads, "on it", "FIX17-R1", ok=False),
        verdict("21:14:25", "on it", "FIX17-R1", {"acked_ms": 12000}, {"verdict": "unread", "meaning": None, "p": None, "action": "stand_down"}),
        *post("21:14:26", ONCALL, "", "listen", "unread:FIX17-R1", f"couldn't read the reply: {PLANTED}", None, 61004,
              "2026-09-28 04:14:29"),
    ]


def main() -> int:
    for name, rows in (("ledger-17-remote.jsonl", remote()), ("ledger-17-failed.jsonl", failed())):
        (HERE / name).write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"{HERE / name}: {len(rows)} rows, every one cached=true source=stub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
