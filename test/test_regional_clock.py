"""Cross-check the JVM export, routed legs and market clocks on a published day."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.diary_clock import phase_period
from scripts.vancouver_downtown import resident_flows


DATA = Path("public/data")


def read(file):
    return json.loads(file.read_bytes())


class RegionalFlowClockTest(unittest.TestCase):
    def test_shared_phase_can_move_a_trip_to_the_previous_hour(self):
        with TemporaryDirectory() as directory:
            day = Path(directory) / "day"
            atlas = Path(directory) / "atlas"
            day.mkdir()
            atlas.mkdir()
            (day / "day.json").write_text(json.dumps({
                "areas": ["Downtown", "Other"], "das": ["a", "b"],
                "templates": [{"parts": [[420, 60, "walk", 0, 1]]}],
            }))
            (atlas / "atlas.json").write_text(json.dumps({
                "areas": {"Downtown": {"das": ["a", "b"]}},
            }))
            for da in ("a", "b"):
                (day / f"{da}.json").write_text(json.dumps({"plans": [[0, 1]] * 2}))
                (atlas / f"{da}.json").write_text(json.dumps({"people": [[0] * 8] * 2}))
            places = [[0, 0, 0], [100, 0, 1]]
            rounded = resident_flows(day, atlas, places)["counts"]
            shared = resident_flows(day, atlas, places, shared_clock=True)["counts"]
            self.assertEqual([sum(rounded[h][0][1]) for h in (6, 7)], [0, 4])
            self.assertEqual([sum(shared[h][0][1]) for h in (6, 7)], [1, 3])


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

        phases = phase_period()

        starts = set()
        for hour, digest in enumerate(index["hours"]):
            for leg in read(overview / (digest + ".json")):
                start = leg["times"][0]
                if hour * 60 <= start < (hour + 1) * 60 and start != 240:
                    source = round(start / 5) * 5
                    self.assertAlmostEqual(start - source, phases[leg["agent"] % len(phases)])
                    starts.add(round(start % 5, 3))
        self.assertGreater(len(starts), 1000)

        path = region / "market" / (run["day"] + "_" + run["streets"])
        original = read(Path(str(path) + ".json"))["occasions"]
        continuous = read(Path(str(path) + "-continuous.json"))["occasions"]
        self.assertEqual(len(original), len(continuous))
        for before, after in zip(original, continuous):
            d, person = after[:2]
            self.assertEqual(before[:3], after[:3])
            self.assertAlmostEqual(after[3] - before[3], phases[(offsets[d] + person) % len(phases)])
