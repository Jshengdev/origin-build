"""The scout (roadmap item 14): one button turns the dog 360 degrees in place at drop-off while its LiDAR fills the
session's occupancy grid (wtdd/dog/occupancy.py) around one centre, and the press leaves one dog.scout receipt.

The honest line: the LiDAR sees 360 already; the spin fills the shadow behind it, gives the camera the room, and closes
the heading. The Go2's L1 has a 360 x 90 degree field of view (https://www.unitree.com/mobile/LiDAR/), so the turn
is not how the site gets seen: what it buys is the arc the body shadows, a few seconds of densifying, the narrow
camera pointed all round, and a free check that the IMU yaw comes back to where it began. The only numbers it earns are cells_added and the closure degrees on its row.
band_hits beside them (the band cells its frames put into the grid, one per cell per frame) is what says whether the z
band caught anything: 0 is the FAILED "0 band cells"; hits with 0 cells added is a grid that already held them (a
second press at the same spot), ok with a WARN, never blamed on the band.

Run. POST /dog/scout (wtdd/api.py) calls DogSession.scout (wtdd/dog/session.py), which refuses while following or
recording, connects, ties "nose at drop-off is up" to the empty canvas when nothing is tied yet (one dog.calibrate row,
args.source "dropoff": CANVAS_CENTRE facing DROPOFF_HEADING_DEG; a person's earlier tap is kept as "tap"), switches the
LiDAR on, holds (0, 0, z) for the drive loop every TICK_S (the Q/E keys' path; DRIVE_HOLD_S is the dead-man) until the
wrapped IMU yaw deltas integrate past target_deg, then halts once itself and reads the yaw back. Main's drive loop
also sends its own release halt when the held velocity drops (it still reads `moving` while the scout's StopMove is in
flight), so the dog may see one or two StopMoves per press; the second is a harmless retry. This module holds only the
pure parts it uses, read at call time as scout.X (the tests patch them): integrate_yaw, closed, row, the constants.
z = 0 is the standing control (Needs the dog 14.4): nothing is commanded, it stands for timeout_s, and the row's
cells_added is the number the spin is compared against, each on a cleared grid (POST /dog/grid {clear: true}): on one
grid the second press only counts what the first missed. Offline:

    python -m wtdd.dog.scout --replay wtdd/dog/fixtures/spin_frames.npz --png /tmp/scout.png [--threshold N] [--save F] [--frames N]

runs the driver's own decoder on each stored window (fixtures/make_spin_frames.py: eight 45-degree wedges of a four-wall
room from ONE origin), accumulates one grid, prints one `[wtdd:scout] frame k ... cells=+N` line per frame and a
summary naming each wall of the fixture's declared world with its cells found, writes the PNG (and the grid json with
--save), and exits 2 with `WARN <wall> missing (f of n cells)` when a wall is not wholly in the grid. No ledger row: a
replay of a fixture, not a step. Nothing is cached anywhere on this path (no DEMO_CACHE): the live path is the button.

05b (localize) and 05a (utlidar yaw) are not on this base: the row names them "absent", never omits the key. When they
merge, the session reads self.loc and 05a's utpose through getattr and fills the same keys.

UNVERIFIED on the real dog (each is a Needs-the-dog step, none has run):
  14.1 the voxel window's origin stays put during a pure turn, so the walls fill in around one centre; if the walls
       rotate with the cone on the page the points are body-relative: STOP, everything on 01 waits.
  14.2 whether the avoidance service's MOVE carries a yaw-only command (the shipped take ran avoid off); the row says
       which velocity path carried it and "did not turn" names avoid on or off.
  14.3 IMU closure within CLOSE_TOL_DEG, compared with 05a's utlidar yaw and 05b's summed dtheta when they exist.
  14.4 cells added spinning versus the z 0 control standing still for the same seconds, the grid cleared before each.
"""
from __future__ import annotations
import argparse
import itertools
import sys
import time
from typing import Any

from ..ledger import log
from . import nav

TICK_S = 0.1              # the held velocity is refreshed and the yaw read this often (the drive loop publishes at MOVE_HZ)
NO_TURN_S = 3.0           # after this long with z commanded ...
NO_TURN_DEG = 10.0        # ... less than this much turn is "did not turn": FAILED, halted
CLOSE_TOL_DEG = 10.0      # | |turned| - target | within this is closed; outside it the row says not closed (ok, WARN)
CANVAS_CENTRE = (530, 770)   # ui/house.svg's viewBox 1060 x 1540, halved: where the dog is put on an empty canvas
DROPOFF_HEADING_DEG = -90    # map heading of "up" (nav.py: 0 = +x on screen, y down): nose at drop-off is up, a convention

