"""Look and say: the dog nods and photographs (dog_look, tilt by default), the frame goes to the vision model, and the
one sentence plus the photo are posted to the castle behind the gate and the never-twice claim. Returns the look's
fields (file_up, file_down, pitch_deg, pitch_down_deg, fired, attempts), text, person, out_of_place, pick (1 = the
floor picture, 2 = the room), why, file (the picked one, boxed by the detector when it ran, the one posted), detector
({file, classes, n, ms} or {error}), baseline, model, vision_ms and the confirmed post row. The caption gets a
"[detector: cup, chair x2]" suffix when the detector saw something. look_and_see() is the half without the post: the chat listener calls it and posts under the wake message's
guid (say:<guid>), and sounds light_alarm when person is true.

  python -m wtdd dog_say                          nod, look, say, post (trigger defaults to say-<epoch>)
  python -m wtdd dog_say look=sit trigger=k       the sit look; trigger is the idempotence key of the post
  python -m wtdd dog_say baseline=true stop=2     capture this look at map stop 2 as its tidy reference (DEMO_CACHE below), no post
Vision: OPENROUTER_VISION_MODEL (x-ai/grok-4.20, about 1 s on a dog frame), the JSON prompt below, the frame (and the
tidy baseline when one exists) downscaled to 640 px wide and sent as base64 JPEG. The reply must be JSON with say,
person and out_of_place, or the call raises (no canned sentence, CLAUDE.md section 2); say over 140 characters is cut
at a word with a WARN. One llm.generate row (agent watch) per look. A tilt that did not fire (fired=False, IMU-checked
in wtdd/dog/session.py) still yields a real frame and a real sentence; the result says so."""
ARGS = {"look": {"type": "string", "default": "tilt", "doc": "tilt | level | sit"},
        "trigger": {"type": "string", "default": None, "doc": "idempotence key of the post; defaults to say-<epoch>"},
        "baseline": {"type": "boolean", "default": False, "doc": "true = capture this look as the tidy reference, no post"},
        "stop": {"type": "number", "default": None, "doc": "map stop index the dog is at (picks that stop's tidy baseline)"}}

SYSTEM = (
    "You are a robot dog's eyes on a night round of a shared house. Floor-level camera. You get two pictures from one nod: "
    "1 = looking down at the floor, 2 = looking up at the room. Reply with JSON only: "
    '{"say": <one casual sentence, under 200 characters, for the housemates\' group chat: what you see and anything out of '
    "place (cups, clothes, trash, bags on the floor); if a sock or clothes are on the floor ask whose they are; no "
    'adjectives, no dashes, no names of people, say "someone" if a person is in view>, '
    '"person": <true if any person is in view in either picture, else false>, '
    '"out_of_place": <a list of short names of the things out of place, [] if none>, '
    '"pick": <1 or 2: the picture to send to the group, the one that shows the thing out of place or the person; 2 if nothing is>, '
    '"why": <under 60 characters: why that picture>, '
    '"detector_check": <"agree" if the detector labels given to you fit what you see, else one casual clause naming the '
    'mislabeled thing as what it really is, in the form "it says <label> but that is really <what you see>">}. '
    "If an image labeled tidy is given, it is the same spot when it was tidy: report only what is new or moved since. "
    "Say only what is in the pictures: if there are no socks, no clothes, no cups, do not mention them. When something "
    "that is there clearly belongs to someone (clothes, a sock, a cup left out), guess an owner by first name from the "
    "housemates list if one is given, casually ('probably <name>'s'), and fold the detector_check clause into say when "
    "it is not 'agree'. A cup, mug, glass or bottle left out gets one witty line of public shaming: what kind it is, who "
    "probably drank from it, and what they should do with it now. Socks or clothes on the floor: ask whose they are."
)
MAX_SAY = 200   # the witty lines run longer than a report; over this the sentence is cut at a word
MAX_CHARS = 140
WIDTH = 640
PICTURES = "~/Pictures/wtdd"


def _part(file: str) -> dict:
    import base64
    import io
    from PIL import Image
    img = Image.open(file).convert("RGB")
    img.thumbnail((WIDTH, WIDTH))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}


