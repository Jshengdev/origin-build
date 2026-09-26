"""The live object layer: what the detector boxes in the dog's camera is placed on the map at the nearest LiDAR cell
along its bearing, named with the detector's label and probability, given a thumbnail and one drafted line, and marked
stale when the detector stops seeing it. Shapes stay the grid's (wtdd/dog/occupancy.py); a pin is one point where a
ray met cells the LiDAR counted, and the words come from the detector and the model. No model draws anything here.

Run. The API's dog session (wtdd/dog/session.py) owns one Store. GET /dog/objects (and the session's 'objects' thread,
every TICK_S once the first GET started it) reads WATCH, the watch.json wtdd/watch.py writes at about 4 Hz (mirrored
here, never imported: cv2 must not load in the API), and every new detector window goes through Store.observe under
the grid's lock; the thread drafts at most one line every DRAFT_S, outside every lock. Offline:

    python -m wtdd.dog.objects --replay wtdd/dog/fixtures/voxel_frames.npz --watch wtdd/dog/fixtures/watch-frame.json \\
        --pose 0,0,0 --fov 90 --png /tmp/objects.png [--threshold N]

builds the grid from the replayed frames (the loop of occupancy.main), places the fixture's boxes from the given pose,
drafts with the stub, and writes the occupancy PNG with one PIN_PX square in PIN_RGB per placed object: one stderr
line per object and a summary, exit 2 with a WARN when nothing is placed. It writes no ledger row (a replay of a
fixture is not a step).

How. bearing(): the box centre u in a pinhole camera of horizontal field of view fov, atan((u / W - 1/2) * 2 tan(fov/2)),
right of the optical axis positive. The ray starts at the dog's odometry position (LF_SPORT_MOD_STATE) at yaw - bearing
(odometry yaw is counter-clockwise positive, so the camera's right is a negative angle) and is sampled every half cell
up to MAX_RANGE_M; the pin is the first sample whose cell (np.rint onto the grid's lattice, exactly Grid.cell's rule)
was seen threshold+ times, at that cell's lattice point (the dots' convention), projected to map pixels through the same
calibration as the dots (occupancy.to_map_px). The store matches a box to an object with the same label whose pin is
within MATCH_PX, else to a fresh (not stale) one of that label still waiting for its first pin; an unplaced box (no
pose, no blob, no frame for one window) takes an unplaced object of its label, else the fresh one of its label seen
last, which keeps its last pin: a window that cannot place a thing is not a new thing. Otherwise the box is a new
object "o<n>"; an object unseen for STALE_WINDOWS detector windows is stale, and comes back (seen_again) when a box
matches it again (a stale pin only by a placement within MATCH_PX of it). Label and p are the
detector's own name and confidence (label_source "detector") unless a decide hook is given (label_source "decide").
One object.seen row per event: new, drafted, stale, seen_again, never per frame; a matched object whose p or pin moves
is updated in place without a row. Draft: WTDD_OBJECTS_DRAFT=live (default) is one llm.generate per new object with the
crop and a text line (the model names the thing; the pin is already placed); stub is the DEMO_CACHE line below. A failed
draft is a failed row and a FAILED message_source, never a canned line, and it is not retried.

UNVERIFIED on the real dog (the first live walk must confirm): the camera's horizontal field of view (env
WTDD_CAM_FOV_DEG; empty = boxes are stored unplaced and GET /dog/objects says why); the bearing's sign on the real
camera (right of the image = clockwise on the map); that the voxel frame (the grid) and LF_SPORT_MOD_STATE (the ray's
origin) are one odometry (lidar.py's docstring, frame (2)); the camera sits about 0.3 m ahead of the odometry origin and
no offset is applied; the pose is read when the window is taken, not when the frame was shot (the detector's latency
at walking speed is a few centimetres); the thumbnail is cropped from watch.jpg, the detector's boxed copy (its drawn box
edge is in the crop), which the detector may already have replaced by the next frame. Placement is the first counted
cell on the ray, so a person in front of a wall the LiDAR has not separated pins on the wall: placement can be wrong."""
from __future__ import annotations
import argparse
import base64
import contextlib
import io
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .. import config
from ..config import ROOT
from ..ledger import append as ledger_append, log
from . import occupancy

