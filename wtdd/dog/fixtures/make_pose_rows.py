"""Writes pose_rows.jsonl: a ledger with planted drift for wtdd.dog.test_drift. Deterministic, no dog, no random.

Six replays of the taught route (ui/route-saved.json: 23 waypoints from [448, 455] to [436, 586], stops 11, 15, 22).
Walks 1-3 are driven on the sport odometry (LF_SPORT_MOD_STATE), walks 4-6 on the utlidar pose (rt/utlidar/robot_pose);
both sources are sampled at every other waypoint and the last on every walk (the goal: the two poses recorded side by
side; a real walk samples at 1 Hz, the report reads only each walk's last sample), and the dog.follow row counts them.
Planted: by the end of walk k the sport position is off by SPORT_M[k] metres and the utlidar pose by UTLIDAR_M[k]; each
drift vector grows linearly with the distance walked, in a direction that turns from walk to walk. The follower stops
where ITS source believes the route end is, so the dog physically ends off by the driver's drift; DRAG_AFTER_S seconds
after each walk a dog.calibrate row (the drag on the remote, the shipped correction) puts the dot where the dog
actually stood. Measured from that drag, each source's end error is exactly its planted drift, whoever drove; measured
from the route end alone, the driver's error is its own belief (0) and the other source's is only the disagreement.

Every pose.sample carries the raw odometry (args x, y, yaw) as the inverse of nav.to_map through that source's tie
(state_after.cals of the walk's first dog.calibrate row), so re-projecting the raw pose gives state_after.map back.
Rows are labeled cached: true, source: "fixture" (the ledger's live/stub label); the pose source is args.source.
The rt/utlidar/robot_pose frame behind the utlidar rows is UNVERIFIED on this dog (wtdd/dog/drift.py, utpose_xyyaw).

Run: /Users/johnnysheng/code/origin-build/.venv/bin/python -m wtdd.dog.fixtures.make_pose_rows   (rewrites the file)
"""
from __future__ import annotations
import json
import math
import time
from pathlib import Path

from .. import nav

HERE = Path(__file__).resolve().parent
OUT = HERE / "pose_rows.jsonl"
ROUTE = HERE.parents[2] / "ui" / "route-saved.json"
SOURCES = ("sport", "utlidar")
SPORT_M = [0.55, 0.62, 0.58, 0.60, 0.57, 0.63]      # planted end drift of the sport odometry, per walk, metres
UTLIDAR_M = [0.12, 0.16, 0.14, 0.13, 0.15, 0.14]    # planted end drift of the utlidar pose, per walk, metres
DROVE = ["sport", "sport", "sport", "utlidar", "utlidar", "utlidar"]   # three walks per source (the goal's Needs the dog)
SHIFT_ID = "2026-09-26"
RUN_ID = "fixture-05a"
T0 = time.mktime(time.strptime("2026-09-26T21:00:00", "%Y-%m-%dT%H:%M:%S"))
WALK_GAP_S, STEP_S, DRAG_AFTER_S = 600, 3, 8
# each source's power-on odometry frame at the start of walk k: (x, y, yaw) of the dog at the route start, made up
FRAME0 = {"sport": (-0.25, 2.52, 0.015), "utlidar": (1.30, -0.40, -1.2)}


def from_map(cal: dict, px: float, py: float, heading: float) -> tuple[float, float, float]:
    """The inverse of nav.to_map: a map pose -> the raw odometry (x, y, yaw) that projects to it through `cal`."""
    ox, oy, oyaw = cal["odom"]
    h = cal["heading"]
    u, v = (px - cal["map"][0]) / nav.PX_PER_M, (py - cal["map"][1]) / nav.PX_PER_M
    f, l = u * math.cos(h) + v * math.sin(h), u * math.sin(h) - v * math.cos(h)
    dx, dy = f * math.cos(oyaw) - l * math.sin(oyaw), f * math.sin(oyaw) + l * math.cos(oyaw)
    return ox + dx, oy + dy, nav.wrap(oyaw + (h - heading))


