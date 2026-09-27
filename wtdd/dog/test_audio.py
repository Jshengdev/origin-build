"""The dog's own speaker (roadmap 30): `who dis?!` and `ok, standing down` played through the AudioHub service, each
play one dog.say row with the response code and the player state read back, and the speaker never blocking the ask.
Run: /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_audio -v

Dry, like every test here: the connection is wtdd/dog/audio.py's recording stub (StubConn: records every request,
answers code 0 or the play code it is given, emits the canned player state STUB_PLAYER marked source "stub"), never a
dog. The ledger, the uuid cache and the rendered WAVs are temp files (WTDD_LEDGER is set before wtdd.ledger is
imported; SAY_DIR and CACHE are patched). WTDD_API_PORT points at a closed port so no test can reach an API, least of
all Johnny's live one on 7788. The macOS render (/usr/bin/say, then ffmpeg) is the one step that runs a real program;
it is skipped with a WARN line when either is absent, never faked. The fixture WAV is wtdd/dog/fixtures/say-1s.wav,
written by make_say_1s.py beside it (1 s, 44.1 kHz mono 16-bit, 88,244 bytes: 29 blocks of base64).
What it checks, each against the goal's words:
  - the upload: base64 of the WAV in the driver's own chunk size (read from webrtc_audiohub.py's text, a module that is
    never imported), the 1-based block index, the block count, the md5 and size of the file, the list read after it;
  - play sends 1002 {unique_id}; code 0 is an ok dog.say row with the player state, or "no read-back" plus GET_PLAY_MODE
    and the sport state when the topic is silent; a non-zero code is a FAILED row and .say.error; stub rows are labeled;
  - the speaker never blocks the ask: a fake ask that posts then says returns its post while the say fails on its own
    thread; the two hooks (intruder_alarm's ask, the listener's stand-down) speak after the post, and not in dry mode;
    a first say's render never stalls the body's loop; with the speaker unimportable, the stranger alarm still sounds
    and the ask is still posted and armed (neither waits on the speaker's import);
  - the uuid cache round-trips; a cached line plays without a list or an upload; a listed line is never re-uploaded;
  - GET /dog/state .say carries age_s, and is speaking from the ack on, not only after the read-back; WTDD_STATE_FIXTURE
    serves a planted state marked source "stub";
  - `say` is a tool (python -m wtdd list) and dog_say is untouched; WTDD_SAY_STUB=0 is the dog, not the stub.
"""
from __future__ import annotations
import asyncio
import base64
import contextlib
import hashlib
import importlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-audio-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_API_PORT"] = "9"   # discard: nothing listens, so a stray _via_api finds no API instead of Johnny's

from unitree_webrtc_connect.constants import AUDIO_API, RTC_TOPIC  # noqa: E402

from wtdd import ledger  # noqa: E402
from wtdd.dog import body as body_mod  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures"
WAV = FIX / "say-1s.wav"
ASK, STAND_DOWN = "who dis?!", "ok, standing down"


def audio():
    """The module under test, imported inside each test so each one fails on its own before the module exists."""
    return importlib.import_module("wtdd.dog.audio")


def n_rows() -> int:
    return len(ledger.rows())


def new_rows(n0: int, tool: str | None = None) -> list[dict]:
    return [r for r in ledger.rows()[n0:] if tool is None or r["tool"] == tool]


def param(opts: dict):
    p = opts.get("parameter")
    return json.loads(p) if isinstance(p, str) else p


def stub_body(play_code: int = 0, player: bool = True) -> body_mod.Body:
    """A Body over the recording stub, subscribed to the player-state topic the way connect() does, with one sport
    state sample planted so fresh_state() returns a real snapshot (with a WARN that no newer sample came)."""
    b = body_mod.Body()
    b.conn = audio().StubConn(play_code=play_code, player=player)
    b.conn.datachannel.pub_sub.subscribe(RTC_TOPIC["AUDIO_HUB_PLAY_STATE"], b._on_player)
    b._on_state({"data": {"mode": 0, "position": [0.0, 0.0, 0.31], "body_height": 0.31, "imu_state": {"rpy": [0.0, 0.0, 0.0]}}})
    return b


