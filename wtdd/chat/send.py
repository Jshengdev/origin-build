"""The mouth: osascript sends to the ONE allowed group, each confirmed by reading the dog's own from-me row back.

wtdd.chat.__main__.post is the caller: it runs the target gate and the never-twice claim first, each as its own ledger
row (chat.gate, chat.claim), then wraps the send in a chat.post row. send_text and send_file ALSO call gate() as their
first statement, so a direct caller (a future tool, the agent loop, a REPL) can never reach osascript past the gate;
the second check is one read-only chat.db lookup. No retries, ever: real people are on the other end, and an
unconfirmed send raises instead of sending again.

The gate (gate()): guid == WTDD_CHAT_GUID AND chat.db's display_name for that guid == TARGET_NAME. TARGET_NAME is
WTDD_CHAT_NAME from .env, default "wtdd test" (the build-night test group). On 2026-09-13 Johnny set it to "THE CASTLE",
the real housemates group (8 members), on purpose; test_chat.Gate pins that choice. Both checks must hold, so a guid
pointed at any other chat, or a renamed chat, is refused with a PermissionError before anything is claimed or sent.

Verified on this Mac (2026-09-13): AppleScript `chat id "<guid>"` resolves the chat.db guid directly (Automation
permission for Messages is granted to the terminal). A file send is `POSIX file "<path>" as alias` and the file has to
sit under ~/Pictures/wtdd (sandboxed Messages.app can read there), so stage() copies it in first; a caption goes in the
same script after `delay 3` and is confirmed as a second from-me row above the file row. Text and guid are escaped for
AppleScript string literals (backslash first, then double quote). osascript gets 30 s; rc != 0 raises."""
from __future__ import annotations
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import config
from ..ledger import log
from . import db

TARGET_NAME = config.maybe("WTDD_CHAT_NAME") or "wtdd test"   # wtdd: the ONE group this process may post to; guid AND name must match
PICTURES = Path("~/Pictures/wtdd").expanduser()
CONFIRM_S = 10.0


def gate(guid: str) -> None:
    """Two checks, both must hold: guid == WTDD_CHAT_GUID, and that chat is named exactly TARGET_NAME in chat.db."""
    want = config.get("WTDD_CHAT_GUID")
    if guid != want:
        raise PermissionError(f"refused: {guid} is not WTDD_CHAT_GUID")
    name = db.chat_name(guid)
    if name != TARGET_NAME:
        raise PermissionError(f"refused: {guid} is named {name!r}, not {TARGET_NAME!r}")


def escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def script_text(guid: str, text: str) -> str:
    return (
        'tell application "Messages"\n'
        f'    set targetChat to chat id "{escape(guid)}"\n'
        f'    send "{escape(text)}" to targetChat\n'
        'end tell'
    )


def script_file(guid: str, path: Path, text: str | None = None) -> str:
    lines = [
        'tell application "Messages"',
        f'    set targetChat to chat id "{escape(guid)}"',
        f'    set theFile to (POSIX file "{escape(str(path))}") as alias',
        '    send theFile to targetChat',
        '    delay 3',
    ]
    if text:
        lines.append(f'    send "{escape(text)}" to targetChat')
    lines.append('end tell')
    return "\n".join(lines)


def _osascript(script: str) -> None:
    t0 = time.perf_counter()
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    log("chat", f"osascript rc={p.returncode}", ms=round((time.perf_counter() - t0) * 1000),
        stderr=p.stderr.strip()[:120])
    if p.returncode != 0:
        raise RuntimeError(f"osascript rc={p.returncode}: {p.stderr.strip()}")


def send_text(guid: str, text: str) -> dict[str, Any]:
    """Gate, send, then confirm. Returns the confirmed from-me row {guid, rowid, ts} or raises."""
    gate(guid)
    watermark = db.max_rowid()
    _osascript(script_text(guid, text))
    row = db.find_from_me(guid, watermark, text, CONFIRM_S)
    if row is None:
        raise RuntimeError(f"unconfirmed send: no from-me row above {watermark} within {CONFIRM_S:.0f}s (not retried)")
    return row


def stage(path: str | Path) -> Path:
    """Copies the file into ~/Pictures/wtdd/ (sandboxed Messages.app can read it there). Returns the staged path."""
    src = Path(path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    PICTURES.mkdir(parents=True, exist_ok=True)
    if src.parent == PICTURES:
        return src
    dst = PICTURES / f"{int(time.time())}-{src.name}"
    shutil.copy2(src, dst)
    log("chat", "staged photo", src=str(src), dst=str(dst), bytes=dst.stat().st_size)
    return dst


def send_file(guid: str, path: str | Path, text: str | None = None) -> dict[str, Any]:
    """Gate, stage, send the file (plus an optional caption in the same script), confirm the file row.
    Returns the confirmed from-me file row; with a caption, row["caption"] is the confirmed caption row."""
    gate(guid)
    staged = stage(path)
    watermark = db.max_rowid()
    _osascript(script_file(guid, staged, text))
    row = db.find_from_me(guid, watermark, None, CONFIRM_S)
    if row is None:
        raise RuntimeError(f"unconfirmed photo: no from-me attachment row above {watermark} within {CONFIRM_S:.0f}s (not retried)")
    if text:
        cap = db.find_from_me(guid, row["rowid"], text, CONFIRM_S)
        if cap is None:
            raise RuntimeError(f"photo confirmed (rowid {row['rowid']}) but caption unconfirmed (not retried)")
        row["caption"] = cap
    return row
