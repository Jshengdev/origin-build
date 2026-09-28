"""What the dashboard's People, Monitoring and Integrations pages read: who the dog texts, and whether each integration
works, from evidence already on this Mac. Reads only: no ledger row, no network call, never a handle or a key's value.

  people()               GET /people {group: {name, members, last_ts}, group_why?, people: [{id, label, is_me,
                         messages_24h, last_ts, replies_to_dog}], why?}. The group chat (chat.db's chat whose guid is
                         WTDD_CHAT_GUID, read-only through wtdd/chat/db.py connect()) and one card per participant of it
                         (chat_handle_join, by handle ROWID) after "you" (this Mac's account: its from-me rows). group.name
                         is WTDD_CHAT_NAME (null with group_why when unset), members the participants (not you), last_ts the
                         group's newest row. messages_24h counts that sender's messages in the group in the last 24 h
                         (tapbacks dropped, as db.new_messages does); last_ts is their newest row there, a tapback included
                         (activity); both are the ledger's local time format. replies_to_dog counts that sender's distinct
                         replies (by message guid: one reply is a reply.decided row and an intruder.verdict row) in the
                         ledger's reply.decided, intruder.verdict and chat.correction rows, matched on args.from inside this
                         function (a from-me row's from is ""). label is "you", else the first name <repo>/people-names.json
                         ({"<handle>": "Teri"}, local, gitignored, only people who agreed to appear) gives, else "member N".
                         A handle is never in the answer, not even as an id: ids are "me", "m1".. in handle ROWID order, and
                         a label that is a handle reads "a member". Never macOS Contacts, never HOUSEMATES (its allowlist is
                         unchanged). chat.db unreadable (no Full Disk Access, missing) or the group not in it raises a
                         RuntimeError naming it, which the API answers 500 {error} (B9): never [], which reads as nobody.
                         No participants is a WARN with why. The ledger is read in full, only its reply lines parsed.
  integrations(session)  GET /integrations {checked_at, integrations: [{name, ok, detail, as_of, key_set?}]}, in this order:
    unitree     session.state(): true when connected, the state stream fresher than session.STALE_MS and avoidance read
                back on; false when stale, avoidance not on, or the last connect failed (its reason, session._unreachable);
                null when nothing has connected yet. as_of is the newest state sample.
    lidar       session.lidar() (GET /dog/lidar's reader): true when on and the newest frame is fresher than STALE_MS;
                false when on and stale, or on with no frame and frames rejected (decode errors); null when not
                connected, switched off, or no frame yet and none rejected.
    hue, tuya   the newest lights.* row with that app (the alarm's "hue+tuya" counts for both): its ok and ts.
    imessage    <repo>/listen.json, the heartbeat GET /chat reads: true under ALIVE_S old, false older (the listener
                stopped), null with no file (it has not run here); armed and dry in the detail, never armed_by.
    jev         key_set: JEV_API_KEY set, a bool only; and the newest Jev row (decided, reply.decided, zone.decided,
                blob.labelled) with app openrouter or stub: a row a Jev call wrote. A failed "name blobs" press that
                never reached Jev (dog off: app unitree) is not one.
    openrouter  key_set: OPENROUTER_API_KEY set, a bool only; and the newest llm.generate row.
    ledger      the row count (newlines: append() writes one per row) and the newest row's ts; null with no rows (a WARN).
  A row from the stub (source or app "stub", DEMO_CACHE) is never a live ok: its integration is null and says stub. A
  key that is not set is false whatever the rows say: the live path cannot run without it. The ledger is read once, its
  newest TAIL rows (ledger.rows); evidence older than that reads "no ... row in the newest TAIL ledger rows" (null), never
  a search of the whole file. An unreadable ledger is false on every integration that needed a row, and an integration
  whose reader raises is false with the error; the others are still answered. One stderr line per call with the counts
  and the latency, a WARN when any is false or none is ok.
UNVERIFIED on this Mac: people() ran on a planted chat.db only (wtdd/test_status.py); the first live GET /people must
show THE CASTLE's members (8) plus you and no handle. UNVERIFIED on the dog: unitree and lidar are read from a fake Body
only (wtdd/test_status.py). The first live GET /integrations with the dog connected and the LiDAR on must read both true, and after a dog power cycle unitree must read
false ("stale") before the next dog command reconnects.
"""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import config, ledger
from .chat import db
from .chat.housemates import PRIVATE
from .config import ROOT
from .decide import JEV_APP

TAIL = 10000     # newest ledger rows read per call (about 90-110 ms on the 25 MB ledger); older evidence is not searched
ALIVE_S = 10     # GET /chat's alive: the listener writes listen.json every poll
JEV_TOOLS = ("decided", "reply.decided", "zone.decided", "blob.labelled")
REPLY_TOOLS = ("reply.decided", "intruder.verdict", "chat.correction")   # rows that record a member answering the dog
NAMES = "people-names.json"   # local first names, {"<handle>": "Teri"}; gitignored, never committed, never in ui/ (served as-is)
# One sender's rows in one chat: messages in the last 24 h (no tapbacks) and the newest row. {who} picks the sender.
AGG_SQL = """SELECT COALESCE(SUM(m.associated_message_type = 0 AND m.date > :since), 0) AS n24, MAX(m.date) AS last
FROM message m JOIN chat_message_join cmj ON cmj.message_id = m.ROWID WHERE cmj.chat_id = :chat AND {who}"""


