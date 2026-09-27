"""Item 17, the reply read typed: the on-call person's words become one typed meaning with a probability, logged, and
the listener's verdict comes from it. Run: python -m unittest wtdd.chat.test_reply -v
(the goal's command runs it after wtdd.test_decide in one process: python -m unittest wtdd.test_decide wtdd.chat.test_reply)

Checks wtdd/decide.py read_reply(asked, text, **row_args) -> {meaning, p, named, p_named, action}: two Choice questions
in one System One request (meaning over acknowledged / handled / standing_down / stranger / unclear; named over the site
labels + not_said) when JEV_API_KEY is set, the shipped IDK / CORRECTION regexes plus two word lists as the labeled
DEMO_CACHE stub otherwise; WTDD_REPLY_THRESHOLD (default 0.8): below it, or unclear, the action is one re-ask; one
`reply.decided` row per reading (agent central, never tool "decided", which 11's unsafe() counts as a stop's model
call); a live failure is that row with ok=False, raised, never the regex. Then wtdd/chat/listen.py verdict(): the
reply.decided row, then the intruder.verdict row (verdict typed from the meaning: stranger, known for standing_down,
handled, acknowledged, unclear; unread when the reading failed; acked_ms as 03 measures it), then what the meaning asks
for. Only a who_dis flag (03's person-in-frame at an ask stop, or intruder_alarm) can sound the alarm; a heads_up (17's
escalation of a decided label) or a decide question stands down on stranger. acknowledged holds the flag open for
handled; handled closes it; below the threshold or unclear, "do you know them? yes or no" once, then stand down, logged
as unclear; the round's hold goes on across the re-ask. A pending of kind halt (item 00) never enters read_reply.
From the review of 17: the answer to the re-ask is read against the re-ask (args.question); one acked_ms per flag (a
close after a hold carries closed_ms instead; after a re-ask the final row keeps the first reply's time), so
numbers.shifts() on the remote fixture counts one; a verdict read by the stub is a cached/stub row, an unread one is not.
From the second review: the stub reads a yes or no against the re-ask itself ("no" to "do you know them?" is a stranger,
so a who_dis flag sounds the alarm; "yes" stands down), where 02's CORRECTION had read a bare "no" as standing_down.
From the third review: a reply stamped before the open question's confirmed post is not its answer (the person typed it
about an earlier flag): no reading, no verdict, the question stays open.
From the final review (round 4, fixed by the head's grant): a re-ask nobody answers is one unclear / stand_down verdict
row with the first reply's acked_ms and reading, when the hold times out or the window expires, never a silent unlink.
An acknowledged flag is exempt from PENDING_WINDOW_S, so "handled" 130 s after the heads-up still closes it; it lasts
ACK_WINDOW_S (1800 s, the head's choice for beat 2.4b) from the acknowledgement, then one expired / stand_down row
naming the acknowledgement and the window, never a silent unlink.

Offline: the scratch ledger and memory.db are set through WTDD_LEDGER / WTDD_MEMORY before wtdd.ledger is imported. Run
alone, they are this module's; after wtdd.test_decide in one process they are that module's (wtdd.ledger reads the
variable once, docs/gotchas/03-3), so every check here reads only rows carrying its own trigger, or rows appended since
it began. JEV_API_KEY is forced empty (a .env key must not turn these into live calls); the live checks patch
requests.post or point JEV_URL at a closed port. The on-call person is fake and E.164-shaped. tools.call is patched in
every verdict check, so no light is ever written. The stub replies are the ones a scratch Jev probe on this Mac read on
2026-09-26 (docs/evidence/night-2/jev-probe-2026-09-26.jsonl, point C_reply); the numbers checked here are the stub's,
never Jev's. UNVERIFIED: the two-question request and its reply shape have been probed (22 calls, all 200) but never
sent by this code with a key."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-reply-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
for _k in ("JEV_API_KEY", "JEV_MODEL", "JEV_LIVE", "WTDD_REPLY_THRESHOLD", "WTDD_DECIDE_THRESHOLD"):
    os.environ[_k] = ""                   # the stub path and the defaults; config.maybe() reads an empty value as unset
os.environ["WTDD_ON_CALL_NAME"] = "Sam Stand-in"
os.environ["WTDD_ON_CALL_HANDLE"] = "+15550002222"

from wtdd import config, decide, ledger  # noqa: E402
from wtdd.chat import listen as L  # noqa: E402

ROOT = config.ROOT
PY = sys.executable
GROUP = "any;+;00000000000000000000000000000000"
HANDLE = "+15550002222"
ONCALL = f"any;-;{HANDLE}"
SITE = ["clear", "material_stack", "opening", "hazard", "person", "other"]
MEANINGS = ["acknowledged", "handled", "standing_down", "stranger", "unclear"]
ACTIONS = {"stranger": "alarm", "standing_down": "stand_down", "handled": "close", "acknowledged": "hold", "unclear": "reask"}
KEYS = {"meaning", "p", "named", "p_named", "action"}
WHO = "who dis?!"
HEADS = "heads up: opening at ninety eight percent at stop one. what is it?"
REASK = "do you know them? yes or no"
STANDING_DOWN = "ok, standing down"


class Stub(unittest.TestCase):
    """read_reply without JEV_API_KEY: the shipped IDK and CORRECTION regexes (wtdd/chat/listen.py) plus two word lists,
    labeled DEMO_CACHE; its rows say cached=True, source="stub". The probe's replies, where the stub agrees with Jev."""
    CASES = [  # (asked, text, meaning, p)
        (WHO, "idk who that is", "stranger", 0.9),
        (WHO, "not me", "stranger", 0.9),
        (WHO, "thats my friend", "standing_down", 0.85),
        (HEADS, "thats a tarp, not an opening", "standing_down", 0.85),
        (HEADS, "handled, cover is back on", "handled", 0.85),
        (HEADS, "on it", "acknowledged", 0.85),
        (WHO, "omw", "acknowledged", 0.85),
        (WHO, "wait what", "unclear", 0.5),
    ]

    def test_the_probes_replies(self):
        for asked, text, meaning, p in self.CASES:
            r = decide.read_reply(asked, text)
            self.assertEqual(set(r), KEYS, text)
            self.assertEqual((r["meaning"], r["p"]), (meaning, p), text)
            self.assertEqual(r["action"], ACTIONS[meaning] if p >= 0.8 else "reask", text)
            self.assertIn(r["named"], SITE + ["not_said"], text)
            self.assertTrue(0.0 <= r["p_named"] <= 1.0, text)

    def test_the_five_meanings(self):
        self.assertEqual(decide.MEANINGS, MEANINGS)

    def test_a_reply_never_reads_as_an_alarm_unless_it_says_stranger(self):
        for text in ("no", "yes", "wait what", "thats my friend", "on it", "handled"):
            self.assertNotEqual(decide.read_reply(WHO, text)["action"], "alarm", text)


