"""The body: one Unitree Go2 over one WebRTC connection, held for the process lifetime.

Goal. One process holds a single connection to the dog and exposes: state (mode, odometry position, velocity,
IMU, obstacle range) as a stream, the predefined sport commands (Sit, RiseSit, StandUp, StandDown, Hello, Stretch,
Move x/y/z for a duration, StopMove, Dance1), a scripted route runner (a JSON list of cmd/move/sleep/look steps
with obstacle avoidance on), and the newest camera frame as a JPEG on demand. Every call writes one ledger row
with the state read back after it.

Run. `python -m wtdd.dog {commands,check,probe,state,cmd,move,avoid,route,frame}` (see __main__.py). From the
chat and the remote the same Body is reached through wtdd/commands.py (dog_cmd, look, do_round). Done when:
`commands` lists the 49 SPORT_CMD names; `probe` reports a reachable dog or the precise missing pieces; `state`
prints a live row; `cmd Sit` then `cmd RiseSit` produce ledger rows whose state_after mode changed; `frame` writes
a JPEG; `route corridor` runs wtdd/dog/routes/corridor.json.

Run live so far (ledger.jsonl, 2026-09-13, dog at 192.168.12.1 with no AES key): connect 1.0 to 2.5 s; the state
stream arrives at 20.0 Hz (59 samples in 3 s, mode 0); the first camera frame (1280x720, JPEG about 157 KB) lands
within 0.75 s of switching the channel on. cmd, move, avoid and route have not run against the dog yet.

Driver facts (read from the installed source of unitree_webrtc_connect 2.2.0 in .venv: webrtc_driver.py,
webrtc_datachannel.py, webrtc_video.py, msgs/pub_sub.py, constants.py, multicast_scanner.py, unitree_auth.py, and
its go2 examples sportmode, sportmodestate, obstacles_avoid, camera_stream).
  connection: UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=..., aes_128_key=...); await connect().
  requests:   conn.datachannel.pub_sub.publish_request_new(RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["Hello"]}).
  mode:       RTC_TOPIC["MOTION_SWITCHER"] api 1001 (query) / 1002 (set {"name": "normal"}); the dog stands up
              while switching, the example waits 5 s.
  state:      pub_sub.subscribe(RTC_TOPIC["LF_SPORT_MOD_STATE"], cb); message["data"] is the state dict.
  avoidance:  RTC_TOPIC["OBSTACLES_AVOID"] with OBSTACLES_AVOID_API {SWITCH_SET 1001, SWITCH_GET 1002, MOVE 1003,
              USE_REMOTE_COMMAND_FROM_API 1004}; MOVE has no reply. Joystick-style drive also exists via
              publish_without_callback(RTC_TOPIC["WIRELESS_CONTROLLER"], {lx, ly, rx, ry, keys}) at 50 Hz (unused).
  camera:     conn.video.add_track_callback(cb) then conn.video.switchVideoChannel(True); the driver discards
              frame 1 and awaits the callback with the live track. PIL via av; never import cv2 in this process,
              the av and cv2 wheels both bundle libavdevice and clash.
  lidar:      wtdd/dog/lidar.py (lidar_on/lidar_off/lidar_points here): disableTrafficSaving(True), set_decoder("native"),
              "on" to rt/utlidar/switch, subscribe rt/utlidar/voxel_map_compressed; frames arrive LZ4-decoded as meters
              in the voxel frame. Not yet run on this dog.
  auth:       firmware 1.1.15+ needs aes_128_key, fetched once with
              `unitree-fetch-aes-key --email <unitree account> --password '...' --device-type Go2`.
  discovery:  discover_ip_sn() is multicast 231.1.1.1:10131; a dog in STA mode on another subnet does not answer.
  signaling:  the dog listens on TCP 9991 (con_notify) or 8081 (legacy /offer).
  navigation: the driver names LiDAR mapping and navigation topics but implements no example for them; there is
              no waypoint navigation here. A route is a scripted list of moves with avoidance on
              (TrajectoryFollow 1018 exists for short trajectories if ever needed).

Johnny must do. 1) Put the dog on the house Wi-Fi in STA mode via the Unitree Go app and set UNITREE_ROBOT_IP
in .env. 2) Read the firmware version in the app; if 1.1.15 or newer, fetch the key (above) into
UNITREE_AES_128_KEY. 3) Clear a 3 m corridor and stand by the dog for the first `cmd` calls.

Never. No command to the dog unless probe() passed in this process (connect() enforces it); no flips, no jumps
(ALLOW below); no silent reconnect loops; never two moves at once; no git commit (the coordinator commits).
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from unitree_webrtc_connect import (
    RTC_TOPIC,
    SPORT_CMD,
    UnitreeWebRTCConnection,
    WebRTCConnectionMethod,
    discover_ip_sn,
)
from unitree_webrtc_connect.constants import DATA_CHANNEL_TYPE
from unitree_webrtc_connect.unitree_auth import _probe_tcp_port

from .. import config
from ..ledger import log, step
from . import lidar

try:
    from unitree_webrtc_connect.constants import OBSTACLES_AVOID_API
except ImportError:  # older driver: avoid() and route() refuse; commands/check/probe/state/cmd/move/frame still run
    OBSTACLES_AVOID_API = None
    log("dog", "WARN OBSTACLES_AVOID_API is missing from the installed unitree_webrtc_connect; avoid and route are refused")

# Allowlist. cmd() refuses (raises, recorded in the ledger) anything not listed: no flips, jumps, gait or height
# changes. `python -m wtdd.dog commands` prints the full allow/deny table.
ALLOW = frozenset({
    "Euler", "Pose",   # body pose on the legs (pitch the camera down for a look), no locomotion

    "Damp", "BalanceStand", "StopMove", "StandUp", "StandDown", "RecoveryStand", "Move",
    "Sit", "RiseSit", "Hello", "Stretch", "Content", "Scrape", "WiggleHips", "FingerHeart",
    "Dance1", "Dance2", "GetState", "GetBodyHeight", "GetSpeedLevel", "SpeedLevel",
})
_missing = ALLOW - SPORT_CMD.keys()
if _missing:
    raise ImportError(f"[wtdd:dog] allowlist names not in the installed SPORT_CMD: {sorted(_missing)}")

MAX_SPEED = 0.8            # m/s for x and y, rad/s for z; the ceiling for any move
MAX_MOVE_S = 20.0          # per move() call
MOVE_HZ = 10
CONNECT_TIMEOUT_S = 30.0   # the driver's own data-channel wait is 15 s inside this
REQ_TIMEOUT_S = 3.0        # one request/response on the data channel
AVOID_TIMEOUT_S = 10.0     # the obstacle-avoidance service answers slowly (or not at all) right after a power cycle
TICK_TIMEOUT_S = 0.5       # one Move tick ack
FRAME_TIMEOUT_S = 15.0     # switchVideoChannel(True) to first frame
FRAME_STALE_S = 2.0
STATE_FRESH_S = 2.0        # wait for a state sample newer than the call
MOTION_SWITCHER_GET, MOTION_SWITCHER_SET = 1001, 1002   # sportmode example
PICTURES = Path.home() / "Pictures" / "wtdd"
ROUTES = Path(__file__).parent / "routes"


def probe(scan: bool = True) -> tuple[list[tuple[str, str, str]], bool]:
    """Preflight. Returns ([(check, ok|warn|fail, detail)], reachable). A failing check lands on its own
    row instead of crashing the table; nothing here fakes success. Writes one dog.probe ledger row."""
    rows: list[tuple[str, str, str]] = []

    def check(name: str, fn) -> None:
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001  (reported on the row, the table always prints)
            status, detail = "fail", f"{type(e).__name__}: {e}"
        rows.append((name, status, detail))

    ip = config.maybe("UNITREE_ROBOT_IP")
    key = config.maybe("UNITREE_AES_128_KEY")

    def venv():
        inside = Path(sys.prefix).resolve() == (config.ROOT / ".venv").resolve()
        return ("ok" if inside else "fail"), f"python {sys.version.split()[0]} at {sys.prefix}"

    def driver():
        import importlib.metadata as m
        import aiortc, av, PIL  # noqa: E401
        v = m.version("unitree_webrtc_connect")
        return "ok", f"unitree_webrtc_connect {v}, aiortc {aiortc.__version__}, av {av.__version__}, PIL {PIL.__version__}"

    def no_cv2():
        return ("fail" if "cv2" in sys.modules else "ok"), "cv2 must never load in this process (libavdevice clash)"

    def env_ip():
        return ("ok" if ip else "fail"), (ip or "UNITREE_ROBOT_IP is empty; set it in .env (dog IP from the Unitree Go app)")

    def env_key():
        if not key:
            return "warn", "UNITREE_AES_128_KEY is empty; required if firmware >= 1.1.15 (unitree-fetch-aes-key)"
        ok = len(key) == 32 and all(c in "0123456789abcdefABCDEF" for c in key)
        return ("ok" if ok else "fail"), (f"32 hex chars, starts {key[:4]}" if ok else f"expected 32 hex chars, got {len(key)} chars")

    def discover():
        found = discover_ip_sn(timeout=2, device_type="Go2")
        if not found:
            return "warn", "0 devices answered multicast 231.1.1.1:10131 (STA mode dogs on another subnet do not answer)"
        listed = ", ".join(f"{sn}={addr}" for sn, addr in found.items())
        if ip and ip not in found.values():
            return "warn", f"{len(found)} found but none at UNITREE_ROBOT_IP={ip}: {listed}"
        return "ok", f"{len(found)} found: {listed}"

    def signaling():
        if not ip:
            return "fail", "skipped: no IP"
        open_ports = [p for p in (9991, 8081) if _probe_tcp_port(ip, p, timeout=1.5)]
        if not open_ports:
            return "fail", f"{ip} answers on neither 9991 (con_notify) nor 8081 (legacy offer)"
        return "ok", f"{ip} open on {open_ports} ({'con_notify' if 9991 in open_ports else 'legacy /offer'})"

    t0 = time.perf_counter()
    check("venv", venv)
    check("driver", driver)
    check("no cv2", no_cv2)
    check("UNITREE_ROBOT_IP", env_ip)
    check("UNITREE_AES_128_KEY", env_key)
    if scan:
        check("discover (multicast)", discover)
    check("signaling port", signaling)
    reachable = not any(status == "fail" for _name, status, _detail in rows)
    with step("dog", "dog.probe", "unitree", {"scan": scan, "ip": ip}) as r:
        r["response_or_error"] = [{"check": c, "status": s, "detail": d} for c, s, d in rows]
        r["state_after"] = {"reachable": reachable}
    log("dog", f"probe reachable={reachable}", checks=len(rows), ms=round((time.perf_counter() - t0) * 1000))
    return rows, reachable


def _parse(steps: Any) -> list[tuple[str, Any, str]]:
    """Static check of a route (no connection): one (kind, argument, description) per step; raises ValueError.
    kind cmd -> (name, parameter); move -> (x, y, z, seconds); sleep -> seconds; look -> None."""
    if not isinstance(steps, list) or not steps:
        raise ValueError("route must be a non-empty JSON list of steps")
    plan = []
    for i, s in enumerate(steps):
        keys = set(s) - {"parameter"} if isinstance(s, dict) else set()
        if len(keys) != 1:
            raise ValueError(f"step {i + 1}: expected exactly one of cmd/move/sleep/look, got {s!r}")
        (kind,) = keys
        if kind == "cmd":
            name = s["cmd"]
            if name not in SPORT_CMD:
                raise ValueError(f"step {i + 1}: {name!r} is not a SPORT_CMD")
            if name not in ALLOW:
                raise ValueError(f"step {i + 1}: {name!r} is not in the allowlist")
            arg, desc = (name, s.get("parameter")), f"cmd {name}" + (f" {s['parameter']}" if "parameter" in s else "")
        elif kind == "move":
            m = s["move"]
            x, y, z, sec = float(m.get("x", 0)), float(m.get("y", 0)), float(m.get("z", 0)), float(m["seconds"])
            if max(abs(x), abs(y), abs(z)) > MAX_SPEED or not 0 < sec <= MAX_MOVE_S:
                raise ValueError(f"step {i + 1}: move needs |x|,|y|,|z| <= {MAX_SPEED} and 0 < seconds <= {MAX_MOVE_S}")
            arg, desc = (x, y, z, sec), f"move x={x} y={y} z={z} {sec}s"
        elif kind == "sleep":
            sec = float(s["sleep"])
            if not 0 < sec <= 60:
                raise ValueError(f"step {i + 1}: sleep must be 0 < seconds <= 60")
            arg, desc = sec, f"sleep {sec}s"
        elif kind == "look":
            if s["look"] is not True:
                raise ValueError(f"step {i + 1}: look must be true")
            arg, desc = None, "look"
        else:
            raise ValueError(f"step {i + 1}: unknown step kind {kind!r}")
        plan.append((kind, arg, desc))
    return plan


def validate_route(steps: Any) -> list[str]:
    """Static check of a route (no connection). Returns one description per step; raises ValueError on a bad
    route (never an empty list: a valid route has at least one step)."""
    return [desc for _kind, _arg, desc in _parse(steps)]


class Body:
    """One connection, one asyncio loop. connect() then cmd/move/avoid/route/frame, then close();
    or `async with Body() as body:` which does both."""

    def __init__(self) -> None:
        self.ip = config.maybe("UNITREE_ROBOT_IP")
        self.key = config.maybe("UNITREE_AES_128_KEY")
        self.conn: UnitreeWebRTCConnection | None = None
        self._normal = False              # motion mode "normal" confirmed this process
        self._avoid: bool | None = None   # last obstacle-avoidance read-back
        self._moving = False
        self._st: dict | None = None      # latest LF_SPORT_MOD_STATE data
        self._st_n = 0
        self._st_t0 = 0.0
        self._st_at = 0.0
        self._fr = None                   # latest av.VideoFrame
        self._fr_n = 0
        self._fr_at = 0.0
        self._vid_t0 = 0.0
        self._video = False
        self._lidar: dict | None = None   # newest decoded voxel frame (wtdd/dog/lidar.py decode), None until the first
        self._lidar_n = 0
        self._lidar_err = 0
        self._lidar_at = 0.0
        self._lidar_on = False
        self._utpose: dict | None = None  # newest rt/utlidar/robot_pose data, raw (shape UNVERIFIED; for the frame check)

    # ---- connection

    async def connect(self) -> None:
        """Preflight, then one WebRTC connection. Fails loud on timeout; no mock, no reconnect loop."""
        rows, reachable = probe(scan=False)
        if not reachable:
            bad = "; ".join(f"{c}: {d}" for c, s, d in rows if s == "fail")
            raise RuntimeError(f"probe failed, refusing to connect: {bad}")
        conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip=self.ip, aes_128_key=self.key)
        with step("dog", "dog.connect", "unitree", {"ip": self.ip, "key": bool(self.key)}) as r:
            try:
                await asyncio.wait_for(conn.connect(), CONNECT_TIMEOUT_S)
            except asyncio.TimeoutError:
                await conn.disconnect()
                raise TimeoutError(f"connect to {self.ip} did not complete within {CONNECT_TIMEOUT_S}s") from None
            self.conn = conn
            # Registered before the channel is ever switched on, so the first frame is handed to us.
            conn.video.add_track_callback(self._drain)
            conn.datachannel.pub_sub.subscribe(RTC_TOPIC["LF_SPORT_MOD_STATE"], self._on_state)
            r["state_after"] = await self.fresh_state()
            r["response_or_error"] = {"peer": conn.pc.connectionState, "ice": conn.pc.iceConnectionState,
                                      "state_n": self._st_n}

    async def close(self) -> None:
        if self.conn:
            await self.conn.disconnect()
            self.conn = None
            log("dog", "closed", state_n=self._st_n, frames=self._fr_n)

    async def __aenter__(self) -> Body:
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # ---- state

    def _on_state(self, message: dict) -> None:
        d = message.get("data")
        if not isinstance(d, dict):
            log("dog", "WARN LF_SPORT_MOD_STATE message without a data dict", got=str(message)[:80])
            return
        now = time.monotonic()
        if self._st_n == 0:
            self._st_t0 = now
        self._st, self._st_n, self._st_at = d, self._st_n + 1, now

    def raw(self) -> dict | None:
        """The last full LF_SPORT_MOD_STATE data dict, untouched."""
        return self._st

    def state(self) -> dict | None:
        """Compact snapshot of the latest state message plus the measured rate. None until the first sample."""
        if self._st is None:
            return None
        d, now = self._st, time.monotonic()
        span = self._st_at - self._st_t0
        hz = round((self._st_n - 1) / span, 1) if self._st_n > 1 and span > 0 else None
        imu = d.get("imu_state") or {}
        return {"mode": d.get("mode"), "gait_type": d.get("gait_type"), "progress": d.get("progress"),
                "position": d.get("position"), "velocity": d.get("velocity"), "yaw_speed": d.get("yaw_speed"),
                "body_height": d.get("body_height"), "range_obstacle": d.get("range_obstacle"), "rpy": imu.get("rpy"),
                "n": self._st_n, "hz": hz, "age_ms": round((now - self._st_at) * 1000)}

    async def fresh_state(self, required: bool = False) -> dict | None:
        """Snapshot from a sample that arrived after this call (up to STATE_FRESH_S). required=True raises if
        none arrived: a command is never reported done without a state read-back."""
        n0, t0 = self._st_n, time.monotonic()
        while self._st_n == n0 and time.monotonic() - t0 < STATE_FRESH_S:
            await asyncio.sleep(0.02)
        if self._st_n == n0:
            msg = f"no LF_SPORT_MOD_STATE sample within {STATE_FRESH_S}s (n={n0})"
            if required:
                raise RuntimeError(msg)
            log("dog", "WARN " + msg)
        return self.state()

    # ---- requests

    async def _request(self, topic: str, api_id: int, parameter: Any = None,
                       timeout: float = REQ_TIMEOUT_S) -> tuple[int, dict]:
        """One request on the data channel; returns (status code, raw response data). Raises on timeout or
        a malformed response. The caller decides what a non-zero code means."""
        opts: dict[str, Any] = {"api_id": api_id}
        if parameter is not None:
            opts["parameter"] = parameter
        t0 = time.perf_counter()
        try:
            resp = await asyncio.wait_for(self.conn.datachannel.pub_sub.publish_request_new(topic, opts), timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"no response from {topic} api_id={api_id} within {timeout}s") from None
        data = resp.get("data") if isinstance(resp, dict) else None
        code = (((data or {}).get("header") or {}).get("status") or {}).get("code")
        ms = round((time.perf_counter() - t0) * 1000)
        log("dog", f"req {topic} api_id={api_id} code={code}", ms=ms)
        if code is None:
            raise ValueError(f"malformed response from {topic} api_id={api_id}: {str(resp)[:200]}")
        return code, data

    def _send_noreply(self, topic: str, api_id: int, parameter: Any = None) -> None:
        """A request whose api has no reply (OBSTACLES_AVOID MOVE). Same payload shape as
        pub_sub.publish_request_new, sent without a future so nothing waits forever."""
        ps = self.conn.datachannel.pub_sub
        if ps.channel.readyState != "open":  # the driver returns silently here; we do not
            raise ConnectionError("data channel is not open")
        payload = {"header": {"identity": {"id": int(time.time() * 1000) % 2147483648, "api_id": api_id}},
                   "parameter": json.dumps(parameter) if parameter is not None else ""}
        ps.publish_without_callback(topic, payload, DATA_CHANNEL_TYPE["REQUEST"])

    async def _ensure_normal(self) -> None:
        """Motion mode ready once per process: "normal" or "mcf" as found; anything else is switched to "normal" (query 1001, set 1002, wait 5 s)."""
        if self._normal:
            return
        with step("dog", "dog.mode", "unitree", {"want": "normal"}, self.state()) as r:
            code, data = await self._request(RTC_TOPIC["MOTION_SWITCHER"], MOTION_SWITCHER_GET)
            if code != 0:
                raise RuntimeError(f"motion_switcher query refused: code={code}")
            was = json.loads(data["data"])["name"]
            switched = False
            # "mcf" is the motion controller on firmware >= 1.1.7 (this dog); it refuses a switch to "normal"
            # (code 7004) and takes the same Sit/Hello/Move/StandUp ids, so it counts as ready.
            if was not in ("normal", "mcf"):
                code, _ = await self._request(RTC_TOPIC["MOTION_SWITCHER"], MOTION_SWITCHER_SET, {"name": "normal"})
                if code != 0:
                    raise RuntimeError(f"motion_switcher set normal refused: code={code} (was {was})")
                await asyncio.sleep(5)  # the dog stands up while switching
                switched = True
            r["response_or_error"] = {"was": was, "switched": switched, "code": code}
            r["state_after"] = await self.fresh_state()
        self._normal = True

    # ---- tools

    async def cmd(self, name: str, parameter: Any = None) -> int:
        """One SPORT_CMD by name. Ensures motion mode "normal" once, publishes, returns the status code
        (0 = accepted). A non-zero code raises; the row records it."""
        args = {"name": name, "api_id": SPORT_CMD.get(name), "parameter": parameter}
        with step("dog", "dog.cmd", "unitree", args, self.state()) as r:
            if name not in ALLOW:
                raise PermissionError(f"{name!r} is not in the allowlist (ALLOW in wtdd/dog/body.py)")
            await self._ensure_normal()
            code, data = await self._request(RTC_TOPIC["SPORT_MOD"], SPORT_CMD[name], parameter)
            r["response_or_error"] = data
            if code != 0:
                raise RuntimeError(f"{name} refused by the dog: code={code}")
            r["state_after"] = await self.fresh_state(required=True)
        return code

    async def _tick(self, via: str, x: float, y: float, z: float) -> int | None:
        """One velocity tick. via "avoid": OBSTACLES_AVOID MOVE 1003, no reply, returns None.
        via "sport": SPORT_CMD Move 1008, returns the ack code."""
        if via == "avoid":
            self._send_noreply(RTC_TOPIC["OBSTACLES_AVOID"], OBSTACLES_AVOID_API["MOVE"],
                               {"x": x, "y": y, "yaw": z, "mode": 0})
            return None
        code, _ = await self._request(RTC_TOPIC["SPORT_MOD"], SPORT_CMD["Move"], {"x": x, "y": y, "z": z},
                                      timeout=TICK_TIMEOUT_S)
        return code

    async def move(self, x: float = 0.0, y: float = 0.0, z: float = 0.0, seconds: float = 1.0) -> dict:
        """Velocity command at MOVE_HZ for `seconds`, then StopMove. x forward m/s, y left m/s, z yaw rad/s.
        With obstacle avoidance on, the velocity goes to the avoidance service; otherwise to the sport service."""
        args = {"x": x, "y": y, "z": z, "seconds": seconds}
        with step("dog", "dog.move", "unitree", args, self.state()) as r:
            if self._moving:
                raise RuntimeError("a move is already running (never two moves at once)")
            if max(abs(x), abs(y), abs(z)) > MAX_SPEED or not 0 < seconds <= MAX_MOVE_S:
                raise ValueError(f"move refused: |x|,|y|,|z| <= {MAX_SPEED} and 0 < seconds <= {MAX_MOVE_S}")
            await self._ensure_normal()
            # wtdd: which of the two velocity paths the dog honours with avoidance on is UNVERIFIED; the swap
            # is one line in _tick. Both end with SPORT StopMove and a state read-back.
            via = "avoid" if self._avoid else "sport"
            n, sent, acked = max(1, round(seconds * MOVE_HZ)), 0, 0
            t0 = time.perf_counter()
            self._moving = True
            try:
                for i in range(n):
                    code = await self._tick(via, x, y, z)
                    if code is not None:
                        if code != 0:
                            raise RuntimeError(f"Move refused at tick {i + 1}/{n}: code={code}")
                        acked += 1
                    sent += 1
                    await asyncio.sleep(max(0.0, t0 + (i + 1) / MOVE_HZ - time.perf_counter()))
            finally:
                self._moving = False
                elapsed = time.perf_counter() - t0
                if via == "avoid":
                    await self._tick(via, 0, 0, 0)
                try:
                    stop_code, _ = await self._request(RTC_TOPIC["SPORT_MOD"], SPORT_CMD["StopMove"])
                except Exception:
                    log("dog", "StopMove got no response: DOG MAY STILL BE MOVING", via=via, ticks=sent)
                    raise
            res = {"via": via, "ticks": sent, "acked": acked,
                   "hz": round(sent / elapsed, 1) if elapsed else None, "stop_code": stop_code}
            r["response_or_error"] = res
            if stop_code != 0:
                raise RuntimeError(f"StopMove refused: code={stop_code}; DOG MAY STILL BE MOVING")
            log("dog", f"move done via={via}", ticks=sent, acked=acked, ms=round(elapsed * 1000))
            r["state_after"] = await self.fresh_state(required=True)
        return res

    async def avoid(self, on: bool) -> bool:
        """Obstacle avoidance on/off with read-back. Also routes API velocity through the avoidance service
        (USE_REMOTE_COMMAND_FROM_API) so move() can drive while it is on."""
        with step("dog", "dog.avoid", "unitree", {"on": on}, self.state()) as r:
            if OBSTACLES_AVOID_API is None:
                raise RuntimeError("OBSTACLES_AVOID_API is missing from the installed driver; avoid and route are refused")
            topic = RTC_TOPIC["OBSTACLES_AVOID"]
            set_code, _ = await self._request(topic, OBSTACLES_AVOID_API["SWITCH_SET"], {"enable": on}, timeout=AVOID_TIMEOUT_S)
            if set_code != 0:
                raise RuntimeError(f"OBSTACLES_AVOID SWITCH_SET enable={on} refused: code={set_code}")
            api_code, _ = await self._request(topic, OBSTACLES_AVOID_API["USE_REMOTE_COMMAND_FROM_API"],
                                              {"is_remote_commands_from_api": on}, timeout=AVOID_TIMEOUT_S)
            if api_code != 0:
                raise RuntimeError(f"OBSTACLES_AVOID USE_REMOTE_COMMAND_FROM_API={on} refused: code={api_code}")
            get_code, data = await self._request(topic, OBSTACLES_AVOID_API["SWITCH_GET"], timeout=AVOID_TIMEOUT_S)
            if get_code != 0:
                raise RuntimeError(f"OBSTACLES_AVOID SWITCH_GET refused: code={get_code}")
            enabled = json.loads(data["data"])["enable"]
            if enabled is not on:
                raise RuntimeError(f"avoidance read-back mismatch: asked {on}, dog says {enabled}")
            self._avoid = enabled
            r["response_or_error"] = {"set_code": set_code, "api_code": api_code, "get_code": get_code,
                                      "enable": enabled}
            r["state_after"] = {**(await self.fresh_state() or {}), "avoid": enabled}
        return enabled

    async def route(self, steps: list, name: str = "route") -> list[dict]:
        """Runs a validated list of steps with obstacle avoidance on; every step writes its own row with a
        state read-back. Avoidance is switched back off afterwards, also on failure."""
        plan = _parse(steps)
        with step("dog", "dog.route", "unitree", {"name": name, "steps": [d for _, _, d in plan]}, self.state()) as r:
            await self.avoid(True)
            done: list[dict] = []
            try:
                for i, (kind, arg, desc) in enumerate(plan):
                    log("dog", f"route {name} step {i + 1}/{len(plan)}: {desc}")
                    if kind == "cmd":
                        res: Any = await self.cmd(*arg)
                    elif kind == "move":
                        res = await self.move(*arg)
                    elif kind == "sleep":
                        await asyncio.sleep(arg)
                        res = self.state()
                    else:
                        out = PICTURES / f"{time.strftime('%Y%m%dT%H%M%S')}_{name}_{i + 1}.jpg"
                        res = {"path": str(out), "sha256": hashlib.sha256(await self.frame(out)).hexdigest()}
                    done.append({"step": i + 1, "desc": desc, "result": res})
            finally:
                await self.avoid(False)
            r["response_or_error"] = {"done": len(done), "of": len(plan)}
            r["state_after"] = await self.fresh_state()
        return done

    # ---- lidar (wtdd/dog/lidar.py)

    async def lidar_on(self) -> None:
        """The dog's LiDAR voxel stream on, once per connection; decoded frames land in _on_lidar, the newest is kept."""
        if self._lidar_on:
            return
        await lidar.subscribe(self.conn, self._on_lidar, self._on_utpose)
        self._lidar_on = True

    async def lidar_off(self) -> None:
        if not self._lidar_on:
            return
        lidar.unsubscribe(self.conn)
        self._lidar_on = False
        log("dog", "lidar off", frames=self._lidar_n, errors=self._lidar_err)

    def _on_lidar(self, message: dict) -> None:
        """Runs inside the driver's message handler. A frame that fails to decode is counted, logged and re-raised (the
        driver prints the traceback); nothing stands in for it. The first frame logs its shape, its z layers and how far
        the window's center is from the LF_SPORT_MOD_STATE position (the frame check in lidar.py's docstring)."""
        try:
            d = lidar.decode(message)
        except Exception as e:  # noqa: BLE001  (counted and re-raised; lidar_points() reports the count)
            self._lidar_err += 1
            log("dog", "WARN lidar frame rejected", err=f"{type(e).__name__}: {str(e)[:120]}", errors=self._lidar_err)
            raise
        now = time.monotonic()
        if self._lidar_n == 0:
            pos = (self.state() or {}).get("position") or [0.0, 0.0, 0.0]
            off = math.hypot(d["center"][0] - float(pos[0]), d["center"][1] - float(pos[1]))
            z = d["points"][:, 2]
            layers = {round(float(k), 2): int(c) for k, c in zip(*np.unique(z, return_counts=True))} if len(z) else {}
            log("dog", f"first lidar frame frame_id={d['frame']}", voxels=d["n"], width=d["width"], res=d["resolution"],
                origin=[round(v, 2) for v in d["origin"]], center=[round(v, 2) for v in d["center"]],
                odom_pos=[round(float(v), 2) for v in pos[:3]], center_vs_odom_m=round(off, 2), z_layers=layers)
            if off > 1.0:
                log("dog", "WARN lidar window center is far from the LF_SPORT_MOD_STATE position: the voxel frame may not be that odometry",
                    center_vs_odom_m=round(off, 2), frame_id=d["frame"], utlidar_pose=str(self._utpose)[:160])
        self._lidar, self._lidar_n, self._lidar_at = d, self._lidar_n + 1, now
        if self._lidar_n % 100 == 0:
            log("dog", f"lidar frames={self._lidar_n}", voxels=d["n"], errors=self._lidar_err)

    def _on_utpose(self, message: dict) -> None:
        self._utpose = message.get("data")

    def lidar_points(self) -> dict:
        """The newest decoded voxel frame and the counts: {on, n (frames), errors, age_ms, frame (None until the first:
        id, stamp, origin, resolution, width, center, voxels), points (float64 (N, 3) meters or None), utlidar_pose}."""
        d = self._lidar
        return {"on": self._lidar_on, "n": self._lidar_n, "errors": self._lidar_err,
                "age_ms": round((time.monotonic() - self._lidar_at) * 1000) if d else None,
                "frame": {"id": d["frame"], "stamp": d["stamp"], "origin": d["origin"], "resolution": d["resolution"],
                          "width": d["width"], "center": d["center"], "voxels": d["n"]} if d else None,
                "points": d["points"] if d else None, "utlidar_pose": self._utpose}

    # ---- camera

    async def _drain(self, track) -> None:
        """The only video callback. The driver awaits it with the live track after discarding frame 1;
        it must never return, so aiortc's queue stays flat and self._fr is always the newest frame."""
        while True:
            f = await track.recv()  # MediaStreamError on peer close, caught by the driver
            now = time.monotonic()
            if self._fr_n == 0:
                log("dog", f"first frame {f.width}x{f.height} after {round((now - self._vid_t0) * 1000)} ms")
            self._fr, self._fr_n, self._fr_at = f, self._fr_n + 1, now
            if self._fr_n % 300 == 0:
                log("dog", f"video frames={self._fr_n}")

    async def _video_on(self) -> None:
        if self._video:
            return
        self._vid_t0 = time.monotonic()
        self.conn.video.switchVideoChannel(True)
        self._video = True
        while self._fr is None:
            if time.monotonic() - self._vid_t0 > FRAME_TIMEOUT_S:
                raise TimeoutError(f"no video frame within {FRAME_TIMEOUT_S}s of switching the channel on (frames=0)")
            await asyncio.sleep(0.05)

    async def jpeg(self, quality: int = 70) -> tuple[bytes, Any, float]:
        """The newest frame as JPEG bytes (PIL via av; never cv2), plus the frame and its age. No ledger row: this is
        the read behind the remote's live view (GET /dog/frame.jpg); frame() is the receipted capture."""
        await self._video_on()
        age = time.monotonic() - self._fr_at
        if age > FRAME_STALE_S:
            raise RuntimeError(f"video stale: last frame {age:.1f}s ago (frames={self._fr_n})")
        f = self._fr
        buf = io.BytesIO()
        f.to_image().save(buf, "JPEG", quality=quality)
        return buf.getvalue(), f, age

    async def frame(self, out: Path | str | None = None) -> bytes:
        """JPEG bytes of the newest video frame. Writes `out` if given. The row carries the sha256 of the exact bytes."""
        with step("dog", "dog.frame", "unitree", {"out": str(out) if out else None}, self.state()) as r:
            data, f, age = await self.jpeg(quality=85)
            sha = hashlib.sha256(data).hexdigest()
            if out:
                out = Path(out).expanduser()
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            info = {"w": f.width, "h": f.height, "bytes": len(data), "sha256": sha, "frames_seen": self._fr_n,
                    "age_ms": round(age * 1000), "path": str(out) if out else None}
            r["response_or_error"] = info
            r["state_after"] = {**(self.state() or {}), "frame_sha256": sha}
            log("dog", f"frame {f.width}x{f.height} bytes={len(data)} sha256={sha[:12]}", n=self._fr_n)
        return data
