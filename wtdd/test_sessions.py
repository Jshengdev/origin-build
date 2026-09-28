"""GET /sessions: one line per run, newest first, so Record lists the sessions without re-reading each record. Run:
    python -m unittest wtdd.test_sessions -v
The real handler on an ephemeral port in this process, on a planted ledger (WTDD_LEDGER set before wtdd.ledger is
imported; shift.json would sit beside it in the temp dir and is never written). Two runs: a night signed by a stand-in
handle with two stops and one flag, every row live; then a morning, the run in force (WTDD_SHIFT), unsigned, one stop,
two of its rows stand-ins (cached, source stub). Checked: the table and its order, every number as the record counts
it (GET /record per run agrees), the signer's handle reads "a member" (B10), stub_rows says how much is stand-in, and
the ledger's bytes do not change (a read, no row). Handles are stand-ins."""
from __future__ import annotations
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-sessions-test-"))
LEDGER = _TMP / "ledger.jsonl"
os.environ["WTDD_LEDGER"] = str(LEDGER)
os.environ["WTDD_SHIFT"] = ""   # gotcha 02-2: an empty value blocks .env and reads as unset

from wtdd import api  # noqa: E402

NIGHT, MORNING = "2026-09-26-night", "2026-09-27-morning"
SIGNER = "+15550003333"


def _row(ts, tool, args, after=None, stub=False, ok=True):
    return {"ts": ts, "run_id": "run-test", "cached": stub, "source": "stub" if stub else "live", "step": tool, "agent": "central",
            "tool": tool, "app": "stub", "args": args, "state_before": None, "state_after": after, "ok": ok,
            "response_or_error": None, "latency_ms": 0}


def _look(ts, stub=False):
    return _row(ts, "dog.look", {"kind": "tilt"}, {"file": "look-tilt.jpg", "kind": "tilt", "pitch_deg": -16.0, "fired": True}, stub)


def _post(ts, trigger, sid, kind="listen", stub=False):
    return _row(ts, "chat.post", {"guid": "any;+;group", "kind": kind, "trigger": trigger, "text": "a cup", "file": "look-tilt-boxed.jpg",
                                  "shift_id": sid}, {"guid": f"MSG-{trigger}", "rowid": 1, "ts": ts.replace("T", " ")}, stub)


ROWS = [
    _row("2026-09-26T22:00:00", "chat.wake", {"from": "+15550001111", "text": "yo dog do a round", "guid": "W1"}),
    _look("2026-09-26T22:00:10"),
    _post("2026-09-26T22:00:15", "say:W1:1", NIGHT),
    _look("2026-09-26T22:01:10"),
    _post("2026-09-26T22:01:15", "say:W1:2", NIGHT),
    _post("2026-09-26T22:01:20", "alarm:W1:2", NIGHT, kind="escalate"),
    _row("2026-09-26T23:30:00", "record.signed", {"by": SIGNER, "at": "2026-09-26T23:30:00", "shift_id": NIGHT},
         {"signed": True, "at": "2026-09-26T23:30:00", "shift_id": NIGHT}),
    _row("2026-09-27T07:00:00", "shift.started", {"name": "morning", "shift_id": MORNING}, {"shift_id": MORNING, "source": "file"}),
    _look("2026-09-27T07:05:00", stub=True),
    _post("2026-09-27T07:05:05", "say:W2:1", MORNING, stub=True),
]
TABLE = [
    {"shift_id": MORNING, "start": "2026-09-27T07:00:00", "end": "2026-09-27T07:05:05", "rows": 3, "stops": 1, "flags": 0,
     "signed": False, "signed_by": None, "stub_rows": 2, "in_force": True},
    {"shift_id": NIGHT, "start": "2026-09-26T22:00:00", "end": "2026-09-26T23:30:00", "rows": 7, "stops": 2, "flags": 1,
     "signed": True, "signed_by": "a member", "stub_rows": 0, "in_force": False},
]


class Sessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        LEDGER.write_text("".join(json.dumps(r) + "\n" for r in ROWS))
        cls.raw = LEDGER.read_bytes()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {"WTDD_SHIFT": MORNING}))   # the run in force
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def tearDown(self):
        self.assertEqual(LEDGER.read_bytes(), self.raw, "a read wrote the ledger")

    def get(self, path: str) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def sessions(self) -> list:
        code, text = self.get("/sessions")
        self.assertEqual(code, 200, text)
        return json.loads(text)

    def test_the_table_newest_first(self):
        self.assertEqual(self.sessions(), TABLE)

    def test_every_number_is_the_records(self):
        for s in self.sessions():
            with self.subTest(s["shift_id"]):
                code, text = self.get(f"/record?shift={s['shift_id']}")
                rec = json.loads(text)
                self.assertEqual(code, 200, text)
                self.assertEqual((s["start"], s["end"], s["rows"], s["stops"], s["flags"], s["stub_rows"]),
                                 (rec["window"]["from"], rec["window"]["to"], rec["rows"], len(rec["stops"]), len(rec["flags"]), rec["stub_rows"]))
                self.assertEqual((s["signed"], s["signed_by"]), (rec["signed"] is not None, (rec["signed"] or {}).get("by")))

    def test_the_signers_handle_reads_a_member(self):
        code, text = self.get("/sessions")
        self.assertEqual(code, 200, text)
        for private in (SIGNER, SIGNER[1:]):
            self.assertNotIn(private, text)

    def test_the_run_in_force_follows_the_shift(self):
        with mock.patch.dict(os.environ, {"WTDD_SHIFT": NIGHT}):
            self.assertEqual([(s["shift_id"], s["in_force"]) for s in self.sessions()], [(MORNING, False), (NIGHT, True)])


if __name__ == "__main__":
    unittest.main()
