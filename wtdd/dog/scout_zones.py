"""The scout's proposed no-go zones: every thing 07 pins on the grid is asked once whether it is a hazard; a hazard
becomes a PROPOSED zone made of the LiDAR cells it sits on, with the photo, the label and p; only a named person's tap
makes it a rule, written into 04's `nogo: true` schema on ui/map.json. A proposal refuses nothing: the walk and the
follower read only the map (04's nogo.refuse(), untouched), and a proposal is never on the map.

Run. The API's dog session (wtdd/dog/session.py) owns one Proposals store; its 'objects' thread feeds it 07's objects
after every detector window (session.scout_feed), GET /dog/scout reads it, POST /dog/scout {id, action: confirm |
dismiss, by, _version} is the person's tap. Offline:

    python -m wtdd.dog.scout_zones --replay wtdd/dog/fixtures/voxel_frames.npz --watch wtdd/dog/fixtures/watch-frame.json \\
        --pose 0,0,0 --fov 90 --png /tmp/scout.png [--threshold N]

builds the grid from the replayed frames, places the fixture's boxes with 07's store, asks the stub (never Jev, even with
a key), and writes the occupancy PNG with every proposed cell a PNG_SCALE square in CELL_RGB: one stderr line per row
it would have written and a summary, exit 2 with a WARN when nothing is proposed. It writes no ledger row.

How. blob(): the cells seen threshold+ times, flood-filled 8-connected from 07's hit cell, keeping a cell only when its
bearing from the dog lies inside the box's angular extent (objects.bearing of the box's left and right columns, each
widened by the half-cell angle atan(res / 2 / d) at the cell's distance d) and d lies in [hit - res, hit + DEPTH_M].
Unbounded, the fill takes the whole wall the thing stands against. polygon(): the cells' corners (+-res/2) in map px
through occupancy.to_map_px, each grown by a PAD_PX square (a Minkowski sum, so every edge moves out by PAD_PX and 04's
hit(), which samples a route every STEP_PX = 10 px, cannot step over a one-cell-thin zone), then Andrew's monotone-chain
hull. The pad is a stated rule on points, drawn dashed on the remote; it is not a shape any model drew. The question:
one Jev (TypeSafe System One) Choice over SCOUT_LABELS with a words-only state (no digits: 02's rule), 02's _jev
vendored as decide_live, or the DEMO_CACHE stub below when JEV_API_KEY is unset; the call runs outside every lock and is
its own zone.decided row, ok or not (never `decided`: 11's grade_decide owns that name). A choice other than
not_a_hazard at p >= WTDD_DECIDE_THRESHOLD (default 0.7) is one zone.proposed row and an open proposal "z<n>" whose photo
is the detector frame copied once to ~/Pictures/wtdd with its sha256. A thing is asked once (07's object id); a thing
whose cells overlap an open proposal, a dismissed one or a scout zone already on the map is the same thing (logged, no
call, no row). A failed call, an unreadable frame or an empty blob is a failed row and a line in state()["failed"],
never a canned label, never retried. confirm(id, by) follows POST /map's rules (a stale _version is 409, the previous
map kept as map.prev.json) and nogo.zones() must accept the entry first; every refusal is a failed zone.confirmed row
before anything is written.

UNVERIFIED on the real dog (the first live run must confirm): everything 07 lists (the camera's field of view, the
bearing's sign, one odometry for the voxel frame and the pose); the cone uses the pose when the scout is fed, not when
the detector's frame was shot; the photo is the newest watch frame, which the detector may already have replaced since
the window 07 placed; a table touching a wall brings the wall's cells inside the cone along (the person sees the cells
and the photo, and decides); positive obstacles only: COCO has no hole or trench and the grid's z band has no floor, so
an opening is always drawn by a person (04). The live Jev call has not been run with a key (02's own UNVERIFIED)."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import json
import math
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import requests

from .. import config, field, nogo
from ..ledger import append as ledger_append, log
from . import objects, occupancy

DEPTH_M = 1.0      # the fill stops this far behind 07's hit (the head's bound)
PAD_PX = 15        # every side of the hull grows this much: > nogo.STEP_PX (10) so hit() cannot step over it
SCOUT_LABELS = ["table", "sharp_object", "blocked_way", "not_a_hazard"]   # no "opening": a hole is never proposed from a photo
CRITERIA = {"table": "a table, bench or chair standing where the dog or a person walks, something to bump into",
            "sharp_object": "a knife, scissors or anything with a blade or a point lying where people or the dog pass",
            "blocked_way": "something standing across a walkway or a door that closes the way through",
            "not_a_hazard": "a thing that is out of the way, that nothing walks into and nothing is cut by"}
QUESTION = "hazard"
INSTRUCTIONS = "A robot dog on a night round of a site saw this thing with its camera and its LiDAR. Is it a hazard to walk into?"
JEV_URL = "https://openrouter.ai/api/v1/systemone"   # 02's decide.py, vendored until 02 (or 17's choose) merges
JEV_TIMEOUT_S = 20.0
DEFAULT_MODEL = "typesafe/jev-1.13"
NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
           "seventeen eighteen nineteen twenty").split()
TABLE_KINDS, SHARP_KINDS = {"dining table", "bench", "chair"}, {"knife", "scissors"}
PHOTOS = Path.home() / "Pictures" / "wtdd"
CELL_RGB = (220, 38, 38)   # the replay PNG's proposed cells
PROPOSAL_KEYS = ("id", "object_id", "kind", "label", "p", "app", "cells", "cells_px", "poly", "thumb", "photo", "dist_m",
                 "area_m2", "ts")


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _key(cells) -> set:
    """Lattice points as a set, rounded to the millimetre: two things sharing one counted cell are the same thing."""
    return {(round(c[0], 3), round(c[1], 3)) for c in cells}


def blob(grid: occupancy.Grid, pose: dict, box, hit: dict, frame_w: float, fov_deg: float,
         threshold: int = occupancy.THRESHOLD) -> list[list[float]]:
    """The thing's own counted cells as sorted lattice points [[x_m, y_m], ...] (see the module docstring for the
    bound); [] when 07's hit cell itself falls outside it (the dog moved since the pin). Pure: the caller holds the
    grid's lock."""
    if threshold < 1:
        raise ValueError(f"threshold must be at least 1 frame, got {threshold}")
    lo = objects.bearing([box[0], 0, box[0], 0], frame_w, fov_deg)
    hi = objects.bearing([box[2], 0, box[2], 0], frame_w, fov_deg)
    res, (ox, oy), (px, py), yaw = grid.resolution, grid.origin, pose["position"][:2], pose["yaw"]
    near, far = hit["dist_m"] - res, hit["dist_m"] + DEPTH_M
    h, w = grid.counts.shape

    def keep(i: int, j: int) -> bool:
        if not (0 <= i < w and 0 <= j < h) or grid.counts[j, i] < threshold:
            return False
        dx, dy = ox + i * res - px, oy + j * res - py
        d = math.hypot(dx, dy)
        if d <= 0 or not near <= d <= far:
            return False
        b, eps = -_wrap(math.atan2(dy, dx) - yaw), math.atan(res / 2 / d)   # camera-right positive, as objects.bearing
        return lo - eps <= b <= hi + eps

    seed = (int(np.rint((hit["xy"][0] - ox) / res)), int(np.rint((hit["xy"][1] - oy) / res)))
    if not keep(*seed):
        return []
    seen, stack = {seed}, [seed]
    while stack:
        i, j = stack.pop()
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                n = (i + di, j + dj)
                if n not in seen and keep(*n):
                    seen.add(n)
                    stack.append(n)
    return sorted([round(ox + i * res, 6), round(oy + j * res, 6)] for i, j in seen)


