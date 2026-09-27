"""The ears' state machine: a wake phrase arms the dog for listen_s; while armed, messages are matched against the
command list and run; "stop" disarms. Every wake, command, and ask is a ledger row (chat.wake / chat.command /
chat.ask); every post goes through __main__.post keyed on the guid of the message that caused it
(wake:/fire:/doin:/say:/alarm:/done:/ack:/res:/stop:/ai:<guid>, and decide:<guid>:<stop> for a stop's "not sure"
question), so a re-read message can never post twice.

Run: python -m wtdd.chat listen [--dry-run] [--every 2] [--listen-s 120] [--once]
     python -m wtdd.chat simulate "what the dog doin" "lights off" "stop"   (dry-run posts, REAL commands)

Facts. No replay at boot: the watermark starts at MAX(ROWID). WTDD_LISTEN_S (default 120) is the armed window and any
recognized message re-arms it. Who may wake the dog: any member while HOUSEMATES is empty (one WARN), else the listed
handles; from-me rows only with WTDD_ALLOW_SELF=1 (Johnny's phone shares the dog's account), and even then the dog's
own posts are refused by confirmed guid and by the opening words of its replies. "yo dog ..." (or "hey dog", "dog ...") is a chat turn: the model answers from the group's context (memory.context: who
said what, what the dog did and reported, corrections), reading the same sender's next messages for GATHER_S as part
of the request; nothing else in the chat is answered. "who dis?!" (a round's look with a person in frame, or
intruder_alarm) is a flag to the on-call person and opens a question (pending.json, naming the chat that was asked):
that chat's next answer within PENDING_WINDOW_S decides, "idk" and its kin = "STRANGER DANGER!!!" x3 + light_alarm,
anything else = "ok, standing down"; no answer = stood down quietly. A housemate's reply that starts like a
correction ("that's socks", "not a bird", "actually ...") within 30 min of the dog's last posted look is a
chat.correction row, is appended to state.json, is acknowledged with "noted: ...", and the next look's prompt carries
it (the vision model is told what the housemates said it got wrong). WTDD_ROUND=dog makes the round the
real dog's: the wake starts the API's path follower (the dog must be calibrated on the remote first) and the field
follows the dog's believed pose; unset, the entity walks the drawn path and the dog is hand-driven. WTDD_WAKE_SHOW=1 makes a wake run the
demo in Johnny's order (dog_on_fire picture, "dog doin", the walk with a look-and-say at every stop on the map: nod,
photo, one sentence from the vision model posted with the photo, and with WTDD_ALARM=1 "who dis?!" when a person is in frame
and a hold of VERDICT_WAIT_S for the on-call person's verdict; then "dog done") instead of a text ack. WTDD_AGENT=1
sends an armed message that is not a fixed command to wtdd.agent.ask with the chat context. A failed command is
reported to the group as its class and message, never faked. Live wake demo receipt (2026-09-13 03:0x, in
README.md): "what teh dog doin" recognized at 0.94, picture 3.4 s, walk 63.6 s, 3 posts, 3 read-back
guids, 0 duplicates.

The on-call person (item 03, oncall.py; WTDD_ON_CALL_NAME / WTDD_ON_CALL_HANDLE). A flag goes to their 1:1 chat
(escalate(), kind "escalate", the photo and "who dis?!"), never to the group; the group still gets the look's say: post.
The listener reads both chats (read(), one watermark each, every message tagged m["chat"]). The on-call chat only
answers flags: a verdict or a correction, from that person's own messages; a wake phrase or command there never arms
the dog. Replies go back to the chat that answered. intruder.verdict and chat.correction rows carry acked_ms (the post's
confirmed chat.db time to the reply's chat.db time, UTC, whole seconds; None + acked_error + a WARN when there is no
confirmed post), shift_id and chat. No person configured, or the send to them failed: one WARN at boot for the first,
and either is posted to the group as its error under escalate-fail:<key> (never alarm:<key>, which a failed send has
already claimed), no question opened, no hold, the round goes on. UNVERIFIED until the first live run: a reply landing
in the 1:1 chat as read here, and the send to it (send.py)."""
from __future__ import annotations
import json
import re
import time
from typing import Any, Callable

from .. import commands as cmds
from .. import config
from ..ledger import append, log, rows as ledger_rows
from . import db, memory, oncall
from .housemates import HOUSEMATES, name as hname
from .triggers import commands as command_list, is_chat, is_wake, match_command, normalize, wake_phrases

