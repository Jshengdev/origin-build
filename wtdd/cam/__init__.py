"""A fixed camera in the same queue: a laptop posts JPEG frames to POST /cam/<id>/frame; the API writes the frame under
<repo>/cams/ (WTDD_CAMS redirects it; the tests set a temp dir), runs the existing detector in its own process
(python -m wtdd.watch --source <frame> --once --out <boxed>; cv2 never loads in the API process), writes one cam.frame
and one cam.detect row, publishes <id>.json for the remote (GET /cam, GET /cam/<id>/frame.jpg), and a person box while
the intruder watch is armed (<repo>/intruder.on, the same gate as the dog's feed) is handed to dispatch on a thread
(wtdd/dispatch.py: a route, a typed decision, the ask in the thread with the frame), at most once per COOLDOWN_S per camera.
The contract is wtdd/cam/test_cam.py; the laptop side is wtdd/cam/__main__.py (python -m wtdd.cam).

  ingest(cam_id, jpeg)     the POST: cam.frame row (the file lands), cam.detect row (the detector's boxes), <id>.json, the ask
  detect_file(frame, out)  the detector subprocess, dog_say.boxed's handshake, keeping the boxes
  person_seen(...)         the dispatch hook: None without a person box; else dispatched, or why not (disarmed, cooldown)
  read_all()               every camera's newest <id>.json plus age_ms (GET /cam)

Rows. cam.frame {cam, shift_id, bytes} -> state_after {file}; FAILED on a bad id or bytes that are not a JPEG (no
detector run, no cam.detect row). cam.detect {cam, shift_id, model, classes, boxes (at most 12)} -> state_after
{classes, n, file (the boxed copy)}, state_before = the classes this camera saw last; latency is the subprocess wall
time (model load + predict, about 1-2 s). One row per posted frame, no HOLD: at the client's 0.5 Hz a one-frame sighting
is a two-second event. shift_id is WTDD_SHIFT or today's date. A person starts at most one dispatch per camera per
COOLDOWN_S, keyed cam:<id>:<epoch> so the chat's claim refuses a second post on the same key; the cooldown starts before
the dispatch (wtdd/watch.py's order), so a failed one waits for the next window instead of re-firing every frame.
The hook is the one call in person_seen(): a thread running the dispatch tool (item 18), so the camera's POST returns
at once while dispatch plans, decides, asks the thread or refuses loud (its own rows), and walks only on a person's yes.

UNVERIFIED: nothing here has met a real laptop or the real detector on a real frame (the unit test stubs the
subprocess; test_cam's LiveDetector runs it only where yolo11n.pt sits). The detector's latency per frame on the Mac
under the API's load, and whether 0.5 Hz keeps up, are what the first live run measures."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..config import ROOT, maybe
# wtdd.ledger, and wtdd.watch which imports it, are imported inside the functions: unittest imports this package before
# test_cam's body points WTDD_LEDGER at a scratch file, and the ledger binds its path at import (docs/gotchas/09-2-*).

ARMED = ROOT / "intruder.on"            # the file wtdd/watch.py and POST /intruder use: the remote's intruder watch arms both eyes
ID = re.compile(r"[a-z0-9_-]{1,32}")    # the id becomes a file name
_last: dict[str, float] = {}             # camera id -> when it last asked
_lock = threading.Lock()                 # the API serves posts on threads


def cams() -> Path:
    """<repo>/cams/, or WTDD_CAMS (plain process env, read per call for the same import-order reason)."""
    return Path(os.environ.get("WTDD_CAMS") or ROOT / "cams").expanduser().absolute()


def shift_id() -> str:
    return maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")


def detect_file(frame: Path, out: Path) -> dict:
    """The existing detector over one saved frame, in its own process: {ts, ms, n, classes, boxes, file}. Raises."""
    pr = subprocess.run([sys.executable, "-m", "wtdd.watch", "--source", str(frame), "--once", "--out", str(out)],
                        capture_output=True, text=True, timeout=90, cwd=ROOT)
    if pr.returncode != 0 or not pr.stdout.strip():
        raise RuntimeError(f"detector rc={pr.returncode}: {pr.stderr.strip()[-200:]}")
    return json.loads(pr.stdout.strip().splitlines()[-1])


def _publish(pub: Path, d: dict) -> None:
    tmp = pub.with_name(pub.name + ".tmp")
    tmp.write_text(json.dumps(d))
    os.replace(tmp, pub)


def ingest(cam_id: str, jpeg: bytes) -> dict:
    """One posted frame. Raises ValueError (after its FAILED cam.frame row) on a bad id or bytes that are not a JPEG;
    a failed detector or ask is {ok: False, error} with its rows written and <id>.json showing the error."""
    from ..ledger import log, step
    from ..watch import MODEL
    sid, home = shift_id(), cams()
    path, pub = home / f"{cam_id}.jpg", home / f"{cam_id}.json"
    with step("cam", "cam.frame", "camera", {"cam": cam_id[:64], "shift_id": sid, "bytes": len(jpeg)}) as r:
        if not ID.fullmatch(cam_id):
            raise ValueError(f"bad camera id {cam_id[:64]!r}: 1 to 32 of a-z 0-9 _ -")
        if jpeg[:3] != b"\xff\xd8\xff":
            raise ValueError(f"not a JPEG ({len(jpeg)} bytes, starts {jpeg[:4].hex() or 'empty'})")
        home.mkdir(parents=True, exist_ok=True)
        tmp = home / f"{cam_id}.tmp.jpg"
        tmp.write_bytes(jpeg)
        os.replace(tmp, path)
        r["state_after"] = {"file": str(path)}
    frame = {"file": path.name, "bytes": len(jpeg)}
    base = {"cam": cam_id, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "model": MODEL, "file": path.name,
            "bytes": len(jpeg), "shift_id": sid}
    before = json.loads(pub.read_text()).get("classes") if pub.exists() else None
    try:
        with step("cam", "cam.detect", "yolo", {"cam": cam_id, "shift_id": sid, "model": MODEL}, before) as r:
            d = detect_file(path, home / f"{cam_id}-boxed.jpg")
            r["args"]["classes"], r["args"]["boxes"] = d["classes"], d["boxes"][:12]
            r["state_after"] = {"classes": d["classes"], "n": d["n"], "file": Path(d["file"]).name}
    except Exception as e:  # noqa: BLE001  (its cam.detect row says why; the remote shows it instead of the last good boxes)
        err = f"{type(e).__name__}: {e}"
        _publish(pub, {**base, "error": err})
        log("cam", f"{cam_id}: detector FAILED", err=err[:120])
        return {"ok": False, "cam": cam_id, "frame": frame, "detect": None, "person": None, "error": err}
    _publish(pub, {**base, "ms": d["ms"], "n": d["n"], "classes": d["classes"], "boxes": d["boxes"], "boxed": Path(d["file"]).name})
    detect = {"classes": d["classes"], "n": d["n"], "boxes": d["boxes"], "ms": d["ms"], "model": MODEL}
    try:
        person = person_seen(cam_id, path, d["boxes"])
    except Exception as e:  # noqa: BLE001  (the intruder.alarm row already has the failure; the cooldown holds)
        err = f"{type(e).__name__}: {e}"
        log("cam", f"{cam_id}: who dis FAILED", err=err[:120])
        return {"ok": False, "cam": cam_id, "frame": frame, "detect": detect, "person": {"asked": False, "why": f"FAILED {err}"[:200]}, "error": err}
    seen = ", ".join(f"{k} x{v}" for k, v in d["classes"].items()) or "nothing in view"
    log("cam", f"{cam_id}: {seen}", ms=d["ms"], bytes=len(jpeg), person="none" if person is None else person.get("trigger") or person["why"])
    return {"ok": True, "cam": cam_id, "frame": frame, "detect": detect, "person": person}


def person_seen(cam_id: str, frame: Path, boxes: list[dict]) -> dict | None:
    """A person box at this camera while armed: handed to the dispatch tool on a thread, once per cooldown; returns now."""
    from ..ledger import log
    from ..watch import COOLDOWN_S
    if not any(b.get("name") == "person" for b in boxes):
        return None
    if not ARMED.exists():   # these two answers land on ingest's one stderr line for the frame
        return {"asked": False, "why": "not armed (POST /intruder {on}, or the remote's intruder watch)"}
    now = time.time()
    with _lock:
        left = COOLDOWN_S - (now - _last.get(cam_id, 0.0))
        if left <= 0:
            _last[cam_id] = now
    if left > 0:
        return {"asked": False, "why": f"cooldown {int(left)} s"}
    key = f"cam:{cam_id}:{int(now)}"
    log("cam", f"INTRUDER: person at camera {cam_id} while armed, dispatching", trigger=key)
    from .. import tools
    threading.Thread(target=tools.call, args=("dispatch",), kwargs={"cam": cam_id, "trigger": key, "file": str(frame)}, daemon=True,
                     name=f"dispatch-{key}").start()   # 18: a dispatch can take a walk's length; the camera's POST returns now
    return {"dispatched": True, "trigger": key}


def read_all() -> dict:
    """Every camera's newest detection ({} until one posts), with age_ms so the remote marks a stale one."""
    out = {}
    for f in sorted(cams().glob("*.json")):
        out[f.stem] = {**json.loads(f.read_text()), "age_ms": round((time.time() - f.stat().st_mtime) * 1000)}
    return out
