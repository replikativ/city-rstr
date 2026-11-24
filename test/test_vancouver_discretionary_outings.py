import unittest

import numpy as np

from scripts.vancouver_discretionary_outings import SHOPPING, available_windows, place_outing


class DiscretionaryOutingsTest(unittest.TestCase):
    def test_existing_walks_split_available_time(self):
        self.assertEqual(list(available_windows([(470, 550), (780, 810)], [(460, 475), (500, 508), (805, 820)])),
                         [(475, 500), (508, 550), (780, 805)])

    def test_outing_needs_both_trip_legs_and_open_shop(self):
        donor = [(30, 480, 15, 25, 12)]
        rng = np.random.default_rng(2023)
        choices = [(7, 8, 13), (8, 8, 11)]
        result = place_outing([(460, 520)], choices, donor, SHOPPING, rng)
        self.assertIsNotNone(result)
        site, start, there, dwell, back, _ = result
        self.assertEqual(site, 8)
        self.assertGreaterEqual(start + there, 480)
        self.assertLessEqual(start + there + dwell + back, 520)
        # Outward and return fit the diary individually. A short outward leg
        # cannot compensate for a return that exceeds its recorded allowance.
        self.assertIsNone(place_outing([(460, 520)], choices[:1], donor, SHOPPING, rng))
        self.assertIsNone(place_outing([(1170, 1300)], [(8, 10, 11)], donor, SHOPPING, rng))
