"""POST /chat/reset {by}: a clean slate between two Loom takes. Run: python -m unittest wtdd.test_chat_reset -v
Johnny, live at 18:3x: "just make sure there's a reset chat button". A half-answered "who dis?!" (pending.json) or an
armed listening window must never leak from one take into the next. The API drops the open question, writes the
listener's flag (listen.RESET, its time) and one chat.reset row {args: {by}, state_before: {pending, armed},
state_after: {dropped}}; nothing is posted and no past row moves. The real handler on an ephemeral port in this process,
as test_api_private runs it; the ledger is WTDD_LEDGER set before wtdd.ledger is imported, and the listener's PENDING,
HEARTBEAT and RESET are temp paths, so the checkout's files are never touched. The listener's side (the flag read in
poll() and inside a hold) is wtdd.chat.test_round.Reset."""
from __future__ import annotations
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-chat-reset-test-"))
LEDGER = _TMP / "ledger.jsonl"
os.environ["WTDD_LEDGER"] = str(LEDGER)
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")

from wtdd import api, ledger  # noqa: E402
from wtdd.chat import listen as L  # noqa: E402

GROUP = "any;+;00000000000000000000000000000000"
PAST = {"step": "intruder.verdict", "agent": "central", "tool": "intruder.verdict", "app": "imessage", "ok": True,
        "args": {"asked": "alarm:T0:3"}, "state_before": None, "state_after": {"verdict": "known"}, "response_or_error": None, "latency_ms": 0}


class Reset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        d = Path(tempfile.mkdtemp(dir=_TMP))
        self.pend, self.hb, self.flag = d / "pending.json", d / "listen.json", d / "chat.reset"
        for name, path in (("PENDING", self.pend), ("HEARTBEAT", self.hb), ("RESET", self.flag)):
            self.enterContext(mock.patch.object(L, name, path, create=True))   # create: RESET is new with this route
        ledger.append(PAST)   # a past take's row: never touched
        self.before = LEDGER.read_bytes()

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        rq = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(rq, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def new_rows(self) -> list[dict]:
        after = LEDGER.read_bytes()
        self.assertTrue(after.startswith(self.before), "a past ledger row was rewritten")
        return [json.loads(l) for l in after[len(self.before):].decode().splitlines() if l.strip()]

    def test_an_open_question_is_dropped_with_one_row_and_the_flag_written(self):
        self.pend.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "file": "/tmp/look.jpg", "seconds": 5,
                                         "trigger": "alarm:T1:5", "chat": GROUP, "question": "who dis?!"}))
        self.hb.write_text(json.dumps({"t": time.time(), "guid": GROUP, "armed": True, "armed_by": "Teri", "dry": True,
                                       "pending": True, "last_rowid": 7}))
        code, got = self.post("/chat/reset", {"by": "Johnny"})
        self.assertEqual((code, got), (200, {"ok": True, "dropped": True, "pending_was": {"trigger": "alarm:T1:5", "kind": "who_dis"}}))
        self.assertFalse(self.pend.exists(), "the half-answered who dis is still open for the next take")
        self.assertRegex(self.flag.read_text(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\n$", "the listener's flag carries the time")
        (r,) = self.new_rows()   # exactly one row: nothing posted (a post is chat.gate, chat.claim and chat.post rows)
        self.assertEqual((r["tool"], r["ok"], r["args"]), ("chat.reset", True, {"by": "Johnny"}))
        self.assertEqual(r["state_before"], {"pending": {"trigger": "alarm:T1:5", "kind": "who_dis"}, "armed": True})
        self.assertEqual(r["state_after"], {"dropped": True})
        self.assertIsInstance(r["latency_ms"], int)

    def test_a_reset_with_nothing_open_is_one_row_dropped_false(self):
        code, got = self.post("/chat/reset", {"by": "Johnny"})   # no question open, no listener has ever beaten
        self.assertEqual((code, got), (200, {"ok": True, "dropped": False, "pending_was": None}))
        self.assertTrue(self.flag.exists(), "the flag is written anyway: the listener may still be armed")
        (r,) = self.new_rows()
        self.assertEqual((r["tool"], r["ok"], r["args"]), ("chat.reset", True, {"by": "Johnny"}))
        self.assertEqual((r["state_before"], r["state_after"]), ({"pending": None, "armed": None}, {"dropped": False}))


if __name__ == "__main__":
    unittest.main()
