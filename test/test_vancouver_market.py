import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.vancouver_cityday import compile_day
from scripts.vancouver_streets import access_graph
from scripts.vancouver_household_market import household_band
from scripts.vancouver_housing_market import food_loss
from scripts.vancouver_market import publish_market, read, feasible, grocery_draw, locate, score, walk_graph, windows


class MarketTest(unittest.TestCase):
    def test_shelter_sensitivity_preserves_baseline_and_bounds_the_reduction(self):
        self.assertEqual(food_loss(8000, 1500, 50000, 0), 0)
        self.assertEqual(food_loss(8000, 1500, 50000, 10), 450)
        self.assertEqual(food_loss(8000, 1500, 15000, 10), 1800)
        self.assertEqual(food_loss(8000, 4000, 15000, 20), 8000)

    def test_cycle_store_requires_forward_access_and_onward_time(self):
        graph, snap = access_graph({"nodes": [[0, 0], [80, 0], [80, 200]], "ways": [[8, 0, [0, 1, 2, 0]]]}, 8, 16)
        coords = np.array([[0, 0], [80, 0], [80, 200]])
        nodes, offsets = snap(coords, lowest_id_on_ties=True)
        stops = [[0, i, 1, 600, 30, -1, None] for i in range(3)]
        # Via node 1, 0→1 is 80 m but 1→0 is over 400 m.
        choices, _ = score(stops, [[0, 0, 1, 1], [0, 0, 1, 3], [1, 2, 1, 2]], graph, snap, nodes,
                           offsets, [], [{"point": [80, 0]}], speed=220, directed=True, coords=coords)
        self.assertEqual([j for j, _ in choices[0]], [1])

    def test_late_storefront_keeps_diary_walk_limits_and_incumbent_ties(self):
        graph, snap = walk_graph({"nodes": [[0, 0], [80, 0], [160, 0]],
                                  "ways": [[1, 0, [0, 1, 2]]]})
        nodes, offsets = snap([[0, 0], [160, 0]])
        store = {"point": [80, 0]}
        stops = [[0, i, 1, start, 30, -1, None] for i, start in enumerate([1170, 1171, 1430, 1500])]
        daytime, extra = score(stops, [[0, 1, 2, 2]] * 3 + [[0, 1, 0, 2]],
                               graph, snap, nodes, offsets, [store], [store])
        self.assertEqual([row[5] for row in stops], [0, -1, -1, -1])
        self.assertEqual(daytime, [[]])
        self.assertEqual(extra, [[[1, 2.0], [2, 2.0]]])

    def test_publishing_a_new_market_retains_the_scored_catalogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = dict(atlas="population", day="weekday", streets="roads", occasions=[])
            publish_market(root, before)
            current = root / "market/weekday_roads.json"
            first = hashlib.sha256(current.read_bytes()).hexdigest()
            saved = root / "market/archive" / first
            publish_market(root, {**before, "occasions": [[0, 1]]})
            self.assertEqual(read(saved / "market.json"), before)
            self.assertEqual(hashlib.sha256((saved / "market.json").read_bytes()).hexdigest(), first)
            self.assertEqual(read(saved / "run.json")["market"], first)
            self.assertNotEqual(read(current), before)

    def test_filter_preserves_detailed_goods_and_two_pure_walking_legs(self):
        chain=[[240,300,"sleep","home"],[540,15,"travel","walk"],[555,35,"shopping","store"],
               [590,10,"travel","walk"],[600,1080,"paid-work","work-or-school"]]
        def select(rows,goods):
            return windows({"episodes":rows,"goods":goods},compile_day(rows))
        self.assertEqual(select(chain,[2]),[(1,555,35,0,2,15,10)])
        self.assertEqual(select(chain,[]),[])
        mixed=chain[:1]+[[540,3,"travel","transit"],[543,12,"travel","walk"]]+chain[2:]
        self.assertEqual(select(mixed,[3]),[])

    def test_workplace_changes_use_either_anchor_and_keep_missing_occasions_separate(self):
        places = [[0, 0, i] for i in range(4)]
        # An external worker also has an ordinary shopping outing on the same day.
        outings = [(0, 0, 2, 600, 15, 1, 0, 1, 3, 1, 2, 2, 10, 15, True),
                   (0, 0, 4, 800, 15, 1, 0, 0, 5, 1, 2, 2, 10, 15, True),
                   (0, 1, 2, 600, 15, 1, 0, 0, 3, 2, -1, 2, 10, 15, True),
                   (0, 2, 2, 600, 15, 1, 0, 0, 1, 1, 2, 2, 10, 15, True)]
        coverage, occasions, routes = locate(outings, places, {(0, 2, 1): 3},
                                             {"outside": [{0}], "paid": [{1}]})
        self.assertEqual(coverage, dict(qualifying=4, drawn=4, missing=1, external=1, externalDrawn=1, missingDrawn=1))
        self.assertEqual(routes, [[1, 2, 10, 15], [1, 3, 10, 15]])
        self.assertEqual([row[8:] for row in occasions], [[1, 2, 2, 10, 15, 1, 2, 0], [1, 2, 3, 10, 15, 1, 3, 0]])

    def test_fixed_legs_and_combined_budget(self):
        valid=feasible(np.array([160,240,2000]),np.array([240,160,2000]),
                       np.array([2,2,30]),np.array([3,3,30]))
        self.assertEqual(valid.tolist(),[True,False,False])

    def test_person_draw_is_stable_across_alternatives(self):
        draw=[grocery_draw("59150123",p,2) for p in range(100)]
        self.assertEqual(draw,[grocery_draw("59150123",p,2) for p in range(100)])
        self.assertGreater(sum(draw),0)
        self.assertLess(sum(draw),100)

    def test_network_keeps_duplicate_foot_edges_at_single_length(self):
        graph,snap=walk_graph({"nodes":[[0,0],[3,4],[4,4]],"ways":[[1,0,[0,1]],[1,1,[1,0]],[6,2,[1,2]]]})
        self.assertEqual(graph[0,1],5)
        self.assertEqual(graph[1,0],5)
        self.assertEqual(graph[1,2],0)
        vertex,offset=snap([4,4])
        self.assertEqual((vertex,offset),(1,1))

    def test_replay_snapping_breaks_multiway_ties_by_network_id(self):
        _, snap = walk_graph({"nodes": [[-1, 0], [0, -1], [1, 0], [10, 0]],
                              "ways": [[1, 0, [0, 3, 1, 2]]]})
        self.assertEqual(snap([0, 0], lowest_id_on_ties=True), (0, 1))
        ids, offsets = snap([[0, 0], [1, 0]], lowest_id_on_ties=True)
        self.assertEqual(ids.tolist(), [0, 2])
        self.assertEqual(offsets.tolist(), [1, 0])


    def test_household_before_tax_income(self):
        cuts = [40000, 70000, 100000, 155000]
        def person(age, income):
            return [age, 0, 0, income]
        self.assertEqual(household_band([person(7, 80000), person(5, -10000), person(2, None)], cuts), 2)
        self.assertEqual(household_band([person(7, 80000), person(3, None)], cuts), 5)
        self.assertEqual(household_band([person(88, None)], cuts), 5)
        self.assertEqual(household_band([person(2, None)], cuts), 5)
