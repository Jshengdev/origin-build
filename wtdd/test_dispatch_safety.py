"""Dispatch's safety holes found in review (item 18, fix round 2). Run alone:

    python -m unittest wtdd.test_dispatch_safety -v

  Approval       approved=true is a person's yes only when the thread says so: an ok intruder.verdict row asking this
                 trigger, "approved", younger than QUESTION_S, for a trigger naming this camera. The tool (every way in:
                 the listener's POST /tools/dispatch, the model loop, the CLI) refuses anything else before a plan or a
                 step, with one FAILED dispatch.decided row; the row's `by` is the verdict's sender, never the caller's.
  GradeApproval  grade(): a person's dispatch.decided (app imessage) with no "approved" verdict before it is unsafe.
  AskRace        one question at a time holds through the ask's own post: a question that opens before or while the
                 ask is posted wins; pending.json is left as that question wrote it, the page and a row say why.
  RefusedSighting  a camera's person that dispatch refuses reaches the thread named, with the camera's frame
                 (the open-question refusal stays text only: the dog's own question is the one being asked).
  Recheck        a calibration loaded from disk and not confirmed (DogSession.recheck) is "not calibrated".

It reuses wtdd/test_dispatch.py whole: imported FIRST, so its scratch ledger, memory, cams and forced-empty keys are set
before the package loads; its setUpModule/tearDownModule and RunCase (the fake session, post, look, alarms).
wtdd/test_dispatch.py, committed RED at ef578e9, is not edited."""
from wtdd import test_dispatch as td  # first: its environment must be in place before any other wtdd import

import copy  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

setUpModule, tearDownModule = td.setUpModule, td.tearDownModule
MODEL_SAYS = "+15559999999"   # a caller's claimed `by`: never what the row records


def verdict(trigger: str, said: str = "approved", ago_s: float = 0.0, sender: str = td.HOUSEMATE) -> None:
    """The listener's row for a reply to "send the dog? yes / no" (wtdd/chat/listen.py verdict, kind dispatch)."""
    td.ledger.append({"ts": (datetime.now() - timedelta(seconds=ago_s)).strftime("%Y-%m-%dT%H:%M:%S"), "step": "intruder.verdict",
                      "agent": "central", "tool": "intruder.verdict", "app": "imessage", "ok": True,
                      "args": {"from": sender, "text": "yes" if said == "approved" else "no", "guid": f"g-{trigger}", "asked": trigger},
                      "state_before": None, "state_after": {"verdict": said}, "response_or_error": None, "latency_ms": 0})


class Approval(td.RunCase):
    def call(self, **kw):
        from wtdd import tools
        return tools.call("dispatch", **kw)

    def test_approved_without_a_yes_on_the_thread_is_refused_before_anything_plans(self):
        base = 1790001000
        verdict(f"cam:lap1:{base + 1}", said="declined")
        verdict(f"cam:lap1:{base + 2}0")                       # a yes, to another question
        verdict(f"cam:lap1:{base + 3}", ago_s=400)             # a yes, long expired
        verdict(f"cam:lap1:{base + 4}")                        # a yes about lap1, spent on another camera below
        cases = {"no reply at all": ("lap1", base), "a no": ("lap1", base + 1), "a yes to another question": ("lap1", base + 2),
                 "a stale yes": ("lap1", base + 3), "a yes about another camera": ("gate2", base + 4)}
        for name, (cam, epoch) in cases.items():
            with self.subTest(name):
                trig, n0, self.posts[:] = f"cam:lap1:{epoch}", len(td.ledger.rows()), []
                with self.assertRaises(ValueError) as cm:
                    self.call(cam=cam, approved=True, trigger=trig, by=MODEL_SAYS)
                self.assertIn("approved without a person's yes on the thread", str(cm.exception))
                self.assertEqual(td.rows_since(n0, "plan.route"), [], "refused before any plan")
                dec = td.rows_since(n0, "dispatch.decided")
                self.assertEqual([(r["ok"], r["app"], r["args"]["trigger"]) for r in dec], [(False, "imessage", trig)])
                self.assertIn("approved without", dec[0]["response_or_error"])
                self.assertEqual((self.s.follows, self.posts), ([], []))

    def test_a_yes_on_the_thread_walks_and_the_row_names_who_said_it(self):
        trig = "cam:lap1:1790002000"
        verdict(trig)
        out = self.call(cam="lap1", approved=True, trigger=trig, by=MODEL_SAYS)
        self.assertEqual(out["phase"], "arrived")
        self.assertEqual(len(self.s.follows), 1)
        dec = td.rows_since(self.n0, "dispatch.decided")
        self.assertEqual([(r["ok"], r["app"], r["args"]["by"]) for r in dec], [(True, "imessage", td.HOUSEMATE)],
                         "by is the verdict's sender, never the caller's word")


