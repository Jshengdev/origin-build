"""A decision at every stop: what the agent has in hand at a stop (the detector's labels and largest box, the vision
sentence and its check on the detector, the stop's place on the map) becomes a short text state in words with no
digits, and the state becomes one typed decision {label, p, needs_person, model} from a fixed label list.

  state_for_stop(stop_name(i), seen, det, frame_wh)   six lines of words: where, what the detector saw, footprint and
                                                      height of its largest box, whether the two eyes agree, the
                                                      sentence, what is out of place
  decide(state, stop=i)                               {label, p, needs_person, model}; one `decided` ledger row
  at_stop(i, seen, det, frame_file)                   both, for dog_say.look_and_see: (state, decision | {error})
  ask_line(d)                                         the chat line when needs_person ("not sure: ...")
  python -m wtdd.decide --state FILE [--stop I]       prints the decision; JEV_LIVE=1 without JEV_API_KEY exits 2

Labels: ui/map.json `labels` (a non-empty list of distinct non-empty strings) or DEFAULT_LABELS; a malformed list is
a ValueError, never a silent default. needs_person = p < WTDD_DECIDE_THRESHOLD (default 0.7; not a float in [0, 1] is
a ValueError). Who decides: Jev (TypeSafe System One, a Choice question over the labels, POST JEV_URL with model
JEV_MODEL, default typesafe/jev-1.13, Bearer JEV_API_KEY) when JEV_API_KEY is set; otherwise the deterministic
DEMO_CACHE stub below, whose rows say cached=True, source="stub". p is the probability Jev gives the chosen label
(answers.stop.probabilities[choice]), not the reply's `confidence`, a separate number (0.75 beside a chosen 0.84 in
OpenRouter's example), so WTDD_DECIDE_THRESHOLD is tuned against the per-label probability. One
request, no retry, no fallback model, no fallback to the stub: a live failure is the decided row with ok=False, raised.
Row: tool "decided", agent "decide", app "stub" | "openrouter"; args {stop, shift_id, state_chars, threshold};
state_before {labels}; state_after = the returned decision; response_or_error = the stub's rule or Jev's raw reply.
Env, read at the point of use: JEV_API_KEY, JEV_MODEL, JEV_LIVE (CLI only), WTDD_DECIDE_THRESHOLD, WTDD_SHIFT.
UNVERIFIED: the live Jev call has not been run with a key. The body and the parse follow OpenRouter's own API reference,
"Submit a System One request" (POST https://openrouter.ai/api/v1/systemone, Bearer key; {model, state, questions} in;
{id, model, provider, answers: {<question>: {type, choice, confidence, probabilities}}, usage} out), and its Jev guide;
an unauthenticated POST to JEV_URL answers 401 where an unknown path answers 404 (checked 2026-09-26), so the route
exists. If the first live call 404s, the documented alternate path on the same OpenRouter key is
https://openrouter.ai/api/alpha/decisions (same body and reply; edit JEV_URL). Only a TypeSafe-native key, not an
OpenRouter one, needs JEV_URL = https://api.typesafe.ai/v1/systemone with JEV_MODEL=jev-latest."""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

from . import config, ledger

DEFAULT_LABELS = ["clear", "out_of_place", "hazard", "person"]
DESCRIBE = {"clear": "nothing to report at this stop",
            "out_of_place": "something left where it does not belong: a cup, a sock, a bag, clothes, trash",
            "hazard": "something that can hurt someone: a spill, a loose cable, a blocked way, an open door, glass, smoke",
            "person": "someone is in view"}
INSTRUCTIONS = "A robot dog on a night round is at a stop. What should it report here?"
JEV_URL = "https://openrouter.ai/api/v1/systemone"
JEV_APP = "openrouter"
JEV_TIMEOUT_S = 20.0
DEFAULT_MODEL = "typesafe/jev-1.13"
NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
           "seventeen eighteen nineteen twenty").split()
HAZARD = re.compile(r"\b(spill|spilled|wet|water|wire|wires|cable|cables|cord|cords|glass|smoke|fire|blocked|open door|ladder|hole)\b")
PERSON = re.compile(r"\b(someone|person)\b")


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


def threshold() -> float:
    v = config.maybe("WTDD_DECIDE_THRESHOLD") or "0.7"
    try:
        t = float(v)
    except ValueError:
        raise ValueError(f"WTDD_DECIDE_THRESHOLD={v!r} is not a number in [0, 1]") from None
    if not 0.0 <= t <= 1.0:
        raise ValueError(f"WTDD_DECIDE_THRESHOLD={v!r} is not in [0, 1]")
    return t


def shift_id() -> str:
    return config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")


def _word(n: int) -> str:
    return NUMBERS[n] if 0 <= n < len(NUMBERS) else "many"


