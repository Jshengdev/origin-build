"""Blob labels: at a stop, every non-wall blob and every low wall run in the camera's view gets one typed word and a
probability from a photo of it; a furniture word moves the run off the wall layer; no label ever adds a cell, a line,
or opens or closes a gap. The shapes are goal 15's (wtdd/dog/floorplan.py, from the LiDAR's own cells), the words come
from models, and a model never draws: delete every model call here and nothing on the map moves, only names and colours.

Run. At a stop, POST /dog/blobs (the remote's "▶ name blobs") calls DogSession.blobs_label: the live frame
(snapshot()), the dog's odometry pose (body.state(), as 07's objects_state reads it), WTDD_CAM_FOV_DEG and a copy of the
session grid go into label_stop(). GET /dog/blobs serves the newest labels pinned on the map; GET /dog/floorplan serves
15's plan with those labels erased into it. One blob.labelled row per label, ok or FAILED; reads write no row.

How.
  find(grid)          15's _plan once, its classes and segments as they are, plus what a model may name: every wall run
                      whose top (the highest layer any of its cells was seen at) is below TALL, kind "run" (the shelf, a
                      far wall seen only low; a full-height wall is never offered), and every 8-connected group of tall,
                      slab and low cells, kind "blob". A read: no row, no model.
  bearing_to          07's bearing() reversed: the dog's position and yaw to the blob's centre, right of the camera positive.
  crop_box, crop      a full-height strip of the frame, a quarter of it wide, centred on the column a pinhole of
                      WTDD_CAM_FOV_DEG puts that bearing on (07's bearing() of the strip gives the bearing back), in 07's
                      thumb() shape (CROP_PX on its long side); the row names the sha256 of the JPEG the model saw.
  line                the blob in words with no digit (02's rule): how high, how long, grounded or floating, how far.
  label               the strip and the line to OpenRouter's vision model (llm.generate, agent blobs) for ONE word of
                      LABELS; that reply through Jev's Choice (decide._jev with this module's DESCRIBE and INSTRUCTIONS)
                      for {label, p}. Never decide.decide(): no `decided` row, nothing for 17's policy, never the chat, so
                      a label never escalates. A word off the list or a p outside [0, 1] is FAILED, and a FAILED label is
                      label None with the error, never a canned word.
  erase               a FURNITURE word at p >= WTDD_DECIDE_THRESHOLD on a run whose cells it covers more than half of:
                      that run's class-1 cells become class 3 (slab), except the ones a kept run also holds (the wall the
                      shelf stands against keeps its thickness), and its segment is dropped. Never a run whose top
                      reaches TALL in the plan given (15's `full`): a label kept from an earlier plan, where that run was
                      still low, is refused there, WARNed once. Nothing else ever changes: a label's cells outside the
                      run are never read, a wall word moves nothing, a word on a blob only names it, and the plan given
                      is never touched.
Env, read at the point of use: WTDD_BLOBS_LABEL (live, the default; stub, the DEMO_CACHE below; anything else fails
every label, WARN once), WTDD_DECIDE_THRESHOLD, WTDD_SHIFT; through llm and decide OPENROUTER_API_KEY,
OPENROUTER_VISION_MODEL, JEV_API_KEY, JEV_MODEL.

UNVERIFIED on the real dog: the camera's horizontal field of view (WTDD_CAM_FOV_DEG, 07's open item); the bearing's sign
on the real camera (right of the image = clockwise on the map); the camera sits about 0.3 m ahead of the odometry origin
and no offset is applied; the pose is read at the press, not when the frame was shot; the snapshot's framing (a pitched
or sitting dog moves the blob up or down, and the strip is a quarter of the frame wide, so a long shelf close up is only
partly in it); p is Jev's probability for the word, calibrated against nothing; a label made on one plan is matched to a
later plan's runs by majority cell overlap. Nothing here has run on the dog, and no accuracy number is claimed."""
from __future__ import annotations
import base64
import hashlib
import json
import math
import re
import time
from typing import Any, Callable

import numpy as np

from .. import config, decide, ledger
from ..ledger import log
from . import floorplan, objects, occupancy

