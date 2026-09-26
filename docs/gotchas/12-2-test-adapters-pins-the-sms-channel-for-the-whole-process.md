# 12-2 · test_adapters pins the SMS channel for the whole process

**Symptom.** Each module passes in its own process; in one process together, item 03's checks go red:
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_oncall wtdd.chat.test_adapters
ERROR: test_escalation_is_claimed_once (wtdd.chat.test_oncall.Escalate.test_escalation_is_claimed_once)
ERROR: test_on_call_target_passes_when_that_chat_is_the_one_handle (wtdd.chat.test_oncall.Gate.test_on_call_target_passes_when_that_chat_is_the_one_handle)
FAIL: test_person_is_name_handle_and_the_one_to_one_guid (wtdd.chat.test_oncall.Person.test_person_is_name_handle_and_the_one_to_one_guid)
  [... 8 more test_oncall failures, and test_adapters' own NeverTwice check ...]
Ran 72 tests
FAILED (failures=10, errors=2)
```

**Root cause.** test_adapters sets `WTDD_ON_CALL_CHANNEL=sms` (and the Twilio keys empty) in `os.environ` at import,
the same way test_oncall and test_chat set their scratch ledger (gotcha 03-3). unittest imports every named module
before it runs any test, and `oncall.guid()` reads the channel at call time, so every test_oncall check then sees the
on-call target as `sms:+15550002222` instead of the 1:1 `any;-;+15550002222`. test_oncall does not pin the channel
because on its branch the key did not exist. The two modules also share one scratch ledger in one process (03-3):
test_oncall's escalations, now sent to sms:, leave two extra ok sms chat.gate rows there, so test_adapters'
`[(True, "sms", True, "stub")] * 2` count at line 285 sees four. Nothing is wrong with either module alone.

**Fix (verbatim).** No code change. Run the chat test modules as separate processes, as the goal command and the
standing command do:
```
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_adapters
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_oncall
WTDD_WAKE_SHOW=0 /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_triggers wtdd.chat.test_chat wtdd.hue.test_stub
```

**Verify.** The combined command above fails as shown; each of the three commands in the fix prints OK.
