import unittest

import networkx as nx

from scripts.vancouver_grocery import PROFILES, SHARE, itinerary, opening_choice, scenario_counts, shop_day


class GroceryPilotTest(unittest.TestCase):
    def test_feasible_trip_respects_both_legs_dwell_wait_and_deadline(self):
        distances = {1:{2:160},3:{2:240}}
        shop = {"id":"x","name":"shop","node":2}
        trip = itinerary(1,3,shop,476,10,493,distances,[480,495])
        self.assertEqual([trip[k] for k in ("arrival","leave","end")],[478,490,493])
        self.assertIsNone(itinerary(1,3,shop,476,10,492,distances,[480,495]))
        self.assertIsNone(itinerary(1,3,shop,476,10,493,distances,[480,489]))
        self.assertIsNone(itinerary(1,3,shop,476,10,600,{1:{},3:{2:0}},[480,600]))

    def test_incumbent_wins_ties_and_preference_cannot_buy_time(self):
        incumbent, entrant = {"cost":7}, {"cost":9}
        self.assertIs(opening_choice(incumbent,entrant,2),incumbent)
        self.assertIs(opening_choice(incumbent,entrant,3),entrant)
        self.assertIs(opening_choice(incumbent,None,3),incumbent)

    def test_openings_conserve_demand_and_keep_paired_paths(self):
        graph = nx.path_graph(5)
        for n in graph:
            graph.nodes[n]["xy"] = (n*80,0)
        nx.set_edge_attributes(graph,80,"weight")
        def store(node):
            return dict(id=str(node),name=str(node),node=node,point=(node*80,0),grocery=True)
        person = {"id":"resident","age":"35-44","area":"Mount Pleasant","weight":10,"goods":[2],
                  "chain":[[240,270,"sleep","home"],[510,5,"travel","walk"],[515,10,"shopping","store"],
                           [525,5,"travel","walk"],[530,20,"eating","home"]]}
        anchors = [{0:0,2:3,4:0}]*2
        for shops in ([],[store(4)]):
            day = {p["id"]:scenario_counts() for p in PROFILES}
            examples = {}
            shop_day(person,2023,anchors,graph,shops,[store(1),store(2)],day,examples)
            base=day["standard"]
            self.assertEqual(base["eligible"],SHARE*10)
            self.assertEqual(base["eligible"],base["baseline"]+base["deferred"])
            for site in base["sites"]:
                self.assertEqual(site["visits"],site["gained"]+site["diverted"])
                self.assertEqual(site["visits"],SHARE*10)
                self.assertEqual(site["gained"],0 if shops else SHARE*10)
            self.assertEqual(day["hours"]["sites"][0]["visits"],0)
            example = next(iter(next(iter(examples.values())).values()))
            self.assertEqual(example["after"]["to"][0],example["after"]["onward"][-1])
            self.assertEqual(example["after"]["to"][-1],example["after"]["onward"][0])
