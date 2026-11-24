"""Fit recreational home-to-home bike rides into Vancouver's municipal weekday."""
import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import re
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import largest_remainder
from scripts.vancouver_cityday import xy
from scripts.vancouver_cycle_counts import SUMMER, screen_fraction
from scripts.vancouver_cycle_tours import SPEED
from scripts.vancouver_cycling import FORWARD, REVERSE
from scripts.vancouver_discretionary_outings import read_opportunities
from scripts.vancouver_flexible_transit import protected_intervals
from scripts.vancouver_mobility import SOURCE
from scripts.vancouver_north_shore_demand import SURVEY_2025, SURVEY_2025_ARCHIVE, SURVEY_2025_DIGEST, verify_survey
from scripts.vancouver_recreation_loops import ExerciseDonors, LoopRouter, MAX_DONOR_SHIFT, TUS_SOURCE, fit, publish_loops, verify_loop_clock
from scripts.vancouver_region import read
from scripts.vancouver_street_scenarios import RECREATION, publish_index
from scripts.vancouver_streets import access_graph
from scripts.vancouver_survey_zones import ZONES
from scripts.vancouver_transit_commutes import pointer


SEED = 202523
MIN_PACE = 120  # m/min including time at junctions
MAX_ACCESS = 80  # metres from the assigned home to a bicycle-permitted node
RECREATION_TRIPS = 152900  # 2023 Vancouver Transportation Survey, Figure 46
RECREATION_CYCLE_SHARE = .13
HOME_LOOP_SHARE = .04 / .22  # North Shore 2025 survey section 5.3, transfer across region and mode
SPORTS_DURATION = (20, 120)  # Limit the multi-sport diary proxy to short and half-day rides
GREENWAYS = ("Seaside", "Seawall", "Stanley Park Seawall", "Arbutus Greenway", "Central Valley Greenway")


class BikeLoopRouter:
    def __init__(self, network, places, rng):
        self.graph, snap = access_graph(network, FORWARD, REVERSE)
        self.reverse = self.graph.T.tocsr()
        self.nodes, self.rng = network["nodes"], rng
        self.homes = [p[:2] for p in places]
        self.snaps, self.offsets = snap(self.homes, lowest_id_on_ties=True)
        self.origins = np.repeat(np.arange(len(self.nodes)), np.diff(self.graph.indptr))
        self.scenic = set()
        for bits, name, nodes in network["ways"]:
            if network["names"][name].startswith(GREENWAYS):
                for a, b in zip(nodes, nodes[1:]):
                    if bits & (FORWARD | REVERSE):
                        self.scenic.add((min(a, b), max(a, b)))
        self.scenic_arcs = np.array([(min(a, b), max(a, b)) in self.scenic
                                     for a, b in zip(self.origins, self.graph.indices, strict=True)])

    @lru_cache(maxsize=8192)
    def loop(self, home, minutes):
        access = float(self.offsets[home])
        limit = SPEED * minutes - 2 * access
        minimum = MIN_PACE * minutes - 2 * access
        if access > MAX_ACCESS or limit <= 0:
            return None
        root = int(self.snaps[home])
        outward, before = dijkstra(self.graph, indices=root, limit=limit, return_predecessors=True)
        inward, after = dijkstra(self.reverse, indices=root, limit=limit, return_predecessors=True)
        origins, ends = self.origins, self.graph.indices
        lengths = outward[origins] + self.graph.data + inward[ends]
        feasible = (lengths >= minimum) & (lengths <= limit)
        preferred = (minimum + limit) / 2
        candidates = set()
        for mask in (feasible, feasible & self.scenic_arcs):
            choices = np.flatnonzero(mask)
            if len(choices) > 16:
                nearest = np.argpartition(np.abs(lengths[choices] - preferred), 15)[:16]
                choices = choices[nearest]
            candidates.update(choices)
        result = None
        best = -np.inf
        for edge in sorted(candidates):
            outward_path = LoopRouter.stem(before, root, int(origins[edge]))
            return_path = LoopRouter.stem(after, root, int(ends[edge]))[::-1]
            route = outward_path + return_path
            traversed = [(min(a, b), max(a, b)) for a, b in zip(route, route[1:])]
            unique = set(traversed)
            fraction = len(unique & self.scenic) / len(traversed)
            repeated = 1 - len(unique) / len(traversed)
            score = (fraction - .5 * repeated - abs(lengths[edge] - preferred) / limit
                     + self.rng.uniform(0, .15))
            if score > best:
                best = score
                path = [self.homes[home], *(self.nodes[i] for i in route), self.homes[home]]
                vertices = [p for j, p in enumerate(path) if j == 0 or p != path[j - 1]]
                kind = "out-and-back" if traversed == traversed[::-1] else "circuit"
                result = kind, vertices, round(float(lengths[edge]) + 2 * access, 2)
        return result


