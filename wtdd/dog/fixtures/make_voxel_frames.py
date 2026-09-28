"""Synthetic LiDAR voxel frames for wtdd/dog/occupancy.py (its tests and `--replay`): three 128x128x38 windows of one
fixed world, bit-packed and LZ4-wrapped the way the dog's data channel sends them, so the tests and the replay run the
driver's own decoder (unitree_webrtc_connect 2.2.0, no peer) and never a shortcut. Nothing here has seen the real dog.

    python -m wtdd.dog.fixtures.make_voxel_frames      rewrites voxel_frames.npz next to this file, decodes it back
                                                        through the driver and prints one line per frame (counts)

The world, in absolute metres of the frame the dog calls `odom` (lattice index = metres / RES; boxes are half-open
[lo, hi) per axis; z index counts up from the window's z origin Z0):
  WALL_A  x = 2.0 m, y -2.7..2.7 m, in the band: inside every window, so seen three times.
  WALL_B  y = 2.8 m, x -3.0..4.0 m, in the band: each window clips it, so its ends are seen once, its middle three
          times, and the part past x = 3.2 m lies outside the first window (the grid must grow past one window).
  BLOB    a 0.2 m box at (0.0, -1.0), frame 1 only: something that passed through; never a wall at threshold 2.
  FLOOR   a patch at (-1.0, -1.0) below lidar.Z_MIN in every frame: floor clutter outside the band, never counted.
The windows' origins are (-3.2, -3.2), (-2.7, -3.2), (-2.2, -3.2) at z Z0: the dog walks +0.5 m in x between frames
while the world stays put. That is the frame convention lidar.py's docstring reads from the viewers (points = voxel
index * resolution + origin, absolute in `frame_id`) and the first live frame must confirm; whether `origin` moves
with the dog at all is UNVERIFIED there.

Wire format, read from the driver source (the same reading lidar.py's docstring cites): uint16 (2, 0) | uint32
json_len | 4 bytes the driver skips | json | LZ4 block of 77824 bytes, bit-packed z-major (byte i -> z = i // 0x800,
y = (i % 0x800) // 0x10, x = (i % 0x10) * 8 + bit, MSB first: lidar/lidar_decoder_native.py:32-58; the slicing:
webrtc_datachannel.py:126-131 drops the 4-byte type header, :153-156 reads the length at 0 and the json at 8 of what is
left, so the json starts at byte 12 of the wire buffer). Bytes 8-11 carry the block length here; what the dog puts
there is UNVERIFIED (the driver ignores them). Header json: {type, topic, data: {stamp, frame_id, resolution,
src_size, origin, width}}.

The npz holds `blobs` (n, maxlen) uint8 with `blob_len` (n,): a fixed-width byte matrix, because an |S array strips
a trailing NUL (an LZ4 block can end in 0x00) and an object array needs pickle on load; plus `origins`, `resolution`,
`width`, `z0`, `frame_ids` for the reader's own checks. world_cells() is the analytic answer, {(gx, gy): frames_seen}
on the absolute lattice, band-filtered with lidar.Z_MIN/Z_MAX, computed with plain Python sets and no numpy grid, so
the tests compare the accumulator against an independent count."""
from __future__ import annotations
import json
import struct
import sys
from pathlib import Path

import lz4.block
import numpy as np

from .. import lidar   # Z_MIN, Z_MAX: the band the grid keeps, so world_cells() and the grid agree by construction

NPZ = Path(__file__).with_name("voxel_frames.npz")
W, H, D = 128, 128, 38          # width = [128, 128, 38] voxels, the shape lidar.py verified offline
RES = 0.05                      # metres per voxel
Z0 = -0.3                       # the windows' z origin (metres); where z = 0 sits on the dog is UNVERIFIED (lidar.py)
FRAME_ID = "odom"               # expected, UNVERIFIED (lidar.py docstring, frame (1))
ORIGINS = [(-3.2, -3.2), (-2.7, -3.2), (-2.2, -3.2)]   # x, y of each window's corner: +0.5 m in x per frame
STAMP0 = 1000.0

# the world on the absolute lattice (index = metres / RES), half-open [lo, hi); z is the voxel index above Z0
WALL_A = {"x": (40, 41), "y": (-54, 54), "z": (10, 24), "frames": (0, 1, 2)}      # x = 2.0 m, y -2.7..2.7, z 0.2..0.9 m
WALL_B = {"x": (-60, 80), "y": (56, 57), "z": (10, 24), "frames": (0, 1, 2)}      # y = 2.8 m, x -3.0..4.0
BLOB = {"x": (0, 4), "y": (-20, -16), "z": (10, 24), "frames": (1,)}              # 0.2 m box at (0.0, -1.0), frame 1 only
FLOOR = {"x": (-20, -16), "y": (-20, -16), "z": (0, 4), "frames": (0, 1, 2)}      # z -0.3..-0.15 m: below the band
WORLD = {"wall_a": WALL_A, "wall_b": WALL_B, "blob": BLOB, "floor": FLOOR}


def window_offset(origin_xy) -> tuple[int, int]:
    """The window corner as absolute lattice indices."""
    return round(origin_xy[0] / RES), round(origin_xy[1] / RES)


