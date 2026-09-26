"""Item 03, one named person: the flag goes to the on-call handle (a 1:1 chat, never the group, never a third chat),
the reply time is a logged field (acked_ms), and record.signed closes the shift once. Run:
    python -m unittest wtdd.chat.test_oncall -v
Offline like test_chat: a scratch ledger and memory.db via WTDD_LEDGER / WTDD_MEMORY (set before wtdd.ledger is
imported), a fake WTDD_CHAT_GUID, a fake on-call person (WTDD_ON_CALL_NAME / WTDD_ON_CALL_HANDLE, E.164-shaped, not a
real handle), WTDD_SHIFT pinned. osascript is stubbed to fail loudly; chat.db is read only where test_chat reads it
(the gate's lookups are patched so no 1:1 chat has to exist on this Mac). The listener's runtime files (pending.json,
state.json, listen.json) are pointed at the scratch dir. The fixture wtdd/chat/fixtures/oncall-shift.jsonl is one
shift's rows as this item writes them, every row labeled cached=true source="stub" (no fixture row claims to be live).

Clock for acked_ms: both ends are chat.db's clock, UTC, one-second resolution: the post's confirmed from-me row
(chat.post state_after.ts) and the reply's ts_utc. Never the ledger's local ts (7 h off in PT). So acked_ms is a
multiple of 1000 and is honest about it; a reply earlier than its post is a clock fault and raises."""
from __future__ import annotations
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-oncall-test-"))
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_CHAT_GUID"] = "any;+;00000000000000000000000000000000"
os.environ["WTDD_CHAT_NAME"] = "wtdd test"
os.environ["WTDD_ON_CALL_NAME"] = "Sam Stand-in"
os.environ["WTDD_ON_CALL_HANDLE"] = "+15550002222"
os.environ["WTDD_SHIFT"] = "2026-09-27"
os.environ["WTDD_WAKE_SHOW"] = "0"
os.environ["WTDD_AGENT"] = "0"
os.environ["WTDD_ALLOW_SELF"] = "0"
os.environ["WTDD_ALARM"] = "1"

from wtdd import ledger, numbers, tools  # noqa: E402
from wtdd.chat import __main__ as cli, db, listen as L, memory, send  # noqa: E402

GROUP = os.environ["WTDD_CHAT_GUID"]
NAME = "Sam Stand-in"
HANDLE = "+15550002222"
ONCALL = f"any;-;{HANDLE}"                 # a 1:1 chat on this Mac: guid any;-;<handle>, display_name '', one member
OTHER = "any;-;+15550009999"               # another 1:1 chat: never a target
CASTLE = "any;+;9dc250e675d447a888c6287339f429e0"
SHIFT = "2026-09-27"
FIXTURE = Path(__file__).parent / "fixtures" / "oncall-shift.jsonl"


def _oncall():
    """The module this item builds (wtdd/chat/oncall.py); imported per test so RED shows every check, not one ImportError."""
    from wtdd.chat import oncall
    return oncall


def _no_osascript(script: str) -> None:
    raise AssertionError("osascript must not run in tests: " + script[:60])


def _fixture_rows() -> list[dict]:
    return [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]


def _members(guid: str) -> list[str]:
    """Stand-in for chat.db's chat_handle_join: the on-call 1:1 exists with exactly the on-call handle; nothing else does."""
    return [HANDLE] if guid == ONCALL else []


def _msg(guid: str, text: str, chat: str, ts_utc: str = "2026-09-27 12:18:22", sender: str = HANDLE) -> dict:
    return {"rowid": 7, "guid": guid, "text": text, "is_from_me": 0, "sender": sender, "ts_utc": ts_utc,
            "attachments": [], "chat": chat}


class Fixture(unittest.TestCase):
    def test_every_fixture_row_is_labeled_stub(self):
        rows = _fixture_rows()
        self.assertEqual(len(rows), 6)
        for r in rows:
            self.assertIs(r["cached"], True, r["tool"])
            self.assertEqual(r["source"], "stub", r["tool"])
        self.assertEqual([r["tool"] for r in rows],
                         ["chat.gate", "chat.claim", "chat.post", "intruder.verdict", "chat.correction", "record.signed"])


