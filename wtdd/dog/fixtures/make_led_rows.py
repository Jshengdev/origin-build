"""TEST/DEMO ONLY. Writes the dry screenshot's receipts: two dog.led rows through the real Body.led against the recording
stub (vui_stub.py), labelled cached=True, source="stub" (NIGHT-1 contracts E) so no fixture row ever claims to be live:
cyan acked (code 0, brightness 7 read back) and cyan refused (code 7, a FAILED row). Nothing here reaches a dog.
Refuses to run unless WTDD_LEDGER names a scratch file (never <repo>/ledger.jsonl).

  WTDD_LEDGER=/tmp/night1/25/ledger.jsonl python -m wtdd.dog.fixtures.make_led_rows
"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

from wtdd.config import ROOT

_LEDGER = os.environ.get("WTDD_LEDGER")
if not _LEDGER or Path(_LEDGER).resolve() == (ROOT / "ledger.jsonl").resolve():
    sys.exit("make_led_rows: set WTDD_LEDGER to a scratch file, never <repo>/ledger.jsonl: these are stub receipts")

from wtdd.dog.body import Body  # noqa: E402  (after the check: the ledger reads WTDD_LEDGER at import)
from wtdd.dog.fixtures.vui_stub import StubConn  # noqa: E402


async def main() -> None:
    ok = Body()
    ok.conn = StubConn({1007: (0, None), 1006: (0, {"brightness": 7})})
    print("acked:", await ok.led("cyan", 5, cached=True, source="stub"))
    bad = Body()
    bad.conn = StubConn({1007: (7, None)})
    try:
        await bad.led("cyan", 5, cached=True, source="stub")
        sys.exit("make_led_rows: the planted code 7 was not refused")
    except RuntimeError:
        print("refused as planted:", bad.led_state)
    print("rows written to", _LEDGER)


if __name__ == "__main__":
    asyncio.run(main())
