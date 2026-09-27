"""A fixed camera in the same queue, offline. Run: python -m unittest wtdd.cam.test_cam -v
Checks, through the real API handler in a thread: a fixture frame POSTed raw (image/jpeg) to /cam/<id>/frame lands as
a file, is detected, writes one cam.frame and one cam.detect row (both carrying shift_id), is served back to the remote
(GET /cam, GET /cam/<id>/frame.jpg); a person box while the intruder watch is armed is handed to the dispatch tool
(item 18: tools.call("dispatch", cam, trigger, file=<the sighting's boxed copy, cams/<id>.<epoch>.boxed.jpg>) on a
thread, so a later frame never reaches the ask; wtdd/test_dispatch.py tests what it does), not when disarmed, and not
twice inside the
cooldown; garbage bytes and a failed detector are FAILED rows and error responses, never hidden; the map names the
camera; the client posts a file source once and reports a dead server loud; cv2 never loads in the API process.
Stubbed, and why: the detector subprocess (yolo11n.pt is gitignored and downloads on first run; a unit test never
touches the network) is replaced by wtdd/cam/fixtures/detect.json; the chat send and the second detector run inside
intruder_alarm are fakes (no osascript, no weights). The real subprocess handshake runs only when yolo11n.pt sits at
the repo root (LiveDetector; skipped otherwise, and it says so). A scratch ledger, memory.db, cams dir and ROOT (for
pending.json and intruder.on) keep a running listener in the real checkout from ever seeing a fixture question."""
from __future__ import annotations
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-cam-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
os.environ["WTDD_CAMS"] = str(_TMP / "cams")
os.environ["WTDD_SHIFT"] = "2026-09-26-test"

from wtdd import api, cam, config, ledger  # noqa: E402
from wtdd.tools import chat_post, dog_say  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
FRAME = (FIX / "frame.jpg").read_bytes()
DETECT = json.loads((FIX / "detect.json").read_text())
CAMS = Path(os.environ["WTDD_CAMS"])
SHIFT = os.environ["WTDD_SHIFT"]
SRV: ThreadingHTTPServer | None = None


def setUpModule():
    global SRV
    SRV = ThreadingHTTPServer(("127.0.0.1", 0), api.H)   # an ephemeral port: 7807 is the item's browser check, not this test
    threading.Thread(target=SRV.serve_forever, daemon=True).start()


def tearDownModule():
    if SRV:
        SRV.shutdown()


def url() -> str:
    return f"http://127.0.0.1:{SRV.server_address[1]}"