class Person(unittest.TestCase):
    def test_person_is_name_handle_and_the_one_to_one_guid(self):
        self.assertEqual(_oncall().person(), {"name": NAME, "handle": HANDLE, "guid": ONCALL})

    def test_person_fails_loud_when_the_handle_is_unset(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("WTDD_ON_CALL_HANDLE", None)
            with self.assertRaises(RuntimeError) as cm:
                _oncall().person()
        self.assertIn("WTDD_ON_CALL_HANDLE", str(cm.exception))

    def test_shift_id_is_env_else_today(self):
        self.assertEqual(_oncall().shift_id(), SHIFT)
        with mock.patch.dict(os.environ):
            os.environ.pop("WTDD_SHIFT", None)
            self.assertEqual(_oncall().shift_id(), time.strftime("%Y-%m-%d"))


class Gate(unittest.TestCase):
    """The allow-set is exactly two targets: the group (guid + chat.db display_name) and the on-call 1:1 (guid + its one
    chat.db member handle). Every other guid is refused before anything is claimed or sent, with a chat.gate row."""

    def setUp(self):
        self._real = send._osascript
        send._osascript = _no_osascript

    def tearDown(self):
        send._osascript = self._real

    def test_on_call_target_passes_when_that_chat_is_the_one_handle(self):
        with mock.patch.object(db, "chat_members", side_effect=_members):
            send.gate(ONCALL)
            cli.gate(ONCALL)
        row = [r for r in ledger.rows() if r["tool"] == "chat.gate" and r["args"]["guid"] == ONCALL][-1]
        self.assertTrue(row["ok"])
        self.assertEqual(row["state_after"], {"guid": ONCALL, "name": NAME})

    def test_on_call_target_refused_when_that_chat_has_another_member(self):
        with mock.patch.object(db, "chat_members", return_value=["+15550009999"]):
            with self.assertRaises(PermissionError) as cm:
                send.gate(ONCALL)
        self.assertIn(HANDLE, str(cm.exception))

    def test_on_call_target_refused_when_no_such_chat(self):
        with mock.patch.object(db, "chat_members", return_value=[]):
            with self.assertRaises(PermissionError):
                send.gate(ONCALL)

    def test_on_call_target_refused_when_no_person_is_configured(self):
        with mock.patch.dict(os.environ), mock.patch.object(db, "chat_members", side_effect=_members):
            os.environ.pop("WTDD_ON_CALL_HANDLE", None)
            with self.assertRaises(PermissionError):
                send.gate(ONCALL)

    def test_third_guid_refused_before_claim_with_a_receipt(self):
        with mock.patch.object(db, "chat_members", side_effect=_members):
            for guid in (OTHER, CASTLE):
                with self.assertRaises(PermissionError):
                    cli.post(guid, f"t-third-{guid[-4:]}", "escalate", text="who dis?!")
        with memory.connect() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM posts WHERE trigger_guid LIKE 't-third-%'").fetchone())
        for guid in (OTHER, CASTLE):
            row = [r for r in ledger.rows() if r["tool"] == "chat.gate" and r["args"]["guid"] == guid][-1]
            self.assertFalse(row["ok"])
            self.assertIn("refused", row["response_or_error"])
        self.assertFalse(any(r["tool"] == "chat.post" and r["args"]["guid"] in (OTHER, CASTLE) for r in ledger.rows()))

    def test_transport_refuses_another_one_to_one(self):
        with mock.patch.object(db, "chat_members", side_effect=_members):
            with self.assertRaises(PermissionError):
                send.send_text(OTHER, "who dis?!")
            with self.assertRaises(PermissionError):
                send.send_file(OTHER, __file__)

    def test_group_gate_unchanged(self):
        # test_chat.Gate pins the group; here only that the on-call set did not loosen it: the fake group guid still refuses.
        with mock.patch.object(db, "chat_members", side_effect=_members):
            with self.assertRaises(PermissionError):
                send.gate(GROUP)


class Escalate(unittest.TestCase):
    """The listener's flag goes to the on-call guid with kind "escalate", carrying the photo; the group is not the target."""

    def setUp(self):
        self.posts: list[tuple] = []
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener(GROUP, lambda g, k, kind, t, f: self.posts.append((g, k, kind, t, f)), listen_s=60)
        self.l.allowed = lambda m: True

    def test_escalate_posts_to_the_on_call_not_the_group(self):
        self.l.escalate("alarm:g1:11", "who dis?!", "/tmp/look-level-boxed.jpg")
        self.assertEqual(self.posts, [(ONCALL, "alarm:g1:11", "escalate", "who dis?!", "/tmp/look-level-boxed.jpg")])

    def test_look_and_say_flags_the_on_call_with_the_photo(self):
        seen = {"text": "someone by the trench cover", "file": "/tmp/look-level-boxed.jpg", "person": True,
                "detector": {"classes": ["person"]}}
        with mock.patch("wtdd.tools.dog_say.look_and_see", return_value=seen), \
             mock.patch.object(L, "PENDING", _TMP / "pending.json"), \
             mock.patch.object(self.l, "await_verdict", return_value=False):
            self.l.look_and_say({"guid": "g1", "sender": HANDLE, "text": "what the dog doin"})
        self.assertEqual(self.posts, [
            (GROUP, "say:g1", "listen", "someone by the trench cover", "/tmp/look-level-boxed.jpg"),
            (ONCALL, "alarm:g1", "escalate", "who dis?!", "/tmp/look-level-boxed.jpg"),
        ])
        pend = json.loads((_TMP / "pending.json").read_text())
        self.assertEqual(pend["trigger"], "alarm:g1")

    def test_escalation_is_claimed_once(self):
        confirmed = {"guid": "P-1", "rowid": 60001, "ts": "2026-09-27 12:18:10",
                     "caption": {"guid": "P-1c", "rowid": 60002, "ts": "2026-09-27 12:18:11"}}
        with mock.patch.object(db, "chat_members", side_effect=_members), \
             mock.patch.object(send, "_osascript", _no_osascript), \
             mock.patch.object(send, "send_file", return_value=confirmed) as sf:
            row = cli.post(ONCALL, "alarm:g2:11", "escalate", "who dis?!", "/tmp/look-level-boxed.jpg")
            self.assertEqual(row["rowid"], 60001)
            sf.assert_called_once_with(ONCALL, "/tmp/look-level-boxed.jpg", "who dis?!")
            with self.assertRaises(PermissionError):
                cli.post(ONCALL, "alarm:g2:11", "escalate", "who dis?!", "/tmp/look-level-boxed.jpg")
        claims = [r["ok"] for r in ledger.rows() if r["tool"] == "chat.claim" and r["args"]["trigger"] == "alarm:g2:11"]
        self.assertEqual(claims, [True, False])
        posts = [r for r in ledger.rows() if r["tool"] == "chat.post" and r["args"]["trigger"] == "alarm:g2:11"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["args"]["guid"], ONCALL)
        self.assertEqual(posts[0]["args"]["kind"], "escalate")
        self.assertEqual(posts[0]["state_after"]["ts"], "2026-09-27 12:18:10")

    def test_poll_reads_the_on_call_chat_and_tags_the_chat(self):
        reply = {"rowid": 9, "guid": "R-9", "text": "thats my friend", "is_from_me": 0, "sender": HANDLE,
                 "ts_utc": "2026-09-27 12:18:22", "attachments": []}
        seen: list[dict] = []
        with mock.patch.object(L.db, "new_messages", side_effect=lambda guid, after: [dict(reply)] if guid == ONCALL else []) as nm, \
             mock.patch.object(L, "HEARTBEAT", _TMP / "listen.json"), \
             mock.patch.object(L, "PENDING", _TMP / "pending-none.json"), \
             mock.patch.object(self.l, "handle", side_effect=seen.append):
            n = self.l.poll()
        self.assertEqual(n, 1)
        self.assertEqual(sorted(c.args[0] for c in nm.call_args_list), sorted([GROUP, ONCALL]))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["guid"], "R-9")
        self.assertEqual(seen[0]["chat"], ONCALL)

    def test_the_on_call_chat_does_not_wake_the_dog(self):
        with mock.patch.object(L, "PENDING", _TMP / "pending-none.json"), mock.patch.object(L, "STATE", _TMP / "state.json"):
            self.l.handle(_msg("W-1", "what the dog doin", ONCALL))
        self.assertFalse(self.l.armed)
        self.assertEqual(self.posts, [])


