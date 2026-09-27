"""livecheck: one command grades a live hardware step from the ledger rows and the API's stderr log within a second of
them landing, PASS / FAIL / UNSAFE with the deciding row, graded from device state like the evals (never from anyone's
report). The table of steps is wtdd/livecheck/steps.json, drafted from every PR's Needs-the-dog list.

  python -m wtdd.livecheck --step 01.3                 tail <repo>/ledger.jsonl and <repo>/logs/api.log from their current
                                                       end, one stderr line per second, then the verdict on stdout
  python -m wtdd.livecheck --step 01.3 --replay --ledger wtdd/livecheck/fixtures/ledger-01-3.jsonl --log wtdd/livecheck/fixtures/api-01-3.log
                                                       the fixture, clocked by the rows' ts, no sleeping (the dry path)
  python -m wtdd.livecheck --list                      the table: item, step, title, rows count; `unchecked` when rows is empty
  python -m wtdd.livecheck --from-prs                  every open PR's Needs-the-dog lines -> wtdd/livecheck/steps.draft.json (rows empty;
                                                       `gh pr list` then `gh pr view <n> --json body`; --draft-out elsewhere)
  GET /livecheck                                       <repo>/livecheck.json (OUT), the newest verdict or waiting state plus age_s (the
                                                       remote's one mono line); --out writes elsewhere (the tests)

Step keys are <item>.<k>: k is the number (or letter) of the line in that item's PR under **Needs the dog**, the same k
the evening's `live <item> <k>` uses. A step with no rows is `unchecked`: it cannot PASS and says so (exit 1).

Verdicts, in the order they are decided while the files are tailed:
  UNSAFE <step> · <U> after <T> · <the U row, verbatim>        an `unsafe` pattern matched ({tool: T, before: U}: a T row
                                                              then a U row; {tool: T, between: [A, B]}: a T row after A and
                                                              before B); exit 2
  FAIL   <step> · <the fatal WARN line, verbatim>              a `fatal_warns` regex matched a log line; exit 1
  FAIL   <step> · stub row cannot pass a live step · <row>     a matched row with cached true or source "stub" outside
                                                              --replay (a fixture row never grades a live step); exit 1
  FAIL   <step> · <tool> failed: row i/n wants <tool> ok · <row>    the expected row in every field but `ok`: the device
                                                              said the step went the other way (a failed stop is a FAIL,
                                                              never read later as a misorder); exit 1
  FAIL   <step> · timeout after N s: missing <tool> where <field op value>    N s since the check started (timeout_s,
                                                              or --timeout) and the next expected row never landed; exit 1
  FAIL   <step> · the API log <path> was silent while k rows landed: fatal_warns never read · <the tee line>
                                                              every row matched but not one new log line in SILENT_S s
                                                              after (the API was started without the tee): a PASS
                                                              nobody checked; exit 1
  FAIL   <step> · unchecked: ... | no API log at <path>: ... | interrupted after N s     before or instead of tailing; exit 1
                                                              (only a step with fatal_warns reads, and needs, the API log)
  PASS   <step> · <ts> <tool> ok                               every expected row matched in order, then settle_s more
                                                              seconds with no fatal warn and no unsafe pattern, and the
                                                              API log alive when the step has fatal_warns; exit 0
Every verdict, and every per-second `waiting` state, is written atomically (<out>.tmp, then os.replace) to
<repo>/livecheck.json {step, title, t0, elapsed_s, seen, expected, verdict, why, deciding_row, line, short, replay, ledger,
log}; `short` is the remote's mono line ('live · 01.3 · 12 s · rows 2/3 · waiting', 'PASS · 01.3 · dog.grid_save ok'),
and a replay says so on it (`replay · ...`, `... · replay`): a fixture verdict never reads as a live one on the page.
livecheck writes no ledger row: it reads and grades, like the record (10) and the evals (11).

Tailing: both files are opened and seeked to their end when the command starts (--from-start reads history too); rows
are matched by `tool` (and `agent` when given) and by `ok`, then by every `where` field (a dotted path over the row:
args.zone, state_after.cells, source; a plain value is equality, {gte, lte, in, re} are operators). Rows that match
nothing are traffic and skipped; a row with the expected tool that misses a field is a WARN naming the field and the
value seen, but one that holds every field except `ok` is that step's own row and FAILs; a complete ledger line that is
not JSON is a WARN naming it, never dropped in silence. Log lines carry no
timestamp, so in --replay every log line is read before the first tick and the clock is the rows' ts; a row with no
readable ts is a WARN naming it and is clocked with the row before it.

UNVERIFIED on the real dog: nothing here has tailed a live ledger; the frames/cells thresholds in steps.json are guesses
(marked in each step's `note`) until the first live 01.3 writes its two dog.grid_save rows.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .. import ledger as _ledger
from ..config import ROOT

HERE = Path(__file__).resolve().parent
OUT = ROOT / "livecheck.json"
LOG = ROOT / "logs" / "api.log"
STEPS = HERE / "steps.json"
DRAFT = HERE / "steps.draft.json"
POLL_S = 0.2            # the tail's poll: a row is graded within this of landing
STALE_S = 3             # GET /livecheck: a waiting state older than this is a killed livecheck (the page draws it red)
SILENT_S = 2            # live: after the last row, how long a still-silent API log may take to show a line (ledger.step
                        # appends the row, then logs it; the tee and the poll can read them a poll apart) before FAIL
TEE = "start the API as python -m wtdd.api 2>&1 | tee -a logs/api.log"
MISSING = object()      # get()'s answer for a path the row does not have (None is a real value)
OPS = ("gte", "lte", "in", "re")


def say(msg: str) -> None:
    _ledger.log("livecheck", msg)


def load_steps(path: Path | str = STEPS) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for s in json.loads(Path(path).read_text())["steps"]:
        if s["step"] in out:
            raise ValueError(f"duplicate step {s['step']} in {path}")
        bad = [op for r in s["rows"] for c in (r.get("where") or {}).values() if isinstance(c, dict) for op in c if op not in OPS]
        if bad:   # a typo in the table fails when it is loaded, not at the first matching row of a live run
            raise ValueError(f"{s['step']} in {path}: unknown where operator(s) {bad}: use a plain value or {', '.join(OPS)}")
        out[s["step"]] = s
    return out


def get(row, dotted: str):
    v = row
    for k in dotted.split("."):
        if not isinstance(v, dict) or k not in v:
            return MISSING
        v = v[k]
    return v


def _val(x) -> str:
    if isinstance(x, list):
        return "|".join(_val(i) for i in x)
    return x if isinstance(x, str) else json.dumps(x, default=str)


def _holds(op: str, v, x) -> bool:
    num = isinstance(v, (int, float)) and not isinstance(v, bool)
    if op == "gte":
        return num and v >= x
    if op == "lte":
        return num and v <= x
    if op == "in":
        return v in x
    if op == "re":
        return re.search(x, str(v)) is not None
    raise ValueError(f"unknown where operator {op!r}: use a plain value or {', '.join(OPS)}")


def match(row: dict, want: dict) -> str | None:
    """None when the row is the expected one, else the first reason it is not ('args.frames gte 100: saw 74')."""
    for k in ("tool", "agent", "ok"):
        if k in want and row.get(k) != want[k]:
            return f"{k} {_val(want[k])}: saw {_val(row.get(k))}"
    for path, cond in (want.get("where") or {}).items():
        v = get(row, path)
        if v is MISSING:
            return f"{path} missing"
        if not isinstance(cond, dict):
            if v != cond:
                return f"{path} {_val(cond)}: saw {_val(v)[:80]}"
            continue
        for op, x in cond.items():
            if not _holds(op, v, x):
                return f"{path} {op} {_val(x)}: saw {_val(v)[:80]}"
    return None


def render_where(where: dict) -> str:
    return ", ".join(f"{p} " + (" ".join(f"{op} {_val(x)}" for op, x in c.items()) if isinstance(c, dict) else _val(c))
                     for p, c in where.items())


def _write(out: Path, d: dict) -> None:
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(d, default=str))
    os.replace(tmp, out)


def _okw(r: dict) -> str:
    return "ok" if r.get("ok") else "failed"


class _Check:
    """One run's state: the expected rows matched so far, the tools seen (for the unsafe patterns), the clock."""

    def __init__(self, step, spec, out, replay, ledger, log, timeout_s):
        self.step, self.spec, self.out, self.replay, self.ledger, self.log = step, spec or {}, out, replay, ledger, log
        self.n = len(self.spec.get("rows") or [])
        self.timeout = timeout_s if timeout_s is not None else self.spec.get("timeout_s", 0)
        self.i = self.k = self.bad = self.loglines = 0   # matched · rows seen · non-JSON lines · log lines seen
        self.tools: dict[str, int] = {}                  # tool -> the index of its newest row (the unsafe patterns)
        self.last = self.matched = self.v = None
        self.settle_until = None
        self.elapsed = 0
        self.t0 = time.strftime("%Y-%m-%dT%H:%M:%S")

    def state(self, verdict, why, deciding, line, short) -> dict:
        return {"step": self.step, "title": self.spec.get("title", ""), "t0": self.t0, "elapsed_s": round(self.elapsed, 1),
                "seen": self.i, "expected": self.n, "verdict": verdict, "why": why, "deciding_row": deciding, "line": line,
                "short": short, "replay": self.replay, "ledger": str(self.ledger), "log": str(self.log)}

    def done(self, verdict: str, why: str, deciding, brief: str) -> None:
        line = f"{verdict} {self.step} · {why}"
        self.v = self.state(verdict, why, deciding, line, f"{verdict} · {self.step} · {brief}" + (" · replay" if self.replay else ""))
        _write(self.out, self.v)
        print(line, flush=True)

    def row(self, raw: str) -> None:
        try:
            r = json.loads(raw)
        except ValueError:
            r = None
        if not isinstance(r, dict):
            self.bad += 1
            return say(f"WARN {self.step} · ledger line is not a JSON row ({self.bad} so far): {raw[:160]}")
        self.k += 1
        self.last, tool = r, r.get("tool")
        for u in self.spec["unsafe"]:
            if "before" in u and tool == u["before"] and u["tool"] in self.tools:
                return self.done("UNSAFE", f"{tool} after {u['tool']} · {raw}", r, f"{tool} after {u['tool']}")
            if "between" in u and tool == u["tool"] and self.tools.get(u["between"][0], -1) > self.tools.get(u["between"][1], -1):
                a, b = u["between"]
                return self.done("UNSAFE", f"{tool} between {a} and {b} · {raw}", r, f"{tool} between {a} and {b}")
        self.tools[tool] = self.k
        if self.i == self.n:
            return
        want = self.spec["rows"][self.i]
        why = match(r, want)
        if why is None:
            if not self.replay and (r.get("cached") is True or r.get("source") == "stub"):
                return self.done("FAIL", f"stub row cannot pass a live step · {raw}", r, "stub row cannot pass a live step")
            self.i, self.matched = self.i + 1, r
            if self.i == self.n:
                self.settle_until = self.elapsed + self.spec.get("settle_s", 0)
        elif r.get("ok") != want["ok"] and match({**r, "ok": want["ok"]}, want) is None:   # the step's own row, gone the other way
            return self.done("FAIL", f"{tool} {_okw(r)}: row {self.i + 1}/{self.n} wants {tool} {_okw(want)} · {raw}", r, f"{tool} {_okw(r)}")
        elif tool == want["tool"]:
            say(f"WARN {self.step} · a {tool} row landed but is not row {self.i + 1}/{self.n}: {why}")

    def logline(self, line: str) -> None:
        self.loglines += 1
        if any(re.search(rx, line) for rx in self.spec["fatal_warns"]):
            self.done("FAIL", line, {"log": line}, line)

    def settle(self) -> None:
        if self.v is not None or self.i != self.n or self.elapsed < self.settle_until:
            return
        if self.spec["fatal_warns"] and not self.loglines:   # the API was started without the tee: no regex was ever tried
            if self.replay or self.elapsed >= self.settle_until + SILENT_S:
                self.done("FAIL", f"the API log {self.log} was silent while {self.k} rows landed: fatal_warns never read · {TEE}", None,
                          "API log silent: fatal_warns never read")
            return
        r = self.matched
        self.done("PASS", f"{r.get('ts')} {r.get('tool')} {_okw(r)}", r, f"{r.get('tool')} {_okw(r)}")

    def tick(self, s: int) -> None:
        phase = "settling" if self.i == self.n else "waiting"
        last = f"{self.last.get('tool')} {_okw(self.last)}" if self.last else "none"
        msg = f"{self.step} · {s} s · rows {self.i}/{self.n} · last {last} · {phase}"
        say(msg)
        _write(self.out, self.state("waiting", phase, None, f"[wtdd:livecheck] {msg}",
                                    f"{'replay' if self.replay else 'live'} · {self.step} · {s} s · rows {self.i}/{self.n} · {phase}"))

    def timed_out(self) -> None:
        if self.v is not None or self.i == self.n or self.elapsed < self.timeout:
            return
        want = self.spec["rows"][self.i]
        where = render_where(want.get("where") or {})
        if self.k == 0:
            say(f"WARN {self.step} · zero ledger rows landed in {self.timeout:g} s: is the API writing to {self.ledger}?")
        if self.spec["fatal_warns"] and self.loglines == 0:
            say(f"WARN {self.step} · zero API log lines in {self.timeout:g} s: is the API's stderr teed to {self.log}?")
        self.done("FAIL", f"timeout after {self.timeout:g} s: missing {want['tool']}" + (f" where {where}" if where else ""), None,
                  f"timeout: missing {want['tool']}")


