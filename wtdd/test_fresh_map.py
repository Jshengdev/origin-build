"""Checks the shipped ui/map.json starts a night fresh: no route, no stops, no stop actions, no no-go zone. The route and
the no-go zones are drawn on the night (the page's "draw path" and "draw no-go", or 21's taps), never inherited from a past
take; the house itself (rooms, lights, the lighting zones a, b, c, the entity's tuning) stays. Johnny, 2026-09-27 02:40:
"why is the default a saved route. remove that so we start fresh". The old route lives on as wtdd/fixtures/map_route.json
for the tests that need a route, and ui/route-saved.json stays behind the page's "restore saved route" button.
  python -m unittest wtdd.test_fresh_map
"""
from __future__ import annotations
import json
import unittest

from wtdd.config import ROOT

MAP = ROOT / "ui" / "map.json"


class FreshMap(unittest.TestCase):
    def setUp(self):
        self.m = json.loads(MAP.read_text())

    def test_no_route_no_stops_no_actions(self):
        self.assertEqual(self.m.get("path"), [])
        self.assertEqual(self.m.get("stops"), [])
        self.assertEqual(self.m.get("actions"), {})

    def test_no_nogo_zone_until_one_is_drawn(self):
        self.assertEqual([z["name"] for z in self.m.get("zones", []) if z.get("nogo")], [])

    def test_the_house_stays(self):
        for k in ("rooms", "lights", "zones", "entity"):
            self.assertTrue(self.m.get(k), f"{k} must stay on the fresh map")


if __name__ == "__main__":
    unittest.main()
