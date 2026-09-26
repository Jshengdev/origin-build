# 23-1 · on 09's base the page's save never reaches the API, then 09's map refuses it

**Symptom.** A dry API on port 7930 serving feat/09-fixed-cam from a worktree. Headless: load the remote, wait 3 s, click
`save`. No POST /map is sent (`POST /map responses: []`, no `POST /map` line on the API's stderr) and the page records
`page errors: ["ReferenceError: roomOf is not defined"]`. With that fixed, the same click is sent and refused:
`POST /map responses: [400]`, the page shows `not saved: points 11 and 12 are 526 px apart (over 300): a jump, delete
the stray one`, and the API logs `[wtdd:api] map NOT saved problems=1`. A `place camera` click can never be saved
while either holds.

**Root cause.** Two dry-mode bugs from main that 09 carries (night-1 contracts, section F). F.2: `withRooms()`, which
both `save` and `walk the path` call before POST /map, calls `roomOf`, and `roomOf` is defined nowhere in
ui/index.html. The throw happens inside the click handler, so the page stays up and says nothing. F.4: ui/map.json's
own path has two consecutive points 526 px apart (MAX_STEP_PX is 300), so `check_path` refuses any save that sends
that path. ui/route-saved.json (23 points, max gap 75 px) is the runnable taught route.

**Fix (verbatim).** F.2, the contracts' patch 2: the same bytes as feat/04-nogo's line, so the two hunks merge clean. In ui/index.html, right after
the line `const inside = ...`, insert exactly:
```
const roomOf = (p, rooms) => ((rooms || []).find(r => inside(p, r.poly)) || {}).name || null;   // the room a map point sits in, for the page's save; field.py recomputes it anyway
```
F.4 is not patched (the contracts forbid it). In dry mode, click `restore saved route` (POST /map/restore) once before
any save. That rewrites the tracked ui/map.json, so afterwards run `git checkout -- ui/map.json` and
`rm -f ui/map.prev.json`, and never commit the result.

**Verify.** With the patch, start `python -m wtdd.api 7930` from the worktree. Click `restore saved route`, reload,
click `place camera`, click the map, click `save`: the page shows `saved`, and GET /map holds the camera's new pt with
the zone the API computed (docs/evidence/night-2/23-remote.png). Before the patch, the same clicks leave the API's
stderr without a single `POST /map` line.
