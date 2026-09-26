# 29-1 · the remote goes blank and GET /dog/state is a 500 in dry mode

**Symptom.** Two failures, both before any 29 code runs, in a worktree with no `.env` and no `dog_cal.json`:
- The remote draws for about a second and then the page is empty (the lights call fails, and a render reads `status.hue.filter` on `{error}`).
- `GET /dog/state` on a fresh API raises `AttributeError: 'DogSession' object has no attribute 'recheck'` (RED, `wtdd.dog.test_stream`: `test_no_dog_no_video` and `test_video_on_dog_state_with_fps_from_frame_deltas` end in `RemoteDisconnected`). The remote's 1 s `/dog/state` poll then never gets a `dog`, so the live view could never show.

**Root cause.** The page stores `{ error }` as `status` when `lights_status` fails. Two render expressions check only that `status` is truthy and then read `status.hue`, so React unmounts the tree. `DogSession.__init__` sets `self.recheck` only inside `if CAL_FILE.exists():`. `state()` reads it unconditionally, and `dog_cal.json` is a gitignored runtime file.

**Fix (verbatim, NIGHT-1-CONTRACTS section F patches 1, 1b and 3; the same bytes on every sibling branch).**
In `ui/index.html`, replace `const palette = status ? [...status.hue.filter(` with
`const palette = Array.isArray(status?.hue) ? [...status.hue.filter(`, and replace
``${status && html`<div class="panel"><h2>State · read back</h2>`` with
``${Array.isArray(status?.hue) && status.strip && html`<div class="panel"><h2>State · read back</h2>``.
In `wtdd/dog/session.py`, immediately before the line `        if CAL_FILE.exists():   # a calibration survives an API restart`, insert
`        self.recheck = False   # no calibration loaded; state() reads this before any connect`.
Patch 2 (`roomOf`) is not applied: 29's gate does not need it.

**Verify.** `UNITREE_ROBOT_IP= python -c "from wtdd.dog.session import DogSession; print(DogSession().state()['recheck'])"` prints `False`.
Start `python -m wtdd.api 7936` from the worktree and load the page in headless chromium with a `pageerror` listener.
It gives `{"root_children":1,"page_errors":[]}`, and the page still shows the lights card and "The eye" panel after 4 s.
