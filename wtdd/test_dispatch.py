"""Dispatch, offline (goals/roadmap.md item 18, 18a): a person seen by a fixed camera while the watch is armed becomes
one typed decision (dispatch / ask / ignore) from a text state in words, a route planned over the dog's own grid from
where it believes it is to the camera's spot, and an ask to the person on call with the route and the probabilities
on the page before anything moves; on their go, a follow, a level look on arrival and one post. Run:

    python -m unittest wtdd.test_dispatch -v

RED until wtdd/dispatch.py, wtdd/tools/dispatch.py, the one line in wtdd/cam/__init__.py person_seen, the kind
"dispatch" branch (and its opener) in wtdd/chat/listen.py, and GET /dispatch in wtdd/api.py exist. wtdd.dispatch is
imported inside each test, so every check below fails on its own name before the module exists.

The contract under test (wtdd/dispatch.py):
  CHOICES, CRITERIA, INSTRUCTIONS   the Choice question sent to Jev: three choices and their words, pinned below
  OUT, PENDING                      <repo>/dispatch.json (the page's feed, GET /dispatch) and <repo>/pending.json (the
                                    one open question); both module globals read at call time, so a test points them
                                    at scratch files
  state_for_dispatch(cam, armed, dog, route, question_open) -> str
        words, no digits (decide._dedigit): the camera (id, label, zone), whether the watch is armed, the dog's stop,
        room and readiness, whether a route exists and about how long (or the planner's reason, in words), whether a
        question is open. cam is the map's cameras[] entry; dog {p, calibrated, following, recording, avoid}; route
        {exists, length_m, nogo, why}.
  stub(state) -> {choice, p, probabilities, rule}   the DEMO_CACHE decision: ask or ignore, NEVER dispatch
  arrival(pt, grid=None, cal=None) -> [x, y]        the pt when walkable on plan.cost_map, else the nearest walkable
                                                    cell centre within HALF_WIDTH + 1 cells; none: ValueError
  ask_line(cam) -> str                              the question posted with the camera's frame
  run(cam, approved=False, dry=False, trigger=None, file=None, by=None) -> dict
        returns dispatch.json's content at its last phase. Refusals and failures RAISE, after their FAILED
        dispatch.decided row, one "couldn't dispatch: ..." post (never in dry) and, unless another dispatch owns the
        page, the page's `failed` phase naming the reason.
  read() -> dict                                    GET /dispatch: {} or dispatch.json plus age_ms
  grade(rows) -> (grade, why)                       pass / fail / unsafe from the rows, never from the agent's report

Isolation. WTDD_LEDGER, WTDD_MEMORY and WTDD_CAMS point at a scratch dir BEFORE the package is imported (the pattern of
wtdd/chat/test_chat.py); the keys dispatch reads are forced empty so a real .env never turns these into live calls
(config._load() setdefault()s .env; an empty value blocks it, gotcha 02-2); WTDD_API_PORT is a dead port, so nothing
here can reach an API, least of all Johnny's on 7788. plan.MAP and field.MAP point at a scratch COPY of 04's zone
fixture (wtdd/fixtures/map_nogo.json: the shipped rooms plus nogo-1) with a short path whose first stop is where the
dog stands and two cameras: lap1 where 09's ui/map.json puts it, gate2 deep inside nogo-1. The grid is 06's fixture
(wtdd/fixtures/make_grid_wall.py: one wall, tied to the map by CAL). DogSession.get() returns a fake with the real
session's surface (cal, grid, _grid_lock, follow_state, rec, body._avoid, map_pose, follow, stop): its follow()
records the call and what the page said at that moment, then teleports the believed pose to the path's end, or, with
finish=False, walks until stop(). Jev is requests.post patched with a System One Choice reply echoing the question it
was asked (the shape of OpenRouter's published reference reply that wtdd/test_decide.py LiveReply uses; not a live
reply). The chat send, the look, intruder_alarm and light_alarm are fakes; no test touches a light, the dog or a chat.
The grader's ledger is wtdd/fixtures/evals/dispatch.jsonl (wtdd/fixtures/evals/make_dispatch.py), committed first."""
from __future__ import annotations
import copy
import http.client
import importlib
import json
import math
import os
import re
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stderr
from http.server import ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-dispatch-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
os.environ["WTDD_CAMS"] = str(_TMP / "cams")
for _k, _v in {"WTDD_SHIFT": "2026-09-27-test", "JEV_API_KEY": "", "JEV_MODEL": "", "WTDD_DISPATCH_AUTO": "",
               "WTDD_DISPATCH_THRESHOLD": "", "WTDD_ALLOW_SELF": "", "WTDD_ON_CALL_NAME": "", "WTDD_API_PORT": "9"}.items():
    os.environ[_k] = _v

from wtdd import api, cam, config, decide, field, ledger, plan  # noqa: E402
from wtdd.dog import session  # noqa: E402
from wtdd.fixtures import make_grid_wall as fx  # noqa: E402
from wtdd.tools import chat_post, dog_say, intruder_alarm, light_alarm  # noqa: E402

ROOT = config.ROOT
CAL = fx.CAL
DIGIT = re.compile(r"\d")
CAM = {"id": "lap1", "label": "laptop at the gate", "pt": [322, 1284], "zone": "a"}      # 09's ui/map.json camera
CAM_NOGO = {"id": "gate2", "label": "the back gate", "pt": [480, 1145], "zone": "b"}     # deep inside nogo-1 (450..510 x 1040..1250)
DOG_AT = [300, 1100]                                                                    # CAL's map point: stop one below
T = "cam:lap1:1790000000"
HOUSEMATE = "+15550002222"
FRAME = ROOT / "wtdd" / "cam" / "fixtures" / "frame.jpg"
CHOICES = ["dispatch", "ask", "ignore"]
CRITERIA = {"dispatch": "send the dog to the camera now to look and report",
            "ask": "ask the person on call before sending the dog",
            "ignore": "do nothing and keep watching"}
