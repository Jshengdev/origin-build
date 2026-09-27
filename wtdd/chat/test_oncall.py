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
# what dog_say.look_and_see returns beside the look since 02: every stop carries its decision (17 adds the action)
DECISION = {"label": "person", "p": 0.95, "needs_person": False, "model": "stub", "action": "escalate"}


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
                "detector": {"classes": ["person"]}, "decision": DECISION}
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
        self.assertEqual(pend["chat"], ONCALL)             # the question names the chat that was asked; only it answers

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
        self.assertEqual(posts[0]["args"]["shift_id"], SHIFT)          # the live post carries the shift, as the fixture row shows
        self.assertEqual(posts[0]["state_after"]["ts"], "2026-09-27 12:18:10")

    def test_intruder_alarm_flags_the_on_call(self):
        # The detector-armed path (wtdd/watch.py -> POST /tools/intruder_alarm) is the same flag: photo + "who dis?!"
        # to the on-call 1:1, never the group. The look and the detector are stubbed; the send goes through the gate.
        from wtdd.config import ROOT
        self.addCleanup(lambda: (ROOT / "pending.json").unlink(missing_ok=True))   # the tool writes the listener's pending file
        confirmed = {"guid": "P-W", "rowid": 60011, "ts": "2026-09-27 12:30:10",
                     "caption": {"guid": "P-Wc", "rowid": 60012, "ts": "2026-09-27 12:30:11"}}
        before = len(ledger.rows())   # only this tool's rows are read below: another test's group post is not its post
        with mock.patch("wtdd.commands.look", return_value={"file": "/tmp/look-level.jpg", "pitch_deg": 0.4}), \
             mock.patch("wtdd.tools.dog_say.boxed", return_value={"file": "/tmp/look-level-boxed.jpg", "n": 1, "classes": {"person": 1}}), \
             mock.patch.object(db, "chat_members", side_effect=_members), \
             mock.patch.object(send, "_osascript", _no_osascript), \
             mock.patch.object(send, "send_file", return_value=confirmed) as sf:
            out = tools.call("intruder_alarm", trigger="alarm:watch-1")
        self.assertIs(out["pending"], True)
        self.assertEqual(out["post"]["rowid"], 60011)
        sf.assert_called_once_with(ONCALL, "/tmp/look-level-boxed.jpg", "who dis?!")
        post = [r for r in ledger.rows() if r["tool"] == "chat.post" and r["args"]["trigger"] == "alarm:watch-1"][-1]
        self.assertEqual((post["args"]["guid"], post["args"]["kind"], post["args"]["text"], post["args"]["file"]),
                         (ONCALL, "escalate", "who dis?!", "/tmp/look-level-boxed.jpg"))
        self.assertFalse(any(r["tool"] in ("chat.gate", "chat.post") and r["args"]["guid"] == GROUP for r in ledger.rows()[before:]))
        self.assertEqual(json.loads((ROOT / "pending.json").read_text())["trigger"], "alarm:watch-1")

    def test_no_on_call_configured_is_posted_as_the_error_not_faked(self):
        # Fail loud, round goes on: like "couldn't look:", a flag with nobody to send it to is posted to the group as its
        # error under its own escalate-fail: key (alarm: can already be claimed by a flag whose send failed, see the next
        # test), no question is opened, the dog does not hold 45 s.
        seen = {"text": "someone by the trench cover", "file": "/tmp/look-level-boxed.jpg", "person": True,
                "detector": {"classes": ["person"]}, "decision": DECISION}
        with mock.patch.dict(os.environ), \
             mock.patch("wtdd.tools.dog_say.look_and_see", return_value=seen), \
             mock.patch.object(L, "PENDING", _TMP / "pending-5.json"), \
             mock.patch.object(self.l, "await_verdict", return_value=False) as av:
            os.environ.pop("WTDD_ON_CALL_HANDLE", None)
            self.l.look_and_say({"guid": "g5", "sender": HANDLE, "text": "what the dog doin"})
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(self.posts[0][:2], (GROUP, "say:g5"))
        guid, key, kind, text, file = self.posts[1]
        self.assertEqual((guid, key, file), (GROUP, "escalate-fail:g5", None))
        self.assertTrue(text.startswith("couldn't escalate: RuntimeError:"), text)
        self.assertIn("WTDD_ON_CALL_HANDLE", text)
        self.assertFalse((_TMP / "pending-5.json").exists())
        av.assert_not_called()

    def test_a_failed_flag_send_is_posted_under_its_own_key_and_the_round_goes_on(self):
        # The case the first live send checks: the gate and the claim pass, then osascript cannot resolve the 1:1 ("Can't
        # get chat id"). That claim consumed alarm:<k>, so the error goes to the group under escalate-fail:<k>, the real
        # error stays on the failed chat.post row, and look_and_say returns (field.walk's on_stop has no try around it):
        # no question opened, no hold, the round goes on.
        seen = {"text": "someone by the trench cover", "file": "/tmp/look-level-boxed.jpg", "person": True,
                "detector": {"classes": ["person"]}, "decision": DECISION}
        rowids = iter(range(60100, 60200))

        def confirmed(ts: str) -> dict:
            r = next(rowids)
            return {"guid": f"G-{r}", "rowid": r, "ts": ts, "caption": {"guid": f"G-{r}c", "rowid": r + 1000, "ts": ts}}

        def send_file(guid, file, text=None):
            if guid == ONCALL:
                raise RuntimeError('osascript rc=1: Messages got an error: Can\'t get chat id "any;-;+15550002222". (-1728)')
            return confirmed("2026-09-27 12:40:00")

        with mock.patch.object(db, "max_rowid", return_value=60000):
            l = L.Listener(GROUP, cli.post, listen_s=60)
        with mock.patch("wtdd.tools.dog_say.look_and_see", return_value=seen), \
             mock.patch.object(L, "PENDING", _TMP / "pending-9.json"), \
             mock.patch.object(l, "await_verdict", return_value=False) as av, \
             mock.patch.object(db, "chat_members", side_effect=_members), \
             mock.patch.object(db, "chat_name", side_effect=lambda g: send.TARGET_NAME if g == GROUP else None), \
             mock.patch.object(db, "max_rowid", return_value=60000), \
             mock.patch.object(send, "_osascript", _no_osascript), \
             mock.patch.object(send, "send_file", side_effect=send_file), \
             mock.patch.object(send, "send_text", side_effect=lambda g, t: confirmed("2026-09-27 12:40:05")) as st:
            l.look_and_say({"guid": "g9", "sender": HANDLE, "text": "what the dog doin"})   # returns: does not raise
        st.assert_called_once()
        self.assertEqual(st.call_args.args[0], GROUP)
        self.assertTrue(st.call_args.args[1].startswith("couldn't escalate: RuntimeError: osascript rc=1"), st.call_args.args[1])
        rows = ledger.rows()
        flag = [r for r in rows if r["tool"] == "chat.post" and r["args"]["trigger"] == "alarm:g9"]
        self.assertEqual([(r["ok"], r["args"]["guid"], r["args"]["kind"]) for r in flag], [(False, ONCALL, "escalate")])
        self.assertIn("Can't get chat id", flag[0]["response_or_error"])
        self.assertEqual([r["ok"] for r in rows if r["tool"] == "chat.claim" and r["args"]["trigger"] == "alarm:g9"], [True])
        err = [r for r in rows if r["tool"] == "chat.post" and r["args"]["trigger"] == "escalate-fail:g9"]
        self.assertEqual([(r["ok"], r["args"]["guid"]) for r in err], [(True, GROUP)])
        self.assertFalse((_TMP / "pending-9.json").exists())
        av.assert_not_called()

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