def roster_access(atlas, day, access, offsets):
    names = {da: name for name, area in atlas["areas"].items() for da in area["das"]}
    counts = Counter(dict.fromkeys(atlas["areas"], 0))
    for d, da in enumerate(day["das"]):
        end = offsets[d + 1] if d + 1 < len(offsets) else len(access)
        counts[names[da]] += int(np.count_nonzero(access[offsets[d]:end]))
    return dict(sorted(counts.items()))


def count_loops(loops, router):
    sites = {}
    for key, name, year, daily, point, [dx, dy, width], page in SUMMER:
        length = math.hypot(dx, dy)
        sites[key] = (xy(*point), [dx/length, dy/length, width],
                      dict(name=name, year=year, observed=daily, added=0, recorded=0,
                           source=f"https://vancouver.ca/files/cov/{year}-transportation-snapshot.pdf#page={page}"))
    for d, i, home, start, minutes, added, _, path, _, _ in loops:
        connected = router.homes[home] == router.nodes[router.snaps[home]]
        u, v = (0, len(path)) if connected else (1, len(path)-1)
        road = path[u:v]
        edges = [math.dist(a, b) for a, b in zip(path, path[1:])]
        along = np.cumsum([0, *edges])
        x, y = zip(*road, strict=True)
        left, right, top, bottom = min(x), max(x), min(y), max(y)
        for point, screen, evidence in sites.values():
            px, py = point
            width = screen[2]
            if not (left-width <= px <= right+width and top-width <= py <= bottom+width):
                continue
            for j, (a, b) in enumerate(zip(road, road[1:]), start=u):
                hit = screen_fraction(a, b, point, screen, min_alignment=.5)
                if hit:
                    evidence["added" if added else "recorded"] += 1
                    minute = start + minutes * (along[j] + hit[0]*edges[j]) / along[-1]
                    if added:
                        evidence.setdefault("example", [d, i, float(minute)])
    return {key: evidence for key, (_, _, evidence) in sites.items()}


