"""Coordinate North Vancouver school journeys with the adults in each household."""
import argparse
from collections import Counter, defaultdict
import csv
import math
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from scipy.sparse.csgraph import dijkstra

from scripts.vancouver_atlas import write_json
from scripts.vancouver_bridge_traffic import road_profile
from scripts.vancouver_cityday import xy
from scripts.vancouver_discretionary_outings import available_windows, verify_intervals
from scripts.vancouver_recreation_loops import WORKPLACE_RUN, reservations
from scripts.vancouver_region import package, read, rows
from scripts.vancouver_streets import access_graph
from scripts.vancouver_transit_commutes import pointer

MUNICIPALITIES = ("City of North Vancouver", "District of North Vancouver")
SCHOOL_SURVEY = ("https://www.cnv.org/-/media/City-of-North-Vancouver/Documents/"
                 "Safe-and-Active-Schools/Safe-and-Active-School-Travel-Program-Refresh-Appendices.pdf")
# Appendix B, Figures 4 and 5, City of North Vancouver respondents.
# Walking is an upper bound on walking with an adult. Carpool is a separate category.
SHARES = {"drop-off": {"walk": .40, "car-driver": .43}, "pick-up": {"walk": .45, "car-driver": .28}}
WALK_PACE = 70
HANDOFF = 2
START, END, TRAVEL_ALLOWANCE = 540, 900, 30
SEED = 442021


def mapped_schools(archive, places, areas):
    school_file = archive / "data/raw/probes/anchors_bc_k12_schools.csv"
    with school_file.open(encoding="utf-8-sig") as source:
        centres = {(*xy(float(row["LONGITUDE"]), float(row["LATITUDE"])), row["SCHOOL_NAME"])
                   for row in csv.DictReader(source)
                   if row["DISTRICT_NUMBER"] == "044" and row["PUBLIC_OR_INDEPENDENT"] == "Public School"
                   and row["FACILITY_TYPE"] == "Standard School"
                   and "Elementary" in row["SCHOOL_EDUCATION_LEVEL"] and row["LONGITUDE"] and row["LATITUDE"]}
    return {i for i, (x, y, zone, name) in enumerate(places)
            if zone >= 0 and areas[zone] in MUNICIPALITIES and (x, y, name) in centres}


def read_households(atlas, day, schools, scratch):
    options, output = scratch / "schools.json", scratch / "families.jsonl"
    write_json(options, dict(municipalities=MUNICIPALITIES, schools=sorted(schools)))
    subprocess.run(["clojure", "-J-Xmx1g", "-M", "-m", "city.vancouver.school-escorts", atlas,
                    day, options, output], check=True)
    return list(rows(output))


def path(nodes, root, dest, predecessor):
    indexes = [dest]
    while indexes[-1] != root:
        indexes.append(int(predecessor[indexes[-1]]))
    return [nodes[i] for i in indexes[::-1]], indexes[::-1]


def itinerary(path_points, minutes, source, target, start_offset, end_offset):
    # Cumulative route time preserves arterial speed changes and slower access connectors.
    polyline = []
    offsets = []
    for coordinates, minute in zip([source, *path_points, target],
                                   [0, *(m + start_offset for m in minutes), minutes[-1] + start_offset + end_offset],
                                   strict=True):
        if not polyline or coordinates != polyline[-1]:
            polyline.append(coordinates)
            offsets.append(minute)
    duration = max(1, math.ceil(offsets[-1]))
    return duration, [polyline, [round(x * duration / offsets[-1], 5) for x in offsets]]


def school_routes(households, network, places, mode, profile):
    if mode == "walk":
        graph, snap = access_graph(network, 1, 1)
        unit, connector, max_cost = WALK_PACE, 250, min(TRAVEL_ALLOWANCE * WALK_PACE, 2000)
    else:
        graph, snap = access_graph(network, 2, 4, speeds=profile["kmh"])
        unit, connector, max_cost = 1, profile["connectorMetres"], TRAVEL_ALLOWANCE
    connector_pace = WALK_PACE if mode == "walk" else profile["connectorKmh"] * 1000 / 60
    points = [p[:2] for p in places]
    roots, distance = snap(points, lowest_id_on_ties=True)
    candidates = defaultdict(set)
    for _, home, _, pupils, adults, _ in households:
        if mode == "car-driver" and not any(driver for _, _, driver, _ in adults):
            continue
        for school in {site for _, site in pupils}:
            if max(distance[home], distance[school]) <= connector and points[home] != points[school]:
                candidates[school].add(home)
    results = {}
    reverse = graph.T.tocsr()
    nodes = network["nodes"]
    for school, homes in sorted(candidates.items()):
        anchor = int(roots[school])
        go, go_steps = dijkstra(reverse, indices=anchor, limit=max_cost, return_predecessors=True)
        back, back_steps = dijkstra(graph, indices=anchor, limit=max_cost, return_predecessors=True)
        school_access = distance[school] / connector_pace
        for home in sorted(homes):
            origin = int(roots[home])
            home_access = distance[home] / connector_pace
            extra = home_access + school_access
            if max(go[origin], back[origin]) + extra * unit > max_cost:
                continue
            return_points, return_nodes = path(nodes, anchor, origin, back_steps)
            outbound_points, outbound_nodes = path(nodes, anchor, origin, go_steps)
            outward = itinerary(outbound_points[::-1], (go[origin] - go[outbound_nodes[::-1]]) / unit,
                                points[home], points[school], home_access, school_access)
            inward = itinerary(return_points, back[return_nodes] / unit, points[school], points[home],
                               school_access, home_access)
            results[home, school, mode] = outward, inward
    return results


