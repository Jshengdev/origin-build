"""A decision at every stop: what the agent has in hand at a stop (the detector's labels and largest box, the vision
sentence and its check on the detector, the stop's place on the map) becomes a short text state in words with no
digits, and the state becomes one typed decision {label, p, needs_person, model, action} from a fixed label list. The
action comes from a table in code a person can read, never from the model. The on-call person's reply to the question
that action asked is read the same way, typed: {meaning, p, named, p_named, action}.

  state_for_stop(stop_name(i), seen, det, frame_wh)   six lines of words: where, what the detector saw, footprint and
                                                      height of its largest box, whether the two eyes agree, the
                                                      sentence, what is out of place
  decide(state, stop=i)                               {label, p, needs_person, model, action}; one `decided` ledger row
  at_stop(i, seen, det, frame_file)                   both, for dog_say.look_and_see: (state, decision | {error})
  policy(label, p, thr, table)                        {action, rule}: the table below
  choose(name, state, criteria, instructions)         the one System One Choice call (decide and read_reply use it)
  ask_line(d) / heads_up_line(d, stop)                the chat line: "not sure: ..." / what the person on call gets
  read_reply(asked, text)                             {meaning, p, named, p_named, action}; one `reply.decided` row
  rules()                                             what the page's Rules panel prints (GET /rules)
  python -m wtdd.decide --state FILE [--stop I]       prints the decision and its rule
  python -m wtdd.decide --reply TEXT --asked Q        prints the reading; JEV_LIVE=1 without JEV_API_KEY exits 2 (both)

Labels: ui/map.json `labels` (a non-empty list of distinct non-empty strings) or DEFAULT_LABELS, the one site list
(clear, material_stack, opening, hazard, person, other); a malformed list is a ValueError, never a silent default.
needs_person = p < WTDD_DECIDE_THRESHOLD (default 0.7; not a float in [0, 1] is a ValueError), unchanged from 02.
The table (Jev names; code chooses): ui/map.json `policy` = {"escalate": [labels]}, else DEFAULT_POLICY (opening, hazard,
person), read at call time. A label in `escalate` goes to the person on call at any p (action escalate, rule
escalate:<label>); any other label below the threshold asks (ask, ask:p<thr); else continue. A malformed `policy` (not
a dict with exactly the key escalate, holding distinct labels of the map) is a ValueError on the decided row, never the
default. A scratch probe on this Mac, 2026-09-26 (docs/evidence/night-2/jev-probe-2026-09-26.jsonl), handed Jev an
action list and it sent an open cover to dispatch_alarm at 0.68: which labels reach a person is this table, not the model.
Who decides: Jev (TypeSafe System One, a Choice question over the labels, POST JEV_URL with model JEV_MODEL, default
typesafe/jev-1.13, Bearer JEV_API_KEY) when JEV_API_KEY is set; otherwise the deterministic DEMO_CACHE stub below,
whose rows say cached=True, source="stub". p is the probability Jev gives the chosen label
(answers.stop.probabilities[choice]), not the reply's `confidence`, a separate number (0.75 beside a chosen 0.84 in
OpenRouter's example), so WTDD_DECIDE_THRESHOLD is tuned against the per-label probability. One
request, no retry, no fallback model, no fallback to the stub: a live failure is the decided row with ok=False, raised.
Row: tool "decided", agent "decide", app "stub" | "openrouter"; args {stop, shift_id, state_chars, threshold, rule,
policy_source: map | default}; state_before {labels}; state_after = the returned decision; response_or_error = the
stub's rule or Jev's raw reply.
The reply: the state is "the dog asked: <question>\\nthey replied: <text>" and nothing else (numbers in words). Live, one
request with two Choice questions: meaning over MEANINGS and named over the site labels + not_said; p and p_named are the
probabilities of the chosen options. action = ACTION[meaning] (alarm, stand_down, close, hold), or reask when the
meaning is unclear or p is below WTDD_REPLY_THRESHOLD (default 0.8, validated like the decide threshold). Without a key
the shipped IDK / CORRECTION regexes (wtdd/chat/listen.py) plus two word lists read it (DEMO_CACHE, _reply_stub), and
a yes or no to the re-ask is read against the re-ask first (no -> stranger, yes -> standing_down). Row:
tool "reply.decided" (never "decided": 11's unsafe() counts that as a stop's model call), agent central, app stub |
openrouter; args {question, text, shift_id, threshold, model, plus the listener's trigger, chat, guid, from};
state_before {meanings, labels}; state_after the reading; a live failure is the row with ok=False, raised, never the regex.
Env, read at the point of use: JEV_API_KEY, JEV_MODEL, JEV_LIVE (CLI only), WTDD_DECIDE_THRESHOLD, WTDD_REPLY_THRESHOLD,
WTDD_SHIFT.
UNVERIFIED: this code has not made a live Jev call with a key (the probe above was a separate script, 22 calls, all
200). The body and the parse follow OpenRouter's own API reference,
"Submit a System One request" (POST https://openrouter.ai/api/v1/systemone, Bearer key; {model, state, questions} in;
{id, model, provider, answers: {<question>: {type, choice, confidence, probabilities}}, usage} out), and its Jev guide;
an unauthenticated POST to JEV_URL answers 401 where an unknown path answers 404 (checked 2026-09-26), so the route
exists. If the first live call 404s, the documented alternate path on the same OpenRouter key is
https://openrouter.ai/api/alpha/decisions (same body and reply; edit JEV_URL). Only a TypeSafe-native key, not an
OpenRouter one, needs JEV_URL = https://api.typesafe.ai/v1/systemone with JEV_MODEL=jev-latest. Every probability is
raw and uncalibrated (no labeled replies yet)."""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

