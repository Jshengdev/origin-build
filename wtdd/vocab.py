"""Modes are a vocabulary, not a detector (roadmap 20). WTDD_MODE (house | site) names one word list in ui/map.json
`vocab`; the vision prompt (wtdd/tools/dog_say.py see()) is told to name what it sees from that list when it fits, else
to say what it is. YOLO11n (wtdd/watch.py) stays the person and box detector, unchanged: this module never touches it.

  words(mode=None, m=None)    the mode's list; mode from WTDD_MODE (config.get, read at the point of use), m from
                              ui/map.json under config.ROOT, re-read on every call (POST /map edits it live)
  status(mode=None, m=None)   {mode, vocab, vocab_error} for GET /dog/state: a list missing on the map is the page's
                              yellow state (vocab None, vocab_error "vocab missing on the map (...)"), never a default
  sentence(mode=None)         "Name it from this list when it fits, else say what it is: w1, w2, ...": the prompt's line

Fail loud, never a default: an empty WTDD_MODE raises RuntimeError (config.get), a mode that is not house or site raises
ValueError naming it and both modes, a mode with no list on the map raises LookupError naming the mode and `vocab`.
Importing this module checks all three once and logs `[wtdd:vocab] mode <m>: <n> words`, so the API (which imports it
at startup) refuses to start on any of them. The list is `vocab`, separate from a decision `labels` list on the map.
UNVERIFIED on the real dog: that the vision model names a listed site thing in its sentence at a real stop (20.1)."""
from __future__ import annotations
import json

from . import config
from .ledger import log

MODES = ("house", "site")
SENTENCE = "name it from this list when it fits, else say what it is"


def load_map() -> dict:
    return json.loads((config.ROOT / "ui" / "map.json").read_text())


def words(mode: str | None = None, m: dict | None = None) -> list[str]:
    mode = mode or config.get("WTDD_MODE")
    if mode not in MODES:
        raise ValueError(f"WTDD_MODE={mode!r} is neither house nor site: set WTDD_MODE=house or WTDD_MODE=site in .env (see .env.example)")
    m = load_map() if m is None else m
    v = m.get("vocab")
    v = v.get(mode) if isinstance(v, dict) else None
    if not (isinstance(v, list) and v and all(isinstance(w, str) and w.strip() for w in v)):
        raise LookupError(f"WTDD_MODE={mode}: ui/map.json has no `vocab.{mode}` list; set it on the map (never a default)")
    return v


def status(mode: str | None = None, m: dict | None = None) -> dict:
    mode = mode or config.get("WTDD_MODE")
    try:
        return {"mode": mode, "vocab": words(mode, m), "vocab_error": None}
    except LookupError as e:   # the page's yellow state, named; a misnamed mode (ValueError) is not a state: it propagates
        return {"mode": mode, "vocab": None, "vocab_error": f"vocab missing on the map ({e})"}


def sentence(mode: str | None = None) -> str:
    return SENTENCE[0].upper() + SENTENCE[1:] + ": " + ", ".join(words(mode)) + "."


_mode = config.get("WTDD_MODE")
log("vocab", f"mode {_mode}: {len(words(_mode))} words")
