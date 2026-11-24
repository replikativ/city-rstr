"""Route recorded and additional home-based recreational walks on regional streets."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import largest_remainder, write_json
from scripts.vancouver_discretionary_outings import WALK_SPEED, available_windows, read_opportunities, verify_intervals
from scripts.vancouver_flexible_transit import protected_intervals
from scripts.vancouver_north_shore_demand import NORTH_SHORE, SURVEY_ROWS, SURVEY_2025, SURVEY_2025_ARCHIVE
from scripts.vancouver_north_shore_demand import SURVEY_2025_DIGEST, held_out_rows, verify_survey
from scripts.vancouver_region import package, read
from scripts.vancouver_streets import walk_graph
from scripts.vancouver_transit_commutes import pointer

WORKPLACE_RUN = "06c504c638de40f775a7"
SEED = 202540
LOOP_FRACTION = 0.04  # Expected share of all trips, North Shore survey section 5.3.
WALK_FRACTION = 0.49  # Figure 31, all recreation purposes, used as a scenario prior.
MIN_WALK_PACE = 60  # metres per minute
MAX_DONOR_SHIFT = 60  # minutes from an observed exercise start
TUS_SOURCE = "https://www150.statcan.gc.ca/n1/en/catalogue/45250001"


class LoopRouter:
    def __init__(self, network, places, rng):
        self.graph, snap = walk_graph(network)
        self.nodes, self.rng = network["nodes"], rng
        self.homes = [p[:2] for p in places]
        self.snaps, self.offsets = snap(self.homes, lowest_id_on_ties=True)

    @staticmethod
    def stem(previous, root, node):
        branch = [node]
        while node != root:
            node = int(previous[node])
            branch.append(node)
        return branch[::-1]

    @lru_cache(maxsize=16384)
    def loop(self, home, minutes):
        attachment = float(self.offsets[home])
        limit = WALK_SPEED * minutes - 2 * attachment
        if attachment > 500 or limit <= 0:
            return None
        root = int(self.snaps[home])
        lengths, previous = dijkstra(self.graph, indices=root, limit=limit / 2 + 1e-8,
                                     return_predecessors=True)
        nearby = np.flatnonzero(np.isfinite(lengths))
        edges = self.graph[nearby]
        a = np.repeat(nearby, np.diff(edges.indptr))
        b = edges.indices
        distances = lengths[a] + lengths[b] + edges.data
        minimum = MIN_WALK_PACE * minutes - 2 * attachment
        circuits = np.flatnonzero((a < b) & (previous[a] != b) & (previous[b] != a) &
                                   (distances >= minimum) & (distances <= limit))
        if circuits.size:
            # Draw among circuits near the desired distance, including several
            # directions from the same walkable access node.
            nearest = circuits[np.argsort(distances[circuits], kind="stable")[-16:]]
            edge = self.rng.choice(nearest)
            route = self.stem(previous, root, int(a[edge])) + self.stem(previous, root, int(b[edge]))[::-1]
            kind, length = "circuit", float(distances[edge])
        else:
            reachable = nearby[(2 * lengths[nearby] >= minimum) & (lengths[nearby] > 0) &
                               (2 * lengths[nearby] <= limit)]
            if not reachable.size:
                return None
            closest = reachable[np.argsort(lengths[reachable], kind="stable")[-16:]]
            turn = int(self.rng.choice(closest))
            outbound = self.stem(previous, root, turn)
            route = outbound + outbound[-2::-1]
            kind, length = "out-and-back", float(2 * lengths[turn])
        path = [self.homes[home], *(self.nodes[i] for i in route), self.homes[home]]
        vertices = [point for i, point in enumerate(path) if i == 0 or point != path[i - 1]]
        return kind, vertices, round(length + 2 * attachment, 2)


class ExerciseDonors:
    def __init__(self, donors, total=None):
        profiles = [(start, length, donor["weight"]) for donor in donors if donor["weight"] > 0
                    for start, length in donor["bouts"] if length > 0]
        self.starts, self.durations, self.weights = (np.asarray(values) for values in zip(*profiles, strict=True))
        self.responseCount = len(donors)
        self.target = None if total is None else largest_remainder(self.weights, total)
        self.remaining = None if self.target is None else self.target.copy()

    def sample(self, free, rng):
        if not free:
            return None
        first, last = np.array(free).T[:, :, None]
        latest = last - self.durations
        if self.remaining is not None:
            hour = self.starts // 60 * 60
            first = np.maximum(first, hour)
            latest = np.minimum(latest, hour + 59)
        shifted = np.clip(self.starts, first, latest)
        displacement = np.abs(shifted - self.starts)
        valid = (latest >= first) & (displacement <= MAX_DONOR_SHIFT)
        costs = np.where(valid, displacement, np.inf)
        best = np.argmin(costs, axis=0)
        columns = np.arange(len(self.starts))
        weights = (self.weights if self.remaining is None else self.remaining) * np.exp(-costs[best, columns] / MAX_DONOR_SHIFT)
        mass = weights.sum()
        if mass == 0:
            return None
        i = rng.choice(len(weights), p=weights / mass)
        start = int(shifted[best[i], i])
        if self.remaining is not None:
            lo = max(start - 7, first[best[i], i])
            hi = min(start + 7, latest[best[i], i])
            start = int(rng.integers(lo, hi + 1))
        return start, int(self.durations[i]), int(self.starts[i]), i


def reservations(region, versions, day, occupancy):
    outing_dir = region / "discretionary-outings"
    outing_key = versions["atlas"] + "_" + versions["day"] + ".json"
    outing_version = read(outing_dir / outing_key)["version"]
    outing = read(outing_dir / outing_version / "report.json")
    if any(outing["versions"][key] != versions[key] for key in ("atlas", "day", "streets")):
        raise ValueError("Loops and outings must use the same weekday and network")
    protected = protected_intervals(region, versions, day, outing_version)
    flex_key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    flex_index = region / "work-transit-flex" / (flex_key + ".json")
    flex_version = None
    if flex_index.is_file():
        flex_version = read(flex_index)["version"]
        clock = read(region / "household-clock" / flex_version / "clock.json")
        if any(clock[k] != versions[k] for k in ("atlas", "day", "streets")):
            raise ValueError("Recreation and flexible transit must use the same weekday")
        base_templates = day["templates"]
        for da, edits in clock["changes"].items():
            for person, old, revised in edits:
                original = base_templates[old]["parts"]
                chosen = clock["templates"][revised - len(base_templates)]["day"]["parts"]
                for (start, length, mode, *_), (now, duration, *_) in zip(original, chosen, strict=True):
                    if mode != "stop" and [start, length] != [now, duration]:
                        protected[da, person].append((now, now + duration))
        occupancy = np.asarray(clock["occupancy"])
    walk_path = region / "short-walks" / (versions["day"] + "_" + versions["streets"] + ".json")
    occupancy = occupancy + np.asarray(outing["occupancyDelta"])
    walking = None
    if walk_path.is_file():
        walks = read(walk_path)
        occupancy += np.asarray(walks["occupancyDelta"])
        walking = hashlib.sha256(walk_path.read_bytes()).hexdigest()
    return protected, occupancy, dict(outings=outing_version, flexibleTransit=flex_version, shortWalkDigest=walking)


def population_targets(evidence):
    residents = {group: evidence["model"][group]["residents"] for group in SURVEY_ROWS}
    source = held_out_rows()["North Shore"]
    assumed_rate = source["trips"] / source["residents"] * LOOP_FRACTION * WALK_FRACTION
    total = sum(residents.values())
    counts = largest_remainder(np.array(list(residents.values())) * assumed_rate, round(total * assumed_rate))
    return dict(zip(residents, map(int, counts), strict=True)), residents, source


def fit(opportunities, targets, router, donors, protected, das, rng):
    recorded = Counter()
    routed_recorded = Counter()
    has_recorded = set()
    result = []
    for d, i, home, start, duration, age, municipality in opportunities["recorded"]:
        has_recorded.add((d, i))
        recorded[municipality] += 1
        route = router.loop(home, duration)
        if route:
            routed_recorded[municipality] += 1
            result.append([d, i, home, start, duration, False, *route, start])
    print("Recorded home-to-home trips", sum(recorded.values()), "street routes", sum(routed_recorded.values()), flush=True)
    added = Counter()
    ages = Counter()
    no_route = missing_time = 0
    residents = opportunities["residents"]
    windows = opportunities["windows"]
    for j in rng.permutation(len(residents)):
        if all(recorded[name] + added[name] >= target for name, target in targets.items()):
            break
        d, i, home, template, municipality, _, age = residents[j]
        if (d, i) in has_recorded or home < 0 or recorded[municipality] + added[municipality] >= targets[municipality]:
            continue
        free = list(available_windows(windows[template], sorted(protected.get((das[d], i), ()))))
        plan = donors.sample(free, rng)
        if plan is None:
            missing_time += 1
            continue
        start, duration, donor_start, donor_index = plan
        route = router.loop(home, duration)
        if not route:
            no_route += 1
            continue
        result.append([d, i, home, start, duration, True, *route, donor_start])
        if donors.remaining is not None:
            donors.remaining[donor_index] -= 1
        added[municipality] += 1
        ages[age] += 1
        if sum(added.values()) % 3000 == 0:
            print(f"Placed {sum(added.values()):,} added loops.", flush=True)
    breakdown = {name: dict(recorded=recorded[name], recordedRouted=routed_recorded[name],
                            added=added[name], target=targets[name]) for name in targets}
    return result, breakdown, dict(noRoute=no_route, noFreeTime=missing_time, ageCounts=dict(sorted(ages.items())))


def verify_loop_clock(loops, places, occupancy, scratch, backend):
    cols = occupancy.shape[1]
    delta = np.zeros((1441, cols), dtype=np.int32)
    schedules = []
    for _, _, home, start, duration, added, *_ in loops:
        if not added:
            continue
        area = places[home][2]
        a, b = start - 240, start + duration - 240
        if not (0 <= a < b <= 1440 and 0 <= area < cols - 2):
            raise ValueError("A recreation loop has an invalid day interval or home")
        delta[a:b, area] -= 1
        delta[a:b, cols - 2] += 1
        schedules.append(((a * cols + area, b * cols + area, cols - 2 - area),))
    return verify_intervals(schedules, delta, occupancy, scratch, backend)


def publish_loops(root, report, loops, day):
    by_da = defaultdict(list)
    sample = {(d, i) for d, i, *_ in day["sample"]}
    sampled = []
    for row in sorted(loops, key=lambda r: (r[0], r[1], r[3])):
        d, i, *_ = row
        by_da[day["das"][d]].append(row)
        if (d, i) in sample:
            sampled.append(row)
    examples = {}
    for name, added in (("recorded", False), ("added", True)):
        best = min((row for row in loops if row[5] == added),
                   key=lambda r: (r[6] != "circuit", abs(r[3] - 1020), r[0], r[1]), default=None)
        if best:
            examples[name] = best
    report.update(areas=sorted(by_da), kinds=dict(Counter(row[6] for row in loops)),
                  examples=examples, total=len(loops))

    def write(directory):
        write_json(directory / "report.json", report)
        write_json(directory / "sample.json", sampled)
        for area, rows in by_da.items():
            write_json(directory / f"{area}.json", rows)

    return package(root, "recreation-loops", write)


def publish(region, archive, workplace_run, backend):
    verify_survey(SURVEY_2025_ARCHIVE, SURVEY_2025_DIGEST)
    parent = read(region / "regional-workplaces" / workplace_run / "report.json")
    versions = dict(parent["versions"], day=parent["day"])
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    da = region / "cityday" / versions["day"]
    atlas = region / "atlas" / versions["atlas"]
    day, places = read(da / "day.json"), read(da / "places.json")
    demand = region / "north-shore-demand"
    evidence = read(demand / read(demand / (versions["atlas"] + "_" + versions["day"] + ".json"))["version"] / "report.json")
    targets, residents, source = population_targets(evidence)
    if sum(residents.values()) != evidence["model"][NORTH_SHORE]["residents"]:
        raise ValueError("North Shore adult population does not reconcile")
    protected, occupancy, shared = reservations(region, versions, day, np.asarray(day["occupancy"]))
    rng = np.random.default_rng(SEED)
    router = LoopRouter(read(region / "streets" / versions["streets"] / "network.json"), places, rng)
    with tempfile.TemporaryDirectory() as folder:
        scratch = Path(folder)
        donor_file = scratch / "exercise.json"
        with donor_file.open("w") as f:
            subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.atlas-diaries", archive,
                            "--outdoor-exercise"], stdout=f, check=True)
        donors = ExerciseDonors(read(donor_file))
        opportunities = read_opportunities(atlas, da, scratch, detail="with-loops")
        loops, breakdown, misses = fit(opportunities, targets, router, donors, protected, day["das"], rng)
        print("Checking population accounting for", len(loops), "walks", flush=True)
        clock = verify_loop_clock(loops, places, occupancy, scratch, backend)
    if len({(d, i, start) for d, i, _, start, *_ in loops}) != len(loops):
        raise ValueError("A recreational walk was assigned twice")
    data = dict(versions=versions, workplaceRun=workplace_run, shared=shared, outcomes=breakdown,
                residents=residents, survey=dict(trips=source["trips"], population=source["residents"],
                loopShare=LOOP_FRACTION, walkShare=WALK_FRACTION, source=SURVEY_2025, digest=SURVEY_2025_DIGEST),
                donor=dict(respondents=donors.responseCount, bouts=len(donors.starts), source=TUS_SOURCE,
                           maxShift=MAX_DONOR_SHIFT, speed=WALK_SPEED, minPace=MIN_WALK_PACE),
                weekday=dict(recordedTrips=evidence["model"][NORTH_SHORE]["trips"],
                             shortWalks=evidence.get("gapWalks", {}).get(NORTH_SHORE, 0),
                             observedTripsPerResident=source["trips"] / source["residents"]),
                seed=SEED, misses=misses, **clock)

    release = publish_loops(region, data, loops, day)
    pointer(region / "recreation-loops" / (key + ".json"), {"version": release})
    print(release, breakdown, misses, data["kinds"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default=WORKPLACE_RUN)
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    publish(args.region, args.archive, args.workplace_run, args.backend)
