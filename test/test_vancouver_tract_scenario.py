import unittest

import numpy as np

from scripts.vancouver_tract_scenario import active_route_check, allocate, targets, transfers


class CensusWorkplaceTest(unittest.TestCase):
    def test_integer_targets_redistribute_after_applying_floors(self):
        np.testing.assert_array_equal(targets(np.array([10, 20, 70]), np.array([30, 25, 0]), 100), [30, 25, 45])
        np.testing.assert_array_equal(targets(np.array([0, 20]), np.array([2, 0]), 10), [2, 8])
        np.testing.assert_array_equal(targets(np.array([15, 20]), np.array([1, 1]), 2), [1, 1])

    def test_minimum_distance_transport(self):
        centres = np.array([[0, 0], [100, 0], [11, 0], [90, 0]])
        self.assertEqual(transfers(np.array([2, 4, 1, 0]), np.array([0, 1, 3, 3]), centres),
                         {0: {2: 2}, 1: {3: 3}})

    def test_one_worker_moves_once_and_uncovered_and_protected_workers_stay(self):
        places = [[0, 0], [10, 0], [25, 0], [15, 1], [0, 4]]
        rows = [[0, 0, 4, 0, True], [0, 1, 4, 0, False], [0, 2, 4, 1, False],
                [0, 3, 4, 1, False], [0, 4, 4, 3, False]]
        report = allocate([row + [[]] for row in rows], places, ["A", "B"], np.array([1, 3]), np.array([0, 0, 1, -1, -1]),
                          np.array([1., 2., 4., 1., 0.]))
        self.assertEqual(report["after"], [1, 3])
        self.assertEqual(report["covered"], 4)
        self.assertEqual([row[1] for row in report["moves"]], [1, 2, 3])
        self.assertTrue(all(row[-1] == 2 for row in report["moves"]))

    def test_short_stop_limits_workplace_choice(self):
        places = [[0, 0], [5000, 0], [100, 0]]
        rows = [[0, 0, 2, 0, False, [[2, 1, "car-driver"]]]]
        report = allocate(rows, places, ["A", "B"], np.array([0, 10]), np.array([0, 1, -1]),
                          np.array([1., 1., 0.]))
        self.assertEqual(report["moves"], [])
        self.assertEqual(report["unfilled"], 1)

    def test_cycling_routes_require_the_direction_of_each_diary_leg(self):
        coords = np.array([[0, 0], [100, 0]])
        graph = {"nodes": coords.tolist(), "ways": [[8, 0, [0, 1]]]}
        reachable = active_route_check({"bike": graph}, coords)
        np.testing.assert_array_equal(reachable([1, 1], [[[0, 1, "bike", False]], [[0, 1, "bike", True]]]), [True, False])

    def test_workplace_move_can_recover_an_active_commute_within_its_tract(self):
        places = [[0, 0], [1800, 0], [50, 0]]
        graph = {"nodes": places, "ways": [[1, 0, [0, 2, 1]]]}
        rows = [[0, 0, 0, 1, False, [[0, 2, "walk", False], [0, 2, "walk", True]]]]
        report = allocate(rows, places, ["A"], np.array([1]), np.array([-1, 0, 0]), np.array([0., 1., 1.]),
                          networks={"walk": graph})
        self.assertEqual(report["moves"], [[0, 0, 1, 2]])
        self.assertEqual(report["after"], [1])
        self.assertEqual(report["activeRoutes"], {"workers": 1, "before": 0, "after": 1, "withinTract": 1})
