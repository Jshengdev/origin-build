"""Modes are a vocabulary, not a new detector (roadmap 20), offline. Run: python -m unittest wtdd.test_vocab -v
RED first. Today the vision prompt dog_say.see() sends hard-codes "80 COCO classes, it cannot say sock or clothes" and
carries no word list, ui/map.json has no `vocab`, wtdd/vocab.py does not exist, wtdd/watch.py's docstring claims
Apache-2.0 weights and model.predict gets no device, GET /dog/state carries no mode. What must become true:
  ui/map.json `vocab`     {house: [12 words], site: [14 words]}, verbatim from the goal, separate from a decision `labels`;
                          'person' in both and the only person word (the alarm keys on the exact name, wtdd/watch.py)
  wtdd/vocab.py           words(mode=None, m=None) the mode's list (mode: WTDD_MODE through config.get at the point of use;
                          m: load_map(), ui/map.json under wtdd.config.ROOT, re-read every call); a mode not house|site is
                          a ValueError naming it and both modes; a list missing on the map is a LookupError naming the
                          mode and `vocab`, never a default. status(mode=None, m=None) -> {mode, vocab, vocab_error} with
                          vocab_error "vocab missing on the map" (the page's yellow state) instead of the LookupError.
                          sentence(mode=None) -> "name it from this list when it fits, else say what it is: w1, w2, ...".
                          Importing it raises on an empty or misnamed WTDD_MODE and on a missing list (the API imports
                          it at startup, so the API refuses to start).
  wtdd/tools/dog_say.py   the system text see() sends carries sentence() for the mode, with or without detector labels,
                          and no COCO-only wording; the detector's labels still reach the model; vocab is imported inside
                          see(), never at module top (python -m wtdd list imports every tool)
  wtdd/watch.py           docstring AGPL-3.0, not Apache-2.0; WTDD_WATCH_DEVICE reaches model.predict (unset = cpu);
                          mps asked while torch.backends.mps.is_available() is False logs one WARN and runs on cpu;
                          detect()'s boxes stay {name, conf, xyxy}
  wtdd/api.py             GET /dog/state carries mode, vocab, vocab_error; GET /map serves the vocab
  ui/index.html           one component between `// 20 · mode-vocabulary · start` and `· end`, rendering vocab_error
  .env.example            WTDD_MODE= under the marker `# 20 · mode-vocabulary`
  docs/gotchas/20-1-yolo-weights-are-agpl.md; docs/evidence/night-2/20-remote.png and 20-failed.png
  docs/evidence/night-2/detectors-2026-09-26.json   numbers only, written by docs/evidence/night-2/detectors.py
The model is never called here: wtdd.llm.generate is replaced by a recorder. The Draft07 case is skipped on main (07's
wtdd/dog/objects.py is not on this base) and runs after the rebase onto feat/07-objects. The Api cases start
python -m wtdd.api on port 7927 (the item's dry port) and stop it."""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

os.environ["WTDD_MODE"] = "site"
os.environ["WTDD_LEDGER"] = os.path.join(tempfile.mkdtemp(), "ledger.jsonl")   # before any wtdd import: never the real ledger
os.environ["WTDD_HOUSEMATE_NAMES"] = ""   # env wins over .env: no names in the prompt text under test

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
PORT = 7927
HOUSE = ("person", "cup", "sock", "clothes", "backpack", "bag", "chair", "couch", "laptop", "bottle", "blanket", "trash")
SITE = ("person", "traffic cone", "ladder", "pallet", "cable", "spill", "open cover", "trench", "fire extinguisher",
        "hard hat", "shovel", "hose", "barrier tape", "puddle")
OTHER_PERSON_WORDS = ("man", "woman", "people", "someone", "human", "worker", "child")
SENTENCE = "name it from this list when it fits, else say what it is"
COCO_ONLY = ("COCO", "cannot say")
REPLY = json.dumps({"say": "a traffic cone on the floor", "person": False, "out_of_place": ["traffic cone"], "pick": 2,
                    "why": "the cone", "detector_check": "agree"})
EVIDENCE = ROOT / "docs" / "evidence" / "night-2"
ARTEFACT = EVIDENCE / "detectors-2026-09-26.json"
FRAMES = ("look-tilt", "look-down", "dog-live", "look-level", "dog-sit-look")
PICTURES = Path("~/Pictures/wtdd").expanduser()


def _map() -> dict:
    return json.loads((ROOT / "ui" / "map.json").read_text())


