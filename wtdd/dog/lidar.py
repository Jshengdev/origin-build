"""The dog's own LiDAR occupancy on the house map: switch the voxel stream on, decode a frame to meters, keep the
floor-to-head band, and draw it in map pixels through the same calibration the dog's dot uses (wtdd/dog/nav.py).

Run. Body.lidar_on() (wtdd/dog/body.py) calls subscribe(); the session's lidar() (wtdd/dog/session.py) runs
top_down and to_map_points on the newest frame for GET /dog/lidar; the remote polls it every 500 ms while the dog is
connected and draws the dots (class "lidar") under the dog's cone. Checked offline on 2026-09-13 without a dog: a
synthetic 128x128x38 LZ4 voxel frame through WebRTCDataChannel.deal_array_buffer with UnifiedLidarDecoder("native")
came back as the planted cells in meters, and decode/top_down/to_map_points matched nav.to_map pixel for pixel.
Nothing here has run against the real dog yet; every "UNVERIFIED" below is what the first live frame must confirm.

Driver facts (unitree_webrtc_connect 2.2.0 in .venv, read from source; the upstream example is
examples/go2/data_channel/lidar/lidar_stream.py, not shipped in the wheel, fetched from GitHub on 2026-09-13):
  topics:   constants.py:62 RTC_TOPIC, :66 "ULIDAR_SWITCH": "rt/utlidar/switch", :68 "ULIDAR_ARRAY":
            "rt/utlidar/voxel_map_compressed", :70 "ROBOTODOM": "rt/utlidar/robot_pose".
  switch:   the example does `await conn.datachannel.disableTrafficSaving(True)` (webrtc_datachannel.py:167, an
            RTC_INNER_REQ "disable_traffic_saving" "on", returns True only when the dog answers execution "ok"), then
            `pub_sub.publish_without_callback("rt/utlidar/switch", "on")`, then `pub_sub.subscribe(
            "rt/utlidar/voxel_map_compressed", cb)`. Nothing switches it off in the example; unsubscribe() here does.
  parsing:  binary data-channel messages whose first two uint16 are (2, 0) are LiDAR frames (webrtc_datachannel.py:
            126-131 slices those 4 bytes off); in the wire buffer the uint32 json length is at byte 4, four bytes at
            8-11 the driver skips (content UNVERIFIED), the json at [12:12+len], the LZ4 block after (:153-156 read the
            length at 0 and the json at 8 of the sliced buffer). The driver decodes the block
            BEFORE the callback with the decoder set by set_decoder (default "libvoxel", :28) and puts the result in
            message["data"]["data"] (:153-163). The json's data keys (upstream plot_lidar_stream.py:174-179):
            stamp, frame_id, resolution, src_size, origin, width; width defaults to [128, 128, 38] there (:260), so at
            resolution 0.05 the window is 6.4 x 6.4 x 1.9 m and src_size = 128*128*38/8 = 77824 bytes (the libvoxel
            decompress buffer is 80000, lidar_decoder_libvoxel.py:70).
  decoders: "native" (lidar_decoder_native.py, lz4 + numpy, both installed) returns {"points": float64 (N, 3)} with
            points = voxel index * resolution + origin, i.e. METERS in the frame of `origin` (:32-58, :60-67); bit
            layout x = 8 bits per byte MSB first, 16 bytes per row, y = 128 rows, z = 2048 bytes per slice.
            "libvoxel" (the Go app's wasm via wasmtime, installed) returns a mesh: uint8 positions of face vertices in
            voxel-index units, uvs, uint32 indices (:143-161); the upstream viewers scale that mesh by resolution and
            place it at origin (tfoldi/go2-webrtc javascript/threejs.js:180-182). subscribe() sets "native".
  frame:    the voxel window is a grid whose corner is `origin`; the viewers never apply the robot pose to it, so the
            points are ABSOLUTE in the frame named by frame_id, not body-relative. UNVERIFIED on this dog: (1) the
            value of frame_id (expected "odom"), (2) that it is the same odometry as LF_SPORT_MOD_STATE position
            (both are dead-reckoned from power-on; the lidar odometry rt/utlidar/robot_pose is subscribed alongside
            and reported so the two can be compared on the first live run), (3) where z = 0 sits (Z_MIN/Z_MAX are a
            guess: the first frame logs the z range and the count per z layer; tune from that log).
Accumulation (wtdd/dog/occupancy.py, item 01): every decoded window is handed to the session's grid from
Body._on_lidar; the map draws the grid under the newest window's dots; no wall extraction beyond the count threshold.

Surfaces (keep, surfaces). The dog's voxel map fills space it cannot see as solid columns. Live, 2026-09-27 19:10,
the first frame after a restart: a flat ~2,400 voxels in every layer from 0.12 to 0.73 m (a wall line would be
100-300), persistent in 5,900 of ~6,000 cells over 550 frames, drawn beyond the room as solid blocks cut by the
6.4 m window's straight edges. Body._on_lidar runs keep() on every decoded window before anything reads it, so the
dots (session.lidar, _live_px), the grid, the re-correction, top_m and the floor plan all see the same kept points.
Per window, on its own lattice: a column is FREE when it holds a floor voxel (FLOOR_LO <= z < Z_MIN) and nothing in
Z_MIN <= z < FREE_Z_MAX; OCCUPIED when it holds a voxel in the band (Z_MIN..Z_MAX); a SURFACE is an occupied column
with a free column among its neighbours within SURFACE_REACH cells (8 at 1). Only surface columns are kept, every
voxel of them (floor and above the band too, so zmask's heights are the kept columns' own): a filled block's interior
and its window-cut edges are dropped and never counted, so top_m can never be raised by one; a wall's room side and
a table (the floor is seen under its top up to FREE_Z_MAX, so its top and legs border free columns) are kept. A
window with no free column cannot say what a surface is: nothing is kept (Body logs the WARN with the counts),
never the unfiltered fill. WTDD_SURFACES=0 passes every window through (the old behaviour), served as "surfaces":
"off". UNVERIFIED on the real dog: FLOOR_LO and FREE_Z_MAX (the floor band read off one live log; a wrong band shows
as no_floor windows and a WARN); that the fill never has a floor voxel with an empty 0.10-0.30 m under it (a filled
column open below would be kept as free floor's neighbour); how thin the kept wall is when the dog stands in a
doorway (only the column facing the free side is kept).
"""
from __future__ import annotations
import asyncio
import os
import time
from typing import Any, Callable

