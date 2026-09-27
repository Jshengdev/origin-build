# 17-4 · the stub read the answer to the dog's own yes-or-no re-ask backwards

**Symptom.** On e379239 (item 17 after its first review), with no JEV_API_KEY, a who_dis flag answered "wait what" gets
"do you know them? yes or no". Then a bare "no" (they do not know them) stood the flag down, and "yes" (they do) read
as unclear:
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide wtdd.chat.test_reply
FAIL: test_no_to_the_reask_is_a_stranger_and_the_alarm (wtdd.chat.test_reply.Verdict.test_no_to_the_reask_is_a_stranger_and_the_alarm)
AssertionError: Expected 'call' to be called once. Called 0 times.
FAIL: test_yes_to_the_reask_stands_down (wtdd.chat.test_reply.Verdict.test_yes_to_the_reask_stands_down)
AssertionError: Lists differ: [('unclear', 'stand_down')] != [('known', 'stand_down')]
Ran 89 tests
FAILED (failures=2)
```
`read_reply(REASK, "no")` returned `{meaning: standing_down, p: 0.85, action: stand_down}`, and verdict() posted "ok,
standing down" on a stranger.

**Root cause.** `decide._reply_stub(text)` read only the reply, never the question. It reuses 02's CORRECTION regex,
`^(its|...|no|nope|...)\b`, which reads a leading "no" as "no, that's X" (a correction, so standing_down). That is
right after "who dis?!" and backwards after "do you know them? yes or no". Round 1's check
(test_the_answer_to_the_reask_is_read_against_the_reask) asserted only the row's args.question, not the reading, so it
could not catch this. The live path never calls the stub: it sends Jev "the dog asked: ... they replied: ...". How
Jev reads a bare "no" there is UNVERIFIED until the first live run.

**Fix (verbatim).** wtdd/decide.py:
```
REASK_NO = re.compile(r"^(no|nope|nah)\b")      # the answer to listen.REASK, "do you know them? yes or no", only
REASK_YES = re.compile(r"^(yes|yeah|yep|yup)\b")
...
def _reply_stub(asked: str, text: str) -> tuple[str, float, str, float, str]:
    ...
    from .chat.listen import CORRECTION, IDK, REASK   # here, not at the top: listen imports this module inside its functions
    from .chat.triggers import normalize
    t = normalize(text)
    if asked == REASK and REASK_NO.match(t):
        meaning, p, rule = "stranger", 0.9, "REASK no"
    elif asked == REASK and REASK_YES.match(t):
        meaning, p, rule = "standing_down", 0.85, "REASK yes"
    elif IDK.search(t):
```
and read_reply calls `_reply_stub(asked, text)`. wtdd/fixtures/make_ledger_17.py passes its question too
(`decide._reply_stub(heads, text)`); the committed fixtures regenerate byte for byte. After any other question the
stub reads as before ("no" to "who dis?!" is still a correction).

**Verify.**
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide wtdd.chat.test_reply
Ran 89 tests
OK
```
