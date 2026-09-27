# 00-6 · a message from the dog's own account has no sender, so it has no name to resume with

**Symptom.** This was seen in a dry run only: the OwnAccount test, where a Listener gets a stubbed API. No real chat was
involved. With WTDD_ALLOW_SELF=1 (the .env.example default, because Johnny's phone is signed in to the dog's account),
"resume" typed from that phone goes out as POST /dog/resume with {"by": "", "via": "imessage"}. The API refuses it
correctly, since a blank name is not a person. The chat then answers "couldn't resume: ValueError: a halt resumes
only with a person's name", which points the wrong way, because a person did type it.

**Root cause.** chat.db has no handle row for a message the account sent itself. wtdd/chat/db.py selects
`COALESCE(h.id, '') AS sender`, so every is_from_me message has sender ''. allowed() accepts it under
WTDD_ALLOW_SELF, and resume_word() passes m["sender"] as `by`. Any code that uses the sender as a person's name meets
this: it is '' exactly for the one phone that shares the dog's account.

**Fix (verbatim, wtdd/chat/listen.py resume_word).** The refusal and its stop.resumed row stay. What is said changes:

```
        if not out.get("ok"):
            why = str(out.get("error"))[:160]
            if not str(m.get("sender") or "").strip():   # is_from_me: chat/db.py gives sender ''; "no name" is not the cause
                why = ("this message has no sender handle in chat.db (the dog's own account); resume from the page with your "
                       "name, or type it from another phone")
            log("chat", f"WARN resume word refused: {why}", by=hname(m["sender"]), err=str(out.get("error"))[:120])
            self.say(f"halt-fail:{m['guid']}", f"couldn't resume: {why}")
            return True
```

The drill's phone resume (Needs the dog 00.4) must come from the stand-in's own handle, not from the dog's account.

**Verify.** Run `python -m unittest wtdd.dog.test_halt.OwnAccount`. The POST still carries {"by": "", "via": "imessage"}.
The one line said in the chat starts "couldn't resume" and names "no sender handle", not "person's name". A WARN line on
stderr names the same cause.
