import random
import unittest

import networkx as nx
from scipy.spatial import cKDTree

from scripts.vancouver_pedestrians import passage_counts
from scripts.vancouver_walks import ORIGIN, can_reach_site, hourly_run, make_walks, passing_minute


class WalkingReplayTest(unittest.TestCase):
    def test_parallel_passage_count_preserves_hours_and_modes(self):
        points = [[-300, 0], [0, 0], [300, 0]]
        network = {"nodes": points, "ways": [[1, 0, [0, 1, 2]]]}
        sites = [{"point": [0, 0]}]
        legs = [["work", 0, 2, 420, 10, 750], ["shop", 2, 0, 477, 10, 750],
                ["work", 0, 2, 520, 5, 375]]
        serial = passage_counts(network, points, sites, legs, workers=1)
        self.assertEqual(serial, {(0, "work", 420): 1, (0, "shop", 480): 1})
        self.assertEqual(passage_counts(network, points, sites, legs, workers=2), serial)

    def test_passing_uses_distance_and_excludes_endpoints(self):
        # The segment crosses the site without placing a graph node in the buffer.
        path = [(-300, 0), (-100, 0), (100, 0)]
        self.assertEqual(passing_minute(path, (0, 0), 410, 20), 425)
        self.assertIsNone(passing_minute(path, (100, 0), 410, 20))
        self.assertIsNone(passing_minute(path, (0, 30), 410, 20))

    def test_home_remains_at_external_origin_on_return(self):
        graph = nx.path_graph(3)
        points = [(0, 0), (400, 0), (800, 0)]
        nx.set_node_attributes(graph, dict(enumerate(points)), "xy")
        nx.set_edge_attributes(graph, 400, "weight")
        tree = cKDTree(points)
        person = {"home": ORIGIN, "chain": [
            [240, 180, "sleep", "home"], [420, 10, "travel", "walk"],
            [430, 60, "shopping", "store"], [490, 10, "travel", "walk"],
            [500, 30, "eating", "home"]]}
        walks = list(make_walks(person, graph, lambda p: tree.query(p)[1],
                               {"store": cKDTree([points[-1]])}, random.Random(1), {}))
        self.assertEqual([w["points"] for w in walks], [points, points[::-1]])
        self.assertEqual([w["start"] for w in walks], [420, 490])


class SurveyWindowsTest(unittest.TestCase):
    def rows(self):
        header = ["Start Time"] + ["Peds"] * 4
        return [()] * 9 + [header] + [
            [f"{t//60:02}:{t%60:02}", 0, int(t == 600), 0, 0]
            for t in range(420, 660, 5)]

    def test_split_survey_preserves_measured_zeros_and_skips_padding(self):
        from scripts.vancouver_walks import survey_counts
        summary = ["Count Time:", "07:00\n10:00", "to", "08:00\n11:00"]
        windows, counts = survey_counts(summary, self.rows())
        self.assertEqual(windows, [[420, 480], [600, 660]])
        self.assertEqual(counts, [0]*12 + [1] + [0]*11)

    def test_missing_measured_bin_is_an_error(self):
        from scripts.vancouver_walks import survey_counts
        with self.assertRaisesRegex(ValueError, "do not cover"):
            survey_counts(["Count Time:", "07:00", "to", "11:00"], self.rows()[:-1])

class SeededSurveyTest(unittest.TestCase):
    def test_site_filter_includes_paths_grazing_buffer(self):
        self.assertTrue(can_reach_site((-300, 21), (300, 21), (0, 0), 600))
        self.assertFalse(can_reach_site((-300, 1000), (300, 1000), (0, 0), 600))

    def test_repeated_hours_keep_zero_and_skip_unobserved_break(self):
        study = {"windows": [[420, 540], [960, 1080]],
                 "events": [[421, 6.5, True], [480, 10, False], [1079.9, 2, True]]}
        self.assertEqual(hourly_run(study, 42), {"seed": 42, "hours": [6.5, 10, 0, 2]})


class WalkingReachTest(unittest.TestCase):
    def test_detour_limits_use_graph_distance_and_keep_scheduled_walks(self):
        from scripts.vancouver_walk_reach import network_bounds

        # A level path skirts the count circle. A branch reaches the circle midway along a link.
        network = {"nodes": [[-100, 30], [0, 30], [100, 30], [0, -30], [-100, -40], [100, -40]],
                   "ways": [[1, 0, [0, 1, 2]], [1, 0, [1, 3]], [1, 0, [4, 5]]]}
        site = {"point": [0, 0], "hours": [420, 480], "access": [1, 0], "egress": [0, 1]}
        walks = [["work", 0, 2, 478, 4, 320, 80, 200],
                 ["shopping", 4, 5, 478, 4, 320, 80, 200]]
        (strict, wider), = network_bounds(network, network["nodes"], [site], walks, 10)
        self.assertEqual((strict["unique"], strict["hourly"]), (2, [1, 1]))
        self.assertEqual((wider["unique"], wider["hourly"]), (3, [2, 2]))
        self.assertEqual(wider["byPurpose"], {"work": 1, "shopping": 0})
