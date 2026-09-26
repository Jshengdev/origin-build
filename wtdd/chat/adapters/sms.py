"""The SMS adapter (item 12): the on-call person on a plain phone number, through Twilio's Messaging REST API.

Target `sms:<E.164>` (oncall.guid() forms it when WTDD_ON_CALL_CHANNEL=sms). The gate admits exactly one target,
sms:<WTDD_ON_CALL_HANDLE>, and only while WTDD_ON_CALL_CHANNEL=sms; anything else is a PermissionError before anything
is claimed or sent, and post_text/post_photo gate again as their first statement (like send.py).

Live (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM set), over `requests` (already in requirements.txt):
  send       POST {API}.json  To, From, Body (+ MediaUrl for a photo), HTTP basic auth (account sid, token)
  read-back  GET  {API}/<sid>.json every 0.5 s for CONFIRM_S: status sent|delivered confirms (the from-me row's
             equivalent), failed|undelivered raises with Twilio's error_code, still queued past CONFIRM_S raises
             "unconfirmed send". Never retried: a real person is on the other end.
  replies    GET  {API}.json?From=<handle>&To=<TWILIO_FROM>&DateSent>=<day>: inbound only, date_sent >= the mark,
             each sid handed out once (the seen set).
  photo      MMS: MediaUrl = TWILIO_MEDIA_BASE + /pictures/<name>, the file staged into ~/Pictures/wtdd by send.stage(),
             which the API already serves at /pictures/. TWILIO_MEDIA_BASE must be a public https base reaching this
             Mac's API (a tunnel); unset = the photo post raises naming it (fail loud; the listener posts that to the
             group as escalate-fail), never a silent photo-less flag.
Units. A Twilio message has no row id, so "rowid" is its date_sent as unix seconds and mark() is the clock now in the
same unit; ts and ts_utc are date_sent in UTC "%Y-%m-%d %H:%M:%S", so oncall.acked_ms works across adapters (both ends
on Twilio's clock). Two replies in one second share a rowid: both reach the listener, memory.db keeps the first (its
rowid is the primary key), and replies_since says so in a WARN line. A received MMS's media is counted in the log
line, never fetched: attachments is [].

The stub: see the DEMO_CACHE comment above class Sms.

UNVERIFIED (never run against a live account): the resource shapes are Twilio's documented 2010-04-01 Message
resource (wtdd/chat/fixtures/sms-thread.jsonl, hand-written from the docs); MMS needs an MMS-capable (US/CA) number
and a reachable TWILIO_MEDIA_BASE; a trial account only sends to verified numbers (error 21608); the day filter is
sent as the query key `DateSent>` with the date as its value, exactly as twilio-python sends date_sent_after
(rest/api/v2010/account/message/__init__.py: `"DateSent>": serialize.iso8601_datetime(date_sent_after)`), which is
`DateSent%3E=<day>` on the wire, the docs' "`>=YYYY-MM-DD` (to find Messages with sent_dates on and after a specific
date)"; a 400 there raises out of replies_since and stops the listener's poll, loud. It is date-granular, so
`rowid >= after` plus the seen set is the real filter (a reply in the same second as the boot mark is still read,
once); PageSize 50 is one page, newest first; the mark is this Mac's clock against Twilio's date_sent."""
from __future__ import annotations
import time
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Any

from ... import config
from ...ledger import log
from .. import send

PREFIX = "sms:"
API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages"
KEYS = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM")
CONFIRM_S = 10.0                       # the read-back window (send.CONFIRM_S's twin), read at call time
CONFIRMED = ("sent", "delivered")
FAILED = ("failed", "undelivered")
TIMEOUT_S = 20


def target(handle: str) -> str:
    return PREFIX + handle


def handle_of(t: str) -> str:
    return t.removeprefix(PREFIX)


def _utc(rfc2822: str) -> datetime:
    return parsedate_to_datetime(rfc2822).astimezone(timezone.utc)


def ts_utc(rfc2822: str) -> str:
    """Twilio's RFC 2822 date as chat.db's UTC text, the clock oncall.acked_ms reads."""
    return _utc(rfc2822).strftime("%Y-%m-%d %H:%M:%S")


def epoch(rfc2822: str) -> int:
    return int(_utc(rfc2822).timestamp())


def _now() -> str:
    return format_datetime(datetime.now(timezone.utc))


def message_from(m: dict[str, Any]) -> dict[str, Any]:
    """A Twilio Message resource as the listener's message (db.new_messages' shape)."""
    when = m.get("date_sent") or m["date_created"]
    return {"rowid": epoch(when), "guid": m["sid"], "text": m.get("body"), "is_from_me": 0 if m.get("direction") == "inbound" else 1,
            "sender": m["from"], "ts_utc": ts_utc(when), "attachments": []}


