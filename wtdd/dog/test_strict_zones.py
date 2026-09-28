"""Johnny, 2026-09-27 20:23 and 20:26, after a scout with zones on stacked 41 auto zones in ten minutes, most wrong: two
kinds of zone. A PERSON is a soft, temporary zone with the detection photo, drawn from the live LiDAR points around them,
never on ui/map.json and never in a route's way. Everything else is a HAZARD, written only when four gates pass: the
detector's p (1), the same thing seen again and again (2), a stronger vision model confirming the photo (3), and a lit
LiDAR cluster in the newest window around the pin (4). The zone's shape is that lit cluster, never a fill over the
accumulated grid. Dry: synthetic objects, synthetic live points, a scratch map, a stubbed confirm model (no network).

    python -m unittest wtdd.dog.test_strict_zones
"""
from __future__ import annotations
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ..config import ROOT
from .. import images, ledger, nogo
from . import occupancy
from .fixtures import make_objects_fixture as ofx
from . import scout_zones as sz

RES, CAL, FOV, POSE = 0.05, ofx.CAL, ofx.FOV_DEG, ofx.POSE
TABLE_AT, PERSON_AT = [2.0, 0.0], [1.5, -1.0]


def square(c, half: float) -> list:
    """Voxel columns on the 5 cm lattice filling a square of side 2*half around c (a thing the LiDAR lit)."""
    k = int(round(half / RES))
    return [[round(c[0] + i * RES, 3), round(c[1] + j * RES, 3)] for i in range(-k, k + 1) for j in range(-k, k + 1)]


WALL = [[4.0, round(-1.0 + j * RES, 3)] for j in range(41)]   # a far wall: lit, but nowhere near either pin
LIVE = square(TABLE_AT, 0.15) + square(PERSON_AT, 0.1) + WALL


def obj(oid="o1", label="dining table", p=0.85, hit=TABLE_AT, unseen=0) -> dict:
    return {"id": oid, "label": label, "p": p, "label_source": "detector", "hit_m": list(hit), "dist_m": float(np.hypot(*hit)),
            "pos_px": occupancy.to_map_px([hit], CAL).tolist()[0], "box": [280, 200, 360, 330], "bearing_deg": 0.0,
            "thumb": None, "stale": False, "windows_unseen": unseen}


def frame(i: int = 0) -> dict:
    return {"file": str(ofx.FRAME), "t": 1790420400.0 + i, "ts": f"2026-09-27T20:30:{i:02d}", "boxes": []}


def yes(name="dining table", p=0.9, calls=None):
    def f(q):
        if calls is not None:
            calls.append(q)
        return {"answer": "yes", "name": name, "p": p, "model": "test/confirm-double", "raw": '{"double": true}',
                "app": "openrouter", "cached": False}
    return f


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wtdd-strict-"))
        self.map = self.tmp / "map.json"
        shutil.copy(ROOT / "ui" / "map.json", self.map)
        self.pics = self.tmp / "pictures"
        self.rows: list = []
        self.t = [1000.0]
        self.grid = occupancy.Grid(RES, (-3.2, -3.2), "odom")
        for p in (mock.patch.dict(os.environ, {"WTDD_DECIDE_THRESHOLD": "0.7", "WTDD_SHIFT": "2026-09-27", "WTDD_SCOUT_ZONES": ""}),
                  mock.patch.object(ledger, "LEDGER", self.tmp / "ledger.jsonl")):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.i = 0

    def props(self, confirm=None, calls=None):
        return sz.Proposals(append=self.rows.append, decide=sz.decide_stub, photo_dir=self.pics, map_path=self.map,
                            confirm=confirm or yes(calls=calls), clock=lambda: self.t[0])

    def feed(self, p, objs, n=1, dt=1.0, live=LIVE):
        """n detector windows, dt seconds apart, each a new frame."""
        for _ in range(n):
            with contextlib.redirect_stderr(io.StringIO()):
                p.feed(objs, frame(self.i), POSE, self.grid, CAL, FOV, grid_lock=None, live=live)
            self.i += 1
            self.t[0] += dt

    def auto(self) -> list:
        return [z for z in json.loads(self.map.read_text())["zones"] if z.get("by") == "auto"]

    def tool(self, name) -> list:
        return [r for r in self.rows if r["tool"] == name]


