"""The iMessage adapter (item 12): the shipped transport behind the adapter interface, unchanged.

send.py stays the mouth (the two-target gate, osascript, the from-me read-back, stage()) and db.py the ears
(new_messages over chat.db); this class is the seam post() and the listener call. Every call goes through the module
attribute at call time (send.send_text, db.new_messages, ...), never a copied reference, so a test that patches
send._osascript or db.new_messages patches this path too. One addition: an sms: target is refused here, before
send.gate, because it is never an iMessage chat. Verified and UNVERIFIED lines: send.py's and db.py's docstrings."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from .. import db, send
from . import sms


class IMessage:
    app = "imessage"
    stub = False

    def gate(self, target: str) -> str:
        if target.startswith(sms.PREFIX):
            raise PermissionError(f"refused: {target} is an sms target, not an iMessage chat")
        return send.gate(target)

    def mark(self) -> int:
        return db.max_rowid()

    def post_text(self, target: str, text: str) -> dict[str, Any]:
        return send.send_text(target, text)

    def post_photo(self, target: str, path: str | Path, text: str | None = None) -> dict[str, Any]:
        return send.send_file(target, path, text)

    def replies_since(self, target: str, after: int) -> list[dict[str, Any]]:
        return db.new_messages(target, after)


ADAPTER = IMessage()