ARGS = ("z_rad_s", "target_deg", "timeout_s", "shift_id", "source")
BEFORE = ("map", "heading0_deg", "grid_frames", "cells", "lidar_n", "range_obstacle", "localize", "utlidar")
AFTER = ("seconds", "frames", "cells_added", "cells_total", "turned_deg", "heading_end_deg", "closed", "avoid",
         "cb_errors_during", "range_obstacle", "velocity", "yaw_speed", "localize", "utlidar_turned_deg",
         "heading0", "closed_deg", "velocity_path", "why", "band_hits")


def integrate_yaw(prev: float, now: float, acc: float) -> float:
    """acc + the wrapped yaw step prev -> now (radians): a turn integrated across the +-pi wrap, either sign."""
    return acc + nav.wrap(now - prev)


def closed(turned_deg: float, target_deg: float = 360, tol_deg: float | None = None) -> bool:
    """True when the turn's magnitude lands within tol_deg (default CLOSE_TOL_DEG) of the target: clockwise closes too."""
    return abs(abs(turned_deg) - target_deg) <= (CLOSE_TOL_DEG if tol_deg is None else tol_deg)


def row(args: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """The dog.scout row's payload {args, state_before, state_after}; ValueError naming every contract key missing."""
    missing = [f"{part}.{k}" for part, d, keys in (("args", args, ARGS), ("state_before", before, BEFORE), ("state_after", after, AFTER))
               for k in keys if k not in d]
    if missing:
        raise ValueError("dog.scout row lacks " + ", ".join(missing) + " (an absent module is named \"absent\", never omitted)")
    return {"args": args, "state_before": before, "state_after": after}


def main(argv: list[str] | None = None) -> int:
    from . import occupancy
    from .fixtures import make_spin_frames
    ap = argparse.ArgumentParser(prog="python -m wtdd.dog.scout", description="Replay a spin's LiDAR windows into one grid and check the walls.")
    ap.add_argument("--replay", required=True, help="npz of wire-format frames (wtdd/dog/fixtures/spin_frames.npz)")
    ap.add_argument("--png", required=True, help="where the grid PNG goes")
    ap.add_argument("--threshold", type=int, default=1, help="frames a cell must be seen in to count (default 1: each wall cell is in one wedge)")
    ap.add_argument("--save", help="also write the grid json here (ui/grid.json is what GET /dog/grid falls back to)")
    ap.add_argument("--frames", type=int, help="replay only the first N frames")
    a = ap.parse_args(argv)
    t_all = time.perf_counter()
    try:
        g = None
        for k, d in enumerate(itertools.islice(occupancy.replay(a.replay), a.frames)):
            t0 = time.perf_counter()
            if g is None:
                g = occupancy.Grid.from_frame(d)
            n0 = int((g.counts > 0).sum())
            g.update_frame(d)
            log("scout", f"frame {k}", voxels=d["n"], cells=f"+{int((g.counts > 0).sum()) - n0}", origin=[round(v, 2) for v in d["origin"][:2]],
                ms=round((time.perf_counter() - t0) * 1000, 1))
        if g is None:
            raise ValueError(f"{a.replay} holds no frames")
        found = {name: (sum(g.cell(gx * g.resolution, gy * g.resolution) >= a.threshold for gx, gy in cells), len(cells))
                 for name, cells in make_spin_frames.wall_cells().items()}
        occupancy.png(g, a.threshold, a.png)
        saved = g.save(a.save) if a.save else None
    except Exception as e:  # noqa: BLE001  (reported with the path, non-zero exit; nothing written stands in for it)
        log("scout", "FAILED", err=f"{type(e).__name__}: {e}")
        return 1
    log("scout", "replay done", frames=g.frames, walls=" ".join(f"{n}={f}/{t}" for n, (f, t) in found.items()),
        cells=int((g.counts > 0).sum()), threshold=a.threshold, grid=f"{g.shape[1]}x{g.shape[0]}", png=a.png, saved=saved,
        ms=round((time.perf_counter() - t_all) * 1000))
    short = [(n, f, t) for n, (f, t) in found.items() if f < t]
    for n, f, t in short:
        log("scout", f"WARN {n} missing ({f} of {t} cells)")
    return 2 if short else 0


if __name__ == "__main__":
    sys.exit(main())
