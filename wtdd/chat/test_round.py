"""The round's safety and its beats (fix/round-safety, from the preflight of 2026-09-27). Run:
    python -m unittest wtdd.chat.test_round -v

wake_show and field.walk run for real against a fake API: requests.get / requests.post are patched with Api below
(POST /dog/follow, /dog/resume, /dog/stop; GET /dog/state plays a script of follower states, and a script entry that
is an exception is raised as that read's failure, a callable is called first). Light writes are recorded, never sent
(field._write); the look is stubbed (dog_say.look_and_see); posts are collected by the poster. Offline like test_chat:
WTDD_LEDGER / WTDD_MEMORY point at scratch files before the package is imported; field.MAP (a scratch copy of
wtdd/fixtures/map_route.json, its first 11 dots), FIELD and STOP, and the listener's PENDING, STATE and HEARTBEAT are patched to scratch
paths, so no check touches the checkout's map, its live walk file, a light, the dog or the chat. JEV_API_KEY and the
on-call keys are forced empty (a .env key must not make these live). Each check was seen failing before its fix (the
PR's Proof table names the RED and fix commits)."""
from __future__ import annotations
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-round-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
for _k in ("JEV_API_KEY", "JEV_MODEL", "JEV_LIVE", "WTDD_REPLY_THRESHOLD", "WTDD_DECIDE_THRESHOLD", "WTDD_ON_CALL_GUID",
           "WTDD_ON_CALL_HANDLE", "WTDD_ALARM", "WTDD_AGENT", "WTDD_ALLOW_SELF", "WTDD_COMMANDS", "WTDD_TRIGGERS", "WTDD_ROUND_AVOID"):
    os.environ[_k] = ""   # config.maybe() reads an empty value as unset: the defaults, never a live call

import requests  # noqa: E402
from wtdd import config, field, ledger  # noqa: E402
from wtdd.chat import listen as L  # noqa: E402

MAP = _TMP / "map.json"
_m = json.loads((Path(field.__file__).parent / "fixtures" / "map_route.json").read_text())
PATH = _m["path"] = _m["path"][:11]   # its first 11 dots: the fixture's 12th is a 526 px jump, which check_path refuses
MAP.write_text(json.dumps(_m))
GROUP = "any;+;00000000000000000000000000000000"
SEEN = {"text": "a chair by the door", "file": "/tmp/look.jpg", "person": False, "detector": {"classes": {}},
        "decision": {"label": "clear", "p": 0.9, "needs_person": False, "model": "stub", "action": "continue"}}


def state(i: int, p=None, **follow) -> dict:
    """One GET /dog/state: the follower at path index i, the pose on that dot (or p), as session.follow_state reads."""
    return {"map": {"p": p or PATH[i]}, "follow": {"active": True, "i": i, "stopped_at": None, "done": False, "error": None, **follow}}


