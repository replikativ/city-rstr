import unittest
from collections import defaultdict

import numpy as np

from scripts.vancouver_campus import match


class CampusTimetableTest(unittest.TestCase):
    def setUp(self):
        self.patterns = [('99', [1, 2, 3],
                          np.array([[600, 620, 700, 720, 800, 820],
                                    [603, 625, 680, 690, 799, 809]]), [24, 25])]
        self.boards = defaultdict(list, {1: [(0, 0)], 2: [(0, 1)]})

    def test_dwell_and_overtaking_keep_earliest_feasible_arrival(self):
        self.assertEqual(match(10, 4, {1:20}, {3:41}, self.patterns, self.boards),
                         ['99',25,0,2,20,41])

    def test_walks_and_wait_fit_in_both_ends_of_window(self):
        self.assertIsNone(match(10, 4, {1:26}, {3:40}, self.patterns, self.boards))
        self.assertIsNone(match(10, 4, {1:20}, {3:42}, self.patterns, self.boards))
        self.assertIsNone(match(10, 4, {2:0}, {1:0}, self.patterns, self.boards))

    def test_after_midnight_uses_extended_service_clock(self):
        self.patterns[0][2][:] += 24*3600
        self.assertEqual(match(1450, 4, {1:20}, {3:41}, self.patterns, self.boards),
                         ['99',25,0,2,20,41])