LABELS = ("wall", "shelf", "table", "stack", "hazard", "person", "unknown")   # closed; `opening` is 17's escalate word, and a gap is geometry
FURNITURE = ("shelf", "table", "stack")   # the words that move a run off the wall layer, at p >= WTDD_DECIDE_THRESHOLD
CROP_PX = 384   # the strip's long side, px (07's thumb() at a size a vision model can read)
KINDS = {2: "tall blob", 3: "slab", 5: "low blob"}   # a blob's verdict names its majority class
HEIGHTS = ((0.3, "ankle high"), (0.6, "knee high"), (1.0, "waist high"), (1.5, "chest high"))   # top below -> words
DESCRIBE = {"wall": "a wall of the building itself: a flat surface from the floor up, part of the room",
            "shelf": "a shelf, a rack, a cabinet or a bookcase: furniture standing on the floor, often against a wall",
            "table": "a table, a desk or a counter: a flat top on legs",
            "stack": "a stack or a pile of boxes, crates, pallets or materials",
            "hazard": "something that can hurt someone: a spill, a loose cable, a hole, a trench, glass",
            "person": "someone is there",
            "unknown": "the words do not say what it is"}
INSTRUCTIONS = "A robot dog's camera model described one thing its LiDAR saw. Which word names that thing?"
ASK = f"Which one word from this list names the thing in the middle of the photo: {', '.join(LABELS)}? Reply with that one word only."
SYSTEM = ("You are a robot dog's eyes. You get a narrow vertical strip of its camera frame, cut where its LiDAR saw one "
          f"shape, and one line about that shape in words. Name the thing in the middle of the strip with one word from this list: "
          f"{', '.join(LABELS)}. Say unknown if the photo does not show it. Never say where walls are or what shape anything has.")
_warned: set[str] = set()   # WTDD_BLOBS_LABEL values already WARNed about (once each)
_refused: set[str] = set()   # erase's refusals already WARNed about: the reads re-erase every 2 s, one line each is enough


