"""Recognition and the listener state machine, offline. Run: python -m unittest wtdd.chat.test_triggers -v
The from-me rule is tested in its strict form (WTDD_ALLOW_SELF=0); the wake demo and the model path are switched off
(WTDD_WAKE_SHOW=0, WTDD_AGENT=0) so the machine is wake -> command -> stop with a stubbed commands.run."""
from __future__ import annotations
import os
import tempfile
import unittest
from unittest import mock

os.environ["WTDD_WAKE_SHOW"] = "0"
os.environ["WTDD_AGENT"] = "0"
os.environ["WTDD_ALLOW_SELF"] = "0"
os.environ["WTDD_TRIGGERS"] = "what the dog doin,what the dog doing,whats the dog doing,what is the dog doing,wtdd"
os.environ["WTDD_COMMANDS"] = "do a round,lights on,lights off,dim,bright,show,sit,stand,hello,look,status,stop"
os.environ.setdefault("WTDD_LEDGER", os.path.join(tempfile.mkdtemp(), "ledger.jsonl"))
os.environ.setdefault("WTDD_MEMORY", os.path.join(tempfile.mkdtemp(), "memory.db"))

from wtdd.chat import listen as L  # noqa: E402
from wtdd.chat import triggers as T  # noqa: E402


class Recognize(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(T.normalize("What’s the DOG doin'?!"), "whats the dog doin")

    def test_wake_exact_and_close(self):
        for s in ["what the dog doin", "WHAT THE DOG DOIN??", "yo whats the dog doing", "wat da dog doin",
                  "wtdd", "what's the dog doin rn", "dog doin"]:
            self.assertIsNotNone(T.is_wake(s), s)

    def test_not_wake(self):
        for s in ["whats for dinner", "the lights are on", "hotdog time", "doing homework", "the dog is cute", ""]:
            self.assertIsNone(T.is_wake(s), s)

    def test_commands(self):
        self.assertEqual(T.match_command("turn the lights on")[0], "lights on")
        self.assertEqual(T.match_command("lights off pls")[0], "lights off")
        self.assertEqual(T.match_command("sit")[0], "sit")
        self.assertEqual(T.match_command("sitt")[0], "sit")
        self.assertEqual(T.match_command("run a round")[0], "do a round")
        self.assertEqual(T.match_command("that's all, stop")[0], "stop")
        self.assertIsNone(T.match_command("whats for dinner"))


def _m(text, sender="+15550001", guid=None, from_me=0):
    _m.n += 1
    return {"rowid": _m.n, "guid": guid or f"g{_m.n}", "text": text, "is_from_me": from_me, "sender": sender,
            "ts_utc": "2026-09-13 08:00:00", "attachments": []}
_m.n = 0


class Machine(unittest.TestCase):
    def setUp(self):
        self.posts = []
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener("any;+;test", lambda g, k, kind, t, f: self.posts.append((k, t, f)), listen_s=60)

    def test_wake_then_command_then_stop(self):
        with mock.patch.object(L.cmds, "run", return_value="lights on: a, b") as run:
            self.l.handle(_m("lights on"))                       # not armed: ignored
            self.assertEqual(self.posts, [])
            self.l.handle(_m("yo what the dog doin"))            # wake
            self.assertTrue(self.l.armed)
            self.assertTrue(self.posts[-1][0].startswith("wake:"))
            self.l.handle(_m("turn the lights on"))              # command
            run.assert_called_once_with("lights on")
            self.assertEqual([p[0].split(":")[0] for p in self.posts], ["wake", "ack", "res"])
            self.assertEqual(self.posts[-1][1], "lights on: a, b")
            self.l.handle(_m("ok stop"))                         # stop
            self.assertFalse(self.l.armed)
            self.assertTrue(self.posts[-1][0].startswith("stop:"))

    def test_failure_is_reported_not_faked(self):
        with mock.patch.object(L.cmds, "run", side_effect=ConnectionError("dog unreachable")):
            self.l.handle(_m("what the dog doin"))
            self.l.handle(_m("sit"))
            self.assertIn("couldn't sit: ConnectionError: dog unreachable", self.posts[-1][1])

    def test_own_messages_and_unknown_text_ignored(self):
        with mock.patch.object(L.cmds, "run") as run:
            self.l.handle(_m("what the dog doin", from_me=1))    # the dog's own echo never wakes it
            self.assertFalse(self.l.armed)
            self.l.handle(_m("what the dog doin"))
            self.l.handle(_m("lol nothing"))                     # armed, not a command
            run.assert_not_called()
            self.assertEqual(len(self.posts), 1)

    def test_photo_result(self):
        with mock.patch.object(L.cmds, "run", return_value={"text": "here's what i see", "file": "/tmp/x.jpg"}):
            self.l.handle(_m("wtdd")); self.l.handle(_m("look"))
            self.assertEqual(self.posts[-1], ("res:" + self.posts[-1][0].split(":")[1], "here's what i see", "/tmp/x.jpg"))


if __name__ == "__main__":
    unittest.main()
