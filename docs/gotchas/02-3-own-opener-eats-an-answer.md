# 02-3 · an opener that is also a natural reply eats the reply

**Symptom.** The decide question "not sure: person at 60 percent. what is it?" is posted and the round holds, but an answer typed from Johnny's phone, "not sure, looks like a cup", is never read: no `intruder.verdict` row, no log line, and the round waits the full `VERDICT_WAIT_S` (45 s) and moves on as if nobody answered.

**Root cause.** Johnny's phone shares the dog's iMessage account, so with `WTDD_ALLOW_SELF=1` (on in `.env.example`) `Listener.allowed()` in `wtdd/chat/listen.py` tells the dog's own posts from Johnny's by two things: the confirmed guids in `memory.posted_guids()` and the text prefixes in `OWN_OPENERS`. `allowed()` lowercases the text and refuses it when it `startswith(OWN_OPENERS)`. The first cut added the opener `"not sure"`, which is also how a person starts an answer to "what is it?". `await_verdict()` skips a refused message silently, so the answer was lost. "who dis" never had this problem because no answer starts with it.

**Fix (verbatim, `wtdd/chat/listen.py` `OWN_OPENERS`).**
```python
               "living room lights", "did:", "listening for", "not sure:")   # how the dog's own text posts begin
```
The opener is the exact prefix `decide.ask_line()` posts, colon included. An opener must be a prefix no housemate would type in reply to the post it marks.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide.ListenAsk` passes: `test_a_housemates_not_sure_is_an_answer` checks that under `WTDD_ALLOW_SELF=1` the dog's `ask_line()` is refused and "not sure, a cup" and "Not sure tbh" are allowed. On the dog: answer a decide question from Johnny's phone with "not sure, ..." and confirm an `intruder.verdict` row whose `args.asked` is `decide:<guid>:<stop>`.