class _Tail:
    """New complete lines of a file since the last call; a partial last line waits in the buffer for its newline."""

    def __init__(self, path: Path, from_start: bool):
        self.path, self.buf = path, b""
        self.pos = 0 if from_start or not path.exists() else path.stat().st_size

    def lines(self) -> list[str]:
        if not self.path.exists():
            return []
        if self.path.stat().st_size < self.pos:
            say(f"WARN {self.path} shrank below the tail's position: it was truncated or replaced; reading it from the start")
            self.pos, self.buf = 0, b""
        with self.path.open("rb") as f:
            f.seek(self.pos)
            data = f.read()
        self.pos += len(data)
        *done, self.buf = (self.buf + data).split(b"\n")
        return [l.decode("utf-8", "replace").rstrip("\r") for l in done]


def _live(c: _Check, from_start: bool) -> None:
    if not c.ledger.exists():
        say(f"WARN {c.step} · no ledger at {c.ledger} yet: waiting for it (the API's first row creates it)")
    rows, logs = _Tail(c.ledger, from_start), _Tail(c.log, from_start) if c.spec["fatal_warns"] else None
    t0, ticked = time.monotonic(), 0
    while True:
        c.elapsed = time.monotonic() - t0
        for l in logs.lines() if logs else []:
            c.logline(l)
            if c.v:
                return
        for l in rows.lines():
            if l.strip():
                c.row(l)
            if c.v:
                return
        c.settle()
        if c.v:
            return
        if int(c.elapsed) > ticked:
            ticked = int(c.elapsed)
            c.tick(ticked)
        c.timed_out()
        if c.v:
            return
        time.sleep(POLL_S)


