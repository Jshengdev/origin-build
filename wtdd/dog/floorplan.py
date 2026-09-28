"""The floor plan: walls as straight runs and furniture as grey, sorted from the LiDAR's own cells by the height
profile of each cell (Grid.zmask, wtdd/dog/occupancy.py) and by straightness. No model draws or labels anything here;
walls and furniture, not rooms.

Run. The session (wtdd/dog/session.py) runs run() off the driver's dispatcher, on its own thread, at most once per
FLOORPLAN_S and only when grid.frames advanced (floorplan_tick), and always on POST /dog/floorplan (the button); GET
/dog/floorplan serves the newest result in map pixels and the remote draws it over the grid. Offline:

    python -m wtdd.dog.floorplan --replay wtdd/dog/fixtures/voxel_furniture.npz --png /tmp/fp.png [--threshold N] [--tall M] [--save F]

replays the frames through the driver's own decoder into a grid (occupancy.replay), classifies it, prints the same
`[wtdd:floorplan]` line run() prints, and draws a PNG (PNG_SCALE px per cell, row = grid row: white empty, ink wall,
purple tall, grey slab, light grey low, the segments in blue). It writes no ledger row: a replay of a fixture, not a
step. Exit 0; 2 with `WARN no wall found` (the PNG is still written); 1 with FAILED.

How. Only the cells seen threshold+ times are classified. A cell's profile is its mask's layers at or above FLOOR
(below is floor clutter); its lowest such layer below GROUND makes it grounded, else it floats (a table top, a shelf
board: nothing under it). A wall is a grounded cell on a straight run at least RUN long, at ANY height: the
head-mounted cone sees a far wall only low, so a height-only rule would call it furniture. The runs: a 180-angle
rho histogram over the grounded cells picks the main direction (the most concentrated offsets: a one-cell window slid
along them in quarter-cell steps, its counts squared and summed) and its orthogonal; per direction and integer offset,
the unused cells within one cell of the line are sorted along it and split where consecutive cells are more than GAP
apart; a run qualifies by its EXTENT (end to end), never its cell count; the longest (then the fullest) run over both
directions is taken, it and every cell within THICK of its line inside its extent (the wall's own thickness) are
marked used in that direction only (a corner's cells stay free for the orthogonal wall), and the rest re-run until
none qualifies. So a wall that is thick, turned, or meets another at a corner is one segment. A segment lies on the mode offset of its cells, from its first
to its last cell, at cell CORNERS in odometry metres (index * res + origin, the walls() convention). Classes: 1 wall,
2 tall blob (grounded, off every run, top at or above TALL), 5 low blob (grounded, off every run, below TALL),
3 floating slab, 0 empty. Numpy only; PIL only inside png().

Heights (S13, the remote's 2.5D view). A classified cell's top is its highest layer at or above FLOOR in metres
(z_ref + layer * resolution, the z FLOOR, GROUND and TALL are in: above the floor only where z = 0 is the floor,
UNVERIFIED below); a segment's top is the highest over the cells it took. GET /dog/floorplan serves both rounded to
0.05 (to_px). Measured layers only: a grid with no height profile (saved before item 15) serves none, never zeros.

Known limit, ours by design: a shelf or a cabinet standing against a wall is grounded and straight, so it is a wall
here (the fixture's 2 m shelf is class 1 and the tests say so). Only goal 16's label may move such a run to grey; a
label never adds, moves or widens a cell or a line. For the same reason anything grounded within THICK of a wall's
line (a box pushed against it) is that wall's thickness, class 1. And the limit is wider than walls: any grounded blob
at least RUN long, free-standing or not (a sofa, a bed, a counter, a desk with a modesty panel or a pedestal), is wall,
drawn as parallel runs about THICK plus one cell apart across its whole depth (a 2 x 0.9 m sofa 0.45 m high, alone in
a room: 4 runs, every cell wall, none grey); a table on legs is not, because its top floats. Here too only goal 16's
label may move such runs to grey.

Known limit of the runs (tests: ClosedRoom): walls 1 and 2 cells thick are one segment each, every cell a wall, at
every turn of the room; 3 cells thick is one segment each square and at 30 degrees, but at a few turns (a 1-degree
sweep: 17, 18, 35, 44, 46, 55 and 72 degrees) up to 2% of its outermost staircase cells fall outside THICK and show as
tall or low singletons. Walls thicker than that, or a site whose walls are not at right angles to each other (only two
directions are searched, in whole degrees), give extra segments.

UNVERIFIED on the real dog: where z = 0 sits (the fixture guesses the first window's z origin at -0.3 m; if z = 0 is
the LiDAR, two knobs shift together by the mount height: this constants block (FLOOR, GROUND, TALL) and 01's band
lidar.Z_MIN/Z_MAX, which picks the cells that get classified at all, since only cells counted threshold+ times inside
that band are read; a band set too high never counts the box, the chair seat or the low part of a wall, whatever FLOOR,
GROUND and TALL say; set both from the first live frame's z range, Needs the dog 15.1); every constant below; how high
a wall at 3 m is seen through the cone (tunes TALL); how thick a wall accumulates over a walk (noise and odometry
drift; THICK holds up to about 3 cells); the whole rule set until the first live frame. No accuracy number is claimed."""
from __future__ import annotations
import argparse
import math
import sys
import time
from typing import Any

