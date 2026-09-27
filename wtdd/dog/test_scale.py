"""S5 · the map scale (pixels per metre on house.svg) is a measured setting, WTDD_PX_PER_M, not a hand guess in code.

Before S5, wtdd/dog/nav.py fixed PX_PER_M = 108.5 from "the bottom living room is 445 px wide and 4.1 m", and every
metre-to-pixel conversion (the dog, the grid, the floor plan, routes, pins) went through it. S5 reads the measured
value at import; a missing key keeps 108.5; a value that is not a number, or outside 20..400, stops the import loud.
  python -m unittest wtdd.dog.test_scale
"""
import importlib
import os
import unittest
from unittest import mock

from .. import config
from . import nav


def reload_with(value):
    env = {k: v for k, v in os.environ.items() if k != "WTDD_PX_PER_M"}
    if value is not None:
        env["WTDD_PX_PER_M"] = value
    with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(config, "_loaded", True):
        return importlib.reload(nav).PX_PER_M


class Scale(unittest.TestCase):
    def tearDown(self):
        reload_with(None)   # leave nav at the default for every other test in the process

    def test_the_default_is_the_old_guess(self):
        self.assertEqual(reload_with(None), 108.5)

    def test_a_measured_scale_is_used(self):
        self.assertEqual(reload_with("103.4"), 103.4)

    def test_every_conversion_follows_it(self):
        reload_with("100")
        cal = nav.calibration([0.0, 0.0, 0.0], 0.0, [500.0, 500.0], 0.0)
        px, py, _ = nav.to_map(cal, [1.0, 0.0, 0.0], 0.0)   # one metre forward, heading 0 = +x on screen
        self.assertAlmostEqual(px - 500.0, 100.0, places=6)

    def test_a_scale_that_is_not_a_number_stops_loud(self):
        with self.assertRaisesRegex(ValueError, "WTDD_PX_PER_M"):
            reload_with("108,5")

    def test_a_scale_outside_twenty_to_four_hundred_stops_loud(self):
        for bad in ("0", "-5", "5000"):
            with self.assertRaisesRegex(ValueError, "WTDD_PX_PER_M", msg=bad):
                reload_with(bad)


if __name__ == "__main__":
    unittest.main()