def publish(root, archive, backend, bc_donors=False, balanced=True, clock_version=None):
    verify_survey(SURVEY_2025_ARCHIVE, SURVEY_2025_DIGEST)
    base = read(root / "cityday/current.json")
    streets = read(root / "streets/current.json")["version"]
    cycling = read(root / "cycling" / (streets + ".json"))["version"]
    versions = dict(atlas=base["atlas"], day=base["version"], streets=streets, cycling=cycling)
    access_key = "_".join(versions.values())
    tour_version = read(root / "cycle-tours" / (access_key + ".json"))["version"]
    tour = root / "cycle-tours" / tour_version
    access_report = read(tour / "report.json")
    if any(access_report["versions"][k] != v for k, v in versions.items()):
        raise ValueError("Bicycle access uses a different weekday")
    access = np.fromfile(tour / "access.bin", dtype=np.uint8)
    offsets = access_report["offsets"]
    day_dir, atlas_dir = root / "cityday" / versions["day"], root / "atlas" / versions["atlas"]
    day, places = read(day_dir / "day.json"), read(day_dir / "places.json")
    if len(access) != day["population"] or len(offsets) != len(day["das"]):
        raise ValueError("Bicycle access does not cover the complete resident roster")
    groups = roster_access(read(atlas_dir / "atlas.json"), day, access, offsets)
    surveyed = sum(row[-1] for row in ZONES)
    rate = RECREATION_TRIPS * RECREATION_CYCLE_SHARE * HOME_LOOP_SHARE / surveyed
    target = round(sum(groups.values()) * rate)
    targets = dict(zip(groups, map(int, largest_remainder(np.array(list(groups.values())) * rate, target)), strict=True))
    clock_path = None
    reserved = {}
    occupancy = np.array(day["occupancy"])
    if clock_version:
        if not re.fullmatch(r"[0-9a-f]{20}", clock_version):
            raise ValueError("Invalid departure clock release")
        clock_path = root / "departure-clock" / clock_version / "clock.json"
        clock = read(clock_path)
        if (clock["atlas"], clock["day"], clock["kind"], clock["population"]) != (
                versions["atlas"], versions["day"], "spread-departures", day["population"]):
            raise ValueError("The departure clock uses a different resident weekday")
        occupancy = np.array(clock["occupancy"])
        versions["clock"] = clock_version
    else:
        reserved = protected_intervals(root, versions, day, None)
    short_walk_path = root / "short-walks" / f"{versions['day']}_{streets}.json"
    walk_digest = None
    if not clock_path and short_walk_path.is_file():
        occupancy += np.asarray(read(short_walk_path)["occupancyDelta"])
        walk_digest = hashlib.sha256(short_walk_path.read_bytes()).hexdigest()
    rng = np.random.default_rng(SEED)
    router = BikeLoopRouter(read(root / "cycling" / cycling / "network.json"), places, rng)
    with tempfile.TemporaryDirectory() as folder:
        scratch = Path(folder)
        donor_file = scratch / "sports.json"
        donor_scope = "--outdoor-sports-bc" if bc_donors else "--outdoor-sports"
        with donor_file.open("w") as output:
            subprocess.run(["clojure", "-J-Xmx2g", "-M", "-m", "city.vancouver.atlas-diaries", archive,
                            donor_scope], stdout=output, check=True)
        donors = []
        for diary in read(donor_file):
            bouts = [b for b in diary["bouts"] if SPORTS_DURATION[0] <= b[1] <= SPORTS_DURATION[1]]
            if bouts:
                donors.append(dict(diary, bouts=bouts))
        opportunities = read_opportunities(atlas_dir, day_dir, scratch, detail="with-bicycle-loops",
                                           municipalities=groups, clock=clock_path)
        opportunities["residents"] = [r for r in opportunities["residents"] if access[offsets[r[0]] + r[1]] == 2]
        recorded = Counter(row[-1] for row in opportunities["recorded"])
        desired = sum(max(0, n-recorded[name]) for name, n in targets.items())
        donors = ExerciseDonors(donors, desired if balanced else None)
        loops, outcomes, misses = fit(opportunities, targets, router, donors, reserved, day["das"], rng)
        print(f"Checking the clock for {len(loops):,} bicycle loops.", flush=True)
        clock = verify_loop_clock(loops, places, occupancy, scratch, backend)
    if len({(r[0], r[1], r[3]) for r in loops}) != len(loops):
        raise ValueError("A recreational bicycle loop was assigned twice")
    report = dict(mode="bike", versions=versions, shared=dict(shortWalkDigest=walk_digest, bicycleAccess=tour_version),
                  outcomes=outcomes, residents=groups, seed=SEED, misses=misses,
                  survey=dict(recreationTrips=RECREATION_TRIPS, cyclingShare=RECREATION_CYCLE_SHARE,
                              loopShare=HOME_LOOP_SHARE, source=SOURCE, loopSource=SURVEY_2025, target=target),
                  donor=dict(respondents=donors.responseCount, bouts=len(donors.starts), source=TUS_SOURCE,
                             maxShift=MAX_DONOR_SHIFT, speed=SPEED, minPace=MIN_PACE, duration=SPORTS_DURATION),
                  crossings=count_loops(loops, router), **clock)
    if balanced:
        keys = sorted(set(int(s) // 60 for s in donors.starts))
        desired_by_hour = Counter()
        fitted_by_hour = Counter()
        for start, quota, remaining in zip(donors.starts, donors.target, donors.remaining, strict=True):
            desired_by_hour[int(start) // 60] += int(quota)
            fitted_by_hour[int(start) // 60] += int(quota - remaining)
        report["donor"]["hours"] = [[hour, desired_by_hour[hour], fitted_by_hour[hour]] for hour in keys]
        report["donor"]["unassigned"] = sum(map(int, donors.remaining))
    release = publish_loops(root, report, loops, day)
    publish_index(root, RECREATION, release)
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    if clock_version:
        key += "_" + clock_version
    pointer(root / "recreation-loops" / (key + ".json"), {"version": release})
    print(release, target, report["kinds"], misses, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path("public/data/vancouver"))
    parser.add_argument("--backend", default="jvm")
    parser.add_argument("--bc-donors", action="store_true", help="Use only British Columbia time-use donors")
    parser.add_argument("--unbalanced", action="store_true", help="Use the earlier conditional donor sample without timing targets")
    parser.add_argument("--departure-clock", help="Fit the rides to a published spread-departures weekday")
    args = parser.parse_args()
    publish(args.root, args.archive, args.backend, args.bc_donors, not args.unbalanced, args.departure_clock)