from . import config, ledger

DEFAULT_LABELS = ["clear", "material_stack", "opening", "hazard", "person", "other"]   # the one site list, as on ui/map.json
DESCRIBE = {"clear": "nothing to report at this stop",
            "material_stack": "material stored on purpose: pallets, stacked boards, wrapped bundles",
            "opening": "a hole, trench, missing floor cover or unguarded edge",
            "hazard": "something that can hurt someone: a spill, a cable across the way, glass, smoke, a blocked exit",
            "person": "someone is in view",
            "other": "something worth a look that none of the others names",
            "out_of_place": "something left where it does not belong: a cup, a sock, a bag, clothes, trash"}   # a house map may list it
DEFAULT_POLICY = {"escalate": ["opening", "hazard", "person"]}   # to the person on call at any p; ui/map.json `policy` overrides it
UNCONFIRMED_BELOW = 0.9   # a pin from the threshold up to this says "unconfirmed" (the 60-80% band measured 54% accurate, Jev-Calibration)
MEANINGS = ["acknowledged", "handled", "standing_down", "stranger", "unclear"]
MEANING = {"acknowledged": "they are on their way or looking: on it, omw, checking",
           "handled": "they say it is dealt with: fixed, covered, cleared, done",
           "standing_down": "they say it is fine or known: a friend, expected, a tarp not a hole",
           "stranger": "they do not know who or what it is, or it is not theirs",
           "unclear": "the reply does not answer the question"}
NOT_SAID = "the reply does not say what it is"
ACTION = {"stranger": "alarm", "standing_down": "stand_down", "handled": "close", "acknowledged": "hold", "unclear": "reask"}
INSTRUCTIONS = "A robot dog on a night round is at a stop. What should it report here?"
REPLY_INSTRUCTIONS = "A robot dog asked the person on call about something it saw. What does their reply mean?"
NAMED_INSTRUCTIONS = "A robot dog asked the person on call about something it saw. What does their reply say it is?"
JEV_URL = "https://openrouter.ai/api/v1/systemone"
JEV_APP = "openrouter"
JEV_TIMEOUT_S = 20.0
DEFAULT_MODEL = "typesafe/jev-1.13"
NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
           "seventeen eighteen nineteen twenty").split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
OPENING = re.compile(r"\b(opening|hole|holes|trench|cover is off|cover off|missing floor|missing cover|unguarded edge)\b")
HAZARD = re.compile(r"\b(spill|spilled|wet|water|wire|wires|cable|cables|cord|cords|glass|smoke|fire|blocked|open door|ladder)\b")
PERSON = re.compile(r"\b(someone|person)\b")
MATERIAL = re.compile(r"\b(pallet|pallets|stacked|boards|lumber|bundle|bundles|wrapped)\b")
HANDLED = re.compile(r"\b(handled|done|fixed|back on|cleared|covered|taken care of)\b")
ACK = re.compile(r"\b(on it|omw|on my way|looking|checking|coming)\b")
REASK_NO = re.compile(r"^(no|nope|nah)\b")      # the answer to listen.REASK, "do you know them? yes or no", only
REASK_YES = re.compile(r"^(yes|yeah|yep|yup)\b")