class Hazard(Base):
    def test_a_the_gates(self):
        calls: list = []
        p = self.props(calls=calls)
        self.feed(p, [obj()], n=1)
        self.assertEqual((self.auto(), calls), ([], []), "seen once at high p: no zone and no confirm call")
        self.feed(p, [obj()], n=3)   # windows 2..4, 3 s after the first
        zs = self.auto()
        self.assertEqual(len(zs), 1, zs)
        self.assertEqual(len(calls), 1, "one confirm call per thing")
        ev = zs[0]["evidence"]
        self.assertEqual((ev["p"], ev["seen_n"], ev["span_s"]), (0.85, 4, 3.0))
        self.assertEqual(ev["confirm"], {"model": "test/confirm-double", "answer": "yes", "name": "dining table", "p": 0.9})
        self.assertEqual(ev["points_n"], len(square(TABLE_AT, 0.15)))
        self.assertEqual(zs[0]["kind"], "hazard")
        served = [z for z in p.state(CAL)["zones"] if z["kind"] == "hazard"]
        self.assertEqual(len(served), 1)
        self.assertEqual(served[0]["evidence"], ev)
        self.assertTrue(Path(self.pics / served[0]["photo"]["file"]).exists())
        self.assertEqual(served[0]["photo"]["url"], "/pictures/" + served[0]["photo"]["file"])
        row = self.tool("zone.confirmed")[0]
        self.assertTrue(row["ok"])
        self.assertEqual(row["args"]["evidence"], ev)
        self.feed(p, [obj()], n=4)
        self.assertEqual(len(self.auto()), 1, "a thing is taken once")

    def test_b_the_confirm_model_says_no_or_errors(self):
        for name, fn in (("no", lambda q: {**yes()(q), "answer": "no"}), ("unsure", yes(p=0.7)), ("disagrees", yes(name="a cardboard box"))):
            with self.subTest(name):
                self.rows.clear()
                p = self.props(confirm=fn)
                self.feed(p, [obj()], n=5)
                self.assertEqual(self.auto(), [])
                r = self.tool("zone.confirm")
                self.assertEqual(len(r), 1)
                self.assertTrue(r[0]["ok"], "the model answered: its answer is the row")
        self.rows.clear()

        def boom(q):
            raise TimeoutError("read timed out")
        p = self.props(confirm=boom)
        self.feed(p, [obj()], n=8)
        self.assertEqual(self.auto(), [])
        r = self.tool("zone.confirm")
        self.assertEqual(len(r), 1, "one FAILED row, never retried")
        self.assertFalse(r[0]["ok"])
        self.assertIn("TimeoutError", r[0]["response_or_error"])
        self.assertTrue(any("TimeoutError" in f["error"] for f in p.state(CAL)["failed"]))

    def test_c_no_lit_cluster_no_zone(self):
        calls: list = []
        for live in (None, [], WALL, square(TABLE_AT, 0.05)):   # no view, empty, lit elsewhere, too few points
            p = self.props(calls=calls)
            self.feed(p, [obj()], n=6, live=live)
            self.assertEqual(self.auto(), [])
        self.assertEqual(calls, [], "no confirm call without a lit cluster")

    def test_d_low_p_no_zone(self):
        calls: list = []
        p = self.props(calls=calls)
        self.feed(p, [obj(p=sz.HAZARD_P_MIN - 0.05)], n=8)
        self.assertEqual((self.auto(), calls), ([], []))
        st = p.state(CAL)
        self.assertIn("low_p", json.dumps(st["gates"]))

    def test_e_the_poly_is_the_lit_cluster(self):
        p = self.props()
        self.feed(p, [obj()], n=4)
        z = self.auto()[0]
        want = {(round(x, 3), round(y, 3)) for x, y in square(TABLE_AT, 0.15)}
        self.assertEqual({(round(x, 3), round(y, 3)) for x, y in z["cells"]}, want)
        self.assertEqual(z["poly"], sz.polygon(sorted([list(c) for c in want]), CAL, RES))
        self.assertFalse(hasattr(sz, "blob"), "the flood fill over the accumulated grid is gone")


