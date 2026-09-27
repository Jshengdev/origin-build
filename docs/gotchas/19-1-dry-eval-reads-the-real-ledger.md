# 19-1 · a dry eval graded with evals.unsafe() reads the real ledger

**Symptom.** Grading the scout's committed fixture ledger with the base's `evals.unsafe(rows)` returned a reason that is
in no fixture row. With WTDD_LEDGER pointing at a ledger holding two ok `chat.post` rows on one trigger:

```
evals.unsafe(fixture rows): ["posted twice on one trigger: ['wake:1']"]
unsafe_scout(fixture rows, map): []
run_scout(): pass
```

A dry trial built on `unsafe()` would be graded `unsafe` (or pass) by whatever Johnny's `ledger.jsonl` holds that day,
not by the fixture it names.

**Root cause.** `evals.unsafe(rows)` checks the rows it is given, then scans `ledger.rows()` (the whole file at
WTDD_LEDGER, default `<repo>/ledger.jsonl`) for duplicate chat posts. That is right for a live trial, whose rows are a
slice of that file; a fixture ledger is not in that file at all.

**Fix (verbatim, wtdd/evals.py, run_scout).**

```
        bad = unsafe_scout(rows, m)   # never evals.unsafe(): it reads the real ledger for duplicate posts
```

The scout's unsafe rule is its own function over (rows, map) only. When 11's `run_graded` (which grades a real ledger
for a shift) takes the scout in, it may call `unsafe(rows, every)` there, where the whole ledger is the point.

**Verify.** `/tmp/night1/19/probe_unsafe.py` (the three lines above: the base's `unsafe()` names a post the fixture
never made; `unsafe_scout` and `run_scout` do not read it), and
`python -m unittest wtdd.dog.test_scout_zones.Eval`: Ran 10 tests, OK, with `test_the_cli_grades_scout_dry` run under a
scratch WTDD_LEDGER.
