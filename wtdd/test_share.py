"""POST /images/share and the replies it keeps. Run: python -m unittest wtdd.test_share -v
Johnny, live at 19:4x: "it should put it in the routines photos album and I can choose to send it to the group chat with
a button in it, and people can respond, and it'll save the responses for me."

The API side: the real handler on an ephemeral port in this process (as test_images runs it), on a planted ledger
(WTDD_LEDGER set before wtdd.ledger is imported) and a planted pictures folder (api.PICTURES and send.PICTURES patched to
one temp dir holding a few bytes per name, never a photo). The send is the stub: osascript is never run (send._osascript
records the script), chat.db is never read (db.max_rowid, db.chat_name and db.find_from_me answer stand-ins), and the
gate runs for real on WTDD_CHAT_GUID = the stand-in group and its stand-in name. The listener's side: a Listener whose
read() returns planted messages, poll() as run() calls it. The listener's PENDING, RESET, HEARTBEAT, STATE and SHARE
are temp paths and WTDD_MEMORY a temp db, so the checkout's pending.json, share.json, chat.reset and ledger are never
touched. Handles are stand-ins (+1555...)."""
from __future__ import annotations
import contextlib
import io
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

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-share-test-")).resolve()   # send.stage compares resolved parents (/var is /private/var)
LEDGER = _TMP / "ledger.jsonl"
os.environ["WTDD_LEDGER"] = str(LEDGER)
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
GROUP = "any;+;00000000000000000000000000000000"
os.environ["WTDD_CHAT_GUID"] = GROUP
for _k in ("WTDD_SHIFT", "JEV_API_KEY", "JEV_MODEL", "JEV_LIVE", "WTDD_REPLY_THRESHOLD", "WTDD_DECIDE_THRESHOLD", "WTDD_ON_CALL_GUID",
           "WTDD_ON_CALL_HANDLE", "WTDD_ALARM", "WTDD_AGENT", "WTDD_ALLOW_SELF", "WTDD_COMMANDS", "WTDD_TRIGGERS", "WTDD_ROUND"):
    os.environ[_k] = ""   # config.maybe() reads an empty value as unset: the defaults, never a live call

from wtdd import api, ledger  # noqa: E402
from wtdd.chat import db, memory, send  # noqa: E402
from wtdd.chat import listen as L  # noqa: E402

PICS = _TMP / "pictures"
S = "2026-09-27-night"
LOOK, GONE, LOOSE = "look-tilt-20260927T210005-a1.jpg", "look-level-20260927T210200-b2.jpg", "not-named-by-any-row.jpg"
TERI, OTHER = "+15550001111", "+15550003333"


def _row(ts, tool, args, after=None, ok=True):
    return {"ts": ts, "run_id": "run-test", "cached": True, "source": "stub", "step": tool, "agent": "central", "tool": tool,
            "app": "stub", "args": args, "state_before": None, "state_after": after, "ok": ok, "response_or_error": None, "latency_ms": 0}


ROWS = [
    _row("2026-09-27T21:00:00", "chat.wake", {"from": TERI, "text": "yo dog do a round", "guid": "W1", "shift_id": S}),
    _row("2026-09-27T21:00:10", "chat.post", {"guid": GROUP, "kind": "listen", "trigger": "say:W1:2", "text": "a cup on the table",
                                              "file": str(PICS / LOOK), "shift_id": S}, {"guid": "MSG-say", "rowid": 1, "ts": "x"}),
    _row("2026-09-27T21:02:00", "chat.post", {"guid": GROUP, "kind": "listen", "trigger": "say:W1:3", "text": "a sock",
                                              "file": str(PICS / GONE), "shift_id": S}, {"guid": "MSG-say3", "rowid": 2, "ts": "x"}),
]


