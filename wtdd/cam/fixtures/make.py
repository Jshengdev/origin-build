"""Makes the fixture for wtdd/cam/test_cam.py: frame.jpg, a 320x240 JPEG of a drawn figure (head, body, legs) on a
gray wall, and detect.json, the detector's `--once` stdout shape (wtdd/watch.py: ts, ms, n, classes, boxes, file) with
one person box exactly where the figure was drawn. Not a photo: no face lands in a tracked file. The unit test never
runs the real detector on it (yolo11n.pt is gitignored, downloads on first run), so the box and its conf are fixture
values, not measurements; test_cam's LiveDetector case reports what the real detector sees when the weights exist.

  /Users/johnnysheng/code/origin-build/.venv/bin/python wtdd/cam/fixtures/make.py     (run once; commit both outputs)
"""
from __future__ import annotations
import json
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).parent
W, H = 320, 240
BOX = [108, 34, 212, 236]        # xyxy around the figure below, with a margin (fixture value)
INK = (60, 40, 40)


def main() -> None:
    img = np.full((H, W, 3), 196, np.uint8)
    cv2.rectangle(img, (0, 200), (W, H), (150, 150, 150), -1)              # a floor line so the frame is not flat
    cv2.circle(img, (160, 60), 22, INK, -1)                                  # head
    cv2.rectangle(img, (132, 84), (188, 170), INK, -1)                       # body
    cv2.rectangle(img, (118, 90), (132, 150), INK, -1)                       # arms
    cv2.rectangle(img, (188, 90), (202, 150), INK, -1)
    cv2.rectangle(img, (136, 170), (156, 230), INK, -1)                      # legs
    cv2.rectangle(img, (164, 170), (184, 230), INK, -1)
    cv2.putText(img, "fixture, not a photo", (8, 232), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (90, 90, 90), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    assert ok
    (HERE / "frame.jpg").write_bytes(buf.tobytes())
    det = {"ts": "2026-09-26T00:00:00", "ms": 41, "n": 1, "classes": {"person": 1},
           "boxes": [{"name": "person", "conf": 0.87, "xyxy": BOX}], "file": "lap1-boxed.jpg", "model": "yolo11n.pt",
           "note": "fixture: the box is where make.py drew the figure and 0.87 is a made-up conf; the shape is python -m wtdd.watch --once's stdout"}
    (HERE / "detect.json").write_text(json.dumps(det, indent=2) + "\n")
    print(f"frame.jpg {len(buf)} B  detect.json box {BOX}")


if __name__ == "__main__":
    main()
