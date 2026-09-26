# 03-3 · two chat test modules in one process share one scratch ledger

**Symptom.** Each module passes alone, and in the order test_chat then test_oncall, but not the other way round:
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_oncall wtdd.chat.test_chat
FAIL: test_post_refuses_before_claiming_and_leaves_a_receipt (wtdd.chat.test_chat.Gate.test_post_refuses_before_claiming_and_leaves_a_receipt)
  File ".../wtdd/chat/test_chat.py", line 113, in test_post_refuses_before_claiming_and_leaves_a_receipt
AssertionError: True is not false
Ran 57 tests
FAILED (failures=1)
```
The failing line is `self.assertFalse(any(r["tool"] == "chat.post" for r in ledger.rows()))`.

**Root cause.** Both modules point the ledger and memory.db at their own temp dir by setting `WTDD_LEDGER` and
`WTDD_MEMORY` in `os.environ` at import, before importing `wtdd.ledger`. But `wtdd.ledger` reads the variable once, at
its first import (`LEDGER = Path(os.environ.get("WTDD_LEDGER", ROOT / "ledger.jsonl"))`, wtdd/ledger.py:29), and
`wtdd.chat.memory` does the same for `MEMORY`. In one process the second module's assignment comes too late: it
inherits the first module's scratch ledger. test_oncall writes confirmed chat.post rows (its gate and escalate checks),
and test_chat's receipt check asserts the ledger holds no chat.post row at all, so it goes red. In the other order
test_chat writes no chat.post row and test_oncall's checks filter by trigger or read only their own rows, so it passes.
Nothing is wrong with the item or with either test alone; the standing command and the goal command already run them
as separate processes.

**Fix (verbatim).** No code change. Run the chat test modules as separate processes, as the standing command and the
goal command do:
```
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_oncall
WTDD_WAKE_SHOW=0 /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_triggers wtdd.chat.test_chat wtdd.hue.test_stub
```
An item that wants them in one command (12 stacks on this branch and moves the seams test_chat patches) gives each
module its own process, or makes both read the ledger path at call time, and says so in its own PR.

**Verify.** The combined command above fails with the one line shown; each of the two commands in the fix prints OK.
