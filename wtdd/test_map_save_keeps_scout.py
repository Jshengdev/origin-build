"""POST /map never drops the scout's auto zones (live 22:02: Johnny saved a routine from Paths and the save wrote the
page's copy of the zones over the file, so nogo-2 and nogo-3 "chair" (source scout) vanished, and the zone he drew took
the name nogo-2). The real handler on an ephemeral port, the map a temp file."""
from __future__ import annotations
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-map-save-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")

from wtdd import api  # noqa: E402

ROOMS = [{"name": "room", "poly": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]}]
SCOUT = {"name": "nogo-2", "label": "chair", "poly": [[100, 100], [140, 100], [140, 140], [100, 140]], "nogo": True,
         "source": "scout", "by": "auto", "kind": "hazard", "p": 0.95}


class MapSave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.map = Path(tempfile.mkdtemp(dir=_TMP)) / "map.json"
        self.map.write_text(json.dumps({"path": [[200, 200], [300, 200]], "stops": [], "rooms": ROOMS, "lights": [], "zones": [SCOUT]}))
        self.enterContext(mock.patch.object(api, "MAP", self.map))

    def post(self, body: dict) -> tuple[int, dict]:
        rq = urllib.request.Request(self.base + "/map", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(rq, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_a_page_save_keeps_the_scouts_zones_and_renames_a_clashing_drawn_zone(self):
        drawn = {"name": "nogo-2", "label": "no-go 2", "poly": [[400, 400], [480, 400], [480, 480], [400, 480]], "nogo": True}
        page = {"path": [[200, 200], [300, 250]], "stops": [], "rooms": ROOMS, "lights": [], "zones": [drawn],
                "_version": int(self.map.stat().st_mtime)}   # the page's copy never had the scout's zone
        code, out = self.post(page)
        self.assertEqual((code, out.get("ok")), (200, True), out)
        zones = json.loads(self.map.read_text())["zones"]
        scout = [z for z in zones if z.get("source") == "scout"]
        self.assertEqual([z["name"] for z in scout], ["nogo-2"], "the scout's zone survives a page save")
        mine = [z for z in zones if z.get("source") != "scout"]
        self.assertEqual(len(mine), 1)
        self.assertNotEqual(mine[0]["name"], "nogo-2", "a drawn zone never takes a scout zone's name")
        self.assertEqual(mine[0]["poly"], drawn["poly"])
        self.assertEqual(json.loads(self.map.read_text())["path"], page["path"], "the route the page saved is the route")


if __name__ == "__main__":
    unittest.main()
