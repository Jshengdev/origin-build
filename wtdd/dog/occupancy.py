"""The site drawn by the dog's own LiDAR: every decoded voxel window is accumulated into one 2D occupancy grid in the
odometry frame, so the map keeps what the dog has seen instead of only the newest 6.4 m window.

Run. Body._on_lidar (wtdd/dog/body.py) hands every decoded frame to the session (wtdd/dog/session.py), whose grid
takes it through update_frame(); GET /dog/grid serves walls(threshold) in map pixels through the same calibration as
the LiDAR dots (to_map_px is nav.to_map vectorised), and the remote draws it under the dots. POST /dog/grid {save}
writes ui/grid.json (runtime, gitignored) with the calibration it was tied to (`cal`): a saved grid carries that tie
and the page draws it through that, not the current one, because its cells are in the odometry frame of the power-on
that made them; {clear} drops the grid after a power cycle. Offline:

    python -m wtdd.dog.occupancy --replay wtdd/dog/fixtures/voxel_frames.npz --png /tmp/grid.png [--threshold N] [--save F]

runs the driver's own decoder on each stored frame (wtdd/dog/fixtures/make_voxel_frames.py), accumulates, and writes
a PNG (PNG_SCALE px per cell, row = grid row, white empty, grey seen fewer than N times, black walls; no axes, no
text), one stderr line per frame and a summary. It writes no ledger row: a replay of a fixture, not a step.

How. Grid.counts is uint32 [iy, ix]; cell (0, 0)'s corner is `origin` (x0, y0) in metres, both taken from the first
frame's own `origin` and `resolution`. update(points) keeps lidar.Z_MIN..Z_MAX (the dots' band), snaps each (x, y)
to the nearest lattice cell (np.rint((x - x0) / res): the driver's points sit on the lattice when the window origin
does; a live origin off the lattice lands in the nearest cell), and adds 1 per distinct cell per frame, however many
z voxels stack there. A point outside the grid grows it on that side by max(needed, GROW_MARGIN) cells
(deterministic: the same frames give the same shape), up to MAX_SIDE cells per side (120 m at 0.05 m); past that the
frame is refused with ValueError (a runaway origin is not allocated). walls(threshold) is the cells seen at least
threshold times, as cell CORNERS in metres (index * res + origin, the driver's convention for the dots). Shapes are
only cells counted from points; no model draws or labels anything here.

The height profile (item 15, read by wtdd/dog/floorplan.py). Grid.zmask is uint64 [iy, ix], the same shape as counts
and grown with it in _grow: bit k set means absolute layer k was seen in that cell at least once, z = z_ref + k * res,
with z_ref the first frame's origin[2]. It is band-free (the floor, a table top and a wall's top all land in it) and
ORed per frame with np.unique + np.bitwise_or.at, even when the band is empty. A later frame with another origin[2]
lands on the same lattice, because its points are absolute metres; update_frame counts it in z_rebased with a WARN.
A layer outside 0..63 is a WARN and dropped, never wrapped (z_dropped). counts and walls(threshold) are exactly what
they were before the mask. ui/grid.json keeps it as a fourth column; a 01-era file loads with an empty mask.

UNVERIFIED on the real dog (the first live frame must confirm; lidar.py's docstring has the same list): the value of
frame_id (expected "odom"; a frame with another frame_id than the grid's is refused); whether the window `origin`
moves with the dog over a fixed world (the fixture assumes it does; if the points are body-relative the grid smears
into a streak); where z = 0 sits (the Z_MIN/Z_MAX band; z_ref is the first frame's origin[2], the fixture guesses
-0.3 m); whether origin[2] moves between frames (z_rebased must stay 0 live); what the four wire bytes 8-11 carry
(the driver skips them). The grid is in the odometry frame and smears with drift; nothing here corrects it."""
from __future__ import annotations
import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from ..ledger import log
from . import lidar, nav

THRESHOLD = 3        # frames a cell must be seen in to be drawn as a wall (GET /dog/grid?threshold=N, --threshold N)
PNG_SCALE = 4        # PNG pixels per grid cell (--png)
GROW_MARGIN = 128    # the first allocation per side and the least a side grows by (one 128-voxel window)
MAX_SIDE = 2400      # cells per side, 120 m at 0.05 m: a frame that would grow the grid past this is refused


