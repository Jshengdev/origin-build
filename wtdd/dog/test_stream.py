"""The dog's live view as one stream, offline. Run: python -m unittest wtdd.dog.test_stream -v

Checks, through the real Body._drain, the real DogSession loop and the real API handler in a thread:
  - Body.jpeg_cached() -> {bytes, sha, n, w, h, at}: one PIL encode per frame number however many readers (the
    encodes are counted on PIL's Image.save), a repeat read of the same n costs nothing, a new n costs one encode;
  - GET /dog/frame.jpg carries X-Frame-Sha (sha256 of the bytes served) and X-Frame-N; eight readers of one frame at once
    cost one encode;
  - GET /dog/stream.mjpg is multipart/x-mixed-replace: the current frame on connect, then one part per new frame number,
    none for a repeat, each part with the same two headers; two viewers and frame.jpg share one encode per frame;
  - the stall rule: no new frame for FRAME_STALE_S ends the response (never a stale image), /dog/frame.jpg is 503 with
    the error, a new stream request is 503, /dog/state says video.stale; the next frame brings the stream back;
  - a stall that ended a stream is counted (video.gaps) when the frames resume, and the page keys the stream URL on it,
    so a stall that no 1 s poll saw still reopens the stream; a channel with no first frame says so, not a bogus age;
  - GET /dog/state gains video {fps (from _fr_n deltas over the last second), age_ms, bytes, w, h, frames, sha, stale};
  - GET /watch gains frames_behind (the cache's newest n minus the n the detector boxed), None when unknown, never 0;
  - wtdd/watch.py records frame_sha and frame_n from the headers it pulled; a --source file writes neither;
  - the DEMO_CACHE stub (WTDD_VIDEO_STUB=<fps>, the dry screenshots' body) cycles a 1280x720 frame and says `stub`;
  - no ledger row for any of it (reads, as today); the page takes the stream and names the stall.
Stubbed, and why: the dog. A real Body with no connection gets its frames from a fake track whose recv() hands over
synthetic av.VideoFrames the test pushes (Body._drain runs unchanged on the session loop); _video is set so _video_on
never reaches for a conn. watch.py's detector and cv2 are fakes in sys.modules (no weights, and cv2 must never load in a
process that has av). A scratch ledger and a scratch ROOT for watch.json keep the real checkout untouched.
UNVERIFIED on the dog: the delivered fps through one multipart connection, the codec, the encode cost on the dog loop."""
from __future__ import annotations
import asyncio
import hashlib
import http.client
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-stream-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_VIDEO_STUB"] = ""   # the DEMO_CACHE stub body must never replace this test's body (an empty key wins over .env)
os.environ["UNITREE_ROBOT_IP"] = ""  # and no request here may ever reach a real dog: an unset IP fails the probe before any connect

import av  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from wtdd import api, config, ledger, watch  # noqa: E402
from wtdd.dog import body as B  # noqa: E402
from wtdd.dog.session import DogSession  # noqa: E402

W, H = 320, 180
ENCODES: list[str] = []   # one entry per PIL Image.save, the encode being counted
_real_save = Image.Image.save
SRV: ThreadingHTTPServer | None = None
_ROOT = api.ROOT


def _counting_save(self, *a, **k):
    ENCODES.append(threading.current_thread().name)
    return _real_save(self, *a, **k)


def setUpModule():
    global SRV
    Image.Image.save = _counting_save
    (_TMP / "root").mkdir(exist_ok=True)
    api.ROOT = _TMP / "root"   # GET /watch reads <ROOT>/watch.json: a scratch one, never the live detector's
    SRV = ThreadingHTTPServer(("127.0.0.1", 0), api.H)   # an ephemeral port: 7936 is the item's browser check
    threading.Thread(target=SRV.serve_forever, daemon=True).start()


def tearDownModule():
    Image.Image.save = _real_save
    api.ROOT = _ROOT
    DogSession._inst = None
    if SRV:
        SRV.shutdown()


