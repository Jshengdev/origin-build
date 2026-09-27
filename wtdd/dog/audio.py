"""The dog's own speaker (roadmap 30): the two fixed chat lines, `who dis?!` (intruder_alarm's ask) and `ok, standing
down` (the listener's stand-down), played through the AudioHub service; each play is one dog.say row with the response
code and the player state read back, and the speaker never blocks the ask.

How. Every request goes through Body._request (one timed request, its status code) behind ALLOW, a per-topic allowlist
of api ids refused before anything is sent. The driver's own wrapper, unitree_webrtc_connect/webrtc_audiohub.py, is
never imported: its line 8 imports pydub, which imports audioop, removed in Python 3.13 (docs/gotchas/30-1-audiohub-import.md).
Each of its methods is one publish_request_new, so the same requests are sent here, read from its text:
  GET_AUDIO_LIST 1001 {}               :29-38    data.data is JSON {audio_list: [{CUSTOM_NAME, UNIQUE_ID, ...}]}
  SELECT_START_PLAY 1002 {unique_id}   :40-50
  PAUSE 1003 {}                        :52-60
  GET_PLAY_MODE 1010 {}                :109-118
  UPLOAD_AUDIO_FILE 2001               :120-187  base64 of the WAV in 4096-character blocks (`chunk_size = 4096` at :148;
      the module's CHUNK_SIZE = 61440 at :13 is never used: docs/gotchas/30-2-chunk-size.md), one request per block {file_name,
      file_type "wav", file_size, current_block_index (1-based), total_block_number, block_content, current_block_size,
      file_md5, create_time ms}, 0.1 s apart (:180). The file is then found in 1001's list by CUSTOM_NAME == file_name.
  VUI 1003 {volume: 0..10} set, 1004 {} get -> {volume}: upstream examples/go2/data_channel/vui/vui.py, not in the wheel.
Topics and ids: constants.py:83 (VUI), :105-106 (AUDIO_HUB_REQ, AUDIO_HUB_PLAY_STATE), :352-384 (AUDIO_API). A dict
parameter is json.dumps'd by msgs/pub_sub.py:87-118.

A line is rendered once on this Mac (render: /usr/bin/say, then ffmpeg to a 44.1 kHz mono 16-bit WAV in <repo>/say/,
on a worker thread so the body's loop keeps its drive ticks and StopMove),
uploaded once, and its uuid cached in <repo>/say.json (both gitignored, per dog; delete say.json after a dog reset); a
line the dog already lists is never uploaded again. say() plays by uuid: one dog.say {text, uuid, via: "audiohub"} row,
response_or_error the raw 1002 response, state_after the next rt/audiohub/player/state message (Body._on_player,
subscribed at connect) plus the sport state, or, when that topic is silent for PLAYER_WAIT_S, the literal "no read-back"
plus GET_PLAY_MODE (its raw response, never parsed; a refusal is a WARN) and a fresh sport state, never a default.
A non-zero play code is a FAILED row. Body.say_state is the last play, published at the ack (its player_state joins
after the read-back); served() adds age_s and speaking for GET /dog/state .say. speaking is the ack (code 0) plus
the line's own length (the WAV's seconds) until 30.3 pastes the player-state shape here; the row always carries the raw
player state or
"no read-back". after(text) is the one hook line an ask calls after its chat post: a thread, so the text lands in the
thread first and a failed say is only its own row, .say.error (the red badge) and one WARN line.

UNVERIFIED on this dog (nothing here has run on it): every request shape above, the 1001 payload keys, the
player-state topic's shape and rate (30.3), the VUI ids (30.4), whether this WAV plays as is. Known limit: two first-time
uploads of the same line at once would both upload (the two lines are an ask and a human reply apart).

DEMO_CACHE, two paths, each one flag from live: StubConn below (a recording stub pub_sub: code 0 or the play code it is
given, the canned player state STUB_PLAYER marked source "stub", every row cached=True source="stub"), run by
WTDD_SAY_STUB=1 (wtdd/tools/say.py); and WTDD_STATE_FIXTURE (wtdd/dog/session.py), a planted dog state for the dry
screenshots. Needs the dog: 30.1 upload, 30.2 sound, 30.3 player-state shape, 30.4 volume, 30.5 one live ask.
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from unitree_webrtc_connect.constants import AUDIO_API, RTC_TOPIC

from ..config import ROOT
from ..ledger import log, step

TOPIC, PLAYER_TOPIC, VUI_TOPIC = RTC_TOPIC["AUDIO_HUB_REQ"], RTC_TOPIC["AUDIO_HUB_PLAY_STATE"], RTC_TOPIC["VUI"]
LIST, PLAY, PAUSE, PLAY_MODE, UPLOAD = (AUDIO_API[k] for k in ("GET_AUDIO_LIST", "SELECT_START_PLAY", "PAUSE", "GET_PLAY_MODE", "UPLOAD_AUDIO_FILE"))
VOL_SET, VOL_GET = 1003, 1004   # upstream examples/go2/data_channel/vui/vui.py; absent from the wheel; UNVERIFIED
ALLOW = {TOPIC: frozenset({LIST, PLAY, PAUSE, PLAY_MODE, UPLOAD}), VUI_TOPIC: frozenset({VOL_SET, VOL_GET})}   # no megaphone, corpus, delete, LED
CHUNK = 4096          # base64 characters per upload block: webrtc_audiohub.py:148
CHUNK_GAP_S = 0.1     # between blocks: webrtc_audiohub.py:180
PLAYER_WAIT_S = 1.0   # how long a play waits for the player-state topic before reading GET_PLAY_MODE instead
LINES = {"who dis?!": "who-dis", "ok, standing down": "standing-down"}   # the only text say() plays -> its file_name (CUSTOM_NAME)
SAY_DIR, CACHE, SAY_BIN = ROOT / "say", ROOT / "say.json", "/usr/bin/say"
NO_READ_BACK = "no read-back"
# DEMO_CACHE: the player state StubConn emits after a play, marked stub; the live one is whatever the dog publishes.
STUB_PLAYER = {"source": "stub", "state": "playing"}


async def request(body, topic: str, api_id: int, parameter: Any = None) -> tuple[int, dict]:
    """Body._request behind ALLOW: an id outside it raises PermissionError before anything is sent."""
    if api_id not in ALLOW.get(topic, ()):
        raise PermissionError(f"{topic} api_id={api_id} is not in audio.ALLOW")
    return await body._request(topic, api_id, parameter)


def _payload(data: dict) -> Any:
    """The JSON inside a response's data.data. Missing or malformed raises: never {} and never a default."""
    p = (data or {}).get("data")
    if isinstance(p, dict):
        return p
    if not isinstance(p, str) or not p:
        raise ValueError(f"no JSON payload in the response: {str(data)[:160]}")
    return json.loads(p)


