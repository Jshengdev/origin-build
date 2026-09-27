# 12-1 · a post refused at the claim still leaves an ok chat.gate row

**Symptom.** With the adapters built, the RED spec had one failure left, in the never-twice check itself:
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_adapters
FAIL: test_flag_posts_once_and_every_row_is_labeled_stub (wtdd.chat.test_adapters.NeverTwice.test_flag_posts_once_and_every_row_is_labeled_stub)
  File ".../wtdd/chat/test_adapters.py", line 284, in test_flag_posts_once_and_every_row_is_labeled_stub
    self.assertEqual([(r["ok"], r["app"], r["cached"], r["source"]) for r in gate], [(True, "sms", True, "stub")])
AssertionError: Lists differ: [(True, 'sms', True, 'stub'), (True, 'sms', True, 'stub')] != [(True, 'sms', True, 'stub')]
Ran 36 tests
FAILED (failures=1)
```

**Root cause.** The expectation, not the code. `chat/__main__.post` is gate, then claim, then send (item 03's order,
pinned by `Gate.test_wrong_sms_number_is_refused_before_claim_with_a_receipt`: a wrong target is refused before
anything is claimed). So each `post()` call writes one `chat.gate` row. The test posts the same trigger twice: the
second call passes the gate (one more ok `chat.gate` row) and is refused at the claim. The same test's next assertion
expects exactly that, two `chat.claim` rows `[(True, ...), (False, ...)]`, which the second call can only reach through
a second passed gate. One gate row for two calls cannot hold without moving the claim ahead of the gate, which would
claim a trigger for a target the gate then refuses. Anyone counting rows (item 11's grader) should count posts by
`chat.post` rows or by ok `chat.claim` rows, never by `chat.gate` rows.

**Fix (verbatim).** wtdd/chat/test_adapters.py, the one assertion:
```
-        self.assertEqual([(r["ok"], r["app"], r["cached"], r["source"]) for r in gate], [(True, "sms", True, "stub")])
+        # one gate row per post(): the second post passes the gate and is refused at the claim (the two claim rows below)
+        self.assertEqual([(r["ok"], r["app"], r["cached"], r["source"]) for r in gate], [(True, "sms", True, "stub")] * 2)
```
Every gate row is still checked for ok, app "sms" and the stub label; dropping the label from `chat/__main__.gate`
makes this line fail.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_adapters` prints
`Ran 36 tests ... OK`.