class Grid:
    """Occupied counts on a lattice in the odometry frame (see the module docstring)."""

    def __init__(self, resolution: float, origin_xy, frame_id: str | None = None, z_ref: float | None = None) -> None:
        self.resolution = float(resolution)
        self.origin = [float(origin_xy[0]), float(origin_xy[1])]   # metres: the corner of cell (0, 0)
        self.counts = np.zeros((GROW_MARGIN, GROW_MARGIN), dtype=np.uint32)   # [iy, ix]
        self.zmask = np.zeros(self.counts.shape, dtype=np.uint64)   # [iy, ix]: bit k = absolute layer k seen (z_ref + k * res), band-free
        self.z_ref = None if z_ref is None else float(z_ref)   # metres: the first frame's origin[2]; None in a 01-era saved grid (no mask)
        self.z_rebased = 0   # frames whose origin[2] moved (a WARN each, re-based onto z_ref's lattice); must stay 0 live, UNVERIFIED
        self.z_dropped = 0   # voxels the mask could not take: a layer outside 0..63 (a WARN) or a point outside the grid
        self._z_last = self.z_ref   # the previous frame's origin[2]
        self.frames = 0
        self.frame_id = frame_id
        self.z_band = (lidar.Z_MIN, lidar.Z_MAX)
        self.cal: dict | None = None   # the odometry <-> map tie it was saved under (session.cal); None for a replayed fixture

    @property
    def shape(self) -> tuple[int, int]:
        return self.counts.shape   # (H, W)

    @classmethod
    def from_frame(cls, d: dict) -> "Grid":
        """A new grid on the frame's own lattice: its resolution, its origin (x, y), its frame_id and its z origin (z_ref)."""
        return cls(d["resolution"], d["origin"][:2], d["frame"], float(d["origin"][2]))

    def _index(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ix = np.rint((xy[:, 0] - self.origin[0]) / self.resolution).astype(np.int64)
        iy = np.rint((xy[:, 1] - self.origin[1]) / self.resolution).astype(np.int64)
        return ix, iy

    def _grow(self, ix_min: int, ix_max: int, iy_min: int, iy_max: int) -> tuple[int, int]:
        """Pads counts so the index range fits; returns the (x, y) shift applied to indices (the low-side padding)."""
        h, w = self.counts.shape
        lo_x = max(-ix_min, GROW_MARGIN) if ix_min < 0 else 0
        hi_x = max(ix_max - w + 1, GROW_MARGIN) if ix_max >= w else 0
        lo_y = max(-iy_min, GROW_MARGIN) if iy_min < 0 else 0
        hi_y = max(iy_max - h + 1, GROW_MARGIN) if iy_max >= h else 0
        if not (lo_x or hi_x or lo_y or hi_y):
            return 0, 0
        nw, nh = w + lo_x + hi_x, h + lo_y + hi_y
        if max(nw, nh) > MAX_SIDE:
            raise ValueError(f"grid would exceed {MAX_SIDE} cells per side ({nw}x{nh} at {self.resolution} m): "
                             f"frame reaches x index {ix_min}..{ix_max}, y {iy_min}..{iy_max} of a {w}x{h} grid; refused")
        c = np.zeros((nh, nw), dtype=np.uint32)
        c[lo_y:lo_y + h, lo_x:lo_x + w] = self.counts
        m = np.zeros((nh, nw), dtype=np.uint64)
        m[lo_y:lo_y + h, lo_x:lo_x + w] = self.zmask
        self.counts, self.zmask = c, m
        self.origin = [self.origin[0] - lo_x * self.resolution, self.origin[1] - lo_y * self.resolution]
        return lo_x, lo_y

    def update(self, points, z_min: float | None = None, z_max: float | None = None) -> int:
        """(N, 3) absolute metres (or (N, 2) already in the band) -> +1 per distinct cell; returns the cells touched.
        Every call the grid takes is one frame (an empty one too: 0 cells in the band is a WARN with the counts, never
        hidden); a call refused past MAX_SIDE (ValueError) is not counted and changes nothing. (N, 3) points also OR
        their absolute layer into zmask, band-free, even when the band is empty (_or_mask)."""
        p = np.asarray(points, dtype=np.float64)
        if p.ndim != 2 or p.shape[1] not in (2, 3):
            raise ValueError(f"points must be (N, 3) or (N, 2) metres, got shape {p.shape}")
        mask = None
        if p.shape[1] == 3:
            if self.z_ref is not None:
                k = np.rint((p[:, 2] - self.z_ref) / self.resolution).astype(np.int64)
                ok = (k >= 0) & (k <= 63)
                mask = (p[ok], k[ok], k[~ok])
            lo = self.z_band[0] if z_min is None else z_min
            hi = self.z_band[1] if z_max is None else z_max
            p = p[(p[:, 2] >= lo) & (p[:, 2] <= hi)]
        if len(p):
            ix, iy = self._index(p)
            cells = np.unique(np.column_stack([ix, iy]), axis=0)
            sx, sy = self._grow(int(cells[:, 0].min()), int(cells[:, 0].max()), int(cells[:, 1].min()), int(cells[:, 1].max()))
        if mask is not None:
            self._or_mask(*mask)   # after _grow (the grown grid's indices), before the empty-band return (bits above the band count)
        if len(p) == 0:
            self.frames += 1
            log("occupancy", "WARN frame with 0 cells in the band", frames=self.frames, z_band=list(self.z_band), grid=self.shape)
            return 0
        self.counts[cells[:, 1] + sy, cells[:, 0] + sx] += 1
        self.frames += 1   # after _grow: a frame refused past MAX_SIDE is not one the grid took
        return int(len(cells))

    def _or_mask(self, p: np.ndarray, k: np.ndarray, out_k: np.ndarray) -> None:
        """zmask[iy, ix] |= 1 << k for every point, one np.bitwise_or.at per frame. A layer outside 0..63 (out_k) is a
        WARN and dropped, never wrapped (1 << 64 would land on bit 0); a point outside the grid (only ever out of the
        band: _grow covers the band) is dropped; both are counted in z_dropped."""
        if len(out_k):
            self.z_dropped += len(out_k)
            log("occupancy", "WARN layer outside 0..63 dropped, never wrapped", n=len(out_k), k_min=int(out_k.min()),
                k_max=int(out_k.max()), z_ref=self.z_ref, z_dropped=self.z_dropped)
        ix, iy = self._index(p)
        h, w = self.zmask.shape
        inside = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        self.z_dropped += int((~inside).sum())
        bits = np.left_shift(np.uint64(1), k[inside].astype(np.uint64))   # numpy 2 refuses np.uint64(1) << int64
        u, inv = np.unique(iy[inside] * w + ix[inside], return_inverse=True)
        acc = np.zeros(len(u), dtype=np.uint64)
        np.bitwise_or.at(acc, inv, bits)
        self.zmask.reshape(-1)[u] |= acc

    def update_frame(self, d: dict) -> int:
        """update() from a decoded frame (lidar.decode); refuses another resolution or another frame_id (another
        lattice, another world) with ValueError. A frame whose origin[2] moved from the previous frame's is a WARN
        (z_rebased): its points are absolute metres, so update() already puts them on z_ref's lattice; off_lattice_m
        is how far that origin sits between two layers (nonzero: its layers were snapped to the nearest)."""
        if float(d["resolution"]) != self.resolution:
            raise ValueError(f"frame resolution {d['resolution']} m is not the grid's {self.resolution} m: refused")
        if self.frame_id is not None and d["frame"] != self.frame_id:
            raise ValueError(f"frame_id {d['frame']!r} is not the grid's {self.frame_id!r}: another frame, refused")
        n = self.update(d["points"])
        z = float(d["origin"][2])
        if self._z_last is not None and abs(z - self._z_last) > 1e-9:
            self.z_rebased += 1
            off = (z - self.z_ref) / self.resolution
            log("occupancy", "WARN frame origin z moved: re-based onto z_ref", **{"from": self._z_last, "to": z}, z_ref=self.z_ref,
                off_lattice_m=round((off - round(off)) * self.resolution, 4) + 0.0, z_rebased=self.z_rebased)
        self._z_last = z
        return n

    def walls(self, threshold: int = THRESHOLD) -> np.ndarray:
        """(M, 2) float64 metres: the corners of the cells seen at least threshold times, in (iy, ix) order."""
        if threshold < 1:
            raise ValueError(f"threshold must be at least 1 frame, got {threshold}")
        iy, ix = np.nonzero(self.counts >= threshold)
        return np.column_stack([self.origin[0] + ix * self.resolution, self.origin[1] + iy * self.resolution]).astype(np.float64)

    def cell(self, x: float, y: float) -> int:
        """The count at a point in metres; 0 outside the grid."""
        ix, iy = self._index(np.array([[x, y]], dtype=np.float64))
        h, w = self.counts.shape
        return int(self.counts[iy[0], ix[0]]) if 0 <= ix[0] < w and 0 <= iy[0] < h else 0

    def extent_m(self) -> dict[str, list[float]]:
        h, w = self.counts.shape
        x0, y0 = self.origin
        return {"x": [round(x0, 3), round(x0 + w * self.resolution, 3)], "y": [round(y0, 3), round(y0 + h * self.resolution, 3)]}

    def to_dict(self) -> dict[str, Any]:
        """ui/grid.json: every nonzero cell as [ix, iy, count, zmask] (zmask a JSON int up to 2**64 - 1, through
        tolist(), never int64) plus z_ref; odometry metres, never map pixels; `cal` ties them to the map. A cell seen
        only outside the band (count 0, mask bits only) is not saved: the floor plan reads cells seen threshold+ times."""
        iy, ix = np.nonzero(self.counts)
        h, w = self.counts.shape
        return {"resolution": self.resolution, "origin": list(self.origin), "width": [w, h], "frames": self.frames,
                "frame_id": self.frame_id, "z_band": list(self.z_band), "cal": self.cal, "z_ref": self.z_ref,
                "cells": [list(r) for r in zip(ix.tolist(), iy.tolist(), self.counts[iy, ix].tolist(), self.zmask[iy, ix].tolist())],
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    @classmethod
    def from_dict(cls, d: dict) -> "Grid":
        """A saved grid; a 01-era file ([ix, iy, count] rows, no z_ref) loads with an empty mask."""
        g = cls(d["resolution"], d["origin"], d["frame_id"], d.get("z_ref"))
        w, h = d["width"]
        g.counts = np.zeros((int(h), int(w)), dtype=np.uint32)
        g.zmask = np.zeros((int(h), int(w)), dtype=np.uint64)
        rows = d["cells"]
        c = np.asarray([r[:3] for r in rows], dtype=np.int64).reshape(-1, 3)
        g.counts[c[:, 1], c[:, 0]] = c[:, 2]
        if rows and len(rows[0]) == 4:   # never through int64: a mask with bit 63 set overflows it
            g.zmask[c[:, 1], c[:, 0]] = np.array([r[3] for r in rows], dtype=np.uint64)
        g.frames, g.z_band, g.cal = int(d["frames"]), tuple(d["z_band"]), d.get("cal")
        return g

    def save(self, path) -> Path:
        """Writes the json through a temp file and a rename, so a reader never sees half a grid."""
        p = Path(path)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict()) + "\n")
        tmp.replace(p)
        return p

    @classmethod
    def load(cls, path) -> "Grid":
        return cls.from_dict(json.loads(Path(path).read_text()))