def _replay(c: _Check) -> None:
    """The fixture, clocked by the rows' ts at one-second resolution; every log line is read before the first tick."""
    for l in c.log.read_text().splitlines() if c.spec["fatal_warns"] else []:
        c.logline(l)
        if c.v:
            return
    q, first, off, unclocked = [], None, 0, 0
    for l in (l for l in c.ledger.read_text().splitlines() if l.strip()):
        try:
            r = json.loads(l)
        except ValueError:
            r = None   # not JSON: c.row() WARNs and counts it when it lands
        try:
            ts = datetime.fromisoformat(r["ts"])
            first = first or ts
            off = (ts - first).total_seconds()
        except (ValueError, KeyError, TypeError):
            if isinstance(r, dict):
                unclocked += 1
                say(f"WARN {c.step} · replay row has no readable ts ({unclocked} so far), clocked with the row before it: {l[:160]}")
        q.append((off, l))
    c.t0 = first.isoformat() if first else c.t0
    s = j = 0
    while True:
        c.elapsed = s
        while j < len(q) and q[j][0] <= s:
            c.row(q[j][1])
            j += 1
            if c.v:
                return
        c.settle()
        if c.v:
            return
        if s:
            c.tick(s)
        c.timed_out()
        if c.v:
            return
        s += 1


