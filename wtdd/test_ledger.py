"""b2 · the receipts read only the rows they return. Run: python -m unittest wtdd.test_ledger -v
ledger.rows(n) used to json-parse every row of the file and slice after: the page polls GET /ledger?n=25 every 2 s,
and a 32k-row ledger took ~200 ms a poll. Now it reads and splits the file as before (read_text, str.splitlines, blank
lines skipped) but parses only the lines it returns. These checks hold it to the old implementation (_old, main's
code verbatim) on a fixture with blank and whitespace-only lines, a CRLF line, raw unicode, non-dict JSON values and no
final newline, for n None, 0, positive, past the end and negative; a malformed line in the returned window, or anywhere
for rows(), raises the same JSONDecodeError as before. The one difference is named: with n, a malformed line OLDER than
the window is no longer parsed, so it no longer raises (rows() still does). The ledger is a temp file (ledger.LEDGER
patched; WTDD_LEDGER set before wtdd.ledger is imported), never <repo>/ledger.jsonl."""
from __future__ import annotations
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMP = Path(tempfile.mkdtemp(prefix="wtdd-ledger-test-"))
os.environ["WTDD_LEDGER"] = str(_TMP / "ledger.jsonl")

from wtdd import ledger  # noqa: E402


def _old(path: Path, n: int | None = None) -> list:
    """rows(n) as it was on main (6786bde), with the file as an argument."""
    if not path.exists():
        return []
    out = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return out[-n:] if n else out


class Rows(unittest.TestCase):
    def setUp(self):
        self.f = Path(tempfile.mkdtemp(dir=_TMP)) / "ledger.jsonl"
        p = mock.patch.object(ledger, "LEDGER", self.f)
        p.start()
        self.addCleanup(p.stop)

    def write(self, lines: list[str], end: str = "\n") -> None:
        self.f.write_text("\n".join(lines) + end)

    def fixture(self) -> None:
        rows = [json.dumps({"ts": f"2026-09-27T05:{i:02d}:00", "tool": "dog.look", "ok": i % 3 != 0, "i": i}) for i in range(40)]
        rows[5] = json.dumps({"tool": "chat.post", "args": {"text": "café ☕ who dis?!"}}, ensure_ascii=False)   # raw unicode
        rows[12] = rows[12] + "\r"                                                                            # a CRLF line
        rows[20:20] = ["", "   ", "\t"]                                                                      # blank and whitespace-only lines
        rows[30:30] = ["[1, 2]", '"a string"', "7", "null"]                                                  # JSON that is not a row
        self.write(rows + ["", json.dumps({"tool": "last"})], end="")                                       # no final newline

    def test_every_n_returns_what_the_old_read_returned(self):
        self.fixture()
        total = len(_old(self.f))
        self.assertEqual(total, 45)
        for n in (None, 0, 1, 2, 3, 10, 25, total - 1, total, total + 5, -1, -3, -(total + 2)):
            with self.subTest(n=n):
                self.assertEqual(ledger.rows(n), _old(self.f, n))

    def test_no_ledger_is_no_rows(self):
        for n in (None, 0, 5, -1):
            self.assertEqual(ledger.rows(n), _old(self.f, n))
            self.assertEqual(ledger.rows(n), [])

    def test_a_malformed_line_in_the_window_raises_as_before(self):
        self.write([json.dumps({"i": i}) for i in range(30)] + ['{"tool": "torn'])
        for n in (None, 0, 1, 25):
            with self.subTest(n=n):
                with self.assertRaises(json.JSONDecodeError) as old:
                    _old(self.f, n)
                with self.assertRaises(json.JSONDecodeError) as new:
                    ledger.rows(n)
                self.assertEqual(str(new.exception), str(old.exception))

    def test_rows_n_parses_only_the_rows_it_returns(self):
        self.write([json.dumps({"i": i}) for i in range(1000)])
        with mock.patch.object(ledger.json, "loads", wraps=json.loads) as loads:
            got = ledger.rows(25)
        self.assertEqual([r["i"] for r in got], list(range(975, 1000)))
        self.assertEqual(loads.call_count, 25, "every row of the file was parsed to return the last 25")

    def test_a_malformed_row_older_than_the_window_is_not_read(self):
        """The named difference: GET /ledger?n=25 shows the newest rows past an old torn one; rows() still raises."""
        self.write(['{"tool": "torn'] + [json.dumps({"i": i}) for i in range(30)])
        self.assertEqual([r["i"] for r in ledger.rows(25)], list(range(5, 30)))
        with self.assertRaises(json.JSONDecodeError):
            ledger.rows()


if __name__ == "__main__":
    unittest.main()