def polygon(cells, cal: dict, resolution: float) -> list[list[int]]:
    """The padded monotone-chain hull of the cells' corners in map px, plain ints, >= 3 points. No cells: ValueError."""
    if not len(cells):
        raise ValueError("no cells: a zone is made of counted cells, never drawn empty")
    r = resolution / 2
    corners = occupancy.to_map_px([[x + sx * r, y + sy * r] for x, y in cells for sx in (-1, 1) for sy in (-1, 1)], cal)
    pts = sorted({(int(cx + ax), int(cy + ay)) for cx, cy in corners.tolist() for ax in (-PAD_PX, PAD_PX) for ay in (-PAD_PX, PAD_PX)})

    def half(seq):
        out: list[tuple[int, int]] = []
        for p in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]
    return [list(p) for p in half(pts) + half(pts[::-1])]


# DEMO_CACHE: the scout's hazard answer. What: COCO names mapped to a scout label (dining table, bench, chair -> table;
# knife, scissors -> sharp_object; anything else -> not_a_hazard) with p = the detector's own confidence, raw
# "stub: <kind> -> <label>". Why: no JEV_API_KEY in a worktree, and the dry screenshot and the replay must reach a
# proposal without a model. Live: set JEV_API_KEY in .env; decider() then picks decide_live, one Jev call per thing.
# Its zone.decided and zone.proposed rows say cached=true, source=stub, and the remote says "stub" beside the proposal.
def decide_stub(q: dict) -> dict[str, Any]:
    kind = q["kind"]
    label = "table" if kind in TABLE_KINDS else "sharp_object" if kind in SHARP_KINDS else "not_a_hazard"
    if label not in q["labels"]:
        raise ValueError(f"stub label {label!r} is not among {q['labels']}")
    p = float(q["conf"])
    return {"label": label, "p": p, "probabilities": {label: p}, "model": None,
            "raw": f"stub: {kind} -> {label} (p is the detector's conf)", "app": "stub", "cached": True}


