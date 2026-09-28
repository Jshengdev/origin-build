# The API contract

Every route `wtdd/api.py` serves on main (read at 4665be9, checked against 681501b), what it takes and what it answers. It is read from the handler code and the
functions each route calls (`wtdd/dog/session.py`, `scout_zones.py`, `objects.py`, `occupancy.py`, `floorplan.py`,
`record.py`, `shift.py`, `decide.py`), then checked against a dry API (no dog) with curl. The shapes are today's, including
their inconsistencies: a client builds against these, and a change to one is a change to this file.

## Where it listens
- `python -m wtdd.api` serves `config.API`, `http://127.0.0.1:<WTDD_API_PORT, default 7788>/`, the address every
  caller in `wtdd/` uses. `python -m wtdd.api <port>` overrides the port for the server alone.
- **It binds 127.0.0.1 only.** Nothing off this Mac reaches it; there is no auth.
- Every answer carries `Access-Control-Allow-Origin: *`. `OPTIONS` on any path is 204 with
  `Allow-Headers: Content-Type` and `Allow-Methods: GET, POST, OPTIONS`.
- JSON answers are `Content-Type: application/json`. POST bodies are JSON; an empty body is `{}`.
- One stderr line per request (`[wtdd:api] "GET /x HTTP/1.1" 200 -`). Reads write no ledger row; the rows a POST writes
  are named below.

## Envelopes
**Success.** A GET answers its body with no `ok` key. A POST answers `{ok: true, ...}`, except the two named below.

**The three failure envelopes:**

| Method | Status | Body |
|---|---|---|
| GET | 500 (404, 503 where named) | `{error: "<Type>: <msg>"}` |
| POST | 400, 404, 409 or 500 | `{ok: false, error: "<Type>: <msg>"}` |
| POST /dog/floorplan, no wall found | **200** | `{ok: false, why, threshold, frames, cells, grid_source, ...}` |

**The exceptions to them:**
- Five GET layers add their empty keys to the error, so a page can draw nothing without a guard:
  - `/dog/grid`: `{n: 0, cells_px: [], error}`
  - `/dog/objects`: `{n: 0, objects: [], error}`
  - `/dog/floorplan`: `{segments_px: [], error}`
  - `/dog/blobs`: `{labels: [], error}`
  - `/dog/scout`: `{n: 0, proposals: [], failed: [], error}`
- POST `/tools/<name>` adds the call: `{ok: false, tool, args, error}`.
- POST `/dog/blobs` has no `ok` key at all: success is `{labelled, skipped, failed, labels}` and failure is 500 `{error}`.
- Some errors are a plain sentence with no `<Type>: ` prefix:
  - POST `/map`'s 400 and 409 (`not saved: ...`);
  - POST `/dog/scout`'s 400, 404 and 409;
  - GET `/record`'s 404 (`no shift <id>: no row is stamped with it; shifts: ...`);
  - every 404 for an unknown path or picture.
- An unknown path is 404: `{error: "no <path>"}` on GET (the static fallback), `{error: "not found"}` on POST.
- **Anything a route does not catch** is 500 in its method's envelope, with one `[wtdd:api] <METHOD> <path> FAILED`
  stderr line (B9): a bad `?n=`, a missing or corrupt `ui/map.json`, a body that is not JSON. It is never a dropped connection.

## Facts that trip a client
- **GET /ledger returns a bare array**, not an object. `n` defaults to 20. `n=0` returns every row. A negative `n`
  returns all but the first |n|.
- **`p` means two things.**
  - In `/dog/state` (`.map.p`, `.follow.p`) and in POST `/dog/calibrate`'s body, it is a map point `[x, y]` in map pixels.
  - In `/dog/objects` (`objects[].p`), `/dog/blobs` (`labels[].p`) and `/dog/scout` (`proposals[].p`, `zones[].p`), it is a probability from 0 to 1.
- **GET /chat reports `age_s`** (seconds, one decimal). `/watch` and `/dog/lidar` report `age_ms`.
- **Timestamps are local time with no zone.** Ledger `ts` and every other `ts`, `first_seen`, `last_seen` and `at` are
  `YYYY-MM-DDTHH:MM:SS` from `time.strftime`. The exceptions:
  - `/evals`'s `written` and `rows[].ran` are `YYYY-MM-DD HH:MM`.
  - `/watch`'s `t` and `/dog/state`'s `follow.started` are epoch seconds.
