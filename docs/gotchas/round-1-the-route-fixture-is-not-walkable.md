# round-1 · wtdd/fixtures/map_route.json cannot be walked whole: field.walk refuses its path

**Symptom.** Found building fix/round-safety on 2026-09-27. A dry `wake_show` over a scratch copy of `wtdd/fixtures/map_route.json` never read `/dog/state` once; the round went straight to its end look and posted `dog done (couldn't walk the path: ValueError: the path cannot be run: points 11 and 12 are 526 px apart (over 300): a jump, delete the stray one)`.

**Root cause.** The fixture's 48-dot path has a 526 px gap between dots 11 and 12 (1-based). `field.check_path` refuses any step over `MAX_STEP_PX` (300) before the walk starts, so every walk of that map fails in its first line. The planner and the follower tests never call `field.walk`, so nothing had tripped on it.

**Fix (verbatim).** In `wtdd/chat/test_round.py`, the scratch map keeps the first 11 dots:
```
_m = json.loads((Path(field.__file__).parent / "fixtures" / "map_route.json").read_text())
PATH = _m["path"] = _m["path"][:11]   # its first 11 dots: the fixture's 12th is a 526 px jump, which check_path refuses
MAP.write_text(json.dumps(_m))
```
The fixture itself is unchanged (other tests read it as it is).

**Verify.** `python -c "import json; from wtdd.field import check_path; m=json.load(open('wtdd/fixtures/map_route.json')); print(check_path(m['path'], m['rooms']), check_path(m['path'][:11], m['rooms']))"` prints the jump, then `[]`; `python -m unittest wtdd.chat.test_round` walks the trimmed map.
