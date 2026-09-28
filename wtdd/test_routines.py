"""Named routines through the real handler. Run: python -m unittest wtdd.test_routines -v
The demo's two routes (kitchen → bedroom 2, bedroom 2 → living room) are saved from ui/map.json's path, stops and
actions under a name (POST /routines {action: save, name}), listed (GET /routines), loaded back into the map with one
call each (load) and deleted (delete). A load replaces the route and nothing else (rooms, lights, zones, labels, policy,
entity and note untouched), keeps the map it replaced as map.prev.json and advances _version, so an open page's stale
POST /map is still a 409. Each action is one routine.saved / routine.loaded / routine.deleted row with the state before
and after. The refusals are a 400 (a name that is not 1 to 40 characters, an empty path, an unknown action) or a 404
naming the routines that exist, each on its failed row (an unknown action has no row: it names no step); a malformed
routines.json is a 500 naming it, never an empty list. The real handler on an ephemeral port in this process; the ledger
is WTDD_LEDGER set before wtdd.ledger is imported (and ledger.LEDGER patched, so no row reaches the real file whatever
imported it first), the map a temp file (api.MAP patched), and routines.json lands beside it. No dog, no lights."""
from __future__ import annotations
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

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-routines-test-"))
LEDGER = _TMP / "ledger.jsonl"
os.environ["WTDD_LEDGER"] = str(LEDGER)

from wtdd import api, ledger  # noqa: E402

MP = _TMP / "ui" / "map.json"
FILE = MP.with_name("routines.json")
K2B, B2L = "kitchen → bedroom 2", "bedroom 2 → living room"
KITCHEN_BED2 = {"path": [[330, 700], [340, 640], [360, 580]], "stops": [2],
                "actions": {"2": {"look": "tilt", "say": True, "ask": False}}}
BED2_LIVING = {"path": [[360, 580], [400, 700], [430, 900], [450, 1100]], "stops": [1, 3],
               "actions": {"1": {"look": "level", "say": True, "ask": False}, "3": {"look": "sit", "say": True, "ask": True}}}
REST = {"note": "the scratch map", "rooms": [{"name": "living room", "poly": [[255, 1040], [700, 1040], [700, 1440]]}],
        "lights": [{"id": "h1", "kind": "dot", "device": "hue", "pts": [[322, 991]], "room": "dining room"}],
        "zones": [{"name": "a", "label": "zone a", "poly": [[255, 1040], [400, 1040], [400, 1470]], "strip": False}],
        "labels": ["clear", "hazard", "person"], "policy": {"escalate": ["hazard", "person"]}, "entity": {"radius_px": 220}}
ROUTE = ("path", "stops", "actions")


