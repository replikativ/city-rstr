import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.sparse import csr_matrix

from scripts.vancouver_bridge_traffic import access_graph, hour_fields, ironworkers_observations, prune_bridge_candidates, score, score_window


class BridgeTrafficTest(unittest.TestCase):
    def test_resident_passages_use_the_drive_clock_and_keep_purposes_separate(self):
        points = [[-100, 0], [100, 0]]
        graph = dict(nodes=points, names=["Road"], ways=[[6, 0, [0, 1]]])
        profile = dict(kmh=[[12, 12]], connectorKmh=22.8, connectorMetres=500)
        arcs = {(0, 1): (0, 0, .5), (1, 0): (0, 1, .5)}
        legs = np.array([[1, 0, 1, 478, 15, 0, 12], [2, 1, 0, 958, 20, 0, 24]])
        sites = [{"name": "Counter"}]
        score_window(legs, points, graph, sites, ["DA"], scenarios=2, arcs=arcs, profile=profile, elapsed=True)
        work, other = sites[0]["scenarios"]
        self.assertEqual(work["examples"][0][7], ["DA", 12, 478.5, 478, 15, 0, 1])
        self.assertEqual(other["examples"][1][15], ["DA", 24, 958.5, 958, 20, 1, 0])
        self.assertEqual(work["counts"][1][15], 0)
        self.assertEqual(other["counts"][0][7], 0)

    def test_road_speeds_count_the_fastest_bridge_and_keep_diary_clock(self):
        places = [[0, 0], [0, 500]]
        network = {
            "nodes": [*places, [300, 0], [300, 500]],
            "names": ["Local bridge", "Fast bridge"],
            "ways": [[6, 0, [0, 1]], [6, 1, [0, 2, 3, 1]]],
        }
        screens = [
            ("local", "Local bridge", 250, ("Local bridge",), ("Southbound", "Northbound")),
            ("fast", "Fast bridge", 250, ("Fast bridge",), ("Southbound", "Northbound")),
        ]
        sites = [{"name": screen[1]} for screen in screens]
        legs = np.array([[1, 0, 1, 479, 4, 0, 0]])
        score(legs, places, network, sites, ["DA"], bridges=screens, scenarios=1)
        self.assertEqual(sites[0]["scenarios"][0]["counts"][0][8], 1)
        self.assertEqual(sites[1]["scenarios"][0]["counts"][0][8], 0)

        profile = {"kmh": [[15, 15], [90, 90]], "connectorKmh": 22.8, "connectorMetres": 500}
        required = {}
        _, searches = score(legs, places, network, sites, ["DA"], bridges=screens, scenarios=1,
                            required_crossing=required, profile=profile)
        self.assertEqual(searches, 0)
        self.assertEqual(required["fits"], 1)
        self.assertEqual(sites[0]["scenarios"][0]["counts"][0][8], 0)
        self.assertEqual(sites[1]["scenarios"][0]["examples"][0][8], ["DA", 0, 481.0])

    def test_ironworkers_monthly_report_averages_weekdays_with_export_padding(self):
        hours = [f"{hour:02d}:00" for hour in range(24)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shifted-report.csv"
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                for letter, value in (("E", 1500), ("W", 2500)):
                    writer.writerow([letter, "March 2025"])
                    writer.writerow([hours[0], "", *hours[1:], "Total"])
                    for day in range(1, 32):
                        weekend = day % 7 in (1, 2)
                        readings = [value + 1000 * weekend] * 24
                        writer.writerow([day, readings[0], "", *readings[1:], sum(readings)])
                    writer.writerow(["Month Total"])
            counters = ironworkers_observations(path)["counters"]
        self.assertEqual([row["days"] for row in counters], [21, 21])
        self.assertEqual([row["counts"] for row in counters], [[1500] * 24, [2500] * 24])

    def test_directional_observed_costs_use_the_departure_hour(self):
        points = [[0, 0], [0, 500], [300, 0], [300, 500]]
        network = dict(nodes=points, names=["Local", "Fast"], ways=[[6, 0, [0, 1]], [6, 1, [0, 2, 3, 1]]])
        bridges = [(name, name, 250, (name,), ("Southbound", "Northbound")) for name in network["names"]]
        sites = [dict(name=screen[1]) for screen in bridges]
        profile = dict(kmh=[[15, 15], [90, 90]], connectorKmh=22.8, connectorMetres=500,
                       hourly=dict(hours=[16], corridors=[dict(arcs=[[2, 3]], factors=[6])]))
        legs = np.array([
            [1, 0, 1, 959, 4, 0, 0],  # The crossing occurs after 16:00.
            [1, 0, 1, 960, 4, 0, 1],
            [1, 1, 0, 960, 4, 0, 2],
        ])
        required = {}
        coverage, _ = score(legs, points, network, sites, ["DA"], bridges=bridges, scenarios=1,
                            profile=profile, required_crossing=required)
        local, fast = [site["scenarios"][0] for site in sites]
        self.assertEqual(local["examples"][0][16], ["DA", 1, 962])
        self.assertEqual(fast["examples"][0][16], ["DA", 0, 961])
        self.assertEqual(fast["examples"][1][16], ["DA", 2, 962])
        self.assertEqual(coverage[0]["possibleBridge"], 3)
        self.assertEqual((required["legs"], required["fits"]), (3, 3))
        self.assertAlmostEqual(required["medianRoadMinutes"], 1100 / 1500)

    def test_pruning_keeps_a_tie_and_respects_one_way_connections(self):
        network = {
            "nodes": [[0, 0], [3, 0], [7, 0]],
            "names": ["One way"],
            "ways": [[2, 0, [0, 1, 2]]],
        }
        graph, _ = access_graph(network, 2, 4)
        kept = prune_bridge_candidates(np.arange(3), np.array([8, 7, 8]),
                                      np.array([0, 0, 2]), np.array([2, 2, 0]),
                                      graph, graph.T.tocsr(), network["nodes"])
        self.assertEqual(kept.tolist(), [1, 2])

    def test_published_hour_fields_cover_one_day(self):
        fields = hour_fields()
        self.assertEqual(len(set(fields)), 24)
        self.assertEqual(fields[0], "F_1200am_0100am")
        self.assertEqual(fields[10], "F_10000am_1100am")
        self.assertEqual(fields[-1], "F_1100pm_1200am")

    def test_counts_crossing_minute_on_a_directed_shortest_path(self):
        places = [[0, 200], [0, 0], [700, 200]]
        network = {
            "nodes": [[0, 200], [0, 0], [120, 120], [120, 80]],
            "names": ["Bridge", "Approaches", "Bypass"],
            "ways": [[6, 0, [2, 3]], [6, 1, [0, 2]], [6, 1, [3, 1]]],
        }
        legs = np.asarray([
            [7, 0, 1, 478, 10, 0, 12],
            [1, 1, 0, 958, 10, 0, 20],
            [8, 2, 1, 480, 60, -1, -1],
        ])
        bridges = [("bridge", "Bridge", 100, ("Bridge",), ("Southbound", "Northbound"))]
        with patch("scripts.vancouver_bridge_traffic.BRIDGES", bridges):
            sites = [{"name": "Bridge"}]
            required = {}
            coverage, _ = score(legs, places, network, sites, ["DA"], required_crossing=required)
            report = sites[0]["scenarios"]
            self.assertEqual(report[0]["counts"][1][8], 1)
            self.assertEqual(report[0]["counts"][0][16], 1)
            self.assertEqual(report[0]["examples"][1][8], ["DA", 12, 483.0])
            self.assertEqual(report[1]["counts"][0][16], 0)
            self.assertEqual(coverage[3]["snapped"], 0)
            self.assertEqual((required["legs"], required["fits"]), (2, 2))

            regional = [{"name": "Bridge"}]
            regional_coverage, _ = score(legs[:2], places, network, regional, ["DA"],
                                         bridges=bridges, scenarios=1)
            self.assertEqual(regional[0]["scenarios"], [report[0]])
            self.assertEqual(regional_coverage, [coverage[0]])

            network["ways"].append([6, 2, [0, 1]])
            required = {}
            score(legs, places, network, sites, ["DA"], required_crossing=required)
            self.assertEqual(sum(sum(group) for group in sites[0]["scenarios"][0]["counts"]), 0)
            self.assertEqual(required, {"legs": 0, "fits": 0})
