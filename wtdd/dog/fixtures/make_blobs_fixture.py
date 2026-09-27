"""Writes wtdd/dog/fixtures/blobs.json, the planted labels WTDD_BLOBS serves for the page's dry check of goal 16 (DEMO_CACHE,
wtdd/dog/session.py _labels_now). find() runs on goal 15's furnished room (voxel_furniture.npz, replayed through the
driver's own decoder), and three of its blobs, picked by the fixture's analytic truth and never by a model, get a record
in blobs.label()'s shape:
  the shelf's run   shelf at p 0.91: over the default WTDD_DECIDE_THRESHOLD 0.7, so GET /dog/floorplan greys it
  the far wall      wall at p 0.95: a wall word moves nothing
  the table         FAILED (label and p null, the planted error): a failed call is a red FAILED pin, never a word
model "fixture", source "fixture", no photo (crop_sha null), no time (ts null): nothing here saw a camera or a model,
and every cell is one the fixture's LiDAR saw. No ledger row (a fixture, not a step).

    python -m wtdd.dog.fixtures.make_blobs_fixture   rewrites blobs.json next to this file, one line per record
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from ...ledger import log
from .. import blobs, occupancy
from . import make_furniture_frames as ff

OUT = Path(__file__).with_name("blobs.json")
PLANTED = (("shelf", "run", "shelf", 0.91, None), ("wall_b", "run", "wall", 0.95, None),
           ("table", "blob", None, None, "RuntimeError: openrouter 502: bad gateway (planted)"))
TRUTH = {"shelf": ("shelf",), "wall_b": ("wall_b",), "table": ("table_top", "table_legs")}


def main() -> int:
    g = None
    for d in occupancy.replay(ff.NPZ):
        if g is None:
            g = occupancy.Grid.from_frame(d)
        g.update_frame(d)
    plan, res = blobs.find(g, occupancy.THRESHOLD), g.resolution
    out = []
    for name, kind, word, p, err in PLANTED:
        truth = set().union(*(ff.object_cells(n) for n in TRUTH[name]))
        (b,) = [x for x in plan["blobs"] if x["kind"] == kind and {(round(x_ / res), round(y_ / res)) for x_, y_ in x["cells"]} <= truth]
        r = {"blob_id": b["id"], "kind": kind, "cells": b["cells"], "xy": b["xy"], "geometry_verdict": b["geometry_verdict"],
             "label": word, "p": p, "model": "fixture", "erase": kind == "run" and word in blobs.FURNITURE and p >= 0.7,
             "source": "fixture", "crop_sha": None, "ts": None}
        out.append({**r, "error": err} if err else r)
        log("blobs", "planted", name=name, blob=b["id"], label=word, p=p, cells=len(b["cells"]), verdict=f"'{b['geometry_verdict']}'")
    OUT.write_text(json.dumps({"labels": out}) + "\n")
    log("blobs", "fixture written", file=OUT.name, labels=len(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
