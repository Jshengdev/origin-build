"""The dashboard's People, Monitoring and Integrations pages read real status, never a mock. Johnny, 2026-09-27, for the
Loom walkthrough: "the people to show who we are texting. the monitoring and the integrations".
GET /people is the group's name and the housemates' first names, never a handle. GET /integrations is one entry per
integration (unitree, lidar, hue, tuya, imessage, jev, openrouter, ledger), each {name, ok: true | false | null, detail,
as_of}, read from the dog session, the ledger's newest rows and the listener's heartbeat; a key is only ever a bool
(key_set). Both are reads: no row, no network. The real handler on an ephemeral port in this process; the ledger is a
temp file (WTDD_LEDGER set before import, ledger.LEDGER patched), listen.json sits in a temp root (status.ROOT patched),
and the dog is a DogSession whose Body is a fake. Handles and keys are stand-ins, never real ones.
  python -m unittest wtdd.test_status -v
"""
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

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-status-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")

from wtdd import api, ledger  # noqa: E402
from wtdd.chat import housemates  # noqa: E402
from wtdd.dog import session  # noqa: E402

PHONE, EMAIL, PHONE2, PHONE3 = "+15550003333", "sam@example.com", "+15550004444", "+15550005555"
JEV_KEY, OR_KEY = "jev-stand-in-4f2a9c", "sk-or-v1-stand-in-8e1d77"
NAMES = ["unitree", "lidar", "hue", "tuya", "imessage", "jev", "openrouter", "ledger"]


def _row(ts, tool, app, ok=True, err=None, source="live"):
    return {"ts": ts, "run_id": "run-1790481401", "cached": source == "stub", "source": source, "step": tool, "agent": "t",
            "tool": tool, "app": app, "args": {}, "ok": ok, "response_or_error": err, "state_before": None, "state_after": None,
            "latency_ms": 5}


class FakeBody:
    """What DogSession.state() and .lidar() read from a Body: the state snapshot, the avoidance read-back, the voxel counts."""

    def __init__(self, age_ms=40, avoid=True, lidar_on=True, frames=120, lidar_age_ms=200, errors=0):
        self.age_ms, self._avoid, self.lidar_on, self.frames, self.lidar_age_ms, self.errors = age_ms, avoid, lidar_on, frames, lidar_age_ms, errors

    def state(self):
        return {"mode": 1, "gait_type": 0, "progress": 0, "position": None, "velocity": None, "yaw_speed": 0, "body_height": 0.3,
                "range_obstacle": None, "rpy": None, "n": 500, "hz": 20.0, "age_ms": self.age_ms}

    def lidar_points(self):
        return {"on": self.lidar_on, "n": self.frames, "errors": self.errors, "cb_errors": 0,
                "age_ms": self.lidar_age_ms if self.frames else None, "frame": None, "points": None, "utlidar_pose": None}


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path: str) -> tuple[str, dict]:
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            self.assertEqual(r.status, 200, path)
            text = r.read().decode()
        return text, json.loads(text)


class People(Api):
    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {"WTDD_CHAT_NAME": "THE CASTLE"}))

    def test_names_only_never_a_handle(self):
        with mock.patch.dict(housemates.HOUSEMATES, {PHONE: "Sam", EMAIL: "Sam", PHONE2: "Alex", PHONE3: PHONE3}, clear=True):
            text, body = self.get("/people")
        self.assertEqual(body["group"], "THE CASTLE")
        self.assertEqual(body["people"], [{"name": "Sam"}, {"name": "Alex"}, {"name": "a member"}],
                         "one entry per person (two handles, one name), a handle typed in as a name reads a member")
        self.assertNotIn("why", body)
        for private in (PHONE, PHONE[1:], EMAIL, "example.com", PHONE2, PHONE2[1:], PHONE3, PHONE3[1:]):
            self.assertNotIn(private, text)

    def test_no_housemates_is_empty_with_why(self):
        with mock.patch.dict(housemates.HOUSEMATES, {}, clear=True):
            _, body = self.get("/people")
        self.assertEqual(body["people"], [])
        self.assertEqual(body["why"], "HOUSEMATES is empty: fill it locally (never committed)")

    def test_no_group_name_is_null_with_why(self):
        with mock.patch.dict(os.environ, {"WTDD_CHAT_NAME": ""}), mock.patch.dict(housemates.HOUSEMATES, {PHONE: "Sam"}, clear=True):
            _, body = self.get("/people")
        self.assertIsNone(body["group"])
        self.assertIn("WTDD_CHAT_NAME is not set", body["group_why"])
        self.assertEqual(body["people"], [{"name": "Sam"}])