def _at(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))   # the ledger's ts format: local time, no zone


def _apple_at(ns: int | None) -> str | None:
    return None if ns is None else _at(ns / 1e9 + 978307200)   # message.date: nanoseconds since 2001-01-01


def _replies() -> dict[str, set]:
    """args.from -> the message guids it replied to the dog with; only lines naming a REPLY_TOOLS tool are parsed."""
    by: dict[str, set] = {}
    if not ledger.LEDGER.exists():
        return by
    with ledger.LEDGER.open() as f:
        for line in f:
            if any(t in line for t in REPLY_TOOLS) and (r := json.loads(line)).get("tool") in REPLY_TOOLS:
                a = r.get("args") or {}
                by.setdefault(a.get("from"), set()).add(a.get("guid") or line)
    return by


def people() -> dict[str, Any]:
    t0 = time.perf_counter()
    f = ROOT / NAMES
    try:
        names = json.loads(f.read_text()) if f.exists() else {}
    except ValueError as e:
        raise ValueError(f"{NAMES} is not JSON: {e}") from None
    if not isinstance(names, dict):
        raise ValueError(f"{NAMES} is not an object of handle to first name")
    guid = config.get("WTDD_CHAT_GUID")
    since = int((time.time() - 86400 - 978307200) * 1e9)
    try:
        with db.connect() as c:
            chat = c.execute("SELECT ROWID FROM chat WHERE guid = ?", (guid,)).fetchone()
            if chat is None:
                raise RuntimeError("the group WTDD_CHAT_GUID names is not in chat.db (python -m wtdd.chat chats lists the guids)")
            agg = lambda who, **kw: c.execute(AGG_SQL.format(who=who), {"chat": chat[0], "since": since, **kw}).fetchone()  # noqa: E731
            group, me = agg("1"), agg("m.is_from_me = 1")
            members = [(h["id"], agg("m.is_from_me = 0 AND m.handle_id = :h", h=h["ROWID"])) for h in c.execute(
                "SELECT h.ROWID, h.id FROM chat_handle_join chj JOIN handle h ON h.ROWID = chj.handle_id"
                " WHERE chj.chat_id = ? ORDER BY h.ROWID", (chat[0],))]
    except sqlite3.Error as e:
        raise RuntimeError(f"chat.db unreadable ({str(db.CHAT_DB).replace(str(Path.home()), '~')}: {e}): "
                           "give this terminal Full Disk Access and restart the API") from None
    replies = _replies()
    card = lambda i, label, handle, a: {"id": i, "label": label, "is_me": i == "me", "messages_24h": a["n24"],  # noqa: E731
                                        "last_ts": _apple_at(a["last"]), "replies_to_dog": len(replies.get(handle, ()))}
    out: dict[str, Any] = {
        "group": {"name": config.maybe("WTDD_CHAT_NAME"), "members": len(members), "last_ts": _apple_at(group["last"])},
        "people": [card("me", "you", "", me)] + [card(f"m{n}", PRIVATE.sub("a member", str(names.get(h) or f"member {n}")), h, a)
                                                 for n, (h, a) in enumerate(members, 1)]}
    if not out["group"]["name"]:
        out["group_why"] = "WTDD_CHAT_NAME is not set in .env: the gate posts only to the default test group (wtdd/chat/send.py TARGET_NAME)"
    if not members:
        out["why"] = "the group has no other participants in chat.db"
    ledger.log("status", f"{'WARN ' if not members else ''}people members={len(members)}",
               named=sum(1 for h, _ in members if names.get(h)), replies=sum(p["replies_to_dog"] for p in out["people"]),
               ms=round((time.perf_counter() - t0) * 1000))
    return out


def _row(r: dict | None, what: str) -> dict[str, Any]:
    """An integration read from its newest row: ok and ts. A stub row is null (not a live call); no row is null."""
    if r is None:
        return {"ok": None, "detail": f"no {what} row in the newest {TAIL} ledger rows", "as_of": None}
    stub = "stub" in (r.get("source"), r.get("app"))
    said = "ok" if r.get("ok") else f"FAILED: {PRIVATE.sub('a member', str(r.get('response_or_error')))[:160]}"   # redacted before cut
    return {"ok": None if stub else bool(r.get("ok")), "as_of": r.get("ts"),
            "detail": f"{r.get('tool')} via {r.get('app')} ({'stub, DEMO_CACHE: not a live call' if stub else 'live'}): {said}"}


def _keyed(env: str, r: dict | None, what: str, without: str) -> dict[str, Any]:
    key = bool(config.maybe(env))   # only whether it is set: the value is never kept or served
    out = {**_row(r, what), "key_set": key}
    if not key:
        out["ok"], out["detail"] = False, f"{env} is not set: {without}; {out['detail']}"
    return out


