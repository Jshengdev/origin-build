"""The scout's auto zones, two kinds (Johnny, 2026-09-27 20:23: "one is if it has a person and one is everything else").

PERSON. A thing 07's detector labels "person" (its own label, no model call) is a soft, temporary zone: its shape is the
live LiDAR points within PERSON_R_M of 07's pin in the NEWEST window (in the dots' band, after lidar.keep's surface
filter), their cells, projected through the calibration in force when GET /dog/scout is served (stored in odometry
metres). No lit point there: no zone, and state()'s why says so. Refreshed at every window that sees them lit; gone
PERSON_TTL_S after the last one. It carries the detection photo {file, url} (the frame copied once to ~/Pictures/wtdd,
listed by GET /images?kind=scout from its zone.person row), or {missing: true, error} when the copy failed. It is NEVER
written to ui/map.json, so nothing that plans or walks (04's refuse, the follower, the round) ever sees it. Rows: one
zone.person when it appears, one zone.person_cleared when it expires; never per frame.

HAZARD (everything else). Johnny, 20:26, after the scout stacked 41 auto zones in ten minutes: "only use high confidence
repeat and picture confirmation ... be more strict". A hazard zone is written into 04's `nogo: true` schema on
ui/map.json (by "auto") only when ALL four gates pass, each a named constant below, UNVERIFIED live:
  1. HIGH CONFIDENCE: the detector's p >= HAZARD_P_MIN.
  2. REPEAT: the same object (07's id, matched by 07's store) seen at HAZARD_P_MIN+ in >= HAZARD_SEEN_N separate
     detector windows spanning >= HAZARD_SPAN_S. A one-off detection never makes a zone.
  4. LIT CLUSTER (checked before any model call): the live points of the newest window within HAZARD_R_M of the pin,
     8-connected on the grid's lattice from the point nearest the pin, >= HAZARD_MIN_POINTS of them. That cluster IS
     the zone (polygon(): the cells' padded hull); the flood fill over the accumulated grid is gone. No lit cluster:
     no zone, and the thing is considered again at the next window.
  3. PICTURE CONFIRMATION: the object's crop from the detector frame goes to a vision model (confirm_live, the repo's
     one OpenRouter path, llm.generate) with STRICT_QUESTION; a zone only if it answers yes AND p >= CONFIRM_P_MIN AND
     the thing it names agrees with the detector's label class (agrees()). The model is WTDD_SCOUT_CONFIRM_MODEL,
     default CONFIRM_MODEL (google/gemini-2.5-pro: a stronger vision model than OPENROUTER_VISION_MODEL's
     x-ai/grok-4.20, which the repo picked for speed; UNVERIFIED live: its answers on the real frames). A failed,
     timed-out or unparseable call is NO zone and one FAILED zone.confirm row (never a default yes, never retried).
     With no OPENROUTER_API_KEY the DEMO_CACHE confirm_stub answers (below); its zone says app "stub".
Before the confirm, Jev (TypeSafe System One, decide_live, or decide_stub with no JEV_API_KEY) still names WHAT it is
(table, sharp_object, blocked_way, not_a_hazard: its own zone.decided row, threshold WTDD_DECIDE_THRESHOLD); its
not_a_hazard or a p below that threshold also leaves the thing a pin. Each hazard zone carries its evidence on the map,
on GET /dog/scout and on its zone.confirmed row: {p, seen_n, span_s, confirm: {model, answer, name, p}, points_n}, and
its photo {file, url, path, sha256, bytes}. A thing that fails a gate is counted per reason (state()'s gates), and one
stderr line every SUMMARY_S says how many were considered and why each was rejected; no zone added yet is a WARN.

A thing is taken once (07's id) past gates 1, 2 and 4; a thing whose lit cells overlap an open proposal, a dismissed
zone or a scout zone on the map is the same thing (logged, no call, no row). Every scout write to the map (_rewrite: an
auto zone, confirm(id, by), dismiss(id, by)) follows POST /map's rules (a stale _version is 409, the previous map kept as
map.prev.json) and nogo.zones() must accept the result; every refusal is a failed zone.* row before anything is written.
dismiss() of an auto zone takes that one entry off the map and remembers its cells (no re-add this session); a zone a
person drew (04) or confirmed is never the scout's to dismiss (404). The open-proposal path (confirm, a proposal's
dismiss, state()'s proposals) is kept, but the feed opens none.

Switch. WTDD_SCOUT_ZONES (config.scout_zones(), read at each use): unset or 1 = both kinds; person = person zones only
(no hazard zone, no Jev and no confirm call: the filming setting); 0 = none (07's objects and pins stay; one OFF line per
store). Anything else raises on every feed and GET. GET /dog/scout serves auto_zones "on" | "person only
(WTDD_SCOUT_ZONES=person)" | "off (WTDD_SCOUT_ZONES=0)".

Run. The API's dog session (wtdd/dog/session.py) owns one Proposals store; its 'objects' thread feeds it 07's objects
and the newest LiDAR window's band (session._live_m) after every detector window, GET /dog/scout reads it through the
calibration in force, POST /dog/scout {id, action: confirm | dismiss, by, _version} is the person's tap. Offline:

    python -m wtdd.dog.scout_zones --replay wtdd/dog/fixtures/voxel_frames.npz --watch wtdd/dog/fixtures/watch-frame.json \\
        --pose 0,0,0 --fov 90 --png /tmp/scout.png [--threshold N]

builds the grid from the replayed frames, places the fixture's boxes with 07's store, feeds that one window
HAZARD_SEEN_N times HAZARD_SPAN_S apart on a replay clock with the last frame's band as the live view (the repeat gate
is exercised, not proven: it is one window), asks the stubs (never Jev or OpenRouter, even with a key), adds its zones
to a scratch map and writes the occupancy PNG with every zone cell in CELL_RGB; exit 2 with a WARN when nothing is
added. It writes no ledger row and never touches ui/map.json.

UNVERIFIED on the real dog (the first live run must confirm): every constant below (p, repeat, span, radius, points,
TTL) against a real table and a real person; that 07's pin (the first counted cell on the ray) sits inside the lit
cluster of the thing, not on the wall behind it (a table against a wall brings the wall's lit points within
HAZARD_R_M along; a person in front of a wall the LiDAR has not separated pins on the wall); the confirm model's live
answers and latency (none has been made: tests stub it); the photo is the newest watch frame, which the detector may
have replaced since the window 07 placed; positive obstacles only: COCO has no hole and the band has no floor, so an
opening is always drawn by a person (04)."""
from __future__ import annotations
import argparse
import base64
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

