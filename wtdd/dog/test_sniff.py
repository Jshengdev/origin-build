"""RED for roadmap item 28 (sniff): one command watches one topic for N seconds and writes what the dog actually
publishes as one dog.sniff row, and GET /dog/streams says which streams the body publishes and which it was never
seen to. Dry: a stub stands in for the driver's pub_sub, so no dog, no network and no real ledger is ever touched.

  python -m unittest wtdd.dog.test_sniff

The stub copies the driver (unitree_webrtc_connect 2.2.0, msgs/pub_sub.py): one callback per topic in `subscriptions`
(:16), subscribe() overwrites it (:128-129), unsubscribe() only sends (:133-140), run_resolve() calls the one callback
registered for message["topic"] (:18-26). Every send is recorded in `sent`, so "never subscribes" and "refused before
any send" are asserted on the stub. Messages arrive on the same asyncio loop the sniff sleeps on, as the driver's
on_message does (webrtc_datachannel.py:60-84).

What it checks (the goal's verifying command):
  - rt/lf/lowstate (fixtures/sniff-lowstate-stub.json, an UNVERIFIED typed guess) at 10 Hz for 1 s: messages 10, hz
    within ten percent, the key tree with types and array lengths, first_payload cut to 2 KB, subscribed once and
    unsubscribed once, one dog.sniff row labeled cached/stub, one stderr line per second, Body.streams() counts it but
    never calls a stub "seen";
  - a topic that never answers: ok=false and "0 messages in 1 s"; on a utlidar topic args.why names the decoder trap;
  - LF_SPORT_MOD_STATE, ULIDAR_ARRAY, ROBOTODOM: nothing sent at all (no pub_sub.subscribe), still counted through
    Body's own callback, Body's own state still moves, the tap is gone afterwards; the RTC_TOPIC key is accepted;
  - an unknown topic is refused before any send, by Body and by DogSession (no connect), with its row;
  - a non-owned topic whose one driver slot already holds a callback the sniff did not put there (30's _on_player on
    rt/audiohub/player/state) is refused before any send, that callback left in place, with its row; a topic the sniff
    itself subscribed before can be sniffed again;
  - every message returns with the ledger file's size unchanged (the tap never writes the ledger);
  - GET /dog/streams: the three owned topics with seen false before any message; dog.sniff rows merged (a live row
    makes a topic seen, a stub row never does, a failed row's text is served for the red cell);
  - the registry has the sniff tool (python -m wtdd list).
The key tree: a dict is a dict of subtrees; a list is [length, subtree of its first item] ([0] when empty); a leaf is
its type name: "int", "float", "str", "bool", "null" ("bytes[N]" and "ndarray[shape] dtype" for binary payloads).
Nothing here ran on the dog.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-sniff-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "import.jsonl")   # before any wtdd import: the real ledger.jsonl is never opened
os.environ["UNITREE_ROBOT_IP"] = "192.0.2.1"              # TEST-NET-1: a connect by mistake can never reach a real dog

from http.server import ThreadingHTTPServer  # noqa: E402

import numpy as np  # noqa: E402

from wtdd import ledger, tools  # noqa: E402
from wtdd.dog import body as B  # noqa: E402

T = B.RTC_TOPIC
OWNED = (T["LF_SPORT_MOD_STATE"], T["ULIDAR_ARRAY"], T["ROBOTODOM"])
CONTRACT = {"topic", "owned", "hz", "age_ms", "messages", "keys_n", "seen", "last_row_ts"}
LOW = json.loads((Path(__file__).parent / "fixtures" / "sniff-lowstate-stub.json").read_text())

# Typed stand-ins for the three owned topics, not messages from the dog: only the keys Body's own callbacks read.
SPORT = {"mode": 0, "position": [0.1, 0.2, 0.0], "velocity": [0.0, 0.0, 0.0], "imu_state": {"rpy": [0.0, 0.01, 1.57]}}
VOXEL = {"stamp": 1.0, "frame_id": "odom", "resolution": 0.05, "src_size": 77824, "origin": [0.0, 0.0, -0.3],
         "width": [128, 128, 38], "data": {"points": np.array([[1.0, 1.0, 0.2], [1.05, 1.0, 0.2], [1.1, 1.0, 0.25]])}}
POSE = {"pose": {"position": {"x": 0.1, "y": 0.2, "z": 0.0}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}


class StubPubSub:
    """The driver's WebRTCDataChannelPubSub with every send recorded in `sent`."""

    def __init__(self) -> None:
        self.channel = type("Channel", (), {"readyState": "open"})()
        self.subscriptions: dict = {}
        self.sent: list[tuple[str, str]] = []

    def subscribe(self, topic, callback=None):
        self.sent.append(("subscribe", topic))
        if callback:
            self.subscriptions[topic] = callback

    def unsubscribe(self, topic):
        self.sent.append(("unsubscribe", topic))

    def publish_without_callback(self, topic, data=None, msg_type=None):
        self.sent.append(("publish", topic))

    async def publish(self, topic, data=None, msg_type=None):
        self.sent.append(("publish", topic))
        raise AssertionError(f"a sniff published to {topic}")

    async def publish_request_new(self, topic, options=None):
        self.sent.append(("request", topic))
        raise AssertionError(f"a sniff sent a request to {topic}")

    def run_resolve(self, message):   # the driver's dispatch: the ONE callback registered for the topic
        cb = self.subscriptions.get(message.get("topic"))
        if cb:
            cb(message)


