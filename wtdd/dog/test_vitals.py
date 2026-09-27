"""Item 24 · vitals-strip, checked offline (no dog, no network). Run: python -m unittest wtdd.dog.test_vitals -v

What it checks. A state message typed in the shape rt/lf/sportmodestate had on 2026-09-13 (fixtures/sportmodestate.json;
typed values, never a recorded row) through Body._on_state gives Body.state() six more keys (gyroscope, accelerometer,
imu_temp, error_code, skew_ms, foot_force) and one stderr line per state second, `[wtdd:dog] state zeros=...`, a WARN
while any of foot_force / range_obstacle is all zeros or any of the six is absent. The driver's pushed fault messages
(errors / add_error / rm_error) through the wrapper Body._watch_faults installs on the data channel's handle_response become
Body.faults and one dog.fault row each, written on the loop after the callback has returned, never inside it (a slow
callback stalls the 20 Hz stream). A push that does not parse is a WARN and one dog.fault row with ok false, raised to the
loop's handler, and still reaches the driver; an rm for an id not held is a WARN.
DogSession.state() serves the faults with age_s and the health of every stream; WTDD_STATE_FIXTURE serves a typed state
(fixtures/state-vitals.json, a DEMO_CACHE for the screenshot) that says it is a fixture and carries no key the live path
does not serve. The ledger is a temp file: WTDD_LEDGER is set before wtdd.ledger is imported.
UNVERIFIED on the dog, whatever this passes: the temperature's unit, error_code's meaning, whether a fault message ever
arrives, whether foot_force or range_obstacle ever leave zero on this topic, the frame of state.velocity.
"""
from __future__ import annotations
import asyncio
import contextlib
import copy
import io
import json
import os
import re
import tempfile
import time
import types
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="wtdd-vitals-test-")
os.environ["WTDD_LEDGER"] = str(Path(_TMP) / "ledger.jsonl")

from wtdd import ledger  # noqa: E402
from wtdd.dog.body import Body  # noqa: E402
from wtdd.dog.session import DogSession  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
MSG = json.loads((FIX / "sportmodestate.json").read_text())
SIX = ("gyroscope", "accelerometer", "imu_temp", "error_code", "skew_ms", "foot_force")
SERVED = ("mode", "position", "velocity", "yaw_speed", "body_height", "range_obstacle", "rpy", "n", "hz", "age_ms")
LINE = re.compile(r"^\[wtdd:dog\] (WARN )?state zeros=(\S+)(.*)$")   # the per-state-second line; zeros=- when none
LOW_BATTERY = "Low battery software protection"   # the driver's text for 600_8 (constants.py app_error_code_600_8)


def _size() -> int:
    return ledger.LEDGER.stat().st_size if ledger.LEDGER.exists() else 0


def _fault_rows() -> list[dict]:
    return [r for r in ledger.rows() if r.get("tool") == "dog.fault"]


def _fed(msg: dict | None = None, times: int = 1) -> tuple[Body, str]:
    """A fresh Body that has received the state message `times` times; returns it and what it wrote to stderr."""
    b, err = Body(), io.StringIO()
    with contextlib.redirect_stderr(err):
        for _ in range(times):
            b._on_state(copy.deepcopy(msg or MSG))
    return b, err.getvalue()


def _state_lines(err: str) -> list[tuple[bool, list[str], str]]:
    """(is a WARN, the zeros list, the line) for every per-state-second line."""
    return [(bool(m.group(1)), m.group(2).split(","), line) for line in err.splitlines() if (m := LINE.match(line))]


def _dc():
    """A stand-in for the driver's WebRTCDataChannel: only the attribute the wrapper replaces, recording what reaches it."""
    seen: list[dict] = []

    async def handle_response(msg: dict) -> None:
        seen.append(msg)

    return types.SimpleNamespace(handle_response=handle_response), seen


def _with_fault(b: Body) -> Body:
    """b with the planted 600_8 fault pushed through the wrapper and its row written."""
    async def go():
        dc, _ = _dc()
        b._watch_faults(dc)
        await dc.handle_response({"type": "add_error", "data": [time.time() - 12, 600, 8]})
        await asyncio.sleep(0.05)
    asyncio.run(go())
    return b


