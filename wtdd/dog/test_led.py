"""The verifying command of roadmap item 25 (head-led): python -m unittest wtdd.dog.test_led. No dog; the real ledger and
the real calibration are untouched (WTDD_LEDGER points at a scratch file before wtdd.ledger is imported, session.CAL_FILE
at a scratch path); no check here can reach the chat or an API (the hook's API transport is replaced by a recorder).

The head light is VUI 1007 {color, time, flash_cycle?} on RTC_TOPIC["VUI"]; the ids come from the upstream vui.py example
and are absent from the wheel, so these checks pin what we send and how we record it, never what the dog does.
  Shape    the recording stub pub_sub (fixtures/vui_stub.py) sees {color, time} and {color, time, flash_cycle}, time an
           int like the example's, then 1006 for the read-back on the same topic.
  Allow    VUI_ALLOW is exactly {1005, 1006, 1007}; an id outside it and a colour outside VUI_COLOR are refused before
           any send (a refused colour is still its FAILED dog.led row).
  Receipt  code 0 is one ok dog.led row {color, seconds, flash_ms} with the raw reply and Body.led_state.at set; code 7 is
           a FAILED row naming the code and .led {code: 7, error}; 1006's brightness lands in state_after and its absence
           reads the string "no read-back", never a default; a stub caller's rows say cached=True, source="stub".
  Hook     the colour table is the head's; a fake ask that calls the hook returns at once and completes while the dog
           refuses (code 7, the FAILED row lands later); no connected dog in the API is a WARN and no row; another
           process goes through the API.
  Hold     a state is resent every WTDD_LED_TIME_S while it holds, on the first send's clock (a slow 1006 read-back never
           stretches the period); a new state cancels the held one; a refusal is not resent; until the ceiling is known
           one request holds 5 s.
  Wired    the real session.py with a fake body: lidar(True) and the follow's start are cyan, the follow's end green,
           stop() red. intruder_alarm's "who dis?!" (red) and the listener's "ok, standing down" (green) are read from
           the source: running either would post to the chat.
  Served   GET /dog/state .led is the body's led_state, None without a body; WTDD_STATE_FIXTURE (the DEMO_CACHE path)
           serves the planted file with source "stub", a relative path from the repo root.
  Tool     dog_led in the registry with {color, seconds, flash_ms} and in `python -m wtdd list`; the CLI waits out a hold
           (its resends die with the process otherwise), the API process does not; importing the hook module does not
           load the driver (the listener imports it).
  Page     the ring's marked block in ui/index.html with its texts in its code (not its comment, which names them too),
           colours only as var(--x, #fallback), the dot still orange, and the night-1 dry-mode patches 1 and 1b the
           screenshot needs.
"""
from __future__ import annotations
import asyncio
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-led-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")   # before importing the ledger: never the real file
for _k in ("WTDD_STATE_FIXTURE", "WTDD_LED_TIME_S"):
    os.environ.pop(_k, None)

from unitree_webrtc_connect import RTC_TOPIC  # noqa: E402

from wtdd import ledger, tools  # noqa: E402
from wtdd.dog import led, nav, session  # noqa: E402
from wtdd.dog.body import VUI_ALLOW, Body  # noqa: E402
from wtdd.dog.fixtures.vui_stub import StubConn  # noqa: E402

session.CAL_FILE = _TMP / "dog_cal.json"   # never the repo's calibration
ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
VUI = RTC_TOPIC["VUI"]
OK = {1007: (0, None), 1006: (0, {"brightness": 7})}
COLOURS = ("white", "red", "yellow", "blue", "green", "cyan", "purple")   # the wheel's VUI_COLOR, constants.py:343-350


def _body(answers: dict | None = None, delay: dict | None = None) -> Body:
    b = Body()
    b.conn = StubConn(OK if answers is None else answers, delay)
    return b


def _count() -> int:
    return len(ledger.rows())


def _led_rows(n0: int) -> list[dict]:
    return [r for r in ledger.rows()[n0:] if r["tool"] == "dog.led"]


def _wait_led_rows(n0: int, want: int, timeout: float = 3.0) -> list[dict]:
    t0 = time.monotonic()
    while len(_led_rows(n0)) < want and time.monotonic() - t0 < timeout:
        time.sleep(0.02)
    return _led_rows(n0)