class StubDataChannel:
    def __init__(self) -> None:
        self.pub_sub = StubPubSub()

    def set_decoder(self, name):
        self.pub_sub.sent.append(("set_decoder", name))

    async def disableTrafficSaving(self, on):  # noqa: N802  (the driver's name)
        self.pub_sub.sent.append(("disableTrafficSaving", str(on)))
        return True


class StubConn:
    """Rows written through a stub say so (night-1 contracts E: cached=True, source="stub"); Body reads `source`."""
    source = "stub"

    def __init__(self) -> None:
        self.datachannel = StubDataChannel()


def stub_body() -> B.Body:
    """A Body as connect() and lidar_on() leave it (body.py:273, lidar.py:74-76), wired to the stub. The owned
    callbacks go straight into the driver's dict, so the stub's `sent` starts empty."""
    b = B.Body()
    b.conn = StubConn()
    ps = b.conn.datachannel.pub_sub
    ps.subscriptions[T["LF_SPORT_MOD_STATE"]] = b._on_state
    ps.subscriptions[T["ULIDAR_ARRAY"]] = b._on_lidar
    ps.subscriptions[T["ROBOTODOM"]] = b._on_utpose
    b._lidar_on = True
    return b


def ledger_size() -> int:
    return ledger.LEDGER.stat().st_size if ledger.LEDGER.exists() else 0


async def emit(ps: StubPubSub, topic: str, data, n: int, hz: float, grew: list) -> None:
    """n messages at hz on the loop's clock, the first 50 ms in; the ledger size is read around every dispatch."""
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    for i in range(n):
        await asyncio.sleep(max(0.0, t0 + 0.05 + i / hz - loop.time()))
        before = ledger_size()
        ps.run_resolve({"type": "msg", "topic": topic, "data": data})
        grew.append(ledger_size() - before)


def run_sniff(b: B.Body, topic: str, seconds: int = 1, data=None, n: int = 0, hz: float = 10.0,
              emit_topic: str | None = None, grew: list | None = None):
    """Body.sniff(topic, seconds) with the stub emitting on the same loop; returns its result or raises its error."""
    async def main():
        jobs = [b.sniff(topic, seconds)]
        if n:
            jobs.append(emit(b.conn.datachannel.pub_sub, emit_topic or topic, data, n, hz, grew if grew is not None else []))
        return (await asyncio.gather(*jobs, return_exceptions=True))[0]
    out = asyncio.run(main())
    if isinstance(out, BaseException):
        raise out
    return out


def sniff_rows() -> list[dict]:
    return [r for r in ledger.rows() if r.get("tool") == "dog.sniff"]


