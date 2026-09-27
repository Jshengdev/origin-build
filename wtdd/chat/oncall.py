"""The on-call person (item 03): who a flag goes to, the shift a row belongs to, and how long the person took to answer.

A flag (the "who dis?!" photo from a round's look, or from intruder_alarm when the detector sees a person) goes to one
named person in the 1:1 chat they already have with this Mac's Messages account, never to the housemates group. The
person is env WTDD_ON_CALL_NAME and WTDD_ON_CALL_HANDLE (their handle exactly as chat.db stores it: E.164 or email),
read through config at the point of use; unset = RuntimeError naming the key (fail loud; the listener posts that to
the group as the error). The 1:1 chat on this Mac is chat.db guid `any;-;<handle>`, one chat_handle_join member (that
handle), display_name usually '' (read-only query 2026-09-26: 253 such chats, every one with exactly one member equal to
its guid's suffix, 248 with an empty name). The send gate (send.py) admits it by guid + that one member. UNVERIFIED
until the first live send: that AppleScript `chat id "any;-;<handle>"` resolves it (the group's `any;+;` form was
verified 2026-09-13).

S10, the demo: WTDD_ON_CALL_GUID (the group's guid, the same value as WTDD_CHAT_GUID for THE CASTLE) makes the group
itself the on-call target: the flag goes there, any member's first clear reply decides (listen.py), and the handle is
not needed. The send gate is not loosened: a guid that is neither the group nor the on-call 1:1 is still refused.

The shift: every row of this item and every chat.post row carries args.shift_id = env WTDD_SHIFT, else today's local
date YYYY-MM-DD. record_sign closes a shift with one ok record.signed row; the ledger is the record.

The clock for acked_ms: the post's confirmed from-me row (chat.post state_after.ts) to the reply's ts_utc, both read
from chat.db, UTC, one-second resolution. Never the ledger's local ts (7 h off in PT). So acked_ms is a multiple of 1000
and says so; a reply stamped before its post is a clock fault (ValueError). Item 11's escalate grader uses this rule.
A reply with no confirmed post row (a dry run, a failed send) gets acked_ms None, the reason as acked_error and a WARN,
never a number."""
from __future__ import annotations
import calendar
import time
from typing import Any

from .. import config
from ..ledger import log, rows as ledger_rows

UTC = "%Y-%m-%d %H:%M:%S"   # chat.db's datetime(... 'unixepoch') text


def guid(handle: str) -> str:
    """The 1:1 chat with a handle, as chat.db (and, UNVERIFIED, AppleScript's chat id) names it."""
    return f"any;-;{handle}"


def person() -> dict[str, Any]:
    """{name, handle, guid} of the on-call person; RuntimeError naming the missing key when unset. WTDD_ON_CALL_GUID set
    (S10: the group's guid, THE CASTLE for the demo) makes that chat the target: {name, handle None, guid, group True}."""
    g = config.maybe("WTDD_ON_CALL_GUID")
    if g:
        return {"name": config.maybe("WTDD_ON_CALL_NAME") or "the group", "handle": None, "guid": g, "group": True}
    handle = config.get("WTDD_ON_CALL_HANDLE")
    return {"name": config.get("WTDD_ON_CALL_NAME"), "handle": handle, "guid": guid(handle)}


def shift_id() -> str:
    return config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")


def post_for(trigger: str | None, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The last ok chat.post row posted under this trigger (the flag a reply answers), else None."""
    hits = [r for r in rows if r.get("tool") == "chat.post" and r.get("ok") and (r.get("args") or {}).get("trigger") == trigger]
    return hits[-1] if hits else None


def acked_ms(post_row: dict[str, Any], reply_ts_utc: str) -> int:
    """Reply ts_utc minus the post's confirmed state_after.ts, in ms, both on chat.db's UTC clock (whole seconds)."""
    posted = post_row["state_after"]["ts"]
    ms = (calendar.timegm(time.strptime(reply_ts_utc, UTC)) - calendar.timegm(time.strptime(posted, UTC))) * 1000
    if ms < 0:
        raise ValueError(f"clock fault: reply {reply_ts_utc} before its post {posted}")
    return ms


def reply_fields(post_row: dict[str, Any] | None, reply_ts_utc: str | None) -> dict[str, Any]:
    """What a reply row (intruder.verdict, chat.correction) gains: acked_ms and shift_id. No confirmed post, or a clock
    fault, is acked_ms None with the reason as acked_error and one WARN line: visible, never a made-up number."""
    out: dict[str, Any] = {"acked_ms": None, "shift_id": shift_id()}
    try:
        if not post_row or not (post_row.get("state_after") or {}).get("ts"):
            raise LookupError("no confirmed post row for this reply (dry run, or the post failed)")
        out["acked_ms"] = acked_ms(post_row, reply_ts_utc or "")
    except (LookupError, ValueError) as e:
        out["acked_error"] = f"{type(e).__name__}: {e}"
        log("chat", "WARN acked_ms none", why=out["acked_error"][:120])
    return out


def signed(shift_id: str, rows: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The last ok record.signed row of this shift (from rows, else the whole ledger), else None: unsigned."""
    hits = [r for r in (ledger_rows() if rows is None else rows)
            if r.get("tool") == "record.signed" and r.get("ok") and (r.get("args") or {}).get("shift_id") == shift_id]
    return hits[-1] if hits else None
