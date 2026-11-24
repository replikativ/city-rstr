import unittest

from scripts.vancouver_regional_inbound import split_stock


class RegionalInboundTest(unittest.TestCase):
    def test_partial_census_subdivision_uses_only_outside_home_areas(self):
        homes = [["covered", 0, 0, 40, 150], ["outside", 0, 0, 60, 50]]
        stock, candidates, basis = split_stock({"stock": 115}, homes, {"covered"})
        self.assertEqual(stock, 29)
        self.assertEqual(candidates, [homes[1]])
        self.assertEqual(basis, "out-of-municipality workers")

    def test_wholly_covered_origins_have_no_incoming_cohort(self):
        homes = [["covered", 0, 0, 20, 10], ["also covered", 0, 0, 20, 5]]
        stock, candidates, _ = split_stock({"stock": 30}, homes, {"covered", "also covered"})
        self.assertEqual(stock, 0)
        self.assertEqual(candidates, [])