import numpy as np

from .. import ledger
from ..ledger import log
from . import nav, occupancy

FLOOR = 0.10   # m: layers below this are floor clutter, never part of a cell's profile. UNVERIFIED until the first live frame shows where z = 0 sits
GROUND = 0.30   # m: a cell whose lowest layer at or above FLOOR is below this stands on the floor (grounded). UNVERIFIED
TALL = 1.10   # m: a grounded blob off every run whose top reaches this is tall (a post, a person, a door frame). UNVERIFIED (15.2: how high a far wall is seen)
RUN = 1.0   # m: a straight run of grounded cells at least this long end to end is a wall, whatever its height. UNVERIFIED
GAP = 0.2   # m: a run splits where consecutive cells along its line are further apart than this. UNVERIFIED
THICK = 0.15   # m: the grounded cells this close to a taken wall's line, inside its extent, are its thickness, never a second parallel run. UNVERIFIED
FLOORPLAN_S = 2.0   # s: the session runs the floor plan at most this often, and only when grid.frames advanced
ROW_S = 30.0   # s: the ticker's quiet runs are one summary dog.floorplan row at most this often (live: 552 rows in 35 min buried the receipts)
ROW_CELLS, ROW_SHARE = 3, 0.10   # a class count moving by more than max(ROW_CELLS, ROW_SHARE of it), or the segment count changing, is a change: a row at once
CLASS_NAMES = {1: "wall", 2: "tall", 3: "slab", 5: "low"}   # 0 is empty: never counted, never named
COLOURS = {0: (255, 255, 255), 1: (38, 35, 35), 2: (120, 60, 160), 3: (150, 150, 150), 5: (205, 205, 205)}   # the PNG
SEG_RGB = (11, 13, 196)   # the PNG's segments, the remote's blue


class NoWall(Exception):
    """A run that found no wall: its row is ok=false, the page says it in red."""


def _layer(z: float, grid: occupancy.Grid) -> int:
    """The first absolute layer at or above z metres, clamped to 0..64."""
    return min(max(math.ceil((z - grid.z_ref) / grid.resolution - 1e-6), 0), 64)


