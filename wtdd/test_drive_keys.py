"""S1 · the remote drives the dog from the keyboard only while armed in #admin, and leaving the tab stops a held key.

Found live on 2026-09-27: ui/index.html listened for W A S D Q E on the whole window in every view, exempted only
<input>, and had no blur handler, so a key held when focus left the tab kept POSTing /dog/drive every 200 ms and the
server's 0.6 s dead-man never fired. This reads the page's source (the way the page tests on the branches do); the
real-browser check is in the PR body.
  python -m unittest wtdd.test_drive_keys
"""
import pathlib
import re
import unittest

PAGE = (pathlib.Path(__file__).resolve().parent.parent / "ui" / "index.html").read_text()


def line(prefix: str) -> str:
    m = re.search(r"^\s*" + re.escape(prefix) + r".*$", PAGE, re.M)
    if not m:
        raise AssertionError(f"no line starting {prefix!r} in ui/index.html")
    return m.group(0)


class DriveKeys(unittest.TestCase):
    def test_the_keyboard_is_disarmed_by_default(self):
        self.assertIn("const armedRef = useRef(false)", PAGE)
        self.assertIn("const [armed, setArmed] = useState(false)", PAGE)

    def test_a_keydown_drives_only_while_armed(self):
        kd = line("const kd = e =>")
        self.assertIn("!armedRef.current", kd)

    def test_typing_or_a_shortcut_is_never_driving(self):
        kd = line("const kd = e =>") + line("const typing = e =>")
        for word in ("isContentEditable", "INPUT", "TEXTAREA", "SELECT", "e.ctrlKey", "e.metaKey", "e.altKey"):
            self.assertIn(word, kd, word)

    def test_leaving_the_tab_releases_every_key_and_disarms(self):
        self.assertIn('window.addEventListener("blur", off)', PAGE)
        self.assertIn('document.addEventListener("visibilitychange", vis)', PAGE)
        self.assertIn("arm(false)", line("const off = () =>"))
        ra = line("const releaseAll = () =>")
        self.assertIn("keys.current.clear()", ra)
        self.assertIn("clearInterval(driveTimer.current)", ra)
        self.assertIn('if (held) post("/dog/stop")', ra)   # a stop only when a key was held: a blur never cuts a route walk

    def test_leaving_admin_disarms(self):
        self.assertIn("if (!admin) arm(false)", PAGE)

    def test_the_arm_is_a_visible_toggle_in_admin(self):
        self.assertRegex(PAGE, r"onClick=\$\{\(\) => arm\(!armed\)\}")
        self.assertIn("keys drive", PAGE)


if __name__ == "__main__":
    unittest.main()
