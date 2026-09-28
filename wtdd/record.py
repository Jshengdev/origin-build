"""The morning page (item 10): one shift's record, rendered from nothing but the ledger and the map.

  python -m wtdd.record --shift <id> --html /tmp/record.html    the page (default shift: the run in force, shift.current())
  python -m wtdd.record --shift <id>                            the same record as JSON on stdout
  WTDD_LEDGER=wtdd/fixtures/ledger_shift.jsonl python -m wtdd.record --shift 2026-09-26 --html /tmp/record.html
  GET /record?shift=<id>, GET /record/shifts (wtdd/api.py)     the same JSON over HTTP; shifts() newest first, the run in force

On the page: the stops (each look, what the detector and the model said, whether a person was pinged, the post that
confirmed it, the correction that fixes it), the flags (every escalate post and every stop's "not sure: ..." question,
decide.ask_line, which is also its stop's ping) with who resolved what and when (the newest intruder.verdict for
the flag: a hold then "handled" reads handled, a hold then its expiry reads expired; the first reply's acked_ms, the
close's closed_ms; or "unanswered"; who is its args.by, the listener's HOUSEMATES first name or "a member", else, on
a row from before S10, the raw handle args.from), the corrections, every refusal and every failure, the map with its labeled shapes (rooms, zones, lights,
the path, the shift's planned stops), and the signature line: "unsigned" until an ok record.signed {by, at, shift_id}
row exists (item 03, `python -m wtdd record_sign`), then the name and the time. Every number is counted from rows,
nothing is typed by hand. It reads the ledger through ledger.rows() (so WTDD_LEDGER is honoured) and ui/map.json; it
never appends a row and never writes the map. One stderr line per run with the counts; 0 stops, 0 flags, or a map
with 0 rooms, path points or lights is a WARN; a shift with no stamped row is exit 1, naming the shift ids that exist,
and nothing is written.

Which rows are a shift's (the rule wtdd/test_record.py pins): every row stamped args.shift_id == id (03 stamps every
post, reply and signature), plus the unstamped rows of its window. The window opens at the round's chat.wake (the
nearest one before the first stamped row, with no other shift's row between) or at the first stamped row when there
is no wake; it closes at the shift's ok record.signed row (inclusive), else at the next shift's opener, else at the end
of the ledger (an open shift). A row stamped with another shift never joins. When both a signature and the next
shift's opener exist, the window closes at whichever comes first, so a shift signed after the next one began never
takes the next one's looks.

A stop is a dog.look row plus the rows up to the next look (so a look pressed by hand shows too); its post is the
listener's say:<wake>:<n> (the map index is its n) or, pressed by hand, dog_say's say-<epoch> (kind remote, no map
index; dog_say raises before it posts when its look fails, so a say- post always follows its own look; its "not sure:"
question, say-<epoch>:decide, is that look's ping, not a second say), its model call
is the llm.generate of agent watch (dog_say's; a chat turn after the round is agent central and never lands on the
last stop), and a correction joins it when its args.corrects.at is that post's ledger ts. The follower's own look at
a dot on blue (args.by "follow", session._classify) is no stop: it closes the stop before it, so its vision call and
vision.check land on no stop, and its route.decided classified row is in the ledger, not the stops. A say post with no dog.look
of its own before it (the stop before already has its post, or there is no stop yet) is a look that never reached the
dog (README: "the dog drops or is unreachable ... the look posts the error"; the API is down, so no dog.look row
exists): it opens its own stop, ok false, kind none, its error the post's text, never joined to the stop before. Its
error says what was searched, "no dog.look row in this shift's window": the page vouches for its window, not the
ledger, and the usual other cause is a look that lies outside it (a night crossing midnight without WTDD_SHIFT set,
gotcha 10-1, puts a stop's look on the other page). A
post of any kind stamped with the shift after its signature (dog_say's say or intruder_alarm's escalate fired the next
morning with WTDD_SHIFT still set: the post joins, being stamped, while its unstamped look lies past the window the
signature closed) is never a stop, never a stop's ping and never a flag, so a signed page's stops, pinged cells and
flags do not change on re-render; it is listed under after_signature, with its trigger, rowid and ts, in one red line
on the page. The header's rows, posts and window still count it: they count what the page read, not the record. A
refusal is an ok=false row whose error is a PermissionError or whose tool ends in .refused; every other ok=false row
is a failure. Both are listed, never hidden.

Honest edges. A shift with no chat.wake (a round started from the page) opens at the nearest earlier unstamped wake
when no stamped row lies between, else at its first stamped row: on a ledger that still holds pre-03 rows, the first
such shift reaches back into them. The page prints the window's first and last ts so that is visible. The map is drawn
as ui/map.json is now, not as it was that night (the ledger holds the stop indices, not the drawing); a planned stop
off today's path is listed as such. Models label, they never draw: every shape is the map's polygons and path, no
row's text becomes geometry. No DEMO_CACHE here: the record is a pure read with no live path to flip; a page built
from fixture rows (cached=true, source="stub") says so in its header.

UNVERIFIED on a real night: every join above was checked against listen.py's code and the fixture, never against rows
a live 03 round wrote; the first live render (Needs the dog) confirms them.
"""
from __future__ import annotations
import argparse
import json
import statistics
import sys
from html import escape
from pathlib import Path
from typing import Any

