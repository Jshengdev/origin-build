"""Item 12, a channel adapter beyond iMessage: the on-call person can be on SMS; the same gate -> claim -> send ->
read-back post, the "who dis?!" question and the reply flow run through wtdd/chat/adapters/, with iMessage unchanged.
Run:
    python -m unittest wtdd.chat.test_adapters -v

Offline like test_oncall: a scratch ledger and memory.db via WTDD_LEDGER / WTDD_MEMORY (set before wtdd.ledger is
imported), a fake WTDD_CHAT_GUID, a fake on-call person, WTDD_SHIFT pinned, and WTDD_ON_CALL_CHANNEL=sms. The three
Twilio keys are set EMPTY here so config.maybe() sees none whatever .env says: the adapter under test is the
# DEMO_CACHE: stub (the one a worktree, and a judge without a Twilio account, gets). The live path is tested with
requests.post / requests.get patched: no test here ever reaches the network, osascript, or a real 1:1 chat.

The target string carries the channel: the group and the 1:1 are chat.db guids (any;+;..., any;-;<handle>) and go to
iMessage; the on-call person on SMS is `sms:<E.164>` (oncall.guid() forms it when WTDD_ON_CALL_CHANNEL=sms), and
adapters.for_target() picks the adapter, so post(guid, ...) keeps its signature for every caller (listener, tools,
CLI, API). The SMS adapter's gate admits exactly one target, sms:<WTDD_ON_CALL_HANDLE>; the iMessage gate refuses
sms: targets and, while the person is on SMS, their iMessage 1:1 too (one channel per person, never two).

Rows. Every adapter posts through chat/__main__.post: chat.gate and chat.post carry the adapter's app ("imessage" |
"sms"); a stub post's gate, claim and post rows and the reply rows it answers (intruder.verdict, chat.correction)
carry cached=true source="stub" (contract: no stub row ever claims to be live); live rows are untouched. An SMS
"rowid" is the message's date_sent as unix seconds (Twilio has no row ids); the watermark is the same unit. The
read-back is Twilio's own status on GET /Messages/<sid>.json: sent or delivered confirms, failed/undelivered raises
with Twilio's error code, queued past CONFIRM_S is an unconfirmed send (raised, never retried), exactly like an
iMessage from-me row that never lands.

Fixtures. wtdd/chat/fixtures/sms-thread.jsonl: three Twilio Message resources (the POST response queued, the GET
read-back sent, the inbound reply) in the documented 2010-04-01 shape, hand-written from the docs, UNVERIFIED against
a live account. wtdd/chat/fixtures/sms-shift.jsonl: the ledger rows one stub flag round writes, every row labeled."""
from __future__ import annotations
import contextlib
import io
import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-adapters-test-"))
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_CHAT_GUID"] = "any;+;00000000000000000000000000000000"
os.environ["WTDD_CHAT_NAME"] = "wtdd test"
os.environ["WTDD_ON_CALL_NAME"] = "Sam Stand-in"
os.environ["WTDD_ON_CALL_HANDLE"] = "+15550002222"
os.environ["WTDD_ON_CALL_CHANNEL"] = "sms"
os.environ["WTDD_SHIFT"] = "2026-09-27"
os.environ["WTDD_WAKE_SHOW"] = "0"
os.environ["WTDD_AGENT"] = "0"
os.environ["WTDD_ALLOW_SELF"] = "0"
os.environ["WTDD_ALARM"] = "1"
for _k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_MEDIA_BASE"):
    os.environ[_k] = ""   # empty = unset for config.maybe(); .env cannot override an existing (empty) variable

import requests  # noqa: E402  (already a dependency; patched below, never called)

from wtdd import ledger  # noqa: E402
from wtdd.chat import __main__ as cli, db, listen as L, memory, oncall, send  # noqa: E402

GROUP = os.environ["WTDD_CHAT_GUID"]
NAME = "Sam Stand-in"
HANDLE = "+15550002222"
SMS = f"sms:{HANDLE}"                       # the on-call person on SMS
ONE_TO_ONE = f"any;-;{HANDLE}"              # the same person's iMessage 1:1 (item 03): not a target while they are on SMS
OTHER_SMS = "sms:+15550009999"
CASTLE = "any;+;9dc250e675d447a888c6287339f429e0"
FROM = "+15550001111"                       # the Twilio number (TWILIO_FROM) in the live tests
SHIFT = "2026-09-27"
FIXTURES = Path(__file__).parent / "fixtures"
UTC_RE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")


