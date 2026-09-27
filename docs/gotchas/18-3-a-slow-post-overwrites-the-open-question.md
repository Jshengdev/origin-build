# 18-3 · a slow post, then pending.json: the question that opened meanwhile is overwritten

**Symptom.** In a scratch repro, the dog's own who-dis opens while dispatch's "send the dog? yes / no" is being posted.
Afterwards the thread holds both questions, but `pending.json` says `kind: dispatch`. A reply meant for the who-dis,
such as "yeah that's my neighbour", matches dispatch's AFFIRM and walks the dog toward the person. An "idk" reads as
`declined`, so the alarm the dog's eye asked about never sounds.

**Root cause.** `pending.json` is one file that every question writes: intruder_alarm's who-dis, decide's "not
sure", and dispatch's ask. `run()` looked for an open question once, before planning. `_ask()` then posted through
`chat_post.run` (gate, claim, send, read-back: about 3.4 s on the fixture) and wrote `pending.json` without looking
again. Anything that writes the one shared question after a slow step has to look again right before it writes.

**Fix (verbatim, `wtdd/dispatch.py` `_ask`).**
```python
    hold("before the ask was posted")
    try:
        chat_post.run(text=ask_line(c), file=frame, trigger=trigger)
    except Exception as e:  # noqa: BLE001  (its chat.* rows have it; drawn and re-raised)
        _publish(page, phase="failed", error=f"the ask was not posted: {type(e).__name__}: {e}")
        raise
    hold("while the ask was posted")
    PENDING.write_text(json.dumps({"kind": "dispatch", "t": time.time(), "cam": c["id"], "trigger": trigger, "file": frame}))
```
`hold()` refuses through `run()`'s refusal when `_open_question()` finds a question. That writes a FAILED
`dispatch.decided` "question open" row, the failed page and a text-only "couldn't dispatch", and leaves the other
question's `pending.json` as it was written. Microseconds remain between the second look and the write. A who-dis
written after the dispatch pending overwrites it, and then the dog's own eye wins, which is the rule.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_dispatch_safety.AskRace -v`
passes. A who-dis opened during the decision, or during the ask's post, is still the `pending.json` afterwards, and
the page is `failed` with "question open".