def _runs(ix: np.ndarray, iy: np.ndarray, res: float) -> tuple[list[tuple], np.ndarray, list[int], int, list[np.ndarray]]:
    """Grounded cells (grid indices) -> (segments in grid index units [(x0, y0, x1, y1, cells)], on-run bool per cell,
    the two directions in degrees, the most cells in one cell of offset along the main direction, and per segment the
    indices of the cells it took, its thickness included: a corner cell or a shelf column within THICK of two lines is
    in both)."""
    n = len(ix)
    on = np.zeros(n, dtype=bool)
    if n == 0:
        return [], on, [], 0, []
    x, y = ix.astype(np.float64), iy.astype(np.float64)
    score, peaks = [], []
    for a in range(180):
        # how concentrated the offsets are: the cells in a one-cell window slid along rho in quarter-cell steps, the
        # counts squared and summed. The single highest 1-cell bin ties a thick or cornered wall with a 1-degree tilt;
        # fixed bins split a turned wall's staircase in two. Quarter bins by floor: a whole offset stays in one.
        q = np.floor((x * math.cos(math.radians(a)) + y * math.sin(math.radians(a))) * 4).astype(np.int64)
        cum = np.concatenate([[0], np.cumsum(np.bincount(q - q.min() + 3), dtype=np.int64), np.zeros(3, np.int64)])
        cum[-3:] = cum[-4]   # 3 empty quarter bins at each end: every window that touches a cell is counted
        w = cum[4:] - cum[:-4]
        score.append(int((w * w).sum()))
        peaks.append(int(w.max()))
    a0 = int(np.argmax(score))
    dirs = [a0, (a0 + 90) % 180]
    bands = []   # (direction 0 | 1, rho, along, cell indices within one cell of an integer offset, sorted along the line)
    for d, a in enumerate(dirs):
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        rho, along = x * c + y * s, -x * s + y * c
        for o in np.unique(np.rint(rho)):
            idx = np.nonzero(np.abs(rho - o) <= 1 + 1e-9)[0]
            bands.append((d, rho, along, idx[np.argsort(along[idx], kind="stable")]))
    used = np.zeros((2, n), dtype=bool)   # per direction: a wall's corner cells stay free for the orthogonal wall that shares them

    def best(b):
        d, rho, along, idx = b
        k = idx[~used[d][idx]]
        out = None
        for part in np.split(k, np.nonzero(np.diff(along[k]) > GAP / res + 1e-9)[0] + 1) if len(k) else []:
            ext = (along[part[-1]] - along[part[0]]) * res
            if ext >= RUN - 1e-9 and (out is None or (ext, len(part)) > out[:2]):
                out = (ext, len(part), part)
        return out

    cand = [best(b) for b in bands]
    segs, takes = [], []
    while any(cand):
        i = max((j for j in range(len(cand)) if cand[j]), key=lambda j: cand[j][:2])
        d, rho, along, _idx = bands[i]
        part = cand[i][2]
        r = np.rint(rho[part]).astype(np.int64)
        m = int(np.argmax(np.bincount(r - r.min())) + r.min())   # the mode offset: the wall, not the shelf beside it
        c, s = math.cos(math.radians(dirs[d])), math.sin(math.radians(dirs[d]))
        t0, t1 = along[part].min(), along[part].max()
        segs.append((m * c - t0 * s, m * s + t0 * c, m * c - t1 * s, m * s + t1 * c, int(len(part))))
        # the wall's own thickness: every cell within THICK of its line and inside its extent is this wall, used in
        # this direction only (a thick or turned wall is one run, never a parallel sliver per row of cells)
        take = (np.abs(rho - m) <= THICK / res + 1e-9) & (along >= t0 - 1e-9) & (along <= t1 + 1e-9)
        take[part] = True
        used[d][take] = on[take] = True
        takes.append(np.nonzero(take)[0])
        # removing cells only shrinks or splits runs: a band whose best run kept all its cells keeps it
        cand = [best(b) if c_ is not None and used[b[0]][c_[2]].any() else c_ for b, c_ in zip(bands, cand)]
    return segs, on, dirs, peaks[a0], takes