def _adapters():
    """The package this item builds (wtdd/chat/adapters/); imported per test so RED shows every check, not one ImportError."""
    from wtdd.chat import adapters
    return adapters


def _sms():
    from wtdd.chat.adapters import sms
    return sms


def _fresh():
    """The per-process SMS adapter, reset so each test starts with an empty stub inbox and nothing sent."""
    s = _sms()
    s.reset()
    return s.adapter()


def _rows(name: str) -> list[dict]:
    return [json.loads(l) for l in (FIXTURES / name).read_text().splitlines() if l.strip()]


def _no_osascript(script: str) -> None:
    raise AssertionError("osascript must not run in tests: " + script[:60])


def _no_http(*a, **kw):
    raise AssertionError(f"the network must not be reached on the stub path: {a[:1]} {sorted(kw)}")


class _Resp:
    def __init__(self, code: int, body: dict):
        self.status_code, self._body = code, body

    def json(self) -> dict:
        return self._body

    @property
    def text(self) -> str:
        return json.dumps(self._body)


class Offline(unittest.TestCase):
    """Nothing in this module may reach osascript or the network; the stub path is asserted against both."""

    def setUp(self):
        self._real = send._osascript
        send._osascript = _no_osascript
        self._post = mock.patch.object(requests, "post", side_effect=_no_http)
        self._get = mock.patch.object(requests, "get", side_effect=_no_http)
        self._post.start()
        self._get.start()

    def tearDown(self):
        send._osascript = self._real
        self._post.stop()
        self._get.stop()


class Fixture(unittest.TestCase):
    def test_thread_fixture_is_the_documented_twilio_shape(self):
        rows = _rows("sms-thread.jsonl")
        self.assertEqual([(r["direction"], r["status"]) for r in rows],
                         [("outbound-api", "queued"), ("outbound-api", "sent"), ("inbound", "received")])
        for r in rows:
            self.assertRegex(r["sid"], r"^SM[0-9a-f]{32}$")
            for k in ("account_sid", "from", "to", "body", "num_media", "date_created", "date_sent", "error_code", "error_message", "uri"):
                self.assertIn(k, r)
        self.assertIsNone(rows[0]["date_sent"])                          # queued: not sent yet
        self.assertEqual(rows[1]["date_sent"], "Sun, 27 Sep 2026 12:18:10 +0000")   # RFC 2822, as Twilio returns it
        self.assertEqual((rows[2]["from"], rows[2]["to"]), (HANDLE, FROM))

    def test_every_shift_fixture_row_is_labeled_stub(self):
        rows = _rows("sms-shift.jsonl")
        self.assertEqual([r["tool"] for r in rows], ["chat.gate", "chat.claim", "chat.post", "intruder.verdict", "chat.post"])
        for r in rows:
            self.assertIs(r["cached"], True, r["tool"])
            self.assertEqual(r["source"], "stub", r["tool"])
            self.assertEqual(r["run_id"], "fixture-12")
        self.assertEqual([r["app"] for r in rows], ["sms", "memory", "sms", "sms", "sms"])
        post = rows[2]
        self.assertEqual(post["args"]["guid"], SMS)
        self.assertEqual(post["args"]["shift_id"], SHIFT)
        self.assertEqual(post["state_after"]["ts"], "2026-09-27 12:18:10")
        self.assertEqual(post["state_after"]["rowid"], 1790511490)          # date_sent as unix seconds
        self.assertEqual(rows[3]["args"]["acked_ms"], 12000)
        self.assertEqual(rows[3]["args"]["chat"], SMS)


class Interface(Offline):
    def test_group_and_one_to_one_are_imessage(self):
        a = _adapters()
        for t in (GROUP, ONE_TO_ONE, CASTLE):
            self.assertEqual(a.for_target(t).app, "imessage", t)
            self.assertIs(a.for_target(t).stub, False, t)

    def test_sms_target_is_the_sms_adapter_and_a_stub_without_keys(self):
        a = _adapters().for_target(SMS)
        self.assertEqual(a.app, "sms")
        self.assertIs(a.stub, True)

    def test_every_adapter_has_the_interface(self):
        a = _adapters()
        for t in (GROUP, SMS):
            ad = a.for_target(t)
            for m in ("gate", "mark", "post_text", "post_photo", "replies_since"):
                self.assertTrue(callable(getattr(ad, m, None)), f"{ad.app}.{m}")
            self.assertIsInstance(ad.mark(), int)

    def test_label_is_stub_only_for_the_stub(self):
        a = _adapters()
        self.assertEqual(a.label(SMS), {"cached": True, "source": "stub"})
        self.assertEqual(a.label(GROUP), {})

    def test_target_and_prefix_agree_with_oncall(self):
        s = _sms()
        self.assertEqual(s.target(HANDLE), SMS)
        self.assertEqual(s.handle_of(SMS), HANDLE)
        self.assertEqual(oncall.guid(HANDLE), SMS)