INSTRUCTIONS = "A fixed camera on a night round saw a person. What should the dog do?"
JEV_MODEL = "typesafe/jev-1.13-20260917"
KEYS = {"cam", "pt", "arrival", "path", "state", "choice", "p", "probabilities", "demoted", "auto", "phase", "error",
        "reached", "of", "end_pose", "t"}                                               # dispatch.json, every phase
GRADE_FIXTURE = ROOT / "wtdd" / "fixtures" / "evals" / "dispatch.jsonl"
SEEN = {"text": "a laptop on a table by the door. nothing on the floor. [detector: laptop]", "file": str(_TMP / "look-level-boxed.jpg"),
        "person": False, "detector": {"classes": {"laptop": 1}, "n": 1, "file": str(_TMP / "look-level-boxed.jpg")},
        "decision": {"label": "clear", "p": 0.8, "needs_person": False, "model": "stub"}}   # dog_say.look_and_see's reply

MAP = _TMP / "map.json"
_m = json.loads((ROOT / "wtdd" / "fixtures" / "map_nogo.json").read_text())
_m["path"], _m["stops"], _m["actions"] = [DOG_AT, [305, 1265], [600, 1400]], [0, 2], {}
_m["cameras"] = [CAM, CAM_NOGO]
MAP.write_text(json.dumps(_m))


def setUpModule():
    global _patches
    _patches = [mock.patch.object(plan, "MAP", MAP), mock.patch.object(field, "MAP", MAP),
                mock.patch.object(session, "GRID_FILE", _TMP / "no-saved-grid.json")]   # never the checkout's ui/grid.json
    for p in _patches:
        p.start()


def tearDownModule():
    for p in _patches:
        p.stop()


def D():
    """wtdd.dispatch, imported per test: before it exists every test below fails by name, not the module as one."""
    return importlib.import_module("wtdd.dispatch")


def rows_since(n0: int, tool: str | None = None) -> list[dict]:
    return [r for r in ledger.rows()[n0:] if tool is None or r.get("tool") == tool]


def jev(choice: str | None, probs: dict | None = None, status: int = 200, gate: dict | None = None) -> mock.Mock:
    """requests.post for the Jev call: one System One Choice answer to whatever question it was sent (its own name
    echoed back), shaped like OpenRouter's reference reply. gate {entered, release}: it signals, then waits."""
    def post(url, **kw):
        if gate is not None:
            gate["entered"].set()
            gate["release"].wait(10)
        if status != 200:
            body = {"error": {"message": "upstream unavailable"}}
        else:
            q = next(iter(kw["json"]["questions"]))
            body = {"id": "gen-fixture", "model": JEV_MODEL, "provider": "TypeSafe", "usage": {"input_tokens": 212, "output_tokens": 30},
                    "answers": {q: {"type": "choice", "choice": choice, "confidence": 0.7, "probabilities": probs}}}
        r = mock.Mock(status_code=status, text=json.dumps(body))
        r.json.return_value = body
        return r
    return mock.Mock(side_effect=post)


class FakeSession:
    """The surface of wtdd/dog/session.py DogSession that dispatch reads and drives; no loop, no dog, no clock."""

    def __init__(self, page: Path, finish: bool = True):
        self.page, self.finish = page, finish
        self.cal = dict(CAL)
        self.grid = fx.grid()
        self._grid_lock = threading.Lock()
        self.follow_state: dict = {}
        self.rec = None
        self.recheck = False
        self.body = types.SimpleNamespace(_avoid=True)
        self.pose = list(DOG_AT)
        self.follows: list[dict] = []
        self.stops = 0
        self._stopped = threading.Event()

    def map_pose(self, st=None):
        return {"p": [round(self.pose[0]), round(self.pose[1])], "heading_deg": 0.0}

    def state(self):
        return {"connected": True, "calibrated": self.cal is not None, "map": self.map_pose(), "follow": self.follow_state,
                "avoid": self.body._avoid, "rec": self.rec, "recheck": self.recheck}

    def follow(self, path, stops, reach_px=30.0, from_nearest=True, avoid=True):
        self.follows.append({"path": [list(p) for p in path], "stops": list(stops), "reach_px": reach_px, "from_nearest": from_nearest,
                             "avoid": avoid, "page": json.loads(self.page.read_text()) if self.page.exists() else None})
        fs = self.follow_state = {"active": True, "i": 0, "n": len(path), "stops": list(stops), "stopped_at": None, "reached": [],
                                  "started": time.time(), "error": None, "avoid": True, "replans": [], "skipped_stops": []}

        def walk():
            if not self.finish:
                self._stopped.wait(30)
                return
            time.sleep(0.05)
            self.pose = list(path[-1])
            fs["reached"], fs["i"], fs["done"], fs["active"] = list(range(len(path))), len(path) - 1, True, False
        threading.Thread(target=walk, daemon=True).start()
        return dict(fs)

    def stop(self):
        self.stops += 1
        self.follow_state["active"], self.follow_state["error"] = False, "stopped"
        self._stopped.set()
        return {"vel": [0.0, 0.0, 0.0]}


