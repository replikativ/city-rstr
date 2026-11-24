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


class GeographicFootprintTest(unittest.TestCase):
    def test_block_populations_and_census_areas_outside_the_replay(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from zipfile import ZipFile
        from scripts.vancouver_census_geography import compare
        with TemporaryDirectory() as folder:
            path = Path(folder)/"gaf.zip"
            with ZipFile(path, "w") as z:
                z.writestr("2021_92-151_X.csv",
                           "DAUID_ADIDU,CSDUID_SDRIDU,CSDNAME_SDRNOM,DBPOP2021_IDPOP2021,DARPLONG_ADLONG,DARPLAT_ADLAT\n"
                           "a,x,City,10,1,2\na,x,City,7,1,2\nb,x,City,15,3,4\nc,y,Neighbour,12,5,6\n")
            ids, points, info = compare(["a", "c"], path, "x")
            self.assertEqual((ids, points), (["a", "c", "b"], [(1, 2), (5, 6), (3, 4)]))
            self.assertEqual(info["municipal"], [True, False, True])
            self.assertEqual((info["missing"], info["adjacent"]), ({"b": 15}, {"c": 12}))
            self.assertEqual(info["municipalPopulation"], 32)
            with self.assertRaisesRegex(ValueError, "population differ for a"):
                compare(["a", "b"], path, "x", profile_population={"a": 18, "b": 14})
