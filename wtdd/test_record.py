"""Item 10, the morning page: `python -m wtdd.record --shift <id> --html <path>` renders one shift's record from the
ledger and the map, every number computed, "unsigned" until an ok record.signed row exists. Run:
    python -m unittest wtdd.test_record -v
Offline: WTDD_LEDGER is pointed at wtdd/fixtures/ledger_shift.jsonl BEFORE wtdd.ledger is imported (the recipe is
wtdd/fixtures/make_ledger_shift.py: two shifts, 2026-09-25 unsigned and 2026-09-26 signed, every row labeled
cached=true source="stub"), WTDD_MEMORY at a scratch dir, WTDD_SHIFT pinned to the unsigned shift so the CLI's default
is tested too. The fixture is tracked: every test checks its bytes did not change (the record reads, never appends).

The binding rule the tests pin (wtdd/record.py's docstring states it): a shift's rows are every row stamped
args.shift_id == id (03 stamps every post, reply and signature), plus the unstamped rows of its window. The window
opens at the round's chat.wake (the nearest one before the first stamped row, with no other shift's row between) or
at the first stamped row when there is no wake; it closes at the shift's ok record.signed row (inclusive), else at the
next shift's opener, else at the end of the ledger (an open shift). A row stamped with another shift never joins.
Expected numbers were counted by hand from the recipe, once, and are written here, not derived."""
from __future__ import annotations
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "ledger_shift.jsonl"
_TMP = Path(tempfile.mkdtemp(prefix="wtdd-record-test-"))
os.environ["WTDD_LEDGER"] = str(FIXTURE)
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
os.environ["WTDD_SHIFT"] = "2026-09-25"

from wtdd import ledger, record  # noqa: E402
from wtdd.fixtures import make_ledger_shift  # noqa: E402

A, B = "2026-09-25", "2026-09-26"
GROUP, ONCALL = make_ledger_shift.GROUP, make_ledger_shift.ONCALL
EMPTY_SITE = {"rooms": [], "zones": [], "path": [], "stops": [], "actions": {}, "lights": []}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class Fixture(unittest.TestCase):
    def test_fixture_matches_its_recipe_and_every_row_is_labeled_stub(self):
        rows = ledger.rows()
        self.assertEqual(rows, make_ledger_shift.rows(), "regenerate: python -m wtdd.fixtures.make_ledger_shift")
        self.assertEqual(len(rows), 71)
        for r in rows:
            self.assertIs(r["cached"], True, r["tool"])
            self.assertEqual(r["source"], "stub", r["tool"])
        self.assertEqual(sorted({(r.get("args") or {}).get("shift_id") for r in rows} - {None}), [A, B])


class Guard(unittest.TestCase):
    """The record reads the ledger and the map, never appends: the tracked fixture is byte-identical after every test."""

    def setUp(self):
        self.before = _sha(FIXTURE)

    def tearDown(self):
        self.assertEqual(_sha(FIXTURE), self.before, "the record wrote to the ledger it was rendering")


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

    def test_the_goal_command_as_a_process(self):
        out = _TMP / "process.html"
        env = {**os.environ, "WTDD_LEDGER": str(FIXTURE)}
        p = subprocess.run([sys.executable, "-m", "wtdd.record", "--shift", B, "--html", str(out)],
                           cwd=HERE.parent, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("[wtdd:record]", p.stderr)          # one line per run, with its counts
        self.assertIn("Sam Stand-in", out.read_text())


if __name__ == "__main__":
    unittest.main()
