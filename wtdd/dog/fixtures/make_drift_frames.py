"""Synthetic LiDAR windows with planted odometry drift, for wtdd/dog/localize.py (its tests): four more 128x128x38
windows of make_voxel_frames' world, bit-packed and LZ4-wrapped like the dog's data channel sends them, in which the
dog's odometry is wrong by a known offset per window. Nothing here has seen the real dog.

    python -m wtdd.dog.fixtures.make_drift_frames     rewrites drift_frames.npz next to this file, decodes it back
                                                       through the driver and prints one line per frame (counts)

The world is make_voxel_frames' (WALL_A x = 2.0 m, WALL_B y = 2.8 m, FLOOR below the band; the BLOB is left out) plus
WALL_C and WALL_C2, a corner at (12.0, 12.0) m in a room the dog has never seen. The windows continue that fixture's
walk (+0.5 m in x per frame) and then jump to the new room:
  k  declared origin   drift (dx, dy) m   what the matcher must do, given the correction it holds
  0  (-1.7, -3.2)      (+0.10, -0.05)     find +0.10, -0.05 (two cells right, one cell up): applied
  1  (-1.2, -3.2)      (+0.15, -0.05)     find the change since k = 0, +0.05, 0.00: applied, the correction accumulates
  2  (-0.7, -3.2)      (+0.50, -0.05)     find +0.35, 0.00: a jump past the cap, rejected; the correction stays at k = 1's
  3  (10.0, 10.0)      (+0.15, -0.05)     WALL_C only, nothing the grid knows: unmatched, drawn into the grid through the
                                          correction held (k = 1's), so WALL_C lands at its true x = 12.0 m
Drift means: the dog's odometry reads pose P while the true pose in the grid's frame is P + drift. The window's points
are what the dog reports in its own (drifted) odometry frame, so the world appears shifted by -drift inside a window
whose declared `origin` is the odometry's. Every drift is a whole number of cells (RES = 0.05 m), so the planted answer
is exact on the lattice and the test's tolerance is the lattice's. Rotation drift is not planted here (a rotated wall
does not rasterise exactly); test_localize rotates decoded point arrays for that.

Wire format, header json and the npz layout are make_voxel_frames' (its docstring cites the driver lines): uint16 (2, 0)
| uint32 json_len | 4 bytes the driver skips | json | LZ4 block of 77824 bytes. frame_cells(k) is the analytic answer,
{(gx, gy)} on the declared (drifted) lattice of window k, band-filtered with lidar.Z_MIN/Z_MAX and computed with plain
sets, so the tests compare the decoder and the matcher against an independent count; true_cells(k) is the same set moved
back by the drift, where those cells sit in the grid's frame."""
from __future__ import annotations
import json
import struct
import sys
from pathlib import Path

import lz4.block
import numpy as np

from .. import lidar
from . import make_voxel_frames as fx

NPZ = Path(__file__).with_name("drift_frames.npz")
W, H, D, RES, Z0, FRAME_ID = fx.W, fx.H, fx.D, fx.RES, fx.Z0, fx.FRAME_ID
ORIGINS = [(-1.7, -3.2), (-1.2, -3.2), (-0.7, -3.2), (10.0, 10.0)]   # declared (odometry) window corners, x, y
DRIFTS = [(0.10, -0.05), (0.15, -0.05), (0.50, -0.05), (0.15, -0.05)]   # true pose = odometry + drift, metres, whole cells
STAMP0 = fx.STAMP0 + len(fx.ORIGINS)

WALL_C = {"x": (240, 241), "y": (210, 290), "z": (10, 24), "frames": (3,)}   # x = 12.0 m, y 10.5..14.5 m: the new room
WALL_C2 = {"x": (210, 240), "y": (240, 241), "z": (10, 24), "frames": (3,)}  # y = 12.0 m, x 10.5..12.0 m: its corner
WORLD = {"wall_a": {**fx.WALL_A, "frames": (0, 1, 2)}, "wall_b": {**fx.WALL_B, "frames": (0, 1, 2)},
         "floor": {**fx.FLOOR, "frames": (0, 1, 2, 3)}, "wall_c": WALL_C, "wall_c2": WALL_C2}


def drift_cells(k: int) -> tuple[int, int]:
    """Frame k's drift as whole lattice cells (the docstring's guarantee)."""
    cx, cy = DRIFTS[k][0] / RES, DRIFTS[k][1] / RES
    assert abs(cx - round(cx)) < 1e-9 and abs(cy - round(cy)) < 1e-9, DRIFTS[k]
    return round(cx), round(cy)


