# 10-3 · gotcha 10-1's Verify prints `stops [22, 23]` on its second line, not `stops [23]`

**Symptom.** Gotcha 10-1's Verify script, run verbatim from the worktree root, no longer prints its Symptom's second line:
```
2026-09-25 rows 17 stops [10, None] flags 0 closed_by shift 2026-09-26 signed None
2026-09-26 rows 18 stops [22, 23] flags 1 closed_by open signed None
```
10-1 says `stops [23]` and "prints the two lines under Symptom". Gotchas are never edited, so 10-1 stays as written.

**Root cause.** 307250e (after 10-1 was written at a9d4ebd): a say post with no dog.look of its own before it opens
its own FAILED stop. On the 2026-09-26 half, stop 22's say post has no look before it (the look is on the 09-25 half),
so it is now listed as stop 22 with the error "no dog.look row before this post" instead of being dropped. The split
10-1 describes is unchanged and is easier to see: the look sits on one page, its post as a FAILED stop on the other.

**Fix (verbatim).** None in code. Read 10-1's second Symptom line as `stops [22, 23]` for any record.py at or after 307250e.

**Verify.** Run 10-1's Verify script verbatim: it prints the two lines above. Against record.py as of d5dc931 (before
307250e) the same script prints `stops [23]`; against 307250e it prints `stops [22, 23]`. It reads the fixture and appends nothing.
