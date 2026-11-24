import unittest

from scripts.artifacts import write_json


class CycleCountsTest(unittest.TestCase):
    def test_junction_bound_respects_direction_access_and_survey_hours(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from scripts.vancouver_cycle_counts import add_junction_bounds
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            net, day = root/"cycling"/"g", root/"cityday"/"d"
            net.mkdir(parents=True); day.mkdir(parents=True)
            write_json(net/"network.json", dict(nodes=[[0,0],[40,0],[80,0]], ways=[[8,0,[0,1,2]]]))
            write_json(day/"places.json", [[-10,0],[90,0]])
            site = dict(key="junction", point=[40,0], hours=[8,10])
            report = dict(versions=dict(cycling="g", day="d"),sites=[site],runs={"city":{"sites":[{"counts":[0,0]}]}})
            # 10 m/min. A feasible rider can pass at 08:00 or exactly 10:00.
            legs = [["city",0,1,475,10,100],["city",0,1,595,10,100],
                    ["city",0,1,535,10,100],["city",1,0,475,10,100],
                    ["city",0,1,475,9,90]]
            add_junction_bounds(root, report, legs)
            self.assertEqual(report["runs"]["city"]["sites"][0]["reachable"], 2)
