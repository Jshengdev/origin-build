"""S11 · a morning and a night run. Johnny, 2026-09-27 04:17: "I really like the record and the report. it should have
that as a main feature. a morning and night run". Run: python -m unittest wtdd.test_shift -v
Checks wtdd/shift.py: current() is shift.json's shift_id, else WTDD_SHIFT, else today's date; a malformed shift.json is a
ValueError naming the file; start(name) writes the file and one shift.started row with the ids before and after; a
name other than morning or night is a FAILED row AND no file change. decide, oncall and localize stamp the file's id
after a start, in this process and in a separate one (the API, the chat listener and the watch are separate processes
that read the same file), and no module but shift.py reads WTDD_SHIFT. GET /shift and POST /shift (wtdd/api.py) run on
an ephemeral port in this process. The remote (ui/index.html) has both buttons in the receipts panel and reads GET /shift.
The scratch ledger is set through WTDD_LEDGER before wtdd.ledger is imported; shift.json sits beside the ledger, so
these checks never read or write <repo>/shift.json. WTDD_SHIFT is set to "", never popped (docs/gotchas/02-2). Run in one
process with another test module, the ledger is whichever module imported wtdd.ledger first (docs/gotchas/10-2), so FILE
is taken from ledger.LEDGER, a child is handed that ledger, and each check deletes shift.json and restores WTDD_SHIFT
after itself: no module after this one finds a run started here."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-shift-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_SHIFT"] = ""

from wtdd import config, ledger  # noqa: E402

ROOT = config.ROOT
FILE = ledger.LEDGER.with_name("shift.json")


def _shift():
    """The module this item builds (wtdd/shift.py); imported per test so RED shows every check, not one ImportError."""
    from wtdd import shift
    return shift


def _started() -> list[dict]:
    return [r for r in ledger.rows() if r["tool"] == "shift.started"]


def _today() -> str:
    return time.strftime("%Y-%m-%d")


class Clean(unittest.TestCase):
    def setUp(self):
        FILE.unlink(missing_ok=True)
        self.addCleanup(FILE.unlink, missing_ok=True)
        env = mock.patch.dict(os.environ, {"WTDD_SHIFT": ""})
        env.start()
        self.addCleanup(env.stop)


class Current(Clean):
    def test_no_file_and_no_env_is_todays_date(self):
        self.assertEqual(_shift().current(), _today())
        self.assertEqual(_shift().read(), {"shift_id": _today(), "source": "date"})

    def test_wtdd_shift_wins_over_the_date(self):
        with mock.patch.dict(os.environ, {"WTDD_SHIFT": "shift-x"}):
            self.assertEqual(_shift().current(), "shift-x")
            self.assertEqual(_shift().read()["source"], "WTDD_SHIFT")

    def test_the_file_wins_over_both(self):
        FILE.write_text(json.dumps({"shift_id": "2026-09-27-morning", "started": "2026-09-27T07:00:00"}))
        with mock.patch.dict(os.environ, {"WTDD_SHIFT": "shift-x"}):
            self.assertEqual(_shift().current(), "2026-09-27-morning")
            self.assertEqual(_shift().read(), {"shift_id": "2026-09-27-morning", "source": "file"})

    def test_a_malformed_file_is_a_valueerror_naming_it(self):
        for bad in ("{not json", json.dumps({"started": "x"}), json.dumps(["2026-09-27-night"]), json.dumps({"shift_id": ""})):
            FILE.write_text(bad)
            with self.assertRaises(ValueError, msg=bad) as cm:
                _shift().current()
            self.assertIn(str(FILE), str(cm.exception))

    def test_the_file_sits_beside_the_ledger(self):
        self.assertEqual(_shift().FILE, FILE)
        env = {k: v for k, v in os.environ.items() if k != "WTDD_LEDGER"}   # the live default, read by a child: no file is touched
        r = subprocess.run([sys.executable, "-c", "from wtdd import shift; print(shift.FILE)"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertEqual(r.stdout.strip(), str(ROOT / "shift.json"))


class Start(Clean):
    def test_start_night_writes_the_file_and_one_row_with_before_and_after(self):
        n0 = len(_started())
        out = _shift().start("night")
        self.assertEqual(out["shift_id"], f"{_today()}-night")
        time.strptime(out["started"], "%Y-%m-%dT%H:%M:%S")
        self.assertEqual(json.loads(FILE.read_text()), out)
        self.assertEqual(list(FILE.parent.glob("*.tmp")), [], "the temp file was renamed over it")
        rows = _started()
        self.assertEqual(len(rows), n0 + 1)
        row = rows[-1]
        self.assertTrue(row["ok"], row["response_or_error"])
        self.assertEqual(row["state_before"]["shift_id"], _today())
        self.assertEqual(row["state_after"]["shift_id"], out["shift_id"])
        self.assertEqual(_shift().current(), out["shift_id"])

    def test_a_second_start_names_the_run_it_ends(self):
        first = _shift().start("morning")
        self.assertEqual(first["shift_id"], f"{_today()}-morning")
        second = _shift().start("night")
        row = _started()[-1]
        self.assertEqual((row["state_before"]["shift_id"], row["state_after"]["shift_id"]), (first["shift_id"], second["shift_id"]))

    def test_a_bad_name_is_a_failed_row_and_no_file_change(self):
        _shift().start("morning")
        was, n0 = FILE.read_text(), len(_started())
        for bad in ("noon", "", None, "Night"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                _shift().start(bad)
            self.assertEqual(FILE.read_text(), was, f"start({bad!r}) changed shift.json")
        rows = _started()[n0:]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["ok"] is False for r in rows))
        self.assertIn("noon", rows[0]["response_or_error"])

    def test_a_bad_name_with_no_run_writes_no_file(self):
        with self.assertRaises(ValueError):
            _shift().start("noon")
        self.assertFalse(FILE.exists())
        self.assertFalse(_started()[-1]["ok"])


class Stamps(Clean):
    def test_decide_oncall_and_localize_stamp_the_run_after_a_start(self):
        from wtdd import decide
        from wtdd.chat import oncall
        from wtdd.dog import localize
        out = _shift().start("night")
        self.assertEqual([decide.shift_id(), oncall.shift_id(), localize.shift_id()], [out["shift_id"]] * 3)

    def test_a_separate_process_stamps_the_same_run(self):
        out = _shift().start("morning")
        code = ("from wtdd import decide; from wtdd.chat import oncall; from wtdd.dog import localize; "
                "print(decide.shift_id(), oncall.shift_id(), localize.shift_id())")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**os.environ, "WTDD_LEDGER": str(ledger.LEDGER)}, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertEqual(r.stdout.split(), [out["shift_id"]] * 3)

    def test_no_module_but_shift_reads_wtdd_shift(self):
        """plan, nogo and objects stamped config.maybe("WTDD_SHIFT") inline; left so, their rows would split a run."""
        hits = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "wtdd").rglob("*.py")
                      if not p.name.startswith("test_") and p.name != "shift.py" and '"WTDD_SHIFT")' in p.read_text())
        self.assertEqual(hits, [])


class Api(Clean):
    """GET /shift is a read (no row); POST /shift {name} is start(name); a bad name is a 400 with the reason."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from wtdd import api
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/shift"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, body=None):
        data = None if body is None else json.dumps(body).encode()
        rq = urllib.request.Request(self.url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(rq, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_get_is_the_run_in_force_and_writes_no_row(self):
        n0 = len(ledger.rows())
        self.assertEqual(self.req(), (200, {"shift_id": _today(), "source": "date"}))
        self.assertEqual(len(ledger.rows()), n0)

    def test_post_starts_the_run(self):
        code, body = self.req({"name": "morning"})
        self.assertEqual((code, body["ok"], body["shift_id"]), (200, True, f"{_today()}-morning"))
        self.assertEqual(self.req(), (200, {"shift_id": f"{_today()}-morning", "source": "file"}))

    def test_post_a_bad_name_is_a_400_naming_it(self):
        code, body = self.req({"name": "noon"})
        self.assertEqual((code, body["ok"]), (400, False))
        self.assertIn("noon", body["error"])
        self.assertFalse(FILE.exists())


class Page(unittest.TestCase):
    """The remote: both buttons in the receipts panel (drawn in the demo view and #admin alike), the run in force read
    from GET /shift, a start posted by name and its reply shown: the shift_id, or FAILED and the red reason."""
    PAGE = (ROOT / "ui" / "index.html").read_text()

    def test_both_buttons_sit_in_the_receipts_panel(self):
        head = self.PAGE.index("Receipts · ledger.jsonl")
        rows = self.PAGE.index('<div class="ledger">', head)
        for label in ("start morning run", "start night run"):
            self.assertTrue(head < self.PAGE.find(label) < rows, f"{label!r} is not between the receipts heading and its rows")

    def test_the_run_in_force_is_read_from_get_shift(self):
        self.assertTrue("fetch(`${API}/shift`)" in self.PAGE, "the page never GETs /shift")

    def test_a_start_posts_its_name_and_shows_the_reply_or_the_red_reason(self):
        self.assertTrue('post("/shift", { name })' in self.PAGE, "the page never POSTs /shift {name}")
        shown = next((l for l in self.PAGE.splitlines() if "shiftOut.shift_id" in l), "")
        self.assertIn('"bad"', shown)
        self.assertIn("FAILED ${shiftOut.error}", shown)


if __name__ == "__main__":
    unittest.main()