def synth(n: int, w: int = W, h: int = H) -> av.VideoFrame:
    """A synthetic decoded frame whose shade and bar position depend on n, so every n encodes to different bytes."""
    a = np.full((h, w, 3), (n * 37) % 256, np.uint8)
    x = (n * 23) % (w - 20)
    a[h // 4:3 * h // 4, x:x + 20] = (220, 30, 30)
    return av.VideoFrame.from_ndarray(a, format="rgb24")


def get(path: str) -> tuple[int, dict, bytes]:
    c = http.client.HTTPConnection("127.0.0.1", SRV.server_address[1], timeout=10)
    c.request("GET", path)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def wait_for(cond, timeout: float, what: str) -> None:
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(0.01)


def _headers(f) -> dict:
    h = {}
    while True:
        line = f.readline()
        if line in (b"\r\n", b"\n", b""):
            return h
        k, _, v = line.decode().partition(":")
        h[k.strip().lower()] = v.strip()


class Track:
    """Stands in for aiortc's RemoteStreamTrack: recv() awaits the next frame the test pushes."""

    def __init__(self, loop):
        self.loop, self.q = loop, asyncio.Queue()

    async def recv(self):
        return await self.q.get()

    def push(self, f) -> None:
        self.loop.call_soon_threadsafe(self.q.put_nowait, f)


class Reader:
    """One viewer of GET /dog/stream.mjpg on a raw socket: every part's headers and bytes, and when the server ended it."""

    def __init__(self):
        self.sock = socket.create_connection(("127.0.0.1", SRV.server_address[1]), timeout=15)
        self.sock.sendall(b"GET /dog/stream.mjpg HTTP/1.0\r\nHost: test\r\n\r\n")
        self.f = self.sock.makefile("rb")
        self.status = int(self.f.readline().split()[1])
        self.head = _headers(self.f)
        self.parts: list[tuple[dict, bytes]] = []
        self.ended: float | None = None
        self.error: Exception | None = None
        ctype = self.head.get("content-type", "")
        if self.status == 200 and ctype.startswith("multipart/x-mixed-replace"):
            self.boundary = b"--" + ctype.split("boundary=", 1)[1].strip().strip('"').encode()
            threading.Thread(target=self._read, daemon=True).start()
        else:
            self.body = self.f.read()
            self.ended = time.monotonic()

    def _read(self) -> None:
        try:
            while True:
                line = self.f.readline()
                if not line or line.strip() == self.boundary + b"--":
                    break   # the server ended the response
                if not line.strip():
                    continue
                if line.strip() != self.boundary:
                    raise AssertionError(f"expected the boundary, got {line[:60]!r}")
                h = _headers(self.f)
                self.parts.append((h, self.f.read(int(h["content-length"]))))
        except Exception as e:  # noqa: BLE001  (kept and asserted on by the test)
            self.error = e
        finally:
            self.ended = time.monotonic()

    def ns(self) -> list[str]:
        return [h.get("x-frame-n") for h, _ in self.parts]

    def close(self) -> None:
        self.sock.close()


class Rig(unittest.TestCase):
    """A fresh session per test whose body is a real Body fed by a fake track through its own _drain."""

    def setUp(self):
        ENCODES.clear()
        self.s = DogSession()
        self.b = B.Body()
        self.b._video, self.b._vid_t0 = True, time.monotonic()   # the channel counts as on: there is no conn to switch
        self.s.body = self.b
        DogSession._inst = self.s
        self.track = Track(self.s.loop)
        self.drain = asyncio.run_coroutine_threadsafe(self.b._drain(self.track), self.s.loop)
        self.n = 0
        self.rows0 = len(ledger.rows())

    def tearDown(self):
        self.drain.cancel()
        DogSession._inst = None

    def push(self, k: int = 1, fps: float | None = None) -> None:
        """k new frames through the real _drain (at `fps` if given); returns once the body has counted them."""
        for _ in range(k):
            self.n += 1
            self.track.push(synth(self.n))
            if fps:
                time.sleep(1 / fps)
        wait_for(lambda: self.b._fr_n >= self.n, 2, f"the body to count frame {self.n}")

    def no_rows(self) -> None:
        self.assertEqual(len(ledger.rows()), self.rows0, "a read of the live view wrote a ledger row")


class Cache(Rig):
    def test_one_encode_per_frame_number(self):
        self.push()
        c = self.s.run(self.b.jpeg_cached())
        self.assertLessEqual({"bytes", "sha", "n", "w", "h", "at"}, set(c))
        self.assertEqual(c["sha"], hashlib.sha256(c["bytes"]).hexdigest())
        self.assertEqual((c["n"], c["w"], c["h"]), (1, W, H))
        self.assertTrue(c["bytes"].startswith(b"\xff\xd8"), "not a JPEG")
        again = self.s.run(self.b.jpeg_cached())
        self.assertEqual((again["n"], again["sha"]), (1, c["sha"]))
        self.assertEqual(len(ENCODES), 1, "a repeat read of frame 1 encoded again")
        self.push()
        new = self.s.run(self.b.jpeg_cached())
        self.assertEqual(new["n"], 2)
        self.assertNotEqual(new["sha"], c["sha"])
        self.assertEqual(len(ENCODES), 2)
        self.no_rows()

    def test_no_first_frame_is_named_not_aged(self):
        # _video_on timed out: the channel is on and no frame ever came. The page's FAILED tile shows this error.
        with self.assertRaisesRegex(RuntimeError, r"no video frame yet \(frames=0\)"):
            self.s.run(self.b.jpeg_cached())
        st, _, data = get("/dog/frame.jpg")
        self.assertEqual(st, 503)
        self.assertIn("no video frame yet", json.loads(data)["error"], "a missing first frame was reported as an age")
        self.assertEqual(len(ENCODES), 0)
        self.no_rows()


class FrameJpeg(Rig):
    def test_headers_and_eight_readers_one_encode(self):
        self.push()
        got: list = []
        ts = [threading.Thread(target=lambda: got.append(get("/dog/frame.jpg"))) for _ in range(8)]
        [t.start() for t in ts]
        [t.join(15) for t in ts]
        self.assertEqual([st for st, _, _ in got], [200] * 8, [d[:120] for _, _, d in got])
        self.assertEqual(len(ENCODES), 1, f"8 readers of one frame cost {len(ENCODES)} encodes")
        for _, h, data in got:
            self.assertEqual(h.get("content-type"), "image/jpeg")
            self.assertEqual(h.get("x-frame-sha"), hashlib.sha256(data).hexdigest())
            self.assertEqual(h.get("x-frame-n"), "1")
        self.push()
        st, h, data = get("/dog/frame.jpg")
        self.assertEqual((st, h.get("x-frame-n")), (200, "2"))
        self.assertEqual(h.get("x-frame-sha"), hashlib.sha256(data).hexdigest())
        self.assertEqual(len(ENCODES), 2)
        self.no_rows()


class Stream(Rig):
    def test_each_new_frame_is_one_part_a_repeat_is_none(self):
        self.push()
        a, b = Reader(), Reader()
        try:
            self.assertEqual((a.status, b.status), (200, 200), getattr(a, "body", b"")[:200])
            wait_for(lambda: len(a.parts) == 1 and len(b.parts) == 1, 3, "the current frame on connect")
            for k in (2, 3):
                self.push()
                wait_for(lambda: len(a.parts) == k and len(b.parts) == k, 3, f"part {k} on both viewers")
            self.assertEqual(a.ns(), ["1", "2", "3"])
            self.assertEqual(b.ns(), ["1", "2", "3"])
            for h, data in a.parts + b.parts:
                self.assertEqual(h.get("content-type"), "image/jpeg")
                self.assertEqual(h.get("x-frame-sha"), hashlib.sha256(data).hexdigest())
            self.assertEqual([h["x-frame-sha"] for h, _ in a.parts], [h["x-frame-sha"] for h, _ in b.parts])
            st, h, _ = get("/dog/frame.jpg")
            self.assertEqual((st, h.get("x-frame-n"), h.get("x-frame-sha")), (200, "3", a.parts[-1][0]["x-frame-sha"]))
            self.assertEqual(len(ENCODES), 3, f"3 frames to two viewers and frame.jpg cost {len(ENCODES)} encodes")
            time.sleep(0.6)   # no new frame, not yet stale: a repeat is no part and the stream stays open
            self.assertEqual((len(a.parts), len(b.parts)), (3, 3), "a repeated frame number was pushed again")
            self.assertIsNone(a.ended, "the stream ended while the video was fresh")
            self.no_rows()
        finally:
            a.close()
            b.close()

    def test_stall_ends_the_stream_and_frame_jpg_is_503(self):
        self.push()
        last = time.monotonic()
        a = Reader()
        try:
            self.assertEqual(a.status, 200, getattr(a, "body", b"")[:200])
            wait_for(lambda: len(a.parts) == 1, 3, "the current frame on connect")
            wait_for(lambda: a.ended is not None, B.FRAME_STALE_S + 2, "the handler to end a stalled stream")
            self.assertIsNone(a.error, f"the stream did not end cleanly: {a.error!r}")
            self.assertGreaterEqual(a.ended - last, B.FRAME_STALE_S * 0.9, "the stream ended before the frame was stale")
            self.assertEqual(len(a.parts), 1, "a stale frame was pushed")
        finally:
            a.close()
        st, _, data = get("/dog/frame.jpg")
        self.assertEqual(st, 503)
        self.assertIn("stale", json.loads(data)["error"])
        again = Reader()
        again.close()
        self.assertEqual(again.status, 503, "a stalled video must not open a stream")
        self.assertIn("stale", json.loads(again.body)["error"])
        st, _, data = get("/dog/state")
        self.assertEqual(st, 200)
        v = json.loads(data)["video"]
        self.assertIs(v["stale"], True)
        self.assertGreaterEqual(v["age_ms"], B.FRAME_STALE_S * 1000)
        self.push()   # the dog is back: the next request streams again
        back = Reader()
        try:
            self.assertEqual(back.status, 200)
            wait_for(lambda: len(back.parts) == 1, 3, "the stream back after the stall")
            self.assertEqual(back.ns(), ["2"])
        finally:
            back.close()
        self.no_rows()


class Gaps(Rig):
    def test_a_stall_that_ended_a_stream_is_counted_when_the_frames_resume(self):
        self.push()
        a = Reader()
        try:
            self.assertEqual(a.status, 200, getattr(a, "body", b"")[:200])
            self.push(3, fps=14)   # frames at the dog's rate: no gap
            self.assertEqual(json.loads(get("/dog/state")[2])["video"]["gaps"], 0, "frames at 14 fps were counted as a gap")
            wait_for(lambda: a.ended is not None, B.FRAME_STALE_S + 2, "the handler to end a stalled stream")
        finally:
            a.close()
        # No /dog/state landed during the stall, so a page never saw video.stale: the count is what reopens its stream.
        self.push()
        v = json.loads(get("/dog/state")[2])["video"]
        self.assertEqual((v["gaps"], v["stale"]), (1, False), "a stall that ended a stream was not counted")
        self.push(3, fps=14)
        self.assertEqual(json.loads(get("/dog/state")[2])["video"]["gaps"], 1, "frames after the stall were counted again")
        self.no_rows()


class State(Rig):
    def test_video_on_dog_state_with_fps_from_frame_deltas(self):
        self.push(21, fps=14)
        st, h, data = get("/dog/frame.jpg")
        self.assertEqual(st, 200)
        st, _, raw = get("/dog/state")
        self.assertEqual(st, 200, raw[:200])
        v = json.loads(raw)["video"]
        self.assertLessEqual({"fps", "age_ms", "bytes", "w", "h", "frames", "sha", "stale"}, set(v))
        self.assertTrue(10 <= v["fps"] <= 16, f"fps {v['fps']} from 14 frames a second")
        self.assertEqual((v["frames"], v["w"], v["h"]), (21, W, H))
        self.assertEqual((v["sha"], v["bytes"]), (h["x-frame-sha"], len(data)))
        self.assertLess(v["age_ms"], B.FRAME_STALE_S * 1000)
        self.assertIs(v["stale"], False)
        self.no_rows()

    def test_no_dog_no_video(self):
        DogSession._inst = DogSession()
        st, _, raw = get("/dog/state")
        self.assertEqual(st, 200, raw[:200])
        self.assertIsNone(json.loads(raw)["video"])


class Watch(Rig):
    def plant(self, d: dict) -> None:
        (api.ROOT / "watch.json").write_text(json.dumps(d))

    def test_frames_behind_from_the_frame_numbers(self):
        self.push(5)
        self.assertEqual(get("/dog/frame.jpg")[0], 200)
        box = {"name": "person", "conf": 0.87, "xyxy": [10, 20, 90, 160]}
        self.plant({"t": time.time(), "boxes": [box], "classes": {"person": 1}, "frame_sha": "a" * 64, "frame_n": 3})
        d = json.loads(get("/watch")[2])
        self.assertEqual(d["frames_behind"], 2)
        self.assertEqual(d["frame_sha"], "a" * 64)
        self.plant({"t": time.time(), "boxes": [box], "classes": {"person": 1}})   # a detector from before this change
        self.assertIsNone(json.loads(get("/watch")[2])["frames_behind"], "an unknown lag must not be served as a number")
        DogSession._inst = DogSession()   # no dog: nothing to be behind
        self.plant({"t": time.time(), "boxes": [], "frame_sha": "a" * 64, "frame_n": 3})
        self.assertIsNone(json.loads(get("/watch")[2])["frames_behind"])

    def test_watch_records_the_frame_it_boxed(self):
        self.push(2)
        out = _TMP / "watch-live.json"
        fake_cv2 = types.SimpleNamespace(IMWRITE_JPEG_QUALITY=1, imwrite=lambda p, img, params: Path(p).write_bytes(b"boxed") > 0)
        fake_yolo = types.SimpleNamespace(YOLO=lambda name: object())
        boxes = [{"name": "cup", "conf": 0.5, "xyxy": [1, 2, 30, 40]}]
        with mock.patch.dict(sys.modules, {"cv2": fake_cv2, "ultralytics": fake_yolo}), \
                mock.patch.object(watch, "detect", lambda model, img: (boxes, None, 7)), \
                mock.patch.object(watch, "WATCH", out), mock.patch.object(watch, "OUT", _TMP / "watch.jpg"), \
                redirect_stdout(io.StringIO()):
            url = f"http://127.0.0.1:{SRV.server_address[1]}/dog/frame.jpg"
            self.assertEqual(watch.main(["--source", url, "--once"]), 0)
            d = json.loads(out.read_text())
            st, h, _ = get("/dog/frame.jpg")
            self.assertEqual((d.get("frame_sha"), d.get("frame_n")), (h["x-frame-sha"], 2))
            f = _TMP / "frame.jpg"
            buf = io.BytesIO()
            synth(99).to_image().save(buf, "JPEG")
            f.write_bytes(buf.getvalue())
            self.assertEqual(watch.main(["--source", str(f), "--once"]), 0)   # a file source: unchanged, no frame to name
            d = json.loads(out.read_text())
            self.assertEqual(d["source"], str(f))
            self.assertIsNone(d.get("frame_sha"))
            self.assertIsNone(d.get("frame_n"))
        self.no_rows()


class Stub(unittest.TestCase):
    def test_demo_cache_stub_cycles_and_says_so(self):
        with mock.patch.dict(os.environ, {"WTDD_VIDEO_STUB": "14"}):
            s = DogSession()
        self.assertIsNotNone(s.body, "WTDD_VIDEO_STUB=14 did not install the stub body at construction")
        DogSession._inst = s
        try:
            wait_for(lambda: s.body._fr_n >= 5, 3, "the stub body to cycle frames")
            self.assertEqual(get("/dog/frame.jpg")[0], 200)
            v = json.loads(get("/dog/state")[2])["video"]
            self.assertEqual((v["source"], v["w"], v["h"]), ("stub", 1280, 720))
        finally:
            DogSession._inst = None

    def test_a_dog_command_under_the_stub_is_refused_by_name(self):
        with mock.patch.dict(os.environ, {"WTDD_VIDEO_STUB": "14"}):
            s = DogSession()
        n0 = len(ledger.rows())
        with self.assertRaises(Exception) as e:
            s.cmd("Sit")
        self.assertIn("DEMO_CACHE video stub", str(e.exception), "a command under the stub body failed without naming the stub")
        new = ledger.rows()[n0:]
        self.assertTrue(new, "a refused command under the stub wrote no row")
        for r in new:
            self.assertIn("DEMO_CACHE video stub", r["response_or_error"] or "", f"the {r['tool']} row's error does not name the stub")


class Page(unittest.TestCase):
    def test_the_page_takes_the_stream_and_names_the_stall(self):
        page = (config.ROOT / "ui" / "index.html").read_text()
        for said in ("// 29 · live-stream · start", "/dog/stream.mjpg", "stream stalled", "video FAILED", "frames behind",
                     "fps ·", "frame_sha"):
            self.assertTrue(said in page, f"ui/index.html does not say {said!r}")
        self.assertFalse("onError=${() => next(2000)}" in page, "the silent retry is still there (ui/index.html)")

    def test_a_counted_stall_reopens_the_stream(self):
        page = (config.ROOT / "ui" / "index.html").read_text()
        srcs = [line for line in page.splitlines() if "/dog/stream.mjpg?e=" in line]
        self.assertTrue(srcs, "ui/index.html has no /dog/stream.mjpg?e= src")
        for line in srcs:
            self.assertIn("gaps", line, "the stream URL is not keyed on video.gaps: a stall no poll saw leaves the frozen frame up")


if __name__ == "__main__":
    unittest.main()
