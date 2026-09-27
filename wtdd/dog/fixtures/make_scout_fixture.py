"""The page's fixtures for the scout's proposed no-go zones (wtdd/dog/scout_zones.py, roadmap item 19): the exact GET
/dog/scout bodies the remote draws, written from the fixtures' declared world, never from the module's output, so the
remote can be screenshotted with no dog, no detector and no key. Nothing here has seen the real dog or a model.

    python -m wtdd.dog.fixtures.make_scout_fixture      rewrites scout.json and scout-failed.json next to this file

scout.json: one open proposal, z1, from make_objects_fixture's chair box (centred, FOV_DEG 90, the dog at POSE facing
+x): the chair's ray meets WALL_A of make_voxel_frames at (2.0, 0.0) m, and the proposal's cells are the WALL_A lattice
points inside the box's angular extent (its edge bearings, each widened by the half-cell angle atan(RES / 2 / d) at the
cell's distance d) and within [hit - RES, hit + DEPTH_M] of the dog: the 11 cells y = -0.25..0.25 m. The stub named it
(DEMO_CACHE: COCO "chair" -> "table", p = the detector's conf 0.71), so app is "stub" and the page says so. The poly is
the cells' corners in map px padded PAD_PX on every side (for this straight row, their bounding box grown by PAD_PX):
the rule the module states, re-derived here for one row of cells, so the test can check the page's contract (every
cell centre inside the poly, PAD_PX from its edge) independently of the module.
scout-failed.json: no proposal and one failed model call on the chair, the named failure the page draws in red
(19-failed.png). Its error text says "(fixture)": it is not a reply anyone received.

Serving either is a DEMO_CACHE path in the API (WTDD_SCOUT=<file>); the live path is the session's store fed by 07's
objects thread."""
from __future__ import annotations
import hashlib
import json
import math
import sys
from pathlib import Path

from PIL import Image

from .. import nav
from . import make_objects_fixture as ofx
from . import make_voxel_frames as fx

HERE = Path(__file__).resolve().parent
SCOUT_JSON = HERE / "scout.json"
SCOUT_FAILED_JSON = HERE / "scout-failed.json"
RES = fx.RES
DEPTH_M = 1.0      # the goal's bound: the fill stops this far behind the hit
PAD_PX = 15        # the goal's pad: > nogo.STEP_PX (10) so a route's samples cannot step over a one-cell-thin zone
WALL_A_X = fx.WALL_A["x"][0] * RES
WALL_A_KS = range(*fx.WALL_A["y"])       # the wall's lattice rows (y index), all seen in every frame
CHAIR = ofx.BOXES[0]
KEYS = ("id", "object_id", "kind", "label", "p", "app", "cells", "cells_px", "poly", "thumb", "photo", "dist_m", "area_m2", "ts")


def edge(u: float) -> float:
    """Pinhole bearing of image column u, right of the optical axis positive (objects.bearing's rule)."""
    return math.atan((u / ofx.W - 0.5) * 2 * math.tan(math.radians(ofx.FOV_DEG) / 2))


def chair_cells() -> list[list[float]]:
    hit = math.hypot(*CHAIR["hit_m"])
    lo, hi = edge(CHAIR["xyxy"][0]), edge(CHAIR["xyxy"][2])
    out = []
    for k in WALL_A_KS:
        x, y = WALL_A_X, round(k * RES, 6)
        d = math.hypot(x, y)
        a = -math.atan2(y, x)                # the dog faces +x (yaw 0): camera-right is a negative odometry angle
        eps = math.atan(RES / 2 / d)
        if lo - eps <= a <= hi + eps and hit - RES <= d <= hit + DEPTH_M:
            out.append([x, y])
    return out


def px(xy) -> list[int]:
    x, y, _ = nav.to_map(ofx.CAL, xy, 0.0)
    return [round(x), round(y)]


def write() -> list[Path]:
    cells = chair_cells()
    corners = [px((x + sx * RES / 2, y + sy * RES / 2)) for x, y in cells for sx in (-1, 1) for sy in (-1, 1)]
    x0, y0 = min(c[0] for c in corners) - PAD_PX, min(c[1] for c in corners) - PAD_PX
    x1, y1 = max(c[0] for c in corners) + PAD_PX, max(c[1] for c in corners) + PAD_PX
    img = Image.open(ofx.FRAME).convert("RGB")
    data = ofx.FRAME.read_bytes()
    prop = {"id": "z1", "object_id": "o1", "kind": CHAIR["name"], "label": "table", "p": CHAIR["conf"], "app": "stub",
            "cells": cells, "cells_px": [px(c) for c in cells], "poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
            "thumb": ofx.thumb(img, CHAIR["xyxy"]),
            "photo": {"path": "wtdd/dog/fixtures/frame.jpg", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
            "dist_m": round(math.hypot(*CHAIR["hit_m"]), 3), "area_m2": round(len(cells) * RES * RES, 4), "ts": ofx.TS}
    assert tuple(prop) == KEYS
    SCOUT_JSON.write_text(json.dumps({"n": 1, "proposals": [prop], "failed": [], "source": "wtdd/dog/fixtures/scout.json",
                                      "why": None}, indent=1) + "\n")
    failed = {"object_id": "o1", "kind": CHAIR["name"], "error": "RuntimeError: jev 401: (fixture) no auth credentials found", "ts": ofx.TS}
    SCOUT_FAILED_JSON.write_text(json.dumps({"n": 0, "proposals": [], "failed": [failed], "source": "wtdd/dog/fixtures/scout-failed.json",
                                             "why": "no proposal: 1 model call failed"}, indent=1) + "\n")
    return [SCOUT_JSON, SCOUT_FAILED_JSON]


def main() -> int:
    for p in write():
        print(f"wrote {p} ({p.stat().st_size} bytes)", file=sys.stderr)
    cells = chair_cells()
    print(f"chair: {len(cells)} cells on WALL_A, y {cells[0][1]}..{cells[-1][1]} m", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