class StateKeys(unittest.TestCase):
    def test_six_keys_from_the_raw_message_and_skew_from_the_stamp(self):
        d = MSG["data"]
        before = time.time()
        b, _ = _fed()
        after = time.time()
        st = b.state()
        for k in SIX + SERVED:
            self.assertIn(k, st, f"state() does not serve {k}")
        self.assertEqual(st["gyroscope"], d["imu_state"]["gyroscope"])
        self.assertEqual(st["accelerometer"], d["imu_state"]["accelerometer"])
        self.assertEqual(st["imu_temp"], d["imu_state"]["temperature"])
        self.assertEqual(st["error_code"], d["error_code"])
        self.assertEqual(st["foot_force"], d["foot_force"])
        self.assertEqual(st["rpy"], d["imu_state"]["rpy"])
        self.assertEqual(st["n"], 1)
        stamp = d["stamp"]["sec"] + d["stamp"]["nanosec"] / 1e9   # the dog's clock; skew = arrival wall time minus it
        self.assertIsInstance(st["skew_ms"], (int, float))
        self.assertGreaterEqual(st["skew_ms"], (before - stamp) * 1000 - 1)
        self.assertLessEqual(st["skew_ms"], (after - stamp) * 1000 + 1)


class ZeroRule(unittest.TestCase):
    def test_all_zero_foot_force_is_a_warn_line_with_hz_and_skew(self):
        lines = _state_lines(_fed()[1])
        self.assertTrue(lines, "no `[wtdd:dog] state zeros=...` line on the first state message")
        warn, zeros, line = lines[0]
        self.assertIn("foot_force", zeros)
        self.assertIn("range_obstacle", zeros)
        self.assertTrue(warn, f"a zero must be a WARN: {line}")
        self.assertIn("hz=", line)
        self.assertIn("skew_ms=", line)

    def test_nonzero_foot_force_is_not_named(self):
        msg = copy.deepcopy(MSG)
        msg["data"]["foot_force"] = [21, 19, 22, 20]
        lines = _state_lines(_fed(msg)[1])
        self.assertTrue(lines, "no `[wtdd:dog] state zeros=...` line on the first state message")
        self.assertNotIn("foot_force", lines[0][1])
        self.assertIn("range_obstacle", lines[0][1])

    def test_one_line_per_state_second_not_per_message(self):
        lines = _state_lines(_fed(times=20)[1])
        self.assertEqual(len(lines), 1, "20 messages inside one second must print one state line, not 0 and not 20")

    def test_an_absent_key_is_a_warn_that_names_it(self):
        msg = copy.deepcopy(MSG)
        msg["data"]["foot_force"], msg["data"]["range_obstacle"] = [21, 19, 22, 20], [1.2, 0.8, 2.0, 1.5]   # no zeros: absent is the only reason to WARN
        del msg["data"]["imu_state"]["temperature"]
        lines = _state_lines(_fed(msg)[1])
        self.assertTrue(lines, "no `[wtdd:dog] state zeros=...` line on the first state message")
        warn, zeros, line = lines[0]
        self.assertEqual(zeros, ["-"])
        self.assertTrue(warn, f"an absent key must be a WARN: {line}")
        self.assertIn(" absent=imu_temp ", line)