class Routines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        MP.parent.mkdir()
        cls.patches = [mock.patch.object(api, "MAP", MP), mock.patch.object(ledger, "LEDGER", LEDGER)]
        for p in cls.patches:
            p.start()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        for p in cls.patches:
            p.stop()

    def setUp(self):
        LEDGER.write_text("")   # the test's scratch ledger: each test reads only its own rows
        for f in (FILE, MP.with_name("map.prev.json")):
            f.unlink(missing_ok=True)
        self.put({**REST, **KITCHEN_BED2})

    def put(self, m: dict) -> None:
        """m as the map a page saved a while ago (mtime 100 s back), so a write now must advance its _version."""
        MP.write_text(json.dumps(m, indent=2) + "\n")
        t = time.time() - 100
        os.utime(MP, (t, t))

    def call(self, method: str, path: str, body=None) -> tuple[int, dict]:
        req = urllib.request.Request(self.base + path, method=method, headers={"Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def save(self, name: str) -> dict:
        code, out = self.call("POST", "/routines", {"action": "save", "name": name})
        self.assertEqual(code, 200, out)
        return out

    def rows(self, tool: str) -> list[dict]:
        return [r for r in ledger.rows() if r["tool"] == tool]

    def test_save_lists_the_route_under_its_name(self):
        self.assertEqual(self.call("GET", "/routines"), (200, {"routines": [], "loaded": None}))   # no save yet: no file, nothing saved
        out = self.save(K2B)
        self.assertTrue(out["ok"])
        (r,) = out["routines"]
        self.assertEqual((r["name"], r["dots"], r["stops"]), (K2B, 3, [2]))
        self.assertRegex(r["saved_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertEqual(out["loaded"], K2B)   # the map's route is the one just saved
        self.assertEqual(self.call("GET", "/routines"), (200, {"routines": out["routines"], "loaded": K2B}))
        (kept,) = json.loads(FILE.read_text())["routines"]
        self.assertEqual({k: kept[k] for k in ROUTE}, KITCHEN_BED2)   # the route itself, actions included
        (row,) = self.rows("routine.saved")
        self.assertTrue(row["ok"], row)
        self.assertEqual((row["args"]["name"], row["state_before"]["names"], row["state_after"]["names"]), (K2B, [], [K2B]))

    def test_saving_a_name_again_replaces_that_routine(self):
        self.save(K2B)
        self.put({**REST, **BED2_LIVING})
        out = self.save(K2B)
        self.assertEqual([(r["name"], r["dots"]) for r in out["routines"]], [(K2B, 4)])

    def test_load_puts_the_route_on_the_map_and_keeps_the_rest(self):
        self.save(K2B)
        self.put({**REST, **BED2_LIVING})
        self.save(B2L)
        _, page = self.call("GET", "/map")   # the open page's copy, with its _version
        code, out = self.call("POST", "/routines", {"action": "load", "name": K2B})
        self.assertEqual(code, 200, out)
        m = json.loads(MP.read_text())
        self.assertEqual({k: m[k] for k in ROUTE}, KITCHEN_BED2)   # the route replaced
        self.assertEqual({k: v for k, v in m.items() if k not in ROUTE}, REST)   # rooms, lights, zones, labels, policy untouched
        self.assertEqual({k: v for k, v in json.loads(MP.with_name("map.prev.json").read_text()).items() if k in ROUTE}, BED2_LIVING)
        _, now = self.call("GET", "/map")
        self.assertGreater(now["_version"], page["_version"])
        self.assertEqual((out["_version"], out["loaded"]), (now["_version"], K2B))
        self.assertEqual(self.call("GET", "/routines")[1]["loaded"], K2B)
        code, err = self.call("POST", "/map", page)   # the stale page saves its old route with its old _version
        self.assertEqual(code, 409, err)
        self.assertEqual(json.loads(MP.read_text())["path"], KITCHEN_BED2["path"])   # and wrote nothing
        (row,) = self.rows("routine.loaded")
        self.assertTrue(row["ok"], row)
        self.assertEqual((row["state_before"]["loaded"], row["state_after"]["loaded"]), (B2L, K2B))
        self.assertEqual((row["state_before"]["_version"], row["state_after"]["_version"]), (page["_version"], now["_version"]))

    def test_delete_drops_the_name_and_leaves_the_map(self):
        self.save(K2B)
        self.save(B2L)
        code, out = self.call("POST", "/routines", {"action": "delete", "name": K2B})
        self.assertEqual(code, 200, out)
        self.assertEqual([r["name"] for r in out["routines"]], [B2L])
        self.assertEqual(json.loads(MP.read_text())["path"], KITCHEN_BED2["path"])   # the route stays on the map; only its name goes
        (row,) = self.rows("routine.deleted")
        self.assertTrue(row["ok"], row)
        self.assertEqual((row["state_before"]["names"], row["state_after"]["names"]), ([K2B, B2L], [B2L]))

    def test_refusals_are_a_plain_reason_and_a_failed_row(self):
        self.save(K2B)
        for name in ("", "   ", "x" * 41, None, 7):
            with self.subTest(name=name):
                code, out = self.call("POST", "/routines", {"action": "save", "name": name})
                self.assertEqual((code, out["ok"]), (400, False), out)
                self.assertIn("name", out["error"])
        self.save("x" * 40)   # 40 characters is a name
        code, out = self.call("POST", "/routines", {"action": "load", "name": "bedroom 3"})
        self.assertEqual((code, out["ok"]), (404, False), out)
        self.assertIn("bedroom 3", out["error"])
        self.assertIn(K2B, out["error"])   # it names the routines that exist
        self.assertEqual(json.loads(MP.read_text())["path"], KITCHEN_BED2["path"])   # the refused load wrote no map
        self.assertFalse(MP.with_name("map.prev.json").exists())
        self.assertEqual(self.call("POST", "/routines", {"action": "delete", "name": "bedroom 3"})[0], 404)
        code, out = self.call("POST", "/routines", {"action": "walk", "name": K2B})
        self.assertEqual((code, out["ok"]), (400, False), out)
        self.put({**REST, "path": [], "stops": [], "actions": {}})
        code, out = self.call("POST", "/routines", {"action": "save", "name": "empty"})
        self.assertEqual((code, out["ok"]), (400, False), out)
        self.assertIn("path", out["error"])
        self.assertEqual([r["name"] for r in json.loads(FILE.read_text())["routines"]], [K2B, "x" * 40])   # nothing refused was kept
        self.assertEqual([r["ok"] for r in self.rows("routine.saved")], [True, False, False, False, False, False, True, False])
        self.assertEqual([r["ok"] for r in self.rows("routine.loaded")], [False])
        self.assertEqual([r["ok"] for r in self.rows("routine.deleted")], [False])
        self.assertEqual(len(ledger.rows()), 10)   # the unknown action wrote no row

    def test_a_malformed_file_is_a_500_naming_it(self):
        FILE.write_text("{not json")
        code, out = self.call("GET", "/routines")
        self.assertEqual(code, 500, out)
        self.assertIn("routines.json", out["error"])
        code, out = self.call("POST", "/routines", {"action": "load", "name": K2B})
        self.assertEqual((code, out["ok"]), (500, False), out)
        self.assertIn("routines.json", out["error"])
        (row,) = self.rows("routine.loaded")
        self.assertFalse(row["ok"])


if __name__ == "__main__":
    unittest.main()