def see(file: str, baseline: str | None = None, file_down: str | None = None, labels: dict | None = None) -> dict:
    """The room frame at `file`, the floor frame at `file_down` (if the nod gave one) and the tidy baseline (if any) to
    the vision model. Returns {text, person, out_of_place, pick (1 floor | 2 room), why, model, ms}; raises on an empty
    or malformed reply (no canned sentence)."""
    import json
    import time
    from ..ledger import log
    from ..llm import generate
    content = []
    if baseline:
        content += [{"type": "text", "text": "this is the spot when it was tidy:"}, _part(baseline)]
    if file_down:
        content += [{"type": "text", "text": "picture 1, looking down at the floor:"}, _part(file_down)]
    content += [{"type": "text", "text": ("picture 2, looking up at the room" if file_down else "this is now") + ". what do you see?"}, _part(file)]
    system = SYSTEM
    from .. import config
    names = config.maybe("WTDD_HOUSEMATE_NAMES")
    if names:
        system += f" The housemates are: {names}."
    if labels:   # the detector's COCO labels on the floor picture, for the second opinion (it cannot say 'sock')
        system += " The object detector (80 COCO classes, it cannot say sock or clothes) labeled the floor picture: " + \
                  ", ".join(f"{k} x{v}" for k, v in labels.items()) + ". Check them against what you see."
    fixes = corrections()
    if fixes:   # what the housemates said the dog got wrong before: true for those pictures; a hint, not a script, for this one
        system += (" The housemates corrected earlier pictures (they were right about those): " + " | ".join(fixes) +
                   ". Use a correction only if the same thing is in view now; never report something you do not see.")
    t0 = time.perf_counter()
    out = generate("watch", [{"role": "system", "content": system}, {"role": "user", "content": content}],
                   max_tokens=160, temperature=0.3, response_format={"type": "json_object"})
    raw = out["text"].strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        d = json.loads(raw)
        text = " ".join(str(d["say"]).split())
        person = bool(d["person"])
        items = [str(x) for x in d.get("out_of_place") or []]
        pick = int(d.get("pick") or 2) if file_down else 2
        if pick not in (1, 2):
            raise ValueError(f"pick must be 1 or 2, got {pick!r}")
        why = " ".join(str(d.get("why") or "").split())[:80]
        check = " ".join(str(d.get("detector_check") or "agree").split())[:140]
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"vision model reply is not the expected JSON ({type(e).__name__}: {e}): {raw[:160]!r}") from None
    if not text:
        raise RuntimeError(f"vision model returned an empty sentence (model={out['model']})")
    if len(text) > MAX_SAY:
        log("watch", f"WARN sentence {len(text)} chars, cut to {MAX_SAY}")
        text = text[:MAX_SAY].rsplit(" ", 1)[0]
    ms = round((time.perf_counter() - t0) * 1000)
    log("watch", f"saw: {text}", person=person, out_of_place=len(items), pick=pick, why=why, check=check, baseline=bool(baseline), model=out["model"], ms=ms)
    if labels is not None:   # the second opinion as its own receipt: what the detector said vs what the model saw
        from ..ledger import append
        append({"step": "vision.check", "agent": "watch", "tool": "vision.check", "app": "openrouter", "ok": True,
                "args": {"detector": labels, "file": file.split("/")[-1]},
                "state_before": None, "state_after": {"out_of_place": items, "person": person, "detector_check": check, "agree": check.lower() == "agree"},
                "response_or_error": text, "latency_ms": ms})
    return {"text": text, "person": person, "out_of_place": items, "pick": pick, "why": why, "detector_check": check, "model": out["model"], "ms": ms}


def corrections(n: int = 5) -> list[str]:
    """The housemates' last n corrections from <repo>/state.json (wtdd/chat/listen.py writes them), as prompt lines."""
    import json
    from ..config import ROOT
    f = ROOT / "state.json"
    if not f.exists():
        return []
    out = []
    for c in (json.loads(f.read_text()).get("corrections") or [])[-n:]:
        said = (c.get("corrects") or {}).get("said") or ""
        out.append(f'the dog said "{said[:80]}" and a housemate replied "{c.get("text", "")[:80]}"')
    return out


def tidy_path(look: str, stop: int | None = None) -> str:
    import os
    return os.path.expanduser(f"{PICTURES}/tidy-{look}" + (f"-stop{stop}" if stop is not None else "") + ".jpg")


