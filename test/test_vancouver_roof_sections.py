import importlib.util
import unittest

import numpy as np

from scripts.vancouver_building_heights import matching_pixels

if importlib.util.find_spec("shapely"):
    from shapely import union_all
    from shapely.geometry import Polygon
    from scripts.vancouver_roof_sections import predict, roof_sections


@unittest.skipUnless(importlib.util.find_spec("shapely"),"Roof section fitting uses Shapely")
class RoofSectionsTest(unittest.TestCase):
    def setUp(self):
        self.rings = [[[0,0],[32,0],[32,32],[0,32],[0,0]],[[3,3],[3,8],[8,8],[8,3],[3,3]]]
        self.points = matching_pixels(self.rings)
        self.ground = self.points[:,1]*.08

    def test_partitions_a_podium_and_tower_without_filling_the_courtyard(self):
        surface = np.where(self.points[:,0]<18,12.,38.)
        volumes,audit = roof_sections(self.rings,self.points,surface,self.ground,9,9,"assumed")
        self.assertEqual(len(volumes),2)
        self.assertAlmostEqual(volumes[1][0]-volumes[0][0],26)
        low,high = (shape for _,shape in volumes)
        self.assertAlmostEqual(low.intersection(high).area,0)
        self.assertAlmostEqual(union_all([low,high]).symmetric_difference(Polygon(self.rings[0],self.rings[1:])).area,0)
        positions,observed,reference_error = audit
        self.assertLess(abs(predict(volumes,positions)-observed).sum(),reference_error.sum()/3)

    def test_slope_in_the_ground_is_not_a_roof_step(self):
        ground = self.ground*5
        surface = np.full(len(ground),18.)
        self.assertIsNone(roof_sections(self.rings,self.points,surface,ground,9,9,"assumed"))

    def test_large_disagreement_with_a_published_height_keeps_the_flat_building(self):
        surface = np.where(self.points[:,0]<18,12.,38.)
        self.assertIsNone(roof_sections(self.rings,self.points,surface,self.ground,15,15,"height"))
