<!-- fixture for wtdd/livecheck/test_livecheck.py: the shape of PR #15's body (feat/26-timeline-marks), `**Bold**` headings and
the steps numbered inside bold (`- **<item>.<k>** text`). The Needs the dog section is copied verbatim from that PR; every other
section is cut down to a stub so the parser meets numbered lines outside the section. Nothing here is a result. -->
**Goal**

26 · Every row has a tick under the receipts and, when it names a place, a mark on the map that lights when the tick is tapped; the marks and the ages are computed server-side from the row and the calibration, the page computes nothing, and a row with `ok=false` is a red tick and a red mark.

**Verified**

1. (cut from this fixture)

**Needs the dog**

Run all of these from `/Users/johnnysheng/code/origin-build` itself, never from a worktree: a worktree API can never reach the dog. Check out `feat/26-timeline-marks` there, start on a fresh ledger (confirm-first step 1), then start the API as usual.

- **26.1** After the first live `dog.calibrate`, open the remote on the tablet and tap that calibrate's tick with a finger. Confirm three things:
  1. The pinned line reads `pinned · dog.calibrate · <age> s · <m> m` for that row, and the ts in the tick's title matches the receipts list.
  2. The blue arrow runs from the believed pose to the placed point.
  3. The metres agree with a tape measured between those two spots on the floor.
- **26.2** During one walk, confirm that the `dog.follow` tick appears within one 5 s poll. Then confirm that a finger tap rings where the walk ended (or gave up), with an arrow from where it started.
- **26.3** Send one command that gets refused. Confirm the tick is red and, if the row is placed, that the map mark and the pinned ring are red, with `FAILED` in the pinned line.
- **26.4 (a known limit)** On the tablet, check whether a finger can pick one specific tick. Each tick is about 1.25 px wide. Rows within about 2 s of each other in one lane stack, and the last one drawn wins. On a live n=2000 window, most ticks will sit under a finger's width, and one frequent tool can fill the whole timeline. Confirm that the rows you mean to show in the demo (the calibrate and the FAILED follow) can each be tapped on their own. Decide whether the demo needs a narrower window (a smaller `n` in `useMarks`).
- **26.5 (load)** `GET /marks` parses the whole ledger every 5 s per open page, on top of `/ledger`'s parse every 2 s. The whole ledger is needed so each row gets the calibration in force when it was written. `serve()` took 18 ms on a 32,858-row ledger in the reviewer's dry replay. Watch `ms=` on the `[wtdd:marks] served` line against the live ledger.

**Shared files touched**

1. (cut from this fixture)
**2 · (cut from this fixture)**

**Cut**

1. (cut from this fixture)
