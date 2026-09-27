# 10-2 · a tracked fixture set as WTDD_LEDGER is written by the next test module in the process

**Symptom.** Each module passes alone. Run together at 598a7cf, the tracked fixture changes:
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_record wtdd.chat.test_oncall
FAIL: test_default_shift_is_wtdd_shift (wtdd.test_record.Cli.test_default_shift_is_wtdd_shift)
AssertionError: 1 != 0
Ran 52 tests in 0.085s
FAILED (failures=1)
$ git status --short
 M wtdd/fixtures/ledger_shift.jsonl
$ wc -l wtdd/fixtures/ledger_shift.jsonl
     103 wtdd/fixtures/ledger_shift.jsonl
```
The committed file has 71 rows. test_record's Guard hashes the file only around its own tests, so nothing caught it.

**Root cause.** `wtdd.ledger` reads the variable once, at its first import
(`LEDGER = Path(os.environ.get("WTDD_LEDGER", ROOT / "ledger.jsonl"))`, wtdd/ledger.py:29). test_record set
`WTDD_LEDGER` to the tracked `wtdd/fixtures/ledger_shift.jsonl` and imported `wtdd.ledger` first; test_oncall's own
`os.environ["WTDD_LEDGER"] = ...` came too late, so its record_sign and escalate rows were appended to the tracked
fixture. The failing test is the same mechanism on another key: both modules set `WTDD_SHIFT` at import, the last
import wins, and `oncall.shift_id()` reads it at call time, so the CLI default asked for 2026-09-27 (exit 1). It is
gotcha 03-3's mechanism with a worse outcome: there two scratch ledgers were shared; here a committed file is written.

**Fix (verbatim, wtdd/test_record.py).** The process's ledger is a scratch copy; the tracked file is only read:
```
FIXTURE = HERE / "fixtures" / "ledger_shift.jsonl"      # tracked: copied and hashed, never the ledger
_TMP = Path(tempfile.mkdtemp(prefix="wtdd-record-test-"))
LEDGER = _TMP / "ledger_shift.jsonl"                     # the process's ledger: a scratch copy of the fixture
shutil.copyfile(FIXTURE, LEDGER)
os.environ["WTDD_LEDGER"] = str(LEDGER)
```
The Fixture test asserts `ledger.LEDGER == LEDGER` (loud when another module imported `wtdd.ledger` first) and
`_sha(LEDGER) == _sha(FIXTURE)`; Guard and the subprocess test use `LEDGER`. `WTDD_SHIFT` is no longer set at import;
the CLI default test sets it with `mock.patch.dict(os.environ, {"WTDD_SHIFT": A})`. Any test that reads a tracked
fixture as its ledger (item 11's too) copies it first.

**Verify.**
```
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_record wtdd.chat.test_oncall
git status --short wtdd/fixtures/ledger_shift.jsonl
```
prints `Ran 54 tests` and `OK`, then nothing from git status (the fixture stays at 71 lines). In the reverse order
test_oncall passes, test_record fails, and its Fixture test names the cause ("another test module imported
wtdd.ledger first in this process: run this one alone"); the fixture is untouched either way. Run it alone, as the
goal command does.
