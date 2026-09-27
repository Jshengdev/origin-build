# 18-5 · a failure on the camera hook's thread reaches nobody

**Symptom.** With a half-written `ui/grid.json` (`{"cells": `) and no LiDAR grid in the session,
`python -m wtdd dispatch cam=lap1 dry=true` printed a JSONDecodeError and exited 1 with zero ledger rows.
`dispatch.json` still held the previous run's dry `decided`, an end phase the page never marks stale, so the remote
showed the old success. In the API the same failure on a real sighting left only a thread traceback on stderr, with no
row, no page and nothing in the thread.

**Root cause.** `run()` caught its named refusals, the decision step, the ask's post and the walk. Everything else
escaped: `_body()`'s `occupancy.Grid.load`, `camera()` on a map it could not parse, `_publish`, `PENDING.write_text`,
and the tool's `why_unseen()`, which parses the whole ledger. In 09 the camera's POST ran the ask inline, so an
exception came back in the POST's 500 reply. Item 18 moved the hand-off onto a daemon thread so the POST returns at
once, and that removed the only caller who could have seen the exception.

**Fix (verbatim, `wtdd/dispatch.py` run()).** A last net around the whole run sends any failure that nothing above
has told through the same refusal, once. Failures that are already told are marked with `_told()` and pass through
unchanged:
```python
    except Exception as e:  # noqa: BLE001  (the last net: a failure no step above has told, e.g. an unreadable ui/grid.json)
        if getattr(e, "told", False):
            raise
        refuse(f"{type(e).__name__}: {e}", frame=False)
    finally:
        _lock.release()
```
In `wtdd/tools/dispatch.py`, an exception from `why_unseen()` becomes
`unseen = f"FAILED to read the camera's sighting: {type(e).__name__}: {e}"`, which `run()` refuses even dry.
In `wtdd/cam/__init__.py`, a failed hand-off appends one FAILED `dispatch.decided` (agent cam) naming the boxed frame.

**Verify.** Run `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_dispatch_safety -v`
alone. `AnyFailure` covers both the corrupt grid (in the API and dry) and `why_unseen` raising: each gives exactly one
FAILED row, the failed page and one text-only "couldn't dispatch". Also run `python -m unittest wtdd.cam.test_cam -v`,
whose Person check `test_a_sighting_that_never_reached_dispatch_is_a_failed_row` covers the hand-off. When you move
work onto a thread, ask who now sees its exceptions. If the answer is nobody, the work must write its own row.