def _ok(r: Any) -> dict[str, Any]:
    """Twilio's JSON body, or its own error code and message raised (never read as a success)."""
    body = r.json()
    if r.status_code >= 300:
        raise RuntimeError(f"twilio {r.status_code} code={body.get('code')}: {body.get('message')}")
    return body


# DEMO_CACHE: without the three Twilio keys this adapter is a stub. Cached: the Twilio send, its status read-back and
# the inbound list, replayed in memory (sent, inbox, stub_status, stub_error; receive() stands in for the person's
# phone). Why: no Twilio account in a worktree, and the on-call person's phone type is unknown until Sunday. Live: set
# WTDD_ON_CALL_CHANNEL=sms and TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM in .env (TWILIO_MEDIA_BASE for the
# photo). All three keys unset = this stub: one WARN at construction, and every row of a stub post or reply is labeled
# cached: true, source: "stub" (adapters.label). One key set = all three required: one or two set is a RuntimeError
# naming the missing ones (a half-set live channel stops the post at its chat.gate row), never this stub.

class Sms:
    app = "sms"

    def __init__(self, sid: str | None = None, token: str | None = None, from_: str | None = None, media_base: str | None = None):
        self.sid, self.token, self.from_, self.media_base = sid, token, from_, media_base
        keys = (sid, token, from_)
        if any(keys) and not all(keys):   # a mistyped key must not quietly become the stub that sends nothing
            raise RuntimeError("[wtdd:config] " + ", ".join(k for k, v in zip(KEYS, keys) if not v) + " required: one Twilio "
                               f"key set means all three. Set them in {config.ROOT / '.env'} (see .env.example), or none for the stub")
        self.stub = not any(keys)
        self.sent: list[dict[str, Any]] = []      # stub: what would have gone to Twilio
        self.inbox: list[dict[str, Any]] = []     # stub: what Twilio would list as received (receive())
        self.seen: set[str] = set()               # sids already handed out by replies_since
        self.stub_status, self.stub_error = "sent", None   # stub: the status the read-back replays, (code, message) on failure
        if self.stub:
            log("chat", "WARN sms adapter is the DEMO_CACHE stub: nothing leaves this process, every row cached/stub",
                missing=",".join(KEYS))

    def _url(self, suffix: str) -> str:
        return API.format(sid=self.sid) + suffix

    def gate(self, t: str) -> str:
        """Exactly sms:<WTDD_ON_CALL_HANDLE>, only while WTDD_ON_CALL_CHANNEL=sms; returns the person's name."""
        if (config.maybe("WTDD_ON_CALL_CHANNEL") or "imessage") != "sms":
            raise PermissionError(f"refused: {t}: the on-call person is not on sms (WTDD_ON_CALL_CHANNEL)")
        h = config.maybe("WTDD_ON_CALL_HANDLE")
        if not h or t != target(h):
            raise PermissionError(f"refused: {t} is not the on-call person's sms target")
        return config.get("WTDD_ON_CALL_NAME")

    def mark(self) -> int:
        return int(time.time())

    def post_text(self, t: str, text: str) -> dict[str, Any]:
        """Gate, send, read Twilio's status back. Returns {guid: sid, rowid, ts, status} or raises."""
        self.gate(t)
        return self._confirm(self._send({"To": handle_of(t), "From": self.from_, "Body": text}))

    def post_photo(self, t: str, path: str | Path, text: str | None = None) -> dict[str, Any]:
        """One MMS: the photo and the line in the same message (no caption bubble). The row gains `media`."""
        self.gate(t)
        data = {"To": handle_of(t), "From": self.from_, **({"Body": text} if text else {})}
        if self.stub:   # DEMO_CACHE: the file name only; the file is never read, staged, served or uploaded, so a
            media = Path(path).name   # missing file fails only on the live path (send.stage: FileNotFoundError)
        else:
            if not self.media_base:
                raise RuntimeError("[wtdd:config] TWILIO_MEDIA_BASE is required to send a photo over sms: a public https "
                                   "base that reaches this Mac's API (see .env.example)")
            media = self.media_base.rstrip("/") + "/pictures/" + send.stage(path).name
        data["MediaUrl"] = media
        return {**self._confirm(self._send(data)), "media": media}

    def _send(self, data: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        if self.stub:   # DEMO_CACHE: the POST, replayed as the queued resource Twilio documents
            res = {"sid": "SM" + uuid.uuid4().hex, "direction": "outbound-api", "status": "queued", "from": data["From"],
                   "to": data["To"], "body": data.get("Body"), "num_media": "1" if data.get("MediaUrl") else "0",
                   "date_created": _now(), "date_sent": None, "error_code": None, "error_message": None}
            self.sent.append(res)
        else:
            import requests
            res = _ok(requests.post(self._url(".json"), data=data, auth=(self.sid, self.token), timeout=TIMEOUT_S))
        log("chat", "sms send", sid=res["sid"], status=res["status"], media=res.get("num_media"), stub=self.stub,
            ms=round((time.perf_counter() - t0) * 1000))
        return res

    def _confirm(self, res: dict[str, Any]) -> dict[str, Any]:
        """Twilio's own status for this sid, polled until it says sent/delivered, failed, or CONFIRM_S runs out."""
        t0, sid = time.perf_counter(), res["sid"]
        deadline = time.monotonic() + CONFIRM_S
        while True:
            if self.stub:   # DEMO_CACHE: the status read-back, replayed from stub_status / stub_error
                code, msg = self.stub_error or (None, None)
                res.update(status=self.stub_status, date_sent=_now() if self.stub_status in CONFIRMED else None,
                           error_code=code, error_message=msg)
                m = res
            else:
                import requests
                m = _ok(requests.get(self._url(f"/{sid}.json"), auth=(self.sid, self.token), timeout=TIMEOUT_S))
            status, ms = m["status"], round((time.perf_counter() - t0) * 1000)
            if status in CONFIRMED and m.get("date_sent"):
                log("chat", "confirmed sms", sid=sid, status=status, stub=self.stub, ms=ms)
                return {"guid": sid, "rowid": epoch(m["date_sent"]), "ts": ts_utc(m["date_sent"]), "status": status}
            if status in FAILED:
                log("chat", "WARN sms failed", sid=sid, status=status, code=m.get("error_code"), ms=ms)
                raise RuntimeError(f"twilio {status} code={m.get('error_code')}: {m.get('error_message')}")
            if time.monotonic() > deadline:
                log("chat", "WARN sms unconfirmed", sid=sid, status=status, ms=ms)
                raise RuntimeError(f"unconfirmed send: {sid} still {status} after {CONFIRM_S:g}s (not retried)")
            time.sleep(0.5)

    def replies_since(self, t: str, after: int) -> list[dict[str, Any]]:
        """The person's messages to TWILIO_FROM with date_sent >= after, each sid once, oldest first."""
        t0, h = time.perf_counter(), handle_of(t)
        if self.stub:   # DEMO_CACHE: the inbound list, replayed from what receive() put in the inbox
            listed = list(self.inbox)
        else:
            import requests
            day = time.strftime("%Y-%m-%d", time.gmtime(after))   # "DateSent>" = day: on the wire DateSent>=<day> (docstring)
            params = {"From": h, "To": self.from_, "DateSent>": day, "PageSize": 50}
            listed = _ok(requests.get(self._url(".json"), params=params, auth=(self.sid, self.token), timeout=TIMEOUT_S))["messages"]
        keep = [m for m in listed if m.get("direction") == "inbound" and m.get("from") == h and m["sid"] not in self.seen
                and epoch(m.get("date_sent") or m["date_created"]) >= after]
        self.seen.update(m["sid"] for m in keep)
        out = sorted(map(message_from, keep), key=lambda x: x["rowid"])
        if keep:
            log("chat", f"sms replies n={len(keep)}", listed=len(listed), after=after, stub=self.stub,
                media_not_fetched=sum(int(m.get("num_media") or 0) for m in keep), ms=round((time.perf_counter() - t0) * 1000))
        same = [m["guid"] for m in out if [x["rowid"] for x in out].count(m["rowid"]) > 1]
        if same:   # every one reaches the listener; memory.db's rowid primary key stores the first (INSERT OR IGNORE)
            log("chat", "WARN same-second sms replies: memory.db keeps one per rowid", n=len(same), sids=",".join(same))
        return out

    def receive(self, from_: str, body: str, date_sent: str | None = None) -> dict[str, Any]:
        """Stub only: the person typing a reply on their phone, appended to the inbox as Twilio would list it."""
        if not self.stub:
            raise RuntimeError("receive() is the stub's stand-in for the person's phone; a live adapter reads Twilio's list")
        when = date_sent or _now()
        m = {"sid": "SM" + uuid.uuid4().hex, "direction": "inbound", "status": "received", "from": from_, "to": self.from_,
             "body": body, "num_media": "0", "date_created": when, "date_sent": when, "error_code": None, "error_message": None}
        self.inbox.append(m)
        return m


_ADAPTER: Sms | None = None


def adapter() -> Sms:
    """The process's SMS adapter, built once from .env: live with the three keys, the labeled stub with none of them,
    a RuntimeError naming the missing ones with one or two (and built again on the next call)."""
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = Sms(*(config.maybe(k) for k in (*KEYS, "TWILIO_MEDIA_BASE")))
    return _ADAPTER


def reset() -> None:
    """Forget the adapter (keys changed, or a test wants an empty stub)."""
    global _ADAPTER
    _ADAPTER = None
