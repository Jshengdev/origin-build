"""TEST ONLY. A local HTTPS fake of the Hue bridge (self-signed cert, like the real one) plus the checks that run
against it: request shaping, the read-back rule, bad key, rate limit, the pair poll, zones, and the signal refusal.
Nothing here touches a real bridge. Run: python -m wtdd.hue.test_stub
"""
from __future__ import annotations
import contextlib
import io
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="wtdd-hue-"))
os.environ["WTDD_LEDGER"] = str(TMP / "ledger.jsonl")  # before importing the ledger: never the real file
os.environ["HUE_REMOTE_TOKEN"] = ""   # the stub is a local bridge; never route these checks through the cloud

from .. import ledger  # noqa: E402
from . import __main__ as cli  # noqa: E402
from .api import HueBridge, HueError  # noqa: E402

KEY = "stub-app-key-0123456789"
L_COLOR = "11111111-1111-1111-1111-111111111111"
L_WHITE = "22222222-2222-2222-2222-222222222222"
D_COLOR, D_WHITE = "aaaaaaaa-0000-0000-0000-000000000001", "aaaaaaaa-0000-0000-0000-000000000002"


STATE = {
    "lights": {
        L_COLOR: {"id": L_COLOR, "type": "light", "owner": {"rid": D_COLOR, "rtype": "device"},
                  "metadata": {"name": "Hall lamp", "archetype": "table_shade"}, "on": {"on": False},
                  "dimming": {"brightness": 20.0, "min_dim_level": 0.2}, "color": {"xy": {"x": 0.3, "y": 0.3}, "gamut_type": "C"},
                  "signaling": {"signal_values": ["no_signal", "on_off", "on_off_color", "alternating"]}},
        L_WHITE: {"id": L_WHITE, "type": "light", "owner": {"rid": D_WHITE, "rtype": "device"},
                  "metadata": {"name": "Desk", "archetype": "classic_bulb"}, "on": {"on": True},
                  "dimming": {"brightness": 100.0, "min_dim_level": 1.0},
                  "signaling": {"signal_values": ["no_signal", "on_off"]}},
    },
    "rooms": [{"id": "r1", "type": "room", "metadata": {"name": "Hallway", "archetype": "hallway"},
               "children": [{"rid": D_COLOR, "rtype": "device"}], "services": [{"rid": "g1", "rtype": "grouped_light"}]},
              {"id": "r2", "type": "room", "metadata": {"name": "Office", "archetype": "office"},
               "children": [{"rid": D_WHITE, "rtype": "device"}], "services": [{"rid": "g2", "rtype": "grouped_light"}]}],
    "zigbee": [{"id": "z1", "type": "zigbee_connectivity", "owner": {"rid": D_COLOR, "rtype": "device"}, "status": "connected"},
               {"id": "z2", "type": "zigbee_connectivity", "owner": {"rid": D_WHITE, "rtype": "device"}, "status": "disconnected"}],
    "presses_needed": 2, "accept_signal": True, "ignore_brightness": False, "rate_limit": False,
    "puts": [],
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"null")

    def _authed(self) -> bool:
        if self.headers.get("hue-application-key") == KEY:
            return True
        self._send(401, {"errors": [{"description": "unauthorized user"}], "data": []})
        return False

    def do_GET(self):
        if self.path == "/api/0/config":
            return self._send(200, {"name": "wtdd-stub", "swversion": "1968096020", "apiversion": "1.68.0", "bridgeid": "STUBBRIDGE"})
        if not self.path.startswith("/clip/v2/resource/"):
            return self._send(404, {"errors": [{"description": "no route"}]})
        if not self._authed():
            return None
        parts = self.path[len("/clip/v2/resource/"):].split("/")
        if parts[0] == "light":
            if len(parts) == 1:
                return self._send(200, {"errors": [], "data": list(STATE["lights"].values())})
            l = STATE["lights"].get(parts[1])
            return self._send(200, {"errors": [], "data": [l]}) if l else self._send(404, {"errors": [{"description": "not found"}], "data": []})
        if parts[0] == "room":
            return self._send(200, {"errors": [], "data": STATE["rooms"]})
        if parts[0] == "zigbee_connectivity":
            return self._send(200, {"errors": [], "data": STATE["zigbee"]})
        return self._send(404, {"errors": [{"description": "no route"}], "data": []})

    def do_POST(self):
        if self.path != "/api":
            return self._send(404, {"errors": [{"description": "no route"}]})
        body = self._body()
        assert body.get("devicetype") and body.get("generateclientkey") is True, body
        if STATE["presses_needed"] > 0:
            STATE["presses_needed"] -= 1
            return self._send(200, [{"error": {"type": 101, "address": "", "description": "link button not pressed"}}])
        return self._send(200, [{"success": {"username": KEY, "clientkey": "00112233445566778899AABBCCDDEEFF"}}])

    def do_PUT(self):
        if not self._authed():
            return None
        parts = self.path[len("/clip/v2/resource/"):].split("/")
        if parts[0] != "light" or len(parts) != 2 or parts[1] not in STATE["lights"]:
            return self._send(404, {"errors": [{"description": "not found"}], "data": []})
        if STATE["rate_limit"]:
            return self._send(429, {"errors": [{"description": "too many requests"}], "data": []})
        body = self._body()
        STATE["puts"].append((parts[1], body))
        l = STATE["lights"][parts[1]]
        for k, v in body.items():
            if k == "on":
                l["on"] = {"on": bool(v["on"])}
            elif k == "dimming":
                if not STATE["ignore_brightness"]:
                    l["dimming"]["brightness"] = max(float(l["dimming"]["min_dim_level"]), float(v["brightness"]))
            elif k == "color":
                if "color" not in l:
                    return self._send(400, {"errors": [{"description": "invalid value, color, for parameter"}], "data": []})
                l["color"]["xy"] = {"x": float(v["xy"]["x"]), "y": float(v["xy"]["y"])}
            elif k == "signaling":
                if not STATE["accept_signal"]:
                    return self._send(400, {"errors": [{"description": "signaling not accepted"}], "data": []})
                colors = v.get("colors")
                if not isinstance(colors, list) or not all("xy" in c for c in colors) or v["signal"] not in l["signaling"]["signal_values"]:
                    return self._send(400, {"errors": [{"description": f"invalid value, {list(v)}, for parameter, signaling"}], "data": []})
                l["signaling"]["status"] = {"signal": v["signal"], "estimated_end": "2026-09-13T00:00:00Z"}
            else:
                return self._send(400, {"errors": [{"description": f"invalid value, {k}, for parameter"}], "data": []})
        return self._send(200, {"errors": [], "data": [{"rid": parts[1], "rtype": "light"}]})


