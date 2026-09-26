"""Env loading. Reads <repo>/.env once into os.environ (setdefault: a real environment variable wins over the file).
get(key) returns the value or raises RuntimeError when it is missing or empty (fail loud, CLAUDE.md section 2);
maybe(key) returns None instead. Line format: KEY=value, surrounding quotes stripped, `#` starts a comment only after
a space (keys and values may contain #). ROOT is the repo root; ledger.jsonl, memory.db and ui/ hang off it.
"""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
