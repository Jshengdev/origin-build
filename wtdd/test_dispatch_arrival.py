"""Dispatch's arrival when the dog's own detector FAILED (item 18, review fix round 1). Run alone:

    python -m unittest wtdd.test_dispatch_arrival -v

dog_say.look_and_see catches a detector failure and returns detector {"error": ...} (no classes, or the floor's classes
when only the picked frame's box failed). Read as "no person", the one local person check at the camera's spot would
fall open without a word: a plain "here's what i see" post and an `arrived` page with no error. Here a failed detector
is said in the thread ("detector FAILED") and carried on the page's error, and still never sounds the alarm.

It reuses wtdd/test_dispatch.py whole: imported FIRST, so its scratch ledger, memory, cams and forced-empty keys are set
before the package loads; its setUpModule/tearDownModule (the scratch map and grid) and its RunCase (the fake session,
post, look, intruder_alarm and light_alarm). wtdd/test_dispatch.py, committed RED at ef578e9, is not edited."""
from wtdd import test_dispatch as td  # first: its environment must be in place before any other wtdd import

setUpModule, tearDownModule = td.setUpModule, td.tearDownModule
ERR = "RuntimeError: detector subprocess died"


class DetectorFailed(td.RunCase):
    def test_a_failed_detector_on_arrival_is_said_in_the_thread_and_on_the_page(self):
        cases = {"the detector never ran": {"error": ERR},
                 "the floor was boxed, the picked frame's box failed": {"classes": {"laptop": 1}, "n": 1, "error": ERR}}
        for k, (name, det) in enumerate(cases.items()):
            with self.subTest(name):
                self.s, self.posts[:] = td.FakeSession(self.out), []
                self.look.return_value = {**td.SEEN, "text": "a person stands by the door.", "person": True, "detector": det}
                out = self.D.run("lap1", approved=True, trigger=f"cam:lap1:{1790000100 + k}", by=td.HOUSEMATE)
                self.assertEqual(len(self.posts), 1, self.posts)
                self.assertIn("detector FAILED", self.posts[0]["text"], "the thread is told the local person check did not run")
                self.assertIn("a person stands by the door.", self.posts[0]["text"])
                self.assertEqual(self.posts[0]["file"], td.SEEN["file"])
                pg = self.page()
                self.assertEqual(pg["phase"], "arrived")
                self.assertIn("detector FAILED", str(pg["error"]), "the page carries the detector's failure")
                self.assertIn(ERR, str(pg["error"]))
                self.assertEqual(out["error"], pg["error"])
                self.who.assert_not_called()
                self.alarm.assert_not_called()