class GradeApproval(unittest.TestCase):
    def test_a_persons_dispatch_with_no_approved_verdict_is_unsafe(self):
        def no_ask_no_reply(rows):   # the approved run alone: nobody was asked, nobody said yes
            del rows[2:11]

        def a_no(rows):
            rows[td.at(rows, "intruder.verdict")]["state_after"]["verdict"] = "declined"
        for fn in (no_ask_no_reply, a_no):
            with self.subTest(fn.__name__):
                rows = copy.deepcopy(td.fixture())
                fn(rows)
                g, why = td.D().grade(rows)
                self.assertEqual(g, "unsafe", why)
                self.assertIn("intruder.verdict", why)
        g, why = td.D().grade(td.fixture())
        self.assertEqual(g, "pass", why)


class AskRace(td.RunCase):
    WHO = {"kind": "who_dis", "t": 0.0, "trigger": "alarm:watch:1", "seconds": 5}

    def test_a_question_that_opens_before_or_while_the_ask_is_posted_wins(self):
        real_post, real_stub = td.chat_post.run, self.D.stub   # RunCase's fake post; the module's stub

        def during_decision(state):   # watch.py -> intruder_alarm opens a who-dis while dispatch decides
            self.pending.write_text(json.dumps(self.who))
            return real_stub(state)

        def during_post(text="", file=None, trigger=None):   # ... or while the ask is in flight (3.4 s on the fixture)
            out = real_post(text=text, file=file, trigger=trigger)
            if "send the dog?" in text:
                self.pending.write_text(json.dumps(self.who))
            return out
        cases = {"before the ask": ((self.D, "stub", during_decision), False),
                 "while the ask is posted": ((td.chat_post, "run", during_post), True)}
        for k, (name, (patch, asked)) in enumerate(cases.items()):
            with self.subTest(name):
                self.s, self.posts[:] = td.FakeSession(self.out), []
                self.pending.unlink(missing_ok=True)
                self.who = {**self.WHO, "t": time.time()}
                n0 = len(td.ledger.rows())
                with td.mock.patch.object(*patch), self.assertRaises(RuntimeError):
                    self.D.run("lap1", trigger=f"cam:lap1:{1790003000 + k}", file=str(td.FRAME))
                self.assertEqual(json.loads(self.pending.read_text()), self.who, "the dog's own question is left as it wrote it")
                pg = self.page()
                self.assertEqual(pg["phase"], "failed")
                self.assertIn("question open", pg["error"])
                dec = td.rows_since(n0, "dispatch.decided")
                self.assertEqual([r["ok"] for r in dec], [True, False], "the decision, then the refusal naming why")
                self.assertIn("question open", dec[1]["response_or_error"])
                texts = [p["text"] for p in self.posts]
                self.assertEqual(texts[:-1], [self.D.ask_line(td.CAM)] if asked else [], texts)
                self.assertTrue(texts[-1].startswith("couldn't dispatch: question open"), texts)
                self.assertIsNone(self.posts[-1]["file"], "two eyes: the refusal is text only")
                self.assertEqual(self.s.follows, [])


class RefusedSighting(td.RunCase):
    def test_a_refused_sighting_is_named_with_the_cameras_frame(self):
        cases = {"not calibrated": ("lap1", lambda s: setattr(s, "cal", None)),
                 "following": ("lap1", lambda s: s.follow_state.update(active=True)),
                 "recording": ("lap1", lambda s: setattr(s, "rec", {"points": [], "marks": []})),
                 "no route": ("gate2", lambda s: None)}
        for k, (why, (cam, arrange)) in enumerate(cases.items()):
            with self.subTest(why):
                self.s, self.posts[:] = td.FakeSession(self.out), []
                arrange(self.s)
                n0 = len(td.ledger.rows())
                self.refused(cam, trigger=f"cam:{cam}:{1790004000 + k}", file=str(td.FRAME))
                self.assert_refused_loud(why, n0)
                c = next(x for x in (td.CAM, td.CAM_NOGO) if x["id"] == cam)
                text = self.posts[0]["text"]
                self.assertIn(f"person at camera {cam}", text, "the person on call learns a person is at the camera")
                self.assertIn(c["label"], text)
                self.assertEqual(self.posts[0]["file"], str(td.FRAME), "with the camera's frame")
        with self.subTest("question open"):   # two eyes: the dog's own question is the one being asked; text only
            self.s, self.posts[:] = td.FakeSession(self.out), []
            self.pending.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "trigger": "alarm:g1:22", "seconds": 5}))
            self.refused("lap1", trigger="cam:lap1:1790004100", file=str(td.FRAME))
            self.assertEqual(len(self.posts), 1, self.posts)
            self.assertIsNone(self.posts[0]["file"])


class Recheck(td.RunCase):
    def test_a_loaded_unconfirmed_calibration_is_not_calibrated(self):
        self.s.recheck = True   # DogSession loads dog_cal.json on an API restart with recheck = True: not confirmed
        n0 = len(td.ledger.rows())
        self.refused("lap1", trigger="cam:lap1:1790005000")
        self.assert_refused_loud("not calibrated", n0)
        self.assertIn("not confirmed", td.rows_since(n0, "dispatch.decided")[0]["response_or_error"])
        self.assertEqual(td.rows_since(n0, "plan.route"), [], "refused before planning")
        self.assertEqual(self.page()["phase"], "failed")


if __name__ == "__main__":
    unittest.main()
