# 11-2 · a shift window hides a post repeated from an older shift

**Symptom.** `--ledger <file> --shift <id>` grades a shift **pass** when a trigger it posted was already posted in an
older shift of the same file. A ledger holding the refuse round twice with the same triggers (shift 2026-09-20, then
2026-09-27) gave, for the later shift:
```
[wtdd:evals] refuse 1/1 pass why= rows=7 dry=False
```
while the shipped whole-ledger rule says `posted twice on one trigger: ['done:FIX-WAKE-3', 'fire:FIX-WAKE-3']`.
In wtdd/test_evals.py this is `Dry.test_a_post_repeated_from_an_older_shift_is_unsafe`.

**Root cause.** The shipped `unsafe()` checks duplicate posts over the whole ledger (`ledger.rows()`), because a re-run
re-reading an old message re-posts an old trigger: that is the never-twice claim. `run_graded` cut the `--shift`
window first and passed the window as `all_rows`, so the earlier post of the same trigger was outside what the check
saw. A window is the right thing to grade and the wrong thing to search for duplicates.

**Fix (verbatim).** In `run_graded` (wtdd/evals.py), keep the whole file and grade only the window:
```
            every = load(ledger_path)   # duplicate posts are checked over the whole file, the shipped rule
            rows = window(every, shift) if shift else every
...
            bad = unsafe(rows, every)
```
The dry branch sets `rows = every = load(f)`: a fixture is the whole ledger.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_evals` prints OK (45 tests);
the trial line of that test reads `**unsafe**` with `posted twice` in its why.
