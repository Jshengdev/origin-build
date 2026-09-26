"""python -m wtdd.dog <command>. One asyncio loop per invocation; each live command opens one connection,
acts, writes ledger rows, and closes. `commands`, `check` and `probe` never touch the dog.

  commands            every SPORT_CMD name and id from the installed driver, allow/deny
  check [route]       static: allowlist vs SPORT_CMD, every SPORT_CMD[...] literal in this package, every route file (no dog)
  probe [--no-scan]   env, driver, discovery scan, key, signaling port; prints what is blocked
  state [--seconds]   one LF_SPORT_MOD_STATE message and the measured publish rate
  cmd <Name>          one SPORT_CMD by name (motion mode normal first)
  move --x --y --z --seconds     velocity at 10 Hz, then StopMove
  avoid on|off        obstacle avoidance with read-back
  route <file|name>   a JSON route (path, or a name under wtdd/dog/routes/) with avoidance on
  frame [--out]       the newest camera frame as JPEG (default ~/Pictures/wtdd/frame.jpg)
Without a dog on the network only commands, check, probe and --help can be verified.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

from unitree_webrtc_connect import SPORT_CMD

from ..ledger import step
from . import body as B


def cmd_commands(a: argparse.Namespace) -> int:
    for name, api_id in sorted(SPORT_CMD.items(), key=lambda kv: (kv[1], kv[0])):
        print(f"{api_id}  {name:<18} {'allow' if name in B.ALLOW else 'deny'}")
    print(f"{len(SPORT_CMD)} SPORT_CMD entries, {len(B.ALLOW)} allowed, {len(SPORT_CMD) - len(B.ALLOW)} denied")
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    """Static: allowlist vs SPORT_CMD (asserted when body imports), every SPORT_CMD[...] literal in this
    package against the installed driver, every route file."""
    bad = 0
    print(f"allowlist: {len(B.ALLOW)} names, all in SPORT_CMD (asserted at import)")
    here = Path(__file__).parent
    refs: set[str] = set()
    for src in (here / "body.py", here / "__main__.py"):
        refs |= set(re.findall(r'SPORT_CMD\["(\w+)"\]', src.read_text()))
    missing = sorted(refs - SPORT_CMD.keys())
    print(f"SPORT_CMD literals in code: {sorted(refs)} missing={missing}")
    bad += len(missing)
    files = [Path(a.route)] if a.route else sorted(B.ROUTES.glob("*.json"))
    for f in files:
        try:
            plan = B.validate_route(json.loads(f.read_text()))
            print(f"{f.name}: ok, {len(plan)} steps")
            for i, d in enumerate(plan):
                print(f"  {i + 1:>2}. {d}")
        except (ValueError, KeyError, TypeError, OSError) as e:
            print(f"{f.name}: FAIL {type(e).__name__}: {e}")
            bad += 1
    print("check: " + ("ok" if not bad else f"{bad} problem(s)"))
    return 0 if not bad else 1


def cmd_probe(a: argparse.Namespace) -> int:
    rows, reachable = B.probe(scan=not a.no_scan)
    w = max(len(c) for c, _, _ in rows)
    print()
    for c, s, d in rows:
        print(f"  {c:<{w}}  {s:<4}  {d}")
    print(f"\n  dog reachable: {'yes' if reachable else 'NO'}")
    for c, s, d in rows:
        if s == "fail":
            print(f"  blocked by {c}: {d}")
    return 0 if reachable else 1


async def cmd_state(a: argparse.Namespace) -> int:
    async with B.Body() as body:
        await asyncio.sleep(a.seconds)
        with step("dog", "dog.state", "unitree", {"seconds": a.seconds}) as r:
            s = body.state()
            if s is None:
                raise RuntimeError(f"no LF_SPORT_MOD_STATE message in {a.seconds}s")
            r["response_or_error"] = body.raw()
            r["state_after"] = s
        print(json.dumps(body.raw(), indent=1))
        print(f"[wtdd:dog] state samples={s['n']} hz={s['hz']} mode={s['mode']} position={s['position']}")
    return 0


async def cmd_cmd(a: argparse.Namespace) -> int:
    parameter = json.loads(a.parameter) if a.parameter else None
    async with B.Body() as body:
        code = await body.cmd(a.name, parameter)
        print(f"[wtdd:dog] {a.name} code={code} state_after={json.dumps(body.state())}")
    return 0


async def cmd_move(a: argparse.Namespace) -> int:
    async with B.Body() as body:
        res = await body.move(a.x, a.y, a.z, a.seconds)
        print(f"[wtdd:dog] move {res} state_after={json.dumps(body.state())}")
    return 0


async def cmd_avoid(a: argparse.Namespace) -> int:
    async with B.Body() as body:
        enabled = await body.avoid(a.state == "on")
        print(f"[wtdd:dog] avoid enable={enabled}")
    return 0


async def cmd_route(a: argparse.Namespace) -> int:
    path = Path(a.file)
    if not path.exists() and (B.ROUTES / f"{a.file}.json").exists():
        path = B.ROUTES / f"{a.file}.json"
    steps = json.loads(path.read_text())
    B.validate_route(steps)  # a bad route fails here, before any connection
    async with B.Body() as body:
        done = await body.route(steps, name=path.stem)
        for d in done:
            print(f"[wtdd:dog] {d['step']:>2}. {d['desc']}: {json.dumps(d['result'])[:120]}")
        print(f"[wtdd:dog] route {path.stem} done {len(done)}/{len(steps)}")
    return 0


async def cmd_frame(a: argparse.Namespace) -> int:
    async with B.Body() as body:
        data = await body.frame(a.out)
        print(f"[wtdd:dog] wrote {a.out} bytes={len(data)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="[%(name)s] %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="python -m wtdd.dog",
                                description="The body: one Unitree Go2 over one WebRTC connection. "
                                            "Every dog call writes a ledger row with the state read back.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("commands", help="print every SPORT_CMD name and id from the installed driver")
    s = sub.add_parser("check", help="static check: allowlist, SPORT_CMD literals, route files (no dog)")
    s.add_argument("route", nargs="?", help="one route file to validate (default: wtdd/dog/routes/*.json)")
    s = sub.add_parser("probe", help="env, discovery scan, key, signaling port; prints what is blocked")
    s.add_argument("--no-scan", action="store_true", help="skip the 2 s multicast discovery")
    s = sub.add_parser("state", help="print one LF_SPORT_MOD_STATE message and the measured rate")
    s.add_argument("--seconds", type=float, default=3.0)
    s = sub.add_parser("cmd", help="one SPORT_CMD by name (motion mode normal first)")
    s.add_argument("name")
    s.add_argument("--parameter", help="JSON parameter, e.g. '{\"data\": true}'")
    s = sub.add_parser("move", help="velocity at 10 Hz for --seconds, then StopMove")
    s.add_argument("--x", type=float, default=0.0, help="forward m/s")
    s.add_argument("--y", type=float, default=0.0, help="left m/s")
    s.add_argument("--z", type=float, default=0.0, help="yaw rad/s")
    s.add_argument("--seconds", type=float, default=1.0)
    s = sub.add_parser("avoid", help="obstacle avoidance on|off with read-back")
    s.add_argument("state", choices=["on", "off"])
    s = sub.add_parser("route", help="run a JSON route with obstacle avoidance on")
    s.add_argument("file", help="path or a name under wtdd/dog/routes/")
    s = sub.add_parser("frame", help="write the newest camera frame as JPEG")
    s.add_argument("--out", default=str(B.PICTURES / "frame.jpg"))
    a = p.parse_args(argv)

    sync = {"commands": cmd_commands, "check": cmd_check, "probe": cmd_probe}
    live = {"state": cmd_state, "cmd": cmd_cmd, "move": cmd_move, "avoid": cmd_avoid, "route": cmd_route,
            "frame": cmd_frame}
    if a.command in sync:
        return sync[a.command](a)
    return asyncio.run(live[a.command](a))


if __name__ == "__main__":
    sys.exit(main())