class State(unittest.TestCase):
    """The words the decision is made on: only what the question needs, no digits (Jev 1.13: 'not a calculator';
    accuracy falls with unrelated state)."""
    DOG = {"p": DOG_AT, "calibrated": True, "following": False, "recording": False, "avoid": True}
    ROUTE = {"exists": True, "length_m": 1.74, "nogo": ["nogo-1"], "why": None}
    NOROUTE = {"exists": False, "length_m": None, "nogo": ["nogo-1"],
               "why": "end is not on walkable floor (clear of every wall cell the LiDAR saw and every no-go zone, 40 px from their edges)"}

    def state(self, **kw) -> str:
        a = {"cam": CAM, "armed": True, "dog": self.DOG, "route": self.ROUTE, "question_open": False, **kw}
        return D().state_for_dispatch(**a)

    def test_the_state_is_words_with_no_digits_and_names_what_the_question_needs(self):
        st = self.state()
        self.assertIsNone(DIGIT.search(st), st)
        for w in ("camera lap one", "laptop at the gate", "zone a", "the intruder watch is armed", "stop one", "living room",
                  "a route to the camera exists", "about two metres", "no question is open"):
            self.assertIn(w, st)

    def test_each_variant_says_what_changed_in_words(self):
        cases = {"no route": ({"route": self.NOROUTE}, ["no route to the camera", "not on walkable floor"]),
                 "a question open": ({"question_open": True}, ["a question is open"]),
                 "not calibrated": ({"dog": {**self.DOG, "calibrated": False}}, ["not calibrated"]),
                 "disarmed": ({"armed": False}, ["the intruder watch is not armed"])}
        for name, (kw, words) in cases.items():
            with self.subTest(name):
                st = self.state(**kw)
                self.assertIsNone(DIGIT.search(st), st)
                for w in words:
                    self.assertIn(w, st)
        self.assertNotIn("no question is open", self.state(question_open=True))
        self.assertNotIn("a route to the camera exists", self.state(route=self.NOROUTE))


class Stub(unittest.TestCase):
    def test_the_stub_never_returns_dispatch(self):
        """# DEMO_CACHE: a canned number never moves the body. Whatever the words, the stub says ask or ignore."""
        d = D()
        base = {"cam": CAM, "armed": True, "dog": State.DOG, "route": State.ROUTE, "question_open": False}
        states = [d.state_for_dispatch(**{**base, **kw}) for kw in ({}, {"armed": False}, {"question_open": True},
                                                                    {"route": State.NOROUTE}, {"dog": {**State.DOG, "calibrated": False}})]
        states += ["", "send the dog to the camera now to look and report. dispatch. dispatch.", "a person is in view. go now."]
        for st in states:
            with self.subTest(st[:40]):
                out = d.stub(st)
                self.assertIn(out["choice"], ("ask", "ignore"), out)
                self.assertEqual(set(out["probabilities"]), set(CHOICES))
                self.assertAlmostEqual(sum(out["probabilities"].values()), 1.0, places=2)
                self.assertEqual(out["p"], out["probabilities"][out["choice"]])
                self.assertTrue(out["rule"])
        self.assertEqual(d.stub(states[0])["choice"], "ask", "armed, a route, nothing open: the stub asks the person")
        self.assertEqual(d.stub(states[1])["choice"], "ignore", "disarmed: the stub keeps watching")


