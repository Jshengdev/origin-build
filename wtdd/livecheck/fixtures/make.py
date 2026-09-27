"""Writes the livecheck fixtures next to this file. Every row is labelled `cached: true, source: "stub"` (NIGHT-1
contracts, section E: no fixture row ever claims to be live) and carries `fixture` naming this script. Row shapes
follow wtdd/ledger.py's keys and the rows the branches write: dog.calibrate and dog.follow (main, wtdd/dog/session.py),
dog.grid_save (feat/01-occupancy, session.grid_save: args {file, frames, frame_id, resolution, cal_at}, state_after
{file, bytes, cells, frames, extent_m}, extent_m being Grid.extent_m()'s {"x": [x0, x1], "y": [y0, y1]}, never a scalar),
route.refused (feat/04-nogo, wtdd/nogo.py: ok false, args {zone, waypoint, index, source, path_pts, shift_id}). The log
lines copy feat/01's log() calls (wtdd/dog/body.py _on_lidar, session._on_frame, occupancy.py update_frame's refusal
text). The numbers are invented for the dry path; none was read from a dog.

  python wtdd/livecheck/fixtures/make.py          rewrites:
    ledger-01-3.jsonl          01.3 PASS: calibrate, a baseline grid save, the save after the 3 m drive (frames 8 -> 74)
    ledger-01-3-timeout.jsonl  01.3 FAIL: the same without the final save
    ledger-04-4-unsafe.jsonl   04.4 UNSAFE: a route.refused row, then a dog.follow row 3 s later
    api-01-3.log               the API's stderr for a PASS (no fatal WARN); log lines carry no timestamp
    api-01-3-warn.log          the same plus one `WARN lidar frame callback failed` line: a later frame's frame_id refused
                               by the grid the first frame started (occupancy.update_frame's ValueError, verbatim)
Not written here: pr-body-01.md and pr-body-04.md, hand-trimmed copies of PR #5's and PR #4's bodies (their Needs the dog
sections verbatim), the two heading shapes --from-prs has to read.
"""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABEL = {"run_id": "fixture-22", "cached": True, "source": "stub", "fixture": "wtdd/livecheck/fixtures/make.py"}


def row(ts: str, tool: str, agent: str, app: str, args: dict, before, after, ok: bool = True, err=None, ms: int = 0) -> dict:
    return {"ts": ts, **LABEL, "step": tool, "agent": agent, "tool": tool, "app": app, "args": args,
            "state_before": before, "state_after": after, "ok": ok, "response_or_error": err, "latency_ms": ms}


CAL = "2026-09-27T20:00:00"
CALIBRATE = row(CAL, "dog.calibrate", "dog", "map", {"p": [442, 498], "heading_deg": -90.0},
                {"p": [440, 500], "heading_deg": -88.0},
                {"cal": {"odom": [0.0, 0.0, 0.0], "map": [442.0, 498.0], "heading": -1.5708, "at": CAL}, "map": {"p": [442, 498], "heading_deg": -90.0}})
SAVE_0 = row("2026-09-27T20:00:03", "dog.grid_save", "dog", "map",
             {"file": "ui/grid.json", "frames": 8, "frame_id": "odom", "resolution": 0.05, "cal_at": CAL},
             {"file_bytes": None}, {"file": "ui/grid.json", "bytes": 4210, "cells": 640, "frames": 8,
                                    "extent_m": {"x": [-3.2, 3.2], "y": [-3.2, 3.2]}}, ms=3)
SAVE_1 = row("2026-09-27T20:00:12", "dog.grid_save", "dog", "map",
             {"file": "ui/grid.json", "frames": 74, "frame_id": "odom", "resolution": 0.05, "cal_at": CAL},
             {"file_bytes": 4210}, {"file": "ui/grid.json", "bytes": 9880, "cells": 1510, "frames": 74,
                                       "extent_m": {"x": [-3.2, 6.4], "y": [-3.2, 3.2]}}, ms=4)

REFUSED = row("2026-09-27T20:10:00", "route.refused", "dog", "map",
              {"zone": "nogo-1", "waypoint": [480, 1100], "index": 3, "source": "map", "path_pts": 23, "shift_id": "2026-09-27"},
              None, None, ok=False, err="route refused: the route crosses no-go zone nogo-1 between points 4 and 5 at 480,1100")
FOLLOW = row("2026-09-27T20:10:03", "dog.follow", "dog", "map", {"n": 23, "start": 0, "stops": [10, 22], "reach_px": 30.0, "avoid": True},
             {"p": [412, 460], "heading_deg": -94.0},
             {"reached": [0, 1, 2, 3, 4, 5], "of": 23, "seconds": 14.0, "map": {"p": [488, 1096], "heading_deg": 91.0}}, ms=14000)

LOG_OK = """# fixture: written by wtdd/livecheck/fixtures/make.py, not a real API log (line shapes from wtdd/ledger.py log() and feat/01-occupancy)
[wtdd:api] serving http://127.0.0.1:7788/  tools=23 ui=/Users/johnnysheng/code/origin-build/ui
[wtdd:dog] probe reachable=True checks=6 ms=812
[wtdd:dog] dog.connect ok=True app=unitree ms=2140 err=
[wtdd:dog] first lidar frame frame_id=odom voxels=3812 width=[128, 128, 38] res=0.05 origin=[-3.2, -3.2, -0.3] center=[0.0, 0.0, 0.65] odom_pos=[0.28, 0.12, 0.31] center_vs_odom_m=0.31 z_layers={-0.3: 1210, 0.1: 980, 0.5: 902, 1.0: 720}
[wtdd:dog] grid started frame_id=odom resolution=0.05 origin=[-3.2, -3.2]
[wtdd:dog] calibrated p=[442, 498] heading_deg=-90.0
[wtdd:dog] dog.calibrate ok=True app=map ms=0 err=
[wtdd:dog] dog.grid_save ok=True app=map ms=3 err=
[wtdd:api] "POST /dog/grid HTTP/1.1" 200 -
[wtdd:dog] grid frames=100 cells=1210 shape=(128, 128) touched=612 ms=2.1
[wtdd:dog] dog.grid_save ok=True app=map ms=4 err=
[wtdd:api] "POST /dog/grid HTTP/1.1" 200 -
"""
GRID_STARTED = "[wtdd:dog] grid started frame_id=odom resolution=0.05 origin=[-3.2, -3.2]\n"
LOG_WARN = LOG_OK.replace(GRID_STARTED, GRID_STARTED + "[wtdd:dog] WARN lidar frame callback failed err=ValueError: frame_id 'map' is not "
                          "the grid's 'odom': another frame, refused errors=1\n")


def jsonl(name: str, rows: list[dict]) -> None:
    (HERE / name).write_text("".join(json.dumps(r) + "\n" for r in rows))


def main() -> None:
    jsonl("ledger-01-3.jsonl", [CALIBRATE, SAVE_0, SAVE_1])
    jsonl("ledger-01-3-timeout.jsonl", [CALIBRATE, SAVE_0])
    jsonl("ledger-04-4-unsafe.jsonl", [REFUSED, FOLLOW])
    (HERE / "api-01-3.log").write_text(LOG_OK)
    (HERE / "api-01-3-warn.log").write_text(LOG_WARN)
    print("wrote 5 fixtures under", HERE)


if __name__ == "__main__":
    main()
