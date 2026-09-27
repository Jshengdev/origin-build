"""A camera is placed on the map from the remote, like a lamp, offline. Run: python -m unittest wtdd.cam.test_place -v
Checks: zone_of(pt, zones), the first drawn non-nogo zone containing the point under field.inside, else None;
validate_cameras(cameras, zones): ids unique and non-empty (and postable: cam.ID, the rule POST /cam/<id>/frame already
applies, so a placed camera can always receive frames), pt a pair inside the viewBox (0 0 1060 1540), zone recomputed
from pt whatever the page sent, a camera in no zone kept with zone null plus exactly one WARN line
`[wtdd:cam] camera lap1 placed in no zone: the roster will refuse`, the zones it reads a list of named polygons or a
ValueError naming the zone (a 400, never a dropped socket); and, through the real API handler in a thread,
POST /map with cameras[]: a placed camera round-trips through GET /map with its zone recomputed and the previous file
in map.prev.json, one map.camera_placed row {id, pt, zone, shift_id} per camera whose pt is new or moved (none when
nothing moved, none on a refused save; the night-2 contracts' row for 22's livecheck; still written when the previous
file's cameras are null or hand-added without an id), a duplicate id, a bad zone and a pt outside
the viewBox are 400 with the file and map.prev.json untouched, and a map with no cameras key is saved as sent (no key
invented). Lights pass through a save untouched. The page's half (the `place camera` button beside each camera in 09's
Cams panel, the placing mode, the glyph `lap1 · zone a` / `lap1 · no zone` in yellow) is the headless screenshot gate
in the PR body; here only the page's source is checked for the button, the mode, the marker and the lights' own
`place dot` still being there.
Fixture: 09's ui/map.json (cameras: lap1 at [322, 1284] in zone a) with route-saved.json's runnable path (the map's
own path has a 526 px jump that check_path refuses, night-1 contracts F.4), copied to a scratch dir per test; a scratch
ledger. The zones are the map's lighting zones a, b, c plus two no-go zones built here (04's fixture polygon, which sits
inside b, and one alone in bedroom 3). Nothing real is touched."""
from __future__ import annotations
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-place-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
os.environ.setdefault("WTDD_CAMS", str(_TMP / "cams"))   # posts no frame; never overwrite test_cam's dir when both load in one process
os.environ["WTDD_SHIFT"] = "2026-09-26-test"

from wtdd import api, cam, config, field, ledger  # noqa: E402

UI = config.ROOT / "ui"
BASE = json.loads((UI / "map.json").read_text())            # 09's map: cameras [{lap1, laptop at the gate, [322, 1284], a}]
ROUTE = json.loads((UI / "route-saved.json").read_text())   # the runnable taught route (23 points, max gap 75 px)
ZONES = BASE["zones"]                                        # a, b, c: the lighting zones, none of them nogo
NOGO_IN_B = {"name": "nogo-1", "label": "no-go 1", "nogo": True, "poly": [[450, 1040], [510, 1040], [510, 1250], [450, 1250]]}   # 04's fixture zone, inside b
NOGO_ALONE = {"name": "nogo-2", "label": "no-go 2", "nogo": True, "poly": [[800, 200], [900, 200], [900, 300], [800, 300]]}      # bedroom 3: no lighting zone there
SHIFT = os.environ["WTDD_SHIFT"]
WARN = "[wtdd:cam] camera lap1 placed in no zone: the roster will refuse"
SRV: ThreadingHTTPServer | None = None


def setUpModule():
    global SRV
    SRV = ThreadingHTTPServer(("127.0.0.1", 0), api.H)   # an ephemeral port: 7930 is the item's browser check, not this test
    threading.Thread(target=SRV.serve_forever, daemon=True).start()


def tearDownModule():
    if SRV:
        SRV.shutdown()


