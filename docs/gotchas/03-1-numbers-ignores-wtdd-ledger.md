# 03-1 · numbers.py ignored WTDD_LEDGER

**Symptom.** `WTDD_LEDGER=<fixture> python -m wtdd.numbers` printed the counts of `<repo>/ledger.jsonl`, not of the
fixture: a shift that exists only in the fixture (or in a test's scratch ledger) never showed up, and in a fresh
worktree every ledger count was 0.

**Root cause.** `count()` built its own path, `ROOT / "ledger.jsonl"`, instead of using `ledger.LEDGER`, the one path
that honours `WTDD_LEDGER` (wtdd/ledger.py:29). Every other reader goes through `ledger.rows()`.

**Fix (verbatim, wtdd/numbers.py).**
```python
from .ledger import LEDGER, log, rows as ledger_rows
...
def count(pred) -> int:
    f = LEDGER   # honours WTDD_LEDGER (docs/gotchas/03-1)
    return sum(1 for l in f.read_text().splitlines() if l.strip() and pred(l)) if f.exists() else 0
```
and the per-shift lines read `ledger_rows()`. With WTDD_LEDGER unset nothing changes: the default is still
`<repo>/ledger.jsonl`.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_oncall.Numbers` (the
block test appends a shift to the scratch ledger WTDD_LEDGER names and finds its acked_ms and "unsigned" in the block).
