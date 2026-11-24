import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import csv
import io
import json

import numpy as np

from scripts.vancouver_outbound import AGE_ROWS, eligible, observed_modes, commute_pairs, route_distances
from scripts.vancouver_cycling import directions, FORWARD, REVERSE


class OutboundWorkplaceTest(unittest.TestCase):
    def test_bicycle_access_and_direction_override(self):
        street = {"highway":"residential","oneway":"yes"}
        self.assertEqual(directions(street), FORWARD)
        self.assertEqual(directions({**street,"oneway:bicycle":"no"}), FORWARD | REVERSE)
        self.assertEqual(directions({**street,"oneway:bicycle":"-1"}), REVERSE)
        self.assertEqual(directions({**street,"cycleway":"opposite_lane"}), FORWARD | REVERSE)
        self.assertEqual(directions({**street,"bicycle":"dismount"}), 0)
        self.assertEqual(directions({"highway":"cycleway","access":"private"}), 0)
        self.assertEqual(directions({"highway":"footway"}), 0)
        self.assertEqual(directions({"highway":"footway","bicycle":"designated"}), FORWARD | REVERSE)

    def test_cycling_budget_respects_direction_to_and_from_the_job(self):
        points = [[0,0],[10,0],[10,20],[0,20]]
        network = {"nodes":points, "ways":[[FORWARD,0,[0,1,2,3,0]]]}
        # Starting the search at the job requires reversing the graph for the trip to work.
        requests = {(0,1,False):1, (1,0,True):1}
        self.assertEqual(route_distances(requests, points, network, 15, FORWARD, REVERSE),
                         [[0,1,10.0]])
        self.assertEqual(route_distances(requests, points, network, 50, FORWARD, REVERSE),
                         [[0,1,10.0],[1,0,50.0]])

    def test_pedestrian_budget_includes_detour_and_access_at_both_ends(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            atlas, day, streets = [root/name for name in ("atlas", "day", "streets")]
            for path in (atlas, day, streets):
                path.mkdir()
            def write(path, data):
                path.write_text(json.dumps(data))
            write(day/"places.json", [[-5,0], [55,0]])
            write(streets/"network.json", {"nodes": [[0,0],[0,50],[50,50],[50,0]],
                                           "ways": [[1,0,[0,1,2,3]], [2,0,[0,3]]]})
            write(atlas/"da.json", {"people": [[0,0,0,0,0,0,2,0]]})
            write(day/"da.json", {"plans": [[0,1]]})
            for minutes, expected in [(2, []), (3, [[0,1,160.0]])]:
                write(day/"day.json", {"das": ["da"], "templates": [
                    {"slots": ["home","job"], "parts": [[540,minutes,"walk",1,0]]}]})
                self.assertEqual(route_distances(commute_pairs(atlas,day), [[-5,0],[55,0]],
                                                 json.loads((streets/"network.json").read_text()), 75, 1, 1), expected)

    def test_age_cross_tab_keeps_disjoint_external_destinations(self):
        csv_file = io.StringIO()
        writer = csv.writer(csv_file)
        header = ["REF_DATE", "GEO", "DGUID", "Age (15A)", "Gender (3)", "Statistics (3)",
                  "Main mode of commuting (11A)", "Coordinate"]
        for category in ["Total", "Commute within CSD", "Commute to a different CSD",
                         "Commute to a different CD", "Commute to a different province"]:
            header.extend(["Commuting destination (5):"+category, "Symbol"])
        writer.writerow(header)
        for age in [*AGE_ROWS, "25 to 64 years"]:
            for mode in ["Driver (only worker in vehicle)", "Passenger (only worker in vehicle)",
                         "Driver with 1 or more workers", "Passenger with 2 or more workers",
                         "Public transit", "Active transportation", "Other method"]:
                writer.writerow([2021, "Vancouver", "2021A00055915022", age, "Total - Gender", "Count", mode,
                                 1, 100, "", 70, "", 20, "", 5, "", 5, ""])
        with TemporaryDirectory() as directory:
            path = Path(directory)/"modes.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("98100462.csv", csv_file.getvalue())
            result = observed_modes(path)
        self.assertEqual(set(result), set(AGE_ROWS.values()))
        self.assertEqual(result["15–24"], {"Car driver": 60, "Car passenger": 60, "Public transit": 30,
                                         "Walking or bicycle": 30, "Other": 30})

    def test_status_from_whole_private_household(self):
        a, b = [5, 1, 1, 30000, 2, 5, 6], [6, 2, 1, 40000, 2, 7, 2]
        roster = dict(people=[a+[0], b+[0], a+[0]], homes=[[0, 2, 1]])
        index = {(1, (tuple(a), tuple(b))): Counter({(5, 1): 1})}
        self.assertEqual(eligible(roster, index, np.random.default_rng(1)), ([(0, 1, 5)], 0))