def rasterise(k: int) -> np.ndarray:
    """Frame k's window as bool (D, H, W) indexed [z, y, x]: each world box clipped to the window."""
    kx, ky = window_offset(ORIGINS[k])
    v = np.zeros((D, H, W), dtype=bool)
    for box in WORLD.values():
        if k not in box["frames"]:
            continue
        x0, x1 = max(box["x"][0], kx) - kx, min(box["x"][1], kx + W) - kx
        y0, y1 = max(box["y"][0], ky) - ky, min(box["y"][1], ky + H) - ky
        z0, z1 = max(box["z"][0], 0), min(box["z"][1], D)
        if x0 < x1 and y0 < y1 and z0 < z1:
            v[z0:z1, y0:y1, x0:x1] = True
    return v


def pack(vox: np.ndarray) -> bytes:
    """bool (D, H, W) -> the driver's bit layout: 16 bytes per y row, 2048 bytes per z slice, MSB first."""
    assert vox.shape == (D, H, W), vox.shape
    return np.packbits(vox.astype(np.uint8), axis=2, bitorder="big").tobytes()


def frame_bytes(k: int) -> bytes:
    """Frame k as one data-channel buffer (see the docstring: wire format)."""
    return wire(rasterise(k), ORIGINS[k], STAMP0 + k)


def wire(vox: np.ndarray, origin_xy, stamp: float) -> bytes:
    """Any bool (D, H, W) window at origin (x, y, Z0) as one data-channel buffer (test_surfaces' scenes use it too)."""
    raw = pack(vox)
    assert len(raw) == W * H * D // 8 == 77824, len(raw)
    block = lz4.block.compress(raw, store_size=False)
    hdr = {"type": "msg", "topic": "rt/utlidar/voxel_map_compressed",
           "data": {"stamp": stamp, "frame_id": FRAME_ID, "resolution": RES, "src_size": len(raw),
                    "origin": [origin_xy[0], origin_xy[1], Z0], "width": [W, H, D]}}
    j = json.dumps(hdr).encode()
    return struct.pack("<HH", 2, 0) + struct.pack("<I", len(j)) + struct.pack("<I", len(block)) + j + block


def in_band(box: dict, z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> bool:
    return any(z_min <= Z0 + iz * RES <= z_max for iz in range(*box["z"]))


def frame_cells(k: int, z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> set[tuple[int, int]]:
    """The absolute lattice cells (gx, gy) frame k shows inside the band: the top-down view of that window."""
    kx, ky = window_offset(ORIGINS[k])
    cells: set[tuple[int, int]] = set()
    for box in WORLD.values():
        if k not in box["frames"] or not in_band(box, z_min, z_max):
            continue
        for gx in range(max(box["x"][0], kx), min(box["x"][1], kx + W)):
            for gy in range(max(box["y"][0], ky), min(box["y"][1], ky + H)):
                cells.add((gx, gy))
    return cells


def world_cells(z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> dict[tuple[int, int], int]:
    """{(gx, gy): how many of the frames showed that cell in the band}: what the accumulator must reproduce."""
    seen: dict[tuple[int, int], int] = {}
    for k in range(len(ORIGINS)):
        for c in frame_cells(k, z_min, z_max):
            seen[c] = seen.get(c, 0) + 1
    return seen


def decode_wire(buf: bytes) -> dict:
    """One data-channel buffer -> the driver's decoded message ({.., data: {.., data: {points}}}), through the same
    code a live frame runs (webrtc_datachannel.py deal_array_buffer -> native LZ4 decode). Built without a peer:
    __new__ skips the constructor, and deal_array_buffer uses nothing but .decoder."""
    from unitree_webrtc_connect.lidar.lidar_decoder_unified import UnifiedLidarDecoder
    from unitree_webrtc_connect.webrtc_datachannel import WebRTCDataChannel
    dc = WebRTCDataChannel.__new__(WebRTCDataChannel)
    dc.decoder = UnifiedLidarDecoder("native")
    return dc.deal_array_buffer(buf)


def blobs(path: Path = NPZ) -> list[bytes]:
    """The stored buffers, one per frame, in order."""
    z = np.load(path)
    return [z["blobs"][i, : int(n)].tobytes() for i, n in enumerate(z["blob_len"])]


def write(path: Path = NPZ) -> Path:
    bufs = [frame_bytes(k) for k in range(len(ORIGINS))]
    width = max(map(len, bufs))
    np.savez_compressed(path,
                        blobs=np.stack([np.frombuffer(b.ljust(width, b"\0"), dtype=np.uint8) for b in bufs]),
                        blob_len=np.array([len(b) for b in bufs]),
                        origins=np.array([[ox, oy, Z0] for ox, oy in ORIGINS]), resolution=RES,
                        width=np.array([W, H, D]), z0=Z0, frame_ids=np.array([FRAME_ID] * len(ORIGINS)))
    return path


def main() -> int:
    path = write()
    print(f"wrote {path} ({path.stat().st_size} bytes)", file=sys.stderr)
    for k, buf in enumerate(blobs(path)):
        d = lidar.decode(decode_wire(buf))
        pts = d["points"]
        cells = frame_cells(k)
        print(f"frame {k}: bytes={len(buf)} voxels={d['n']} origin={d['origin']} frame_id={d['frame']} "
              f"band_cells={len(cells)} x_range=({pts[:, 0].min():.2f}, {pts[:, 0].max():.2f}) "
              f"wall_a_voxels={int(np.isclose(pts[:, 0], 2.0).sum())}", file=sys.stderr)
    w = world_cells()
    print(f"world: cells={len(w)} seen_once={sum(1 for n in w.values() if n == 1)} "
          f"seen_twice={sum(1 for n in w.values() if n == 2)} seen_thrice={sum(1 for n in w.values() if n == 3)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