def to_map_px(xy, cal: dict) -> np.ndarray:
    """(M, 2) odometry metres -> (M, 2) int map pixels: nav.to_map (wtdd/dog/nav.py:34-43) with the same operations in
    the same order, vectorised over the points, so a cell and a LiDAR dot at the same metres land on the same pixel."""
    p = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    ox, oy, oyaw = cal["odom"]
    dx, dy = p[:, 0] - ox, p[:, 1] - oy
    f = dx * math.cos(oyaw) + dy * math.sin(oyaw)      # forward since calibration, meters
    l = -dx * math.sin(oyaw) + dy * math.cos(oyaw)     # left since calibration, meters
    h = cal["heading"]
    px = cal["map"][0] + nav.PX_PER_M * (f * math.cos(h) + l * math.sin(h))
    py = cal["map"][1] + nav.PX_PER_M * (f * math.sin(h) - l * math.cos(h))
    return np.rint(np.column_stack([px, py])).astype(np.int64).reshape(-1, 2)


def response(grid: Grid | None, cal: dict | None, threshold: int, source: str | None) -> dict[str, Any]:
    """The GET /dog/grid JSON: {n, cells_px (cell corners, plain ints), cell_px, threshold, resolution, frames,
    frame_id, extent_m, source}; whenever n is 0 a `why` says which of no grid / not calibrated / no cell seen often
    enough."""
    if grid is None:
        return {"n": 0, "cells_px": [], "cell_px": None, "threshold": threshold, "resolution": None, "frames": 0,
                "frame_id": None, "extent_m": None, "source": None,
                "why": "no grid: no LiDAR frames this session and no ui/grid.json"}
    base = {"cell_px": round(grid.resolution * nav.PX_PER_M, 1), "threshold": threshold, "resolution": grid.resolution,
            "frames": grid.frames, "frame_id": grid.frame_id, "extent_m": grid.extent_m(), "source": source}
    if cal is None:
        return {"n": 0, "cells_px": [], **base, "why": "not calibrated: drag the dog to where it is (POST /dog/calibrate)"}
    w = grid.walls(threshold)
    out = {"n": int(len(w)), "cells_px": to_map_px(w, cal).tolist(), **base}
    if len(w) == 0:
        out["why"] = f"0 cells seen {threshold}+ times in {grid.frames} frames"
    return out


