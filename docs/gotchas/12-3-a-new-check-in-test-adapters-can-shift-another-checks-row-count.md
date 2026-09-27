# 12-3 · a new check in test_adapters can shift another check's row count

**Symptom.** Review round 1 added a check that posts to `sms:<handle>` with only TWILIO_ACCOUNT_SID set and
expects one failed `chat.gate` row. Once `chat/__main__.gate()` wrote that row, a check that had nothing to do with
it went red:
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_adapters
FAIL: test_flag_posts_once_and_every_row_is_labeled_stub (wtdd.chat.test_adapters.NeverTwice.test_flag_posts_once_and_every_row_is_labeled_stub)
+ [(True, 'sms', True, 'stub'), (True, 'sms', True, 'stub')]
- [(False, 'sms', False, 'live'),
-  (True, 'sms', True, 'stub'),
-  (True, 'sms', True, 'stub')]
```

**Root cause.** The module has one scratch ledger for all its checks (WTDD_LEDGER is set once, at import, the
03-3 pattern), and NeverTwice counts every `chat.gate` row whose `args.guid` is the sms target, from the start of
the file. unittest runs classes in name order, so `Live` runs before `NeverTwice`, and the new check's failed gate
row for the same target was counted as a third gate row.

**Fix (verbatim).** The new check writes to its own ledger file for the duration of the post
(`ledger.append` and `ledger.rows` read the module global `LEDGER` at call time), which also lets it assert that
the failed gate row is the only row of that post:
```
        # its own scratch ledger: the module's is shared, and NeverTwice counts every sms chat.gate row in it
        with mock.patch.dict(os.environ, {"TWILIO_ACCOUNT_SID": self.SID}), mock.patch.object(ledger, "LEDGER", _TMP / "partial-keys.jsonl"), \
             mock.patch.object(requests, "post", side_effect=_no_http), mock.patch.object(requests, "get", side_effect=_no_http):
            ...
            rows = ledger.rows()
        # the failure is the gate's own row, and the only row: nothing claimed, nothing sent
        self.assertEqual([(r["tool"], r["ok"], r["app"], r["args"]) for r in rows], [("chat.gate", False, "sms", {"guid": SMS})])
```
Any later check in this module that posts to `sms:+15550002222` through `cli.post` does the same, or NeverTwice's
count moves again.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_adapters` prints
`Ran 38 tests ... OK`.