CORRECTION = re.compile(r"^(its|it s|thats|that s|those are|these are|that is|no|nope|wrong|actually|not)\b")
CORRECTION_WINDOW_S = 1800   # a correction counts within this long after the dog's last post
STATE = config.ROOT / "state.json"
PENDING = config.ROOT / "pending.json"   # the open question from intruder_alarm ("who dis?!"): the chat's next answer decides
HEARTBEAT = config.ROOT / "listen.json"  # written every poll: the remote's "group chat" status reads it (GET /chat)
PENDING_WINDOW_S = 120
VERDICT_WAIT_S = 45.0         # at a stop with a person in frame the round holds this long for the on-call person's answer
IDK = re.compile(r"\b(idk|dunno|no idea|dont know|don t know|no clue|not me|nope|who|never seen|stranger)\b")
GATHER_S = 6.0                # after "yo dog ...", the same sender's next messages within this long join the request

Poster = Callable[[str, str, str, str | None, str | None], Any]   # (guid, trigger_key, kind, text, file)
OWN_OPENERS = ("the dog is doin", "dog doin", "dog done", "on it:", "couldn't", "here's what i see", "yo, we don't know", "noted:",
               "who dis", "stranger danger", "ok, standing down", "ok, done listening",
               "living room lights", "did:", "listening for", "not sure:")   # how the dog's own text posts begin


def _flag(key: str) -> bool:
    return config.maybe(key) not in (None, "0", "false", "no")