def run(step: str, ledger=None, log=None, replay: bool = False, timeout_s: float | None = None, from_start: bool = False,
        out=None) -> dict:
    """Grade one step; prints ticks to stderr and the verdict line to stdout; returns the verdict (also in `out`)."""
    spec = load_steps().get(step)
    c = _Check(step, spec, Path(out or OUT), replay, Path(ledger or _ledger.LEDGER), Path(log or LOG), timeout_s)
    if spec is None:
        c.done("FAIL", f"unknown step {step}: not in {STEPS} (python -m wtdd.livecheck --list)", None, "unknown step")
    elif not c.n:
        c.done("FAIL", "unchecked: no rows in steps.json, this step cannot PASS", None, "unchecked: this step cannot PASS")
    elif spec["fatal_warns"] and not c.log.exists():
        c.done("FAIL", f"no API log at {c.log}: {TEE}", None, f"no API log at {c.log}")
    elif replay and not c.ledger.exists():
        c.done("FAIL", f"no ledger at {c.ledger}: a replay needs a fixture ledger (--ledger)", None, "no ledger to replay")
    else:
        say(f"start {step} · {'replay' if replay else 'live'} · rows {c.n} · timeout {c.timeout:g} s · settle {spec.get('settle_s', 0)} s · "
            f"unsafe {len(spec['unsafe'])} · fatal_warns {len(spec['fatal_warns'])} · ledger {c.ledger} · "
            + (f"log {c.log}" if spec["fatal_warns"] else "log not read (no fatal_warns)")
            + (" · from the start" if from_start else ""))
        try:
            _replay(c) if replay else _live(c, from_start)
        except KeyboardInterrupt:
            c.done("FAIL", f"interrupted after {int(c.elapsed)} s", None, "interrupted")
    return c.v


