"""Each look keeps its own photo. Run: python -m unittest wtdd.test_look_photos -v

Before this, DogSession._look wrote every frame to the fixed ~/Pictures/wtdd/look-<kind>.jpg and look-down.jpg, and
the detector's copy went to <name>-boxed.jpg beside it. send.stage() uses a file already in ~/Pictures/wtdd as is. So
each stop's look overwrote the previous stop's photo, every chat.post row of a round named the one newest image, and
after a real run only the last stop's photo was left on disk.

Offline, no dog, no API, no real photo: the session's Body is test_avoid_on's fake whose frame() here writes distinct
bytes on every call; PICTURES (the session's, send.stage's and dog_say's tidy lookup) is a temp dir; commands._via_api answers "no API up" so
nothing reaches 127.0.0.1:7788; the detector's subprocess is a fake that writes --out as the copy of --source, as
wtdd/watch.py's one-shot does; the vision model and the decision are patched; Messages is patched at osascript and
the chat.db read-back. The chat path above that is real: Listener.look_and_say, dog_say.look_and_see and boxed(),
chat __main__.post (gate, claim, the chat.post row) and send.send_file with its stage(). The ledger and memory.db are
temp files, set before wtdd.ledger is imported."""
from __future__ import annotations
import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-look-photos-test-")).resolve()   # resolved: stage() compares resolved parents
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")
os.environ["WTDD_MEMORY"] = str(_TMP / "memory.db")
os.environ["WTDD_CHAT_GUID"] = "any;+;00000000000000000000000000000000"
os.environ["WTDD_CHAT_NAME"] = "wtdd test"
for _k in ("WTDD_ON_CALL_NAME", "WTDD_ON_CALL_HANDLE", "WTDD_ON_CALL_GUID", "WTDD_ALARM", "WTDD_HOUSEMATE_NAMES", "JEV_API_KEY"):
    os.environ[_k] = ""   # config.maybe() reads an empty value as unset, and a .env value never refills it
os.environ["WTDD_SHIFT"] = "2026-09-27"

from wtdd import commands, decide, field, ledger  # noqa: E402
from wtdd.chat import __main__ as cli, db, listen, send  # noqa: E402
from wtdd.dog import session  # noqa: E402
from wtdd.dog.test_avoid_on import FakeBody, stop  # noqa: E402
from wtdd.tools import dog_say  # noqa: E402

GROUP = os.environ["WTDD_CHAT_GUID"]
PAGE = Path(__file__).resolve().parent.parent / "ui" / "index.html"
CONTINUE = {"label": "clear", "p": 0.9, "needs_person": False, "model": "stub", "action": "continue"}


def shot(n: int) -> bytes:
    return b"frame %d" % n   # not a photo: the bytes only have to differ between frames


def detector(cmd, **kw):
    """wtdd/watch.py --source S --once --out O, faked: O is S's bytes plus a marker; the one-shot's JSON line on stdout."""
    src, out = cmd[cmd.index("--source") + 1], cmd[cmd.index("--out") + 1]
    Path(out).write_bytes(Path(src).read_bytes() + b" boxed")
    line = {"ts": "2026-09-27T10:00:00", "ms": 1, "n": 0, "classes": {}, "boxes": [], "file": out}
    return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(line) + "\n", stderr="")


def seen(file, baseline=None, file_down=None, labels=None):
    return {"text": f"a clear floor at {Path(file).name}", "person": False, "out_of_place": [], "pick": 2, "why": "",
            "detector_check": "agree", "model": "stub", "ms": 1}


