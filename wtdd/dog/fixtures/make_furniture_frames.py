"""Synthetic LiDAR voxel frames of a furnished room for wtdd/dog/floorplan.py (its tests and `--replay`): three
128x128x38 windows of one fixed world, bit-packed and LZ4-wrapped exactly the way make_voxel_frames.py does it, so the
tests and the replay run the driver's own decoder (unitree_webrtc_connect 2.2.0, no peer) and never a shortcut.
Nothing here has seen the real dog.

    python -m wtdd.dog.fixtures.make_furniture_frames   rewrites voxel_furniture.npz next to this file, decodes it back
                                                         through the driver and prints one line per frame and per object

A parameterised copy of make_voxel_frames.pack/frame_bytes (which read module globals): rasterise(), frame_bytes() and
write() take the world and the window origins as arguments, so a test can write a world of its own (a box and no wall)
into a temp npz. pack(), decode_wire() and blobs() are reused from make_voxel_frames as they are.

The world, in absolute metres of the frame the dog calls `odom` (lattice index = metres / RES; boxes are half-open
[lo, hi) per axis; z is the ABSOLUTE layer k above Z0 = -0.3 m, z = Z0 + k * RES, so k 6 = 0.0 m, 8 = 0.10 m (FLOOR),
12 = 0.30 m (GROUND), 20 = 0.70 m, 24 = 0.90 m, 28 = 1.10 m (TALL), 37 = 1.55 m, the window's top). Every object sits
inside all three windows (seen three times, so the default THRESHOLD 3 keeps all of it) and at least 0.3 m from every
other object and from the walls, except the shelf, which stands against the near wall by design:
  WALL_A    the near wall, x = 2.0 m, y -2.7..2.7 m, full height 0.0..1.55 m.                         class 1 (wall)
  WALL_B    the far wall, y = 2.8 m, x -2.0..1.5 m, seen only to 0.9 m (the head-mounted cone sees a far wall low;
            0.9 < TALL, so a height-only rule would miss it; the straight-run rule must not). It stops 0.5 m short
            of WALL_A (a doorway at the corner), so each wall is its own straight run.                  class 1 (wall)
  SHELF     2 m long, 0.3 m deep, 0.9 m high, grounded, against WALL_A (x 1.7..2.0 m, y -1.0..1.0 m). Grounded and
            straight for 2 m: the classifier calls it a wall. That is the documented limit; only goal 16's label
            may move it to grey.                                                                        class 1 (wall)
  TABLE_TOP a 1.2 x 0.8 m top at 0.70..0.75 m (x -0.5..0.7, y -2.5..-1.7), nothing under it but the legs.  class 3 (slab)
  TABLE_LEGS four 0.1 m legs at the top's corners, floor to top.                                         class 5 (low)
  FLOOR_CLUTTER a patch under the table below FLOOR (z -0.3..0.05 m, x -0.3..0.3, y -2.3..-1.9): floor clutter
            outside lidar's band, never counted, and it must NOT ground the table top above it.           (the top's: 3)
  CHAIR_SEAT a 0.45 m seat at 0.40 m (x -1.5..-1.05, y -2.5..-2.05).                                    class 3 (slab)
  CHAIR_BACK the seat's rear row, 0.45..0.85 m.                                                          class 3 (slab)
  CHAIR_LEGS four 0.05 m legs at the seat's corners, floor to seat (the rear pair carries the back).       class 5 (low)
  BOX       a 0.35 m cube on the floor at x -2.0..-1.65, y 1.0..1.35.                                    class 5 (low)
  PERSON    a 0.3 m column, floor to the window's top, at x 0.0..0.3, y 0.5..0.8.                        class 2 (tall)
Where several objects share a cell the grounded part wins (a leg under a top is one column from the floor): the truth
is built in WORLD's order and a later object overrides an earlier one, so legs come after tops.

The windows' origins are (-3.2, -3.2, -0.3), (-2.7, -3.2, -0.3), (-2.2, -3.2, -0.25): the dog walks +0.5 m in x
between frames while the world stays put (make_voxel_frames' convention, UNVERIFIED live), and the third window's z
origin is one layer higher, so a reader that keeps a height profile must re-base that frame onto the first frame's
z lattice (absolute layer k, not the window's layer index) or its bits land one layer low.

The npz holds `blobs` (n, maxlen) uint8 with `blob_len` (n,), `origins` (n, 3), `resolution`, `width`, `z0` (the first
frame's z origin), `frame_ids` (make_voxel_frames' layout) plus the analytic truth per cell, computed with plain Python
sets from the boxes above and never from any accumulator: `truth_cells` int64 (m, 3) [gx, gy, class],
`truth_zmask` uint64 (m,) (bit k = absolute layer k occupied in that cell, over all frames), `truth_names` (m,) the
object that owns the cell, `wall_lines` float64 (2, 4) [x0, y0, x1, y1] metres (cell corners) with `wall_names`."""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

