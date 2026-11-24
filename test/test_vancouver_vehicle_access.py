import unittest
from types import SimpleNamespace

from scripts.vancouver_transit_load import BusSpaces
from scripts.vancouver_vehicle_access import active_leg, active_paths, household_access, transit_tours


class VehicleAccessTest(unittest.TestCase):
    def test_all_members_share_the_assignment_and_unknown_income_keeps_original_access(self):
        def person(age, income):
            return [age, None, None, income]

        roster = {"homes": [[0, 2, 0], [2, 2, 0], [4, 2, 0]],
                  "people": [person(4, 12000), person(2, None), person(5, 20000), person(2, None),
                             person(4, 15000), person(5, None)]}
        flags, bands, summary = household_access([roster])
        self.assertEqual(flags, household_access([roster])[0])
        self.assertEqual([len(set(flags[0][i:i+2])) for i in (0, 2, 4)], [1, 1, 1])
        self.assertEqual(flags[0][4:], [0, 0])
        self.assertEqual(bands[0][:4], [0, 0, 0, 0])
        self.assertEqual(summary[0]["withVehicle"], 1)

    def test_cycling_path_rejects_wrong_way_and_contains_mapped_bend(self):
        network = {"nodes": [[0, 0], [0, 80], [120, 80]], "ways": [[8, 0, [0, 1, 2]]]}
        legs = [[480, 1, 0, 1], [515, 1, 1, 0]]
        paths = active_paths([[0, 0, 5, legs]], [[0, 0], [120, 80]], network, 220, 8, 16)
        self.assertEqual(active_leg(legs[0], paths, 220, "bike")[-1], network["nodes"])
        self.assertIsNone(active_leg(legs[1], paths, 220, "bike"))

    def test_incomplete_tour_retains_the_boarding_space_for_other_riders(self):
        spaces = BusSpaces({"bus": 1})
        spaces.preload([["bus", 0, 0, 1], ["bus", 0, 0, 1]])
        available = ["bus", 1, 0, 1, 8, 8]
        legs = [[480, 20, 0, 1], [520, 15, 1, 0]]
        service = SimpleNamespace(latest_departure=lambda *args: lambda *args: None)
        planner = SimpleNamespace(latest=lambda *args: None)
        tours = [(0, 0, 5, legs, [None, None])]
        choices = {(480, 500, 0, 1): (485, 490, available),
                   (520, 535, 1, 0): (525, 527, ["bus", 0, 0, 1, 8, 8])}
        self.assertEqual(transit_tours(tours, choices, planner, service, {}, spaces), [])
        self.assertTrue(spaces.fits(available))
        self.assertEqual(spaces.loads["bus", 0][0], 2)
