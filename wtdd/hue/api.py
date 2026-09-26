"""HueBridge: Philips Hue CLIP v2 client. One ledger row per network call; every PUT is followed by a GET read-back
that must match the request (_matches) or the row fails and the call raises.

Local: https://<HUE_BRIDGE_IP>/clip/v2/... with the hue-application-key header over the bridge's self-signed cert
(verify=False, LAN only, logged once). Remote: the same paths under https://api.meethue.com/route with an OAuth
bearer token (HUE_REMOTE_TOKEN): slower, works from any network, and the route this repo runs in practice because
the bridge (10.66.1.109) sits on a different subnet than this Mac (10.66.10.0/24). from_env() picks remote whenever
HUE_REMOTE_TOKEN is set.

Verified on the real bridge 2026-09-13 (id 001788FFFE616851 "Hue Bridge Car", sw 1978293000, apiversion 1.78.0,
7 lights, 4 of them in the living room):
- PUT /clip/v2/resource/light/<id> bodies: {"on": {"on": bool}}, {"dimming": {"brightness": 0..100}},
  {"color": {"xy": {"x", "y"}}}, {"signaling": {"signal": "alternating", "duration": ms, "colors": [{"xy": {...}}]}}.
  The read-back shows signaling.status.signal == "alternating"; a light lists what it accepts in signaling.signal_values.
  The bridge answers {"errors": [], "data": [{"rid", "rtype"}]}; a non-empty errors list is a failure even on HTTP 200.
- Pairing: POST /api {"devicetype", "generateclientkey": true} answers [{"error": {"type": 101, "description": "link
  button not pressed"}}] until the button is pressed, then [{"success": {"username", "clientkey"}}]. On the cloud
  route PUT /api/0/config {"linkbutton": true} presses it.
- Rate: Hue's guidance is about 10 light commands per second and 1 grouped_light per second (PUT_GAP_S). Measured on
  the cloud route: 15 of 15 back-to-back sets ok, no 429, median 794 ms; about 0.8 s per set including the read-back.
- Discovery (https://discovery.meethue.com/) returns [{"id", "internalipaddress", "port"}] and rate-limits: HTTP 429
  after repeated probes, so probe treats it as informational once HUE_BRIDGE_IP is set.
"""
from __future__ import annotations
import json
import socket
import time
from typing import Any

import requests
import urllib3

from .. import config, ledger

AGENT, APP = "lights", "hue"
DISCOVERY_URL = "https://discovery.meethue.com/"
REMOTE_BASE = "https://api.meethue.com/route"
OAUTH = "https://api.meethue.com/v2/oauth2"
RED_XY, BLUE_XY = (0.675, 0.322), (0.167, 0.04)
PUT_GAP_S = {"light": 0.1, "grouped_light": 1.0}


def raw(x: Any) -> str:
    """response_or_error is stored as compact JSON: the raw response, never a summary. wtdd.ledger.step slices it
    for the log line."""
    return json.dumps(x, separators=(",", ":"), default=str)


class HueError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


def discover() -> list[dict[str, Any]]:
    """Cloud discovery: [{"id", "internalipaddress", "port"}]. One row."""
    with ledger.step(AGENT, "lights.discover", APP, {"url": DISCOVERY_URL}) as r:
        resp = requests.get(DISCOVERY_URL, timeout=5)
        r["response_or_error"] = raw({"status": resp.status_code, "body": resp.text})
        if resp.status_code != 200:
            raise HueError(f"discovery HTTP {resp.status_code}", resp.status_code)
        bridges = resp.json()
        if not bridges:
            ledger.log(AGENT, "WARN discovery returned zero bridges")
        r["state_after"] = bridges
        return bridges


def tcp_open(ip: str, port: int = 443, timeout: float = 3.0) -> float:
    """Raw TCP connect to `host` or `host:port`; returns connect time in ms or raises. One row."""
    host, _, p = ip.partition(":")
    port = int(p) if p else port
    with ledger.step(AGENT, "lights.tcp", APP, {"ip": host, "port": port}) as r:
        t0 = time.perf_counter()
        try:
            socket.create_connection((host, port), timeout=timeout).close()
        except OSError as e:
            raise HueError(f"tcp {host}:{port} closed: {e}") from e
        ms = round((time.perf_counter() - t0) * 1000, 1)
        r["response_or_error"] = raw({"connect_ms": ms})
        return ms