def msg(text: str, guid: str = "W1", rowid: int = 1, sender: str = "+15550001111") -> dict:
    return {"rowid": rowid, "guid": guid, "text": text, "is_from_me": 0, "sender": sender,
            "ts_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "attachments": [], "chat": GROUP}


class Api:
    """The API process as the round sees it. GET /dog/state returns the next scripted state (the last one repeats); an
    exception in the script is raised as that read, a callable is called and its result returned. Every call is
    appended to `events`, which the look shares, so the order of stop and look is checkable."""

    def __init__(self, states: list, events: list, follow_ok: bool = True, stop_fails: bool = False):
        self.states, self.events, self.follow_ok, self.stop_fails = list(states), events, follow_ok, stop_fails

    def get(self, url: str, **kw):
        self.events.append(("GET", url[len(config.API):]))
        s = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        s = s() if callable(s) else s
        if isinstance(s, BaseException):
            raise s
        return SimpleNamespace(json=lambda: s)

    def post(self, url: str, json: dict | None = None, **kw):
        path = url[len(config.API):]
        self.events.append(("POST", path))
        if path == "/dog/stop" and self.stop_fails:
            raise requests.ConnectionError("the API is not answering")
        if path == "/dog/follow":
            return SimpleNamespace(json=lambda: {"ok": True, "follow": {"i": 0, "n": len(PATH), "stops": []}} if self.follow_ok
                                   else {"ok": False, "error": "RuntimeError: already following; POST /dog/stop first"})
        return SimpleNamespace(json=lambda: {"ok": True})


class Round(unittest.TestCase):
    """wake_show with WTDD_ROUND=dog: the follower is the fake API's, the field follows its pose."""

    def setUp(self):
        self.events: list = []
        self.posts: list[tuple[str, str | None]] = []
        self.writes: list[tuple[str, int]] = []
        self.n0 = len(ledger.rows())
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener(GROUP, lambda g, k, kind, t, f: self.posts.append((k, t)), listen_s=60)
        for p in (mock.patch.dict(os.environ, {"WTDD_ROUND": "dog"}),
                  mock.patch.object(field, "MAP", MAP), mock.patch.object(field, "FIELD", _TMP / "field.json"),
                  mock.patch.object(field, "STOP", _TMP / "field.stop"), mock.patch.object(field, "HZ", 200.0),
                  mock.patch.object(field, "_write", self._write),
                  mock.patch.object(L, "PENDING", _TMP / "pending.json"), mock.patch.object(L, "STATE", _TMP / "state.json"),
                  mock.patch.object(L, "HEARTBEAT", _TMP / "listen.json"),
                  mock.patch("wtdd.tools.dog_say.look_and_see", self._look), mock.patch("wtdd.tools.call", self._tool)):
            self.enterContext(p)
        self.addCleanup(lambda: field.STOP.unlink(missing_ok=True))
        self._stops([])

    def _write(self, light: dict, level: int) -> float:
        self.writes.append((light["id"], level))
        return 0.0

    def _look(self, look: str = "tilt", stop: int | None = None) -> dict:
        self.events.append(("look", stop))
        return dict(SEEN)

    def _tool(self, name: str, **kw) -> dict:
        if name == "dog_on_fire":
            return {"file": "/tmp/fire.jpg"}
        raise AssertionError(f"no tool call expected here: {name}")

    def _stops(self, stops: list[int]) -> None:
        m = json.loads(MAP.read_text())
        m["stops"] = stops
        MAP.write_text(json.dumps(m))

    def round(self, states: list, **api) -> None:
        self.api = Api(states, self.events, **api)
        with mock.patch.object(requests, "get", self.api.get), mock.patch.object(requests, "post", self.api.post):
            self.l.wake_show(msg("what the dog doin"))

    def rows(self, tool: str) -> list[dict]:
        return [r for r in ledger.rows()[self.n0:] if r["tool"] == tool]

    # ask 1 = lights 1: the walk fails mid-round (one slow /dog/state read), the follower is still driving

    def test_a_failed_walk_stops_the_follower_before_the_end_look(self):
        self.round([state(1), state(2), requests.ReadTimeout("read timeout=3")])
        self.assertIn(("POST", "/dog/stop"), self.events, "the follower was left driving the dog after the walk failed")
        self.assertLess(self.events.index(("POST", "/dog/stop")), self.events.index(("look", None)), "stop first, then the end look")
        self.assertTrue(self.posts[-1][1].startswith("dog done (couldn't walk the path: ReadTimeout"), self.posts[-1])
        self.assertEqual([r["ok"] for r in self.rows("dog.stop")], [True], "one dog.stop row: the stop is a step with a receipt")

    def test_ctrl_c_mid_round_stops_the_follower_and_exits(self):
        with self.assertRaises(KeyboardInterrupt):
            self.round([state(1), KeyboardInterrupt()])
        self.assertIn(("POST", "/dog/stop"), self.events, "Ctrl-C of the listener left the follower driving")
        self.assertNotIn(("look", None), self.events)   # the listener is exiting: no look, no "dog done"

    def test_a_failed_stop_is_a_failed_row_and_the_round_still_ends(self):
        self.round([state(1), requests.ReadTimeout("read timeout=3")], stop_fails=True)
        self.assertIn(("POST", "/dog/stop"), self.events)
        self.assertTrue(self.posts[-1][1].startswith("dog done (couldn't walk the path"), self.posts[-1])
        stop = self.rows("dog.stop")
        self.assertEqual([r["ok"] for r in stop], [False])
        self.assertIn("ConnectionError", stop[0]["response_or_error"])

    # lights 1: field.walk ends dark and drains its pool even when it raises (a failed read) or is interrupted (Ctrl-C)

    def test_a_walk_that_fails_or_is_interrupted_ends_dark(self):
        lamp = json.loads(MAP.read_text())["lights"][0]
        for err in (requests.ReadTimeout("read timeout=3"), KeyboardInterrupt()):
            with self.subTest(err=type(err).__name__):
                self.writes.clear()
                api = Api([state(1, p=lamp["pts"][0]), err], self.events)   # the dog on the lamp: it goes to 100, then the read fails
                with mock.patch.object(requests, "get", api.get), self.assertRaises(type(err)):
                    field.walk(source="dog")
                mine = [lv for lid, lv in self.writes if lid == lamp["id"]]
                self.assertEqual([lv > 0 for lv in mine], [False, True, False], f"the lamp wrote {mine}: left lit after the walk")
                self.assertEqual(set({lid: lv for lid, lv in self.writes}.values()), {0}, f"every light ends at 0: {self.writes}")

    # ask 2: Stop on either dashboard mid-round (field.stop, and /dog/stop) is no end look and "dog done (stopped)"

    def test_stop_pressed_mid_round_is_no_end_look_and_dog_done_stopped(self):
        pressed = lambda: (field.STOP.write_text("x"), state(2))[1]   # noqa: E731  the dashboard's /field/stop lands during this read
        ended = state(2, active=False, error="stopped")                # its /dog/stop reached the follower first
        for name, script in (("field.stop", [state(1), pressed]), ("follow ended: stopped", [state(1), ended])):
            with self.subTest(name):
                self.events.clear()
                self.posts.clear()
                self.round(script)
                self.assertNotIn(("look", None), self.events, "the dog looked (and could ask who dis) after Stop")
                self.assertTrue(self.posts[-1][1].startswith("dog done (stopped)"), self.posts[-1])

    def test_a_stop_left_from_an_earlier_walk_does_not_skip_the_look(self):
        """Guards the fix's clock (passes before it): field.stop is cleared only when a walk starts, so one left from
        before this wake (the follow refused, the walk never began) is not this round's Stop. A bare STOP.exists() fails."""
        field.STOP.write_text("x")
        os.utime(field.STOP, (time.time() - 60, time.time() - 60))
        self.round([state(1)], follow_ok=False)
        self.assertIn(("look", None), self.events)
        self.assertTrue(self.posts[-1][1].startswith("dog done (couldn't walk the path: RuntimeError: follow refused"), self.posts[-1])



class Wake(unittest.TestCase):
    """ask 8: handle() with WTDD_WAKE_SHOW=1 and the round stubbed (it only moves chat.db's MAX(ROWID) and outlasts
    listen_s), so the message's own ROWID against the round's end is what decides."""

    def test_a_wake_sent_during_the_round_starts_nothing_and_one_after_dog_done_starts_the_next(self):
        top = [100]                                    # chat.db's MAX(ROWID)
        rounds: list[str] = []
        with mock.patch.object(L.db, "max_rowid", side_effect=lambda: top[0]), \
                mock.patch.dict(os.environ, {"WTDD_WAKE_SHOW": "1"}), \
                mock.patch.object(L, "PENDING", _TMP / "pending-wake.json"), mock.patch.object(L, "STATE", _TMP / "state-wake.json"):
            l = L.Listener(GROUP, lambda *a: None, listen_s=60)

            def show(m: dict) -> None:
                rounds.append(m["guid"])
                top[0] += 3              # during the round: the wake's row, a second "what the dog doin", "dog done"
                l.armed_until = 0.0      # the round outlasted listen_s: the chat is no longer listening when it ends

            l.wake_show = show
            l.handle(msg("what the dog doin", "W1", 101))
            l.handle(msg("what the dog doin", "W2", 102))   # typed during W1's round, read after its "dog done"
            l.handle(msg("what the dog doin", "W3", 104))   # typed after "dog done": the next take
        self.assertEqual(rounds, ["W1", "W3"])



class Reply(unittest.TestCase):
    """The group as its own on-call chat (S10, WTDD_ON_CALL_GUID = the group), a who_dis question open in it, the
    replies read by the DEMO_CACHE stub (no JEV_API_KEY); tools.call patched, so no alarm light is written."""

    def setUp(self):
        self.posts: list[tuple[str, str | None]] = []
        self.pend = _TMP / f"pending-{self._testMethodName}.json"
        with mock.patch.dict(os.environ, {"WTDD_ON_CALL_GUID": GROUP}), mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener(GROUP, lambda g, k, kind, t, f: self.posts.append((k, t)), listen_s=60)
        self.enterContext(mock.patch.object(L, "PENDING", self.pend))
        self.enterContext(mock.patch("wtdd.tools.call"))
        self.addCleanup(lambda: self.pend.unlink(missing_ok=True))

    def _ask(self, trigger: str) -> None:
        self.pend.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "file": "/tmp/look.jpg", "seconds": 5,
                                         "trigger": trigger, "chat": GROUP, "question": "who dis?!"}))

    # ask 3: one-word commands fuzzy-match one word of a sentence ("it" is sit at 0.8), so a real answer was dropped

    def test_a_reply_with_a_command_word_in_it_is_read_and_a_bare_command_is_not(self):
        self.assertTrue(self.l.group_oncall)
        for text, read in (("it is teri", True), ("right, that's teri", True), ("hell no", True), ("looks like teri", True),
                           ("sit", False), ("lights off", False)):
            with self.subTest(text):
                self._ask(f"alarm:{text}")
                self.assertEqual(self.l.verdict(msg(text, f"R-{text}")), read, "a bare command is the group's; anything else is an answer")

    # ask 4: the re-ask ("do you know them? yes or no") had only what was left of the first 45 s

    def test_the_reask_gets_its_own_wait(self):
        """An unclear first reply at 40 s of the 45 s hold, then "yes" to the re-ask at 48 s: read, "ok, standing down"."""
        self._ask("alarm:reask")
        clock = [0.0]
        due = [(40.0, msg("wait what", "R-1")), (48.0, msg("yes", "R-2"))]

        def read() -> list[dict]:
            out = [m for t, m in due if t <= clock[0]]
            del due[:len(out)]
            return out

        with mock.patch.object(L.time, "monotonic", lambda: clock[0]), \
                mock.patch.object(L.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s)), \
                mock.patch.object(self.l, "read", read):
            self.assertTrue(self.l.await_verdict(L.VERDICT_WAIT_S), "the answer to the re-ask came after the hold ended")
        self.assertEqual([t for _, t in self.posts], [L.REASK, "ok, standing down"])