class Acked(unittest.TestCase):
    """acked_ms: the post's confirmed chat.db time to the reply's chat.db time, on the rows that carry the reply."""

    def test_acked_ms_from_fixture_rows(self):
        o = _oncall()
        post = o.post_for("alarm:FIX-1:11", _fixture_rows())
        self.assertEqual(post["tool"], "chat.post")
        self.assertEqual(o.acked_ms(post, "2026-09-27 12:18:22"), 12000)

    def test_same_second_is_zero_and_earlier_raises(self):
        o = _oncall()
        post = o.post_for("alarm:FIX-1:11", _fixture_rows())
        self.assertEqual(o.acked_ms(post, "2026-09-27 12:18:10"), 0)
        with self.assertRaises(ValueError):
            o.acked_ms(post, "2026-09-27 12:18:09")

    def test_post_for_unknown_trigger_is_none(self):
        self.assertIsNone(_oncall().post_for("alarm:nope", _fixture_rows()))

    def test_verdict_row_carries_acked_ms_and_shift(self):
        posts: list[tuple] = []
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            l = L.Listener(GROUP, lambda g, k, kind, t, f: posts.append((g, k, kind, t, f)), listen_s=60)
        l.allowed = lambda m: True
        ledger.append({"step": "chat.post", "agent": "central", "tool": "chat.post", "app": "imessage", "ok": True,
                       "args": {"guid": ONCALL, "kind": "escalate", "trigger": "alarm:g3:11", "text": "who dis?!", "file": "/tmp/f.jpg"},
                       "state_before": {"max_rowid": 1}, "state_after": {"guid": "P-3", "rowid": 2, "ts": "2026-09-27 12:18:10"},
                       "response_or_error": None, "latency_ms": 900})
        pend = _TMP / "pending-3.json"
        pend.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "file": "/tmp/f.jpg", "seconds": 5, "trigger": "alarm:g3:11"}))
        with mock.patch.object(L, "PENDING", pend):
            self.assertTrue(l.verdict(_msg("R-3", "thats my friend", ONCALL, "2026-09-27 12:18:22")))
        self.assertFalse(pend.exists())
        row = [r for r in ledger.rows() if r["tool"] == "intruder.verdict"][-1]
        self.assertEqual(row["args"]["asked"], "alarm:g3:11")
        self.assertEqual(row["args"]["acked_ms"], 12000)
        self.assertEqual(row["args"]["shift_id"], SHIFT)
        self.assertEqual(row["state_after"]["verdict"], "known")
        self.assertEqual(posts[-1][0], ONCALL)              # "ok, standing down" goes back to the chat that answered
        self.assertEqual(posts[-1][1], "ok:R-3")
        self.assertEqual(posts[-1][3], "ok, standing down")

    def test_correction_row_carries_acked_ms_and_shift(self):
        posts: list[tuple] = []
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            l = L.Listener(GROUP, lambda g, k, kind, t, f: posts.append((g, k, kind, t, f)), listen_s=60)
        l.allowed = lambda m: True
        ledger.append({"step": "chat.post", "agent": "central", "tool": "chat.post", "app": "imessage", "ok": True,
                       "args": {"guid": ONCALL, "kind": "escalate", "trigger": "alarm:g4:11", "text": "who dis?!", "file": "/tmp/look-4.jpg"},
                       "state_before": {"max_rowid": 1}, "state_after": {"guid": "P-4", "rowid": 4, "ts": "2026-09-27 12:20:00"},
                       "response_or_error": None, "latency_ms": 900})
        with mock.patch.object(L, "STATE", _TMP / "state-4.json"), mock.patch.object(L, "PENDING", _TMP / "pending-none.json"):
            self.assertTrue(l.correction(_msg("R-4", "thats a tarp not a person", ONCALL, "2026-09-27 12:20:20")))
        row = [r for r in ledger.rows() if r["tool"] == "chat.correction"][-1]
        self.assertEqual(row["args"]["corrects"]["file"], "look-4.jpg")
        self.assertEqual(row["args"]["acked_ms"], 20000)
        self.assertEqual(row["args"]["shift_id"], SHIFT)
        self.assertEqual(posts[-1][0], ONCALL)              # "noted: ..." goes back to the chat that answered
        self.assertTrue(posts[-1][3].startswith("noted:"))


