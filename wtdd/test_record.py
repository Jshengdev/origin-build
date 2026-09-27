"""Item 10, the morning page: `python -m wtdd.record --shift <id> --html <path>` renders one shift's record from the
ledger and the map, every number computed, "unsigned" until an ok record.signed row exists. Run:
    python -m unittest wtdd.test_record -v
Offline: WTDD_LEDGER is pointed at a scratch copy of wtdd/fixtures/ledger_shift.jsonl BEFORE wtdd.ledger is imported
(the recipe is wtdd/fixtures/make_ledger_shift.py: two shifts, 2026-09-25 unsigned and 2026-09-26 signed, every row
labeled cached=true source="stub"), WTDD_MEMORY at a scratch dir, WTDD_SHIFT pinned to the unsigned shift inside the
CLI default test only (set at import it would leak into test_oncall, which reads it at call time). The tracked fixture
is never the process's ledger: wtdd.ledger reads WTDD_LEDGER once, at its first import, so a later test module in the
same process that appends (test_oncall's record_sign) would write into it. The copy is checked byte-for-byte against
the tracked file, and every test checks the copy's bytes did not change (the record reads, never appends).

The binding rule the tests pin (wtdd/record.py's docstring states it): a shift's rows are every row stamped
args.shift_id == id (03 stamps every post, reply and signature), plus the unstamped rows of its window. The window
opens at the round's chat.wake (the nearest one before the first stamped row, with no other shift's row between) or
at the first stamped row when there is no wake; it closes at the shift's ok record.signed row (inclusive), else at the
next shift's opener, else at the end of the ledger (an open shift); when both exist, whichever comes first. A row
stamped with another shift never joins. Expected numbers were counted by hand from the recipe, once, and are written
here, not derived.

S13: the same record over HTTP, GET /record?shift=<id> and GET /record/shifts (wtdd/api.py), class Http."""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "ledger_shift.jsonl"      # tracked: copied and hashed, never the ledger
TAKE = HERE.parent / "docs" / "evidence" / "ledger-take-2026-09-13.jsonl"   # the shipped take, pre-03: read only
_TMP = Path(tempfile.mkdtemp(prefix="wtdd-record-test-"))
LEDGER = _TMP / "ledger_shift.jsonl"                     # the process's ledger: a scratch copy of the fixture
shutil.copyfile(FIXTURE, LEDGER)
os.environ["WTDD_LEDGER"] = str(LEDGER)
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")

from wtdd import ledger, record  # noqa: E402
from wtdd.fixtures import make_ledger_shift  # noqa: E402

A, B = "2026-09-25", "2026-09-26"
GROUP, ONCALL = make_ledger_shift.GROUP, make_ledger_shift.ONCALL
EMPTY_SITE = {"rooms": [], "zones": [], "path": [], "stops": [], "actions": {}, "lights": []}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _unreached(rows: list[dict], stop: int) -> list[dict]:
    """Shift A's rows as the README's live failure mode writes them at one stop ("the dog drops or is unreachable ...
    the look posts the error"): the API is down, so the stop has no dog.look, watch.boxes, llm.generate or vision.check
    row, and listen.py still claims and posts say:<wake>:<n> as "couldn't look: ...". In memory; the ledger is untouched."""
    i = next(i for i, r in enumerate(rows) if r["tool"] == "chat.post" and r["args"]["trigger"] == f"say:WAKE-A:{stop}")
    look = max(j for j in range(i) if rows[j]["tool"] == "dog.look")
    said = {**rows[i], "args": {**rows[i]["args"], "text": "couldn't look: ConnectionError: the API is not answering", "file": None}}
    return [r for j, r in enumerate(rows[:i]) if j < look or r["tool"] == "chat.claim"] + [said] + rows[i + 1:]


class Fixture(unittest.TestCase):
    def test_fixture_matches_its_recipe_and_every_row_is_labeled_stub(self):
        rows = ledger.rows()
        self.assertEqual(ledger.LEDGER, LEDGER, "another test module imported wtdd.ledger first in this process: run this one alone")
        self.assertEqual(_sha(LEDGER), _sha(FIXTURE))
        self.assertEqual(rows, make_ledger_shift.rows(), "regenerate: python -m wtdd.fixtures.make_ledger_shift")
        self.assertEqual(len(rows), 71)
        for r in rows:
            self.assertIs(r["cached"], True, r["tool"])
            self.assertEqual(r["source"], "stub", r["tool"])
        self.assertEqual(sorted({(r.get("args") or {}).get("shift_id") for r in rows} - {None}), [A, B])


