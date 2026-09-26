"""The night's two rows, from the map: the roster (who holds what) and the quote (what the night costs beside the guard
shift it replaces). Both are computed from the map dict and config on every call, and each call writes one ledger row.

  roster(map)                                  schedule.shift {shift_id, stops: [{i, who}], cameras: [{id, zone}], on_call}
  quote(map, price_per_stop_night, nights=1)   quote.night {shift_id, stops, nights, price, guard_shift_ref: {value, cite}}
  python -m wtdd roster                        the same on ui/map.json (wtdd/tools/roster.py); POST /tools/roster
  python -m wtdd quote nights=2                the same, price from WTDD_PRICE_PER_STOP_NIGHT unless given (wtdd/tools/quote.py)
Stops: map.stops are indices into map.path. Each is handed to the body exactly once, in map order; a duplicate or an
index off the path is refused (ValueError naming it). No stops is an empty roster with a WARN, and no quote (a quote for
nothing is not a quote). Cameras: map.cameras [{id, label, pt, zone}] (09 owns the key). A camera's own `zone` wins when
it has one, else the zone polygon its `pt` sits in (field.room_of over map.zones); a `nogo: true` zone never holds a
camera; a camera in no drawn zone is refused, never placed. No cameras key is cameras [] with a WARN, never invented.
Config, read at the point of use (config.get: missing = RuntimeError naming the key): WTDD_ON_CALL_NAME (03 defines it),
WTDD_GUARD_SHIFT_USD (the one guard shift the night replaces, a number Johnny enters), WTDD_GUARD_SHIFT_CITE (where that
number comes from, shown beside it), WTDD_PRICE_PER_STOP_NIGHT (the quote's default price). The shift id is WTDD_SHIFT,
else today's date (YYYY-MM-DD); it is in every row's args and state_after. Every check runs inside the row's step, so a
refusal is a FAILED row with the error, never a silent default. The remote draws the newest of each row (ui/index.html,
08 · roster-quote) from its own poll of the last 2000 ledger rows, and names that window when it finds none. Nothing is
cached here: there is no DEMO_CACHE path.
UNVERIFIED: nothing here touches the dog. The camera-to-zone rule has run only on the test fixture: the shipped map has no
cameras until 09 adds them. The guard-shift figure is whatever is in .env; this code does not check its source.
"""
from __future__ import annotations
import math
import time
from typing import Any

from .config import get, maybe
from .field import room_of
from .ledger import log, step


def shift_id() -> str:
    return maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")


def _stops(m: dict[str, Any]) -> list[int]:
    n, seen = len(m.get("path") or []), []
    for i in m.get("stops") or []:
        if not isinstance(i, int) or not 0 <= i < n:
            raise ValueError(f"stop {i!r} is not a point of the path (indices 0..{n - 1})")
        if i in seen:
            raise ValueError(f"stop {i} is listed twice; each stop is walked once")
        seen.append(i)
    return seen


def _zone_of(cam: dict[str, Any], zones: list[dict[str, Any]]) -> str:
    held = [z for z in zones if not z.get("nogo")]   # a no-go zone holds nothing, a camera included
    z = cam.get("zone") or (room_of(cam["pt"], held) if cam.get("pt") else None)
    if z not in [h["name"] for h in held]:
        raise ValueError(f"camera {cam.get('id')!r} is in no drawn zone (zone {cam.get('zone')!r}, point {cam.get('pt')}); "
                         f"zones: {', '.join(h['name'] for h in held) or 'none'}")
    return z


def _counts(m: dict[str, Any]) -> dict[str, int]:
    return {k: len(m.get(k) or []) for k in ("path", "stops", "cameras", "zones")}


def roster(m: dict[str, Any]) -> dict[str, Any]:
    sid = shift_id()
    with step("schedule", "schedule.shift", "map", {"shift_id": sid}, _counts(m)) as r:
        stops = [{"i": i, "who": "body"} for i in _stops(m)]
        cameras = [{"id": c["id"], "zone": _zone_of(c, m.get("zones") or [])} for c in m.get("cameras") or []]
        r["state_after"] = out = {"shift_id": sid, "stops": stops, "cameras": cameras, "on_call": get("WTDD_ON_CALL_NAME")}
    for what, n in (("stops", len(stops)), ("cameras", len(cameras))):
        if not n:
            log("schedule", f"WARN no {what} on the map", shift=sid)
    log("schedule", "roster", shift=sid, stops=len(stops), cameras=len(cameras), on_call=out["on_call"], ms=r["latency_ms"])
    return out


def quote(m: dict[str, Any], price_per_stop_night: float | None = None, nights: int = 1) -> dict[str, Any]:
    sid = shift_id()
    args = {"shift_id": sid, "price_per_stop_night": price_per_stop_night, "nights": nights}
    with step("schedule", "quote.night", "map", args, _counts(m)) as r:
        p = float(get("WTDD_PRICE_PER_STOP_NIGHT") if price_per_stop_night is None else price_per_stop_night)
        k, n = int(float(nights)), len(_stops(m))
        args.update(price_per_stop_night=p, nights=k)   # the row carries the numbers priced, not the raw input
        if not n or not 0 < p < math.inf or k < 1 or k != float(nights):
            raise ValueError(f"no quote for {n} stops x {nights} nights x {p} per stop-night: each must be above zero, nights whole")
        ref = {"value": float(get("WTDD_GUARD_SHIFT_USD")), "cite": get("WTDD_GUARD_SHIFT_CITE")}
        r["state_after"] = out = {"shift_id": sid, "stops": n, "nights": k, "price": round(n * k * p, 2), "guard_shift_ref": ref}
    log("schedule", "quote", shift=sid, stops=n, nights=k, price=out["price"], guard_shift=ref["value"], ms=r["latency_ms"])
    return out