MAX_RANGE_M = 8.0     # a ray that meets no counted cell within this is "no blob"
STALE_WINDOWS = 8     # detector windows unseen before an object is stale (2 s at the detector's 4 Hz)
MATCH_PX = 60         # map pixels (about 0.55 m): a box of the same label pinned this close is the same object
THUMB_PX = 96         # the thumbnail's longest side
MAX_OBJECTS = 64      # past this the oldest stale object is dropped
DRAFT_S = 4.0         # at most one drafted line this often
MAX_MESSAGE = 120     # a drafted line longer than this is cut at a word (WARN)
FRESH_S = 3.0         # a watch.json older than this is no detector window (the remote's own rule for /watch)
TICK_S = 0.25         # the session's objects thread: the detector's 4 Hz
PIN_PX = 9            # the replay PNG's pin square, pixels
PIN_RGB = (220, 30, 30)
WATCH = ROOT / "watch.json"   # what wtdd/watch.py writes (publish()); mirrored, not imported
KEYS = ("id", "label", "p", "label_source", "message", "message_source", "thumb", "box", "bearing_deg", "hit_m", "dist_m",
        "pos_px", "why", "first_seen", "last_seen", "windows_unseen", "stale")
FOV_WHY = "WTDD_CAM_FOV_DEG is required: the camera's horizontal field of view in degrees, UNVERIFIED until measured on the Go2 (see .env.example)"
SYSTEM = ("You are a robot dog's eyes on a night round of a work site. You get a small crop of its camera frame around "
          "one thing its object detector boxed, the detector's label and probability, and where the thing sits from the dog. "
          "Reply with one line under 100 characters for the site's group chat: what the thing is and where it sits. No "
          "adjectives, no dashes, no names of people, say someone if it is a person. Say only what is in the picture; if the "
          "detector's label is wrong, say what it really is. Never describe walls, rooms or their shape.")


def bearing(xyxy, frame_w: float, fov_deg: float) -> float:
    """Radians from the optical axis to the box centre, right positive (pinhole)."""
    if fov_deg is None or not 0 < fov_deg < 180:
        raise ValueError(f"field of view must be in (0, 180) degrees, got {fov_deg}")
    if not frame_w or frame_w <= 0:
        raise ValueError(f"frame width must be positive, got {frame_w}")
    u = (xyxy[0] + xyxy[2]) / 2
    return math.atan((u / frame_w - 0.5) * 2 * math.tan(math.radians(fov_deg) / 2))


def nearest_blob(grid: occupancy.Grid, xy_m, angle_rad: float, threshold: int = occupancy.THRESHOLD,
                 max_range_m: float = MAX_RANGE_M) -> dict[str, Any] | None:
    """The first cell seen threshold+ times along the ray, as {xy (its lattice point, metres), dist_m, count}; None when
    the ray meets none within max_range_m. Pure: the caller holds the grid's lock."""
    if threshold < 1:
        raise ValueError(f"threshold must be at least 1 frame, got {threshold}")
    res = grid.resolution
    t = np.arange(0.0, max_range_m + 1e-9, res / 2)
    ix = np.rint((xy_m[0] + t * math.cos(angle_rad) - grid.origin[0]) / res).astype(np.int64)
    iy = np.rint((xy_m[1] + t * math.sin(angle_rad) - grid.origin[1]) / res).astype(np.int64)
    h, w = grid.counts.shape
    inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
    c = np.zeros(len(t), dtype=np.int64)
    c[inside] = grid.counts[iy[inside], ix[inside]]
    k = np.flatnonzero(c >= threshold)
    if not len(k):
        return None
    k = int(k[0])
    xy = [round(float(grid.origin[0] + ix[k] * res), 6), round(float(grid.origin[1] + iy[k] * res), 6)]
    return {"xy": xy, "dist_m": round(math.hypot(xy[0] - xy_m[0], xy[1] - xy_m[1]), 3), "count": int(c[k])}