class Guard(unittest.TestCase):
    """The record reads the ledger and the map, never appends: the ledger it reads is byte-identical after every test."""

    def setUp(self):
        self.before = _sha(LEDGER)

    def tearDown(self):
        self.assertEqual(_sha(LEDGER), self.before, "the record wrote to the ledger it was rendering")


class Unsigned(Guard):
    def setUp(self):
        super().setUp()
        self.rec = record.build(A)

    def test_binding(self):
        r = self.rec
        self.assertEqual(r["shift_id"], A)
        self.assertEqual(r["rows"], 36)        # the wake, its gate and claim, every row to the noon light write; not the 18:00 calibration
        self.assertEqual(r["stamped"], 11)     # 9 posts, the verdict, the correction
        self.assertEqual(r["posts"], 9)
        self.assertEqual(r["window"], {"from": "2026-09-25T22:00:00", "to": "2026-09-26T12:00:00", "closed_by": f"shift {B}"})
        self.assertIsNone(r["signed"])

    def test_stops_are_the_looks_with_what_followed_each(self):
        stops = self.rec["stops"]
        self.assertEqual(self.rec["planned_stops"], [10, 22, 23])
        self.assertEqual([s["index"] for s in stops], [10, 22, 23])
        self.assertEqual([s["kind"] for s in stops], ["tilt", "sit", "tilt"])
        s10, s22, s23 = stops
        self.assertTrue(s10["ok"] and s10["fired"])
        self.assertEqual(s10["classes"], {"chair": 2, "cup": 1})
        self.assertIn("tarp", s10["sentence"])
        self.assertIs(s10["person"], False)
        self.assertIs(s10["pinged"], False)
        self.assertEqual(s10["posted"]["rowid"], 70003)
        self.assertEqual(s10["correction"], "thats a tarp not a cup")   # the row it got wrong and who fixed it (drill row 12)
        self.assertIs(s22["person"], True)
        self.assertIs(s22["pinged"], True)
        self.assertIsNone(s22["correction"])
        self.assertFalse(s23["ok"])
        self.assertIn("401001", s23["error"])
        self.assertIsNone(s23["sentence"])
        self.assertIs(s23["pinged"], False)

    def test_flags_carry_who_resolved_what_and_when(self):
        flags = self.rec["flags"]
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual((f["stop"], f["to"], f["text"], f["file"]), (22, ONCALL, "who dis?!", "look-sit-boxed.jpg"))
        self.assertEqual(f["ts"], "2026-09-25T22:01:34")
        self.assertEqual(f["resolved"], {"by": "+15550002222", "text": "thats my friend, standing down", "verdict": "known",
                                         "acked_ms": 14000, "ts": "2026-09-25T22:01:47"})
        c = self.rec["corrections"]
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["by"], c[0]["text"], c[0]["acked_ms"], c[0]["ts"]), ("+15550001111", "thats a tarp not a cup", 556000, "2026-09-25T22:10:05"))
        self.assertTrue(c[0]["said"].startswith("a cup on the floor"))
        self.assertEqual(self.rec["acked_ms"], [14000, 556000])
        self.assertEqual(self.rec["acked_median_ms"], 285000)

    def test_refusals_and_failures_are_listed_not_hidden(self):
        ref, bad = self.rec["refusals"], self.rec["failures"]
        self.assertEqual([x["tool"] for x in ref], ["chat.claim"])
        self.assertIn("already claimed", ref[0]["error"])
        self.assertEqual(ref[0]["ts"], "2026-09-25T22:10:30")
        self.assertEqual([x["tool"] for x in bad], ["dog.look"])
        self.assertIn("401001", bad[0]["error"])

    def test_page_renders_unsigned_and_every_count(self):
        h = record.html(self.rec)
        self.assertIn(A, h)
        self.assertIn("unsigned", h)
        for needle in ("who dis?!", "thats my friend", "14000", "thats a tarp not a cup", "already claimed", "401001", "556000"):
            self.assertIn(needle, h, needle)
        self.assertIn("&amp; a tarp", h)              # the model's words are escaped, never injected
        self.assertNotIn("& a tarp", h)
        self.assertIn("<svg", h)                       # the map
        for label in ("living room", "stop 10", "stop 22", "stop 23"):
            self.assertIn(label, h, label)

    def test_a_chat_turn_after_the_round_is_not_the_last_stops_model(self):
        rows = ledger.rows()
        noon = next(i for i, r in enumerate(rows) if r["tool"] == "lights.set")   # inside A's window, after its last look
        turn = {"ts": "2026-09-25T22:30:00", "run_id": "fixA-chat", "cached": True, "source": "stub", "step": "llm.generate",
                "agent": "central", "tool": "llm.generate", "app": "openrouter", "args": {"model": "a-chat-model"}, "ok": True,
                "state_before": None, "state_after": {"model": "a-chat-model", "usage": {"total_tokens": 9}}, "response_or_error": "sup", "latency_ms": 7}
        s23 = record.build(A, rows=rows[:noon] + [turn] + rows[noon:])["stops"][2]
        self.assertIsNone(s23["model"])      # a "yo dog" turn (agent central) is the chat's; the failed look had no model call

    def test_a_say_post_with_no_look_before_it_is_its_own_failed_stop(self):
        mid = record.build(A, rows=_unreached(ledger.rows(), 22))["stops"]     # stop 22 never reached the dog
        self.assertEqual([s["index"] for s in mid], [10, 22, 23])
        s10, s22, _ = mid
        self.assertEqual(s10["posted"]["rowid"], 70003)                        # stop 10 keeps its own post and sentence
        self.assertIn("tarp", s10["sentence"])
        self.assertEqual(s22["posted"]["rowid"], 70005)
        self.assertIsNone(s22["kind"])
        self.assertIs(s22["ok"], False)
        self.assertIsNone(s22["sentence"])
        self.assertIn("couldn't look", s22["error"])
        self.assertIn("no dog.look row in this shift's window before this post", s22["error"])   # true on a midnight split too
        first = record.build(A, rows=_unreached(ledger.rows(), 10))["stops"]   # the round's first stop never reached the dog
        self.assertEqual([s["index"] for s in first], [10, 22, 23])
        self.assertIsNone(first[0]["kind"])
        self.assertIn("couldn't look", first[0]["error"])
        self.assertEqual(first[0]["posted"]["rowid"], 70003)
        self.assertEqual((first[1]["kind"], first[1]["posted"]["rowid"]), ("sit", 70005))
        self.assertIn("no dog.look row", record.html(record.build(A, rows=_unreached(ledger.rows(), 22))))   # the page shows it FAILED

    def test_page_renders_with_an_empty_map(self):
        h = record.html(record.build(A, site=EMPTY_SITE))
        self.assertIn("<svg", h)
        self.assertIn("stop 23", h)