def serve() -> str:
    """Starts the HTTPS stub on a free port with a throwaway self-signed cert; returns host:port."""
    crt, key = TMP / "stub.crt", TMP / "stub.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(crt),
                    "-subj", "/CN=127.0.0.1", "-days", "1"], check=True, capture_output=True)
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(crt), str(key))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"127.0.0.1:{srv.server_address[1]}"


def expect_error(fn, *needle: str, typ=HueError) -> Exception:
    try:
        fn()
    except typ as e:
        for s in needle:
            assert s in str(e), (s, str(e))
        return e
    raise AssertionError(f"expected {typ.__name__} containing {needle}")


def main() -> int:
    host = serve()
    b = HueBridge(host, KEY, timeout=5)
    n = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal n
        n += 1
        assert cond, f"{name}: {detail}"
        print(f"  pass {n:02d} {name}")

    # 1. probe against the stub: every line ok (discovery is the real meethue.com; skip it if offline by not asserting it)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ok = cli.probe(host, KEY)
    lines = out.getvalue()
    check("probe prints a table with every check", all(s in lines for s in ("tcp ", "/api/0/config", "HUE_APP_KEY", "/clip/v2/resource/light")), lines)
    check("probe config and light lines ok", "name=wtdd-stub" in lines and "n=2:" in lines, lines)

    # 2. pair: two 'link button not pressed' rows, then success; .env gets the key; key is never printed
    env = TMP / ".env"
    env.write_text("HUE_BRIDGE_IP=x\nHUE_APP_KEY=\nOTHER=1\n")
    b2 = HueBridge(host, None)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        paired = cli.pair(b2, env_path=env, poll_s=0.05, max_s=5)
    check("pair returns True after the button", paired)
    check("pair wrote HUE_APP_KEY into .env in place", env.read_text() == f"HUE_BRIDGE_IP=x\nHUE_APP_KEY={KEY}\nOTHER=1\n", env.read_text())
    check("pair never prints the key", KEY not in out.getvalue() and "PRESS THE ROUND LINK BUTTON" in out.getvalue(), out.getvalue())
    rows = [r for r in ledger.rows(10) if r["tool"] == "lights.pair"]
    check("pair ledger: 2 failed attempts then 1 ok", [r["ok"] for r in rows] == [False, False, True], str([r["ok"] for r in rows]))
    check("pair ledger never holds the key", KEY not in json.dumps(rows))
    fresh = TMP / "fresh.env"
    cli.write_env_key(fresh, "HUE_APP_KEY", "k")
    check("pair on a missing .env copies .env.example", "HUE_APP_KEY=k\n" in fresh.read_text() and "HUE_BRIDGE_IP=" in fresh.read_text(), fresh.read_text())

    # 3. lights table: room from room.children, reachable from zigbee_connectivity
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        table = cli.lights_table(b)
    by = {t["name"]: t for t in table}
    check("lights table joins room and reachability", by["Hall lamp"]["room"] == "Hallway" and by["Hall lamp"]["reachable"] == "connected"
          and by["Desk"]["room"] == "Office" and by["Desk"]["reachable"] == "disconnected" and by["Hall lamp"]["color"] and not by["Desk"]["color"], str(table))
    check("resolve by name, prefix, and full id", all(cli.resolve(b.lights(), ref)["id"] == L_COLOR for ref in ("hall lamp", L_COLOR[:8], L_COLOR)))
    expect_error(lambda: cli.resolve(b.lights(), "nope"), "matches 0 lights")

    # 4. set: PUT body shape, then GET read-back lands in state_after and match is true
    after = b.set(L_COLOR, on=True, bri=50, xy=(0.675, 0.322))
    rid, body = STATE["puts"][-1]
    check("set PUT body is CLIP v2 shaped", rid == L_COLOR and body == {"on": {"on": True}, "dimming": {"brightness": 50}, "color": {"xy": {"x": 0.675, "y": 0.322}}}, str(body))
    row = ledger.rows(1)[0]
    check("set row: ok, state_before off, state_after on@50 red, match", row["tool"] == "lights.set" and row["ok"] and row["match"]
          and row["state_before"]["on"] is False and row["state_after"] == {"on": True, "brightness": 50.0, "xy": [0.675, 0.322], "signal": None}
          and after == row["state_after"] and row["latency_ms"] >= 0, json.dumps(row))
    check("set row response_or_error is the raw PUT response", json.loads(row["response_or_error"]) == {"errors": [], "data": [{"rid": L_COLOR, "rtype": "light"}]}, row["response_or_error"])
    e = expect_error(lambda: b.set(L_COLOR), "nothing to set", typ=ValueError)
    check("set requires on, bri, or xy", isinstance(e, ValueError))

    # 5. the read-back rule: a dropped brightness write must fail the step (never marked done)
    STATE["ignore_brightness"] = True
    expect_error(lambda: b.set(L_COLOR, bri=90), "read-back mismatch")
    row = ledger.rows(1)[0]
    check("dropped write: row ok=False, match False, state_after recorded", row["ok"] is False and row["match"] is False
          and row["state_after"]["brightness"] == 50.0 and "read-back mismatch" in row["response_or_error"], json.dumps(row))
    STATE["ignore_brightness"] = False

    # 6. bad key and rate limit are recorded on the exact step and raised, no retry
    puts_before = len(STATE["puts"])
    expect_error(lambda: HueBridge(host, "wrong").read(L_COLOR), "bad key (HTTP 401)")
    check("bad key row", ledger.rows(1)[0]["tool"] == "lights.read" and ledger.rows(1)[0]["ok"] is False and "bad key" in ledger.rows(1)[0]["response_or_error"])
    expect_error(lambda: HueBridge(host, None).read(L_COLOR), "HUE_APP_KEY is empty")
    STATE["rate_limit"] = True
    expect_error(lambda: b.set(L_COLOR, on=False), "rate limited (HTTP 429)")
    STATE["rate_limit"] = False
    check("429: exactly one PUT attempted, row ok=False", len(STATE["puts"]) == puts_before and ledger.rows(1)[0]["ok"] is False and "429" in ledger.rows(1)[0]["response_or_error"])
    expect_error(lambda: HueBridge("127.0.0.1:1", KEY, timeout=1).read(L_COLOR), "unreachable 127.0.0.1:1")
    check("connection error row", ledger.rows(1)[0]["ok"] is False and "unreachable" in ledger.rows(1)[0]["response_or_error"])

    # 7. signal: exactly one PUT in the CLIP v2 shape (colors: [{xy}]), one row with the read-back
    STATE["puts"].clear()
    after = b.signal(L_COLOR, 8)
    check("signal PUT body: alternating, duration ms, colors [{xy}]", len(STATE["puts"]) == 1 and STATE["puts"][0][1] == {"signaling": {"signal": "alternating", "duration": 8000,
          "colors": [{"xy": {"x": 0.675, "y": 0.322}}, {"xy": {"x": 0.167, "y": 0.04}}]}} and after["signal"] == "alternating", str(STATE["puts"]))
    check("signal row ok with read-back", ledger.rows(1)[0]["tool"] == "lights.signal" and ledger.rows(1)[0]["ok"] and ledger.rows(1)[0]["state_after"]["signal"] == "alternating")
    # the bridge rejects signaling: one failed row, raised, no second shape tried
    STATE["lights"][L_COLOR]["signaling"].pop("status")
    STATE["accept_signal"] = False
    STATE["puts"].clear()
    expect_error(lambda: b.signal(L_COLOR, 5), "signaling not accepted")
    check("signal rejected by the bridge: one PUT, one failed row, raised (no shape guessing)",
          len(STATE["puts"]) == 1 and ledger.rows(1)[0]["tool"] == "lights.signal" and ledger.rows(1)[0]["ok"] is False)
    STATE["accept_signal"] = True
    STATE["puts"].clear()
    expect_error(lambda: b.signal(L_WHITE, 5), "does not support signal alternating")
    check("signal on a white bulb: refused after one read, zero PUTs", len(STATE["puts"]) == 0 and ledger.rows(1)[0]["tool"] == "lights.read")
    STATE["rate_limit"] = True
    expect_error(lambda: b.signal(L_COLOR, 5), "rate limited (HTTP 429)")
    STATE["rate_limit"] = False
    check("signal under 429: raised, no retry", len(STATE["puts"]) == 0
          and ledger.rows(1)[0]["tool"] == "lights.signal" and ledger.rows(1)[0]["ok"] is False)

    # 8. zone: empty zone refuses; unknown id refuses; filled zone sets each light with per-light rows
    zj = TMP / "zones.json"
    zj.write_text(json.dumps({"a": {"lights": []}}))
    expect_error(lambda: cli.set_zone(b, "a", True, 30, path=zj), "no lights", "Johnny must fill")
    expect_error(lambda: cli.set_zone(b, "zz", True, 30, path=zj), "zone 'zz' not in")
    zj.write_text(json.dumps({"a": {"lights": ["deadbeef-0000-0000-0000-000000000000"]}}))
    expect_error(lambda: cli.set_zone(b, "a", True, 30, path=zj), "bridge does not have")
    zj.write_text(json.dumps({"a": {"lights": [L_COLOR, L_WHITE]}}))
    STATE["puts"].clear()
    after = cli.set_zone(b, "a", True, 30, path=zj)
    rows = ledger.rows(3)
    check("zone: one PUT per light, one lights.set row each, one set_zone row on top",
          [p[0] for p in STATE["puts"]] == [L_COLOR, L_WHITE] and [r["tool"] for r in rows] == ["lights.set", "lights.set", "lights.set_zone"]
          and rows[2]["ok"] and rows[2]["state_after"] == after and after[L_WHITE]["brightness"] == 30.0, json.dumps(rows[2]))

    # 9. the shipped zones.json (filled 2026-09-13): corridor zones a/b/c whose union is the 4-light living room
    z = cli.load_zones()
    check("shipped zones.json: a/b/c corridor zones whose union is the 4-light living room",
          {"a", "b", "c", "living room"} <= set(z) and len(z["living room"]["lights"]) == 4
          and set(z["living room"]["lights"]) == {i for k in "abc" for i in z[k]["lights"]})

    # 10. the argparse entry point end to end, pointed at the stub through the same env vars config.py reads
    os.environ["HUE_BRIDGE_IP"], os.environ["HUE_APP_KEY"] = host, KEY
    STATE["lights"][L_COLOR]["signaling"].pop("status", None)

    def run_cli(*argv: str) -> tuple[int, str, str]:
        o, e = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
            code = cli.main(list(argv))
        return code, o.getvalue(), e.getvalue()

    code, out, _ = run_cli("probe")
    check("cli probe exit 0 against the stub", code == 0 and "BLOCKED" not in out, out)
    code, out, _ = run_cli("lights")
    check("cli lights prints both rows", code == 0 and "Hall lamp" in out and "Desk" in out and "disconnected" in out, out)
    code, out, _ = run_cli("read", "desk")
    check("cli read by name", code == 0 and json.loads(out)["brightness"] == 30.0, out)
    code, out, _ = run_cli("set", "desk", "--off", "--bri", "40")
    check("cli set --off --bri 40 prints the read-back", code == 0 and json.loads(out) == {"on": False, "brightness": 40.0, "xy": None, "signal": None}, out)
    code, out, _ = run_cli("set", L_COLOR[:8], "--xy", "0.2,0.7")
    check("cli set --xy by id prefix", code == 0 and json.loads(out)["xy"] == [0.2, 0.7], out)
    code, out, _ = run_cli("signal", "hall lamp", "--seconds", "3")
    check("cli signal", code == 0 and json.loads(out)["signal"] == "alternating" and STATE["puts"][-1][1]["signaling"]["duration"] == 3000, out)
    code, out, err = run_cli("zone", "a", "--on")
    check("cli zone with the shipped ids fails loud on a bridge that lacks them", code == 1 and "bridge does not have" in err, err)
    code, out, err = run_cli("pair")
    check("cli pair refuses when a key is set (use --force)", code == 1 and "--force" in out, out)
    code, out, err = run_cli("read", "ghost")
    check("cli read of an unknown light fails loud", code == 1 and "matches 0 lights" in err, err)

    print(f"ok: {n} checks passed against the stub at https://{host}; ledger rows in {ledger.LEDGER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
