<!-- fixture for wtdd/livecheck/test_livecheck.py: the shape of PR #4's body (feat/04-nogo), `## ` headings and the numbered list
right under the heading. The Needs the dog section is copied verbatim from that PR; every other section is cut down to a stub so the
parser meets numbered lines outside the section. Nothing here is a result. -->
## Goal
04 · A zone drawn on the map blocks the planner and the follower; a route that touches one is refused, and the refusal is a ledger row sourced to the map.

## Verified
1. (cut from this fixture)

## Needs the dog
Nothing in this PR ran on the dog; the follower's refusal was exercised with a `DogSession` that never connected. Run these in `/Users/johnnysheng/code/origin-build` itself, not a worktree (a worktree API cannot reach the dog):
1. Check out `feat/04-nogo`, start the API (`.venv/bin/python -m wtdd.api`), open the remote, calibrate ("dog is here…").
2. Press "restore saved route" (or record a route) first: the tracked `ui/map.json` path still has the 526 px jump (contracts F.4, never patched), and until the path can be run both "save" and the walk button's own save are refused with a 400 before any zone is looked at.
3. Press "draw no-go", click the corners of a zone across the recorded route, "close zone", "save". Confirm `ui/map.json` now has `{name: "nogo-1", label: "no-go 1", nogo: true, poly: [...]}` in `zones` and the remote shades it red with a dashed edge.
4. Press "▶ walk the path" (and, separately, `POST /dog/follow`). Expected: the page's FAILED line `ValueError: route refused: … no-go zone nogo-1 (drawn on the map)`; `python -m wtdd ledger_tail n=3` shows exactly one `route.refused` row (`agent` dog, `source` map, `args.zone`, `args.waypoint`, `args.index`, `args.shift_id`); no `dog.follow` row and no `dog.probe` row; the dog never moved.
5. `python -m wtdd plan_path from=<the dog's map point> to=<a point beyond the zone> save=true`, then walk that route. This is the first live check that `HALF_WIDTH` = 4 cells (about 40 px, 0.37 m) keeps the real body clear of the drawn edge. Watch the body, not the line.
6. UNVERIFIED until then: the whole refusal path on the body, and the clearance on the real floor.

## Shared files touched
1. (cut from this fixture)
2. (cut from this fixture)

## Cut
1. (cut from this fixture)