class Row(unittest.TestCase):
    """One reply.decided row per reading: agent central (a chat answer, not a stop's model call), never tool decided."""

    def test_one_reply_decided_row(self):
        n0 = len(ledger.rows())
        r = decide.read_reply(WHO, "thats my friend", trigger="alarm:row-1", chat=ONCALL, **{"from": HANDLE})
        new = ledger.rows()[n0:]
        self.assertEqual([x["tool"] for x in new], ["reply.decided"])
        row = new[0]
        self.assertEqual((row["agent"], row["app"], row["ok"], row["cached"], row["source"]), ("central", "stub", True, True, "stub"))
        a = row["args"]
        self.assertEqual((a["question"], a["text"], a["trigger"], a["chat"], a["from"], a["threshold"], a["model"]),
                         (WHO, "thats my friend", "alarm:row-1", ONCALL, HANDLE, 0.8, "stub"))
        self.assertTrue(isinstance(a["shift_id"], str) and a["shift_id"])
        self.assertEqual(row["state_before"], {"meanings": MEANINGS, "labels": SITE + ["not_said"]})
        self.assertEqual(row["state_after"], r)
        self.assertIsInstance(row["latency_ms"], int)
        self.assertTrue(isinstance(row["response_or_error"], str) and row["response_or_error"])   # the stub's rule, named


class Threshold(unittest.TestCase):
    def tearDown(self):
        os.environ["WTDD_REPLY_THRESHOLD"] = ""

    def test_default_is_point_eight(self):
        self.assertEqual(decide.reply_threshold(), 0.8)

    def test_below_the_threshold_is_a_reask(self):
        os.environ["WTDD_REPLY_THRESHOLD"] = "0.95"
        r = decide.read_reply(WHO, "thats my friend")
        self.assertEqual((r["meaning"], r["action"]), ("standing_down", "reask"))
        self.assertEqual(ledger.rows(1)[0]["args"]["threshold"], 0.95)

    def test_a_bad_threshold_fails_loud_on_the_row(self):
        for bad in ("abc", "1.5", "-0.1"):
            os.environ["WTDD_REPLY_THRESHOLD"] = bad
            with self.assertRaises(ValueError, msg=bad):
                decide.read_reply(WHO, "idk")
            self.assertEqual((ledger.rows(1)[0]["tool"], ledger.rows(1)[0]["ok"]), ("reply.decided", False), bad)


