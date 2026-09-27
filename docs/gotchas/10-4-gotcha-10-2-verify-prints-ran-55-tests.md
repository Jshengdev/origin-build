# 10-4 · gotcha 10-2's Verify prints `Ran 55 tests`, not `Ran 54 tests`

**Symptom.** Gotcha 10-2's Verify, run verbatim from the worktree root:
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_record wtdd.chat.test_oncall
Ran 55 tests in 0.090s
OK
$ git status --short wtdd/fixtures/ledger_shift.jsonl
```
10-2 says `Ran 54 tests`. Gotchas are never edited, so 10-2 stays as written.

**Root cause.** c7b8954 added one test to wtdd/test_record.py (ByHand: a look pressed by hand keeps its say-<epoch>
post), so test_record runs 19 tests, not 18. 10-2's check is unchanged: OK, and the fixture stays at 71 lines.

**Fix (verbatim).** None in code. Read 10-2's count as the number of tests in the two modules at the commit run: 55 at c7b8954 and after.

**Verify.** The command above prints `Ran 55 tests` and `OK`, git status prints nothing, `wc -l < wtdd/fixtures/ledger_shift.jsonl` prints 71.
