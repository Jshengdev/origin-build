"""Local checks that never touch osascript or send anything. Run: python -m unittest wtdd.chat.test_chat -v
Uses a scratch memory.db and ledger via WTDD_MEMORY / WTDD_LEDGER (set before the ledger is imported, so the real file
is never touched) and a fake WTDD_CHAT_GUID. The Db case reads the real chat.db (read-only)."""
from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="wtdd-chat-test-")
os.environ["WTDD_MEMORY"] = str(Path(_TMP) / "memory.db")
os.environ["WTDD_LEDGER"] = str(Path(_TMP) / "ledger.jsonl")
os.environ["WTDD_CHAT_GUID"] = "any;+;00000000000000000000000000000000"

from wtdd import ledger  # noqa: E402
from wtdd.chat import __main__ as cli, db, memory, send  # noqa: E402

CASTLE = "any;+;9dc250e675d447a888c6287339f429e0"
FAKE = os.environ["WTDD_CHAT_GUID"]


def _no_osascript(script: str) -> None:
    raise AssertionError("osascript must not run in tests: " + script[:60])


class Escape(unittest.TestCase):
    def test_backslash_then_quote(self):
        self.assertEqual(send.escape('a"b\\c'), 'a\\"b\\\\c')

    def test_text_script_shape(self):
        s = send.script_text(FAKE, 'say "hi"')
        self.assertEqual(s.splitlines(), [
            'tell application "Messages"',
            f'    set targetChat to chat id "{FAKE}"',
            '    send "say \\"hi\\"" to targetChat',
            'end tell',
        ])

    def test_file_script_shape(self):
        s = send.script_file(FAKE, Path("/Users/johnnysheng/Pictures/wtdd/frame-1.jpg"))
        self.assertEqual(s.splitlines(), [
            'tell application "Messages"',
            f'    set targetChat to chat id "{FAKE}"',
            '    set theFile to (POSIX file "/Users/johnnysheng/Pictures/wtdd/frame-1.jpg") as alias',
            '    send theFile to targetChat',
            '    delay 3',
            'end tell',
        ])

    def test_file_script_with_caption(self):
        s = send.script_file(FAKE, Path("/Users/johnnysheng/Pictures/wtdd/f.jpg"), "cap")
        self.assertIn('    send "cap" to targetChat', s.splitlines()[-2])


class Gate(unittest.TestCase):
    """Every post goes through cli.post, which gates before it claims or sends; send_text/send_file gate again
    on their own, so the transport refuses a direct caller too. _osascript is stubbed to fail loudly."""

    def setUp(self):
        self._real = send._osascript
        send._osascript = _no_osascript

    def tearDown(self):
        send._osascript = self._real

    def test_castle_is_not_the_configured_guid(self):
        with self.assertRaises(PermissionError):
            cli.post(CASTLE, "t-gate-1", "send", text="x")

    def test_configured_guid_must_carry_the_target_name(self):
        # FAKE is WTDD_CHAT_GUID but no chat in chat.db carries that guid, so the name check refuses it too.
        with self.assertRaises(PermissionError) as cm:
            cli.post(FAKE, "t-gate-2", "send", text="x")
        self.assertIn(send.TARGET_NAME, str(cm.exception))

    def test_guid_and_name_must_both_match_the_one_target(self):
        # The gate allows exactly one group: guid == WTDD_CHAT_GUID and its chat.db name == TARGET_NAME.
        # Pointing the guid at the castle while the target name is something else must refuse.
        os.environ["WTDD_CHAT_GUID"] = CASTLE
        real_name = send.TARGET_NAME
        send.TARGET_NAME = "wtdd test"
        try:
            with self.assertRaises(PermissionError) as cm:
                cli.post(CASTLE, "t-gate-3", "photo", file=__file__)
            self.assertIn("THE CASTLE", str(cm.exception))
            # And with the target name set to the castle (Johnny's explicit choice on 2026-09-13), the gate passes.
            send.TARGET_NAME = "THE CASTLE"
            send.gate(CASTLE)
        finally:
            send.TARGET_NAME = real_name
            os.environ["WTDD_CHAT_GUID"] = FAKE

    def test_transport_refuses_castle_text(self):
        with self.assertRaises(PermissionError):
            send.send_text(CASTLE, "x")

    def test_transport_refuses_unnamed_configured_guid(self):
        with self.assertRaises(PermissionError):
            send.send_text(FAKE, "x")

    def test_transport_refuses_castle_file(self):
        with self.assertRaises(PermissionError):
            send.send_file(CASTLE, __file__)

    def test_post_refuses_before_claiming_and_leaves_a_receipt(self):
        with self.assertRaises(PermissionError):
            cli.post(CASTLE, "t-castle", "send", text="x")
        with memory.connect() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM posts WHERE trigger_guid = 't-castle'").fetchone())
        row = [r for r in ledger.rows() if r["tool"] == "chat.gate" and r["args"]["guid"] == CASTLE][-1]
        self.assertFalse(row["ok"])
        self.assertIn("refused: " + CASTLE, row["response_or_error"])
        self.assertFalse(any(r["tool"] == "chat.post" for r in ledger.rows()))


