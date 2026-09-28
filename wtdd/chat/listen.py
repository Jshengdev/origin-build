"""The ears' state machine: a wake phrase arms the dog for listen_s; while armed, messages are matched against the
command list and run; "stop" disarms. Every wake, command, and ask is a ledger row (chat.wake / chat.command /
chat.ask); every post goes through __main__.post keyed on the guid of the message that caused it
(wake:/fire:/doin:/say:/alarm:/done:/ack:/res:/stop:/ai:<guid>, decide:<guid>:<stop> for a stop's question, and
ok:/reask:/unread:/danger:<reply guid> for what a reply was read as), so a re-read message can never post twice. post()
claims a key before it sends, so a send that fails has consumed its key: its error is posted under its own
(say-fail:/fire-fail:/ai-fail:/escalate-fail:), never re-posted under the claimed one.

Run: python -m wtdd.chat listen [--dry-run] [--every 2] [--listen-s 120] [--once]
     python -m wtdd.chat simulate "what the dog doin" "lights off" "stop"   (dry-run posts, REAL commands)

Facts. No replay at boot: the watermark starts at MAX(ROWID). WTDD_LISTEN_S (default 120) is the armed window and any
recognized message re-arms it. Who may wake the dog: any member while HOUSEMATES is empty (one WARN), else the listed
handles (any other sender is ignored with one masked WARN per sender); from-me rows only with WTDD_ALLOW_SELF=1
(Johnny's phone shares the dog's account), and even then the dog's
own posts are refused by confirmed guid and by the opening words of its replies. "yo dog ..." (or "hey dog", "dog ...") is a chat turn: the model answers from the group's context (memory.context: who
said what, what the dog did and reported, corrections), reading the same sender's next messages for GATHER_S as part
of the request; nothing else in the chat is answered. "who dis?!" (a round's look with a person in frame, or
intruder_alarm) is a flag to the on-call person and opens a question (pending.json, naming the chat that was asked):
that chat's next answer within PENDING_WINDOW_S (a held flag: ACK_WINDOW_S) is read typed (verdict(), below); no
answer = stood down, logged. A
housemate's reply that starts like a correction ("that's socks", "not a bird", "actually ...") within 30 min of the
dog's last posted look is a
chat.correction row, is appended to state.json, is acknowledged with "noted: ...", and the next look's prompt carries
it (the vision model is told what the housemates said it got wrong). WTDD_ROUND=dog makes the round the
real dog's: the wake starts the API's path follower (the dog must be calibrated on the remote first) and the field
follows the dog's believed pose; unset, the entity walks the drawn path and the dog is hand-driven. WTDD_WAKE_SHOW=1 makes a wake run the
demo in Johnny's order (dog_on_fire picture, "dog doin", the walk with a look-and-say at every stop on the map: nod,
photo, one sentence from the vision model posted with the photo, and with WTDD_ALARM=1 "who dis?!" when a person is in frame
and a hold of VERDICT_WAIT_S for the on-call person's verdict; then "dog done") instead of a text ack. The round
blocks the poll, so a wake typed while it ran is read after "dog done": one whose chat.db ROWID is at or below
MAX(ROWID) when the round ended starts nothing (one WARN); one typed after "dog done" starts the next, armed or not (a
round shorter than WTDD_LISTEN_S leaves the chat armed; a wake there is not a re-arm). WTDD_AGENT=1
sends an armed message that is not a fixed command to wtdd.agent.ask with the chat context. A failed command is
reported to the group as its class and message, never faked; a done one as its text, else the tool's result, else
the raw dict (a registry tool answers {"result": ...}), never an empty message. Live wake demo receipt (2026-09-13 03:0x, in
README.md): "what teh dog doin" recognized at 0.94, picture 3.4 s, walk 63.6 s, 3 posts, 3 read-back
guids, 0 duplicates.

The on-call person (item 03, oncall.py; WTDD_ON_CALL_NAME / WTDD_ON_CALL_HANDLE). A flag goes to their 1:1 chat
(escalate(), kind "escalate", the photo and "who dis?!"), not the group unless S10 (below) makes the group the on-call
chat; the group still gets the look's say: post.
The listener reads both chats (read(), one watermark each, every message tagged m["chat"]). The on-call chat only
answers flags: a verdict or a correction, from that person's own messages; a wake phrase or command there never arms
the dog. Replies go back to the chat that answered. intruder.verdict and chat.correction rows carry acked_ms (the post's
confirmed chat.db time to the reply's chat.db time, UTC, whole seconds; None + acked_error + a WARN when there is no
confirmed post), shift_id and chat. No person configured, or the send to them failed: one WARN at boot for the first,
and either is posted to the group as its error under escalate-fail:<key> (never alarm:<key>, which a failed send has
already claimed), no question opened, no hold, the round goes on. UNVERIFIED until the first live run: a reply landing
in the 1:1 chat as read here, and the send to it (send.py).

S10, the demo: WTDD_ON_CALL_GUID set to the group's own guid makes the group the on-call target (oncall.person()). The
flag goes to the group, the group is read once, and it keeps its wake words, commands and chat turns: while a flag is
open those are not an answer (a command only when the whole message is one: "sit" is not an answer, "it is teri"
is; the 1:1 rule above, answers only, applies to a 1:1 on-call chat only). The first clear
reply from a member (not a wake word, a command or a chat turn) decides, as in the 1:1. Every intruder.verdict row
carries args.by (the HOUSEMATES first name, else "a member"), args.say (one first-person sentence, the reply quoted
with any phone or email in it replaced by "a member", as the page's redact() does) and args.decided true; args.from
keeps the raw handle (the ledger is private, the page is filmed). UNVERIFIED until the first live run in THE CASTLE.
With 17, every row _row writes carries them; say quotes the reading's verdict and ends with what the listener did
(DID_SAY: sounding the alarm, standing down, closing it, holding it open).

The stop's action (item 17, wtdd/decide.py: the label and p through the table on the map). escalate: the photo and
decide.heads_up_line go to the on-call 1:1 through escalate() under decide:<guid>:<stop>, a pending question of kind
heads_up, and the hold ("couldn't escalate" in the group, no question, when that fails); ask: 02's "not sure" line to
the group, kind decide; continue: nothing. A stop whose who-dis already asked asks nothing more (one question per stop).
The verdict: the answer is read by decide.read_reply (one reply.decided row: a meaning and its p), then one
intruder.verdict row {verdict, meaning, p, action: what the listener did}. stranger sounds the alarm ("STRANGER
DANGER!!!" x3 + light_alarm) only on a who_dis question (a person in frame at an ask stop, or intruder_alarm); on a
heads_up or decide question it stands down. standing_down: "ok, standing down" (verdict known); handled: "ok, closed";
acknowledged: the question stays open for handled, nothing posted; below WTDD_REPLY_THRESHOLD or unclear: "do you know
them? yes or no" once (no verdict row yet; the round keeps holding; the next reply is read against the re-ask), then
stand down, logged as unclear; a re-ask nobody answers gets that unclear row from the first reply's reading and acked
fields when the hold times out or the window expires (_drop), never a silent unlink. A failed live reading: "couldn't
read the reply: <error>", verdict unread, stand down, never the regex. Never an alarm on an unclear reply. A pending of
kind halt (item 00) is never read as a reply. One acked_ms per flag: the verdict row after a hold carries closed_ms
instead, and after a re-ask the final row keeps the first reply's time. A verdict read by the DEMO_CACHE stub (no
JEV_API_KEY) is a cached/stub row, like its reply.decided row; an unread one is not. pending.json holds one question.
A held flag is exempt from PENDING_WINDOW_S: it lasts until handled closes it, until the next stop's question replaces
it (one WARN naming it), or ACK_WINDOW_S (1800 s, the head's choice for beat 2.4b) after the acknowledgement, whichever
is first; then one intruder.verdict row, expired / stand_down, names the acknowledgement and the window, with a WARN.
Only the chat that was asked answers: the group's "not sure" names the group (dog_say's, which names no chat,
is the group's), so the on-call person's "handled" about a held flag never answers the group's question. A reply whose
chat.db time is before the open question's confirmed post was typed about an earlier flag: one WARN, not read, the
question stays open (a dry or failed post cannot prove this, and reads as before). UNVERIFIED until the first live run:
the re-ask's answer read by Jev, a hold across two stops, that ACK_WINDOW_S (1800 s) is long enough for a real "handled"
on camera, and that a live reply's chat.db time is never before the post it answers.

Reset, between two takes (POST /chat/reset): the API drops pending.json, writes RESET (its time) and one chat.reset row.
The next poll(), or the hold in progress (await_verdict, every second), reads RESET (_reset): disarmed, any question still
open dropped, the hold ended as reset (no verdict row, nothing posted), one line, the flag deleted; the next wake starts a
fresh round. A reset pressed mid-walk ends the next stop's hold as it starts and never stops the walk (Stop does that).
UNVERIFIED until the first live run: a press landing during a real hold at a stop.
The reset also closes a photo share's window (the API deletes SHARE; _reset drops the one read this poll).

A shared photo's replies (POST /images/share, wtdd/images.py share). SHARE (<repo>/share.json {trigger, file, by, at,
until}) is read once per poll() (_share: in a try, a missing file is none open, never exists-then-read); past its until
it is closed, with one line per window. While it is open and no question is (pending.json), a group message from an
allowed sender that the verdict, the correction, the chat turn and the wake did not take, and that is not a bare
command (the whole message one), is ONE chat.reply row {share, file, from (the raw handle: GET /images and /ledger
redact it), text, ts (chat.db's, UTC), rowid, guid} (share_reply). Nothing is posted and no model is called. The dog's
own posts never reach it (allowed(): its confirmed guids, and "from the dog's round", the default caption, among
OWN_OPENERS). A reply opening like a correction ("that's ...", "its ...", "not ...") within CORRECTION_WINDOW_S of the
dog's last posted look (the shared photo is one) is a correction and is acknowledged "noted: ...", never a reply. The
window ends at until, at the next share (a new trigger), or at POST /chat/reset (SHARE deleted). UNVERIFIED until the
first live share: that a real reply in THE CASTLE lands in the window and is read here, and that SHARE_WINDOW_S (600 s)
is the right length."""
from __future__ import annotations
import json
import re
import threading
import time
from typing import Any, Callable