class Sniff(unittest.TestCase):
    def setUp(self) -> None:
        ledger.LEDGER = _TMP / f"{self._testMethodName}.jsonl"   # a fresh file per test

    def test_lowstate_counts_rate_keys_and_cuts_the_payload(self):
        b, t, grew, err = stub_body(), T["LOW_STATE"], [], io.StringIO()
        ps = b.conn.datachannel.pub_sub
        with contextlib.redirect_stderr(err):
            out = run_sniff(b, t, 1, data=LOW["data"], n=10, grew=grew)
        self.assertEqual(out["messages"], 10)
        self.assertIsNotNone(out["hz"])
        self.assertLessEqual(abs(out["hz"] - 10.0), 1.0, f"hz {out['hz']} is not 10 within ten percent")
        k = out["keys"]
        self.assertEqual(set(k), set(LOW["data"]))
        self.assertEqual(k["imu_state"]["quaternion"], [4, "float"])
        self.assertEqual(k["imu_state"]["temperature"], "int")
        self.assertEqual(k["motor_state"][0], len(LOW["data"]["motor_state"]))
        self.assertEqual(k["motor_state"][1]["q"], "float")
        self.assertEqual(k["motor_state"][1]["temperature"], "int")
        self.assertEqual(k["bms_state"]["soc"], "int")
        self.assertEqual(k["bms_state"]["cell_vol"], [8, "int"])
        self.assertEqual(k["power_v"], "float")
        self.assertGreater(len(json.dumps(LOW["data"]).encode()), 2048, "the fixture must be big enough to be cut")
        fp = out["first_payload"]
        self.assertIsInstance(fp, str)
        self.assertLessEqual(len(fp.encode()), 2048, "first_payload is not cut to 2 KB")
        self.assertIn('"imu_state"', fp)
        self.assertIsInstance(out["last_at"], str)
        self.assertEqual(ps.sent, [("subscribe", t), ("unsubscribe", t)], "one subscribe for N s, one unsubscribe after")
        self.assertEqual(grew, [0] * 10, "a tap wrote the ledger")
        rows = sniff_rows()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertTrue(r["ok"])
        self.assertEqual((r["args"]["topic"], r["args"]["seconds"]), (t, 1))
        self.assertEqual(r["response_or_error"]["messages"], 10)
        self.assertEqual((r["cached"], r["source"]), (True, "stub"), "a row written through a stub must say so")
        lines = [ln for ln in err.getvalue().splitlines() if "sniff" in ln and t in ln]
        self.assertGreaterEqual(len(lines), 1, "no stderr line per sniff second")
        streams = {e["topic"]: e for e in b.streams()}
        self.assertTrue(set(OWNED) <= set(streams), "Body.streams() must list the three owned topics")
        e = streams[t]
        self.assertFalse(e["owned"])
        self.assertEqual((e["messages"], e["keys_n"]), (10, len(LOW["data"])))
        self.assertFalse(e["seen"], "a stub is not this dog: seen stays false")
        self.assertEqual(e["source"], "stub")

    def test_silent_topic_fails_loud(self):
        b, t = stub_body(), T["MULTIPLE_STATE"]
        with self.assertRaises(Exception) as cm:
            run_sniff(b, t, 1)
        self.assertIn("0 messages in 1 s", str(cm.exception))
        rows = sniff_rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])
        self.assertIn("0 messages in 1 s", str(rows[0]["response_or_error"]))
        self.assertEqual(b.conn.datachannel.pub_sub.sent, [("subscribe", t), ("unsubscribe", t)], "unsubscribed even on silence")

    def test_utlidar_silence_names_the_decoder_trap(self):
        b, t = stub_body(), T["ULIDAR_STATE"]
        with self.assertRaises(Exception):
            run_sniff(b, t, 1)
        rows = sniff_rows()
        self.assertEqual(len(rows), 1, "no dog.sniff row for the silent utlidar topic")
        r = rows[0]
        self.assertFalse(r["ok"])
        self.assertIn("0 messages in 1 s", str(r["response_or_error"]))
        self.assertIn("decoder", str(r["args"].get("why") or "").lower(), "args.why must name the utlidar decoder trap")

    def test_owned_topics_are_tapped_never_subscribed(self):
        cases = ((T["LF_SPORT_MOD_STATE"], SPORT, lambda b: b._st_n == 5),
                 (T["ULIDAR_ARRAY"], VOXEL, lambda b: b._lidar_n == 5),
                 (T["ROBOTODOM"], POSE, lambda b: b._utpose == POSE))
        for t, data, moved in cases:
            with self.subTest(topic=t):
                b, grew = stub_body(), []
                ps = b.conn.datachannel.pub_sub
                own = ps.subscriptions[t]
                out = run_sniff(b, t, 1, data=data, n=5, grew=grew)
                self.assertEqual(out["messages"], 5)
                self.assertEqual(ps.sent, [], "an owned topic must never be subscribed (or anything sent)")
                self.assertEqual(ps.subscriptions[t], own, "Body's own callback was replaced")
                self.assertTrue(moved(b), "Body's own callback stopped doing its job")
                self.assertFalse(b.taps.get(t), "the tap outlived the sniff")
                self.assertEqual(grew, [0] * 5, "a tap wrote the ledger")

    def test_rtc_topic_key_is_accepted(self):
        b = stub_body()
        out = run_sniff(b, "LF_SPORT_MOD_STATE", 1, data=SPORT, n=3, emit_topic=T["LF_SPORT_MOD_STATE"])
        self.assertEqual(out["messages"], 3)
        rows = sniff_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["args"]["topic"], T["LF_SPORT_MOD_STATE"], "the row names the rt/ topic, not the key")
        self.assertEqual(b.conn.datachannel.pub_sub.sent, [])

    def test_unknown_topic_is_refused_before_any_send(self):
        b = stub_body()
        ps = b.conn.datachannel.pub_sub
        with self.assertRaises(ValueError):
            asyncio.run(b.sniff("rt/not/a/topic", 1))
        self.assertEqual(ps.sent, [])
        self.assertFalse(any(getattr(b, "taps", {}).values()))
        rows = sniff_rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])
        self.assertIn("rt/not/a/topic", str(rows[0]["response_or_error"]))
        from wtdd.dog.session import DogSession
        s = DogSession.get()
        with self.assertRaises(ValueError):
            s.sniff("rt/not/a/topic", 1)
        self.assertIsNone(s.body, "the session connected before refusing (a connect is a send)")
        seen = [r.get("tool") for r in ledger.rows()]
        self.assertNotIn("dog.probe", seen)
        self.assertNotIn("dog.connect", seen)
        self.assertEqual(len(sniff_rows()), 2, "the session's refusal is a row too")

    def test_a_slot_someone_else_holds_is_refused_before_any_send(self):
        b, t = stub_body(), T["AUDIO_HUB_PLAY_STATE"]
        ps = b.conn.datachannel.pub_sub

        def foreign(m):   # as 30's connect() leaves Body._on_player: in the driver's one slot for the whole session
            pass
        ps.subscriptions[t] = foreign
        with self.assertRaises(RuntimeError):
            run_sniff(b, t, 1)
        self.assertEqual(ps.sent, [], "a subscribe here would replace the callback already in the driver's one slot")
        self.assertIs(ps.subscriptions[t], foreign, "the sniff replaced another callback in the driver")
        self.assertFalse(b.taps.get(t), "the refused sniff left a tap behind")
        rows = sniff_rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])
        self.assertIn(t, str(rows[0]["response_or_error"]))
        again = T["MULTIPLE_STATE"]   # the driver keeps the sniff's own callback after unsubscribe: a re-sniff is not refused
        for _ in range(2):
            self.assertEqual(run_sniff(b, again, 1, data={"a": 1}, n=3)["messages"], 3)
        self.assertEqual(ps.sent, [("subscribe", again), ("unsubscribe", again)] * 2)

    def test_registry_has_sniff(self):
        m = tools.registry().get("sniff")
        self.assertIsNotNone(m, "python -m wtdd list does not show sniff")
        self.assertEqual(set(m.ARGS), {"topic", "seconds"})


