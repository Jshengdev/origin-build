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
for _k in ("JEV_API_KEY", "WTDD_ON_CALL_GUID", "WTDD_ON_CALL_HANDLE", "WTDD_ALARM", "WTDD_AGENT", "WTDD_ALLOW_SELF",
           "WTDD_COMMANDS", "WTDD_TRIGGERS", "WTDD_ROUND_AVOID"):
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


if __name__ == "__main__":
    unittest.main()