from .. import commands as cmds
from .. import config
from ..ledger import append, log, rows as ledger_rows
from . import db, memory, oncall
from .housemates import HOUSEMATES, PRIVATE, name as hname
from .triggers import commands as command_list, is_chat, is_wake, match_command, normalize, wake_phrases

CORRECTION = re.compile(r"^(its|it s|thats|that s|those are|these are|that is|no|nope|wrong|actually|not)\b")
CORRECTION_WINDOW_S = 1800   # a correction counts within this long after the dog's last post
STATE = config.ROOT / "state.json"
PENDING = config.ROOT / "pending.json"   # the open question from intruder_alarm ("who dis?!"): the chat's next answer decides
RESET = config.ROOT / "chat.reset"       # POST /chat/reset's flag (its time): the next poll() or the hold in progress disarms (_reset)
HEARTBEAT = config.ROOT / "listen.json"  # the remote's "group chat" status (GET /chat): beat(), from its own thread in run()
SHARE = config.ROOT / "share.json"       # POST /images/share's open window {trigger, file, by, at, until}: the group's replies are kept (share_reply)
SHARE_WINDOW_S = 600                     # how long after a shared photo the group's messages are kept as its replies
PENDING_WINDOW_S = 120
ACK_WINDOW_S = 1800           # the head's choice for beat 2.4b: a held flag ("on it") stays open this long after the acknowledgement
VERDICT_WAIT_S = 45.0         # at a stop with a person in frame the round holds this long for the on-call person's answer
IDK = re.compile(r"\b(idk|dunno|no idea|dont know|don t know|no clue|not me|nope|who|never seen|stranger)\b")
GATHER_S = 6.0                # after "yo dog ...", the same sender's next messages within this long join the request
DID_SAY = {"alarm": "I'm sounding the alarm.", "stand_down": "I'm standing down.", "close": "I'm closing it.",
           "hold": "I'm holding it open until it's handled."}   # args.say's ending, by what the listener did (17's actions)

