"""Synthetic LiDAR voxel frames for the scout's spin (wtdd/dog/scout.py, its tests and `--replay`): eight 128x128x38
windows from ONE fixed origin, each holding the 45-degree wedge of a four-wall room that the dog's nose sweeps during a
pure turn, bit-packed and LZ4-wrapped the way the dog's data channel sends them, so the tests and the replay run the
driver's own decoder (unitree_webrtc_connect 2.2.0, no peer) and never a shortcut. Nothing here has seen the real dog.

    python -m wtdd.dog.fixtures.make_spin_frames      rewrites spin_frames.npz next to this file, decodes it back
                                                       through the driver and prints one line per frame (counts)

The premise this fixture states (UNVERIFIED on the dog; 14's first LIVE step is exactly this): during a pure turn the
dog does not translate, so the window `origin` stays put and the walls fill in around one centre while the cone turns.
If the live points are body-relative the grid smears into a rosette instead, and everything on 01 waits. The real L1
LiDAR sees 360 degrees in every frame (https://www.unitree.com/mobile/LiDAR/); the 45-degree wedge is the fixture's
way of making "the walls appear as the nose comes round" a checkable claim, not a model of the sensor.

The world, in absolute metres of the frame the dog calls `odom` (lattice index = metres / RES; boxes are half-open
[lo, hi) per axis; z index counts up from the window's z origin Z0), the dog at (0, 0) with its nose along +x:
  FRONT  x = 2.50 m, y -2.55..2.55 m, in the band     LEFT   y = 2.50 m, x -2.55..2.55 m (a positive yaw turns left)
  BACK   x = -2.55 m, y -2.55..2.55 m                 RIGHT  y = -2.55 m, x -2.55..2.55 m
  FLOOR  a patch at (-1.0, -1.0) below lidar.Z_MIN in every frame: floor clutter outside the band, never counted.
Frame k holds the wall cells whose centre, seen from (0, 0), lies in wedge k: bearings [45k, 45k + 45) degrees
counter-clockwise from +x, the direction a positive ROS yaw turns. Every wall cell is in exactly one wedge, so the
eight frames show each cell once and their union is the four walls (404 cells; the four corners are shared by two
walls). The window origin is ORIGIN in every frame.

Wire format and npz layout: make_voxel_frames.py (reused here: pack, decode_wire, blobs, W/H/D/RES/Z0/FRAME_ID).
wall_cells() and frame_cells() are the analytic answer, computed with plain Python sets and no numpy grid, so the tests
and the replay compare the accumulator against an independent count."""
from __future__ import annotations
import json
import struct
import sys
from pathlib import Path

import lz4.block
import numpy as np

from .. import lidar
from .make_voxel_frames import D, FRAME_ID, H, RES, W, Z0, blobs, decode_wire, pack

NPZ = Path(__file__).with_name("spin_frames.npz")
ORIGIN = (-3.2, -3.2)           # x, y of every window's corner: the dog at (0, 0) does not move during a pure turn
WEDGES = 8                      # 360 / 45
STAMP0 = 2000.0

# the walls on the absolute lattice (index = metres / RES), half-open [lo, hi); z is the voxel index above Z0
WALLS = {
    "front": {"x": (50, 51), "y": (-51, 51), "z": (10, 24)},    # x = 2.50 m, z 0.2..0.9 m
    "left":  {"x": (-51, 51), "y": (50, 51), "z": (10, 24)},    # y = 2.50 m
    "back":  {"x": (-51, -50), "y": (-51, 51), "z": (10, 24)},  # x = -2.55 m
    "right": {"x": (-51, 51), "y": (-51, -50), "z": (10, 24)},  # y = -2.55 m
}
FLOOR = {"x": (-20, -16), "y": (-20, -16), "z": (0, 4)}        # z -0.3..-0.15 m: below the band, every frame


def wedge_of(gx: int, gy: int) -> int:
    """The 45-degree wedge (0..7, counter-clockwise from +x) holding the cell's centre as seen from the dog at (0, 0).
    On doubled integer centres (2 gx + 1, 2 gy + 1) no centre sits on an axis and a diagonal falls to one side by an
    exact integer comparison, so the answer is the same on every machine."""
    cx, cy = 2 * gx + 1, 2 * gy + 1
    if cx > 0 and cy > 0:
        return 0 if cy < cx else 1          # 0..45 | 45..90
    if cx < 0 and cy > 0:
        return 2 if -cx < cy else 3         # 90..135 | 135..180
    if cx < 0 and cy < 0:
        return 4 if -cy < -cx else 5        # 180..225 | 225..270
    return 6 if cx < -cy else 7             # 270..315 | 315..360


