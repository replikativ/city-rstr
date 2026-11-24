import unittest

import numpy as np

from scripts.vancouver_downtown_workplaces import allocate
from scripts.vancouver_commute_sensitivity import exchange_workplaces, reassign


class Travel:
    def __init__(self, feasible):
        self.allowed = feasible

    def feasible(self, worker, site):
        return (worker[1], site) in self.allowed


class DowntownWorkplacesTest(unittest.TestCase):
    def test_incoming_transit_swap_preserves_protected_jobs_and_both_distance_bands(self):
        places = [[0, 0], [100, 0], [1_000, 0], [2_500, 0], [3_050, 0]]
        core = [False, False, False, True, True]
        north = {("north", 0): ("north", 0, 480, 35, 0, 2, True)}
        wrong_band = ("south", 0, 490, 50, 1, 4, True)
        eligible = ("south", 1, 500, 45, 0, 3, True)
        protected = {("south", 2)}
        workers = {**north, ("south", 0): wrong_band, ("south", 1): eligible,
                   ("south", 2): ("south", 2, 490, 50, 0, 3, True)}
        strata = dict.fromkeys(workers, (1, 2))
        swaps, counts = exchange_workplaces(workers, places, core, {"north": (7, 3)}, strata, protected)
        self.assertEqual(swaps, {("north", 0): 3, ("south", 1): 2})
        self.assertEqual(counts["north"]["after"], 1)
        self.assertEqual(reassign(("north", 0, 1000, 35, 2, 0, False), swaps),
                         ("north", 0, 1000, 35, 3, 0, False))

    def test_swap_respects_occupation_and_both_diary_windows(self):
        cities = ["Vancouver", "City of North Vancouver", "District of North Vancouver", "West Vancouver"]
        points = np.array([[0, 0], [100, 0], [50, 0], [150, 0]])
        places = [[*p, i == 1] for i, p in enumerate(points)]
        areas = ["Other Vancouver", "Downtown"]

        def worker(i, home, job, occ):
            return [0, i, home, 0, job, [1], [[2, 10, "car-driver", 480, False]], occ]

        workers = [worker(0, 1, 0, 1), worker(1, 0, 1, 2), worker(2, 0, 1, 1)]
        rows, moves, pairs, modes = allocate(workers, cities, areas, places, points, Travel({(0, 1), (1, 0)}))
        self.assertEqual(rows[0]["target"], 1)
        self.assertFalse(pairs)
        allowed = Travel({(0, 1), (2, 0)})
        rows, moves, pairs, modes = allocate(workers, cities, areas, places, points, allowed)
        self.assertEqual(rows[0]["after"], 1)
        self.assertEqual(moves[0], [[0, [1], 0, 1], [2, [1], 1, 0]])
        self.assertEqual(modes, {"car-driver": 1})


if __name__ == "__main__":
    unittest.main()
