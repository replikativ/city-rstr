import unittest

import numpy as np

from scripts.vancouver_regional_workplaces import allocate, paired_distance


class RegionalWorkplaceTest(unittest.TestCase):
    def test_move_conserves_worker_stock_and_respects_diary_budget(self):
        coords = np.array([[0, 0], [8_000, 0], [2_000, 0], [4_000, 0], [4_500, 0]])
        municipalities = np.array([0, 1, 2, 3, 3])
        workers = [[i, 0, 0, i, i, [1], [[0, duration, "transit"]]]
                   for i, duration in enumerate([1, 1, 2, 2])]
        # One unmovable resident whose paid-work location crosses an untimed stop.
        workers.append([4, 1, 0, 1, 1, [1], None])
        census = np.eye(4, dtype=int)
        result, moves = allocate(workers, municipalities, coords, census, None)
        self.assertEqual(result["target"][0], [5, 0, 0, 0])
        self.assertEqual(result["after"][0], [4, 1, 0, 0])
        self.assertEqual(len(moves), 3)
        for [_, _, _, new] in [move for group in moves.values() for move in group]:
            self.assertEqual(new, 0)

    def test_cross_inlet_road_leg_considers_both_directions_and_connectors(self):
        coords = np.array([[0, 0], [10, 0]])
        north = np.array([False, True])
        entering = np.array([[70, 1000], [1000, 150]])
        exiting = np.array([[1000, 80], [90, 1000]])
        roads = entering, exiting, np.array([[10], [10]]), np.array([2, 3])
        metres = paired_distance(0, np.array([1]), north, coords, roads, "car-driver")
        self.assertEqual(metres.tolist(), [255])
