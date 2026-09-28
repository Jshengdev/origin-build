"""GET /images: the photos one run's rows name, for the dashboard's Routines and Waiting. Run:
    python -m unittest wtdd.test_images -v
The real handler on an ephemeral port in this process, on a planted ledger (WTDD_LEDGER set before wtdd.ledger is
imported) and a planted pictures folder (api.PICTURES patched to a temp dir holding a few bytes per name, never a
photo). The rows: another shift's post; then this shift's wake, the wake show's made picture, a tilt look (its room
frame since replaced by a newer look under the same name), the say post with a phone number in its text, the flag
(escalate) to a 1:1, a text-only post, the scout's auto zone, and a say post whose file is gone. Checked: this shift's
photos in time order with their kinds, stops and captions; the number reads "a member" (B10) and no folder path is
answered; the other shift's photo is not listed; the gone file lists with missing true and the replaced frame with
replaced true; ?trigger= and ?kind= filter; the default shift is the run in force; an unknown shift is a 404 naming the
shifts and an unknown kind a 400 naming the kinds; the listed url serves the planted bytes through /pictures; the
ledger's bytes do not change (a read, no row). Handles are stand-ins."""
from __future__ import annotations
import contextlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-images-test-"))
LEDGER = _TMP / "ledger.jsonl"
os.environ["WTDD_LEDGER"] = str(LEDGER)
os.environ["WTDD_SHIFT"] = ""   # gotcha 02-2: an empty value blocks .env and reads as unset

from wtdd import api  # noqa: E402

PICS = _TMP / "pictures"
S, OTHER = "2026-09-27-night", "2026-09-26-night"
W = "W1-WAKE"
PHONE = "+15550001111"
ONE = "any;-;+15550002222"


def _t(ts: str) -> float:
    return time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))


def _row(ts, tool, args, after=None, before=None, ok=True, resp=None, agent="central"):
    return {"ts": ts, "run_id": "run-test", "cached": True, "source": "stub", "step": tool, "agent": agent, "tool": tool,
            "app": "stub", "args": args, "state_before": before, "state_after": after, "ok": ok,
            "response_or_error": resp, "latency_ms": 0}


def _post(ts, trigger, kind, text, file, shift=S, guid="any;+;group"):
    return _row(ts, "chat.post", {"guid": guid, "kind": kind, "trigger": trigger, "text": text,
                                  "file": None if file is None else str(PICS / file), "shift_id": shift},
                {"guid": f"MSG-{trigger}", "rowid": 1, "ts": ts.replace("T", " ")})


SCOUT = "scout-20260927T210100-z1.jpg"
SAID = "I added a no-go zone around the chair: the stub (DEMO_CACHE, not Jev) is 0.91 sure it's a hazard."
ROWS = [
    _post("2026-09-26T22:00:00", "say:W0:1", "listen", "a shoe", "other-night.jpg", shift=OTHER),
    _row("2026-09-27T21:00:00", "chat.wake", {"from": PHONE, "text": "yo dog do a round", "guid": W}),
    _post("2026-09-27T21:00:02", f"fire:{W}", "listen", None, "this-is-fine.jpg"),
    _row("2026-09-27T21:00:05", "dog.look", {"kind": "tilt"},
         {"text": "here's what i see", "file": str(PICS / "look-tilt.jpg"), "kind": "tilt", "pitch_deg": -16.0, "fired": True,
          "attempts": 1, "file_down": str(PICS / "look-down.jpg"), "pitch_down_deg": 14.0}, agent="dog"),
    _post("2026-09-27T21:00:10", f"say:{W}:2", "listen", f"a cup on the table. text {PHONE}", "look-down-boxed.jpg"),
    _post("2026-09-27T21:00:20", f"alarm:{W}:2", "escalate", "who dis?!", "look-down-boxed.jpg", guid=ONE),
    _post("2026-09-27T21:00:25", f"doin:{W}", "listen", "dog doin", None),
    _row("2026-09-27T21:01:00", "zone.confirmed", {"id": "z1", "zone": "nogo-3", "by": "auto (stub 0.91)", "shift_id": S},
         {"_version": 1}, before={"id": "z1", "kind": "chair", "p": 0.91,
                                  "photo": {"path": str(PICS / SCOUT), "sha256": "0" * 64, "bytes": 7}}, resp=SAID, agent="scout"),
    _post("2026-09-27T21:02:00", f"say:{W}:3", "listen", "a sock by the door", "look-level-boxed.jpg"),
]
PLANTED = {"other-night.jpg": "2026-09-26T21:59:00", "this-is-fine.jpg": "2026-09-27T21:00:01",
           "look-tilt.jpg": "2026-09-27T21:09:00",   # a newer look wrote this name after its row: replaced
           "look-down.jpg": "2026-09-27T21:00:04", "look-down-boxed.jpg": "2026-09-27T21:00:08", SCOUT: "2026-09-27T21:00:59"}
# look-level-boxed.jpg is never planted: its post lists it, missing


