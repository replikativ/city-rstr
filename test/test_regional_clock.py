"""Cross-check the JVM export, routed legs and market clocks on a published day."""
import json
import unittest
from pathlib import Path


DATA = Path("public/data")


def read(file):
    return json.loads(file.read_bytes())


@unittest.skipUnless((DATA / "runs/current.json").exists(), "requires published regional data")
class RegionalClockTest(unittest.TestCase):
    def test_replay_and_groceries_use_the_same_agent_phase(self):
        run = next(r for r in read(DATA / "runs/current.json") if r.get("regionalWorkers"))
        region = DATA / "vancouver/region"
        overview = DATA / "overview"
        index = read(overview / (run["release"] + "-traces.json"))
        day = read(region / "cityday" / run["day"] / "day.json")
        atlas = read(region / "atlas" / run["atlas"] / "atlas.json")
        offsets, population = [], 0
        for da in day["das"]:
            offsets.append(population)
            population += atlas["das"][da]["population"]
        self.assertEqual(population, run["population"])

        def expected_phase(agent):
            return 5 * (((agent + 1) * 7919 % 10007) + .5) / 10007 - 2.5

        starts = set()
        for hour, digest in enumerate(index["hours"]):
            for leg in read(overview / (digest + ".json")):
                start = leg["times"][0]
                if hour * 60 <= start < (hour + 1) * 60 and start != 240:
                    source = round(start / 5) * 5
                    self.assertAlmostEqual(start - source, expected_phase(leg["agent"]))
                    starts.add(round(start % 5, 3))
        self.assertGreater(len(starts), 1000)

        path = region / "market" / (run["day"] + "_" + run["streets"])
        original = read(Path(str(path) + ".json"))["occasions"]
        continuous = read(Path(str(path) + "-continuous.json"))["occasions"]
        self.assertEqual(len(original), len(continuous))
        for before, after in zip(original, continuous):
            d, person = after[:2]
            self.assertEqual(before[:3], after[:3])
            self.assertAlmostEqual(after[3] - before[3], expected_phase(offsets[d] + person))