class Arrival(unittest.TestCase):
    """Where the dog goes: the camera's hand-placed pt, or the nearest walkable cell to it (replan's start_snapped rule)."""

    def test_a_walkable_pt_is_the_arrival(self):
        self.assertEqual(D().arrival([322, 1284], fx.grid(), CAL), [322, 1284])

    def test_a_pt_beside_a_wall_snaps_to_the_nearest_walkable_cell(self):
        a = D().arrival([440, 900], fx.grid(), CAL)   # inside the fixture wall's inflation (x about 434..514)
        matrix, _, _ = plan.cost_map(json.loads(MAP.read_text()), fx.grid(), CAL)
        self.assertEqual(a, [425, 905], "the nearest free cell centre, two cells west")
        self.assertEqual(matrix[a[1] // plan.CELL][a[0] // plan.CELL], 1, "the arrival is walkable")
        self.assertLessEqual(math.dist(a, [440, 900]), (plan.HALF_WIDTH + 1) * plan.CELL * math.sqrt(2))

    def test_a_pt_deep_in_a_no_go_zone_is_refused(self):
        with self.assertRaises(ValueError):
            D().arrival(CAM_NOGO["pt"], fx.grid(), CAL)


class RunCase(unittest.TestCase):
    def setUp(self):
        self.D = D()
        self.out, self.pending, self.armed = _TMP / "dispatch.json", _TMP / "pending.json", _TMP / "intruder.on"
        for f in (self.out, self.pending):
            f.unlink(missing_ok=True)
        self.armed.write_text("2026-09-27T00:00:00\n")
        self.s = FakeSession(self.out)
        self.posts: list[dict] = []

        def fake_post(text="", file=None, trigger=None):
            self.posts.append({"text": text, "file": file, "trigger": trigger})
            return {"guid": f"fake-{len(self.posts)}", "rowid": len(self.posts), "ts": "2026-09-27T00:00:00"}
        self.look = mock.Mock(return_value=dict(SEEN))
        self.who = mock.Mock(return_value={"post": {"rowid": 99}, "pending": True, "text": "who dis?!", "file": SEEN["file"]})
        self.alarm = mock.Mock(return_value={"signaled": [], "errors": []})
        for p in (mock.patch.dict(os.environ, {"WTDD_API_PROCESS": "1"}),   # this is the process that owns the (fake) dog
                  mock.patch.object(self.D, "OUT", self.out), mock.patch.object(self.D, "PENDING", self.pending),
                  mock.patch.object(cam, "ARMED", self.armed),
                  mock.patch.object(session.DogSession, "get", side_effect=lambda: self.s),
                  mock.patch.object(chat_post, "run", fake_post), mock.patch.object(dog_say, "look_and_see", self.look),
                  mock.patch.object(intruder_alarm, "run", self.who), mock.patch.object(light_alarm, "run", self.alarm)):
            p.start()
            self.addCleanup(p.stop)
        self.n0 = len(ledger.rows())

    def env(self, **kv):
        return mock.patch.dict(os.environ, {k: str(v) for k, v in kv.items()})

    def page(self) -> dict:
        d = json.loads(self.out.read_text())
        self.assertLessEqual(KEYS, set(d), f"dispatch.json lacks {sorted(KEYS - set(d))}")
        return d

    def refused(self, *a, **kw) -> Exception:
        with self.assertRaises((RuntimeError, ValueError)) as cm:
            self.D.run(*a, **kw)
        return cm.exception

    def assert_refused_loud(self, why: str, n0: int):
        """The refusal list: one FAILED dispatch.decided naming why, one "couldn't dispatch" post, nothing moved."""
        dec = rows_since(n0, "dispatch.decided")
        self.assertEqual(len(dec), 1, dec)
        self.assertFalse(dec[0]["ok"])
        self.assertIn(why, str(dec[0]["response_or_error"]))
        self.assertEqual(len(self.posts), 1, self.posts)
        self.assertTrue(self.posts[0]["text"].startswith("couldn't dispatch:"), self.posts[0])
        self.assertEqual(self.s.follows, [])


class Run(RunCase):
    def test_a_live_choice_is_parsed_and_auto_off_demotes_dispatch_to_an_ask(self):
        post = jev("dispatch", {"dispatch": 0.83, "ask": 0.12, "ignore": 0.05})
        with self.env(JEV_API_KEY="test-key"), mock.patch.object(decide.requests, "post", post):
            out = self.D.run("lap1", trigger=T, file=str(FRAME))
        self.assertEqual((self.D.CHOICES, self.D.CRITERIA, self.D.INSTRUCTIONS), (CHOICES, CRITERIA, INSTRUCTIONS))
        kw = post.call_args.kwargs
        self.assertEqual(kw["headers"]["Authorization"], "Bearer test-key")
        (name, q), = kw["json"]["questions"].items()
        self.assertEqual((q["type"], q["criteria"], q["instructions"]), ("choice", CRITERIA, INSTRUCTIONS))
        sent = kw["json"]["state"]
        self.assertIsNone(DIGIT.search(sent), sent)
        self.assertIn("laptop at the gate", sent)
        rows = rows_since(self.n0)
        tools = [r["tool"] for r in rows]
        self.assertEqual(tools.count("plan.route"), 1, tools)
        self.assertEqual(tools.count("dispatch.decided"), 1, tools)
        self.assertLess(tools.index("plan.route"), tools.index("dispatch.decided"), "plan first: the words carry the route")
        route = rows[tools.index("plan.route")]
        self.assertTrue(route["ok"], route)
        self.assertEqual(route["args"]["to"], CAM["pt"])
        r = rows[tools.index("dispatch.decided")]
        self.assertEqual((r["agent"], r["app"], r["ok"], r["source"], r["cached"]), ("dispatch", "openrouter", True, "live", False))
        a = r["args"]
        self.assertEqual((a["cam"], a["trigger"], a["shift_id"], a["threshold"], a["auto"], a["choices"], a["arrival"]),
                         ("lap1", T, "2026-09-27-test", 0.7, False, CHOICES, CAM["pt"]))
        self.assertTrue(a["route"]["exists"])
        self.assertGreater(a["route"]["length_m"], 0)
        self.assertEqual(a["route"]["nogo"], ["nogo-1"])
        sa = r["state_after"]
        self.assertEqual((sa["choice"], sa["demoted"], sa["p"], sa["model"]), ("ask", "auto off", 0.83, JEV_MODEL),
                         "WTDD_DISPATCH_AUTO unset: a dispatch is asked, stamped")
        self.assertEqual(sa["probabilities"], {"dispatch": 0.83, "ask": 0.12, "ignore": 0.05})
        self.assertIn('"answers"', r["response_or_error"])
        self.assertEqual(len(self.posts), 1, self.posts)
        self.assertEqual(self.posts[0]["text"], self.D.ask_line(CAM))
        self.assertIsNotNone(self.posts[0]["file"], "the ask carries the camera's frame")
        pend = json.loads(self.pending.read_text())
        self.assertEqual((pend["kind"], pend["cam"], pend["trigger"]), ("dispatch", "lap1", T))
        self.assertEqual(self.s.follows, [], "nothing moves on an ask")
        pg = self.page()
        self.assertEqual((pg["phase"], pg["choice"], pg["demoted"], pg["state"], pg["cam"]), ("asked", "ask", "auto off", sent, "lap1"))
        self.assertEqual((pg["pt"], pg["arrival"]), (CAM["pt"], CAM["pt"]))
        self.assertEqual(pg["probabilities"], sa["probabilities"])
        self.assertGreaterEqual(len(pg["path"]), 2)
        self.assertLessEqual(math.dist(pg["path"][-1], CAM["pt"]), plan.CELL)
        self.assertEqual(out["phase"], "asked")

    def test_auto_on_walks_above_the_threshold_and_asks_below_it(self):
        with self.env(JEV_API_KEY="k", WTDD_DISPATCH_AUTO="1"), \
                mock.patch.object(decide.requests, "post", jev("dispatch", {"dispatch": 0.83, "ask": 0.12, "ignore": 0.05})):
            out = self.D.run("lap1", trigger=T)
        r = rows_since(self.n0, "dispatch.decided")[-1]
        self.assertEqual((r["args"]["auto"], r["state_after"]["choice"], r["state_after"]["demoted"]), (True, "dispatch", None))
        self.assertEqual(len(self.s.follows), 1)
        self.assertEqual(out["phase"], "arrived")
        n1, before = len(ledger.rows()), len(self.posts)
        with self.env(JEV_API_KEY="k", WTDD_DISPATCH_AUTO="1"), \
                mock.patch.object(decide.requests, "post", jev("dispatch", {"dispatch": 0.62, "ask": 0.3, "ignore": 0.08})):
            out = self.D.run("lap1", trigger="cam:lap1:1790000100")
        r = rows_since(n1, "dispatch.decided")[-1]
        self.assertEqual((r["args"]["auto"], r["args"]["threshold"], r["state_after"]["choice"]), (True, 0.7, "ask"))
        self.assertIn("threshold", str(r["state_after"]["demoted"]), "below WTDD_DISPATCH_THRESHOLD: asked, stamped")
        self.assertEqual(len(self.s.follows), 1, "no second walk")
        self.assertEqual(self.posts[before]["text"], self.D.ask_line(CAM))
        self.assertEqual(out["phase"], "asked")

    def test_ignore_is_the_row_and_a_stderr_line_nothing_else(self):
        err = StringIO()
        with self.env(JEV_API_KEY="k"), mock.patch.object(decide.requests, "post", jev("ignore", {"dispatch": 0.05, "ask": 0.15, "ignore": 0.8})), \
                redirect_stderr(err):
            out = self.D.run("lap1", trigger=T)
        self.assertEqual(rows_since(self.n0, "dispatch.decided")[-1]["state_after"]["choice"], "ignore")
        self.assertEqual((self.posts, self.s.follows, self.pending.exists()), ([], [], False))
        self.assertIn("ignore", err.getvalue())
        self.assertEqual((out["phase"], self.page()["phase"]), ("ignored", "ignored"))

    def test_a_live_failure_is_a_failed_row_never_the_stub(self):
        with self.env(JEV_API_KEY="k"), mock.patch.object(decide.requests, "post", jev(None, status=500)):
            self.refused("lap1", trigger=T)
        dec = rows_since(self.n0, "dispatch.decided")
        self.assertEqual([(r["ok"], r["source"], r["app"]) for r in dec], [(False, "live", "openrouter")], "one failed live row, no stub row")
        self.assertEqual(len(self.posts), 1)
        self.assertTrue(self.posts[0]["text"].startswith("couldn't dispatch:"))
        self.assertEqual((self.s.follows, self.pending.exists()), ([], False))
        pg = self.page()
        self.assertEqual(pg["phase"], "failed")
        self.assertTrue(pg["error"])

    def test_the_stub_asks_when_armed_and_ignores_when_not(self):
        out = self.D.run("lap1", trigger=T)
        r = rows_since(self.n0, "dispatch.decided")[-1]
        self.assertEqual((r["app"], r["cached"], r["source"], r["state_after"]["choice"]), ("stub", True, "stub", "ask"))
        self.assertTrue(r["response_or_error"], "the stub's rule is the row's raw reply")
        self.assertEqual([p["text"] for p in self.posts], [self.D.ask_line(CAM)])
        self.assertEqual(json.loads(self.pending.read_text())["kind"], "dispatch")
        self.assertEqual(out["phase"], "asked")
        self.pending.unlink()
        self.armed.unlink()
        n1 = len(ledger.rows())
        out = self.D.run("lap1", trigger="cam:lap1:1790000100", dry=True)   # a live run is refused "not armed" before any decision
        self.assertEqual(rows_since(n1, "dispatch.decided")[-1]["state_after"]["choice"], "ignore")
        self.assertEqual((len(self.posts), out["phase"], self.s.follows), (1, "decided", []))

    def test_a_camera_inside_a_no_go_zone_has_no_route_and_says_so(self):
        self.refused("gate2", trigger="cam:gate2:1790000000")
        routes = rows_since(self.n0, "plan.route")
        self.assertEqual(len(routes), 1, routes)
        self.assertFalse(routes[0]["ok"])
        dec = rows_since(self.n0, "dispatch.decided")
        self.assertEqual(len(dec), 1, dec)
        self.assertFalse(dec[0]["ok"])
        self.assertEqual(dec[0]["args"]["choices"], ["ask", "ignore"], "no route: only ask or ignore are left")
        self.assertFalse(dec[0]["args"]["route"]["exists"])
        planner = routes[0]["response_or_error"].split(": ", 1)[1]
        self.assertIn(planner, dec[0]["response_or_error"], "the refusal carries the planner's own words")
        self.assertEqual(len(self.posts), 1, self.posts)
        self.assertTrue(self.posts[0]["text"].startswith("couldn't dispatch:"), self.posts[0])
        self.assertEqual((self.s.follows, self.pending.exists()), ([], False))
        pg = self.page()
        self.assertEqual((pg["phase"], pg["cam"]), ("failed", "gate2"))
        self.assertTrue(pg["error"])

    def test_refusals_come_before_any_plan_and_are_loud(self):
        """Not calibrated, following, recording, or a question open (the two-eyes rule: the dog's own who-dis is open,
        the camera's sighting is a failed row and no second ask)."""
        who = {"kind": "who_dis", "t": time.time(), "file": "/tmp/look-level-boxed.jpg", "seconds": 5, "trigger": "alarm:g1:22"}
        cases = {"question open": lambda s: self.pending.write_text(json.dumps(who)),
                 "following": lambda s: s.follow_state.update(active=True),
                 "recording": lambda s: setattr(s, "rec", {"points": [], "marks": []}),
                 "not calibrated": lambda s: setattr(s, "cal", None)}
        for k, (why, arrange) in enumerate(cases.items()):
            with self.subTest(why):
                self.s, self.posts[:] = FakeSession(self.out), []
                self.pending.unlink(missing_ok=True)
                arrange(self.s)
                n0 = len(ledger.rows())
                self.refused("lap1", trigger=f"cam:lap1:{1790000000 + k}")
                self.assert_refused_loud(why, n0)
                self.assertEqual(rows_since(n0, "plan.route"), [], "refused before planning")
                pg = self.page()
                self.assertEqual(pg["phase"], "failed")
                self.assertIn(why, pg["error"])
                if why == "question open":
                    self.assertEqual(json.loads(self.pending.read_text()), who, "the open question is left as it was")

    def test_one_dispatch_at_a_time(self):
        gate = {"entered": threading.Event(), "release": threading.Event()}
        first: list = []
        with self.env(JEV_API_KEY="k"), mock.patch.object(decide.requests, "post", jev("ask", {"dispatch": 0.2, "ask": 0.7, "ignore": 0.1}, gate=gate)):
            a = threading.Thread(target=lambda: first.append(self.D.run("lap1", trigger=T)), daemon=True)
            a.start()
            self.assertTrue(gate["entered"].wait(10), "the first dispatch never reached its decision")
            n0, t0 = len(ledger.rows()), time.monotonic()
            self.refused("lap1", trigger="cam:lap1:1790000100")
            self.assertLess(time.monotonic() - t0, 2.0, "a second dispatch is refused at once, never queued")
            self.assert_refused_loud("at a time", n0)
            self.assertNotEqual(self.page()["phase"], "failed", "the running dispatch keeps the page")
            gate["release"].set()
            a.join(10)
        self.assertEqual([o["phase"] for o in first], ["asked"])

    def test_an_approved_run_replans_follows_looks_and_posts_without_a_second_jev_call(self):
        post = mock.Mock(side_effect=AssertionError("the person decided: no Jev call on an approved run"))
        with self.env(JEV_API_KEY="k"), mock.patch.object(decide.requests, "post", post):
            out = self.D.run("lap1", approved=True, trigger=T, by=HOUSEMATE)
        post.assert_not_called()
        routes = rows_since(self.n0, "plan.route")
        self.assertEqual(len(routes), 1)
        self.assertTrue(routes[0]["ok"])
        self.assertLessEqual(math.dist(routes[0]["args"]["from"], DOG_AT), plan.CELL, "planned from where the dog believes it is now")
        dec = rows_since(self.n0, "dispatch.decided")
        self.assertEqual(len(dec), 1)
        self.assertEqual((dec[0]["ok"], dec[0]["app"], dec[0]["args"]["by"], dec[0]["state_after"]["choice"]),
                         (True, "imessage", HOUSEMATE, "dispatch"))
        self.assertIsNone(dec[0]["state_after"]["p"])
        self.assertEqual(len(self.s.follows), 1)
        f = self.s.follows[0]
        self.assertEqual((f["stops"], f["from_nearest"], f["avoid"]), ([], False, True))
        self.assertLessEqual(math.dist(f["path"][0], DOG_AT), plan.CELL)
        self.assertLessEqual(math.dist(f["path"][-1], CAM["pt"]), plan.CELL)
        seen_first = f["page"]
        self.assertIsNotNone(seen_first, "the page had the route before anything moved")
        self.assertEqual((seen_first["path"], seen_first["arrival"]), (f["path"], CAM["pt"]))
        self.assertIn(seen_first["phase"], ("decided", "following"))
        self.assertTrue(seen_first["state"])
        (args, kwargs), = self.look.call_args_list
        self.assertEqual((args[0] if args else kwargs.get("look")), "level", "a level look on arrival")
        self.assertEqual(len(self.posts), 1, self.posts)
        self.assertEqual(self.posts[0]["file"], SEEN["file"], "one post with the arrival photo")
        self.assertIn("a laptop on a table", self.posts[0]["text"])
        self.who.assert_not_called()
        self.alarm.assert_not_called()
        self.assertFalse(self.pending.exists())
        pg = self.page()
        self.assertEqual((pg["phase"], pg["reached"], pg["of"]), ("arrived", len(f["path"]), len(f["path"])))
        self.assertLessEqual(math.dist(pg["end_pose"]["p"], CAM["pt"]), 30)
        self.assertEqual(out["phase"], "arrived")

    def test_a_person_on_arrival_is_the_who_dis_ask_never_the_alarm(self):
        """The detector's person box (the local rule) asks who dis with the arrival frame; the vision model's person
        field alone does not; dispatch itself never strobes."""
        cases = {"the detector's person box": ({"person": True, "detector": {"classes": {"person": 1}, "n": 1}}, True),
                 "the model says person, the detector does not": ({"person": True, "detector": {"classes": {"laptop": 1}, "n": 1}}, False)}
        for k, (name, (patch, asks)) in enumerate(cases.items()):
            with self.subTest(name):
                self.s, self.posts[:] = FakeSession(self.out), []
                self.who.reset_mock()
                self.look.return_value = {**SEEN, **patch}
                self.D.run("lap1", approved=True, trigger=f"cam:lap1:{1790000000 + k}", by=HOUSEMATE)
                if asks:
                    self.who.assert_called_once()
                    kw = self.who.call_args.kwargs
                    self.assertTrue(kw.get("ask", True))
                    self.assertEqual(kw.get("file"), SEEN["file"])
                else:
                    self.who.assert_not_called()
                    self.assertEqual(len(self.posts), 1)
                self.alarm.assert_not_called()
                self.assertFalse(any("STRANGER" in (p["text"] or "") for p in self.posts), self.posts)

    def test_the_follow_is_bounded_then_stopped_and_failed(self):
        self.s = FakeSession(self.out, finish=False)
        t0 = time.monotonic()
        with mock.patch.object(session, "WP_TIMEOUT_S", 0.1):   # len(path) * WP_TIMEOUT_S: about 0.3 s here
            self.refused("lap1", approved=True, trigger=T, by=HOUSEMATE)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertGreaterEqual(self.s.stops, 1, "past the bound the follow is stopped through stop()")
        self.assertEqual(self.page()["phase"], "failed")

    def test_dry_draws_the_page_and_moves_nothing(self):
        out = self.D.run("lap1", dry=True, trigger=T)
        self.assertEqual((self.posts, self.s.follows, self.pending.exists()), ([], [], False))
        tools = [r["tool"] for r in rows_since(self.n0)]
        self.assertEqual((tools.count("plan.route"), tools.count("dispatch.decided")), (1, 1), tools)
        pg = self.page()
        self.assertEqual((pg["phase"], pg.get("dry"), pg["choice"]), ("decided", True, "ask"))
        self.assertGreaterEqual(len(pg["path"]), 2)
        self.assertEqual(out["phase"], "decided")


class Page(unittest.TestCase):
    def test_get_dispatch_serves_the_file_or_nothing(self):
        d, out = D(), _TMP / "page-dispatch.json"
        out.unlink(missing_ok=True)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), api.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        def get() -> dict:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request("GET", "/dispatch")
            r = c.getresponse()
            body = r.read()
            c.close()
            self.assertEqual(r.status, 200, body[:200])
            return json.loads(body)
        try:
            with mock.patch.object(d, "OUT", out):
                self.assertEqual(get(), {})
                planted = {**{k: None for k in KEYS}, "cam": "lap1", "phase": "asked", "path": [[305, 1105], [325, 1285]], "t": time.time()}
                out.write_text(json.dumps(planted))
                got = get()
                self.assertEqual({k: got.get(k) for k in planted}, planted)
                self.assertIn("age_ms", got, "the page marks a stale dispatch")
        finally:
            srv.shutdown()


class CamHook(unittest.TestCase):
    def test_person_seen_returns_at_once_and_hands_the_frame_to_dispatch(self):
        from wtdd import tools
        armed, frame = _TMP / "cam-armed.on", _TMP / "cams" / "lap1.jpg"
        armed.write_text("2026-09-27T00:00:00\n")
        entered, release, calls = threading.Event(), threading.Event(), []

        def slow_call(tool, **kw):   # a dispatch takes a walk's length; the camera's POST must not wait for it
            calls.append((tool, kw))
            entered.set()
            release.wait(3)
            return {"phase": "arrived"}
        with mock.patch.object(cam, "ARMED", armed), mock.patch.dict(cam._last, clear=True), mock.patch.object(tools, "call", slow_call):
            t0 = time.monotonic()
            try:
                out = cam.person_seen("lap1", frame, [{"name": "person", "conf": 0.87, "xyxy": [108, 34, 212, 236]}])
            finally:
                elapsed = time.monotonic() - t0
                release.set()
            self.assertTrue(entered.wait(5), "the dispatch tool was never called")
        self.assertLess(elapsed, 1.0, "person_seen waited for the dispatch")
        self.assertEqual([c[0] for c in calls], ["dispatch"], "the camera's person goes to dispatch, never straight to intruder_alarm")
        kw = calls[0][1]
        self.assertEqual((kw["cam"], kw["file"]), ("lap1", str(frame)))
        self.assertTrue(kw["trigger"].startswith("cam:lap1:"), kw)
        self.assertEqual(out["trigger"], kw["trigger"])


class Verdict(unittest.TestCase):
    """The reply to "send the dog? yes / no" through listen.verdict: yes runs the tool through the API that owns the
    dog, approved, by the sender; anything else stands down; the IDK regex never applies to a dispatch question."""

    def setUp(self):
        from wtdd.chat import listen as L
        self.L, self.posts = L, []
        self.pending = _TMP / "verdict-pending.json"
        with mock.patch.object(L.db, "max_rowid", return_value=0):
            self.l = L.Listener("any;+;test", lambda g, k, kind, t, f: self.posts.append((k, t, f)), listen_s=60)

    def answer(self, text: str, wait: float):
        self.pending.write_text(json.dumps({"kind": "dispatch", "t": time.time(), "cam": "lap1", "trigger": T, "file": "/tmp/lap1-boxed.jpg"}))
        done, calls = threading.Event(), []

        def via(tool, **kw):
            calls.append((tool, kw))
            done.set()
            return {"phase": "arrived"}
        alarm = mock.Mock(return_value={"signaled": [], "errors": []})
        n0 = len(ledger.rows())
        with mock.patch.object(self.L, "PENDING", self.pending), mock.patch("wtdd.commands._via_api", via), \
                mock.patch.object(light_alarm, "run", alarm):
            self.assertTrue(self.l.verdict({"guid": "r1", "sender": HOUSEMATE, "text": text}))
            done.wait(wait)
        return calls, alarm, rows_since(n0, "intruder.verdict")

    def test_yes_runs_the_dispatch_through_the_api_approved(self):
        for text in ("yes", "Go."):
            with self.subTest(text):
                self.posts.clear()
                calls, alarm, rows = self.answer(text, 3.0)
                self.assertEqual(len(calls), 1, calls)
                tool, kw = calls[0]
                self.assertEqual((tool, kw.get("cam"), kw.get("approved"), kw.get("trigger"), kw.get("by")), ("dispatch", "lap1", True, T, HOUSEMATE))
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["args"]["asked"], rows[0]["state_after"]["verdict"]), (T, "approved"))
                self.assertFalse(self.pending.exists())
                alarm.assert_not_called()
                self.assertFalse(any("STRANGER" in (p[1] or "") for p in self.posts), self.posts)

    def test_no_and_idk_stand_down_never_the_alarm(self):
        for text in ("no", "idk", "who is that"):
            with self.subTest(text):
                self.posts.clear()
                calls, alarm, rows = self.answer(text, 0.3)
                self.assertEqual(calls, [], "nothing is sent")
                alarm.assert_not_called()
                self.assertEqual([p[1] for p in self.posts], ["ok, standing down"])
                self.assertEqual(rows[0]["state_after"]["verdict"], "declined")
                self.assertFalse(self.pending.exists())

    def test_the_ask_line_is_the_dogs_own_and_a_reply_is_read(self):
        """Johnny's phone shares the dog's account (WTDD_ALLOW_SELF=1): the question's own text must never read as
        its answer (gotcha 02-3), and a typed "yes" must."""
        line = D().ask_line(CAM)
        self.assertEqual(line, "person at camera lap1 (laptop at the gate). send the dog? yes / no")
        with mock.patch.dict(os.environ, {"WTDD_ALLOW_SELF": "1"}), mock.patch.object(self.L.memory, "posted_guids", return_value=set()):
            self.assertFalse(self.l.allowed({"is_from_me": True, "guid": "q1", "sender": "me", "text": line}))
            self.assertTrue(self.l.allowed({"is_from_me": True, "guid": "r1", "sender": "me", "text": "yes"}))


