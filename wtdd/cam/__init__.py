"""A fixed camera in the same queue: a laptop posts JPEG frames to POST /cam/<id>/frame; the API writes the frame under
<repo>/cams/ (WTDD_CAMS redirects it; the tests set a temp dir), runs the existing detector in its own process
(python -m wtdd.watch --source <frame> --once --out <boxed>; cv2 never loads in the API process), writes one cam.frame
and one cam.detect row, publishes <id>.json for the remote (GET /cam, GET /cam/<id>/frame.jpg), and a person box while
the intruder watch is armed (<repo>/intruder.on, the same gate as the dog's feed) raises the same who-dis path a stop
raises (intruder_alarm with file=<the frame>, pending.json, one gated post), at most once per COOLDOWN_S per camera.
The contract is wtdd/cam/test_cam.py; the laptop side is wtdd/cam/__main__.py (python -m wtdd.cam).

  ingest(cam_id, jpeg)     the POST: cam.frame row (the file lands), cam.detect row (the detector's boxes), <id>.json, the ask
  detect_file(frame, out)  the detector subprocess, dog_say.boxed's handshake, keeping the boxes
  person_seen(...)         the who-dis hook: None without a person box; else asked, or why not (disarmed, cooldown)
  read_all()               every camera's newest <id>.json plus age_ms (GET /cam)
  zone_of(pt, zones)       the first drawn zone without nogo: true that holds pt (field.inside), else None (item 23)
  validate_cameras(cameras, zones)   ui/map.json cameras[] as POST /map saves it: ids unique and postable (ID), pt a
                           pair inside VIEW, zone recomputed from pt; ValueError naming the camera or the zone (zones a
                           list of {name, poly}: never a TypeError the API would drop); no zone = None + one WARN
  placed(before, cameras, path)   after the save: one map.camera_placed row per camera whose pt is new or moved

Rows. cam.frame {cam, shift_id, bytes} -> state_after {file}; FAILED on a bad id or bytes that are not a JPEG (no
detector run, no cam.detect row). cam.detect {cam, shift_id, model, classes, boxes (at most 12)} -> state_after
{classes, n, file (the boxed copy)}, state_before = the classes this camera saw last; latency is the subprocess wall
time (model load + predict, about 1-2 s). One row per posted frame, no HOLD: at the client's 0.5 Hz a one-frame sighting
is a two-second event. shift_id is WTDD_SHIFT or today's date. A person raises at most one intruder.alarm row per
camera per COOLDOWN_S, keyed cam:<id>:<epoch> so the chat's claim refuses a second post on the same key; the cooldown
starts before the ask (wtdd/watch.py's order), so a failed ask waits for the next window instead of re-firing every frame.
The hook is the one call in person_seen(): when item 02's decide path lands, it is re-pointed there in one line.
A camera is placed on the map from the remote like a lamp (item 23, wtdd/cam/test_place.py): one map.camera_placed row
{id, pt, zone, shift_id} per camera whose pt is new or moved, state_before {pt, zone} of that id on the previous
ui/map.json (None for a new camera, or when that file's cameras are null or lack an id), state_after {pt, zone} read
back from the saved file inside the step (a failed read-back is an ok=False row, then the API's 500); none when no pt
moved (a zone-only change included), none on a refused save. 08's roster reads the zone.

UNVERIFIED: nothing here has met a real laptop or the real detector on a real frame (the unit test stubs the
subprocess; test_cam's LiveDetector runs it only where yolo11n.pt sits). The detector's latency per frame on the Mac
under the API's load, and whether 0.5 Hz keeps up, are what the first live run measures. A camera's pt is a click on
the plan, not a measurement; where the Mac really sits is confirmed on Sunday."""
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
VIEW = (1060, 1540)                      # the remote's map viewBox and house.svg's size: a camera's pt lives inside it
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
    """A person box at this camera: the same who-dis path the dog's stops and its feed raise, once per cooldown."""
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
    log("cam", f"INTRUDER: person at camera {cam_id} while armed, asking who dis", trigger=key)
    from .. import tools
    out = tools.call("intruder_alarm", file=str(frame), trigger=key)
    return {"asked": True, "trigger": key, "post": out["post"]["rowid"], "pending": out["pending"]}


