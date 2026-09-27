# 17-5 · a reply filed under whichever question was open, not the one it answers

**Symptom.** On 45b4910 (item 17 after its second review), with no JEV_API_KEY: "on it" holds the opening at stop 10
and the round walks on. Two things then go wrong.

**Case 1.** Stop 23 asks the group "not sure: other at 50 percent. what is it?". The on-call person then texts
"handled, cover is back on" in their 1:1. That text is read as the answer to the group's question:
- reply.decided has args.question = the group's line, which that person never saw;
- intruder.verdict has asked = decide:W:23, handled / close;
- "ok, closed" goes to the 1:1;
- the opening's own flag never gets a close row.

**Case 2.** Stop 22 flags "who dis?!" in the same 1:1, confirmed posted at 12:19:30. A "handled" typed at 12:19:05,
while the dog walked, closes the who-dis as handled / close. The person in frame is never asked about, and
light_alarm is never called.

```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide wtdd.chat.test_reply
ERROR: test_the_on_call_persons_reply_never_answers_the_groups_question (wtdd.test_decide.ListenEscalate...)
KeyError: 'chat'
FAIL: test_a_question_that_does_not_name_itself_fails_loud (wtdd.test_decide.ListenEscalate...)
AssertionError: KeyError not raised
FAIL: test_the_tool_paths_question_is_the_groups_and_its_receipt_names_the_line_posted (wtdd.test_decide.ListenEscalate...)
AssertionError: True is not false
FAIL: test_a_reply_older_than_the_open_question_is_not_its_answer (wtdd.chat.test_reply.Verdict...)
AssertionError: True is not false
Ran 93 tests
FAILED (failures=3, errors=1)
```

**Root cause.** pending.json holds one question, and verdict() reads any reply as the answer to whatever is in it.
Before 17 a question lasted one stop, so that was safe. 17's hold ("on it" keeps a flag open while the round walks
on) invites a later "handled" that can arrive after the next stop's question has replaced the flag. The guards that
should have caught it had gaps:

1. The ask branch of look_and_say wrote its pending with no "chat". verdict()'s check `if pend.get("chat") and chat !=
   pend["chat"]` therefore let any chat answer it. dog_say.run's tool-path pending (kind decide) names no chat either.
2. oncall.reply_fields() already found the second case: acked_error "ValueError: clock fault: reply ... before its
   post ...". verdict() recorded the error and read the reply anyway.
3. A pending with no question fell back to "what is it?". That is a line the dog never posted, and it became the
   receipt's args.question and the state Jev reads. dog_say's pending actually posted ask_line(decision).

**Fix (verbatim).** wtdd/chat/listen.py, look_and_say's ask branch:
```
            self._open({"kind": "decide", "t": time.time(), "file": seen.get("file"), "seconds": 5,
                        "trigger": f"decide:{k}", "chat": self.guid, "classes": (seen.get("detector") or {}).get("classes"),
                        "decision": dec, "question": line})
```
verdict():
```
        chat = m.get("chat") or self.guid
        kind = pend.get("kind")
        asked_in = pend.get("chat") or (self.guid if kind == "decide" else None)   # dog_say's decide names none: it posted to the group
        if asked_in and chat != asked_in:   # only the chat that was asked answers (the on-call person, not the group, and back)
            return False
        if kind == "halt":   # item 00's local stop: resumed by its own word or button, never by a model reading
            return False
        from .. import tools
        from ..decide import ask_line, read_reply
        if kind == "who_dis" and "question" not in pend:
            asked = "who dis?!"   # intruder_alarm's pending names none; this is what it posted (intruder_alarm.ASK)
        elif kind == "decide" and "question" not in pend:
            asked = ask_line(pend["decision"])   # dog_say.run's pending names none; this is the line it posted (dog_say.py:214)
        else:
            asked = pend["question"]   # listen names it on every kind it opens; none here is a KeyError, never a guessed question
        now = oncall.reply_fields(oncall.post_for(pend.get("trigger"), ledger_rows()), m.get("ts_utc"))
        if (now.get("acked_error") or "").startswith("ValueError: clock fault"):   # typed before this question's confirmed post:
            log("chat", "WARN a reply older than the open question is not its answer", trigger=pend.get("trigger"),
                reply=m["guid"], why=now["acked_error"][:120])   # it answers an earlier flag; this one stays open
            return False
```
The chat check stays tied to kind decide because 03's own check (test_oncall.test_verdict_row_carries_acked_ms_and_shift)
answers a who_dis pending with no chat from the on-call 1:1.

The fix also changed two test fakes, which had no question on kinds whose real writers always post one:
- test_reply.Verdict._ask(heads_up) now carries HEADS;
- test_decide.ListenAsk._answer(decide) now carries ask_line(...).
Their assertions are unchanged.

Only a confirmed post can prove a reply is older than its question. A dry run or a failed post (LookupError) reads
as before.

UNVERIFIED until the first live run: that a real reply's chat.db time is never before the post it answers. If the
phone's clock runs behind the Mac's, a quick real reply would be dropped by this guard. It is visible in the WARN line
above, never silent.

**Verify.**
```
$ /Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_decide wtdd.chat.test_reply
Ran 93 tests
OK
```
