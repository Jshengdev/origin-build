"""The CLI over the tool registry (wtdd/tools): one subcommand per tool file, args as key=value.

  python -m wtdd list                      every tool, its first doc line, its args with defaults
  python -m wtdd lights_dim percent=30
  python -m wtdd zone_set zone=b on=false
  python -m wtdd walk_path dry=true
  python -m wtdd ask "make the living room warm and dim, then tell me what you did"   (the model picks the tools)
Values parse as true/false, int, float, else str. Stdout is the tool's JSON result; exit 0 on success, 1 when the tool
raised (error class and message on stderr; the ledger row already has it), 2 on an argument that is not key=value.
The remote (ui/index.html) prints the equivalent `python -m wtdd <name> k=v` line under every button.
Run everything inside .venv (`source .venv/bin/activate`): the device SDKs and the mcp package live there, and
`python -m wtdd.dog probe` fails its venv check from any other interpreter.
"""
from __future__ import annotations
import json
import sys

from . import tools


def _parse(v: str):
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(v) if v.lstrip("-").isdigit() else float(v)
    except ValueError:
        return v


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "list"):
        for t in tools.describe():
            args = ", ".join(f"{k}={v.get('default')!r}" for k, v in t["args"].items())
            print(f"{t['name']:14s} {t['doc'].splitlines()[0]}" + (f"\n{'':14s} args: {args}" if args else ""))
        return 0
    if argv[0] == "ask":
        from .agent import ask
        out = ask(" ".join(argv[1:]))
        print(out["text"])
        print(f"[{len(out['calls'])} tool call(s), {out['usage'].get('total_tokens', '?')} tokens]", file=sys.stderr)
        return 0
    name, args = argv[0], {}
    for item in argv[1:]:
        if "=" not in item:
            print(f"args are key=value (got {item!r})", file=sys.stderr)
            return 2
        k, v = item.split("=", 1)
        args[k] = _parse(v)
    try:
        print(json.dumps(tools.call(name, **args), default=str, indent=1))
        return 0
    except Exception as e:  # noqa: BLE001  (the tool's ledger row has the failure; the CLI reports it and exits non-zero)
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