def thumb(src, xyxy, width: int = THUMB_PX) -> str:
    """The box cropped from the frame (a path, or an opened PIL image) as a data:image/jpeg;base64 URL, at most width px
    on its longest side. Raises on a missing file."""
    from PIL import Image
    img = src if isinstance(src, Image.Image) else Image.open(src).convert("RGB")
    x0, y0 = min(max(int(xyxy[0]), 0), img.width - 1), min(max(int(xyxy[1]), 0), img.height - 1)
    x1, y1 = max(min(int(xyxy[2]), img.width), x0 + 1), max(min(int(xyxy[3]), img.height), y0 + 1)
    t = img.crop((x0, y0, x1, y1))
    t.thumbnail((width, width))
    buf = io.BytesIO()
    t.save(buf, "JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _where(obj: dict) -> str | None:
    if obj["dist_m"] is None or obj["bearing_deg"] is None:
        return None
    return f"{obj['dist_m']:.1f} m away, {abs(obj['bearing_deg']):.0f} degrees {'right' if obj['bearing_deg'] > 0 else 'left'} of where the dog looks"


# DEMO_CACHE: the drafted one-liner. What: the label, p, distance and bearing as one line tagged [stub: no model]. Why: no
# OPENROUTER key in a worktree, and a demo take that must not wait on a model. Live: WTDD_OBJECTS_DRAFT=live (the
# default) with OPENROUTER_API_KEY set: one llm.generate row per new object. Its object.seen rows say cached=true,
# source=stub, and the object's message_source says stub.
def draft_stub(obj: dict) -> dict[str, Any]:
    if obj["dist_m"] is not None and obj["bearing_deg"] is not None:
        msg = f"{obj['label']} ({obj['p']:.2f}) {obj['dist_m']:.1f} m away, {obj['bearing_deg']:+.0f} deg from where it looks [stub: no model]"
    else:
        msg = f"{obj['label']} ({obj['p']:.2f}), not placed: {obj['why']} [stub: no model]"
    return {"message": msg, "cached": True, "source": "stub", "model": None}


def draft_live(obj: dict) -> dict[str, Any]:
    """One llm.generate (agent objects, the vision model when there is a thumbnail) for the object's one line. Raises on
    an empty reply or no key (config.get); no retry, no fallback line."""
    from ..llm import generate
    where = _where(obj) or f"not placed on the map ({obj['why']})"
    text = f"the detector boxed this as {obj['label']} with probability {obj['p']:.2f}, {where}"
    content: list[dict[str, Any]] = [{"type": "text", "text": text + ("" if obj["thumb"] else ". no picture: the frame file was missing")}]
    if obj["thumb"]:
        content.append({"type": "image_url", "image_url": {"url": obj["thumb"]}})
    out = generate("objects", [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}], max_tokens=60, temperature=0.3)
    msg = " ".join(out["text"].split()).strip('"')
    if not msg:
        raise RuntimeError(f"vision model returned an empty line (model={out['model']})")
    return {"message": msg, "cached": False, "source": "live", "model": out["model"]}


def drafter() -> Callable[[dict], dict]:
    """draft_live, or draft_stub when WTDD_OBJECTS_DRAFT=stub (read here, at the point of use; logged)."""
    mode = config.maybe("WTDD_OBJECTS_DRAFT") or "live"
    if mode not in ("live", "stub"):
        log("objects", f"WARN WTDD_OBJECTS_DRAFT={mode!r} is neither live nor stub: drafting live")
    log("objects", "drafts " + ("stub (DEMO_CACHE: tagged [stub: no model], rows cached=true)" if mode == "stub" else "live (one llm.generate per new object)"))
    return draft_stub if mode == "stub" else draft_live


def _cut(msg: str) -> str:
    if len(msg) <= MAX_MESSAGE:
        return msg
    log("objects", f"WARN drafted line {len(msg)} chars, cut to {MAX_MESSAGE}")
    return msg[:MAX_MESSAGE].rsplit(" ", 1)[0]


