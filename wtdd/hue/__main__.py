"""Philips Hue lights agent: python -m wtdd.hue <cmd>. Every command writes ledger rows (agent 'lights', app 'hue';
tools lights.set, lights.set_zone, lights.list, lights.rooms, lights.connectivity, lights.read, lights.signal,
lights.identify, lights.pair, lights.config, lights.discover, lights.tcp, lights.oauth_token); every PUT is followed by
a GET read-back that must match or the row fails and the call raises. Env: HUE_BRIDGE_IP, HUE_APP_KEY,
HUE_REMOTE_TOKEN, HUE_REMOTE_REFRESH, HUE_CLIENT_ID, HUE_CLIENT_SECRET, HUE_APP_ID (all read through wtdd.config).

Commands:
  probe                                   discovery, tcp, config, key, light count; never throws before the table
  pair [--force]                          local link-button flow; writes HUE_APP_KEY into .env; never prints the key
  lights                                  table: id, name, room, on, bri, color, reachable (zigbee_connectivity)
  read <light>                            one light's summary; <light> = full id, unique id prefix, or name
  set <light> --on|--off [--bri 0-100] [--xy x,y]
  signal <light> --seconds N              native alternating red/blue on a colour light
  zone <name> --on|--off [--bri N]        every light of a zone from zones.json (a, b, c, living room)
  remote-auth [--port 8787] [--timeout 180] [--no-open]   cloud path: OAuth -> tokens -> cloud link button -> app key
  remote-refresh                          new HUE_REMOTE_TOKEN from HUE_REMOTE_REFRESH
  burst <light> [--n 15]                  rate-limit probe: n quick sets with the throttle off, stop at the first 429

Done when (all seen on the real bridge 2026-09-13): probe reports the bridge reachable and the key valid; lights
prints every light with live state; set then read shows the change in state_after; signal runs on a colour bulb; each
of those is one ledger row with latency. Measured numbers (0.8 s per set, 15 of 15 burst sets ok) are in api.py.

Facts (2026-09-13). Bridge 001788FFFE616851 "Hue Bridge Car" at 10.66.1.109 (meethue discovery); this Mac is on
10.66.10.0/24 and cannot reach it on the LAN, so everything runs through the cloud route (HUE_REMOTE_TOKEN set).
7 lights on the bridge; the four in the living room are Hue Iris 2, Go table lamp 1, special, sticky canbo.
Cloud path setup: register a "Remote Hue API" app at https://developers.meethue.com/my-apps/ with callback
http://localhost:8787/callback, put HUE_CLIENT_ID, HUE_CLIENT_SECRET, HUE_APP_ID in .env, run `remote-auth` (opens
the browser, catches the code on :8787, exchanges tokens, presses the cloud link button, creates the app key; writes
HUE_REMOTE_TOKEN, HUE_REMOTE_REFRESH, HUE_APP_KEY to .env). Local path: Johnny puts this Mac on the bridge's subnet
(or moves the bridge's Ethernet to this router), runs `pair`, and presses the physical link button when it says so.

zones.json: zone name -> {"lights": [full light ids], "names": [the same lights, for humans]}. a, b, c are the three
corridor thirds (1.5 m each; their polygons and the strip flag live in ui/map.json); "living room" is all four.
set_zone reads only `lights`, refuses an empty zone or an id the bridge does not have, and never touches an id absent
from the file.

Never: no fallbacks, no cached light state pretending to be live, no writes to lights not named in the command, no git
commit from here.
Tests: python -m wtdd.hue.test_stub (an in-process HTTPS fake bridge covering request shaping, the read-back rule,
bad key, rate limit, the pair poll, zones, and the signal refusal; nothing there touches the real bridge).
"""
from __future__ import annotations
import argparse
import http.server
import json
import re
import shutil
import socketserver
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests

from .. import config, ledger
from .api import OAUTH, AGENT, APP, HueBridge, HueError, discover, raw, summary, tcp_open

ZONES = Path(__file__).resolve().with_name("zones.json")
ENV = config.ROOT / ".env"