def _dedigit(text: str) -> str:
    return re.sub(r"\d+", lambda m: _word(int(m.group())), text)


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
    # DEMO_CACHE: deterministic decision rules. What: the label and p come from words in the text state (spill, wet,
    # water, wire, cable, cord, glass, smoke, fire, blocked, open door, ladder, hole -> hazard 0.85, checked first;
    # someone or person -> person 0.9; an "out of place:" line naming anything -> out_of_place 0.85; else clear 0.8),
    # and "the eyes disagree" lowers p by 0.3 (two eyes disagreeing is the one uncertainty signal the shipped system
    # has). Why: no Jev key in a worktree, and the round must reach the ask beat dry. Live: set JEV_API_KEY in .env
    # (JEV_LIVE=1 on the CLI refuses the stub); decide() then POSTs the same state to JEV_URL with model JEV_MODEL and
    # the row says source=live.
    s = state.lower()
    if HAZARD.search(s):
        label, p = "hazard", 0.85
    elif PERSON.search(s):
        label, p = "person", 0.9
    elif re.search(r"^out of place: (?!nothing\.)", s, re.M):
        label, p = "out_of_place", 0.85
    else:
        label, p = "clear", 0.8
    disagree = "the eyes disagree" in s
    if disagree:
        p -= 0.3
    if label not in choices:
        raise ValueError(f"stub cannot decide among custom labels {choices}; set JEV_API_KEY for the live path")
    return label, p, "stub", f"stub: {label}; eyes {'disagree' if disagree else 'agree'}"


def _jev(state: str, choices: list[str]) -> tuple[str, float, str, str]:
    """One System One Choice request over the labels; the reply's chosen label and the probability it gives that label."""
    model = config.maybe("JEV_MODEL") or DEFAULT_MODEL
    body = {"state": state, "model": model,
            "questions": {"stop": {"type": "choice", "instructions": INSTRUCTIONS,
                                   "criteria": {c: DESCRIBE.get(c, c.replace("_", " ")) for c in choices}}}}
    resp = requests.post(JEV_URL, headers={"Authorization": f"Bearer {config.get('JEV_API_KEY')}", "Content-Type": "application/json"},
                         json=body, timeout=JEV_TIMEOUT_S)
    if resp.status_code != 200:
        raise RuntimeError(f"jev {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        answer = data["answers"]["stop"]
        label = str(answer["choice"])
        p = float(answer["probabilities"][label])
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"jev reply is not a System One choice ({type(e).__name__}: {e}): {resp.text[:300]!r}") from None
    return label, p, str(data.get("model") or model), resp.text


def decide(state: str, stop: int | None = None, labels: list[str] | None = None) -> dict:
    """{label, p, needs_person, model} for this state; one `decided` row, ok or raised. Never catches."""
    key = config.maybe("JEV_API_KEY")
    with ledger.step("decide", "decided", JEV_APP if key else "stub",
                     {"stop": stop, "shift_id": shift_id(), "state_chars": len(state), "threshold": None}) as r:
        if not key:
            r["cached"], r["source"] = True, "stub"
        choices = labels if labels is not None else _labels()
        r["state_before"] = {"labels": choices}
        thr = r["args"]["threshold"] = threshold()
        label, p, model, raw = _jev(state, choices) if key else _stub(state, choices)
        if label not in choices or not 0.0 <= p <= 1.0:
            raise ValueError(f"decision out of contract: label={label!r} (choices {choices}), p={p!r}")
        d = {"label": label, "p": round(p, 3), "needs_person": round(p, 3) < thr, "model": model}
        r["state_after"], r["response_or_error"] = d, raw[:600]
    ledger.log("decide", f"{label} p={d['p']}" + (" ASK a person" if d["needs_person"] else ""), stop=stop, model=model,
               threshold=thr, chars=len(state))
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
                           "args": {"stop": stop, "shift_id": shift_id(), "state_chars": 0, "threshold": None},
                           "state_before": None, "state_after": None, "ok": False,
                           "response_or_error": f"{type(e).__name__}: {e}", "latency_ms": round((time.perf_counter() - t0) * 1000),
                           **({} if key else {"cached": True, "source": "stub"})})
        ledger.log("decide", f"FAILED no decision at this stop: {err['error']}", stop=stop)
        return state, err


def ask_line(d: dict) -> str:
    """The one line posted with the photo when needs_person; begins "not sure:" (chat/listen.py OWN_OPENERS, colon included
    so a housemate's "not sure, ..." is still read as an answer)."""
    return f"not sure: {d['label'].replace('_', ' ')} at {int(round(d['p'] * 100))} percent. what is it?"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wtdd.decide", description="one typed decision from a text state")
    ap.add_argument("--state", required=True, help="a text file with the stop's state (words, no digits)")
    ap.add_argument("--stop", type=int, default=None, help="map stop index, for the row")
    a = ap.parse_args(argv)
    if (config.maybe("JEV_LIVE") or "0") not in ("0", "false", "no") and not config.maybe("JEV_API_KEY"):
        print(f"[wtdd:decide] JEV_API_KEY is not set: no live decision. Set it in {config.ROOT / '.env'} (see .env.example), "
              "or drop JEV_LIVE=1 to run the DEMO_CACHE stub.", file=sys.stderr)
        return 2
    try:
        d = decide(Path(a.state).read_text().strip(), stop=a.stop)
    except Exception as e:  # noqa: BLE001  (the decided row already has it, when it was reached)
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(d))
    if d["model"] == "stub":
        print("[wtdd:decide] stub decision (DEMO_CACHE), not live: set JEV_API_KEY for Jev", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