def _shifted(box: dict, k: int) -> dict:
    """The world box as the drifted odometry of frame k sees it: moved by -drift."""
    cx, cy = drift_cells(k)
    return {**box, "x": (box["x"][0] - cx, box["x"][1] - cx), "y": (box["y"][0] - cy, box["y"][1] - cy)}


def rasterise(k: int) -> np.ndarray:
    """Frame k's window as bool (D, H, W) indexed [z, y, x]: each world box, drifted, clipped to the window."""
    kx, ky = fx.window_offset(ORIGINS[k])
    v = np.zeros((D, H, W), dtype=bool)
    for box in WORLD.values():
        if k not in box["frames"]:
            continue
        b = _shifted(box, k)
        x0, x1 = max(b["x"][0], kx) - kx, min(b["x"][1], kx + W) - kx
        y0, y1 = max(b["y"][0], ky) - ky, min(b["y"][1], ky + H) - ky
        z0, z1 = max(b["z"][0], 0), min(b["z"][1], D)
        if x0 < x1 and y0 < y1 and z0 < z1:
            v[z0:z1, y0:y1, x0:x1] = True
    return v


def frame_bytes(k: int) -> bytes:
    """Frame k as one data-channel buffer (make_voxel_frames' wire format)."""
    raw = fx.pack(rasterise(k))
    assert len(raw) == W * H * D // 8 == 77824, len(raw)
    block = lz4.block.compress(raw, store_size=False)
    hdr = {"type": "msg", "topic": "rt/utlidar/voxel_map_compressed",
           "data": {"stamp": STAMP0 + k, "frame_id": FRAME_ID, "resolution": RES, "src_size": len(raw),
                    "origin": [ORIGINS[k][0], ORIGINS[k][1], Z0], "width": [W, H, D]}}
    j = json.dumps(hdr).encode()
    return struct.pack("<HH", 2, 0) + struct.pack("<I", len(j)) + struct.pack("<I", len(block)) + j + block


def frame_cells(k: int, z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> set[tuple[int, int]]:
    """The lattice cells (gx, gy) window k shows inside the band, on its own declared (drifted) lattice."""
    kx, ky = fx.window_offset(ORIGINS[k])
    cells: set[tuple[int, int]] = set()
    for box in WORLD.values():
        if k not in box["frames"] or not fx.in_band(box, z_min, z_max):
            continue
        b = _shifted(box, k)
        for gx in range(max(b["x"][0], kx), min(b["x"][1], kx + W)):
            for gy in range(max(b["y"][0], ky), min(b["y"][1], ky + H)):
                cells.add((gx, gy))
    return cells


def true_cells(k: int) -> set[tuple[int, int]]:
    """frame_cells(k) moved back by the drift: where those cells are in the grid's (true) frame."""
    cx, cy = drift_cells(k)
    return {(gx + cx, gy + cy) for gx, gy in frame_cells(k)}


def blobs(path: Path = NPZ) -> list[bytes]:
    return fx.blobs(path)


def write(path: Path = NPZ) -> Path:
    bufs = [frame_bytes(k) for k in range(len(ORIGINS))]
    width = max(map(len, bufs))
    np.savez_compressed(path,
                        blobs=np.stack([np.frombuffer(b.ljust(width, b"\0"), dtype=np.uint8) for b in bufs]),
                        blob_len=np.array([len(b) for b in bufs]),
                        origins=np.array([[ox, oy, Z0] for ox, oy in ORIGINS]), drifts=np.array(DRIFTS),
                        resolution=RES, width=np.array([W, H, D]), z0=Z0, frame_ids=np.array([FRAME_ID] * len(ORIGINS)))
    return path


def main() -> int:
    path = write()
    print(f"wrote {path} ({path.stat().st_size} bytes)", file=sys.stderr)
    for k, buf in enumerate(blobs(path)):
        d = lidar.decode(fx.decode_wire(buf))
        pts = d["points"]
        print(f"frame {k}: bytes={len(buf)} voxels={d['n']} origin={d['origin']} drift={DRIFTS[k]} "
              f"band_cells={len(frame_cells(k))} x_range=({pts[:, 0].min():.2f}, {pts[:, 0].max():.2f}) "
              f"wall_a_at_x={2.0 - DRIFTS[k][0]:.2f}: {int(np.isclose(pts[:, 0], 2.0 - DRIFTS[k][0]).sum())} voxels", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