def decide_live(q: dict) -> dict[str, Any]:
    """One System One Choice request over q["labels"] (02's _jev, vendored): the chosen label and the probability Jev
    gives it (never `confidence`). Non-200, a reply that is not a choice, a choice outside the labels or a p outside
    [0, 1] raise. One request, no retry, no fallback to the stub."""
    model = config.maybe("JEV_MODEL") or DEFAULT_MODEL
    body = {"state": q["state"], "model": model,
            "questions": {QUESTION: {"type": "choice", "instructions": INSTRUCTIONS,
                                     "criteria": {c: CRITERIA.get(c, c.replace("_", " ")) for c in q["labels"]}}}}
    resp = requests.post(JEV_URL, headers={"Authorization": f"Bearer {config.get('JEV_API_KEY')}", "Content-Type": "application/json"},
                         json=body, timeout=JEV_TIMEOUT_S)
    if resp.status_code != 200:
        raise RuntimeError(f"jev {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        answer = data["answers"][QUESTION]
        label = str(answer["choice"])
        probs = {str(k): float(v) for k, v in answer["probabilities"].items()}
        p = probs[label]
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise RuntimeError(f"jev reply is not a System One choice ({type(e).__name__}: {e}): {resp.text[:300]!r}") from None
    if label not in q["labels"] or not 0.0 <= p <= 1.0:
        raise RuntimeError(f"jev answered out of contract: choice {label!r} (labels {q['labels']}), p {p!r}")
    return {"label": label, "p": p, "probabilities": probs, "model": str(data.get("model") or model), "raw": resp.text,
            "app": "openrouter", "cached": False}


def decider() -> Callable[[dict], dict]:
    """decide_live when JEV_API_KEY is set, else decide_stub (read here, at the point of use; logged)."""
    live = bool(config.maybe("JEV_API_KEY"))
    log("scout", "decides " + ("live (one Jev call per thing)" if live else "stub (DEMO_CACHE: COCO name -> label, p = the detector's conf; rows cached=true)"))
    return decide_live if live else decide_stub


def decide_threshold() -> float:
    """WTDD_DECIDE_THRESHOLD (02's threshold(), the same key and rule): default 0.7; not a number in [0, 1] is a
    ValueError."""
    v = config.maybe("WTDD_DECIDE_THRESHOLD") or "0.7"
    try:
        t = float(v)
    except ValueError:
        raise ValueError(f"WTDD_DECIDE_THRESHOLD={v!r} is not a number in [0, 1]") from None
    if not 0.0 <= t <= 1.0:
        raise ValueError(f"WTDD_DECIDE_THRESHOLD={v!r} is not in [0, 1]")
    return t


def shift_id() -> str:
    return config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")


def words(kind: str, conf: float, dist_m: float | None, bearing_deg: float | None, area_m2: float) -> str:
    """The state Jev reads: words only (no digits, 02's rule), naming the kind."""
    n = None if dist_m is None else round(dist_m)
    far = ("at an unknown distance" if n is None else "less than a metre" if n < 1 else
           f"about {NUMBERS[n] if n < len(NUMBERS) else 'many'} metre{'' if n == 1 else 's'}")
    side = "" if bearing_deg is None or abs(bearing_deg) < 10 else f" and to the {'right' if bearing_deg > 0 else 'left'}"
    s = (f"the detector boxed a {kind} with probability {'high' if conf >= 0.7 else 'medium' if conf >= 0.4 else 'low'}, "
         f"{far} ahead{side}, footprint {'small' if area_m2 < 0.1 else 'medium' if area_m2 < 0.5 else 'large'}, "
         f"against cells the lidar has counted")
    if re.search(r"\d", s):
        raise ValueError(f"the state for Jev must be words only: {s!r}")
    return s


class Refused(Exception):
    """A person's tap the store will not apply: code 400 (no name, a malformed zone), 404 (no open proposal), 409 (a
    stale page). Its failed row is already written."""

    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code


class Proposals:
    """The scout's open proposals this session, insertion-ordered (see the module docstring for the rules)."""

    def __init__(self, append: Callable[[dict], Any] = ledger_append, decide: Callable[[dict], dict] | None = None,
                 photo_dir=None, map_path=None) -> None:
        self.append, self.decide = append, decide
        self.photo_dir = Path(photo_dir) if photo_dir else None   # None: PHOTOS, read at the write
        self.map_path = Path(map_path) if map_path else None      # None: field.MAP, read at call time
        self.open: dict[str, dict[str, Any]] = {}
        self.dismissed: list[tuple] = []     # (id, cells) of every proposal a person said no to, this session
        self.handled: set[str] = set()       # 07's object ids already taken (asked, deduped or failed): never again
        self.failed: list[dict[str, Any]] = []
        self.n_ids = 0
        self.counts = {"asked": 0, "proposed": 0, "confirmed": 0, "dismissed": 0, "deduped": 0}
        self.thr: float | None = None        # the threshold of the last feed, for state()'s why
        self._warned: str | None = None
        self._lock = threading.Lock()        # this store's own state; never held during the model call

    def _map(self) -> Path:
        return self.map_path or field.MAP

    def feed(self, objs: list[dict], frame: dict, pose: dict | None, grid: occupancy.Grid | None, cal: dict | None,
             fov_deg: float | None, threshold: int = occupancy.THRESHOLD, grid_lock=None) -> dict[str, int]:
        """Every placed object not handled before is handled once (see the module docstring); returns the counts."""
        t_all = time.perf_counter()
        with self._lock:
            cands = [o for o in objs if o.get("pos_px") is not None and o.get("hit_m") is not None and o["id"] not in self.handled]
        n = {"handled": 0, "decided": 0, "proposed": 0, "failed": 0, "deduped": 0}
        if not cands:
            return n
        missing = [k for k, v in (("pose", pose), ("grid", grid), ("calibration", cal), ("field of view", fov_deg)) if v is None]
        if missing:   # taken again when they are back: 07 placed these, the scout cannot see them now
            why = f"WARN {len(cands)} placed object(s) waiting: no {', no '.join(missing)}"
            if why != self._warned:
                log("scout", why)
            self._warned = why
            return n
        self._warned = None
        thr = self.thr = decide_threshold()
        on_map = [(z.get("name"), _key(z["cells"])) for z in json.loads(self._map().read_text()).get("zones", [])
                  if z.get("source") == "scout" and z.get("cells")]   # a person already made these rules
        with self._lock:
            self.handled.update(o["id"] for o in cands)
        n["handled"] = len(cands)
        try:
            data = Path(frame["file"]).read_bytes()
            from PIL import Image
            width = Image.open(io.BytesIO(data)).width
        except (OSError, KeyError, TypeError) as e:
            err = f"frame unreadable, no photo and no question: {type(e).__name__}: {e} (watch.json file {frame.get('file')})"
            for o in cands:
                self._fail(o, "frame read", err)
                self._row("zone.proposed", "map", {"object_id": o["id"], "kind": o["label"]}, None, None, False, err, 0)
            n["failed"] = len(cands)
            return self._summary(n, t_all)
        fn = self.decide or decider()
        for o in cands:
            t0 = time.perf_counter()
            try:
                with grid_lock or contextlib.nullcontext():
                    res = grid.resolution
                    cells = blob(grid, pose, o["box"], {"xy": o["hit_m"], "dist_m": o["dist_m"]}, width, fov_deg, threshold)
                    poly = polygon(cells, cal, res) if cells else None
            except Exception as e:  # noqa: BLE001  (a failed row and a failed line, never a zone of no cells)
                cells, poly, err = [], None, f"blob FAILED: {type(e).__name__}: {e}"
            else:
                err = None if cells else (f"no cell seen {threshold}+ times inside the box's cone within {DEPTH_M} m of the hit "
                                          f"from the pose now (the dog moved since 07 placed it?)")
            if err:
                self._fail(o, "cells", err)
                self._row("zone.proposed", "map", {"object_id": o["id"], "kind": o["label"]}, None, None, False, err,
                          round((time.perf_counter() - t0) * 1000))
                n["failed"] += 1
                continue
            key = _key(cells)
            with self._lock:
                same = (next((z["id"] for z in self.open.values() if key & _key(z["cells"])), None)
                        or next((f"{name} (dismissed)" for name, d in self.dismissed if key & d), None)
                        or next((f"{name} on the map" for name, c in on_map if key & c), None))
                if same:
                    self.counts["deduped"] += 1
            if same:
                log("scout", f"{o['id']} is the same thing as {same}: no call, no row", kind=o["label"], cells=len(cells))
                n["deduped"] += 1
                continue
            blob_ms = round((time.perf_counter() - t0) * 1000)
            area = round(len(cells) * res * res, 4)
            q = {"kind": o["label"], "conf": o["p"], "state": None, "labels": list(SCOUT_LABELS)}
            t1 = time.perf_counter()
            try:   # outside every lock: a model call can take seconds
                q["state"] = words(o["label"], o["p"], o["dist_m"], o.get("bearing_deg"), area)
                d, derr = fn(q), None
                if d["label"] not in SCOUT_LABELS or not 0.0 <= float(d["p"]) <= 1.0:
                    raise ValueError(f"decision out of contract: label {d['label']!r}, p {d['p']!r}")
            except Exception as e:  # noqa: BLE001  (its own failed zone.decided row, no proposal, never retried)
                d, derr = None, f"{type(e).__name__}: {e}"
            ms = round((time.perf_counter() - t1) * 1000)
            stub = bool(d["cached"]) if d else fn is decide_stub
            app = d["app"] if d else ("stub" if fn is decide_stub else "openrouter")
            got = {"label": d["label"], "p": float(d["p"]), "model": d["model"]} if d else {"label": None, "p": None, "model": None}
            self._row("zone.decided", app, {"object_id": o["id"], "kind": o["label"], "labels": list(SCOUT_LABELS), **got,
                                            "probabilities": d["probabilities"] if d else None, "threshold": thr},
                      {"state": q["state"], "labels": list(SCOUT_LABELS)}, got if d else None, d is not None,
                      d["raw"] if d else derr, ms, stub)
            if d is None:
                self._fail(o, None, derr)
                n["failed"] += 1
                continue
            n["decided"] += 1
            with self._lock:
                self.counts["asked"] += 1
            if d["label"] == "not_a_hazard" or float(d["p"]) < thr:
                log("scout", f"{o['id']} stays a pin: {d['label']} at p {float(d['p']):.2f} (threshold {thr})", kind=o["label"])
                continue
            with self._lock:
                self.n_ids += 1
                zid = f"z{self.n_ids}"
            t2 = time.perf_counter()
            try:
                pdir = self.photo_dir or PHOTOS
                pdir.mkdir(parents=True, exist_ok=True)
                f = pdir / f"scout-{time.strftime('%Y%m%dT%H%M%S')}-{zid}.jpg"
                f.write_bytes(data)
            except OSError as e:
                err = f"photo not written, no proposal: {type(e).__name__}: {e}"
                self._fail(o, "photo write", err)
                self._row("zone.proposed", "map", {"id": zid, "object_id": o["id"], "kind": o["label"]}, None, None, False, err, 0, stub)
                n["failed"] += 1
                continue
            z = {"id": zid, "object_id": o["id"], "kind": o["label"], "label": d["label"], "p": float(d["p"]), "app": app,
                 "cells": cells, "cells_px": occupancy.to_map_px(cells, cal).tolist(), "poly": poly, "thumb": o.get("thumb"),
                 "photo": {"path": str(f), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
                 "dist_m": o["dist_m"], "area_m2": area, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
            with self._lock:
                self.open[zid] = z
                self.counts["proposed"] += 1
            self._row("zone.proposed", app, {"id": zid, "object_id": o["id"], "kind": o["label"], "label": z["label"], "p": z["p"],
                                             "cells": cells, "cells_n": len(cells), "poly": poly, "photo": z["photo"],
                                             "dist_m": z["dist_m"], "area_m2": area},
                      {"decided": got}, {"open": len(self.open)}, True,
                      f"proposed {zid}: {len(cells)} cells, {z['label']} at p {z['p']:.2f}, {z['dist_m']} m",
                      blob_ms + round((time.perf_counter() - t2) * 1000), stub)   # the cells and the photo; the call is its own row's
            n["proposed"] += 1
        return self._summary(n, t_all)

    def _summary(self, n: dict, t_all: float) -> dict[str, int]:
        log("scout", f"{'WARN ' if n['handled'] and not n['proposed'] else ''}feed", **n, open=len(self.open),
            ms=round((time.perf_counter() - t_all) * 1000))
        return n

    def _fail(self, o: dict, stage: str | None, err: str) -> None:
        f = {"object_id": o["id"], "kind": o["label"], "error": err, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if stage:   # absent: the model call failed (the contract's four keys); else what failed before any call
            f["stage"] = stage
        with self._lock:
            self.failed.append(f)

    def _row(self, tool: str, app: str, args: dict, before: Any, after: Any, ok: bool, resp: Any, ms: int, stub: bool = False) -> None:
        row = {"step": tool, "agent": "scout", "tool": tool, "app": app, "args": {**args, "shift_id": shift_id()},
               "state_before": before, "state_after": after, "ok": ok, "response_or_error": resp, "latency_ms": int(ms)}
        if stub:
            row.update(cached=True, source="stub")
        self.append(row)
        kv = {k: args[k] for k in ("id", "object_id", "zone", "label", "p", "by") if args.get(k) is not None}
        log("scout", f"{tool} ok={ok}", app=app, **kv, **({} if ok else {"err": str(resp)[:160]}), ms=int(ms))

    def _tap(self, tool: str, zid: str, by: Any, t0: float, fn: Callable[[dict, str], tuple[dict, Any]]) -> dict[str, Any]:
        """A person's confirm or dismiss under the store's lock: a name and an open id first, then fn(proposal, by) ->
        (out, state_after); one row either way, the failed one written before the raise."""
        by = str(by or "").strip()
        with self._lock:
            z = self.open.get(zid)
            before = None if z is None else {k: v for k, v in z.items() if k != "thumb"}
            args = {"id": zid, **({"zone": None} if tool == "zone.confirmed" else {}), "by": by}
            try:
                if not by:
                    raise Refused(400, f"{'a confirm' if tool == 'zone.confirmed' else 'a dismiss'} needs the name of the person making it (by)")
                if z is None:
                    raise Refused(404, f"no open proposal {zid!r} (open: {', '.join(self.open) or 'none'})")
                out, after = fn(z, by)
            except Exception as e:
                self._row(tool, "map", args, before, None, False, f"{type(e).__name__}: {e}", round((time.perf_counter() - t0) * 1000))
                raise
            del self.open[zid]
            self.counts[tool.split(".")[1]] += 1
            if tool == "zone.confirmed":
                args["zone"] = out["zone"]["name"]
            self._row(tool, "map", args, before, after, True, out.get("say"), round((time.perf_counter() - t0) * 1000))
        return {k: v for k, v in out.items() if k != "say"}

    def confirm(self, zid: str, by: Any, version: Any = None) -> dict[str, Any]:
        """The proposal becomes 04's no-go zone on ui/map.json (see the module docstring); {ok, zone, _version}."""
        def write(z: dict, by: str) -> tuple[dict, Any]:
            mp = self._map()
            if version is not None and int(mp.stat().st_mtime) != int(version):   # POST /map's rule: a stale page never overwrites
                raise Refused(409, f"not confirmed: the map changed on the server since this page loaded (page {version}, "
                                   f"file {int(mp.stat().st_mtime)}). Reload the page, then confirm again.")
            old = mp.read_text()
            m = json.loads(old)
            zones = list(m.get("zones") or [])
            names, k = {x.get("name") for x in zones}, sum(1 for x in zones if x.get("nogo") is True) + 1
            while f"nogo-{k}" in names:   # NoGoButtons' rule: the next free nogo-<n>
                k += 1
            entry = {"name": f"nogo-{k}", "label": f"{z['label']} · {z['p']:.2f} · scout", "poly": z["poly"], "nogo": True,
                     "source": "scout", "cells": z["cells"], "proposal": z["id"], "by": by}
            m["zones"] = zones + [entry]
            try:
                nogo.zones(m)
            except ValueError as e:
                raise Refused(400, f"not confirmed: 04 refuses the zone: {e}") from None
            mp.with_name("map.prev.json").write_text(old)   # the previous map survives one overwrite
            mp.write_text(json.dumps(m, indent=2) + "\n")
            v = int(mp.stat().st_mtime)
            return ({"ok": True, "zone": entry, "_version": v, "say": f"{z['id']} is {entry['name']} on the map, by {by}"},
                    {"zone": entry, "_version": v})
        return self._tap("zone.confirmed", zid, by, time.perf_counter(), write)

    def dismiss(self, zid: str, by: Any) -> dict[str, Any]:
        """The person says no: the proposal is dropped and its cells are remembered (no re-ask this session)."""
        def drop(z: dict, by: str) -> tuple[dict, Any]:
            self.dismissed.append((z["id"], _key(z["cells"])))
            return {"ok": True, "dismissed": z["id"], "say": f"{z['id']} dismissed by {by}"}, {"open": len(self.open) - 1}
        return self._tap("zone.dismissed", zid, by, time.perf_counter(), drop)

    def state(self) -> dict[str, Any]:
        """The GET /dog/scout body (without `source`): {n, proposals, failed, why}; why names the reason whenever n is 0."""
        with self._lock:
            props = [{k: z[k] for k in PROPOSAL_KEYS} for z in self.open.values()]
            failed, c = [dict(f) for f in self.failed], dict(self.counts)
            handled = len(self.handled)
        why = None
        if not props:
            if not handled:
                why = "no placed object yet: the scout asks once about each thing 07 pins on the grid"
            else:
                parts = [f"{c['asked']} asked, {c['proposed']} proposed as a hazard at p >= {self.thr}"]
                parts += [f"{c[k]} {k}" for k in ("confirmed", "dismissed", "deduped") if c[k]]
                parts += [f"{len(failed)} failed (listed)"] if failed else []
                why = "no open proposal: " + ", ".join(parts)
        return {"n": len(props), "proposals": props, "failed": failed, "why": why}


def png(grid: occupancy.Grid, threshold: int, cells, path) -> Path:
    """occupancy.png, then every proposed cell one PNG_SCALE square in CELL_RGB (grid rows and columns, not the map)."""
    from PIL import Image
    occupancy.png(grid, threshold, path)
    im = np.array(Image.open(path).convert("RGB"))
    s = occupancy.PNG_SCALE
    for x, y in cells:
        c, r = int(np.rint((x - grid.origin[0]) / grid.resolution)), int(np.rint((y - grid.origin[1]) / grid.resolution))
        im[r * s:(r + 1) * s, c * s:(c + 1) * s] = CELL_RGB
    Image.fromarray(im).save(path)
    return Path(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wtdd.dog.scout_zones", description="Replay LiDAR frames and one detector window: propose the scout's zones (stub), draw their cells.")
    ap.add_argument("--replay", required=True, help="npz of wire-format frames (wtdd/dog/fixtures/voxel_frames.npz)")
    ap.add_argument("--watch", required=True, help="a watch.json-shaped detector window (wtdd/dog/fixtures/watch-frame.json)")
    ap.add_argument("--pose", required=True, help="x,y,yaw of the dog in the frames' odometry (metres, radians)")
    ap.add_argument("--fov", type=float, required=True, help="the camera's horizontal field of view, degrees")
    ap.add_argument("--png", required=True, help="where the grid PNG with the proposed cells goes")
    ap.add_argument("--threshold", type=int, default=occupancy.THRESHOLD, help=f"frames a cell must be seen in (default {occupancy.THRESHOLD})")
    a = ap.parse_args(argv)
    t_all = time.perf_counter()
    try:
        from .fixtures.make_objects_fixture import CAL
        g = None
        for d in occupancy.replay(a.replay):
            if g is None:
                g = occupancy.Grid.from_frame(d)
            g.update_frame(d)
        if g is None:
            raise ValueError(f"{a.replay} holds no frames")
        w = Path(a.watch)
        frame = json.loads(w.read_text())
        if not Path(frame["file"]).is_absolute():
            frame["file"] = str(w.resolve().parent / frame["file"])
        x, y, yaw = (float(v) for v in a.pose.split(","))
        pose = {"position": [x, y], "yaw": yaw}
        store = objects.Store(append=lambda r: log("objects", "replay row (not written)", event=r["args"]["event"], id=r["args"]["id"]),
                              draft=objects.draft_stub)
        store.observe(frame, pose, g, CAL, a.fov, a.threshold)
        with tempfile.TemporaryDirectory(prefix="wtdd-scout-replay-") as tmp:   # the photo copies and an empty map: nothing real is read or written
            (Path(tmp) / "map.json").write_text('{"zones": []}\n')
            # DEMO_CACHE: the replay always asks decide_stub (COCO name -> label, p = the detector's conf), even with
            # JEV_API_KEY set. Why: a replay of fixtures is not a step and must not spend a model call or claim a live
            # answer. Live: the session's feed (GET /dog/objects starts it) asks decider(), Jev when the key is set.
            props = Proposals(append=lambda r: log("scout", "replay row (not written)", tool=r["tool"], ok=r["ok"]),
                              decide=decide_stub, photo_dir=tmp, map_path=Path(tmp) / "map.json")
            props.feed(store.to_list(), frame, pose, g, CAL, a.fov, a.threshold)
            st = props.state()
        for z in st["proposals"]:
            log("scout", z["id"], kind=z["kind"], label=z["label"], p=z["p"], cells=len(z["cells"]), dist_m=z["dist_m"], poly=z["poly"])
        png(g, a.threshold, [c for z in st["proposals"] for c in z["cells"]], a.png)
    except Exception as e:  # noqa: BLE001  (reported with the path, non-zero exit; nothing written stands in for it)
        log("scout", "FAILED", err=f"{type(e).__name__}: {e}")
        return 1
    log("scout", "replay done", proposed=st["n"], failed=len(st["failed"]), placed=sum(o["pos_px"] is not None for o in store.to_list()),
        frames=g.frames, threshold=a.threshold, fov_deg=a.fov, cal="make_objects_fixture.CAL (the tests' tie)", png=a.png,
        ms=round((time.perf_counter() - t_all) * 1000))
    if st["n"] == 0:
        log("scout", f"WARN proposed=0: {st['why']} (the PNG has the grid, no proposed cell)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