def feasible_adults(adults, free, awake, mode, start, end, care_at_home):
    present = [i for i, _, _, _ in adults if any(a <= start and end <= b for a, b in awake[i])]
    for i, _, driver, _ in adults:
        if mode == "car-driver" and not driver:
            continue
        if any(a <= start and end <= b for a, b in free[i]):
            if not care_at_home:
                yield i, None
            else:
                for caregiver in present:
                    if caregiver != i:
                        yield i, caregiver


def available(adults, protected, da):
    free = {i: list(available_windows(windows, sorted(protected.get((da, i), ())))) for i, windows, *_ in adults}
    awake = {i: list(available_windows(windows, sorted(protected.get((da, i), ())))) for i, _, _, windows in adults}
    return free, awake


def fit(households, routes, protected, das):
    rng = np.random.default_rng(SEED)
    populations = Counter()
    for _, _, name, pupils, _, _ in households:
        populations[name] += len(pupils)
    limits = {(name, direction, mode): round(n * rate)
              for name, n in populations.items() for direction, shares in SHARES.items() for mode, rate in shares.items()}
    counts, misses, trips = Counter(), Counter(), []
    for selected in rng.permutation(len(households)):
        d, home, municipality, pupils, adults, dependent = households[selected]
        da = das[d]
        siblings = defaultdict(list)
        for child, school in pupils:
            siblings[school].append(child)
        vehicle_use = []
        for school, children in siblings.items():
            for direction, bell in (("drop-off", START), ("pick-up", END)):
                free, awake = available(adults, protected, da)
                options = []
                for mode in SHARES[direction]:
                    k = (municipality, direction, mode)
                    if counts[k] + len(children) > limits[k] or (home, school, mode) not in routes:
                        continue
                    outward, inward = routes[home, school, mode]
                    there, out = outward
                    back, come = inward
                    start = bell - there - (HANDOFF if direction == "pick-up" else 0)
                    end = start + there + HANDOFF + back
                    if mode == "car-driver" and any(start < b and a < end for a, b in vehicle_use):
                        continue
                    staff = list(feasible_adults(adults, free, awake, mode, start, end, dependent))
                    if staff:
                        options.append((k, start, end, there, back, out, come, staff))
                if not options:
                    misses[municipality, direction] += len(children)
                    continue
                # Remaining share is the probability weight when either mode fits.
                weights = np.array([1 - counts[o[0]] / limits[o[0]] for o in options])
                k, start, end, there, back, go, come, staff = options[rng.choice(len(options), p=weights / weights.sum())]
                mode = k[-1]
                adult, caregiver = staff[rng.integers(len(staff))]
                protected[da, adult].append((start, end))
                if caregiver is not None:
                    protected[da, caregiver].append((start, end))
                if mode == "car-driver":
                    vehicle_use.append((start, end))
                counts[k] += len(children)
                trips.append([d, adult, children, home, school, mode, direction, start, there, HANDOFF, back, go, come, caregiver])
    outcomes = {name: {direction: {mode: {"pupils": counts[name, direction, mode],
                                           "surveyCeiling": limits[name, direction, mode]}
                                   for mode in SHARES[direction]} | {"unassigned": misses[name, direction]}
                        for direction in SHARES} for name in populations}
    return trips, dict(populations), outcomes


