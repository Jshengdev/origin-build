"""S10 · the page's Receipts are filmed: the Receipts line and the last-result line render their text through one
redact() that turns a phone handle ("+" and 7 to 15 digits) or an email into "a member". Dates, times, coordinates and
plain numbers are left alone. Reads ui/index.html's source, as test_drive_keys does; the pattern is taken from the
page's redact() line and run here with Python's re (it and the browser's RegExp agree on it: ASCII classes, no
lookbehind, no flags but g). The real-browser check is Johnny's, on the remote.
  python -m unittest wtdd.test_page_redact
"""
import pathlib
import re
import unittest

PAGE = (pathlib.Path(__file__).resolve().parent.parent / "ui" / "index.html").read_text()


def line(fragment: str) -> str:
    hits = [l for l in PAGE.splitlines() if fragment in l]
    if len(hits) != 1:
        raise AssertionError(f"{len(hits)} lines with {fragment!r} in ui/index.html, want 1")
    return hits[0]


def redact():
    m = re.search(r'^const redact = .*?\.replace\(/(.+?)/([a-z]*), "a member"\)', PAGE, re.M)
    if not m:
        raise AssertionError('no one-line `const redact = ... .replace(/.../g, "a member")` in ui/index.html')
    if "g" not in m.group(2):
        raise AssertionError("redact()'s pattern has no g flag: only the first handle would be replaced")
    rx = re.compile(m.group(1))
    return lambda s: rx.sub("a member", s)


class Redact(unittest.TestCase):
    def test_phones_and_emails_become_a_member(self):
        r = redact()
        self.assertEqual(r("+13105551234"), "a member")
        self.assertEqual(r("jo.smith+dog@gmail.com"), "a member")
        self.assertEqual(r('{"from":"+15550003333","text":"idk","to":"sam@example.org"}'),
                         '{"from":"a member","text":"idk","to":"a member"}')

    def test_dates_times_coordinates_and_numbers_survive(self):
        r = redact()
        for s in ("2026-09-27T03:10:50", "[441, 211]", "0.5 m", '{"px_per_m":108.5,"latency_ms":900}', "acked 12000 ms",
                  "+5 dB", "shift 2026-09-27"):
            self.assertEqual(r(s), s)

    def test_the_receipts_line_renders_through_redact(self):
        rec = line('filter(r => r.tool !== "pose.corrected").slice(0, 25)')
        for part in ("redact(r.args.say)", "redact(JSON.stringify(r.args)).slice(0, 60)", "redact(String(r.response_or_error"):
            self.assertIn(part, rec)
        self.assertNotIn("JSON.stringify(r.args).slice", rec)   # redact before the cut: a handle cut to 6 digits would slip past

    def test_the_last_result_line_renders_through_redact(self):
        res = line("${last.tool} ")
        self.assertIn("redact(JSON.stringify(last.args))", res)
        self.assertIn("redact(last.ok ?", res)


if __name__ == "__main__":
    unittest.main()
