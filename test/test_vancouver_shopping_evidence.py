import unittest

from scripts.vancouver_shopping_evidence import clocks, shopping_arrivals


class ShoppingEvidenceTest(unittest.TestCase):
    def test_clock_weights_repeat_stops_by_respondent(self):
        def diary(weight, starts):
            episodes = [[240, starts[0]-250, "housework", "home"]]
            goods = []
            for j, s in enumerate(starts):
                episodes.append([s-10, 10, "travel", "bike"])
                goods.append(len(episodes))
                episodes.extend([[s, 20, "shopping", "store"], [s+20, 10, "travel", "bike"],
                                 [s+30, (starts[j+1]-10 if j+1 < len(starts) else 1680)-s-30, "housework", "home"]])
            return dict(pool="sample", goods=goods, weight=weight, episodes=episodes)
        group = clocks([diary(1, [600, 800]), diary(2, [600])])["sample"]["modes"]["bike"]
        self.assertEqual((group["donors"], group["occasions"], group["effective"]), (2, 3, 2))
        self.assertEqual(group["clock"], [[600, 20, .75], [800, 20, .25]])

    def test_only_arrivals_at_shopping_switch(self):
        diary = {"episodes": [[240, 60, "sleep", "home"], [300, 10, "travel", "car-driver"],
                              [310, 20, "shopping", "store"], [330, 15, "travel", "car-driver"],
                              [345, 30, "housework", "home"]]}
        trips = [[0, 1, 0, "210", "Shopping", [[300, 10, 1, 2], [330, 15, 2, 1]], True]]
        outcome = shopping_arrivals([["210", "Auto driver", "Shopping", 5]], trips, [diary])
        self.assertEqual(outcome["switchedFifths"], {"ride": 5, "access": 5})

    def test_2010_requires_in_person_food_at_a_grocer_and_matching_legs(self):
        from scripts.vancouver_grocery_survey import occasions
        def stops(place, code, out):
            return [(1, b"450.0", 1, 240, 20), (17, b"390.0", 1, 260, 5),
                    (place, code, 1, 265, 10), (out, b"390.0", 1, 275, 5),
                    (1, b"450.0", 1, 280, 30)]
        self.assertEqual(list(occasions(stops(6, b"301.0", 17))), [("bike", True, 1, 265, 10)])
        self.assertEqual(list(occasions(stops(7, b"301.0", 17))), [("bike", False, 1, 265, 10)])
        self.assertEqual(list(occasions(stops(6, b"302.3", 17))), [])
        self.assertEqual(list(occasions(stops(6, b"301.0", 12))), [])
