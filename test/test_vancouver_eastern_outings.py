import unittest

from scripts.vancouver_discretionary_outings import RECREATION, SHOPPING
from scripts.vancouver_eastern_outings import MODE, assign, eligible_residents, survey_limits
from scripts.vancouver_north_shore_demand import EASTERN_DESTINATION, NORTH_SHORE


class EasternOutingsTest(unittest.TestCase):
    def test_survey_ceiling_keeps_all_existing_eastern_work_and_scales_for_population(self):
        model = dict(residents=80, outbound={EASTERN_DESTINATION: [35]})
        survey = dict(residents=100, outbound={EASTERN_DESTINATION: 100})
        check = dict(outbound={EASTERN_DESTINATION: 120})
        evidence = dict(model={NORTH_SHORE: model}, observations={NORTH_SHORE: survey},
                        heldOut2025=dict(observations={NORTH_SHORE: check}))
        comparison, caps = survey_limits(evidence, [["North", SHOPPING, MODE, 12, 25, 8]], 3)
        self.assertEqual(comparison["scaledCeiling"]-comparison["assigned"]-comparison["attendance"], 42)
        self.assertEqual(comparison["check2025"], 120)
        self.assertEqual(caps["North", SHOPPING], 5)

    def test_candidate_preserves_protected_time_and_requires_both_drives_to_fit(self):
        model = dict(residents=[[0, 3, 100, 0, "North", True]], windows=[[(500, 650)]])
        candidates = list(eligible_residents(model, ["DA"], {("DA", 3): [(575, 650)]}, 60))
        self.assertEqual(candidates[0][-1], [(500, 575)])
        options = {(100, SHOPPING): [(200, 19, 21), (201, 20, 20)]}
        donors = {SHOPPING: [(7, 540, 20, 30, 20)], RECREATION: []}
        tours, counters = assign(candidates, options, donors, {("North", SHOPPING): 1, ("North", RECREATION): 0}, 1)
        self.assertEqual(len(tours), 1)
        self.assertEqual(tours[0][3], 201)
        self.assertLessEqual(sum(tours[0][6:10]), 575)
        self.assertEqual(counters["North", SHOPPING], 1)