class Signed(Guard):
    def setUp(self):
        super().setUp()
        self.rec = record.build(B)

    def test_binding_closes_at_the_signature(self):
        r = self.rec
        self.assertEqual(r["rows"], 33)        # the wake to the signature, plus the refused second signature; not the 09:00 calibration
        self.assertEqual(r["stamped"], 9)      # 7 posts, the signature, the refused signature
        self.assertEqual(r["posts"], 7)
        self.assertEqual(r["window"], {"from": "2026-09-26T22:00:00", "to": "2026-09-27T06:06:00", "closed_by": "signature"})
        self.assertEqual(r["signed"], {"by": "Sam Stand-in", "at": "2026-09-27T06:05:00"})

    def test_an_unanswered_flag_stays_unanswered(self):
        self.assertEqual(len(self.rec["stops"]), 3)
        self.assertEqual(len(self.rec["flags"]), 1)
        self.assertIsNone(self.rec["flags"][0]["resolved"])
        self.assertEqual(self.rec["corrections"], [])
        self.assertEqual(self.rec["acked_ms"], [])
        self.assertIsNone(self.rec["acked_median_ms"])
        self.assertEqual([x["tool"] for x in self.rec["refusals"]], ["record.signed"])
        self.assertIn("already signed", self.rec["refusals"][0]["error"])
        self.assertEqual(self.rec["failures"], [])

    def test_page_shows_the_name_and_time_and_not_unsigned(self):
        h = record.html(self.rec)
        self.assertIn("Sam Stand-in", h)
        self.assertIn("2026-09-27T06:05:00", h)
        self.assertNotIn("unsigned", h)
        self.assertIn("unanswered", h)
        self.assertIn("already signed", h)
        self.assertEqual(self.rec["after_signature"], [])
        self.assertNotIn("after the signature", h)

    def test_a_post_after_the_signature_leaves_the_signed_stops_alone(self):
        """WTDD_SHIFT left set after the morning signature (gotcha 10-1's operating step), dog_say pressed from the page
        at 10:00: its look is unstamped and after the signature (outside the window), its say-<epoch> post is stamped B
        (every stamped row joins). The signed page keeps its three stops; the post is listed as after the signature,
        never as a stop whose look "does not exist". In memory; the ledger is untouched."""
        m, rows = make_ledger_shift, ledger.rows()
        sig = next(i for i, r in enumerate(rows) if r["tool"] == "record.signed" and r["ok"])
        late = [m.look("2026-09-27T10:00:00", "late-dog", "tilt", 9001),
                m.row("2026-09-27T10:00:04", "late-chat", "watch", "watch.boxes", "yolo", {"file": "look-down.jpg"},
                      {"file": "look-down-boxed.jpg", "classes": {"cup": 1}, "n": 1, "ms": 900}, ms=900),
                m.claim("2026-09-27T10:00:06", "late-chat", "say-1790500000"),
                m.post("2026-09-27T10:00:09", "late-chat", GROUP, "remote", "say-1790500000", "a cup on the table",
                       "look-down-boxed.jpg", B, 90001, "2026-09-27 17:00:08")]
        rec = record.build(B, rows=rows[:sig + 2] + late + rows[sig + 2:])   # after the signature and the refused second one
        self.assertEqual(len(rec["stops"]), 3)
        self.assertEqual([s["index"] for s in rec["stops"]], [10, 22, 23])
        self.assertEqual(rec["signed"], {"by": "Sam Stand-in", "at": "2026-09-27T06:05:00"})
        self.assertEqual(rec["after_signature"], [{"ts": "2026-09-27T10:00:09", "trigger": "say-1790500000", "rowid": 90001}])
        h = record.html(rec)
        self.assertNotIn("no dog.look row", h)
        self.assertIn("1 post stamped after the signature, not on the record", h)

    def test_an_escalate_post_after_the_signature_neither_pings_a_signed_stop_nor_adds_a_flag(self):
        """intruder_alarm fired the next morning with WTDD_SHIFT still set: its look, boxes, gate and claim are unstamped
        and after the signature (outside the window), its escalate post intruder-<epoch> to the on-call is stamped B
        (every stamped row joins). The signed page keeps stop 23 unpinged and its one flag; the post is listed as after
        the signature. In memory; the ledger is untouched."""
        m, rows, base = make_ledger_shift, ledger.rows(), self.rec
        sig = next(i for i, r in enumerate(rows) if r["tool"] == "record.signed" and r["ok"])
        late = [m.look("2026-09-27T10:00:00", "late-dog", "level", 9001),
                m.row("2026-09-27T10:00:04", "late-chat", "watch", "watch.boxes", "yolo", {"file": "look-level.jpg"},
                      {"file": "look-level-boxed.jpg", "classes": {"person": 1}, "n": 1, "ms": 900}, ms=900),
                m.gate("2026-09-27T10:00:06", "late-chat", ONCALL, m.NAME),
                m.claim("2026-09-27T10:00:06", "late-chat", "intruder-1790500000"),
                m.post("2026-09-27T10:00:09", "late-chat", ONCALL, "escalate", "intruder-1790500000", "who dis?!",
                       "look-level-boxed.jpg", B, 90001, "2026-09-27 17:00:08")]
        rec = record.build(B, rows=rows[:sig + 2] + late + rows[sig + 2:])   # after the signature and the refused second one
        self.assertEqual(len(rec["stops"]), 3)
        self.assertEqual([(s["index"], s["pinged"]) for s in rec["stops"]], [(10, False), (22, True), (23, False)])
        self.assertEqual(rec["flags"], base["flags"])
        self.assertEqual(len(rec["flags"]), 1)
        self.assertEqual(rec["signed"], {"by": "Sam Stand-in", "at": "2026-09-27T06:05:00"})
        self.assertEqual(rec["after_signature"], [{"ts": "2026-09-27T10:00:09", "trigger": "intruder-1790500000", "rowid": 90001}])
        h = record.html(rec)
        self.assertIn("Flags (1)", h)
        self.assertIn("1 post stamped after the signature, not on the record", h)