class OnCallTarget(unittest.TestCase):
    def test_channel_sms_makes_the_on_call_target_sms(self):
        self.assertEqual(oncall.person(), {"name": NAME, "handle": HANDLE, "guid": SMS})

    def test_channel_imessage_or_unset_is_the_one_to_one(self):
        with mock.patch.dict(os.environ, {"WTDD_ON_CALL_CHANNEL": "imessage"}):
            self.assertEqual(oncall.guid(HANDLE), ONE_TO_ONE)
        with mock.patch.dict(os.environ):
            os.environ.pop("WTDD_ON_CALL_CHANNEL", None)
            self.assertEqual(oncall.guid(HANDLE), ONE_TO_ONE)   # 03 unchanged by default

    def test_unknown_channel_fails_loud(self):
        with mock.patch.dict(os.environ, {"WTDD_ON_CALL_CHANNEL": "pigeon"}):
            with self.assertRaises(RuntimeError) as cm:
                oncall.guid(HANDLE)
        self.assertIn("WTDD_ON_CALL_CHANNEL", str(cm.exception))


class Gate(Offline):
    """The SMS adapter admits exactly one target: sms:<WTDD_ON_CALL_HANDLE>. Everything else is refused before anything
    is claimed or sent, with a chat.gate row. The iMessage gate never admits an sms: target."""

    def test_sms_gate_admits_exactly_the_on_call_number(self):
        self.assertEqual(_fresh().gate(SMS), NAME)

    def test_sms_gate_refuses_another_number_the_group_and_the_castle(self):
        a = _fresh()
        for t in (OTHER_SMS, GROUP, CASTLE, ONE_TO_ONE):
            with self.assertRaises(PermissionError, msg=t):
                a.gate(t)

    def test_sms_gate_refuses_when_no_person_is_configured(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("WTDD_ON_CALL_HANDLE", None)
            with self.assertRaises(PermissionError):
                _fresh().gate(SMS)

    def test_sms_gate_refuses_while_the_person_is_on_imessage(self):
        with mock.patch.dict(os.environ, {"WTDD_ON_CALL_CHANNEL": "imessage"}):
            with self.assertRaises(PermissionError):
                _fresh().gate(SMS)

    def test_imessage_refuses_the_sms_target_and_the_one_to_one_while_the_person_is_on_sms(self):
        im = _adapters().for_target(GROUP)
        with mock.patch.object(db, "chat_members", return_value=[HANDLE]):   # even with the 1:1 present on this Mac
            with self.assertRaises(PermissionError):
                im.gate(SMS)
            with self.assertRaises(PermissionError):
                im.gate(ONE_TO_ONE)
            with self.assertRaises(PermissionError):
                send.gate(ONE_TO_ONE)

    def test_wrong_sms_number_is_refused_before_claim_with_a_receipt(self):
        _fresh()
        with self.assertRaises(PermissionError):
            cli.post(OTHER_SMS, "t-sms-other", "escalate", text="who dis?!")
        with memory.connect() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM posts WHERE trigger_guid = 't-sms-other'").fetchone())
        row = [r for r in ledger.rows() if r["tool"] == "chat.gate" and r["args"]["guid"] == OTHER_SMS][-1]
        self.assertFalse(row["ok"])
        self.assertEqual(row["app"], "sms")
        self.assertIn("refused", row["response_or_error"])
        self.assertFalse(any(r["tool"] == "chat.post" and r["args"]["guid"] == OTHER_SMS for r in ledger.rows()))

    def test_transport_gates_first(self):
        a = _fresh()
        with self.assertRaises(PermissionError):
            a.post_text(OTHER_SMS, "x")
        with self.assertRaises(PermissionError):
            a.post_photo(OTHER_SMS, "/tmp/look-level-boxed.jpg", "who dis?!")
        self.assertEqual(a.sent, [])


class NeverTwice(Offline):
    """The stub adapter passes the same never-twice test as iMessage: one claim, one post, the second refused, the
    read-back guid landed on the claim row, and every row of the stub post labeled."""

    def test_flag_posts_once_and_every_row_is_labeled_stub(self):
        a = _fresh()
        row = cli.post(SMS, "alarm:s1:11", "escalate", "who dis?!", "/tmp/look-level-boxed.jpg")
        self.assertRegex(row["guid"], r"^SM[0-9a-f]{32}$")
        self.assertIsInstance(row["rowid"], int)
        self.assertRegex(row["ts"], UTC_RE)
        self.assertEqual(row["status"], "sent")
        self.assertEqual(row["media"], "look-level-boxed.jpg")            # the stub records the photo; it never stages or uploads it
        self.assertNotIn("caption", row)                                   # an MMS is one message: no second bubble
        with self.assertRaises(PermissionError):
            cli.post(SMS, "alarm:s1:11", "escalate", "who dis?!", "/tmp/look-level-boxed.jpg")
        rows = ledger.rows()
        gate = [r for r in rows if r["tool"] == "chat.gate" and r["args"]["guid"] == SMS]
        # one gate row per post(): the second post passes the gate and is refused at the claim (the two claim rows below)
        self.assertEqual([(r["ok"], r["app"], r["cached"], r["source"]) for r in gate], [(True, "sms", True, "stub")] * 2)
        claims = [r for r in rows if r["tool"] == "chat.claim" and r["args"]["trigger"] == "alarm:s1:11"]
        self.assertEqual([(r["ok"], r["app"], r["cached"], r["source"]) for r in claims], [(True, "memory", True, "stub"), (False, "memory", True, "stub")])
        posts = [r for r in rows if r["tool"] == "chat.post" and r["args"]["trigger"] == "alarm:s1:11"]
        self.assertEqual(len(posts), 1)
        p = posts[0]
        self.assertEqual((p["ok"], p["app"], p["cached"], p["source"]), (True, "sms", True, "stub"))
        self.assertEqual(p["args"]["guid"], SMS)
        self.assertEqual(p["args"]["kind"], "escalate")
        self.assertEqual(p["args"]["shift_id"], SHIFT)
        self.assertIsInstance(p["state_before"]["max_rowid"], int)
        self.assertEqual(p["state_after"]["guid"], row["guid"])
        self.assertIn(row["guid"], memory.posted_guids())
        with memory.connect() as c:
            r = c.execute("SELECT posted_guid, confirmed_at FROM posts WHERE trigger_guid = 'alarm:s1:11'").fetchone()
            self.assertEqual(r["posted_guid"], row["guid"])
            self.assertIsNotNone(r["confirmed_at"])
            self.assertIsNone(c.execute("SELECT 1 FROM posts WHERE trigger_guid = 'alarm:s1:11#caption'").fetchone())
        self.assertEqual(len(a.sent), 1)

    def test_text_post_confirms_and_lands_the_guid(self):
        a = _fresh()
        row = cli.post(SMS, "ok:s2", "listen", "ok, standing down")
        self.assertEqual(a.sent[-1]["body"], "ok, standing down")
        self.assertEqual(a.sent[-1]["to"], HANDLE)
        self.assertEqual(a.sent[-1]["direction"], "outbound-api")
        self.assertIn(row["guid"], memory.posted_guids())
        post = [r for r in ledger.rows() if r["tool"] == "chat.post" and r["args"]["trigger"] == "ok:s2"][-1]
        self.assertEqual(post["state_after"], row)
        self.assertEqual(post["args"]["file"], None)


class ReadBack(Offline):
    """The read-back is Twilio's status, replayed by the stub: sent confirms; queued past CONFIRM_S is unconfirmed and
    the step fails without a retry; failed carries Twilio's error code. Same discipline as the from-me row."""

    def test_queued_past_the_timeout_is_unconfirmed_and_not_retried(self):
        a = _fresh()
        a.stub_status = "queued"
        with mock.patch.object(_sms(), "CONFIRM_S", 0.2):
            with self.assertRaises(RuntimeError) as cm:
                cli.post(SMS, "alarm:s3:11", "escalate", "who dis?!", "/tmp/look-level-boxed.jpg")
        self.assertIn("unconfirmed", str(cm.exception))
        self.assertIn("not retried", str(cm.exception))
        self.assertEqual(len(a.sent), 1)
        post = [r for r in ledger.rows() if r["tool"] == "chat.post" and r["args"]["trigger"] == "alarm:s3:11"][-1]
        self.assertFalse(post["ok"])
        self.assertIn("unconfirmed", post["response_or_error"])
        self.assertEqual((post["cached"], post["source"]), (True, "stub"))
        with memory.connect() as c:
            r = c.execute("SELECT posted_guid FROM posts WHERE trigger_guid = 'alarm:s3:11'").fetchone()
        self.assertIsNotNone(r)                                            # the claim was consumed: the flag is never re-sent
        self.assertIsNone(r["posted_guid"])

    def test_failed_status_raises_with_twilios_code(self):
        a = _fresh()
        a.stub_status = "failed"
        a.stub_error = (30003, "Unreachable destination handset")
        with self.assertRaises(RuntimeError) as cm:
            a.post_text(SMS, "who dis?!")
        self.assertIn("30003", str(cm.exception))
        self.assertIn("Unreachable destination handset", str(cm.exception))
        self.assertEqual(len(a.sent), 1)


class Replies(Offline):
    """The listener reads the on-call chat through the adapter and answers a flag the same way: the verdict and the
    correction rows carry acked_ms, the sms chat, the adapter's app, and the stub label; the reply posts go back to
    the sms target through the same gate."""

    def setUp(self):
        super().setUp()
        self.a = _fresh()
        self.posts: list[tuple] = []
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener(GROUP, lambda g, k, kind, t, f: self.posts.append((g, k, kind, t, f)), listen_s=60)
        self.l.marks[SMS] = 0   # read everything the stub receives, whatever the clock says

    def test_listener_targets_the_sms_chat(self):
        self.assertEqual(self.l.oncall, SMS)
        self.assertEqual(sorted(self.l.marks), sorted([GROUP, SMS]))
        self.assertEqual(self.l.escalate("alarm:g1:11", "who dis?!", "/tmp/look-level-boxed.jpg"), SMS)
        self.assertEqual(self.posts, [(SMS, "alarm:g1:11", "escalate", "who dis?!", "/tmp/look-level-boxed.jpg")])

    def test_listener_reads_the_sms_inbox_through_the_adapter(self):
        m = self.a.receive(HANDLE, "thats my friend", "Sun, 27 Sep 2026 12:18:22 +0000")
        self.assertEqual(m["direction"], "inbound")
        with mock.patch.object(L.db, "new_messages", return_value=[]):
            got = self.l.read()
        self.assertEqual(len(got), 1)
        r = got[0]
        self.assertEqual((r["chat"], r["sender"], r["is_from_me"], r["text"], r["ts_utc"], r["rowid"], r["attachments"]),
                         (SMS, HANDLE, 0, "thats my friend", "2026-09-27 12:18:22", 1790511502, []))
        self.assertEqual(r["guid"], m["sid"])
        with memory.connect() as c:
            self.assertEqual(c.execute("SELECT chat_guid FROM chat_messages WHERE guid = ?", (m["sid"],)).fetchone()[0], SMS)
        with mock.patch.object(L.db, "new_messages", return_value=[]):
            self.assertEqual(self.l.read(), [])                            # the watermark moved: read once

    def test_the_dogs_own_sms_is_never_a_reply(self):
        self.a.inbox.append({**_rows("sms-thread.jsonl")[1]})            # the dog's own outbound message, as Twilio lists it
        self.assertEqual(self.a.replies_since(SMS, 0), [])
        m = self.a.receive(HANDLE, "on it")
        self.assertTrue(self.l.allowed({**self.a.replies_since(SMS, 0)[0], "chat": SMS}))
        self.assertFalse(self.l.allowed({"rowid": 1, "guid": "x", "text": "x", "is_from_me": 1, "sender": "", "ts_utc": "", "attachments": [], "chat": SMS}))
        self.assertIsNotNone(m)

    def test_two_replies_in_one_second_both_reach_the_listener_with_a_warn(self):
        when = "Sun, 27 Sep 2026 12:18:22 +0000"
        self.a.receive(HANDLE, "on it", when)
        self.a.receive(HANDLE, "wait its a tarp", when)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            got = self.a.replies_since(SMS, 0)
        self.assertEqual([m["text"] for m in got], ["on it", "wait its a tarp"])   # both handed out, oldest first
        self.assertEqual({m["rowid"] for m in got}, {1790511502})                  # one rowid (seconds): memory.db keeps one
        self.assertIn("WARN same-second sms replies", err.getvalue())             # said, never silent

    def test_verdict_round_trip_through_the_stub(self):
        l = L.Listener(GROUP, cli.post, listen_s=60)   # the real poster: "ok, standing down" goes through the stub adapter
        l.marks[SMS] = 0
        ledger.append({"step": "chat.post", "agent": "central", "tool": "chat.post", "app": "sms", "cached": True, "source": "stub", "ok": True,
                       "args": {"guid": SMS, "kind": "escalate", "trigger": "alarm:g3:11", "text": "who dis?!", "file": "/tmp/f.jpg", "shift_id": SHIFT},
                       "state_before": {"max_rowid": 1790511489}, "state_after": {"guid": "SM" + "3" * 32, "rowid": 1790511490, "ts": "2026-09-27 12:18:10", "status": "sent"},
                       "response_or_error": None, "latency_ms": 1})
        pend = _TMP / "pending-3.json"
        pend.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "file": "/tmp/f.jpg", "seconds": 5, "trigger": "alarm:g3:11", "chat": SMS}))
        reply = self.a.receive(HANDLE, "thats my friend, standing down", "Sun, 27 Sep 2026 12:18:22 +0000")
        with mock.patch.object(L, "PENDING", pend), mock.patch.object(L, "HEARTBEAT", _TMP / "listen.json"), \
             mock.patch.object(L.db, "new_messages", return_value=[]), \
             mock.patch("wtdd.tools.light_alarm.run", side_effect=AssertionError("the alarm must not sound on a known person")):
            self.assertEqual(l.poll(), 1)
        self.assertFalse(pend.exists())
        v = [r for r in ledger.rows() if r["tool"] == "intruder.verdict"][-1]
        self.assertEqual(v["args"]["asked"], "alarm:g3:11")
        self.assertEqual(v["args"]["guid"], reply["sid"])
        self.assertEqual(v["args"]["acked_ms"], 12000)
        self.assertEqual(v["args"]["shift_id"], SHIFT)
        self.assertEqual(v["args"]["chat"], SMS)
        self.assertEqual(v["app"], "sms")
        self.assertEqual((v["cached"], v["source"]), (True, "stub"))
        self.assertEqual(v["state_after"]["verdict"], "known")
        down = [r for r in ledger.rows() if r["tool"] == "chat.post" and r["args"]["trigger"] == f"ok:{reply['sid']}"]
        self.assertEqual(len(down), 1)
        self.assertEqual((down[0]["ok"], down[0]["app"], down[0]["cached"], down[0]["source"]), (True, "sms", True, "stub"))
        self.assertEqual((down[0]["args"]["guid"], down[0]["args"]["text"]), (SMS, "ok, standing down"))
        self.assertEqual(self.a.sent[-1]["body"], "ok, standing down")

    def test_correction_round_trip_is_labeled(self):
        ledger.append({"step": "chat.post", "agent": "central", "tool": "chat.post", "app": "sms", "cached": True, "source": "stub", "ok": True,
                       "args": {"guid": SMS, "kind": "escalate", "trigger": "alarm:g4:11", "text": "who dis?!", "file": "/tmp/look-4.jpg", "shift_id": SHIFT},
                       "state_before": {"max_rowid": 1790511599}, "state_after": {"guid": "SM" + "4" * 32, "rowid": 1790511600, "ts": "2026-09-27 12:20:00", "status": "sent"},
                       "response_or_error": None, "latency_ms": 1})
        self.a.receive(HANDLE, "thats a tarp not a person", "Sun, 27 Sep 2026 12:20:20 +0000")
        with mock.patch.object(L, "STATE", _TMP / "state-4.json"), mock.patch.object(L, "PENDING", _TMP / "pending-none.json"), \
             mock.patch.object(L, "HEARTBEAT", _TMP / "listen.json"), mock.patch.object(L.db, "new_messages", return_value=[]):
            self.assertEqual(self.l.poll(), 1)
        row = [r for r in ledger.rows() if r["tool"] == "chat.correction"][-1]
        self.assertEqual(row["args"]["corrects"]["file"], "look-4.jpg")
        self.assertEqual(row["args"]["acked_ms"], 20000)
        self.assertEqual(row["args"]["chat"], SMS)
        self.assertEqual(row["app"], "sms")
        self.assertEqual((row["cached"], row["source"]), (True, "stub"))
        self.assertEqual(self.posts[-1][0], SMS)
        self.assertTrue(self.posts[-1][3].startswith("noted:"))

    def test_an_sms_never_wakes_the_dog(self):
        self.a.receive(HANDLE, "what the dog doin")
        with mock.patch.object(L, "PENDING", _TMP / "pending-none.json"), mock.patch.object(L, "STATE", _TMP / "state.json"), \
             mock.patch.object(L, "HEARTBEAT", _TMP / "listen.json"), mock.patch.object(L.db, "new_messages", return_value=[]):
            self.l.poll()
        self.assertFalse(self.l.armed)
        self.assertEqual(self.posts, [])