class Live(unittest.TestCase):
    """requests.post patched (no network, no key): one request carrying two Choice questions, meaning and named; p and
    p_named are the probabilities the reply gives the chosen options; the row says live. REPLY is shaped on OpenRouter's
    documented System One reply (answers: {<question>: {type, choice, confidence, probabilities}}); its meaning numbers are
    the probe's for this reply (C_reply my_friend: standing_down 0.98); the named answer is written here. Not a live reply."""
    REPLY = {"model": "typesafe/jev-1.13-20260917", "usage": {"input_tokens": 300, "output_tokens": 60},
             "answers": {"meaning": {"type": "choice", "choice": "standing_down", "confidence": 0.9,
                                     "probabilities": {"acknowledged": 0.0, "handled": 0.01, "standing_down": 0.98, "stranger": 0.01, "unclear": 0.0}},
                         "named": {"type": "choice", "choice": "not_said", "confidence": 0.8,
                                   "probabilities": {**{x: 0.02 for x in SITE}, "not_said": 0.88}}}}

    def _read(self, reply, status=200, text="thats my friend"):
        resp = mock.Mock(status_code=status, text=json.dumps(reply))
        resp.json.return_value = reply
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "test-key", "JEV_MODEL": ""}), \
                mock.patch.object(decide.requests, "post", return_value=resp) as post:
            return decide.read_reply(WHO, text, trigger="alarm:live-1"), post

    def test_one_request_two_questions(self):
        r, post = self._read(self.REPLY)
        self.assertEqual(r, {"meaning": "standing_down", "p": 0.98, "named": "not_said", "p_named": 0.88, "action": "stand_down"})
        post.assert_called_once()
        kw = post.call_args.kwargs
        body = kw["json"]
        self.assertEqual(kw["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(body["model"], "typesafe/jev-1.13")
        self.assertEqual(body["state"], "the dog asked: who dis?!\nthey replied: thats my friend")   # nothing else: accuracy falls with unrelated state
        self.assertEqual(list(body["questions"]), ["meaning", "named"])
        self.assertEqual([q["type"] for q in body["questions"].values()], ["choice", "choice"])
        self.assertEqual(list(body["questions"]["meaning"]["criteria"]), MEANINGS)
        self.assertEqual(list(body["questions"]["named"]["criteria"]), SITE + ["not_said"])
        row = ledger.rows(1)[0]
        self.assertEqual((row["tool"], row["ok"], row["source"], row["cached"], row["app"], row["args"]["model"]),
                         ("reply.decided", True, "live", False, "openrouter", "typesafe/jev-1.13-20260917"))
        self.assertIn('"answers"', row["response_or_error"])
        self.assertEqual(row["state_after"], r)

    def test_a_meaning_that_was_not_offered_fails_loud(self):
        bad = json.loads(json.dumps(self.REPLY))
        bad["answers"]["meaning"] = {"type": "choice", "choice": "banana", "probabilities": {"banana": 0.9}}
        with self.assertRaises(ValueError):
            self._read(bad)
        self.assertEqual((ledger.rows(1)[0]["tool"], ledger.rows(1)[0]["ok"]), ("reply.decided", False))

    def test_a_reply_without_both_answers_fails_loud(self):
        for reply, status in (({"model": "x", "answers": {"meaning": self.REPLY["answers"]["meaning"]}}, 200), ({"error": "no credits"}, 402)):
            with self.assertRaises(RuntimeError, msg=reply):
                self._read(reply, status)
            row = ledger.rows(1)[0]
            self.assertEqual((row["tool"], row["ok"], row["source"]), ("reply.decided", False, "live"))

    def test_a_refused_connection_is_a_failed_row_never_the_stub(self):
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "not-a-real-key"}), mock.patch.object(decide, "JEV_URL", "http://127.0.0.1:9/"), \
                mock.patch.object(decide, "JEV_TIMEOUT_S", 2):
            with self.assertRaises(requests.RequestException):   # the transport's own error, raised, not a missing function
                decide.read_reply(WHO, "idk who that is")
        row = ledger.rows(1)[0]
        self.assertEqual((row["tool"], row["ok"], row["source"], row["cached"]), ("reply.decided", False, "live", False))
        self.assertIsNone(row["state_after"])
        self.assertIn("Error", row["response_or_error"])