from .. import config, field, nogo, shift
from ..ledger import append as ledger_append, log
from . import localize, objects, occupancy

HAZARD_P_MIN = 0.6       # gate 1: the detector's own p; below it a box stays 07's pin (41 zones in 10 min came from any p)
HAZARD_SEEN_N = 4        # gate 2: separate detector windows the thing is seen in at HAZARD_P_MIN+ (one window at 4 Hz is a flicker)
HAZARD_SPAN_S = 3.0      # gate 2: ...spanning at least this long, so four frames of one glance are not a repeat
HAZARD_R_M = 0.5         # gate 4: live points this close to 07's pin are the thing's candidates (a table is about 1 m across)
HAZARD_MIN_POINTS = 8    # gate 4: the lit cluster needs this many columns (0.4 m of lit edge at the 5 cm voxel): no stray return
CONFIRM_P_MIN = 0.8      # gate 3: the confirm model's own confidence in its yes
CONFIRM_MODEL = "google/gemini-2.5-pro"   # gate 3's default; WTDD_SCOUT_CONFIRM_MODEL overrides (UNVERIFIED live)
CONFIRM_TIMEOUT_S = 30.0
CROP_MARGIN = 0.25       # the confirm crop is the box grown by this fraction of its size on every side (the floor around it)
STRICT_QUESTION = ("Is there a physical obstacle on the floor here that a small walking robot must go around? "
                   'Answer only JSON: {"answer": "yes" or "no", "name": the object\'s name, "confidence": 0 to 1}.')
PERSON = "person"        # 07's detector label (COCO) that makes a person zone
PERSON_R_M = 0.6         # live points this close to a person's pin are the person (legs and body at the band's height)
PERSON_TTL_S = 20.0      # a person zone is cleared this long after the last window that saw them lit
PERSON_MERGE_M = 0.5     # a new detector id this close (odometry m) to a live person zone's last pin is that person again
SUMMARY_S = 30.0         # one gate summary line this often, never per frame
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
CELL_RGB = (220, 38, 38)   # the replay PNG's zone cells
OFF = "scout zones off (WTDD_SCOUT_ZONES=0): objects kept, no auto zone"   # the one stderr line and state()'s why
PROPOSAL_KEYS = ("id", "object_id", "kind", "label", "p", "app", "cells", "cells_px", "poly", "thumb", "photo", "dist_m",
                 "area_m2", "ts")


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _key(cells) -> set:
    """Lattice points as a set, rounded to the millimetre: two things sharing one counted cell are the same thing."""
    return {(round(c[0], 3), round(c[1], 3)) for c in cells}


def lit(live, hit, r_m: float, grid: occupancy.Grid, connected: bool = True) -> tuple[list[list[float]], int]:
    """The newest window's live points (odometry metres, (N, 2)) within r_m of 07's pin, on the grid's lattice (np.rint,
    Grid.cell's rule): (sorted cells [[x_m, y_m], ...], the points in them). connected: only the cells 8-connected to
    the one holding the point nearest the pin (a hazard's cluster); else every cell in the radius (a person's legs). No
    live view or no point: ([], 0). Shapes come from these points only."""
    pts = np.asarray(live if live is not None else [], dtype=np.float64).reshape(-1, 2)
    d = np.hypot(pts[:, 0] - hit[0], pts[:, 1] - hit[1])
    pts, d = pts[d <= r_m], d[d <= r_m]
    if not len(pts):
        return [], 0
    res, (ox, oy) = grid.resolution, grid.origin
    ij = [tuple(c) for c in np.rint((pts - [ox, oy]) / res).astype(int).tolist()]
    count: dict[tuple, int] = {}
    for c in ij:
        count[c] = count.get(c, 0) + 1
    keep = set(count)
    if connected:
        seed = ij[int(np.argmin(d))]
        keep, stack = {seed}, [seed]
        while stack:
            i, j = stack.pop()
            for n in ((i + di, j + dj) for di in (-1, 0, 1) for dj in (-1, 0, 1)):
                if n in count and n not in keep:
                    keep.add(n)
                    stack.append(n)
    return sorted([round(ox + i * res, 6), round(oy + j * res, 6)] for i, j in keep), sum(count[c] for c in keep)


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
# zone without a model. Live: set JEV_API_KEY in .env; decider() then picks decide_live, one Jev call per thing.
# Its zone.decided and zone.confirmed rows say cached=true, source=stub, by "auto (stub <p>)", and the remote says "stub"
# beside the zone.
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


CLASSES = {"table": ("table", "desk", "bench", "chair", "stool", "seat", "sofa", "couch"),
           "sharp_object": ("knife", "scissors", "blade")}


def klass(name: str) -> str:
    """A thing's name -> its class (CLASSES' key when one of its words is in the name), else the name itself."""
    n = " ".join(str(name).lower().replace("_", " ").split())
    return next((k for k, ws in CLASSES.items() if any(w in n for w in ws)), n)


def agrees(detected: str, named: str) -> bool:
    """Gate 3's last clause: the confirm model's name is the detector's label class ("a wooden table" for "dining
    table"; "backpack" inside "a black backpack")."""
    a, b = klass(detected), klass(named)
    return bool(a and b) and (a == b or a in b or b in a)