def msg(text: str, guid: str, rowid: int = 10, sender: str = TERI, me: int = 0) -> dict:
    return {"rowid": rowid, "guid": guid, "text": text, "is_from_me": me, "sender": sender,
            "ts_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "attachments": [], "chat": GROUP}


class Share(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        PICS.mkdir(parents=True, exist_ok=True)
        for name in (LOOK, LOOSE):
            (PICS / name).write_bytes(f"planted {name}, not a photo".encode())
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.err = io.StringIO()
        self.enterContext(contextlib.redirect_stderr(self.err))
        LEDGER.write_text("".join(json.dumps(r) + "\n" for r in ROWS))
        self.before = LEDGER.read_bytes()
        d = Path(tempfile.mkdtemp(dir=_TMP))
        self.pend, self.share, self.flag = d / "pending.json", d / "share.json", d / "chat.reset"
        self.sent: list[str] = []
        self.fail_send: Exception | None = None
        for p in (mock.patch.object(L, "PENDING", self.pend), mock.patch.object(L, "RESET", self.flag),
                  mock.patch.object(L, "SHARE", self.share, create=True), mock.patch.object(L, "HEARTBEAT", d / "listen.json"),
                  mock.patch.object(L, "STATE", d / "state.json"), mock.patch.object(memory, "MEMORY", d / "memory.db"),   # a fresh never-twice gate: every test shares in the same second
                  mock.patch.object(api, "PICTURES", PICS), mock.patch.object(send, "PICTURES", PICS),
                  mock.patch.object(send, "_osascript", self._osascript), mock.patch.object(db, "max_rowid", return_value=0),
                  mock.patch.object(db, "chat_name", return_value=send.TARGET_NAME),
                  mock.patch.object(db, "find_from_me", self._confirmed),
                  mock.patch.dict(L.HOUSEMATES, {TERI: "Teri"}), mock.patch("wtdd.tools.call")):
            self.enterContext(p)
        self.posts: list[tuple[str, str | None]] = []
        self.l = L.Listener(GROUP, lambda g, k, kind, t, f: self.posts.append((k, t)), listen_s=60)

    def _osascript(self, script: str) -> None:
        if self.fail_send:
            raise self.fail_send
        self.sent.append(script)

    def _confirmed(self, guid, after, text, timeout_s=10.0):
        n = len(self.sent)
        return {"guid": f"SENT-{n}-{'caption' if text else 'file'}", "rowid": 100 + n, "ts": "2026-09-27 21:10:00"}

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        rq = urllib.request.Request(self.base + path, method=method, headers={"Content-Type": "application/json"},
                                    data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(rq, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def new_rows(self) -> list[dict]:
        after = LEDGER.read_bytes()
        self.assertTrue(after.startswith(self.before), "a past ledger row was rewritten")
        return [json.loads(l) for l in after[len(self.before):].decode().splitlines() if l.strip()]

    def image(self, name: str = LOOK) -> dict:
        code, body = self.call("GET", f"/images?shift={S}")
        self.assertEqual(code, 200, body)
        (img,) = [i for i in body["images"] if i["file"] == name]
        return img

    def replies(self) -> list[dict]:
        return [r for r in self.new_rows() if r["tool"] == "chat.reply"]

    def shared(self) -> dict:
        code, got = self.call("POST", "/images/share", {"file": LOOK, "by": "Johnny"})
        self.assertEqual(code, 200, got)
        return got

    def poll(self, *msgs: dict) -> None:
        with mock.patch.object(self.l, "read", return_value=list(msgs)):
            self.l.poll()

    # the share itself

    def test_a_share_posts_the_photo_once_and_opens_the_window(self):
        t0 = time.time()
        got = self.shared()
        self.assertEqual(set(got), {"ok", "trigger", "until"})
        self.assertTrue(got["ok"])
        self.assertRegex(got["trigger"], rf"^share:{LOOK}:\d+$")
        self.assertAlmostEqual(got["until"], t0 + L.SHARE_WINDOW_S, delta=5)
        self.assertEqual(L.SHARE_WINDOW_S, 600)
        self.assertEqual(len(self.sent), 1, "one osascript send: the photo and its caption")
        self.assertIn(str(PICS / LOOK), self.sent[0])
        self.assertIn("from the dog's round", self.sent[0], "the default caption names where the photo is from")
        (post,) = [r for r in self.new_rows() if r["tool"] == "chat.post"]
        self.assertTrue(post["ok"])
        self.assertEqual({k: post["args"][k] for k in ("kind", "trigger", "by", "guid")},
                         {"kind": "share", "trigger": got["trigger"], "by": "Johnny", "guid": GROUP})
        self.assertEqual(Path(post["args"]["file"]).name, LOOK)
        w = json.loads(self.share.read_text())
        self.assertEqual({k: w[k] for k in ("trigger", "by")}, {"trigger": got["trigger"], "by": "Johnny"})
        self.assertEqual(Path(w["file"]).name, LOOK)
        self.assertAlmostEqual(w["until"] - w["at"], L.SHARE_WINDOW_S, delta=0.01)

    def test_refusals_are_one_failed_row_and_no_post(self):
        for body, code in (({"file": LOOSE, "by": "Johnny"}, 404),           # in the folder, but no row names it
                           ({"file": "../../../etc/hosts", "by": "Johnny"}, 404),   # basename only: never a path outside
                           ({"file": GONE, "by": "Johnny"}, 404),            # named by a row, gone from the folder
                           ({"by": "Johnny"}, 400), ({"file": LOOK}, 400), ({"file": LOOK, "by": "  "}, 400)):
            with self.subTest(body=body):
                n = len(self.new_rows())
                got_code, got = self.call("POST", "/images/share", body)
                self.assertEqual((got_code, got["ok"]), (code, False), got)
                (r,) = self.new_rows()[n:]
                self.assertFalse(r["ok"])
                self.assertTrue(r["tool"].startswith("chat.share"), r["tool"])
        self.assertEqual(self.sent, [])
        self.assertFalse(self.share.exists())

    def test_a_share_while_a_question_is_open_is_409_and_no_post(self):
        self.pend.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "trigger": "alarm:T1:5", "chat": GROUP,
                                         "question": "who dis?!"}))
        code, got = self.call("POST", "/images/share", {"file": LOOK, "by": "Johnny"})
        self.assertEqual((code, got["ok"]), (409, False), got)
        (r,) = self.new_rows()
        self.assertFalse(r["ok"])
        self.assertEqual(self.sent, [], "the who-dis flow wins: nothing posted")
        self.assertFalse(self.share.exists())

    def test_a_failed_post_opens_no_window_and_the_album_shows_it_failed(self):
        self.fail_send = RuntimeError("osascript rc=1: Messages got an error")
        code, got = self.call("POST", "/images/share", {"file": LOOK, "by": "Johnny"})
        self.assertEqual((code, got["ok"]), (500, False), got)
        self.assertIn("osascript rc=1", got["error"])
        self.assertFalse(self.share.exists(), "a failed post opened a window")
        self.poll(msg("so cute", "R-1"))
        self.assertEqual(self.replies(), [])
        img = self.image()
        self.assertEqual((img["shared"]["ok"], img["shared"]["by"], img["replies"]), (False, "Johnny", []))

    def test_a_new_share_replaces_the_open_window_with_one_warn(self):
        first = self.shared()["trigger"]
        time.sleep(1.05)   # the trigger carries epoch seconds: a second share in the same second is the same claim, refused
        second = self.shared()["trigger"]
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads(self.share.read_text())["trigger"], second)
        self.assertEqual(len([l for l in self.err.getvalue().splitlines() if "WARN" in l and "replace" in l]), 1, self.err.getvalue())

    # the replies

    def test_two_group_replies_are_kept_on_that_image(self):
        trig = self.shared()["trigger"]
        self.poll(msg("so cute", "R-1", 11))
        with mock.patch.dict(L.HOUSEMATES, {}, clear=True):   # an empty list lets any member in: a handle with no name
            self.poll(msg(f"lol text me {OTHER}", "R-2", 12, sender=OTHER))
        self.assertEqual(self.posts, [], "a reply is kept, never answered")
        rs = self.replies()
        self.assertEqual([(r["args"]["share"], r["args"]["from"], r["args"]["rowid"]) for r in rs],
                         [(trig, TERI, 11), (trig, OTHER, 12)])
        self.assertTrue(all(Path(r["args"]["file"]).name == LOOK and r["ok"] for r in rs))
        img = self.image()
        self.assertEqual({k: img["shared"][k] for k in ("trigger", "by", "ok")}, {"trigger": trig, "by": "Johnny", "ok": True})
        self.assertRegex(img["shared"]["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertEqual([(x["by"], x["text"]) for x in img["replies"]], [("Teri", "so cute"), ("a member", "lol text me a member")])
        self.assertIsNone(self.image(GONE)["shared"])
        self.assertEqual(self.image(GONE)["replies"], [])
        code, body = self.call("GET", f"/images?shift={S}")
        self.assertEqual([i["file"] for i in body["images"]], [LOOK, GONE], "the share post is listed as a new photo")

    def test_a_wake_word_in_the_window_starts_a_round_and_is_not_a_reply(self):
        self.shared()
        rounds: list[str] = []
        self.l.wake_show = lambda m: rounds.append(m["guid"])
        with mock.patch.dict(os.environ, {"WTDD_WAKE_SHOW": "1"}):
            self.poll(msg("what the dog doin", "W2", 11), msg("haha", "R-1", 12))
        self.assertEqual(rounds, ["W2"])
        self.assertEqual([r["args"]["guid"] for r in self.replies()], ["R-1"])

    def test_a_bare_command_in_the_window_is_not_a_reply(self):
        self.shared()
        self.poll(msg("lights off", "C1", 11), msg("haha", "R-1", 12))
        self.assertEqual([r["args"]["guid"] for r in self.replies()], ["R-1"])

    def test_a_who_dis_answer_while_pending_is_the_verdict_not_a_reply(self):
        self.shared()
        with mock.patch.dict(os.environ, {"WTDD_ON_CALL_GUID": GROUP}):
            self.l = L.Listener(GROUP, lambda g, k, kind, t, f: self.posts.append((k, t)), listen_s=60)
        self.pend.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "file": "/tmp/look.jpg", "seconds": 5,
                                         "trigger": "alarm:T1:5", "chat": GROUP, "question": "who dis?!"}))
        self.poll(msg("that's teri", "V1", 11), msg("cute pic", "R-1", 12))   # the verdict closes the question: then a reply
        self.assertEqual([r["tool"] for r in self.new_rows() if r["tool"] == "intruder.verdict"], ["intruder.verdict"])
        self.assertEqual([r["args"]["guid"] for r in self.replies()], ["R-1"])

    def test_a_correction_in_the_window_is_the_correction_not_a_reply(self):
        self.shared()
        self.poll(msg("that's a mug not a cup", "F1", 11), msg("lol", "R-1", 12))
        self.assertEqual([r["tool"] for r in self.new_rows() if r["tool"] == "chat.correction"], ["chat.correction"])
        self.assertEqual([r["args"]["guid"] for r in self.replies()], ["R-1"])

    def test_a_reset_closes_the_window(self):
        trig = self.shared()["trigger"]
        code, got = self.call("POST", "/chat/reset", {"by": "Johnny"})
        self.assertEqual(code, 200, got)
        self.assertFalse(self.share.exists(), "the reset left the window open")
        (r,) = [r for r in self.new_rows() if r["tool"] == "chat.reset"]
        self.assertEqual((r["state_before"]["share"], r["state_after"]["share"]), (trig, None))
        self.poll(msg("so cute", "R-1"))
        self.assertEqual(self.replies(), [])

    def test_a_reply_after_until_is_not_kept_and_the_close_is_one_line(self):
        self.shared()
        w = json.loads(self.share.read_text())
        self.share.write_text(json.dumps({**w, "until": time.time() - 1}))
        with mock.patch.object(L, "log", wraps=L.log) as log:
            self.poll(msg("so cute", "R-1", 11))
            self.poll(msg("still cute", "R-2", 12))
        self.assertEqual(self.replies(), [])
        self.assertEqual(len([c for c in log.call_args_list if "share" in c.args[1].lower() and "closed" in c.args[1].lower()]), 1)

    def test_the_dogs_own_post_is_never_a_reply(self):
        trig = self.shared()["trigger"]
        with mock.patch.dict(os.environ, {"WTDD_ALLOW_SELF": "1"}):   # Johnny's phone shares the dog's account
            memory.claim("share:own")
            memory.confirm("share:own", "OWN-1")
            self.poll(msg("look at this", "OWN-1", 11, sender=None, me=1),                        # its confirmed guid
                      msg("from the dog's round · stop 2", "OWN-2", 12, sender=None, me=1))       # its caption's opening words
        self.poll(msg("look at this", "OWN-3", 13, sender=None, me=1), msg("nice", "R-1", 14))   # a from-me row, no WTDD_ALLOW_SELF
        self.assertEqual([(r["args"]["share"], r["args"]["guid"]) for r in self.replies()], [(trig, "R-1")])


if __name__ == "__main__":
    unittest.main()