class Claim(unittest.TestCase):
    def test_claim_once(self):
        self.assertTrue(memory.claim("trig-1"))
        self.assertFalse(memory.claim("trig-1"))
        memory.confirm("trig-1", "p-guid-1")
        with memory.connect() as c:
            r = c.execute("SELECT posted_guid, confirmed_at FROM posts WHERE trigger_guid = 'trig-1'").fetchone()
        self.assertEqual(r["posted_guid"], "p-guid-1")
        self.assertIsNotNone(r["confirmed_at"])

    def test_confirm_without_claim_raises(self):
        with self.assertRaises(RuntimeError):
            memory.confirm("never-claimed", "p")

    def test_cli_claim_refusal_is_a_ledger_row(self):
        cli.claim("trig-2")
        with self.assertRaises(PermissionError):
            cli.claim("trig-2")
        rows = [r for r in ledger.rows() if r["tool"] == "chat.claim" and r["args"]["trigger"] == "trig-2"]
        self.assertEqual([r["ok"] for r in rows], [True, False])
        self.assertIn("already claimed", rows[1]["response_or_error"])


class Spam(unittest.TestCase):
    def test_cap_and_suffix(self):
        plan = cli.spam_plan("t", "hello", 25)
        self.assertEqual(len(plan), cli.SPAM_CAP)
        self.assertEqual(plan[0], ("t#1", "hello (1/10)"))
        self.assertEqual(plan[-1], ("t#10", "hello (10/10)"))

    def test_small_n(self):
        self.assertEqual(cli.spam_plan("t", "x", 3), [("t#1", "x (1/3)"), ("t#2", "x (2/3)"), ("t#3", "x (3/3)")])


class Compose(unittest.TestCase):
    def test_messages_shape_for_wtdd_llm(self):
        msgs = cli.compose("## chat\n[07:00] dog: on it", "what the dog doin")
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])
        self.assertEqual(msgs[0]["content"], cli.SYSTEM)
        self.assertIn("## the ask\nwhat the dog doin", msgs[1]["content"])
        self.assertIn("[07:00] dog: on it", msgs[1]["content"])


MSGS = [
    {"rowid": 1, "guid": "g1", "text": "what the dog doin", "is_from_me": 0, "sender": "+15550001111",
     "ts_utc": "2026-09-13 07:00:00", "attachments": []},
    {"rowid": 2, "guid": "g2", "text": None, "is_from_me": 0, "sender": "+15550001111",
     "ts_utc": "2026-09-13 07:00:05", "attachments": ["/tmp/a.png"]},
    {"rowid": 3, "guid": "g3", "text": "on it", "is_from_me": 1, "sender": "",
     "ts_utc": "2026-09-13 07:00:09", "attachments": []},
]


class Memory(unittest.TestCase):
    def setUp(self):
        memory.store("chat-A", MSGS)   # idempotent on guid, so every test sees the same three rows

    def test_store_is_idempotent(self):
        self.assertEqual(memory.store("chat-A", MSGS), 0)

    def test_context(self):
        ctx = memory.context("chat-A")
        self.assertIn("[07:00] +15550001111: what the dog doin", ctx)
        self.assertIn("[07:00] +15550001111: [non-text] [photo]", ctx)
        self.assertIn("[07:00] dog: on it", ctx)
        self.assertIn("## what the dog did", ctx)
        self.assertIn("## what was reported", ctx)
        self.assertIn("## state", ctx)
        self.assertNotIn("+15550001111: what the dog doin", memory.context("chat-B"))   # no cross-chat leak (the chat line, not a ledger row)

    def test_last_trigger_needs_known_housemate(self):
        self.assertIsNone(memory.last_trigger("chat-A", {}))
        t = memory.last_trigger("chat-A", {"+15550001111": "A"})
        self.assertEqual(t["guid"], "g1")


class Db(unittest.TestCase):
    def test_read_only_and_castle_name(self):
        self.assertGreater(db.max_rowid(), 0)
        self.assertEqual(db.chat_name(CASTLE), "THE CASTLE")
        self.assertIsNone(db.chat_name(FAKE))


if __name__ == "__main__":
    unittest.main()
