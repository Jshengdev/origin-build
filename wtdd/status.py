"""What the dashboard's People, Monitoring and Integrations pages read: who the dog texts, and whether each integration
works, from evidence already on this Mac. Reads only: no ledger row, no network call, never a handle or a key's value.

  people()               GET /people {group, group_why?, people: [{name}], why?}. group is WTDD_CHAT_NAME, the one group the
                         gate posts to (wtdd/chat/send.py), null with group_why when unset. people are the distinct first
                         names in wtdd/chat/housemates.py HOUSEMATES (one person with two handles is one name), never a key;
                         [] with why (a WARN) when it is empty. The API also passes /people through redact() (B10), so a
                         handle typed in as a name reads "a member".
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
  and the latency, a WARN when any is false.
UNVERIFIED on the dog: unitree and lidar are read from a fake Body only (wtdd/test_status.py). The first live GET
/integrations with the dog connected and the LiDAR on must read both true, and after a dog power cycle unitree must read
false ("stale") before the next dog command reconnects.
"""
from __future__ import annotations
import json
import time
from typing import Any

from . import config, ledger
from .chat.housemates import HOUSEMATES, PRIVATE
from .config import ROOT
from .decide import JEV_APP

TAIL = 10000     # newest ledger rows read per call (about 60 ms on a 25 MB ledger); older evidence is not searched
ALIVE_S = 10     # GET /chat's alive: the listener writes listen.json every poll
JEV_TOOLS = ("decided", "reply.decided", "zone.decided", "blob.labelled")


def _at(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))   # the ledger's ts format: local time, no zone


def people() -> dict[str, Any]:
    names = list(dict.fromkeys(HOUSEMATES.values()))
    out: dict[str, Any] = {"group": config.maybe("WTDD_CHAT_NAME"), "people": [{"name": n} for n in names]}
    if not out["group"]:
        out["group_why"] = "WTDD_CHAT_NAME is not set in .env: the gate posts only to the default test group (wtdd/chat/send.py TARGET_NAME)"
    if not names:
        out["why"] = "HOUSEMATES is empty: fill it locally (never committed)"
        ledger.log("status", "WARN people: HOUSEMATES is empty", group=out["group"])
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
    ledger.log("status", ("WARN " if False in oks else "") + "integrations", ok=oks.count(True), failed=oks.count(False),
               unknown=oks.count(None), ms=round((time.perf_counter() - t0) * 1000))
    return {"checked_at": _at(time.time()), "integrations": out}
