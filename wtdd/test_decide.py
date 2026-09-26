"""A decision at every stop, offline. Run: python -m unittest wtdd.test_decide -v
Checks wtdd/decide.py: the fixed label list (ui/map.json `labels` or the default), the text state (words, never
digits), the deterministic DEMO_CACHE stub when JEV_API_KEY is unset, the threshold rule (needs_person = p below
WTDD_DECIDE_THRESHOLD, default 0.7), the `decided` ledger row (stub rows say cached=True source="stub"; a live
failure is a row with ok=False and is raised, never a canned decision), the CLI's exit-2 branch without a key, and the
ordering law: the local detector's watch.boxes row lands before the decided row.

The scratch ledger is set through WTDD_LEDGER before wtdd.ledger is imported, so the real file is never touched.
JEV_API_KEY is forced empty here (a real environment or .env value must not turn these into live calls), and so are
the other keys the module reads: config._load() setdefault()s every <repo>/.env key on the first config.maybe(), so a
popped key comes back from the file (a threshold tuned in .env would fail these checks); an empty value blocks that
and reads as unset.
wtdd/fixtures/stop_state.txt is hand-written prose from the take's first stop (docs/evidence/ledger-take-2026-09-13.jsonl:
the watch.boxes row said couch, the vision.check row said someone on the couch, a blanket and a cup, and that the
detector's couch was really a person; its field.walk row reached stop 11 of the taught route, ui/route-saved.json, which
field.room_of puts in the dining room); the box geometry below is chosen to word that frame as large and tall, it is not
from the ledger (the take's boxes rows carry counts, not boxes).

Item 17 (decision-to-action) adds: the one site label list (clear, material_stack, opening, hazard, person, other; the
map's and the default), the policy table that turns (label, p, threshold) into {action, rule} (ESCALATE = opening,
hazard, person at any p; any other label below the threshold asks; else continue; ui/map.json `policy` overrides the
default), the `decided` row's state_after.action, args.rule and args.policy_source, heads_up_line (the words sent to
the person on call), rules() (what the page's Rules panel prints), the CLI's action and rule, and the chat round
escalating on action == escalate through 03's escalate(). wtdd/fixtures/stop_opening.txt is the open-cover state of a
scratch Jev probe on this Mac, 2026-09-26 (docs/evidence/night-2/jev-probe-2026-09-26.jsonl, case open_cover_agree),
where Jev chose the action list's dispatch_alarm at 0.68: which labels go to a person is this table, not the model."""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="wtdd-decide-test-")
os.environ["WTDD_LEDGER"] = str(Path(_TMP) / "ledger.jsonl")
for _k in ("JEV_API_KEY", "JEV_MODEL", "JEV_LIVE", "WTDD_DECIDE_THRESHOLD", "WTDD_SHIFT"):
    os.environ[_k] = ""                   # the stub path and the defaults; config.maybe() reads an empty value as unset
os.environ["WTDD_ON_CALL_NAME"] = "Sam Stand-in"      # 03 merged beneath 17: "who dis?!" goes through escalate() to the on-call 1:1,
os.environ["WTDD_ON_CALL_HANDLE"] = "+15550002222"   # so the listener checks need a (fake, E.164-shaped) person or every flag fails
os.environ["WTDD_REPLY_THRESHOLD"] = ""               # 17: the reply reader's default (0.8), never a tuned .env value

from wtdd import config, decide, ledger  # noqa: E402

ROOT = config.ROOT
FIXTURE = ROOT / "wtdd" / "fixtures" / "stop_state.txt"
OPENING = ROOT / "wtdd" / "fixtures" / "stop_opening.txt"   # 17: a floor cover off, nobody around (the probe's open_cover_agree)
SITE = ["clear", "material_stack", "opening", "hazard", "person", "other"]   # 17: the one site list (map and default)
ESCALATE = ["opening", "hazard", "person"]                                  # 17: the labels that go to the person on call at any p
ONCALL = "any;-;+15550002222"
DECISION_KEYS = {"label", "p", "needs_person", "model", "action"}           # 17: 02's four plus the action the table chose
PY = sys.executable
DIGIT = re.compile(r"\d")

# the take's first stop, as look_and_see has it in hand: see()'s reply and boxed()'s result
SEEN = {"text": "someone on the couch with their feet up. a red blanket on the floor. probably teris cup on the coffee table. "
                "put that cup in the sink teri.",
        "person": True, "out_of_place": ["blanket", "cup"], "pick": 2, "why": "",
        "detector_check": "it says couch but that is really a person on the couch", "model": "x-ai/grok-4.20"}
DET = {"file": "look-level-boxed.jpg", "classes": {"couch": 1}, "n": 1, "ms": 5695,
       "boxes": [{"name": "couch", "conf": 0.7, "xyxy": [120, 200, 1100, 700]}]}
FRAME = (1280, 720)


def _state() -> str:
    return FIXTURE.read_text().strip()