def _jpeg(path: Path) -> Path:
    from PIL import Image
    Image.new("RGB", (32, 24), (90, 90, 90)).save(path, "JPEG")
    return path


class Lists(unittest.TestCase):
    def test_map_has_both_lists_verbatim(self):
        m = _map()
        self.assertIn("vocab", m, "ui/map.json has no `vocab`")
        self.assertIsInstance(m["vocab"], dict, "`vocab` is one object keyed by mode")
        self.assertEqual(sorted(m["vocab"]), ["house", "site"])
        self.assertEqual(m["vocab"]["house"], list(HOUSE))
        self.assertEqual(m["vocab"]["site"], list(SITE))

    def test_vocab_is_not_the_decision_labels(self):
        self.assertNotIn(_map().get("labels"), (list(HOUSE), list(SITE)), "the vocabulary is separate from 17's decision `labels`")

    def test_person_is_the_only_person_word(self):
        v = _map().get("vocab") or {}
        for words in (HOUSE, SITE, tuple(v.get("house") or ()), tuple(v.get("site") or ())):
            self.assertEqual([w for w in OTHER_PERSON_WORDS if w in words], [], "another person word bypasses `\"person\" in now`")
        for mode in ("house", "site"):
            self.assertIn("person", v.get(mode) or (), f"`vocab.{mode}` must carry the exact word person")


class Words(unittest.TestCase):
    FULL = {"vocab": {"house": list(HOUSE), "site": list(SITE)}}

    def test_words_for_each_mode(self):
        from wtdd import vocab
        self.assertEqual(vocab.words("site", self.FULL), list(SITE))
        self.assertEqual(vocab.words("house", self.FULL), list(HOUSE))
        self.assertEqual(vocab.words(), list(SITE), "mode from WTDD_MODE, list from ui/map.json")
        with mock.patch.dict(os.environ, {"WTDD_MODE": "house"}):
            self.assertEqual(vocab.words(), list(HOUSE), "WTDD_MODE is read at the point of use")

    def test_missing_list_raises_with_the_message_never_a_default(self):
        from wtdd import vocab
        for m in ({"vocab": {"house": list(HOUSE)}}, {"vocab": {}}, {}):
            with self.assertRaises(LookupError, msg=f"map {m!r}") as cm:
                vocab.words("site", m)
            self.assertIn("site", str(cm.exception))
            self.assertIn("vocab", str(cm.exception))

    def test_misnamed_mode_raises_naming_both_modes(self):
        from wtdd import vocab
        with self.assertRaises(ValueError) as cm:
            vocab.words("garden", self.FULL)
        for w in ("garden", "house", "site"):
            self.assertIn(w, str(cm.exception))

    def test_status_is_the_page_state(self):
        from wtdd import vocab
        self.assertEqual(vocab.status("site", self.FULL), {"mode": "site", "vocab": list(SITE), "vocab_error": None})
        bad = vocab.status("site", {"vocab": {"house": list(HOUSE)}})
        self.assertEqual((bad["mode"], bad["vocab"]), ("site", None))
        self.assertIn("vocab missing on the map", bad["vocab_error"])
        with self.assertRaises(ValueError):   # a misnamed mode is not a page state: the API refused to start on it
            vocab.status("garden", self.FULL)

    def test_sentence_carries_the_words(self):
        from wtdd import vocab
        s = vocab.sentence("site")
        self.assertIn(SENTENCE, s.lower())
        self.assertEqual([w for w in SITE if w not in s], [])
        self.assertNotIn("cup", s)

    def test_import_refuses_empty_misnamed_or_missing(self):
        planted = tempfile.mkdtemp()
        (Path(planted) / "ui").mkdir()
        (Path(planted) / "ui" / "map.json").write_text(json.dumps({"vocab": {"house": list(HOUSE)}}))
        missing = f"import pathlib, wtdd.config as c; c.ROOT = pathlib.Path({planted!r}); import wtdd.vocab"
        for mode, code, needles in (("", "import wtdd.vocab", ("WTDD_MODE",)),
                                    ("garden", "import wtdd.vocab", ("garden", "house", "site")),
                                    ("site", missing, ("site", "vocab"))):
            pr = subprocess.run([PY, "-c", code], cwd=ROOT, env={**os.environ, "WTDD_MODE": mode}, capture_output=True, text=True, timeout=60)
            self.assertNotIn("ModuleNotFoundError", pr.stderr, "wtdd/vocab.py does not exist")
            self.assertNotEqual(pr.returncode, 0, f"WTDD_MODE={mode!r}: `{code[-16:]}` succeeded; it must raise with the message")
            last = (pr.stderr.strip().splitlines() or [""])[-1]
            for n in needles:
                self.assertIn(n, last, f"WTDD_MODE={mode!r}: the raised message must name {n!r}")