class Keys(unittest.TestCase):
    """ask 5 = lights 2: chat/__main__.post claims a key before it sends, so a send that fails after its claim has
    consumed the key. The poster here claims the same way (a second post under one key is the PermissionError claim()
    raises) and fails the keys in `fail` after the claim, as an unconfirmed photo does."""

    def setUp(self):
        self.posts: list[tuple[str, str | None]] = []
        self.claimed: set[str] = set()
        self.fail: set[str] = set()
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener(GROUP, self._post, listen_s=60)
        for p in (mock.patch.object(L, "PENDING", _TMP / "pending-keys.json"), mock.patch.object(L, "STATE", _TMP / "state-keys.json"),
                  mock.patch.object(field, "MAP", MAP), mock.patch.dict(os.environ, {"WTDD_ROUND": "entity", "WTDD_AGENT": "1"}),
                  mock.patch("wtdd.tools.dog_say.look_and_see", return_value=dict(SEEN)),
                  mock.patch("wtdd.tools.call", return_value={"file": "/tmp/fire.jpg"}),
                  mock.patch("wtdd.agent.ask", return_value={"text": "a reply", "calls": []}), mock.patch.object(L.time, "sleep")):
            self.enterContext(p)

    def _post(self, guid: str, key: str, kind: str, text: str | None, file: str | None) -> None:
        if key in self.claimed:
            raise PermissionError(f"gate refused: trigger {key!r} already claimed")
        self.claimed.add(key)
        if key in self.fail:
            raise RuntimeError("unconfirmed send: no read-back within 10s")
        self.posts.append((key, text))

    def test_a_failed_photo_at_a_stop_is_posted_under_say_fail_and_on_stop_returns(self):
        self.fail.add("say:K1:5")
        self.l.look_and_say(msg("what the dog doin", "K1"), 5)   # field.walk's on_stop: it must return, not raise
        self.assertEqual(self.posts, [("say-fail:K1:5", "couldn't look: RuntimeError: unconfirmed send: no read-back within 10s")])

    def test_a_failed_picture_is_posted_under_fire_fail_and_the_round_goes_on(self):
        self.fail.add("fire:K2")
        with mock.patch.object(field, "walk", lambda **kw: {"seconds": 0.0, "writes": 0, "errors": 0, "rooms": [], "stops": []}):
            self.l.wake_show(msg("what the dog doin", "K2"))
        self.assertEqual([k for k, _ in self.posts], ["fire-fail:K2", "doin:K2", "say:K2", "done:K2"])
        self.assertTrue(self.posts[0][1].startswith("couldn't make the picture: RuntimeError"), self.posts[0])

    def test_a_failed_reply_is_posted_under_ai_fail(self):
        self.fail.update({"ai:K3", "ai:K4"})
        with mock.patch.object(self.l, "read", return_value=[]):
            self.l.chat(msg("yo dog who was that", "K3"))               # a chat turn
            self.l.armed_until = time.time() + 60
            self.l.handle(msg("tell me a joke", "K4"))                  # an armed ask with WTDD_AGENT=1
        self.assertEqual([k for k, _ in self.posts], ["ai-fail:K3", "ai-fail:K4"])


if __name__ == "__main__":
    unittest.main()
