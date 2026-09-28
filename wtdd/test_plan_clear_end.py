"""plan.clear never calls a leg blocked for live cells hugging the leg's OWN end (live 22:36:50: dot 6 snapped to free floor
beside a permanent blocker; every new leg to it failed plan.clear at once, so MAX_REPLANS burned in one second from the
same pose and the walk was refused). The end is the (snapped) target plan.leg was asked for; the dog's avoidance covers it."""
from __future__ import annotations
import unittest

from wtdd import plan


class ClearEnd(unittest.TestCase):
    def test_live_cells_at_the_legs_own_end_do_not_block_it(self):
        C = plan.CELL
        end = [300, 300]
        blob = [[end[0] + 2 * C, end[1] + dy] for dy in range(-2 * C, 2 * C + 1, C)]   # a wall 2 cells right of the target
        leg = [[300, 100], [300, 200], end]
        self.assertTrue(plan.clear(leg, blob), "a blocker hugging the target it snapped to is not a new obstacle on the way")

    def test_a_live_cell_in_the_middle_of_the_leg_still_blocks(self):
        C = plan.CELL
        leg = [[300, 100], [300, 200], [300, 400]]
        self.assertFalse(plan.clear(leg, [[300, 260]]), "something ON the way, far from both ends, still re-plans")


if __name__ == "__main__":
    unittest.main()