class Sign(unittest.TestCase):
    """record_sign: one record.signed {by, at, shift_id} row closes the shift; a second sign of the same shift is refused
    with its own ok=false row. The shift is closed when the ledger says so, never from the tool's own report."""

    def test_tool_is_listed(self):
        self.assertIn("record_sign", tools.registry())

    def test_signed_row_shape(self):
        out = tools.call("record_sign", by=NAME, shift_id="2026-09-30")
        self.assertEqual(out["by"], NAME)
        self.assertEqual(out["shift_id"], "2026-09-30")
        self.assertRegex(out["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertIs(out["signed"], True)
        row = ledger.rows()[-1]
        self.assertEqual(row["tool"], "record.signed")
        self.assertTrue(row["ok"])
        self.assertEqual(row["args"], {"by": NAME, "at": out["at"], "shift_id": "2026-09-30"})
        self.assertIs(row["state_before"]["signed"], False)
        self.assertIs(row["state_after"]["signed"], True)
        self.assertEqual(row["cached"], False)
        self.assertEqual(row["source"], "live")
        self.assertEqual(_oncall().signed("2026-09-30")["args"]["by"], NAME)

    def test_second_sign_of_the_same_shift_is_refused(self):
        tools.call("record_sign", by=NAME, shift_id="2026-10-01")
        with self.assertRaises(PermissionError) as cm:
            tools.call("record_sign", by="Someone Else", shift_id="2026-10-01")
        self.assertIn("already signed", str(cm.exception))
        rows = [r for r in ledger.rows() if r["tool"] == "record.signed" and r["args"]["shift_id"] == "2026-10-01"]
        self.assertEqual([r["ok"] for r in rows], [True, False])
        self.assertIn("already signed", rows[1]["response_or_error"])
        self.assertEqual(_oncall().signed("2026-10-01")["args"]["by"], NAME)

    def test_by_and_shift_default_to_the_on_call_name_and_the_shift_env(self):
        out = tools.call("record_sign")
        self.assertEqual((out["by"], out["shift_id"]), (NAME, SHIFT))

    def test_unsigned_shift_is_none(self):
        self.assertIsNone(_oncall().signed("1999-01-01"))


class Numbers(unittest.TestCase):
    """python -m wtdd.numbers reports, per shift, the acked_ms values and whether the shift is signed, read from rows."""

    def test_shifts_from_fixture(self):
        s = numbers.shifts(_fixture_rows())
        self.assertEqual(s, [{"shift_id": SHIFT, "flags": 1, "acked_ms": [12000, 20000], "signed": True, "signed_by": NAME}])

    def test_unsigned_shift_from_fixture(self):
        rows = [r for r in _fixture_rows() if r["tool"] != "record.signed"]
        self.assertEqual(numbers.shifts(rows), [{"shift_id": SHIFT, "flags": 1, "acked_ms": [12000, 20000], "signed": False, "signed_by": None}])

    def test_no_rows_is_no_shifts(self):
        self.assertEqual(numbers.shifts([]), [])


if __name__ == "__main__":
    unittest.main()