def crop(data: bytes, box) -> str:
    """The box grown by CROP_MARGIN on every side, cut from the detector frame at full resolution, as a JPEG data URL."""
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    x0, y0, x1, y1 = (float(v) for v in box)
    mx, my = (x1 - x0) * CROP_MARGIN, (y1 - y0) * CROP_MARGIN
    out = io.BytesIO()
    im.crop((max(0, int(x0 - mx)), max(0, int(y0 - my)), min(im.width, int(x1 + mx)), min(im.height, int(y1 + my)))).save(out, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def confirm_model() -> str:
    return config.maybe("WTDD_SCOUT_CONFIRM_MODEL") or CONFIRM_MODEL


# DEMO_CACHE: gate 3's picture confirmation. What: no picture is looked at; "yes" for a COCO table/bench/chair or a
# knife/scissors (else "no"), named the detector's label, p = the detector's own conf, model "stub". Why: no
# OPENROUTER_API_KEY in a worktree or a replay, and a model that cannot see must not claim a confidence it does not
# have (so only a detector p >= CONFIRM_P_MIN passes). Live: set OPENROUTER_API_KEY; confirmer() then picks
# confirm_live, one vision call per thing past gates 1, 2 and 4. Its zone.confirm row says cached=true, source=stub,
# and its zone keeps app "stub" on the map (the remote says stub).
def confirm_stub(q: dict) -> dict[str, Any]:
    yes = q["kind"] in TABLE_KINDS or q["kind"] in SHARP_KINDS
    return {"answer": "yes" if yes else "no", "name": q["kind"], "p": float(q["conf"]), "model": "stub",
            "raw": f"stub: {q['kind']} -> {'yes' if yes else 'no'} (p is the detector's conf; no picture was looked at)",
            "app": "stub", "cached": True}


def confirm_live(q: dict) -> dict[str, Any]:
    """One llm.generate (agent scout, model q["model"]) with the crop and STRICT_QUESTION, JSON only. A non-200, a reply
    that is not {answer: yes|no, name, confidence in [0, 1]} or a timeout raise: no retry, no default."""
    from ..llm import generate
    out = generate("scout", [{"role": "user", "content": [
        {"type": "text", "text": f"A robot's detector boxed this as '{q['kind']}'. {STRICT_QUESTION}"},
        {"type": "image_url", "image_url": {"url": q["image"]}}]}],
        model_id=q["model"], max_tokens=120, temperature=0.0, response_format={"type": "json_object"}, timeout=CONFIRM_TIMEOUT_S)
    text = out["text"].strip()
    try:
        j = json.loads(text[text.index("{"):text.rindex("}") + 1])
        answer, name, p = str(j["answer"]).strip().lower(), str(j["name"]).strip(), float(j["confidence"])
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"confirm reply is not {{answer, name, confidence}} ({type(e).__name__}: {e}): {text[:200]!r}") from None
    if answer not in ("yes", "no") or not 0.0 <= p <= 1.0:
        raise RuntimeError(f"confirm answered out of contract: answer {answer!r}, confidence {p!r}")
    return {"answer": answer, "name": name, "p": p, "model": str(out["model"]), "raw": text[:600], "app": "openrouter", "cached": False}


def confirmer() -> Callable[[dict], dict]:
    """confirm_live when OPENROUTER_API_KEY is set, else confirm_stub (read here, at the point of use; logged)."""
    live = bool(config.maybe("OPENROUTER_API_KEY"))
    log("scout", f"confirms {'live (' + confirm_model() + ', one vision call per thing past gates 1, 2 and 4)' if live else 'stub (DEMO_CACHE: no picture looked at, p = the detector conf; rows cached=true)'}")
    return confirm_live if live else confirm_stub