class Faults(unittest.TestCase):
    def test_add_error_is_one_row_written_after_the_callback_returns(self):
        async def go():
            b, (dc, seen) = Body(), _dc()
            b._watch_faults(dc)
            msg = {"type": "add_error", "data": [time.time() - 12, 600, 8]}
            size0, n0 = _size(), len(_fault_rows())
            await dc.handle_response(msg)
            self.assertEqual(_size(), size0, "the callback touched the ledger file: a slow write stalls the 20 Hz stream")
            self.assertEqual(seen, [msg], "the driver's own handler must still get the message")
            self.assertEqual([(f["source"], f["code"], f["id"], f["text"]) for f in b.faults], [(600, 8, "600_8", LOW_BATTERY)])
            await asyncio.sleep(0.05)   # the loop runs: now the row
            rows = _fault_rows()[n0:]
            self.assertEqual(len(rows), 1)
            self.assertEqual({k: rows[0]["args"].get(k) for k in ("kind", "source", "code", "text")},
                             {"kind": "add", "source": 600, "code": 8, "text": LOW_BATTERY})
            self.assertTrue(rows[0]["ok"])
        asyncio.run(go())

    def test_rm_error_clears_it_with_its_row(self):
        async def go():
            b, (dc, _) = Body(), _dc()
            b._watch_faults(dc)
            t = time.time() - 12
            await dc.handle_response({"type": "add_error", "data": [t, 600, 8]})
            await asyncio.sleep(0.05)
            n0 = len(_fault_rows())
            await dc.handle_response({"type": "rm_error", "data": [t, 600, 8]})
            self.assertEqual(b.faults, [])
            await asyncio.sleep(0.05)
            self.assertEqual([(r["args"]["kind"], r["args"]["source"], r["args"]["code"]) for r in _fault_rows()[n0:]],
                             [("rm", 600, 8)])
        asyncio.run(go())

    def test_errors_snapshot_becomes_add_and_rm_rows(self):
        async def go():
            b, (dc, _) = Body(), _dc()
            b._watch_faults(dc)
            t = time.time() - 30
            n0 = len(_fault_rows())
            await dc.handle_response({"type": "errors", "data": [[t, 600, 8], [t, 300, 16]]})
            self.assertEqual(sorted(f["id"] for f in b.faults), ["300_10", "600_8"])   # 16 is 0x10: the driver's table is keyed in hex
            self.assertIn("Winding overheating", [f["text"] for f in b.faults])
            await dc.handle_response({"type": "errors", "data": [[t, 300, 16]]})   # 600_8 is gone from the dog's snapshot
            self.assertEqual([f["id"] for f in b.faults], ["300_10"])
            await asyncio.sleep(0.05)
            self.assertEqual(sorted((r["args"]["kind"], r["args"]["source"], r["args"]["code"]) for r in _fault_rows()[n0:]),
                             [("add", 300, 16), ("add", 600, 8), ("rm", 600, 8)])
        asyncio.run(go())

    def test_other_messages_pass_through_without_a_row(self):
        async def go():
            b, (dc, seen) = Body(), _dc()
            b._watch_faults(dc)
            n0 = len(_fault_rows())
            hb = {"type": "heartbeat", "data": {"timeInStr": "2026-09-26 17:00:00", "timeInNum": 1790470800}}
            await dc.handle_response(hb)
            await asyncio.sleep(0.05)
            self.assertEqual(seen, [hb])
            self.assertEqual(b.faults, [])
            self.assertEqual(len(_fault_rows()), n0)
        asyncio.run(go())

    def test_a_push_that_does_not_parse_is_a_failed_row_and_still_reaches_the_driver(self):
        async def go():
            raised: list = []
            asyncio.get_running_loop().set_exception_handler(lambda _loop, ctx: raised.append(ctx.get("exception")))
            b, (dc, seen) = Body(), _dc()
            b._watch_faults(dc)
            bad = [{"type": "add_error", "data": [time.time() - 12, 600]}, {"type": "add_error", "data": "junk"}]
            n0, err = len(_fault_rows()), io.StringIO()
            with contextlib.redirect_stderr(err):
                for m in bad:
                    await dc.handle_response(m)
                await asyncio.sleep(0.05)
            self.assertEqual(seen, bad, "the driver's own handler must still get a message that did not parse")
            self.assertEqual(b.faults, [])
            rows = _fault_rows()[n0:]
            self.assertEqual([r["ok"] for r in rows], [False, False], "one failed dog.fault row per push that did not parse")
            for r in rows:
                self.assertTrue(str(r["response_or_error"]).startswith("ValueError: fault message not parsed"), r["response_or_error"])
            self.assertEqual(err.getvalue().count("WARN fault message not parsed"), 2)
            self.assertEqual(len(raised), 2, "the parse error is raised to the loop's handler, never swallowed")
        asyncio.run(go())

    def test_rm_for_an_id_not_held_is_a_warn_and_its_row(self):
        async def go():
            b, (dc, seen) = Body(), _dc()
            b._watch_faults(dc)
            msg = {"type": "rm_error", "data": [time.time() - 12, 600, 8]}
            n0, err = len(_fault_rows()), io.StringIO()
            with contextlib.redirect_stderr(err):
                await dc.handle_response(msg)
                await asyncio.sleep(0.05)
            self.assertIn("WARN fault rm for an id not held id=600_8", err.getvalue())
            self.assertEqual(seen, [msg])
            self.assertEqual(b.faults, [])
            self.assertEqual([(r["args"]["kind"], r["ok"]) for r in _fault_rows()[n0:]], [("rm", True)])
        asyncio.run(go())


