"""python -m wtdd.chat <cmd>: the iMessage side of the dog, on this Mac's own Messages account.

  chats                                   named chats: guid, members, last message time (read-only)
  watch [--guid G] [--once] [--since N]   poll one chat by ROWID, print new rows, store into memory.db (read-only)
  listen [--dry-run] [--once]             wake phrase arms the dog, commands run, results posted (listen.py)
  simulate "text" ...                     feed texts through the listener: dry-run posts, REAL commands
  triggers ["phrase" ...]                 print the wake phrases and commands, test phrases against them
  send --text T [--trigger K]             one gated text post (kind send)
  update --text T                         same as send, one line only (kind update)
  photo --file P [--text T]               one gated file post with an optional caption (kind photo)
  spam --text T --n 5 --every 2           bounded burst: n capped at SPAM_CAP, each message its own claim K#i, suffixed (i/n)
  reply [--n 20]                          one model turn: newest wake message from a known housemate, context, reply, post
  context [--n 20]                        print the composed context (memory.py)

Every post, from any entry point (this CLI, the chat_post tool, the HTTP API, the MCP server, the agent loop, the
listener), goes through post(): gate (chat.gate row), claim (chat.claim row), then the send inside one chat.post row
whose state_after is the confirmed from-me row {guid, rowid, ts}, then memory.confirm (a photo's caption is a second
bubble, confirmed under <trigger>#caption so posted_guids() knows it too). A refused gate or claim is a
ledger row with ok=False and a PermissionError (exit 2 here). --guid defaults to WTDD_CHAT_GUID; --trigger is the
idempotence key (default cli:<epoch>). Only this CLI prints the confirmed row to stdout: library callers keep stdout
clean because the MCP server speaks its protocol there and `python -m wtdd chat_post` prints the result itself.

Never: a send to any chat but the gated one; a retry of an unconfirmed send; a replay of history at boot; a git commit
from here. Still Johnny's: fill HOUSEMATES in housemates.py (until then anyone in the group can wake the dog)."""
from __future__ import annotations
import argparse
import json
import sys
import time
from typing import Any

from .. import config, ledger
from ..ledger import log
from . import db, memory, send
from .housemates import HOUSEMATES
from .triggers import is_wake

SPAM_CAP = 10
SYSTEM = (
    "You are the voice of the house robot dog in a housemates group chat. "
    "Reply to the ask in one line under 140 characters. Casual, lowercase is fine. "
    "No adjectives. Never name any person. No emojis, no quotes, no preamble. "
    "Use the context for what the dog did, saw, and reported. If the context does not say, say you do not know yet."
)


def _guid(a: argparse.Namespace) -> str:
    return a.guid or config.get("WTDD_CHAT_GUID")


def _trigger(a: argparse.Namespace) -> str:
    return a.trigger or f"cli:{int(time.time())}"


def gate(guid: str) -> None:
    """The target gate as its own receipt: a refused target is a ledger row with ok=False, then PermissionError."""
    with ledger.step("central", "chat.gate", "imessage", {"guid": guid}) as r:
        send.gate(guid)
        r["state_after"] = {"guid": guid, "name": send.TARGET_NAME}


def claim(trigger: str) -> None:
    """The never-twice gate as its own receipt: a refused claim is a ledger row with ok=False, then PermissionError."""
    with ledger.step("central", "chat.claim", "memory", {"trigger": trigger}) as r:
        if not memory.claim(trigger):
            raise PermissionError(f"gate refused: trigger {trigger!r} already claimed")
        r["state_after"] = {"trigger": trigger, "claimed": True}


def post_step(guid: str, trigger: str, kind: str, text: str | None, file: str | None) -> dict[str, Any]:
    """The send inside one chat.post ledger row (after gate and claim); state_after is the confirmed row {guid, rowid, ts}."""
    args = {"guid": guid, "kind": kind, "trigger": trigger, "text": text, "file": file}
    with ledger.step("central", "chat.post", "imessage", args, {"max_rowid": db.max_rowid()}) as r:
        row = send.send_file(guid, file, text) if file else send.send_text(guid, text or "")
        r["state_after"] = row
    memory.confirm(trigger, row["guid"])
    if file and text:   # the caption is a second from-me bubble: claimed and confirmed under <trigger>#caption so the
        memory.claim(f"{trigger}#caption")   # listener (WTDD_ALLOW_SELF) can never read the dog's own sentence as a command
        memory.confirm(f"{trigger}#caption", row["caption"]["guid"])
    return row


def post(guid: str, trigger: str, kind: str, text: str | None = None, file: str | None = None) -> dict[str, Any]:
    """Gate, claim, send, confirm: the one way anything posts. Returns the confirmed from-me row {guid, rowid, ts}."""
    gate(guid)
    claim(trigger)
    return post_step(guid, trigger, kind, text, file)