def shift_id() -> str:
    return shift.current()   # S11: the run in force (shift.json, else WTDD_SHIFT, else the date), as every stamp


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
    """The scout's zones this session: open proposals (insertion-ordered), person zones, the hazard gates' sightings
    (see the module docstring for the rules)."""

    def __init__(self, append: Callable[[dict], Any] = ledger_append, decide: Callable[[dict], dict] | None = None,
                 photo_dir=None, map_path=None, confirm: Callable[[dict], dict] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.append, self.decide, self.confirm_fn, self.clock = append, decide, confirm, clock   # confirm_fn: gate 3's model (None: confirmer())
        self.photo_dir = Path(photo_dir) if photo_dir else None   # None: PHOTOS, read at the write
        self.map_path = Path(map_path) if map_path else None      # None: field.MAP, read at call time
        self.open: dict[str, dict[str, Any]] = {}
        self.dismissed: list[tuple] = []     # (id, cells) of every proposal or auto zone a person said no to, this session
        self.handled: set[str] = set()       # 07's object ids already taken (asked, deduped or failed): never again
        self.failed: list[dict[str, Any]] = []
        self.n_ids = 0
        self.counts = {"asked": 0, "added": 0, "confirmed": 0, "dismissed": 0, "deduped": 0}
        self.sight: dict[str, dict[Any, float]] = {}   # gate 2: object id -> {detector window: clock} at HAZARD_P_MIN+
        self.people: dict[str, dict[str, Any]] = {}    # object id -> its live person zone (never on the map)
        self.gates = self._gates0()
        self._t0 = self._sum_at = None       # the first feed's clock; the last gate summary's
        self._person_why: str | None = None
        self.thr: float | None = None        # the threshold of the last feed, for state()'s why
        self._warned: str | None = None     # what placed objects wait for, logged once per change
        self.error: str | None = None        # the last feed's raise, on the GET until a feed gets past the map read
        self._taking: dict | None = None     # the object this feed took last; a raise before its row lands names it in failed
        self._lock = threading.Lock()        # this store's own state; never held during a model call
        self._off_said = False               # the OFF line is logged once per store, never per feed
        with contextlib.suppress(ValueError):   # a bad value is raised by every feed and GET, not here: the session still starts
            self.mode()

    @staticmethod
    def _gates0() -> dict[str, set]:
        return {k: set() for k in ("considered", "low_p", "repeat", "no_lit", "deduped", "not_a_hazard", "confirm_no", "confirm_failed")}

    def mode(self) -> str:
        """config.scout_zones() ("on" | "person" | "off"), read at each use; logs OFF once per store."""
        m = config.scout_zones()
        if m == "off" and not self._off_said:
            self._off_said = True
            log("scout", OFF)
        return m

    def zones_off(self) -> str | None:
        return OFF if self.mode() == "off" else None

    def _map(self) -> Path:
        return self.map_path or field.MAP

    def _warn(self, *whys: str | None) -> None:
        """One WARN line per change of what placed objects wait for, kept for state()'s why; none: nothing does."""
        why = "; ".join(w for w in whys if w) or None
        if why and why != self._warned:
            log("scout", why)
        self._warned = why

    def feed(self, objs: list[dict], frame: dict, pose: dict | None, grid: occupancy.Grid | None, cal: dict | None,
             fov_deg: float | None, threshold: int = occupancy.THRESHOLD, grid_lock=None, live=None) -> dict[str, int]:
        """One detector window: person zones refreshed, made or expired; every hazard candidate through the gates (see
        the module docstring); returns the counts. live: the newest LiDAR window's band in odometry metres ((N, 2)),
        None with no live view. A raise (a bad WTDD_SCOUT_ZONES or WTDD_DECIDE_THRESHOLD, an unreadable ui/map.json, a
        failed ledger write) is kept as state()["error"] and re-raised for the objects thread's log; the object it was
        taking stays handled and is a line in state()["failed"]."""
        self._taking = None
        try:
            return self._feed(objs, frame, grid, cal, grid_lock, live)
        except Exception as e:
            err = f"feed: {type(e).__name__}: {e}"
            with self._lock:
                self.error = err
                o = self._taking if self._taking and not any(f["object_id"] == self._taking["id"] for f in self.failed) else None
            if o:
                self._fail(o, "feed", err)
            raise

    def _take(self, o: dict) -> None:
        """o is handled from here on: never taken again; a raise before this feed ends names it (feed())."""
        with self._lock:
            self.handled.add(o["id"])
            self._taking = o

    def _photo(self, data: bytes | None, name: str, err: str | None = None) -> dict[str, Any]:
        """The detector frame copied once to the pictures folder: {file, url, path, sha256, bytes}; {missing: true,
        error} when there are no bytes or the copy fails (never a made-up url)."""
        if data is None:
            return {"missing": True, "error": err or "no detector frame"}
        try:
            pdir = self.photo_dir or PHOTOS
            pdir.mkdir(parents=True, exist_ok=True)
            f = pdir / f"scout-{time.strftime('%Y%m%dT%H%M%S')}-{name}.jpg"
            f.write_bytes(data)
        except OSError as e:
            return {"missing": True, "error": f"photo not written: {type(e).__name__}: {e}"}
        return {"file": f.name, "url": f"/pictures/{f.name}", "path": str(f), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    @staticmethod
    def _at(t: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))

    def _persons(self, seen: list[dict], data: bytes | None, derr: str | None, live, grid, now: float, wkey: Any) -> int:
        """Every person 07 saw in this window: refreshed (cells, last seen) when lit, made when new and lit (one
        zone.person row, the photo); a new detector id within PERSON_MERGE_M of a live zone's last pin renews that zone (07
        re-ids one person often: without it one person stacked several zones); then every person zone past PERSON_TTL_S
        is cleared (one zone.person_cleared row)."""
        made, whys = 0, []
        for o in (o for o in seen if o["label"] == PERSON):
            name = f"person-{o['id'].lstrip('o')}"
            z = self.people.get(o["id"])
            if z and z["window"] == wkey:
                continue
            if not z and o.get("hit_m"):   # 07 often gives one person a new id (live 21:23): the nearest live zone is theirs
                near = [(math.dist(v["hit_m"], o["hit_m"]), k) for k, v in self.people.items()
                        if v.get("hit_m") and v["window"] != wkey and now < v["last_seen"] + PERSON_TTL_S]
                if near and min(near)[0] <= PERSON_MERGE_M:
                    with self._lock:   # re-keyed under the new id, its name kept: renewed, never a second zone
                        z = self.people.pop(min(near)[1])
                        z["object_id"] = o["id"]
                        self.people[o["id"]] = z
            cells, pts = lit(live, o["hit_m"], PERSON_R_M, grid, connected=False) if grid is not None else ([], 0)
            if not cells:
                whys.append(f"{name} ({o['id']}) seen but {'no live LiDAR view' if live is None else f'no lit LiDAR point within {PERSON_R_M} m of the pin'}: no person zone")
                continue
            if z:
                z.update(cells=cells, points_n=pts, last_seen=now, window=wkey, p=float(o["p"]), hit_m=list(o["hit_m"]))
                continue
            z = {"name": name, "object_id": o["id"], "p": float(o["p"]), "cells": cells, "points_n": pts, "res": grid.resolution,
                 "hit_m": list(o["hit_m"]),
                 "photo": self._photo(data, name, derr), "first_seen": now, "last_seen": now, "window": wkey}
            with self._lock:
                self.people[o["id"]] = z
            made += 1
            self._row("zone.person", "map", {"zone": name, "object_id": o["id"], "p": z["p"], "points_n": pts, "ttl_s": PERSON_TTL_S},
                      None, {"zone": name, "cells": cells, "expires_at": self._at(now + PERSON_TTL_S), "photo": z["photo"]}, True,
                      f"a person ({o['id']}, p {z['p']:.2f}): a temporary zone of {pts} lit point(s), cleared {PERSON_TTL_S:.0f} s after last seen", 0)
        self._person_why = "; ".join(whys) or None
        for oid, z in list(self.people.items()):
            if now >= z["last_seen"] + PERSON_TTL_S:
                with self._lock:
                    self.people.pop(oid, None)
                self._row("zone.person_cleared", "map", {"zone": z["name"], "object_id": oid, "ttl_s": PERSON_TTL_S},
                          {"zone": z["name"], "expires_at": self._at(z["last_seen"] + PERSON_TTL_S)}, None, True,
                          f"{z['name']} cleared: not seen lit for {PERSON_TTL_S:.0f} s", 0)
        return made

    def _feed(self, objs, frame, grid, cal, grid_lock, live) -> dict[str, int]:
        n = {"handled": 0, "decided": 0, "added": 0, "failed": 0, "deduped": 0, "people": 0}
        mode = self.mode()
        if mode == "off":   # THE gate: no model call, no photo, no zone, no zone.* row; 07's objects are not the scout's
            return n
        now, t_all = self.clock(), time.perf_counter()
        self._t0 = now if self._t0 is None else self._t0
        self._sum_at = now if self._sum_at is None else self._sum_at
        wkey = frame.get("t") or frame.get("ts") or frame.get("file")   # the detector window's own stamp
        placed = [o for o in objs if o.get("pos_px") is not None and o.get("hit_m") is not None and not o.get("stale")]
        seen = [o for o in placed if o.get("windows_unseen", 0) == 0]
        data, derr = None, None
        if any(o["label"] == PERSON and o["id"] not in self.people for o in seen) or mode == "on":   # read only when a photo may be taken
            try:
                data = Path(frame["file"]).read_bytes()
                from PIL import Image
                Image.open(io.BytesIO(data)).verify()
            except (OSError, KeyError, TypeError, SyntaxError) as e:
                data, derr = None, f"frame unreadable, no photo and no question: {type(e).__name__}: {e} (watch.json file {frame.get('file')})"
        n["people"] = self._persons(seen, data, derr, live, grid, now, wkey)
        if mode == "person":   # the filming setting: no hazard zone, no Jev and no confirm call
            return n
        g, cands = self.gates, []
        with self._lock:
            for o in placed:
                if o["label"] == PERSON or o["id"] in self.handled:
                    continue
                g["considered"].add(o["id"])
                s = self.sight.setdefault(o["id"], {})
                if float(o["p"]) < HAZARD_P_MIN:   # gate 1
                    g["low_p"].add(o["id"])
                    continue
                if o in seen:
                    s[wkey] = now
                span = max(s.values()) - min(s.values()) if s else 0.0
                if len(s) < HAZARD_SEEN_N or span < HAZARD_SPAN_S:   # gate 2
                    g["repeat"].add(o["id"])
                    continue
                cands.append((o, len(s), round(span, 1)))
        if cands and (grid is None or cal is None):   # considered again when they are back
            self._warn(f"WARN {len(cands)} hazard candidate(s) waiting: no {'grid' if grid is None else 'calibration'}")
            cands = []
        if cands:
            n = self._hazards(cands, frame, data, derr, grid, cal, grid_lock, live, n)
        self._gate_summary(now)
        return self._summary(n, t_all) if n["handled"] or n["people"] else n

    def _hazards(self, cands, frame, data, derr, grid, cal, grid_lock, live, n) -> dict[str, int]:
        g = self.gates
        thr = self.thr = decide_threshold()
        mp = self._map()
        ver = int(mp.stat().st_mtime)   # the version this feed's writes check: a map changed during a model call is 409
        on_map = [(z.get("name"), _key(z["cells"])) for z in json.loads(mp.read_text()).get("zones", [])
                  if z.get("source") == "scout" and z.get("cells")]   # the scout's zones already on the map
        with self._lock:
            self.error = None   # past the threshold and the map: this feed can ask
        fn, cfn, waiting = self.decide, self.confirm_fn, []   # the model paths are read when a call is about to be made
        for o, seen_n, span_s in cands:
            t0 = time.perf_counter()
            try:   # gate 4, before any model call: the lit cluster around the pin in the newest window
                with grid_lock or contextlib.nullcontext():
                    res = grid.resolution
                    cells, pts = lit(live, o["hit_m"], HAZARD_R_M, grid)
                    poly = polygon(cells, cal, res) if pts >= HAZARD_MIN_POINTS else None
                err = None
            except Exception as e:  # noqa: BLE001  (a failed row and a failed line, never a zone of no cells)
                cells, pts, poly, err = [], 0, None, f"lit cluster FAILED: {type(e).__name__}: {e}"
            if not err and poly is None:   # a wait, not a failure: the thing is considered again at the next window
                g["no_lit"].add(o["id"])
                waiting.append(f"{o['id']} {o['label']} ({'no live view' if live is None else f'{pts} lit point(s) < {HAZARD_MIN_POINTS}'})")
                continue
            self._take(o)
            n["handled"] += 1
            if err or data is None:
                err = err or derr
                self._fail(o, "cells" if data is not None else "frame read", err)
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
                    g["deduped"].add(o["id"])
            if same:
                log("scout", f"{o['id']} is the same thing as {same}: no call, no row", kind=o["label"], cells=len(cells))
                n["deduped"] += 1
                continue
            blob_ms = round((time.perf_counter() - t0) * 1000)
            area = round(len(cells) * res * res, 4)
            q = {"kind": o["label"], "conf": o["p"], "state": None, "labels": list(SCOUT_LABELS)}
            fn = fn or decider()
            t1 = time.perf_counter()
            try:   # outside every lock: a model call can take seconds. Jev names WHAT it is; the gates decide WHETHER
                q["state"] = words(o["label"], o["p"], o["dist_m"], o.get("bearing_deg"), area)
                d, derr2 = fn(q), None
                if d["label"] not in SCOUT_LABELS or not 0.0 <= float(d["p"]) <= 1.0:
                    raise ValueError(f"decision out of contract: label {d['label']!r}, p {d['p']!r}")
            except Exception as e:  # noqa: BLE001  (its own failed zone.decided row, no zone, never retried)
                d, derr2 = None, f"{type(e).__name__}: {e}"
            ms = round((time.perf_counter() - t1) * 1000)
            stub = bool(d["cached"]) if d else fn is decide_stub
            app = d["app"] if d else ("stub" if fn is decide_stub else "openrouter")
            got = {"label": d["label"], "p": float(d["p"]), "model": d["model"]} if d else {"label": None, "p": None, "model": None}
            self._row("zone.decided", app, {"object_id": o["id"], "kind": o["label"], "labels": list(SCOUT_LABELS), **got,
                                            "probabilities": d["probabilities"] if d else None, "threshold": thr},
                      {"state": q["state"], "labels": list(SCOUT_LABELS)}, got if d else None, d is not None,
                      d["raw"] if d else derr2, ms, stub)
            if d is None:
                self._fail(o, None, derr2)
                n["failed"] += 1
                continue
            n["decided"] += 1
            with self._lock:
                self.counts["asked"] += 1
            if d["label"] == "not_a_hazard" or float(d["p"]) < thr:
                g["not_a_hazard"].add(o["id"])
                log("scout", f"{o['id']} stays a pin: {d['label']} at p {float(d['p']):.2f} (threshold {thr})", kind=o["label"])
                continue
            cfn = cfn or confirmer()   # gate 3: the picture, a stronger vision model
            cq = {"kind": o["label"], "conf": float(o["p"]), "model": confirm_model(), "image": None}
            t3 = time.perf_counter()
            try:
                cq["image"] = crop(data, o["box"])
                c, cerr = cfn(cq), None
                if c["answer"] not in ("yes", "no") or not 0.0 <= float(c["p"]) <= 1.0:
                    raise ValueError(f"confirm out of contract: answer {c['answer']!r}, p {c['p']!r}")
            except Exception as e:  # noqa: BLE001  (NO zone and one FAILED row: never a default yes, never retried)
                c, cerr = None, f"{type(e).__name__}: {e}"
            cstub = bool(c["cached"]) if c else cfn is confirm_stub
            conf = {"model": c["model"], "answer": c["answer"], "name": c["name"], "p": float(c["p"])} if c else None
            passed = bool(c) and c["answer"] == "yes" and float(c["p"]) >= CONFIRM_P_MIN and agrees(o["label"], c["name"])
            self._row("zone.confirm", (c["app"] if c else "stub" if cstub else "openrouter"),
                      {"object_id": o["id"], "kind": o["label"], "model": c["model"] if c else cq["model"], "threshold": CONFIRM_P_MIN,
                       **(conf or {"answer": None, "name": None, "p": None}), "passed": passed},
                      {"question": STRICT_QUESTION, "kind": o["label"]}, conf, c is not None, c["raw"] if c else cerr,
                      round((time.perf_counter() - t3) * 1000), cstub)
            if c is None:
                g["confirm_failed"].add(o["id"])
                self._fail(o, "confirm", cerr)
                n["failed"] += 1
                continue
            if not passed:
                g["confirm_no"].add(o["id"])
                log("scout", f"{o['id']} stays a pin: the confirm model said {c['answer']} ({c['name']!r}, p {float(c['p']):.2f}; "
                             f"needs yes, p >= {CONFIRM_P_MIN}, the detector's {o['label']!r} class)", kind=o["label"])
                continue
            with self._lock:
                self.n_ids += 1
                zid = f"z{self.n_ids}"
            t2 = time.perf_counter()
            photo = self._photo(data, zid)
            if photo.get("missing"):
                self._fail(o, "photo write", photo["error"])
                self._row("zone.proposed", "map", {"id": zid, "object_id": o["id"], "kind": o["label"]}, None, None, False, photo["error"], 0, stub)
                n["failed"] += 1
                continue
            stub = stub or cstub
            ev = {"p": float(o["p"]), "seen_n": seen_n, "span_s": span_s, "confirm": conf, "points_n": pts}
            z = {"id": zid, "object_id": o["id"], "kind": o["label"], "label": d["label"], "p": float(d["p"]), "app": "stub" if stub else app,
                 "cells": cells, "cells_px": occupancy.to_map_px(cells, cal).tolist(), "poly": poly, "thumb": o.get("thumb"),
                 "photo": {k: photo[k] for k in ("path", "sha256", "bytes", "file", "url")}, "evidence": ev,
                 "dist_m": o["dist_m"], "area_m2": area, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
            by, before = f"auto ({'stub' if stub else 'jev + ' + c['model']} {z['p']:.2f})", {k: v for k, v in z.items() if k != "thumb"}
            try:   # on the map at once, by confirm's own path and rules
                with self._lock:
                    out, after = self._add(z, "auto", ver, "the scout read it before the model calls; not retried")
                    self.counts["added"] += 1
            except Exception as e:  # noqa: BLE001  (a stale map, a zone 04 refuses, an unwritable file: a failed row, never retried)
                self._fail(o, "map write", f"{type(e).__name__}: {e}")
                self._row("zone.confirmed", "map", {"id": zid, "zone": None, "by": by, "evidence": ev}, before, None, False,
                          f"{type(e).__name__}: {e}", blob_ms + round((time.perf_counter() - t2) * 1000), stub)
                n["failed"] += 1
                continue
            ver = after["_version"]
            on_map.append((out["zone"]["name"], key))   # a second thing on these cells in this feed is the same thing
            self._row("zone.confirmed", "map", {"id": zid, "zone": out["zone"]["name"], "by": by, "evidence": ev}, before, after, True,
                      f"I added a no-go zone around the {o['label']}: seen {seen_n} times over {span_s} s at p {o['p']:.2f}, "
                      f"{pts} lit LiDAR points, and {'the stub (DEMO_CACHE, no picture looked at)' if cstub else c['model']} "
                      f"says it's {c['name']!r} at {float(c['p']):.2f}.",
                      blob_ms + round((time.perf_counter() - t2) * 1000), stub)   # the photo, the write; each call is its own row
            n["added"] += 1
        self._taking = None   # every row landed
        self._warn(f"WARN {len(waiting)} hazard candidate(s) past gates 1 and 2 waiting for a lit LiDAR cluster: {', '.join(waiting)}"
                   if waiting else None)
        return n

    def _gate_summary(self, now: float) -> None:
        """One line every SUMMARY_S: the things considered and the ones each gate rejected (distinct ids); no zone added
        since the first feed is a WARN, never silence."""
        if now - self._sum_at < SUMMARY_S:
            return
        g, added = self.gates, self.counts["added"]
        log("scout", f"{'WARN ' if not added else ''}{added} hazard zone(s) in {(now - self._t0) / 60:.1f} min; the last {now - self._sum_at:.0f} s",
            **{k: len(v) for k, v in g.items()}, people=len(self.people))
        with self._lock:
            self.gates, self._sum_at = self._gates0(), now

    def _summary(self, n: dict, t_all: float) -> dict[str, int]:
        log("scout", f"{'WARN ' if n['handled'] and not n['added'] else ''}feed", **n, open=len(self.open),
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
        """A person's confirm or dismiss under the store's lock: a name and an open id (a dismiss: or an auto zone on the
        map) first, then fn(proposal or map entry, by) -> (out, state_after); one row either way, the failed one written
        before the raise."""
        by = str(by or "").strip()
        with self._lock:
            z = self.open.get(zid)
            before = None if z is None else {k: v for k, v in z.items() if k != "thumb"}
            args = {"id": zid, **({"zone": None} if tool == "zone.confirmed" else {}), "by": by}
            try:
                if not by:
                    raise Refused(400, f"{'a confirm' if tool == 'zone.confirmed' else 'a dismiss'} needs the name of the person making it (by)")
                if z is None and tool == "zone.dismissed":   # an auto zone on the map; never one a person drew (04) or confirmed
                    z = before = next((x for x in json.loads(self._map().read_text()).get("zones", [])
                                       if x.get("name") == zid and x.get("source") == "scout" and x.get("by") == "auto"), None)
                if z is None:
                    raise Refused(404, f"no open proposal{' or auto zone' if tool == 'zone.dismissed' else ''} {zid!r} "
                                       f"(open: {', '.join(self.open) or 'none'})")
                out, after = fn(z, by)
            except Exception as e:
                self._row(tool, "map", args, before, None, False, f"{type(e).__name__}: {e}", round((time.perf_counter() - t0) * 1000))
                raise
            self.open.pop(zid, None)
            self.counts[tool.split(".")[1]] += 1
            if tool == "zone.confirmed":
                args["zone"] = out["zone"]["name"]
            self._row(tool, "map", args, before, after, True, out.get("say"), round((time.perf_counter() - t0) * 1000))
        return {k: v for k, v in out.items() if k != "say"}

    def _rewrite(self, version: Any, verb: str, change: Callable[[list], list],
                 since: str = "this page loaded; reload the page, then try again") -> int:
        """Every scout write to ui/map.json, by POST /map's rules: a version that is not the file's int(mtime) is 409 (a
        stale page, or a map changed during the model call), nogo.zones() must accept the new map (else 400), the previous
        map is kept as map.prev.json. change(zones) -> the new zones. Returns the new version. The caller holds the lock."""
        mp = self._map()
        if version is not None and int(mp.stat().st_mtime) != int(version):   # POST /map's rule: a stale read never overwrites
            raise Refused(409, f"not {verb}: the map changed on the server (version {version}, file {int(mp.stat().st_mtime)}) since {since}")
        old = mp.read_text()
        m = json.loads(old)
        m["zones"] = change(list(m.get("zones") or []))
        try:
            nogo.zones(m)
        except ValueError as e:
            raise Refused(400, f"not {verb}: 04 refuses the map: {e}") from None
        mp.with_name("map.prev.json").write_text(old)   # the previous map survives one overwrite
        mp.write_text(json.dumps(m, indent=2) + "\n")
        return int(mp.stat().st_mtime)

    def _add(self, z: dict, by: str, version: Any, since: str = "this page loaded; reload the page, then try again") -> tuple[dict, Any]:
        """z becomes 04's no-go zone on ui/map.json by _rewrite's rules, the next free nogo-<n>: confirm's (by a person's
        name) and the feed's (by "auto", with the label and p). -> (out, state_after)."""
        box: dict = {}

        def add(zones: list) -> list:
            names, k = {x.get("name") for x in zones}, sum(1 for x in zones if x.get("nogo") is True) + 1
            while f"nogo-{k}" in names:   # NoGoButtons' rule: the next free nogo-<n>
                k += 1
            e = box["e"] = {"name": f"nogo-{k}", "label": f"{z['label']} · {z['p']:.2f} · scout", "poly": z["poly"], "nogo": True,
                            "source": "scout", "cells": z["cells"], "proposal": z["id"], "by": by,
                            **({"app": "stub"} if z["app"] == "stub" else {})}   # DEMO_CACHE provenance survives; 04 ignores the key
            if by == "auto":   # a model's label and p, no person's name: the remote says "auto · <label> · <p>"
                e.update(label=z["label"], p=z["p"], kind="hazard", evidence=z.get("evidence"),
                         photo={k: z["photo"][k] for k in ("file", "url")} if (z.get("photo") or {}).get("file") else None)
            return zones + [e]
        v = self._rewrite(version, "added" if by == "auto" else "confirmed", add, since)
        e = box["e"]
        return {"ok": True, "zone": e, "_version": v, "say": f"{z['id']} is {e['name']} on the map, by {by}"}, {"zone": e, "_version": v}

    def confirm(self, zid: str, by: Any, version: Any = None) -> dict[str, Any]:
        """An open proposal becomes 04's no-go zone on ui/map.json in a person's name (kept; the feed opens none now);
        {ok, zone, _version}."""
        return self._tap("zone.confirmed", zid, by, time.perf_counter(), lambda z, by: self._add(z, by, version))

    def dismiss(self, zid: str, by: Any, version: Any = None) -> dict[str, Any]:
        """The person says no: an open proposal is dropped; an auto zone (by "auto") leaves the map by _rewrite's rules,
        exactly that entry. Either way its cells are remembered (no re-add this session)."""
        def drop(z: dict, by: str) -> tuple[dict, Any]:
            say, after = f"{zid} dismissed by {by}", {"open": len(self.open) - 1}
            if zid not in self.open:
                v = self._rewrite(version, "dismissed", lambda zs: [x for x in zs if not (x.get("name") == zid and x.get("source") == "scout"
                                                                                          and x.get("by") == "auto")])
                say, after = f"I took {zid} (auto · {z['label']} · {z['p']:.2f}) off the map: {by} dismissed it.", {"_version": v}
            self.dismissed.append((zid, _key(z["cells"])))
            return {"ok": True, "dismissed": zid, "say": say}, after
        return self._tap("zone.dismissed", zid, by, time.perf_counter(), drop)

    def state(self, cal: dict | None = None) -> dict[str, Any]:
        """The GET /dog/scout body (without `source`): {n, proposals, zones, auto_zones, gates, _version, failed, why,
        error?}. zones: the hazard zones on the map (kind "hazard", by "auto", with their evidence and photo) then the
        live person zones (kind "person", temporary, expires_at, photo, poly through cal, the calibration in force now;
        poly None without one), none past its TTL. _version is the map's (a dismiss sends it back); gates counts the
        things considered and rejected per gate since the last summary line; why names the reason whenever nothing is
        served (OFF when off); error is the last feed's raise (the page draws it red)."""
        mode = self.mode()
        mp = self._map()
        v = int(mp.stat().st_mtime)
        zones = [{**z, "kind": z.get("kind") or "hazard"} for z in json.loads(mp.read_text()).get("zones", [])
                 if z.get("source") == "scout" and z.get("by") == "auto"]
        now = self.clock()
        with self._lock:
            props = [{k: z[k] for k in PROPOSAL_KEYS} for z in self.open.values()]
            failed, c = [dict(f) for f in self.failed], dict(self.counts)
            handled, warned, error, pwhy = len(self.handled), self._warned, self.error, self._person_why
            people = [dict(z) for z in self.people.values() if now < z["last_seen"] + PERSON_TTL_S]
            gates = {k: len(x) for k, x in self.gates.items()}
        if mode != "off":
            zones += [{"name": z["name"], "kind": "person", "label": PERSON, "temporary": True, "object_id": z["object_id"], "p": z["p"],
                       "expires_at": self._at(z["last_seen"] + PERSON_TTL_S), "points_n": z["points_n"], "cells": z["cells"],
                       "photo": {k: z["photo"][k] for k in ("file", "url")} if z["photo"].get("file") else z["photo"],
                       "poly": polygon(z["cells"], cal, z["res"]) if cal else None} for z in people]
        why = None
        if not props:
            if not handled:
                why = warned or ("no object taken: the last feed FAILED (error)" if error else
                                 f"no hazard candidate yet: a zone needs p >= {HAZARD_P_MIN}, {HAZARD_SEEN_N} windows over "
                                 f"{HAZARD_SPAN_S:.0f} s, a lit cluster of {HAZARD_MIN_POINTS}+ points and the confirm model's yes")
            else:
                parts = [f"{c['asked']} asked, {c['added']} added to the map as a hazard past the four gates"]
                parts += [f"{c[k]} {k}" for k in ("confirmed", "dismissed", "deduped") if c[k]]
                parts += [f"{len(failed)} failed (listed)"] if failed else []
                parts += [warned] if warned else []
                why = "no open proposal: " + ", ".join(parts)
            why = "; ".join(w for w in (why, pwhy) if w)
            why = OFF if mode == "off" else why
        auto = {"on": "on", "person": "person only (WTDD_SCOUT_ZONES=person)", "off": "off (WTDD_SCOUT_ZONES=0)"}[mode]
        return {"n": len(props), "proposals": props, "zones": zones, "auto_zones": auto, "gates": gates,
                "_version": v, "failed": failed, "why": why,
                **({"error": error} if error else {})}

def png(grid: occupancy.Grid, threshold: int, cells, path) -> Path:
    """occupancy.png, then every zone cell one PNG_SCALE square in CELL_RGB (grid rows and columns, not the map)."""
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
    ap = argparse.ArgumentParser(prog="python -m wtdd.dog.scout_zones", description="Replay LiDAR frames and one detector window: add the scout's zones to a scratch map (stub), draw their cells.")
    ap.add_argument("--replay", required=True, help="npz of wire-format frames (wtdd/dog/fixtures/voxel_frames.npz)")
    ap.add_argument("--watch", required=True, help="a watch.json-shaped detector window (wtdd/dog/fixtures/watch-frame.json)")
    ap.add_argument("--pose", required=True, help="x,y,yaw of the dog in the frames' odometry (metres, radians)")
    ap.add_argument("--fov", type=float, required=True, help="the camera's horizontal field of view, degrees")
    ap.add_argument("--png", required=True, help="where the grid PNG with the zone cells goes")
    ap.add_argument("--threshold", type=int, default=occupancy.THRESHOLD, help=f"frames a cell must be seen in (default {occupancy.THRESHOLD})")
    a = ap.parse_args(argv)
    t_all = time.perf_counter()
    try:
        from .fixtures.make_objects_fixture import CAL
        g, last = None, None
        for d in occupancy.replay(a.replay):
            if g is None:
                g = occupancy.Grid.from_frame(d)
            g.update_frame(d)
            last = d
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
            # DEMO_CACHE: the replay always asks decide_stub and confirm_stub (the detector's conf, no picture looked
            # at), even with JEV_API_KEY or OPENROUTER_API_KEY set, and feeds its ONE window HAZARD_SEEN_N times
            # HAZARD_SPAN_S apart on a replay clock. Why: a replay of fixtures is not a step and must not spend a model
            # call or claim a live answer or a real repeat. Live: the session's feed (GET /dog/objects starts it) asks
            # decider() and confirmer() once per thing past the gates, on real windows.
            clock = [0.0]
            props = Proposals(append=lambda r: log("scout", "replay row (not written)", tool=r["tool"], ok=r["ok"]),
                              decide=decide_stub, confirm=confirm_stub, photo_dir=tmp, map_path=Path(tmp) / "map.json",
                              clock=lambda: clock[0])
            live = localize.band(last["points"])   # the last replayed window, as the session's _live_m
            for k in range(HAZARD_SEEN_N):
                props.feed(store.to_list(), {**frame, "t": k}, pose, g, CAL, a.fov, a.threshold, live=live)
                clock[0] += HAZARD_SPAN_S / (HAZARD_SEEN_N - 1)
            st = props.state(CAL)
        st["zones"] = [z for z in st["zones"] if z["kind"] == "hazard"]
        for z in st["zones"]:
            log("scout", z["name"], label=z["label"], p=z["p"], by=z["by"], cells=len(z["cells"]), poly=z["poly"])
        png(g, a.threshold, [c for z in st["zones"] for c in z["cells"]], a.png)
    except Exception as e:  # noqa: BLE001  (reported with the path, non-zero exit; nothing written stands in for it)
        log("scout", "FAILED", err=f"{type(e).__name__}: {e}")
        return 1
    log("scout", "replay done", added=len(st["zones"]), failed=len(st["failed"]), placed=sum(o["pos_px"] is not None for o in store.to_list()),
        frames=g.frames, threshold=a.threshold, fov_deg=a.fov, cal="make_objects_fixture.CAL (the tests' tie)", png=a.png,
        ms=round((time.perf_counter() - t_all) * 1000))
    if not st["zones"]:
        log("scout", f"WARN added=0: {st['why']} (the PNG has the grid, no zone cell)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
