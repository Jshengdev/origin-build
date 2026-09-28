"""Synthetic detector frame and object fixtures for wtdd/dog/objects.py (its tests, its `--replay`, and the remote's
dry check): one 640x480 frame with two flat-colour rectangles where a detector box would sit, the watch.json-shaped
detections for it, and the exact GET /dog/objects body the page draws. Nothing here has seen the real dog or a model.

    python -m wtdd.dog.fixtures.make_objects_fixture      rewrites frame.jpg, watch-frame.json, objects.json next to this file

The pose the fixtures assume, in the odometry frame of voxel_frames.npz (make_voxel_frames.py's world): the dog at
POSE (0, 0) facing +x (yaw 0), camera field of view FOV_DEG = 90 (a test value: the real Go2 FOV is UNVERIFIED and
lives in env WTDD_CAM_FOV_DEG). Box A ("chair") is centred in the frame, so its bearing is 0 and the ray along +x
meets WALL_A at (2.0, 0.0) m. Box B ("backpack") is centred at 0.9 of the width, so its bearing is atan(0.8) = 38.7
degrees to the right, and the ray meets WALL_A at (2.0, -1.6) m. Both are 3-frame cells (walls at threshold 3).
Map pixels come through CAL (the same tie wtdd/dog/test_occupancy.py uses: at map (449, 491) facing down the page).

objects.json is the page's contract, not the store's output: it holds what the store's stub path produces for these
boxes (a detector label and confidence, a stub one-liner tagged [stub: no model], a thumbnail cropped from the frame)
with o1 fresh and o2 stale, so the remote can be screenshotted with no dog, no detector and no key. Serving it is a
DEMO_CACHE path in the API (WTDD_OBJECTS=<this file>); the live path is the session store fed by watch.json."""
from __future__ import annotations
import base64
import io
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from .. import nav

HERE = Path(__file__).resolve().parent
FRAME = HERE / "frame.jpg"
WATCH_JSON = HERE / "watch-frame.json"
OBJECTS_JSON = HERE / "objects.json"
W, H = 640, 480
FOV_DEG = 90.0
POSE = {"position": [0.0, 0.0], "yaw": 0.0}
CAL = {"odom": [0.0, 0.0, 0.0], "map": [449.0, 491.0], "heading": 1.5708}
THUMB_PX = 96
BG = (235, 235, 230)
BOXES = [   # name, conf, xyxy, fill colour, the odometry point its ray meets on WALL_A (x = 2.0 m) at FOV_DEG
    {"name": "chair", "conf": 0.71, "xyxy": [280, 200, 360, 330], "rgb": (200, 40, 40), "hit_m": [2.0, 0.0]},
    {"name": "backpack", "conf": 0.55, "xyxy": [536, 260, 616, 350], "rgb": (40, 60, 200), "hit_m": [2.0, -1.6]},
]
TS = "2026-09-26T03:00:00"


def bearing_deg(xyxy) -> float:
    """Pinhole bearing of a box centre, right positive: the same rule objects.bearing implements."""
    u = (xyxy[0] + xyxy[2]) / 2
    return math.degrees(math.atan((u / W - 0.5) * 2 * math.tan(math.radians(FOV_DEG) / 2)))


def thumb(img: Image.Image, xyxy, width: int = THUMB_PX) -> str:
    t = img.crop(tuple(xyxy)).convert("RGB")
    t.thumbnail((width, width))
    buf = io.BytesIO()
    t.save(buf, "JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def write() -> list[Path]:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for b in BOXES:
        d.rectangle(tuple(b["xyxy"]), fill=b["rgb"])
    img.save(FRAME, "JPEG", quality=85)
    boxes = [{"name": b["name"], "conf": b["conf"], "xyxy": list(b["xyxy"])} for b in BOXES]
    classes: dict[str, int] = {}
    for b in boxes:
        classes[b["name"]] = classes.get(b["name"], 0) + 1
    WATCH_JSON.write_text(json.dumps({"ts": TS, "t": 1790420400.0, "ms": 21, "n": len(boxes), "classes": classes, "boxes": boxes,
                                      "source": "fixture", "model": "yolo11n.pt", "file": FRAME.name}, indent=1) + "\n")
    objs = []
    for i, b in enumerate(BOXES):
        px, py, _ = nav.to_map(CAL, b["hit_m"], 0.0)
        deg = round(bearing_deg(b["xyxy"]), 1)
        dist = round(math.hypot(*b["hit_m"]), 2)
        stale = i == 1
        objs.append({"id": f"o{i + 1}", "label": b["name"], "p": b["conf"], "label_source": "detector",
                     "message": f"{b['name']} ({b['conf']:.2f}) {dist:.1f} m away, {deg:+.0f} deg from where it looks [stub: no model]",
                     "message_source": "stub", "thumb": thumb(img, b["xyxy"]), "box": list(b["xyxy"]),
                     "bearing_deg": deg, "hit_m": b["hit_m"], "dist_m": dist, "pos_px": [round(px), round(py)], "why": None,
                     "first_seen": TS, "last_seen": "2026-09-26T03:00:02" if stale else "2026-09-26T03:00:05",
                     "windows_unseen": 9 if stale else 0, "stale": stale, "depth_cam_m": None, "placed_by": "first lidar hit"})
    OBJECTS_JSON.write_text(json.dumps({"n": len(objs), "objects": objs, "windows": 12, "fov_deg": FOV_DEG,
                                        "source": "wtdd/dog/fixtures/objects.json", "why": None}, indent=1) + "\n")
    return [FRAME, WATCH_JSON, OBJECTS_JSON]


def main() -> int:
    for p in write():
        print(f"wrote {p} ({p.stat().st_size} bytes)", file=sys.stderr)
    for b in BOXES:
        print(f"{b['name']}: bearing {bearing_deg(b['xyxy']):+.1f} deg -> WALL_A at {b['hit_m']} m", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