class Prompt(unittest.TestCase):
    """The system text dog_say.see() sends to the vision model, read off a recording generate()."""

    @classmethod
    def setUpClass(cls):
        d = Path(tempfile.mkdtemp())
        cls.room, cls.floor = str(_jpeg(d / "room.jpg")), str(_jpeg(d / "floor.jpg"))

    def _system(self, labels=None) -> str:
        from wtdd.tools import dog_say
        with mock.patch("wtdd.llm.generate", return_value={"text": REPLY, "model": "stub"}) as gen, \
                mock.patch.object(dog_say, "corrections", return_value=[]):
            dog_say.see(self.room, None, self.floor, labels=labels)
        self.assertEqual(gen.call_count, 1)
        return gen.call_args.args[1][0]["content"]

    def test_site_prompt_carries_the_site_words_and_no_coco_wording(self):
        text = self._system({"chair": 1, "person": 2})
        self.assertIn(SENTENCE, text.lower())
        self.assertEqual([w for w in SITE if w not in text], [], "site words missing from the prompt")
        self.assertEqual([b for b in COCO_ONLY if b in text], [], "COCO-only wording still in the prompt")
        self.assertIn("chair x1", text, "the detector's labels still reach the model")
        self.assertIn("person x2", text)

    def test_house_prompt_carries_the_house_words(self):
        with mock.patch.dict(os.environ, {"WTDD_MODE": "house"}):
            text = self._system({"cup": 1})
        self.assertIn(SENTENCE, text.lower())
        self.assertEqual([w for w in HOUSE if w not in text], [], "house words missing from the prompt")
        self.assertNotIn("traffic cone", text)
        self.assertEqual([b for b in COCO_ONLY if b in text], [])

    def test_prompt_without_detector_labels_still_names_the_list(self):
        text = self._system(None)
        self.assertIn(SENTENCE, text.lower())
        self.assertIn("traffic cone", text)

    def test_missing_list_fails_loud_before_any_model_call(self):
        from wtdd import vocab
        from wtdd.tools import dog_say
        with mock.patch.object(vocab, "load_map", return_value={"vocab": {"house": list(HOUSE)}}), \
                mock.patch("wtdd.llm.generate", return_value={"text": REPLY, "model": "stub"}) as gen:
            with self.assertRaises(LookupError):
                dog_say.see(self.room, None, self.floor, labels={"chair": 1})
        self.assertEqual(gen.call_count, 0, "a missing list must fail before the model is called")


@unittest.skipUnless((ROOT / "wtdd" / "dog" / "objects.py").is_file(), "07's wtdd/dog/objects.py is not on this base (main); runs after the rebase onto feat/07-objects")
class Draft07(unittest.TestCase):
    def test_draft_prompt_carries_the_words(self):
        from wtdd.dog import objects
        obj = {"label": "traffic cone", "p": 0.61, "dist_m": None, "bearing_deg": None, "why": "no pose", "thumb": None}
        with mock.patch("wtdd.llm.generate", return_value={"text": "a traffic cone", "model": "stub"}) as gen:
            objects.draft_live(obj)
        text = gen.call_args.args[1][0]["content"]
        self.assertIn(SENTENCE, text.lower())
        self.assertEqual([w for w in SITE if w not in text], [])
        self.assertEqual([b for b in COCO_ONLY if b in text], [])


class _R:   # the one ultralytics Results field set detect() reads
    names = {0: "person"}

    class boxes:
        class cls:
            tolist = staticmethod(lambda: [0.0])

        class conf:
            tolist = staticmethod(lambda: [0.9])

        class xyxy:
            tolist = staticmethod(lambda: [[1.0, 2.0, 30.0, 20.0]])

    @staticmethod
    def plot():
        import numpy as np
        return np.zeros((24, 32, 3), np.uint8)


