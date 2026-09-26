"""Tuya WT1 Wi-Fi 2CH LED controller (warm white + cool white strip) over the LAN, protocol 3.5, via tinytuya.
python -m wtdd.tuya probe | status | on | off | dim <pct> | temp <pct> | fade [--start 5 --end 100 --seconds 4 --steps 16]

Every write is one ledger row (agent 'lights', app 'tuya'; tool lights.tuya_set or lights.tuya_fade) whose state_after
is a fresh read of the strip: the WT1 never acks a write, so the read-back is the only proof it landed.

Env: TUYA_DEVICE_ID, TUYA_DEVICE_IP, TUYA_LOCAL_KEY (required), TUYA_VERSION (default 3.5).
Facts (2026-09-13). `python -m tinytuya scan` finds device ebfd2e5d73c07e6f302clt at 10.66.10.44, product
hprgre8k9nlpjayk, uuid dfbb145970d51179, protocol 3.5 (no scan file is kept; this line is the record). Control needs
the device's LOCAL KEY, which only the Tuya IoT platform hands out: make a cloud project at iot.tuya.com, link the Smart
Life app to it by QR, then `python -m tinytuya wizard` prints the key. Datapoints for this "dj" light: 20 switch,
21 work_mode (always "white" on a CCT strip), 22 brightness 10..1000 (percent = (v - 10) / 990 * 100), 23 colour
temperature 0..1000 (percent = v / 10; 0 warm, 100 cool). Measured: about 0.4 s per set on the LAN; probe ok, on,
dim 30, temp 80 and a 17-step fade 5 to 100 over 4 s all read back (dps 20/22/23). Right after a burst of writes the
WT1 sometimes answers a partial dps, so fade re-reads once when brightness is missing.

strip(on, bri, temp) is the programmatic entry (commands.py, tools strip_set/strip_temp/identify): ONE write carrying
every requested field, then one read-back. On the CLI, dim and temp also switch the strip on (dim 0 switches it off),
so their rows carry `on` next to brightness_pct / temp_pct; the percent is clamped to 0..100 before it is written or
recorded. Brightness is encoded as the inverse of the decode above (30 -> dps 307, reads back 30.0).
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from typing import Any

import tinytuya

from .. import config
from ..ledger import log, step

AGENT, APP = "lights", "tuya"
DPS = {"switch": "20", "mode": "21", "bright": "22", "temp": "23"}


def device() -> tinytuya.BulbDevice:
    d = tinytuya.BulbDevice(config.get("TUYA_DEVICE_ID"), config.get("TUYA_DEVICE_IP"), config.get("TUYA_LOCAL_KEY"),
                            version=float(config.maybe("TUYA_VERSION") or 3.5))
    d.set_socketPersistent(True)
    d.set_socketTimeout(3)
    return d


def read(d: tinytuya.BulbDevice) -> dict[str, Any]:
    """Live status decoded to {on, mode, raw, brightness_pct?, temp_pct?}; the key names reach the UI and the chat."""
    st = d.status()
    if not isinstance(st, dict) or "dps" not in st:
        raise RuntimeError(f"tuya status failed: {st}")   # e.g. {'Error': 'Network Error: Unable to Connect', 'Err': '901'}
    dps = st["dps"]
    out = {"on": dps.get(DPS["switch"]), "mode": dps.get(DPS["mode"]), "raw": dps}
    if dps.get(DPS["bright"]) is not None:
        out["brightness_pct"] = round((int(dps[DPS["bright"]]) - 10) / 990 * 100, 1)
    if dps.get(DPS["temp"]) is not None:
        out["temp_pct"] = round(int(dps[DPS["temp"]]) / 1000 * 100, 1)
    return out


def strip(on: bool | None = None, bri: float | None = None, temp: float | None = None) -> dict[str, Any]:
    """ONE write carrying every requested field (switch, brightness, colour temperature), then one read-back; one
    lights.tuya_set row. With no field it is just the read."""
    dps: dict[str, Any] = {}
    if on is not None:
        dps[DPS["switch"]] = bool(on)
    if bri is not None:
        dps[DPS["bright"]] = int(round(10 + max(0.0, min(100.0, float(bri))) * 9.9))
    if temp is not None:
        dps[DPS["temp"]] = int(round(max(0.0, min(100.0, float(temp))) * 10))
    d = device()
    before = read(d)
    if not dps:
        return before
    args = {k: v for k, v in (("on", on), ("brightness_pct", bri), ("temp_pct", temp)) if v is not None}
    with step(AGENT, "lights.tuya_set", APP, args, before) as r:
        resp = d.set_multiple_values(dps, nowait=True)
        if isinstance(resp, dict) and resp.get("Error"):
            raise RuntimeError(f"tuya lights.tuya_set failed: {resp}")
        time.sleep(0.3)
        r["state_after"] = read(d)
        r["response_or_error"] = json.dumps(resp, default=str)[:300]
        return r["state_after"]


def cmd_probe(a: argparse.Namespace) -> int:
    """Never raises before the table: LAN scan, key check, live status."""
    want = config.maybe("TUYA_DEVICE_ID")
    found = tinytuya.deviceScan(False, 8)
    hit = next((v for v in found.values() if v.get("id") == want), None)
    key = config.maybe("TUYA_LOCAL_KEY")
    rows = [("scan", "ok" if hit else "FAIL", f"{len(found)} tuya device(s); " + (f"ours at {hit['ip']} v{hit['version']}" if hit else f"{want} not broadcasting")),
            ("TUYA_LOCAL_KEY", "ok" if key else "FAIL", "present" if key else "empty: Tuya IoT project, QR-link the Smart Life app, `python -m tinytuya wizard` (module docstring)")]
    if hit and key:
        try:
            st = read(device())
            rows.append(("status", "ok", json.dumps({k: v for k, v in st.items() if k != "raw"})))
        except Exception as e:  # noqa: BLE001  (the probe reports the failure as a row; never a fake state)
            rows.append(("status", "FAIL", f"{type(e).__name__}: {str(e)[:120]}"))
    w = max(len(l) for l, _, _ in rows)
    for l, s, n in rows:
        print(f"{l:<{w}}  {s:<5} {n}")
    return 0 if all(s == "ok" for _, s, _ in rows) else 1


def cmd_fade(a: argparse.Namespace) -> int:
    """Ramp brightness from --start to --end over --seconds in --steps steps; one lights.tuya_fade row; prints the
    read-back (tools/strip_fade.py reads it back from the ledger row)."""
    d = device()
    before = read(d)
    with step(AGENT, "lights.tuya_fade", APP, {"start": a.start, "end": a.end, "seconds": a.seconds, "steps": a.steps}, before) as r:
        d.turn_on(nowait=True)
        for i in range(a.steps + 1):
            pct = a.start + (a.end - a.start) * i / a.steps
            resp = d.set_brightness_percentage(pct, nowait=True)   # the WT1 does not ack writes; read-back proves them
            if isinstance(resp, dict) and resp.get("Error"):
                raise RuntimeError(f"tuya fade step {i} failed: {resp}")
            log(AGENT, f"fade step {i}/{a.steps}", pct=round(pct, 1))
            time.sleep(a.seconds / a.steps)
        time.sleep(0.5)
        after = read(d)
        if after.get("brightness_pct") is None:   # the WT1 sometimes answers a partial dps right after a burst
            time.sleep(0.5)
            after = read(d)
        r["state_after"] = after
        print(json.dumps(after))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m wtdd.tuya", description="Tuya WT1 LED controller, local protocol 3.5")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="scan for the device, key check, live status")
    sub.add_parser("status", help="read dps and decode on/brightness/temp")
    sub.add_parser("on", help="switch on, read back")
    sub.add_parser("off", help="switch off, read back")
    sub.add_parser("dim", help="brightness percent (switches on; 0 switches off)").add_argument("percent", type=float)
    sub.add_parser("temp", help="colour temperature percent (0 warm .. 100 cool; switches on)").add_argument("percent", type=float)
    s = sub.add_parser("fade", help="ramp brightness")
    s.add_argument("--start", type=float, default=5); s.add_argument("--end", type=float, default=100)
    s.add_argument("--seconds", type=float, default=4); s.add_argument("--steps", type=int, default=16)
    a = p.parse_args(argv)
    try:
        if a.cmd == "probe":
            return cmd_probe(a)
        if a.cmd == "fade":
            return cmd_fade(a)
        if a.cmd == "status":
            print(json.dumps(read(device()), indent=1))
        elif a.cmd in ("dim", "temp"):
            pct = max(0.0, min(100.0, a.percent))   # clamped here so the row args say what was written
            print(json.dumps(strip(on=pct > 0, bri=pct) if a.cmd == "dim" else strip(on=True, temp=pct)))
        else:
            print(json.dumps(strip(on=(a.cmd == "on"))))
        return 0
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