from .chat import oncall
from .config import ROOT
from .ledger import LEDGER, log, rows as ledger_rows

SITE = {"rooms": [], "zones": [], "path": [], "stops": [], "actions": {}, "lights": []}


def _shift(r: dict) -> str | None:
    return (r.get("args") or {}).get("shift_id")


def _index(trigger: Any) -> int | None:
    """The map stop index a trigger carries (say:<wake>:<n>, alarm:<wake>:<n>), else None."""
    last = str(trigger or "").rsplit(":", 1)[-1]
    return int(last) if last.isdigit() else None


def _bind(shift_id: str, rows: list[dict]) -> tuple[list[dict], str | None]:
    """(the shift's rows in ledger order, what closed its window: "signature" | "shift <id>" | "open")."""
    first: dict[str, int] = {}
    for i, r in enumerate(rows):
        if _shift(r) is not None:
            first.setdefault(_shift(r), i)
    if shift_id not in first:
        return [], None
    opens = {}
    for s, f in first.items():
        opens[s] = f
        for j in range(f - 1, -1, -1):          # walk back over unstamped rows to the round's wake
            if _shift(rows[j]) is not None:
                break
            if rows[j].get("tool") == "chat.wake":
                opens[s] = j
                break
    o = opens[shift_id]
    ends = [(i + 1, "signature") for i, r in enumerate(rows)
            if r.get("tool") == "record.signed" and r.get("ok") and _shift(r) == shift_id][:1]
    ends += [(x, f"shift {s}") for s, x in opens.items() if s != shift_id and x > o]
    close, closed_by = min(ends, key=lambda e: e[0], default=(len(rows), "open"))
    return [r for i, r in enumerate(rows) if _shift(r) == shift_id or (_shift(r) is None and o <= i < close)], closed_by


def shift_rows(shift_id: str, rows: list[dict]) -> list[dict]:
    """The rows of one shift (the rule in this module's docstring); [] when no row is stamped with it."""
    return _bind(shift_id, rows)[0]


def shifts(rows: list[dict]) -> list[str]:
    """Every shift that has rows (_bind's rule: one row stamped with its id), newest first by its first stamped row."""
    return list(dict.fromkeys(s for r in rows if (s := _shift(r)) is not None))[::-1]


