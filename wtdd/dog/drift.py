"""Which odometry drifts less: the dog's two poses side by side, the follower's switch, and the end-error report.

What. The dog publishes two poses. "sport" is the LF_SPORT_MOD_STATE position plus the IMU yaw (leg odometry, the one
the shipped follower steers on); "utlidar" is rt/utlidar/robot_pose, the LiDAR odometry. Body.connect subscribes both
for the whole session; every follow (wtdd/dog/session.py _follow) writes one pose.sample row per source every
POSE_SAMPLE_S and once more right before its dog.follow row, each with the raw x, y, yaw and its map projection through
THAT source's own tie (every drag ties both). Env WTDD_POSE_SOURCE (sport | utlidar, absent = sport) chooses the one the
follower steers on, the drag requires and GET /dog/state calls "map"; the dog.follow row names it in args.pose_source.

How. `python -m wtdd.dog.drift --ledger ledger.jsonl` cuts any ledger into walks at the dog.follow rows (the samples
before a follow row are that walk's) and measures, per source, how far the walk's last sample is from where the dog
really stood. The reference is the first dog.calibrate after the walk, within DRAG_WINDOW_S: the drag on the remote,
the shipped correction ("the dot is dragged on camera and the correction is a row"), and only if the dog had not moved
since: the drag's state_before (the steering source's belief at the drag) must sit within the walk's reach_px of that
source's last sample, else it is a later drag (hand-driven back to the start, say) and is refused, WARN. Without
one it is the taught route end (ui/route-saved.json path[-1]); then the driving source's error is only under reach_px
by construction (the follower stops where its own source believes the end is) and the other's is only the
disagreement, so every walk says which reference it used and who drove. A walk that did not reach the end and has no
drag has no reference: no number. The report names the source with the lower mean end error.

UNVERIFIED on this dog (the first live run confirms; the PR's Needs the dog): the shape of rt/utlidar/robot_pose
(utpose_xyyaw reads a ROS PoseStamped, a guess: the driver names the topic and parses nothing); whether the dog publishes
it with the LiDAR switch off; whether its frame and yaw convention match the sport odometry's (each source has its own
tie, so a different origin is fine; a mirrored yaw is not, and shows as the first utlidar-driven turn going the wrong way).
No DEMO_CACHE: the committed fixture (wtdd/dog/fixtures/pose_rows.jsonl, rows labeled cached/fixture) feeds the test only;
the live path is this same CLI over the real ledger after real walks.
"""
from __future__ import annotations
import argparse
import json
import math
import time
from pathlib import Path

from .. import config
from ..ledger import log
from . import nav

SOURCES = ("sport", "utlidar")
DRAG_WINDOW_S = 120   # a drag this soon after a walk is where the dog stood at the end of it
TS = "%Y-%m-%dT%H:%M:%S"


def selected_source() -> str:
    """The pose the follower steers on: env WTDD_POSE_SOURCE, absent = sport (the shipped source); anything else raises."""
    v = config.maybe("WTDD_POSE_SOURCE") or "sport"
    if v not in SOURCES:
        raise RuntimeError(f"[wtdd:drift] WTDD_POSE_SOURCE={v!r} is not one of {SOURCES}")
    return v


def shift_id() -> str:
    return config.maybe("WTDD_SHIFT") or time.strftime("%Y-%m-%d")


def utpose_xyyaw(msg) -> tuple[float, float, float]:
    """rt/utlidar/robot_pose data -> (x, y, yaw). Reads {"pose": {"position", "orientation"}} (header optional) or a bare
    {"position", "orientation"}; yaw from the quaternion. UNVERIFIED shape: anything else raises naming what came."""
    pose = msg.get("pose", msg) if isinstance(msg, dict) else None
    try:
        p, q = pose["position"], pose["orientation"]
        x, y = float(p["x"]), float(p["y"])
        qx, qy, qz, qw = (float(q[k]) for k in "xyzw")
    except (KeyError, TypeError, ValueError):
        got = f"keys {sorted(msg)}" if isinstance(msg, dict) else f"type {type(msg).__name__}"
        raise ValueError(f"rt/utlidar/robot_pose shape not understood (UNVERIFIED guess is a PoseStamped): {got}") from None
    return x, y, math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))


def sample(source: str, x: float, y: float, yaw: float, cal: dict | None, shift: str) -> dict:
    """One pose.sample row for ledger.append: the raw pose in args, its map projection through `cal` (that source's tie)."""
    if source not in SOURCES:
        raise ValueError(f"pose source must be one of {SOURCES}, got {source!r}")
    if cal is None:
        after = {"map": None, "why": f"no calibration for {source}"}
    else:
        px, py, h = nav.to_map(cal, (x, y), yaw)
        after = {"map": {"p": [round(px), round(py)], "heading_deg": round(math.degrees(h), 1)}}
    return {"step": "pose.sample", "agent": "dog", "tool": "pose.sample", "app": "map",
            "args": {"source": source, "x": float(x), "y": float(y), "yaw": float(yaw), "shift_id": shift},
            "state_before": None, "state_after": after, "ok": True, "response_or_error": None, "latency_ms": 0}


