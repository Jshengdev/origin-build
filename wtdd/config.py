"""Env loading. Reads <repo>/.env once into os.environ (setdefault: a real environment variable wins over the file).
get(key) returns the value or raises RuntimeError when it is missing or empty (fail loud, CLAUDE.md section 2);
maybe(key) returns None instead. Line format: KEY=value, surrounding quotes stripped, `#` starts a comment only after
a space (keys and values may contain #). ROOT is the repo root; ledger.jsonl, memory.db and ui/ hang off it.
API is the local API's address, http://127.0.0.1:<WTDD_API_PORT, default 7788>, read once from the process env at import
(as commands.py read it; .env is not consulted): python -m wtdd.api serves on its port and every caller uses it.
"""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = f"http://127.0.0.1:{os.environ.get('WTDD_API_PORT', '7788')}"
_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.split(" #", 1)[0].strip().strip('"').strip("'"))
    _loaded = True


def get(key: str, default: str | None = None) -> str:
    _load()
    v = os.environ.get(key, default)
    if v is None or v == "":
        raise RuntimeError(f"[wtdd:config] {key} is required. Set it in {ROOT / '.env'} (see .env.example).")
    return v


def maybe(key: str) -> str | None:
    _load()
    return os.environ.get(key) or None


def scout_zones() -> bool:
    """WTDD_SCOUT_ZONES, the scout's own switch (wtdd/dog/scout_zones.py): unset, empty or 1 = on, the scout as it was
    before the knob; 0 = off: it still receives 07's objects (their pins and names stay) but asks no model, writes no auto
    zone and no zone.* row. Its own key so that turning zones off never moves WTDD_DECIDE_THRESHOLD, which the chat
    round's decide shares. Read at each use; any other value is a ValueError (fail loud, never a guess)."""
    v = (maybe("WTDD_SCOUT_ZONES") or "1").strip()
    if v not in ("0", "1"):
        raise ValueError(f"WTDD_SCOUT_ZONES={v!r} is not 0 (off) or 1 (on)")
    return v == "1"