class Parse(unittest.TestCase):
    def test_message_from_the_inbound_fixture(self):
        m = _sms().message_from(_rows("sms-thread.jsonl")[2])
        self.assertEqual(m, {"rowid": 1790511502, "guid": "SM00000000000000000000000000000002", "text": "thats my friend, standing down",
                             "is_from_me": 0, "sender": HANDLE, "ts_utc": "2026-09-27 12:18:22", "attachments": []})

    def test_message_from_the_outbound_fixture_is_from_me(self):
        m = _sms().message_from(_rows("sms-thread.jsonl")[1])
        self.assertEqual((m["is_from_me"], m["guid"], m["rowid"]), (1, "SM00000000000000000000000000000001", 1790511490))

    def test_ts_utc_converts_offsets(self):
        s = _sms()
        self.assertEqual(s.ts_utc("Sun, 27 Sep 2026 12:18:22 +0000"), "2026-09-27 12:18:22")
        self.assertEqual(s.ts_utc("Sun, 27 Sep 2026 13:18:22 +0100"), "2026-09-27 12:18:22")
        self.assertEqual(s.epoch("Sun, 27 Sep 2026 12:18:22 +0000"), 1790511502)


class Live(unittest.TestCase):
    """The live path against Twilio's REST API, with requests patched: the exact POST, the status read-back, the
    inbound list. Built by constructor arguments (like the Hue stub test), never from .env."""

    SID, TOKEN = "AC00000000000000000000000000000000", "tok"
    URL = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages"

    def setUp(self):
        self._real = send._osascript
        send._osascript = _no_osascript
        self.thread = _rows("sms-thread.jsonl")

    def tearDown(self):
        send._osascript = self._real
        _sms().reset()

    def _live(self, media_base: str | None = None):
        a = _sms().Sms(self.SID, self.TOKEN, FROM, media_base)
        self.assertIs(a.stub, False)
        return a

    def test_keys_in_env_make_for_target_live(self):
        with mock.patch.dict(os.environ, {"TWILIO_ACCOUNT_SID": self.SID, "TWILIO_AUTH_TOKEN": self.TOKEN, "TWILIO_FROM": FROM}):
            _sms().reset()
            a = _adapters().for_target(SMS)
            self.assertIs(a.stub, False)
            self.assertEqual(_adapters().label(SMS), {})

    def test_one_twilio_key_set_means_all_three_and_the_post_stops_at_the_gate(self):
        with self.assertRaises(RuntimeError) as cm:
            _sms().Sms(self.SID, self.TOKEN, None)
        self.assertIn("TWILIO_FROM", str(cm.exception))
        # its own scratch ledger: the module's is shared, and NeverTwice counts every sms chat.gate row in it
        with mock.patch.dict(os.environ, {"TWILIO_ACCOUNT_SID": self.SID}), mock.patch.object(ledger, "LEDGER", _TMP / "partial-keys.jsonl"), \
             mock.patch.object(requests, "post", side_effect=_no_http), mock.patch.object(requests, "get", side_effect=_no_http):
            _sms().reset()
            with self.assertRaises(RuntimeError) as cm:
                _adapters().for_target(SMS)                  # never the stub: a half-set live channel is a config failure
            self.assertIn("TWILIO_AUTH_TOKEN", str(cm.exception))
            with self.assertRaises(RuntimeError):
                cli.post(SMS, "alarm:partial-keys", "escalate", "who dis?!")
            rows = ledger.rows()
        # the failure is the gate's own row, and the only row: nothing claimed, nothing sent
        self.assertEqual([(r["tool"], r["ok"], r["app"], r["args"]) for r in rows], [("chat.gate", False, "sms", {"guid": SMS})])
        self.assertIn("TWILIO_AUTH_TOKEN", rows[0]["response_or_error"])

    def test_post_text_posts_to_twilio_and_reads_the_status_back(self):
        a = self._live()
        with mock.patch.object(requests, "post", return_value=_Resp(201, self.thread[0])) as p, \
             mock.patch.object(requests, "get", return_value=_Resp(200, self.thread[1])) as g:
            row = a.post_text(SMS, "who dis?!")
        self.assertEqual(p.call_args.args[0], self.URL + ".json")
        self.assertEqual(p.call_args.kwargs["auth"], (self.SID, self.TOKEN))
        self.assertEqual(p.call_args.kwargs["data"], {"To": HANDLE, "From": FROM, "Body": "who dis?!"})
        self.assertEqual(g.call_args.args[0], self.URL + "/SM00000000000000000000000000000001.json")
        self.assertEqual(row, {"guid": "SM00000000000000000000000000000001", "rowid": 1790511490, "ts": "2026-09-27 12:18:10", "status": "sent"})

    def test_post_photo_needs_a_public_media_base(self):
        a = self._live(media_base=None)
        with mock.patch.object(requests, "post", side_effect=_no_http), mock.patch.object(send, "stage", return_value=Path("/x/1-look.jpg")):
            with self.assertRaises(RuntimeError) as cm:
                a.post_photo(SMS, "/tmp/look-level-boxed.jpg", "who dis?!")
        self.assertIn("TWILIO_MEDIA_BASE", str(cm.exception))

    def test_post_photo_sends_the_staged_picture_url(self):
        a = self._live(media_base="https://dog.example.test")
        staged = Path("/Users/johnnysheng/Pictures/wtdd/1790511489-look-level-boxed.jpg")
        with mock.patch.object(send, "stage", return_value=staged) as st, \
             mock.patch.object(requests, "post", return_value=_Resp(201, self.thread[0])) as p, \
             mock.patch.object(requests, "get", return_value=_Resp(200, self.thread[1])):
            row = a.post_photo(SMS, "/tmp/look-level-boxed.jpg", "who dis?!")
        st.assert_called_once_with("/tmp/look-level-boxed.jpg")
        self.assertEqual(p.call_args.kwargs["data"], {"To": HANDLE, "From": FROM, "Body": "who dis?!",
                                                      "MediaUrl": "https://dog.example.test/pictures/1790511489-look-level-boxed.jpg"})
        self.assertEqual(row["media"], "https://dog.example.test/pictures/1790511489-look-level-boxed.jpg")
        self.assertEqual(row["guid"], "SM00000000000000000000000000000001")

    def test_twilios_error_is_the_error_and_nothing_is_read_back(self):
        a = self._live()
        err = {"code": 21608, "message": "The number +15550002222 is unverified. Trial accounts cannot send messages to unverified numbers", "status": 400}
        with mock.patch.object(requests, "post", return_value=_Resp(400, err)), mock.patch.object(requests, "get", side_effect=_no_http):
            with self.assertRaises(RuntimeError) as cm:
                a.post_text(SMS, "who dis?!")
        self.assertIn("21608", str(cm.exception))
        self.assertIn("unverified", str(cm.exception))

    def test_replies_since_lists_inbound_after_the_mark(self):
        a = self._live()
        listing = {"messages": [self.thread[1], self.thread[2]], "page": 0, "page_size": 50}
        with mock.patch.object(requests, "get", return_value=_Resp(200, listing)) as g:
            got = a.replies_since(SMS, 1790511490)
        self.assertEqual(g.call_args.args[0], self.URL + ".json")
        params = g.call_args.kwargs["params"]
        self.assertEqual((params["From"], params["To"]), (HANDLE, FROM))
        self.assertEqual(params["DateSent>"], "2026-09-27")   # twilio-python's key for date_sent_after, the date as the value
        self.assertIn("DateSent%3E=2026-09-27", requests.Request("GET", self.URL + ".json", params=params).prepare().url)
        # ^ on the wire: DateSent>=2026-09-27 once decoded, the doc's ">=YYYY-MM-DD" (on and after); UNVERIFIED live
        self.assertEqual([m["guid"] for m in got], ["SM00000000000000000000000000000002"])   # the dog's own outbound row is not a reply
        self.assertEqual(got[0]["ts_utc"], "2026-09-27 12:18:22")
        with mock.patch.object(requests, "get", return_value=_Resp(200, listing)):
            self.assertEqual(a.replies_since(SMS, 1790511490), [])       # handed out once: the same sid is never a second reply


if __name__ == "__main__":
    unittest.main()