class Listener:
    def __init__(self, guid: str, post: Poster, listen_s: float = 120.0, dry_run: bool = False):
        self.guid, self.post, self.listen_s, self.dry = guid, post, listen_s, dry_run
        self.armed_until = 0.0
        self.armed_by: str | None = None
        self.last = db.max_rowid()          # no replay at boot
        self._warned = False
        self.oncall_handle = config.maybe("WTDD_ON_CALL_HANDLE")
        self.oncall = oncall.guid(self.oncall_handle) if self.oncall_handle else None   # the on-call 1:1 (item 03)
        self.marks = {g: self.last for g in (guid, self.oncall) if g}   # one watermark per chat read (ROWIDs are global)
        if not self.oncall:
            log("chat", "WARN no on-call person (WTDD_ON_CALL_HANDLE unset): a flag will be posted to the group as its error")

    @property
    def armed(self) -> bool:
        return time.time() < self.armed_until

    def allowed(self, m: dict[str, Any]) -> bool:
        if self.oncall and m.get("chat") == self.oncall:   # the on-call 1:1: only that person's own words, never a from-me bubble
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
        return m["sender"] in HOUSEMATES

    def say(self, key: str, text: str | None, file: str | None = None, guid: str | None = None) -> None:
        if self.dry:
            log("chat", f"DRY would post [{key}]: {text}", file=file or "", to=guid or self.guid)
            return
        self.post(guid or self.guid, key, "listen", text, file)

    def escalate(self, key: str, text: str, file: str | None) -> str:
        """A flag to the on-call person's 1:1 (kind "escalate"), never the group. No person configured raises the
        RuntimeError naming the key (the caller posts it as the error). Returns the chat the flag went to."""
        to = oncall.person()["guid"]
        if self.dry:
            log("chat", f"DRY would escalate [{key}]: {text}", to=to, file=file or "")
            return to
        self.post(to, key, "escalate", text, file)
        return to

    def _event(self, tool: str, m: dict[str, Any], **extra: Any) -> None:
        append({"step": tool, "agent": "central", "tool": tool, "app": "imessage", "ok": True,
                "args": {"from": m["sender"], "text": (m["text"] or "")[:200], "guid": m["guid"], **extra},
                "state_before": None, "state_after": {"armed": self.armed, "armed_by": self.armed_by},
                "response_or_error": None, "latency_ms": 0})

    def look_and_say(self, m: dict[str, Any], at: int | None = None) -> None:
        """A look point: nod, photograph, one sentence from the vision model, posted with the photo; a person in frame
        (WTDD_ALARM, or the stop's ask) is flagged to the on-call person with the photo and the round holds for their verdict.
        Keys carry the stop index, so every stop of one wake is its own never-twice claim. A failure is posted as its
        error, never faked. The stop's decision (wtdd/decide.py) asks when it is not sure: the "not sure" line with the
        photo, the same pending question and hold as "who dis?!", which wins when both would ask (one question per stop)."""
        from .. import tools
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
            self.say(f"say:{k}", f"couldn't look: {type(e).__name__}: {str(e)[:100]}")
            return
        if seen.get("person") and ask:   # the intruder check: someone in frame, flag the on-call person, hold here for their verdict
            try:
                to = self.escalate(f"alarm:{k}", "who dis?!", seen.get("file"))
            except Exception as e:  # noqa: BLE001  (nobody to flag, or the flag failed: posted to the group as its error, no hold;
                # its own key, since a send that failed after its claim has consumed alarm:<k> and the stop is never re-flagged)
                self.say(f"escalate-fail:{k}", f"couldn't escalate: {type(e).__name__}: {str(e)[:100]}")
                return
            PENDING.write_text(json.dumps({"kind": "who_dis", "t": time.time(), "file": seen.get("file"), "seconds": 5,
                                           "trigger": f"alarm:{k}", "chat": to, "classes": (seen.get("detector") or {}).get("classes")}))
            self.await_verdict(VERDICT_WAIT_S)
        dec = seen["decision"]   # look_and_see always returns one: {label, p, needs_person, model} or {error}
        if "error" in dec:
            self.say(f"decide:{k}", f"couldn't decide: {dec['error']}")
        elif dec["needs_person"] and not (seen.get("person") and ask):
            from ..decide import ask_line
            self.say(f"decide:{k}", ask_line(dec), seen.get("file"))
            PENDING.write_text(json.dumps({"kind": "decide", "t": time.time(), "file": seen.get("file"), "seconds": 5,
                                           "trigger": f"decide:{k}", "classes": (seen.get("detector") or {}).get("classes"),
                                           "decision": dec}))
            self.await_verdict(VERDICT_WAIT_S)

    def await_verdict(self, seconds: float) -> bool:
        """After "who dis?!" at a stop, the listener is inside the round, so it reads the chats here: the asked chat's
        next message decides (verdict(): "idk" = STRANGER DANGER + the alarm, else stand down). No answer in `seconds` =
        the question is withdrawn and the round goes on; that is logged, never faked."""
        t0 = time.monotonic()
        log("chat", "who dis: waiting for the verdict", seconds=seconds)
        while time.monotonic() - t0 < seconds:
            for m in self.read():
                if m.get("text") and self.allowed(m) and self.verdict(m):
                    return True
                log("chat", "who dis: a message while holding, not the verdict: not handled", chat=m["chat"], chars=len(m.get("text") or ""))
            time.sleep(1.0)
        PENDING.unlink(missing_ok=True)
        log("chat", "who dis: no answer at the stop, moving on", waited_s=round(time.monotonic() - t0))
        return False

    def wake_show(self, m: dict[str, Any]) -> None:
        """The wake demo, in Johnny's order: the picture, "dog doin" as the walk starts, the walk (wtdd/field.py, the same
        one the remote's button runs) with look_and_say at every stop drawn on the map (or once at the end when the map
        has no stops), then "dog done". Each part is a tool call and a gated post keyed on the wake message; a failed
        part is posted as its error, never faked, and the sequence still ends with "dog done"."""
        from .. import tools
        from ..field import walk
        try:
            pic = tools.call("dog_on_fire")
            self.say(f"fire:{m['guid']}", None, pic["file"])
        except Exception as e:  # noqa: BLE001
            self.say(f"fire:{m['guid']}", f"couldn't make the picture: {type(e).__name__}: {str(e)[:100]}")
        self.say(f"doin:{m['guid']}", "dog doin")
        walked: str | None = None
        stops: list[int] = []
        source = "dog" if (config.maybe("WTDD_ROUND") or "entity") == "dog" else "entity"
        try:
            if source == "dog":   # the real dog walks the round: the API's follower drives it, the field follows its pose
                import requests
                avoid = (config.maybe("WTDD_ROUND_AVOID") or "1") not in ("0", "false", "no")   # 0 = follow without the dog's avoidance, by explicit choice
                r = requests.post("http://127.0.0.1:7788/dog/follow", json={"avoid": avoid}, timeout=20).json()
                if not r.get("ok"):
                    raise RuntimeError(f"follow refused: {r.get('error')}")
                log("chat", "follower started", **{k: v for k, v in r["follow"].items() if k in ("i", "n", "stops")})
            out = walk(on_stop=lambda i, p, here: self.look_and_say(m, i), source=source)
            stops = out.get("stops", [])
            log("chat", "walked", seconds=out["seconds"], writes=out["writes"], errors=out["errors"], stops=len(stops), rooms=",".join(out["rooms"]))
            if out.get("errors"):
                walked = f"{out['errors']} light write(s) failed, see the ledger"
        except Exception as e:  # noqa: BLE001
            walked = f"couldn't walk the path: {type(e).__name__}: {str(e)[:100]}"
        if not stops:                      # no stop reached: the look point is wherever the dog is now
            self.look_and_say(m)
        self.say(f"done:{m['guid']}", "dog done" + (f" ({walked})" if walked else ""))

    def correction(self, m: dict[str, Any]) -> bool:
        """A housemate correcting the dog's last report ("that's socks, not a bird"): one chat.correction row naming
        what it corrects (the last posted look: sentence, file, detector counts), appended to state.json so the next
        look's prompt carries it (wtdd/tools/dog_say.py), and acknowledged in the chat. Only within CORRECTION_WINDOW_S
        of the dog's last post, armed or not."""
        if not CORRECTION.match(normalize(m["text"])):
            return False
        chat = m.get("chat") or self.guid   # a chat corrects the last photo it was shown (a row without a guid predates 03)
        looks = [r for r in ledger_rows(300) if r.get("tool") == "chat.post" and r.get("ok") and (r.get("args") or {}).get("file")
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
        """The chat answering "who dis?!" (intruder_alarm): "idk" and its kin mean a stranger, so "STRANGER DANGER!!!"
        three times and light_alarm; anything else stands the dog down with "ok". One intruder.verdict row either way.
        An answer to a decide question (pending kind "decide", "not sure: ...") is the same row and always stands down:
        only "who dis?!" can sound the alarm, so WTDD_ALARM and the map's ask flags still gate it."""
        if not PENDING.exists():
            return False
        pend = json.loads(PENDING.read_text())
        if time.time() - pend.get("t", 0) > PENDING_WINDOW_S:
            PENDING.unlink(missing_ok=True)
            log("chat", "who dis: no answer in time, standing down")
            return False
        chat = m.get("chat") or self.guid
        if pend.get("chat") and chat != pend["chat"]:   # only the chat that was asked answers (the on-call person, not the group)
            return False
        from .. import tools
        stranger = pend.get("kind") != "decide" and bool(IDK.search(normalize(m["text"])))
        PENDING.unlink(missing_ok=True)
        acked = oncall.reply_fields(oncall.post_for(pend.get("trigger"), ledger_rows()), m.get("ts_utc"))
        append({"step": "intruder.verdict", "agent": "central", "tool": "intruder.verdict", "app": "imessage", "ok": True,
                "args": {"from": m["sender"], "text": m["text"][:200], "guid": m["guid"], "asked": pend.get("trigger"), **acked, "chat": chat},
                "state_before": None, "state_after": {"verdict": "stranger" if stranger else "known"}, "response_or_error": None, "latency_ms": 0})
        log("chat", "VERDICT", by=hname(m["sender"]), verdict="stranger" if stranger else "known", text=m["text"][:60], acked_ms=acked["acked_ms"])
        if not stranger:
            self.say(f"ok:{m['guid']}", "ok, standing down", guid=chat)
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
            self.say(f"ai:{m['guid']}", f"couldn't: {type(e).__name__}: {str(e)[:120]}")

    def handle(self, m: dict[str, Any]) -> None:
        text = m["text"]
        if not text or not self.allowed(m):
            return
        if self.oncall and m.get("chat") == self.oncall:   # the on-call 1:1 answers flags only; it never wakes or commands the dog
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
        if not self.armed:
            if not wake:
                return
            self.armed_until = time.time() + self.listen_s
            self.armed_by = m["sender"]
            log("chat", "WAKE", by=hname(m["sender"]), phrase=wake[0], score=wake[1])
            self._event("chat.wake", m, phrase=wake[0], score=wake[1])
            if _flag("WTDD_WAKE_SHOW"):
                self.wake_show(m)
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
                self.say(f"ai:{m['guid']}", f"couldn't: {type(e).__name__}: {str(e)[:120]}")
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
        if isinstance(out, dict):
            self.say(f"res:{m['guid']}", out.get("text"), out.get("file"))
        else:
            self.say(f"res:{m['guid']}", str(out)[:300])

    def poll(self) -> int:
        HEARTBEAT.write_text(json.dumps({"t": time.time(), "guid": self.guid, "armed": self.armed, "armed_by": hname(self.armed_by) if self.armed_by else None,
                                         "dry": self.dry, "pending": PENDING.exists(), "last_rowid": self.last}))
        if self.armed_by and not self.armed:
            log("chat", "disarmed (timeout)", was=hname(self.armed_by))
            self.armed_by = None
        if PENDING.exists() and time.time() - json.loads(PENDING.read_text()).get("t", 0) > PENDING_WINDOW_S:
            PENDING.unlink(missing_ok=True)
            log("chat", "who dis: no answer in time, standing down")
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
        log("chat", f"listen guid={self.guid}", oncall=self.oncall or "none", from_rowid=self.last, listen_s=self.listen_s, dry=self.dry,
            wake_phrases=len(wake_phrases()), commands=len(command_list()))
        while True:
            self.poll()
            if once:
                break
            time.sleep(every)