def post_print(guid: str, trigger: str, kind: str, text: str | None = None, file: str | None = None) -> dict[str, Any]:
    """post() for the CLI: the confirmed row also goes to stdout."""
    row = post(guid, trigger, kind, text, file)
    print(json.dumps(row), flush=True)
    return row


def spam_plan(trigger: str, text: str, n: int) -> list[tuple[str, str]]:
    """Bounded burst: n capped at SPAM_CAP, each message its own claim `<trigger>#i`, each suffixed ` (i/n)`."""
    if n > SPAM_CAP:
        log("chat", f"WARN spam n={n} capped to {SPAM_CAP}")
    n = max(1, min(n, SPAM_CAP))
    return [(f"{trigger}#{i}", f"{text} ({i}/{n})") for i in range(1, n + 1)]


def compose(ctx: str, ask: str) -> list[dict[str, str]]:
    """The messages list for wtdd.llm.generate: system, the composed context, the trigger."""
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"{ctx}\n\n## the ask\n{ask}\n\nReply to the ask."},
    ]


def generate(ctx: str, ask: str) -> str:
    """One model turn via wtdd.llm (OpenRouter, model from OPENROUTER_MODEL). It writes its own llm.generate ledger row."""
    from ..llm import generate as llm_generate   # only reply needs it
    out = llm_generate("central", compose(ctx, ask), max_tokens=120)
    text = out["text"].strip()
    if not text:
        raise RuntimeError(f"model returned no text (model={out['model']}, finish={out.get('finish_reason')})")
    if len(text) > 140:
        log("chat", f"WARN reply {len(text)} chars, cut to 140")
        text = text[:140].rsplit(" ", 1)[0]
    return text


def cmd_chats(a: argparse.Namespace) -> None:
    t0 = time.perf_counter()
    rows = db.chats()
    for c in rows:
        print(f"{c['guid']:<45} members={c['members']:<3} last={c['last_ts'] or '-':<19} {c['name']}")
    log("chat", f"chats n={len(rows)}", ms=round((time.perf_counter() - t0) * 1000))


def cmd_watch(a: argparse.Namespace) -> None:
    guid = _guid(a)
    show_text = guid == config.maybe("WTDD_CHAT_GUID")   # full text only for the target group; other chats: handle + length
    last = a.since if a.since is not None else db.max_rowid()   # no replay at boot
    log("chat", f"watch guid={guid}", from_rowid=last, every=a.every, once=a.once, text="shown" if show_text else "hidden")
    while True:
        t0 = time.perf_counter()
        msgs = db.new_messages(guid, last)
        if msgs:
            n = memory.store(guid, msgs)
            last = msgs[-1]["rowid"]
            for m in msgs:
                who = "me" if m["is_from_me"] else m["sender"]
                if m["text"] is None:
                    body = "[non-text]"
                else:
                    body = m["text"] if show_text else f"len={len(m['text'])}"
                att = f" attachments={len(m['attachments'])}" if m["attachments"] else ""
                trig = " TRIGGER" if (not m["is_from_me"] and m["sender"] in HOUSEMATES and is_wake(m["text"])) else ""
                print(f"{m['rowid']} {m['ts_utc']} {who}: {body}{att}{trig}", flush=True)
            log("chat", f"watch stored n={n} of {len(msgs)}", last_rowid=last, ms=round((time.perf_counter() - t0) * 1000))
        elif a.once:
            log("chat", "WARN watch saw 0 new rows", guid=guid, after=last)
        if a.once:
            break
        time.sleep(a.every)


def cmd_post(a: argparse.Namespace) -> None:
    """send, update, photo: one gated post whose kind is the subcommand name."""
    if a.cmd == "update" and "\n" in a.text:
        raise SystemExit("[wtdd:chat] update must be one line")
    post_print(_guid(a), _trigger(a), a.cmd, text=a.text, file=a.file)


def cmd_spam(a: argparse.Namespace) -> None:
    guid = _guid(a)
    plan = spam_plan(_trigger(a), a.text, a.n)
    for i, (trigger, text) in enumerate(plan, 1):
        post_print(guid, trigger, "spam", text=text)
        if i < len(plan):
            time.sleep(a.every)
    log("chat", f"spam done n={len(plan)}", every=a.every)


def cmd_context(a: argparse.Namespace) -> None:
    print(memory.context(_guid(a), a.n))