class Images(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        PICS.mkdir(parents=True, exist_ok=True)
        for name, ts in PLANTED.items():
            (PICS / name).write_bytes(f"planted {name}, not a photo".encode())
            os.utime(PICS / name, (_t(ts), _t(ts)))
        LEDGER.write_text("".join(json.dumps(r) + "\n" for r in ROWS))
        cls.raw = LEDGER.read_bytes()
        cls.patch = mock.patch.object(api, "PICTURES", PICS)
        cls.patch.start()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.patch.stop()

    def setUp(self):
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def tearDown(self):
        self.assertEqual(LEDGER.read_bytes(), self.raw, "a read wrote the ledger")

    def get(self, path: str) -> tuple[int, str]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def images(self, query: str) -> dict:
        code, text = self.get(f"/images?{query}")
        self.assertEqual(code, 200, text)
        return json.loads(text)

    def test_the_shifts_photos_in_time_order_with_kinds_stops_and_captions(self):
        body = self.images(f"shift={S}")
        got = [(i["file"], i["kind"], i["stop"], i["trigger"], i["ts"]) for i in body["images"]]
        self.assertEqual(got, [
            ("look-tilt.jpg", "look", 2, None, "2026-09-27T21:00:05"),
            ("look-down.jpg", "look", 2, None, "2026-09-27T21:00:05"),
            ("look-down-boxed.jpg", "look", 2, f"say:{W}:2", "2026-09-27T21:00:10"),
            ("look-down-boxed.jpg", "ask", 2, f"alarm:{W}:2", "2026-09-27T21:00:20"),
            (SCOUT, "scout", None, None, "2026-09-27T21:01:00"),
            ("look-level-boxed.jpg", "look", 3, f"say:{W}:3", "2026-09-27T21:02:00"),
        ])
        self.assertEqual((body["shift"], body["n"]), (S, 6))
        self.assertEqual([i["caption"] for i in body["images"]],
                         [None, None, "a cup on the table. text a member", "who dis?!", SAID, "a sock by the door"])
        self.assertEqual({(i["shift_id"], i["ok"]) for i in body["images"]}, {(S, True)})
        self.assertEqual([i["url"] for i in body["images"]], [f"/pictures/{i['file']}" for i in body["images"]])

    def test_the_made_picture_and_a_text_only_post_are_not_photos(self):
        files = [i["file"] for i in self.images(f"shift={S}")["images"]]
        self.assertNotIn("this-is-fine.jpg", files)   # dog_on_fire draws it over a dog.ceo photo; the dog never took it
        self.assertEqual(len(files), 6)

    def test_no_phone_number_and_no_folder_path_is_answered(self):
        code, text = self.get(f"/images?shift={S}")
        self.assertEqual(code, 200)
        for private in (PHONE, PHONE[1:], "+15550002222", str(PICS), str(_TMP)):
            self.assertNotIn(private, text)
        self.assertTrue(all("/" not in i["file"] for i in json.loads(text)["images"]))

    def test_another_shifts_photo_is_not_listed(self):
        self.assertNotIn("other-night.jpg", [i["file"] for i in self.images(f"shift={S}")["images"]])
        self.assertEqual([i["file"] for i in self.images(f"shift={OTHER}")["images"]], ["other-night.jpg"])

    def test_a_gone_file_still_lists_missing_and_a_replaced_frame_says_so(self):
        body = self.images(f"shift={S}")
        self.assertEqual([i["missing"] for i in body["images"]], [False, False, False, False, False, True])
        self.assertEqual([i["replaced"] for i in body["images"]], [True, False, False, False, False, False])
        self.assertIn("1 missing", body["why"])
        self.assertIn("1 replaced", body["why"])

    def test_trigger_and_kind_filter(self):
        body = self.images(f"shift={S}&trigger=alarm:{W}:2")
        self.assertEqual([(i["kind"], i["trigger"]) for i in body["images"]], [("ask", f"alarm:{W}:2")])
        self.assertEqual(body["n"], 1)
        self.assertEqual([i["file"] for i in self.images(f"shift={S}&kind=scout")["images"]], [SCOUT])
        none = self.images(f"shift={S}&trigger=nope")
        self.assertEqual((none["images"], none["n"]), ([], 0))
        self.assertIn("nope", none["why"])

    def test_the_default_shift_is_the_run_in_force(self):
        with mock.patch.dict(os.environ, {"WTDD_SHIFT": S}):
            body = self.images("")
        self.assertEqual((body["shift"], body["n"]), (S, 6))

    def test_an_unknown_shift_is_a_404_naming_the_shifts(self):
        code, text = self.get("/images?shift=nope")
        self.assertEqual(code, 404, text)
        err = json.loads(text)["error"]
        for s in ("nope", S, OTHER):
            self.assertIn(s, err)
        self.assertNotIn("images", json.loads(text), "never an empty list")

    def test_an_unknown_kind_is_a_400_naming_the_kinds(self):
        code, text = self.get(f"/images?shift={S}&kind=selfie")
        self.assertEqual(code, 400, text)
        for k in ("selfie", "look", "ask", "scout", "blob"):
            self.assertIn(k, json.loads(text)["error"])

    def test_the_url_serves_the_planted_bytes_through_pictures(self):
        img = self.images(f"shift={S}&kind=ask")["images"][0]
        with urllib.request.urlopen(self.base + img["url"], timeout=30) as r:
            self.assertEqual(r.read(), b"planted look-down-boxed.jpg, not a photo")
        code, text = self.get(f"/images?shift={S}")
        self.assertNotIn("planted", text, "GET /images serves no bytes")


if __name__ == "__main__":
    unittest.main()
