# 09-2 · a package's tests set WTDD_LEDGER too late for the package's own __init__

**Symptom.** `python -m unittest wtdd.cam.test_cam` failed with
`FileNotFoundError: ... /T/wtdd-cam-test-.../cams/lap1.jpg` right after a 200, and the worktree root gained a
`ledger.jsonl` holding 16 `cam.*` fixture rows (`source: "live"`) and a `cams/` directory. In the real checkout those
rows would have gone into the real ledger.

**Root cause.** test_cam.py sets `WTDD_LEDGER`, `WTDD_MEMORY` and `WTDD_CAMS` at the top of its module body, before its
own `from wtdd import ...` (the wtdd/chat/test_chat.py pattern). But unittest imports the package `wtdd.cam`
(`wtdd/cam/__init__.py`) before it runs `wtdd/cam/test_cam.py`'s body. The first build of `__init__.py` imported
`wtdd.ledger` at module level (directly, and again through `wtdd.watch`), and `ledger.py` binds `LEDGER` from
`WTDD_LEDGER` once at import; it also computed `CAMS` from `WTDD_CAMS` at import. Both read the environment before the
test had set it. wtdd/chat/test_chat.py never hit this because `wtdd/chat/__init__.py` imports nothing.

**Fix (verbatim, wtdd/cam/__init__.py).**
```python
from ..config import ROOT, maybe
# wtdd.ledger, and wtdd.watch which imports it, are imported inside the functions: unittest imports this package before
# test_cam's body points WTDD_LEDGER at a scratch file, and the ledger binds its path at import (docs/gotchas/09-2-*).
```
```python
def cams() -> Path:
    """<repo>/cams/, or WTDD_CAMS (plain process env, read per call for the same import-order reason)."""
    return Path(os.environ.get("WTDD_CAMS") or ROOT / "cams").expanduser().absolute()
```
and `from ..ledger import log, step` / `from ..watch import MODEL` (or `COOLDOWN_S`) as the first lines of `ingest()`
and `person_seen()`. The same rule applies to any package that keeps its tests inside itself: its `__init__.py` must not
import `wtdd.ledger` (or anything that does) at module level.

**Verify.** `python -m unittest wtdd.cam.test_cam` passes, and afterwards `ls` at the worktree root shows no
`ledger.jsonl` and no `cams/`.
