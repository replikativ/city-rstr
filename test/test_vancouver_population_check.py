import unittest
import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.vancouver_population_check import DA, benchmark, compare, roster_counts
from scripts.vancouver_census_geography import CITY, area_membership, profile_cells


class PopulationValidationTest(unittest.TestCase):
    def test_census_membership_and_suppressed_gender_cells(self):
        inside, outside = DA + "59153586", DA + "59154012"
        with TemporaryDirectory() as tmp:
            raw = Path(tmp)
            index = raw / "fixture_Geo_starting_row_BritishColumbia.CSV"
            index.write_text("\n".join(["Geo Code", CITY, inside, "2021A00055915802", outside]))
            with (raw / "fixture_data_BritishColumbia.csv").open("w", newline="") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
                for key, total in [(inside, 1105), (outside, 593)]:
                    writer.writerow([2021, key, *[""] * 6, 1, "", "", total, "", "", "", 50])
            self.assertEqual(area_membership(raw, {CITY[-7:]}), {"59153586": CITY[-7:]})
            self.assertEqual(profile_cells(raw, {inside}, {1}), {inside: {1: 1105}})
            self.assertEqual(profile_cells(raw, {inside, outside}, {1}, columns=(11, 13, 15)),
                             {inside: {1: [1105, None, 50]}, outside: {1: [593, None, 50]}})

    def test_private_household_universe_and_unavailable_income(self):
        def p(age, income, mode):
            return [age, 1, 1, income, 0, 1, mode, 0]
        roster = {"homes": [[0, 3, 1], [3, 1, 2]],
                  "people": [p(9, 115000, 3), p(6, -15000, 6), p(1, None, 9),
                             p(88, None, 9), p(7, 500000, 2)]}
        model = roster_counts(roster)
        self.assertEqual(model["income"].tolist(), [0, 0, 1, 0, 1])
        self.assertEqual(model["commute"].tolist(), [0, 0, 1, 0, 0, 1])

    def test_common_footprint_and_direct_municipal_denominator(self):
        model = {d: roster_counts({"homes": [[0, 1, 1]], "people": [[6, 2, 1, 110000, 0, 1, 6]]})
                 for d in ("1", "2")}
        ref = {DA + "1": {"commute": [75, 45, 5, 15, 5, 5, 5]}, DA + "2": {"commute": None}}
        result = compare(["1", "2"], model, ref, "commute")
        self.assertEqual((result["covered"], result["denominator"], sum(result["model"])), (1, 75, 1))
        self.assertIsNone(compare(["2"], model, ref, "commute"))
        city = compare(["1", "2"], model, ref, "commute", ref[DA + "1"]["commute"])
        self.assertTrue(city["direct"])
        self.assertEqual(sum(city["model"]), 2)
        cells = {i: 1 for i in range(2603, 2611)}
        cells[2608] = None
        self.assertIsNone(benchmark(cells, "commute"))

    def test_housing_averages_use_published_tenure_denominators(self):
        from scripts.vancouver_population_check import aggregate_housing
        rows = [{"ownerValue": [10, 400000], "tenantCost": [30, 1200]},
                {"ownerValue": [30, 800000]}, {"tenantCost": [10, 1600]}]
        self.assertEqual(aggregate_housing(rows), {"ownerValue": [40, 700000], "tenantCost": [40, 1300]})
