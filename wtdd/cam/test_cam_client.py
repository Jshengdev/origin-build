"""The laptop's camera client on an armed sighting (item 18, review fix round 2). Run alone:

    python -m unittest wtdd.cam.test_cam_client -v

person_seen() now answers an armed person with {dispatched: True, trigger} (the dispatch tool runs on a thread), not
09's {asked, why}. The client (python -m wtdd.cam) prints one stderr line per frame from that answer; reading the old
key, it died on the first armed sighting: no more frames, the Cams panel stale, the next sighting never posted. Here
the client posts the fixture frame once while armed and must exit 0 and say which dispatch it started.

It reuses wtdd/cam/test_cam.py whole: imported FIRST, so its scratch ledger, memory and cams are set before the package
loads; its setUpModule/tearDownModule (the real API handler on an ephemeral port) and its Case (the fake detector).
The dispatch tool itself is patched: wtdd/test_dispatch.py tests what it does. wtdd/cam/test_cam.py is not edited."""
from wtdd.cam import test_cam as tc  # first: its environment must be in place before any other wtdd import

import io  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
from contextlib import redirect_stderr, redirect_stdout  # noqa: E402
from unittest import mock  # noqa: E402

setUpModule, tearDownModule = tc.setUpModule, tc.tearDownModule


class ArmedClient(tc.Case):
    def test_an_armed_sighting_is_dispatched_and_the_client_lives(self):
        from wtdd import tools
        from wtdd.cam import __main__ as client
        armed = tc._TMP / "client-armed.on"
        armed.write_text("2026-09-26T00:00:00\n")
        calls, called = [], threading.Event()

        def fake_call(tool, **kw):
            calls.append((tool, kw))
            called.set()
            return {"phase": "asked"}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(tc.cam, "ARMED", armed), mock.patch.dict(tc.cam._last, clear=True), \
                mock.patch.object(tools, "call", fake_call), redirect_stdout(out), redirect_stderr(err):
            rc = client.main(["--server", tc.url(), "--cam", "lap1", "--source", str(tc.FIX / "frame.jpg"), "--once"])
            self.assertTrue(called.wait(5), "the server never handed the person to dispatch")
        self.assertEqual(rc, 0, err.getvalue()[-600:])
        printed = json.loads(out.getvalue().strip().splitlines()[-1])
        trig = printed["person"]["trigger"]
        self.assertTrue(printed["person"]["dispatched"], printed)
        self.assertEqual([(t, kw["trigger"]) for t, kw in calls], [("dispatch", trig)])
        self.assertIn(f"person dispatched {trig}", err.getvalue(), "the client's frame line names the dispatch it started")