def _plan(grid: occupancy.Grid, threshold: int, tall: float) -> dict[str, Any]:
    """classes() and segments() in one pass: {cls, segments (odometry metres, 3 dp), runs, full, why?, dirs, peak}; runs[k]
    is segment k's cells as an int array (m, 2) of [ix, iy], every one class 1 (goal 16's erase greys a run by them);
    full[k] is True when any of them was seen at or above `tall` (a full-height wall: goal 16 never offers it to a model
    and its erase never greys it). Plus, when the grid has a height profile, top (S13): float32 [iy, ix], each
    classified cell's top in metres, NaN elsewhere (a segment's top is the highest over its runs[k], to_px)."""
    if threshold < 1:
        raise ValueError(f"threshold must be at least 1 frame, got {threshold}")
    cls = np.zeros(grid.counts.shape, dtype=np.uint8)
    iy, ix = np.nonzero(grid.counts >= threshold)
    out = {"cls": cls, "segments": [], "runs": [], "full": [], "dirs": [], "peak": 0}
    if len(ix) == 0:
        return {**out, "why": f"no wall found: 0 cells seen {threshold}+ times in {grid.frames} frames"}
    m = grid.zmask[iy, ix]
    if grid.z_ref is None or not m.any():
        return {**out, "why": "no wall found: no height profile in this grid (saved before item 15)"}
    bits = ((m[:, None] >> np.arange(64, dtype=np.uint64)) & np.uint64(1)).astype(bool)   # (cells, 64)
    bits[:, :_layer(FLOOR, grid)] = False
    has = bits.any(axis=1)
    lowest = np.argmax(bits, axis=1)
    top = 63 - np.argmax(bits[:, ::-1], axis=1)
    grounded = has & (lowest < _layer(GROUND, grid))
    segs, on, dirs, peak, takes = _runs(ix[grounded], iy[grounded], grid.resolution)
    onrun = np.zeros(len(ix), dtype=bool)
    onrun[np.nonzero(grounded)[0][on]] = True
    tallc = top >= _layer(tall, grid)
    cls[iy, ix] = np.select([grounded & onrun, grounded & tallc, grounded, has], [1, 2, 5, 3], 0).astype(np.uint8)
    r, (ox, oy) = grid.resolution, grid.origin
    out["segments"] = [tuple(round(float(v), 3) for v in (ox + x0 * r, oy + y0 * r, ox + x1 * r, oy + y1 * r)) + (n,)
                       for x0, y0, x1, y1, n in segs]
    out["runs"] = [np.column_stack([ix[grounded][t], iy[grounded][t]]) for t in takes]
    out["full"] = [bool(tallc[grounded][t].any()) for t in takes]
    z = grid.z_ref + top * r   # each cell's highest measured layer in metres, the z FLOOR, GROUND and TALL are in
    out["top"] = np.full(cls.shape, np.nan, dtype=np.float32)   # float32: served rounded to 0.05
    out["top"][iy[has], ix[has]] = z[has]
    if not (cls == 1).any():
        out["why"] = f"no wall found: {len(ix)} cells, 0 grounded straight runs >= {RUN} m"
    return {**out, "dirs": dirs, "peak": peak}


def classes(grid: occupancy.Grid, threshold: int = occupancy.THRESHOLD, tall: float = TALL) -> np.ndarray:
    """uint8 [iy, ix], the shape of grid.counts: 0 empty, 1 wall, 2 tall blob, 3 floating slab, 5 low blob."""
    return _plan(grid, threshold, tall)["cls"]


def segments(grid: occupancy.Grid, threshold: int = occupancy.THRESHOLD) -> list[tuple]:
    """[(x0, y0, x1, y1, cells)] in odometry metres at cell corners: one per straight wall run."""
    return _plan(grid, threshold, TALL)["segments"]


def _counts(cls: np.ndarray) -> dict[str, int]:
    return {name: int((cls == v).sum()) for v, name in CLASS_NAMES.items()}


def _line(counts: dict, p: dict, ms: float, threshold: int, source: str) -> None:
    """The one `[wtdd:floorplan]` line per run (run() and the CLI): a WARN when any class or the segment count is 0."""
    zero = [k for k, v in counts.items() if v == 0] + ([] if p["segments"] else ["segments"])
    log("floorplan", ("WARN " if zero else "") + "floor plan", **counts, segments=len(p["segments"]), ms=ms, threshold=threshold,
        source=source, dirs=p["dirs"], peak=p["peak"], **({"zero": ",".join(zero)} if zero else {}))