class ByHand(Guard):
    def test_a_look_pressed_by_hand_keeps_the_post_that_confirmed_it(self):
        """The README's by-hand path: dog_say from the page posts under say-<epoch> (kind remote), not say:<wake>:<n>.
        On the shipped take the tilt look on line 145 is confirmed by the post on line 151 (rowid 54682). Its rows
        carry no shift id (pre-03): the posts are stamped in memory; the evidence file is only read."""
        rows = [json.loads(line) for line in TAKE.read_text().splitlines() if line.strip()]
        for r in rows:
            if r["tool"] == "chat.post":
                r["args"]["shift_id"] = "take"
        last = record.build("take", rows=rows, site=EMPTY_SITE)["stops"][-1]
        self.assertEqual((last["ts"], last["kind"], last["ok"], last["index"]), ("2026-09-13T15:19:36", "tilt", True, None))
        self.assertEqual(last["posted"], {"rowid": 54682, "ts": "2026-09-13 22:19:44", "file": "look-down-boxed.jpg"})


class Outcome(Guard):
    """B1: a flag's resolved is its final outcome, the newest intruder.verdict for its trigger, never the first. Item
    17's fixture (wtdd/fixtures/ledger-17-remote.jsonl, as listen.verdict() writes it): "on it" holds the flag
    (acknowledged / hold, acked_ms 12000), then "handled, cover is back on" closes it (handled / close, closed_ms 95000,
    no acked_ms: a flag has one). The fixture is only read; the expiry row is added in memory as listen._drop writes it."""

    def setUp(self):
        super().setUp()
        self.rows = [json.loads(x) for x in (HERE / "fixtures" / "ledger-17-remote.jsonl").read_text().splitlines() if x.strip()]

    def test_a_held_then_handled_flag_reads_handled_with_the_holds_acked_ms(self):
        rec = record.build("2026-09-27", rows=self.rows, site=EMPTY_SITE)
        (f,) = rec["flags"]
        self.assertEqual(f["resolved"], {"by": "+15550002222", "text": "handled, cover is back on", "verdict": "handled",
                                         "acked_ms": 12000, "closed_ms": 95000, "ts": "2026-09-27T21:15:47"})
        self.assertEqual(rec["acked_ms"], [12000])   # the flag's one acked_ms, the hold's
        self.assertNotIn("acknowledged", record.html(rec))

    def test_a_held_flag_that_expired_reads_expired(self):
        hold = next(i for i, r in enumerate(self.rows) if r["tool"] == "intruder.verdict")
        a = {k: v for k, v in self.rows[hold]["args"].items() if k != "acked_ms"}
        expired = {**self.rows[hold], "ts": "2026-09-27T21:44:24", "args": {**a, "window_s": 1800},
                   "state_after": {**self.rows[hold]["state_after"], "verdict": "expired", "action": "stand_down"}}
        (f,) = record.build("2026-09-27", rows=self.rows[:hold + 1] + [expired], site=EMPTY_SITE)["flags"]
        self.assertEqual(f["resolved"], {"by": "+15550002222", "text": "on it", "verdict": "expired", "acked_ms": 12000,
                                         "ts": "2026-09-27T21:44:24"})