- **GET /field returns `{}` when idle**, not `{walking: false}`. Idle means no `field.json`, or one older than 2 s.
- **The scout starts only when something GETs `/dog/objects`.**
  - The first GET `/dog/objects` in the API process starts the `objects` thread. It ticks every 0.25 s from then on, and
    each tick feeds the scout.
  - Until that GET, `/dog/scout` reads an idle store: no dog, page or poll of `/dog/scout` starts it.
  - With `WTDD_OBJECTS` set, `/dog/objects` serves the file and the thread never starts.
- **GET /dog/frame.jpg connects the dog.** It takes the dog's one WebRTC slot if nothing holds it. So do POST
  `/dog/drive`, `/dog/calibrate`, `/dog/follow`, `/dog/avoid`, `/dog/record {on: true}` and `/dog/lidar {on: true}`. Every
  other GET is a read that never connects.
- **POST /dog/scout needs `by`**, a person's name, for confirm and for dismiss (400 without it).
- **Confirm is dead on the live path.** The feed puts a hazard straight onto `ui/map.json` as an auto zone
  (`by: "auto"`, `scout_zones.py` 431-436). Only a test writes an open proposal, so live `proposals` is always `[]` and a
  confirm is 404. What works live is dismissing an auto zone, `id` = its map name (`nogo-<n>`).
- **The record** is GET `/record?shift=<id>` (default: the run in force) and GET `/record/shifts`. An unknown shift is a
  404 naming the shifts that exist, never an empty record.
- **Five GETs never answer a phone number or an email** (B10): `/chat`, `/evals`, `/record`, `/record/shifts` and
  `/ledger`. Every string value in them, errors included, has a `+<7-15 digits>` handle or an email read `a member`.
  Keys and numbers are untouched, the ledger file keeps the raw values, and the other routes are not redacted.
- `_version` is `int(mtime)` of `ui/map.json`. Send it back on POST `/map` and `/dog/scout`, or the write is a 409.

## GET

| Method | Path | Params | 200 body (top-level keys; `?` = only sometimes) | Failure |
|---|---|---|---|---|
| GET | `/ledger` | `n` (default 20) | `[{ts, run_id, cached, source, step, agent, tool, app, args, ok, response_or_error, state_before, state_after, latency_ms}]` | 500 `{error}` |
| GET | `/tools` | | `[{name, doc, args}]` | 500 `{error}` |
| GET | `/map` | | `{path, stops, rooms, _version, ...}` | 500 `{error}` |
| GET | `/field` | | `{}` | 500 `{error}` |
| GET | `/chat` | | `{alive, age_s, armed, armed_by, pending, group}` | 500 `{error}` |
| GET | `/evals` | | `{written?, rows?}` | 500 `{error}` |
| GET | `/watch` | | `{intruder, ts?, t?, ms?, n?, classes?, boxes?, source?, model?, file?, age_ms?}` | 500 `{error}` |
| GET | `/shift` | | `{shift_id, source}` | 500 `{error}` |
| GET | `/record` | `shift` (default: the run in force) | `{shift_id, rows, stamped, posts, window, planned_stops, stops, flags, corrections, acked_ms, acked_median_ms, refusals, failures, signed, after_signature, site, stub_rows}` | 404 `{error}` unknown shift (a plain sentence); 500 `{error}` |
| GET | `/record/shifts` | | `{shifts, current}` | 500 `{error}` |
| GET | `/rules` | | `{labels, escalate, source, threshold, reply_threshold, unconfirmed, lines}` | 500 `{error}` |
| GET | `/dog/state` | | `{connected, moving, vel, state, map, calibrated, follow, avoid, recheck, corr, rec}` | 500 `{error}` |
| GET | `/dog/scale` | | `{px_per_m, source}` | 500 `{error}` |
| GET | `/dog/lidar` | | `{on, n, errors, cb_errors, grid_frames, localize, age_ms, frame, points_px, utlidar_pose?, n_xy?, z_m?, known?, why?}` | 500 `{error}` |
| GET | `/dog/grid` | `threshold` (default 3) | `{n, cells_px, cell_px, threshold, resolution, frames, frame_id, extent_m, source, hits?, cb_errors?, why?}` | 500 `{n: 0, cells_px: [], error}` |
| GET | `/dog/floorplan` | `threshold` (default 3) | `{segments_px, classes, class_px, source, ok?, threshold?, frames?, ms?, ts?, cell_px?, segments_top_m?, class_top_m?, moved?, why?}` | 500 `{segments_px: [], error}` |
| GET | `/dog/blobs` | | `{labels, source, moved, ts?, why?}` | 500 `{labels: [], error}` |
| GET | `/dog/objects` | | `{n, objects, windows, fov_deg, source, why?}` | 500 `{n: 0, objects: [], error}` |
| GET | `/dog/scout` | | `{n, proposals, zones, _version, failed, why, source, error?}` | 500 `{n: 0, proposals: [], failed: [], error}` |
| GET | `/dog/frame.jpg` | | JPEG bytes (`image/jpeg`); **connects the dog** | 503 `{error}` |
| GET | `/pictures/<name>` | | the file under `~/Pictures/wtdd` | 404 `{error}` |
| GET | `/`, `/<file>` | | `ui/index.html`, or the file under `ui/` (`/route-saved.json`, `/house.svg`, ...) | 404 `{error: "no <file>"}` |