def build(shift_id: str, rows: list[dict] | None = None, site: dict | None = None) -> dict[str, Any]:
    """One shift's record as a dict, every value read from rows (default: the ledger) and site (default: ui/map.json)."""
    rows = ledger_rows() if rows is None else rows
    site = json.loads((ROOT / "ui" / "map.json").read_text()) if site is None else site
    members, closed_by = _bind(shift_id, rows)

    def ok(r: dict, tool: str) -> bool:
        return r.get("tool") == tool and bool(r.get("ok"))

    corrections = [{"ts": r["ts"], "by": a.get("from"), "text": a.get("text"), "said": (a.get("corrects") or {}).get("said"),
                    "at": (a.get("corrects") or {}).get("at"), "acked_ms": a.get("acked_ms")}
                   for r in members if ok(r, "chat.correction") for a in [r.get("args") or {}]]
    sig = oncall.signed(shift_id, members)
    stops: list[dict] = []
    after_sig: list[dict] = []   # posts stamped with the shift after its signature: never a stop, a ping or a flag of the signed record
    cur = None

    def late(r: dict) -> bool:   # dog_say or intruder_alarm fired after signing with WTDD_SHIFT still set: its look is outside the window
        return sig is not None and ok(r, "chat.post") and r["ts"] > sig["ts"]

    def asks(a: dict) -> bool:   # a person asked: an escalate post ("who dis?!", a heads up) or the stop's "not sure:" (decide.ask_line)
        return a.get("kind") == "escalate" or str(a.get("text") or "").startswith("not sure:")

    def stop(r: dict, **kv: Any) -> dict:
        stops.append({"n": len(stops) + 1, "index": None, "ts": r["ts"], "kind": None, "ok": False, "fired": None, "pitch_deg": None, "error": None,
                      "classes": None, "sentence": None, "person": None, "out_of_place": None, "detector_check": None,
                      "model": None, "model_ms": None, "tokens": None, "posted": None, "pinged": False, "correction": None, **kv})
        return stops[-1]

    for r in members:
        a, after = r.get("args") or {}, r.get("state_after") or {}
        trig = str(a.get("trigger") or "")
        say = ok(r, "chat.post") and trig.startswith(("say:", "say-")) and not trig.endswith(":decide")   # the listener's, dog_say's by hand
        if r.get("tool") == "dog.look":
            cur = None if a.get("by") == "follow" else stop(r, kind=a.get("kind"), ok=bool(r.get("ok")), fired=after.get("fired"),
                                                             pitch_deg=after.get("pitch_deg"), error=None if r.get("ok") else r.get("response_or_error"))
            continue
        if late(r):   # any kind: a say would open a stop with no look, an escalate would ping the last signed stop
            after_sig.append({"ts": r["ts"], "trigger": a.get("trigger"), "rowid": after.get("rowid")})
            continue
        if say and (cur is None or cur["posted"] is not None):   # a look that never reached the dog, or one outside the window
            cur = stop(r, error=f"no dog.look row in this shift's window before this post: {a.get('text')}")
        if cur is None or not r.get("ok"):
            continue
        if r["tool"] == "watch.boxes":
            cur["classes"] = after.get("classes")
        elif r["tool"] == "vision.check":
            cur.update(sentence=r.get("response_or_error"), person=after.get("person"), out_of_place=after.get("out_of_place"),
                       detector_check=after.get("detector_check"))
        elif r["tool"] == "llm.generate" and r.get("agent") == "watch":   # dog_say's call; a chat turn's is agent central
            cur.update(model=after.get("model"), model_ms=r.get("latency_ms"), tokens=(after.get("usage") or {}).get("total_tokens"))
        elif say:
            cur.update(index=_index(a["trigger"]), posted={"rowid": after.get("rowid"), "ts": after.get("ts"), "file": a.get("file")},
                       correction=next((c["text"] for c in corrections if c["at"] == r["ts"]), None))
        elif r["tool"] == "chat.post" and asks(a):
            cur["pinged"] = True

    verdicts = [r for r in members if ok(r, "intruder.verdict")]
    flags = []
    for r in members:
        a = r.get("args") or {}
        if ok(r, "chat.post") and asks(a) and not late(r):   # a flag after the signature is listed, not counted
            vs = [x for x in verdicts if x["args"].get("asked") == a.get("trigger")]   # a hold, then handled or expired: the newest is the outcome
            v = vs[-1] if vs else None
            flags.append({"ts": r["ts"], "trigger": a.get("trigger"), "stop": _index(a.get("trigger")), "to": a.get("guid"),
                          "text": a.get("text"), "file": a.get("file"),
                          "resolved": v and {"by": v["args"].get("by") or v["args"].get("from"), "text": v["args"].get("text"),
                                             "verdict": (v.get("state_after") or {}).get("verdict"), "acked_ms": vs[0]["args"].get("acked_ms"), "ts": v["ts"],
                                             **({"closed_ms": v["args"]["closed_ms"]} if v["args"].get("closed_ms") is not None else {})}})
    acked = [a["acked_ms"] for r in members for a in [r.get("args") or {}]
             if (ok(r, "intruder.verdict") or ok(r, "chat.correction")) and a.get("acked_ms") is not None]
    bad = [{"ts": r.get("ts"), "tool": r.get("tool"), "error": r.get("response_or_error"), "args": r.get("args")} for r in members if not r.get("ok")]
    refusal = [str(b["error"] or "").startswith("PermissionError") or str(b["tool"]).endswith(".refused") for b in bad]
    walks = ([r for r in members if r.get("tool") == "field.walk" and (r.get("args") or {}).get("stops") is not None]
             or [r for r in members if r.get("tool") == "dog.follow" and (r.get("args") or {}).get("stops") is not None])
    return {
        "shift_id": shift_id, "rows": len(members), "stamped": sum(_shift(r) == shift_id for r in members),
        "posts": sum(ok(r, "chat.post") for r in members),
        "window": {"from": members[0]["ts"] if members else None, "to": members[-1]["ts"] if members else None, "closed_by": closed_by},
        "planned_stops": walks[-1]["args"]["stops"] if walks else None,
        "stops": stops, "flags": flags, "corrections": corrections,
        "acked_ms": acked, "acked_median_ms": round(statistics.median(acked)) if acked else None,
        "refusals": [b for b, x in zip(bad, refusal) if x], "failures": [b for b, x in zip(bad, refusal) if not x],
        "signed": {"by": sig["args"].get("by"), "at": sig["args"].get("at")} if sig else None, "after_signature": after_sig,
        "site": {k: site.get(k) or v for k, v in SITE.items()},
        "stub_rows": sum(r.get("cached") is True for r in members),
    }


