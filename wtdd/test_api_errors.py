"""B9 · every API error answers with its reason. Run: python -m unittest wtdd.test_api_errors -v
An exception raised in wtdd/api.py outside a route's own try used to drop the connection with no reply, so the remote
(and v2's proxy) showed a generic failure with no reason. These checks run the real handler on an ephemeral port in this
process and send the inputs that raised there: GET /ledger?n=x, a missing or corrupt ui/map.json on GET /map, an
unreadable evals.json on GET /evals, POST /map/restore with no saved route, and a body that is not JSON on POST /map,
/intruder, /dog/drive, /dog/grid, /dog/scale, /dog/scout and /tools/<name>. Each must be an HTTP 500 in today's envelope:
GET {error: "<Type>: <msg>"}, POST {ok: false, error: "<Type>: <msg>"}. Map, route and repo files are temp copies
(api.MAP, api.UI and api.ROOT patched), the ledger is WTDD_LEDGER set before wtdd.ledger is imported; no dog is touched
(a bad body fails before DogSession.get())."""
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

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-api-errors-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")

from wtdd import api  # noqa: E402


class Errors(unittest.TestCase):
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
        self.dir = Path(tempfile.mkdtemp(dir=_TMP))
        for target, value in (("MAP", self.dir / "map.json"), ("UI", self.dir), ("ROOT", self.dir)):
            p = mock.patch.object(api, target, value)
            p.start()
            self.addCleanup(p.stop)

    def req(self, path, body=None):
        """(status, parsed JSON) for an answer, (None, why) for a connection dropped with no reply."""
        rq = urllib.request.Request(self.base + path, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(rq, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
        except Exception as e:  # noqa: BLE001  (the bug: no HTTP reply at all)
            return None, f"dropped with no reply: {type(e).__name__}: {e}"

    def assertAnswers(self, path, body, envelope, error_type):
        code, got = self.req(path, body)
        self.assertEqual(code, 500, f"{path}: {got}")
        self.assertEqual(sorted(got), sorted([*envelope, "error"]), f"{path}: {got}")
        for k, v in envelope.items():
            self.assertEqual(got[k], v, path)
        self.assertTrue(got["error"].startswith(error_type + ": "), f"{path}: {got}")

    def test_get_a_bad_ledger_count_answers(self):
        self.assertAnswers("/ledger?n=x", None, {}, "ValueError")

    def test_get_a_missing_map_answers(self):
        self.assertAnswers("/map", None, {}, "FileNotFoundError")

    def test_get_a_corrupt_map_answers(self):
        (self.dir / "map.json").write_text("{not json")
        self.assertAnswers("/map", None, {}, "JSONDecodeError")

    def test_get_a_corrupt_evals_file_answers(self):
        (self.dir / "evals.json").write_text("{not json")
        self.assertAnswers("/evals", None, {}, "JSONDecodeError")

    def test_post_restore_with_no_saved_route_answers(self):
        (self.dir / "map.json").write_text('{"path": []}')
        self.assertAnswers("/map/restore", b"", {"ok": False}, "FileNotFoundError")
        self.assertFalse((self.dir / "map.prev.json").exists(), "a failed restore must not touch the map")

    def test_post_a_body_that_is_not_json_answers(self):
        for path in ("/map", "/intruder", "/dog/drive", "/dog/grid", "/dog/scale", "/dog/scout", "/tools/lights_status"):
            with self.subTest(path=path):
                self.assertAnswers(path, b"{not json", {"ok": False}, "JSONDecodeError")
        self.assertFalse((self.dir / "map.json").exists(), "a refused save must not write the map")
        self.assertFalse((self.dir / "intruder.on").exists(), "a refused arm must not arm the watch")


if __name__ == "__main__":
    unittest.main()
