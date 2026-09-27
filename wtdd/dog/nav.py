"""Where the dog thinks it is on the map, and how it follows the drawn path. Pure functions; the session runs them.

Frames. Odometry (LF_SPORT_MOD_STATE position x,y in meters and IMU yaw in radians) is fixed at power-on and drifts
(leg odometry slips on rugs and turns; yaw is gyro-integrated). The map is ui/house.svg pixel space, y down, about
PX_PER_M pixels per meter (WTDD_PX_PER_M, measured; 108.5 when unset, from the bottom living room guessed at 445 px and 4.1 m;
set_scale moves it while the API runs, the page's slider through DogSession.scale). One calibration ties them: the odometry
pose at the moment Johnny says "the dog is at map point (mx, my) facing heading h". Map heading is radians, 0 = +x on
screen, increasing clockwise (because y is down); a positive ROS yaw turns the dog left, which is counter-clockwise on
screen, so heading = h - (yaw - yaw0). "I'm here" later re-ties the position (keeps the heading): that is the
back-and-forth alignment, the human corrects the drift and the belief moves.

Follower. steer() is a proportional heading controller: turn toward the next waypoint at up to WMAX rad/s, move at
VMAX m/s only while the heading error is under AHEAD rad, waypoint reached inside reach_px. No planner and no map of
walls: the drawn path is the plan, obstacle avoidance is off, the controller and the stop button are the safety."""
from __future__ import annotations
import math

from .. import config


def _checked(raw, name: str) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be pixels per metre as a number (like 103.4), got {raw!r}") from None
    if not 20.0 <= v <= 400.0:
        raise ValueError(f"{name}={v} is outside 20..400 pixels per metre; house.svg's first guess was 108.5")
    return v


def _px_per_m() -> tuple[float, str]:
    """S5: the map scale is measured, not guessed. WTDD_PX_PER_M in .env (pixels per metre on house.svg); unset keeps
    108.5, the first guess ("445 px wide and 4.1 m"). Measure it: the living room's width on the scan in pixels (scan_px,
    drawn at the old scale) against the drawing's 445 px gives WTDD_PX_PER_M = 108.5 * 445 / scan_px. Read at import; a
    value that is not a number, or outside 20..400, stops loud. Returns (value, source)."""
    raw = config.maybe("WTDD_PX_PER_M")
    return (108.5, "default") if raw is None else (_checked(raw, "WTDD_PX_PER_M"), "WTDD_PX_PER_M")


def set_scale(v, source: str) -> float:
    """S5b: the scale while the API runs (the page's slider, a saved dog_cal.json; wtdd/dog/session.py scale). Every
    reader (to_map, occupancy.to_map_px, lidar.to_map_points) reads PX_PER_M at call time, so all follow at once. Outside
    20..400 or not a number: ValueError naming the value, and the scale is left as it was."""
    global PX_PER_M, SCALE_SOURCE
    PX_PER_M, SCALE_SOURCE = _checked(v, "px_per_m"), source
    return PX_PER_M


PX_PER_M, SCALE_SOURCE = _px_per_m()   # SCALE_SOURCE: default | WTDD_PX_PER_M | dog_cal.json | page
VMAX, WMAX, AHEAD, K = 0.3, 0.5, 0.6, 1.6


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading_of(a, b) -> float:
    """Map heading from point a to point b (radians, y down)."""
    return math.atan2(b[1] - a[1], b[0] - a[0])


def calibration(pos, yaw: float, p, heading: float) -> dict:
    return {"odom": [float(pos[0]), float(pos[1]), float(yaw)], "map": [float(p[0]), float(p[1])], "heading": float(heading)}


def to_map(cal: dict, pos, yaw: float) -> tuple[float, float, float]:
    """Odometry pose -> (px, py, heading) on the map through the calibration."""
    ox, oy, oyaw = cal["odom"]
    dx, dy = float(pos[0]) - ox, float(pos[1]) - oy
    f = dx * math.cos(oyaw) + dy * math.sin(oyaw)      # forward since calibration, meters
    l = -dx * math.sin(oyaw) + dy * math.cos(oyaw)     # left since calibration, meters
    h = cal["heading"]
    px = cal["map"][0] + PX_PER_M * (f * math.cos(h) + l * math.sin(h))
    py = cal["map"][1] + PX_PER_M * (f * math.sin(h) - l * math.cos(h))
    return px, py, wrap(h - (float(yaw) - oyaw))


def steer(px: float, py: float, heading: float, target, reach_px: float) -> dict:
    """One control step toward target: {x (m/s), z (rad/s), dist_px, err_deg, reached}."""
    dist = math.hypot(target[0] - px, target[1] - py)
    if dist <= reach_px:
        return {"x": 0.0, "z": 0.0, "dist_px": round(dist), "err_deg": 0.0, "reached": True}
    err = wrap(heading_of((px, py), target) - heading)   # positive = target is clockwise on screen = to the dog's right
    z = max(-WMAX, min(WMAX, -K * err))                   # right turn = negative ROS yaw rate
    x = VMAX if abs(err) < AHEAD else 0.0
    return {"x": x, "z": round(z, 3), "dist_px": round(dist), "err_deg": round(math.degrees(err), 1), "reached": False}


def nearest_index(path, p) -> int:
    return min(range(len(path)), key=lambda i: math.hypot(path[i][0] - p[0], path[i][1] - p[1]))