class LookPhotos(unittest.TestCase):
    def setUp(self):
        self.pics = _TMP / f"pictures-{self._testMethodName}"
        self.pics.mkdir()
        (_TMP / "ledger.jsonl").unlink(missing_ok=True)
        self.err = io.StringIO()
        self.enterContext(contextlib.redirect_stderr(self.err))
        self.enterContext(mock.patch.object(session, "PICTURES", self.pics))
        self.enterContext(mock.patch.object(send, "PICTURES", self.pics))
        self.enterContext(mock.patch.object(dog_say, "PICTURES", str(self.pics)))   # the tidy baseline lookup: never the real dir
        self.enterContext(mock.patch.object(session.asyncio, "sleep", mock.AsyncMock()))
        self.s = session.DogSession()
        self.b = FakeBody()
        self.frames = 0

        async def frame(out=None):
            self.frames += 1
            Path(out).write_bytes(shot(self.frames))
            return shot(self.frames)

        self.b.frame = frame
        self.b.raw = lambda: {"imu_state": {"rpy": [0.0, -0.3, 0.0]}}   # nose up 17 deg: the tilt fired on the first nod
        self.s.body = self.b

    def tearDown(self):
        stop(self.s)

    def looks(self) -> list[dict]:
        return [r["state_after"] for r in ledger.rows() if r["tool"] == "dog.look" and r["ok"]]

    def test_two_looks_leave_two_photos_each_named_on_its_own_row(self):
        for _ in range(2):
            self.s.run(self.s._look(self.b, "tilt"), timeout=10)
        looks = self.looks()
        self.assertEqual(len(looks), 2)
        named = [f for a in looks for f in (a["file_down"], a["file"])]   # frame order: the floor, then the room
        self.assertEqual(len(set(named)), 4, f"every frame its own file, never a fixed name: {[Path(f).name for f in named]}")
        for i, f in enumerate(named, 1):
            self.assertEqual(Path(f).parent, self.pics, f)
            self.assertEqual(Path(f).read_bytes(), shot(i), f"{Path(f).name} holds the frame its row names")

    def test_each_stops_post_names_its_own_photo(self):
        mp = _TMP / f"map-{self._testMethodName}.json"
        mp.write_text(json.dumps({"actions": {"1": {"look": "tilt"}, "2": {"look": "tilt"}}}))
        n = iter(range(60001, 60100))

        def from_me(guid, after, text, timeout_s=10.0):
            i = next(n)
            return {"guid": f"P-{i}", "rowid": i, "ts": "2026-09-27 17:00:00"}

        with mock.patch.object(commands, "_via_api", return_value=None), \
                mock.patch.object(session.DogSession, "get", return_value=self.s), \
                mock.patch("subprocess.run", detector), mock.patch.object(dog_say, "see", seen), \
                mock.patch.object(decide, "at_stop", return_value=("a clear floor", CONTINUE)), \
                mock.patch.object(field, "MAP", mp), mock.patch.object(db, "max_rowid", return_value=60000), \
                mock.patch.object(db, "chat_name", return_value="wtdd test"), \
                mock.patch.object(send, "_osascript", return_value=None), mock.patch.object(db, "find_from_me", from_me):
            lst = listen.Listener(GROUP, cli.post, listen_s=60)
            lst.look_and_say({"guid": "W1"}, at=1)
            lst.look_and_say({"guid": "W1"}, at=2)
        looks = self.looks()
        posts = [r for r in ledger.rows() if r["tool"] == "chat.post" and r["ok"]]
        self.assertEqual([p["args"]["trigger"] for p in posts], ["say:W1:1", "say:W1:2"])
        self.assertEqual(len(looks), 2)
        files = [p["args"]["file"] for p in posts]
        self.assertNotEqual(files[0], files[1], f"each stop's post names its own photo: {[Path(f).name for f in files]}")
        for i, (look, f) in enumerate(zip(looks, files)):
            room = Path(look["file"])
            self.assertEqual(f, str(room.with_name(room.stem + "-boxed.jpg")), "the post is the boxed copy of this stop's room frame")
            self.assertEqual(Path(f).read_bytes(), shot(2 * i + 2) + b" boxed", f"stop {i + 1}'s photo is still on disk after the round")
        staged = [p.name for p in self.pics.iterdir() if re.match(r"\d+-", p.name)]
        self.assertEqual(staged, [], "a look's file is already in ~/Pictures/wtdd: stage() sends it as is, no copy")

    def test_the_page_shows_the_rows_file_never_a_fixed_name(self):
        page = PAGE.read_text()
        self.assertEqual(re.findall(r"pictures/look-[^\"'`]*\.jpg", page), [],
                         "the remote's photos come from the dog.look row's file, never look-<kind>.jpg")


if __name__ == "__main__":
    unittest.main()