def sent(b: body_mod.Body, topic: str | None = None, api_id: int | None = None) -> list[tuple[str, dict]]:
    return [(t, o) for t, o in b.conn.datachannel.pub_sub.sent
            if (topic is None or t == topic) and (api_id is None or o["api_id"] == api_id)]


def copy_fixture(text: str, out) -> Path:
    """Stands in for the macOS render in the flows that only need a WAV on disk (the render has its own test)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(WAV, out)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.a = audio()
        self.tmp = Path(tempfile.mkdtemp(dir=_TMP))
        self.cache = self.tmp / "say.json"
        for p in (mock.patch.object(body_mod, "STATE_FRESH_S", 0.05),
                  mock.patch.object(self.a, "PLAYER_WAIT_S", 0.2),
                  mock.patch.object(self.a, "CHUNK_GAP_S", 0.0),
                  mock.patch.object(self.a, "SAY_DIR", self.tmp / "say"),
                  mock.patch.object(self.a, "CACHE", self.tmp / "say.live.json")):
            p.start()
            self.addCleanup(p.stop)

    def plant(self, uuid: str = "u-1") -> None:
        self.a.save_cache(self.cache, {ASK: {"name": self.a.LINES[ASK], "uuid": uuid}})

    def one(self, rows: list[dict]) -> dict:
        self.assertEqual(len(rows), 1, [r["tool"] for r in rows])
        return rows[0]


class Driver(Base):
    def test_topics_and_ids_are_the_drivers(self):
        a = self.a
        self.assertEqual(a.TOPIC, RTC_TOPIC["AUDIO_HUB_REQ"])
        self.assertEqual(a.PLAYER_TOPIC, RTC_TOPIC["AUDIO_HUB_PLAY_STATE"])
        self.assertEqual(a.VUI_TOPIC, RTC_TOPIC["VUI"])
        self.assertEqual((a.LIST, a.PLAY, a.PAUSE, a.PLAY_MODE, a.UPLOAD),
                         (AUDIO_API["GET_AUDIO_LIST"], AUDIO_API["SELECT_START_PLAY"], AUDIO_API["PAUSE"],
                          AUDIO_API["GET_PLAY_MODE"], AUDIO_API["UPLOAD_AUDIO_FILE"]))
        self.assertEqual((a.VOL_SET, a.VOL_GET), (1003, 1004))   # upstream vui.py; absent from the wheel

    def test_chunk_size_is_the_drivers_own_upload_line(self):
        src = (Path(importlib.util.find_spec("unitree_webrtc_connect").origin).parent / "webrtc_audiohub.py").read_text()
        upload = src[src.index("async def upload_audio_file"):]
        self.assertEqual(self.a.CHUNK, int(re.search(r"chunk_size = (\d+)", upload).group(1)))
        self.assertEqual(self.a.CHUNK, 4096)   # the module-level CHUNK_SIZE = 61440 is never used by the upload

    def test_never_imports_the_drivers_audiohub(self):
        src = Path(self.a.__file__).read_text()
        self.assertIsNone(re.search(r"(?m)^\s*(from|import)\s+\S*(webrtc_audiohub|pydub)", src))
        self.assertNotIn("unitree_webrtc_connect.webrtc_audiohub", sys.modules)

    def test_the_two_fixed_lines_are_the_ones_posted(self):
        from wtdd.tools import intruder_alarm
        self.assertEqual(set(self.a.LINES), {intruder_alarm.ASK, STAND_DOWN})
        self.assertIn(f'"{STAND_DOWN}"', (ROOT / "wtdd" / "chat" / "listen.py").read_text())
        names = list(self.a.LINES.values())
        self.assertEqual(len(set(names)), 2)
        for n in names:
            self.assertRegex(n, r"^[a-z0-9-]+$")


class Upload(Base):
    def test_chunks_carry_the_parameters_the_md5_the_count_and_a_1_based_index(self):
        a, data = self.a, WAV.read_bytes()
        b64, md5 = base64.b64encode(data).decode(), hashlib.md5(data).hexdigest()
        n = math.ceil(len(b64) / 4096)
        self.assertEqual((len(data), n), (88244, 29))
        b, n0, t0 = stub_body(), n_rows(), int(time.time() * 1000)
        out = asyncio.run(a.upload(b, WAV, "who-dis"))
        ups = sent(b, a.TOPIC, a.UPLOAD)
        self.assertEqual(len(ups), n)
        blocks = []
        for i, (_t, o) in enumerate(ups, 1):
            p = param(o)
            self.assertEqual(p["current_block_index"], i)
            self.assertEqual(p["total_block_number"], n)
            self.assertEqual(p["file_md5"], md5)
            self.assertEqual(p["file_size"], len(data))
            self.assertEqual(p["file_type"], "wav")
            self.assertEqual(p["file_name"], "who-dis")
            self.assertEqual(p["current_block_size"], len(p["block_content"]))
            self.assertEqual(len(p["block_content"]), 4096 if i < n else len(b64) - 4096 * (n - 1))
            self.assertIsInstance(p["create_time"], int)
            self.assertLess(abs(p["create_time"] - t0), 60_000)
            blocks.append(p["block_content"])
        self.assertEqual("".join(blocks), b64)
        # read back: the list after the last block names the file under its CUSTOM_NAME
        order = [o["api_id"] for _t, o in sent(b, a.TOPIC)]
        self.assertIn(a.LIST, order[order.index(a.UPLOAD) + n:])
        uuid = next(x["UNIQUE_ID"] for x in b.conn.datachannel.pub_sub.listed if x["CUSTOM_NAME"] == "who-dis")
        self.assertEqual((out["uuid"], out["chunks"]), (uuid, n))
        r = self.one(new_rows(n0, "dog.audio_upload"))
        self.assertTrue(r["ok"])
        self.assertEqual((r["args"]["file_md5"], r["args"]["file_size"]), (md5, len(data)))
        self.assertIn(uuid, json.dumps(r["state_after"]))
        self.assertIsInstance(r["latency_ms"], int)
        self.assertEqual((r["cached"], r["source"]), (True, "stub"))


class Play(Base):
    def test_play_sends_1002_unique_id_and_reads_back_the_player_state(self):
        a, b = self.a, stub_body()
        self.plant("u-1")
        n0 = n_rows()
        asyncio.run(b.say(ASK, cache=self.cache))
        self.assertEqual([param(o) for _t, o in sent(b, a.TOPIC, a.PLAY)], [{"unique_id": "u-1"}])
        self.assertEqual(sent(b, a.TOPIC, a.UPLOAD) + sent(b, a.TOPIC, a.LIST), [])   # cached: straight to play
        self.assertEqual(sent(b, a.TOPIC, a.PLAY_MODE), [])                           # the topic answered
        r = self.one(new_rows(n0, "dog.say"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["args"], {"text": ASK, "uuid": "u-1", "via": "audiohub"})
        self.assertEqual(r["response_or_error"]["header"]["status"]["code"], 0)
        self.assertEqual(r["state_after"]["player_state"], a.STUB_PLAYER)
        self.assertEqual(a.STUB_PLAYER["source"], "stub")
        self.assertIsNotNone(r["state_after"]["sport"])
        self.assertEqual((r["cached"], r["source"]), (True, "stub"))
        st = b.say_state
        self.assertEqual((st["text"], st["code"], st["player_state"]), (ASK, 0, a.STUB_PLAYER))
        self.assertIsInstance(st["at"], float)
        self.assertNotIn("error", st)

    def test_a_silent_topic_is_no_read_back_plus_the_play_mode_and_the_sport_state(self):
        a, b = self.a, stub_body(player=False)
        self.plant()
        n0 = n_rows()
        asyncio.run(b.say(ASK, cache=self.cache))
        r = self.one(new_rows(n0, "dog.say"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["state_after"]["player_state"], "no read-back")
        self.assertEqual(len(sent(b, a.TOPIC, a.PLAY_MODE)), 1)
        self.assertIn("play_mode", r["state_after"])
        self.assertIsNotNone(r["state_after"]["sport"])
        self.assertEqual(b.say_state["player_state"], "no read-back")

    def test_a_play_mode_that_is_not_json_is_kept_raw_and_the_accepted_play_stays_ok(self):
        # GET_PLAY_MODE's payload shape is UNVERIFIED: a 1010 answering code 0 with a plain string (not JSON) is kept
        # raw on state_after, and the dog's code-0 answer to 1002 stays the row's response: never a FAILED row, never red.
        a, b = self.a, stub_body(player=False)
        self.plant()
        ps, raw = b.conn.datachannel.pub_sub, {}
        orig = ps.publish_request_new

        async def plain(topic, options):
            out = await orig(topic, options)
            if (topic, options["api_id"]) == (a.TOPIC, a.PLAY_MODE):
                out["data"]["data"] = "single_cycle"
                raw["play_mode"] = out["data"]
            elif (topic, options["api_id"]) == (a.TOPIC, a.PLAY):
                raw["play"] = out["data"]
            return out
        ps.publish_request_new = plain
        n0 = n_rows()
        asyncio.run(b.say(ASK, cache=self.cache))
        r = self.one(new_rows(n0, "dog.say"))
        self.assertTrue(r["ok"], r["response_or_error"])
        self.assertEqual(r["state_after"]["play_mode"], {"code": 0, "data": raw["play_mode"]})
        self.assertEqual(r["response_or_error"], raw["play"])
        self.assertEqual(r["response_or_error"]["header"]["status"]["code"], 0)
        self.assertEqual(b.say_state["player_state"], "no read-back")
        self.assertNotIn("error", b.say_state)

    def test_speaking_is_served_from_the_ack_while_a_silent_topic_is_still_awaited(self):
        """The badge is green while the line plays: .say is published at the ack (code 0), not after the read-back wait,
        GET_PLAY_MODE and the fresh sport state, which on a silent topic outlast a 1 s line."""
        a, b = self.a, stub_body(player=False)
        self.plant()
        copy_fixture(ASK, a.SAY_DIR / f"{a.LINES[ASK]}.wav")   # 1.00 s: the line's own length
        ack, seen, req = {}, [], b._request

        async def timed(topic, api_id, parameter=None, **k):
            out = await req(topic, api_id, parameter, **k)
            if (topic, api_id) == (a.TOPIC, a.PLAY):
                ack["t"] = time.time()
            return out
        b._request = timed

        async def go():
            t = asyncio.create_task(b.say(ASK, cache=self.cache))
            while not t.done():
                if "t" in ack:
                    s = a.served(b.say_state)
                    seen.append(bool(s and s["speaking"]))
                await asyncio.sleep(0.02)
            await t
        with mock.patch.object(a, "PLAYER_WAIT_S", 0.5):
            asyncio.run(go())
        self.assertTrue(seen and any(seen), f"never speaking while the read-back was awaited: {seen}")
        self.assertLess(abs(b.say_state["at"] - ack["t"]), 0.1)
        self.assertEqual(b.say_state["player_state"], "no read-back")   # the read-back still lands on .say after

    def test_code_7_is_a_failed_row_and_say_error(self):
        a, b = self.a, stub_body(play_code=7)
        self.plant()
        n0 = n_rows()
        with self.assertRaises(RuntimeError):
            asyncio.run(b.say(ASK, cache=self.cache))
        r = self.one(new_rows(n0, "dog.say"))
        self.assertFalse(r["ok"])
        self.assertIn("code=7", r["response_or_error"])
        st = b.say_state
        self.assertEqual((st["text"], st["code"]), (ASK, 7))
        self.assertIn("code=7", st["error"])
        self.assertNotIn("player_state", st)
        self.assertEqual(sent(b, a.TOPIC, a.PLAY_MODE), [])

    def test_a_line_that_is_not_one_of_the_two_is_refused_before_any_send(self):
        b = stub_body()
        n0 = n_rows()
        with self.assertRaises((PermissionError, ValueError)):
            asyncio.run(b.say("hello there", cache=self.cache))
        self.assertEqual(b.conn.datachannel.pub_sub.sent, [])
        self.assertFalse(self.one(new_rows(n0, "dog.say"))["ok"])
        self.assertIn("error", b.say_state)

    def test_an_id_outside_the_allowlist_is_refused_before_any_send(self):
        a, b = self.a, stub_body()
        for topic, api_id in ((a.TOPIC, 4001), (a.TOPIC, 3001), (a.TOPIC, 1009), (a.VUI_TOPIC, 1007)):
            with self.assertRaises(PermissionError):
                asyncio.run(a.request(b, topic, api_id))
        self.assertEqual(b.conn.datachannel.pub_sub.sent, [])

    def test_pause_and_volume_set_then_read_back(self):
        a, b = self.a, stub_body()
        asyncio.run(a.pause(b))
        self.assertEqual(len(sent(b, a.TOPIC, a.PAUSE)), 1)
        n0 = n_rows()
        self.assertEqual(asyncio.run(a.volume(b, 5)), 5)
        vui = [(o["api_id"], param(o)) for _t, o in sent(b, a.VUI_TOPIC)]
        self.assertEqual(vui[0], (1003, {"volume": 5}))
        self.assertEqual(vui[1][0], 1004)
        r = self.one(new_rows(n0, "dog.volume"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["state_after"]["volume"], 5)
        self.assertEqual(asyncio.run(a.volume_get(b)), 5)
        k, n1 = len(sent(b, a.VUI_TOPIC)), n_rows()
        with self.assertRaises(ValueError):
            asyncio.run(a.volume(b, 11))
        self.assertEqual(len(sent(b, a.VUI_TOPIC)), k)
        self.assertFalse(self.one(new_rows(n1, "dog.volume"))["ok"])


class Cache(Base):
    def test_the_uuid_cache_round_trips(self):
        d = {ASK: {"name": "who-dis", "uuid": "u-9", "md5": "0" * 32}}
        self.a.save_cache(self.cache, d)
        self.assertEqual(self.a.load_cache(self.cache), d)
        self.assertEqual(self.a.load_cache(self.tmp / "absent.json"), {})

    def test_the_first_say_uploads_and_caches_the_next_plays_by_the_cached_uuid(self):
        a, b = self.a, stub_body()
        with mock.patch.object(a, "render", side_effect=copy_fixture) as render:
            asyncio.run(b.say(ASK, cache=self.cache))
            render.assert_called_once()
        self.assertGreater(len(sent(b, a.TOPIC, a.UPLOAD)), 0)
        uuid = a.load_cache(self.cache)[ASK]["uuid"]
        self.assertEqual(uuid, next(x["UNIQUE_ID"] for x in b.conn.datachannel.pub_sub.listed
                                    if x["CUSTOM_NAME"] == a.LINES[ASK]))
        self.assertAlmostEqual(b.say_state["seconds"], 1.0, places=2)   # the line's own length, from the WAV
        b2 = stub_body()   # a fresh connection whose dog lists nothing: the cache alone names the uuid
        with mock.patch.object(a, "render", side_effect=copy_fixture) as render:
            asyncio.run(b2.say(ASK, cache=self.cache))
            render.assert_not_called()
        self.assertEqual(sent(b2, a.TOPIC, a.UPLOAD) + sent(b2, a.TOPIC, a.LIST), [])
        self.assertEqual([param(o) for _t, o in sent(b2, a.TOPIC, a.PLAY)], [{"unique_id": uuid}])

    def test_a_line_the_dog_already_lists_is_not_uploaded_again(self):
        a, b = self.a, stub_body()
        b.conn.datachannel.pub_sub.listed.append({"CUSTOM_NAME": a.LINES[ASK], "UNIQUE_ID": "dog-1"})
        with mock.patch.object(a, "render", side_effect=copy_fixture) as render:
            asyncio.run(b.say(ASK, cache=self.cache))
            render.assert_not_called()
        self.assertEqual(sent(b, a.TOPIC, a.UPLOAD), [])
        self.assertEqual([param(o) for _t, o in sent(b, a.TOPIC, a.PLAY)], [{"unique_id": "dog-1"}])
        self.assertEqual(a.load_cache(self.cache)[ASK]["uuid"], "dog-1")


class Render(Base):
    def test_say_then_ffmpeg_make_a_44k1_mono_16_bit_wav(self):
        with wave.open(str(WAV)) as w:   # the fixture has the shape the render must produce
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()), (44100, 1, 2, 44100))
        if not Path("/usr/bin/say").exists() or not (shutil.which("ffmpeg") or Path("/opt/homebrew/bin/ffmpeg").exists()):
            print("[wtdd:test] WARN /usr/bin/say or ffmpeg is absent: the render step is skipped, not faked", file=sys.stderr)
            self.skipTest("/usr/bin/say or ffmpeg absent")
        out = self.a.render(ASK, self.tmp / "who-dis.wav")
        with wave.open(str(out)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (44100, 1, 2))
            self.assertTrue(0.2 < w.getnframes() / w.getframerate() < 5.0)


class NeverBlocks(Base):
    def test_a_failed_say_never_blocks_the_ask(self):
        a, b = self.a, stub_body(play_code=7)
        self.plant()
        order: list[str] = []

        def say(text):
            order.append("say")
            return asyncio.run(b.say(text, cache=self.cache))

        def ask():   # the shape of every ask: post, then the one hook line, then return the post
            post = {"rowid": 42, "text": ASK}
            order.append("post")
            self.thread = a.after(ASK, say=say)
            return post

        n0 = n_rows()
        self.assertEqual(ask(), {"rowid": 42, "text": ASK})
        self.assertIsInstance(self.thread, threading.Thread)
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())
        self.assertEqual(order, ["post", "say"])
        r = self.one(new_rows(n0, "dog.say"))
        self.assertFalse(r["ok"])
        self.assertIn("code=7", r["response_or_error"])
        self.assertEqual(b.say_state["code"], 7)

    def test_after_returns_before_a_slow_speaker(self):
        t0 = time.monotonic()
        th = self.a.after(ASK, say=lambda text: time.sleep(0.6))
        self.assertLess(time.monotonic() - t0, 0.2)
        th.join(5)

    def test_intruder_alarm_speaks_its_ask_after_the_post(self):
        calls: list[tuple[str, str]] = []
        frame = self.tmp / "frame.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xd9")
        with mock.patch("wtdd.commands.look", return_value={"file": str(frame), "pitch_deg": 0.0}), \
             mock.patch("wtdd.tools.dog_say.boxed", return_value={"file": str(frame), "classes": ["person"]}), \
             mock.patch("wtdd.tools.chat_post.run", side_effect=lambda **kw: calls.append(("post", kw.get("text"))) or {"rowid": 42}), \
             mock.patch("wtdd.dog.audio.after", side_effect=lambda text, *a_, **k: calls.append(("say", text))), \
             mock.patch("wtdd.config.ROOT", self.tmp):
            from wtdd.tools import intruder_alarm
            out = intruder_alarm.run(ask=True)
        self.assertEqual(calls, [("post", ASK), ("say", ASK)])
        self.assertEqual(out["post"], {"rowid": 42})

    def test_the_listener_speaks_the_stand_down_after_its_post_and_not_in_dry_mode(self):
        from wtdd.chat import listen
        calls: list[tuple[str, str]] = []
        pend = self.tmp / "pending.json"

        def listener(dry: bool):
            L = listen.Listener.__new__(listen.Listener)   # no chat.db: only what verdict() reads
            L.guid, L.dry, L.armed_until, L.armed_by = "any;+;test", dry, 0.0, None
            L.post = lambda guid, key, kind, text, file: calls.append(("post", text))
            return L

        for dry, want in ((False, [("post", STAND_DOWN), ("say", STAND_DOWN)]), (True, [])):
            calls.clear()
            pend.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "trigger": "intruder-1", "seconds": 5}))
            with mock.patch.object(listen, "PENDING", pend), \
                 mock.patch("wtdd.dog.audio.after", side_effect=lambda text, *a_, **k: calls.append(("say", text))):
                self.assertTrue(listener(dry).verdict({"sender": "+15550000000", "text": "that's my roommate", "guid": f"g-{dry}"}))
            self.assertEqual(calls, want, f"dry={dry}")

    def test_a_first_say_never_stalls_the_body_loop(self):
        # The render (say + ffmpeg, about a second on this Mac) runs off the loop that also carries the drive's
        # 10 Hz Move and its StopMove: a ticker on the same loop never waits more than 0.3 s during a first say.
        a, b = self.a, stub_body()

        def slow(text, out):
            time.sleep(1.0)
            return copy_fixture(text, out)

        async def go() -> float:
            gaps: list[float] = []

            async def tick():
                last = time.monotonic()
                while True:
                    await asyncio.sleep(0.02)
                    gaps.append(time.monotonic() - last)
                    last = time.monotonic()
            t = asyncio.create_task(tick())
            await asyncio.sleep(0.05)
            try:
                await b.say(ASK, cache=self.cache)
            finally:
                t.cancel()
            return max(gaps)
        with mock.patch.object(a, "render", side_effect=slow) as render:
            worst = asyncio.run(go())
            render.assert_called_once()
        self.assertLess(worst, 0.3, f"the render held the body's loop for {worst:.2f} s")

    def unimportable_speaker(self):
        """wtdd.dog.audio cannot be imported (a broken SDK install): the paths below must not need it before the post."""
        import wtdd.dog as pkg
        import wtdd.tools.light_alarm  # noqa: F401  (imported before sys.modules is snapshotted and restored)
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.dict(sys.modules, {"wtdd.dog.audio": None}))
        stack.enter_context(mock.patch.object(pkg, "audio"))   # restored on exit
        del pkg.audio
        return stack

    def test_the_stranger_alarm_never_waits_on_the_speaker(self):
        from wtdd.chat import listen
        calls: list[tuple[str, str]] = []
        pend = self.tmp / "pending.json"
        pend.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "trigger": "intruder-1", "seconds": 5}))
        L = listen.Listener.__new__(listen.Listener)   # no chat.db: only what verdict() reads
        L.guid, L.dry, L.armed_until, L.armed_by = "any;+;test", False, 0.0, None
        L.post = lambda guid, key, kind, text, file: calls.append(("post", text))
        with mock.patch.object(listen, "PENDING", pend), \
             mock.patch("wtdd.tools.call", side_effect=lambda name, **kw: calls.append(("tool", name)) or {"signaled": [], "errors": []}), \
             self.unimportable_speaker():
            self.assertTrue(L.verdict({"sender": "+15550000000", "text": "idk", "guid": "g-idk"}))
        self.assertEqual([c[0] for c in calls], ["post", "tool"])
        self.assertIn("STRANGER DANGER", calls[0][1])
        self.assertEqual(calls[1], ("tool", "light_alarm"))

    def test_the_ask_is_posted_and_armed_before_the_speaker_is_imported(self):
        calls: list[tuple[str, str]] = []
        frame = self.tmp / "frame.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xd9")
        from wtdd.tools import intruder_alarm
        with mock.patch("wtdd.commands.look", return_value={"file": str(frame), "pitch_deg": 0.0}), \
             mock.patch("wtdd.tools.dog_say.boxed", return_value={"file": str(frame), "classes": ["person"]}), \
             mock.patch("wtdd.tools.chat_post.run", side_effect=lambda **kw: calls.append(("post", kw.get("text"))) or {"rowid": 42}), \
             mock.patch("wtdd.config.ROOT", self.tmp), self.unimportable_speaker():
            with self.assertRaises(ImportError):   # loud, on the intruder.alarm row, after the ask is in the thread
                intruder_alarm.run(ask=True)
        self.assertEqual(calls, [("post", ASK)])
        self.assertEqual(json.loads((self.tmp / "pending.json").read_text())["kind"], "who_dis")


class Served(Base):
    def test_served_adds_age_s_and_speaking(self):
        a, now = self.a, time.time()
        s = a.served({"text": ASK, "code": 0, "at": now - 0.3, "seconds": 1.0, "player_state": "no read-back"})
        self.assertTrue(s["speaking"])
        self.assertAlmostEqual(s["age_s"], 0.3, delta=0.2)
        s = a.served({"text": ASK, "code": 0, "at": now - 5.0, "seconds": 1.0, "player_state": "no read-back"})
        self.assertFalse(s["speaking"])
        self.assertAlmostEqual(s["age_s"], 5.0, delta=0.2)
        s = a.served({"text": ASK, "code": 7, "at": now, "seconds": 1.0, "error": "RuntimeError: code=7"})
        self.assertFalse(s["speaking"])
        self.assertIn("code=7", s["error"])
        self.assertIsNone(a.served(None))

    def test_dog_state_serves_say_with_age_s(self):
        from wtdd.dog.session import DogSession
        b = stub_body()
        self.plant()
        asyncio.run(b.say(ASK, cache=self.cache))
        s = DogSession()
        self.addCleanup(s.loop.call_soon_threadsafe, s.loop.stop)
        s.body = b
        say = s.state()["say"]
        self.assertEqual((say["text"], say["code"]), (ASK, 0))
        self.assertGreaterEqual(say["age_s"], 0)
        self.assertIn("speaking", say)


class Fixture(unittest.TestCase):
    """The shared DEMO_CACHE block (24, 25, 29, 30): WTDD_STATE_FIXTURE=<json> makes GET /dog/state serve the file,
    marked source "stub", without touching a dog. Unset, the live session answers."""

    def test_state_fixture_is_served_marked_stub(self):
        from wtdd.dog.session import DogSession
        for name in ("state-say.json", "state-say-failed.json"):
            s = DogSession()
            self.addCleanup(s.loop.call_soon_threadsafe, s.loop.stop)
            with mock.patch.dict(os.environ, {"WTDD_STATE_FIXTURE": str(FIX / name)}):
                st = s.state()
            self.assertEqual(st, {**json.loads((FIX / name).read_text()), "source": "stub"})
        self.assertEqual(st["say"]["code"], 7)
        self.assertIn("error", st["say"])


class Tool(unittest.TestCase):
    def test_say_is_a_tool_and_dog_say_is_untouched(self):
        from wtdd import tools
        reg = tools.registry()
        self.assertIn("say", sorted(reg))
        self.assertIn("text", reg["say"].ARGS)
        self.assertIn("dog_say", reg)
        out = subprocess.run([sys.executable, "-m", "wtdd", "list"], capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr[-400:])
        self.assertRegex(out.stdout, r"(?m)^say\s")


class StubFlag(Base):
    def test_the_stub_flag_runs_the_whole_line_on_the_recording_stub_and_labels_every_row(self):
        from wtdd import tools
        n0 = n_rows()
        with mock.patch.dict(os.environ, {"WTDD_SAY_STUB": "1"}), mock.patch.object(self.a, "render", side_effect=copy_fixture):
            out = tools.call("say", text=ASK)
        rows = [r for r in new_rows(n0) if r["tool"].startswith("dog.")]
        self.assertTrue({"dog.audio_upload", "dog.say"} <= {r["tool"] for r in rows}, [r["tool"] for r in rows])
        for r in rows:
            self.assertTrue(r["ok"], r)
            self.assertEqual((r["cached"], r["source"]), (True, "stub"), r["tool"])
        self.assertEqual((out["text"], out["code"], out["source"]), (ASK, 0, "stub"))
        self.assertFalse((self.tmp / "say.live.json").exists())   # the stub never writes the live uuid cache

    def test_the_stub_flag_set_to_0_false_or_no_is_the_dog_not_the_stub(self):
        """The repo's flags read 0/false/no as off (listen._flag, WTDD_ROUND_AVOID): WTDD_SAY_STUB=0 in a live .env
        must reach the dog's own speaker, never the recording stub."""
        from wtdd.dog import session
        from wtdd.tools import say
        for v in ("0", "false", "No"):
            with mock.patch.dict(os.environ, {"WTDD_SAY_STUB": v}), mock.patch.object(self.a, "stub_say") as stub, \
                    mock.patch.object(session.DogSession, "get") as get:
                say.run(text=ASK)
            stub.assert_not_called()
            get.return_value.say.assert_called_once_with(ASK, None)


if __name__ == "__main__":
    unittest.main()