class Session(unittest.TestCase):
    def setUp(self):
        os.environ["WTDD_STATE_FIXTURE"] = ""   # the live path (config.maybe reads "" as unset; .env's setdefault cannot override it)

    def _state(self, body: Body) -> dict:
        s = DogSession()
        self.addCleanup(s.loop.call_soon_threadsafe, s.loop.stop)
        s.body = body
        return s.state()

    def test_state_serves_faults_with_age_and_every_stream(self):
        st = self._state(_with_fault(_fed()[0]))
        self.assertEqual([(f["id"], f["text"]) for f in st["faults"]], [("600_8", LOW_BATTERY)])
        self.assertIsInstance(st["faults"][0]["age_s"], (int, float))
        self.assertGreaterEqual(st["faults"][0]["age_s"], 0)
        for k in SIX:
            self.assertIn(k, st["state"])
        self.assertEqual(set(st["streams"]), {"state", "video", "lidar"})
        self.assertEqual(st["streams"]["state"]["n"], 1)
        self.assertFalse(st["streams"]["state"]["stale"])
        self.assertEqual(st["streams"]["video"], {"on": False, "n": 0, "age_ms": None, "stale": False})
        self.assertEqual(st["streams"]["lidar"], {"on": False, "n": 0, "age_ms": None, "stale": False})

    def test_a_stream_that_stops_is_stale_with_its_age(self):
        b, _ = _fed()
        b._st_at -= 4.2   # the last state message arrived 4.2 s ago
        s = self._state(b)["streams"]["state"]
        self.assertTrue(s["stale"])
        self.assertGreaterEqual(s["age_ms"], 4200)


class Fixture(unittest.TestCase):
    def tearDown(self):
        os.environ["WTDD_STATE_FIXTURE"] = ""

    def _session(self) -> DogSession:
        s = DogSession()
        self.addCleanup(s.loop.call_soon_threadsafe, s.loop.stop)
        return s

    def test_the_fixture_says_so_and_carries_only_live_keys(self):
        os.environ["WTDD_STATE_FIXTURE"] = "wtdd/dog/fixtures/state-vitals.json"   # relative to the repo root, as the screenshot runs it
        served = self._session().state()
        self.assertTrue(str(served.get("fixture", "")).endswith("state-vitals.json"), "a served fixture must name itself (DEMO_CACHE)")
        self.assertEqual([f["id"] for f in served["faults"]], ["600_8"])
        os.environ["WTDD_STATE_FIXTURE"] = ""
        s = self._session()
        s.body = _with_fault(_fed()[0])
        live = s.state()
        for name in ("state-vitals.json", "state-vitals-stale.json"):
            fx = json.loads((FIX / name).read_text())
            top = {k for k in fx if not k.startswith("_")}
            self.assertLessEqual({"state", "faults", "streams", "map", "vel"}, top)
            self.assertLessEqual(top, set(live), f"{name} carries a key the live path never serves")
            self.assertLessEqual(set(fx["state"]), set(live["state"]), f"{name}: a state key the live Body never serves")
            for k in SIX:
                self.assertIn(k, fx["state"])
            self.assertLessEqual(set(fx["faults"][0]), set(live["faults"][0]))
            for k, v in fx["streams"].items():
                self.assertLessEqual(set(v), set(live["streams"][k]))
        stale = json.loads((FIX / "state-vitals-stale.json").read_text())
        self.assertGreater(stale["state"]["age_ms"], 2000)
        self.assertTrue(all(v["stale"] for v in stale["streams"].values()))

    def test_a_missing_fixture_fails_loud(self):
        os.environ["WTDD_STATE_FIXTURE"] = "wtdd/dog/fixtures/absent.json"
        with self.assertRaises(FileNotFoundError):   # never the live body, never an empty state
            self._session().state()


if __name__ == "__main__":
    unittest.main()
