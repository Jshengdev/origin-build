"""Before origin-build goes public (Johnny, 2026-09-27): no real phone number is committed anywhere in the repo.
Every tracked text file is scanned for a North American number in the form +1NXXNXXXXXX. Fictional ones pass: area or
exchange 555, or an area code starting 0 or 1 (not a real area code), which is how every stand-in here is written.
The recorded take in docs/evidence once carried a housemate's real handle (chat.wake armed_by); it now carries a 555
stand-in. Run: python -m unittest wtdd.test_no_private_numbers -v"""
from __future__ import annotations
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHONE = re.compile(r"\+1(\d{3})(\d{3})(\d{4})(?!\d)")


def real(area: str, exchange: str) -> bool:
    return area[0] not in "01" and "555" not in (area, exchange)


class NoRealNumbers(unittest.TestCase):
    def test_no_tracked_file_holds_a_real_phone_number(self):
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        hits = []
        for f in files:
            try:
                text = (ROOT / f).read_text()
            except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                for m in PHONE.finditer(line):
                    if real(m.group(1), m.group(2)):
                        hits.append(f"{f}:{i}: +1{m.group(1)}***{m.group(3)[-2:]}")   # masked: the test never prints a number
        self.assertEqual(hits, [], "a real-looking phone number is committed:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