def replay(npz_path) -> Iterator[dict]:
    """Decoded frames from a fixture npz, each through the driver's own decoder (fixtures.make_voxel_frames)."""
    from .fixtures.make_voxel_frames import blobs, decode_wire
    p = Path(npz_path)
    if not p.is_file():
        raise FileNotFoundError(f"no replay file at {p}")
    for b in blobs(p):
        yield lidar.decode(decode_wire(b))


def png(grid: Grid, threshold: int, path) -> Path:
    """The grid as it is stored (row = iy, not rotated onto the map): white empty, grey 1..threshold-1, black walls."""
    from PIL import Image
    c = grid.counts
    rgb = np.full(c.shape + (3,), 255, dtype=np.uint8)
    rgb[(c > 0) & (c < threshold)] = 200
    rgb[c >= threshold] = 0
    Image.fromarray(np.repeat(np.repeat(rgb, PNG_SCALE, axis=0), PNG_SCALE, axis=1)).save(path)
    return Path(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wtdd.dog.occupancy", description="Replay stored LiDAR frames into the occupancy grid and draw it.")
    ap.add_argument("--replay", required=True, help="npz of wire-format frames (wtdd/dog/fixtures/voxel_frames.npz)")
    ap.add_argument("--png", required=True, help="where the grid PNG goes")
    ap.add_argument("--threshold", type=int, default=THRESHOLD, help=f"frames a cell must be seen in to be a wall (default {THRESHOLD})")
    ap.add_argument("--save", help="also write the grid json here (ui/grid.json is what GET /dog/grid falls back to)")
    a = ap.parse_args(argv)
    t_all = time.perf_counter()
    try:
        g = None
        for k, d in enumerate(replay(a.replay)):
            t0 = time.perf_counter()
            if g is None:
                g = Grid.from_frame(d)
            touched = g.update_frame(d)
            log("occupancy", f"frame {k}", frame_id=d["frame"], voxels=d["n"], cells=touched, grid=f"{g.shape[1]}x{g.shape[0]}",
                origin=[round(v, 2) for v in d["origin"][:2]], ms=round((time.perf_counter() - t0) * 1000, 1))
        if g is None:
            raise ValueError(f"{a.replay} holds no frames")
        walls = g.walls(a.threshold)
        png(g, a.threshold, a.png)
        saved = g.save(a.save) if a.save else None
    except Exception as e:  # noqa: BLE001  (reported with the path, non-zero exit; nothing written stands in for it)
        log("occupancy", "FAILED", err=f"{type(e).__name__}: {e}")
        return 1
    log("occupancy", "replay done", frames=g.frames, walls=len(walls), threshold=a.threshold, grid=f"{g.shape[1]}x{g.shape[0]}",
        extent_m=g.extent_m(), png=a.png, saved=saved, ms=round((time.perf_counter() - t_all) * 1000))
    if len(walls) == 0:
        log("occupancy", f"WARN 0 walls at threshold {a.threshold}", frames=g.frames, cells_seen=int((g.counts > 0).sum()))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