from .. import lidar   # Z_MIN, Z_MAX: the band the grid's counts keep, so world_cells() and the counts agree by construction
from .make_voxel_frames import D, FRAME_ID, H, RES, STAMP0, W, blobs, decode_wire, pack  # noqa: F401  (re-exported for the tests)

NPZ = Path(__file__).with_name("voxel_furniture.npz")
Z0 = -0.3                        # the first window's z origin (metres): where z = 0 sits on the dog is UNVERIFIED (lidar.py)
ORIGINS = [(-3.2, -3.2, -0.3), (-2.7, -3.2, -0.3), (-2.2, -3.2, -0.25)]   # x, y, z of each window's corner
ALL = (0, 1, 2)

# the world on the absolute lattice (index = metres / RES), half-open [lo, hi); z is the absolute layer k above Z0.
# `cls` is the class the floor plan must give the cell (None: no claim of its own; the object above it owns the cell);
# `line` marks a wall whose straight line the segment extractor must find (the shelf is class 1 but not a wall line).
WORLD = {
    "wall_a": {"x": (40, 41), "y": (-54, 54), "z": (6, 38), "frames": ALL, "cls": 1, "line": True},
    "wall_b": {"x": (-40, 30), "y": (56, 57), "z": (6, 25), "frames": ALL, "cls": 1, "line": True},
    "shelf": {"x": (34, 40), "y": (-20, 20), "z": (6, 25), "frames": ALL, "cls": 1},
    "table_top": {"x": (-10, 14), "y": (-50, -34), "z": (20, 22), "frames": ALL, "cls": 3},
    "floor_clutter": {"x": (-6, 6), "y": (-46, -38), "z": (0, 8), "frames": ALL, "cls": None},
    "table_legs": {"x": ((-10, -8), (12, 14)), "y": ((-50, -48), (-36, -34)), "z": (6, 20), "frames": ALL, "cls": 5},
    "chair_seat": {"x": (-30, -21), "y": (-50, -41), "z": (14, 15), "frames": ALL, "cls": 3},
    "chair_back": {"x": (-30, -21), "y": (-42, -41), "z": (15, 24), "frames": ALL, "cls": 3},
    "chair_legs": {"x": ((-30, -29), (-22, -21)), "y": ((-50, -49), (-42, -41)), "z": (6, 14), "frames": ALL, "cls": 5},
    "box": {"x": (-40, -33), "y": (20, 27), "z": (6, 13), "frames": ALL, "cls": 5},
    "person": {"x": (0, 6), "y": (10, 16), "z": (6, 38), "frames": ALL, "cls": 2},
}
FURNITURE = ("table_top", "table_legs", "chair_seat", "chair_back", "chair_legs", "box")   # never a wall, whatever the rule
CLEAR_CELLS = 6                  # every two objects (but shelf/wall_a) keep at least this many empty cells between them (0.3 m)


def boxes(spec: dict) -> list[tuple[tuple[int, int], tuple[int, int], tuple[int, int]]]:
    """One object -> its axis-aligned boxes [(x, y, z)]: a leg spec lists several x and y ranges (their product)."""
    xs = spec["x"] if isinstance(spec["x"][0], tuple) else (spec["x"],)
    ys = spec["y"] if isinstance(spec["y"][0], tuple) else (spec["y"],)
    return [(x, y, spec["z"]) for x in xs for y in ys]


def window_offset(origin) -> tuple[int, int, int]:
    """The window corner as absolute lattice indices (x, y) and the z layer offset against Z0."""
    return round(origin[0] / RES), round(origin[1] / RES), round((origin[2] - Z0) / RES)