def _label(body, r: dict) -> None:
    """DEMO_CACHE: a row written on StubConn says so (cached=True, source="stub"); ledger.append lets these keys win."""
    if getattr(body.conn, "stub", False):
        r["cached"], r["source"] = True, "stub"


async def _next_player(body, n0: int) -> Any:
    """The first rt/audiohub/player/state message after n0, raw, or NO_READ_BACK after PLAYER_WAIT_S (with a WARN)."""
    t0 = time.monotonic()
    while body._player_n == n0 and time.monotonic() - t0 < PLAYER_WAIT_S:
        await asyncio.sleep(0.02)
    if body._player_n > n0:
        return body._player
    log("dog", f"WARN 0 {PLAYER_TOPIC} messages within {PLAYER_WAIT_S}s: {NO_READ_BACK}")
    return NO_READ_BACK


def chunks(wav: bytes, name: str) -> list[dict]:
    """The upload's blocks, the driver's parameters exactly (webrtc_audiohub.py:156-166), passed as dicts."""
    b64, md5 = base64.b64encode(wav).decode(), hashlib.md5(wav).hexdigest()
    blocks = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)]
    return [{"file_name": name, "file_type": "wav", "file_size": len(wav), "current_block_index": i,
             "total_block_number": len(blocks), "block_content": c, "current_block_size": len(c), "file_md5": md5,
             "create_time": int(time.time() * 1000)} for i, c in enumerate(blocks, 1)]


def seconds(wav: Path) -> float:
    with wave.open(str(wav)) as w:
        return round(w.getnframes() / w.getframerate(), 2)


