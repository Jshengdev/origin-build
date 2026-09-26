# goals/roadmap.md · the contract for every roadmap item

One section per item from `context/origin-docs/ROADMAP.md`. Cut before building: goal, definition of done, a verifying command that can fail, routing, what it stacks on, what needs the dog, what it serves. An agent that finds a verifying command not runnable writes one that is, in the same shape, and says so in the PR body. Status is read from the branch and PR, not from this file.

Shared conventions for every item: branch `feat/<nn>-<slug>`; new tests under the package next to the code (`wtdd/<area>/test_<name>.py`), run with `python -m unittest`; fixtures under `wtdd/<area>/fixtures/` and small; every new external call logs one ledger row with latency; every new decision or refusal is a ledger row; the three existing test modules stay green; no new dependency without a line in the PR body saying why.

---

## 01 · occupancy accumulation
**Goal.** Every LiDAR window is accumulated into a persistent 2D occupancy grid in the odometry frame, and the remote draws the grid, not only the newest window.
**Definition of done.** `wtdd/dog/occupancy.py`: a grid (resolution and origin from the frame's own `resolution` and `origin`), an `update(points)` that increments occupied counts and a `walls(threshold)` that returns cells seen occupied at least N times; `GET /dog/lidar` gains `grid` (or a sibling `GET /dog/grid`) in map pixels through the same calibration as the dots; the remote draws it under the LiDAR dots; the grid persists across the session and can be saved to `ui/grid.json`. Synthetic frames (the same 128×128×38 LZ4 voxel shape `lidar.py` verified offline) drive the tests.
**Verifying command.** `python -m unittest wtdd.dog.test_occupancy` (fails before: module absent). Plus `python -m wtdd.dog.occupancy --replay wtdd/dog/fixtures/voxel_frames.npz --png /tmp/grid.png` writes a PNG with walls where the synthetic frames put them.
**Routing.** Fable cuts the grid contract and reviews; Opus builds; Sonnet pulls `lidar.py`, `nav.py`, the driver's voxel layout, and the remote's LiDAR drawing code.
**Stacks on.** main.
**Needs the dog.** The first live frame's `frame_id`, its z range, and whether the voxel `origin` moves with the dog or stays absolute (all marked UNVERIFIED in `lidar.py`).
**Serves.** Demo beats 2.1, 2.2; the substrate for 05b, 06, 07.

## 02 · a decision at every stop
**Goal.** At each stop the agent produces a typed decision with a probability from a text state, logs it, and asks a person when the confidence is below a threshold, before any action.
**Definition of done.** `wtdd/decide.py`: `state_for_stop(...)` builds a short text state (footprint and height in words, detector labels, the vision sentence, the stop name; no raw numbers); `decide(state)` returns `{label, p, needs_person, model}` from a fixed label list (read from `ui/map.json` `labels` or a default list) via Jev when `JEV_API_KEY` is set and via a deterministic stub otherwise (labeled `# DEMO_CACHE:` naming the live path); a `decided` ledger row per stop; when `needs_person`, the existing `chat.post` sends the photo and one line and the round waits for a reply through the existing question flow; the local person-in-frame stop stays local and precedes any model call.
**Verifying command.** `python -m unittest wtdd.test_decide` (stub path, threshold behavior, ledger row shape, state contains no digits) and `JEV_LIVE=1 python -m wtdd.decide --state wtdd/fixtures/stop_state.txt` prints a live typed decision when a key is present, exits 2 with a clear message when it is not.
**Routing.** Fable owns the label list and the threshold rule; Opus builds; Sonnet fetches the TypeSafe API shape (`POST /v1/systemone`, Choice / Noul) and the OpenRouter route `typesafe/jev-1.13`.
**Stacks on.** main (footprint words come from 07 later; until then from the detector box size).
**Needs the dog.** Nothing for the stub path; a live Jev key for the live path.
**Serves.** Demo beats 2.2, 2.3; drill rows 3, 6, 12.

## 03 · one named person, the acknowledgement, the signature
**Goal.** Flags go to one named person, their reply time is a logged field, and a signed-record row closes the shift.
**Definition of done.** `config.py` gains `ON_CALL` (a name and a handle) and the escalation path posts to that handle, not the group; `chat.correction` / verdict rows gain `acked_ms` measured from the post's confirmed time to the reply's row; a new tool `record.sign` writes `record.signed {by, at, shift_id}` and marks the shift closed; `python -m wtdd numbers` reports acked_ms per shift and whether the shift is signed.
**Verifying command.** `python -m unittest wtdd.chat.test_oncall` (routing to the on-call handle, acked_ms computed from fixture rows, signed row shape, a second sign refused). The existing never-twice tests stay green.
**Routing.** Fable; Opus; Sonnet pulls `chat/` listener and post code and the ledger schema.
**Stacks on.** main.
**Needs the dog.** Nothing. Needs a real person's handle on Sunday.
**Serves.** Demo beats 2.3, 2.4, 3.2; drill rows 6, 8.

## 04 · no-go zones as refusals
**Goal.** A zone drawn on the map blocks the planner and the follower; a route that touches one is refused, and the refusal is a ledger row sourced to the map.
**Definition of done.** `ui/map.json` `zones` gains a `nogo: true` kind drawable on the remote; `plan.py` treats no-go cells as blocked; `field.walk` / `dog.follow` refuse a waypoint inside a zone before moving and write `route.refused {zone, waypoint, source: "map"}`; the remote shades the zone.
**Verifying command.** `python -m unittest wtdd.test_nogo` (a planned path never enters a zone; a taught route through a zone is refused with the row). `python -m wtdd plan_path from=… to=…` around a fixture zone prints a detour.
**Routing.** Fable; Opus; Sonnet pulls `plan.py`, `field.py`, the map schema note in `ui/map.json`.
**Stacks on.** main (06 will re-base the planner on the grid; the zone semantics stay).
**Needs the dog.** One walk toward a drawn zone to see the refusal live.
**Serves.** Demo beats 1.3, 2.6; drill row 15.

## 05a · which odometry drifts less
**Goal.** The two poses the dog publishes are recorded side by side on a replay and the follower can be switched to either by config.
**Definition of done.** `dog/session.py` records both `LF_SPORT_MOD_STATE` position and `rt/utlidar/robot_pose` into `pose.sample` rows with a source field; `config.POSE_SOURCE` selects the follower's source; `python -m wtdd.dog.drift --ledger <file>` reports end-position error per source against the taught route end.
**Verifying command.** `python -m unittest wtdd.dog.test_drift` on fixture rows with planted drift; the report names the lower-drift source.
**Routing.** Fable; Opus; Sonnet pulls `session.py`, `nav.py`, the driver topics.
**Stacks on.** main.
**Needs the dog.** Three walks of the taught route per source. This item is mostly measurement; the code is small.
**Serves.** Demo beat 2.1's honest line; the drift number a judge may ask for.

## 05b · scan-to-map re-correction
**Goal.** Each new LiDAR window is aligned to the accumulated grid and the pose is corrected by the best small offset, every window, with jumps capped.
**Definition of done.** `dog/localize.py`: correlative scan matching over a small window of dx, dy, dθ around the odometry pose, scoring occupied-cell overlap, numpy only; the correction is applied to the believed pose and logged as `pose.corrected {dx, dy, dtheta, score}`; a cap rejects implausible jumps; the manual drag still works and still logs.
**Verifying command.** `python -m unittest wtdd.dog.test_localize` (a synthetic map, a synthetic window shifted by a known offset, recovered within tolerance; a jump above the cap rejected).
**Routing.** Fable; Opus; Sonnet pulls `occupancy.py` (01) and `nav.py`.
**Stacks on.** 01.
**Needs the dog.** A live run to tune the search window and the cap.
**Serves.** Demo beat 2.1; the "constant re-correction" Johnny asked for.

## 06 · the planner over the grid
**Goal.** A* runs over the occupancy grid with obstacles inflated by the dog's radius and no-go zones as hard blocks, and replans when a new blob blocks the path.
**Definition of done.** `plan.py` accepts the grid from 01 as the cost map (rooms remain a fallback), inflates obstacles, blocks zones (04's semantics), and exposes `replan()`; the follower calls `replan()` when the next waypoint is now occupied; rows: `plan.route`, `plan.replanned`.
**Verifying command.** `python -m unittest wtdd.test_plan_grid` (a path avoids inflated walls and zones; inserting a blob mid-route triggers a replan that reaches the goal).
**Routing.** Fable; Opus; Sonnet pulls `plan.py`, `occupancy.py`.
**Stacks on.** 01 (and reads zones in 04's format; if 04 is not merged, use the same schema and note it).
**Needs the dog.** One live reroute.
**Serves.** Demo beat 2.6.

## 07 · the live object layer
**Goal.** Objects seen by the live camera are placed on the map at the nearest LiDAR blob along their bearing, labeled with a probability, a drafted one-line message and a thumbnail, and decay to stale when the scan stops seeing them.
**Definition of done.** `dog/objects.py`: bearing from a detector box's horizontal position and the camera field of view (a calibration constant in config, marked UNVERIFIED until measured); nearest occupied blob along the bearing in the grid; an object store `{id, label, p, message, thumb, pos_px, first_seen, last_seen}`; the vision one-liner drafted on a cadence for new or changed objects only; label and p from 02's `decide` (stub path if 02 is absent); decay after N windows unseen; `GET /dog/objects`; the remote draws pins with label, p and thumbnail and fades stale ones.
**Verifying command.** `python -m unittest wtdd.dog.test_objects` (bearing math, nearest-blob association on a synthetic grid, decay, message drafted once per new object). A replay run writes `/tmp/objects.png`.
**Routing.** Fable owns the association rule and the cadence; Opus builds; Sonnet pulls `watch.py`, the vision call in `llm.py`, `occupancy.py`.
**Stacks on.** 01.
**Needs the dog.** The camera field of view measured; a live walk to see mis-association and drift.
**Serves.** Demo beat 2.2, the visual awe; drill rows 3, 12. The model never draws geometry.

## 08 · the agent's two rows: the roster and the quote
**Goal.** From the map, the agent produces the night's roster and a quote, both as ledger rows and both on the remote.
**Definition of done.** `wtdd/schedule.py`: `roster(map)` assigns each stop to the body, each fixed camera to its zone, and names the on-call person from config, as `schedule.shift`; `quote(map, price_per_stop_night)` produces `quote.night {stops, nights, price, guard_shift_ref}` with the guard-shift comparison read from config (a number Johnny enters, cited); the remote shows both under the queue.
**Verifying command.** `python -m unittest wtdd.test_schedule` (roster covers every stop exactly once; quote arithmetic; rows shaped).
**Routing.** Fable; Opus; Sonnet pulls the map schema and the remote's status panel.
**Stacks on.** main.
**Needs the dog.** Nothing. Needs the interview's guard-shift number.
**Serves.** Demo beats 1.2, 3.3; drill row 13.

## 09 · a fixed camera in the same queue
**Goal.** A laptop camera streams to the server, its detections enter the same decision path and the same thread, and the remote shows it as one more eye.
**Definition of done.** `wtdd/cam/`: a small client that posts frames (or detections) to `POST /cam/<id>/frame`; the server runs the existing detector; a person box at a fixed camera raises the same `needs_person` path as a stop; the remote shows the camera's last frame and boxes; rows: `cam.frame`, `cam.detect`.
**Verifying command.** `python -m unittest wtdd.cam.test_cam` (a fixture frame posted, detected, a row written, the person path armed).
**Routing.** Fable; Opus; Sonnet pulls `watch.py`, `api.py`.
**Stacks on.** main.
**Needs the dog.** Nothing. Needs one laptop on the site network.
**Serves.** Demo beat 1.2 (the gate); drill row 11.

## 10 · the morning page
**Goal.** One command renders the shift's record from the ledger: stops, flags, escalations with who resolved what and when, refusals, the map with labeled shapes, and the signature line.
**Definition of done.** `python -m wtdd.record --shift <id> --html /tmp/record.html` reads only the ledger and the map; every number on the page is computed; the page shows "unsigned" until a `record.signed` row exists; nothing is typed by hand.
**Verifying command.** `python -m unittest wtdd.test_record` (fixture ledger → page with the expected counts; an unsigned shift renders "unsigned"; a signed one shows the name and time).
**Routing.** Fable; Opus; Sonnet pulls `numbers.py`, the ledger schema, `record.sign` (03).
**Stacks on.** 03.
**Needs the dog.** Nothing.
**Serves.** Demo beats 3.1, 3.2; drill rows 2, 5, 12.

## 11 · evals for the new round, seen to fail first
**Goal.** Three new eval scenarios grade the new path from device state: the round with decisions, the escalation with a reply, the refusal at a no-go; plus the failure-shot check that a corrected label re-pins.
**Definition of done.** `evals.py` gains scenarios `decide`, `escalate`, `refuse`, `correct`; each graded pass / fail / unsafe from rows and read-backs, never from the agent's report; `unsafe` includes a model call that preceded a local stop; the README's trials table regenerates with the new rows.
**Verifying command.** `python -m wtdd.evals --scenario decide` (and each of the others) runs dry on fixtures; each was committed failing first (the PR shows both runs).
**Routing.** Fable; Opus; Sonnet pulls `evals.py` and the existing scenario shapes.
**Stacks on.** 02 and 03 and 04 (three parents; base on 03, note the others; final integration is Johnny's merge order).
**Needs the dog.** The live runs for the trials table.
**Serves.** The reliability section of the README; drill rows 6, 8, 15.

## 12 · a channel adapter beyond iMessage
**Goal.** The on-call person can be on SMS or WhatsApp; the same post, question and reply flow works through an adapter, with iMessage unchanged.
**Definition of done.** `chat/adapters/`: an interface (post text, post photo, read replies since) with the iMessage implementation moved behind it and one second implementation (Twilio SMS or WhatsApp Cloud API) behind env keys, stubbed when keys are absent and labeled `# DEMO_CACHE:`; the never-twice gate applies to every adapter.
**Verifying command.** `python -m unittest wtdd.chat.test_adapters` (the stub adapter passes the same never-twice and read-back tests as iMessage).
**Routing.** Fable; Opus; Sonnet fetches the chosen API's send and webhook docs.
**Stacks on.** 03.
**Needs the dog.** Nothing. Needs the real person's phone type on Sunday.
**Serves.** Drill row 8's honest line.

## Not goals for agents
13 · one real night on a permitted site, the numbers regenerated, the video, the deck: Johnny's, on Sunday. Frontier exploration, tag anchors, a second body, the fleet: slide six.