import numpy as np
from unitree_webrtc_connect import RTC_TOPIC

from ..ledger import log
from . import nav

REQ_TIMEOUT_S = 3.0      # disableTrafficSaving round trip
MAX_POINTS = 2000        # dots on the map per frame
Z_MIN, Z_MAX = 0.10, 1.00   # wtdd: UNVERIFIED band in the voxel frame's z (meters); floor clutter below, ceiling/lamps above
KEYS = ("stamp", "frame_id", "resolution", "src_size", "origin", "width")
FLOOR_LO = -0.15      # m: the floor band is FLOOR_LO <= z < Z_MIN; live 19:10 the floor layers were -0.12..0.08 (10,492 voxels at -0.02). UNVERIFIED
FREE_Z_MAX = 0.30     # m: a floor column with nothing in Z_MIN..this is free (the floor seen under a table counts). UNVERIFIED
SURFACE_REACH = 1     # cells: an occupied column is a surface when a free column is this close (1 = its 8 neighbours)
FILL_KEYS = ("occupied", "free", "surface", "dropped")   # per window, in columns (cells of the window's own lattice)


async def subscribe(conn: Any, cb: Callable[[dict], None], pose_cb: Callable[[dict], None] | None = None) -> None:
    """Switches the LiDAR stream on the way the upstream example does and routes decoded frames to cb(message).
    Order: disableTrafficSaving(True) (must answer ok, else RuntimeError), set_decoder("native"), publish "on" to
    rt/utlidar/switch, subscribe rt/utlidar/voxel_map_compressed (and rt/utlidar/robot_pose to pose_cb when given).
    Refuses on a closed data channel instead of the driver's silent print."""
    dc = conn.datachannel
    if dc.pub_sub.channel.readyState != "open":
        raise ConnectionError("data channel is not open")
    t0 = time.perf_counter()
    try:
        ok = await asyncio.wait_for(dc.disableTrafficSaving(True), REQ_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise TimeoutError(f"disable_traffic_saving got no answer within {REQ_TIMEOUT_S}s") from None
    if ok is not True:
        raise RuntimeError(f"disable_traffic_saving refused: {ok!r}")
    dc.set_decoder("native")                       # meters, not the app's mesh (docstring: decoders)
    dc.pub_sub.publish_without_callback(RTC_TOPIC["ULIDAR_SWITCH"], "on")
    dc.pub_sub.subscribe(RTC_TOPIC["ULIDAR_ARRAY"], cb)
    if pose_cb is not None:
        dc.pub_sub.subscribe(RTC_TOPIC["ROBOTODOM"], pose_cb)
    log("lidar", "stream on", topic=RTC_TOPIC["ULIDAR_ARRAY"], pose_topic=RTC_TOPIC["ROBOTODOM"] if pose_cb else None,
        ms=round((time.perf_counter() - t0) * 1000))


def unsubscribe(conn: Any) -> None:
    """Publishes "off" to rt/utlidar/switch and unsubscribes both topics (the driver keeps the callbacks registered;
    the dog stops sending). UNVERIFIED that "off" is honoured; the frame count in Body tells."""
    dc = conn.datachannel
    if dc.pub_sub.channel.readyState != "open":
        raise ConnectionError("data channel is not open")
    dc.pub_sub.publish_without_callback(RTC_TOPIC["ULIDAR_SWITCH"], "off")
    dc.pub_sub.unsubscribe(RTC_TOPIC["ULIDAR_ARRAY"])
    dc.pub_sub.unsubscribe(RTC_TOPIC["ROBOTODOM"])
    log("lidar", "stream off", topic=RTC_TOPIC["ULIDAR_ARRAY"])


def decode(message: dict) -> dict[str, Any]:
    """One driver message (already LZ4-decoded by the native decoder) -> {"frame": frame_id, "stamp", "origin" [m],
    "resolution" [m], "width" [voxels], "center" [m, the window's middle], "n", "points": float64 (N, 3) meters,
    absolute in `frame`}. Raises on a missing key, on the libvoxel mesh shape (subscribe() was not used), or on a
    payload that is not (N, 3). A frame with 0 voxels is returned and logged as a WARN, never hidden."""
    d = message.get("data") if isinstance(message, dict) else None
    if not isinstance(d, dict):
        raise ValueError(f"lidar message without a data dict: {str(message)[:120]}")
    missing = [k for k in KEYS if k not in d]
    if missing:
        raise ValueError(f"lidar frame missing {missing}; keys seen {sorted(d)[:12]}")
    inner = d.get("data")
    if isinstance(inner, dict) and "positions" in inner and "points" not in inner:
        raise RuntimeError("lidar frame decoded by the libvoxel mesh decoder (face_count=%s); subscribe() sets the native decoder"
                           % inner.get("face_count"))
    if not isinstance(inner, dict) or "points" not in inner:
        raise ValueError(f"lidar frame data is not the native decoder's {{points}}: {type(inner).__name__} {str(inner)[:80]}")
    pts = np.asarray(inner["points"], dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"lidar points are not (N, 3): shape {pts.shape}")
    origin, width, res = [float(v) for v in d["origin"]], [int(v) for v in d["width"]], float(d["resolution"])
    if len(origin) != 3 or len(width) != 3 or res <= 0:
        raise ValueError(f"lidar frame geometry is off: origin={origin} width={width} resolution={res}")
    center = [origin[i] + width[i] * res / 2 for i in range(3)]
    out = {"frame": str(d["frame_id"]), "stamp": d["stamp"], "origin": origin, "resolution": res, "width": width,
           "center": center, "src_size": int(d["src_size"]), "n": int(len(pts)), "points": pts}
    if len(pts) == 0:
        log("lidar", "WARN frame with 0 voxels", frame=out["frame"], origin=origin, width=width, src_size=out["src_size"])
    return out


def surfaces_on() -> bool:
    """WTDD_SURFACES=0 turns the surface filter off (the old behaviour); read per window, default on."""
    return os.environ.get("WTDD_SURFACES", "1") != "0"


def surfaces(points, resolution: float) -> tuple[np.ndarray, dict[str, int]]:
    """(N, 3) metres -> (the voxels of the surface columns (M, 3), {occupied, free, surface, dropped} columns, voxels,
    kept}) (the module docstring: Surfaces). A window with no free column keeps nothing (free 0 says why)."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(p) == 0:
        return p, {"occupied": 0, "free": 0, "surface": 0, "dropped": 0, "voxels": 0, "kept": 0}
    r = SURFACE_REACH
    ix = np.rint((p[:, 0] - p[:, 0].min()) / resolution).astype(np.int64) + r
    iy = np.rint((p[:, 1] - p[:, 1].min()) / resolution).astype(np.int64) + r
    shape, z = (int(iy.max()) + r + 1, int(ix.max()) + r + 1), p[:, 2]

    def cols(sel: np.ndarray) -> np.ndarray:
        m = np.zeros(shape, dtype=bool)
        m[iy[sel], ix[sel]] = True
        return m
    occ = cols((z >= Z_MIN) & (z <= Z_MAX))
    free = cols((z >= FLOOR_LO) & (z < Z_MIN)) & ~cols((z >= Z_MIN) & (z < FREE_Z_MAX))
    near = np.zeros(shape, dtype=bool)
    h, w = shape
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx or dy:
                near[r:h - r, r:w - r] |= free[r + dy:h - r + dy, r + dx:w - r + dx]
    surf = occ & near
    kept = p[surf[iy, ix]]
    n_occ, n_surf = int(occ.sum()), int(surf.sum())
    return kept, {"occupied": n_occ, "free": int(free.sum()), "surface": n_surf, "dropped": n_occ - n_surf,
                  "voxels": int(len(p)), "kept": int(len(kept))}


def keep(d: dict) -> dict:
    """A decoded window (decode) -> the same window with only its surface voxels in `points` and the counts in `fill`
    ({surfaces: "on", occupied, free, surface, dropped, voxels, kept}); with WTDD_SURFACES=0 the window as it came,
    fill {surfaces: "off"}. A window that already carries `fill` is returned as it is (kept once)."""
    if "fill" in d:
        return d
    if not surfaces_on():
        return {**d, "fill": {"surfaces": "off"}}
    kept, c = surfaces(d["points"], d["resolution"])
    return {**d, "points": kept, "fill": {"surfaces": "on", **c}}


def top_down(voxels: np.ndarray, z_min: float = Z_MIN, z_max: float = Z_MAX, with_z: bool = False) -> list[tuple[float, ...]]:
    """Occupied voxels (N, 3) meters -> unique (x, y) of those with z_min <= z <= z_max (the band between floor
    clutter and head height, in the voxel frame's z). Logs in/out counts; a WARN with the z range seen when the
    band is empty (so a wrong Z_MIN/Z_MAX is one grep away). with_z: (x, y, z) with z the highest in-band z of that
    (x, y) column, in the same order (the page colours the dots by it; nothing is drawn from it)."""
    v = np.asarray(voxels, dtype=np.float64).reshape(-1, 3)
    if len(v) == 0:
        log("lidar", "WARN top_down of 0 voxels")
        return []
    keep = v[(v[:, 2] >= z_min) & (v[:, 2] <= z_max)]
    xy, inv = np.unique(keep[:, :2], axis=0, return_inverse=True) if len(keep) else (keep[:, :2], np.zeros(0, dtype=np.int64))
    if len(xy) == 0:
        log("lidar", "WARN top_down kept 0 of %d voxels" % len(v), z_min=z_min, z_max=z_max,
            z_seen=(round(float(v[:, 2].min()), 2), round(float(v[:, 2].max()), 2)))
    else:
        log("lidar", "top_down", voxels=len(v), in_band=len(keep), xy=len(xy), z_min=z_min, z_max=z_max)
    if with_z:
        top = np.full(len(xy), -np.inf)
        np.maximum.at(top, np.asarray(inv).reshape(-1), keep[:, 2])
        return [(float(x), float(y), float(z)) for (x, y), z in zip(xy, top)]
    return [(float(x), float(y)) for x, y in xy]


def thin(seq, max_points: int = MAX_POINTS):
    """Every stride-th item when there are more than max_points (to_map_points' thinning, shared so parallel lists stay parallel)."""
    n = len(seq)
    return seq[::-(-n // max_points)] if n > max_points else seq


def to_map_points(points_m, cal: dict, pos, yaw: float, max_points: int = MAX_POINTS) -> list[list[int]]:
    """Absolute odometry-frame (x, y) meters -> map pixels [px, py] through nav.to_map, the same calibration that
    places the dog's dot (so the two agree by construction). `pos`/`yaw` are the dog's odometry pose now, used only
    for the log (how far the window's points reach from the dog); the points themselves are absolute, so the
    calibration alone maps them. More than max_points is thinned to an evenly spaced subset."""
    pts = list(points_m)
    n = len(pts)
    pts = thin(pts, max_points)
    px = [[round(v) for v in nav.to_map(cal, p, yaw)[:2]] for p in pts]
    if n == 0:
        log("lidar", "WARN to_map_points of 0 points", pos=[round(float(v), 2) for v in pos[:2]])
    else:
        reach = max(((p[0] - float(pos[0])) ** 2 + (p[1] - float(pos[1])) ** 2) ** 0.5 for p in pts)
        log("lidar", "to_map_points", n=n, drawn=len(px), reach_m=round(reach, 2))
    return px