def render(text: str, out: Path) -> Path:
    """The line as the dog will say it: /usr/bin/say to AIFF, then ffmpeg to 44.1 kHz mono 16-bit PCM WAV with a bare
    header (the rate the driver's own upload converts to). A missing program raises; nothing stands in for it."""
    ff = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    out, t0 = Path(out), time.perf_counter()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        aiff = Path(d) / "line.aiff"
        subprocess.run([SAY_BIN, "-o", str(aiff), text], check=True, timeout=30)
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le",
                        "-map_metadata", "-1", "-fflags", "+bitexact", str(out)], check=True, timeout=30)
    log("dog", f"say rendered {out.name}", seconds=seconds(out), bytes=out.stat().st_size, ms=round((time.perf_counter() - t0) * 1000))
    return out


def load_cache(path: Path) -> dict:
    """{text: {name, uuid, md5?, at}}; {} when the file is absent (nothing uploaded from this checkout yet). Corrupt raises."""
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else {}


def save_cache(path: Path, d: dict) -> None:
    Path(path).write_text(json.dumps(d, indent=1) + "\n")


async def audio_list(body) -> list[dict]:
    """GET_AUDIO_LIST: one dog.audio_list row; the items as the dog sends them."""
    with step("dog", "dog.audio_list", "unitree", {}, body.state()) as r:
        _label(body, r)
        code, data = await request(body, TOPIC, LIST, {})
        r["response_or_error"] = data
        if code != 0:
            raise RuntimeError(f"GET_AUDIO_LIST refused by the dog: code={code}")
        items = _payload(data)["audio_list"]
        r["state_after"] = {"n": len(items), "names": [x.get("CUSTOM_NAME") for x in items]}
        if not items:
            log("dog", "WARN the dog lists 0 audio files")
    return items


async def upload(body, wav: Path, name: str) -> dict:
    """UPLOAD_AUDIO_FILE block by block, then GET_AUDIO_LIST inside the same dog.audio_upload row: the upload is done only
    when the dog lists `name`. The first non-zero block code raises, naming the block."""
    raw = Path(wav).read_bytes()
    blocks, md5 = chunks(raw, name), hashlib.md5(raw).hexdigest()
    args = {"file_name": name, "file_size": len(raw), "file_md5": md5, "chunks": len(blocks)}
    with step("dog", "dog.audio_upload", "unitree", args, body.state()) as r:
        _label(body, r)
        if not blocks:
            raise ValueError(f"{wav} is empty: 0 blocks to upload")
        codes = []
        for i, p in enumerate(blocks, 1):
            code, last = await request(body, TOPIC, UPLOAD, p)
            codes.append(code)
            if code != 0:
                raise RuntimeError(f"UPLOAD_AUDIO_FILE block {i}/{len(blocks)} of {name} refused by the dog: code={code}")
            await asyncio.sleep(CHUNK_GAP_S)
        r["response_or_error"] = {"codes": codes, "last": last}
        code, data = await request(body, TOPIC, LIST, {})
        if code != 0:
            raise RuntimeError(f"GET_AUDIO_LIST after the upload refused by the dog: code={code}")
        items = _payload(data)["audio_list"]
        hit = [x for x in items if x.get("CUSTOM_NAME") == name]
        if not hit:
            raise RuntimeError(f"uploaded {len(blocks)} blocks but {name} is not in GET_AUDIO_LIST ({len(items)} items)")
        r["state_after"] = {"listed": True, "uuid": hit[-1]["UNIQUE_ID"], "names": [x.get("CUSTOM_NAME") for x in items]}
    log("dog", f"uploaded {name}", blocks=len(blocks), bytes=len(raw), uuid=hit[-1]["UNIQUE_ID"])
    return {"uuid": hit[-1]["UNIQUE_ID"], "chunks": len(blocks), "md5": md5, "bytes": len(raw)}


