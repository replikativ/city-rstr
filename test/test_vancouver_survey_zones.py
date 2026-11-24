import unittest

import numpy as np

from scripts.vancouver_survey_zones import classify


def rectangle(x, y, width, height):
    return np.array([(x, y), (x+width, y), (x+width, y+height), (x, y+height), (x, y)])


class ZoneCrosswalkTest(unittest.TestCase):
    def test_membership_holes_overlaps_and_distance_to_another_group(self):
        polygons = [(0, [rectangle(0, 0, 10, 10), rectangle(1, 1, 2, 2)]),
                    (0, [rectangle(10, 0, 10, 10)]), (1, [rectangle(20, 0, 10, 10)]),
                    (1, [rectangle(4, 4, 2, 2)])]
        points = [(2, 2), (5, 5), (10.1, 5), (18, 1), (17.9, 1), (21, 1), (33, 1)]
        zones, border = classify(points, polygons, 2)
        self.assertEqual(zones.tolist(), [-1, -2, 0, 0, 0, 1, -1])
        self.assertEqual(border.tolist(), [False, False, False, True, False, True, False])
