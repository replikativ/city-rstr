"""Replay a route-constrained change from working at home to working on site."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from scripts.vancouver_atlas import write_json
from scripts.vancouver_bridge_traffic import road_profile
from scripts.vancouver_campus import access_routes
from scripts.vancouver_city_transit import DirectService
from scripts.vancouver_cityday import SPEED
from scripts.vancouver_discretionary_outings import available_windows, verify_intervals
from scripts.vancouver_eastern_workplaces import candidates_for
from scripts.vancouver_flexible_transit import WORKPLACE_RUN
from scripts.vancouver_inbound import leave_band, duration_band
from scripts.vancouver_north_shore_demand import (
    MODES, SURVEY_ROWS, SURVEY_2025, SURVEY_2025_ARCHIVE, SURVEY_2025_DIGEST, trip_inputs, verify_survey,
)
from scripts.vancouver_north_shore_zones import WORK_ZONES, OBSERVED, ZONES, crosswalk, workplace_groups
from scripts.vancouver_outbound import donor_index, household_profiles
from scripts.vancouver_region import package, read
from scripts.vancouver_school_escorts import itinerary, path, reserve_recreation
from scripts.vancouver_streets import access_graph
from scripts.vancouver_transit_commutes import BOARDING_MARGIN_SECONDS, pointer
from scripts.vancouver_transit_load import ANNUAL_TABLE, TABLE, BusSpaces, bus_capacity_profile, bus_load_evidence, ride_legs
from scripts.vancouver_transit_transfers import OneTransfer, walk_transfers
from scripts.vancouver_work_transit import choose, outing_rides

SEED = 202549
# Tables 50–52 report distinct people who made a trip to work or a work-related trip.
SURVEY_WORKERS = {
    "City of North Vancouver": (24100, [14400, 300, 5600, 2000, 1500, 300]),
    "District of North Vancouver": (28400, [19000, 800, 5000, 900, 2300, 400]),
    "West Vancouver": (11700, [8000, 1000, 2100, 400, 100, 50]),
}
REGIONAL_CITIES = {*SURVEY_ROWS, "Burnaby", "New Westminster", "UBC Vancouver campus"}
TRAVEL = {1: ("bike", "Cycling"), 2: ("car-driver", "Auto driver"),
          6: ("transit", "Transit"), 7: ("walk", "Walking")}
MAX_MINUTES = 90


def options(archive, atlas_dir, day_dir, atlas, day, shifts, protected, zone):
    census = donor_index(archive / "data/raw/statcan/pumf/data_donnees_2021_hier_v2.csv",
                        ("POWST", "PWLEAVE", "PWDUR"))
    homes = {da: name for name in SURVEY_ROWS for da in atlas["areas"][name]["das"]}
    input_trips = [trip_inputs(diary, plan)[0] for diary, plan in zip(atlas["templates"], day["templates"], strict=True)]
    profiles = [(next(((trip[0], trip[5]) for trip in trips if trip[1] == "Paid work"), None), spec)
                for trips, spec in zip(input_trips, shifts, strict=True)]
    baseline, jobs, cells, residents_by_zone = defaultdict(Counter), Counter(), Counter(), Counter()
    considered, candidates, exclusions = defaultdict(Counter), [], Counter()
    for d, da in enumerate(day["das"]):
        roster = read(atlas_dir / (da + ".json"))
        spatial = read(day_dir / (da + ".json"))
        for person, plan in zip(roster["people"][:atlas["das"][da]["private"]], spatial["plans"], strict=False):
            for slot in shifts[person[-1]]["paidSlots"]:
                if plan[slot] >= 0:
                    jobs[plan[slot]] += 1
        if da not in homes:
            continue
        name = homes[da]
        for first, people, statuses, _ in household_profiles(roster, census, np.random.default_rng([SEED, int(da)])):
            dependent = any(shifts[p[-1]]["careAtHome"] for p in people)
            care = []
            if dependent:
                for j, person in enumerate(people, first):
                    if 4 <= person[0] <= 13:
                        free = list(available_windows(shifts[person[-1]]["awake"], sorted(protected.get((da, j), ()))))
                        care.append((j, free))
            for i, (person, assignment) in enumerate(zip(people, statuses, strict=True), first):
                age, _, labour, _, _, _, usual, t = person
                if not 3 <= age <= 13:
                    continue
                home = spatial["home"][i]
                district = (zone["placeZones"][home] if home >= 0 else 0) or zone["daZones"][da]
                residents_by_zone[district] += 1
                baseline[name]["residents"] += 1
                if labour != 1:
                    continue
                baseline[name]["employed"] += 1
                trip, spec = profiles[t]
                if trip is not None:
                    mode, slot = trip
                    baseline[name]["withWorkTrip"] += 1
                    baseline[name][mode] += 1
                    if slot >= 0 and spatial["plans"][i][slot] >= 0:
                        cells[district, spatial["plans"][i][slot]] += 1
                status, departure, duration = assignment
                if trip is not None or not spec["shift"]:
                    continue
                considered[name]["atHomeShift"] += 1
                if status not in (4, 5) or departure not in range(1, 7) or duration not in range(1, 6):
                    exclusions["noFixedMetroCommuteProfile"] += 1
                    continue
                if usual not in TRAVEL:
                    exclusions["unsupportedUsualMode"] += 1
                    continue
                if home < 0:
                    exclusions["missingHome"] += 1
                    continue
                before, start, end, after, paid = spec["shift"]
                free = available_windows([(before, after)], sorted(protected.get((da, i), ())))
                span = next(((a, b) for a, b in free if a < start and end < b), None)
                if span is None:
                    exclusions["reservedTime"] += 1
                    continue
                a, b = span
                if dependent and not any(j != i and x <= start and end <= y for j, windows in care for x, y in windows):
                    exclusions["homeCare"] += 1
                    continue
                candidates.append(dict(d=d, i=i, home=home, municipality=name, zone=district, status=status,
                                       departure=departure, duration=duration, mode=TRAVEL[usual][0],
                                       modeLabel=TRAVEL[usual][1], before=a, start=start, end=end, after=b, paid=paid,
                                       care=care if dependent else None))
                considered[name][TRAVEL[usual][1]] += 1
    return candidates, baseline, jobs, cells, residents_by_zone, considered, exclusions


def municipality(area):
    return area if area in REGIONAL_CITIES else "Vancouver"


def site_indexes(jobs, places, groups, areas):
    keys = defaultdict(Counter)
    for loc, n in jobs.items():
        area = places[loc][2]
        if area >= 0:
            keys[municipality(areas[area]), groups[loc]][loc] += n
    result = {}
    for k, counts in sorted(keys.items()):
        sites = np.asarray(sorted(counts))
        weights = np.asarray([counts[loc] for loc in sites], dtype=float)
        result[k] = (sites, weights / weights.sum(), cKDTree([places[loc][:2] for loc in sites]))
    return result


def road_points(places, network, mode, profile):
    if mode == "car-driver":
        graph, snap = access_graph(network, 2, 4, speeds=profile["kmh"])
        scale, pace, connector = 1, profile["connectorKmh"] * 1000 / 60, profile["connectorMetres"]
    else:
        bits = (1, 1) if mode == "walk" else (8, 16)
        graph, snap = access_graph(network, *bits)
        scale, pace, connector = SPEED[mode], SPEED[mode], 500
    nodes, offsets = snap([place[:2] for place in places], lowest_id_on_ties=True)
    return graph, scale, offsets / pace, offsets <= connector, nodes


class StreetTrips:
    def __init__(self, places, network, mode, profile):
        self.places = places
        self.points = network["nodes"]
        graph, self.scale, self.offsets, self.connected, self.nodes = road_points(places, network, mode, profile)
        self.outward, self.inward = graph, graph.T.tocsr()

    @lru_cache(maxsize=8)
    def trees(self, home, there, back):
        origin = int(self.nodes[home])
        return (dijkstra(self.outward, indices=origin, limit=there * self.scale, return_predecessors=True),
                dijkstra(self.inward, indices=origin, limit=back * self.scale, return_predecessors=True))

    def trips(self, candidate, dest, shortest, longest):
        home = candidate["home"]
        points = self.places
        if not (self.connected[home] and self.connected[dest]) or points[home][:2] == points[dest][:2]:
            return None
        start, end = candidate["start"], candidate["end"]
        forward = min(longest, start - candidate["before"])
        backward = min(MAX_MINUTES, candidate["after"] - end)
        if min(forward, backward) < 1:
            return None
        (distance, go), (back_distance, back) = self.trees(home, forward, backward)
        a, b = int(self.nodes[home]), int(self.nodes[dest])
        access, egress = self.offsets[home], self.offsets[dest]
        raw = distance[b] / self.scale + access + egress
        returned = back_distance[b] / self.scale + access + egress
        if not shortest <= raw <= forward or not returned <= backward:
            return None
        outward_duration = max(1, int(np.ceil(raw)))
        depart = start - outward_duration
        if leave_band(depart) != candidate["departure"] or duration_band(outward_duration) != candidate["duration"]:
            return None
        line, ids = path(self.points, a, b, go)
        there = itinerary(line, distance[ids] / self.scale, points[home][:2], points[dest][:2], access, egress)
        line, ids = path(self.points, a, b, back)
        ret = itinerary(line[::-1], (back_distance[b] - back_distance[ids[::-1]]) / self.scale,
                        points[dest][:2], points[home][:2], egress, access)
        return depart, end + ret[0], there[1], ret[1], start


class TransitTrips:
    def __init__(self, archive, root, versions, places, site_ids, protected):
        timetable = root / "transit" / versions["transit"]
        streets = root / "streets" / versions["streets"]
        self.service = DirectService(timetable)
        self.access = access_routes(places, site_ids, self.service.stations, streets)
        rules = read(timetable / "transfers.json")["pairs"]
        self.planner = OneTransfer(self.service, self.access,
                                  walk_transfers(self.service, rules, streets / "network.json", BOARDING_MARGIN_SECONDS),
                                  BOARDING_MARGIN_SECONDS)
        self.observed = archive / "data/raw/probes" / TABLE
        annual = self.observed.with_name(ANNUAL_TABLE)
        self.profile = bus_capacity_profile(self.service.route_manifest, self.observed, annual if annual.is_file() else None)
        self.space = BusSpaces(self.profile["limits"])
        outing, reserved = outing_rides(root, versions, protected["outings"])
        if outing != protected["outings"]:
            raise ValueError("The attendance replay uses different discretionary transit")
        if protected["flexibleTransit"]:
            clock = read(root / "household-clock" / protected["flexibleTransit"] / "report.json")
            work = root / "work-transit" / clock["workTransitRelease"]
            prior = read(work / "report.json")
            reserved.extend(row[6:] for da in prior["coverage"]["areas"] for row in read(work / (da + ".json")))
        self.prior = tuple(tuple(leg) for ride in reserved for leg in ride_legs(ride))
        for ride in reserved:
            self.space.reserve(ride)
        self.direct = self.service.latest_departure(self.access, BOARDING_MARGIN_SECONDS, self.space.available)

    def transfer(self, deadline, a, b):
        best = self.planner.latest(deadline, a, b)
        if best is None or self.space.fits(best[2]):
            return best
        return self.planner.latest(deadline, a, b, self.space.available)

    def trips(self, candidate, dest, shortest, longest):
        home = candidate["home"]
        if home not in self.access or dest not in self.access or home == dest:
            return None
        start, end = candidate["start"], candidate["end"]
        began = max(start - longest, candidate["before"])
        outward = choose(self.direct, self.transfer, began, start, home, dest)
        if outward is None:
            return None
        began, actual, first = outward
        if leave_band(began) != candidate["departure"] or int(np.ceil(actual / 60)) - began < shortest:
            return None
        return_trip = choose(self.direct, self.transfer, end, min(end + MAX_MINUTES, candidate["after"]), dest, home)
        if return_trip is None:
            return None
        left, home_at, second = return_trip
        # Find the earliest return that fits. The latest departure at a much
        # later deadline could otherwise leave the worker waiting far too long.
        lo, hi = end + 1, int(np.ceil(home_at / 60))
        while lo < hi:
            mid = (lo + hi) // 2
            trial = choose(self.direct, self.transfer, end, mid, dest, home)
            if trial is None:
                lo = mid + 1
            else:
                hi = mid
                left, home_at, second = trial
        if left < end or left >= hi or int(np.ceil(home_at / 60)) > hi:
            return None
        if {(a, b) for a, b, *_ in ride_legs(first)} & {(a, b) for a, b, *_ in ride_legs(second)}:
            return None
        return began, hi, first, [left, second], int(np.ceil(actual / 60))


def departure_fits(person, shortest, longest):
    low = max(person["before"], person["start"] - longest)
    high = person["start"] - max(1, shortest)
    return any(leave_band(t) == person["departure"] for t in range(low, high + 1))


def allocate(candidates, baseline, jobs, cells, residents_by_zone, places, groups, areas, routers, protected, das):
    indexes = site_indexes(jobs, places, groups, areas)
    # The 2025 survey populations accompany Tables 50–52.
    survey_pop = dict(zip(SURVEY_WORKERS, (54800, 75300, 39100), strict=True))
    survey_limits = {(name, m): round(baseline[name]["residents"] * count / survey_pop[name])
                     for name, (_, modes) in SURVEY_WORKERS.items() for m, count in zip(MODES, modes, strict=True)}
    zone_counts = Counter()
    for (zone, loc), count in cells.items():
        zone_counts[zone, groups[loc]] += count
    zone_goal = {(zone, group): round(observed * residents_by_zone[zone] / population)
                 for group, row in zip(WORK_ZONES, OBSERVED, strict=True)
                 for zone, (_, population) in enumerate(ZONES, 1)
                 if isinstance(observed := row[zone-1], int)}
    outcomes, added, misses = [], Counter(), Counter()
    rng = np.random.default_rng(SEED)
    for j in rng.permutation(len(candidates)):
        person = candidates[j]
        home, name, mode, label = (person[k] for k in ("home", "municipality", "mode", "modeLabel"))
        if baseline[name][label] + added[name, label] >= survey_limits[name, label]:
            misses["modeCeiling"] += 1
            continue
        lo = (person["duration"] - 1) * 15
        hi = min(MAX_MINUTES, lo + 14) if lo < 60 else MAX_MINUTES
        if not departure_fits(person, lo, hi):
            misses["departureBand"] += 1
            continue
        zone = person["zone"]
        same = person["status"] == 4
        possible = [key for key in indexes if (key[0] == name) == same]
        noise = {key: rng.random() for key in possible}
        possible.sort(key=lambda key: (zone_counts[zone, key[1]] - zone_goal.get((zone, key[1]), 0), noise[key]))
        used = None
        da = das[person["d"]]
        for key in possible:
            for dest in candidates_for(np.asarray(places[home][:2]), indexes[key], rng):
                if dest == home or places[home][:2] == places[dest][:2]:
                    continue
                rate = 2500 if mode in ("car-driver", "transit") else SPEED[mode]
                if np.linalg.norm(np.subtract(places[home][:2], places[dest][:2])) > hi * rate:
                    continue
                trip = routers[mode].trips(person, int(dest), lo, hi)
                if not trip:
                    continue
                start, end, go, back, arrival = trip
                helper = None
                if person["care"] is not None:
                    helper = next((i for i, spans in person["care"] if i != person["i"] and
                                   any(a <= start and end <= b for a,b in spans) and
                                   all(b <= start or end <= a for a,b in protected.get((da,i), ()))), None)
                    if helper is None:
                        continue
                used = dest, start, end, go, back, helper, arrival
                break
            if used is not None:
                break
        if used is None:
            misses["noPairedCommute"] += 1
            continue
        dest, start, end, go, back, helper, arrival = used
        # Another candidate in the same household may have become the caregiver.
        if any(b > start and end > a for a, b in protected.get((da, person["i"]), ())):
            misses["reservedTime"] += 1
            continue
        if helper is not None:
            protected[da, helper].append((start, end))
        protected[da, person["i"]].append((start, end))
        if mode == "transit":
            routers[mode].space.reserve(go)
            routers[mode].space.reserve(back[1])
        zone_counts[zone, groups[dest]] += 1
        added[name, label] += 1
        outcomes.append([person["d"], person["i"], home, int(dest), mode, start, person["start"], person["end"], end,
                         go, back, person["paid"], helper, person["status"], person["departure"], person["duration"], arrival])
    report = {name: {m: {"recorded": before[m], "scaledSurvey": survey_limits[name, m], "added": added[name, m]}
                     for m in MODES} for name, before in baseline.items()}
    return outcomes, report, misses


def verify_clock(tours, places, occupancy, scratch, backend):
    cols = occupancy.shape[1]
    delta = np.zeros((1441, cols), dtype=np.int32)
    itineraries = []
    for _, _, home, site, mode, start, work, leave, end, _, back, *_, arrival in tours:
        orig, job = places[home][2], places[site][2]
        departure = back[0] if mode == "transit" else leave
        ranges = ((start, arrival, cols - 2), (arrival, departure, job), (departure, end, cols - 2))
        if not 240 <= start < arrival <= work < leave <= departure < end <= 1680 or min(orig, job) < 0:
            raise ValueError("Attendance outside the original resident's day")
        sequence = []
        for a, b, new in ranges:
            lo, hi = a - 240, b - 240
            delta[lo:hi, orig] -= 1
            delta[lo:hi, new] += 1
            sequence.append((lo * cols + orig, hi * cols + orig, new - orig))
        itineraries.append(tuple(sequence))
    return verify_intervals(itineraries, delta, occupancy, scratch, backend)


def reserve_school(root, versions, day):
    protected, occupancy, shared = reserve_recreation(root, versions, day)
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    school = root / "school-escorts"
    version = read(school / (key + ".json"))["version"]
    release = school / version
    report = read(release / "report.json")
    if report["versions"] != versions or report["shared"] != shared:
        raise ValueError("School escorts use different weekday inputs")
    for da in report["areas"]:
        for _, adult, _, _, _, _, _, start, travel, handoff, back, _, _, caregiver in read(release / (da + ".json")):
            interval = (start, start + travel + handoff + back)
            protected[da, adult].append(interval)
            if caregiver is not None:
                protected[da, caregiver].append(interval)
    occupancy += np.asarray(report["occupancyDelta"])
    return protected, occupancy, dict(shared, schools=version)


def publish(root, archive, workplace_run, backend):
    verify_survey(SURVEY_2025_ARCHIVE, SURVEY_2025_DIGEST)
    parent = read(root / "regional-workplaces" / workplace_run / "report.json")
    versions = dict(parent["versions"], day=parent["day"], transit=parent["timetable"])
    base_versions = dict(parent["versions"], day=parent["day"])
    atlas_dir = root / "atlas" / versions["atlas"]
    day_dir = root / "cityday" / versions["day"]
    atlas, day, places = read(atlas_dir / "atlas.json"), read(day_dir / "day.json"), read(day_dir / "places.json")
    protected, occupancy, shared = reserve_school(root, base_versions, day)
    zones = crosswalk(SURVEY_2025_ARCHIVE, atlas, atlas_dir, places, day["areas"], SURVEY_ROWS)
    groups = workplace_groups(places, day["areas"], zones["placeZones"], SURVEY_ROWS)
    with tempfile.TemporaryDirectory() as work:
        scratch = Path(work)
        shifts = scratch / "shifts.json"
        subprocess.run(["clojure", "-J-Xmx1g", "-M", "-m", "city.vancouver.weekday-attendance", atlas_dir / "atlas.json",
                        day_dir / "day.json", shifts], check=True)
        rows, baseline, jobs, cells, population, eligible, exclusions = options(
            archive, atlas_dir, day_dir, atlas, day, read(shifts), protected, zones)
        print(len(rows), "candidate shifts", dict(Counter(row["mode"] for row in rows)),
              sum(n["withWorkTrip"] for n in baseline.values()), "workers with trips", flush=True)
        streets = read(root / "streets" / versions["streets"] / "network.json")
        cycle = read(root / "cycling" / (versions["streets"] + ".json"))["version"]
        bicycle = read(root / "cycling" / cycle / "network.json")
        profile, roads = road_profile(root, versions["streets"], "time")
        transit = TransitTrips(archive, root, versions, places, {row["home"] for row in rows if row["mode"] == "transit"} |
                               set(jobs), shared)
        print(len(transit.access), "places with timetable access", flush=True)
        routers = {"car-driver": StreetTrips(places, streets, "car-driver", profile),
                   "walk": StreetTrips(places, streets, "walk", profile),
                   "bike": StreetTrips(places, bicycle, "bike", profile), "transit": transit}
        tours, modes, misses = allocate(rows, baseline, jobs, cells, population, places, groups, day["areas"], routers,
                                       protected, day["das"])
        print(len(tours), "paired trips, verifying Raster and capacity", flush=True)
        clock = verify_clock(tours, places, occupancy, scratch, backend)
    transit_rows = []
    for d, i, home, site, mode, start, work, leave, end, go, back, *_ in tours:
        if mode == "transit":
            left, ride = back
            transit_rows.extend([[day["das"][d], i, start, work-start, home, site, *go],
                                 [day["das"][d], i, left, end-left, site, home, *ride]])
    bus = bus_load_evidence(root / "transit" / versions["transit"], transit.service.route_manifest, transit_rows,
                            transit.observed, transit.profile["limits"], reserved=transit.prior)
    if bus["above"]:
        raise ValueError("Additional attendance exceeds the existing bus capacity budget")
    sampled, by_da = [], defaultdict(list)
    sample_ids = {(d, i) for d, i, *_ in day["sample"]}
    for row in sorted(tours, key=lambda r: tuple(r[:2])):
        d, i, *_ = row
        by_da[day["das"][d]].append(row)
        if (d, i) in sample_ids:
            sampled.append(row)
    examples = {mode: min((row for row in tours if row[4] == mode),
                          key=lambda r: (abs(510-r[5]), -r[11]), default=None) for mode in routers}
    report = dict(versions=versions, workplaceRun=workplace_run, shared=shared, modes=modes, baseline=baseline,
                  eligible=eligible, exclusions=exclusions, misses=misses, total=len(tours), areas=sorted(by_da),
                  examples=examples, survey=SURVEY_2025, surveyDigest=SURVEY_2025_DIGEST, surveyWorkers=SURVEY_WORKERS,
                  bus=bus, roads=roads, serviceDate=transit.service.route_manifest["date"],
                  cycling=cycle, seed=SEED, **clock)

    def write(output):
        write_json(output / "report.json", report)
        write_json(output / "sample.json", sampled)
        for da, data in by_da.items():
            write_json(output / (da + ".json"), data)

    version = package(root, "weekday-attendance", write)
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    pointer(root / "weekday-attendance" / (key + ".json"), {"version": version})
    print(version, modes, eligible, exclusions, misses, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default=WORKPLACE_RUN)
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    publish(args.region, args.archive, args.workplace_run, args.backend)