def req(method: str, path: str, body: bytes | None = None, ctype: str = "image/jpeg") -> tuple[int, str, bytes]:
    c = http.client.HTTPConnection("127.0.0.1", SRV.server_address[1], timeout=30)
    c.request(method, path, body=body, headers={"Content-Type": ctype} if body is not None else {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, r.getheader("Content-Type") or "", data


def rows_since(n0: int, tool: str) -> list[dict]:
    return [r for r in ledger.rows()[n0:] if r.get("tool") == tool]


class Case(unittest.TestCase):
    def setUp(self):
        self.calls: list[tuple[bytes, str]] = []   # (the frame bytes the detector was given, the boxed path it was asked for)

        def fake_detect(frame, out):
            self.calls.append((Path(frame).read_bytes(), str(out)))
            return {**DETECT, "file": str(out)}
        self.detector = mock.patch.object(cam, "detect_file", fake_detect)
        self.detector.start()
        self.addCleanup(self.detector.stop)
        disarmed = mock.patch.object(cam, "ARMED", _TMP / "never-armed")   # the checkout's intruder.on may be armed; only Person arms
        disarmed.start()
        self.addCleanup(disarmed.stop)

    def tearDown(self):
        self.assertNotIn("cv2", sys.modules, "cv2 loaded in the API process (wtdd/watch.py: it never does; its ffmpeg clashes with PyAV's)")
        self.assertNotIn("ultralytics", sys.modules, "ultralytics loaded in the API process")


class Frame(Case):
    def test_frame_posted_detected_rows_written_served(self):
        n0 = len(ledger.rows())
        status, _, data = req("POST", "/cam/lap1/frame", FRAME)
        self.assertEqual(status, 200, data[:300])
        r = json.loads(data)
        self.assertTrue(r["ok"])
        self.assertEqual(r["cam"], "lap1")
        self.assertEqual(r["detect"]["classes"], {"person": 1})
        self.assertEqual(r["detect"]["boxes"], DETECT["boxes"])
        self.assertEqual(r["frame"]["bytes"], len(FRAME))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], FRAME, "the detector must see the exact bytes that were posted")
        self.assertEqual((CAMS / "lap1.jpg").read_bytes(), FRAME)
        frames, detects = rows_since(n0, "cam.frame"), rows_since(n0, "cam.detect")
        self.assertEqual(len(frames), 1, [x["tool"] for x in ledger.rows()[n0:]])
        self.assertEqual(len(detects), 1)
        f, d = frames[0], detects[0]
        self.assertTrue(f["ok"])
        self.assertEqual(f["args"]["cam"], "lap1")
        self.assertEqual(f["args"]["shift_id"], SHIFT)
        self.assertEqual(f["args"]["bytes"], len(FRAME))
        self.assertEqual((f["cached"], f["source"]), (False, "live"))
        self.assertTrue(d["ok"])
        self.assertEqual(d["args"]["cam"], "lap1")
        self.assertEqual(d["args"]["shift_id"], SHIFT)
        self.assertEqual(d["args"]["classes"], {"person": 1})
        self.assertEqual(d["args"]["boxes"], DETECT["boxes"])
        self.assertIsInstance(d["latency_ms"], int)
        self.assertLess(ledger.rows().index(f), ledger.rows().index(d), "the frame row precedes its detection row")
        status, ctype, data = req("GET", "/cam")
        self.assertEqual(status, 200)
        j = json.loads(data)
        self.assertEqual(j["lap1"]["classes"], {"person": 1})
        self.assertEqual(j["lap1"]["boxes"], DETECT["boxes"])
        self.assertEqual(j["lap1"]["n"], 1)
        self.assertIsInstance(j["lap1"]["age_ms"], int)
        status, ctype, data = req("GET", "/cam/lap1/frame.jpg")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("image/jpeg"), ctype)
        self.assertEqual(data, FRAME)
        status, _, _ = req("GET", "/cam/nope/frame.jpg")
        self.assertEqual(status, 404)

    def test_not_a_jpeg_is_refused_with_a_failed_row(self):
        n0 = len(ledger.rows())
        status, _, data = req("POST", "/cam/lap1/frame", b"not a jpeg at all")
        self.assertEqual(status, 400, data[:300])
        r = json.loads(data)
        self.assertFalse(r["ok"])
        self.assertIn("jpeg", r["error"].lower())
        self.assertEqual(self.calls, [], "no detector run on garbage")
        frames = rows_since(n0, "cam.frame")
        self.assertEqual(len(frames), 1)
        self.assertFalse(frames[0]["ok"])
        self.assertIn("jpeg", (frames[0]["response_or_error"] or "").lower())
        self.assertEqual(rows_since(n0, "cam.detect"), [])
        status, _, data = req("POST", "/cam/a%20b/frame", FRAME)   # the id becomes a file name: only [a-z0-9_-]
        self.assertEqual(status, 400, data[:300])

    def test_detector_failure_is_a_failed_row_and_shown(self):
        def broken(frame, out):
            raise RuntimeError("detector rc=1: no weights here")
        with mock.patch.object(cam, "detect_file", broken):
            n0 = len(ledger.rows())
            status, _, data = req("POST", "/cam/lap1/frame", FRAME)
        self.assertEqual(status, 500, data[:300])
        r = json.loads(data)
        self.assertFalse(r["ok"])
        self.assertIn("detector rc=1", r["error"])
        frames, detects = rows_since(n0, "cam.frame"), rows_since(n0, "cam.detect")
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0]["ok"], "the frame did land; only the detection failed")
        self.assertEqual(len(detects), 1)
        self.assertFalse(detects[0]["ok"])
        self.assertIn("detector rc=1", detects[0]["response_or_error"])
        status, _, data = req("GET", "/cam")
        self.assertEqual(status, 200)
        self.assertIn("detector rc=1", json.loads(data)["lap1"]["error"], "the remote shows the failure, not the last good boxes")

    def test_map_names_the_camera(self):
        m = json.loads((config.ROOT / "ui" / "map.json").read_text())
        cams = m["cameras"]
        self.assertIsInstance(cams, list)
        self.assertIn("lap1", [c["id"] for c in cams], "the demo's one laptop camera is on the map (08 reads this key)")
        zones = {z["name"] for z in m["zones"]}
        for c in cams:
            self.assertEqual(set(c) & {"id", "label", "pt", "zone"}, {"id", "label", "pt", "zone"}, c)
            self.assertIn(c["zone"], zones)
            x, y = c["pt"]
            self.assertTrue(0 <= x <= 1060 and 0 <= y <= 1540, c)


