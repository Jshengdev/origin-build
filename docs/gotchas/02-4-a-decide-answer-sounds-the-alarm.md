# 02-4 · an "idk" to the not-sure question sounded the intruder alarm

**Symptom.** Found in review by reading `verdict()`, reproduced by `wtdd.test_decide.ListenAsk` on commit 60dfe14, not seen on the dog. The round posts "not sure: out of place at 55 percent. what is it?" at a cup stop, a housemate answers "no idea", and the dog posts "STRANGER DANGER!!!" three times and calls `light_alarm` on every living-room light. It happens with `WTDD_ALARM=0` and at a stop whose map action has `ask: false`, which on main are the two switches that keep a round from ever opening a question.

**Root cause.** The decide question reuses the existing question flow: `pending.json` plus `Listener.verdict()` in `wtdd/chat/listen.py`. `verdict()` read every pending question as "who dis?!": any answer matching `IDK` (idk, dunno, no idea, dont know, no clue, not me, nope, who, never seen, stranger) set `stranger` and sounded the alarm, whatever `pending.json`'s `kind` said. Before 02 only `who_dis` questions existed, so the kind was never read.

**Fix (verbatim, `wtdd/chat/listen.py` `verdict()`).**
```python
        stranger = pend.get("kind") != "decide" and bool(IDK.search(normalize(m["text"])))
```
A decide answer is still one `intruder.verdict` row with `args.asked` = the question's trigger and `state_after.verdict` = "known", and the dog posts "ok, standing down". The who-dis path, its `ok:`/`danger:` keys and the PENDING unlink order are unchanged.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide.ListenAsk` passes: `test_idk_to_a_decide_question_never_sounds_the_alarm` (no `light_alarm`, one "ok, standing down", the row joined by `decide:g1:10`) and `test_idk_to_who_dis_still_sounds_the_alarm` (the control). On the dog: answer a decide question with "idk" and confirm no `lights.signal` rows follow the `intruder.verdict` row.
