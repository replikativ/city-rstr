import unittest
import numpy as np

from scripts.vancouver_local_groceries import score
from scripts.vancouver_streets import walk_graph


class GroceryWalkTest(unittest.TestCase):
    def test_time_limits_store_hours_and_incumbent_ties(self):
        graph, snap = walk_graph(dict(nodes=[[0, 0], [400, 0], [800, 0], [1200, 0]],
                                     ways=[[1, "", [0, 1, 2, 3]]]))
        # Everyone departs from the same home and returns there.
        homes = np.zeros((4, 2), dtype=int)
        rows = [[0, i, 1, s, 20, a, b] for i, (s, a, b) in enumerate(
            [(600, 15, 15), (600, 5, 15), (1190, 15, 15), (600, 15, 6)])]
        counts, sites = score(graph, snap, [[0, 0], [1200, 0]], homes, rows, [dict(point=[800, 0])],
                              [dict(id="near", point=[400, 0]), dict(id="tie", point=[800, 0]),
                               dict(id="far", point=[1200, 0]), dict(id="home", point=[0, 0])])
        self.assertEqual(counts, [[1, 1], [1, 1]])
        self.assertEqual([r[-2] for r in rows], [0, -1, -1, -1])
        self.assertEqual(sites["near"]["visits"], [[0, 400.0], [2, 400.0]])
        self.assertEqual(sites["tie"]["visits"], [[2, 800.0]])
        self.assertEqual(sites["far"]["visits"], [])
        self.assertEqual(sites["home"]["visits"], [])


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