def find(grid: occupancy.Grid, threshold: int = occupancy.THRESHOLD, tall: float = floorplan.TALL) -> dict[str, Any]:
    """{cls, segments, runs, full, blobs, origin, resolution, threshold, why?}: cls, segments and full are floorplan._plan's
    own; runs are every segment's cells [[ix, iy]] (full-height walls included; erase reads them); blobs are what a model may name,
    each {id, kind run | blob, seg?, cells [[x, y]] metres, xy, top_m, length_m, grounded, geometry_verdict}. JSON as it
    stands, but cls. A read: no row, no model."""
    p = floorplan._plan(grid, threshold, tall)
    cls, r, (ox, oy) = p["cls"], grid.resolution, grid.origin

    def shape(a: np.ndarray) -> dict[str, Any]:   # a (m, 2) [ix, iy] -> its cells in metres, their centre, its top layer and height
        m = np.column_stack([ox + a[:, 0] * r, oy + a[:, 1] * r])
        top = int(np.bitwise_or.reduce(grid.zmask[a[:, 1], a[:, 0]])).bit_length() - 1   # the highest layer any cell was seen at
        return {"cells": [[round(float(x), 3), round(float(y), 3)] for x, y in m], "xy": [round(float(v), 3) for v in m.mean(axis=0)],
                "top": top, "top_m": round(float(grid.z_ref + top * r), 3)}

    blobs = []
    for k, (seg, run) in enumerate(zip(p["segments"], p["runs"])):
        if p["full"][k]:
            continue   # a full-height wall: never offered to a model, and never greyed (erase)
        s = shape(run)
        s.pop("top")
        length = round(math.dist(seg[:2], seg[2:4]) + r, 2)   # its cells end to end
        blobs.append({"id": f"r{k}", "kind": "run", "seg": k, **s, "length_m": length, "grounded": True,
                      "geometry_verdict": f"wall (grounded, straight {length:.1f} m, {s['top_m']:.1f} m high)"})
    iy, ix = np.nonzero(np.isin(cls, list(KINDS)))
    left = set(zip(ix.tolist(), iy.tolist()))
    for start in sorted(left, key=lambda c: (c[1], c[0])):   # row by row: the same grid gives the same ids
        if start not in left:
            continue
        left.discard(start)
        group, todo = [], [start]
        while todo:   # 8-connected
            x, y = todo.pop()
            group.append((x, y))
            for n in ((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                if n in left:
                    left.discard(n)
                    todo.append(n)
        a = np.array(sorted(group), dtype=np.int64)
        c = cls[a[:, 1], a[:, 0]]
        major = max(KINDS, key=lambda v: int((c == v).sum()))
        grounded = int((c == 3).sum()) * 2 <= len(a)   # slab cells are not the majority: it stands on the floor
        s = shape(a)
        s.pop("top")
        length = round(float(max(np.ptp(a[:, 0]), np.ptp(a[:, 1])) + 1) * r, 2)
        blobs.append({"id": f"b{sum(x['kind'] == 'blob' for x in blobs)}", "kind": "blob", **s, "length_m": length, "grounded": grounded,
                      "geometry_verdict": f"{KINDS[major]} ({'grounded' if grounded else 'floating'}, {length:.1f} m, {s['top_m']:.1f} m high)"})
    out = {"cls": cls, "segments": p["segments"], "runs": [run.tolist() for run in p["runs"]], "full": p["full"], "blobs": blobs,
           "origin": [float(ox), float(oy)], "resolution": r, "threshold": threshold}
    return {**out, "why": p["why"]} if p.get("why") else out


def bearing_to(xy, pose: dict) -> float:
    """Radians from the optical axis to xy, right positive, in (-pi, pi]: 07's ray leaves the position at yaw - bearing."""
    a = pose["yaw"] - math.atan2(xy[1] - pose["position"][1], xy[0] - pose["position"][0])
    return math.pi - (math.pi - a) % (2 * math.pi)


def crop_box(bearing: float, size, fov_deg: float) -> tuple[int, int, int, int]:
    """(x0, 0, x1, h): the full-height strip centred on the column a pinhole of fov_deg puts that bearing on, a quarter of
    the frame wide (32 px .. half the frame), narrower near an edge so it stays centred. ValueError outside the view."""
    w, h = size
    if fov_deg is None or not 0 < fov_deg < 180:
        raise ValueError(f"field of view must be in (0, 180) degrees, got {fov_deg}")
    half = math.radians(fov_deg) / 2
    if not abs(bearing) < half:
        raise ValueError(f"bearing {math.degrees(bearing):.1f} deg is outside the {fov_deg} deg field of view")
    u = w * (0.5 + math.tan(bearing) / (2 * math.tan(half)))
    hw = max(min(min(max(w // 4, 32), w // 2) / 2, u, w - u), 16)
    x0 = min(max(round(u - hw), 0), w - round(2 * hw))
    return x0, 0, x0 + round(2 * hw), h


def crop(img, box) -> tuple[str, str]:
    """(data:image/jpeg;base64 URL, sha256 hex of its JPEG bytes): the strip in 07's thumb() shape."""
    url = objects.thumb(img, box, width=CROP_PX)
    return url, hashlib.sha256(base64.b64decode(url.split(",", 1)[1])).hexdigest()


def _metres(m: float) -> str:
    n = round(m * 2) / 2
    if n < 0.5:
        return "less than half a metre"
    if n == 0.5:
        return "about half a metre"
    whole, and_half = int(n), n % 1 == 0.5
    return f"about {'a' if n == 1 else decide._word(whole)}{' and a half' if and_half else ''} metre{'s' if n > 1 else ''}"


def line(blob: dict, dist_m: float) -> str:
    """The one line the models get, in words: height, length, grounded or floating, distance. No digit, no newline."""
    high = next((w for top, w in HEIGHTS if blob["top_m"] < top), "head high or taller")
    s = (f"{'a straight run' if blob['kind'] == 'run' else 'a shape'} the LiDAR saw, {high}, {_metres(blob['length_m'])} long, "
         f"{'grounded, standing on the floor' if blob['grounded'] else 'floating, with nothing under it'}, {_metres(dist_m)} away")
    if re.search(r"[\d\n]", s):
        raise ValueError(f"a digit or a newline in the line to the models: {s!r}")
    return s


def _vision(url: str, said: str) -> dict[str, Any]:
    """One llm.generate (agent blobs, the vision model: one image part) for one word. Raises on an empty reply."""
    from ..llm import generate   # at call time, as 07's draft_live: a patch of wtdd.llm.generate reaches it
    out = generate("blobs", [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": [{"type": "text", "text": f"{said}. {ASK}"},
                                                          {"type": "image_url", "image_url": {"url": url}}]}],
                   max_tokens=20, temperature=0.0)
    text = " ".join(out["text"].split())
    if not text:
        raise RuntimeError(f"vision model returned an empty reply (model={out['model']})")
    return {"text": text, "model": out["model"]}


def _choose(text: str, labels: list[str]) -> tuple[str, float, str, str]:
    """The vision reply typed by Jev's Choice over the closed list: decide._jev, looked up at call time, never decide()."""
    return decide._jev(decide._dedigit(text), list(labels), DESCRIBE, INSTRUCTIONS)


def label(blob: dict, img, pose: dict, fov_deg: float, *, vision: Callable | None = None, choose: Callable | None = None) -> dict[str, Any]:
    """{blob_id, kind, cells, xy, geometry_verdict, label, p, model, erase, source, crop_sha, ts, error?} and one
    blob.labelled row. Never raises for a model's failure: that is the FAILED row and label None, p None, error."""
    mode = config.maybe("WTDD_BLOBS_LABEL") or "live"
    stub = mode == "stub"
    if mode not in ("live", "stub") and mode not in _warned:
        _warned.add(mode)
        log("blobs", "WARN WTDD_BLOBS_LABEL is neither live nor stub: every label FAILED", value=mode)
    out = {"blob_id": blob["id"], "kind": blob["kind"], "cells": blob["cells"], "xy": blob["xy"], "geometry_verdict": blob["geometry_verdict"],
           "label": None, "p": None, "model": None, "erase": False, "source": "stub" if stub else "live", "crop_sha": None}
    args = {"blob_id": blob["id"], "kind": blob["kind"], "cells": len(blob["cells"]), "geometry_verdict": blob["geometry_verdict"],
            "crop_sha": None, "line": None, "bearing_deg": None, "dist_m": None, "fov_deg": fov_deg, "threshold": None, "shift_id": decide.shift_id()}
    try:
        with ledger.step("blobs", "blob.labelled", "stub" if stub else "openrouter", args, {"geometry_verdict": blob["geometry_verdict"]}) as r:
            if stub:
                r["cached"], r["source"] = True, "stub"
            elif mode != "live":
                raise ValueError(f"WTDD_BLOBS_LABEL={mode!r} is neither live nor stub: no model was called")
            args["threshold"] = thr = decide.threshold()
            b = bearing_to(blob["xy"], pose)
            args["bearing_deg"], args["dist_m"] = round(math.degrees(b), 1), round(math.dist(pose["position"][:2], blob["xy"]), 2)
            url, args["crop_sha"] = crop(img, crop_box(b, img.size, fov_deg))
            args["line"] = said = line(blob, args["dist_m"])
            if stub:
                # DEMO_CACHE: the label. What: "unknown" at p 0 for every blob, no model called (so nothing ever moves).
                # Why: no OPENROUTER or JEV key in a worktree, and a dry take that must not wait on a model. Live:
                # WTDD_BLOBS_LABEL=live (the default) with OPENROUTER_API_KEY and JEV_API_KEY set: one llm.generate row
                # and one Jev Choice per blob. This row says cached=true, source=stub, app stub; the page says "stub".
                lab, p, model, vmodel, raw = "unknown", 0.0, "stub", None, "stub: no model (DEMO_CACHE, WTDD_BLOBS_LABEL=stub)"
            else:
                v = (vision or _vision)(url, said)
                lab, p, model, jraw = (choose or _choose)(v["text"], list(LABELS))
                try:
                    jev = json.loads(jraw)
                except (TypeError, ValueError):
                    jev = str(jraw)[:2000]
                vmodel, raw = v.get("model"), json.dumps({"vision": v["text"], "jev": jev})
            if lab not in LABELS or isinstance(p, bool) or not isinstance(p, (int, float)) or not 0.0 <= p <= 1.0:
                raise ValueError(f"label out of contract: label={lab!r} (the closed list: {', '.join(LABELS)}), p={p!r}")
            p = round(float(p), 3)
            er = blob["kind"] == "run" and lab in FURNITURE and p >= thr
            r["state_after"] = {"label": lab, "p": p, "model": model, "vision_model": vmodel, "erase": er}
            r["response_or_error"] = raw
        out.update(label=lab, p=p, model=model, erase=er)
    except Exception as e:  # noqa: BLE001  (its FAILED row is written; the label is None with the error, never a canned word)
        out["error"] = f"{type(e).__name__}: {e}"
        log("blobs", "WARN label FAILED", blob=blob["id"], err=out["error"][:160])
    out["crop_sha"], out["ts"] = args["crop_sha"], time.strftime("%Y-%m-%dT%H:%M:%S")
    return out


def label_stop(grid: occupancy.Grid, img, pose: dict, fov_deg: float, threshold: int = occupancy.THRESHOLD, *,
               vision: Callable | None = None, choose: Callable | None = None) -> dict[str, Any]:
    """{plan, labels, skipped}: find(), then label() for every blob whose centre is inside the field of view; the rest are
    skipped with no row. One `[wtdd:blobs] stop` line; nothing in view, or a FAILED label, is a WARN."""
    if fov_deg is None or not 0 < fov_deg < 180:
        raise ValueError(f"field of view must be in (0, 180) degrees, got {fov_deg}")
    t0 = time.perf_counter()
    plan = find(grid, threshold)
    labels, skipped = [], []
    for b in plan["blobs"]:
        if abs(bearing_to(b["xy"], pose)) < math.radians(fov_deg) / 2:
            labels.append(label(b, img, pose, fov_deg, vision=vision, choose=choose))
        else:
            skipped.append(b["id"])
    failed = sum(1 for x in labels if x.get("error"))
    log("blobs", ("WARN " if not labels or failed else "") + "stop", labelled=len(labels), skipped=len(skipped), failed=failed,
        blobs=len(plan["blobs"]), fov_deg=fov_deg, ms=round((time.perf_counter() - t0) * 1000))
    return {"plan": plan, "labels": labels, "skipped": skipped}


def erase(plan: dict, labels: list[dict], threshold: float | None = None) -> dict[str, Any]:
    """A new plan {**plan, cls, segments, runs, full, moved, refused, erased}: every run a FURNITURE label at p >= threshold
    (default WTDD_DECIDE_THRESHOLD) covers more than half of goes from class 1 to class 3, but for the cells a kept run
    also holds, and its segment is dropped; moved lists "r<k>". A run whose plan["full"] is True (its top reaches TALL:
    a full-height wall) is never moved, whatever a label kept from an earlier plan says: it is listed in refused and
    WARNed once. erased[i] says whether labels[i] moved a run in this plan (GET /dog/blobs serves it as the label's
    erase). A label off the list is a ValueError. Nothing else changes."""
    bad = [x.get("label") for x in labels if x.get("label") is not None and x.get("label") not in LABELS]
    if bad:
        raise ValueError(f"labels off the closed list ({', '.join(LABELS)}): {bad}")
    thr = decide.threshold() if threshold is None else threshold
    r, (ox, oy) = plan["resolution"], plan["origin"]
    runs = [{(int(a), int(b)) for a, b in np.asarray(x, dtype=np.int64).reshape(-1, 2)} for x in plan["runs"]]
    covers = []   # per label, the runs it names: a furniture word over the threshold on more than half of a run's cells
    for lab in labels:
        s = ({(round((x - ox) / r), round((y - oy) / r)) for x, y in lab["cells"]}
             if lab.get("kind") == "run" and lab.get("label") in FURNITURE and lab.get("p") is not None and lab["p"] >= thr else set())
        covers.append([k for k, run in enumerate(runs) if len(run & s) * 2 > len(run)])
    gone = sorted({k for c in covers for k in c if not plan["full"][k]})
    refused = sorted({k for c in covers for k in c if plan["full"][k]})
    for lab, c in zip(labels, covers):
        for k in c:
            if plan["full"][k] and (key := f"{lab.get('blob_id')} {lab['label']} {lab['p']} r{k} {len(runs[k])}") not in _refused:
                _refused.add(key)
                log("blobs", "WARN erase refused: a furniture word on a full-height wall run, which stays a wall",
                    blob=lab.get("blob_id"), label=lab["label"], p=lab["p"], run=f"r{k}", cells=len(runs[k]))
    kept = set().union(*(run for k, run in enumerate(runs) if k not in gone))
    cls = plan["cls"].copy()
    for a, b in set().union(*(runs[k] for k in gone)) - kept:
        if cls[b, a] == 1:
            cls[b, a] = 3
    return {**plan, "cls": cls, "segments": [s for k, s in enumerate(plan["segments"]) if k not in gone],
            "runs": [x for k, x in enumerate(plan["runs"]) if k not in gone], "full": [f for k, f in enumerate(plan["full"]) if k not in gone],
            "moved": [f"r{k}" for k in gone], "refused": [f"r{k}" for k in refused], "erased": [any(k in gone for k in c) for c in covers]}