class Integrations(Api):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=_TMP))
        self.led = self.root / "ledger.jsonl"
        self.enterContext(mock.patch("wtdd.status.ROOT", self.root))
        self.enterContext(mock.patch.object(ledger, "LEDGER", self.led))
        self.enterContext(mock.patch.dict(os.environ, {"JEV_API_KEY": JEV_KEY, "OPENROUTER_API_KEY": OR_KEY}))
        self.s = session.DogSession()
        self.enterContext(mock.patch.object(session.DogSession, "get", return_value=self.s))

    def tearDown(self):
        self.s.loop.call_soon_threadsafe(self.s.loop.stop)
        while self.s.loop.is_running():
            time.sleep(0.01)
        self.s.loop.close()

    def plant(self, *rows):
        self.led.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def beat(self, age_s=1.0, armed=True, dry=False):
        (self.root / "listen.json").write_text(json.dumps({"t": time.time() - age_s, "guid": "any;+;0000", "armed": armed,
                                                           "armed_by": "Sam", "dry": dry, "pending": False, "last_rowid": 7}))

    def status(self) -> tuple[str, dict[str, dict]]:
        text, body = self.get("/integrations")
        self.assertEqual([i["name"] for i in body["integrations"]], NAMES)
        self.assertTrue(body["checked_at"])
        for i in body["integrations"]:
            self.assertEqual(set(i) - {"key_set"}, {"name", "ok", "detail", "as_of"}, i)
            self.assertIn(i["ok"], (True, False, None), i)
            self.assertTrue(i["detail"], i)
        return text, {i["name"]: i for i in body["integrations"]}

    def test_each_integration_reads_its_own_evidence(self):
        self.s.body = FakeBody()
        self.beat(1.0, armed=True)
        self.plant(_row("2026-09-27T20:00:00", "lights.list", "hue"),
                   _row("2026-09-27T20:01:00", "zone.decided", "stub", source="stub"),
                   _row("2026-09-27T20:02:00", "lights.set_zone", "hue"),
                   _row("2026-09-27T20:03:00", "lights.tuya_set", "tuya", ok=False, err="TimeoutError: the strip did not answer in 5 s"),
                   _row("2026-09-27T20:04:00", "zone.decided", "openrouter"),
                   _row("2026-09-27T20:05:00", "llm.generate", "openrouter", ok=False, err="RuntimeError: openrouter 402: insufficient credits"),
                   _row("2026-09-27T20:06:00", "dog.cmd", "dog"))
        _, st = self.status()
        u, li, hue, tuya, im, jev, ort, led = (st[n] for n in NAMES)
        self.assertIs(u["ok"], True, u)
        self.assertIn("avoidance on", u["detail"])
        self.assertTrue(u["as_of"])
        self.assertIs(li["ok"], True, li)
        self.assertIn("120 frames", li["detail"])
        self.assertEqual((hue["ok"], hue["as_of"]), (True, "2026-09-27T20:02:00"))
        self.assertIn("lights.set_zone", hue["detail"])
        self.assertEqual((tuya["ok"], tuya["as_of"]), (False, "2026-09-27T20:03:00"))
        self.assertIn("did not answer", tuya["detail"])
        self.assertIs(im["ok"], True, im)
        self.assertIn("armed", im["detail"])
        self.assertEqual((jev["ok"], jev["key_set"], jev["as_of"]), (True, True, "2026-09-27T20:04:00"))
        self.assertIn("zone.decided", jev["detail"])
        self.assertIn("live", jev["detail"])
        self.assertEqual((ort["ok"], ort["key_set"], ort["as_of"]), (False, True, "2026-09-27T20:05:00"))
        self.assertIn("402", ort["detail"])
        self.assertEqual((led["ok"], led["as_of"]), (True, "2026-09-27T20:06:00"))
        self.assertIn("7 rows", led["detail"])

    def test_keys_are_bools_and_never_served(self):
        self.plant(_row("2026-09-27T20:04:00", "decided", "openrouter"), _row("2026-09-27T20:05:00", "llm.generate", "openrouter"))
        text, st = self.status()
        self.assertEqual((st["jev"]["key_set"], st["openrouter"]["key_set"]), (True, True))
        for key in (JEV_KEY, OR_KEY, "stand-in"):
            self.assertNotIn(key, text)
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "", "OPENROUTER_API_KEY": ""}):
            _, st = self.status()
        for n, env in (("jev", "JEV_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")):
            self.assertEqual((st[n]["ok"], st[n]["key_set"]), (False, False), st[n])
            self.assertIn(f"{env} is not set", st[n]["detail"])

    def test_nothing_known_is_null_never_ok(self):
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "", "OPENROUTER_API_KEY": ""}):
            _, st = self.status()
        for n in ("unitree", "lidar", "hue", "tuya", "imessage", "ledger"):
            self.assertIsNone(st[n]["ok"], st[n])
            self.assertIsNone(st[n]["as_of"], st[n])
        self.assertIn("not connected", st["unitree"]["detail"])
        self.assertIn("listen.json", st["imessage"]["detail"])
        self.assertIn("lights.", st["hue"]["detail"])
        self.assertEqual((st["jev"]["ok"], st["openrouter"]["ok"]), (False, False), "no key: the live path cannot run")

    def test_stale_is_false_not_unknown(self):
        self.s.body = FakeBody(age_ms=9000, lidar_age_ms=9000)
        self.beat(60.0)
        _, st = self.status()
        self.assertIs(st["unitree"]["ok"], False, st["unitree"])
        self.assertIn("stale", st["unitree"]["detail"])
        self.assertIs(st["lidar"]["ok"], False, st["lidar"])
        self.assertIs(st["imessage"]["ok"], False, st["imessage"])
        self.assertIn("60", st["imessage"]["detail"])

    def test_a_failed_connect_or_avoidance_off_is_false(self):
        self.s._unreachable = (time.monotonic() - 3, "TimeoutError: no answer from the dog")
        _, st = self.status()
        self.assertIs(st["unitree"]["ok"], False, st["unitree"])
        self.assertIn("no answer from the dog", st["unitree"]["detail"])
        self.s._unreachable, self.s.body = None, FakeBody(avoid=False, lidar_on=False)
        _, st = self.status()
        self.assertIs(st["unitree"]["ok"], False, st["unitree"])
        self.assertIn("avoidance OFF", st["unitree"]["detail"])
        self.assertIsNone(st["lidar"]["ok"], "switched off is not a failure")

    def test_a_stub_row_is_never_a_live_ok(self):
        self.plant(_row("2026-09-27T20:04:00", "blob.labelled", "stub", source="stub"))
        _, st = self.status()
        self.assertIsNone(st["jev"]["ok"], st["jev"])
        self.assertIn("stub", st["jev"]["detail"])

    def test_an_unreadable_ledger_is_named_and_the_rest_still_answer(self):
        self.s.body = FakeBody()
        self.led.write_text(json.dumps(_row("2026-09-27T20:02:00", "lights.set", "hue")) + "\n{not json\n")
        _, st = self.status()
        for n in ("hue", "ledger"):
            self.assertIs(st[n]["ok"], False, st[n])
            self.assertIn("unreadable", st[n]["detail"])
        self.assertIs(st["unitree"]["ok"], True)

    def test_a_read_writes_no_row(self):
        self.s.body = FakeBody()
        self.plant(_row("2026-09-27T20:02:00", "lights.set", "hue"))
        before = self.led.read_bytes()
        self.status()
        self.get("/people")
        self.assertEqual(self.led.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