def _e(x: Any) -> str:
    return "-" if x is None else escape(str(x))


def _table(head: list[str], body: list[list[str]]) -> str:
    """Cells arrive escaped; an empty table is the word none, visible."""
    if not body:
        return '<p class="none">none</p>'
    return ("<table><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in body) + "</table>")


def _svg(site: dict, planned: list[int] | None) -> str:
    """The map from ui/map.json alone: rooms, zones, the path, the lights, the planned stops. No shape from a row."""
    pts = lambda p: " ".join(f"{float(x):g},{float(y):g}" for x, y in p)                 # noqa: E731  (a non-number raises, never lands in the svg)
    mid = lambda p: (sum(x for x, _ in p) / len(p), sum(y for _, y in p) / len(p))      # noqa: E731
    out = ['<svg viewBox="0 0 1060 1540" xmlns="http://www.w3.org/2000/svg">']
    for r in site["rooms"]:
        if r.get("poly"):
            x, y = mid(r["poly"])
            out.append(f'<polygon class="room" points="{pts(r["poly"])}"/><text class="rl" x="{x:.0f}" y="{y:.0f}">{_e(r.get("name"))}</text>')
    for z in site["zones"]:
        if z.get("poly"):
            x, y = mid(z["poly"])
            out.append(f'<polygon class="zone" points="{pts(z["poly"])}"/><text class="zl" x="{x:.0f}" y="{y + 28:.0f}">{_e(z.get("label") or z.get("name"))}</text>')
    path = site["path"]
    if path:
        out.append(f'<polyline class="path" points="{pts(path)}"/>')
    for l in site["lights"]:
        p = l.get("pts") or []
        if len(p) > 1:
            out.append(f'<polyline class="strip" points="{pts(p)}"/>')
        if p:
            x, y = float(p[0][0]), float(p[0][1])
            out.append(f'<circle class="light" cx="{x:g}" cy="{y:g}" r="11"/><text class="ll" x="{x + 16:g}" y="{y + 7:g}">{_e(l.get("name"))}</text>')
    for i in planned or []:
        if 0 <= i < len(path):
            x, y = float(path[i][0]), float(path[i][1])
            act = _action(site, i)
            out.append(f'<circle class="stop" cx="{x:g}" cy="{y:g}" r="16"/><text class="sl" x="{x + 22:g}" y="{y - 12:g}">stop {i}{" " + _e(act) if act else ""}</text>')
    return "".join(out) + "</svg>"


def _action(site: dict, i: int) -> str:
    a = site["actions"].get(str(i)) or {}
    return " · ".join(x for x in (a.get("look"), "say" if a.get("say") else None, "ask" if a.get("ask") else None) if x)


def html(rec: dict[str, Any]) -> str:
    """The page: one standalone document, every string escaped, every number an f-string of rec."""
    w, site, planned = rec["window"], rec["site"], rec["planned_stops"]
    sig = rec["signed"]
    resolved = sum(f["resolved"] is not None for f in rec["flags"])
    cls = lambda c: ", ".join(f"{_e(k)} x{_e(v)}" for k, v in c.items()) if c else "-"   # noqa: E731
    stops = [[_e(s["n"]), _e(s["index"]), _e(s["ts"]), _e(s["kind"]), f'{_e(s["fired"])} / {_e(s["pitch_deg"])}', cls(s["classes"]),
              _e(s["sentence"]), _e(s["detector_check"]), _e(s["person"]), _e(", ".join(s["out_of_place"] or []) or None),
              f'{_e(s["model"])}<br>{_e(s["model_ms"])} ms · {_e(s["tokens"])} tok',
              "yes" if s["pinged"] else "no",
              f'rowid {_e(s["posted"]["rowid"])} at {_e(s["posted"]["ts"])}<br>{_e(s["posted"]["file"])}' if s["posted"] else "-",
              _e(s["correction"]), f'<span class="bad">{_e(s["error"])}</span>' if s["error"] else "-"] for s in rec["stops"]]
    flags = [[_e(f["ts"]), _e(f["stop"]), _e(f["to"]), _e(f["text"]), _e(f["file"])]
             + ([_e(f["resolved"]["by"]), _e(f["resolved"]["text"]), _e(f["resolved"]["verdict"]), _e(f["resolved"]["acked_ms"]), _e(f["resolved"]["ts"])]
                if f["resolved"] else ['<b class="bad">unanswered</b>', "-", "-", "-", "-"]) for f in rec["flags"]]
    corr = [[_e(c["ts"]), _e(c["by"]), _e(c["text"]), _e(c["said"]), _e(c["at"]), _e(c["acked_ms"])] for c in rec["corrections"]]
    bad = lambda xs: [[_e(x["ts"]), _e(x["tool"]), f'<span class="bad">{_e(x["error"])}</span>', f"<code>{_e(json.dumps(x['args'], default=str))}</code>"] for x in xs]   # noqa: E731
    legend = ("".join(f'<li>stop {_e(i)}{": " + _e(_action(site, i)) if _action(site, i) else ""}'
                      f'{"" if 0 <= i < len(site["path"]) else " (off the current path)"}</li>' for i in planned)
              if planned is not None else "<li>no planned stops in this shift's rows (no field.walk or dog.follow with stops)</li>")
    stub = (f'<p class="stub">{rec["stub_rows"]} of {rec["rows"]} rows are cached/stub: a fixture, not a night</p>' if rec["stub_rows"] else "")
    late = rec["after_signature"]
    late = (f'<p class="bad">{len(late)} post{"s" * (len(late) != 1)} stamped after the signature, not on the record (no stop, ping or flag above counts it): '
            + "; ".join(f'{_e(x["trigger"])} rowid {_e(x["rowid"])} at {_e(x["ts"])}' for x in late) + "</p>") if late else ""
    median = f'{rec["acked_median_ms"]} ms (n={len(rec["acked_ms"])}: {", ".join(map(str, rec["acked_ms"]))})' if rec["acked_ms"] else "none"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Shift {_e(rec["shift_id"])} · the record</title>
<style>
body{{font:14px/1.45 -apple-system,system-ui,sans-serif;color:#1b1b1b;background:#fafaf8;margin:2rem auto;max-width:1400px;padding:0 1.5rem}}
h1{{font-size:1.8rem;margin:0 0 .3rem}} h2{{font-size:1.1rem;margin:2rem 0 .5rem;border-bottom:1px solid #ccc;padding-bottom:.2rem}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}} th,td{{border:1px solid #ddd;padding:4px 6px;vertical-align:top;text-align:left}}
th{{background:#efefeb}} code{{font-size:11.5px;word-break:break-all}} .bad{{color:#a4161a}} .none{{color:#666}}
.sig{{font-size:1.25rem;font-weight:600;margin:.8rem 0}} .stub{{background:#fff3cd;border:1px solid #e0c060;padding:.4rem .6rem;display:inline-block}}
svg{{width:100%;max-width:520px;background:#fff;border:1px solid #ddd}} .room{{fill:#f4f4f0;stroke:#555;stroke-width:3}}
.zone{{fill:none;stroke:#2a6f97;stroke-width:3;stroke-dasharray:14 10}} .path{{fill:none;stroke:#888;stroke-width:4}}
.strip{{fill:none;stroke:#e09f3e;stroke-width:8}} .light{{fill:#e09f3e}} .stop{{fill:#a4161a}}
.rl{{font-size:24px;fill:#333;text-anchor:middle}} .zl{{font-size:20px;fill:#2a6f97;text-anchor:middle}} .ll{{font-size:18px;fill:#7a5200}} .sl{{font-size:26px;font-weight:700;fill:#a4161a}}
</style></head><body>
<h1>Shift {_e(rec["shift_id"])}</h1>
<p>window {_e(w["from"])} to {_e(w["to"])}, closed by {_e(w["closed_by"])}</p>
<p>{rec["rows"]} rows ({rec["stamped"]} stamped with the shift) · {rec["posts"]} posts confirmed · {len(rec["stops"])} stops
· {len(rec["flags"])} flags, {resolved} resolved · {len(rec["corrections"])} corrections · {len(rec["refusals"])} refusals
· {len(rec["failures"])} failures · acked median {median}</p>
<p class="sig">{f"signed by {_e(sig['by'])} at {_e(sig['at'])}" if sig else "unsigned"}</p>
{late}{stub}
<h2>Stops ({len(rec["stops"])})</h2>
{_table(["#", "stop", "ts", "look", "fired / pitch", "detector", "what it saw", "its check on the detector", "person", "out of place",
         "model", "pinged", "posted", "correction", "error"], stops)}
<h2>Flags ({len(rec["flags"])})</h2>
{_table(["ts", "stop", "to", "text", "photo", "resolved by", "reply", "verdict", "acked_ms", "at"], flags)}
<h2>Corrections ({len(rec["corrections"])})</h2>
{_table(["ts", "by", "text", "corrects", "said at", "acked_ms"], corr)}
<h2>Refusals ({len(rec["refusals"])})</h2>
{_table(["ts", "tool", "error", "args"], bad(rec["refusals"]))}
<h2>Failures ({len(rec["failures"])})</h2>
{_table(["ts", "tool", "error", "args"], bad(rec["failures"]))}
<h2>Map</h2>
{_svg(site, planned)}
<ul>{legend}</ul>
<p class="none">The map is ui/map.json as it is now, not as it was that night; the planned stops are the shift's rows'.
Rendered by python -m wtdd.record from the ledger and the map; every number on this page is counted from rows.</p>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wtdd.record", description="One shift's record as a page, from the ledger and the map.")
    ap.add_argument("--shift", help="the shift id (args.shift_id); default the run in force: shift.json, else WTDD_SHIFT, else today YYYY-MM-DD")
    ap.add_argument("--html", help="write the page here; without it the record is printed as JSON")
    o = ap.parse_args(argv)
    sid = o.shift or oncall.shift_id()
    rows = ledger_rows()
    if not any(_shift(r) == sid for r in rows):
        log("record", f"WARN shift {sid}: 0 rows, nothing written", ledger=LEDGER,
            shifts=",".join(sorted({_shift(r) for r in rows} - {None})) or "none")
        return 1
    rec = build(sid, rows)
    if o.html:
        Path(o.html).write_text(html(rec), encoding="utf-8")
    else:
        print(json.dumps(rec, default=str, indent=1))
    site = rec["site"]   # a key the map lost reads as empty in build(), so its zero is said here
    zero = [k for k in ("stops", "flags") if not rec[k]] + [f"map {k}" for k in ("rooms", "path", "lights") if not site[k]]
    log("record", ("WARN 0 " + ", 0 ".join(zero) + ": " if zero else "") + f"shift {sid}", rows=rec["rows"], stops=len(rec["stops"]),
        flags=len(rec["flags"]), resolved=sum(f["resolved"] is not None for f in rec["flags"]), corrections=len(rec["corrections"]),
        refusals=len(rec["refusals"]), failures=len(rec["failures"]), stub=rec["stub_rows"],
        map=f"rooms:{len(site['rooms'])},lights:{len(site['lights'])},path:{len(site['path'])}",
        signed=f"{rec['signed']['by']} at {rec['signed']['at']}" if rec["signed"] else "unsigned",
        after_signature=len(rec["after_signature"]), out=o.html or "stdout")
    return 0


if __name__ == "__main__":
    sys.exit(main())
