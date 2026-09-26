"""memory.db (WTDD_MEMORY, default <repo>/memory.db): what the chat said, and the never-twice gate on what the dog posts.

Run: python -m wtdd.chat context [--n 20]   prints the four-part context the model gets each turn.

Tables. chat_messages: one row per chat.db message seen by watch/listen, idempotent on guid (INSERT OR IGNORE), tagged
with chat_guid so a read-only watch on another chat never leaks into the target group's context. posts: the never-twice
gate keyed on the trigger (the guid of the message that caused the post, or a CLI key). claim() INSERTs the trigger
BEFORE osascript runs; a primary-key conflict means posted or in flight, so the send does not happen. confirm() lands
the read-back guid on the claim row once the send is confirmed. posted_guids() is how the listener knows its own posts.

context(): the messages are the source of truth and the context is recomputed every turn from four parts: the last n
chat lines (UTC times; senders by first name when HOUSEMATES knows them, else the handle), the last 10 ledger rows
except llm.generate (what the dog did), the last posts row (what was reported), and <repo>/state.json if present.

Dropped on purpose (2026-09-13 fold): the kv table with its write-only last_rowid watermark (nothing ever read it;
watch and listen start at MAX(ROWID) or --since) and the report= half of "what was reported" (no step ever wrote
"report", so it was always None). An older memory.db that still has a kv table is fine: nothing touches it."""
from __future__ import annotations
import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..config import ROOT
from ..ledger import log, rows as ledger_rows
from .housemates import name
from .triggers import is_wake

MEMORY = Path(os.environ.get("WTDD_MEMORY", ROOT / "memory.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages(
  rowid INTEGER PRIMARY KEY, guid TEXT UNIQUE NOT NULL, sender TEXT NOT NULL,
  is_from_me INTEGER NOT NULL, text TEXT, attachments_json TEXT NOT NULL DEFAULT '[]',
  ts_utc TEXT NOT NULL, seen_at TEXT NOT NULL,
  chat_guid TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_chat_ts ON chat_messages(ts_utc DESC);
CREATE TABLE IF NOT EXISTS posts(
  trigger_guid TEXT PRIMARY KEY,
  claimed_at   TEXT NOT NULL,
  posted_guid  TEXT UNIQUE,
  confirmed_at TEXT);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Commits on a clean exit, never on an exception, always closes."""
    c = sqlite3.connect(MEMORY)
    c.executescript(SCHEMA)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def store(chat_guid: str, msgs: list[dict[str, Any]]) -> int:
    """Inserts rows from db.new_messages (tapbacks already dropped). Returns how many were new."""
    n = 0
    with connect() as c:
        for m in msgs:
            cur = c.execute(
                "INSERT OR IGNORE INTO chat_messages(rowid, guid, sender, is_from_me, text, attachments_json, ts_utc, seen_at, chat_guid)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (m["rowid"], m["guid"], m["sender"], m["is_from_me"], m["text"],
                 json.dumps(m["attachments"]), m["ts_utc"], _now(), chat_guid))
            n += cur.rowcount
    return n


def claim(trigger_guid: str) -> bool:
    """Step 1 of a post: insert BEFORE osascript. A primary-key conflict means posted or in flight: False, no send."""
    try:
        with connect() as c:
            c.execute("INSERT INTO posts(trigger_guid, claimed_at) VALUES (?, ?)", (trigger_guid, _now()))
    except sqlite3.IntegrityError:
        log("chat", "gate refused: already claimed", trigger=trigger_guid)
        return False
    return True


def confirm(trigger_guid: str, posted_guid: str) -> None:
    """Step 2 of a post: the read-back guid lands on the claim row."""
    with connect() as c:
        n = c.execute("UPDATE posts SET posted_guid = ?, confirmed_at = ? WHERE trigger_guid = ?",
                      (posted_guid, _now(), trigger_guid)).rowcount
    if n != 1:
        raise RuntimeError(f"confirm without a claim row: trigger={trigger_guid}")


def last_trigger(chat_guid: str, known: dict[str, str]) -> dict[str, Any] | None:
    """Newest stored message in this chat from a known housemate whose text contains a wake phrase."""
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM chat_messages WHERE chat_guid = ? AND is_from_me = 0 AND text IS NOT NULL"
            " ORDER BY rowid DESC LIMIT 50", (chat_guid,)).fetchall()
    for r in rows:
        if r["sender"] in known and is_wake(r["text"]) is not None:
            return dict(r)
    return None


def context(chat_guid: str, n: int = 20) -> str:
    """The four-part context the central agent composes every turn (see the module docstring)."""
    with connect() as c:
        msgs = c.execute("SELECT * FROM chat_messages WHERE chat_guid = ? ORDER BY rowid DESC LIMIT ?",
                         (chat_guid, n)).fetchall()[::-1]
        post = c.execute("SELECT * FROM posts ORDER BY claimed_at DESC, rowid DESC LIMIT 1").fetchone()
    lines = []
    for m in msgs:
        who = "dog" if m["is_from_me"] else name(m["sender"])
        body = m["text"] if m["text"] is not None else "[non-text]"
        photos = "".join(" [photo]" for _ in json.loads(m["attachments_json"]))
        lines.append(f"[{m['ts_utc'][11:16]}] {who}: {body}{photos}")

    did = [r for r in ledger_rows() if r.get("tool") != "llm.generate"][-10:]
    did_lines = [f"{r.get('step')} {r.get('tool')} args={json.dumps(r.get('args'), default=str)}"
                 f" after={json.dumps(r.get('state_after'), default=str)} ok={r.get('ok')}" for r in did]

    state_path = ROOT / "state.json"
    state = json.dumps(json.loads(state_path.read_text())) if state_path.exists() else "(no state.json)"

    return "\n\n".join([
        f"## chat (last {len(lines)}, times UTC)\n" + ("\n".join(lines) or "(none)"),
        f"## what the dog did (last {len(did_lines)} ledger rows)\n" + ("\n".join(did_lines) or "(none)"),
        "## what was reported\n" + f"post={json.dumps(dict(post), default=str) if post else None}",
        "## state\n" + state,
    ])


def posted_guids() -> set[str]:
    """Message guids the dog itself posted (confirmed), so its own words are never mistaken for a housemate's."""
    with connect() as c:
        return {r[0] for r in c.execute("SELECT posted_guid FROM posts WHERE posted_guid IS NOT NULL")}
