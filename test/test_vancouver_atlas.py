import json
import unittest

import numpy as np

from scripts.vancouver_atlas import LABELS, Weekday, adult, largest_remainder, size_plan, sums


class AtlasTest(unittest.TestCase):
    def test_combining_new_and_published_donor_counts_survives_json(self):
        row = dict(population=4, homes=1, private=4, unresolved=0, legacy=0, rawPrivate=4,
                   rawHomes=1, unknownAge=0, fit=[[0]*5 for _ in LABELS], days={0: 1, 2: 3})
        combined = sums([row, json.loads(json.dumps(row))])
        self.assertEqual(json.loads(json.dumps(combined))["days"], {"0": 2, "2": 6})
        with self.assertRaisesRegex(ValueError, "diary counts"):
            sums([{**row, "population": 5}])

    def test_absent_household_size_targets_cannot_expand_small_area(self):
        sizes=size_plan(2,2,[0]*5,np.ones(8))
        self.assertEqual(sizes.tolist(),[2,0,0,0,0,0,0,0])

    def test_rounding_conflicts_preserve_both_hard_counts(self):
        for people in [15,32,79,120]:
            sizes=size_plan(15,people,[10,5,0,5,0],np.ones(8))
            self.assertEqual(sum(sizes),15)
            self.assertEqual(sizes @ np.arange(1,9),people)
            self.assertTrue(all(sizes>=0))
        self.assertEqual(largest_remainder([1,1,0],1).tolist(),[1,0,0])

    def test_masked_age_keeps_observed_adult_status(self):
        self.assertTrue(adult([88,1,0,0,8,99,9]))
        self.assertFalse(adult([88,1,0,None,9,99,9]))

    def test_incomplete_diary_fails(self):
        with self.assertRaisesRegex(ValueError,"24 hours"):
            Weekday([{"age":"a15-24","role":"worker","weight":1,"episodes":[[240,30,"travel","walk"]]}])