class Answers(unittest.TestCase):
    """Who may answer an open flag, through handle() and the real allowed() (never overridden here): only the on-call
    person's own words, in their 1:1, decide it. A from-me bubble in that chat (the dog's own "who dis?!" caption read
    back, or Johnny's phone on the dog's account under WTDD_ALLOW_SELF) and a message in the group are not the verdict.
    light_alarm is patched to fail the test if it ever sounds."""

    def setUp(self):
        self.posts: list[tuple] = []
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener(GROUP, lambda g, k, kind, t, f: self.posts.append((g, k, kind, t, f)), listen_s=60)
        self.trigger = f"alarm:{self._testMethodName}"
        self.pend = _TMP / f"pending-{self._testMethodName}.json"
        self.pend.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "file": "/tmp/f.jpg", "seconds": 5,
                                         "trigger": self.trigger, "chat": ONCALL}))
        self.addCleanup(lambda: self.pend.unlink(missing_ok=True))

    def _handle(self, m: dict, **env: str) -> None:
        with mock.patch.dict(os.environ, env), mock.patch.object(L, "PENDING", self.pend), \
             mock.patch.object(L, "STATE", _TMP / "state-answers.json"), \
             mock.patch("wtdd.tools.call", side_effect=AssertionError("the alarm must not sound in a test")):
            self.l.handle(m)

    def _verdicts(self) -> list[dict]:
        return [r for r in ledger.rows() if r["tool"] == "intruder.verdict" and r["args"]["asked"] == self.trigger]

    def test_a_from_me_bubble_in_the_one_to_one_is_not_the_answer(self):
        # chat.db gives a from-me row in a 1:1 the other party's handle, so the sender alone cannot tell them apart.
        own = {**_msg("D-1", "who dis?!", ONCALL), "is_from_me": 1}    # the dog's own caption, read back while it holds
        mine = {**_msg("D-2", "idk", ONCALL), "is_from_me": 1}        # typed on a phone signed in to the dog's account
        self._handle(own)
        self._handle(own, WTDD_ALLOW_SELF="1")
        self._handle(mine, WTDD_ALLOW_SELF="1")
        self.assertEqual(self._verdicts(), [])
        self.assertTrue(self.pend.exists())
        self.assertEqual(self.posts, [])

    def test_a_group_message_does_not_answer_the_on_call_flag(self):
        self._handle(_msg("G-1", "idk", GROUP, sender="+15550003333"))
        self.assertEqual(self._verdicts(), [])
        self.assertTrue(self.pend.exists())
        self.assertEqual(self.posts, [])
        self._handle(_msg("R-7", "thats my friend", ONCALL))             # then the person asked answers, and that closes it
        self.assertEqual([(r["args"]["chat"], r["state_after"]["verdict"]) for r in self._verdicts()], [(ONCALL, "known")])
        self.assertFalse(self.pend.exists())
        self.assertEqual(self.posts, [(ONCALL, "ok:R-7", "listen", "ok, standing down", None)])

    def test_the_on_call_person_answers_when_housemates_leaves_them_out(self):
        with mock.patch.dict(L.HOUSEMATES, {"+15550003333": "Ana"}):
            self._handle(_msg("R-8", "thats my friend", ONCALL))
        self.assertEqual(len(self._verdicts()), 1)
        self.assertEqual(self.posts, [(ONCALL, "ok:R-8", "listen", "ok, standing down", None)])


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

    def test_block_reports_shifts_from_the_ledger_env(self):
        # The command is `python -m wtdd.numbers` (the goal's `python -m wtdd numbers` is not a tool: KeyError). Its block
        # must read the ledger WTDD_LEDGER points at (today count() reads <repo>/ledger.jsonl and ignores it), so a shift
        # that exists only in this scratch ledger shows up, with its acked_ms and the word "unsigned" (item 10's word too).
        ledger.append({"step": "intruder.verdict", "agent": "central", "tool": "intruder.verdict", "app": "imessage", "ok": True,
                       "args": {"from": HANDLE, "text": "thats my friend", "guid": "R-29", "asked": "alarm:g29:11",
                                "acked_ms": 5000, "shift_id": "2026-09-29", "chat": ONCALL},
                       "state_before": None, "state_after": {"verdict": "known"}, "response_or_error": None, "latency_ms": 0})
        text = numbers.block()
        line = [l for l in text.splitlines() if "2026-09-29" in l]
        self.assertTrue(line, text)
        self.assertIn("5000", "\n".join(line))
        self.assertIn("unsigned", "\n".join(line))


if __name__ == "__main__":
    unittest.main()
