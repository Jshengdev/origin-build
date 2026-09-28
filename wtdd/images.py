"""The photos the dog took in one run, read from the run's ledger rows, never by listing a folder (the dashboard's
Routines and Waiting show them).

  get(query, pictures)                                  (status, body) for GET /images?shift=<id>&trigger=<t>&kind=<k> (wtdd/api.py)
  listing(shift_id, rows, pictures, trigger?, kind?)    the body: {shift, images, n, why?}
  share(body, pictures)                                 (status, body) for POST /images/share {file, caption?, by}

An image is {file (the basename), url "/pictures/<file>", ts (its row's), kind, stop, trigger, caption, shift_id, ok (its
row's), missing, replaced, shared, replies}, in time order. The bytes stay behind the API's /pictures/<name> route; this answers none.
A run's rows are record.shift_rows(), the record's own binding (every row stamped with the run plus the unstamped rows
of its window), so this list and GET /record agree on what a run holds. The default shift is the run in force
(shift.current(), GET /record's); a shift no row is stamped with is a 404 naming the shifts that exist, never an empty
list; a kind other than the four is a 400 naming them.

Where each photo is named (read from the writers):
- look: chat.post args.file (wtdd/chat/__main__.py post_step), the look photo posted to the group (say:, say-, round:,
  res:); dog.look state_after.file and file_down (wtdd/dog/session.py _look: the room frame, a tilt's floor frame).
- ask: chat.post args.file of a question: args.kind "escalate" (the flag to the on-call chat: alarm:, decide:,
  intruder-), or a decide: or :decide trigger (the "not sure" line posted to the group with the photo).
- scout: zone.confirmed state_before.photo.path, ok or not (wtdd/dog/scout_zones.py copies the frame once per zone).
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

Share (Johnny, 19:4x: "I can choose to send it to the group chat with a button in it, and people can respond, and
it'll save the responses for me"). POST /images/share {file, caption?, by}: file is read as its basename (a path never
reaches outside the pictures folder) and must be a photo GET /images lists for some run and still in the folder (404
each, naming it), by a non-empty name (400), and no question open in pending.json (409: the who-dis answer comes
first); each refusal is one failed chat.share.refused row and nothing is posted. Then the photo and its caption
(default "from the dog's round · stop <n>", or its time when no stop) go to the group through chat/__main__.post, the
path the round's looks take: the gate (guid AND name), the claim of share:<file>:<epoch> (a second share of one photo
in the same second is the same claim, refused), ONE chat.post row {kind: "share", file, trigger, by}. A confirmed post
writes <repo>/share.json {trigger, file, by, at, until: at + SHARE_WINDOW_S (600 s, listen.py)} whole (temp file
replaced), replacing an open window with one WARN; the answer is {ok, trigger, until}. A failed post (its row has the
error) is 500 {ok: false, error} and opens no window. The listener keeps the group's messages in the window as
chat.reply rows (wtdd/chat/listen.py share_reply); POST /chat/reset deletes share.json.
A share post is not listed as a photo of its own: it re-posts one. Each image carries shared: its file's newest share
{trigger, at (the post row's ts), by, ok} or null, and replies: [{by, text, ts (the row's)}] from the chat.reply rows of
every share of that file, in time order, read from every row (a photo of one run may be shared during another). by is
the HOUSEMATES first name, else "a member"; the text passes the route's redact(). A share whose post failed shows
ok false and, since it opened no window, no replies of its own. A share refused at the gate or the claim wrote that
row (chat.gate / chat.claim) and no chat.post: its photo shows shared null.

UNVERIFIED on a live run: the kinds and the stop join are read from the writers' code and checked on planted rows
(wtdd/test_images.py), never on rows a real round wrote. The share (wtdd/test_share.py) is checked on the send stub
only: that a real photo and caption land in THE CASTLE from this route, and that the 600 s window is long enough for
the group to answer on camera, wait for the first live share.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any

from . import config, record, shift
from .chat.housemates import HOUSEMATES
from .ledger import append, log, rows as ledger_rows

KINDS = ("look", "ask", "scout", "blob")
STOPS = ("say:", "alarm:", "decide:", "round:")   # the triggers whose last part is the map stop index


def _stop(trigger: Any) -> int | None:
    t = str(trigger or "")
    return record._index(t.removesuffix(":decide")) if t.startswith(STOPS) else None


def _named(r: dict) -> list[tuple[str, str, str | None, Any]]:
    """(path, kind, trigger, caption) for each photo row r names; [] when it names none."""
    a, tool = r.get("args") or {}, r.get("tool")
    trig = str(a.get("trigger") or "")
    if tool == "chat.post" and a.get("file") and not trig.startswith("fire:") and a.get("kind") != "share":   # a share re-posts a listed photo
        ask = a.get("kind") == "escalate" or trig.startswith("decide:") or trig.endswith(":decide")
        return [(a["file"], "ask" if ask else "look", a.get("trigger"), a.get("text"))]
    if tool == "dog.look":
        after = r.get("state_after") or {}
        return [(after[k], "look", None, None) for k in ("file", "file_down") if after.get(k)]
    photo = (r.get("state_before") or {}).get("photo") if tool == "zone.confirmed" else None
    return [(photo["path"], "scout", None, r.get("response_or_error"))] if photo and photo.get("path") else []


def _shared(rows: list[dict]) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """({file: its newest share {trigger, at, by, ok}}, {file: the replies to every share of it [{by, text, ts}], in time
    order}), read from every row: a photo from one run may be shared during another."""
    shared: dict[str, dict] = {}
    of: dict[str, str] = {}   # share trigger -> file
    replies: dict[str, list[dict]] = {}
    for r in rows:
        a = r.get("args") or {}
        if r.get("tool") == "chat.post" and a.get("kind") == "share" and a.get("file"):
            f = Path(a["file"]).name
            shared[f], of[a.get("trigger")] = {"trigger": a.get("trigger"), "at": r["ts"], "by": a.get("by"), "ok": bool(r.get("ok"))}, f
        elif r.get("tool") == "chat.reply" and a.get("share") in of:
            replies.setdefault(of[a["share"]], []).append({"by": HOUSEMATES.get(a.get("from")) or "a member", "text": a.get("text"), "ts": r["ts"]})
    return shared, replies


def listing(shift_id: str, rows: list[dict], pictures: Path, trigger: str | None = None, kind: str | None = None) -> dict[str, Any]:
    members = record.shift_rows(shift_id, rows)
    shared, replies = _shared(rows)
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
                        "replaced": here and f.stat().st_mtime > time.mktime(time.strptime(r["ts"], "%Y-%m-%dT%H:%M:%S")) + 1,
                        "shared": shared.get(f.name), "replies": replies.get(f.name, [])})
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


def _refuse(code: int, error: str, args: dict, before: dict) -> tuple[int, dict[str, Any]]:
    """One failed chat.share.refused row (the record counts it a refusal, not a failure), one line, nothing posted."""
    append({"step": "chat.share.refused", "agent": "chat", "tool": "chat.share.refused", "app": "imessage", "ok": False,
            "args": args, "state_before": before, "state_after": None, "response_or_error": error, "latency_ms": 0})
    log("chat", "share REFUSED", code=code, error=error[:100])
    return code, {"ok": False, "error": error}


def share(body: dict, pictures: Path) -> tuple[int, dict[str, Any]]:
    """POST /images/share {file, caption?, by}: one listed photo to the group through the gated path (chat/__main__.post:
    gate, claim, then ONE chat.post row, kind share, args.by), then the replies window (listen.SHARE, SHARE_WINDOW_S).
    file is read as its basename only: a path never reaches outside the pictures folder."""
    from .chat import listen
    from .chat.__main__ import post
    name, by = Path(str(body.get("file") or "")).name, str(body.get("by") or "").strip()
    args = {"file": name or None, "by": by or None}
    try:
        pend = json.loads(listen.PENDING.read_text())
    except FileNotFoundError:
        pend = None
    try:
        was = listen.window(listen.SHARE.read_text())
    except FileNotFoundError:
        was = None
    except listen.BAD_SHARE as e:   # a corrupt window is replaced by this share, never a reason to refuse it
        log("chat", "WARN share.json unreadable: this share replaces it", err=f"{type(e).__name__}: {str(e)[:80]}")
        was = None
    before = {"pending": pend and pend.get("trigger"), "share": was and was.get("trigger")}
    if not by:
        return _refuse(400, "no by: a share names who sent it", args, before)
    if not name:
        return _refuse(400, "no file: a share names a photo GET /images lists", args, before)
    if pend is not None:
        return _refuse(409, f"a question is open ({pend.get('trigger')}): its answer comes first, share after it", args, before)
    rs = ledger_rows()
    listed = [i for sid in record.shifts(rs) for i in listing(sid, rs, pictures)["images"] if i["file"] == name]
    if not listed:
        return _refuse(404, f"no photo {name}: GET /images lists none by that name for any run", args, before)
    img = listed[-1]
    if img["missing"]:
        return _refuse(404, f"photo {name} is not in the pictures folder", args, before)
    caption = str(body.get("caption") or "").strip() or ("from the dog's round · "
                                                        + (f"stop {img['stop']}" if img["stop"] is not None else img["ts"][11:16]))
    trigger = f"share:{name}:{int(time.time())}"
    try:   # the gate, the claim and the chat.post row each write their own row, ok or not
        post(config.maybe("WTDD_CHAT_GUID") or "", trigger, "share", caption, str(pictures / name), by=by)
    except Exception as e:  # noqa: BLE001  (its row has it; answered, no window)
        return 500, {"ok": False, "error": f"{type(e).__name__}: {e}"}
    at = time.time()
    if was and at < was.get("until", 0):
        log("chat", "WARN a share replaces the open window", was=was.get("trigger"), now=trigger)
    w = {"trigger": trigger, "file": str(pictures / name), "by": by, "at": at, "until": at + listen.SHARE_WINDOW_S}
    tmp = listen.SHARE.with_suffix(".tmp")
    tmp.write_text(json.dumps(w))
    tmp.replace(listen.SHARE)   # whole or not at all: the listener never reads half a window
    log("chat", "share window open", share=trigger, window_s=listen.SHARE_WINDOW_S)
    return 200, {"ok": True, "trigger": trigger, "until": w["until"]}