async def ensure(body, text: str, known: dict) -> str:
    """The uuid the dog plays `text` by: the cache, else the dog's own list by CUSTOM_NAME, else render (once) and upload."""
    name = LINES[text]
    if (known.get(text) or {}).get("uuid"):
        return known[text]["uuid"]
    hit = [x for x in await audio_list(body) if x.get("CUSTOM_NAME") == name]
    if hit:
        entry = {"name": name, "uuid": hit[-1]["UNIQUE_ID"]}
    else:
        wav = SAY_DIR / f"{name}.wav"
        if not wav.exists():   # off the loop: the render takes about a second and the loop carries the drive's StopMove
            await asyncio.to_thread(render, text, wav)
        up = await upload(body, wav, name)
        entry = {"name": name, "uuid": up["uuid"], "md5": up["md5"]}
    known[text] = {**entry, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return known[text]["uuid"]


async def say(body, text: str, cache: Path | None = None) -> dict:
    """One of LINES on the dog's speaker: one dog.say row (the list and upload rows before it the first time only).
    cache: an explicit path, else CACHE on a live connection and memory only on StubConn (the stub never writes say.json).
    Sets body.say_state either way and returns it; a refusal or failure raises after the row and .say.error are written."""
    stub = getattr(body.conn, "stub", False)
    path = Path(cache) if cache is not None else (None if stub else CACHE)
    code = None
    try:
        with step("dog", "dog.say", "unitree", {"text": text, "via": "audiohub"}, body.state()) as r:
            _label(body, r)
            if text not in LINES:
                raise PermissionError(f"say plays only the two fixed lines {sorted(LINES)}, not {text!r}")
            known = load_cache(path) if path else {}
            uuid = await ensure(body, text, known)
            if path:
                save_cache(path, known)
            r["args"]["uuid"] = uuid
            n0, t0 = body._player_n, time.perf_counter()   # before the send: the player message may beat the ack
            code, data = await request(body, TOPIC, PLAY, {"unique_id": uuid})
            ms = round((time.perf_counter() - t0) * 1000)
            r["response_or_error"] = data
            if code != 0:
                raise RuntimeError(f"SELECT_START_PLAY refused by the dog: code={code}")
            wav = SAY_DIR / f"{LINES[text]}.wav"   # .say at the ack: speaking runs while the line plays, not after the read-back
            body.say_state = {"text": text, "code": 0, "at": time.time(), "ms": ms, "uuid": uuid,
                              "seconds": seconds(wav) if wav.exists() else None, **({"source": "stub"} if stub else {})}
            player = await _next_player(body, n0)
            if player == NO_READ_BACK:
                pc, pd = await request(body, TOPIC, PLAY_MODE, {})   # raw: its payload shape is UNVERIFIED, never parsed
                if pc != 0:
                    log("dog", "WARN GET_PLAY_MODE refused after an accepted play", code=pc)
                r["state_after"] = {"player_state": player, "play_mode": {"code": pc, "data": pd},
                                    "sport": await body.fresh_state()}
            else:
                r["state_after"] = {"player_state": player, "sport": body.state()}
            body.say_state = {**body.say_state, "player_state": player}
    except Exception as e:
        body.say_state = {"text": text, "code": code, "at": time.time(), "error": f"{type(e).__name__}: {e}",
                          **({"source": "stub"} if stub else {})}
        raise
    return dict(body.say_state)


async def pause(body) -> Any:
    """PAUSE: one dog.audio_pause row, the next player state (or "no read-back") as state_after."""
    with step("dog", "dog.audio_pause", "unitree", {}, body.state()) as r:
        _label(body, r)
        n0 = body._player_n
        code, data = await request(body, TOPIC, PAUSE, {})
        r["response_or_error"] = data
        if code != 0:
            raise RuntimeError(f"PAUSE refused by the dog: code={code}")
        r["state_after"] = {"player_state": await _next_player(body, n0)}
    return r["state_after"]


async def volume(body, level: int | None) -> int:
    """VUI volume, one dog.volume row: level 0..10 is set (1003) then read back (1004), and a read-back that differs
    FAILS the row; level None only reads. A level outside 0..10 is refused inside the row before any send."""
    with step("dog", "dog.volume", "unitree", {"level": level}, body.state()) as r:
        _label(body, r)
        sent = None
        if level is not None:
            if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= 10:
                raise ValueError(f"volume must be an int 0..10, got {level!r}")
            code, sent = await request(body, VUI_TOPIC, VOL_SET, {"volume": level})
            if code != 0:
                raise RuntimeError(f"VUI set volume refused by the dog: code={code}")
        code, data = await request(body, VUI_TOPIC, VOL_GET, {})
        r["response_or_error"] = {"set": sent, "get": data}
        if code != 0:
            raise RuntimeError(f"VUI get volume refused by the dog: code={code}")
        got = _payload(data)["volume"]
        r["state_after"] = {"volume": got}
        if level is not None and got != level:
            raise RuntimeError(f"volume set to {level} but the dog reads back {got}")
    return got


async def volume_get(body) -> int:
    return await volume(body, None)


def served(st: dict | None) -> dict | None:
    """GET /dog/state .say: the last play plus age_s and speaking, computed here so the page computes nothing."""
    if st is None:
        return None
    age = round(time.time() - st["at"], 1)
    return {**st, "age_s": age, "speaking": st.get("code") == 0 and "error" not in st and age < (st.get("seconds") or 0)}


def after(text: str, say=None) -> threading.Thread:
    """The hook an ask calls AFTER its chat post returned: `text` is said on its own thread and this returns at once,
    so the speaker never blocks or fails the ask. Non-daemon: a one-shot CLI still finishes the say before it exits.
    say defaults to the `say` tool (the API when one runs, else this process's session). A failure is the dog.say row,
    .say.error on GET /dog/state and one WARN line here; it is never raised into the ask."""
    def go() -> None:
        try:
            if say is not None:
                say(text)
            else:
                from .. import tools
                tools.call("say", text=text)
        except Exception as e:  # noqa: BLE001  (the row and .say.error carry it; the ask already landed)
            log("dog", "WARN say FAILED after the post (the ask landed)", text=repr(text), err=f"{type(e).__name__}: {str(e)[:160]}")

    th = threading.Thread(target=go, name=f"say-{LINES.get(text, 'line')}")
    th.start()
    return th


# DEMO_CACHE: the recording stub. It records every request, answers code 0 (the play with the code it is given),
# lists what was uploaded, and emits STUB_PLAYER after a play; every row it touches is cached=True source="stub". It
# runs the whole say with no dog: WTDD_SAY_STUB=1 (wtdd/tools/say.py) and the tests. Unset the flag and the same call
# goes to the dog. An id it has no answer for raises; it never answers a silent 0.
class StubPubSub:
    def __init__(self, play_code: int = 0, player: bool = True) -> None:
        self.play_code, self.player, self.volume = play_code, player, 5
        self.sent: list[tuple[str, dict]] = []
        self.listed: list[dict] = []
        self.subscriptions: dict[str, Any] = {}

    def subscribe(self, topic: str, callback=None) -> None:
        self.subscriptions[topic] = callback

    async def publish_request_new(self, topic: str, options: dict) -> dict:
        self.sent.append((topic, options))
        api, p = options["api_id"], options.get("parameter")
        p, code, out = json.loads(p) if isinstance(p, str) else p, 0, None
        if (topic, api) == (TOPIC, UPLOAD):
            if p["current_block_index"] == p["total_block_number"]:
                self.listed.append({"CUSTOM_NAME": p["file_name"], "UNIQUE_ID": f"stub-{p['file_name']}"})
        elif (topic, api) == (TOPIC, LIST):
            out = {"audio_list": self.listed}
        elif (topic, api) == (TOPIC, PLAY):
            code, cb = self.play_code, self.subscriptions.get(PLAYER_TOPIC)
            if code == 0 and self.player and cb:
                asyncio.get_running_loop().call_soon(cb, {"topic": PLAYER_TOPIC, "data": STUB_PLAYER})
        elif (topic, api) == (TOPIC, PLAY_MODE):
            out = {"play_mode": "stub"}
        elif (topic, api) == (VUI_TOPIC, VOL_SET):
            self.volume = p["volume"]
        elif (topic, api) == (VUI_TOPIC, VOL_GET):
            out = {"volume": self.volume}
        elif (topic, api) != (TOPIC, PAUSE):
            raise ValueError(f"stub: no canned answer for {topic} api_id={api}")
        return {"type": "res", "topic": topic, "data": {"header": {"identity": {"id": len(self.sent), "api_id": api},
                                                                   "status": {"code": code}},
                                                        "data": json.dumps(out) if out is not None else ""}}


class StubConn:
    """DEMO_CACHE: stands in for UnitreeWebRTCConnection (only .datachannel.pub_sub); `stub` labels every row."""
    stub = True

    def __init__(self, play_code: int = 0, player: bool = True) -> None:
        self.datachannel = SimpleNamespace(pub_sub=StubPubSub(play_code, player))


def stub_say(text: str, level: int | None = None) -> dict:
    """DEMO_CACHE: WTDD_SAY_STUB=1 runs the whole say (render, list, upload, play, read-back; the volume first when
    given) on StubConn: no dog, no API, every row cached=True source="stub", say.json never written. Unset the flag and
    `python -m wtdd say` sends the same requests to the dog's own speaker."""
    from .body import Body
    b = Body()
    b.conn = StubConn()
    b.conn.datachannel.pub_sub.subscribe(PLAYER_TOPIC, b._on_player)

    async def go() -> dict:
        if level is not None:
            await volume(b, level)
        return await say(b, text)
    return asyncio.run(go())