Poster = Callable[[str, str, str, str | None, str | None], Any]   # (guid, trigger_key, kind, text, file)
OWN_OPENERS = ("the dog is doin", "dog doin", "dog done", "on it:", "couldn't", "here's what i see", "yo, we don't know", "noted:",
               "who dis", "stranger danger", "ok, standing down", "ok, done listening",
               "living room lights", "did:", "listening for", "not sure:",
               "heads up:", "do you know them", "ok, closed", "from the dog's round")   # how the dog's own text posts begin
REASK = "do you know them? yes or no"   # the one re-ask when a reply is unclear or read below WTDD_REPLY_THRESHOLD


def _flag(key: str) -> bool:
    return config.maybe(key) not in (None, "0", "false", "no")


class Listener:
    def __init__(self, guid: str, post: Poster, listen_s: float = 120.0, dry_run: bool = False):
        self.guid, self.post, self.listen_s, self.dry = guid, post, listen_s, dry_run
        self.armed_until = 0.0
        self.armed_by: str | None = None
        self.last = db.max_rowid()          # no replay at boot
        self.round_end = 0                  # chat.db's MAX(ROWID) when the last round ended: a wake at or below it was typed during it
        self._warned = False
        self._unlisted: set[str] = set()    # senders not in HOUSEMATES already warned about (one WARN each)
        self.share: dict[str, Any] | None = None   # the open photo share, read once per poll() (_share)
        self._closed: str | None = None     # the share whose window closing was already logged (one line)
        self._kept: dict[str, int] = {}     # replies this listener kept, by share trigger
        self.oncall_handle = config.maybe("WTDD_ON_CALL_HANDLE")
        self.oncall = config.maybe("WTDD_ON_CALL_GUID") or (oncall.guid(self.oncall_handle) if self.oncall_handle else None)   # the group (S10) or the 1:1 (03)
        self.group_oncall = self.oncall == guid   # S10: the group answers its own flags and keeps its wake words and commands
        self.marks = {g: self.last for g in (guid, self.oncall) if g}   # one watermark per chat read (ROWIDs are global)
        if not self.oncall:
            log("chat", "WARN no on-call person (WTDD_ON_CALL_GUID and WTDD_ON_CALL_HANDLE unset): a flag will be posted to the group as its error")

    @property
    def armed(self) -> bool:
        return time.time() < self.armed_until

    def allowed(self, m: dict[str, Any]) -> bool:
        if self.oncall and not self.group_oncall and m.get("chat") == self.oncall:   # the on-call 1:1: only that person's own words, never a from-me bubble
            return not m["is_from_me"] and m["sender"] == self.oncall_handle
        if m["is_from_me"]:
            # WTDD_ALLOW_SELF=1 lets Johnny trigger from his own phone (same account as the dog). The dog's own posts are
            # still refused: by confirmed guid, and by the shape of its replies, so it can never wake itself.
            if not _flag("WTDD_ALLOW_SELF"):
                return False
            text = (m.get("text") or "").lower()
            return not (m["guid"] in memory.posted_guids() or text.startswith(OWN_OPENERS))
        if not HOUSEMATES:
            if not self._warned:
                log("chat", "WARN HOUSEMATES is empty: any member of the group may wake the dog")
                self._warned = True
            return True
        if m["sender"] in HOUSEMATES:
            return True
        if m["sender"] not in self._unlisted:   # once per sender, masked (stderr is on screen while filming)
            self._unlisted.add(m["sender"])
            log("chat", "WARN sender not in HOUSEMATES: ignored (add its handle to housemates.py; `python -m wtdd.chat watch` prints it)",
                sender=PRIVATE.sub(lambda h: h.group()[:3] + "…" + h.group()[-4:], m["sender"] or "") or "no handle")
        return False

    def say(self, key: str, text: str | None, file: str | None = None, guid: str | None = None) -> None:
        if self.dry:
            log("chat", f"DRY would post [{key}]: {text}", file=file or "", to=guid or self.guid)
            return
        self.post(guid or self.guid, key, "listen", text, file)

    def escalate(self, key: str, text: str, file: str | None) -> str:
        """A flag (kind "escalate") to oncall.person()'s chat: the on-call person's 1:1 (03), or the group itself when
        WTDD_ON_CALL_GUID names it (S10). No person configured raises the RuntimeError naming the key (the caller posts it
        as the error). Returns the chat the flag went to."""
        to = oncall.person()["guid"]
        if self.dry:
            log("chat", f"DRY would escalate [{key}]: {text}", to=to, file=file or "")
            return to
        self.post(to, key, "escalate", text, file)
        return to

    def _open(self, pend: dict[str, Any]) -> None:
        """This stop's question into pending.json, which holds one. A held flag ("on it") outlives its stop, so an open
        question it replaces is one WARN naming that flag's trigger: dropped, never silently."""
        if PENDING.exists():
            old = json.loads(PENDING.read_text())
            log("chat", "WARN an open flag is replaced by this stop's question", was=old.get("trigger"),
                acknowledged=bool(old.get("acknowledged")), age_s=round(time.time() - old.get("t", 0)), now=pend["trigger"])
        PENDING.write_text(json.dumps(pend))

    def _event(self, tool: str, m: dict[str, Any], **extra: Any) -> None:
        append({"step": tool, "agent": "central", "tool": tool, "app": "imessage", "ok": True,
                "args": {"from": m["sender"], "text": (m["text"] or "")[:200], "guid": m["guid"], **extra},
                "state_before": None, "state_after": {"armed": self.armed, "armed_by": self.armed_by},
                "response_or_error": None, "latency_ms": 0})

    def look_and_say(self, m: dict[str, Any], at: int | None = None) -> None:
        """A look point: nod, photograph, one sentence from the vision model, posted with the photo; a person in frame
        (WTDD_ALARM, or the stop's ask) is flagged to the on-call person with the photo and the round holds for their verdict.
        Keys carry the stop index, so every stop of one wake is its own never-twice claim. A failure is posted as its
        error, never faked. The stop's decision (wtdd/decide.py) carries its action: escalate sends the photo and the
        heads-up line to the on-call person (a heads_up question, the hold); ask posts the "not sure" line with the photo
        to the group (a decide question, the hold); continue asks nothing. "who dis?!" wins when both would ask (one
        question per stop). Every pending names the question it asked."""
        from ..tools.dog_say import look_and_see
        k = m["guid"] + (f":{at}" if at is not None else "")
        look, ask = "tilt", _flag("WTDD_ALARM")
        if at is not None:   # the action recorded at this stop (map.json actions): the look, and whether this is the intruder check
            from ..field import MAP
            action = (json.loads(MAP.read_text()).get("actions") or {}).get(str(at)) or {}
            look, ask = action.get("look", "tilt"), bool(action.get("ask", False))
        try:
            seen = look_and_see(look, stop=at)
            self.say(f"say:{k}", seen["text"], seen["file"])
        except Exception as e:  # noqa: BLE001
            self.say(f"say-fail:{k}", f"couldn't look: {type(e).__name__}: {str(e)[:100]}")
            return
        if seen.get("person") and ask:   # the intruder check: someone in frame, flag the on-call person, hold here for their verdict
            try:
                to = self.escalate(f"alarm:{k}", "who dis?!", seen.get("file"))
            except Exception as e:  # noqa: BLE001  (nobody to flag, or the flag failed: posted to the group as its error, no hold;
                # its own key, since a send that failed after its claim has consumed alarm:<k> and the stop is never re-flagged)
                self.say(f"escalate-fail:{k}", f"couldn't escalate: {type(e).__name__}: {str(e)[:100]}")
                return
            self._open({"kind": "who_dis", "t": time.time(), "file": seen.get("file"), "seconds": 5,
                        "trigger": f"alarm:{k}", "chat": to, "classes": (seen.get("detector") or {}).get("classes"),
                        "question": "who dis?!"})
            self.await_verdict(VERDICT_WAIT_S)
        dec = seen["decision"]   # look_and_see always returns one: {label, p, needs_person, model, action} or {error}
        if "error" in dec:
            self.say(f"decide:{k}", f"couldn't decide: {dec['error']}")
        elif seen.get("person") and ask:
            pass   # one question per stop: the who-dis above already asked the person on call
        elif dec["action"] == "escalate":   # the table on the map sends this label to the person on call, at any p
            from ..decide import heads_up_line
            line = heads_up_line(dec, at)
            try:
                to = self.escalate(f"decide:{k}", line, seen.get("file"))
            except Exception as e:  # noqa: BLE001  (nobody to flag, or the flag failed: posted to the group as its error, no hold)
                self.say(f"escalate-fail:{k}", f"couldn't escalate: {type(e).__name__}: {str(e)[:100]}")
                return
            self._open({"kind": "heads_up", "t": time.time(), "file": seen.get("file"), "seconds": 5,
                        "trigger": f"decide:{k}", "chat": to, "classes": (seen.get("detector") or {}).get("classes"),
                        "decision": dec, "question": line})
            self.await_verdict(VERDICT_WAIT_S)
        elif dec["action"] == "ask":
            from ..decide import ask_line
            line = ask_line(dec)
            self.say(f"decide:{k}", line, seen.get("file"))
            self._open({"kind": "decide", "t": time.time(), "file": seen.get("file"), "seconds": 5,
                        "trigger": f"decide:{k}", "chat": self.guid, "classes": (seen.get("detector") or {}).get("classes"),
                        "decision": dec, "question": line})
            self.await_verdict(VERDICT_WAIT_S)

    def await_verdict(self, seconds: float) -> bool:
        """After "who dis?!" at a stop, the listener is inside the round, so it reads the chats here: the asked chat's
        next message decides (verdict(): read typed). A re-ask keeps the round holding for the answer to it, a fresh
        `seconds` from the re-ask (at most twice `seconds` in all, under the follower's 180 s stop timeout). No answer
        in `seconds` = the question is withdrawn and the round goes on; that is logged, never
        faked, and a re-ask nobody answered is its unclear verdict row (_drop). A reset (RESET) ends the hold at once:
        no verdict, nothing posted, the round goes on."""
        t0 = time.monotonic()
        log("chat", "who dis: waiting for the verdict", seconds=seconds)
        while time.monotonic() - t0 < seconds:
            if self._reset(holding=True):
                return False
            for m in self.read():
                if m.get("text") and self.allowed(m) and self.verdict(m):
                    pend = json.loads(PENDING.read_text()) if PENDING.exists() else {}
                    if pend.get("reasked") and not pend.get("acknowledged"):
                        t0 = time.monotonic()   # asked once more: the re-ask gets its own `seconds`
                        continue
                    return True
                log("chat", "who dis: a message while holding, not the verdict: not handled", chat=m["chat"], chars=len(m.get("text") or ""))
            time.sleep(1.0)
        self._drop(json.loads(PENDING.read_text()) if PENDING.exists() else {}, "who dis: no answer at the stop, moving on",
                   waited_s=round(time.monotonic() - t0))
        return False

    def _reset(self, holding: bool = False) -> bool:
        """POST /chat/reset's flag (RESET), read at every poll() and every second of a hold: disarm, drop any question
        still open (one opened after the press, at a stop mid-walk, would answer the next take's first message), one
        line, delete the flag. No verdict row and nothing posted: the API's chat.reset row is the receipt. True if set."""
        try:
            at = RESET.read_text().strip()   # read once, never exists-then-read (#90): the API writes it from its own process
        except FileNotFoundError:
            return False
        dropped = PENDING.exists()
        log("chat", "RESET: disarmed" + (", hold ended" if holding else "") + ", nothing posted", at=at,
            was_armed=self.armed, dropped=dropped)
        self.armed_until, self.armed_by, self.share = 0.0, None, None   # the API deleted share.json: this poll keeps no reply
        PENDING.unlink(missing_ok=True)
        RESET.unlink(missing_ok=True)
        return True

    def _row(self, pend: dict[str, Any], reply: dict[str, Any], fields: dict[str, Any], stub: bool,
             verdict: str, meaning: str | None, p: float | None, did: str) -> None:
        """One intruder.verdict row: the reply it rests on (from, text, guid, chat), the flag it answers, the reply-clock
        fields; a reading by the DEMO_CACHE stub labels it cached/stub (unread: there was no reading at all). S10's by,
        say and decided on every row: say quotes the reply (phones and emails read "a member"), the verdict, and what
        the listener did (DID_SAY)."""
        by = HOUSEMATES.get(reply["from"]) or "a member"   # S10: the name on camera (the page's Receipts): never the handle
        ms = fields.get("acked_ms", fields.get("closed_ms"))   # after a hold the reply's time from the flag is closed_ms
        say = (f"{by} answered first: '{PRIVATE.sub('a member', reply['text'])[:80]}' ({verdict})"
               + (f" after {ms // 1000} s" if ms is not None else "") + ". " + DID_SAY[did])
        append({"step": "intruder.verdict", "agent": "central", "tool": "intruder.verdict", "app": "imessage", "ok": True,
                "args": {"from": reply["from"], "text": reply["text"], "guid": reply["guid"], "asked": pend.get("trigger"), **fields,
                         "chat": reply["chat"], "by": by, "say": say[:1].upper() + say[1:], "decided": True},
                "state_before": None, "state_after": {"verdict": verdict, "meaning": meaning, "p": p, "action": did},
                "response_or_error": None, "latency_ms": 0,
                **({"cached": True, "source": "stub"} if stub and verdict != "unread" else {})})
        log("chat", "VERDICT", by=hname(reply["from"]), verdict=verdict, meaning=meaning or "", p=p, action=did,
            text=reply["text"][:60], **{k: v for k, v in fields.items() if k.endswith("_ms")})

    def _expired(self, pend: dict[str, Any]) -> bool:
        """An open question past its window is dropped (_drop) and True. PENDING_WINDOW_S from its post; an acknowledged
        flag is exempt from that and lasts ACK_WINDOW_S from the acknowledgement (a pending held before this names none:
        from its post)."""
        held = pend.get("acknowledged")
        since = ((pend.get("held") or {}).get("t") or pend.get("t", 0)) if held else pend.get("t", 0)
        if time.time() - since <= (ACK_WINDOW_S if held else PENDING_WINDOW_S):
            return False
        self._drop(pend, "who dis: no answer in time, standing down")
        return True

    def _drop(self, pend: dict[str, Any], unanswered: str, **kv: Any) -> None:
        """An open question withdrawn with no final reading (the hold timed out, or its window expired), never silently.
        A held flag never closed: one intruder.verdict row, expired / stand_down, naming the acknowledgement it held on and
        ACK_WINDOW_S, with no acked_ms (the hold's row has the flag's one), and a WARN. A re-ask nobody answered: one row,
        unclear / stand_down, from the first reply's reading and with its acked fields (the person answered then).
        Nobody answered at all: the `unanswered` line, no row (no reply)."""
        PENDING.unlink(missing_ok=True)
        first, held = pend.get("first"), pend.get("held")
        if pend.get("acknowledged"):
            if held:
                self._row(pend, held, {"shift_id": held["shift_id"], "window_s": ACK_WINDOW_S}, held["stub"],
                          "expired", held["meaning"], held["p"], "stand_down")
            log("chat", "WARN a held flag was never closed: standing down", trigger=pend.get("trigger"),
                held_on=(held or {}).get("text", "")[:40], window_s=ACK_WINDOW_S, **kv)
        elif pend.get("reasked") and first:
            self._row(pend, first, pend.get("acked") or {}, first["stub"], "unclear", first["meaning"], first["p"], "stand_down")
            log("chat", "re-ask unanswered: standing down, unclear", trigger=pend.get("trigger"), **kv)
        else:
            log("chat", unanswered, **kv)

    def wake_show(self, m: dict[str, Any]) -> None:
        """The wake demo, in Johnny's order: the picture, "dog doin" as the walk starts, the walk (wtdd/field.py, the same
        one the remote's button runs) with look_and_say at every stop drawn on the map (or once at the end when no stop
        was looked at: each is counted as it happens, so a walk that fails after one never looks again), then "dog
        done". Each part is a tool call and a gated post keyed on the wake message; a failed part is posted as its
        error, never faked, and the sequence still ends with "dog done". With the real dog, a walk that fails (or a
        Ctrl-C of the listener) first halts the follower (field.halt, POST /dog/stop: inside walk() before its end dark,
        else here, one dog.stop row either way), so the dog is never driven under the end look and the next wake's
        follow is not refused; a Ctrl-C then exits, no look. Stop on either dashboard during this round (field.stop
        written since the wake, or the follow ended "stopped") is no end look and "dog done (stopped)"; written before
        the walk began (the picture, "dog doin"), no follow starts."""
        from .. import tools
        from ..field import STOP, halt, walk
        t_wake = time.time()
        pressed = lambda: STOP.exists() and STOP.stat().st_mtime >= t_wake   # noqa: E731  Stop on a dashboard since this wake
        try:
            pic = tools.call("dog_on_fire")
            self.say(f"fire:{m['guid']}", None, pic["file"])
        except Exception as e:  # noqa: BLE001
            self.say(f"fire-fail:{m['guid']}", f"couldn't make the picture: {type(e).__name__}: {str(e)[:100]}")
        self.say(f"doin:{m['guid']}", "dog doin")
        walked: str | None = None
        stops: list[int] = []
        source = "dog" if (config.maybe("WTDD_ROUND") or "entity") == "dog" else "entity"
        try:
            if pressed():         # Stop during the picture or "dog doin": walk() would clear it and the follower would start
                raise RuntimeError("stopped before the walk began")
            if source == "dog":   # the real dog walks the round: the API's follower drives it, the field follows its pose
                import requests
                avoid = (config.maybe("WTDD_ROUND_AVOID") or "1") not in ("0", "false", "no")   # 0 = follow without the dog's avoidance, by explicit choice
                r = requests.post(f"{config.API}/dog/follow", json={"avoid": avoid}, timeout=20).json()
                if not r.get("ok"):
                    raise RuntimeError(f"follow refused: {r.get('error')}")
                log("chat", "follower started", **{k: v for k, v in r["follow"].items() if k in ("i", "n", "stops")})
            out = walk(on_stop=lambda i, p, here: (stops.append(i), self.look_and_say(m, i)), source=source)   # as they happen: a walk that raises later keeps them
            log("chat", "walked", seconds=out["seconds"], writes=out["writes"], errors=out["errors"], stops=len(stops), rooms=",".join(out["rooms"]))
            if out.get("errors"):
                walked = f"{out['errors']} light write(s) failed, see the ledger"
        except BaseException as e:  # noqa: BLE001  (a Ctrl-C too: never leave the follower driving with nobody watching)
            if source == "dog" and not getattr(e, "dog_halted", False):   # walk() halts a failure in its own loop, before the dark
                halt(f"{type(e).__name__}: {e}", "chat")
            if not isinstance(e, Exception):
                raise
            walked = f"couldn't walk the path: {type(e).__name__}: {str(e)[:100]}"
        stopped = pressed() or "follow ended with: stopped" in (walked or "")
        if not stops and not stopped:      # no stop reached: the look point is wherever the dog is now
            self.look_and_say(m)
        self.say(f"done:{m['guid']}", "dog done" + (" (stopped)" if stopped else "") + (f" ({walked})" if walked else ""))

    def correction(self, m: dict[str, Any]) -> bool:
        """A housemate correcting the dog's last report ("that's socks, not a bird"): one chat.correction row naming
        what it corrects (the last posted look: sentence, file, detector counts), appended to state.json so the next
        look's prompt carries it (wtdd/tools/dog_say.py), and acknowledged in the chat. Only within CORRECTION_WINDOW_S
        of the dog's last post, armed or not: the whole ledger is scanned for it (a row count would end the window
        early, as the last 300 rows did; the scan runs only on a correction-shaped message)."""
        if not CORRECTION.match(normalize(m["text"])):
            return False
        chat = m.get("chat") or self.guid   # a chat corrects the last photo it was shown (a row without a guid predates 03)
        looks = [r for r in ledger_rows() if r.get("tool") == "chat.post" and r.get("ok") and (r.get("args") or {}).get("file")
                 and (r["args"].get("guid") or chat) == chat]
        if not looks:
            return False
        last = looks[-1]
        age = time.time() - time.mktime(time.strptime(last["ts"], "%Y-%m-%dT%H:%M:%S"))
        if age > CORRECTION_WINDOW_S:
            return False
        a = last["args"]
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": hname(m["sender"]), "text": m["text"][:200],
                 "corrects": {"said": a.get("text"), "file": (a.get("file") or "").split("/")[-1], "at": last["ts"]}}
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        state.setdefault("corrections", []).append(entry)
        STATE.write_text(json.dumps(state, indent=1) + "\n")
        append({"step": "chat.correction", "agent": "central", "tool": "chat.correction", "app": "imessage", "ok": True,
                "args": {"from": m["sender"], "text": m["text"][:200], "guid": m["guid"], "corrects": entry["corrects"],
                         **oncall.reply_fields(last, m.get("ts_utc")), "chat": chat},
                "state_before": None, "state_after": {"corrections": len(state["corrections"])}, "response_or_error": None, "latency_ms": 0})
        log("chat", "CORRECTION", by=entry["by"], text=m["text"][:60], corrects=entry["corrects"]["said"][:40] if entry["corrects"]["said"] else "")
        self.say(f"fix:{m['guid']}", f"noted: {m['text'][:120]}", guid=chat)
        return True

    def verdict(self, m: dict[str, Any]) -> bool:
        """The asked chat answering an open question, read typed by decide.read_reply (its reply.decided row), then one
        intruder.verdict row {verdict, meaning, p, action} and what the meaning asks for. stranger: "STRANGER DANGER!!!"
        three times and light_alarm, only when the question was "who dis?!" (kind who_dis); a heads_up (17) or decide
        (02) question stands down, so WTDD_ALARM and the map's ask flags still gate the alarm. standing_down: "ok,
        standing down"; handled: "ok, closed"; acknowledged: the question stays open for handled (ACK_WINDOW_S from
        now, exempt from PENDING_WINDOW_S; _expired). Unclear or below WTDD_REPLY_THRESHOLD: one re-ask (the pending's
        question becomes it, and keeps this reply's acked fields and reading), no verdict row yet, then stand down as
        unclear (unanswered: _drop writes that row). After a hold, acked_ms is the hold row's; this row gets closed_ms.
        Rows read by the stub say cached/stub. A failed reading is posted as its error and stands down (verdict unread),
        never the regex. A halt (00) is never read here. Only the chat that was asked answers (a decide question with no
        chat is dog_say's, posted to the group). A reply stamped before the question's confirmed post answers an earlier
        flag: one WARN, not read, the question stays open. The question read is the one posted, never a guess."""
        try:
            pend = json.loads(PENDING.read_text())
        except FileNotFoundError:   # none open (or a reset dropped it a moment ago)
            return False
        if self._expired(pend):
            return False
        chat = m.get("chat") or self.guid
        kind = pend.get("kind")
        asked_in = pend.get("chat") or (self.guid if kind == "decide" else None)   # dog_say's decide names none: it posted to the group
        if asked_in and chat != asked_in:   # only the chat that was asked answers (the on-call person, not the group, and back)
            return False
        if kind == "halt":   # item 00's local stop: resumed by its own word or button, never by a model reading
            return False
        if self.group_oncall and (is_wake(m["text"]) or normalize(m["text"]) in command_list() or is_chat(m["text"])):   # S10: not an answer, the group's own
            # a command only when the whole message is one: match_command's fuzzy word ("it" is sit) dropped real answers
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
        # one acked_ms per flag (numbers.py and 10's record count every one): after a hold, the hold's row has it and this
        # reply's time from the flag is closed_ms; after a re-ask, the first reply's time stands (the person answered then)
        acked = {k.replace("acked_", "closed_"): v for k, v in now.items()} if pend.get("acknowledged") else (pend.get("acked") or now)
        stub = not config.maybe("JEV_API_KEY")   # read_reply's own test: its DEMO_CACHE reading labels this verdict row too
        reply = {"from": m["sender"], "text": m["text"][:200], "guid": m["guid"], "chat": chat}

        def row(verdict: str, meaning: str | None, p: float | None, did: str) -> None:
            self._row(pend, reply, acked, stub, verdict, meaning, p, did)

        try:
            r = read_reply(asked, m["text"], trigger=pend.get("trigger"), chat=chat, guid=m["guid"], **{"from": m["sender"]})
        except Exception as e:  # noqa: BLE001  (its reply.decided row has it; posted, stood down, never the regex)
            PENDING.unlink(missing_ok=True)
            row("unread", None, None, "stand_down")
            self.say(f"unread:{m['guid']}", f"couldn't read the reply: {type(e).__name__}: {str(e)[:100]}", guid=chat)
            return True
        if r["action"] == "reask" and not pend.get("reasked"):   # the next reply answers the re-ask; none, and _drop rows this one
            PENDING.write_text(json.dumps({**pend, "reasked": True, "question": REASK, "acked": acked,
                                           "first": {**reply, "meaning": r["meaning"], "p": r["p"], "stub": stub}}))
            log("chat", "reply unclear: asked once more", meaning=r["meaning"], p=r["p"])
            self.say(f"reask:{m['guid']}", REASK, guid=chat)
            return True
        verdict, did = {"reask": ("unclear", "stand_down"), "alarm": ("stranger", "alarm" if kind == "who_dis" else "stand_down"),
                        "stand_down": ("known", "stand_down"), "close": ("handled", "close"),
                        "hold": ("acknowledged", "hold")}[r["action"]]
        if did == "hold":   # on their way: the question stays open for "handled", ACK_WINDOW_S from now (_expired)
            PENDING.write_text(json.dumps({**pend, "acknowledged": True, "held": {**reply, "meaning": r["meaning"], "p": r["p"],
                                           "stub": stub, "shift_id": acked.get("shift_id"), "t": time.time()}}))
        else:
            PENDING.unlink(missing_ok=True)
        row(verdict, r["meaning"], r["p"], did)
        if did == "hold":
            return True
        if did != "alarm":
            self.say(f"ok:{m['guid']}", "ok, closed" if did == "close" else "ok, standing down", guid=chat)
            return True
        self.say(f"danger:{m['guid']}", "STRANGER DANGER!!! STRANGER DANGER!!! STRANGER DANGER!!!", guid=chat)
        try:
            alarm = tools.call("light_alarm", seconds=pend.get("seconds", 5))
            log("chat", "alarm", signaled=len(alarm["signaled"]), errors=len(alarm["errors"]))
        except Exception as e:  # noqa: BLE001
            self.say(f"alarm-fail:{m['guid']}", f"couldn't sound the alarm: {type(e).__name__}: {str(e)[:100]}", guid=chat)
        return True

    def chat(self, m: dict[str, Any]) -> None:
        """A chat turn: "yo dog ..." goes to the model with the group's context (who said what, what the dog did and
        reported, the corrections). The same sender's next messages within GATHER_S are read as part of the request.
        One chat.ask row; the answer is one gated post keyed on the message; nothing else in the chat is answered."""
        from ..agent import ask
        parts = [m["text"]]
        time.sleep(GATHER_S)
        more = self.read()
        here = m.get("chat") or self.guid
        parts += [x["text"] for x in more if x["sender"] == m["sender"] and x["chat"] == here and x.get("text")]
        for x in more:   # a wake, a correction or an on-call answer from anyone else in the window is still handled
            if (x["sender"] != m["sender"] or x["chat"] != here) and x.get("text"):
                self.handle(x)
        text = " ".join(parts)
        self._event("chat.ask", m, gathered=len(parts) - 1, text=text[:200])
        try:
            out = ask(text, context=memory.context(self.guid))
            self.say(f"ai:{m['guid']}", out["text"][:300] or f"did: {', '.join(c['tool'] for c in out['calls']) or 'nothing'}")
        except Exception as e:  # noqa: BLE001
            self.say(f"ai-fail:{m['guid']}", f"couldn't: {type(e).__name__}: {str(e)[:120]}")

    def handle(self, m: dict[str, Any]) -> None:
        text = m["text"]
        if not text or not self.allowed(m):
            return
        if self.oncall and not self.group_oncall and m.get("chat") == self.oncall:   # the on-call 1:1 answers flags only; it never wakes or commands the dog
            if not (self.verdict(m) or self.correction(m)):
                log("chat", "on-call message answers no open flag: not a command there", chars=len(text))
            return
        if self.verdict(m):
            return
        if self.correction(m):
            return
        if is_chat(text):
            self.chat(m)
            return
        wake = is_wake(text)
        if not wake and self.share_reply(m):
            return
        if not self.armed or (wake and self.round_end > 0):   # after a round a wake is judged by its ROWID, armed or not (a short round leaves it armed)
            if not wake:
                return
            if 0 < m.get("rowid", 0) <= self.round_end:   # typed while the last round ran, read only after its "dog done"
                log("chat", "WARN a wake typed during the round: not starting another", by=hname(m["sender"]), phrase=wake[0])
                return
            self.armed_until = time.time() + self.listen_s
            self.armed_by = m["sender"]
            log("chat", "WAKE", by=hname(m["sender"]), phrase=wake[0], score=wake[1])
            self._event("chat.wake", m, phrase=wake[0], score=wake[1])
            if _flag("WTDD_WAKE_SHOW"):
                self.wake_show(m)
                self.round_end = db.max_rowid()
            else:
                self.say(f"wake:{m['guid']}", f"the dog is doin. listening for {int(self.listen_s)}s: {' · '.join(command_list())}")
            return
        hit = match_command(text)
        if not hit:
            if wake:
                self.armed_until = time.time() + self.listen_s
                return
            if not _flag("WTDD_AGENT"):
                log("chat", "armed, no command in message", by=hname(m["sender"]), chars=len(text))
                return
            # the model takes charge: a free-form ask while armed becomes tool calls over the registry
            from ..agent import ask
            self._event("chat.ask", m)
            self.armed_until = time.time() + self.listen_s
            try:
                out = ask(text, context=memory.context(self.guid))
                self.say(f"ai:{m['guid']}", out["text"][:300] or f"did: {', '.join(c['tool'] for c in out['calls']) or 'nothing'}")
            except Exception as e:  # noqa: BLE001
                self.say(f"ai-fail:{m['guid']}", f"couldn't: {type(e).__name__}: {str(e)[:120]}")
            return
        cmd, score = hit
        log("chat", "COMMAND", by=hname(m["sender"]), command=cmd, score=score)
        self._event("chat.command", m, command=cmd, score=score)
        if cmd == "stop":
            self.armed_until = 0.0
            self.armed_by = None
            self.say(f"stop:{m['guid']}", "ok, done listening")
            return
        self.armed_until = time.time() + self.listen_s
        self.say(f"ack:{m['guid']}", f"on it: {cmd}")
        try:
            out = cmds.run(cmd)
        except Exception as e:  # noqa: BLE001  (reported truthfully to the group; the ledger row already has it)
            self.say(f"res:{m['guid']}", f"couldn't {cmd}: {type(e).__name__}: {str(e)[:120]}")
            return
        if isinstance(out, dict):   # a photo {"text", "file"}, a registry tool's {"result"}, else the raw dict: never an empty post
            self.say(f"res:{m['guid']}", out.get("text") or out.get("result") or str(out)[:300], out.get("file"))
        else:
            self.say(f"res:{m['guid']}", str(out)[:300])

    def _share(self) -> dict[str, Any] | None:
        """share.json, read once per poll() (a missing file is none open; POST /chat/reset deletes it from its own process).
        Past its until: None, and one line the first time this listener sees that window closed."""
        try:
            s = json.loads(SHARE.read_text())
        except FileNotFoundError:
            return None
        if time.time() < s["until"]:
            return s
        if self._closed != s["trigger"]:
            self._closed = s["trigger"]
            log("chat", "share window closed", share=s["trigger"], kept=self._kept.get(s["trigger"], 0), window_s=SHARE_WINDOW_S)
        return None

    def share_reply(self, m: dict[str, Any]) -> bool:
        """A group message while a shared photo's window is open (self.share, before its until) and no question is open
        (pending.json: the who-dis answer wins): one chat.reply row naming the share, and True. Nothing is posted and no
        model is called. handle() asks only after the verdict, the correction, the chat turn and the wake have passed it
        by; a bare command (the whole message is one) is the dog's, never a reply. The dog's own posts never reach here
        (allowed())."""
        s = self.share
        if (not s or time.time() >= s["until"] or PENDING.exists() or (m.get("chat") or self.guid) != self.guid
                or normalize(m["text"]) in command_list()):
            return False
        self._kept[s["trigger"]] = n = self._kept.get(s["trigger"], 0) + 1
        append({"step": "chat.reply", "agent": "central", "tool": "chat.reply", "app": "imessage", "ok": True,
                "args": {"share": s["trigger"], "file": s["file"], "from": m["sender"], "text": (m["text"] or "")[:1000],
                         "ts": m.get("ts_utc"), "rowid": m.get("rowid"), "guid": m["guid"]},
                "state_before": {"share": s["trigger"], "until": s["until"]}, "state_after": {"kept": n},
                "response_or_error": None, "latency_ms": 0})
        log("chat", "SHARE REPLY kept", by=HOUSEMATES.get(m["sender"]) or "a member", share=s["trigger"], chars=len(m["text"] or ""), kept=n)
        return True

    def beat(self) -> None:
        """listen.json, whole or not at all (a temp file replaced): GET /chat never reads a half-written beat."""
        hb, by = HEARTBEAT, self.armed_by
        tmp = hb.with_suffix(".tmp")
        tmp.write_text(json.dumps({"t": time.time(), "guid": self.guid, "armed": self.armed, "armed_by": hname(by) if by else None,
                                   "dry": self.dry, "pending": PENDING.exists(), "last_rowid": self.last}))
        tmp.replace(hb)

    def _beats(self, every: float, done: threading.Event) -> None:
        while not done.wait(every):
            self.beat()

    def poll(self) -> int:
        self._reset()
        if self.armed_by and not self.armed:
            log("chat", "disarmed (timeout)", was=hname(self.armed_by))
            self.armed_by = None
        try:
            pend = json.loads(PENDING.read_text())
        except FileNotFoundError:   # none open (POST /chat/reset may unlink it between a check and a read)
            pass
        else:   # outside the try: a FileNotFoundError from _expired's own work is never swallowed here
            self._expired(pend)
        self.share = self._share()
        msgs = self.read()
        for m in msgs:
            self.handle(m)
        return len(msgs)

    def read(self) -> list[dict[str, Any]]:
        """New messages in the group and the on-call 1:1, each stored under its chat and tagged m["chat"], oldest first.
        One watermark per chat: ROWIDs are global, so a shared one could skip a row landing between the two reads."""
        out: list[dict[str, Any]] = []
        for guid, after in list(self.marks.items()):
            msgs = db.new_messages(guid, after)
            if msgs:
                memory.store(guid, msgs)
                self.marks[guid] = msgs[-1]["rowid"]
                out += [{**m, "chat": guid} for m in msgs]
        self.last = max(self.marks.values())
        return sorted(out, key=lambda m: m["rowid"])

    def run(self, every: float = 2.0, once: bool = False) -> None:
        """Polls every `every` s. The heartbeat (listen.json: alive, armed, pending) is beat() once here, then every `every`
        s from its own thread, the only writer, because a round (the walk, the looks, a 45 s hold) runs inside one poll()
        and GET /chat reads a beat older than 10 s as "listener down". Known trade-off: the thread would keep beating if
        the main thread wedged; every blocking call in a round has a timeout (the posts, the API, the follower's 180 s)."""
        log("chat", f"listen guid={self.guid}", oncall=self.oncall or "none", from_rowid=self.last, listen_s=self.listen_s, dry=self.dry,
            wake_phrases=len(wake_phrases()), commands=len(command_list()))
        self.beat()
        done = threading.Event()
        if not once:
            threading.Thread(target=self._beats, args=(every, done), daemon=True).start()
        try:
            while True:
                self.poll()
                if once:
                    break
                time.sleep(every)
        finally:
            done.set()
