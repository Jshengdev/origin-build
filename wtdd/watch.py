"""The eye's second opinion: an open-source detector (ultralytics YOLO11n, COCO's 80 classes, Apache-2.0 weights) in
its own process over the dog's live frames. It pulls GET /dog/frame.jpg from the API at --hz, draws the boxes into
~/Pictures/wtdd/watch.jpg (the API serves it at /pictures/watch.jpg) and writes the counts and boxes to <repo>/watch.json
(GET /watch); the remote shows both. One watch.detect ledger row whenever the set of classes in view changes and the
change holds for HOLD frames (a cup appears, a person walks in; a one-frame flicker is not an event); frames themselves
are not rows.

  python -m wtdd.watch                              live from the API, 4 frames a second
  python -m wtdd.watch --source ~/Pictures/wtdd/dog-live.jpg --once     one file, prints the detections
  python -m wtdd.watch --source look-down.jpg --once --out look-down-boxed.jpg   dog_say's one-shot: the boxed copy of the frame it posts

Facts. cv2 lives here and never in the API process (its ffmpeg clashes with PyAV's). COCO names cup, bowl, bottle,
wine glass, chair, couch, person, backpack, handbag, suitcase, laptop, cell phone, book ... and does NOT name socks,
clothes or "out of place": the vision model in wtdd/tools/dog_say.py names those, and its trials count the misses. The
detector is observability and a receipt, not a gate: the one thing that acts on it is the intruder watch: while <repo>/intruder.on exists
(POST /intruder {on} on the API, the remote's "intruder watch" button) a person in view for HOLD frames calls the API's
intruder_alarm tool (photo, boxes, "STRANGER DANGER!!!" to the castle, red/blue on the room), at most once every COOLDOWN_S. First run downloads yolo11n.pt
(about 5 MB) next to the working directory. The API adds age_ms to /watch so the page hides stale boxes."""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

from .config import ROOT
from .ledger import append, log

WATCH = ROOT / "watch.json"
ARMED = ROOT / "intruder.on"      # the intruder watch is armed while this file exists (POST /intruder {on} on the API)
COOLDOWN_S = 60                   # at most one intruder alarm a minute
OUT = Path("~/Pictures/wtdd/watch.jpg").expanduser()
MODEL = "yolo11n.pt"
CONF = 0.35
HOLD = 3                     # a change in the set of classes must hold for this many frames before it is a row (no flicker rows)
API = "http://127.0.0.1:7788"


def detect(model, img: bytes) -> tuple[list[dict], object, int]:
    import cv2
    import numpy as np
    arr = cv2.imdecode(np.frombuffer(img, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise ValueError(f"not a decodable image ({len(img)} bytes)")
    t0 = time.perf_counter()
    r = model.predict(arr, conf=CONF, verbose=False)[0]
    ms = round((time.perf_counter() - t0) * 1000)
    boxes = [{"name": r.names[int(c)], "conf": round(float(p), 2), "xyxy": [round(float(v)) for v in b]}
             for c, p, b in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.boxes.xyxy.tolist())]
    return boxes, r.plot(), ms


def publish(boxes: list[dict], plotted, ms: int, source: str, out: Path = OUT, state: bool = True) -> dict:
    """Writes the boxed JPEG to `out` (atomic) and, when `state`, the counts to watch.json for the remote."""
    import cv2
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".tmp.jpg")
    cv2.imwrite(str(tmp), plotted, [cv2.IMWRITE_JPEG_QUALITY, 80 if out != OUT else 75])
    os.replace(tmp, out)
    classes: dict[str, int] = {}
    for b in boxes:
        classes[b["name"]] = classes.get(b["name"], 0) + 1
    d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "ms": ms, "n": len(boxes), "classes": classes,
         "boxes": boxes, "source": source, "model": MODEL, "file": str(out)}
    if state:
        tmpj = WATCH.with_suffix(".tmp")
        tmpj.write_text(json.dumps(d))
        os.replace(tmpj, WATCH)
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m wtdd.watch")
    p.add_argument("--source", default=f"{API}/dog/frame.jpg", help="a URL (default: the API's live frame) or an image file")
    p.add_argument("--hz", type=float, default=4.0)
    p.add_argument("--once", action="store_true")
    p.add_argument("--out", help="write the boxed image here instead of the live watch.jpg (and leave watch.json alone): one-shot use by dog_say")
    a = p.parse_args(argv)
    out_path = Path(a.out).expanduser() if a.out else OUT
    from ultralytics import YOLO
    t0 = time.perf_counter()
    model = YOLO(MODEL)
    log("watch", f"model {MODEL} loaded", ms=round((time.perf_counter() - t0) * 1000), conf=CONF, source=a.source)
    is_url = a.source.startswith("http")
    last: set[str] | None = None
    candidate: set[str] | None = None
    held = 0
    n = warned = 0
    last_alarm = 0.0
    while True:
        try:
            if is_url:
                import requests
                r = requests.get(a.source, timeout=5)
                if r.status_code != 200:
                    raise RuntimeError(f"{a.source} -> {r.status_code}: {r.text[:80]}")
                img = r.content
            else:
                img = Path(a.source).expanduser().read_bytes()
            boxes, plotted, ms = detect(model, img)
            d = publish(boxes, plotted, ms, a.source, out_path, state=not a.out)
            n += 1
            warned = 0
            now = set(d["classes"])
            if now == candidate:
                held += 1
            else:
                candidate, held = now, 1
            if now != last and held >= HOLD:
                append({"step": "watch.detect", "agent": "watch", "tool": "watch.detect", "app": "yolo", "ok": True,
                        "args": {"source": a.source, "model": MODEL, "conf": CONF},
                        "state_before": sorted(last) if last is not None else None,
                        "state_after": {"classes": d["classes"], "n": d["n"]},
                        "response_or_error": boxes[:12], "latency_ms": ms})
                log("watch", f"in view: {', '.join(f'{k} x{v}' for k, v in d['classes'].items()) or 'nothing'}", ms=ms, frame=n)
                last = now
            elif n % 40 == 0:
                log("watch", f"frame {n}", n_boxes=d["n"], ms=ms)
            if is_url and "person" in now and held >= HOLD and ARMED.exists() and time.time() - last_alarm > COOLDOWN_S:
                last_alarm = time.time()
                log("watch", "INTRUDER: person in view while armed, sounding the alarm", frames_held=held)
                try:
                    import requests
                    r = requests.post(f"{API}/tools/intruder_alarm", json={}, timeout=120).json()
                    log("watch", "intruder alarm " + ("done" if r.get("ok") else "FAILED"), posted=((r.get("result") or {}).get("post") or {}).get("rowid") if r.get("ok") else r.get("error", "")[:120])
                except Exception as e:  # noqa: BLE001  (logged; the next sighting after the cooldown tries again)
                    log("watch", f"intruder alarm FAILED: {type(e).__name__}: {str(e)[:100]}")
        except Exception as e:  # noqa: BLE001  (no dog, stale video, a bad frame: logged, then try again; never a fake box)
            if warned == 0:
                log("watch", f"WARN no detection: {type(e).__name__}: {str(e)[:100]}")
            warned += 1
            if a.once:
                return 1
            time.sleep(10 if "unreachable" in str(e) or "503" in str(e) else 2)   # no dog: back off, the API is not re-probed either
            continue
        if a.once:
            print(json.dumps({k: d[k] for k in ("ts", "ms", "n", "classes", "boxes", "file")}))
            return 0
        time.sleep(max(0.0, 1 / a.hz))


if __name__ == "__main__":
    sys.exit(main())