# ---------------------------------------------------------------- probe
def probe(ip: str | None, key: str | None) -> bool:
    """Never raises. Prints one status table; returns True only when every line is ok or warn."""
    rows: list[tuple[str, str, str]] = []

    def run(label: str, fn, skip: str | None = None) -> Any:
        if skip:
            rows.append((label, "SKIP", skip))
            return None
        try:
            out, note = fn()
            rows.append((label, "ok", note))
            return out
        except Exception as e:  # noqa: BLE001  (probe reports; the ledger row already has the error)
            rows.append((label, "FAIL", f"{type(e).__name__}: {str(e)[:140]}"))
            return None

    def _disc():
        b = discover()
        found = [x for x in b if x.get("internalipaddress") == ip]
        return b, (f"{len(b)} bridge(s): " + ", ".join(f"{x.get('id')} @ {x.get('internalipaddress')}:{x.get('port')}" for x in b)
                   + (" (matches HUE_BRIDGE_IP)" if found else f" (HUE_BRIDGE_IP={ip} not in list)"))

    def _cfg():
        c = b.config()
        return c, f"name={c.get('name')} swversion={c.get('swversion')} apiversion={c.get('apiversion')} bridgeid={c.get('bridgeid')}"

    def _lights():
        ls = b.lights()
        return ls, f"n={len(ls)}: " + ", ".join(f"{l['id'][:8]} {l['metadata']['name']}" for l in ls)

    key_row = ("HUE_APP_KEY", "ok" if key else "FAIL", f"present ({len(key)} chars)" if key else "empty: run `python -m wtdd.hue pair`")
    token = config.maybe("HUE_REMOTE_TOKEN")
    if token:
        b = HueBridge(ip or "api.meethue.com", key, remote_token=token)
        rows.append(("mode", "ok", "REMOTE via api.meethue.com/route (HUE_REMOTE_TOKEN set)"))
        run("GET /route/api/0/config", _cfg)
        rows.append(key_row)
        run("GET /route/clip/v2/resource/light", _lights, skip=None if key else "no key")
        fix = "if the token expired run `python -m wtdd.hue remote-refresh`; if there is no key run `python -m wtdd.hue pair`."
    else:
        # discovery is informational once HUE_BRIDGE_IP is set (Philips rate-limits it: HTTP 429 after repeated probes)
        run("discovery.meethue.com", _disc)
        if ip and rows[-1][1] == "FAIL":
            rows[-1] = (rows[-1][0], "warn", rows[-1][2] + " (informational; HUE_BRIDGE_IP is set)")
        tcp = False
        if not ip:
            rows.append(("HUE_BRIDGE_IP", "FAIL", f"missing: cp .env.example .env (see {ENV})"))
        else:
            b = HueBridge(ip, key)
            tcp = run(f"tcp {ip if ':' in ip else ip + ':443'}", lambda: (tcp_open(ip), "open")) is not None
            run("GET /api/0/config", _cfg, skip=None if tcp else "tcp closed")
        rows.append(key_row)
        if ip:
            run("GET /clip/v2/resource/light", _lights, skip=None if (tcp and key) else ("tcp closed" if not tcp else "no key"))
        fix = ("1) put this Mac on the bridge's subnet (or move the bridge's Ethernet to this router), then re-run "
               "`python -m wtdd.hue probe`; 2) when tcp is open, run `python -m wtdd.hue pair` and press the link button.")

    w = max(len(r[0]) for r in rows)
    print(f"{'probe':<{w}}  status  detail")
    for label, status, note in rows:
        print(f"{label:<{w}}  {status:<6}  {note}")
    ok = all(r[1] in ("ok", "warn") for r in rows)
    if not ok:
        print(f"\nBLOCKED. Johnny: {fix}")
    return ok


