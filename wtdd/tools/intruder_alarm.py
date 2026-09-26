"""Stranger in the house: a photo (level by default, the fastest look; tilt or sit if the face is higher), the
detector's boxes on it, and the question "who dis?!" to the castle with the picture (ask=true, the default). The
listener then reads the group's verdict for PENDING_WINDOW_S: "idk" (no idea, dunno, not me, no clue...) means
"STRANGER DANGER!!!" three times and the living room strobing red and blue for N seconds (light_alarm); any other
answer stands it down with "ok". ask=false skips the question and alarms at once. Triggered by python -m wtdd.watch when the intruder watch is armed (GET/POST
/intruder) and a person is in view for a few frames, at most once a minute; or by hand. One intruder.alarm row around
the look, the boxes, the post and the lights; each part has its own rows. Nothing here retries."""
ARGS = {"look": {"type": "string", "default": "level", "doc": "level | tilt | sit"},
        "seconds": {"type": "number", "default": 5},
        "trigger": {"type": "string", "default": None, "doc": "idempotence key of the post; defaults to intruder-<epoch>"},
        "ask": {"type": "boolean", "default": True, "doc": "true = post the photo with 'who dis?!' and wait for the chat's verdict (the listener sounds the alarm on 'idk'); false = alarm now"}}

TEXT = "STRANGER DANGER!!! STRANGER DANGER!!! STRANGER DANGER!!!"
ASK = "who dis?!"
PENDING_WINDOW_S = 120


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
        if ask:   # the question with the photo; the chat's answer decides (wtdd/chat/listen.py pending verdict)
            post = chat_post.run(text=ASK, file=file, trigger=key)
            (ROOT / "pending.json").write_text(json.dumps({"kind": "who_dis", "t": time.time(), "file": file, "seconds": seconds,
                                                           "trigger": key, "classes": (det or {}).get("classes")}))
            out = {"file": file, "pitch_deg": shot.get("pitch_deg"), "detector": det, "post": post, "text": ASK, "pending": True}
        else:
            post = chat_post.run(text=TEXT, file=file, trigger=key)
            lights = light_alarm.run(seconds=seconds)
            out = {"file": file, "pitch_deg": shot.get("pitch_deg"), "detector": det, "post": post, "lights": lights, "text": TEXT}
        r["state_after"] = {"file": file, "pitch_deg": shot.get("pitch_deg"), "posted": post.get("rowid"), "asked": ask, "classes": (det or {}).get("classes")}
        return out
