"""The alarm must be SEEN. Live 2026-09-27 20:37-20:47 at Johnny's: the native CLIP v2 "signaling: alternating" was
accepted and read back ("alternating") on all 4 living-room lamps, yet nothing showed; explicit colour sets did show.
So light_alarm must cycle explicit red/blue sets on every living-room lamp, then put each lamp back as it was (on,
brightness, xy), with one lights.alarm row. A stub bridge records the calls; nothing here touches a real bridge or strip.
Run: python -m unittest wtdd.test_light_alarm"""
from __future__ import annotations
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="wtdd-alarm-"))
os.environ["WTDD_LEDGER"] = str(TMP / "ledger.jsonl")  # before importing the ledger: never the real file

from . import ledger  # noqa: E402
from .hue.api import BLUE_XY, RED_XY, HueBridge  # noqa: E402
from .tools import light_alarm  # noqa: E402

IDS = ["L1", "L2", "L3", "L4"]
BEFORE = {"L1": (True, 40.0, (0.30, 0.30)), "L2": (False, 20.0, (0.45, 0.41)),
          "L3": (True, 75.0, (0.20, 0.10)), "L4": (True, 10.0, (0.50, 0.40))}


class StubBridge:
    """Holds each lamp's state and records every call; set() and signal() behave like the bridge after the read-back."""

    def __init__(self, refuse: str | None = None):
        self.lock = threading.Lock()
        self.calls: list[tuple] = []
        self.refuse = refuse
        self.st = {rid: {"on": on, "bri": bri, "xy": xy} for rid, (on, bri, xy) in BEFORE.items()}

    def lights(self):
        return [{"id": rid, "metadata": {"name": f"lamp {rid}"}} for rid in IDS]

    def read(self, rid):
        s = self.st[rid]
        return {"id": rid, "on": {"on": s["on"]}, "dimming": {"brightness": s["bri"]},
                "color": {"xy": {"x": s["xy"][0], "y": s["xy"][1]}},
                "signaling": {"signal_values": ["no_signal", "alternating"]}}

    def set(self, rid, on=None, bri=None, xy=None):
        with self.lock:
            self.calls.append(("set", rid, on, bri, None if xy is None else tuple(xy)))
        if rid == self.refuse:
            raise RuntimeError("stub: lamp refused the set")
        s = self.st[rid]
        s.update({k: v for k, v in (("on", on), ("bri", bri), ("xy", None if xy is None else tuple(xy))) if v is not None})
        return s

    def signal(self, rid, seconds, colors=(RED_XY, BLUE_XY)):
        with self.lock:
            self.calls.append(("signal", rid, seconds))
        return {"signal": "alternating"}


class LightAlarm(unittest.TestCase):
    def setUp(self):
        zones = TMP / f"zones-{self._testMethodName}.json"
        zones.write_text(json.dumps({"living room": {"lights": IDS}}))
        self.strip = []
        p = [mock.patch("wtdd.hue.__main__.ZONES", zones),
             mock.patch("wtdd.tuya.__main__.strip", lambda **kw: self.strip.append(kw) or
                        {"on": kw.get("on", True), "brightness_pct": kw.get("bri", 30.0)}),
             mock.patch.dict(os.environ, {"WTDD_ALARM_MODE": ""})]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def _run(self, stub: StubBridge, seconds: float = 3):
        with mock.patch.object(HueBridge, "from_env", classmethod(lambda cls, *a, **k: stub)):
            n = len(ledger.rows())
            out = light_alarm.run(seconds=seconds)
            return out, [r for r in ledger.rows()[n:] if r["tool"] == "lights.alarm"]

    def _flips(self, stub: StubBridge, rid: str) -> list:
        return [c[4] for c in stub.calls if c[0] == "set" and c[1] == rid and c[4] in (RED_XY, BLUE_XY)]

    def test_cycles_explicit_red_blue_then_restores(self):
        stub = StubBridge()
        out, rows = self._run(stub, seconds=3)
        self.assertFalse([c for c in stub.calls if c[0] == "signal"], "the native signal was accepted live and not seen")
        for rid in IDS:
            flips = self._flips(stub, rid)
            self.assertGreaterEqual(len(flips), 2, f"{rid}: fewer than 2 colour flips: {flips}")
            self.assertEqual(flips[0], RED_XY)
            self.assertTrue(all(a != b for a, b in zip(flips, flips[1:])), f"{rid}: flips do not alternate: {flips}")
            on, bri, xy = BEFORE[rid]
            self.assertEqual((stub.st[rid]["on"], stub.st[rid]["bri"], stub.st[rid]["xy"]), (on, bri, xy),
                             f"{rid}: not put back as it was")
        self.assertEqual(self.strip[0], {"on": True, "bri": 100.0})
        self.assertEqual(len(rows), 1, "one lights.alarm row")
        after = rows[0]["state_after"]
        self.assertTrue(rows[0]["ok"])
        self.assertGreaterEqual(after["flips"], 2)
        self.assertEqual(after["errors"], [])
        self.assertEqual(len(after["restored"]), len(IDS) + 1)

    def test_a_refusing_lamp_is_counted_and_the_others_still_flip_and_restore(self):
        stub = StubBridge(refuse="L2")
        out, rows = self._run(stub, seconds=3)
        after = rows[0]["state_after"]
        self.assertTrue(rows[0]["ok"])
        self.assertTrue(any("lamp L2" in e for e in after["errors"]), after["errors"])
        self.assertTrue(all(f >= 1 for f in after["flip_failures"]), after["flip_failures"])
        for rid in ("L1", "L3", "L4"):
            self.assertGreaterEqual(len(self._flips(stub, rid)), 2)
            on, bri, xy = BEFORE[rid]
            self.assertEqual((stub.st[rid]["on"], stub.st[rid]["bri"], stub.st[rid]["xy"]), (on, bri, xy))
        refused = [c for c in stub.calls if c[1] == "L2"]
        self.assertLessEqual(len(refused), after["flips"] + 2, "a refusing lamp is retried within a flip")


if __name__ == "__main__":
    unittest.main()
