"""Stranger in the house: a photo (level by default, the fastest look; tilt or sit if the face is higher), the
detector's boxes on it, and the question "who dis?!" with the picture to the on-call chat, oncall.person(): the
person's 1:1 (item 03: WTDD_ON_CALL_NAME / WTDD_ON_CALL_HANDLE), or the chat WTDD_ON_CALL_GUID names, the group itself
for the demo (S10). ask=true is the default; nothing configured = this tool fails loud, nothing posted. The listener
reads that chat's answer within its PENDING_WINDOW_S, typed by decide.read_reply (wtdd/chat/listen.py verdict()):
stranger means "STRANGER DANGER!!!" three times and the living room strobing red and blue for N seconds (light_alarm);
standing_down posts "ok, standing down", handled "ok, closed", acknowledged keeps it open for handled, and an unclear
reply is asked once more ("do you know them? yes or no"). ask=false skips the question and alarms at once. Triggered by python -m wtdd.watch when the intruder watch is armed (GET/POST
/intruder) and a person is in view for a few frames, at most once a minute; or by hand. One intruder.alarm row around
the look, the boxes, the post and the lights; each part has its own rows. Nothing here retries."""
ARGS = {"look": {"type": "string", "default": "level", "doc": "level | tilt | sit"},
        "seconds": {"type": "number", "default": 5},
        "trigger": {"type": "string", "default": None, "doc": "idempotence key of the post; defaults to intruder-<epoch>"},
        "ask": {"type": "boolean", "default": True, "doc": "true = post the photo with 'who dis?!' and wait for the chat's verdict (the listener sounds the alarm on 'idk'); false = alarm now"}}

TEXT = "STRANGER DANGER!!! STRANGER DANGER!!! STRANGER DANGER!!!"
ASK = "who dis?!"


def run(look="level", seconds=5, trigger=None, ask=True):
    import json
    import time
    from ..commands import look as _look
    from ..config import ROOT
    from ..ledger import step
    from . import chat_post, light_alarm
    from .dog_say import boxed
    key = trigger or f"intruder-{int(time.time())}"
    with step("central", "intruder.alarm", "wtdd", {"look": look, "seconds": seconds, "ask": ask}) as r:
        shot = _look(look)
        file, det = shot["file"], None
        try:
            det = boxed(file)
            file = det["file"]
        except Exception as e:  # noqa: BLE001  (the plain photo is posted; the failure is on its own watch.boxes row)
            det = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
        if ask:   # the question with the photo, to the on-call person (a flag, kind escalate); their answer decides (listen.py verdict)
            from ..chat.__main__ import post as gated_post
            from ..chat.oncall import person
            to = person()["guid"]
            post = gated_post(to, key, "escalate", ASK, file)
            (ROOT / "pending.json").write_text(json.dumps({"kind": "who_dis", "t": time.time(), "file": file, "seconds": seconds,
                                                           "trigger": key, "chat": to, "classes": (det or {}).get("classes")}))
            out = {"file": file, "pitch_deg": shot.get("pitch_deg"), "detector": det, "post": post, "text": ASK, "pending": True}
        else:
            post = chat_post.run(text=TEXT, file=file, trigger=key)
            lights = light_alarm.run(seconds=seconds)
            out = {"file": file, "pitch_deg": shot.get("pitch_deg"), "detector": det, "post": post, "lights": lights, "text": TEXT}
        r["state_after"] = {"file": file, "pitch_deg": shot.get("pitch_deg"), "posted": post.get("rowid"), "asked": ask, "classes": (det or {}).get("classes")}
        return out
