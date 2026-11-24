import unittest

from scripts.vancouver_cityday import compile_day
from scripts.vancouver_streets import height, permissions


class CityDayTest(unittest.TestCase):
    def test_grouped_daily_plan_keeps_edge_travel_unlocated(self):
        template = compile_day([
            [240,10,"travel","walk"], [250,40,"sleep","home"],
            [290,20,"eating","home"], [310,5,"travel","walk"],
            [315,30,"travel","transit"], [345,12,"study","work-or-school"],
            [357,1323,"travel","travel-ns"]
        ])
        self.assertEqual(template["slots"],["home","school"])
        self.assertEqual(template["parts"],[
            [240,10,"walk",-1,0], [250,60,"stop",0,0], [310,35,"transit",0,1],
            [345,12,"stop",1,1], [357,1323,"travel-ns",1,-1]
        ])

    def test_access_bits_and_direction(self):
        self.assertEqual(permissions({"highway":"residential","oneway":"-1"}),5)
        self.assertEqual(permissions({"highway":"residential","oneway":"yes"}),3)
        self.assertEqual(permissions({"highway":"motorway"}),2)
        self.assertEqual(permissions({"highway":"service","access":"private","foot":"yes"}),1)
        self.assertEqual(permissions({"highway":"footway","area":"yes"}),0)

    def test_building_height_provenance(self):
        self.assertEqual(height({"height":"50 ft","building:levels":"2"}),(15.2,"height"))
        self.assertEqual(height({"building:levels":"4"}),(12,"levels"))
        self.assertEqual(height({"building":"house"}),(6,"assumed"))


class MobilityAuditTest(unittest.TestCase):
    def test_transit_access_legs_count_once_and_zero_trip_people_remain(self):
        from scripts.vancouver_mobility import MobilityAudit
        audit=MobilityAudit([{"episodes":[[240,10,"travel","walk"],[250,30,"travel","transit"],
                                         [280,5,"travel","walk"],[285,1395,"other","home"]]},
                             {"episodes":[[240,1440,"other","home"]]}])
        audit.add([[9,0],[3,1],[88,0],[9,0]],3)
        report=audit.report()
        self.assertEqual(report["main"]["modes"],{"Transit":1})
        self.assertEqual(report["main"]["people"],1.4)
        self.assertEqual(report["age45to49"]["rate"],1)
        self.assertEqual(report["unknownPrivateAge"],1)