class Watch(unittest.TestCase):
    def test_docstring_names_the_real_licence(self):
        from wtdd import watch
        self.assertIn("AGPL-3.0", watch.__doc__)
        self.assertNotIn("Apache-2.0", watch.__doc__, "'Apache-2.0 weights' is false (ultralytics METADATA: AGPL-3.0)")

    def _once(self, env: dict, mps: bool) -> tuple[dict, str, dict]:
        """python -m wtdd.watch --source <tiny jpeg> --once --out <tmp> with ultralytics.YOLO replaced by a recorder."""
        import torch
        import ultralytics
        from wtdd import watch
        seen: dict = {}

        class Fake:
            def __init__(self, *a, **k):
                pass

            def predict(self, arr, **kw):
                seen.update(kw)
                return [_R()]

        d = Path(tempfile.mkdtemp())
        src, out = _jpeg(d / "frame.jpg"), d / "boxed.jpg"
        err, so = io.StringIO(), io.StringIO()
        keep = {k: v for k, v in os.environ.items() if k != "WTDD_WATCH_DEVICE"}
        with mock.patch.dict(os.environ, {**keep, **env}, clear=True), mock.patch.object(ultralytics, "YOLO", Fake), \
                mock.patch.object(torch.backends.mps, "is_available", return_value=mps), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(so):
            rc = watch.main(["--source", str(src), "--once", "--out", str(out)])
        self.assertEqual(rc, 0, err.getvalue()[-400:])
        return seen, err.getvalue(), json.loads(so.getvalue().strip().splitlines()[-1])

    def test_device_reaches_predict(self):
        kw, err, printed = self._once({}, mps=True)
        self.assertEqual(kw.get("device", "cpu"), "cpu", "unset WTDD_WATCH_DEVICE runs on cpu, as today")
        self.assertEqual([sorted(b) for b in printed["boxes"]], [["conf", "name", "xyxy"]], "detect()'s boxes changed")
        kw, err, _ = self._once({"WTDD_WATCH_DEVICE": "mps"}, mps=True)
        self.assertEqual(kw.get("device"), "mps", "WTDD_WATCH_DEVICE=mps must reach model.predict")
        self.assertNotIn("WARN", err)

    def test_mps_unavailable_warns_and_runs_on_cpu(self):
        kw, err, printed = self._once({"WTDD_WATCH_DEVICE": "mps"}, mps=False)
        self.assertEqual(kw.get("device"), "cpu", "mps asked and unavailable: cpu, never a crash, never silent")
        warn = [l for l in err.splitlines() if "WARN" in l and "mps" in l]
        self.assertEqual(len(warn), 1, f"one WARN line naming mps, got: {err[-400:]!r}")
        self.assertEqual(printed["boxes"][0]["name"], "person")


class Artefact(unittest.TestCase):
    """Every number about detectors is read from this file; it holds boxes and numbers, never a frame."""

    def _d(self) -> dict:
        self.assertTrue(ARTEFACT.is_file(), f"{ARTEFACT.relative_to(ROOT)} missing: run docs/evidence/night-2/detectors.py")
        raw = ARTEFACT.read_text()
        self.assertNotIn("base64", raw)
        self.assertLess(len(raw), 400_000, "a frame leaked into the artefact")
        return json.loads(raw)

    def test_numbers_only_on_the_five_real_frames(self):
        d = self._d()
        self.assertEqual([f["name"] for f in d["frames"]], list(FRAMES))
        for f in d["frames"]:
            self.assertEqual(sorted(f), ["bytes", "height", "name", "sha256", "width"])
            real = PICTURES / f"{f['name']}.jpg"
            if real.is_file():   # on this Mac: the artefact names the real frame by its hash
                self.assertEqual(f["sha256"], hashlib.sha256(real.read_bytes()).hexdigest(), f["name"])
        self.assertIn("scratch bench", d["wording"], "the comparison is worded as a scratch bench on this Mac")
        self.assertIn("yolo11n", d["detections"])
        for key, per in d["detections"].items():
            self.assertEqual(sorted(per), sorted(FRAMES), key)
            for name, fr in per.items():
                for b in fr["boxes"]:
                    self.assertEqual(sorted(b), ["conf", "name", "xyxy"], f"{key} {name}: detect()'s interface")
                    self.assertEqual(len(b["xyxy"]), 4)
        for m in d["models"]:
            if m["present"]:
                self.assertTrue(m.get("loaded") or m.get("error"), f"{m['key']}: present, neither loaded nor an error (a silent skip)")

    def test_recall_is_derived_from_the_boxes_in_the_file(self):
        d = self._d()
        conf = d["detect"]["conf"]
        for key, r in d["person_recall"].items():
            got = sum(any(b["name"] == "person" and b["conf"] >= conf for b in fr["boxes"]) for fr in d["detections"][key].values())
            self.assertEqual((r["frames_with_person"], r["of"]), (got, len(FRAMES)), f"{key}: a recall figure not read from its boxes")