def _unitree(s) -> dict[str, Any]:
    from .dog.session import STALE_MS
    st = s.state()
    if not st["connected"]:
        if u := s._unreachable:   # (monotonic when, why) of the last failed connect; cleared by the next good one
            ago = time.monotonic() - u[0]
            return {"ok": False, "detail": f"not connected: the connect {round(ago)} s ago failed: {u[1]}", "as_of": _at(time.time() - ago)}
        return {"ok": None, "detail": "not connected: the first dog command (or POST /dog/lidar {on: true}) connects", "as_of": None}
    d = st["state"]
    if d is None:
        return {"ok": None, "detail": "connected, no state sample yet", "as_of": None}
    fresh = d["age_ms"] <= STALE_MS
    avoid = {True: "on", False: "OFF"}.get(st["avoid"], "not read back")
    return {"ok": fresh and st["avoid"] is True, "as_of": _at(time.time() - d["age_ms"] / 1000),
            "detail": f"connected, state {d['age_ms']} ms old" + ("" if fresh else f" (stale past {STALE_MS} ms: the next dog command reconnects once)")
                      + f", {d.get('hz')} Hz, avoidance {avoid}"}


def _lidar(s) -> dict[str, Any]:
    from .dog.session import STALE_MS
    if s.body is None:
        return {"ok": None, "detail": "not connected", "as_of": None}
    lp = s.lidar()
    if not lp["on"]:
        return {"ok": None, "detail": f"switched off, {lp['n']} frames this session", "as_of": None}
    if lp["age_ms"] is None:   # a frame that fails to decode counts in errors, never in n: on and nothing usable is red
        err = lp.get("errors") or 0
        return {"ok": False if err else None, "as_of": None,
                "detail": "on, no frame yet" + (f", {err} frames rejected (decode errors)" if err else "")}
    fresh = lp["age_ms"] <= STALE_MS
    return {"ok": fresh, "as_of": _at(time.time() - lp["age_ms"] / 1000),
            "detail": f"on, {lp['n']} frames, the newest {lp['age_ms']} ms old" + ("" if fresh else f" (stale past {STALE_MS} ms)")
                      + (f", {lp['errors']} decode errors" if lp.get("errors") else "")}


def _imessage() -> dict[str, Any]:
    f = ROOT / "listen.json"
    if not f.exists():
        return {"ok": None, "detail": "no listen.json: the listener has not run here (python -m wtdd.chat listen)", "as_of": None}
    d = json.loads(f.read_text())
    age = round(time.time() - d["t"], 1)
    return {"ok": age < ALIVE_S, "as_of": _at(d["t"]),
            "detail": (f"listening, heartbeat {age} s ago" if age < ALIVE_S else f"the listener stopped: its last heartbeat was {age} s ago")
                      + (", armed" if d.get("armed") else ", not armed") + (", dry: it posts nothing" if d.get("dry") else "")}


def _ledger(r: dict | None) -> dict[str, Any]:
    if r is None:
        ledger.log("status", "WARN the ledger has no rows")
        return {"ok": None, "detail": "no rows yet", "as_of": None}
    n = ledger.LEDGER.read_bytes().count(b"\n")
    return {"ok": True, "detail": f"{n} rows, the newest {r.get('tool')}", "as_of": r.get("ts")}


def integrations(session) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        tail = ledger.rows(TAIL)
    except Exception as e:  # noqa: BLE001  (named on every integration that needs a row below, never read as an empty ledger)
        tail = e

    def newest(match):
        if isinstance(tail, Exception):
            raise RuntimeError(f"the ledger is unreadable: {type(tail).__name__}: {tail}")
        return next((r for r in reversed(tail) if match(r)), None)

    def lights(app):
        return lambda: _row(newest(lambda r: str(r.get("tool")).startswith("lights.") and app in str(r.get("app")).split("+")), f"lights.* {app}")

    checks = {"unitree": lambda: _unitree(session), "lidar": lambda: _lidar(session), "hue": lights("hue"), "tuya": lights("tuya"),
              "imessage": _imessage,
              "jev": lambda: _keyed("JEV_API_KEY", newest(lambda r: r.get("tool") in JEV_TOOLS and r.get("app") in (JEV_APP, "stub")),
                                    "Jev decision",
                                    "every decision runs on the stub (DEMO_CACHE)"),
              "openrouter": lambda: _keyed("OPENROUTER_API_KEY", newest(lambda r: r.get("tool") == "llm.generate"), "llm.generate",
                                           "every model call fails before it is sent"),
              "ledger": lambda: _ledger(newest(lambda r: True))}
    out = []
    for name, check in checks.items():
        try:
            out.append({"name": name, **check()})
        except Exception as e:  # noqa: BLE001  (that integration reads false with its reason; the others are still answered)
            out.append({"name": name, "ok": False, "detail": f"{type(e).__name__}: {e}", "as_of": None})
    oks = [i["ok"] for i in out]
    ledger.log("status", ("WARN " if False in oks or True not in oks else "") + "integrations", ok=oks.count(True), failed=oks.count(False),
               unknown=oks.count(None), ms=round((time.perf_counter() - t0) * 1000))
    return {"checked_at": _at(time.time()), "integrations": out}
