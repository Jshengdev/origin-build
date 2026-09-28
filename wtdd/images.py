"""The photos the dog took in one run, read from the run's ledger rows, never by listing a folder (the dashboard's
Routines and Waiting show them).

  get(query, pictures)                                  (status, body) for GET /images?shift=<id>&trigger=<t>&kind=<k> (wtdd/api.py)
  listing(shift_id, rows, pictures, trigger?, kind?)    the body: {shift, images, n, why?}

An image is {file (the basename), url "/pictures/<file>", ts (its row's), kind, stop, trigger, caption, shift_id, ok (its
row's), missing, replaced}, in time order. The bytes stay behind the API's /pictures/<name> route; this answers none.
A run's rows are record.shift_rows(), the record's own binding (every row stamped with the run plus the unstamped rows
of its window), so this list and GET /record agree on what a run holds. The default shift is the run in force
(shift.current(), GET /record's); a shift no row is stamped with is a 404 naming the shifts that exist, never an empty
list; a kind other than the four is a 400 naming them.

Where each photo is named (read from the writers):
- look: chat.post args.file (wtdd/chat/__main__.py post_step), the look photo posted to the group (say:, say-, round:,
  res:); dog.look state_after.file and file_down (wtdd/dog/session.py _look: the room frame, a tilt's floor frame).
- ask: chat.post args.file of a question: args.kind "escalate" (the flag to the on-call chat: alarm:, decide:,
  intruder-), or a decide: or :decide trigger (the "not sure" line posted to the group with the photo).
- scout: zone.confirmed state_before.photo.path, ok or not (wtdd/dog/scout_zones.py copies the frame once per zone),
  and zone.person state_after.photo.path (a person zone's photo, copied once when the zone appears).
- blob: none today. A blob.labelled row records only crop_sha: the crop goes to the model as a data URL, never a file.
The wake show's fire: post is not listed: dog_on_fire draws flames over a dog.ceo photo, so the dog never took it. A
post with no file is not a photo.
caption: the post's text; the scout's say, or its row's error; None for a dog.look (its "here's what i see" is a
constant). stop: the map index a say:, alarm:, decide: or round: trigger ends in (record._index, a :decide suffix
dropped); a dog.look's frames take the stop of the next such post before the next look (the record's stop rule).

Fail loud. A file that is not in the pictures folder (~/Pictures/wtdd, what /pictures/<name> serves) is listed with
missing true, never dropped. Rows written before each look had its own name (look-<kind>-<stamp>-<id>.jpg) name the
old fixed ones (look-<kind>.jpg, look-down.jpg and their -boxed copies), which each look overwrote: a file modified after
its row (its whole-second ts plus 1 s) is listed with replaced true, because the bytes at its url are a newer look's,
not this row's. `why` counts the missing and the
replaced, and says so when nothing is listed. A read: no row, and no stderr line of its own (the API logs the request).
Captions carry the housemates' words, so the route is in api.PRIVATE_ROUTES (B10: redact()).

UNVERIFIED on a live run: the kinds and the stop join are read from the writers' code and checked on planted rows
(wtdd/test_images.py), never on rows a real round wrote.
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any

from . import record, shift
from .ledger import rows as ledger_rows

KINDS = ("look", "ask", "scout", "blob")
STOPS = ("say:", "alarm:", "decide:", "round:")   # the triggers whose last part is the map stop index


def _stop(trigger: Any) -> int | None:
    t = str(trigger or "")
    return record._index(t.removesuffix(":decide")) if t.startswith(STOPS) else None


def _named(r: dict) -> list[tuple[str, str, str | None, Any]]:
    """(path, kind, trigger, caption) for each photo row r names; [] when it names none."""
    a, tool = r.get("args") or {}, r.get("tool")
    trig = str(a.get("trigger") or "")
    if tool == "chat.post" and a.get("file") and not trig.startswith("fire:"):
        ask = a.get("kind") == "escalate" or trig.startswith("decide:") or trig.endswith(":decide")
        return [(a["file"], "ask" if ask else "look", a.get("trigger"), a.get("text"))]
    if tool == "dog.look":
        after = r.get("state_after") or {}
        return [(after[k], "look", None, None) for k in ("file", "file_down") if after.get(k)]
    photo = ((r.get("state_before") or {}).get("photo") if tool == "zone.confirmed" else
             (r.get("state_after") or {}).get("photo") if tool == "zone.person" else None)   # a person zone's photo
    return [(photo["path"], "scout", None, r.get("response_or_error"))] if photo and photo.get("path") else []


def listing(shift_id: str, rows: list[dict], pictures: Path, trigger: str | None = None, kind: str | None = None) -> dict[str, Any]:
    members = record.shift_rows(shift_id, rows)
    out: list[dict] = []
    looking: list[dict] = []   # the newest dog.look's frames, waiting for the stop its post names
    for r in members:
        n = _stop((r.get("args") or {}).get("trigger")) if r.get("tool") == "chat.post" else None
        if r.get("tool") == "dog.look" or n is not None:
            for img in looking:
                img["stop"] = n
            looking = []
        for path, k, trig, caption in _named(r):
            f = pictures / Path(path).name
            here = f.is_file()
            out.append({"file": f.name, "url": f"/pictures/{f.name}", "ts": r["ts"], "kind": k, "stop": _stop(trig),
                        "trigger": trig, "caption": caption, "shift_id": shift_id, "ok": bool(r.get("ok")), "missing": not here,
                        "replaced": here and f.stat().st_mtime > time.mktime(time.strptime(r["ts"], "%Y-%m-%dT%H:%M:%S")) + 1})
            if r.get("tool") == "dog.look":
                looking.append(out[-1])
    out.sort(key=lambda i: i["ts"])
    shown = [i for i in out if trigger in (None, i["trigger"]) and kind in (None, i["kind"])]
    miss, rep = sum(i["missing"] for i in shown), sum(i["replaced"] for i in shown)
    why = [f"no photo in the {len(members)} rows of shift {shift_id}" + "".join(f", {k} {v}" for k, v in (("trigger", trigger), ("kind", kind)) if v)] if not shown else []
    why += [f"{miss} missing (not in the pictures folder)"] if miss else []
    why += [f"{rep} replaced (a newer look wrote the same name since its row)"] if rep else []
    return {"shift": shift_id, "images": shown, "n": len(shown), **({"why": "; ".join(why)} if why else {})}


def get(query: dict[str, list[str]], pictures: Path) -> tuple[int, dict[str, Any]]:
    """GET /images: 404 for a shift no row is stamped with (GET /record's rule and words), 400 for an unknown kind."""
    q = {k: v[0] for k, v in query.items() if v and v[0]}
    rs = ledger_rows()
    sid = q.get("shift") or shift.current()
    if sid not in (ids := record.shifts(rs)):
        return 404, {"error": f"no shift {sid}: no row is stamped with it; shifts: {', '.join(ids) or 'none'}"}
    if q.get("kind") not in (None, *KINDS):
        return 400, {"error": f"no kind {q['kind']!r}: one of {', '.join(KINDS)}"}
    return 200, listing(sid, rs, pictures, q.get("trigger"), q.get("kind"))