class Page(unittest.TestCase):
    def test_component_block_renders_the_api_state(self):
        page = (ROOT / "ui" / "index.html").read_text()
        a, b = page.find("// 20 · mode-vocabulary · start"), page.find("// 20 · mode-vocabulary · end")
        self.assertTrue(0 <= a < b, "one component between the item's markers")
        self.assertIn("vocab_error", page[a:b], "the page renders the API's vocab_error; it computes nothing")

    def test_env_example_names_the_mode(self):
        lines = (ROOT / ".env.example").read_text().splitlines()
        self.assertIn("# 20 · mode-vocabulary", lines)
        at = [i for i, l in enumerate(lines) if l.startswith("WTDD_MODE=")]
        self.assertEqual(len(at), 1, ".env.example has no WTDD_MODE line")
        self.assertGreater(at[0], lines.index("# 20 · mode-vocabulary"))

    def test_gotcha(self):
        g = ROOT / "docs" / "gotchas" / "20-1-yolo-weights-are-agpl.md"
        self.assertTrue(g.is_file(), f"{g.relative_to(ROOT)} missing")
        text = g.read_text()
        for h in ("Symptom", "Root cause", "Fix", "Verify", "AGPL-3.0"):
            self.assertIn(h, text)

    def test_two_screenshots(self):
        for name in ("20-remote.png", "20-failed.png"):
            f = EVIDENCE / name
            self.assertTrue(f.is_file(), f"{f.relative_to(ROOT)} missing (no screenshot, no GREEN)")
            self.assertEqual(f.read_bytes()[:8], b"\x89PNG\r\n\x1a\n", name)
            self.assertLess(f.stat().st_size, 600_000, f"{name}: keep the committed PNG small")


class Api(unittest.TestCase):
    """python -m wtdd.api on PORT: under WTDD_MODE=site GET /dog/state carries the mode and GET /map the vocab; under a
    misnamed mode the API refuses to start."""

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=5) as r:
            return json.loads(r.read())

    def _start(self, mode: str):
        env = {**os.environ, "WTDD_MODE": mode, "WTDD_LEDGER": os.path.join(tempfile.mkdtemp(), "ledger.jsonl")}
        err = tempfile.TemporaryFile("w+")
        return subprocess.Popen([PY, "-m", "wtdd.api", str(PORT)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=err, text=True), err

    def _stop(self, pr) -> None:
        if pr.poll() is None:
            pr.terminate()
            try:
                pr.wait(5)
            except subprocess.TimeoutExpired:
                pr.kill()

    def test_misnamed_mode_refuses_to_start(self):
        pr, err = self._start("garden")
        try:
            t0, served = time.time(), False
            while pr.poll() is None and time.time() - t0 < 20 and not served:
                try:
                    self._get("/map")
                    served = True
                except Exception:  # noqa: BLE001  (not serving: what a refusal looks like)
                    time.sleep(0.2)
            self.assertFalse(served, "the API served /map under WTDD_MODE=garden; it must refuse to start")
            self.assertIsNotNone(pr.poll(), "the API neither served nor exited within 20 s")
            self.assertNotEqual(pr.returncode, 0)
            err.seek(0)
            text = err.read()
            for w in ("garden", "house", "site"):
                self.assertIn(w, text, "the refusal names the mode and both lists")
        finally:
            self._stop(pr)

    def test_state_carries_mode_and_map_carries_vocab(self):
        pr, err = self._start("site")
        try:
            t0 = time.time()
            while True:
                try:
                    m = self._get("/map")
                    break
                except Exception:  # noqa: BLE001  (not up yet, or it exited: decided here)
                    if pr.poll() is not None:
                        err.seek(0)
                        self.fail(f"the API exited rc={pr.returncode} before serving: {err.read()[-600:]}")
                    if time.time() - t0 > 15:
                        self.fail("the API did not serve /map within 15 s")
                    time.sleep(0.2)
            self.assertEqual((m.get("vocab") or {}).get("site"), list(SITE), "GET /map must carry the vocab")
            try:
                st = self._get("/dog/state")
            except Exception as e:  # noqa: BLE001
                self.fail(f"GET /dog/state failed ({type(e).__name__}: {e}); on a fresh dry API this is night-1 bug F3 until patch 3 is applied")
            self.assertEqual((st.get("mode"), st.get("vocab"), st.get("vocab_error")), ("site", list(SITE), None))
            self.assertIn("connected", st, "the dog's own state fields stay beside the mode")
        finally:
            self._stop(pr)


if __name__ == "__main__":
    unittest.main()