class Streams(unittest.TestCase):
    def setUp(self) -> None:
        ledger.LEDGER = _TMP / f"{self._testMethodName}.jsonl"

    def _get(self) -> dict:
        from wtdd import api
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/dog/streams", timeout=5) as r:
                got = json.loads(r.read())
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertIsInstance(got, list)
        return {e["topic"]: e for e in got}

    def test_get_dog_streams(self):
        s = self._get()
        for t in OWNED:
            self.assertIn(t, s)
            self.assertTrue(CONTRACT <= set(s[t]), f"{t} lacks {sorted(CONTRACT - set(s[t]))}")
            self.assertTrue(s[t]["owned"])
            self.assertFalse(s[t]["seen"], f"{t} seen before any message")
            self.assertEqual(s[t]["messages"], 0)
        row = {"agent": "dog", "step": "dog.sniff", "tool": "dog.sniff", "app": "unitree", "state_before": None,
               "state_after": None, "latency_ms": 5001}
        live = ledger.append({**row, "ok": True, "args": {"topic": T["LOW_STATE"], "seconds": 5},
                              "response_or_error": {"messages": 12, "hz": 2.4, "keys": {"a": "int", "b": "float"},
                                                    "first_payload": "{}", "last_at": "2026-09-26T20:00:00"}})
        ledger.append({**row, "ok": True, "cached": True, "source": "stub", "args": {"topic": T["MULTIPLE_STATE"], "seconds": 5},
                       "response_or_error": {"messages": 50, "hz": 10.0, "keys": {"a": "int"}, "first_payload": "{}",
                                             "last_at": "2026-09-26T20:00:01"}})
        ledger.append({**row, "ok": False, "args": {"topic": T["ULIDAR_STATE"], "seconds": 5,
                                                    "why": "a binary payload on a utlidar topic dies in the driver's voxel decoder"},
                       "response_or_error": "RuntimeError: 0 messages in 5 s"})
        s = self._get()
        low = s[T["LOW_STATE"]]
        self.assertTrue(CONTRACT <= set(low))
        self.assertFalse(low["owned"])
        self.assertTrue(low["seen"], "a live dog.sniff row with messages is seen")
        self.assertEqual((low["messages"], low["hz"], low["keys_n"]), (12, 2.4, 2))
        self.assertEqual(low["last_row_ts"], live["ts"])
        self.assertFalse(s[T["MULTIPLE_STATE"]]["seen"], "a stub row never makes a topic seen on this dog")
        failed = s[T["ULIDAR_STATE"]]
        self.assertFalse(failed["seen"])
        self.assertIn("0 messages in 5 s", str(failed.get("error")), "the red cell's text is not served")
        for t in OWNED:
            self.assertFalse(s[t]["seen"])


