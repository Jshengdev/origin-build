"""python -m wtdd.cam: the laptop side of a fixed camera. It grabs a frame from the laptop's camera, encodes it as a JPEG
and POSTs it raw to the API's /cam/<id>/frame at --hz; the server saves it, runs the detector, writes the rows and asks
"who dis?!" when the intruder watch is armed (wtdd/cam/__init__.py). This side writes no ledger rows (it runs on
another machine; the server's cam.frame and cam.detect rows are the receipts), one stderr line per frame instead.

  python -m wtdd.cam --cam lap1                                     device 0, 0.5 frames a second, to http://127.0.0.1:7788
  python -m wtdd.cam --cam lap1 --source wtdd/cam/fixtures/frame.jpg --once   one replayed JPEG, prints the server's answer

Reaching the server. The API binds 127.0.0.1 by design (no auth; it drives the dog), so the laptop reaches it through
an SSH tunnel and posts to its own localhost: `ssh -N -L 7788:127.0.0.1:7788 <user>@<the Mac>` then run the client
with the default --server. Opening the bind to the LAN is a decision this client does not make.
--hz defaults to 0.5 because the server spawns the detector per frame (model load + predict, about 1-2 s).
A refused post is logged FAILED with the server's error; an unreachable server is a WARN and a 5 s wait; with --once
either exits 1. A frame is never re-sent; the next tick grabs a new one.

UNVERIFIED: the camera path (cv2.VideoCapture on the laptop) has never run; the first live run confirms the device
opens (macOS asks for camera permission for the terminal), that a frame at 0.5 Hz is current rather than one the
capture backend buffered, and the server's latency per frame."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

import requests   # already a dependency (requirements.txt; wtdd/watch.py uses it)

from ..ledger import log


def post_frame(server: str, cam: str, jpeg: bytes) -> tuple[int, dict]:
    r = requests.post(f"{server}/cam/{cam}/frame", data=jpeg, headers={"Content-Type": "image/jpeg"}, timeout=60)
    return r.status_code, r.json()


def camera(index: int, width: int):
    """The laptop's camera as grab() -> JPEG bytes. cv2 is imported here only: the file path and the API never load it."""
    import cv2
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError(f"camera {index} did not open (macOS: allow the terminal under Privacy & Security > Camera)")

    def grab() -> bytes:
        ok, img = cap.read()
        if not ok or img is None:
            raise RuntimeError(f"camera {index} gave no frame")
        h, w = img.shape[:2]
        if w > width:
            img = cv2.resize(img, (width, round(h * width / w)))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return buf.tobytes()
    return grab


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m wtdd.cam")
    p.add_argument("--server", default="http://127.0.0.1:7788", help="the API (through the SSH tunnel from a laptop)")
    p.add_argument("--cam", default="lap1", help="this camera's id, 1-32 of a-z 0-9 _ - (ui/map.json cameras[].id)")
    p.add_argument("--source", default="0", help="a camera index (default 0, the laptop's own) or a JPEG file to replay")
    p.add_argument("--hz", type=float, default=0.5)
    p.add_argument("--width", type=int, default=640, help="camera frames are scaled down to this width")
    p.add_argument("--once", action="store_true", help="one frame; prints the server's answer; exit 0 only when it said ok")
    a = p.parse_args(argv)
    server = a.server.rstrip("/")
    if a.source.isdigit():
        grab = camera(int(a.source), a.width)
    else:
        # DEMO_CACHE: --source <file> replays one JPEG instead of the laptop camera. What: the frame. Why: a worktree and
        # the unit test have no camera. Live: omit --source (device 0) or pass --source <n>; the server runs the detector
        # and writes the same rows either way, so the receipts have the same shape.
        grab = Path(a.source).expanduser().read_bytes
    n = good = 0
    while True:
        t0 = time.perf_counter()
        try:
            status, r = post_frame(server, a.cam, grab())
        except requests.RequestException as e:
            log("cam", f"WARN server unreachable: {server}: {type(e).__name__}: {str(e)[:120]}")
            if a.once:
                return 1
            time.sleep(5)
            continue
        except Exception as e:  # noqa: BLE001  (a camera that gave nothing, or an answer that is not JSON: loud, then the next tick)
            log("cam", f"{a.cam} FAILED: {type(e).__name__}: {str(e)[:120]}")
            if a.once:
                return 1
            time.sleep(max(0.0, 1 / a.hz))
            continue
        n += 1
        ms = round((time.perf_counter() - t0) * 1000)
        if status == 200 and r.get("ok"):
            good += 1
            det, person = r["detect"], r.get("person")
            seen = " · ".join(f"{k} x{v}" for k, v in det["classes"].items()) or "nothing in view"
            asked = "none" if person is None else f"asked={person['asked']}" + ("" if person["asked"] else f" ({person['why']})")
            log("cam", f"{a.cam} -> {server}: {seen} · detector {det['ms']} ms · round trip {ms} ms · person {asked}")
        else:
            log("cam", f"{a.cam} -> {server}: FAILED {status}: {str(r.get('error'))[:160]}", ms=ms)
        if n % 40 == 0:
            log("cam", f"{n} frames posted", ok=good, failed=n - good)
        if a.once:
            print(json.dumps(r))
            return 0 if status == 200 and r.get("ok") else 1
        time.sleep(max(0.0, 1 / a.hz - (time.perf_counter() - t0)))


if __name__ == "__main__":
    sys.exit(main())
