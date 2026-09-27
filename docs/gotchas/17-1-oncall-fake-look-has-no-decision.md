# 17-1 · 03's look fake has no decision once 02 is beneath it

**Symptom.** On the merge of origin/feat/02-decide and origin/feat/03-named-person (a93e562, this branch's first
commit), before any item-17 code, 03's own check fails:
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_oncall
ERROR: test_look_and_say_flags_the_on_call_with_the_photo (wtdd.chat.test_oncall.Escalate.test_look_and_say_flags_the_on_call_with_the_photo)
  File ".../wtdd/chat/test_oncall.py", line 184, in test_look_and_say_flags_the_on_call_with_the_photo
    self.l.look_and_say({"guid": "g1", "sender": HANDLE, "text": "what the dog doin"})
  File ".../wtdd/chat/listen.py", line 161, in look_and_say
    dec = seen["decision"]   # look_and_see always returns one: {label, p, needs_person, model} or {error}
KeyError: 'decision'
Ran 36 tests
FAILED (errors=1)
```

**Root cause.** 03 wrote its fake `seen` (the patched return of `wtdd.tools.dog_say.look_and_see`) before 02 existed.
On 02, `look_and_see` always returns a `decision` key ({label, p, needs_person, model} or {error}; wtdd/tools/dog_say.py,
the `at_stop` call), and `listen.look_and_say` reads it with `seen["decision"]` on purpose: a stop without its decision
is a loud KeyError, never a skipped question. The two branches each passed alone; the merge is the first place 03's fake
meets 02's contract. The other two fakes of the same shape (no on-call person; a failed flag send) return before the
decision is read, so only one check went red. Separately, from item 17 on, `verdict()` reads the reply through
`decide.read_reply`, which calls Jev when `JEV_API_KEY` is set; `config._load()` refills an absent key from the
primary repo's `.env`, so 03's verdict checks would make live calls there.

**Fix (verbatim).** The test's fake, never `listen.py` (a `.get("decision")` there would hide a missing decision). In
wtdd/chat/test_oncall.py, in the env block:
```
os.environ["JEV_API_KEY"] = ""   # 17: verdict() reads the reply through decide.read_reply; a .env key must not make these live calls
```
after the `FIXTURE = ...` line:
```
# what dog_say.look_and_see returns beside the look since 02: every stop carries its decision (17 adds the action)
DECISION = {"label": "person", "p": 0.95, "needs_person": False, "model": "stub", "action": "escalate"}
```
and each of the three fakes `seen = {..., "detector": {"classes": ["person"]}}` gains `, "decision": DECISION`.

**Verify.**
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_oncall
Ran 36 tests
OK
```
