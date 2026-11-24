import unittest

import numpy as np

from scripts.vancouver_cycle_tours import assign_access, route_tours


class OutingTests(unittest.TestCase):
    def test_person_access_is_repeatable_and_respects_prior_riders(self):
        def draw():
            return assign_access([2, 4, 5, 8, 9], [0, 7, 11], 50, np.random.default_rng(34))
        self.assertEqual(list(draw()), list(draw()))
        self.assertEqual(len(set(draw())), 4)
        self.assertTrue({0, 7, 11}.issubset(draw()))
        with self.assertRaises(ValueError):
            assign_access([], [2, 4], 10, np.random.default_rng(0))

    def test_every_leg_has_to_fit_in_its_own_direction(self):
        net = {"nodes": [[0, 0], [80, 0], [0, 210]], "ways": [[8, 0, [0, 1, 2, 0]]]}
        coords = np.array(net["nodes"])
        def tour(i, legs):
            return [0, i, 1, "360", "Shopping", legs]
        candidates = [tour(0, [[500, 1, 0, 1], [518, 1, 1, 0]]),
                      tour(1, [[500, 1, 0, 1], [518, 3, 1, 0]]),
                      tour(2, [[500, 1, 0, -1], [518, 3, -1, 0]])]
        kept, stats = route_tours(candidates, coords, net)
        self.assertEqual(kept, [candidates[1]])
        self.assertEqual(stats["360"]["legs"], 2)
        self.assertEqual(stats["360"]["streetTimeExceededOrDisconnected"], 1)
        self.assertEqual(stats["360"]["unlocatedOrColocated"], 1)