def boxed(file: str) -> dict:
    """The detector (YOLO11n, wtdd/watch.py) over the exact frame, in its own process: returns {file (the boxed copy),
    classes, n, ms}. A failure raises; the caller decides (dog_say posts the plain frame and records the error)."""
    import json
    import subprocess
    import sys
    import time
    from ..config import ROOT
    from ..ledger import log, step
    out = file.rsplit(".", 1)[0] + "-boxed.jpg"
    t0 = time.perf_counter()
    with step("watch", "watch.boxes", "yolo", {"file": file.split("/")[-1]}) as r:
        pr = subprocess.run([sys.executable, "-m", "wtdd.watch", "--source", file, "--once", "--out", out],
                            capture_output=True, text=True, timeout=90, cwd=ROOT)
        if pr.returncode != 0 or not pr.stdout.strip():
            raise RuntimeError(f"detector rc={pr.returncode}: {pr.stderr.strip()[-200:]}")
        d = json.loads(pr.stdout.strip().splitlines()[-1])
        res = {"file": d["file"], "classes": d["classes"], "n": d["n"], "ms": round((time.perf_counter() - t0) * 1000)}
        r["state_after"] = res
    log("watch", "boxes", n=res["n"], classes=res["classes"], ms=res["ms"])
    return res


def look_and_see(look: str = "tilt", stop: int | None = None) -> dict:
    """The look (through the API while it owns the dog), then the sentence. Posts nothing. `stop` is the map stop index
    the dog is at, which picks that stop's tidy baseline when one was captured."""
    import os
    from ..commands import look as _look
    shot = _look(look)
    # DEMO_CACHE: tidy baseline frame (~/Pictures/wtdd/tidy-<look>[-stop<i>].jpg). What: the same look at the same stop,
    # captured when the spot was tidy, so the model reports only what changed. Why: a tripod and a bin that always sit
    # there are not "out of place". Live: `python -m wtdd dog_say baseline=true stop=<i>` recaptures it with the real dog
    # at that stop; delete the file to run without one (the model then judges the frame on its own, which is logged).
    tidy = tidy_path(look, stop)
    has = os.path.isfile(tidy)
    floor = shot.get("file_down") or shot["file"]
    try:   # the detector first, on the floor picture, so the model gets its labels and can second-guess them
        det = boxed(floor)
    except Exception as e:  # noqa: BLE001  (its watch.boxes row has ok=False; the model then sees no labels)
        det = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    seen = see(shot["file"], tidy if has else None, shot.get("file_down"), labels=det.get("classes") if "classes" in det else None)
    files = {1: shot.get("file_down"), 2: shot["file"]}
    picked = files[seen["pick"]] or shot["file"]
    text = seen["text"]
    if "classes" in det:
        try:
            if picked != floor:   # the room picture was picked: box that one too
                det = {**det, **boxed(picked)}
            picked = det["file"]
            if det["classes"]:
                text = f"{text} [detector: {', '.join(f'{k} x{v}' if v > 1 else k for k, v in det['classes'].items())}]"
        except Exception as e:  # noqa: BLE001  (the plain picked frame is posted; the failure is on its watch.boxes row)
            det = {**det, "error": f"{type(e).__name__}: {str(e)[:100]}"}
    return {**shot, **seen, "text": text, "vision_ms": seen.pop("ms"), "stop": stop, "baseline": tidy if has else None,
            "file_up": shot["file"], "file": picked, "detector": det}   # file = the picture the model picked, boxed when the detector ran


def run(look="tilt", trigger=None, baseline=False, stop=None):
    import shutil
    import time
    from . import chat_post
    stop = int(stop) if stop is not None else None
    if baseline:   # capture the tidy reference for this look (and stop): no model call, no post
        from ..commands import look as _look
        shot = _look(look)
        shutil.copy2(shot["file"], tidy_path(look, stop))
        return {**shot, "baseline": tidy_path(look, stop), "text": "tidy baseline captured"}
    out = look_and_see(look, stop)
    out["post"] = chat_post.run(text=out["text"], file=out["file"], trigger=trigger or f"say-{int(time.time())}")
    return out
