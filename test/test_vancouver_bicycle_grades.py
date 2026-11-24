import unittest

import numpy as np

from scripts.vancouver_bicycle_grades import build, estimate, surface
from scripts.vancouver_streets import encode_way
from scripts.vancouver_terrain import WORLD


class PlanarGround:
    def sample(self, xs, _ys):
        return .05 * (xs * 180 / WORLD + 123.1) * 72600


class BicycleGradeTest(unittest.TestCase):
    def test_short_geometry_segments_use_the_grade_of_the_local_way(self):
        grade = estimate([PlanarGround()], np.array([[0, 0], [2, 0], [62, 0], [80, 0]]))
        np.testing.assert_allclose(grade, [.05, .05, .05], atol=1e-10)
        self.assertTrue(np.isnan(estimate([PlanarGround()], np.array([[0, 0], [4, 0]]))[0]))

    def test_ground_grade_follows_travel_direction_and_excludes_bridge_decks(self):
        tags = {"highway": "cycleway"}
        way = dict(tags=tags, nodes=[5, 8], geometry=[
            {"lon": -123.1, "lat": 49.26}, {"lon": -123.099, "lat": 49.26}])
        nodes, names = [], {}
        encoded = encode_way(way, 24, nodes, {}, names)
        net = dict(nodes=nodes, names=list(names), ways=[encoded])
        self.assertEqual(build(net, [way], [PlanarGround()]), ([[0, 1, 2]], {"0": 1, "2": 1}))
        tags["bridge"] = "yes"
        self.assertEqual(build(net, [way], [PlanarGround()]), ([], {"unknown": 2}))
        self.assertFalse(surface({"layer": "-1"}))
        self.assertFalse(surface({"tunnel": "culvert"}))


if __name__ == "__main__":
    unittest.main()
