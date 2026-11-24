import unittest

from scripts.vancouver_bikeways import match


class CityBikewaysTest(unittest.TestCase):
    def test_excludes_other_streets_later_construction_and_the_unsupported_direction(self):
        def segment(y, construction):
            coords = [[-123.1+x/72600, 49.26-y/111195] for x in (0, 100)]
            return dict(geometry=dict(coordinates=coords), properties=dict(
                street_name="W 10th Ave", bike_route_name="10th Ave", bikeway_type="Local Street",
                status="Active", year_of_construction=construction, upgrade_year=None,
                overall_direction="EW", e_s_bound_type="Local Street", w_n_bound_type=None))
        net = dict(nodes=[[0,0],[100,0],[0,2],[100,2],[0,60],[100,60],[50,-50],[50,50]],
                   names=["West 10th Avenue","Other Street"],
                   ways=[[24,0,[0,1]],[24,1,[2,3]],[24,0,[4,5]],[24,0,[6,7]]])
        model = match(net, [segment(0, "2002"), segment(60, "2024")])
        self.assertEqual(model["arcs"], [(0,1)])
        self.assertEqual(model["eligible"], 1)
        self.assertEqual(model["matchedKm"], 0.1)

    def test_junction_bound_respects_direction_access_and_survey_hours(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from scripts.vancouver_atlas import write_json
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