def summary(light: dict[str, Any]) -> dict[str, Any]:
    """The compact state that goes into state_before and state_after. Keys on/brightness/xy/signal are a contract:
    tools/lights_status.py spreads them into every hue row and ui/index.html reads on and brightness."""
    xy = light.get("color", {}).get("xy")
    return {"on": light.get("on", {}).get("on"),
            "brightness": light.get("dimming", {}).get("brightness"),
            "xy": [xy["x"], xy["y"]] if xy else None,
            "signal": light.get("signaling", {}).get("status", {}).get("signal")}


class HueBridge:
    _warned = False

    def __init__(self, ip: str, key: str | None = None, timeout: float = 5.0, remote_token: str | None = None):
        self.ip, self.key, self.timeout = ip, key, timeout
        self.remote = bool(remote_token)
        self.s = requests.Session()
        self._last_put: dict[str, float] = {}
        if self.remote:
            self.base = REMOTE_BASE
            self.s.headers["Authorization"] = f"Bearer {remote_token}"
            return
        self.base = f"https://{ip}"
        # wtdd: verify=False because the bridge cert is self-signed; LAN only. Upgrade path: pin the Hue root CA.
        self.s.verify = False
        if not HueBridge._warned:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            ledger.log(AGENT, "TLS verify=False: bridge cert is self-signed (LAN only)", ip=ip)
            HueBridge._warned = True

    @classmethod
    def from_env(cls, key_required: bool = True) -> "HueBridge":
        """Remote when HUE_REMOTE_TOKEN is set, else local via HUE_BRIDGE_IP."""
        key = config.get("HUE_APP_KEY") if key_required else config.maybe("HUE_APP_KEY")
        return cls(config.maybe("HUE_BRIDGE_IP") or "api.meethue.com", key, remote_token=config.maybe("HUE_REMOTE_TOKEN"))

    # one HTTP call; maps bad key, rate limit, and connection failures to HueError; never retries
    def _req(self, method: str, path: str, body: Any = None, auth: bool = True) -> Any:
        headers = {"hue-application-key": self.key} if auth else {}
        if auth and not self.key:
            raise HueError("HUE_APP_KEY is empty: run `python -m wtdd.hue pair`")
        try:
            resp = self.s.request(method, self.base + path, json=body, headers=headers, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise HueError(f"unreachable {self.base if self.remote else self.ip}: {type(e).__name__}: {str(e)[:120]}") from e
        text = resp.text[:2000]
        if resp.status_code in (401, 403):
            raise HueError(f"bad key (HTTP {resp.status_code}): {text}", resp.status_code)
        if resp.status_code == 429:
            raise HueError(f"rate limited (HTTP 429): {text}", 429)
        if resp.status_code >= 400:
            raise HueError(f"HTTP {resp.status_code} {method} {path}: {text}", resp.status_code)
        data = resp.json()
        if isinstance(data, dict) and data.get("errors"):
            raise HueError(f"bridge errors on {method} {path}: {data['errors']}", resp.status_code)
        return data

    def _throttle(self, rtype: str) -> None:
        wait = self._last_put.get(rtype, 0.0) + PUT_GAP_S[rtype] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_put[rtype] = time.monotonic()

    def _get_light(self, rid: str) -> dict[str, Any]:
        return self._req("GET", f"/clip/v2/resource/light/{rid}")["data"][0]

    # unauthenticated: name, bridgeid, swversion, apiversion
    def config(self) -> dict[str, Any]:
        with ledger.step(AGENT, "lights.config", APP, {"path": "/api/0/config"}) as r:
            cfg = self._req("GET", "/api/0/config", auth=False)
            r["response_or_error"] = raw(cfg)
            return cfg

    def pair(self, devicetype: str = "wtdd#mac") -> str:
        """One POST /api attempt. Returns the username (the app key); raises HueError('link button not pressed')
        when the button has not been pressed. The caller polls. The key is never logged."""
        with ledger.step(AGENT, "lights.pair", APP, {"devicetype": devicetype}) as r:
            if self.remote:
                self._req("PUT", "/api/0/config", {"linkbutton": True}, auth=False)   # the cloud "link button"
            out = self._req("POST", "/api", {"devicetype": devicetype, "generateclientkey": True}, auth=False)
            first = out[0] if isinstance(out, list) and out else {}
            if "error" in first:
                r["response_or_error"] = raw(first["error"])
                raise HueError(str(first["error"].get("description", first["error"])))
            if "success" not in first or "username" not in first["success"]:
                raise HueError(f"unexpected pair response: {str(out)[:200]}")
            r["response_or_error"] = raw({"success": {"username": "<redacted>"}})
            return first["success"]["username"]

    def lights(self) -> list[dict[str, Any]]:
        with ledger.step(AGENT, "lights.list", APP) as r:
            data = self._req("GET", "/clip/v2/resource/light")["data"]
            r["response_or_error"] = raw(data)
            r["state_after"] = {l["id"]: summary(l) for l in data}
            if not data:
                ledger.log(AGENT, "WARN bridge returned zero lights", ip=self.ip)
            return data

    def rooms(self) -> list[dict[str, Any]]:
        with ledger.step(AGENT, "lights.rooms", APP) as r:
            data = self._req("GET", "/clip/v2/resource/room")["data"]
            r["response_or_error"] = raw(data)
            return data

    def connectivity(self) -> dict[str, str]:
        """device rid -> zigbee status (connected, disconnected, connectivity_issue, unidirectional_incoming)."""
        with ledger.step(AGENT, "lights.connectivity", APP) as r:
            data = self._req("GET", "/clip/v2/resource/zigbee_connectivity")["data"]
            r["response_or_error"] = raw(data)
            return {c["owner"]["rid"]: c["status"] for c in data if "owner" in c}

    def read(self, rid: str) -> dict[str, Any]:
        with ledger.step(AGENT, "lights.read", APP, {"id": rid}) as r:
            light = self._get_light(rid)
            r["response_or_error"] = raw(light)
            r["state_after"] = summary(light)
            return light

    def set(self, rid: str, on: bool | None = None, bri: float | None = None,
            xy: tuple[float, float] | None = None) -> dict[str, Any]:
        """PUT then GET. The step is ok only if the read-back matches what was requested."""
        body: dict[str, Any] = {}
        if on is not None:
            body["on"] = {"on": on}
        if bri is not None:
            body["dimming"] = {"brightness": bri}
        if xy is not None:
            body["color"] = {"xy": {"x": xy[0], "y": xy[1]}}
        if not body:
            raise ValueError("set: nothing to set (on, bri, or xy)")
        return self._put_light(rid, "lights.set", body)

    def signal(self, rid: str, seconds: float, colors=(RED_XY, BLUE_XY)) -> dict[str, Any]:
        """Native `alternating` signal between two xy colors for `seconds`. Refused after one read when the light does
        not list `alternating` in signal_values. One PUT, one ledger row."""
        supported = self.read(rid).get("signaling", {}).get("signal_values", [])
        if "alternating" not in supported:
            raise HueError(f"light {rid[:8]} does not support signal alternating (signal_values={supported})")
        duration = int(round(seconds)) * 1000
        pts = [{"xy": {"x": x, "y": y}} for x, y in colors]
        return self._put_light(rid, "lights.signal", {"signaling": {"signal": "alternating", "duration": duration, "colors": pts}})

    def _put_light(self, rid: str, tool: str, body: dict[str, Any]) -> dict[str, Any]:
        """The one write path: before, throttle, PUT, read back, match. Also called directly by tools/identify.py
        with tool 'lights.identify' and a signaling on_off body."""
        before = summary(self._get_light(rid))
        with ledger.step(AGENT, tool, APP, {"id": rid, **body}, before) as r:
            self._throttle("light")
            r["response_or_error"] = raw(self._req("PUT", f"/clip/v2/resource/light/{rid}", body))
            after = summary(self._get_light(rid))
            r["state_after"] = after
            r["match"] = _matches(body, after)
            if not r["match"]:
                raise HueError(f"read-back mismatch: requested {body}, bridge has {after}")
            return after


def _matches(body: dict[str, Any], after: dict[str, Any]) -> bool:
    if "on" in body and after["on"] != body["on"]["on"]:
        return False
    if "dimming" in body and (after["brightness"] is None
                              or abs(after["brightness"] - body["dimming"]["brightness"]) > 1):
        return False
    if "color" in body:
        want = body["color"]["xy"]
        if after["xy"] is None or abs(after["xy"][0] - want["x"]) > 0.02 or abs(after["xy"][1] - want["y"]) > 0.02:
            return False
    if "signaling" in body and after["signal"] != body["signaling"]["signal"]:
        return False
    return True