def exit_code(v: dict) -> int:
    return {"PASS": 0, "UNSAFE": 2}.get(v["verdict"], 1)


START = re.compile(r"^\s*(\*\*Needs the dog|#{1,3} Needs the dog)", re.I)
END = re.compile(r"^\s*(\*\*[^*]+\*\*\s*$|#{1,3} )")
ITEM = re.compile(r"^(?:- )?\(?(\d+|[a-z])[.)] (.*)$")
BOLD = re.compile(r"^(?:- )?\*\*(?:\d+[a-z]?\.)?(\d+[a-z]?|[a-z])\b(?!\.\w)\s*([^*]*?)\s*\*\*\s*(.*)$")   # **1 · text** / - **21.1b: text**
NUMBOLD = re.compile(r"^(?:- )?\*\*\s*\d")   # a bold line opening with a number: a step, or a WARN when BOLD cannot read it


def needs_the_dog_lines(body: str, who: str = "") -> list[tuple[str, str]]:
    """[(k, the line's text verbatim)] for the numbered lines of the body's Needs-the-dog section only: `1.` / `a)` / `- (a)`,
    and a step numbered inside bold, `**1 · text** more` / `- **24.1 · text**` / `- **26.1** text` / `- **21.1b: text**` (k is
    the number, with its letter, after any `<item>.`; the text is the line with that bold's two `**` and a leading `:` or `·`
    dropped). A bold line that starts with a step number is a step; one whose number cannot be read whole (`**21.1.2 ·`,
    `**21.1bc:`) is a WARN naming `who` and the line, never read as a shorter number; any other bold-only line or heading
    ends the section."""
    out, on = [], False
    for l in body.splitlines():
        if not on:
            on = bool(START.match(l))
        elif m := ITEM.match(l):
            out.append((m.group(1), m.group(2)))
        elif m := BOLD.match(l):
            out.append((m.group(1), " ".join(t for t in m.group(2, 3) if t).lstrip(":· ")))
        elif NUMBOLD.match(l):
            say(f"WARN {who or 'Needs the dog'} · a bold line opens with a number that is not a step number read whole, not drafted: {l.strip()[:160]}")
        elif END.match(l):
            break
    return out


def draft(prs: list[dict]) -> list[dict]:
    """Steps with empty rows (unchecked) from [{number, title, body}]: item = the title before ' · ', pr = the number."""
    return [{"item": p["title"].split(" · ", 1)[0].strip(), "step": f"{p['title'].split(' · ', 1)[0].strip()}.{k}", "pr": p["number"],
             "title": text, "do": "", "rows": [], "fatal_warns": [], "unsafe": [], "timeout_s": 120, "settle_s": 0,
             "note": "drafted by --from-prs: rows empty (unchecked, cannot PASS) until a person fills them"}
            for p in prs for k, text in needs_the_dog_lines(p["body"], f"#{p['number']}")]


def open_prs() -> list[dict]:
    """Every open PR's {number, title, body} through gh; a nonzero gh exit raises with gh's stderr."""
    def gh(*a: str):
        p = subprocess.run(["gh", *a], capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError(f"gh {' '.join(a[:2])} failed (exit {p.returncode}): {p.stderr.strip()}")
        return json.loads(p.stdout)
    prs = gh("pr", "list", "--state", "open", "--json", "number,title", "--limit", "100")
    for p in prs:
        p["body"] = gh("pr", "view", str(p["number"]), "--json", "body")["body"]
    return prs
