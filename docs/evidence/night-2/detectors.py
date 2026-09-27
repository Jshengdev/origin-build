"""Detector outputs on the five real Go2 frames (roadmap 20): boxes and numbers only, never the frames. Writes
docs/evidence/night-2/detectors-2026-09-26.json, the artefact every sentence about detectors must be read from
(roadmap 20: every number about detectors is an artefact in the repo before it is a sentence).

  /Users/johnnysheng/code/origin-build/.venv/bin/python docs/evidence/night-2/detectors.py     from the repo root

What it runs. wtdd.watch.detect() unchanged (CONF 0.35, {name, conf, xyxy} per box) with YOLO11n (<repo>/yolo11n.pt,
the shipped detector) over the five frames of 2026-09-13 in ~/Pictures/wtdd (look-tilt, look-down, dog-live, look-level,
dog-sit-look), and, when the scratch bench of 2026-09-26 still exists, the prompt-list detectors baked there
(/tmp/ovworld: YOLOE-11s with the site list and the house list, YOLOv8s-worldv2 with the same two lists) and the
prompt-free YOLOE (/tmp/ovbench). A weight file that is absent is recorded as absent; one that fails to load is
recorded with its error; nothing is skipped silently and nothing is downloaded. Each model does one untimed warm-up
predict on the first frame, then one timed predict per frame; the device is read back from the predictor, not assumed.
Frames are identified by name, sha256, size and pixel dimensions; no pixel data enters the file. person_recall is
derived from the boxes in this same file (frames with a person box at CONF or above), so a recall sentence in a PR
is a read of this artefact, never a memory of the bench. A scratch bench on this Mac: not a claim about the dog."""
from __future__ import annotations
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WTDD_LEDGER", "/tmp/night1/20/detectors-ledger.jsonl")   # watch imports the ledger; nothing is appended here

OUT = ROOT / "docs" / "evidence" / "night-2" / "detectors-2026-09-26.json"
FRAMES = ["look-tilt", "look-down", "dog-live", "look-level", "dog-sit-look"]
PICTURES = Path("~/Pictures/wtdd").expanduser()
MODELS = {   # key: (path, what its label list is)
    "yolo11n": (ROOT / "yolo11n.pt", "COCO-80, the shipped detector (wtdd/watch.py MODEL)"),
    "yoloe-11s-site": (Path("/tmp/ovworld/yoloe-11s-site.pt"), "YOLOE-11s-seg, the site list baked in (scratch bench 2026-09-26)"),
    "yoloe-11s-house": (Path("/tmp/ovworld/yoloe-11s-house.pt"), "YOLOE-11s-seg, the house list baked in (scratch bench 2026-09-26)"),
    "yolov8s-world-site": (Path("/tmp/ovworld/yolov8s-world-site.pt"), "YOLOv8s-worldv2, the site list baked in (scratch bench 2026-09-26)"),
    "yolov8s-world-house": (Path("/tmp/ovworld/yolov8s-world-house.pt"), "YOLOv8s-worldv2, the house list baked in (scratch bench 2026-09-26)"),
    "yoloe-11s-pf": (Path("/tmp/ovbench/yoloe-11s-seg-pf.pt"), "YOLOE-11s-seg prompt-free, LVIS+Objects365 names (scratch bench 2026-09-26)"),
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    from PIL import Image
    from ultralytics import YOLO
    import torch
    import ultralytics
    from wtdd import watch

    frames = []
    for name in FRAMES:
        f = PICTURES / f"{name}.jpg"
        if not f.is_file():
            raise FileNotFoundError(f"{f}: the five real frames of 2026-09-13 are needed (never committed); nothing was written")
        w, h = Image.open(f).size
        frames.append({"name": name, "sha256": sha(f), "bytes": f.stat().st_size, "width": w, "height": h})

    models, detections, recall = [], {}, {}
    for key, (path, what) in MODELS.items():
        m = {"key": key, "file": path.name, "what": what, "present": path.is_file()}
        if not m["present"]:
            m["note"] = f"{path} is absent on this Mac at generation time; nothing was run for it"
            print(f"[detectors] {key}: absent ({path})", file=sys.stderr)
            models.append(m)
            continue
        m.update({"bytes": path.stat().st_size, "sha256": sha(path)})
        try:
            t0 = time.perf_counter()
            model = YOLO(str(path))
            m["load_ms"] = round((time.perf_counter() - t0) * 1000)
            m["names_n"] = len(model.names)
            m["names"] = [model.names[i] for i in sorted(model.names)] if len(model.names) <= 100 else f"{len(model.names)} names (not listed)"
            first = (PICTURES / f"{frames[0]['name']}.jpg").read_bytes()
            t0 = time.perf_counter()
            watch.detect(model, first)                       # untimed warm-up: the first predict builds the predictor
            m["warmup_ms"] = round((time.perf_counter() - t0) * 1000)
            m["device"] = str(model.predictor.device)        # read back, not assumed
            m["loaded"] = True
        except Exception as e:  # noqa: BLE001  (recorded verbatim on the model entry; the run goes on to the next model)
            m.update({"loaded": False, "error": f"{type(e).__name__}: {str(e)[:300]}"})
            print(f"[detectors] {key}: load FAILED {m['error']}", file=sys.stderr)
            models.append(m)
            continue
        models.append(m)
        per, hits = {}, {}
        for fr in frames:
            img = (PICTURES / f"{fr['name']}.jpg").read_bytes()
            boxes, _plotted, ms = watch.detect(model, img)   # the plotted image is dropped: numbers only
            per[fr["name"]] = {"ms": ms, "n": len(boxes), "boxes": boxes}
            people = [b["conf"] for b in boxes if b["name"] == "person"]
            hits[fr["name"]] = max(people) if people else None
            print(f"[detectors] {key} {fr['name']}: {len(boxes)} boxes {ms} ms person={hits[fr['name']]}", file=sys.stderr)
        detections[key] = per
        recall[key] = {"frames_with_person": sum(v is not None for v in hits.values()), "of": len(frames), "person_conf_by_frame": hits,
                       "rule": f"a box named exactly 'person' at conf >= {watch.CONF} (wtdd/watch.py CONF); the alarm keys on that name"}

    out = {
        "what": "detector outputs on five real Go2 frames: boxes and numbers only, never the frames",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generated_by": "docs/evidence/night-2/detectors.py",
        "wording": ("regenerated 2026-09-26 on this Mac by docs/evidence/night-2/detectors.py from the scratch bench weights of the same "
                    "day (/tmp/ovworld, /tmp/ovbench; not committed) on five real Go2 frames of 2026-09-13 (~/Pictures/wtdd; identified "
                    "by sha256, not committed). A scratch bench on this Mac, not a run on the dog."),
        "machine": {"platform": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0],
                    "ultralytics": ultralytics.__version__, "torch": torch.__version__, "mps_available": bool(torch.backends.mps.is_available())},
        "detect": {"function": "wtdd.watch.detect", "conf": watch.CONF, "box_keys": ["name", "conf", "xyxy"], "timing": "one timed predict per frame after one warm-up"},
        "frames": frames,
        "models": models,
        "person_recall": recall,
        "detections": detections,
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    ran = [m["key"] for m in models if m.get("loaded")]
    print(f"[detectors] wrote {OUT.relative_to(ROOT)} frames={len(frames)} models_ran={len(ran)} ({', '.join(ran)}) "
          f"models_failed={len([m for m in models if m['present'] and not m.get('loaded')])} absent={len([m for m in models if not m['present']])}", file=sys.stderr)
    if not ran:
        print("[detectors] WARN zero models ran", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
