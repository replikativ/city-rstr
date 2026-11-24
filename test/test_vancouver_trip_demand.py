import unittest

from scripts.vancouver_cityday import compile_day
from scripts.vancouver_north_shore_demand import trip_inputs
from scripts.vancouver_trip_demand import trip_terms


class TripDemandTest(unittest.TestCase):
    def test_linked_transit_and_ambiguous_loop(self):
        episodes = [[240, 10, "sleep", "home"], [250, 5, "travel", "walk"],
                    [255, 3, "travel", "transit"], [258, 10, "shopping", "store"],
                    [268, 4, "travel", "walk"], [272, 8, "eating", "home"],
                    [280, 8, "sports", "bike"], [288, 10, "media", "home"],
                    [298, 3, "travel", "bike"]]
        terms = trip_terms({"episodes": episodes}, compile_day(episodes))
        self.assertEqual([(m, p) for m, p, *_ in terms], [
            ("Transit", "Shopping"), ("Walking", "Return home"), ("Cycling", "Other or unclear"),
            ("Cycling", "Other or unclear")])
        self.assertFalse(terms[0][-1])
        self.assertEqual(terms[-1][4], -1)

    def test_north_shore_mode_purpose_departure_and_unrecorded_change(self):
        episodes = [[240, 240, "sleep", "home"], [480, 10, "travel", "taxi"],
                    [490, 70, "study", "work-or-school"], [560, 20, "personal-care", "clinic"],
                    [580, 7, "travel", "car-driver"], [587, 3, "travel", "transit"],
                    [590, 60, "eating", "home"]]
        trips, gaps = trip_inputs({"episodes": episodes}, compile_day(episodes))
        self.assertEqual(trips, [
            ["Other / unspecified", "Education", 8, 485, 0, 1, True],
            ["Transit", "Return home", 9, 585, 2, 3, False],
        ])
        self.assertEqual(gaps, [[1, 2]])