What the keys hold:
- **`/map`**: `ui/map.json` as saved, plus `_version`. The committed map also has `actions`, `zones`, `lights`, `labels`,
  `policy`, `entity` and `note`; the page's save decides which keys exist.
- **`/field`** while a walk runs: `{p: [x, y], here, levels, s, total, dry, stop, source, follower}`.
- **`/chat`**: `alive` means `age_s` < 10. `armed_by` is a name. `pending` is a bool (a question is open). `group` is
  `WTDD_CHAT_NAME` (default `wtdd test`). Every value is null with no `listen.json`, except `alive` (false) and `group`.
- **`/evals`**: `{}` with no `evals.json`. Otherwise `{written, rows: [{scenario, trial, grade, seconds, why, detail, ran}]}`.
- **`/watch`**: `{intruder}` alone with no `watch.json`. Otherwise the detector's newest window plus `age_ms` and `intruder`.
- **`/shift`**: `source` is `file`, `WTDD_SHIFT` or `date`.
- **`/record`**: what `python -m wtdd.record --shift <id>` prints.
  - `window` is `{from, to, closed_by}`.
  - `flags[]` is `{ts, trigger, stop, to, text, file, resolved: null | {by, text, verdict, acked_ms, ts, closed_ms?}}`;
    `to` is the chat guid the flag went to; a 1:1's handle in it reads `a member`.
  - `signed` is null or `{by, at}`.
- **`/record/shifts`**: `shifts` is newest first; `current` is the run in force.
- **`/dog/state`**:
  - `state` is null, or the dog's `{mode, gait_type, progress, position, velocity, yaw_speed, body_height, range_obstacle, rpy, n, hz, age_ms}`.
  - `map` is null, or `{p, heading_deg}`.
  - `follow` is `{}` before any follow. During one it is `{active, i, n, stops, stopped_at, resume, reached, started,
    error, avoid, replans, skipped_stops, passed, unchecked, planned, trace}`, plus `dist_px, err_deg, p, heading_deg`
    while it drives and `done` at the end.
  - `avoid` is null without a dog. `corr` is `{tx, ty, theta, theta_deg}`.
  - `rec` is null, or `{active, n, points, marks, actions}` while recording.
- **`/dog/lidar`**: `localize` is `{applied, rejected, unmatched, skipped, last, corr}`. `z_m` (a number per `points_px`
  entry) is each dot's measured height in metres, the highest z of its column inside the band (the voxel frame's z, the same
  z as `/dog/floorplan`'s `class_top_m`), rounded to 0.05; absent with no frame. `known` (a bool per `points_px`
  entry) is there only with a saved map. `why` names what is missing (not connected, no frame yet, lidar off, not
  calibrated, no saved map).
- **`/dog/grid`**: `source` is `session`, `ui/grid.json` or null. `hits` (a count per `cells_px` entry) is there only when
  cells are drawn.
- **`/dog/floorplan`**: before any plan the answer is `{segments_px: [], classes: {}, class_px: {}, source: null, why}`.
  The heights (`segments_top_m`, `class_top_m`) come only from a grid with a height profile.
- **`/dog/blobs`**: `labels[]` is `{blob_id, kind, xy, geometry_verdict, label, p, model, erase, source, pos_px, error?, ...}`.
- **`/dog/objects`**: `objects[]` is `{id, label, p, label_source, message, message_source, thumb, box, bearing_deg,
  hit_m, dist_m, pos_px, why, first_seen, last_seen, windows_unseen, stale}`.
- **`/dog/scout`**:
  - `proposals[]` is `{id, object_id, kind, label, p, app, cells, cells_px, poly, thumb, photo, dist_m, area_m2, ts}`.
  - `zones` are the auto zones on `ui/map.json`.
  - `failed[]` is `{object_id, kind, error, ts, stage?}`.
  - `why` is null when `n` > 0. `error` is the last feed's raise.
