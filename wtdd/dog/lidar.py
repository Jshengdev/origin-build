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
            126-131): uint32 json length at byte 4, json at [8:8+len], LZ4 block after. The driver decodes the block
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
Ceiling (wtdd:): no accumulation across frames and no wall extraction; the map shows the newest window only.
"""
from __future__ import annotations
import asyncio
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


def top_down(voxels: np.ndarray, z_min: float = Z_MIN, z_max: float = Z_MAX) -> list[tuple[float, float]]:
    """Occupied voxels (N, 3) meters -> unique (x, y) of those with z_min <= z <= z_max (the band between floor
    clutter and head height, in the voxel frame's z). Logs in/out counts; a WARN with the z range seen when the
    band is empty (so a wrong Z_MIN/Z_MAX is one grep away)."""
    v = np.asarray(voxels, dtype=np.float64).reshape(-1, 3)
    if len(v) == 0:
        log("lidar", "WARN top_down of 0 voxels")
        return []
    keep = v[(v[:, 2] >= z_min) & (v[:, 2] <= z_max)]
    xy = np.unique(keep[:, :2], axis=0) if len(keep) else keep[:, :2]
    if len(xy) == 0:
        log("lidar", "WARN top_down kept 0 of %d voxels" % len(v), z_min=z_min, z_max=z_max,
            z_seen=(round(float(v[:, 2].min()), 2), round(float(v[:, 2].max()), 2)))
    else:
        log("lidar", "top_down", voxels=len(v), in_band=len(keep), xy=len(xy), z_min=z_min, z_max=z_max)
    return [(float(x), float(y)) for x, y in xy]


def to_map_points(points_m, cal: dict, pos, yaw: float, max_points: int = MAX_POINTS) -> list[list[int]]:
    """Absolute odometry-frame (x, y) meters -> map pixels [px, py] through nav.to_map, the same calibration that
    places the dog's dot (so the two agree by construction). `pos`/`yaw` are the dog's odometry pose now, used only
    for the log (how far the window's points reach from the dog); the points themselves are absolute, so the
    calibration alone maps them. More than max_points is thinned to an evenly spaced subset."""
    pts = list(points_m)
    n = len(pts)
    if n > max_points:
        stride = -(-n // max_points)
        pts = pts[::stride]
    px = [[round(v) for v in nav.to_map(cal, p, yaw)[:2]] for p in pts]
    if n == 0:
        log("lidar", "WARN to_map_points of 0 points", pos=[round(float(v), 2) for v in pos[:2]])
    else:
        reach = max(((p[0] - float(pos[0])) ** 2 + (p[1] - float(pos[1])) ** 2) ** 0.5 for p in pts)
        log("lidar", "to_map_points", n=n, drawn=len(px), reach_m=round(reach, 2))
    return px