class Isolation(Guard):
    def test_no_shift_leaks_into_another(self):
        a, b = record.shift_rows(A, ledger.rows()), record.shift_rows(B, ledger.rows())
        self.assertEqual((len(a), len(b)), (36, 33))
        self.assertFalse(any((r.get("args") or {}).get("shift_id") == B for r in a))
        self.assertFalse(any((r.get("args") or {}).get("shift_id") == A for r in b))
        self.assertFalse(any(r["tool"] == "dog.calibrate" for r in a + b))   # before the first wake, after the signature: no shift
        self.assertEqual(record.shift_rows("nope", ledger.rows()), [])


class Cli(Guard):
    def test_writes_the_page_for_the_shift_named(self):
        out = _TMP / "signed.html"
        self.assertEqual(record.main(["--shift", B, "--html", str(out)]), 0)
        self.assertIn("Sam Stand-in", out.read_text())

    def test_default_shift_is_wtdd_shift(self):
        out = _TMP / "default.html"
        with mock.patch.dict(os.environ, {"WTDD_SHIFT": A}):   # pinned here, not at import: another module may set it, and this one must not leak it
            self.assertEqual(record.main(["--html", str(out)]), 0)
        h = out.read_text()
        self.assertIn(A, h)
        self.assertIn("unsigned", h)

    def test_unknown_shift_fails_loud_and_writes_nothing(self):
        out = _TMP / "nope.html"
        try:
            code = record.main(["--shift", "nope", "--html", str(out)])
        except SystemExit as e:
            code = e.code
        self.assertNotEqual(code, 0)
        self.assertFalse(out.exists())

    def test_a_map_without_its_shapes_is_a_warn_not_a_quiet_blank(self):
        bare = _TMP / "bare"                                   # a repo root whose ui/map.json lost its rooms, path and lights
        (bare / "ui").mkdir(parents=True, exist_ok=True)
        (bare / "ui" / "map.json").write_text(json.dumps(EMPTY_SITE))
        full = _TMP / "full"                                   # a repo root whose ui/map.json has its shapes: the old shipped route
        (full / "ui").mkdir(parents=True, exist_ok=True)        # (S2 ships ui/map.json with no path, so the tracked map is not it)
        (full / "ui" / "map.json").write_text((HERE / "fixtures" / "map_route.json").read_text())
        for root, warn in ((full, False), (bare, True)):
            err = io.StringIO()
            with mock.patch.object(record, "ROOT", root), contextlib.redirect_stderr(err):
                self.assertEqual(record.main(["--shift", A, "--html", str(_TMP / "map.html")]), 0)
            self.assertEqual("WARN" in err.getvalue(), warn, err.getvalue())
        for k in ("0 map rooms", "0 map path", "0 map lights", "map=rooms:0,lights:0,path:0"):
            self.assertIn(k, err.getvalue())

    def test_the_goal_command_as_a_process(self):
        out = _TMP / "process.html"
        env = {**os.environ, "WTDD_LEDGER": str(LEDGER)}
        p = subprocess.run([sys.executable, "-m", "wtdd.record", "--shift", B, "--html", str(out)],
                           cwd=HERE.parent, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("[wtdd:record]", p.stderr)          # one line per run, with its counts
        self.assertIn("Sam Stand-in", out.read_text())


class Http(Guard):
    """S13, the morning page over HTTP (wtdd/api.py on an ephemeral port in this process, on this module's scratch
    ledger): GET /record?shift=<id> is exactly the JSON `python -m wtdd.record --shift <id>` prints with its handles
    read "a member" (B10: api.redact; the CLI keeps them raw), the default shift the CLI's; GET /record/shifts is every
    stamped shift newest first and the run in force; an unknown shift is a 404 naming the shifts that exist, never an
    empty record. Both reads: Guard checks the ledger's bytes."""

    def setUp(self):
        super().setUp()
        import threading
        from http.server import ThreadingHTTPServer
        from wtdd import api
        self.enterContext(mock.patch.dict(os.environ, {"WTDD_SHIFT": A}))   # the run in force, as test_default_shift_is_wtdd_shift pins it
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.base = f"http://127.0.0.1:{srv.server_address[1]}"
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def get(self, path: str) -> tuple[int, dict]:
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(self.base + path, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def cli(self, *argv: str) -> dict:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(record.main(list(argv)), 0)
        return json.loads(out.getvalue())

    def test_get_record_is_the_cli_json_for_each_shift_and_the_default(self):
        from wtdd import api
        for sid in (A, B):
            self.assertEqual(self.get(f"/record?shift={sid}"), (200, api.redact(self.cli("--shift", sid))), sid)
        self.assertEqual(self.get(f"/record?shift={A}")[1]["flags"][0]["resolved"]["by"], "a member")   # the CLI's reads +15550002222
        self.assertEqual(self.get(f"/record?shift={A}")[1]["rows"], 36)
        self.assertEqual(self.get(f"/record?shift={B}")[1]["signed"]["by"], "Sam Stand-in")
        code, body = self.get("/record")
        self.assertEqual((code, body), (200, api.redact(self.cli())))
        self.assertEqual(body["shift_id"], A)

    def test_get_record_shifts_lists_them_newest_first_with_the_run_in_force(self):
        self.assertEqual(self.get("/record/shifts"), (200, {"shifts": [B, A], "current": A}))

    def test_an_unknown_shift_is_a_404_naming_the_shifts_that_exist(self):
        code, body = self.get("/record?shift=nope")
        self.assertEqual(code, 404, body)
        for s in ("nope", A, B):
            self.assertIn(s, body["error"])
        self.assertNotIn("stops", body, "never an empty record")


if __name__ == "__main__":
    unittest.main()