def window_offset() -> tuple[int, int]:
    return round(ORIGIN[0] / RES), round(ORIGIN[1] / RES)


def in_band(box: dict, z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> bool:
    return any(z_min <= Z0 + iz * RES <= z_max for iz in range(*box["z"]))


def wall_cells(z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> dict[str, set[tuple[int, int]]]:
    """{wall name: its absolute lattice cells (gx, gy) inside the band}: what the replay must find at the end."""
    out: dict[str, set[tuple[int, int]]] = {}
    for name, box in WALLS.items():
        out[name] = {(gx, gy) for gx in range(*box["x"]) for gy in range(*box["y"])} if in_band(box, z_min, z_max) else set()
    return out


def frame_cells(k: int, z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> set[tuple[int, int]]:
    """The band cells frame k shows: the wall cells in wedge k."""
    return {c for cells in wall_cells(z_min, z_max).values() for c in cells if wedge_of(*c) == k}


def world_cells(z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> dict[tuple[int, int], int]:
    """{(gx, gy): how many of the eight frames showed that cell}: 1 for every wall cell, by construction."""
    seen: dict[tuple[int, int], int] = {}
    for k in range(WEDGES):
        for c in frame_cells(k, z_min, z_max):
            seen[c] = seen.get(c, 0) + 1
    return seen


def rasterise(k: int) -> np.ndarray:
    """Frame k's window as bool (D, H, W) indexed [z, y, x]: wedge k of every wall, plus the floor patch."""
    kx, ky = window_offset()
    v = np.zeros((D, H, W), dtype=bool)
    for box in WALLS.values():
        z0, z1 = max(box["z"][0], 0), min(box["z"][1], D)
        for gx in range(*box["x"]):
            for gy in range(*box["y"]):
                if wedge_of(gx, gy) == k and 0 <= gx - kx < W and 0 <= gy - ky < H:
                    v[z0:z1, gy - ky, gx - kx] = True
    x0, x1 = FLOOR["x"][0] - kx, FLOOR["x"][1] - kx
    y0, y1 = FLOOR["y"][0] - ky, FLOOR["y"][1] - ky
    v[FLOOR["z"][0]:FLOOR["z"][1], y0:y1, x0:x1] = True
    return v


def frame_bytes(k: int) -> bytes:
    """Frame k as one data-channel buffer (make_voxel_frames.py: wire format)."""
    raw = pack(rasterise(k))
    assert len(raw) == W * H * D // 8 == 77824, len(raw)
    block = lz4.block.compress(raw, store_size=False)
    hdr = {"type": "msg", "topic": "rt/utlidar/voxel_map_compressed",
           "data": {"stamp": STAMP0 + k, "frame_id": FRAME_ID, "resolution": RES, "src_size": len(raw),
                    "origin": [ORIGIN[0], ORIGIN[1], Z0], "width": [W, H, D]}}
    j = json.dumps(hdr).encode()
    return struct.pack("<HH", 2, 0) + struct.pack("<I", len(j)) + struct.pack("<I", len(block)) + j + block


def write(path: Path = NPZ) -> Path:
    bufs = [frame_bytes(k) for k in range(WEDGES)]
    width = max(map(len, bufs))
    np.savez_compressed(path,
                        blobs=np.stack([np.frombuffer(b.ljust(width, b"\0"), dtype=np.uint8) for b in bufs]),
                        blob_len=np.array([len(b) for b in bufs]),
                        origins=np.array([[ORIGIN[0], ORIGIN[1], Z0]] * WEDGES), resolution=RES,
                        width=np.array([W, H, D]), z0=Z0, frame_ids=np.array([FRAME_ID] * WEDGES), wedges=WEDGES)
    return path


def main() -> int:
    path = write()
    print(f"wrote {path} ({path.stat().st_size} bytes)", file=sys.stderr)
    for k, buf in enumerate(blobs(path)):
        d = lidar.decode(decode_wire(buf))
        cells = frame_cells(k)
        print(f"frame {k}: bytes={len(buf)} voxels={d['n']} origin={d['origin']} frame_id={d['frame']} "
              f"wedge={k * 45}..{k * 45 + 45}deg band_cells={len(cells)}", file=sys.stderr)
    walls = wall_cells()
    w = world_cells()
    print(f"walls: {' '.join(f'{n}={len(c)}' for n, c in walls.items())} union={len(w)} "
          f"seen_once={sum(1 for n in w.values() if n == 1)} seen_more={sum(1 for n in w.values() if n > 1)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
