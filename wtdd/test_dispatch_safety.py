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
Fix round 3:
  Affirm         a reply walks the dog only when the whole reply is a short yes: "ok, no", "go away", "y is the dog
                 barking", "send help", "do it later" stand down (the ask goes to a group; any housemate may answer).
  Sighting       the tool (every way in but a person's yes) reads the device's own sighting first: the newest ok
                 cam.detect row for this camera must box a person and be under COOLDOWN_S old, else a FAILED row "no
                 person seen", before a plan, a model or an ask. The ask's photo is the frame the caller handed in (the
                 camera hook's copy of the sighting), never a file found on disk. A dry run with no sighting plans,
                 says so in its words, and the stub decides (no model reads about a person nobody saw).
  DryStandIn     a dry run with no API stands the saved grid's calibration in for the dog's pose: its decision row
                 is cached, source ui/grid.json (or the stub's), never a live row.
  GradeRefusal   a refusal decides nothing, so it is never "a model before the local detector" (U3); a decision on
                 words with no cam.detect before it still is.
Fix round 4:
  AnyFailure     any exception inside a run, not only the named refusals (an unreadable ui/grid.json, a sighting that
                 cannot be read from the ledger), is one FAILED dispatch.decided naming it, the page's failed phase
                 naming it and one text-only "couldn't dispatch" (never in dry): on the camera hook's thread there is
                 no caller to see a traceback.
  OneYes         one person's yes is one walk: a second approved call on the same verdict (POST /tools/dispatch, the
                 model loop, the CLI) is one FAILED dispatch.decided (app imessage), "this yes already sent the dog",
                 before any plan or follow.
  QuestionWords  the open-question refusal is worded in the thread by the question's kind, with no trigger key: a
                 dispatch's own ask is "still waiting for a yes on the last ask about camera <id>" (no dog's eye is
                 involved, and the ask is not withdrawn); a who-dis or a decide is "the dog's own question is open".
                 The key and the kind stay on the row.