# ---------------------------------------------------------------- pair
def write_env_key(path: Path, name: str, value: str) -> None:
    if not path.exists():
        shutil.copy(config.ROOT / ".env.example", path)
    text = path.read_text()
    line = f"{name}={value}"
    if re.search(rf"^{name}=.*$", text, flags=re.M):
        text = re.sub(rf"^{name}=.*$", line, text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    path.write_text(text)


def pair(b: HueBridge, env_path: Path = ENV, poll_s: float = 2.0, max_s: float = 60.0) -> bool:
    """Polls POST /api until the bridge hands out a username, then writes it to .env. Never prints the key."""
    t0 = time.monotonic()
    prompted = False
    while True:
        try:
            username = b.pair()
            break
        except HueError as e:
            if "link button not pressed" not in str(e):
                raise
            if not prompted:
                print(f"PRESS THE ROUND LINK BUTTON ON THE HUE BRIDGE NOW (polling every {poll_s:g}s for {max_s:g}s)", flush=True)
                prompted = True
            if time.monotonic() - t0 > max_s:
                print("pair: gave up, the link button was not pressed in time; re-run `python -m wtdd.hue pair`.")
                return False
            time.sleep(poll_s)
    write_env_key(env_path, "HUE_APP_KEY", username)
    b.key = username
    print(f"paired: HUE_APP_KEY ({len(username)} chars) written to {env_path}. Next: `python -m wtdd.hue lights`")
    return True


# ---------------------------------------------------------------- lights / resolve
def resolve(lights: list[dict[str, Any]], ref: str) -> dict[str, Any]:
    """Full rid, unique rid prefix, or case-insensitive name."""
    hits = [l for l in lights if l["id"] == ref] or [l for l in lights if l["id"].startswith(ref)] \
        or [l for l in lights if l["metadata"]["name"].lower() == ref.lower()]
    if len(hits) != 1:
        names = ", ".join(f"{l['id'][:8]} {l['metadata']['name']}" for l in lights)
        raise HueError(f"'{ref}' matches {len(hits)} lights; known: {names}")
    return hits[0]


def lights_table(b: HueBridge) -> list[dict[str, Any]]:
    ls, rooms, conn = b.lights(), b.rooms(), b.connectivity()
    room_of = {c["rid"]: rm["metadata"]["name"] for rm in rooms for c in rm.get("children", []) if c["rtype"] == "device"}
    out = []
    for l in ls:
        dev = l.get("owner", {}).get("rid")
        s = summary(l)
        out.append({"id": l["id"][:8], "name": l["metadata"]["name"], "room": room_of.get(dev, "?"),
                    "on": s["on"], "bri": s["brightness"], "color": "color" in l, "reachable": conn.get(dev, "?")})
    hdr = ("id", "name", "room", "on", "bri", "color", "reachable")
    widths = [max(len(h), *(len(str(r[h])) for r in out)) for h in hdr] if out else [len(h) for h in hdr]
    print("  ".join(f"{h:<{w}}" for h, w in zip(hdr, widths)))
    for r in out:
        print("  ".join(f"{str(r[h]):<{w}}" for h, w in zip(hdr, widths)))
    ledger.log(AGENT, f"lights table (n={len(out)})")
    return out


# ---------------------------------------------------------------- zone
def load_zones(path: Path = ZONES) -> dict[str, Any]:
    zones = json.loads(path.read_text())
    if not isinstance(zones, dict) or not zones:
        raise HueError(f"{path} must be a non-empty object of zones")
    return zones


def set_zone(b: HueBridge, name: str, on: bool, bri: float | None, path: Path = ZONES) -> dict[str, Any]:
    """Sets every light in the zone (contract: never touches an id absent from zones.json). One lights.set_zone row on
    top of one lights.set row per light. Returns {light id: summary}."""
    zones = load_zones(path)
    if name not in zones:
        raise HueError(f"zone '{name}' not in {path}; known: {', '.join(zones)}")
    ids = zones[name].get("lights", [])
    if not ids:
        raise HueError(f"zone '{name}' has no lights in {path}: Johnny must fill it (ids from `python -m wtdd.hue lights`)")
    known = {l["id"] for l in b.lights()}
    missing = [i for i in ids if i not in known]
    if missing:
        raise HueError(f"zone '{name}' names light ids the bridge does not have: {missing}")
    before = {i: summary(b._get_light(i)) for i in ids}
    with ledger.step(AGENT, "lights.set_zone", APP, {"zone": name, "on": on, "brightness": bri, "lights": ids}, before) as r:
        r["state_after"] = {i: b.set(i, on=on, bri=bri) for i in ids}
        r["response_or_error"] = raw({"read_back": r["state_after"]})
        r["match"] = True
        return r["state_after"]


# ---------------------------------------------------------------- cloud auth
def _catch_code(port: int, timeout_s: float) -> str | None:
    """Tiny one-shot HTTP listener for the OAuth redirect http://localhost:<port>/callback?code=...; None on timeout."""
    got: dict[str, str] = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got["code"] = (q.get("code") or [""])[0]
            self.send_response(200); self.end_headers()
            self.wfile.write(b"wtdd: got the code, you can close this tab")

        def log_message(self, *a):  # quiet
            pass

    with socketserver.TCPServer(("127.0.0.1", port), H) as srv:
        srv.timeout = timeout_s
        srv.handle_request()
    return got.get("code") or None


def _token(grant: str, **fields: str) -> dict[str, Any]:
    """One POST to the Hue OAuth token endpoint (basic auth with the client id and secret); one lights.oauth_token row."""
    cid, secret = config.get("HUE_CLIENT_ID"), config.get("HUE_CLIENT_SECRET")
    with ledger.step(AGENT, "lights.oauth_token", APP, {"grant": grant}) as r:
        resp = requests.post(f"{OAUTH}/token", auth=(cid, secret), data={"grant_type": grant, **fields}, timeout=15)
        if resp.status_code != 200:
            raise HueError(f"{grant} HTTP {resp.status_code}: {resp.text[:200]}")
        tok = resp.json()
        r["state_after"] = {"expires_in": tok.get("expires_in"), "token_type": tok.get("token_type")}
    write_env_key(ENV, "HUE_REMOTE_TOKEN", tok["access_token"])
    refresh = tok.get("refresh_token", "")
    if refresh or grant == "authorization_code":   # a fresh login always rewrites the refresh token, even to blank
        write_env_key(ENV, "HUE_REMOTE_REFRESH", refresh)
    return tok


def remote_auth(a: argparse.Namespace) -> int:
    """Cloud path: OAuth code -> tokens -> virtual link button -> app key (see the module docstring for the app setup)."""
    url = f"{OAUTH}/authorize?" + urllib.parse.urlencode({"client_id": config.get("HUE_CLIENT_ID"), "response_type": "code",
                                                          "state": "wtdd", "appid": config.get("HUE_APP_ID"),
                                                          "deviceid": "wtdd-mac", "devicename": "wtdd"})
    print("1) Log in and grant in the browser" + (" (opening it now)" if not a.no_open else " (use the tab already open)") + ":\n   " + url, flush=True)
    if not a.no_open:
        subprocess.run(["open", url], check=False)
    print(f"2) Waiting up to {a.timeout:.0f}s for the redirect on http://localhost:{a.port}/callback ...", flush=True)
    code = _catch_code(a.port, a.timeout)
    if not code:
        if not sys.stdin.isatty():
            raise HueError(f"no redirect reached http://localhost:{a.port}/callback within {a.timeout:.0f}s "
                           "(the Hue login or the allow step was not completed); re-run when at the browser")
        code = input("   No redirect caught. Paste the `code` from the redirect URL: ").strip()
    tok = _token("authorization_code", code=code)
    print("3) Tokens written to .env. Creating the app key through the cloud link button ...")
    username = HueBridge("api.meethue.com", None, remote_token=tok["access_token"]).pair("wtdd#remote")
    write_env_key(ENV, "HUE_APP_KEY", username)
    print("4) HUE_APP_KEY written. Now: python -m wtdd.hue probe && python -m wtdd.hue lights")
    return 0


def remote_refresh(a: argparse.Namespace) -> int:
    _token("refresh_token", refresh_token=config.get("HUE_REMOTE_REFRESH"))
    print("refreshed; HUE_REMOTE_TOKEN written")
    return 0


def burst(a: argparse.Namespace) -> int:
    """Rate-limit probe: n back-to-back brightness PUTs (alternating +1/-1, imperceptible) on one light with the throttle
    off; prints status and latency per call and stops at the first 429; restores the original brightness."""
    b = HueBridge.from_env(key_required=False)
    rid = resolve(b.lights(), a.light)["id"]
    base = float(summary(b.read(rid)).get("brightness") or 50)
    results = []
    orig_throttle = b._throttle
    b._throttle = lambda rtype: None
    try:
        for i in range(a.n):
            bri = max(1.0, min(100.0, base + (1 if i % 2 == 0 else -1)))
            t0 = time.monotonic()
            try:
                b.set(rid, bri=bri)
                results.append((i, "ok", round((time.monotonic() - t0) * 1000)))
            except HueError as e:
                results.append((i, f"HTTP {e.status}", round((time.monotonic() - t0) * 1000)))
                if e.status == 429:
                    break
    finally:
        b._throttle = orig_throttle
        time.sleep(1.0)
        b.set(rid, bri=base)
    for i, st, ms in results:
        print(f"{i:>3}  {st:<9} {ms:>5} ms")
    oks = [ms for _, st, ms in results if st == "ok"]
    print(f"\n{len(oks)} ok of {len(results)}; median {sorted(oks)[len(oks)//2] if oks else '-'} ms; "
          f"first 429 at call {next((i for i, st, _ in results if st == 'HTTP 429'), 'none')}; mode={'remote' if b.remote else 'local'}")
    return 0


# ---------------------------------------------------------------- cli
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m wtdd.hue", description="Philips Hue lights agent (CLIP v2, local or cloud route)")
    sub = p.add_subparsers(dest="cmd", required=True)
    ra = sub.add_parser("remote-auth", help="cloud path: OAuth login -> tokens -> cloud link button -> app key (writes .env)")
    ra.add_argument("--port", type=int, default=8787); ra.add_argument("--timeout", type=float, default=180.0)
    ra.add_argument("--no-open", action="store_true", help="do not open a new browser tab; wait for the existing one")
    ra.set_defaults(fn=remote_auth)
    bu = sub.add_parser("burst", help="rate-limit probe: n quick brightness PUTs on one light, stop at first 429")
    bu.add_argument("light"); bu.add_argument("--n", type=int, default=15); bu.set_defaults(fn=burst)
    sub.add_parser("remote-refresh", help="refresh the cloud token with HUE_REMOTE_REFRESH").set_defaults(fn=remote_refresh)
    sub.add_parser("probe", help="discovery, tcp, config, key, light count; never throws before the table")
    sp = sub.add_parser("pair", help="link-button flow; writes HUE_APP_KEY into .env")
    sp.add_argument("--force", action="store_true", help="re-pair even if HUE_APP_KEY is set")
    sub.add_parser("lights", help="table: id, name, room, on, bri, color, reachable")
    sp = sub.add_parser("read", help="read one light")
    sp.add_argument("light", help="id, id prefix, or name")
    sp = sub.add_parser("set", help="set on/off, brightness, xy")
    sp.add_argument("light")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")
    sp.add_argument("--bri", type=float, help="0 to 100")
    sp.add_argument("--xy", help="x,y in CIE 1931, e.g. 0.675,0.322")
    sp = sub.add_parser("signal", help="native alternating red/blue signal")
    sp.add_argument("light")
    sp.add_argument("--seconds", type=float, default=10)
    sp = sub.add_parser("zone", help="set every light of a zone from zones.json")
    sp.add_argument("zone")
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")
    sp.add_argument("--bri", type=float)
    a = p.parse_args(argv)

    try:
        if hasattr(a, "fn"):            # remote-auth, remote-refresh, burst
            return a.fn(a)
        if a.cmd == "probe":
            return 0 if probe(config.maybe("HUE_BRIDGE_IP"), config.maybe("HUE_APP_KEY")) else 1
        b = HueBridge.from_env(key_required=False)
        if a.cmd == "pair":
            if b.key and not a.force:
                print("HUE_APP_KEY already set in .env; use --force to re-pair.")
                return 1
            return 0 if pair(b) else 1
        if a.cmd == "lights":
            return 0 if lights_table(b) else 1
        if a.cmd == "read":
            print(json.dumps(summary(b.read(resolve(b.lights(), a.light)["id"])), indent=1))
            return 0
        if a.cmd == "set":
            on = True if a.on else (False if a.off else None)
            if on is None and a.bri is None and a.xy is None:
                p.error("set: give --on/--off, --bri, or --xy")
            if a.bri is not None and not 0 <= a.bri <= 100:
                p.error("--bri must be 0 to 100")
            xy = tuple(float(v) for v in a.xy.split(",")) if a.xy else None
            if xy and len(xy) != 2:
                p.error("--xy must be x,y")
            print(json.dumps(b.set(resolve(b.lights(), a.light)["id"], on=on, bri=a.bri, xy=xy)))
            return 0
        if a.cmd == "signal":
            print(json.dumps(b.signal(resolve(b.lights(), a.light)["id"], a.seconds)))
            return 0
        print(json.dumps(set_zone(b, a.zone, a.on, a.bri)))   # zone: the last subcommand argparse accepts
        return 0
    except HueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