def load(path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def _t(r: dict) -> float:
    return time.mktime(time.strptime(r["ts"], TS))


def report(rows: list[dict], route_end) -> dict:
    """Walks and end errors per source (the module docstring). Raises RuntimeError when there is no pose.sample row."""
    n_samples = sum(1 for r in rows if r.get("tool") == "pose.sample")
    if n_samples == 0:
        raise RuntimeError(f"0 pose.sample rows in {len(rows)} rows: nothing to measure")
    walks, last, uncal, trailing = [], {}, 0, 0
    for j, r in enumerate(rows):
        tool = r.get("tool")
        if tool == "pose.sample":
            trailing += 1
            m = (r.get("state_after") or {}).get("map")
            if m is None:
                uncal += 1
            else:
                last[r["args"]["source"]] = m["p"]
            continue
        if tool != "dog.follow":
            continue
        trailing = 0
        args, after = r.get("args") or {}, r.get("state_after") or {}
        reached, of = len(after.get("reached") or []), args.get("n")
        drag = None
        for q in rows[j + 1:]:   # the first ok drag before the next walk, if soon enough
            if q.get("tool") == "dog.follow":
                break
            if q.get("tool") == "dog.calibrate" and q.get("ok"):
                drag = q if _t(q) - _t(r) <= DRAG_WINDOW_S else None
                break
        if drag is not None:   # the walk's end only if the driver's belief at the drag is still where the walk left it
            at, was = (drag.get("state_before") or {}).get("p"), last.get(args.get("pose_source"))
            moved = round(math.dist(at, was)) if at and was else None
            if moved is None or moved > args["reach_px"]:
                log("drift", f"WARN walk {len(walks) + 1}: the drag at {drag['args']['p']} came after the dog moved "
                    f"{'an unknown distance' if moved is None else f'{moved} px'} from where the walk ended: not this walk's reference")
                drag = None
        if drag is not None:
            truth, truth_p = "drag", drag["args"]["p"]
        elif r.get("ok"):   # ok only when the follower reached the last waypoint (a replay from mid-route reaches fewer than of)
            truth, truth_p = "route end", list(route_end)
        else:
            truth, truth_p = None, None
            log("drift", f"WARN walk {len(walks) + 1} ended short ({reached}/{of}) with no drag after it: no reference, no number")
        end = {s: ({"p": last[s], "err_m": round(math.dist(last[s], truth_p) / nav.PX_PER_M, 3) if truth_p else None}
                   if s in last else None) for s in SOURCES}
        walks.append({"i": len(walks) + 1, "ts": r.get("ts"), "drove": args.get("pose_source", "unknown"), "reached": reached,
                      "of": of, "ok": r.get("ok"), "truth": truth, "truth_p": truth_p, "end": end})
        last = {}
    if trailing:
        log("drift", f"WARN {trailing} pose.sample rows after the last dog.follow row: a walk in progress is not a walk")
    if uncal:
        log("drift", f"WARN {uncal} pose.sample rows without a map projection (their source was not calibrated)")
    sources = {}
    for s in SOURCES:
        errs = [w["end"][s]["err_m"] for w in walks if w["end"][s] and w["end"][s]["err_m"] is not None]
        sources[s] = {"n": len(errs), "err_m": errs, "mean_m": round(sum(errs) / len(errs), 3) if errs else None,
                      "max_m": max(errs) if errs else None}
    rep = {"route_end": list(route_end), "n_rows": len(rows), "n_samples": n_samples, "uncalibrated": uncal,
           "walks": walks, "sources": sources, "lower": None}
    empty = [s for s in SOURCES if sources[s]["n"] == 0]
    means = sorted((sources[s]["mean_m"], s) for s in SOURCES if sources[s]["n"])
    if not walks:
        rep["why"] = "no dog.follow row: no walk to measure"
    elif empty:
        rep["why"] = f"no measured walk for {', '.join(empty)}"
    elif means[0][0] == means[1][0]:
        rep["why"] = f"the means tie at {means[0][0]} m"
    else:
        rep["lower"] = means[0][1]
    if rep["lower"] is None:
        log("drift", "WARN no lower-drift source: " + rep["why"])
    return rep


def format(rep: dict) -> str:
    def m(v):
        return "-" if v is None else f"{v:.3f} m"
    lines = [f"route end {rep['route_end']} · {rep['n_samples']} pose.sample rows in {rep['n_rows']} rows"]
    for w in rep["walks"]:
        ends = "  ".join(f"{s} {m((w['end'][s] or {}).get('err_m'))}" for s in SOURCES)
        lines.append(f"walk {w['i']} {w['ts']} drove={w['drove']} reached {w['reached']}/{w['of']} ok={w['ok']} "
                     f"vs {w['truth'] or 'no reference'} {w['truth_p']}: {ends}")
    for s in SOURCES:
        v = rep["sources"][s]
        lines.append(f"{s}: n={v['n']} mean {m(v['mean_m'])} max {m(v['max_m'])}")
    sp, ut = rep["sources"]["sport"], rep["sources"]["utlidar"]
    if rep["lower"]:
        lo, hi = (ut, sp) if rep["lower"] == "utlidar" else (sp, ut)
        lines.append(f"lower-drift source: {rep['lower']} ({lo['mean_m']:.3f} m vs {hi['mean_m']:.3f} m over "
                     f"{min(lo['n'], hi['n'])} walks)")
    else:
        lines.append(f"lower-drift source: none ({rep['why']})")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wtdd.dog.drift", description="end-position error per pose source, per walk")
    ap.add_argument("--ledger", required=True, help="a ledger .jsonl (the live one is ledger.jsonl at the repo root)")
    ap.add_argument("--route", default=str(config.ROOT / "ui" / "route-saved.json"), help="the taught route; its end is path[-1]")
    a = ap.parse_args(argv)
    route_end = json.loads(Path(a.route).read_text())["path"][-1]
    try:
        rep = report(load(a.ledger), route_end)
    except RuntimeError as e:
        log("drift", "WARN " + str(e))
        return 1
    print(format(rep))
    log("drift", "report", walks=len(rep["walks"]), samples=rep["n_samples"], uncalibrated=rep["uncalibrated"],
        sport_mean_m=rep["sources"]["sport"]["mean_m"], utlidar_mean_m=rep["sources"]["utlidar"]["mean_m"], lower=rep["lower"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