class Person(Case):
    """A person box at the camera while the intruder watch is armed: handed to dispatch on a thread, once per cooldown."""

    def setUp(self):
        super().setUp()
        self.posts: list[dict] = []

        def fake_post(text="", file=None, trigger=None):
            self.posts.append({"text": text, "file": file, "trigger": trigger})
            return {"guid": f"fake-{len(self.posts)}", "rowid": len(self.posts), "ts": "2026-09-26T00:00:00"}

        def fake_boxed(file):   # intruder_alarm boxes the frame it posts; here the detector has no weights
            return {"file": file.rsplit(".", 1)[0] + "-boxed.jpg", "classes": {"person": 1}, "n": 1, "ms": 1}

        def boxing_detect(frame, out):   # the real detector writes its boxed copy to `out`; this one marks the frame's bytes
            Path(out).write_bytes(b"boxed:" + Path(frame).read_bytes())
            return {**DETECT, "file": str(out)}
        for p in (mock.patch.object(chat_post, "run", fake_post), mock.patch.object(dog_say, "boxed", fake_boxed),
                  mock.patch.object(config, "ROOT", _TMP), mock.patch.object(cam, "ARMED", _TMP / "intruder.on"),
                  mock.patch.object(cam, "detect_file", boxing_detect), mock.patch.dict(cam._last, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        (_TMP / "intruder.on").unlink(missing_ok=True)
        (_TMP / "pending.json").unlink(missing_ok=True)

    def test_person_goes_to_dispatch_once_per_cooldown(self):
        from wtdd import tools
        n0, calls, called = len(ledger.rows()), [], threading.Event()

        def fake_call(tool, **kw):   # the dispatch tool itself is wtdd/test_dispatch.py's; here only the hand-off
            calls.append((tool, kw))
            called.set()
            return {"phase": "asked"}
        with mock.patch.object(tools, "call", fake_call):
            status, _, data = req("POST", "/cam/lap1/frame", FRAME)   # disarmed: a person is a row, not a dispatch
            self.assertEqual(status, 200, data[:300])
            r = json.loads(data)
            self.assertEqual(r["person"]["asked"], False)
            self.assertIn("not armed", r["person"]["why"])
            self.assertFalse(called.wait(0.3))

            (_TMP / "intruder.on").write_text("2026-09-26T00:00:00\n")
            status, _, data = req("POST", "/cam/lap1/frame", FRAME)
            self.assertEqual(status, 200, data[:300])
            r = json.loads(data)
            self.assertTrue(r["ok"])
            self.assertEqual(r["person"]["dispatched"], True)
            self.assertTrue(r["person"]["trigger"].startswith("cam:lap1:"), r["person"])
            self.assertTrue(called.wait(5), "the dispatch tool was never called")
            key = r["person"]["trigger"]
            self.assertEqual(calls, [("dispatch", {"cam": "lap1", "trigger": key, "file": str(CAMS / f"lap1.{key.rsplit(':', 1)[1]}.boxed.jpg")})],
                             "the sighting's own boxed copy, kept under its trigger")

            status, _, data = req("POST", "/cam/lap1/frame", FRAME)   # still in view: no second dispatch inside the cooldown
            self.assertEqual(status, 200, data[:300])
            r = json.loads(data)
            self.assertEqual(r["person"]["asked"], False)
            self.assertTrue(r["person"]["why"].startswith("cooldown"), r["person"])
            time.sleep(0.3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.posts, [], "the camera posts nothing itself: dispatch asks")
        self.assertFalse((_TMP / "pending.json").exists())
        self.assertEqual(len(rows_since(n0, "intruder.alarm")), 0, "never straight to intruder_alarm")
        self.assertEqual(len(rows_since(n0, "cam.detect")), 3, "every frame is still its own detection row")

    def test_the_ask_carries_the_sightings_own_bytes_whatever_the_next_frame_is(self):
        """The POST returns before dispatch reads its file, and the client posts the next frame 0-1 s later; ingest
        replaces lap1.jpg and lap1-boxed.jpg with it. The file handed to dispatch must still be the boxed person."""
        from wtdd import tools
        calls = []
        (_TMP / "intruder.on").write_text("2026-09-26T00:00:00\n")
        later = FRAME + b"\x00later"   # still a JPEG by its first bytes; nobody in it
        with mock.patch.object(tools, "call", lambda tool, **kw: calls.append((tool, kw))):
            status, _, data = req("POST", "/cam/lap1/frame", FRAME)
            self.assertEqual(status, 200, data[:300])
            self.assertTrue(json.loads(data)["person"]["dispatched"])
            time.sleep(0.3)
            with mock.patch.object(cam, "detect_file", lambda frame, out: (Path(out).write_bytes(b"boxed:" + Path(frame).read_bytes()),
                                                                            {**DETECT, "n": 0, "classes": {}, "boxes": [], "file": str(out)})[1]):
                status, _, data = req("POST", "/cam/lap1/frame", later)
            self.assertEqual(status, 200, data[:300])
        (tool, kw), = calls
        self.assertEqual((CAMS / "lap1-boxed.jpg").read_bytes(), b"boxed:" + later, "the shared boxed file is the later frame now")
        self.assertEqual(Path(kw["file"]).read_bytes(), b"boxed:" + FRAME, "the ask posts the frame the detector boxed a person in")

    def test_no_person_no_question(self):
        quiet = {**DETECT, "n": 0, "classes": {}, "boxes": []}
        (_TMP / "intruder.on").write_text("2026-09-26T00:00:00\n")
        with mock.patch.object(cam, "detect_file", lambda frame, out: {**quiet, "file": str(out)}):
            status, _, data = req("POST", "/cam/lap1/frame", FRAME)
        self.assertEqual(status, 200, data[:300])
        self.assertIsNone(json.loads(data)["person"])
        self.assertEqual(self.posts, [])


class Client(Case):
    """python -m wtdd.cam: the laptop side. --source <file> is the DEMO_CACHE replay of one JPEG (no camera in a worktree)."""

    def test_file_source_posts_once(self):
        from wtdd.cam import __main__ as client
        n0 = len(ledger.rows())
        out = io.StringIO()
        with redirect_stdout(out):
            rc = client.main(["--server", url(), "--cam", "lap1", "--source", str(FIX / "frame.jpg"), "--once"])
        self.assertEqual(rc, 0, out.getvalue())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], FRAME)
        self.assertEqual(len(rows_since(n0, "cam.frame")), 1)
        printed = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual(printed["detect"]["classes"], {"person": 1})

    def test_dead_server_is_loud_not_fake(self):
        from wtdd.cam import __main__ as client
        n0 = len(ledger.rows())
        rc = client.main(["--server", "http://127.0.0.1:1", "--cam", "lap1", "--source", str(FIX / "frame.jpg"), "--once"])
        self.assertEqual(rc, 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(rows_since(n0, "cam.frame"), [])


@unittest.skipUnless((config.ROOT / "yolo11n.pt").exists(),
                     "yolo11n.pt is absent here (gitignored; downloads on the first live run): the real detector subprocess is not exercised in this checkout")
class LiveDetector(unittest.TestCase):
    """The real handshake, only where the weights are: python -m wtdd.watch --source <frame> --once --out <boxed>."""

    def test_real_detector_runs_in_its_own_process(self):
        with mock.patch.object(cam, "ARMED", _TMP / "never-armed"):
            n0 = len(ledger.rows())
            status, _, data = req("POST", "/cam/live1/frame", FRAME)
        self.assertEqual(status, 200, data[:300])
        r = json.loads(data)
        detects = rows_since(n0, "cam.detect")
        self.assertEqual(len(detects), 1)
        self.assertTrue(detects[0]["ok"], detects[0]["response_or_error"])
        self.assertTrue((CAMS / "live1-boxed.jpg").exists())
        self.assertNotIn("cv2", sys.modules)
        print(f"\n[wtdd:cam] real detector on the drawn figure: classes={r['detect']['classes']} ms={r['detect']['ms']}", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
