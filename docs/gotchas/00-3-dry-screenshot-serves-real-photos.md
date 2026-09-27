# 00-3 · a dry screenshot can show a real photo from ~/Pictures/wtdd

**Symptom.** A headless screenshot of the dry API with a fresh planted watch.json shows, in "The eye · what it sees",
whatever `~/Pictures/wtdd/watch.jpg` holds on this Mac: the newest frame the detector wrote on a real run, a room of
the house. The same happens to the thumbnails when a fixture ledger carries a look row (`/pictures/look-tilt.jpg`,
`/pictures/look-down.jpg`). A committed evidence PNG would carry a real photo that the fixture never produced.

**Root cause.** `wtdd/api.py` serves `/pictures/<name>` from `Path("~/Pictures/wtdd").expanduser()`, resolved at
import from HOME; the page shows `/pictures/watch.jpg` whenever GET /watch says the file is younger than 3 s, and the
look thumbnails whenever the ledger has those rows. A worktree shares HOME with the live system.

**Fix (verbatim, how 00's screenshots were taken; no code change).** Start the dry API with HOME pointed at a scratch
dir that holds only the fixture's synthetic frames, and delete the planted watch.json afterwards:

```
HOME=/tmp/night1/00/home WTDD_LEDGER=/tmp/night1/00/halted.jsonl /Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.api 7920
```

with `/tmp/night1/00/home/Pictures/wtdd/watch.jpg` and `.../stop-person-<sha12>.jpg` written from
`wtdd.fixtures.evals.make_halt.frame_jpeg()`. Nothing is written into the real `~/Pictures/wtdd`.

**Verify.** `docs/evidence/night-2/00-remote.png` shows the synthetic frame (a dark field, one red box, the words
"synthetic frame · fixture-00 · no camera, no detector") in the eye panel and as the STOPPED thumbnail, and
`ls ~/Pictures/wtdd | grep stop-person` prints nothing.