def run(grid: occupancy.Grid, threshold: int = occupancy.THRESHOLD, *, tall: float = TALL, grid_source: str = "session",
        quiet: bool = False) -> dict[str, Any]:
    """One floor plan and one `dog.floorplan` row. Returns {ok, why?, threshold, frames, cells, classes, segments, ms, ts,
    grid_source, cls, runs, full, origin, resolution, top?} (top only from a grid with a height profile); no wall is
    ok=false with `why` (the row already says so); any other raise propagates after its failed row. quiet (the
    session's ticker): the same result with no row, except a failure, which is always its failed row; the ticker
    writes the row itself on a change or a summary (record)."""
    t0 = time.perf_counter()
    args = {"threshold": threshold, "constants": {"FLOOR": FLOOR, "GROUND": GROUND, "TALL": tall, "RUN": RUN, "GAP": GAP, "THICK": THICK},
            "grid_source": grid_source}
    before = {"cells": int((grid.counts >= threshold).sum()), "frames": grid.frames}
    out: dict[str, Any] = {"ok": False, "threshold": threshold, "frames": grid.frames, "cells": before["cells"],
                           "grid_source": grid_source, "origin": list(grid.origin), "resolution": grid.resolution}
    def fill() -> dict[str, Any]:
        p = _plan(grid, threshold, tall)
        counts, ms = _counts(p["cls"]), round((time.perf_counter() - t0) * 1000, 1)
        out.update(classes=counts, segments=p["segments"], ms=ms, cls=p["cls"], runs=p["runs"], full=p["full"],
                   **({"top": p["top"]} if "top" in p else {}))
        _line(counts, p, ms, threshold, grid_source)
        return p

    try:
        if quiet:
            try:
                p = fill()
            except Exception:  # noqa: BLE001  (a failure is always a row: written here, then raised as before)
                with ledger.step("dog", "dog.floorplan", "map", args, before):
                    raise
            if out["classes"]["wall"] == 0:
                raise NoWall(p.get("why") or "no wall found")
        else:
            with ledger.step("dog", "dog.floorplan", "map", args, before) as r:
                if grid_source != "session":
                    r["cached"], r["source"] = True, "stub"   # a saved grid, not this session's frames (session.floorplan's DEMO_CACHE)
                p = fill()
                r["state_after"] = {"classes": out["classes"], "segments": [list(s) for s in p["segments"]], "ms": out["ms"]}
                if out["classes"]["wall"] == 0:
                    raise NoWall(p.get("why") or "no wall found")
        out["ok"] = True
    except NoWall as e:
        out["why"] = f"floor plan: {e}"
    out["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return out


def signature(res: dict[str, Any]) -> tuple:
    """What a quiet run is compared on: ok, the class counts and the segment count."""
    return (bool(res.get("ok")), dict(res.get("classes") or {}), len(res.get("segments") or []))


def changed(a: tuple | None, b: tuple) -> bool:
    """A real change since the last written row: ok flipped, the segment count moved, or a class count moved by more
    than max(ROW_CELLS, ROW_SHARE of it). No row yet is a change."""
    if a is None or a[0] != b[0] or a[2] != b[2]:
        return True
    return any(abs(b[1].get(k, 0) - a[1].get(k, 0)) > max(ROW_CELLS, ROW_SHARE * a[1].get(k, 0)) for k in set(a[1]) | set(b[1]))


def record(res: dict[str, Any], *, reason: str, ticks: int, tall: float = TALL) -> None:
    """The ticker's one dog.floorplan row for a quiet result: the same shape as run()'s row, plus why it was written
    (changed | summary) and how many ticks it stands for since the last row. ok=false with the no-wall reason."""
    args = {"threshold": res["threshold"], "constants": {"FLOOR": FLOOR, "GROUND": GROUND, "TALL": tall, "RUN": RUN, "GAP": GAP, "THICK": THICK},
            "grid_source": res["grid_source"], "reason": reason, "ticks": ticks}
    try:
        with ledger.step("dog", "dog.floorplan", "map", args, {"cells": res["cells"], "frames": res["frames"]}) as r:
            r["state_after"] = {"classes": res.get("classes"), "segments": [list(s) for s in res.get("segments") or []], "ms": res.get("ms")}
            if not res.get("ok"):
                raise NoWall(str(res.get("why") or "no wall found").removeprefix("floor plan: "))
    except NoWall:
        pass


def to_px(res: dict[str, Any], cal: dict) -> dict[str, Any]:
    """A run()'s result in map pixels through a calibration (occupancy.to_map_px, the LiDAR dots' own projection):
    {cell_px, segments_px [[x0, y0, x1, y1]], class_px {name: [[px, py]] cell corners}}, and from a grid with a height
    profile segments_top_m [m per segments_px entry, the highest over its runs[k], so 16's erase keeps them parallel]
    and class_top_m {name: [m per class_px cell]}, rounded to 0.05."""
    r, o = res["resolution"], np.asarray(res["origin"], dtype=np.float64)
    out = {"cell_px": round(r * nav.PX_PER_M, 1),
           "segments_px": [occupancy.to_map_px([s[:2], s[2:4]], cal).reshape(-1).tolist() for s in res["segments"]],
           "class_px": {name: occupancy.to_map_px(np.argwhere(res["cls"] == v)[:, ::-1] * r + o, cal).tolist()
                        for v, name in CLASS_NAMES.items()}}
    if "top" in res:   # absent, never zeros, when the grid measured no heights (its why says so)
        m = lambda a: (np.rint(np.asarray(a, dtype=np.float64) * 20) / 20).tolist()   # noqa: E731  (metres to 0.05)
        out.update(segments_top_m=m([res["top"][c[:, 1], c[:, 0]].max() for c in res["runs"]]),   # runs[k]: [ix, iy] rows
                   # a boolean mask reads in argwhere's order: parallel to class_px
                   class_top_m={name: m(res["top"][res["cls"] == v]) for v, name in CLASS_NAMES.items()})
    return out


def png(grid: occupancy.Grid, cls: np.ndarray, segs: list[tuple], path) -> None:
    """The classes as stored (row = iy, not rotated onto the map), PNG_SCALE px per cell, the segments drawn on top."""
    from PIL import Image, ImageDraw
    lut = np.full((256, 3), 255, dtype=np.uint8)
    for v, rgb in COLOURS.items():
        lut[v] = rgb
    s = occupancy.PNG_SCALE
    im = Image.fromarray(np.repeat(np.repeat(lut[cls], s, axis=0), s, axis=1))
    d, (ox, oy), r = ImageDraw.Draw(im), grid.origin, grid.resolution
    for x0, y0, x1, y1, _n in segs:
        d.line([((x - ox) / r * s + s / 2, (y - oy) / r * s + s / 2) for x, y in ((x0, y0), (x1, y1))], fill=SEG_RGB, width=2)
    im.save(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wtdd.dog.floorplan", description="Replay stored LiDAR frames and draw the floor plan.")
    ap.add_argument("--replay", required=True, help="npz of wire-format frames (wtdd/dog/fixtures/voxel_furniture.npz)")
    ap.add_argument("--png", required=True, help="where the classes PNG goes")
    ap.add_argument("--threshold", type=int, default=occupancy.THRESHOLD, help=f"frames a cell must be seen in (default {occupancy.THRESHOLD})")
    ap.add_argument("--tall", type=float, default=TALL, help=f"metres a blob's top must reach to be tall (default {TALL})")
    ap.add_argument("--save", help="also write the grid json, masks included (ui/grid.json is what the page falls back to)")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    try:
        g = None
        for d in occupancy.replay(a.replay):
            if g is None:
                g = occupancy.Grid.from_frame(d)
            g.update_frame(d)
        if g is None:
            raise ValueError(f"{a.replay} holds no frames")
        p = _plan(g, a.threshold, a.tall)
        counts, ms = _counts(p["cls"]), round((time.perf_counter() - t0) * 1000, 1)
        png(g, p["cls"], p["segments"], a.png)
        saved = g.save(a.save) if a.save else None
    except Exception as e:  # noqa: BLE001  (reported with the path, exit 1; nothing written stands in for it)
        log("floorplan", "FAILED", err=f"{type(e).__name__}: {e}", replay=a.replay)
        return 1
    _line(counts, p, ms, a.threshold, "replay")
    log("floorplan", "replay done", frames=g.frames, segs=[list(s) for s in p["segments"]], png=a.png, saved=saved)
    if counts["wall"] == 0:
        log("floorplan", "WARN no wall found", why=p.get("why"), png=a.png)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