class Store:
    """The objects seen this session, insertion-ordered (see the module docstring for the rules)."""

    def __init__(self, append: Callable[[dict], Any] = ledger_append, draft: Callable[[dict], dict] = draft_live,
                 decide: Callable[[dict, dict], dict] | None = None, stale_windows: int = STALE_WINDOWS) -> None:
        self.append, self._draft, self.decide, self.stale_windows = append, draft, decide, stale_windows
        self.objs: dict[str, dict[str, Any]] = {}
        self.n_ids = 0
        self.windows = 0
        self.last_t: float | None = None     # the watch.json `t` last taken (tick)
        self.last_draft = 0.0                # time.monotonic() of the last draft attempt (draft_due)
        self.last_why: str | None = ""       # tick's last answer, so a change is logged once
        self._failed: set[str] = set()
        self._warned: set[str] = set()

    def observe(self, frame: dict, pose: dict | None, grid: occupancy.Grid | None, cal: dict | None, fov_deg: float | None,
                threshold: int = occupancy.THRESHOLD) -> dict[str, list[str]]:
        """One detector window: every box placed (or stored unplaced with why), matched or new; unmatched objects age."""
        from PIL import Image
        t0 = time.perf_counter()
        self.windows += 1
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        out: dict[str, list[str]] = {"new": [], "seen": [], "stale": [], "unplaced": []}
        events: list[tuple[dict, str, dict | None]] = []
        boxes = frame.get("boxes") or []
        img, img_why = None, None
        if boxes:
            try:
                img = Image.open(frame["file"]).convert("RGB")
            except OSError as e:   # a missing or unreadable frame: no width, no thumbs; every box says why
                img_why = f"frame file unreadable: {type(e).__name__}: {e}"
                if frame["file"] not in self._warned:
                    self._warned.add(frame["file"])
                    log("objects", "WARN " + img_why)
        matched: set[str] = set()
        for b in boxes:
            if self.decide:
                d = self.decide(b, frame)
                label, p, src = d["label"], float(d["p"]), "decide"
            else:
                label, p, src = b["name"], float(b["conf"]), "detector"
            brg = None if img is None or fov_deg is None else bearing(b["xyxy"], img.width, fov_deg)
            hit, pos_px, why = None, None, None
            if brg is None:
                why = "no bearing: " + (img_why or "WTDD_CAM_FOV_DEG unset")
            elif pose is None:
                why = "no pose: the dog is not connected or has no state"
            elif grid is None:
                why = "no grid: no LiDAR frame this session"
            else:
                hit = nearest_blob(grid, pose["position"], pose["yaw"] - brg, threshold)
                if hit is None:
                    why = f"no blob seen {threshold}+ times along the bearing within {MAX_RANGE_M} m"
                elif cal is None:
                    why = "not calibrated: drag the dog to where it is (POST /dog/calibrate)"
                else:
                    pos_px = occupancy.to_map_px([hit["xy"]], cal)[0].tolist()
            fields = {"label": label, "p": p, "label_source": src, "thumb": thumb(img, b["xyxy"]) if img is not None else None,
                      "box": list(b["xyxy"]), "bearing_deg": None if brg is None else round(math.degrees(brg), 1),
                      "hit_m": hit["xy"] if hit else None, "dist_m": hit["dist_m"] if hit else None, "pos_px": pos_px, "why": why}
            same = [o for o in self.objs.values() if o["label"] == label and o["id"] not in matched]
            fresh = [o for o in same if not o["stale"]]   # with no pin to compare, identity rides on continuity alone
            if pos_px is not None:   # the nearest pin within MATCH_PX, else a fresh object still waiting for its first pin
                near = [(math.dist(o["pos_px"], pos_px), o) for o in same if o["pos_px"] is not None]
                near = [c for c in near if c[0] <= MATCH_PX]
                o = min(near, key=lambda c: c[0])[1] if near else next((o for o in fresh if o["pos_px"] is None), None)
            else:   # an unplaced object, else the fresh one seen last: a blind window (pose, ray, frame) is not a new thing
                o = next((o for o in same if o["pos_px"] is None), None) or max(fresh, key=lambda o: o["last_seen"], default=None)
                if o is not None and o["pos_px"] is not None:   # its last pin stays until a window places it again
                    fields = {k: v for k, v in fields.items() if k not in ("hit_m", "dist_m", "pos_px")}
            if o is not None:
                before = {k: v for k, v in o.items() if k != "thumb"}
                was_stale = o["stale"]
                o.update(fields, last_seen=now, windows_unseen=0, stale=False)
                out["seen"].append(o["id"])
                if was_stale:
                    events.append((o, "seen_again", before))
            else:
                self.n_ids += 1
                o = {"id": f"o{self.n_ids}", **fields, "message": None, "message_source": None, "first_seen": now,
                     "last_seen": now, "windows_unseen": 0, "stale": False}
                self.objs[o["id"]] = o
                out["new"].append(o["id"])
                events.append((o, "new", None))
            matched.add(o["id"])
            if pos_px is None:
                out["unplaced"].append(o["id"])
        for o in self.objs.values():
            if o["id"] in matched:
                continue
            o["windows_unseen"] += 1
            if not o["stale"] and o["windows_unseen"] >= self.stale_windows:
                before = {k: v for k, v in o.items() if k != "thumb"}
                o["stale"] = True
                out["stale"].append(o["id"])
                events.append((o, "stale", before))
        while len(self.objs) > MAX_OBJECTS:
            old = next((k for k, o in self.objs.items() if o["stale"]), None)
            if old is None:
                log("objects", f"WARN {len(self.objs)} objects, none stale: none dropped", max=MAX_OBJECTS)
                break
            log("objects", f"dropped {old}: the oldest stale object past {MAX_OBJECTS}", label=self.objs[old]["label"])
            del self.objs[old]
        ms = round((time.perf_counter() - t0) * 1000)
        for o, event, before in events:
            self._row(o, event, before, latency_ms=ms)
        warn = "WARN " if boxes and len(out["unplaced"]) == len(boxes) else ""
        log("objects", f"{warn}window {self.windows}", boxes=len(boxes), new=len(out["new"]), seen=len(out["seen"]),
            stale=len(out["stale"]), unplaced=len(out["unplaced"]), ms=ms)
        return out

    def draft(self) -> str | None:
        """Drafts the line of the oldest object without one (never one whose draft failed): one row, ok or not."""
        o = next((o for o in list(self.objs.values()) if o["message"] is None and o["id"] not in self._failed), None)
        if o is None:
            return None
        before = {k: v for k, v in o.items() if k != "thumb"}
        t0 = time.perf_counter()
        try:
            r = self._draft(o)
        except Exception as e:  # noqa: BLE001  (recorded on its row and on the object, then re-raised: no canned line)
            err = f"{type(e).__name__}: {e}"
            o["message_source"] = f"FAILED {err}"[:100]
            self._failed.add(o["id"])
            self._row(o, "drafted", before, ok=False, err=err, latency_ms=round((time.perf_counter() - t0) * 1000))
            raise
        o["message"], o["message_source"] = _cut(r["message"]), r["source"]
        flags = {"cached": True, "source": r["source"]} if r["cached"] else {}
        self._row(o, "drafted", before, message=o["message"], latency_ms=round((time.perf_counter() - t0) * 1000), **flags)
        return o["id"]

    def _row(self, o: dict, event: str, before: dict | None, ok: bool = True, err: str | None = None,
             message: str | None = None, latency_ms: int = 0, **flags: Any) -> None:
        after = {k: v for k, v in o.items() if k != "thumb"}
        after["thumb_bytes"] = len(o["thumb"] or "")
        self.append({"step": "object.seen", "agent": "objects", "tool": "object.seen", "app": "map",
                     "args": {"id": o["id"], "label": o["label"], "p": o["p"], "pos_px": o["pos_px"], "event": event,
                              "shift_id": config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")},
                     "state_before": before, "state_after": after, "ok": ok, "response_or_error": message or err,
                     "latency_ms": int(latency_ms), **flags})
        log("objects", f"object.seen {event} {o['id']} ok={ok}", label=o["label"], p=o["p"], pos_px=o["pos_px"],
            why=o["why"], err=(err or "")[:80], ms=int(latency_ms))

    def to_list(self) -> list[dict[str, Any]]:
        return [{k: o[k] for k in KEYS} for o in self.objs.values()]

    def state(self) -> dict[str, Any]:
        objs = self.to_list()
        d: dict[str, Any] = {"n": len(objs), "objects": objs, "windows": self.windows}
        if not objs:
            d["why"] = "no detector window yet" if self.windows == 0 else f"nothing boxed in {self.windows} windows"
        return d


def tick(store: Store, watch_path, pose: dict | None, grid: occupancy.Grid | None, cal: dict | None, fov_deg: float | None,
         grid_lock=None) -> str | None:
    """Takes the detector's newest window if it is new (observe under grid_lock); returns why nothing could be placed or
    taken (no field of view, no detector frame, a stale one), None when all is well. A change is logged once."""
    p = Path(watch_path)
    whys = [] if fov_deg is not None else [FOV_WHY]
    if not p.exists():
        whys.append(f"no detector frame: {p.name} absent (python -m wtdd.watch)")
    elif (age := time.time() - p.stat().st_mtime) > FRESH_S:
        whys.append(f"detector frame {age:.0f} s old: {p.name} (python -m wtdd.watch)")
    else:
        d = json.loads(p.read_text())
        if d.get("t") != store.last_t:
            with grid_lock or contextlib.nullcontext():
                store.observe(d, pose, grid, cal, fov_deg)
            store.last_t = d.get("t")
    why = " · ".join(whys) or None
    if why != store.last_why:
        log("objects", ("WARN " + why) if why else "detector windows fresh", windows=store.windows)
        store.last_why = why
    return why


def draft_due(store: Store) -> str | None:
    """The cadence: at most one draft every DRAFT_S (the session's objects thread, outside every lock). A failed draft is
    already its row; it is logged here and the next call moves on."""
    if time.monotonic() - store.last_draft < DRAFT_S:
        return None
    try:
        oid = store.draft()
    except Exception as e:  # noqa: BLE001  (the object.seen drafted row has it, ok=false; never retried)
        store.last_draft = time.monotonic()
        log("objects", "WARN draft FAILED (its object.seen row has it)", err=f"{type(e).__name__}: {str(e)[:120]}")
        return None
    if oid:
        store.last_draft = time.monotonic()
    return oid


def png(grid: occupancy.Grid, threshold: int, hits, path) -> Path:
    """occupancy.png, then one PIN_PX square in PIN_RGB centred on each hit's cell (metres in, grid rows and columns)."""
    from PIL import Image, ImageDraw
    occupancy.png(grid, threshold, path)
    im = Image.open(path).convert("RGB")
    d, s, r = ImageDraw.Draw(im), occupancy.PNG_SCALE, PIN_PX // 2
    for x, y in hits:
        c = round((x - grid.origin[0]) / grid.resolution) * s + s // 2
        w = round((y - grid.origin[1]) / grid.resolution) * s + s // 2
        d.rectangle([c - r, w - r, c + r, w + r], fill=PIN_RGB)
    im.save(path)
    return Path(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wtdd.dog.objects", description="Replay LiDAR frames and one detector window: place the boxes, draw the pins.")
    ap.add_argument("--replay", required=True, help="npz of wire-format frames (wtdd/dog/fixtures/voxel_frames.npz)")
    ap.add_argument("--watch", required=True, help="a watch.json-shaped detector window (wtdd/dog/fixtures/watch-frame.json)")
    ap.add_argument("--pose", required=True, help="x,y,yaw of the dog in the frames' odometry (metres, radians)")
    ap.add_argument("--fov", type=float, required=True, help="the camera's horizontal field of view, degrees")
    ap.add_argument("--png", required=True, help="where the grid PNG with the pins goes")
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
        store = Store(append=lambda r: log("objects", "replay row (not written)", event=r["args"]["event"], id=r["args"]["id"]), draft=draft_stub)
        store.observe(frame, {"position": [x, y], "yaw": yaw}, g, CAL, a.fov, a.threshold)
        while store.draft():
            pass
        objs = store.to_list()
        for o in objs:
            log("objects", o["id"], label=o["label"], p=o["p"], bearing_deg=o["bearing_deg"], hit_m=o["hit_m"], dist_m=o["dist_m"],
                pos_px=o["pos_px"], why=o["why"], message=repr(o["message"]))
        png(g, a.threshold, [o["hit_m"] for o in objs if o["hit_m"] is not None], a.png)
    except Exception as e:  # noqa: BLE001  (reported with the path, non-zero exit; nothing written stands in for it)
        log("objects", "FAILED", err=f"{type(e).__name__}: {e}")
        return 1
    placed = sum(o["pos_px"] is not None for o in objs)
    log("objects", "replay done", placed=placed, of=len(objs), frames=g.frames, threshold=a.threshold, fov_deg=a.fov,
        cal="make_objects_fixture.CAL (the tests' tie)", png=a.png, ms=round((time.perf_counter() - t_all) * 1000))
    if placed == 0:
        log("objects", f"WARN placed=0 of {len(objs)} boxes: no counted cell along any bearing (the PNG has the grid, no pin)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
