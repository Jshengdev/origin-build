"""The run in force (S11): a morning or a night run, the shift_id every row of it carries in args.shift_id.

  current()       the run's id: shift.json's shift_id, else env WTDD_SHIFT, else today's local date YYYY-MM-DD
  read()          {shift_id, source: file | WTDD_SHIFT | date}; GET /shift (a read, no row)
  start(name)     name "morning" or "night": shift.json = {"shift_id": "<YYYY-MM-DD>-<name>", "started": <iso>}, written
                  atomically (a temp file renamed over it) inside one shift.started row: args {name, shift_id} (the new
                  run's id, so the row opens its record), state_before and state_after the read() before and after (the
                  after is the read-back); returns the file. POST /shift {name}; the remote's two buttons.
The file is <repo>/shift.json, beside the ledger (WTDD_LEDGER moves both, so a test's scratch ledger never reads the live
run). A shift.json that does not parse or has no non-empty string shift_id is a ValueError naming the file, never a
fallback to the env or the date: fix or delete it. Any other name is a ValueError on a FAILED shift.started row and the
file is not touched. Every stamp reads the file at the point of use (decide.shift_id, oncall.shift_id,
localize.shift_id, plan, nogo, objects), so the API, the chat listener and the watch, separate processes, stamp the same
run from the row after a start. The run's date is the day it started: a night run crossing midnight keeps its id.
UNVERIFIED live: a start pressed while the listener and the watch run (wtdd/test_shift.py proves a separate process
stamps the file's id; the first live start confirms their next rows carry it). Offline: python -m unittest wtdd.test_shift
"""
from __future__ import annotations
import json
import os
import time

from . import config
from .ledger import LEDGER, step

FILE = LEDGER.with_name("shift.json")
NAMES = ("morning", "night")


def read() -> dict[str, str]:
    if FILE.exists():
        try:
            sid = json.loads(FILE.read_text())["shift_id"]
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"{FILE} is malformed ({type(e).__name__}: {e}); fix or delete it") from None
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"{FILE} is malformed: shift_id {sid!r} is not a non-empty string; fix or delete it")
        return {"shift_id": sid, "source": "file"}
    env = config.maybe("WTDD_SHIFT")
    return {"shift_id": env, "source": "WTDD_SHIFT"} if env else {"shift_id": time.strftime("%Y-%m-%d"), "source": "date"}


def current() -> str:
    return read()["shift_id"]


def start(name: str) -> dict[str, str]:
    with step("central", "shift.started", "wtdd", {"name": name}) as r:
        r["state_before"] = read()
        if name not in NAMES:
            raise ValueError(f"no run named {name!r}: start a morning or a night run")
        now = time.localtime()
        run = {"shift_id": time.strftime("%Y-%m-%d-", now) + name, "started": time.strftime("%Y-%m-%dT%H:%M:%S", now)}
        r["args"]["shift_id"] = run["shift_id"]
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(run) + "\n")
        os.replace(tmp, FILE)
        r["state_after"] = read()
        if r["state_after"] != {"shift_id": run["shift_id"], "source": "file"}:   # the run is started when the file says so
            raise RuntimeError(f"{FILE} read back {r['state_after']}, not {run['shift_id']}")
    return run
