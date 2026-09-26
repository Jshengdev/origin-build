"""Where the dog thinks it is on the map, and how it follows the drawn path. Pure functions; the session runs them.

Frames. Odometry (LF_SPORT_MOD_STATE position x,y in meters and IMU yaw in radians) is fixed at power-on and drifts
(leg odometry slips on rugs and turns; yaw is gyro-integrated). The map is ui/house.svg pixel space, y down, about
PX_PER_M pixels per meter (the bottom living room is 445 px wide and 4.1 m). One calibration ties them: the odometry
pose at the moment Johnny says "the dog is at map point (mx, my) facing heading h". Map heading is radians, 0 = +x on
screen, increasing clockwise (because y is down); a positive ROS yaw turns the dog left, which is counter-clockwise on
screen, so heading = h - (yaw - yaw0). "I'm here" later re-ties the position (keeps the heading): that is the
back-and-forth alignment, the human corrects the drift and the belief moves.

Follower. steer() is a proportional heading controller: turn toward the next waypoint at up to WMAX rad/s, move at
VMAX m/s only while the heading error is under AHEAD rad, waypoint reached inside reach_px. No planner and no map of
walls: the drawn path is the plan, obstacle avoidance is off, the controller and the stop button are the safety."""
from __future__ import annotations
import math

PX_PER_M = 108.5
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