def rasterise(k: int, world: dict = WORLD, origins: list = ORIGINS) -> np.ndarray:
    """Frame k's window as bool (D, H, W) indexed [z, y, x]: each world box clipped to the window, z re-based onto the
    window's own z origin."""
    kx, ky, kz = window_offset(origins[k])
    v = np.zeros((D, H, W), dtype=bool)
    for spec in world.values():
        if k not in spec["frames"]:
            continue
        for (bx, by, bz) in boxes(spec):
            x0, x1 = max(bx[0], kx) - kx, min(bx[1], kx + W) - kx
            y0, y1 = max(by[0], ky) - ky, min(by[1], ky + H) - ky
            z0, z1 = max(bz[0] - kz, 0), min(bz[1] - kz, D)
            if x0 < x1 and y0 < y1 and z0 < z1:
                v[z0:z1, y0:y1, x0:x1] = True
    return v


def frame_bytes(k: int, world: dict = WORLD, origins: list = ORIGINS) -> bytes:
    """Frame k as one data-channel buffer: make_voxel_frames' wire format, with this frame's own (x, y, z) origin."""
    import json
    import struct
    import lz4.block
    raw = pack(rasterise(k, world, origins))
    block = lz4.block.compress(raw, store_size=False)
    hdr = {"type": "msg", "topic": "rt/utlidar/voxel_map_compressed",
           "data": {"stamp": STAMP0 + k, "frame_id": FRAME_ID, "resolution": RES, "src_size": len(raw),
                    "origin": [float(v) for v in origins[k]], "width": [W, H, D]}}
    j = json.dumps(hdr).encode()
    return struct.pack("<HH", 2, 0) + struct.pack("<I", len(j)) + struct.pack("<I", len(block)) + j + block


# ---- the analytic truth (plain sets; no numpy grid, no accumulator)
def object_cells(name: str, world: dict = WORLD) -> set[tuple[int, int]]:
    """The absolute lattice cells (gx, gy) under an object's footprint (no window clipping: every object is inside every
    window, which write() asserts)."""
    cells: set[tuple[int, int]] = set()
    for (bx, by, _bz) in boxes(world[name]):
        cells |= {(gx, gy) for gx in range(*bx) for gy in range(*by)}
    return cells


def frame_voxels(k: int, world: dict = WORLD, origins: list = ORIGINS) -> set[tuple[int, int, int]]:
    """Every (gx, gy, k_abs) frame k shows: what the driver's decoder must give back, in absolute layers."""
    kx, ky, kz = window_offset(origins[k])
    out: set[tuple[int, int, int]] = set()
    for spec in world.values():
        if k not in spec["frames"]:
            continue
        for (bx, by, bz) in boxes(spec):
            for gx in range(max(bx[0], kx), min(bx[1], kx + W)):
                for gy in range(max(by[0], ky), min(by[1], ky + H)):
                    for kk in range(max(bz[0], kz), min(bz[1], kz + D)):
                        out.add((gx, gy, kk))
    return out