def ts(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def row(t: float, tool: str, args: dict, before, after, ok: bool = True, latency_ms: int = 0) -> dict:
    return {"ts": ts(t), "run_id": RUN_ID, "cached": True, "source": "fixture", "step": tool, "agent": "dog", "tool": tool,
            "app": "map", "args": args, "state_before": before, "state_after": after, "ok": ok, "response_or_error": None,
            "latency_ms": latency_ms}


def calibrate_row(t: float, p, heading: float, before, cals: dict) -> dict:
    sel = cals["sport"]
    return row(t, "dog.calibrate", {"p": [int(p[0]), int(p[1])], "heading_deg": round(math.degrees(heading), 1)}, before,
               {"cal": {**sel, "at": ts(t)}, "cals": cals, "map": {"p": [int(p[0]), int(p[1])], "heading_deg": round(math.degrees(heading), 1)}})


def sample_row(t: float, source: str, cal: dict, p, heading: float) -> dict:
    x, y, yaw = from_map(cal, p[0], p[1], heading)
    px, py, h = nav.to_map(cal, (x, y), yaw)
    assert math.hypot(px - p[0], py - p[1]) < 1e-6 and abs(nav.wrap(h - heading)) < 1e-9, "from_map is not to_map's inverse"
    return row(t, "pose.sample", {"source": source, "x": round(x, 6), "y": round(y, 6), "yaw": round(yaw, 6), "shift_id": SHIFT_ID},
               None, {"map": {"p": [round(px), round(py)], "heading_deg": round(math.degrees(h), 1)}})


def rows() -> list[dict]:
    path = json.loads(ROUTE.read_text())["path"]
    stops = json.loads(ROUTE.read_text())["stops"]
    along = [0.0]
    for i in range(1, len(path)):
        along.append(along[-1] + math.dist(path[i - 1], path[i]))
    headings = [nav.heading_of(path[i], path[i + 1]) for i in range(len(path) - 1)]
    headings.append(headings[-1])
    out: list[dict] = []
    for k in range(len(DROVE)):
        drove = DROVE[k]
        t = T0 + k * WALK_GAP_S
        angle = 0.7 * k + 0.4                                    # the drift's direction on the map, per walk
        planted = {"sport": SPORT_M[k], "utlidar": UTLIDAR_M[k]}
        drift = {s: (planted[s] * nav.PX_PER_M * math.cos(angle + (0 if s == "sport" else 1.9)),
                     planted[s] * nav.PX_PER_M * math.sin(angle + (0 if s == "sport" else 1.9))) for s in SOURCES}
        # the drag to the start: both sources tied to path[0] facing the first segment
        cals = {s: nav.calibration(FRAME0[s][:2], FRAME0[s][2], path[0], headings[0]) for s in SOURCES}
        out.append(calibrate_row(t, path[0], headings[0], None, cals))
        end_belief, end_truth, n = {}, None, {s: 0 for s in SOURCES}
        for i, p in enumerate(path):
            frac = along[i] / along[-1]
            dv = {s: (drift[s][0] * frac, drift[s][1] * frac) for s in SOURCES}
            truth = (p[0] - dv[drove][0], p[1] - dv[drove][1])   # the driver believes it is on the path; the body is off by its drift
            for s in SOURCES:
                belief = p if s == drove else (truth[0] + dv[s][0], truth[1] + dv[s][1])
                end_belief[s] = belief
                if i % 2 == 0 or i == len(path) - 1:   # every other waypoint and always the last (a small file; the report reads the last)
                    out.append(sample_row(t + 5 + STEP_S * i, s, cals[s], belief, headings[i]))
                    n[s] += 1
            end_truth = truth
        t_end = t + 5 + STEP_S * (len(path) - 1) + 1
        hd = round(math.degrees(headings[-1]), 1)
        out.append(row(t_end, "dog.follow", {"n": len(path), "start": 0, "stops": stops, "reach_px": 30.0, "avoid": True, "pose_source": drove},
                       {"p": list(path[0]), "heading_deg": round(math.degrees(headings[0]), 1)},
                       {"reached": list(range(len(path))), "of": len(path), "seconds": float(t_end - t - 5), "map": {"p": list(path[-1]), "heading_deg": hd},
                        "samples": n}, latency_ms=int((t_end - t - 5) * 1000)))
        # the drag: where the dog actually stood, from the person on camera; both sources re-tied there
        cals_end = {s: nav.calibration(from_map(cals[s], end_belief[s][0], end_belief[s][1], headings[-1])[:2],
                                       from_map(cals[s], end_belief[s][0], end_belief[s][1], headings[-1])[2], end_truth, headings[-1]) for s in SOURCES}
        out.append(calibrate_row(t_end + DRAG_AFTER_S, end_truth, headings[-1], {"p": list(path[-1]), "heading_deg": hd}, cals_end))
    return out


def text() -> str:
    return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows())


def main() -> int:
    body = text()
    OUT.write_text(body)
    n = body.count("\n")
    print(f"wrote {OUT} rows={n} walks={len(DROVE)} sources={SOURCES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
