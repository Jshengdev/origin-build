<!-- fixture for wtdd/livecheck/test_livecheck.py: the shape of PR #19's body (feat/21-route-the-map), `## ` headings, a numbered
list of prechecks (1.-4.) and then the goal's steps numbered inside bold with the item and a letter suffix (`- **21.1: text**`,
`- **21.1b: text**`), so the same k is drafted twice. The Needs the dog section is copied verbatim from that PR; every other
section is cut down to a stub so the parser meets numbered lines outside the section. Nothing here is a result. -->
## Goal
21 · A route is planned over the session grid from the drop point through the stops the person taps, each leg `plan_path` over the grid with confirmed no-go zones hard-blocked, and the planned route becomes the map's path with its stops; the taught route stays the fallback; a leg with no route is a visible FAILED leg and nothing is saved.

## Verified
1. (cut from this fixture)
**2 · (cut from this fixture)**

## Needs the dog
Run everything from the repo checkout `/Users/johnnysheng/code/origin-build` itself, never a worktree (body.py refuses to reach the dog from one). The checks that come first, in order:
1. The voxel origin under a pure turn (live 14 1, 1.2's origin test). If the walls rotate or the grid smears into a rosette, STOP: 21 waits with the rest of WOW 1.
2. 01 LIVE 1–3: the session grid fills from real frames, and a wall's cells stay put while extent_m grows.
3. 06's dry check and LIVE 2–3: `plan_path` prints cost_map grid, grid_source session, walls > 0.
4. One confirmed no-go zone on the dog's map (04's draw and save, `nogo: true` in `ui/map.json`).

Then the goal's three steps. Start `.venv/bin/python -m wtdd.api`, POST /dog/lidar {on: true}, let the grid fill, and drag the orange dog to calibrate. Do not plant `ui/grid.json`.
- **21.1: three taps on the session grid at the house.** With the dog calibrated, the start is its believed pose, so three taps make three legs and three stops (the dry fixture's "2 stops" is the no-pose case).
  - Confirm the status line reads `start: the dog's believed pose` and `grid` with no `(ui/grid.json)`.
  - Confirm one `plan.route` row per leg (args.leg/legs) and one `plan.multistop` ok row with `args.grid_source: "session"`, `cached: false`, `source: "live"`.
  - Confirm the polyline bends around the confirmed zone.
  - Press `save route`. Confirm one `plan.saved` ok row with `state_before` holding the previous path_pts and stops, and `state_after.prev = "ui/map.prev.json"`, and that the map reloads with the route as its path and stops.
  - Walk it (`walk the path` / POST /dog/follow). Watch the body, not the line: the body must stay clear of the zone's edge (04 LIVE 5's rule).
  - If a waypoint falls outside the drawn rooms, the save is refused, naming the point (`plan.saved` ok=false, nothing written). That is main's rule until 14's `WTDD_NO_PLAN` is beneath.
- **21.1b: run this early** (the round-3 reviewer's live risk). A believed pose within 40 px (about 0.37 m) of any LiDAR wall cell, including a person standing beside the dog, fails leg 1 loud with no snap: `leg 1 of n … not on walkable floor`, and a red dashed line from the pose to tap 1. If that is what you see, drive the dog a step into open floor and plan again.
- **21.2: one tap behind the zone.** Confirm a detour is drawn: that leg bends around the zone, its `plan.route` row names the zone in `args.nogo`, and the stderr line reads `nogo=1` or more.
- **21.3: one tap inside a wall the LiDAR saw.** Confirm the red dashed `no route · leg k of n`, `route FAILED: …` in red, and the `plan.multistop` ok=false row with `args.failed_leg` in the receipts panel. `save route` stays disabled and `ui/map.json` is unchanged.
- **Afterwards:** `restore saved route` still brings back the taught route.

What the first live run must confirm: the rows say session/live; the route follows the walls the LiDAR actually saw; a failed leg is visible and saves nothing; and the saved route is either walked clear of the zone or refused by name.

## Shared files touched
1. (cut from this fixture)
- **21.9: (cut from this fixture)**

## Cut
1. (cut from this fixture)
