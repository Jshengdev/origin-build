"""The livecheck CLI (goal 22). See wtdd/livecheck/__init__.py for what a verdict means.

  python -m wtdd.livecheck --step 01.3 [--ledger F] [--log F] [--timeout S] [--from-start] [--out F]   live: exit 0 / 1 / 2
  python -m wtdd.livecheck --step 01.3 --replay --ledger <fixture.jsonl> --log <fixture.log>              dry: the same verdicts
  python -m wtdd.livecheck --list                                    the table, one line per step; a WARN per item with no checked step
  python -m wtdd.livecheck --from-prs [--draft-out F]                open PRs' Needs-the-dog lines -> steps.draft.json (rows empty)
A usage error prints `FAIL usage · <message>` and exits 1: argparse's own exit 2 is UNSAFE's code. It writes no livecheck.json.
UNVERIFIED on the real dog: as the package says; this file only parses arguments and prints.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .. import livecheck as lc


def _list() -> int:
    steps = lc.load_steps()
    for s in steps.values():
        print(f"{s['item']}  {s['step']}  {'rows ' + str(len(s['rows'])) if s['rows'] else 'unchecked'}  {s['title']}")
    items = sorted({s["item"] for s in steps.values()})
    checked = [s for s in steps.values() if s["rows"]]
    lc.say(f"--list · {len(steps)} steps · {len(checked)} checked · {len(steps) - len(checked)} unchecked · {len(items)} items · {lc.STEPS}")
    for i in items:
        if not any(s["item"] == i for s in checked):
            lc.say(f"WARN item {i}: zero checked steps, none of its steps can PASS")
    return 0


def _from_prs(out: Path) -> int:
    try:
        prs = lc.open_prs()
    except (RuntimeError, OSError, ValueError) as e:
        print(f"FAIL --from-prs · {type(e).__name__}: {e} · no draft written")
        return 1
    if not prs:
        lc.say("WARN --from-prs · zero open PRs")
    for p in prs:
        if not lc.needs_the_dog_lines(p["body"]):
            lc.say(f"WARN #{p['number']} {p['title']}: no numbered Needs-the-dog lines")
    steps = lc.draft(prs)
    lc._write(out, {"note": "Drafted by python -m wtdd.livecheck --from-prs from every open PR's numbered Needs-the-dog lines; "
                            "rows are empty (unchecked, cannot PASS) until a person fills them and moves the entry into steps.json.",
                    "steps": steps})
    lc.say(f"--from-prs · {len(prs)} PRs · {len(steps)} steps · wrote {out}")
    print(out)
    return 0


def _usage(msg: str):
    print(f"FAIL usage · {msg} · python -m wtdd.livecheck --step <item>.<k> | --list | --from-prs (-h for every flag)", flush=True)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wtdd.livecheck", description="Grade one hardware step from the ledger and the API log.")
    ap.error = _usage   # argparse exits 2 on a usage error, UNSAFE's code: a typo is a FAIL (1)
    ap.add_argument("--step", help="<item>.<k>, a key of wtdd/livecheck/steps.json")
    ap.add_argument("--ledger", help="the ledger to tail (default: wtdd.ledger.LEDGER, WTDD_LEDGER honoured)")
    ap.add_argument("--log", help="the API's stderr log to tail (default: <repo>/logs/api.log)")
    ap.add_argument("--timeout", type=float, help="seconds from the start before a missing row FAILs (default: the step's timeout_s)")
    ap.add_argument("--replay", action="store_true", help="dry: read the fixture files whole, clocked by the rows' ts, no sleeping")
    ap.add_argument("--from-start", action="store_true", help="read both files from their first line, not their current end")
    ap.add_argument("--out", help="where the verdict JSON goes (default: <repo>/livecheck.json, served at GET /livecheck)")
    ap.add_argument("--list", action="store_true", help="print the table")
    ap.add_argument("--from-prs", action="store_true", help="draft steps from every open PR's Needs-the-dog lines through gh")
    ap.add_argument("--draft-out", default=str(lc.DRAFT), help="where --from-prs writes (default: wtdd/livecheck/steps.draft.json)")
    a = ap.parse_args(argv)
    if a.list:
        return _list()
    if a.from_prs:
        return _from_prs(Path(a.draft_out))
    if not a.step:
        ap.error("one of --step <item>.<k>, --list or --from-prs")
    v = lc.run(a.step, ledger=a.ledger, log=a.log, replay=a.replay, timeout_s=a.timeout, from_start=a.from_start, out=a.out)
    return lc.exit_code(v)


if __name__ == "__main__":
    sys.exit(main())