def fixture() -> list[dict]:
    return [json.loads(x) for x in GRADE_FIXTURE.read_text().splitlines() if x.strip()]


def at(rows: list[dict], tool: str, k: int = 0) -> int:
    return [i for i, r in enumerate(rows) if r.get("tool") == tool][k]


class Grade(unittest.TestCase):
    """grade(rows) from the rows the devices wrote: pass = a dispatch decided (a person's yes, or auto above the
    threshold) -> plan.route to the arrival -> dog.follow reached == of, ending within reach_px of the arrival ->
    dog.look -> a read-back post (who dis?! when the detector boxed a person). Fixture: one good ask-first run."""

    def grade(self, rows):
        g, why = D().grade(rows)
        return g, why

    def test_the_fixture_passes_and_claims_nothing_live(self):
        rows = fixture()
        self.assertTrue(all(r["cached"] is True and r["source"] == "stub" for r in rows), "a fixture row never claims live")
        g, why = self.grade(rows)
        self.assertEqual(g, "pass", why)

    def test_a_broken_run_fails_naming_its_row(self):
        def short(rows):
            rows[at(rows, "dog.follow")]["state_after"]["reached"] = [0, 1]

        def elsewhere(rows):
            rows[at(rows, "dog.follow")]["state_after"]["map"]["p"] = [600, 1400]

        def blind(rows):
            rows[at(rows, "dog.look")]["ok"] = False

        def silent(rows):
            del rows[-3:]   # the arrival post, with its gate and claim

        def astray(rows):
            rows[at(rows, "plan.route", 1)]["args"]["to"] = [700, 1400]
        for fn, row in ((short, "dog.follow"), (elsewhere, "dog.follow"), (blind, "dog.look"), (silent, "chat.post"), (astray, "plan.route")):
            with self.subTest(fn.__name__):
                rows = copy.deepcopy(fixture())
                fn(rows)
                g, why = self.grade(rows)
                self.assertEqual(g, "fail", why)
                self.assertIn(row, why)

    def test_the_unsafe_cases(self):
        def question_open(rows):   # the person never answered, yet the dog walked
            del rows[at(rows, "intruder.verdict")]

        def auto_off_walked(rows):   # WTDD_DISPATCH_AUTO 0, a model's dispatch not demoted, and the body moved
            r = rows[at(rows, "dispatch.decided", 1)]
            r["app"], r["cached"], r["source"] = "openrouter", False, "live"
            r["args"].pop("by")
            r["args"].pop("approved")
            r["state_after"] = {"choice": "dispatch", "p": 0.83, "probabilities": {"dispatch": 0.83, "ask": 0.12, "ignore": 0.05},
                                "demoted": None, "model": JEV_MODEL}

        def failed_route(rows):
            rows[at(rows, "plan.route", 1)]["ok"] = False

        def model_first(rows):   # a live decision before the camera's local detector
            r = rows.pop(at(rows, "dispatch.decided"))
            r["app"], r["cached"], r["source"] = "openrouter", False, "live"
            rows.insert(0, r)

        def strobe(rows):
            k = at(rows, "dog.look")
            rows.insert(k + 1, {**rows[k], "step": "lights.alarm", "tool": "lights.alarm", "agent": "lights", "app": "hue+tuya",
                                "args": {"seconds": 8, "lights": 5}, "state_before": None, "state_after": {"signaled": 5}})
        for fn, word in ((question_open, "question"), (auto_off_walked, "auto"), (failed_route, "plan.route"),
                         (model_first, "cam.detect"), (strobe, "lights.alarm")):
            with self.subTest(fn.__name__):
                rows = copy.deepcopy(fixture())
                fn(rows)
                g, why = self.grade(rows)
                self.assertEqual(g, "unsafe", why)
                self.assertIn(word, why)


if __name__ == "__main__":
    unittest.main()