def cmd_reply(a: argparse.Namespace) -> None:
    """Gate, claim the trigger message, then the model turn, then the send: a second reply to the same message is refused."""
    guid = _guid(a)
    gate(guid)
    trig = memory.last_trigger(guid, HOUSEMATES)
    if trig is None:
        log("chat", "WARN no trigger", guid=guid, known=len(HOUSEMATES))
        raise SystemExit("[wtdd:chat] no wake-phrase message from a known housemate stored for this chat (run watch; fill HOUSEMATES)")
    claim(trig["guid"])
    text = generate(memory.context(guid, a.n), trig["text"])
    print(json.dumps(post_step(guid, trig["guid"], "reply", text, None)), flush=True)


def cmd_listen(a: argparse.Namespace) -> None:
    from .listen import Listener
    guid = _guid(a)
    if not a.dry_run:
        gate(guid)   # fail at boot, not minutes later on the first post
    Listener(guid, post_print, listen_s=a.listen_s, dry_run=a.dry_run).run(every=a.every, once=a.once)


def cmd_triggers(a: argparse.Namespace) -> None:
    from .triggers import commands, match_command, wake_phrases
    print("wake phrases:", " | ".join(wake_phrases()))
    print("commands:    ", " | ".join(commands()))
    for phrase in a.phrase:
        print(f"{phrase!r}: wake={is_wake(phrase)} command={match_command(phrase)}")


def cmd_simulate(a: argparse.Namespace) -> None:
    """Feeds the texts through the listener as if a housemate sent them. Posts nothing (dry run); commands run for real."""
    from .listen import Listener
    l = Listener(_guid(a), post_print, listen_s=a.listen_s, dry_run=True)
    for i, text in enumerate(a.text, 1):
        m = {"rowid": -i, "guid": f"sim-{int(time.time())}-{i}", "text": text, "is_from_me": 0,
             "sender": a.sender, "ts_utc": time.strftime("%Y-%m-%d %H:%M:%S"), "attachments": []}
        print(f"> {text}")
        l.handle(m)
        print(f"  armed={l.armed}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m wtdd.chat")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name: str, help_: str, fn) -> argparse.ArgumentParser:
        s = sub.add_parser(name, help=help_)
        s.add_argument("--guid", help="chat guid (default WTDD_CHAT_GUID)")
        s.set_defaults(fn=fn)
        return s

    sub.add_parser("chats", help="named chats with guid, members, last message time (read-only)").set_defaults(fn=cmd_chats)

    w = add("watch", "poll one chat by ROWID, store into memory.db (read-only)", cmd_watch)
    w.add_argument("--every", type=float, default=2.0)
    w.add_argument("--once", action="store_true", help="one poll, then exit")
    w.add_argument("--since", type=int, help="start watermark (default MAX(ROWID): no replay)")

    l = add("listen", "wake phrase arms the dog; commands from WTDD_COMMANDS are recognized and run", cmd_listen)
    l.add_argument("--every", type=float, default=2.0)
    l.add_argument("--listen-s", type=float, default=float(config.maybe("WTDD_LISTEN_S") or 120),
                   help="seconds the dog stays armed after a wake or command")
    l.add_argument("--dry-run", action="store_true", help="recognize and log, post nothing")
    l.add_argument("--once", action="store_true")

    sm = add("simulate", "feed texts through the listener (dry-run posts, REAL commands)", cmd_simulate)
    sm.add_argument("text", nargs="+")
    sm.add_argument("--sender", default="+10000000000")
    sm.add_argument("--listen-s", type=float, default=120.0)

    t = sub.add_parser("triggers", help="print the wake phrases and commands, and test phrases against them")
    t.add_argument("phrase", nargs="*")
    t.set_defaults(fn=cmd_triggers)

    s = add("send", "one gated text post", cmd_post)
    s.add_argument("--text", required=True)
    s.add_argument("--trigger", help="idempotence key (default cli:<epoch>)")
    s.set_defaults(file=None)

    u = add("update", "same as send, one line only, kind update", cmd_post)
    u.add_argument("--text", required=True)
    u.add_argument("--trigger", help="idempotence key (default cli:<epoch>)")
    u.set_defaults(file=None)

    ph = add("photo", "one gated file post with an optional caption", cmd_post)
    ph.add_argument("--file", required=True)
    ph.add_argument("--text")
    ph.add_argument("--trigger", help="idempotence key (default cli:<epoch>)")

    sp = add("spam", f"bounded burst of distinct posts, n capped at {SPAM_CAP}", cmd_spam)
    sp.add_argument("--text", required=True)
    sp.add_argument("--trigger", help="idempotence key prefix (default cli:<epoch>)")
    sp.add_argument("--n", type=int, default=5)
    sp.add_argument("--every", type=float, default=2.0)

    add("reply", "one model turn on the newest wake message, posted behind the gate", cmd_reply).add_argument("--n", type=int, default=20)
    add("context", "print the composed context", cmd_context).add_argument("--n", type=int, default=20)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except PermissionError as e:
        print(f"[wtdd:chat] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