# DEMO_CACHE: the dry screenshots (docs/evidence/night-2/28-remote.png, 28-failed.png) are drawn from rows this harness
# writes with stub messages through stub_body(), not from the dog; every row says cached=True, source="stub", and the page
# tags them "stub" and UNVERIFIED. Live: python -m wtdd.api on the dog (from the repo checkout, never a worktree), then
# python -m wtdd sniff topic=rt/lf/sportmodestate seconds=5, and the rest of the tool's Needs-the-dog order.
def plant(path: Path, fail: bool) -> None:
    """Writes the stub's dog.sniff rows into `path`, never a file inside the repo: rt/lf/sportmodestate at 20 Hz (SPORT,
    the stand-in) and rt/lf/lowstate at 10 Hz (the UNVERIFIED fixture), 2 s each; with fail, also a silent
    rt/utlidar/lidar_state for 5 s, so its row reads "0 messages in 5 s" with the decoder-trap why."""
    import sys
    from wtdd.config import ROOT
    path = path.resolve()
    if ROOT in path.parents:
        raise SystemExit(f"refusing to write stub rows inside the repo: {path}")
    ledger.LEDGER = path
    b = stub_body()
    run_sniff(b, T["LF_SPORT_MOD_STATE"], 2, data=SPORT, n=38, hz=20.0)
    run_sniff(b, T["LOW_STATE"], 2, data=LOW["data"], n=19, hz=10.0)
    if fail:
        try:
            run_sniff(b, T["ULIDAR_STATE"], 5)
        except RuntimeError as e:
            print(f"planted the failed row: {e}", file=sys.stderr)
        else:
            raise SystemExit("the silent topic did not fail")
    print(f"{len(sniff_rows())} dog.sniff rows in {path}", file=sys.stderr)


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="the tests; with --rows, the stub's dog.sniff rows for the dry screenshots")
    ap.add_argument("--rows", type=Path, help="a scratch ledger outside the repo, e.g. /tmp/night1/28/ok.jsonl")
    ap.add_argument("--fail", action="store_true", help="also plant the silent utlidar sniff (the 0-messages row)")
    a, rest = ap.parse_known_args()
    if a.rows:
        plant(a.rows, a.fail)
    else:
        unittest.main(argv=sys.argv[:1] + rest)