class Person(Base):
    def test_f_a_person_is_a_temporary_yellow_zone_from_lit_points(self):
        calls: list = []
        p = self.props(calls=calls)
        before = self.map.read_text()
        you = obj("o3", "person", 0.5, PERSON_AT)
        self.feed(p, [you], n=3)
        self.assertEqual(calls, [], "no model call for a person")
        self.assertEqual(self.map.read_text(), before, "never on ui/map.json")
        zs = [z for z in p.state(CAL)["zones"] if z["kind"] == "person"]
        self.assertEqual(len(zs), 1, zs)
        z = zs[0]
        self.assertEqual((z["name"], z["temporary"]), ("person-3", True))
        self.assertIsInstance(z["expires_at"], str)
        self.assertTrue((self.pics / z["photo"]["file"]).exists())
        self.assertEqual(z["photo"]["url"], "/pictures/" + z["photo"]["file"])
        self.assertEqual(z["poly"], sz.polygon(sorted(square(PERSON_AT, 0.1)), CAL, RES))
        self.assertEqual(len(self.tool("zone.person")), 1, "one row when it appears, never per frame")
        self.assertEqual(images._named(self.tool("zone.person")[0])[0][1], "scout", "listed by GET /images?kind=scout")
        cx, cy = np.mean(z["poly"], axis=0).tolist()
        route = [[cx - 200, cy], [cx + 200, cy]]
        self.assertIsNone(nogo.hit(route, nogo.zones(json.loads(self.map.read_text()))), "a route through a person still plans")
        self.t[0] += sz.PERSON_TTL_S + 1
        self.feed(p, [obj("o3", "person", 0.5, PERSON_AT, unseen=9)], n=1)
        self.assertEqual([z for z in p.state(CAL)["zones"] if z["kind"] == "person"], [])
        self.assertEqual(len(self.tool("zone.person_cleared")), 1)

    def test_f_a_person_with_no_lit_point_is_no_zone(self):
        p = self.props()
        self.feed(p, [obj("o3", "person", 0.9, PERSON_AT)], n=2, live=WALL)
        st = p.state(CAL)
        self.assertEqual([z for z in st["zones"] if z["kind"] == "person"], [])
        self.assertIn("person", st["why"] or "")


class Switch(Base):
    def test_g_the_values(self):
        for v, want, hazards, people in (("", "on", 1, 1), ("1", "on", 1, 1),
                                         ("person", "person only (WTDD_SCOUT_ZONES=person)", 0, 1),
                                         ("0", "off (WTDD_SCOUT_ZONES=0)", 0, 0)):
            with self.subTest(v), mock.patch.dict(os.environ, {"WTDD_SCOUT_ZONES": v}):
                shutil.copy(ROOT / "ui" / "map.json", self.map)
                calls: list = []
                p = self.props(calls=calls)
                self.feed(p, [obj(), obj("o3", "person", 0.5, PERSON_AT)], n=5)
                st = p.state(CAL)
                self.assertEqual(st["auto_zones"], want)
                self.assertEqual(len(self.auto()), hazards)
                self.assertEqual(len([z for z in st["zones"] if z["kind"] == "person"]), people)
                if not hazards:
                    self.assertEqual(calls, [], "no confirm call")
        with mock.patch.dict(os.environ, {"WTDD_SCOUT_ZONES": "yes"}):
            with self.assertRaisesRegex(ValueError, "WTDD_SCOUT_ZONES"):
                self.feed(self.props(), [obj()], n=1)


if __name__ == "__main__":
    unittest.main()
