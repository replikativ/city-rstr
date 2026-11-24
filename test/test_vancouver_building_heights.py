import unittest

import numpy as np

from scripts.vancouver_building_heights import estimate_height, matching_pixels


class BuildingHeightsTest(unittest.TestCase):
    def test_excludes_courtyards_and_the_outer_strip(self):
        outer = [[0,0],[8,0],[8,8],[0,8],[0,0]]
        courtyard = [[3,3],[3,5],[5,5],[5,3],[3,3]]
        pixels = {tuple(p) for p in matching_pixels([outer,courtyard])}
        self.assertNotIn((.5,4.5),pixels)
        self.assertNotIn((2.5,3.5),pixels)
        self.assertNotIn((4.5,4.5),pixels)
        self.assertIn((1.5,1.5),pixels)
        self.assertEqual(pixels,{tuple(p) for p in matching_pixels([outer[::-1],courtyard[::-1]])})

    def test_evidence_requires_coverage_and_a_consistent_roof(self):
        self.assertEqual(estimate_height(np.array([8.]*8+[58.])),([8.,9,0.],"supported"))
        self.assertEqual(estimate_height(np.array([8.]*8+[np.nan]*8)),(None,"insufficient pixels"))
        self.assertEqual(estimate_height(np.array([3.]*4+[15.]*4)),(None,"mixed elevations"))
        self.assertEqual(estimate_height(np.array([0.]*8)),(None,"no consistent elevated surface"))