def req(method: str, path: str, obj: dict | None = None) -> tuple[int, dict]:
    c = http.client.HTTPConnection("127.0.0.1", SRV.server_address[1], timeout=30)
    body = json.dumps(obj).encode() if obj is not None else None
    c.request(method, path, body=body, headers={"Content-Type": "application/json"} if body is not None else {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, json.loads(data)


def rows_since(n0: int, tool: str) -> list[dict]:
    return [r for r in ledger.rows()[n0:] if r.get("tool") == tool]


def fresh_map() -> dict:
    """09's map with the runnable path, as the page would send it (cameras included in every save)."""
    m = json.loads(json.dumps(BASE))
    m["path"], m["stops"] = ROUTE["path"], ROUTE.get("stops", [])
    return m


class Zone(unittest.TestCase):
    """zone_of(pt, zones): the first drawn non-nogo zone the point sits in, else None."""

    def test_first_drawn_non_nogo_zone_or_none(self):
        self.assertEqual(cam.zone_of([322, 1284], ZONES), "a")
        self.assertEqual(cam.zone_of([450, 1200], ZONES), "b")
        self.assertEqual(cam.zone_of([600, 1100], ZONES), "c")
        self.assertIsNone(cam.zone_of([850, 250], ZONES), "bedroom 3 is a room, not a drawn zone")
        self.assertIsNone(cam.zone_of([100, 100], ZONES), "outside every room and zone")
        self.assertIsNone(cam.zone_of([450, 1200], []))
        self.assertEqual(cam.zone_of([480, 1100], [NOGO_IN_B, *ZONES]), "b", "a no-go zone never holds a camera, even when drawn first")
        self.assertIsNone(cam.zone_of([850, 250], [*ZONES, NOGO_ALONE]), "inside only a no-go zone is no zone")
        twice = [ZONES[1], {"name": "b2", "label": "zone b again", "poly": ZONES[1]["poly"]}, ZONES[0]]
        self.assertEqual(cam.zone_of([450, 1200], twice), "b", "the first drawn zone wins when two overlap")


class Validate(unittest.TestCase):
    """validate_cameras(cameras, zones): the list as it will be saved, or ValueError naming the camera."""

    def test_zone_recomputed_from_pt(self):
        out = cam.validate_cameras([{"id": "lap1", "label": "laptop at the gate", "pt": [450, 1200], "zone": "a"}], ZONES)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["zone"], "b", "the saved zone is the drawn zone the point sits in, whatever the page sent")
        self.assertEqual(out[0]["pt"], [450, 1200])
        self.assertEqual(out[0]["id"], "lap1")
        self.assertEqual(out[0]["label"], "laptop at the gate")
        out = cam.validate_cameras([{"id": "lap1", "label": "x", "pt": [322, 1284]}], ZONES)   # no zone key at all: computed
        self.assertEqual(out[0]["zone"], "a")
        self.assertEqual(cam.validate_cameras([], ZONES), [])
        with redirect_stderr(io.StringIO()):   # the corners of the viewBox are inside it (no zone there: a WARN, not a refusal)
            self.assertIsNone(cam.validate_cameras([{"id": "lap1", "label": "x", "pt": [0, 0]}], ZONES)[0]["zone"])
            self.assertIsNone(cam.validate_cameras([{"id": "lap1", "label": "x", "pt": [1060, 1540]}], ZONES)[0]["zone"])

    def test_no_zone_is_null_with_exactly_one_warn(self):
        err = io.StringIO()
        with redirect_stderr(err):
            out = cam.validate_cameras([{"id": "lap1", "label": "x", "pt": [850, 250], "zone": "a"}], ZONES)
        self.assertIsNone(out[0]["zone"], "a stale zone from the page is not kept when the point sits in none")
        self.assertEqual(err.getvalue().count(WARN), 1, err.getvalue())
        err = io.StringIO()
        with redirect_stderr(err):
            cam.validate_cameras([{"id": "lap1", "label": "x", "pt": [322, 1284]}], ZONES)
        self.assertNotIn("no zone", err.getvalue(), "no WARN for a camera that has a zone")

    def test_bad_cameras_raise_naming_the_camera(self):
        ok = {"id": "lap1", "label": "x", "pt": [322, 1284]}
        for bad, why, named in (
            ([ok, {**ok, "pt": [450, 1200]}], "duplicate id", "lap1"),
            ([{**ok, "id": ""}], "empty id", None),
            ([{"label": "x", "pt": [322, 1284]}], "no id", None),
            ([{**ok, "id": "a b"}], "an id POST /cam/<id>/frame would refuse (cam.ID)", "a b"),
            ([{**ok, "pt": [1100, 1284]}], "x past the viewBox", "lap1"),
            ([{**ok, "pt": [322, -5]}], "y before the viewBox", "lap1"),
            ([{**ok, "pt": [322]}], "one coordinate", "lap1"),
            ([{**ok, "pt": "322,1284"}], "pt not a pair", "lap1"),
            ([{"id": "lap1", "label": "x"}], "no pt", "lap1"),
            ({"lap1": ok}, "cameras not a list", None),
            (["lap1"], "a camera that is not a dict", None),
        ):
            with self.subTest(why=why):
                with self.assertRaises(ValueError) as c:
                    cam.validate_cameras(bad, ZONES)
                if named:
                    self.assertIn(named, str(c.exception), why)

    def test_bad_zones_raise_naming_the_zone(self):
        ok = [{"id": "lap1", "label": "x", "pt": [322, 1284]}]
        for zones, why, named in (   # a ValueError is the API's 400; a TypeError or KeyError would drop the page's socket
            (None, "zones null", "zones"),
            ({"a": ZONES[0]}, "zones not a list", "zones"),
            ([ZONES[0], "b"], "a zone that is not a dict", "zone 2"),
            ([ZONES[0], {"label": "no name", "poly": ZONES[1]["poly"]}], "a zone with no name", "zone 2"),
            ([ZONES[0], {"name": "b", "label": "zone b"}], "a zone with no poly", "zone b"),
            ([{**ZONES[0], "poly": [[266, 1135], [372], [372, 1500]]}], "a vertex that is not a pair", "zone a"),
            ([{**NOGO_IN_B, "poly": None}, *ZONES], "a no-go zone with no poly", "zone nogo-1"),
        ):
            with self.subTest(why=why):
                with self.assertRaises(ValueError) as c:
                    cam.validate_cameras(ok, zones)
                self.assertIn(named, str(c.exception), why)


class Save(unittest.TestCase):
    """POST /map with cameras[], through the real handler: what the page's save does after a `place camera` click."""

    def setUp(self):
        d = Path(tempfile.mkdtemp(prefix="map-", dir=_TMP))
        self.map, self.prev = d / "map.json", d / "map.prev.json"
        self.map.write_text(json.dumps(fresh_map(), indent=2) + "\n")
        for p in (mock.patch.object(api, "MAP", self.map), mock.patch.object(field, "MAP", self.map)):
            p.start()
            self.addCleanup(p.stop)

    def post(self, m: dict) -> tuple[int, dict]:
        return req("POST", "/map", m)

    def get(self) -> dict:
        return req("GET", "/map")[1]

    def test_placed_camera_round_trips_with_zone_recomputed_and_prev_kept(self):
        n0 = len(ledger.rows())
        m = fresh_map()
        m["cameras"][0]["pt"] = [450, 1200]      # the click: from zone a into zone b; the page leaves `zone` as it was
        status, r = self.post(m)
        self.assertEqual(status, 200, r)
        self.assertTrue(r["ok"])
        got = self.get()
        self.assertEqual(got["cameras"][0]["id"], "lap1")
        self.assertEqual(got["cameras"][0]["label"], "laptop at the gate")
        self.assertEqual(got["cameras"][0]["pt"], [450, 1200])
        self.assertEqual(got["cameras"][0]["zone"], "b")
        self.assertEqual(json.loads(self.map.read_text())["cameras"][0]["zone"], "b", "the file holds the recomputed zone, not only the response")
        self.assertEqual(json.loads(self.prev.read_text())["cameras"][0]["pt"], [322, 1284], "the previous file survives one overwrite")
        self.assertEqual(got["path"], ROUTE["path"])
        self.assertEqual(got["lights"], m["lights"], "the lights pass through a save untouched")
        placed = rows_since(n0, "map.camera_placed")
        self.assertEqual(len(placed), 1, [x["tool"] for x in ledger.rows()[n0:]])
        row = placed[0]
        self.assertTrue(row["ok"])
        self.assertEqual(row["args"]["id"], "lap1")
        self.assertEqual(row["args"]["pt"], [450, 1200])
        self.assertEqual(row["args"]["zone"], "b")
        self.assertEqual(row["args"]["shift_id"], SHIFT)
        self.assertEqual((row["cached"], row["source"]), (False, "live"))
        self.assertEqual((row["state_before"]["pt"], row["state_before"]["zone"]), ([322, 1284], "a"), "where it was on the previous file")
        self.assertEqual((row["state_after"]["pt"], row["state_after"]["zone"]), ([450, 1200], "b"), "where the saved file says it is")
        self.assertIsInstance(row["latency_ms"], int)

        n1 = len(ledger.rows())                   # saved again with nothing moved: not a placement
        status, r = self.post(got)                # got carries _version, so this is the page's own save
        self.assertEqual(status, 200, r)
        self.assertEqual(rows_since(n1, "map.camera_placed"), [], "a save that moves no camera is not a placement")

        n2 = len(ledger.rows())                   # a second camera added: one row for it alone, nothing before it
        m2 = self.get()
        m2["cameras"].append({"id": "lap2", "label": "laptop by the strip", "pt": [600, 1100], "zone": None})
        status, r = self.post(m2)
        self.assertEqual(status, 200, r)
        placed = rows_since(n2, "map.camera_placed")
        self.assertEqual([x["args"]["id"] for x in placed], ["lap2"])
        self.assertEqual(placed[0]["args"]["zone"], "c")
        self.assertIsNone(placed[0]["state_before"])
        self.assertEqual([c["zone"] for c in self.get()["cameras"]], ["b", "c"])

    def test_no_zone_is_saved_null_with_the_warn(self):
        n0 = len(ledger.rows())
        m = fresh_map()
        m["cameras"][0]["pt"] = [850, 250]        # bedroom 3: a room, no drawn zone
        err = io.StringIO()
        with redirect_stderr(err):
            status, r = self.post(m)
        self.assertEqual(status, 200, r)
        self.assertTrue(r["ok"])
        got = self.get()
        self.assertEqual(got["cameras"][0]["pt"], [850, 250])
        self.assertIsNone(got["cameras"][0]["zone"])
        self.assertEqual(err.getvalue().count(WARN), 1, err.getvalue())
        placed = rows_since(n0, "map.camera_placed")
        self.assertEqual(len(placed), 1)
        self.assertTrue(placed[0]["ok"], "no zone is a saved null and a WARN, not a refusal: 08's roster refuses later")
        self.assertIsNone(placed[0]["args"]["zone"])

    def test_duplicate_id_is_400_and_nothing_written(self):
        n0 = len(ledger.rows())
        before = self.map.read_bytes()
        m = fresh_map()
        m["cameras"].append({**m["cameras"][0], "pt": [450, 1200]})
        status, r = self.post(m)
        self.assertEqual(status, 400, r)
        self.assertFalse(r["ok"])
        self.assertIn("lap1", r["error"])
        self.assertTrue(self.map.read_bytes() == before, "a refused save leaves the file as it was")
        self.assertFalse(self.prev.exists(), "a refused save does not roll map.prev.json")
        self.assertEqual(rows_since(n0, "map.camera_placed"), [])

    def test_pt_outside_the_viewbox_is_400(self):
        before = self.map.read_bytes()
        for pt in ([1100, 1284], [322, -5], [322]):
            with self.subTest(pt=pt):
                m = fresh_map()
                m["cameras"][0]["pt"] = pt
                status, r = self.post(m)
                self.assertEqual(status, 400, r)
                self.assertFalse(r["ok"])
                self.assertIn("lap1", r["error"])
        self.assertTrue(self.map.read_bytes() == before, "a refused save leaves the file as it was")
        self.assertFalse(self.prev.exists())

    def test_bad_zone_is_400_not_a_dropped_connection(self):
        before = self.map.read_bytes()
        for zones in (None, [{"name": "x"}]):
            with self.subTest(zones=zones):
                m = fresh_map()
                m["zones"] = zones
                status, r = self.post(m)   # before the fix: RemoteDisconnected, the handler thread died on a TypeError/KeyError
                self.assertEqual(status, 400, r)
                self.assertFalse(r["ok"])
                self.assertIn("zone", r["error"])
        self.assertTrue(self.map.read_bytes() == before, "a refused save leaves the file as it was")
        self.assertFalse(self.prev.exists())

    def test_previous_file_with_broken_cameras_still_gets_its_row(self):
        for prev, why in (
            (None, "cameras: null on the previous file"),
            ([{"label": "hand-added, no id", "pt": [600, 1100]}], "a hand-added camera with no id on the previous file"),
        ):
            with self.subTest(why=why):
                self.map.write_text(json.dumps({**fresh_map(), "cameras": prev}, indent=2) + "\n")
                n0 = len(ledger.rows())
                status, r = self.post(fresh_map())
                self.assertEqual(status, 200, r)
                placed = rows_since(n0, "map.camera_placed")
                self.assertEqual([(x["args"]["id"], x["ok"]) for x in placed], [("lap1", True)], why)
                self.assertIsNone(placed[0]["state_before"], "no camera lap1 on the previous file: a new camera")
                self.assertEqual(placed[0]["state_after"], {"pt": [322, 1284], "zone": "a"})

    def test_cameras_not_a_list_is_400(self):
        m = fresh_map()
        m["cameras"] = {"lap1": m["cameras"][0]}
        status, r = self.post(m)
        self.assertEqual(status, 400, r)
        self.assertFalse(r["ok"])

    def test_map_without_cameras_is_saved_as_sent(self):
        n0 = len(ledger.rows())
        m = fresh_map()
        m.pop("cameras")
        status, r = self.post(m)
        self.assertEqual(status, 200, r)
        got = self.get()
        self.assertNotIn("cameras", got, "the API invents no cameras key")
        self.assertEqual(got["path"], ROUTE["path"])
        self.assertEqual(rows_since(n0, "map.camera_placed"), [])


class Page(unittest.TestCase):
    """The static half of the screenshot gate: the drawing itself is proven headless in the PR body (23-remote.png, 23-failed.png)."""

    def test_page_source_has_place_camera_and_keeps_place_dot(self):
        import re
        src = (UI / "index.html").read_text()
        has = lambda s, why: self.assertTrue(s in src, f"{why}: {s!r} is not in ui/index.html")   # noqa: E731  (assertIn would print the whole page)
        has("place camera", "one button per camera in 09's Cams panel")
        self.assertTrue(re.search(r'startPlace\(\s*\w+\s*,\s*"camera"\s*\)', src), "the button enters the existing placing mode with kind camera")
        has('mode === "camera"', "the next map click in camera mode sets cameras[i].pt")
        has("no zone", "the glyph names the failed state")
        has("// 23 · camera-placement · start", "the component is marked")
        has("// 23 · camera-placement · end", "the component is marked")
        has('startPlace(L, "dot")', "the lights' own place dot is untouched")
        has('startPlace(L, "line")', "and so is draw line")


if __name__ == "__main__":
    unittest.main()