- **Fixtures (DEMO_CACHE).** With `WTDD_OBJECTS`, `WTDD_SCOUT` or `WTDD_BLOBS` set, that route serves the file's keys
  plus `source: "fixture: <file>"`. The committed `scout.json` has no `zones` or `_version`.

## POST

| Method | Path | Body | 200 body | Failure | Rows written |
|---|---|---|---|---|---|
| POST | `/tools/<name>` | the tool's args | `{ok, tool, args, result}` | 500 `{ok: false, tool, args, error}` | the tool's own |
| POST | `/field/stop` | | `{ok}` | 500 | none (touches `field.stop`) |
| POST | `/map/restore` | | `{ok, path_pts, stops}` | 500 | none (`map.prev.json` kept) |
| POST | `/intruder` | `{on}` (default true) | `{ok, intruder}` | 500 | none (`intruder.on`) |
| POST | `/shift` | `{name: morning \| night}` | `{ok, shift_id, started}` | 400 bad name; 500 | `shift.started`, ok or not |
| POST | `/map` | the map, plus `_version` | `{ok, _version}` | 409 stale `_version`; 400 unrunnable path (points named); 500 | none (`map.prev.json` kept) |
| POST | `/dog/drive` | `{x, y, z}` | `{ok, vel, hold_s}` | 500 | none; **connects** |
| POST | `/dog/stop` | | `{ok, vel, halt?}` (`halt`: `{stop_code, velocity}` with a dog; `velocity` is null when the state read back has none) | 500 | `dog.cmd` StopMove with a dog |
| POST | `/dog/calibrate` | `{p: [x, y], heading_deg}` or `{p, toward: [x, y]}` | `{ok, map: {p, heading_deg}}` | 500 | `dog.calibrate`; **connects** |
| POST | `/dog/follow` | `{reach_px?, avoid?}` | `{ok, follow}` | 500 (a no-go refusal too) | `dog.follow` when the follow ends, or `route.refused`; **connects** |
| POST | `/dog/resume` | | `{ok, follow}` (also with no follow) | 500 | none |
| POST | `/dog/avoid` | `{on}` | `{ok, avoid}` | 500 | `dog.avoid`; **connects** |
| POST | `/dog/record` | `{on}` | on: `{ok, rec: {active, n}}`; off: `{ok, rec: {active, path, stops, actions, length_px, samples, problems}}`, written into `ui/map.json` | 500 (too short: `ui/map.json` is not changed, but `map.prev.json` is already overwritten) | `dog.record` when switched off; on: **connects** |
| POST | `/dog/mark` | `{look?, say?, ask?}` | `{ok, rec: {marks}}` | 500 | none |
| POST | `/dog/lidar` | `{on}` | `{ok, lidar}` (GET `/dog/lidar`'s body) | 500 | none; on: **connects** |
| POST | `/dog/grid` | `{save: true}` or `{clear: true, why?}` | save: `{ok, file, bytes, cells, frames, extent_m}`; clear: `{ok, cleared, frames_before}` | 500 (save with no grid) | `dog.grid_save` / `dog.grid_clear` |
| POST | `/dog/scale` | `{px_per_m}` | `{ok, px_per_m, source, file}` | 400 bad value; 500 | `dog.scale`, ok or not |
| POST | `/dog/floorplan` | `{threshold?}` | `{ok, why?, threshold, frames, cells, grid_source, classes, segments, ms, ts}`; **`ok: false` + `why` at 200** when no wall | 500 `{ok: false, error}` with no grid | `dog.floorplan`, ok or not |
| POST | `/dog/blobs` | `{threshold?}` | `{labelled, skipped, failed, labels}` (**no `ok`**) | 500 `{error}` (**no `ok`**) | `blob.labelled` per label, or one failed |
| POST | `/dog/scout` | `{id, action: confirm \| dismiss, by, _version?}` | confirm: `{ok, zone, _version}`; dismiss: `{ok, dismissed}` | 400 unknown action (no row) or no `by`; 404 no open proposal or auto zone; 409 stale `_version`; 500 | `zone.confirmed` / `zone.dismissed`, ok or not |
| POST | any other | | | 404 `{error: "not found"}` | none |

The dog routes in the first group (`/dog/drive` to `/dog/lidar`) answer every failure 500, a ValueError included.
`/shift` and `/dog/scale` answer a ValueError 400. A route that connects also writes the connect's own rows
(`dog.connect`, then `dog.avoid`), or one failed `dog.connect` row.