def labels(map_path: Path | None = None) -> list[str]:
    """The fixed choices: ui/map.json `labels` when present, else DEFAULT_LABELS (logged)."""
    from .field import MAP
    f = Path(map_path or MAP)
    m = json.loads(f.read_text())
    if "labels" not in m:
        ledger.log("decide", "labels: default list", labels=",".join(DEFAULT_LABELS))
        return list(DEFAULT_LABELS)
    got = m["labels"]
    if not isinstance(got, list) or not got or not all(isinstance(x, str) and x.strip() for x in got) or len(set(got)) != len(got):
        raise ValueError(f"{f}: `labels` must be a non-empty list of distinct non-empty strings, got {got!r}")
    return list(got)


_labels = labels   # decide() takes a `labels` argument; this is the map reader it falls back to


def _table() -> tuple[dict, str]:
    """(table, "map" | "default"): ui/map.json `policy`, read at call time, else DEFAULT_POLICY (logged)."""
    from .field import MAP
    m = json.loads(Path(MAP).read_text())
    if "policy" not in m:
        ledger.log("decide", "policy: default table", escalate=",".join(DEFAULT_POLICY["escalate"]))
        return {"escalate": list(DEFAULT_POLICY["escalate"])}, "default"
    got, names = m["policy"], labels(MAP)
    esc = got.get("escalate") if isinstance(got, dict) and set(got) == {"escalate"} else None
    if not isinstance(esc, list) or not all(isinstance(x, str) and x in names for x in esc) or len(set(esc)) != len(esc):
        raise ValueError(f"{MAP}: `policy` must be {{\"escalate\": [distinct labels of {names}]}}, got {got!r}")
    return {"escalate": list(esc)}, "map"


def policy(label: str, p: float, thr: float, table: dict) -> dict:
    """{action, rule}: a label in table["escalate"] goes to the person on call at any p; any other below the threshold
    asks (round(p, 3), as needs_person); else continue."""
    if label in table["escalate"]:
        return {"action": "escalate", "rule": f"escalate:{label}"}
    if round(p, 3) < thr:
        return {"action": "ask", "rule": f"ask:p<{thr}"}
    return {"action": "continue", "rule": "continue"}


def _unit_env(key: str, default: str) -> float:
    v = config.maybe(key) or default
    try:
        t = float(v)
    except ValueError:
        raise ValueError(f"{key}={v!r} is not a number in [0, 1]") from None
    if not 0.0 <= t <= 1.0:
        raise ValueError(f"{key}={v!r} is not in [0, 1]")
    return t


def threshold() -> float:
    return _unit_env("WTDD_DECIDE_THRESHOLD", "0.7")


def reply_threshold() -> float:
    return _unit_env("WTDD_REPLY_THRESHOLD", "0.8")


def shift_id() -> str:
    return config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")


def _word(n: int) -> str:
    return NUMBERS[n] if 0 <= n < len(NUMBERS) else "many"


