"""The channel adapters (item 12): one interface the post and the listener use, whatever phone the on-call person has.

An adapter is the transport behind wtdd.chat.__main__.post, which stays the one way anything posts: gate (chat.gate
row) -> never-twice claim (chat.claim row) -> send + read-back (chat.post row) -> memory.confirm. The adapter never
claims; post() does, for every adapter, so the never-twice gate is the same for all of them.

  app                              the ledger's app column: "imessage" | "sms"
  stub                             True only for a # DEMO_CACHE: stub (sms without its Twilio keys)
  gate(target) -> name             the verified name, or PermissionError before anything is claimed or sent
  mark() -> int                    the read-back watermark, in the adapter's rowid unit (chat.db ROWID | unix seconds)
  post_text(target, text)          gate, send, read back: the confirmed {guid, rowid, ts} or raise, never retried
  post_photo(target, path, text)   the same for a photo with an optional line (iMessage adds `caption`, SMS adds `media`)
  replies_since(target, after)     the listener's messages {rowid, guid, text, is_from_me, sender, ts_utc, attachments}

The target string carries the channel: chat.db guids (the group any;+;<hex>, the on-call 1:1 any;-;<handle>) are
iMessage (imessage.py wraps send.py, the mouth, and db.py, the ears); `sms:<E.164>` is SMS (sms.py, Twilio), formed by
oncall.guid() when WTDD_ON_CALL_CHANNEL=sms. So post(guid, trigger, kind, text, file) keeps its signature for every
caller. Label rule: every row a stub adapter's post or reply writes carries label(target) = cached: true, source:
"stub", so no stub row ever claims to be live; a live adapter's rows keep the ledger's cached: false, source: "live".
UNVERIFIED on a real phone: everything SMS (see sms.py); iMessage is send.py and db.py unchanged."""
from __future__ import annotations
from typing import Any, Protocol

from . import imessage, sms


class Adapter(Protocol):
    app: str
    stub: bool

    def gate(self, target: str) -> str: ...
    def mark(self) -> int: ...
    def post_text(self, target: str, text: str) -> dict[str, Any]: ...
    def post_photo(self, target: str, path: str, text: str | None = None) -> dict[str, Any]: ...
    def replies_since(self, target: str, after: int) -> list[dict[str, Any]]: ...


def for_target(target: str) -> Adapter:
    """sms:<E.164> is the SMS adapter (live with its keys, else the labeled stub); every other target is iMessage."""
    return sms.adapter() if target.startswith(sms.PREFIX) else imessage.ADAPTER


def label(target: str) -> dict[str, Any]:
    """What a row of this target's post or reply adds: the stub label, or nothing (the ledger's live default)."""
    return {"cached": True, "source": "stub"} if for_target(target).stub else {}
