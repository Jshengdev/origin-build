"""S3 · the dog's own obstacle avoidance is switched on at every connect and read back; a refusal is loud, not fatal.

Johnny, 2026-09-27: "The dog also has its built in avoidance which should always be on for safety." Before S3 only
follow() switched it on; hold-to-drive went through the sport service until someone pressed the avoid toggle. Offline:
the session's Body is replaced by a fake whose avoid() records the call, so no dog is needed. B3 (UnknownNotZero): a
halt or a look whose reading the dog did not send says unknown, never a measured zero.
  python -m unittest wtdd.dog.test_avoid_on
"""
import asyncio
import contextlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from . import session


class FakeBody:
    fail: Exception | None = None
    made: list["FakeBody"] = []

    def __init__(self):
        self._avoid = None
        self.calls: list[bool] = []
        FakeBody.made.append(self)

    async def connect(self):
        return None

    async def avoid(self, on: bool) -> bool:
        self.calls.append(on)
        if FakeBody.fail is not None:
            raise FakeBody.fail
        self._avoid = on
        return on

    def state(self):
        return {"age_ms": 0, "n": 1}

    async def _tick(self, *a):
        return None

    async def close(self):
        return None


def stop(s) -> None:
    if getattr(s, "_driver", None) is not None:
        s.loop.call_soon_threadsafe(s._driver.cancel)
        time.sleep(0.05)
    s.loop.call_soon_threadsafe(s.loop.stop)
    while s.loop.is_running():
        time.sleep(0.01)
    s.loop.close()


class AvoidOnConnect(unittest.TestCase):
    def setUp(self):
        FakeBody.fail, FakeBody.made = None, []
        self.s = session.DogSession()
        self.err = io.StringIO()

    def tearDown(self):
        stop(self.s)

    def connect(self):
        with mock.patch.object(session, "Body", FakeBody), contextlib.redirect_stderr(self.err):
            return self.s.run(self.s._ensure(), timeout=10)

    def test_a_connect_switches_avoidance_on_and_reads_it_back(self):
        b = self.connect()
        self.assertEqual(b.calls, [True], "one avoid(True) right after the connect")
        self.assertIs(b._avoid, True)

    def test_a_refused_avoidance_is_loud_and_the_dog_stays_usable(self):
        FakeBody.fail = RuntimeError("OBSTACLES_AVOID SWITCH_SET enable=True refused: code=3104")
        b = self.connect()
        self.assertIs(self.s.body, b, "the connect still stands: the dog stays usable")
        self.assertEqual(b.calls, [True])
        self.assertIsNot(b._avoid, True)
        self.assertIn("avoidance NOT on", self.err.getvalue())
        self.assertIn("code=3104", self.err.getvalue())

    def test_a_reconnect_switches_it_on_again(self):
        first = self.connect()
        first.state = lambda: {"age_ms": 10 ** 6, "n": 1}   # the peer went stale: the next call reconnects once
        second = self.connect()
        self.assertIsNot(second, first)
        self.assertEqual(second.calls, [True])


class UnknownNotZero(unittest.TestCase):
    """B3 (CLEANUP-PLAN): a reading the dog did not send is unknown, never a measured zero. The halt logged velocity
    `or [0, 0, 0]` and a look's pitch was `rpy or [0, 0, 0]`: a state with no velocity read as a dog standing still, and
    a nod with no IMU rpy read as a level head (a tilt "did not fire" and was retried). None, with a WARN saying unknown."""

    def setUp(self):
        from .. import ledger
        self.s = session.DogSession()
        self.err = io.StringIO()
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(ledger, "LEDGER", Path(tmp) / "ledger.jsonl"))   # the look's dog.look row
        self.b = FakeBody()
        self.b._avoid = True
        self.b.cmd = mock.AsyncMock(return_value=0)
        self.b.frame = mock.AsyncMock()
        self.b.raw = lambda: {"imu_state": {"quaternion": [1.0, 0.0, 0.0, 0.0]}}   # a state with no rpy
        self.s.body = self.b

    def tearDown(self):
        stop(self.s)

    def run_(self, coro):
        with contextlib.redirect_stderr(self.err), mock.patch.object(session.asyncio, "sleep", mock.AsyncMock()):
            return self.s.run(coro, timeout=10)

    def test_a_halt_with_no_velocity_read_back_says_unknown(self):
        self.b.fresh_state = mock.AsyncMock(return_value={"position": [0.0, 0.0, 0.0], "age_ms": 0, "n": 2})   # no velocity
        out = self.run_(self.s._halt())
        self.assertIsNone(out["velocity"], "no reading is not a measured stop")
        self.assertRegex(self.err.getvalue(), r"WARN [^\n]*velocity[^\n]*unknown")
        self.assertNotIn("velocity=[0", self.err.getvalue())

    def test_a_look_with_no_imu_pitch_says_unknown(self):
        res = self.run_(self.s._look(self.b, "level"))
        self.assertIsNone(res["pitch_deg"], "no IMU reading is not a level head")
        self.assertRegex(self.err.getvalue(), r"WARN [^\n]*pitch unknown")

    def test_a_tilt_with_no_imu_pitch_is_unverified_not_a_miss(self):
        res = self.run_(self.s._look(self.b, "tilt"))
        self.assertEqual((res["pitch_deg"], res["pitch_down_deg"], res["fired"]), (None, None, None), res)
        self.assertEqual(res["attempts"], 1, "an unknown pitch is not a miss: no StandUp and second nod")
        self.assertIsNotNone(res["file_down"], "the floor frame was taken; only its pitch is unknown")


if __name__ == "__main__":
    unittest.main()