def _words(n: int) -> str:
    """0..100 in words, "ninety eight" (a space, no hyphen), "one hundred"; above that "many"."""
    if 0 <= n <= 20:
        return NUMBERS[n]
    if 20 < n < 100:
        return TENS[n // 10 - 2] + (f" {NUMBERS[n % 10]}" if n % 10 else "")
    return "one hundred" if n == 100 else "many"


def _dedigit(text: str, word=_word) -> str:
    return re.sub(r"\d+", lambda m: word(int(m.group())), text)


def _period(s: str) -> str:
    s = s.strip()
    return s if s.endswith((".", "!", "?")) else s + "."


def stop_name(stop: int | None, map_path: Path | None = None) -> str:
    """'stop two, in the kitchen': the stop's 1-based place in map.json `stops` and the room its path point sits in."""
    if stop is None:
        return "a stop off the route"
    from .field import MAP, room_of
    m = json.loads(Path(map_path or MAP).read_text())
    stops, path = m.get("stops") or [], m.get("path") or []
    name = f"stop {_word(stops.index(stop) + 1)}" if stop in stops else "an unlisted stop"
    room = room_of(tuple(path[stop]), m.get("rooms") or []) if 0 <= stop < len(path) else None
    return _dedigit(f"{name}, " + (f"in the {room}" if room else "in an unknown room"))


def state_for_stop(stop_name: str, seen: dict, det: dict | None, frame_wh: tuple[int, int] | None = None) -> str:
    """Six lines of words, no digits. `seen` is dog_say.see()'s reply, `det` is dog_say.boxed()'s (or {error})."""
    ran = bool(det) and "error" not in det
    classes = (det or {}).get("classes") or {}
    if not ran:
        saw = "nothing (the detector did not run)"
    else:
        saw = ", ".join(f"{k} ({_word(v)})" if v > 1 else k for k, v in classes.items()) or "nothing"
    boxes = (det or {}).get("boxes") or []
    fp = ht = "unknown"
    if boxes and frame_wh:
        w, h = frame_wh
        x0, y0, x1, y1 = max(boxes, key=lambda b: (b["xyxy"][2] - b["xyxy"][0]) * (b["xyxy"][3] - b["xyxy"][1]))["xyxy"]
        area, tall = (x1 - x0) * (y1 - y0) / (w * h), (y1 - y0) / h
        fp = "small" if area < 0.05 else "medium" if area < 0.25 else "large"
        ht = "low" if tall < 0.25 else "mid" if tall < 0.6 else "tall"
    check = str(seen.get("detector_check") or "agree")
    eyes = "the eyes were not compared." if not ran else \
        "the eyes agree." if check.strip().lower() == "agree" else f"the eyes disagree: {_period(check)}"
    items = seen.get("out_of_place") or []
    lines = [f"at {stop_name}.", f"the detector saw: {saw}.", f"footprint: {fp}. height: {ht}.", eyes,
             f"it sees: {_period(seen['text'])}", "out of place: " + (", ".join(items) if items else "nothing") + "."]
    state = "\n".join(_dedigit(x) for x in lines)
    ledger.log("decide", ("WARN " if not classes else "") + "state", chars=len(state), classes=sum(classes.values()),
               detector="ran" if ran else "did not run", footprint=fp, height=ht)
    return state


def _stub(state: str, choices: list[str]) -> tuple[str, float, str, str]:
    # DEMO_CACHE: deterministic decision rules. What: the label and p come from words in the text state, first rule
    # that hits: opening, hole(s), trench, cover (is) off, missing floor/cover, unguarded edge -> opening 0.9; spill,
    # wet, water, wire, cable, cord, glass, smoke, fire, blocked, open door, ladder -> hazard 0.85; someone or person ->
    # person 0.9; pallet(s), stacked, boards, lumber, bundle(s), wrapped -> material_stack 0.85; an "out of place:" line
    # naming anything -> out_of_place when the map lists it, else other, 0.85; else clear 0.8. "the eyes disagree"
    # lowers p by 0.3 (two eyes disagreeing is the one uncertainty signal the shipped system has). Why: no Jev key in a
    # worktree, and the round must reach the escalate and ask beats dry. Live: set JEV_API_KEY in .env (JEV_LIVE=1 on
    # the CLI refuses the stub); decide() then POSTs the same state to JEV_URL with model JEV_MODEL and the row says
    # source=live.
    s = state.lower()
    if OPENING.search(s):
        label, p = "opening", 0.9
    elif HAZARD.search(s):
        label, p = "hazard", 0.85
    elif PERSON.search(s):
        label, p = "person", 0.9
    elif MATERIAL.search(s):
        label, p = "material_stack", 0.85
    elif re.search(r"^out of place: (?!nothing\.)", s, re.M):
        label, p = ("out_of_place" if "out_of_place" in choices else "other"), 0.85
    else:
        label, p = "clear", 0.8
    disagree = "the eyes disagree" in s
    if disagree:
        p -= 0.3
    if label not in choices:
        raise ValueError(f"stub cannot decide among custom labels {choices}; set JEV_API_KEY for the live path")
    return label, p, "stub", f"stub: {label}; eyes {'disagree' if disagree else 'agree'}"


def _criteria(names: list[str]) -> dict[str, str]:
    """Each label with its rubric sentence (a map's own label without one is offered as its words)."""
    return {n: DESCRIBE.get(n, n.replace("_", " ")) for n in names}


def choose(name: str, state: str, criteria: dict, instructions: str,
           also: dict[str, tuple[dict, str]] | None = None) -> tuple[dict[str, tuple[str, float]], str, str]:
    """One System One request: the Choice question `name` (criteria: option -> rubric sentence), plus each `also`
    question {name2: (criteria2, instructions2)} in the same request, `name` first. Returns ({question: (choice, p)},
    model, raw reply); p is the probability the reply gives the chosen option. A non-200, an unparseable reply or a
    missing answer is a RuntimeError, a choice that was not offered a ValueError. No retry, no fallback."""
    model = config.maybe("JEV_MODEL") or DEFAULT_MODEL
    qs = {q: {"type": "choice", "instructions": ins, "criteria": crit} for q, (crit, ins) in {name: (criteria, instructions), **(also or {})}.items()}
    resp = requests.post(JEV_URL, headers={"Authorization": f"Bearer {config.get('JEV_API_KEY')}", "Content-Type": "application/json"},
                         json={"state": state, "model": model, "questions": qs}, timeout=JEV_TIMEOUT_S)
    if resp.status_code != 200:
        raise RuntimeError(f"jev {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        got = {}
        for q in qs:
            answer = data["answers"][q]
            choice = str(answer["choice"])
            got[q] = (choice, float(answer["probabilities"][choice]))
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"jev reply is not a System One choice ({type(e).__name__}: {e}): {resp.text[:300]!r}") from None
    for q, (choice, _) in got.items():
        if choice not in qs[q]["criteria"]:
            raise ValueError(f"jev chose {choice!r} for {q}, not one of {list(qs[q]['criteria'])}")
    return got, str(data.get("model") or model), resp.text


def decide(state: str, stop: int | None = None, labels: list[str] | None = None) -> dict:
    """{label, p, needs_person, model, action} for this state; one `decided` row, ok or raised. Never catches."""
    key = config.maybe("JEV_API_KEY")
    with ledger.step("decide", "decided", JEV_APP if key else "stub",
                     {"stop": stop, "shift_id": shift_id(), "state_chars": len(state), "threshold": None, "rule": None,
                      "policy_source": None}) as r:
        if not key:
            r["cached"], r["source"] = True, "stub"
        choices = labels if labels is not None else _labels()
        r["state_before"] = {"labels": choices}
        thr = r["args"]["threshold"] = threshold()
        table, r["args"]["policy_source"] = _table()   # a malformed map table fails here, on this row
        if key:
            got, model, raw = choose("stop", state, _criteria(choices), INSTRUCTIONS)
            label, p = got["stop"]
        else:
            label, p, model, raw = _stub(state, choices)
        if label not in choices or not 0.0 <= p <= 1.0:
            raise ValueError(f"decision out of contract: label={label!r} (choices {choices}), p={p!r}")
        pol = policy(label, p, thr, table)
        d = {"label": label, "p": round(p, 3), "needs_person": round(p, 3) < thr, "model": model, "action": pol["action"]}
        r["args"]["rule"] = pol["rule"]
        r["state_after"], r["response_or_error"] = d, raw[:600]
    ledger.log("decide", f"{label} p={d['p']} {d['action'].upper()}", rule=pol["rule"], stop=stop, model=model,
               threshold=thr, table=r["args"]["policy_source"], chars=len(state))
    return d


def _frame_wh(file: str) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(file) as im:
            return im.size
    except Exception as e:  # noqa: BLE001  (a stated absence: the footprint then reads "unknown")
        ledger.log("decide", f"WARN frame size unreadable, footprint unknown: {type(e).__name__}: {str(e)[:80]}")
        return None


def at_stop(stop: int | None, seen: dict, det: dict | None, frame_file: str) -> tuple[str | None, dict]:
    """dog_say.look_and_see's one call, after boxed() and see(): (state, decision), or (state or None, {error}) when
    the state or the decision failed, logged loud here. Every stop leaves exactly one decided row: decide()'s own, ok
    or failed, or, when the state failed before decide() was reached, a failed one appended here."""
    state, t0 = None, time.perf_counter()
    try:
        state = state_for_stop(stop_name(stop), seen, det, _frame_wh(frame_file))
        return state, decide(state, stop=stop)
    except Exception as e:  # noqa: BLE001  (recorded on a decided row, logged, and returned as {error})
        err = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
        if state is None:   # decide() never opened its step: this stop's receipt is written here
            key = config.maybe("JEV_API_KEY")
            ledger.append({"step": "decided", "agent": "decide", "tool": "decided", "app": JEV_APP if key else "stub",
                           "args": {"stop": stop, "shift_id": shift_id(), "state_chars": 0, "threshold": None, "rule": None,
                                    "policy_source": None},
                           "state_before": None, "state_after": None, "ok": False,
                           "response_or_error": f"{type(e).__name__}: {e}", "latency_ms": round((time.perf_counter() - t0) * 1000),
                           **({} if key else {"cached": True, "source": "stub"})})
        ledger.log("decide", f"FAILED no decision at this stop: {err['error']}", stop=stop)
        return state, err


def ask_line(d: dict) -> str:
    """The one line posted with the photo when needs_person; begins "not sure:" (chat/listen.py OWN_OPENERS, colon included
    so a housemate's "not sure, ..." is still read as an answer)."""
    return f"not sure: {d['label'].replace('_', ' ')} at {int(round(d['p'] * 100))} percent. what is it?"


def heads_up_line(d: dict, stop: int | None) -> str:
    """What the person on call gets with the photo on action escalate: a person keeps "who dis?!" (03 and 11 read it);
    below the threshold 02's ask line (11's grade_decide reads "not sure:"); else "heads up: opening at ninety eight
    percent at stop two. what is it?" (the stop as stop_name words it, without the room). No digits."""
    if d["label"] == "person":
        return "who dis?!"
    if d["needs_person"]:
        return ask_line(d)
    return (f"heads up: {d['label'].replace('_', ' ')} at {_words(int(round(d['p'] * 100)))} percent at "
            f"{stop_name(stop).split(',')[0]}. what is it?")


def rules() -> dict:
    """What the page's Rules panel prints (GET /rules), so the page computes nothing: the site labels, the table and where
    it came from, both thresholds in force, the band where a pin adds "unconfirmed", and one line per rule. Raises on a
    malformed table or threshold (the API answers 500 with it)."""
    thr, (table, source) = threshold(), _table()
    esc = table["escalate"]
    return {"labels": labels(), "escalate": esc, "source": source, "threshold": thr, "reply_threshold": reply_threshold(),
            "unconfirmed": [thr, UNCONFIRMED_BELOW],
            "lines": [(" · ".join(esc) or "no label") + " → the person on call, any p", f"below {thr} → ask", "else continue"]}


def _reply_stub(asked: str, text: str) -> tuple[str, float, str, float, str]:
    # DEMO_CACHE: deterministic reply rules. What: the meaning and p come from the reply's words, first rule that hits,
    # on triggers.normalize(text). When `asked` is the re-ask (listen.REASK, "do you know them? yes or no"), first: no,
    # nope, nah at the start -> stranger 0.9 (rule "REASK no"); yes, yeah, yep, yup at the start -> standing_down 0.85
    # (rule "REASK yes"), so a bare "no" is not 02's CORRECTION. Then, for any question: the shipped IDK regex
    # (wtdd/chat/listen.py: idk, dunno, no idea, not me, nope, who, stranger, ...) -> stranger 0.9; handled, done,
    # fixed, back on, cleared, covered, taken care of -> handled 0.85; on it, omw, on my way, looking, checking, coming
    # -> acknowledged 0.85; the shipped CORRECTION regex (its, thats, no, not, actually, ... at the start) ->
    # standing_down 0.85; else unclear 0.5. named is always not_said at 0.5: the stub never names the thing. Why: no Jev
    # key in a worktree, and the verdict beats (alarm, stand down, hold, close, re-ask) must run dry. Live: set
    # JEV_API_KEY in .env (JEV_LIVE=1 on the CLI refuses the stub); read_reply() then asks Jev both questions in one
    # request and the row says source=live. Never the fallback of a failed live call.
    from .chat.listen import CORRECTION, IDK, REASK   # here, not at the top: listen imports this module inside its functions
    from .chat.triggers import normalize
    t = normalize(text)
    if asked == REASK and REASK_NO.match(t):
        meaning, p, rule = "stranger", 0.9, "REASK no"
    elif asked == REASK and REASK_YES.match(t):
        meaning, p, rule = "standing_down", 0.85, "REASK yes"
    elif IDK.search(t):
        meaning, p, rule = "stranger", 0.9, "IDK"
    elif HANDLED.search(t):
        meaning, p, rule = "handled", 0.85, "HANDLED"
    elif ACK.search(t):
        meaning, p, rule = "acknowledged", 0.85, "ACK"
    elif CORRECTION.match(t):
        meaning, p, rule = "standing_down", 0.85, "CORRECTION"
    else:
        meaning, p, rule = "unclear", 0.5, "no rule"
    return meaning, p, "not_said", 0.5, f"stub: {meaning} ({rule})"


def read_reply(asked: str, text: str, **row) -> dict:
    """{meaning, p, named, p_named, action} for the reply `text` to the question `asked`; one `reply.decided` row, ok or
    raised (row: the listener's trigger, chat, guid, from). Never catches; a live failure is never the stub."""
    key = config.maybe("JEV_API_KEY")
    with ledger.step("central", "reply.decided", JEV_APP if key else "stub",
                     {"question": asked, "text": text[:200], "shift_id": shift_id(), "threshold": None, "model": None, **row}) as r:
        if not key:
            r["cached"], r["source"] = True, "stub"
        site = labels()
        names = site + ["not_said"]
        r["state_before"] = {"meanings": MEANINGS, "labels": names}
        thr = r["args"]["threshold"] = reply_threshold()
        state = _dedigit(f"the dog asked: {asked}\nthey replied: {text}", _words)
        if key:
            got, model, raw = choose("meaning", state, MEANING, REPLY_INSTRUCTIONS,
                                     also={"named": ({**_criteria(site), "not_said": NOT_SAID}, NAMED_INSTRUCTIONS)})
            (meaning, p), (named, p_named) = got["meaning"], got["named"]
        else:
            meaning, p, named, p_named, raw = _reply_stub(asked, text)
            model = "stub"
        if meaning not in MEANINGS or named not in names or not (0.0 <= p <= 1.0 and 0.0 <= p_named <= 1.0):
            raise ValueError(f"reading out of contract: meaning={meaning!r} p={p!r} named={named!r} p_named={p_named!r}")
        action = "reask" if meaning == "unclear" or round(p, 3) < thr else ACTION[meaning]
        d = {"meaning": meaning, "p": round(p, 3), "named": named, "p_named": round(p_named, 3), "action": action}
        r["state_after"], r["response_or_error"], r["args"]["model"] = d, raw[:600], model
    ledger.log("decide", f"reply {meaning} p={d['p']} {action.upper()}", named=named, model=model, threshold=thr,
               chars=len(text), trigger=row.get("trigger") or "")
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wtdd.decide", description="one typed decision from a text state, or one typed reading of a reply")
    one = ap.add_mutually_exclusive_group(required=True)
    one.add_argument("--state", help="a text file with the stop's state (words, no digits)")
    one.add_argument("--reply", help="the on-call person's reply, read as one typed meaning")
    ap.add_argument("--asked", help="with --reply: the question the reply answers")
    ap.add_argument("--stop", type=int, default=None, help="map stop index, for the row")
    a = ap.parse_args(argv)
    if a.reply is not None and not a.asked:
        ap.error("--reply needs --asked (the question the reply answers)")
    if (config.maybe("JEV_LIVE") or "0") not in ("0", "false", "no") and not config.maybe("JEV_API_KEY"):
        print(f"[wtdd:decide] JEV_API_KEY is not set: no live {'reading' if a.reply is not None else 'decision'}. Set it in "
              f"{config.ROOT / '.env'} (see .env.example), or drop JEV_LIVE=1 to run the DEMO_CACHE stub.", file=sys.stderr)
        return 2
    try:
        if a.reply is not None:
            out = read_reply(a.asked, a.reply)
        else:
            out = decide(Path(a.state).read_text().strip(), stop=a.stop)
        row = ledger.rows(1)[0]   # the rule and the model as the row recorded them
        if a.reply is None:
            out = {**out, "rule": row["args"]["rule"]}
    except Exception as e:  # noqa: BLE001  (the row already has it, when it was reached)
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out))
    if (out.get("model") or row["args"].get("model")) == "stub":
        print("[wtdd:decide] stub (DEMO_CACHE), not live: set JEV_API_KEY for Jev", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
