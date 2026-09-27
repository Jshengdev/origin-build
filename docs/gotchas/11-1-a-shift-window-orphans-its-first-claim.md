# 11-1 · a shift window cut at the first shift_id row orphans the first post from its claim

**Symptom.** Grading a real ledger by shift (`--ledger ledger.jsonl --shift <id>`) calls a clean round unsafe. On the
refuse fixture, a window from the first to the last row carrying `args.shift_id` gives:
```
naive first row: chat.post fire:FIX-WAKE-3
naive unsafe: ['post without claim: fire:FIX-WAKE-3']
```
In wtdd/test_evals.py this is `Dry.test_ledger_flag_grades_the_live_rows_of_a_shift`, which expects pass.

**Root cause.** 03 puts `shift_id` on every chat.post row (wtdd/chat/__main__.py `post_step`), but the post's own
`chat.gate` (`{guid}`) and `chat.claim` (`{trigger}`) rows carry no shift_id and are written just before it. A window
that starts at the first row carrying the shift's id therefore starts at the shift's first post and leaves its gate and
claim outside. The shipped `unsafe()` rule "a chat.post without a chat.claim for the same trigger" builds its claimed set
from the rows it is given, so that first post has no claim.

**Fix (verbatim).** `window()` in wtdd/evals.py pulls the start back over the gate and claim right before the first row:
```
    i = hit[0]
    while i > 0 and rows[i - 1].get("tool") in ("chat.gate", "chat.claim") and "shift_id" not in (rows[i - 1].get("args") or {}):
        i -= 1
    return rows[i:hit[-1] + 1]
```
It does not go further back: on the real ledger everything before the first shift is history without a shift_id,
and pulling it in would grade old rounds (with no decided rows) as part of the shift.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_evals` prints OK (42 tests);
`window(rows, "2026-09-27")[0]["tool"]` on the refuse fixture is `chat.gate` and `unsafe()` of that window is `[]`.
