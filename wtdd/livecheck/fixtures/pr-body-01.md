<!-- fixture for wtdd/livecheck/test_livecheck.py: the shape of PR #5's body (feat/01-occupancy), `**Bold**` headings. The Needs the dog
section is copied verbatim from that PR; every other section is cut down to a stub so the parser meets numbered lines outside
the section. Nothing here is a result. -->
**Goal**

01 · occupancy accumulation. Every LiDAR window is accumulated into a persistent 2D occupancy grid in the odometry frame, and the remote draws the grid, not only the newest window.

**Makes true**

Beat 1.2 (the room appears). Drill rows 2 and 5.

**Verified**

(cut from this fixture)

**Needs the dog**

Run everything from `/Users/johnnysheng/code/origin-build` itself with `feat/01-occupancy` checked out there (a worktree API cannot reach the dog: body.py's venv check compares `sys.prefix` to `ROOT/.venv`). Connect, then `POST /dog/lidar {on: true}`, then read stderr's `[wtdd:dog] first lidar frame frame_id=...` line.

1. `frame_id` must be `odom`. The grid refuses any later frame whose `frame_id` differs, so a mismatch shows as a rising `cb_errors` on `GET /dog/lidar` and `GET /dog/grid`, paired with `WARN lidar frame callback failed err=ValueError: frame_id ...` on stderr.
2. Read `z_layers` on the same first-frame line to find where the floor sits. If the floor falls inside the band, tune `lidar.Z_MIN` / `Z_MAX` (0.10..1.00 today, a guess).
3. Walk about 3 m and watch `GET /dog/grid`. If `extent_m` grows while a wall's cells stay put, the window `origin` moves with the dog as the fixture assumes. If the grid smears into a streak, the points are body-relative and this item's frame assumption is wrong: STOP, do not tune; the fix is a different transform, not a threshold.
4. `GET /dog/lidar`: `grid_frames` should track `n`, and `cb_errors` should stay 0. A non-zero `cb_errors` names its refusal (frame_id, resolution or `MAX_SIDE`) in the WARN line.
5. The per-frame accumulate cost on the driver's dispatcher is the `ms=` on the `[wtdd:dog] grid frames=... ms=...` line, logged every 100th frame. It must stay well under the frame period (5-10 Hz); on the 3-4k-voxel fixture it is 1-5 ms and a real frame may hold ten times the voxels.
6. `POST /dog/grid {save: true}` must write one `dog.grid_save` row with `cal_at` set. Restart the API: the page should draw the saved grid with `source` `ui/grid.json`, through the calibration saved with it.
7. After a power cycle the `[wtdd:dog] WARN grid kept across the reconnect` line must appear. Then `POST /dog/grid {clear: true, why: "power cycle"}` (one `dog.grid_clear` row), and a fresh grid should start on the next frame (`[wtdd:dog] grid started`).
8. Stays UNVERIFIED because this code cannot see it: wire bytes 8-11 (the driver strips them before any callback).

Nothing in this PR ran on hardware.

**Shared files touched**

1. `wtdd/api.py`: the GET /dog/grid and POST /dog/grid blocks.
2. `ui/index.html`: the grid layer.

**Cut**

(cut from this fixture)

**Deviations**

1. (cut from this fixture)