def frame_cells(k: int, world: dict = WORLD, origins: list = ORIGINS,
                z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> set[tuple[int, int]]:
    """The cells frame k shows inside lidar's band (the counts' view of that window)."""
    return {(gx, gy) for gx, gy, kk in frame_voxels(k, world, origins) if z_min <= Z0 + kk * RES <= z_max}


def world_cells(world: dict = WORLD, origins: list = ORIGINS,
                z_min: float = lidar.Z_MIN, z_max: float = lidar.Z_MAX) -> dict[tuple[int, int], int]:
    """{(gx, gy): frames that showed the cell in the band}: what Grid.counts must hold, unchanged by the mask."""
    seen: dict[tuple[int, int], int] = {}
    for k in range(len(origins)):
        for c in frame_cells(k, world, origins, z_min, z_max):
            seen[c] = seen.get(c, 0) + 1
    return seen


def world_layers(world: dict = WORLD, origins: list = ORIGINS) -> dict[tuple[int, int], set[int]]:
    """{(gx, gy): absolute layers k seen in any frame, band-free}: what Grid.zmask must hold (bit k per layer)."""
    layers: dict[tuple[int, int], set[int]] = {}
    for k in range(len(origins)):
        for gx, gy, kk in frame_voxels(k, world, origins):
            layers.setdefault((gx, gy), set()).add(kk)
    return layers


def zmask_of(layers) -> int:
    return sum(1 << k for k in layers)


def truth_classes(world: dict = WORLD) -> dict[tuple[int, int], tuple[int, str]]:
    """{(gx, gy): (class, owner)} in WORLD order, a later object overriding an earlier one (legs after tops)."""
    out: dict[tuple[int, int], tuple[int, str]] = {}
    for name, spec in world.items():
        if spec["cls"] is None:
            continue
        for c in object_cells(name, world):
            out[c] = (spec["cls"], name)
    return out


def wall_lines(world: dict = WORLD) -> dict[str, tuple[float, float, float, float]]:
    """{name: (x0, y0, x1, y1)} metres, cell corners, along the long axis of each wall marked `line`."""
    out = {}
    for name, spec in world.items():
        if not spec.get("line"):
            continue
        (bx, by, _bz), = boxes(spec)
        if bx[1] - bx[0] == 1:       # a wall along y
            out[name] = (bx[0] * RES, by[0] * RES, bx[0] * RES, by[1] * RES)
        else:                        # a wall along x
            out[name] = (bx[0] * RES, by[0] * RES, bx[1] * RES, by[0] * RES)
    return out


def check(world: dict = WORLD, origins: list = ORIGINS) -> None:
    """The design invariants the truth relies on; raised, never patched over."""
    for k in range(len(origins)):
        kx, ky, kz = window_offset(origins[k])
        for name, spec in world.items():
            for (bx, by, bz) in boxes(spec):
                assert kx <= bx[0] and bx[1] <= kx + W and ky <= by[0] and by[1] <= ky + H, f"{name} leaves window {k}"
                assert 0 <= bz[0] and bz[1] <= D + kz, f"{name} leaves window {k} in z"
    names = list(world)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ca, cb = object_cells(a, world), object_cells(b, world)
            if a.split("_")[0] == b.split("_")[0] or {a, b} == {"shelf", "wall_a"} or "floor_clutter" in (a, b):
                continue   # the same piece of furniture, the shelf on its wall, the clutter under the table
            gap = min(max(abs(x1 - x2), abs(y1 - y2)) for x1, y1 in ca for x2, y2 in cb)
            assert gap > CLEAR_CELLS, f"{a} and {b} are {gap} cells apart (need > {CLEAR_CELLS})"
    if "floor_clutter" in world:
        assert object_cells("floor_clutter", world) <= object_cells("table_top", world), "the clutter must sit under the table top"
    if "table_legs" in world:
        assert object_cells("table_legs", world) <= object_cells("table_top", world), "the legs must sit under the top"


def write(path: Path = NPZ, world: dict = WORLD, origins: list = ORIGINS) -> Path:
    check(world, origins)
    bufs = [frame_bytes(k, world, origins) for k in range(len(origins))]
    width = max(map(len, bufs))
    truth, layers, lines = truth_classes(world), world_layers(world, origins), wall_lines(world)
    cells = sorted(truth)
    np.savez_compressed(path,
                        blobs=np.stack([np.frombuffer(b.ljust(width, b"\0"), dtype=np.uint8) for b in bufs]),
                        blob_len=np.array([len(b) for b in bufs]),
                        origins=np.array(origins, dtype=np.float64), resolution=RES,
                        width=np.array([W, H, D]), z0=Z0, frame_ids=np.array([FRAME_ID] * len(origins)),
                        truth_cells=np.array([[gx, gy, truth[(gx, gy)][0]] for gx, gy in cells], dtype=np.int64).reshape(-1, 3),
                        truth_zmask=np.array([zmask_of(layers[c]) for c in cells], dtype=np.uint64),
                        truth_names=np.array([truth[c][1] for c in cells]),
                        wall_lines=np.array(list(lines.values()), dtype=np.float64).reshape(-1, 4),
                        wall_names=np.array(list(lines)))
    return path


def main() -> int:
    path = write()
    print(f"wrote {path} ({path.stat().st_size} bytes)", file=sys.stderr)
    for k, buf in enumerate(blobs(path)):
        d = lidar.decode(decode_wire(buf))
        pts = d["points"]
        print(f"frame {k}: bytes={len(buf)} voxels={d['n']} origin={d['origin']} frame_id={d['frame']} "
              f"band_cells={len(frame_cells(k))} z_range=({pts[:, 2].min():.2f}, {pts[:, 2].max():.2f})", file=sys.stderr)
    truth = truth_classes()
    for name, spec in WORLD.items():
        cells = object_cells(name)
        owned = sum(1 for c in cells if truth.get(c, (None, None))[1] == name)
        print(f"{name}: cells={len(cells)} owned={owned} cls={spec['cls']}", file=sys.stderr)
    w = world_cells()
    print(f"world: cells={len(w)} seen_thrice={sum(1 for n in w.values() if n == 3)} classes="
          f"{ {c: sum(1 for v in truth.values() if v[0] == c) for c in (1, 2, 3, 5)} } walls={wall_lines()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
