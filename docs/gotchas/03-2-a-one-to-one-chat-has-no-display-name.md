# 03-2 · a 1:1 chat has no display name for the gate to check

**Symptom.** The send gate checked `guid == WTDD_CHAT_GUID` and `chat.db display_name == TARGET_NAME`. A flag to one
named person in the 1:1 chat they already have could never pass it, and `python -m wtdd.chat chats` never lists that
chat, so there is no guid to copy into `.env` either.

**Root cause.** display_name is a group property. On this Mac (read-only chat.db query, 2026-09-26) every 1:1 chat has
the guid `any;-;<handle>` and exactly one chat_handle_join member, that same handle (253 of 253); 248 of the 253 have
display_name '' (empty, not NULL), and `CHATS_SQL` drops empty names. Loosening the name check would have opened the
gate to any chat.

**Fix (verbatim, wtdd/chat/send.py).** The gate is an allow-set of two exact targets; the on-call target is checked by
guid and by its one member, never by a name:
```python
    h = config.maybe("WTDD_ON_CALL_HANDLE")
    if h and guid == oncall.guid(h):
        members = db.chat_members(guid)
        if members != [h]:
            raise PermissionError(f"refused: {guid} members {members!r} are not exactly [{h!r}]")
        return config.get("WTDD_ON_CALL_NAME")
```
followed by the group's two checks, unchanged. `db.chat_members(guid)` is one read-only query on chat_handle_join. The
guid is formed from the handle (`oncall.guid`), not looked up in the chat list.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.chat.test_oncall.Gate` (passes only
with exactly [handle]; another member, no such chat, no person configured, another 1:1 and the castle are all refused,
the last two with an ok=false chat.gate row and no claim) and `wtdd.chat.test_chat.Gate` (the group, unchanged).
Still UNVERIFIED: that AppleScript `chat id "any;-;<handle>"` resolves the 1:1 chat; the first live send says.
