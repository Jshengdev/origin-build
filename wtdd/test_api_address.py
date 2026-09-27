"""b1 · one API address. Run: python -m unittest wtdd.test_api_address -v
Every process that talks to the local API (commands._via_api for the CLI's dog tools, the field's dog source, the evals'
follow scenario, the watch, the chat listener's round, plan_path) and `python -m wtdd.api` itself take the address from
config.API: http://127.0.0.1:<WTDD_API_PORT, default 7788>. So no module but config.py spells the address or the default
port, and one exported WTDD_API_PORT moves them all together. Fixtures (recorded rows) and tests are data, not callers,
and are skipped. The port is read in a child process, so this process's env and imports are untouched."""
from __future__ import annotations
import os
import re
import subprocess
import sys
import unittest

from wtdd import config

ROOT = config.ROOT
LITERAL = re.compile(r"127\.0\.0\.1:7788|[\"']7788[\"']")


class Address(unittest.TestCase):
    def test_no_module_but_config_spells_the_address(self):
        hits = [f"{p.relative_to(ROOT)}:{i}: {line.strip()[:90]}" for p in sorted((ROOT / "wtdd").rglob("*.py"))
                if p.name != "config.py" and not p.name.startswith("test_") and "fixtures" not in p.parts
                for i, line in enumerate(p.read_text().splitlines(), 1) if LITERAL.search(line)]
        self.assertEqual(hits, [], "\n" + "\n".join(hits))

    def test_the_address_follows_wtdd_api_port(self):
        env = {k: v for k, v in os.environ.items() if k != "WTDD_API_PORT"}
        for extra, want in (({}, "http://127.0.0.1:7788"), ({"WTDD_API_PORT": "7985"}, "http://127.0.0.1:7985")):
            r = subprocess.run([sys.executable, "-c", "from wtdd import config; print(config.API)"], cwd=ROOT,
                               env={**env, **extra}, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.stdout.strip(), want, r.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