def _quiet(fn, *a, **kw):
    """Runs fn with stderr captured (the [wtdd:dog] lines); returns (result, captured text)."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = fn(*a, **kw)
    return out, err.getvalue()


class Shape(unittest.TestCase):
    def test_colour_is_1007_color_time_on_the_vui_topic(self):
        b = _body()
        _quiet(asyncio.run, b.led("cyan", 5))
        topic, opts = b.conn.sent[0]
        self.assertEqual(topic, VUI)
        self.assertEqual(opts, {"api_id": 1007, "parameter": {"color": "cyan", "time": 5}})
        self.assertIs(type(opts["parameter"]["time"]), int)   # the example sends time=5; 5.0 is other bytes on the wire

    def test_flash_adds_flash_cycle_in_ms(self):
        b = _body()
        _quiet(asyncio.run, b.led("cyan", 5, flash_ms=1000))
        self.assertEqual(b.conn.sent[0][1], {"api_id": 1007, "parameter": {"color": "cyan", "time": 5, "flash_cycle": 1000}})

    def test_whole_seconds_given_as_a_float_go_out_as_an_int(self):
        b = _body()
        _quiet(asyncio.run, b.led("green", 5.0))
        self.assertIs(type(b.conn.sent[0][1]["parameter"]["time"]), int)

    def test_the_read_back_is_1006_on_the_same_topic_after_the_ack(self):
        b = _body()
        _quiet(asyncio.run, b.led("cyan", 5))
        self.assertEqual([(t, o["api_id"]) for t, o in b.conn.sent], [(VUI, 1007), (VUI, 1006)])


class Allow(unittest.TestCase):
    def test_vui_allow_is_exactly_brightness_set_brightness_get_and_colour(self):
        self.assertEqual(VUI_ALLOW, frozenset({1005, 1006, 1007}))

    def test_an_id_outside_vui_allow_is_refused_before_any_send(self):
        b = _body({1001: (0, None), 1003: (0, None), 1004: (0, None), 2001: (0, None)})
        for api_id in (1003, 1004, 1001, 2001):   # 1003/1004 are the VUI volume set/get: real ids, still not allowed
            with self.assertRaises(PermissionError):
                _quiet(asyncio.run, b.vui(api_id))
        self.assertEqual(b.conn.sent, [])

    def test_a_colour_outside_vui_color_is_refused_before_any_send_as_a_failed_row(self):
        b = _body()
        n0 = _count()
        for bad in ("orange", "CYAN", ""):
            with self.assertRaises(PermissionError):
                _quiet(asyncio.run, b.led(bad, 5))
        self.assertEqual(b.conn.sent, [])
        rows = _led_rows(n0)
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertIs(r["ok"], False)
            self.assertIn("PermissionError", r["response_or_error"])
        self.assertIsNone(b.led_state["code"])
        self.assertIn("PermissionError", b.led_state["error"])

    def test_every_vui_color_is_accepted(self):
        b = _body()
        for c in COLOURS:
            _quiet(asyncio.run, b.led(c, 5))
        self.assertEqual([o["parameter"]["color"] for _, o in b.conn.sent if o["api_id"] == 1007], list(COLOURS))


class Receipt(unittest.TestCase):
    def test_code_0_is_one_ok_row_with_the_raw_reply_and_sets_led_at(self):
        b = _body()
        self.assertIsNone(b.led_state)   # nothing requested yet: nothing claimed
        n0, t0 = _count(), time.time()
        out, _ = _quiet(asyncio.run, b.led("cyan", 5))
        rows = ledger.rows()[n0:]
        self.assertEqual([r["tool"] for r in rows], ["dog.led"])   # one row per change, nothing else
        r = rows[0]
        self.assertEqual((r["agent"], r["app"], r["ok"]), ("dog", "unitree", True))
        self.assertEqual(r["args"], {"color": "cyan", "seconds": 5, "flash_ms": None})
        self.assertEqual(r["response_or_error"]["led"]["header"]["status"]["code"], 0)   # the raw 1007 reply
        self.assertIsInstance(r["latency_ms"], int)
        self.assertEqual((r["cached"], r["source"]), (False, "live"))
        st = b.led_state
        self.assertEqual((st["color"], st["seconds"], st["code"]), ("cyan", 5, 0))
        self.assertIsInstance(st["at"], float)
        self.assertGreaterEqual(st["at"], t0)
        self.assertNotIn("error", st)
        self.assertEqual(out["code"], 0)

    def test_code_7_is_a_failed_row_naming_the_code_and_led_code_7(self):
        b = _body({1007: (7, None), 1006: (0, {"brightness": 7})})
        n0 = _count()
        with self.assertRaises(RuntimeError):
            _quiet(asyncio.run, b.led("red", 5))
        rows = ledger.rows()[n0:]
        self.assertEqual([r["tool"] for r in rows], ["dog.led"])
        self.assertIs(rows[0]["ok"], False)
        self.assertIn("code=7", rows[0]["response_or_error"])
        self.assertEqual(b.led_state["code"], 7)
        self.assertIn("code=7", b.led_state["error"])
        self.assertEqual([o["api_id"] for _, o in b.conn.sent], [1007])   # a refused colour is not read back

    def test_1006_brightness_lands_in_state_after(self):
        b = _body()
        n0 = _count()
        _quiet(asyncio.run, b.led("cyan", 5))
        r = _led_rows(n0)[-1]
        self.assertEqual(r["state_after"], {"brightness": 7})
        self.assertEqual(r["response_or_error"]["readback"]["header"]["status"]["code"], 0)   # the raw 1006 reply

    def test_no_1006_answer_reads_no_read_back_never_a_default(self):
        for bad in (TimeoutError("no answer"), (3, None), (0, {"volume": 2})):
            b = _body({1007: (0, None), 1006: bad})
            n0 = _count()
            _quiet(asyncio.run, b.led("cyan", 5))
            r = _led_rows(n0)[-1]
            self.assertIs(r["ok"], True, bad)   # the colour was acked; only the read-back is missing
            self.assertEqual(r["state_after"], "no read-back", bad)
            self.assertIsInstance(r["response_or_error"]["readback"], str, bad)   # why: the error, the code or the key
            self.assertTrue(r["response_or_error"]["readback"], bad)

    def test_a_stub_callers_rows_are_labelled_cached_stub(self):
        b = _body()
        n0 = _count()
        _quiet(asyncio.run, b.led("cyan", 5, cached=True, source="stub"))
        r = _led_rows(n0)[-1]
        self.assertEqual((r["cached"], r["source"]), (True, "stub"))


class Hook(unittest.TestCase):
    def setUp(self):
        self._inst = session.DogSession._inst
        self._api = os.environ.pop("WTDD_API_PROCESS", None)
        self.posted: list = []
        self._post = mock.patch.object(led, "_post_api", lambda color, seconds: self.posted.append((color, seconds)) or {"code": 0})
        self._post.start()

    def tearDown(self):
        self._post.stop()
        session.DogSession._inst = self._inst
        os.environ.pop("WTDD_API_PROCESS", None)
        if self._api is not None:
            os.environ["WTDD_API_PROCESS"] = self._api

    def _session(self, body) -> session.DogSession:
        s = session.DogSession()
        s.body = body
        session.DogSession._inst = s
        return s

    def test_the_colour_table(self):
        from wtdd.tools import intruder_alarm
        self.assertEqual(led.COLOURS, {"scanning": "cyan", "asking": "red", "halted": "red", "clear": "green"})
        self.assertEqual(set(led.HOLD_S), set(led.COLOURS))
        self.assertEqual(led.HOLD_S["asking"], intruder_alarm.PENDING_WINDOW_S)   # red holds while the question is open
        for state, secs in led.HOLD_S.items():
            self.assertGreater(secs, 0, state)

    def test_a_fake_ask_that_calls_the_hook_completes_while_the_dog_refuses(self):
        s = self._session(_body({1007: (7, None)}, delay={1007: 0.3}))
        os.environ["WTDD_API_PROCESS"] = "1"
        n0 = _count()

        def fake_ask():
            led.hook("asking")
            return "asked"

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            t0 = time.perf_counter()
            self.assertEqual(fake_ask(), "asked")
            self.assertLess(time.perf_counter() - t0, 0.2)   # fire-and-forget: the ask never waits on the light
            rows = _wait_led_rows(n0, 1)
            time.sleep(0.05)
        self.assertEqual(len(rows), 1)
        self.assertIs(rows[0]["ok"], False)
        self.assertEqual(rows[0]["args"]["color"], "red")
        self.assertIn("code=7", rows[0]["response_or_error"])
        self.assertEqual(s.body.led_state["code"], 7)
        self.assertEqual(self.posted, [])   # this process holds the dog: nothing goes over HTTP

    def test_no_connected_dog_in_the_api_is_a_warn_and_no_row(self):
        self._session(None)
        os.environ["WTDD_API_PROCESS"] = "1"
        n0 = _count()
        out, err = _quiet(led.hook, "halted")
        self.assertIsNone(out)
        self.assertIn("WARN", err)
        self.assertEqual(_count(), n0)      # nothing was sent, so nothing is claimed
        self.assertEqual(self.posted, [])   # the API never posts to itself

    def test_an_unknown_state_is_a_warn_never_a_raise(self):
        self._session(_body())
        out, err = _quiet(led.hook, "dancing")
        self.assertIsNone(out)
        self.assertIn("WARN", err)

    def test_another_process_goes_through_the_api(self):
        session.DogSession._inst = None
        _quiet(led.hook, "clear")
        t0 = time.monotonic()
        while not self.posted and time.monotonic() - t0 < 2:
            time.sleep(0.01)
        self.assertEqual(self.posted, [("green", led.HOLD_S["clear"])])


class Hold(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("WTDD_LED_TIME_S", None)

    def test_until_the_ceiling_is_known_one_request_holds_5_s(self):
        b = _body()

        async def go():
            return await led.hold(b, "cyan", 20)

        st, _ = _quiet(asyncio.run, go())   # returns after the first request; the resends are the keeper's
        self.assertEqual(st["code"], 0)
        self.assertEqual(b.conn.sent[0][1]["parameter"], {"color": "cyan", "time": 5})

    def test_a_state_is_resent_every_time_seconds_while_it_holds(self):
        os.environ["WTDD_LED_TIME_S"] = "0.05"
        b = _body()
        n0 = _count()

        async def go():
            await led.hold(b, "cyan", 0.2)
            await asyncio.sleep(0.45)

        _quiet(asyncio.run, go())
        rows = _led_rows(n0)
        self.assertEqual([r["args"].get("resend") for r in rows], [None, 1, 2, 3])   # 0.2 s held in 0.05 s requests
        self.assertTrue(all(r["ok"] and r["args"]["color"] == "cyan" for r in rows))
        self.assertEqual({o["parameter"]["time"] for _, o in b.conn.sent if o["api_id"] == 1007}, {0.05})

    def test_the_resend_period_is_time_not_time_plus_the_read_back(self):
        os.environ["WTDD_LED_TIME_S"] = "0.05"
        b = _body(delay={1006: 0.03})   # a slow read-back; a silent 1006 on the dog waits REQ_TIMEOUT_S (3 s) every request
        ps, sent_at = b.conn.datachannel.pub_sub, []
        send = ps.publish_request_new

        async def stamped(topic, opts):
            if opts["api_id"] == 1007:
                sent_at.append(time.monotonic())
            return await send(topic, opts)

        ps.publish_request_new = stamped

        async def go():
            await led.hold(b, "cyan", 0.2)
            await asyncio.sleep(0.45)

        _quiet(asyncio.run, go())
        self.assertEqual(len(sent_at), 4)
        gaps = [round(y - x, 3) for x, y in zip(sent_at, sent_at[1:])]
        self.assertTrue(all(g < 1.4 * 0.05 for g in gaps), f"1007 gaps {gaps}: the read-back's latency must not dark the head")
        self.assertLess(sent_at[-1] - sent_at[0], 0.2, "every request of the 0.2 s hold starts within the 0.2 s")

    def test_a_new_state_cancels_the_held_one(self):
        os.environ["WTDD_LED_TIME_S"] = "0.05"
        b = _body()
        n0 = _count()

        async def go():
            await led.hold(b, "cyan", 5.0)      # 99 resends if nothing supersedes it
            await asyncio.sleep(0.12)
            await led.hold(b, "green", 0.05)    # one request, no resend
            await asyncio.sleep(0.3)

        _quiet(asyncio.run, go())
        colours = [r["args"]["color"] for r in _led_rows(n0)]
        i = colours.index("green")
        self.assertEqual(colours[i:], ["green"])   # nothing cyan after the new state
        self.assertGreaterEqual(i, 2)              # and cyan was being resent before it

    def test_a_refused_state_is_not_resent(self):
        os.environ["WTDD_LED_TIME_S"] = "0.05"
        b = _body({1007: (7, None)})
        n0 = _count()

        async def go():
            with self.assertRaises(RuntimeError):
                await led.hold(b, "red", 0.3)
            await asyncio.sleep(0.2)

        _quiet(asyncio.run, go())
        self.assertEqual(len(_led_rows(n0)), 1)


class FakeBody:
    """What session.py calls on the body around the hooks, without a dog: a pose, acked commands, the lidar switch."""
    _avoid = True
    led_state = None

    def __init__(self) -> None:
        self.cmds: list[str] = []

    def state(self) -> dict:
        return {"position": [0.0, 0.0, 0.0], "rpy": [0.0, 0.0, 0.0], "velocity": [0.0, 0.0, 0.0], "age_ms": 0, "n": 1}

    async def fresh_state(self, required: bool = False) -> dict:
        return self.state()

    async def cmd(self, name: str, parameter=None) -> int:
        self.cmds.append(name)
        return 0

    async def _tick(self, via, x, y, z):
        return None

    async def lidar_on(self) -> None:
        pass

    async def lidar_off(self) -> None:
        pass

    def lidar_points(self) -> dict:
        return {"on": True, "n": 0, "errors": 0, "age_ms": None, "frame": None, "points": None, "utlidar_pose": None}


class Wired(unittest.TestCase):
    def setUp(self):
        self.hooked: list[str] = []
        self._p = mock.patch.object(led, "hook", self.hooked.append)
        self._p.start()
        self.s = session.DogSession()
        self.s.body = FakeBody()

    def tearDown(self):
        self._p.stop()

    def test_lidar_on_is_scanning_and_a_read_or_off_is_not(self):
        _quiet(self.s.lidar, None)
        _quiet(self.s.lidar, False)
        self.assertEqual(self.hooked, [])
        _quiet(self.s.lidar, True)
        self.assertEqual(self.hooked, ["scanning"])

    def test_the_follow_start_is_scanning_and_its_end_is_clear(self):
        self.s.cal = nav.calibration([0.0, 0.0, 0.0], 0.0, [100, 100], 0.0)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.s.follow([[100, 100], [110, 100]], [])
            self.s._follower.result(timeout=5)
        self.assertTrue(self.s.follow_state.get("done"), self.s.follow_state)
        self.assertEqual(self.hooked, ["scanning", "clear"])   # the end is green, never the halt's red

    def test_stop_is_halted(self):
        _quiet(self.s.stop)
        self.assertEqual(self.hooked, ["halted"])
        self.assertIn("StopMove", self.s.body.cmds)   # the halt itself still ran

    def test_who_dis_is_red_right_after_the_ask_is_posted(self):
        src = (ROOT / "wtdd" / "tools" / "intruder_alarm.py").read_text().splitlines()
        post = next(i for i, line in enumerate(src) if "chat_post.run(text=ASK" in line)
        hooks = [i for i, line in enumerate(src) if 'led.hook("asking")' in line]
        self.assertEqual(len(hooks), 1, "one red hook in intruder_alarm")
        self.assertTrue(post < hooks[0] <= post + 3, "the red hook follows the who dis?! post, in the ask branch")

    def test_standing_down_is_green_right_after_it_is_said(self):
        src = (ROOT / "wtdd" / "chat" / "listen.py").read_text().splitlines()
        said = next(i for i, line in enumerate(src) if "self.say(" in line and '"ok, standing down")' in line)
        hooks = [i for i, line in enumerate(src) if 'led.hook("clear")' in line]
        self.assertEqual(len(hooks), 1, "one green hook in the listener")
        self.assertTrue(said < hooks[0] <= said + 2, "the green hook follows 'ok, standing down'")


class Served(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("WTDD_STATE_FIXTURE", None)

    def test_dog_state_serves_the_bodys_led_state(self):
        s = session.DogSession()
        self.assertIsNone(s.state()["led"])   # no body: nothing lit, nothing claimed
        s.body = _body()
        _quiet(s.run, s.body.led("cyan", 5))
        served = s.state()["led"]
        self.assertEqual(served, s.body.led_state)
        self.assertEqual((served["color"], served["code"]), ("cyan", 0))

    def test_the_state_fixture_is_served_as_stub(self):
        s = session.DogSession()
        s.body = _body()   # even with a body the planted file wins: it is the DEMO_CACHE path, never set live
        for name, code in (("state-led.json", 0), ("state-led-failed.json", 7)):
            os.environ["WTDD_STATE_FIXTURE"] = str(FIX / name)
            st = s.state()
            self.assertEqual(st["source"], "stub", name)
            self.assertEqual(st["led"]["code"], code, name)
            self.assertIs(st["connected"], True, name)
            self.assertEqual(len(st["map"]["p"]), 2, name)
        self.assertIn("code=7", st["led"]["error"])

    def test_a_relative_fixture_path_is_the_repos(self):
        s = session.DogSession()
        os.environ["WTDD_STATE_FIXTURE"] = "wtdd/dog/fixtures/state-led.json"
        cwd = os.getcwd()
        os.chdir(_TMP)
        try:
            st = s.state()
        finally:
            os.chdir(cwd)
        self.assertEqual((st["source"], st["led"]["color"]), ("stub", "cyan"))


class Tool(unittest.TestCase):
    def test_dog_led_is_a_tool_with_the_contract_args(self):
        reg = tools.registry()
        self.assertIn("dog_led", reg)
        spec = reg["dog_led"].ARGS
        self.assertEqual(set(spec), {"color", "seconds", "flash_ms"})
        self.assertIsNone(spec["flash_ms"]["default"])

    def test_python_m_wtdd_list_shows_dog_led(self):
        out = subprocess.run([sys.executable, "-m", "wtdd", "list"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        self.assertRegex(out.stdout, r"(?m)^dog_led\s")

    def test_the_cli_waits_out_the_hold_and_the_api_process_does_not(self):
        """In a CLI the resend task lives on the session's daemon thread and dies at exit, so run() waits for it; in the
        API process the hold stays fire-and-forget. _via_api is replaced: nothing here reaches an API."""
        from wtdd import commands
        dog_led = tools.registry()["dog_led"]
        inst, api = session.DogSession._inst, os.environ.pop("WTDD_API_PROCESS", None)
        os.environ["WTDD_LED_TIME_S"] = "0.1"
        try:
            with mock.patch.object(commands, "_via_api", lambda tool, **a: None):
                for proc, at_return in ((None, 4), ("1", 1)):   # 0.4 s held in 0.1 s requests
                    if proc:
                        os.environ["WTDD_API_PROCESS"] = proc
                    s = session.DogSession()
                    s.body = _body()
                    session.DogSession._inst = s
                    n0 = _count()
                    _quiet(dog_led.run, color="cyan", seconds=0.4)
                    self.assertEqual(len(_led_rows(n0)), at_return, f"rows when run() returns, WTDD_API_PROCESS={proc}")
                    _quiet(_wait_led_rows, n0, 4)
                    self.assertEqual([r["args"].get("resend") for r in _led_rows(n0)], [None, 1, 2, 3], proc)
        finally:
            session.DogSession._inst = inst
            os.environ.pop("WTDD_LED_TIME_S", None)
            os.environ.pop("WTDD_API_PROCESS", None)
            if api is not None:
                os.environ["WTDD_API_PROCESS"] = api

    def test_importing_the_hook_module_does_not_load_the_driver(self):
        code = "import sys, wtdd.dog.led; print('unitree_webrtc_connect' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip(), "False", out.stderr[-500:])


class Page(unittest.TestCase):
    HTML = (ROOT / "ui" / "index.html").read_text()

    def test_the_ring_block_its_texts_and_its_colours(self):
        h = self.HTML
        for marker in ("// 25 · head-led · start", "// 25 · head-led · end", "/* 25 · head-led · start */", "/* 25 · head-led · end */"):
            self.assertEqual(h.count(marker), 1, marker)
        js = h[h.index("// 25 · head-led · start"):h.index("// 25 · head-led · end")]
        css = h[h.index("/* 25 · head-led · start */"):h.index("/* 25 · head-led · end */")]
        self.assertRegex(css, r"\.led\b")
        code = "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))   # the block's comment names these texts too
        for text in ("acked (no read-back)", "led FAILED · code", "stub", "cyan scanning · red asking or halted · green clear"):
            self.assertIn(text, code)
        bare = re.sub(r"var\(--[\w-]+,\s*#[0-9a-fA-F]{3,8}\)", "", css)
        self.assertNotRegex(bare, r"#[0-9a-fA-F]{3,8}\b", "every colour in the block is var(--x, #fallback)")
        self.assertIn(".dogdot { fill: #e8590c;", h)   # the dot stays orange: orange is the body

    def test_the_night_1_dry_mode_patches_1_and_1b(self):
        self.assertIn("const palette = Array.isArray(status?.hue) ? [...status.hue.filter(", self.HTML)
        self.assertIn('${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>', self.HTML)


if __name__ == "__main__":
    unittest.main()
