"""B10 · the API never returns a phone number or an email. Run: python -m unittest wtdd.test_api_private -v
GET /chat, /evals, /record, /record/shifts and /ledger answer from rows and files that carry the housemates' handles
(args.from, args.text, args.guid, a flag's to and resolved.by, the heartbeat's armed_by, an eval's detail). Every
string value in their JSON with a phone handle (+digits) or an email reads "a member" (the listener's PRIVATE pattern),
walked over the parsed JSON: keys and numbers are never touched, and ids carrying 10-digit epoch seconds come back byte
for byte. The ledger file itself stays raw. The real handler on an ephemeral port in this process; the ledger is
WTDD_LEDGER set before wtdd.ledger is imported, listen.json and evals.json are temp files (api.ROOT patched). Handles
are stand-ins, never real ones."""
from __future__ import annotations
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-api-private-test-"))
LEDGER = _TMP / "ledger.jsonl"
os.environ["WTDD_LEDGER"] = str(LEDGER)

from wtdd import api  # noqa: E402

PHONE, EMAIL, SID = "+15550002222", "sam@example.com", "2026-09-27"
ONE = f"any;-;{PHONE}"
IDS = ("eval-claim-1790481401", "cam:lap1:1790000100", "intruder-1790481401", "run-1790481401", "MSG-1790481401")


def _row(ts, tool, args, after=None, run_id="run-1790481401"):
    return {"ts": ts, "run_id": run_id, "cached": True, "source": "stub", "step": tool, "agent": "central", "tool": tool,
            "app": "imessage", "args": args, "state_before": None, "state_after": after, "ok": True,
            "response_or_error": None, "latency_ms": 0}


ROWS = [
    _row("2026-09-27T21:14:08", "chat.post", {"guid": ONE, "kind": "escalate", "trigger": "intruder-1790481401",
                                              "text": "who dis?!", "file": "look-sit.jpg", "shift_id": SID},
         {"guid": "MSG-1790481401", "rowid": 1790000100, "ts": "2026-09-28 04:14:12"}),
    _row("2026-09-27T21:14:24", "intruder.verdict", {"from": PHONE, "text": f"its {EMAIL}, call {PHONE}", "guid": "MSG-1790481401",
                                                     "asked": "intruder-1790481401", "acked_ms": 12000, "shift_id": SID, "chat": ONE},
         {"verdict": "known", "meaning": "known", "p": 0.9, "action": "stand_down"}),
    _row("2026-09-27T21:15:00", "chat.correction", {"from": EMAIL, "text": "thats a tarp", "chat": ONE, "shift_id": SID, "acked_ms": 3000,
                                                    "corrects": {"at": "2026-09-27T21:14:08", "said": "a cup"}}),
    _row("2026-09-27T21:16:00", "chat.claim", {"trigger": "cam:lap1:1790000100"}, {"trigger": "cam:lap1:1790000100", "claimed": True},
         run_id="eval-claim-1790481401"),
]


class Private(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        LEDGER.write_text("".join(json.dumps(r) + "\n" for r in ROWS))
        cls.raw = LEDGER.read_bytes()
        cls.root = Path(tempfile.mkdtemp(dir=_TMP))
        (cls.root / "listen.json").write_text(json.dumps({"t": time.time(), "guid": "any;+;0000", "armed": True, "armed_by": PHONE,
                                                          "dry": True, "pending": False, "last_rowid": 1790000100}))
        (cls.root / "evals.json").write_text(json.dumps({"written": "2026-09-27 21:20", "rows": [
            {"scenario": "escalate", "trial": 1, "grade": "pass", "seconds": 0.4, "why": "",
             "detail": f"1 flag(s) to {ONE}; reply by {PHONE} in 12000 ms ('its {EMAIL}'); claim('eval-claim-1790481401')"}]}))
        cls.patch = mock.patch.object(api, "ROOT", cls.root)
        cls.patch.start()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.patch.stop()

    def get(self, path: str) -> tuple[str, object]:
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            self.assertEqual(r.status, 200, path)
            text = r.read().decode()
        return text, json.loads(text)

    def test_no_route_returns_a_phone_or_an_email(self):
        for path in ("/chat", "/evals", f"/record?shift={SID}", "/record/shifts", "/ledger?n=50"):
            with self.subTest(path):
                text, _ = self.get(path)
                for private in (PHONE, PHONE[1:], EMAIL, "example.com"):
                    self.assertNotIn(private, text, path)

    def test_handles_read_a_member_and_nothing_else_moves(self):
        _, chat = self.get("/chat")
        self.assertEqual(chat["armed_by"], "a member")
        _, rec = self.get(f"/record?shift={SID}")
        (f,) = rec["flags"]
        self.assertEqual((f["to"], f["trigger"], f["resolved"]["by"], f["resolved"]["acked_ms"]), ("any;-;a member", "intruder-1790481401", "a member", 12000))
        self.assertEqual(f["resolved"]["text"], "its a member, call a member")
        self.assertEqual(rec["corrections"][0]["by"], "a member")
        _, ledger = self.get("/ledger?n=50")
        self.assertEqual(len(ledger), len(ROWS))
        v = ledger[1]
        self.assertEqual((v["args"]["from"], v["args"]["chat"], v["args"]["acked_ms"], v["state_after"]["p"]), ("a member", "any;-;a member", 12000, 0.9))
        self.assertEqual(ledger[0]["state_after"]["rowid"], 1790000100)
        self.assertEqual(sorted(ledger[1]["args"]), sorted(ROWS[1]["args"]))   # keys are never touched
        _, ev = self.get("/evals")
        self.assertEqual((ev["rows"][0]["trial"], ev["rows"][0]["seconds"]), (1, 0.4))
        self.assertEqual(ev["rows"][0]["detail"], "1 flag(s) to any;-;a member; reply by a member in 12000 ms ('its a member'); claim('eval-claim-1790481401')")

    def test_ids_with_epoch_seconds_come_back_byte_for_byte(self):
        text, ledger = self.get("/ledger?n=50")
        for i in IDS:
            self.assertIn(i, text)
        self.assertEqual([r["run_id"] for r in ledger], [r["run_id"] for r in ROWS])
        self.assertEqual(ledger[3]["args"]["trigger"], "cam:lap1:1790000100")
        self.assertEqual(ledger[0]["state_after"]["guid"], "MSG-1790481401")

    def test_the_ledger_file_stays_raw(self):
        for path in ("/ledger?n=50", f"/record?shift={SID}"):
            self.get(path)
        self.assertEqual(LEDGER.read_bytes(), self.raw)
        self.assertIn(PHONE.encode(), self.raw)


if __name__ == "__main__":
    unittest.main()