class Labels(unittest.TestCase):
    def _map(self, **extra) -> Path:
        p = Path(_TMP) / f"map-{len(extra)}-{abs(hash(json.dumps(extra, sort_keys=True)))}.json"
        p.write_text(json.dumps({"note": "test", "path": [], "stops": [], "rooms": [], **extra}))
        return p

    def test_default_list_when_the_map_has_none(self):
        self.assertEqual(decide.labels(map_path=self._map()), decide.DEFAULT_LABELS)
        self.assertEqual(decide.DEFAULT_LABELS, SITE)   # 17: the site list, with `other` as the catch-all (was clear/out_of_place/hazard/person)

    def test_map_labels_win(self):
        self.assertEqual(decide.labels(map_path=self._map(labels=["ok", "flag"])), ["ok", "flag"])

    def test_bad_map_labels_raise(self):
        for bad in ([], ["a", "a"], "clear", [""], [1, 2]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                decide.labels(map_path=self._map(labels=bad))


class State(unittest.TestCase):
    def test_fixture_has_no_digits(self):
        self.assertIsNone(DIGIT.search(FIXTURE.read_text()))

    def test_state_for_the_take_matches_the_fixture(self):
        s = decide.state_for_stop("stop one, in the dining room", SEEN, DET, frame_wh=FRAME)
        self.assertEqual(s.strip(), _state())

    def test_state_words_every_number(self):
        seen = {**SEEN, "text": "2 cups and 100 socks on the floor", "detector_check": "agree", "out_of_place": []}
        det = {**DET, "classes": {"cup": 2, "chair": 1}}
        s = decide.state_for_stop("stop two, in the kitchen", seen, det, frame_wh=FRAME)
        self.assertIsNone(DIGIT.search(s), s)
        self.assertIn("two cups", s)
        self.assertIn("many socks", s)
        self.assertIn("cup (two)", s)
        self.assertIn("the eyes agree", s)
        self.assertIn("out of place: nothing", s)

    def test_state_without_a_detector_says_so(self):
        s = decide.state_for_stop("a stop off the route", SEEN, {"error": "RuntimeError: detector rc=1"}, frame_wh=None)
        self.assertIsNone(DIGIT.search(s), s)
        self.assertIn("the detector did not run", s)
        self.assertIn("footprint: unknown", s)

    def test_stop_name_is_words(self):
        self.assertTrue(decide.stop_name(22).startswith("stop two"), decide.stop_name(22))   # ui/map.json stops [10, 22, 23]
        self.assertIsNone(DIGIT.search(decide.stop_name(22)))
        self.assertIsNone(DIGIT.search(decide.stop_name(None)))


class Stub(unittest.TestCase):
    def test_stub_is_deterministic_and_typed(self):
        a, b = decide.decide(_state()), decide.decide(_state())
        self.assertEqual(a, b)
        self.assertEqual(set(a), DECISION_KEYS)
        self.assertIn(a["action"], ("continue", "ask", "escalate"))
        self.assertIn(a["label"], decide.DEFAULT_LABELS)
        self.assertTrue(0.0 <= a["p"] <= 1.0, a)
        self.assertIsInstance(a["needs_person"], bool)
        self.assertEqual(a["model"], "stub")

    def test_two_eyes_disagreeing_asks_a_person(self):
        d = decide.decide(_state())
        self.assertEqual(d["label"], "person")
        self.assertLess(d["p"], 0.7)
        self.assertTrue(d["needs_person"])
        agree = _state().replace("the eyes disagree: it says couch but that is really a person on the couch.", "the eyes agree.")
        e = decide.decide(agree)
        self.assertEqual(e["label"], "person")
        self.assertGreaterEqual(e["p"], 0.7)
        self.assertFalse(e["needs_person"])

    def test_stub_never_invents_a_custom_label(self):
        with self.assertRaises(ValueError):
            decide.decide(_state(), labels=["ok", "flag"])
        row = ledger.rows(1)[0]
        self.assertEqual(row["tool"], "decided")
        self.assertFalse(row["ok"])


class Threshold(unittest.TestCase):
    def tearDown(self):
        os.environ["WTDD_DECIDE_THRESHOLD"] = ""

    def test_default_is_point_seven(self):
        self.assertEqual(decide.threshold(), 0.7)

    def test_needs_person_is_p_below_threshold(self):
        os.environ["WTDD_DECIDE_THRESHOLD"] = "1.0"
        d = decide.decide(_state())
        self.assertLess(d["p"], 1.0)
        self.assertTrue(d["needs_person"])
        os.environ["WTDD_DECIDE_THRESHOLD"] = "0.0"
        self.assertFalse(decide.decide(_state())["needs_person"])

    def test_bad_threshold_fails_loud(self):
        for bad in ("abc", "1.5", "-0.1", ""):
            os.environ["WTDD_DECIDE_THRESHOLD"] = bad
            if bad == "":
                continue   # empty = unset = the default; not an error
            with self.assertRaises(ValueError, msg=bad):
                decide.decide(_state())


class Row(unittest.TestCase):
    def tearDown(self):
        os.environ["WTDD_SHIFT"] = ""

    def test_decided_row_shape(self):
        state = _state()
        d = decide.decide(state, stop=1)
        row = ledger.rows(1)[0]
        self.assertEqual(row["tool"], "decided")
        self.assertEqual(row["agent"], "decide")
        self.assertEqual(row["app"], "stub")
        self.assertTrue(row["ok"])
        self.assertIs(row["cached"], True)
        self.assertEqual(row["source"], "stub")
        self.assertEqual(row["args"]["stop"], 1)
        self.assertEqual(row["args"]["state_chars"], len(state))
        self.assertEqual(row["args"]["threshold"], 0.7)
        self.assertRegex(row["args"]["shift_id"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(row["state_before"], {"labels": decide.DEFAULT_LABELS})
        self.assertEqual(row["state_after"], d)
        self.assertEqual(row["state_after"]["action"], "escalate")          # 17: the fixture is person 0.6; person escalates at any p
        self.assertEqual(row["args"]["rule"], "escalate:person")
        self.assertEqual(row["args"]["policy_source"], "map")              # ui/map.json carries the table
        self.assertIsInstance(row["latency_ms"], int)
        self.assertIsInstance(row["response_or_error"], str)
        self.assertTrue(row["response_or_error"])

    def test_shift_id_from_env(self):
        os.environ["WTDD_SHIFT"] = "shift-x"
        decide.decide(_state(), stop=None)
        row = ledger.rows(1)[0]
        self.assertEqual(row["args"]["shift_id"], "shift-x")
        self.assertIsNone(row["args"]["stop"])


class AtStop(unittest.TestCase):
    """dog_say.look_and_see's one call: every stop leaves exactly one decided row, even when the state itself fails
    before decide() is reached (drill row 3: no stop without its decided column)."""

    def _decided_since(self, n0):
        return [r for r in ledger.rows()[n0:] if r["tool"] == "decided"]

    def test_a_stop_whose_state_fails_still_has_its_decided_row(self):
        n0 = len(ledger.rows())
        state, d = decide.at_stop(10, {"person": False}, DET, str(Path(_TMP) / "no-such-frame.jpg"))   # see() gave no sentence
        self.assertIsNone(state)
        self.assertIn("KeyError", d["error"])
        rows = self._decided_since(n0)
        self.assertEqual(len(rows), 1, rows)
        self.assertFalse(rows[0]["ok"])
        self.assertEqual(rows[0]["args"]["stop"], 10)
        self.assertEqual((rows[0]["source"], rows[0]["cached"], rows[0]["app"]), ("stub", True, "stub"))
        self.assertIn("KeyError", rows[0]["response_or_error"])
        self.assertIsInstance(rows[0]["latency_ms"], int)

    def test_a_failed_decision_is_one_row_not_two(self):
        n0 = len(ledger.rows())
        with mock.patch.dict(os.environ, {"WTDD_DECIDE_THRESHOLD": "abc"}):
            state, d = decide.at_stop(10, SEEN, DET, str(Path(_TMP) / "no-such-frame.jpg"))
        self.assertTrue(state)
        self.assertIn("ValueError", d["error"])
        rows = self._decided_since(n0)
        self.assertEqual(len(rows), 1, rows)
        self.assertFalse(rows[0]["ok"])


class Live(unittest.TestCase):
    """The live half of the verifying command, without a key: exit 2 and a message naming JEV_API_KEY. With a key and
    an endpoint that refuses the connection: the failure is raised and is a row, never a stub decision."""

    def _run(self, **env):
        e = {**os.environ, "WTDD_LEDGER": str(Path(_TMP) / "cli-ledger.jsonl"), "JEV_API_KEY": "", "JEV_LIVE": "",
             "WTDD_DECIDE_THRESHOLD": "", **env}
        return subprocess.run([PY, "-m", "wtdd.decide", "--state", str(FIXTURE)], capture_output=True, text=True, cwd=ROOT, env=e, timeout=60)

    def test_no_key_exits_two_with_a_clear_message(self):
        pr = self._run(JEV_LIVE="1")
        self.assertEqual(pr.returncode, 2, pr.stderr)
        self.assertIn("JEV_API_KEY", pr.stderr)

    def test_stub_cli_prints_a_labeled_decision(self):
        pr = self._run()
        self.assertEqual(pr.returncode, 0, pr.stderr)
        d = json.loads(pr.stdout.strip().splitlines()[-1])
        self.assertEqual(d["model"], "stub")
        self.assertIn("stub", pr.stderr.lower())   # the stderr line says it was not live

    def test_live_failure_is_raised_and_recorded_not_stubbed(self):
        os.environ["JEV_API_KEY"] = "not-a-real-key"
        try:
            with mock.patch.object(decide, "JEV_URL", "http://127.0.0.1:9/"), mock.patch.object(decide, "JEV_TIMEOUT_S", 2):
                with self.assertRaises(Exception):
                    decide.decide(_state(), stop=3)
        finally:
            os.environ["JEV_API_KEY"] = ""
        row = ledger.rows(1)[0]
        self.assertEqual(row["tool"], "decided")
        self.assertFalse(row["ok"])
        self.assertEqual(row["source"], "live")
        self.assertIs(row["cached"], False)
        self.assertIn("Error", row["response_or_error"])


class Ordering(unittest.TestCase):
    """The local person-in-frame check is the detector (wtdd/watch.py, no model); at a stop, look_and_see runs boxed()
    before see() and before decide(), so the watch.boxes row precedes the decided row (11's unsafe rule). The dog, the
    detector and the vision model are patched; the ledger order is what is graded."""

    def setUp(self):
        from PIL import Image
        self.up, self.down = Path(_TMP) / "look-tilt.jpg", Path(_TMP) / "look-down.jpg"
        for f in (self.up, self.down):
            Image.new("RGB", (64, 48), (40, 40, 40)).save(f, "JPEG")

    def test_decide_row_lands_after_the_detector_row(self):
        from wtdd import commands
        from wtdd.tools import dog_say

        def fake_look(kind="tilt"):
            return {"text": "here's what i see", "file": str(self.up), "kind": kind, "pitch_deg": -15.0, "fired": True,
                    "attempts": 1, "file_down": str(self.down), "pitch_down_deg": 15.0}

        def fake_boxed(file):
            with ledger.step("watch", "watch.boxes", "yolo", {"file": file.split("/")[-1]}) as r:
                r["state_after"] = {"file": file, "classes": {"couch": 1}, "n": 1, "ms": 1}
            return {"file": file, "classes": {"couch": 1}, "n": 1, "ms": 1, "boxes": DET["boxes"]}

        def fake_see(file, baseline=None, file_down=None, labels=None):
            return {**SEEN, "pick": 1, "ms": 1}

        n0 = len(ledger.rows())
        with mock.patch.object(commands, "look", fake_look), mock.patch.object(dog_say, "boxed", fake_boxed), \
                mock.patch.object(dog_say, "see", fake_see):
            out = dog_say.look_and_see("tilt", stop=10)
        self.assertIn("decision", out)
        self.assertIn("state", out)
        self.assertIsNone(DIGIT.search(out["state"]), out["state"])
        self.assertEqual(set(out["decision"]), DECISION_KEYS)
        tools = [r["tool"] for r in ledger.rows()[n0:]]
        self.assertIn("watch.boxes", tools)
        self.assertIn("decided", tools)
        self.assertLess(tools.index("watch.boxes"), tools.index("decided"), tools)
        self.assertEqual(ledger.rows()[n0:][tools.index("decided")]["args"]["stop"], 10)


class LiveReply(unittest.TestCase):
    """The live path with requests.post patched (no network, no key): the state and the labels go out as one Choice
    question, the chosen label's probability is p, the row says live. REPLY is shaped on the example reply OpenRouter
    publishes in its API reference "Submit a System One request" (model typesafe/jev-1.13-20260917, usage 476 in and
    70 out, a choice answer carrying choice, confidence and probabilities); its answer is rewritten to this question and
    these labels. It is not a live reply."""
    REPLY = {"model": "typesafe/jev-1.13-20260917", "usage": {"input_tokens": 476, "output_tokens": 70},
             "answers": {"stop": {"type": "choice", "choice": "person", "confidence": 0.7,
                                  "probabilities": {"clear": 0.05, "material_stack": 0.02, "opening": 0.01, "hazard": 0.03,
                                                    "person": 0.82, "other": 0.07}}}}

    def _decide(self, reply, status=200):
        resp = mock.Mock(status_code=status, text=json.dumps(reply))
        resp.json.return_value = reply
        with mock.patch.dict(os.environ, {"JEV_API_KEY": "test-key", "JEV_MODEL": ""}), \
                mock.patch.object(decide.requests, "post", return_value=resp) as post:
            return decide.decide(_state(), stop=10), post

    def test_system_one_choice_is_parsed(self):
        d, post = self._decide(self.REPLY)
        self.assertEqual(d, {"label": "person", "p": 0.82, "needs_person": False, "model": "typesafe/jev-1.13-20260917",
                             "action": "escalate"})
        kw = post.call_args.kwargs
        self.assertEqual(kw["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(kw["json"]["state"], _state())
        self.assertEqual(kw["json"]["model"], "typesafe/jev-1.13")
        self.assertEqual(kw["json"]["questions"]["stop"]["type"], "choice")
        self.assertEqual(list(kw["json"]["questions"]["stop"]["criteria"]), decide.DEFAULT_LABELS)
        row = ledger.rows(1)[0]
        self.assertEqual((row["tool"], row["ok"], row["source"], row["cached"], row["app"]), ("decided", True, "live", False, "openrouter"))
        self.assertEqual(row["state_after"], d)
        self.assertIn('"answers"', row["response_or_error"])

    def test_a_reply_without_the_answer_fails_loud(self):
        for reply, status in (({"model": "x"}, 200), ({"error": "no credits"}, 402)):
            with self.assertRaises(RuntimeError, msg=reply):
                self._decide(reply, status)
            row = ledger.rows(1)[0]
            self.assertEqual((row["tool"], row["ok"], row["source"]), ("decided", False, "live"))

    def test_a_label_that_was_not_offered_fails_loud(self):
        bad = {"model": "x", "answers": {"stop": {"type": "choice", "choice": "banana", "probabilities": {"banana": 0.9}}}}
        with self.assertRaises(ValueError):
            self._decide(bad)
        self.assertFalse(ledger.rows(1)[0]["ok"])


class ListenAsk(unittest.TestCase):
    """The chat round's stop (listen.look_and_say): when the decision is not sure, one "not sure" line with the photo
    under decide:<guid>:<stop>, the pending question, and the hold; "who dis?!" wins when both would ask; a sure
    decision asks nothing; a failed one is posted as its error. look_and_see, the map and the hold are patched."""

    def setUp(self):
        from wtdd.chat import listen as L
        self.L, self.posts = L, []
        self.pending, self.map = Path(_TMP) / "pending.json", Path(_TMP) / "listen-map.json"
        self.pending.unlink(missing_ok=True)
        self.map.write_text(json.dumps({"actions": {"10": {"look": "tilt", "ask": False}, "22": {"look": "sit", "ask": True}}}))
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener("any;+;test", lambda g, k, kind, t, f: self.posts.append((k, t, f)), listen_s=60)

    def _stop(self, at, person, decision):
        seen = {"text": "someone on the couch.", "file": "/tmp/look-down-boxed.jpg", "person": person,
                "detector": {"classes": {"couch": 1}}, "decision": decision}
        with mock.patch("wtdd.tools.dog_say.look_and_see", return_value=seen), mock.patch("wtdd.field.MAP", self.map), \
                mock.patch.object(self.L, "PENDING", self.pending), \
                mock.patch.object(self.L.Listener, "await_verdict", return_value=False) as wait:
            self.l.look_and_say({"guid": "g1"}, at=at)
        return wait

    def test_not_sure_is_one_question_with_the_photo_and_a_hold(self):
        d = {"label": "other", "p": 0.6, "needs_person": True, "model": "stub", "action": "ask"}   # 17: person escalates; `other` asks
        wait = self._stop(10, False, d)
        self.assertEqual([p[0] for p in self.posts], ["say:g1:10", "decide:g1:10"])
        self.assertEqual(self.posts[1], ("decide:g1:10", "not sure: other at 60 percent. what is it?", "/tmp/look-down-boxed.jpg"))
        pend = json.loads(self.pending.read_text())
        self.assertEqual((pend["kind"], pend["trigger"], pend["decision"]), ("decide", "decide:g1:10", d))
        wait.assert_called_once()

    def test_who_dis_wins_one_question_per_stop(self):
        wait = self._stop(22, True, {"label": "person", "p": 0.6, "needs_person": True, "model": "stub", "action": "escalate"})
        self.assertEqual([p[0] for p in self.posts], ["say:g1:22", "alarm:g1:22"])
        self.assertEqual(json.loads(self.pending.read_text())["kind"], "who_dis")
        wait.assert_called_once()

    def test_a_sure_decision_asks_nothing(self):
        wait = self._stop(10, False, {"label": "clear", "p": 0.8, "needs_person": False, "model": "stub", "action": "continue"})
        self.assertEqual([p[0] for p in self.posts], ["say:g1:10"])
        self.assertFalse(self.pending.exists())
        wait.assert_not_called()

    def test_a_failed_decision_is_posted_as_its_error(self):
        self._stop(10, False, {"error": "RuntimeError: jev 500: down"})
        self.assertEqual(self.posts[-1][:2], ("decide:g1:10", "couldn't decide: RuntimeError: jev 500: down"))

    def test_the_ask_line_is_the_dogs_own(self):
        self.assertTrue(decide.ask_line({"label": "out_of_place", "p": 0.42}).startswith(self.L.OWN_OPENERS))

    def _answer(self, kind, trigger, text):
        self.pending.write_text(json.dumps({"kind": kind, "t": time.time(), "file": "/tmp/look-down-boxed.jpg", "seconds": 5,
                                            "trigger": trigger}))
        with mock.patch.object(self.L, "PENDING", self.pending), \
                mock.patch("wtdd.tools.call", return_value={"signaled": [], "errors": []}) as call:
            self.assertTrue(self.l.verdict({"guid": "r1", "sender": "someone", "text": text}))
        return call

    def test_idk_to_a_decide_question_never_sounds_the_alarm(self):
        """The answer to "not sure: ... what is it?" is the intruder.verdict row joined by args.asked, and it stands down:
        only "who dis?!" (WTDD_ALARM=1, or a stop whose map action has ask) may strobe the room. A housemate's "idk" to
        a cup stop must not sound light_alarm."""
        call = self._answer("decide", "decide:g1:10", "idk")
        call.assert_not_called()
        self.assertEqual(self.posts, [("ok:r1", "ok, standing down", None)])
        row = ledger.rows(1)[0]
        self.assertEqual((row["tool"], row["args"]["asked"], row["args"]["text"]), ("intruder.verdict", "decide:g1:10", "idk"))
        # 17: the verdict is typed from read_reply (the stub reads "idk" as stranger), and on a decide question it still stands down
        self.assertEqual((row["state_after"]["verdict"], row["state_after"]["action"]), ("stranger", "stand_down"))
        read = ledger.rows(2)[0]
        self.assertEqual((read["tool"], read["agent"], read["args"]["trigger"]), ("reply.decided", "central", "decide:g1:10"))
        self.assertFalse(self.pending.exists())

    def test_idk_to_who_dis_still_sounds_the_alarm(self):
        call = self._answer("who_dis", "alarm:g1:22", "idk")
        call.assert_called_once_with("light_alarm", seconds=5)
        self.assertEqual(self.posts[0][:2], ("danger:r1", "STRANGER DANGER!!! STRANGER DANGER!!! STRANGER DANGER!!!"))
        self.assertEqual((ledger.rows(1)[0]["state_after"]["verdict"], ledger.rows(1)[0]["state_after"]["action"]), ("stranger", "alarm"))

    def test_a_housemates_not_sure_is_an_answer(self):
        """Johnny's phone shares the dog's account (WTDD_ALLOW_SELF=1): the dog's own question is refused, a reply that
        merely starts with "not sure" is read, or await_verdict drops the answer to "what is it?" without a row."""
        with mock.patch.dict(os.environ, {"WTDD_ALLOW_SELF": "1"}), mock.patch.object(self.L.memory, "posted_guids", return_value=set()):
            self.assertFalse(self.l.allowed({"is_from_me": True, "guid": "q1", "sender": "me",
                                             "text": decide.ask_line({"label": "person", "p": 0.6})}))
            self.assertTrue(self.l.allowed({"is_from_me": True, "guid": "r1", "sender": "me", "text": "not sure, a cup"}))
            self.assertTrue(self.l.allowed({"is_from_me": True, "guid": "r2", "sender": "me", "text": "Not sure tbh"}))



# ---------- 17 · decision-to-action: the label and p choose the action through a table on the map

def _jev_reply(label: str, p: float) -> dict:
    """A System One reply in OpenRouter's documented shape (see LiveReply), choosing `label` at probability p."""
    rest = round((1.0 - p) / (len(SITE) - 1), 3)
    return {"model": "typesafe/jev-1.13-20260917", "usage": {"input_tokens": 470, "output_tokens": 70},
            "answers": {"stop": {"type": "choice", "choice": label, "confidence": 0.7,
                                 "probabilities": {x: (p if x == label else rest) for x in SITE}}}}


def _live(state: str, reply: dict, **kw) -> dict:
    """decide() on the live path with requests.post patched: no network, no real key."""
    resp = mock.Mock(status_code=200, text=json.dumps(reply))
    resp.json.return_value = reply
    with mock.patch.dict(os.environ, {"JEV_API_KEY": "test-key", "JEV_MODEL": ""}), \
            mock.patch.object(decide.requests, "post", return_value=resp):
        return decide.decide(state, **kw)


def _opening() -> str:
    return OPENING.read_text().strip()


class SiteTable(unittest.TestCase):
    """The one site list and the policy table live on the map (ui/map.json `labels`, `policy`); the default in code says
    the same; every label Jev is offered has its own rubric sentence."""

    def test_the_map_names_the_site_labels_and_the_table(self):
        m = json.loads((ROOT / "ui" / "map.json").read_text())
        self.assertEqual(m.get("labels"), SITE)
        self.assertEqual(m.get("policy"), {"escalate": ESCALATE})
        self.assertEqual(decide.labels(), SITE)

    def test_the_default_table_is_the_same(self):
        self.assertEqual(decide.DEFAULT_POLICY, {"escalate": ESCALATE})

    def test_every_site_label_has_its_own_rubric(self):
        for lab in SITE:
            self.assertIn(lab, decide.DESCRIBE, lab)
            self.assertGreater(len(decide.DESCRIBE[lab]), len(lab) + 8, lab)   # a sentence, not the label again

    def test_the_opening_fixture_has_no_digits(self):
        self.assertIsNone(DIGIT.search(OPENING.read_text()))


class Policy(unittest.TestCase):
    """policy(label, p, thr, table) -> {action, rule}. A label in table["escalate"] goes to the person on call at any p;
    any other label below the threshold asks (02's rule, compared on round(p, 3) like needs_person); else continue.
    Jev names; code chooses."""
    CASES = [  # (label, p, thr, action, rule)
        ("opening", 0.98, 0.7, "escalate", "escalate:opening"),
        ("opening", 0.40, 0.7, "escalate", "escalate:opening"),
        ("hazard", 0.71, 0.7, "escalate", "escalate:hazard"),
        ("person", 0.6, 0.7, "escalate", "escalate:person"),
        ("clear", 0.6, 0.7, "ask", "ask:p<0.7"),
        ("other", 0.699, 0.7, "ask", "ask:p<0.7"),
        ("material_stack", 0.7, 0.7, "continue", "continue"),   # at the threshold is not below it
        ("other", 0.6999, 0.7, "continue", "continue"),         # rounds to 0.7, as needs_person does
        ("clear", 0.99, 0.7, "continue", "continue"),
        ("clear", 0.8, 0.9, "ask", "ask:p<0.9"),
    ]

    def test_the_default_table(self):
        for label, p, thr, action, rule in self.CASES:
            self.assertEqual(decide.policy(label, p, thr, decide.DEFAULT_POLICY), {"action": action, "rule": rule}, (label, p, thr))

    def test_a_map_table_overrides_the_default(self):
        only_hazard = {"escalate": ["hazard"]}
        self.assertEqual(decide.policy("opening", 0.98, 0.7, only_hazard), {"action": "continue", "rule": "continue"})
        self.assertEqual(decide.policy("opening", 0.5, 0.7, only_hazard), {"action": "ask", "rule": "ask:p<0.7"})
        self.assertEqual(decide.policy("hazard", 0.98, 0.7, only_hazard), {"action": "escalate", "rule": "escalate:hazard"})
        self.assertEqual(decide.policy("person", 0.95, 0.7, {"escalate": []}), {"action": "continue", "rule": "continue"})


class DecidedAction(unittest.TestCase):
    """Where this item starts (RED): on 02 as shipped an opening at 0.98 is sure (needs_person false), so nothing happens
    and the round walks on. 17: the table sends it to the person on call, and the decided row says which rule did and
    whose table it was (policy_source map | default). The map is read at call time (wtdd.field.MAP, as labels() does)."""

    def _map(self, **over) -> Path:
        m = json.loads((ROOT / "ui" / "map.json").read_text())
        for k, v in over.items():
            if v is None:
                m.pop(k, None)
            else:
                m[k] = v
        f = Path(_TMP) / f"map-17-{self._testMethodName}-{len(list(Path(_TMP).glob('map-17-*')))}.json"
        f.write_text(json.dumps(m))
        return f

    def test_an_opening_at_ninety_eight_escalates(self):
        d = _live(_opening(), _jev_reply("opening", 0.98), stop=22, labels=SITE)
        self.assertEqual(d.get("action", "none: 02 has no action, the round walks on"), "escalate", d)
        self.assertFalse(d["needs_person"])   # sure: 02's p < 0.7 rule alone never asks anyone about it
        row = ledger.rows(1)[0]
        self.assertEqual((row["tool"], row["ok"], row["source"]), ("decided", True, "live"))
        self.assertEqual(row["state_after"]["action"], "escalate")
        self.assertEqual(row["args"]["rule"], "escalate:opening")
        self.assertEqual(row["args"]["policy_source"], "map")
        self.assertEqual(row["args"]["threshold"], 0.7)

    def test_below_the_threshold_it_escalates_and_needs_person_is_still_p_below_threshold(self):
        d = _live(_opening(), _jev_reply("opening", 0.6), stop=22, labels=SITE)
        self.assertEqual((d.get("action"), d["needs_person"]), ("escalate", True))   # 11 recomputes needs_person = p < threshold

    def test_a_clear_stop_continues(self):
        d = _live(_opening(), _jev_reply("clear", 0.99), stop=22, labels=SITE)
        self.assertEqual(d.get("action"), "continue")
        self.assertEqual(ledger.rows(1)[0]["args"].get("rule"), "continue")

    def test_the_stub_names_the_opening_and_escalates(self):
        d = decide.decide(_opening(), stop=22)
        self.assertEqual((d["label"], d.get("action"), d["model"]), ("opening", "escalate", "stub"))
        self.assertGreaterEqual(d["p"], 0.7)
        row = ledger.rows(1)[0]
        self.assertEqual((row["args"].get("rule"), row["cached"], row["source"]), ("escalate:opening", True, "stub"))

    def test_a_map_without_a_table_uses_the_default_and_says_so(self):
        with mock.patch("wtdd.field.MAP", self._map(policy=None)):
            _live(_opening(), _jev_reply("hazard", 0.9), stop=None)
        row = ledger.rows(1)[0]
        self.assertEqual((row["state_after"].get("action"), row["args"].get("rule"), row["args"].get("policy_source")),
                         ("escalate", "escalate:hazard", "default"))

    def test_the_map_table_overrides_the_default(self):
        with mock.patch("wtdd.field.MAP", self._map(policy={"escalate": ["hazard"]})):
            d = _live(_opening(), _jev_reply("opening", 0.98), stop=None)
        self.assertEqual(d.get("action"), "continue")
        row = ledger.rows(1)[0]
        self.assertEqual((row["args"].get("rule"), row["args"].get("policy_source")), ("continue", "map"))

    def test_a_malformed_table_fails_loud_on_the_row(self):
        for bad in ({"escalate": "hazard"}, {"escalate": [1]}, {"escalate": ["banana"]}, {"ask": ["hazard"]}, ["hazard"]):
            with mock.patch("wtdd.field.MAP", self._map(policy=bad)):
                with self.assertRaises(ValueError, msg=repr(bad)):
                    decide.decide(_opening(), stop=None)
            row = ledger.rows(1)[0]
            self.assertEqual((row["tool"], row["ok"]), ("decided", False), repr(bad))


class HeadsUp(unittest.TestCase):
    """heads_up_line(d, stop): the words the person on call gets with the photo. Sure: "heads up: <label> at <p in words>
    percent at stop <n>. what is it?" (n is the stop's place in map.json `stops`, as stop_name words it). Not sure (p below
    the threshold): 02's ask line, so 11's grade_decide still reads the stop's question ("not sure:"). A person keeps
    "who dis?!" so 03 and 11 are unchanged. Every line starts like the dog's own posts (listen.OWN_OPENERS)."""

    def test_sure_is_heads_up_in_words(self):
        for d, stop, want in (
                ({"label": "opening", "p": 0.98, "needs_person": False}, 22, "heads up: opening at ninety eight percent at stop two. what is it?"),
                ({"label": "hazard", "p": 1.0, "needs_person": False}, 10, "heads up: hazard at one hundred percent at stop one. what is it?"),
                ({"label": "hazard", "p": 0.71, "needs_person": False}, 23, "heads up: hazard at seventy one percent at stop three. what is it?"),
                ({"label": "opening", "p": 0.9, "needs_person": False}, None, "heads up: opening at ninety percent at a stop off the route. what is it?")):
            line = decide.heads_up_line(d, stop)
            self.assertEqual(line, want)
            self.assertIsNone(DIGIT.search(line), line)

    def test_not_sure_is_the_ask_line(self):
        d = {"label": "opening", "p": 0.6, "needs_person": True}
        self.assertEqual(decide.heads_up_line(d, 22), "not sure: opening at 60 percent. what is it?")
        self.assertEqual(decide.heads_up_line(d, 22), decide.ask_line(d))

    def test_a_person_keeps_who_dis(self):
        for p, np in ((0.95, False), (0.6, True)):
            self.assertEqual(decide.heads_up_line({"label": "person", "p": p, "needs_person": np}, 22), "who dis?!")

    def test_the_line_is_the_dogs_own(self):
        from wtdd.chat import listen as L
        for d in ({"label": "opening", "p": 0.98, "needs_person": False}, {"label": "hazard", "p": 0.5, "needs_person": True},
                  {"label": "person", "p": 0.95, "needs_person": False}):
            self.assertTrue(decide.heads_up_line(d, 22).startswith(L.OWN_OPENERS), d)


class Rules(unittest.TestCase):
    """rules(): what the page's Rules panel prints, served by GET /rules (the page computes nothing)."""

    def tearDown(self):
        os.environ["WTDD_DECIDE_THRESHOLD"] = ""

    def test_the_rules_in_force(self):
        r = decide.rules()
        self.assertEqual(r["lines"], ["opening · hazard · person → the person on call, any p", "below 0.7 → ask", "else continue"])
        self.assertEqual((r["source"], r["threshold"], r["reply_threshold"]), ("map", 0.7, 0.8))
        self.assertEqual((r["labels"], r["escalate"]), (SITE, ESCALATE))
        self.assertEqual(r["unconfirmed"], [0.7, 0.9])   # a pin between these shows its number and "unconfirmed"

    def test_the_threshold_in_force_is_printed(self):
        os.environ["WTDD_DECIDE_THRESHOLD"] = "0.8"
        self.assertEqual(decide.rules()["lines"][1], "below 0.8 → ask")


class CliAction(unittest.TestCase):
    """The goal's command: python -m wtdd.decide --state FILE prints label, p, action and rule."""

    def _run(self, *args):
        e = {**os.environ, "WTDD_LEDGER": str(Path(_TMP) / "cli-17-ledger.jsonl"), "JEV_API_KEY": "", "JEV_LIVE": "",
             "WTDD_DECIDE_THRESHOLD": ""}
        return subprocess.run([PY, "-m", "wtdd.decide", *args], capture_output=True, text=True, cwd=ROOT, env=e, timeout=60)

    def test_state_prints_action_and_rule(self):
        for fx, want in ((FIXTURE, {"label": "person", "p": 0.6, "action": "escalate", "rule": "escalate:person"}),
                         (OPENING, {"label": "opening", "action": "escalate", "rule": "escalate:opening"})):
            pr = self._run("--state", str(fx))
            self.assertEqual(pr.returncode, 0, pr.stderr)
            d = json.loads(pr.stdout.strip().splitlines()[-1])
            self.assertEqual({k: d.get(k) for k in want}, want, pr.stdout)


class ListenEscalate(unittest.TestCase):
    """The chat round's stop (listen.look_and_say) on action == escalate: the photo and heads_up_line go to the person on
    call through 03's escalate() (kind escalate, their 1:1), one question per stop under decide:<guid>:<stop>, a pending
    question of kind heads_up (never the alarm: only 03's who-dis at an ask stop may strobe the room), and the hold. No
    person on call: "couldn't escalate" in the group, no question, no hold. On 02 + 03 as merged, an opening at 0.98
    posts the look's sentence and the round walks on."""
    FILE = "/tmp/look-down-boxed.jpg"
    GROUP = "any;+;test"

    def setUp(self):
        from wtdd.chat import listen as L
        self.L, self.posts = L, []
        self.pending = Path(_TMP) / f"pending-{self._testMethodName}.json"
        self.pending.unlink(missing_ok=True)
        self.map = Path(_TMP) / "listen-17-map.json"
        m = json.loads((ROOT / "ui" / "map.json").read_text())
        m["actions"] = {"10": {"look": "tilt", "ask": False}, "22": {"look": "sit", "ask": True}, "23": {"look": "tilt", "ask": False}}
        self.map.write_text(json.dumps(m))
        self.l = self._listener()

    def _listener(self):
        with mock.patch.object(self.L.db, "max_rowid", return_value=0):
            return self.L.Listener(self.GROUP, lambda g, k, kind, t, f: self.posts.append((g, k, kind, t, f)), listen_s=60)

    def _stop(self, at, person, decision, listener=None):
        seen = {"text": "a floor cover is off.", "file": self.FILE, "person": person, "detector": {"classes": {}}, "decision": decision}
        with mock.patch("wtdd.tools.dog_say.look_and_see", return_value=seen), mock.patch("wtdd.field.MAP", self.map), \
                mock.patch.object(self.L, "PENDING", self.pending), \
                mock.patch.object(self.L.Listener, "await_verdict", return_value=False) as wait:
            (listener or self.l).look_and_say({"guid": "g1"}, at=at)
        return wait

    def test_an_opening_at_ninety_eight_goes_to_the_person_on_call(self):
        d = {"label": "opening", "p": 0.98, "needs_person": False, "model": "stub", "action": "escalate"}
        wait = self._stop(10, False, d)
        self.assertEqual([(g, k, kind) for g, k, kind, _, _ in self.posts],
                         [(self.GROUP, "say:g1:10", "listen"), (ONCALL, "decide:g1:10", "escalate")])
        self.assertEqual(self.posts[1][3:], ("heads up: opening at ninety eight percent at stop one. what is it?", self.FILE))
        pend = json.loads(self.pending.read_text())
        self.assertEqual((pend["kind"], pend["trigger"], pend["chat"], pend["decision"]), ("heads_up", "decide:g1:10", ONCALL, d))
        wait.assert_called_once()

    def test_below_the_threshold_the_person_on_call_gets_the_not_sure_line(self):
        self._stop(10, False, {"label": "hazard", "p": 0.55, "needs_person": True, "model": "stub", "action": "escalate"})
        self.assertEqual([(g, k, kind, t) for g, k, kind, t, _ in self.posts[1:]],
                         [(ONCALL, "decide:g1:10", "escalate", "not sure: hazard at 55 percent. what is it?")])   # one question

    def test_a_person_label_escalates_as_who_dis_but_never_arms_the_alarm(self):
        self._stop(10, False, {"label": "person", "p": 0.95, "needs_person": False, "model": "stub", "action": "escalate"})
        self.assertEqual(self.posts[1:], [(ONCALL, "decide:g1:10", "escalate", "who dis?!", self.FILE)])
        self.assertEqual(json.loads(self.pending.read_text())["kind"], "heads_up")

    def test_the_who_dis_flag_is_the_one_question_when_both_would_ask(self):
        self._stop(22, True, {"label": "person", "p": 0.95, "needs_person": False, "model": "stub", "action": "escalate"})
        self.assertEqual([k for _, k, _, _, _ in self.posts], ["say:g1:22", "alarm:g1:22"])
        self.assertEqual(json.loads(self.pending.read_text())["kind"], "who_dis")

    def test_no_person_on_call_is_couldnt_escalate_in_the_group(self):
        with mock.patch.dict(os.environ, {"WTDD_ON_CALL_HANDLE": "", "WTDD_ON_CALL_NAME": ""}):
            l = self._listener()
            wait = self._stop(10, False, {"label": "opening", "p": 0.98, "needs_person": False, "model": "stub", "action": "escalate"}, listener=l)
        self.assertEqual([(g, k) for g, k, _, _, _ in self.posts], [(self.GROUP, "say:g1:10"), (self.GROUP, "escalate-fail:g1:10")])
        self.assertTrue(self.posts[1][3].startswith("couldn't escalate: RuntimeError"), self.posts[1][3])
        self.assertFalse(self.pending.exists())
        wait.assert_not_called()

    def test_continue_asks_nobody(self):
        wait = self._stop(10, False, {"label": "material_stack", "p": 0.93, "needs_person": False, "model": "stub", "action": "continue"})
        self.assertEqual([k for _, k, _, _, _ in self.posts], ["say:g1:10"])
        self.assertFalse(self.pending.exists())
        wait.assert_not_called()


if __name__ == "__main__":
    unittest.main()