class Cli(unittest.TestCase):
    """The goal's command: python -m wtdd.decide --reply TEXT --asked QUESTION prints the typed reading."""

    def _run(self, *args, **env):
        e = {**os.environ, "WTDD_LEDGER": str(_TMP / "cli-ledger.jsonl"), "JEV_API_KEY": "", "JEV_LIVE": "",
             "WTDD_REPLY_THRESHOLD": "", **env}
        return subprocess.run([PY, "-m", "wtdd.decide", *args], capture_output=True, text=True, cwd=ROOT, env=e, timeout=60)

    def test_reply_prints_the_typed_meaning(self):
        pr = self._run("--reply", "thats my friend", "--asked", WHO)
        self.assertEqual(pr.returncode, 0, pr.stderr)
        d = json.loads(pr.stdout.strip().splitlines()[-1])
        self.assertEqual((d["meaning"], d["action"]), ("standing_down", "stand_down"))
        self.assertIn("stub", pr.stderr.lower())   # the stderr line says it was not live
        rows = [json.loads(x) for x in (_TMP / "cli-ledger.jsonl").read_text().splitlines() if x.strip()]
        self.assertEqual(rows[-1]["tool"], "reply.decided")

    def test_live_without_a_key_exits_two(self):
        pr = self._run("--reply", "idk", "--asked", WHO, JEV_LIVE="1")
        self.assertEqual(pr.returncode, 2, pr.stderr)
        self.assertIn("JEV_API_KEY", pr.stderr)