def verify_clock(tours, places, occupancy, scratch, backend):
    cols = occupancy.shape[1]
    moving = cols - 2
    delta = np.zeros((1441, cols), dtype=np.int32)
    schedules = []

    def shift(start, end, old, new):
        a, b = start - 240, end - 240
        if not 0 <= a <= b <= 1440 or min(old, new) < 0:
            raise ValueError("School escort has an invalid interval or place")
        delta[a:b, old] -= 1
        delta[a:b, new] += 1
        return a * cols + old, b * cols + old, new - old

    for _, _, children, home, school, _, direction, start, there, handoff, back, *_ in tours:
        area, destination = places[home][2], places[school][2]
        arrival = start + there
        departure = arrival + handoff
        end = departure + back
        schedules.append((shift(start, arrival, area, moving), shift(arrival, departure, area, destination),
                          shift(departure, end, area, moving)))
        for _ in children:
            idle = (START - TRAVEL_ALLOWANCE, start) if direction == "drop-off" else (end, END + TRAVEL_ALLOWANCE)
            if idle[0] < idle[1]:
                schedules.append((shift(*idle, moving, area),))
    return verify_intervals(schedules, delta, occupancy, scratch, backend)


def reserve_recreation(region, versions, day):
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    protected, occupancy, required = reservations(region, versions, day, np.asarray(day["occupancy"]))
    loops = region / "recreation-loops"
    recreation = read(loops / (key + ".json"))["version"]
    release = loops / recreation
    exercise = read(release / "report.json")
    if exercise["versions"] != versions or exercise["shared"] != required:
        raise ValueError("School escorts and recreation use different weekday layers")
    occupancy += np.asarray(exercise["occupancyDelta"])
    for da in exercise["areas"]:
        for _, adult, _, start, length, added, *_ in read(release / (da + ".json")):
            if added:
                protected[da, adult].append((start, start + length))
    required["recreation"] = recreation
    return protected, occupancy, required


def publish(region, archive, workplace_run, backend):
    parent = read(region / "regional-workplaces" / workplace_run / "report.json")
    versions = dict(parent["versions"], day=parent["day"])
    key = "_".join(versions[k] for k in ("atlas", "day", "streets"))
    day_dir = region / "cityday" / versions["day"]
    atlas = region / "atlas" / versions["atlas"]
    day, places = read(day_dir / "day.json"), read(day_dir / "places.json")
    for template in day["templates"]:
        if template["childSchedule"] and [part[:2] for part in template["parts"] if part[2] != "stop"] != [
            [START - TRAVEL_ALLOWANCE, TRAVEL_ALLOWANCE], [END, TRAVEL_ALLOWANCE]
        ]:
            raise ValueError("School escorts use a different child timetable")
    protected, occupancy, required = reserve_recreation(region, versions, day)
    schools = mapped_schools(archive, places, day["areas"])
    with tempfile.TemporaryDirectory() as work:
        scratch = Path(work)
        households = read_households(atlas, day_dir, schools, scratch)
        print(len(schools), "mapped schools and", len(households), "households with assigned pupils", flush=True)
        network = read(region / "streets" / versions["streets"] / "network.json")
        profile, provenance = road_profile(region, versions["streets"], "time")
        routes = school_routes(households, network, places, "walk", profile)
        routes.update(school_routes(households, network, places, "car-driver", profile))
        tours, populations, outcomes = fit(households, routes, protected, day["das"])
        print(len(tours), "joint household schedules", flush=True)
        accounting = verify_clock(tours, places, occupancy, scratch, backend)
    areas = defaultdict(list)
    sampled = []
    sample_ids = {(d, i) for d, i, *_ in day["sample"]}
    for row in sorted(tours, key=lambda r: (r[0], r[7], r[1])):
        d, adult, children, *_ = row
        areas[day["das"][d]].append(row)
        if any((d, i) in sample_ids for i in (adult, *children)):
            sampled.append(row)
    examples = {direction: {mode: min((row for row in tours if row[5:7] == [mode, direction]),
                                      key=lambda r: (-len(r[2]), abs(r[8] + r[10] - 18)), default=None)
                            for mode in shares} for direction, shares in SHARES.items()}
    report = dict(versions=versions, workplaceRun=workplace_run, shared=required,
                  areas=sorted(areas), populations=populations, schools=len(schools), outcomes=outcomes,
                  total=len(tours), examples=examples, survey=SCHOOL_SURVEY, shares=SHARES,
                  roads=provenance, seed=SEED, **accounting)

    def write(output):
        write_json(output / "report.json", report)
        write_json(output / "sample.json", sampled)
        for da, data in areas.items():
            write_json(output / (da + ".json"), data)

    version = package(region, "school-escorts", write)
    pointer(region / "school-escorts" / (key + ".json"), {"version": version})
    print(version, outcomes, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--region", type=Path, default=Path("public/data/vancouver/region"))
    parser.add_argument("--workplace-run", default=WORKPLACE_RUN)
    parser.add_argument("--backend", default="jvm")
    args = parser.parse_args()
    publish(args.region, args.archive, args.workplace_run, args.backend)
