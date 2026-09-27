"""Builds wtdd/fixtures/map_nogo.json: the shipped floor plan (ui/map.json's rooms, entity and lighting zones a/b/c,
unchanged) plus ONE no-go zone, nogo-1, a 60 x 210 px strip across the living room, and a taught route that runs
straight through it. This is the map behind `python -m unittest wtdd.test_nogo` and the planner pair
  WTDD_MAP=wtdd/fixtures/map_nogo.json python -m wtdd plan_path from=300,1100 to=650,1100
(today's straight line [305,1105]->[655,1105] enters the zone; a planner that blocks it prints a detour).
The zone is a fixture, drawn by hand here, not by any model and not on the tracked ui/map.json: the site's real zones
are drawn by a person on the remote. Re-run after the rooms change: python wtdd/fixtures/make_map_nogo.py (stdlib only;
writes the file next to itself). Nothing here touches a device or the real ledger."""
from __future__ import annotations
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIPPED = HERE.parents[1] / "ui" / "map.json"
OUT = HERE / "map_nogo.json"

NOGO = {"name": "nogo-1", "label": "no-go 1", "poly": [[450, 1040], [510, 1040], [510, 1250], [450, 1250]], "nogo": True}
PATH_THROUGH = [[300, 1100], [480, 1100], [650, 1100]]   # waypoint 2 sits inside nogo-1; every point is in the living room, steps under 300 px


def build() -> dict:
    m = json.loads(SHIPPED.read_text())
    return {
        "note": "Fixture for wtdd/test_nogo.py (built by wtdd/fixtures/make_map_nogo.py from ui/map.json). Same space as the "
                "shipped map (house.svg viewBox 0 0 1060 1540). zones[].nogo: true marks a no-go zone: the planner blocks its cells, "
                "the walk and the follower refuse a route that touches it and write route.refused {zone, waypoint, source: map}. "
                "Zones without nogo (a, b, c) are the lighting zones and mean nothing to the planner.",
        "path": PATH_THROUGH,
        "zones": [*m["zones"], NOGO],
        "lights": [],
        "rooms": m["rooms"],
        "entity": m["entity"],
        "stops": [],
        "actions": {},
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1) + "\n")
    print(f"wrote {OUT.relative_to(HERE.parents[1])}: {len(build()['zones'])} zones, {len(PATH_THROUGH)} path points")