Fix round 5 (the independent review's probes):
  Armed          nothing dispatches while the intruder watch is off (intruder.on absent, the file the camera hook reads):
                 a yes that comes after the watch was switched off (probe 1), and a tool call with a person boxed
                 (probe 2), are each one FAILED dispatch.decided "not armed", the failed page and one text-only
                 "couldn't dispatch", with no plan.route, no model, no ask and no follow. A dry run is not refused.
  WalkRecheck    a question that opens while an approved run plans and decides (the dog's own who-dis, probe 4) stops
                 the walk before s.follow: one FAILED dispatch.decided naming it, no follow, its pending.json untouched.

It reuses wtdd/test_dispatch.py whole: imported FIRST, so its scratch ledger, memory, cams and forced-empty keys are set
before the package loads; its setUpModule/tearDownModule and RunCase (the fake session, post, look, alarms).
wtdd/test_dispatch.py, committed RED at ef578e9, is not edited."""
from wtdd import test_dispatch as td  # first: its environment must be in place before any other wtdd import

import copy  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

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
                self.assertEqual(texts[-1], "couldn't dispatch: the dog's own question is open", texts)
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
            self.assertEqual(self.posts[0]["text"], "couldn't dispatch: the dog's own question is open")


class Recheck(td.RunCase):
    def test_a_loaded_unconfirmed_calibration_is_not_calibrated(self):
        self.s.recheck = True   # DogSession loads dog_cal.json on an API restart with recheck = True: not confirmed
        n0 = len(td.ledger.rows())
        self.refused("lap1", trigger="cam:lap1:1790005000")
        self.assert_refused_loud("not calibrated", n0)
        self.assertIn("not confirmed", td.rows_since(n0, "dispatch.decided")[0]["response_or_error"])
        self.assertEqual(td.rows_since(n0, "plan.route"), [], "refused before planning")
        self.assertEqual(self.page()["phase"], "failed")


def detect(cam: str, classes: dict, ago_s: float = 0.0) -> None:
    """A camera's cam.detect row as wtdd/cam ingest writes it, ago_s seconds back."""
    td.ledger.append({"ts": (datetime.now() - timedelta(seconds=ago_s)).strftime("%Y-%m-%dT%H:%M:%S"), "step": "cam.detect",
                      "agent": "cam", "tool": "cam.detect", "app": "yolo", "ok": True,
                      "args": {"cam": cam, "shift_id": "2026-09-27-test", "model": "yolo11n.pt", "classes": classes, "boxes": []},
                      "state_before": None, "state_after": {"classes": classes, "n": sum(classes.values()), "file": f"{cam}-boxed.jpg"},
                      "response_or_error": None, "latency_ms": 1200})


class Fresh(td.RunCase):
    """RunCase on a ledger of its own: the sighting is read from the ledger, so no other test's rows may count."""

    def setUp(self):
        super().setUp()
        self.enterContext(td.mock.patch.object(td.ledger, "LEDGER", Path(tempfile.mkdtemp(prefix="wtdd-dispatch-fresh-")) / "ledger.jsonl"))
        self.n0 = 0

    def call(self, **kw):
        from wtdd import tools
        return tools.call("dispatch", **kw)


class Affirm(unittest.TestCase):
    setUp, answer = td.Verdict.setUp, td.Verdict.answer

    def test_only_a_whole_short_yes_walks(self):
        for text in ("ok, no", "ok wait", "sure, no thanks", "go away", "okay dont", "ok no dont send it", "y is the dog barking",
                     "sure is cold tonight", "ok lol", "send help", "do it later", "yes but not now", "no"):
            with self.subTest(text):
                self.posts.clear()
                calls, alarm, rows = self.answer(text, 0.3)
                self.assertEqual(calls, [], "nothing is sent")
                self.assertEqual(rows[0]["state_after"]["verdict"], "declined")
                self.assertEqual([p[1] for p in self.posts], ["ok, standing down"])
                alarm.assert_not_called()
        for text in ("yes", "Go.", "yep", "send it", "do it", "Yes please", "ok go", "yes, send the dog", "Sure!"):
            with self.subTest(text):
                self.posts.clear()
                calls, alarm, rows = self.answer(text, 3.0)
                self.assertEqual([(t, kw.get("approved")) for t, kw in calls], [("dispatch", True)], text)
                self.assertEqual(rows[0]["state_after"]["verdict"], "approved")


class Sighting(Fresh):
    def test_no_young_person_at_this_camera_is_refused_before_a_plan_a_model_or_an_ask(self):
        jev = td.mock.Mock(side_effect=AssertionError("no model reads about a person nobody saw"))
        cases = {"no detection at all": lambda: None,
                 "a person over COOLDOWN_S ago": lambda: detect("lap1", {"person": 1}, ago_s=90),
                 "a person at another camera": lambda: detect("gate2", {"person": 1}, ago_s=1),
                 "the newest detection has no person": lambda: (detect("lap1", {"person": 1}, 2), detect("lap1", {"laptop": 1}, 1))}
        with self.env(JEV_API_KEY="k"), td.mock.patch.object(td.decide.requests, "post", jev):
            for k, (name, arrange) in enumerate(cases.items()):
                with self.subTest(name):
                    self.s, self.posts[:] = td.FakeSession(self.out), []
                    arrange()
                    n0 = len(td.ledger.rows())
                    with self.assertRaises(RuntimeError) as cm:
                        self.call(cam="lap1", trigger=f"cam:lap1:{1790006000 + k}", file=str(td.FRAME))
                    self.assertIn("no person seen at camera lap1", str(cm.exception))
                    rows = td.rows_since(n0)
                    self.assertEqual([(r["tool"], r["ok"]) for r in rows], [("dispatch.decided", False)], "refused before any plan")
                    self.assertIn("no person seen at camera lap1", rows[0]["response_or_error"])
                    self.assertEqual(len(self.posts), 1, self.posts)
                    self.assertTrue(self.posts[0]["text"].startswith("couldn't dispatch: no person seen at camera lap1"), self.posts)
                    self.assertIsNone(self.posts[0]["file"], "a frame nobody boxed a person in is never posted")
                    self.assertEqual((self.s.follows, self.pending.exists(), self.page()["phase"]), ([], False, "failed"))
                    g, why = td.D().grade(rows)
                    self.assertNotEqual(g, "unsafe", why)
        jev.assert_not_called()

    def test_a_young_person_asks_with_the_frame_handed_in_never_one_found_on_disk(self):
        from wtdd import cam
        cam.cams().mkdir(parents=True, exist_ok=True)
        (cam.cams() / "lap1-boxed.jpg").write_bytes(b"a later frame, maybe with nobody in it")
        for k, file in enumerate((str(td.FRAME), None)):
            with self.subTest(file=file):
                self.s, self.posts[:] = td.FakeSession(self.out), []
                self.pending.unlink(missing_ok=True)
                detect("lap1", {"person": 1}, ago_s=1)
                out = self.call(cam="lap1", trigger=f"cam:lap1:{1790006100 + k}", file=file)
                self.assertEqual(out["phase"], "asked")
                self.assertEqual([(p["text"], p["file"]) for p in self.posts], [(self.D.ask_line(td.CAM), file)])

    def test_dry_with_no_sighting_never_claims_a_person_and_never_asks_a_model(self):
        jev = td.mock.Mock(side_effect=AssertionError("no model reads about a person nobody saw"))
        with self.env(JEV_API_KEY="k"), td.mock.patch.object(td.decide.requests, "post", jev):
            out = self.call(cam="lap1", dry=True, trigger="cam:lap1:1790006200")
        jev.assert_not_called()
        self.assertEqual((out["phase"], self.posts, self.s.follows), ("decided", [], []))
        self.assertNotIn("a person is in view", out["state"])
        self.assertIn("no person", out["state"])
        dec = td.rows_since(0, "dispatch.decided")
        self.assertEqual([(r["ok"], r["app"], r["cached"], r["source"]) for r in dec], [(True, "stub", True, "stub")])
        g, why = td.D().grade(td.ledger.rows())
        self.assertNotEqual(g, "unsafe", why)


class DryStandIn(Fresh):
    def test_a_dry_run_with_no_api_never_writes_a_live_decision(self):
        post = td.jev("dispatch", {"dispatch": 0.83, "ask": 0.12, "ignore": 0.05})
        grid = td.ROOT / "wtdd" / "fixtures" / "grid_wall.json"
        with self.env(JEV_API_KEY="k"), td.mock.patch.object(td.decide.requests, "post", post), \
                td.mock.patch.object(td.session, "GRID_FILE", grid), td.mock.patch.dict(os.environ):
            os.environ.pop("WTDD_API_PROCESS")   # the CLI: no API in this process, the saved grid's calibration stands in
            for k, seen in enumerate((False, True)):
                with self.subTest(seen=seen):
                    if seen:
                        detect("lap1", {"person": 1}, ago_s=1)
                    n0 = len(td.ledger.rows())
                    out = self.call(cam="lap1", dry=True, trigger=f"cam:lap1:{1790006300 + k}")
                    self.assertEqual(out["phase"], "decided")
                    (r,) = td.rows_since(n0, "dispatch.decided")
                    self.assertEqual((r["app"], r["cached"], r["source"]), ("openrouter", True, "ui/grid.json") if seen else ("stub", True, "stub"))
        self.assertEqual(post.call_count, 1, "the model read the words once, about the person the camera saw")
        self.assertEqual([r for r in td.ledger.rows() if r["tool"] == "dispatch.decided" and r["source"] == "live"], [])


class GradeRefusal(unittest.TestCase):
    ROW = {"ts": "2026-09-27T01:00:00", "step": "dispatch.decided", "agent": "dispatch", "tool": "dispatch.decided", "ok": False,
           "cached": False, "source": "live", "state_before": None, "state_after": None, "latency_ms": 3}

    def test_a_refusal_decides_nothing_and_is_never_a_model_before_the_detector(self):
        refusals = {"not calibrated, a key set": {**self.ROW, "app": "openrouter", "args": {"cam": "lap1", "state_chars": 0},
                                                  "response_or_error": "RuntimeError: not calibrated: no believed pose"},
                    "approved with no yes": {**self.ROW, "app": "imessage", "args": {"cam": "lap1", "approved": True},
                                             "response_or_error": "ValueError: approved without a person's yes on the thread"}}
        for name, row in refusals.items():
            with self.subTest(name):
                g, why = td.D().grade([row])
                self.assertEqual(g, "fail", why)
        words = {**self.ROW, "ok": True, "app": "openrouter", "args": {"cam": "lap1", "state_chars": 283},
                 "state_after": {"choice": "ask"}, "response_or_error": "{}"}
        g, why = td.D().grade([words])
        self.assertEqual(g, "unsafe", why)
        self.assertIn("cam.detect", why)


class AnyFailure(Fresh):
    def assert_failed_loud(self, err: str, posts: int = 1):
        dec = td.rows_since(0, "dispatch.decided")
        self.assertEqual([r["ok"] for r in dec], [False], "exactly one FAILED dispatch.decided")
        self.assertIn(err, dec[0]["response_or_error"])
        pg = self.page()
        self.assertEqual(pg["phase"], "failed")
        self.assertIn(err, pg["error"])
        self.assertEqual(len(self.posts), posts, self.posts)
        if posts:
            self.assertTrue(self.posts[0]["text"].startswith("couldn't dispatch:"), self.posts)
            self.assertIn(err, self.posts[0]["text"])
            self.assertIsNone(self.posts[0]["file"], "text only")
        self.assertEqual((self.s.follows, self.pending.exists()), ([], False))

    def test_an_unreadable_saved_grid_is_one_failed_row_the_failed_page_and_one_post(self):
        bad = Path(tempfile.mkdtemp(prefix="wtdd-dispatch-bad-grid-")) / "grid.json"
        bad.write_text('{"cells": ')
        with td.mock.patch.object(td.session, "GRID_FILE", bad):
            with self.subTest("the API: no LiDAR grid in the session, the saved one is read"):
                self.s.grid = None
                with self.assertRaises(RuntimeError) as cm:
                    self.D.run("lap1", trigger="cam:lap1:1790007000")
                self.assertIn("JSONDecodeError", str(cm.exception))
                self.assert_failed_loud("JSONDecodeError")
            with self.subTest("dry with no API: the CLI reads the saved grid"), td.mock.patch.dict(os.environ):
                os.environ.pop("WTDD_API_PROCESS")
                self.enterContext(td.mock.patch.object(td.ledger, "LEDGER", Path(tempfile.mkdtemp(prefix="wtdd-dispatch-fresh-")) / "ledger.jsonl"))
                self.posts[:] = []
                self.out.unlink(missing_ok=True)
                with self.assertRaises(RuntimeError):
                    self.D.run("lap1", dry=True, trigger="cam:lap1:1790007001")
                self.assert_failed_loud("JSONDecodeError", posts=0)

    def test_a_sighting_that_cannot_be_read_is_refused_loud(self):
        with td.mock.patch.object(self.D, "why_unseen", side_effect=ValueError("Expecting value: line 7 column 1 (char 900)")):
            with self.assertRaises(RuntimeError) as cm:
                self.call(cam="lap1", trigger="cam:lap1:1790007100", file=str(td.FRAME))
        self.assertIn("FAILED to read the camera's sighting", str(cm.exception))
        self.assert_failed_loud("FAILED to read the camera's sighting: ValueError: Expecting value")
        self.assertEqual(td.rows_since(0, "plan.route"), [], "refused before any plan")


class OneYes(td.RunCase):
    def test_two_approved_calls_on_one_yes_are_one_walk(self):
        from wtdd import tools
        trig = "cam:lap1:1790008000"
        verdict(trig)
        out = tools.call("dispatch", cam="lap1", approved=True, trigger=trig, by=MODEL_SAYS)
        self.assertEqual((out["phase"], len(self.s.follows)), ("arrived", 1))
        n1 = len(td.ledger.rows())
        with self.assertRaises(ValueError) as cm:
            tools.call("dispatch", cam="lap1", approved=True, trigger=trig, by=MODEL_SAYS)
        self.assertIn("this yes already sent the dog", str(cm.exception))
        self.assertEqual(len(self.s.follows), 1, "one yes, one walk")
        rows = td.rows_since(n1)
        self.assertEqual([(r["tool"], r["ok"], r["app"]) for r in rows], [("dispatch.decided", False, "imessage")], "no plan.route, no follow")
        self.assertIn("this yes already sent the dog", rows[0]["response_or_error"])


class QuestionWords(td.RunCase):
    def test_the_open_question_refusal_says_whose_question_in_words(self):
        open_key = "cam:lap1:1790009000"
        cases = {"dispatch": ({"kind": "dispatch", "cam": "lap1", "trigger": open_key, "file": str(td.FRAME)},
                              "couldn't dispatch: still waiting for a yes on the last ask about camera lap1"),
                 "who_dis": ({"kind": "who_dis", "trigger": "alarm:watch:1790009001", "seconds": 5},
                             "couldn't dispatch: the dog's own question is open"),
                 "decide": ({"kind": "decide", "trigger": "decide:2:1790009002", "seconds": 5},
                            "couldn't dispatch: the dog's own question is open")}
        for k, (kind, (pend, said)) in enumerate(cases.items()):
            with self.subTest(kind):
                self.s, self.posts[:] = td.FakeSession(self.out), []
                self.pending.write_text(json.dumps({**pend, "t": time.time()}))
                n0 = len(td.ledger.rows())
                self.refused("lap1", trigger=f"cam:lap1:{1790009060 + k}", file=str(td.FRAME))
                self.assertEqual([(p["text"], p["file"]) for p in self.posts], [(said, None)])
                (row,) = td.rows_since(n0, "dispatch.decided")
                self.assertIn(pend["trigger"], row["response_or_error"], "the key stays on the row")
                self.assertIn(kind, row["response_or_error"])
                if kind == "dispatch":
                    self.assertNotIn("dog's own", row["response_or_error"], "no dog's eye is involved in the camera's own ask")
        with self.subTest("an unreadable pending.json"):
            self.s, self.posts[:] = td.FakeSession(self.out), []
            self.pending.write_text('{"kind": "who')
            self.refused("lap1", trigger="cam:lap1:1790009070", file=str(td.FRAME))
            self.assertEqual([(p["text"], p["file"]) for p in self.posts], [("couldn't dispatch: a question is open in the thread", None)])


class Armed(Fresh):
    def assert_not_armed(self, app: str):
        dec = td.rows_since(0, "dispatch.decided")
        self.assertEqual([(r["ok"], r["app"]) for r in dec], [(False, app)], "exactly one FAILED dispatch.decided")
        self.assertIn("not armed", dec[0]["response_or_error"])
        self.assertEqual(td.rows_since(0, "plan.route"), [], "refused before any plan")
        pg = self.page()
        self.assertEqual(pg["phase"], "failed")
        self.assertIn("not armed", pg["error"])
        self.assertEqual(len(self.posts), 1, self.posts)
        self.assertTrue(self.posts[0]["text"].startswith("couldn't dispatch: not armed"), self.posts)
        self.assertIsNone(self.posts[0]["file"], "text only: the watch is off, no photo of the person goes out")
        self.assertEqual((self.s.follows, self.pending.exists()), ([], False), "no follow, no ask")

    def test_a_yes_after_the_watch_was_switched_off_is_refused(self):
        trig = "cam:lap1:1790010000"
        verdict(trig)
        self.armed.unlink()                       # someone switched the intruder watch off after the ask (review 5, probe 1)
        with self.assertRaises(RuntimeError) as cm:
            self.call(cam="lap1", approved=True, trigger=trig, by=MODEL_SAYS)
        self.assertIn("not armed", str(cm.exception))
        self.assert_not_armed("imessage")

    def test_a_tool_call_with_a_person_seen_while_disarmed_asks_nobody(self):
        detect("lap1", {"person": 1})             # the camera boxed a person a moment ago; the watch is off (probe 2)
        self.armed.unlink()
        jev = td.mock.Mock(side_effect=AssertionError("no model is asked while the watch is off"))
        with self.env(JEV_API_KEY="k"), td.mock.patch.object(td.decide.requests, "post", jev):
            with self.assertRaises(RuntimeError) as cm:
                self.call(cam="lap1", trigger="cam:lap1:1790010100", file=str(td.FRAME))
        self.assertIn("not armed", str(cm.exception))
        self.assert_not_armed(td.decide.JEV_APP)

    def test_a_dry_run_while_disarmed_still_plans_and_decides(self):
        self.armed.unlink()
        out = self.call(cam="lap1", dry=True, trigger="cam:lap1:1790010200")
        self.assertEqual(out["phase"], "decided")
        self.assertEqual((self.posts, self.s.follows), ([], []))


class WalkRecheck(td.RunCase):
    def test_a_question_that_opens_while_the_approved_run_plans_stops_the_walk(self):
        from wtdd import tools
        trig, who = "cam:lap1:1790011000", {"kind": "who_dis", "t": time.time(), "trigger": "alarm:watch:1790011001", "seconds": 5}
        verdict(trig)
        real = td.plan.plan

        def plan_then_who_dis(*a, **kw):   # the dog's own watch opens who-dis while dispatch plans (review 5, probe 4)
            out = real(*a, **kw)
            self.pending.write_text(json.dumps(who))
            return out
        with td.mock.patch.object(td.plan, "plan", plan_then_who_dis), self.assertRaises(RuntimeError) as cm:
            tools.call("dispatch", cam="lap1", approved=True, trigger=trig, by=MODEL_SAYS)
        self.assertIn("question open: who_dis", str(cm.exception))
        self.assertEqual(self.s.follows, [], "no follow began with the dog's own question open (grade U1)")
        self.assertEqual(td.rows_since(self.n0, "dog.follow"), [])
        dec = td.rows_since(self.n0, "dispatch.decided")
        self.assertEqual([r["ok"] for r in dec], [True, False], "the yes decided; the walk was refused before it began")
        self.assertIn("question open: who_dis", dec[1]["response_or_error"])
        self.assertEqual([(p["text"], p["file"]) for p in self.posts], [("couldn't dispatch: the dog's own question is open", None)])
        self.assertEqual(json.loads(self.pending.read_text()), who, "the dog's question is left as it wrote it")
        self.assertEqual(self.page()["phase"], "failed")


if __name__ == "__main__":
    unittest.main()