def read_all() -> dict:
    """Every camera's newest detection ({} until one posts), with age_ms so the remote marks a stale one."""
    out = {}
    for f in sorted(cams().glob("*.json")):
        out[f.stem] = {**json.loads(f.read_text()), "age_ms": round((time.time() - f.stat().st_mtime) * 1000)}
    return out


def zone_of(pt, zones) -> str | None:
    """The first drawn zone without nogo: true that holds pt under field.inside, else None: a no-go zone never holds a camera."""
    from ..field import inside   # field imports the ledger: inside the function, the 09-2 import order
    return next((z["name"] for z in zones if not z.get("nogo") and inside(pt, z["poly"])), None)


def _pair(v) -> bool:
    """[x, y]: two numbers (a bool is not one)."""
    return isinstance(v, (list, tuple)) and len(v) == 2 and all(type(x) in (int, float) for x in v)


def validate_cameras(cameras, zones) -> list[dict]:
    """cameras[] as POST /map saves it, or ValueError naming the first bad zone or camera (then nothing is saved). The
    zone is always recomputed from pt, whatever the page sent; a camera in no zone is kept with zone None and one WARN
    line, written only once the whole list has passed (08's roster refuses it later, loud)."""
    from ..ledger import log
    if not isinstance(zones, list):   # zone_of walks every zone: a malformed one is a named 400, never a crash that drops the socket
        raise ValueError(f"zones is a {type(zones).__name__}, not a list")
    for n, z in enumerate(zones, 1):
        if not isinstance(z, dict) or not isinstance(z.get("name"), str) or not z["name"]:
            raise ValueError(f"zone {n} has no name")
        if not isinstance(z.get("poly"), list) or not all(map(_pair, z["poly"])):
            raise ValueError(f"zone {z['name']}: poly must be a list of [x, y] pairs")
    if not isinstance(cameras, list):
        raise ValueError(f"cameras is a {type(cameras).__name__}, not a list")
    seen: set[str] = set()
    for n, c in enumerate(cameras, 1):
        if not isinstance(c, dict):
            raise ValueError(f"camera {n} is not an object")
        cid, pt = c.get("id"), c.get("pt")
        if not isinstance(cid, str) or not cid:
            raise ValueError(f"camera {n} has no id")
        if not ID.fullmatch(cid):
            raise ValueError(f"camera {cid[:64]!r}: id must match [a-z0-9_-]{{1,32}} (POST /cam/<id>/frame would refuse it)")
        if cid in seen:
            raise ValueError(f"camera {cid}: duplicate id")
        seen.add(cid)
        if not _pair(pt):
            raise ValueError(f"camera {cid}: pt must be [x, y], two numbers (got {json.dumps(pt)[:40]})")
        if not (0 <= pt[0] <= VIEW[0] and 0 <= pt[1] <= VIEW[1]):
            raise ValueError(f"camera {cid}: pt {json.dumps(pt)} is outside the map (0..{VIEW[0]}, 0..{VIEW[1]})")
    out = [{**c, "pt": list(c["pt"]), "zone": zone_of(c["pt"], zones)} for c in cameras]
    for c in out:
        if c["zone"] is None:
            log("cam", f"camera {c['id']} placed in no zone: the roster will refuse")
    return out


def placed(before, cameras: list[dict], path: Path) -> list[dict]:
    """After POST /map wrote `path` from `cameras` (validate_cameras' list): one map.camera_placed row per camera whose pt
    is new or moved against `before` (the previous file's cameras as it held them; a hand-added camera with no id there
    is no camera to compare against), each read back from the saved file inside its own step, so a failed read-back is
    an ok=False row before the API's 500. A save that moves no camera writes no row."""
    from ..ledger import step
    old = {c.get("id"): c for c in before if isinstance(c, dict)} if isinstance(before, list) else {}
    out = []
    for c in cameras:
        was = old.get(c["id"])
        if was is not None and was.get("pt") == c["pt"]:
            continue
        with step("map", "map.camera_placed", "api", {"id": c["id"], "pt": c["pt"], "zone": c["zone"], "shift_id": shift_id()},
                  None if was is None else {"pt": was.get("pt"), "zone": was.get("zone")}) as r:
            saved = {x["id"]: x for x in json.loads(path.read_text())["cameras"]}[c["id"]]   # the receipt is what the file says
            r["state_after"] = {"pt": saved["pt"], "zone": saved["zone"]}
        out.append(r)
    return out