class Verdict(unittest.TestCase):
    """listen.verdict() typed, driven directly (who may answer is 03's allowed(), tested there). tools.call is patched."""

    def setUp(self):
        self.posts: list[tuple] = []
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener(GROUP, lambda g, k, kind, t, f: self.posts.append((g, k, kind, t, f)), listen_s=60)
        self.trigger = f"alarm:{self._testMethodName}"
        self.pend = _TMP / f"pending-{self._testMethodName}.json"
        self.addCleanup(lambda: self.pend.unlink(missing_ok=True))

    def _ask(self, kind: str) -> None:
        # as the writers write it: listen's heads_up names its question; a who_dis without one is intruder_alarm's
        self.pend.write_text(json.dumps({"kind": kind, "t": time.time(), "file": "/tmp/f.jpg", "seconds": 5,
                                         "trigger": self.trigger, "chat": ONCALL, **({"question": HEADS} if kind == "heads_up" else {})}))

    def _m(self, text: str, n: int = 1, ts: str = "2026-09-27 12:18:22") -> dict:
        return {"rowid": n, "guid": f"R-{self._testMethodName}-{n}", "text": text, "is_from_me": 0, "sender": HANDLE,
                "ts_utc": ts, "attachments": [], "chat": ONCALL}

    def _say(self, text: str, n: int = 1, ts: str = "2026-09-27 12:18:22", **env: str):
        with mock.patch.dict(os.environ, env), mock.patch.object(L, "PENDING", self.pend), \
                mock.patch("wtdd.tools.call", return_value={"signaled": [], "errors": []}) as call:
            got = self.l.verdict(self._m(text, n, ts))
        return got, call

    def _flagged(self, utc: str) -> None:
        """The flag's confirmed chat.post under this check's trigger (read back at `utc`, chat.db's clock), so acked_ms is a number."""
        ledger.append({"step": "chat.post", "agent": "central", "tool": "chat.post", "app": "imessage", "ok": True,
                       "args": {"guid": ONCALL, "kind": "escalate", "trigger": self.trigger, "text": "who dis?!", "file": "/tmp/f.jpg"},
                       "state_before": None, "state_after": {"guid": f"P-{self._testMethodName}", "rowid": 1, "ts": utc},
                       "response_or_error": None, "latency_ms": 0})

    def _rows(self, tool: str) -> list[dict]:
        key = "trigger" if tool == "reply.decided" else "asked"
        return [r for r in ledger.rows() if r.get("tool") == tool and (r.get("args") or {}).get(key) == self.trigger]

    def _verdicts(self) -> list[tuple]:
        return [(r["state_after"].get("verdict"), r["state_after"].get("action")) for r in self._rows("intruder.verdict")]

    def _texts(self) -> list[str]:
        return [t for _, _, _, t, _ in self.posts]

    def test_idk_to_who_dis_is_the_alarm_read_typed(self):
        self._ask("who_dis")
        got, call = self._say("idk who that is")
        self.assertTrue(got)
        call.assert_called_once_with("light_alarm", seconds=5)
        read = self._rows("reply.decided")
        self.assertEqual([(r["state_after"]["meaning"], r["state_after"]["action"]) for r in read], [("stranger", "alarm")])
        v = self._rows("intruder.verdict")
        self.assertEqual({k: v[0]["state_after"].get(k) for k in ("verdict", "meaning", "p", "action")},
                         {"verdict": "stranger", "meaning": "stranger", "p": 0.9, "action": "alarm"})
        self.assertIn("acked_ms", v[0]["args"])
        order = [r["tool"] for r in ledger.rows() if self.trigger in ((r.get("args") or {}).get("trigger"), (r.get("args") or {}).get("asked"))]
        self.assertEqual(order, ["reply.decided", "intruder.verdict"])   # the reading, then the verdict it set
        self.assertTrue(self._texts()[0].startswith("STRANGER DANGER"))
        self.assertEqual(self.posts[0][0], ONCALL)
        self.assertFalse(self.pend.exists())

    def test_a_friend_stands_down(self):
        self._ask("who_dis")
        got, call = self._say("thats my friend")
        call.assert_not_called()
        self.assertEqual(self._verdicts(), [("known", "stand_down")])
        self.assertEqual(self.posts, [(ONCALL, f"ok:R-{self._testMethodName}-1", "listen", STANDING_DOWN, None)])
        self.assertFalse(self.pend.exists())

    def test_idk_to_a_heads_up_never_sounds_the_alarm(self):
        self._ask("heads_up")
        got, call = self._say("idk who that is")
        self.assertTrue(got)
        call.assert_not_called()   # the alarm is lights and "STRANGER DANGER", built for a person; a hole gets nothing from it
        self.assertEqual(self._verdicts(), [("stranger", "stand_down")])
        self.assertEqual(self._texts(), [STANDING_DOWN])
        self.assertFalse(self.pend.exists())

    def test_on_it_holds_the_flag_open_then_handled_closes_it(self):
        self._ask("heads_up")
        got, call = self._say("on it", 1)
        self.assertTrue(got)
        call.assert_not_called()
        self.assertEqual(self._verdicts(), [("acknowledged", "hold")])
        self.assertIn("acked_ms", self._rows("intruder.verdict")[0]["args"])
        self.assertTrue(self.pend.exists())   # still open: waiting for handled
        self.assertEqual(json.loads(self.pend.read_text())["trigger"], self.trigger)
        got, call = self._say("handled, cover is back on", 2)
        self.assertTrue(got)
        call.assert_not_called()
        self.assertEqual(self._verdicts(), [("acknowledged", "hold"), ("handled", "close")])
        self.assertFalse(self.pend.exists())
        self.assertFalse(any(t.startswith("STRANGER") for t in self._texts()))

    def test_an_unclear_reply_is_asked_once_more_then_stands_down(self):
        self._ask("who_dis")
        got, call = self._say("wait what", 1)
        self.assertTrue(got)
        call.assert_not_called()
        self.assertEqual(self._verdicts(), [])   # no verdict yet: the question is still open
        self.assertEqual(self.posts, [(ONCALL, f"reask:R-{self._testMethodName}-1", "listen", REASK, None)])
        self.assertTrue(REASK.startswith(L.OWN_OPENERS))   # the dog never reads its own re-ask as the answer
        self.assertIs(json.loads(self.pend.read_text()).get("reasked"), True)
        got, call = self._say("wait what", 2)
        self.assertTrue(got)
        call.assert_not_called()   # never an alarm on an unclear reply
        self.assertEqual(self._verdicts(), [("unclear", "stand_down")])
        self.assertEqual(self._texts(), [REASK, STANDING_DOWN])
        self.assertEqual([r["state_after"]["meaning"] for r in self._rows("reply.decided")], ["unclear", "unclear"])
        self.assertFalse(self.pend.exists())

    def test_a_stranger_below_the_threshold_is_asked_again_not_the_alarm(self):
        self._ask("who_dis")
        got, call = self._say("idk who that is", WTDD_REPLY_THRESHOLD="0.95")
        call.assert_not_called()
        self.assertEqual(self._texts(), [REASK])
        self.assertIs(json.loads(self.pend.read_text()).get("reasked"), True)

    def test_a_live_failure_posts_couldnt_read_and_stands_down_never_the_regex(self):
        self._ask("who_dis")
        with mock.patch.object(decide, "JEV_URL", "http://127.0.0.1:9/"), mock.patch.object(decide, "JEV_TIMEOUT_S", 2):
            got, call = self._say("idk who that is", JEV_API_KEY="not-a-real-key")
        self.assertTrue(got)
        call.assert_not_called()   # the regex reads "idk" as a stranger: it is not the fallback of a failed live call
        self.assertEqual([(r["ok"], r["source"]) for r in self._rows("reply.decided")], [(False, "live")])
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0][0], ONCALL)
        self.assertTrue(self.posts[0][3].startswith("couldn't read the reply"), self.posts[0][3])
        self.assertEqual(self._verdicts(), [("unread", "stand_down")])
        v = self._rows("intruder.verdict")[0]
        self.assertEqual((v["cached"], v["source"]), (False, "live"))   # no reading happened, so nothing on it is the stub's
        self.assertFalse(self.pend.exists())

    def test_a_halt_is_never_read_as_a_reply(self):
        self._ask("halt")
        got, call = self._say("ok go on")
        self.assertFalse(got)
        call.assert_not_called()
        self.assertEqual(self._rows("reply.decided"), [])
        self.assertEqual(self._rows("intruder.verdict"), [])
        self.assertTrue(self.pend.exists())
        self.assertEqual(self.posts, [])

    def test_the_round_keeps_holding_across_the_reask(self):
        self._ask("who_dis")
        batches = [[self._m("wait what", 1)], [], [self._m("thats my friend", 2)]]
        with mock.patch.object(self.l, "read", side_effect=lambda: batches.pop(0) if batches else []), \
                mock.patch.object(self.l, "allowed", return_value=True), mock.patch.object(L, "PENDING", self.pend), \
                mock.patch.object(L.time, "sleep"), mock.patch("wtdd.tools.call") as call:
            self.assertTrue(self.l.await_verdict(30))
        call.assert_not_called()
        self.assertEqual(self._texts(), [REASK, STANDING_DOWN])
        self.assertEqual(self._verdicts(), [("known", "stand_down")])

    # ---------- fix round 1 (review of 17): each check below was seen failing before its fix

    def test_the_answer_to_the_reask_is_read_against_the_reask(self):
        """After "do you know them? yes or no", the next reply answers that, not "who dis?!": its reply.decided row says so
        (args.question), and the state the model reads is that question and that answer."""
        self._ask("who_dis")
        self._say("wait what", 1)
        self.assertEqual(json.loads(self.pend.read_text()).get("question"), REASK)
        self._say("no", 2)
        read = self._rows("reply.decided")
        self.assertEqual([(r["args"]["question"], r["args"]["text"]) for r in read], [(WHO, "wait what"), (REASK, "no")])

    def test_one_acked_ms_per_flag_the_close_is_closed_ms(self):
        """A held flag has two verdict rows; only the first carries acked_ms (numbers.py and 10's record count every one).
        The close's time from the flag is args.closed_ms."""
        self._ask("heads_up")
        self._flagged("2026-09-27 12:18:10")
        self._say("on it", 1, "2026-09-27 12:18:22")
        self._say("handled, cover is back on", 2, "2026-09-27 12:19:45")
        held, closed = [r["args"] for r in self._rows("intruder.verdict")]
        self.assertEqual(held["acked_ms"], 12000)
        self.assertNotIn("acked_ms", closed)
        self.assertEqual(closed["closed_ms"], 95000)
        self.assertEqual(closed["shift_id"], held["shift_id"])

    def test_after_a_reask_acked_ms_is_the_first_replys(self):
        """The re-ask writes no verdict row, so the final row carries the first reply's time: the person answered then."""
        self._ask("who_dis")
        self._flagged("2026-09-27 12:18:10")
        self._say("wait what", 1, "2026-09-27 12:18:22")
        self._say("thats my friend", 2, "2026-09-27 12:19:00")
        self.assertEqual([r["args"]["acked_ms"] for r in self._rows("intruder.verdict")], [12000])

    def test_a_stub_reading_is_a_stub_verdict_row(self):
        """The verdict's meaning and p are the DEMO_CACHE reader's when JEV_API_KEY is unset: the row says so, like its
        reply.decided row beside it (10's record counts cached rows for its "a fixture, not a night" header)."""
        self._ask("who_dis")
        self._say("thats my friend")
        v = self._rows("intruder.verdict")[0]
        self.assertEqual((v["cached"], v["source"]), (True, "stub"))

    # ---------- fix round 2 (second review of 17): each check below was seen failing before its fix

    def test_no_to_the_reask_is_a_stranger_and_the_alarm(self):
        """"do you know them? yes or no" answered "no" means they do not know them: on a who_dis flag, the alarm. The stub
        read it with 02's CORRECTION (^no) as standing_down and stood a confirmed stranger down."""
        self._ask("who_dis")
        self._say("wait what", 1)
        got, call = self._say("no", 2)
        self.assertTrue(got)
        call.assert_called_once_with("light_alarm", seconds=5)
        self.assertEqual(self._verdicts(), [("stranger", "alarm")])
        self.assertEqual([r["state_after"]["meaning"] for r in self._rows("reply.decided")], ["unclear", "stranger"])
        self.assertEqual(self._texts()[0], REASK)
        self.assertTrue(self._texts()[1].startswith("STRANGER DANGER"))

    def test_yes_to_the_reask_stands_down(self):
        """"yes" to "do you know them?" means they know them: known, "ok, standing down". The stub read it unclear."""
        self._ask("who_dis")
        self._say("wait what", 1)
        got, call = self._say("yes", 2)
        self.assertTrue(got)
        call.assert_not_called()
        self.assertEqual(self._verdicts(), [("known", "stand_down")])
        self.assertEqual(self._texts(), [REASK, STANDING_DOWN])

    # ---------- fix round 3 (third review of 17): seen failing before its fix

    def test_a_reply_older_than_the_open_question_is_not_its_answer(self):
        """The demo path: "on it" holds the opening at stop 10, the round walks on, the person on call types "handled"
        while the dog walks, then stop 22 flags "who dis?!" in the same 1:1. The "handled" was typed before that flag's
        confirmed post, so it cannot answer it: no reading, no verdict, the who-dis stays open (one WARN), and the next
        reply decides it. Only a confirmed post can prove this; a dry or failed post reads as before."""
        self.trigger = f"decide:{self._testMethodName}:10"
        self._ask("heads_up")
        self._flagged("2026-09-27 12:18:10")
        self._say("on it", 1, "2026-09-27 12:18:22")                   # held
        self.trigger = f"alarm:{self._testMethodName}:22"
        self._ask("who_dis")                                            # the next stop's question replaces the held flag
        self._flagged("2026-09-27 12:19:30")                            # its confirmed post, T2
        with mock.patch.object(L, "log") as log:
            got, call = self._say("handled, cover is back on", 2, "2026-09-27 12:19:05")   # typed at T1 < T2
        self.assertFalse(got)
        call.assert_not_called()
        self.assertEqual(self._rows("reply.decided"), [])
        self.assertEqual(self._rows("intruder.verdict"), [])
        self.assertEqual(json.loads(self.pend.read_text())["kind"], "who_dis")
        self.assertEqual(self.posts, [])
        warns = [c for c in log.call_args_list if str(c.args[1]).startswith("WARN")]
        self.assertEqual(len(warns), 1, log.call_args_list)
        self.assertEqual((warns[0].kwargs["trigger"], warns[0].kwargs["reply"]), (self.trigger, f"R-{self._testMethodName}-2"))
        got, call = self._say("idk who that is", 3, "2026-09-27 12:19:40")
        self.assertTrue(got)
        call.assert_called_once_with("light_alarm", seconds=5)
        self.assertEqual(self._verdicts(), [("stranger", "alarm")])
        self.assertEqual(self._rows("intruder.verdict")[0]["args"]["acked_ms"], 10000)

    # ---------- round 4 (the final review of 17, fixed by the head's grant): each check below was seen failing before its fix

    def _poll(self, at: float | None = None) -> None:
        """One poll() with no new messages, the clock at `at` when given (the window checks read time.time())."""
        with mock.patch.object(L, "PENDING", self.pend), mock.patch.object(L, "HEARTBEAT", _TMP / "listen.json"), \
                mock.patch.object(self.l, "read", return_value=[]), mock.patch("wtdd.tools.call") as call, \
                mock.patch.object(L.time, "time", return_value=at if at is not None else time.time()):
            self.l.poll()
        call.assert_not_called()

    def test_an_unanswered_reask_is_one_unclear_verdict_row(self):
        """A heads_up answered "wait what" 9 s after its confirmed post, re-asked, then nothing more: the round's hold
        times out. The person answered, so the flag gets exactly one intruder.verdict row: unclear / stand_down, the first
        reply's acked_ms and reading, stub-labeled like its reply.decided row. Never a silent unlink, never the alarm."""
        self._ask("heads_up")
        self._flagged("2026-09-27 12:00:00")
        batches = [[self._m("wait what", 1, "2026-09-27 12:00:09")]]
        with mock.patch.object(self.l, "read", side_effect=lambda: batches.pop(0) if batches else []), \
                mock.patch.object(self.l, "allowed", return_value=True), mock.patch.object(L, "PENDING", self.pend), \
                mock.patch.object(L.time, "sleep"), mock.patch("wtdd.tools.call") as call:
            self.assertFalse(self.l.await_verdict(0.2))
        call.assert_not_called()
        self.assertEqual(self._texts(), [REASK])
        v = self._rows("intruder.verdict")
        self.assertEqual(len(v), 1, v)
        self.assertEqual({k: v[0]["state_after"].get(k) for k in ("verdict", "meaning", "p", "action")},
                         {"verdict": "unclear", "meaning": "unclear", "p": 0.5, "action": "stand_down"})
        self.assertEqual((v[0]["args"]["acked_ms"], v[0]["args"]["guid"], v[0]["args"]["text"], v[0]["args"]["chat"]),
                         (9000, f"R-{self._testMethodName}-1", "wait what", ONCALL))
        self.assertEqual((v[0]["cached"], v[0]["source"]), (True, "stub"))
        self.assertFalse(self.pend.exists())

    def test_an_unanswered_reask_past_the_window_is_the_same_row(self):
        """The same re-ask left open until poll()'s PENDING_WINDOW_S expiry: the same one row, never a silent unlink."""
        self._ask("heads_up")
        self._flagged("2026-09-27 12:00:00")
        self._say("wait what", 1, "2026-09-27 12:00:09")
        self._poll(time.time() + L.PENDING_WINDOW_S + 1)
        self.assertEqual(self._verdicts(), [("unclear", "stand_down")])
        self.assertEqual(self._rows("intruder.verdict")[0]["args"]["acked_ms"], 9000)
        self.assertFalse(self.pend.exists())

    def test_a_held_flag_outlives_the_question_window_and_handled_closes_it(self):
        """Beat 2.4b: "on it" 12 s after the heads-up, then "handled" when the pending's t is 130 s old, past
        PENDING_WINDOW_S. An acknowledged flag is exempt from that window in poll() and in verdict(), so the close is
        read: handled / close with closed_ms, and "ok, closed"."""
        self._ask("heads_up")
        self._flagged("2026-09-27 12:00:00")
        self._say("on it", 1, "2026-09-27 12:00:12")
        self.pend.write_text(json.dumps({**json.loads(self.pend.read_text()), "t": time.time() - 130}))
        self._poll()
        self.assertTrue(self.pend.exists())   # poll() did not drop the held flag
        got, call = self._say("handled, cover is back on", 2, "2026-09-27 12:02:10")
        self.assertTrue(got)
        call.assert_not_called()
        self.assertEqual(self._verdicts(), [("acknowledged", "hold"), ("handled", "close")])
        self.assertEqual(self._rows("intruder.verdict")[1]["args"]["closed_ms"], 130000)
        self.assertEqual(self._texts(), ["ok, closed"])
        self.assertFalse(self.pend.exists())

    def test_a_held_flag_never_closed_expires_at_the_ack_window_with_its_row(self):
        """A held flag lasts ACK_WINDOW_S (1800 s) after the acknowledgement. Then one loud intruder.verdict row,
        expired / stand_down, naming the acknowledgement it held on and the window (no acked_ms: the hold's row carries
        the flag's one), and one WARN; never a silent unlink."""
        self._ask("heads_up")
        self._flagged("2026-09-27 12:00:00")
        acked_at = time.time()
        self._say("on it", 1, "2026-09-27 12:00:12")
        self._poll(acked_at + 1799)
        self.assertTrue(self.pend.exists())   # inside the window: still open for "handled"
        self.assertEqual(L.ACK_WINDOW_S, 1800)
        with mock.patch.object(L, "log") as log:
            self._poll(acked_at + 1801)
        self.assertFalse(self.pend.exists())
        self.assertEqual(self._verdicts(), [("acknowledged", "hold"), ("expired", "stand_down")])
        held, expired = self._rows("intruder.verdict")
        a = expired["args"]
        self.assertEqual((a["guid"], a["text"], a["chat"], a["window_s"], a["shift_id"]),
                         (f"R-{self._testMethodName}-1", "on it", ONCALL, 1800, held["args"]["shift_id"]))
        self.assertNotIn("acked_ms", a)
        self.assertEqual((expired["state_after"]["meaning"], expired["state_after"]["p"]), ("acknowledged", 0.85))
        self.assertEqual((expired["cached"], expired["source"]), (True, "stub"))
        warns = [c for c in log.call_args_list if str(c.args[1]).startswith("WARN")]
        self.assertEqual(len(warns), 1, log.call_args_list)
        self.assertEqual(warns[0].kwargs["trigger"], self.trigger)
        self.assertEqual(self.posts, [])


class Fixture(unittest.TestCase):
    """The committed remote fixture read by the README's numbers: one flag, one acked_ms (the hold's), not the close's too."""

    def test_numbers_counts_one_acked_ms_for_the_one_flag(self):
        from wtdd import numbers
        rows = [json.loads(x) for x in (ROOT / "wtdd" / "fixtures" / "ledger-17-remote.jsonl").read_text().splitlines() if x.strip()]
        s = numbers.shifts(rows)
        self.assertEqual([(x["shift_id"], x["flags"], x["acked_ms"]) for x in s], [("2026-09-27", 1, [12000])])


if __name__ == "__main__":
    unittest.main()
